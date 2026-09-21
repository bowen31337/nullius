"""Feature 175: each loaded campaign array is pinned, held and measured.

app_spec.xml, "Tree & Artifact Persistence", feature 175: *"System pins
each loaded campaign array in memory, holding roughly 4 MB per campaign
of 500 nodes."*  docs/nullius-tech-architecture.md §9.3 states it as the
second half of the instruction feature 174 built the first half of —
*"Load each campaign's signal returns once as a single dense ``float32``
array of shape ``(nodes × T)`` and pin it in RAM"* — and sizes the hold
in the same breath: ``500 nodes × 2000 periods × 4 B = 4 MB per
campaign``, ``200 campaigns = 800 MB resident``.

These tests pin the feature as six facts, each one a way a careless
version of it would silently fail:

* **the first pin is the load, and every later pin is residence** — the
  first pin of an axis answers feature 174's own array (there is no
  second decoder), and every later pin of that axis answers the same
  resident object without re-reading the store: the array outlives the
  campaign's directory being deleted under it, because it is pinned.
* **the hold is counted, and it ends at the last release** — several
  holders share one buffer and let go in any order; the array stays
  resident while any holder holds it, and the last release drops the
  entry — the next pin re-loads through the store, which is the truth.
* **the handle is honest** — a released pin refuses to answer, a second
  release refuses to spend what the first already spent, and the
  ``with`` scope releases exactly what the block left held.
* **the hold is measured, not estimated** — §9.3's sizing is an
  observable: a campaign of 500 nodes and 2000 periods answers exactly
  4,000,000 bytes (roughly 4 MB), the arena sums its residence (200
  such campaigns would sum to §9.3's 800 MB), a refused load pins
  nothing and a released hold weighs nothing.
* **the residence is keyed by the ask** — ``(campaign, horizon)``, the
  same key spelling the resident cache uses: the policy axis and a
  pinned horizon are two holds on two buffers, released independently.
* **the arena is per-replay state over the store-as-truth** — no lock
  (§10.4 pins a replay to a single core), two arenas over one store are
  two residences, and a node published since a hold was taken is
  invisible to the resident array and visible to the next pin after
  the last release.
"""

from __future__ import annotations

import array as _array
import datetime as dt
import shutil

import pytest

pytest.importorskip("pyarrow", reason="the pins load through feature 174's Parquet read")
from artifacts import (
    CAMPAIGN_SIZING_FOOTPRINT_BYTES,
    CAMPAIGN_SIZING_NODES,
    CAMPAIGN_SIZING_PERIODS,
    FLOAT32_TYPECODE,
    RESIDENT_PIN_POLICY,
    ArtifactCacheError,
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactPinError,
    ArtifactsError,
    ArtifactStore,
    ArtifactStoreError,
    CampaignPin,
    CampaignPins,
    CampaignReturns,
    ReturnRow,
    SignalReturns,
    load_campaign_returns,
    persist_signal_returns,
)

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)

SNAPSHOT = "snap-2026-01"
VENUE = "binance"
VERSION = "v3"


# -- Small builders, the 174 suite's own shapes -------------------------------------


def _row(
    day: dt.date,
    symbol: str,
    net: float,
    *,
    horizon: int = 1,
    charge: float = 0.001,
) -> ReturnRow:
    """One priced row at a horizon — the helper shape of the 170 suite."""
    return ReturnRow(
        rebalance_date=day,
        horizon=horizon,
        symbol=symbol,
        charge=charge,
        post_cost_return=net,
    )


def _panel(
    node_id: str,
    rows: tuple[ReturnRow, ...],
    *,
    snapshot_name: str = SNAPSHOT,
    venue: str = VENUE,
    version: str = VERSION,
) -> SignalReturns:
    """A priced panel for one node, in the identity the caller spells."""
    return SignalReturns(
        node_id=node_id,
        snapshot_name=snapshot_name,
        venue=venue,
        version=version,
        rows=rows,
    )


def _published(
    store: ArtifactStore,
    campaign_id: str,
    *panels: SignalReturns,
) -> None:
    """Persist and commit each panel — the state §9.3's load sweeps."""
    for panel in panels:
        persist_signal_returns(store, campaign_id, panel.node_id, panel)
        store.commit(campaign_id, panel.node_id)


#: Node ``node-a``: two symbols on D1 and D2 at horizon 1.
A_ROWS = (
    _row(D1, "AAA", 0.010),
    _row(D1, "BBB", -0.004, charge=0.002),
    _row(D2, "AAA", -0.020),
    _row(D2, "BBB", 0.006, charge=0.002),
)

#: Node ``node-b``: horizon 1 on D2 and D3 only — ragged against
#: ``node-a``, so the union axis is three periods wide.
B_ROWS = (
    _row(D2, "AAA", -0.010),
    _row(D3, "BBB", 0.008, charge=0.002),
)


def _two_node_campaign(store: ArtifactStore, campaign_id: str) -> None:
    """Publish the working shape: ``node-a`` and ``node-b``, one world."""
    _published(
        store,
        campaign_id,
        _panel("node-a", A_ROWS),
        _panel("node-b", B_ROWS),
    )


def _refused(fn, *args, **kwargs) -> str:
    """Call ``fn``, require an :class:`ArtifactPinError`, return its message."""
    with pytest.raises(ArtifactPinError) as caught:
        fn(*args, **kwargs)
    return str(caught.value)


# -- The first pin is the load, and every later pin is residence ---------------------


def test_the_first_pin_answers_the_load(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The pin loads through feature 174's load and no second decoder:
    # the held array is the load's own — same axes, same horizon
    # policy, same bytes.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    pinned = arena.pin(campaign_id)
    direct = load_campaign_returns(store, campaign_id)
    assert isinstance(pinned, CampaignPin)
    assert pinned.returns.node_ids == direct.node_ids == ("node-a", "node-b")
    assert pinned.returns.periods == direct.periods == (D1, D2, D3)
    assert pinned.returns.horizon == direct.horizon == 1
    assert pinned.returns.values.tobytes() == direct.values.tobytes()


def test_the_second_holder_shares_the_resident_object(
    store: ArtifactStore, campaign_id: str
) -> None:
    # One load per axis per arena, one buffer per load: two holders,
    # one resident object — identity, not an equal copy, because the
    # point is the Parquet was read once for both of them.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    first = arena.pin(campaign_id)
    second = arena.pin(campaign_id)
    assert first.returns is second.returns
    assert arena.pin_count(campaign_id) == 2


def test_a_pinned_array_is_not_re_read(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The honest proof of the pin: with the campaign's directory
    # deleted under it, the next pin of the resident axis still answers
    # the array — a direct load would refuse (ArtifactNotFoundError),
    # so the answer can only have come from RAM.  §9.3's whole answer
    # to the replay bottleneck is this not being a second sweep.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    held = arena.pin(campaign_id)
    shutil.rmtree(store.root / campaign_id)
    again = arena.pin(campaign_id)
    assert again.returns is held.returns
    assert again.returns.values.tobytes() == held.returns.values.tobytes()
    with pytest.raises(ArtifactNotFoundError):
        load_campaign_returns(store, campaign_id)  # the store is empty now


def test_the_arena_is_empty_until_asked(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Nothing arrives unasked: a fresh arena holds nothing, counts
    # nothing and weighs nothing, because an entry appears exactly when
    # a caller pins its key.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    assert arena.resident_campaigns() == ()
    assert arena.footprint_bytes == 0
    assert not arena.holds(campaign_id)
    assert arena.pin_count(campaign_id) == 0


# -- The hold is counted, and it ends at the last release ----------------------------


def test_an_early_release_never_drops_a_buffer_another_holds(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The count is the design: several consumers within one replay
    # hold the same array, and each lets go in its own order — the
    # first release leaves the array resident for the holder that
    # remains, exactly as long as that holder holds it.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    first, second = arena.pin(campaign_id), arena.pin(campaign_id)
    resident = first.returns
    first.release()
    assert arena.holds(campaign_id)
    assert arena.pin_count(campaign_id) == 1
    assert second.returns is resident
    second.release()
    assert not arena.holds(campaign_id)
    assert arena.pin_count(campaign_id) == 0
    assert arena.resident_campaigns() == ()
    assert arena.footprint_bytes == 0


def test_the_last_release_drops_the_hold(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The hold ends as designed as it began: after the last release
    # the next pin re-loads through the store — proven by deleting the
    # campaign's directory first, so the re-pin refuses exactly where a
    # direct load refuses.  A pin that answered from a buffer the arena
    # still held would be a hold that never ended.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    arena.pin(campaign_id).release()
    assert not arena.holds(campaign_id)
    shutil.rmtree(store.root / campaign_id)
    with pytest.raises(ArtifactNotFoundError):
        arena.pin(campaign_id)
    assert arena.resident_campaigns() == ()


def test_a_refused_load_pins_nothing(store: ArtifactStore, campaign_id: str) -> None:
    # The arena holds measurements, not attempts: every refusal of the
    # load refuses the pin unchanged, in the load's own vocabulary (no
    # wrapper class, no second decoder), and leaves the residence
    # exactly what it was.
    arena = CampaignPins(store)
    with pytest.raises(ArtifactNotFoundError) as caught:
        arena.pin(campaign_id)
    assert campaign_id in str(caught.value)
    _two_node_campaign(store, campaign_id)
    with pytest.raises(ArtifactStoreError) as caught:
        arena.pin(campaign_id, horizon=5)
    assert "node-a" in str(caught.value)
    assert arena.resident_campaigns() == ()
    assert arena.footprint_bytes == 0
    assert arena.pin_count(campaign_id) == 0
    assert arena.pin_count(campaign_id, horizon=5) == 0


# -- The handle is honest --------------------------------------------------------------


def test_the_with_scope_pins_and_releases(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A hold is a scope: the block binds the resident array, the
    # block's exit lets go — the spelling a replay's sweep wants, and
    # the one that keeps the RAM tied to the code that asked for it.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    with arena.pin(campaign_id) as campaign:
        assert isinstance(campaign, CampaignReturns)
        assert campaign.shape == (2, 3)
        assert arena.holds(campaign_id)
        assert arena.pin_count(campaign_id) == 1
        assert arena.footprint_bytes == campaign.footprint_bytes
    assert not arena.holds(campaign_id)
    assert arena.footprint_bytes == 0


def test_the_scope_releases_what_the_block_left_held(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A caller that releases early inside the block leaves the scope
    # cleanly: the exit releases only what is still held, and never
    # speaks for a hold twice — the double-release refusal is for the
    # *second explicit release*, not for the scope closing behind one.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    pin = arena.pin(campaign_id)
    with pin:
        pin.release()
    assert pin.released
    assert not arena.holds(campaign_id)


def test_an_exception_inside_the_scope_still_releases(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A hold is a resource, not an error boundary: a replay whose sweep
    # raises mid-block must neither swallow the error nor leak the pin
    # — the exception propagates unchanged and the exit lets go, so a
    # failed run leaves no RAM held and no residence behind.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    with pytest.raises(RuntimeError), arena.pin(campaign_id):
        raise RuntimeError("the sweep failed")
    assert not arena.holds(campaign_id)
    assert arena.pin_count(campaign_id) == 0
    assert arena.resident_campaigns() == ()
    assert arena.footprint_bytes == 0


def test_a_double_release_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The first release spent this hold; a second would subtract one of
    # the holders that still hold the array — the count is only honest
    # if a handle can spend its share exactly once.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    pin = arena.pin(campaign_id)
    pin.release()
    message = _refused(pin.release)
    assert campaign_id in message
    assert "exactly once" in message


def test_a_released_pin_refuses_to_answer(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A released pin vouches for no hold: answering after release would
    # hold the buffer outside the accounting that releasing exists to
    # keep honest — through the accessor, the footprint, and a scope
    # re-entry alike.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    pin = arena.pin(campaign_id)
    resident = pin.returns  # the object, while the pin was live
    assert resident.node_ids == ("node-a", "node-b")
    pin.release()
    assert pin.released
    message = _refused(lambda: pin.returns)
    assert campaign_id in message
    assert "policy axis" in message
    with pytest.raises(ArtifactPinError):
        _ = pin.footprint_bytes
    with pytest.raises(ArtifactPinError), pin:
        pass  # a spent scope is not re-entered


def test_the_refusals_name_the_axis_they_are_about(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A holder juggling several pins must be able to tell which axis of
    # which campaign a refusal is about: the campaign and the horizon
    # axis (pinned or policy) ride every handle refusal.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    pin = arena.pin(campaign_id, horizon=1)
    pin.release()
    message = _refused(pin.release)
    assert campaign_id in message
    assert "horizon 1" in message


# -- The hold is measured, not estimated ----------------------------------------------


def test_a_campaign_of_the_sizing_holds_roughly_4_mb() -> None:
    # §9.3's own arithmetic as a fact of the record: the campaign the
    # sizing describes — 500 nodes, 2000 periods — weighs exactly
    # 4,000,000 bytes ("roughly 4 MB" because §9.3's MB is the decimal
    # megabyte its arithmetic writes), one cell per (node, period) at
    # the 4 bytes binary32 pins.
    sized = _sized_campaign()
    assert sized.shape == (CAMPAIGN_SIZING_NODES, CAMPAIGN_SIZING_PERIODS)
    assert sized.values.itemsize == 4
    assert len(sized.values) == CAMPAIGN_SIZING_NODES * CAMPAIGN_SIZING_PERIODS
    assert sized.footprint_bytes == CAMPAIGN_SIZING_FOOTPRINT_BYTES
    assert CAMPAIGN_SIZING_FOOTPRINT_BYTES == 4_000_000
    # The second line of §9.3's table, as arithmetic on the first: 200
    # campaigns of the sizing are 800 MB resident — the number the
    # arena's summed footprint would answer for 200 such holds.
    assert 200 * CAMPAIGN_SIZING_FOOTPRINT_BYTES == 800_000_000


def _sized_campaign() -> CampaignReturns:
    """The §9.3-sized record — 500 nodes × 2000 periods, one world.

    Built by hand rather than loaded, on purpose: the sizing is a fact
    of the *record* (cells × 4 B), the store would need 500 Parquet
    files to say the same thing, and :class:`CampaignReturns` is public
    and validates at construction — so this is the campaign §9.3
    describes, held, without a store in sight.
    """
    values = _array.array(
        FLOAT32_TYPECODE, bytes(CAMPAIGN_SIZING_FOOTPRINT_BYTES)
    )
    return CampaignReturns(
        campaign_id="camp",
        snapshot_name=SNAPSHOT,
        venue=VENUE,
        version=VERSION,
        horizon=1,
        node_ids=tuple(
            f"node-{position:04d}" for position in range(CAMPAIGN_SIZING_NODES)
        ),
        periods=tuple(
            dt.date(2018, 1, 1) + dt.timedelta(days=position)
            for position in range(CAMPAIGN_SIZING_PERIODS)
        ),
        values=values,
    )


def test_a_small_campaign_weighs_its_own_cells(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The same arithmetic at suite scale: two nodes × three periods ×
    # 4 B = 24 bytes — the footprint is measured from the buffer the
    # load answered, never estimated from a node count.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    with arena.pin(campaign_id) as campaign:
        assert campaign.footprint_bytes == 2 * 3 * 4
        assert arena.footprint_bytes == campaign.footprint_bytes


def test_the_arena_sums_its_residence(
    store: ArtifactStore, campaign_id: str, other_campaign_id: str
) -> None:
    # What the operator reads before sizing a box: the arena weighs its
    # whole residence — per campaign what that campaign's array weighs,
    # summed across the held campaigns, and dropping each hold's weight
    # the moment that hold ends.
    _two_node_campaign(store, campaign_id)  # 2 nodes × 3 periods
    _published(store, other_campaign_id, _panel("node-c", B_ROWS))  # 1 × 2
    arena = CampaignPins(store)
    assert arena.footprint_bytes == 0
    first = arena.pin(campaign_id)
    assert arena.footprint_bytes == first.footprint_bytes == 2 * 3 * 4
    second = arena.pin(other_campaign_id)
    assert arena.footprint_bytes == (
        first.footprint_bytes + second.footprint_bytes
    )
    second.release()
    assert arena.footprint_bytes == first.footprint_bytes
    first.release()
    assert arena.footprint_bytes == 0


# -- The residence is keyed by the ask -------------------------------------------------


def test_the_residence_is_keyed_by_the_ask(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The dense array is one horizon deep, so the key is the ask — the
    # same spelling the resident cache keys by.  ``node-b`` covers
    # horizon 2 only, so the policy axis resolves 2 while a pinned
    # horizon 2 is its own resident entry: two holds on two buffers,
    # identical bytes, released independently.
    _published(
        store,
        campaign_id,
        _panel("node-a", A_ROWS + (_row(D1, "AAA", 0.05, horizon=2),)),
        _panel("node-b", (_row(D2, "BBB", 0.03, horizon=2),)),
    )
    arena = CampaignPins(store)
    policy = arena.pin(campaign_id)
    pinned = arena.pin(campaign_id, horizon=2)
    assert policy.returns is not pinned.returns  # two asks, two holds
    assert policy.returns.horizon == 2  # the policy resolves 2 here
    assert pinned.horizon == 2
    assert policy.returns.values.tobytes() == pinned.returns.values.tobytes()
    assert arena.pin_count(campaign_id) == 1
    assert arena.pin_count(campaign_id, horizon=2) == 1
    assert arena.resident_campaigns() == (campaign_id,)  # once, both axes
    policy.release()
    assert not arena.holds(campaign_id)
    assert arena.holds(campaign_id, horizon=2)  # its own hold, still held
    pinned.release()
    assert arena.footprint_bytes == 0


def test_a_pinned_horizon_the_panels_do_not_cover_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The load's own refusal, passed through unchanged: a pinned
    # horizon some panel covers no date of is the load's to refuse, in
    # the load's own vocabulary — the arena adds no wrapper and no
    # second decoder, and pins nothing on the refusal.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    with pytest.raises(ArtifactStoreError) as caught:
        arena.pin(campaign_id, horizon=5)
    assert "node-a" in str(caught.value)
    assert not arena.holds(campaign_id, horizon=5)


# -- Per-replay state over the store-as-truth ------------------------------------------


def test_two_arenas_over_one_store_are_two_residences(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3 pins arrays per replay, so the arena is built by the replay
    # that holds it: one arena's hold is never another's, and one
    # arena's release never drops another's buffer.
    _two_node_campaign(store, campaign_id)
    mine, yours = CampaignPins(store), CampaignPins(store)
    held = mine.pin(campaign_id)
    shared = yours.pin(campaign_id)
    assert held.returns is not shared.returns
    assert held.returns.values.tobytes() == shared.returns.values.tobytes()
    held.release()
    assert yours.holds(campaign_id)
    assert mine.resident_campaigns() == ()
    shared.release()


def test_the_store_stays_the_truth_a_fresh_hold_answers_a_fresh_load(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A node published since a hold was taken is invisible to the
    # resident array (it answers the campaign that existed when it was
    # pinned, which existed) and visible to the next pin after the last
    # release — both are correct, because the store is the truth each
    # of them loaded.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    held = arena.pin(campaign_id)
    _published(store, campaign_id, _panel("node-c", B_ROWS))
    assert held.returns.node_ids == ("node-a", "node-b")
    witness = arena.pin(campaign_id)
    assert witness.returns is held.returns  # still resident, still 2 nodes
    witness.release()
    held.release()
    fresh = arena.pin(campaign_id)
    assert fresh.returns.node_ids == ("node-a", "node-b", "node-c")
    fresh.release()


# -- The arena's own contract, and the vocabularies around it --------------------------


def test_the_arena_is_bound_to_one_store_by_name(store: ArtifactStore) -> None:
    # The arena's own contract (not the load's, not the layout's): it
    # is bound to one ArtifactStore, because it loads through the read
    # side §1 grants and feature 174's load — an arena handed anything
    # else is an arena nothing can be pinned in.
    with pytest.raises(ArtifactPinError) as caught:
        CampaignPins({"root": store.root})  # type: ignore[arg-type]
    message = str(caught.value)
    assert "ArtifactStore" in message
    assert "dict" in message
    assert CampaignPins(store).store is store


def test_malformed_keys_refuse_as_key_errors(store: ArtifactStore) -> None:
    # The layout's contract, not the arena's: a campaign that cannot
    # serve as its one path segment is refused by the one spelling of
    # that rule every boundary in this member applies, and a horizon
    # that is not a positive period count by the load's own rule —
    # before any store is touched.
    arena = CampaignPins(store)
    for ask in (arena.pin, arena.holds, arena.pin_count):
        with pytest.raises(ArtifactKeyError):
            ask("cam/paign")
    with pytest.raises(ArtifactKeyError):
        arena.pin(".hidden")
    with pytest.raises(ArtifactStoreError):
        arena.pin("camp", horizon=0)


def test_pin_refusals_are_their_own_class_in_the_taxonomy(
    store: ArtifactStore,
) -> None:
    # Feature 175's contract is its own class — a *lifetime* policy, so
    # every refusal it speaks is a lie about a hold — split from the
    # cache's *content* policy the way the taxonomy splits every
    # feature's contract, and catchable by the member's base like all
    # of them.
    assert issubclass(ArtifactPinError, ArtifactsError)
    assert not issubclass(ArtifactPinError, ArtifactCacheError)
    with pytest.raises(ArtifactsError):
        CampaignPins(None)  # type: ignore[arg-type]


# -- The feature, as one behaviour ------------------------------------------------------


def test_the_feature_as_one_behaviour(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The feature's sentence as one behaviour over one published
    # campaign: the first pin loads and holds the resident array
    # (measured — its cells × 4 B), the second holder shares it without
    # a second read, and the last release lets go of exactly the RAM it
    # was holding.
    _two_node_campaign(store, campaign_id)
    arena = CampaignPins(store)
    with arena.pin(campaign_id) as campaign:
        assert campaign.shape == (2, 3)
        assert campaign.values.typecode == "f"
        second = arena.pin(campaign_id)
        assert second.returns is campaign
        expected = campaign.footprint_bytes
        second.release()
        assert arena.footprint_bytes == expected  # one hold still counts
    assert arena.footprint_bytes == 0
    assert arena.resident_campaigns() == ()


def test_the_policy_is_spelled_once() -> None:
    # The hold policy is a sentence, not a type, and it is quoted by
    # every seam that states it — pinned here so the arena's docstrings
    # and the feature's sentence cannot drift apart on what a pin does.
    assert RESIDENT_PIN_POLICY == (
        "pin each loaded campaign array in RAM while a holder holds it "
        "— roughly 4 MB per campaign of 500 nodes — and let go when "
        "the last holder does"
    )


def test_the_module_surface_is_the_arena_the_handle_and_the_sizing() -> None:
    # The structural half of the lifetime policy: the module's public
    # surface is exactly the arena, the handle and the policy/sizing
    # spellings — there is no entry-point for installing a value
    # nothing asked for, and no second spelling of release a later
    # feature could grow here by accident.
    from artifacts import _pins

    assert set(_pins.__all__) == {
        "CAMPAIGN_SIZING_FOOTPRINT_BYTES",
        "CAMPAIGN_SIZING_NODES",
        "CAMPAIGN_SIZING_PERIODS",
        "RESIDENT_PIN_POLICY",
        "CampaignPin",
        "CampaignPins",
    }
    arena = CampaignPins.__new__(CampaignPins)  # no I/O
    for second_spelling in (
        "unpin",
        "free",
        "evict",
        "unhold",
        "drop",
        "install",
        "put",
        "memoize",
    ):
        assert not hasattr(arena, second_spelling), second_spelling


def test_the_new_names_are_exported_from_the_member() -> None:
    # The public API the sibling features (177's factor, 178's updates)
    # and the tests reach.  A name that exists in ``_pins`` and not
    # here is a spelling callers would have to reach into a private
    # module for.
    import artifacts

    for name in (
        "CAMPAIGN_SIZING_FOOTPRINT_BYTES",
        "CAMPAIGN_SIZING_NODES",
        "CAMPAIGN_SIZING_PERIODS",
        "RESIDENT_PIN_POLICY",
        "CampaignPin",
        "CampaignPins",
        "ArtifactPinError",
    ):
        assert name in artifacts.__all__, name
        assert hasattr(artifacts, name), name
