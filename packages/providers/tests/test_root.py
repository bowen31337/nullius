"""Feature 196: the serving provider of every root call, recorded and read back.

*System persists the serving provider on every root-depth call routed to the
rotated frontier model tier* — so the suite below asks the sentence in three
pieces, in the order the store asks it:

* **the configuration** — a :class:`providers.FrontierTier` is the declared
  rotation, canonicalised, refusing an empty declaration and a member stated
  twice, and never carrying a model name of its own (§14.2's *"rates move
  monthly … the numbers are not"*);
* **the gate** — a call below the root tier, a provider the tier does not
  declare, a node the tree does not hold, a declaration the tree contradicts
  and a second record naming another family are each refused **by their own
  error**, naming the fact, and none of them writes a row;
* **the record** — what lands in the table, what ``get`` reads back, and the
  idempotence that makes a retry the same record rather than a second one.

The last section is this feature's distinctive one.  Where feature 199 had to
accept a *stated* measurement — *"no independent recomputation of a remote
deployment's window was available"* — the campaign and the depth of a root call
**are** rows of feature 97's tree, and this store checks them.  So the suite
tests the checking directly: a description the tree contradicts is refused
rather than written, which is the difference between provenance and a claim.

Every test here works on a database a migration built (0118, through its own
``apply``) and never hand-writes ``node``'s DDL — the discipline the conftest
states — and the store's own ``root_serving_provider`` table is created by the
store, which is the thing under test.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from conftest import sqlite_path_of
from providers import (
    ROOT_SERVING_PROVIDER_TABLE,
    ROOT_TIER_MAX_DEPTH,
    FrontierProvider,
    FrontierTier,
    RootCall,
    RootCallProvider,
    RootNotRecordedError,
    RootProviderConflictError,
    RootProviderError,
    RootProviderRotation,
    UnknownRootProviderError,
    UnrotatedCampaignError,
    record_root_provider,
)

#: One member of §14.1's roots row, for the tests that need a single family.
ANTHROPIC = FrontierProvider(provider="anthropic", model="claude-opus-5")

#: Another — a *different* family, which is the axis the record exists for.
OPENAI = FrontierProvider(provider="openai", model="gpt-5.6-sol")

#: A provider that is not frontier at all — the cheap depth tier's, per §14.1.
DEEPSEEK = FrontierProvider(provider="deepseek", model="deepseek-v4-flash")


# ── The configuration: the declared tier ──────────────────────────────────────


def test_a_tier_is_value_equal_whatever_order_it_is_stated_in():
    # Two tiers with the same members spelled in different orders are one
    # tier: the membership check is the whole use of this record, and an
    # order-sensitive ``__eq__`` would make two deployments configured
    # identically report different declarations.
    one = FrontierTier(
        providers=(
            ANTHROPIC,
            OPENAI,
            FrontierProvider(provider="google", model="gemini-3.1-pro"),
        )
    )
    other = FrontierTier(
        providers=(
            FrontierProvider(provider="google", model="gemini-3.1-pro"),
            OPENAI,
            ANTHROPIC,
        )
    )
    assert one == other
    assert one.text() == other.text()


def test_a_tier_canonicalises_into_sorted_order():
    # The canonical order is the record's, not the caller's: one tier has one
    # spelling, which is what lets a refusal quote it and a card render it.
    tier = FrontierTier(providers=(OPENAI, ANTHROPIC))
    assert [member.provider for member in tier.providers] == ["anthropic", "openai"]


def test_a_tier_of_one_is_admitted():
    # §14.1's target is two to three families and a deployment that has added
    # only its first one is a real state.  The tier *describes*; whether a
    # rotation is diverse enough is feature 215's metric, not a constructor's.
    tier = FrontierTier(providers=(ANTHROPIC,))
    assert ANTHROPIC in tier
    assert tier.text() == "anthropic:claude-opus-5"


def test_an_empty_tier_is_refused():
    # The one configuration this module will not hold: a tier with no members
    # declares that the campaign rotates across nobody, so every call's
    # membership check fails and the record can never be written for it.
    with pytest.raises(RootProviderError) as caught:
        FrontierTier(providers=())
    assert "at least one provider" in str(caught.value)


def test_a_member_stated_twice_is_refused():
    # One provider's one model is one family.  A tier holding it twice would
    # report a rotation across two members where there is one, which is the
    # contrast feature 197's sentence spends.
    with pytest.raises(RootProviderError) as caught:
        FrontierTier(providers=(ANTHROPIC, ANTHROPIC))
    assert "twice" in str(caught.value)


def test_a_member_is_recognised_by_its_parts_not_its_class():
    # The module loader imports this member twice, so two ``FrontierProvider``
    # classes exist over one source file.  A tier built from the *other* copy
    # must be admitted and re-made into this one — the discipline every seam
    # in this package keeps.
    class Foreign:
        def __init__(self, provider: str, model: str) -> None:
            self.provider = provider
            self.model = model

    tier = FrontierTier(providers=(Foreign("anthropic", "claude-opus-5"),))
    (member,) = tier.providers
    assert type(member) is FrontierProvider
    assert member == ANTHROPIC
    assert Foreign("anthropic", "claude-opus-5") in tier


def test_a_bare_string_is_not_a_tier():
    # A ``str`` is iterable, so reading one as a member collection would build
    # a tier with one member per character.  Refused before the iteration.
    with pytest.raises(RootProviderError) as caught:
        FrontierTier(providers="anthropic")  # type: ignore[arg-type]
    assert "must be a collection" in str(caught.value)


def test_a_mapping_is_not_a_tier():
    # The keys of a provider-to-something dict are a plausible mis-spelling of
    # a tier; reading them would be guessing which half of the caller's
    # structure was meant.
    with pytest.raises(RootProviderError):
        FrontierTier(providers={"anthropic": "claude-opus-5"})  # type: ignore[arg-type]


def test_a_blank_name_is_refused():
    with pytest.raises(RootProviderError) as caught:
        FrontierProvider(provider="   ", model="claude-opus-5")
    assert "non-empty name" in str(caught.value)


def test_a_name_is_stripped_because_it_is_a_lookup_key():
    # ``' anthropic '`` and ``'anthropic'`` must be one provider: the name is
    # matched against a tier's declarations, and a value that kept its padding
    # would be refused by a membership check it should have passed.
    padded = FrontierProvider(provider=" anthropic ", model=" claude-opus-5 ")
    assert padded == ANTHROPIC
    assert padded in FrontierTier(providers=(ANTHROPIC,))


def test_a_member_missing_its_parts_is_refused_naming_them():
    class Nothing:
        pass

    with pytest.raises(RootProviderError) as caught:
        FrontierTier(providers=(Nothing(),))  # type: ignore[arg-type]
    assert "provider, model" in str(caught.value)


def test_a_member_with_a_non_string_provider_is_told_so():
    # A stub carrying ``provider=7`` is told its provider is not a string, not
    # that it is "not a frontier member": recognition and validation are
    # separate steps.
    class Stub:
        provider = 7
        model = "claude-opus-5"

    with pytest.raises(RootProviderError) as caught:
        FrontierTier(providers=(Stub(),))  # type: ignore[arg-type]
    assert "must be a string" in str(caught.value)


# ── The call ──────────────────────────────────────────────────────────────────


def test_a_call_is_value_equal_and_canonicalizes_its_ids():
    node = uuid.uuid4()
    campaign = uuid.uuid4()
    one = RootCall(node_id=str(node), campaign_id=str(campaign), depth=0)
    other = RootCall(node_id=node, campaign_id=campaign, depth=0)
    assert one == other
    assert one.node_id == str(node)
    assert one.row()["node_id"] == str(node)


def test_a_call_below_the_root_tier_still_constructs():
    # Shape only.  Describing a depth call is not serving a root call with it,
    # and the refusal belongs to the gate — the split feature 198's ``262K``
    # candidate states for its own window.
    call = RootCall(node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=5)
    assert call.depth == 5


def test_a_boolean_is_not_a_depth():
    # ``bool`` is a subclass of ``int``, so ``True`` would otherwise be
    # admitted as depth 1 — a root depth — and a caller that passed a flag
    # where a depth belongs would have it recorded as a fact about the tree.
    with pytest.raises(RootProviderError) as caught:
        RootCall(node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=True)
    assert "must be an int" in str(caught.value)


def test_a_negative_depth_is_refused():
    with pytest.raises(RootProviderError) as caught:
        RootCall(node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=-1)
    assert "non-negative" in str(caught.value)


def test_a_node_id_that_is_not_a_uuid_is_refused():
    with pytest.raises(RootProviderError) as caught:
        RootCall(node_id="not-a-uuid", campaign_id=str(uuid.uuid4()), depth=0)
    assert "is not a UUID" in str(caught.value)


def test_a_call_is_recognised_by_its_parts(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # A caller holding the node row itself satisfies the seam without wrapping
    # anything — the duck-typed discipline feature 184's policy question draws
    # for its own cells.  The row that comes back is built from the tree's own
    # facts, so an unwrapped row records exactly as a :class:`RootCall` does.
    call, node = root_call(tree_database)

    class NodeRow:
        def __init__(self, row) -> None:
            self.node_id = row.node_id
            self.campaign_id = row.campaign_id
            self.depth = row.depth

    record = root_serving_providers.record(
        NodeRow(call), frontier_tier, ANTHROPIC
    )
    assert record.node_id == call.node_id
    assert root_serving_providers.get(node) == replace(record, recorded=False)


def test_a_value_without_the_parts_is_refused_naming_them(root_serving_providers, frontier_tier):
    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(object(), frontier_tier, ANTHROPIC)
    assert "node_id, campaign_id, depth" in str(caught.value)


# ── The gate: the refusals ────────────────────────────────────────────────────


def test_a_call_below_the_root_tier_is_refused(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # The sentence's conditional: *every **root-depth** call routed to the
    # rotated frontier model tier*.  §14.1 puts the frontier rotation at roots
    # (depth 0–1) and everything from depth 2 down on one cheap model, so a
    # depth call has one serving provider and no rotation to record.
    call, node = root_call(tree_database, depth=ROOT_TIER_MAX_DEPTH + 1)
    with pytest.raises(UnrotatedCampaignError) as caught:
        root_serving_providers.record(call, frontier_tier, ANTHROPIC)
    message = str(caught.value)
    assert str(ROOT_TIER_MAX_DEPTH) in message
    assert str(ROOT_TIER_MAX_DEPTH + 1) in message
    # And nothing was written for it — not even the table.
    assert root_serving_providers.get(node) is None


def test_the_boundary_itself_is_a_root_call(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # §14.1's roots are depth 0–1 inclusive, so the deepest root is recorded.
    call, _ = root_call(tree_database, depth=ROOT_TIER_MAX_DEPTH)
    record = root_serving_providers.record(call, frontier_tier, ANTHROPIC)
    assert record.depth == ROOT_TIER_MAX_DEPTH
    assert record.recorded is True


def test_the_boundary_is_the_depth_tiers_own_from_the_other_side():
    # ``ROOT_TIER_MAX_DEPTH`` and ``LARGE_HISTORY_FROM_DEPTH`` are one
    # boundary written from each side — §14.1's table writes both rows.  Pinned
    # here rather than by an import, because two features' constants must not
    # be one constant, and pinned at all because a drift between them would
    # leave a depth nothing classifies.
    from providers import LARGE_HISTORY_FROM_DEPTH

    assert ROOT_TIER_MAX_DEPTH + 1 == LARGE_HISTORY_FROM_DEPTH


def test_a_provider_the_tier_does_not_declare_is_refused(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # The §14.1 failure this whole guard exists for: a silent re-route
    # (deepseek-v4-flash, retired 2026-09-10 while continuing to accept the
    # ID) must not be able to write itself into the provenance as though a
    # human had chosen it.
    call, node = root_call(tree_database)
    with pytest.raises(UnknownRootProviderError) as caught:
        root_serving_providers.record(call, frontier_tier, DEEPSEEK)
    message = str(caught.value)
    assert "deepseek" in message
    assert "anthropic:claude-opus-5" in message  # the declared set, quoted
    # Raised before any database was opened: no table exists and no row does.
    assert not _table_exists(tree_database, ROOT_SERVING_PROVIDER_TABLE)
    assert root_serving_providers.get(node) is None


def test_a_blank_serving_provider_is_refused(root_serving_providers, frontier_tier):
    class Stub:
        provider = "  "
        model = "claude-opus-5"

    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(
            RootCall(
                node_id=str(uuid.uuid4()),
                campaign_id=str(uuid.uuid4()),
                depth=0,
            ),
            frontier_tier,
            Stub(),
        )
    assert "non-empty name" in str(caught.value)


def test_a_tier_that_is_not_a_tier_is_refused(root_serving_providers, root_call, tree_database):
    call, _ = root_call(tree_database)
    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(call, object(), ANTHROPIC)
    assert "providers" in str(caught.value)


def test_a_node_the_tree_does_not_hold_is_refused(
    root_serving_providers, frontier_tier
):
    # The record is written against the node the root call authored, so an id
    # the tree does not hold names a call whose mechanism nobody wrote.  The
    # repair is to expand the root first (feature 239), not to invent the row:
    # ``node`` is feature 97's table and this member does not own it.
    call = RootCall(
        node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=0
    )
    with pytest.raises(RootNotRecordedError) as caught:
        root_serving_providers.record(call, frontier_tier, ANTHROPIC)
    assert call.node_id in str(caught.value)


def test_a_database_with_no_node_table_names_the_migration(
    database_url, frontier_tier
):
    # A fresh database has never held a node, and the refusal says so by
    # naming the revision that builds the table rather than by complaining
    # that a SELECT failed.
    store = RootProviderRotation(database_url)
    call = RootCall(
        node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=0
    )
    with pytest.raises(RootNotRecordedError) as caught:
        store.record(call, frontier_tier, ANTHROPIC)
    assert "0118_node_table" in str(caught.value)


def test_a_campaign_the_tree_contradicts_is_refused(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # The campaign is a column of feature 97's node table, not a field a
    # caller supplies freely.  This is the checking that separates this
    # feature from feature 199's stated measurement.
    call, node = root_call(tree_database, campaign_id=str(uuid.uuid4()))
    lying = RootCall(
        node_id=node, campaign_id=str(uuid.uuid4()), depth=call.depth
    )
    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(lying, frontier_tier, ANTHROPIC)
    message = str(caught.value)
    assert call.campaign_id in message  # what the tree holds
    assert lying.campaign_id in message  # what the call claimed
    assert root_serving_providers.get(node) is None


def test_a_depth_the_tree_contradicts_is_refused(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # Both depths are root depths, so this is not the tiering refusal — it is
    # a description the tree does not support, and it is refused as a bad
    # description rather than as a call in the wrong tier.
    call, node = root_call(tree_database, depth=0)
    off_by_one = RootCall(
        node_id=node, campaign_id=call.campaign_id, depth=ROOT_TIER_MAX_DEPTH
    )
    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(off_by_one, frontier_tier, ANTHROPIC)
    message = str(caught.value)
    assert "declares depth" in message
    assert root_serving_providers.get(node) is None


def test_the_tree_refuses_a_depth_node_whatever_the_call_declared(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # The *fact* refuses the call: a caller that describes a depth-2 node as
    # depth 0 has not made it a root call, and the tree is what decides.
    # Refused as a depth call, because that is what the tree says it is.
    call, node = root_call(tree_database, depth=ROOT_TIER_MAX_DEPTH + 1)
    pretending = RootCall(node_id=node, campaign_id=call.campaign_id, depth=0)
    with pytest.raises(UnrotatedCampaignError) as caught:
        root_serving_providers.record(pretending, frontier_tier, ANTHROPIC)
    assert node in str(caught.value)
    assert root_serving_providers.get(node) is None


# ── The record ────────────────────────────────────────────────────────────────


def test_a_root_call_is_recorded_and_read_back(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    call, node = root_call(tree_database)
    record = root_serving_providers.record(call, frontier_tier, ANTHROPIC)
    assert record.recorded is True
    assert isinstance(record, RootCallProvider)
    assert record.node_id == call.node_id
    assert record.campaign_id == call.campaign_id
    assert record.depth == call.depth
    assert record.provider == "anthropic"
    assert record.model == "claude-opus-5"
    assert record.serving_provider == ANTHROPIC
    assert record.recorded_at.tzinfo is not None

    read = root_serving_providers.get(node)
    assert read is not None
    assert read.recorded is False  # a read wrote nothing
    # Every field is the stored row's; only the answer state differs, because
    # ``recorded`` says whether *this* call wrote the row and a read did not.
    assert read == replace(record, recorded=False)


def test_the_recorded_at_is_the_row_s_not_the_callers(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # The stamp is writer-stamped: a caller's ``now`` is honoured (so a
    # deterministic suite can pin it) but the value that comes back is the
    # row's, re-parsed from the stored text.
    call, node = root_call(tree_database)
    moment = datetime(2026, 9, 10, 4, 15, 0, 123000, tzinfo=UTC)
    first = root_serving_providers.record(call, frontier_tier, ANTHROPIC, now=moment)
    assert first.recorded_at == moment
    stored = _read_text(
        tree_database, ROOT_SERVING_PROVIDER_TABLE, "recorded_at", "node_id", node
    )
    assert stored == "2026-09-10T04:15:00.123Z"


def test_an_aware_instant_of_another_offset_is_the_same_instant(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    call, _ = root_call(tree_database)
    offset = timezone(timedelta(hours=-5))
    moment = datetime(2026, 9, 10, 4, 15, 0, tzinfo=offset)
    record = root_serving_providers.record(call, frontier_tier, ANTHROPIC, now=moment)
    assert record.recorded_at == datetime(2026, 9, 10, 9, 15, 0, tzinfo=UTC)


def test_a_naive_instant_is_refused(root_serving_providers, frontier_tier, root_call, tree_database):
    call, _ = root_call(tree_database)
    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(
            call,
            frontier_tier,
            ANTHROPIC,
            now=datetime(2026, 9, 10, 4, 15, 0),  # noqa: DTZ001 - the refusal's subject
        )
    assert "timezone-aware" in str(caught.value)


def test_a_re_issued_identical_record_answers_the_stored_row(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # A retry is the same record arriving twice.  The row *is* the record, so
    # the retry answers it — including its original instant, which a retry
    # does not move — and did not write a second row.
    call, _ = root_call(tree_database)
    first = root_serving_providers.record(call, frontier_tier, ANTHROPIC)
    later = first.recorded_at + timedelta(hours=1)
    again = root_serving_providers.record(
        call, frontier_tier, ANTHROPIC, now=later
    )
    assert again.recorded is False
    assert again.recorded_at == first.recorded_at
    assert _row_count(tree_database) == 1


def test_a_second_record_naming_another_family_is_a_conflict(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # One root call is one call, and §14.1's rotation assigns each root call
    # to one provider: the same root cannot have been proposed by two families.
    call, node = root_call(tree_database)
    root_serving_providers.record(call, frontier_tier, ANTHROPIC)
    with pytest.raises(RootProviderConflictError) as caught:
        root_serving_providers.record(call, frontier_tier, OPENAI)
    message = str(caught.value)
    assert "anthropic:claude-opus-5" in message  # what is stored
    assert "openai:gpt-5.6-sol" in message  # what the second record named
    assert node in message
    assert _row_count(tree_database) == 1


def test_a_record_missing_the_seam_is_refused(root_serving_providers, frontier_tier, root_call, tree_database):
    call, _ = root_call(tree_database)
    with pytest.raises(RootProviderError) as caught:
        root_serving_providers.record(call, frontier_tier, "anthropic")
    assert "serving provider" in str(caught.value)


def test_get_answers_none_for_a_node_never_recorded(
    root_serving_providers, root_call, tree_database
):
    _, node = root_call(tree_database)
    assert root_serving_providers.get(node) is None


def test_get_answers_none_when_the_table_was_never_created(database_url):
    # A store that has never recorded created nothing, and a read does not
    # create it: ``None`` means *this node's call was never recorded*, not
    # *the read failed*.  An unreachable database raises, so the two cannot
    # be confused.
    store = RootProviderRotation(database_url)
    assert store.get(str(uuid.uuid4())) is None
    assert not _table_exists(database_url, ROOT_SERVING_PROVIDER_TABLE)


def test_get_refuses_a_node_id_that_is_not_a_uuid(root_serving_providers):
    with pytest.raises(RootProviderError):
        root_serving_providers.get("not-a-uuid")


def test_two_root_calls_in_one_campaign_are_two_rows(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # Which is the point of the feature: §14.1 rotates providers across a
    # campaign's roots so the tree's roots can be stratified by family.  A
    # record keyed by campaign rather than by node could not express this.
    campaign = str(uuid.uuid4())
    first, first_node = root_call(tree_database, campaign_id=campaign)
    second, second_node = root_call(tree_database, campaign_id=campaign)
    root_serving_providers.record(first, frontier_tier, ANTHROPIC)
    root_serving_providers.record(second, frontier_tier, OPENAI)
    one = root_serving_providers.get(first_node)
    other = root_serving_providers.get(second_node)
    assert one is not None and other is not None
    assert one.provider == "anthropic"
    assert other.provider == "openai"
    assert _row_count(tree_database) == 2


def test_a_foreign_store_is_rebuilt_into_this_class(
    root_serving_providers, frontier_tier, root_call, tree_database
):
    # The double-import remedy at the record seam: a call and a member built
    # from the workspace's other copy are recognised by their parts and the
    # answer is re-made from this module's classes.
    class ForeignCall:
        def __init__(self, node_id: str, campaign_id: str, depth: int) -> None:
            self.node_id = node_id
            self.campaign_id = campaign_id
            self.depth = depth

    class ForeignMember:
        def __init__(self, provider: str, model: str) -> None:
            self.provider = provider
            self.model = model

    call, node = root_call(tree_database)
    record = root_serving_providers.record(
        ForeignCall(call.node_id, call.campaign_id, call.depth),
        frontier_tier,
        ForeignMember("anthropic", "claude-opus-5"),
    )
    assert type(record) is RootCallProvider
    assert record.provider == "anthropic"
    assert root_serving_providers.get(node) == replace(record, recorded=False)


def test_the_store_answers_its_own_repr(tree_database):
    store = RootProviderRotation(tree_database)
    shown = repr(store)
    assert "RootProviderRotation" in shown
    assert "database_url" in shown
    assert tree_database in shown


# ── The store's construction ──────────────────────────────────────────────────


def test_resolve_answers_none_when_nothing_names_a_store():
    assert RootProviderRotation.resolve({}) is None
    assert RootProviderRotation.resolve({"DATABASE_URL": "   "}) is None
    assert RootProviderRotation.resolve({"DATABASE_URL": "sqlite:///x.db"}) is not None


def test_construction_touches_no_file(database_url):
    # Composition-time work must not touch the disk: the path is resolved on
    # first use, so composing an application opens no database.
    store = RootProviderRotation(database_url)
    assert store._path is None


def test_a_non_sqlite_url_is_refused_by_name(database_url):
    store = RootProviderRotation("postgresql://localhost/tree")
    with pytest.raises(RootProviderError) as caught:
        store.record(
            RootCall(
                node_id=str(uuid.uuid4()),
                campaign_id=str(uuid.uuid4()),
                depth=0,
            ),
            FrontierTier(providers=(ANTHROPIC,)),
            ANTHROPIC,
        )
    assert "sqlite" in str(caught.value)


def test_an_in_memory_url_is_refused(database_url):
    store = RootProviderRotation("sqlite:///:memory:")
    with pytest.raises(RootProviderError) as caught:
        store.record(
            RootCall(
                node_id=str(uuid.uuid4()),
                campaign_id=str(uuid.uuid4()),
                depth=0,
            ),
            FrontierTier(providers=(ANTHROPIC,)),
            ANTHROPIC,
        )
    assert "no database path" in str(caught.value)


def test_a_blank_database_url_is_refused():
    with pytest.raises(RootProviderError):
        RootProviderRotation("   ")


# ── The free function ─────────────────────────────────────────────────────────


def test_record_root_provider_lands_the_row(tree_database, frontier_tier, root_call):
    call, node = root_call(tree_database)
    record = record_root_provider(
        call, frontier_tier, ANTHROPIC, database_url=tree_database
    )
    assert record.recorded is True
    stored = RootProviderRotation(tree_database).get(node)
    assert stored == replace(record, recorded=False)


def test_record_root_provider_reads_the_environment(
    tree_database, frontier_tier, root_call, monkeypatch
):
    call, _ = root_call(tree_database)
    monkeypatch.setenv("DATABASE_URL", tree_database)
    assert record_root_provider(call, frontier_tier, ANTHROPIC).recorded is True


def test_record_root_provider_refuses_by_name_when_nothing_names_a_store(
    frontier_tier,
):
    # A record that quietly skipped its write would leave the campaign's root
    # stratum unaudited — and §14.1's whole reason for the rotation is that
    # the stratification can be read afterwards.
    call = RootCall(
        node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=0
    )
    with pytest.raises(RootProviderError) as caught:
        record_root_provider(call, frontier_tier, ANTHROPIC, env={})
    assert "DATABASE_URL" in str(caught.value)


def test_the_free_function_lets_the_stores_refusal_through(
    tree_database, frontier_tier
):
    # Unwrapped: the refusal already names the call, the campaign and the
    # fact, and re-wrapping would put a second message in front of the one an
    # operator needs.
    call = RootCall(
        node_id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()), depth=0
    )
    with pytest.raises(RootNotRecordedError):
        record_root_provider(call, frontier_tier, ANTHROPIC, database_url=tree_database)


# ── Raw reads, so the assertions are about the table and not the store ────────


def _table_exists(database_url: str, table: str) -> bool:
    with closing(sqlite3.connect(sqlite_path_of(database_url))) as connection:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )


def _row_count(database_url: str) -> int:
    with closing(sqlite3.connect(sqlite_path_of(database_url))) as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {ROOT_SERVING_PROVIDER_TABLE}"
        ).fetchone()[0]


def _read_text(
    database_url: str, table: str, column: str, key: str, value: str
) -> str:
    with closing(sqlite3.connect(sqlite_path_of(database_url))) as connection:
        return connection.execute(
            f"SELECT {column} FROM {table} WHERE {key} = ?", (value,)
        ).fetchone()[0]
