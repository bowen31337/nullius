"""Feature 176: the series cached, the marginal information ratio declined.

app_spec.xml, "Tree & Artifact Persistence", feature 176: *"System declines
to cache marginal information ratio against canonical books, caching the
return series instead."*  docs/nullius-tech-architecture.md §9.3 states the
sentence as the instruction it is — *"So do not cache marginal IR against
canonical books. Cache the return series."* — and closes with the property
under test: *"``ir_marginal`` then becomes array indexing plus a rank-1
update, with no canonical-book cache anywhere."*

These tests pin the feature as its two halves, each half a way a careless
version of it would silently fail:

* **the decline is a named verdict, not a silent absence** — the ask to
  cache a marginal IR against a canonical book is refused with the
  ``declined_marginal_ir`` code from both seams that can receive it
  (the module function and the cache object), names the three terms of
  the ask, states the §9.2 reason the entry would be stale by
  construction, and points at the instead; and it fires without
  consulting the store, because a decline is a policy rather than a
  lookup.
* **the malformed ask is refused as malformed, not declined** — a book
  that cannot be named is the cache contract's refusal; a key that
  cannot address the layout is the layout's — so a caller can tell a
  typo from the policy.
* **the instead is load-once, answer-resident** — the first ask runs
  feature 174's load (and every refusal of the load refuses the ask
  unchanged: no second decoder, nothing cached on refusal), and every
  later ask answers the same resident object without re-reading the
  store — the array outlives the campaign's directory being deleted
  under it, because it is resident.
* **the key is the ask** — ``(campaign, horizon)``, the policy axis and
  each pinned horizon resident under their own keys, and two caches
  over one store are two residences, because §9.3 pins arrays per
  replay and the store stays the truth.
* **the cache cannot hold anything else** — structurally: the module's
  public surface is the decline and the series, and no spelling of a
  book reaches a residence key.
"""

from __future__ import annotations

import datetime as dt
import shutil

import pytest

pytest.importorskip("pyarrow", reason="the resident cache loads through feature 174's Parquet read")
from artifacts import (
    DECLINED_MARGINAL_IR,
    IR_MARGINAL,
    RESIDENT_CACHE_POLICY,
    ArtifactCacheError,
    ArtifactKeyError,
    ArtifactMarginalIRDeclinedError,
    ArtifactNotFoundError,
    ArtifactsError,
    ArtifactStore,
    ArtifactStoreError,
    ReturnRow,
    ReturnSeriesCache,
    SignalReturns,
    decline_marginal_ir,
    load_campaign_returns,
    persist_signal_returns,
)

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)

SNAPSHOT = "snap-2026-01"
VENUE = "binance"
VERSION = "v3"

BOOK = "canonical-book-1"


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


def _declined(fn, *args, **kwargs) -> str:
    """Call ``fn``, require the verdict, return its message."""
    with pytest.raises(ArtifactMarginalIRDeclinedError) as caught:
        fn(*args, **kwargs)
    return str(caught.value)


# -- The decline is a named verdict --------------------------------------------------


def test_the_ask_to_cache_a_marginal_ir_against_a_canonical_book_declines() -> None:
    # The feature's first half, spoken: the ask is refused, the refusal
    # is the named verdict (not the base class an accident would raise),
    # and the message names all three terms of the ask it declines.
    message = _declined(decline_marginal_ir, "camp", "node-a", BOOK)
    assert message.startswith(f"{DECLINED_MARGINAL_IR}:")
    assert "node-a" in message
    assert "camp" in message
    assert BOOK in message
    assert IR_MARGINAL in message


def test_the_verdict_is_catchable_by_every_wider_vocabulary() -> None:
    # The taxonomy's promise: a caller catching the cache's contract
    # catches the decline, and a caller catching the member's base
    # catches everything — the decline is a verdict, not a breakage,
    # but it travels the same channels one does.
    with pytest.raises(ArtifactCacheError):
        decline_marginal_ir("camp", "node-a", BOOK)
    with pytest.raises(ArtifactsError):
        decline_marginal_ir("camp", "node-a", BOOK)


def test_the_decline_names_the_instead(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A refusal that names only what it refuses strands the caller; this
    # one names the instead the feature's own sentence pins — the
    # resident return series of the very campaign the ask named, and
    # §9.3's recomputation over it.
    _two_node_campaign(store, campaign_id)
    message = _declined(
        decline_marginal_ir, campaign_id, "node-a", BOOK
    )
    assert "return series" in message
    assert "ReturnSeriesCache" in message
    assert campaign_id in message
    assert "rank-1 update" in message


def test_the_decline_states_the_reason_it_is_the_design() -> None:
    # §9.2's sentence is the whole reason: the same node scores
    # differently depending on the path a policy took to reach it, so
    # the book is an argument of the metric, not a dimension of the
    # data — the refusal quotes it rather than paraphrasing it away.
    message = _declined(decline_marginal_ir, "camp", "node-a", BOOK)
    assert "path a policy took" in message
    assert "canonical-book cache" in message


def test_the_decline_fires_without_consulting_the_store(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A decline is a policy, not a lookup: nothing is persisted, no
    # campaign exists, the ask is declined all the same — and the cache
    # object's spelling declines identically over the empty store,
    # which is what a replay holding it would hit first.
    cache = ReturnSeriesCache(store)
    _declined(cache.marginal_ir, campaign_id, "node-a", BOOK)
    assert cache.resident_campaigns() == ()  # nothing was loaded to decline


def test_the_cache_object_answers_the_same_verdict_the_module_does(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Two seams, one decline: the object-side spelling a replay holding
    # the cache reaches for, and the data-side spelling feature 179's
    # reject_duplicate set the pattern for.  Same class, same code, so
    # the two cannot drift apart on what is declined.
    cache = ReturnSeriesCache(store)
    from_object = _declined(cache.marginal_ir, campaign_id, "node-b", BOOK)
    from_module = _declined(decline_marginal_ir, campaign_id, "node-b", BOOK)
    assert from_object.startswith(f"{DECLINED_MARGINAL_IR}:")
    assert from_object == from_module


def test_the_decline_is_spelled_by_one_code() -> None:
    # The code is pinned as the spec-side vocabulary for the refusal
    # (the convention duplicate_code_hash set), and the refusal carries
    # it as a prefix rather than a substring, so a log line cannot
    # carry it by accident.
    assert DECLINED_MARGINAL_IR == "declined_marginal_ir"
    assert IR_MARGINAL == "ir_marginal"
    message = _declined(decline_marginal_ir, "camp", "node-a", BOOK)
    assert message.split(":", 1)[0] == DECLINED_MARGINAL_IR


def test_the_policy_is_spelled_once() -> None:
    # The cache's content policy is a sentence, not a type, and it is
    # quoted by every seam that states it — pinned here so the class
    # docstrings and the refusal cannot drift apart on what the cache
    # holds.
    assert RESIDENT_CACHE_POLICY == (
        "cache the return series, never a marginal information ratio "
        "keyed against a canonical book"
    )


# -- The malformed ask is refused as malformed ---------------------------------------


def test_a_book_that_cannot_be_named_refuses_as_malformed() -> None:
    # Not the verdict: an ask whose book term cannot be named is
    # malformed before it is declined, and is refused as the cache's
    # own contract so the caller fixes the ask rather than mistaking a
    # typo for the policy.
    for book in ("", "   ", None, 7, b"book"):
        with pytest.raises(ArtifactCacheError) as caught:
            decline_marginal_ir("camp", "node-a", book)
        message = str(caught.value)
        assert "canonical book" in message
        assert DECLINED_MARGINAL_IR not in message  # malformed, not declined
    with pytest.raises(ArtifactCacheError):
        ReturnSeriesCache("not-a-store").series("camp")  # type: ignore[arg-type]


def test_malformed_keys_refuse_as_key_errors() -> None:
    # The layout's contract, not the cache's: a campaign or node that
    # cannot serve as its one path segment is refused by the one
    # spelling of that rule every boundary in this member applies.
    with pytest.raises(ArtifactKeyError):
        decline_marginal_ir("cam/paign", "node-a", BOOK)
    with pytest.raises(ArtifactKeyError):
        decline_marginal_ir("camp", ".node", BOOK)


# -- The instead: load once, answer resident -----------------------------------------


def test_the_first_ask_answers_the_load(store: ArtifactStore, campaign_id: str) -> None:
    # The cache answers feature 174's own array — same axes, same
    # horizon policy, same bytes — because it loads through that load
    # and no second decoder exists to answer anything else.
    _two_node_campaign(store, campaign_id)
    cache = ReturnSeriesCache(store)
    answered = cache.series(campaign_id)
    direct = load_campaign_returns(store, campaign_id)
    assert answered.node_ids == direct.node_ids == ("node-a", "node-b")
    assert answered.periods == direct.periods == (D1, D2, D3)
    assert answered.horizon == direct.horizon == 1
    assert answered.values.tobytes() == direct.values.tobytes()


def test_the_second_ask_answers_the_same_resident_object(
    store: ArtifactStore, campaign_id: str
) -> None:
    # "Caching the return series": one load per key per cache, and the
    # resident object is *the* answer afterwards — identity, not an
    # equal copy, because the point is the Parquet was read once.
    _two_node_campaign(store, campaign_id)
    cache = ReturnSeriesCache(store)
    assert cache.series(campaign_id) is cache.series(campaign_id)


def test_the_resident_answer_does_not_re_read_the_store(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The honest proof of residency: with the campaign's directory
    # deleted under it, the second ask still answers the array — a
    # direct load would refuse (ArtifactNotFoundError), so the resident
    # answer can only have come from RAM.  §9.3's whole answer to the
    # replay bottleneck is this not being a second sweep.
    _two_node_campaign(store, campaign_id)
    cache = ReturnSeriesCache(store)
    resident = cache.series(campaign_id)
    shutil.rmtree(store.root / campaign_id)
    again = cache.series(campaign_id)
    assert again is resident
    assert again.values.tobytes() == resident.values.tobytes()
    with pytest.raises(ArtifactNotFoundError):
        load_campaign_returns(store, campaign_id)  # the store is empty now


def test_the_residence_is_keyed_by_the_ask(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The dense array is one horizon deep, so the key is the ask: the
    # policy axis and a pinned horizon are two resident axes of one
    # campaign, each answered resident under its own key.  ``node-b``
    # covers horizon 2 only, so the policy axis resolves 2 — the same
    # fixture the 174 suite pins its horizon policy with.
    _published(
        store,
        campaign_id,
        _panel("node-a", A_ROWS + (_row(D1, "AAA", 0.05, horizon=2),)),
        _panel("node-b", (_row(D2, "BBB", 0.03, horizon=2),)),
    )
    cache = ReturnSeriesCache(store)
    policy_axis = cache.series(campaign_id)
    pinned_axis = cache.series(campaign_id, horizon=2)
    assert policy_axis is not pinned_axis  # two asks, two residents
    assert policy_axis.horizon == 2  # the policy resolves 2 here
    assert pinned_axis.horizon == 2
    assert policy_axis.values.tobytes() == pinned_axis.values.tobytes()
    # Identical bytes, because feature 174's loads are deterministic —
    # the property that makes answering any spelling of the ask from
    # residence safe.
    assert cache.series(campaign_id) is policy_axis
    assert cache.series(campaign_id, horizon=2) is pinned_axis
    assert cache.holds(campaign_id)
    assert cache.holds(campaign_id, horizon=2)
    assert not cache.holds(campaign_id, horizon=1)  # an axis never asked


def test_a_pinned_horizon_the_panels_do_not_cover_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The load's own refusal, passed through unchanged: a pinned
    # horizon some panel covers no date of is the load's to refuse, in
    # the load's own vocabulary — the cache adds no wrapper and no
    # second decoder, and caches nothing on the refusal.
    _two_node_campaign(store, campaign_id)
    cache = ReturnSeriesCache(store)
    with pytest.raises(ArtifactStoreError) as caught:
        cache.series(campaign_id, horizon=5)
    assert "node-a" in str(caught.value)
    assert not cache.holds(campaign_id, horizon=5)
    assert cache.resident_campaigns() == ()


def test_a_campaign_the_store_does_not_hold_refuses_unchanged(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A fact about the store's contents, answered as the load answers
    # it — ArtifactNotFoundError, the same class a direct load raises —
    # and nothing is resident afterwards: the cache holds measurements,
    # not attempts.
    cache = ReturnSeriesCache(store)
    with pytest.raises(ArtifactNotFoundError) as caught:
        cache.series(campaign_id)
    assert campaign_id in str(caught.value)
    assert cache.resident_campaigns() == ()
    assert not cache.holds(campaign_id)


def test_the_residence_lists_its_campaigns_sorted_once(
    store: ArtifactStore, campaign_id: str, other_campaign_id: str
) -> None:
    # The operator's listing: every campaign the cache holds, sorted,
    # each once however many horizon axes were pinned — and empty
    # before any ask, because nothing arrives unasked.
    _two_node_campaign(store, campaign_id)
    _published(store, other_campaign_id, _panel("node-c", B_ROWS))
    cache = ReturnSeriesCache(store)
    assert cache.resident_campaigns() == ()
    cache.series(campaign_id)
    cache.series(other_campaign_id)
    expected = tuple(sorted((campaign_id, other_campaign_id)))
    assert cache.resident_campaigns() == expected
    assert list(cache.resident_campaigns()) == sorted(
        cache.resident_campaigns()
    )


def test_two_campaigns_reside_apart(
    store: ArtifactStore, campaign_id: str, other_campaign_id: str
) -> None:
    # The first key does the separating, as everywhere in this store:
    # each campaign's ask answers its own array, never the other's.
    _two_node_campaign(store, campaign_id)
    _published(store, other_campaign_id, _panel("node-c", B_ROWS))
    cache = ReturnSeriesCache(store)
    assert cache.series(campaign_id).node_ids == ("node-a", "node-b")
    assert cache.series(other_campaign_id).node_ids == ("node-c",)


def test_the_store_stays_the_truth_a_fresh_cache_answers_a_fresh_load(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3 pins arrays per replay; the cache is per-process state, not
    # a correction of the store.  A node published after the first
    # cache loaded is invisible to that cache (it answers the campaign
    # it loaded, which existed) and visible to a fresh one — both are
    # correct, because the store is the truth each of them loaded.
    _two_node_campaign(store, campaign_id)
    first = ReturnSeriesCache(store)
    resident = first.series(campaign_id)
    _published(store, campaign_id, _panel("node-c", B_ROWS))
    assert first.series(campaign_id) is resident  # still 2 nodes
    assert resident.node_ids == ("node-a", "node-b")
    second = ReturnSeriesCache(store)
    assert second.series(campaign_id).node_ids == (
        "node-a",
        "node-b",
        "node-c",
    )


def test_two_caches_over_one_store_are_two_residences(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The bounded key is what makes "no eviction" safe: each cache
    # holds exactly what its own asks loaded, and one cache's residence
    # is never another's — a replay builds its own, per §9.3.
    _two_node_campaign(store, campaign_id)
    first = ReturnSeriesCache(store)
    second = ReturnSeriesCache(store)
    assert first.series(campaign_id) is not second.series(campaign_id)
    assert (
        first.series(campaign_id).values.tobytes()
        == second.series(campaign_id).values.tobytes()
    )


# -- The feature, as one behaviour ---------------------------------------------------


def test_the_one_ask_is_declined_and_the_other_is_cached(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The feature's sentence as one behaviour over one published
    # campaign: the marginal-IR ask against a canonical book is
    # declined with the named verdict, the return-series ask answers
    # the resident (nodes × periods) float32 array — and the declined
    # number is a recomputation over the cached one, never a recall,
    # which is why §9.3 closes with "no canonical-book cache anywhere".
    _two_node_campaign(store, campaign_id)
    cache = ReturnSeriesCache(store)
    with pytest.raises(ArtifactMarginalIRDeclinedError):
        cache.marginal_ir(campaign_id, "node-a", BOOK)
    series = cache.series(campaign_id)
    assert series.shape == (2, 3)
    assert series.values.typecode == "f"
    assert cache.holds(campaign_id)
    assert cache.resident_campaigns() == (campaign_id,)


def test_the_module_surface_is_the_decline_and_the_cache() -> None:
    # The structural half of "no canonical-book cache anywhere": the
    # module's public surface is exactly the decline, the cache and the
    # two spellings of the policy — there is no entry-point for any
    # other kind of resident value, and a later feature cannot grow one
    # here by accident.
    from artifacts import _cache

    assert set(_cache.__all__) == {
        "DECLINED_MARGINAL_IR",
        "IR_MARGINAL",
        "RESIDENT_CACHE_POLICY",
        "ReturnSeriesCache",
        "decline_marginal_ir",
    }
    cache = ReturnSeriesCache.__new__(ReturnSeriesCache)  # no I/O
    for second_spelling in ("put", "store", "install", "memoize", "remember"):
        assert not hasattr(cache, second_spelling), second_spelling


def test_the_cache_is_bound_to_one_store_by_name(store: ArtifactStore) -> None:
    # The cache's own contract (not the load's, not the layout's): it
    # is bound to one ArtifactStore, because it loads through the read
    # side §1 grants and feature 174's load — a cache handed anything
    # else is a cache nothing can be asked of.
    with pytest.raises(ArtifactCacheError) as caught:
        ReturnSeriesCache({"root": store.root})  # type: ignore[arg-type]
    message = str(caught.value)
    assert "ArtifactStore" in message
    assert "dict" in message
    assert ReturnSeriesCache(store).store is store
