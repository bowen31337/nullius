"""Feature 49's laziness: materialise on first request, then reuse.

app_spec.xml feature 49: *System materializes a feature to Parquet lazily on
first request, persisting the result for later reuse.*  Four words in that
sentence are four separable claims, and these tests take them one at a time:

* **materializes to Parquet** — a request writes a real Parquet file, at the
  path the key itself spells (``test_parquet.py`` covers the format);
* **lazily** — nothing is computed until a request arrives, so construction
  touches no disk and a feature nobody asks for costs nothing;
* **on first request** — the first request computes, and the second does not;
* **persisting the result for later reuse** — the second request returns the
  stored feature, read back from the lake, without calling the definition.

The last two are the ones worth the most care, because a cache that recomputes
and returns the same answer is indistinguishable from one that works unless the
*computation itself* is observed.  So the tests below count calls rather than
compare values: ``compute`` is a spy, and the assertion is on whether it ran.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip(
    "pyarrow",
    reason="the Parquet materialisation suite requires pyarrow (a declared dependency)",
)

from feature_store import (  # noqa: E402
    FEATURES_DIRECTORY,
    LAKE_ROOT_ENV,
    MATERIALISED_SUFFIX,
    FeatureKey,
    FeatureMaterialiser,
    MaterialisationError,
    MaterialisedFeature,
    stamp_rows,
)


def make_key(**overrides: object) -> FeatureKey:
    components: dict[str, object] = {
        "feature_name": "realized_vol_30",
        "feature_version": "1",
        "snapshot_hash": "f" * 64,
        "symbol": "BTCUSDT",
        "frequency": "1d",
    }
    components.update(overrides)
    return FeatureKey(**components)  # type: ignore[arg-type]


class Compute:
    """A stand-in feature definition that records how often it was called.

    Returns the rows it was given, so a test can assert on both the number of
    calls and the content that came back — the two facts a cache assertion
    needs, and the second is worthless without the first.
    """

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.calls = 0
        self._rows = rows if rows is not None else [{"ret": 0.5, "n": 3}]

    def __call__(self):
        self.calls += 1
        return list(self._rows)


@pytest.fixture
def materialiser(lake_root: Path) -> FeatureMaterialiser:
    # The shared fixture has already pointed LAKE_ROOT at a fresh temporary
    # lake, so from_env() resolves it — the same path production takes.
    return FeatureMaterialiser.from_env()


# ---------------------------------------------------------------------------
# Materializes to Parquet, at the key's own path
# ---------------------------------------------------------------------------


def test_a_request_writes_a_parquet_file_under_the_lake(
    materialiser: FeatureMaterialiser, lake_root: Path
) -> None:
    key = make_key()
    result = materialiser.materialise(key, Compute())
    assert result.path.is_file()
    assert result.path.read_bytes()[:4] == b"PAR1"
    assert result.path.is_relative_to(lake_root)


def test_the_path_is_the_keys_own_five_segments_plus_the_suffix(
    materialiser: FeatureMaterialiser,
) -> None:
    # §4.4's "keeping it on the key means what is stored and where it is stored
    # can never disagree": the file's path IS the key's path. The suffix goes on
    # the last segment rather than becoming a sixth, so to_path stays a
    # five-segment path from_path can parse.
    key = make_key()
    path = materialiser.path_for(key)
    expected = (
        materialiser.features_root.joinpath(*key.to_path().parts[:-1])
        / (key.to_path().parts[-1] + MATERIALISED_SUFFIX)
    )
    assert path == expected
    assert path.name == "1d.parquet"
    assert FEATURES_DIRECTORY in path.parts


@pytest.mark.parametrize(
    "component,other",
    [
        ("feature_name", "other_feature"),
        ("feature_version", "2"),  # feature 53: a bump is a new file, not an overwrite
        ("snapshot_hash", "0" * 64),
        ("symbol", "ETHUSDT"),
        ("frequency", "1m"),
    ],
)
def test_changing_any_key_component_changes_the_file(
    materialiser: FeatureMaterialiser, component: str, other: str
) -> None:
    # The on-disk layout inherits feature 48's identity: two features differing
    # in any single component are two files, so one can never shadow the other.
    assert materialiser.path_for(make_key()) != materialiser.path_for(
        make_key(**{component: other})
    )


# ---------------------------------------------------------------------------
# Lazily: nothing happens until something asks
# ---------------------------------------------------------------------------


def test_construction_performs_no_io(lake_root: Path) -> None:
    # The lake is untouched by building a materialiser — no directory made, no
    # file read — so composing an application costs nothing.
    before = sorted(lake_root.rglob("*"))
    fresh = FeatureMaterialiser(lake_root)
    assert not fresh.features_root.exists()
    assert sorted(lake_root.rglob("*")) == before


def test_from_env_construction_performs_no_io(lake_root: Path) -> None:
    # The composed path: resolving the lake root through the environment must
    # still write nothing, or composing an application would materialise a
    # directory tree before any request arrived.
    before = sorted(lake_root.rglob("*"))
    FeatureMaterialiser.from_env()
    assert sorted(lake_root.rglob("*")) == before


def test_from_env_resolves_the_lake_root(lake_root: Path) -> None:
    assert FeatureMaterialiser.from_env().lake_root == lake_root


def test_from_env_prefers_an_explicit_lake_root_over_the_environment() -> None:
    resolved = FeatureMaterialiser.from_env({LAKE_ROOT_ENV: "/tmp/some-lake"})
    assert resolved.lake_root == Path("/tmp/some-lake")


def test_from_env_treats_a_blank_lake_root_as_unset() -> None:
    # Whitespace-only counts as unset, the same treatment the shared fixtures
    # give TEST_DATABASE_URL and SnapshotService.from_env gives LAKE_ROOT.
    resolved = FeatureMaterialiser.from_env({LAKE_ROOT_ENV: "   "})
    assert resolved.lake_root.name == "lake"


def test_nothing_is_computed_until_a_request_arrives(
    materialiser: FeatureMaterialiser, lake_root: Path
) -> None:
    definition = Compute()
    assert definition.calls == 0
    assert materialiser.is_materialised(make_key()) is False
    assert materialiser.load(make_key()) is None
    assert definition.calls == 0  # still nothing computed
    assert not materialiser.features_root.exists()


def test_a_lake_root_that_cannot_be_resolved_refuses_rather_than_guesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Materialising into "/" is never what a caller meant.
    monkeypatch.delenv(LAKE_ROOT_ENV, raising=False)
    monkeypatch.setattr(
        "feature_store.materialise.find_workspace_root", lambda: None
    )
    with pytest.raises(MaterialisationError, match=LAKE_ROOT_ENV):
        FeatureMaterialiser.from_env()


def test_a_blank_lake_root_is_refused_at_construction() -> None:
    with pytest.raises(MaterialisationError, match="non-empty"):
        FeatureMaterialiser("   ")


# ---------------------------------------------------------------------------
# On first request: compute once, then reuse
# ---------------------------------------------------------------------------


def test_the_first_request_computes_and_reports_that_it_did(
    materialiser: FeatureMaterialiser,
) -> None:
    definition = Compute()
    result = materialiser.materialise(make_key(), definition)
    assert definition.calls == 1
    assert result.materialised is True


def test_the_second_request_reuses_without_computing(
    materialiser: FeatureMaterialiser,
) -> None:
    # The whole of feature 49's "persisting the result for later reuse": the
    # definition is NOT called the second time, so the stored file is the only
    # source of the answer.  Asserted on the call count, because a cache that
    # recomputes and returns the same value would pass a value-only check.
    key = make_key()
    definition = Compute()
    first = materialiser.materialise(key, definition)
    second = materialiser.materialise(key, definition)
    assert definition.calls == 1  # computed once, not twice
    assert second.materialised is False
    assert second.rows == first.rows


def test_a_reused_materialisation_is_the_same_feature(
    materialiser: FeatureMaterialiser,
) -> None:
    # The reuse is safe to do silently precisely because the rows are identical
    # — same content, same stamps, same order.
    key = make_key()
    first = materialiser.materialise(key, Compute([{"ret": 0.5}, {"ret": 0.25}]))
    second = materialiser.materialise(key, Compute([{"totally": "different"}]))
    assert second.rows == first.rows
    assert [row.values for row in second.rows] == [{"ret": 0.5}, {"ret": 0.25}]


def test_the_stamp_is_not_restamped_by_a_later_read(
    materialiser: FeatureMaterialiser,
) -> None:
    # A stamp records when a row was computed — a fact about the past — so
    # reading a materialisation back must return the instant that was written,
    # never the instant of the read (feature 51's discipline, across the lake).
    written = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    key = make_key()
    materialiser.materialise(key, lambda: stamp_rows([{"a": 1}], computed_as_of=written))
    (later,) = materialiser.materialise(key, Compute()).rows
    assert later.computed_as_of == written


def test_reuse_survives_a_new_materialiser(
    materialiser: FeatureMaterialiser, lake_root: Path
) -> None:
    # The persistence is on disk, not in memory: a second process — or the same
    # one after a restart — finds the file and reuses it.
    key = make_key()
    materialiser.materialise(key, Compute())
    other = FeatureMaterialiser(lake_root)
    definition = Compute()
    result = other.materialise(key, definition)
    assert definition.calls == 0
    assert result.materialised is False


def test_replace_true_recomputes_deliberately(
    materialiser: FeatureMaterialiser,
) -> None:
    # Replacing a stored feature is a decision, never a default — the same
    # discipline FeatureStore.put applies to a duplicate key.
    key = make_key()
    definition = Compute([{"v": 1}])
    materialiser.materialise(key, definition)
    replaced = materialiser.materialise(key, Compute([{"v": 2}]), replace=True)
    assert replaced.materialised is True
    assert [row.values for row in replaced.rows] == [{"v": 2}]
    # And the new content is what a later read sees.
    assert [row.values for row in materialiser.load(key)] == [{"v": 2}]


def test_a_version_bump_lands_beside_rather_than_over(
    materialiser: FeatureMaterialiser,
) -> None:
    # Feature 53: a changed definition gets a new feature_version, so the new
    # rows get a new file and the prior-version file is left untouched.
    v1, v2 = make_key(feature_version="1"), make_key(feature_version="2")
    first = materialiser.materialise(v1, Compute([{"v": 1}]))
    second = materialiser.materialise(v2, Compute([{"v": 2}]))
    assert first.path != second.path
    assert first.path.is_file() and second.path.is_file()
    assert [row.values for row in materialiser.load(v1)] == [{"v": 1}]
    assert [row.values for row in materialiser.load(v2)] == [{"v": 2}]


# ---------------------------------------------------------------------------
# The definition is the caller's; the clock is the materialiser's
# ---------------------------------------------------------------------------


def test_rows_already_stamped_by_the_definition_are_used_as_they_are(
    materialiser: FeatureMaterialiser,
) -> None:
    # A definition that stamps as it computes (the normal case for feature 51's
    # row layer) hands FeatureRows back, and re-stamping them would restate a
    # write-time fact — the one thing a stamp must never do.
    written = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    stamped = stamp_rows([{"a": 1}], computed_as_of=written)
    result = materialiser.materialise(make_key(), lambda: stamped)
    assert result.rows[0].computed_as_of == written


def test_plain_mappings_are_stamped_once_per_write(
    materialiser: FeatureMaterialiser,
) -> None:
    # An unstamped definition is stamped through feature 51's seam, so the
    # whole batch still carries one instant: a batch straddling a clock tick
    # would let a `<= t` query return part of one write.
    result = materialiser.materialise(make_key(), Compute([{"a": 1}, {"a": 2}]))
    stamps = {row.computed_as_of for row in result.rows}
    assert len(stamps) == 1


def test_the_injected_clock_decides_the_stamp(lake_root: Path) -> None:
    pinned = dt.datetime(2021, 6, 1, tzinfo=dt.timezone.utc)
    materialiser = FeatureMaterialiser(lake_root, clock=lambda: pinned)
    result = materialiser.materialise(make_key(), Compute())
    assert result.rows[0].computed_as_of == pinned


def test_a_mix_of_rows_and_mappings_is_refused(materialiser: FeatureMaterialiser) -> None:
    stamped = stamp_rows([{"a": 1}])
    with pytest.raises(MaterialisationError, match="mix"):
        materialiser.materialise(make_key(), lambda: [stamped[0], {"a": 2}])


def test_a_non_callable_definition_is_refused(materialiser: FeatureMaterialiser) -> None:
    with pytest.raises(MaterialisationError, match="zero-argument callable"):
        materialiser.materialise(make_key(), "not callable")  # type: ignore[arg-type]


def test_a_definition_returning_something_unusable_is_refused(
    materialiser: FeatureMaterialiser,
) -> None:
    with pytest.raises(MaterialisationError, match="rows"):
        materialiser.materialise(make_key(), lambda: None)
    with pytest.raises(MaterialisationError, match="rows"):
        materialiser.materialise(make_key(), lambda: b"bytes")


def test_a_definition_returning_a_mapping_is_refused_not_silently_empty(
    materialiser: FeatureMaterialiser,
) -> None:
    # "one row with no columns" and "a batch of column names" are both wrong,
    # and the row layer names the likely intent; it must not be silently
    # accepted as an empty feature.
    with pytest.raises(MaterialisationError):
        materialiser.materialise(make_key(), lambda: {"a": 1})


# ---------------------------------------------------------------------------
# A corrupt lake is not an unmaterialised feature
# ---------------------------------------------------------------------------


def test_a_corrupt_materialisation_is_refused_rather_than_recomputed(
    materialiser: FeatureMaterialiser,
) -> None:
    # Silently recomputing would destroy the evidence and hand back a different
    # answer than a replay may have already read from this path.
    key = make_key()
    path = materialiser.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a parquet file")
    with pytest.raises(MaterialisationError, match="damaged"):
        materialiser.load(key)
    definition = Compute()
    with pytest.raises(MaterialisationError, match="damaged"):
        materialiser.materialise(key, definition)
    assert definition.calls == 0  # refused, not silently recomputed


def test_a_corrupt_materialisation_can_be_replaced_deliberately(
    materialiser: FeatureMaterialiser,
) -> None:
    key = make_key()
    path = materialiser.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"junk")
    result = materialiser.materialise(key, Compute([{"v": 9}]), replace=True)
    assert result.materialised is True
    assert [row.values for row in result.rows] == [{"v": 9}]


def test_the_temporary_file_does_not_survive_a_write(
    materialiser: FeatureMaterialiser,
) -> None:
    # The atomic write stages a uniquely-named file beside the destination;
    # leaving it behind would litter the features area with debris that a
    # later `*.parquet` scan could pick up.
    materialiser.materialise(make_key(), Compute())
    leftovers = [
        p
        for p in materialiser.features_root.rglob("*")
        if p.is_file() and p.name.startswith(".")
    ]
    assert leftovers == []


# ---------------------------------------------------------------------------
# The store's key discipline still applies
# ---------------------------------------------------------------------------


def test_a_feature_with_no_rows_is_materialised_like_any_other(
    materialiser: FeatureMaterialiser,
) -> None:
    # A feature computed over an empty window is a stored feature, not a
    # missing one (feature 48's own words) — and it must be materialisable.
    key = make_key()
    result = materialiser.materialise(key, lambda: [])
    assert result.materialised is True
    assert len(result) == 0
    assert result.path.is_file()
    reused = materialiser.materialise(key, Compute())
    assert reused.materialised is False
    assert reused.rows == ()


def test_is_materialised_answers_without_reading_the_file(
    materialiser: FeatureMaterialiser,
) -> None:
    key = make_key()
    assert materialiser.is_materialised(key) is False
    materialiser.materialise(key, Compute())
    assert materialiser.is_materialised(key) is True


def test_the_result_reports_its_own_row_count(
    materialiser: FeatureMaterialiser,
) -> None:
    result = materialiser.materialise(make_key(), Compute([{"a": 1}, {"a": 2}]))
    assert len(result) == 2
    assert isinstance(result, MaterialisedFeature)
    assert result.key == make_key()


# ---------------------------------------------------------------------------
# Feature 50 — the reuse is measured, not merely performed
# ---------------------------------------------------------------------------


def test_a_miss_does_not_move_the_cache_hit_counter(
    materialiser: FeatureMaterialiser,
) -> None:
    # Feature 50 counts reuse, and a first request is not a reuse: it computes
    # and writes.  The counter stays at zero, and the miss is counted instead,
    # so the hit rate has both its terms from the very first request.
    result = materialiser.materialise(make_key(), Compute())
    assert result.materialised is True
    assert materialiser.cache_hit == 0
    assert materialiser.cache_miss == 1


def test_a_reuse_increments_the_cache_hit_counter(
    materialiser: FeatureMaterialiser,
) -> None:
    # The whole of feature 50 in one assertion: the second request finds the
    # stored file and returns it without calling compute, and the counter that
    # was zero is now one.  Asserted on the counter AND on the call count,
    # because a cache that recomputed and merely reported a hit would move the
    # call count but a counter incremented in the wrong place would not.
    key = make_key()
    definition = Compute()
    materialiser.materialise(key, definition)
    result = materialiser.materialise(key, definition)
    assert definition.calls == 1  # reused, not recomputed
    assert result.materialised is False
    assert materialiser.cache_hit == 1
    assert materialiser.cache_miss == 1


def test_the_counter_counts_reuse_across_many_requests(
    materialiser: FeatureMaterialiser,
) -> None:
    # A counter that saturates at one would pass a single-reuse test; counting
    # every reuse is the point of a counter.  Five further requests over the
    # same key, none of them calling compute, move it to five.
    key = make_key()
    definition = Compute()
    materialiser.materialise(key, definition)
    for _ in range(5):
        materialiser.materialise(key, definition)
    assert definition.calls == 1
    assert materialiser.cache_hit == 5
    assert materialiser.cache_miss == 1


def test_each_distinct_key_is_its_own_cache(
    materialiser: FeatureMaterialiser,
) -> None:
    # The counter is per-materialiser, not per-key, but the reuse it measures
    # is per-key: a hit on one key does not credit a miss on another.  Two keys
    # each computed once, then one reused once — the counter is one, not two.
    a, b = make_key(), make_key(symbol="ETHUSDT")
    definition = Compute()
    materialiser.materialise(a, definition)
    materialiser.materialise(b, definition)
    assert materialiser.cache_hit == 0
    materialiser.materialise(a, definition)
    assert materialiser.cache_hit == 1
    assert definition.calls == 2  # a and b each computed once


def test_the_result_snapshots_the_counter_at_that_request(
    materialiser: FeatureMaterialiser,
) -> None:
    # The counter keeps rising for the life of the materialiser, so a caller
    # that must attribute a hit to a particular request reads it off the
    # result, which carries the count as it stood after that call — not the
    # current, later value.
    key = make_key()
    definition = Compute()
    materialiser.materialise(key, definition)
    first = materialiser.materialise(key, definition)
    second = materialiser.materialise(key, definition)
    assert first.cache_hit == 1
    assert second.cache_hit == 2
    assert materialiser.cache_hit == 2


def test_a_replace_true_recompute_is_a_miss_not_a_hit(
    materialiser: FeatureMaterialiser,
) -> None:
    # replace=True deliberately recomputes over a stored feature, so it does
    # the work a miss does and must not be credited as a reuse.  The hit
    # counter is untouched; the miss counter records the deliberate recompute.
    key = make_key()
    definition = Compute()
    materialiser.materialise(key, definition)
    materialiser.materialise(key, definition, replace=True)
    assert materialiser.cache_hit == 0
    assert materialiser.cache_miss == 2


def test_a_corrupt_lake_refused_is_not_credited_as_a_hit(
    materialiser: FeatureMaterialiser,
) -> None:
    # A corrupt materialisation is refused, not reused, so the reuse counter
    # must not move — a refused read is neither a hit nor a served request.
    key = make_key()
    path = materialiser.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"junk")
    with pytest.raises(MaterialisationError, match="damaged"):
        materialiser.load(key)
    assert materialiser.cache_hit == 0
    assert materialiser.cache_miss == 0


def test_the_cache_hit_rate_is_hits_over_total(
    materialiser: FeatureMaterialiser,
) -> None:
    # The ratio, not just the count: one miss then three hits is 3 / (1 + 3).
    key = make_key()
    definition = Compute()
    materialiser.materialise(key, definition)
    for _ in range(3):
        materialiser.materialise(key, definition)
    assert materialiser.cache_hit == 3
    assert materialiser.cache_miss == 1
    assert materialiser.cache_hit_rate == pytest.approx(0.75)


def test_the_cache_hit_rate_is_zero_before_any_request(
    materialiser: FeatureMaterialiser,
) -> None:
    # No requests means no reuse to measure; the rate is defined as 0.0 rather
    # than a division by zero, so a freshly composed materialiser reports a
    # sane number instead of raising.
    assert materialiser.cache_hit == 0
    assert materialiser.cache_miss == 0
    assert materialiser.cache_hit_rate == 0.0


def test_reset_cache_stats_bounds_the_measurement_window(
    materialiser: FeatureMaterialiser,
) -> None:
    # A replay or a test that must measure one window in isolation resets both
    # counters to zero, so an earlier scenario's counts do not bleed into a
    # later one.  After the reset the counters start again from a clean slate.
    key = make_key()
    definition = Compute()
    materialiser.materialise(key, definition)
    for _ in range(4):
        materialiser.materialise(key, definition)
    assert materialiser.cache_hit == 4
    materialiser.reset_cache_stats()
    assert materialiser.cache_hit == 0
    assert materialiser.cache_miss == 0
    assert materialiser.cache_hit_rate == 0.0
    # The stored file still exists, so a plain request after the reset would be
    # a hit; a deliberate recompute (replace=True) is the miss that proves the
    # two counters climb again from the clean slate.
    materialiser.materialise(key, definition, replace=True)
    assert materialiser.cache_hit == 0
    assert materialiser.cache_miss == 1
    materialiser.materialise(key, definition)
    assert materialiser.cache_hit == 1
    assert materialiser.cache_miss == 1


def test_the_counter_is_process_memory_not_persisted(
    materialiser: FeatureMaterialiser, lake_root: Path
) -> None:
    # Feature 50 measures a running process, and feature 49 persists the bytes.
    # The two must not be confused: a second materialiser over the same lake
    # finds the stored file and reuses it, but its own counter starts at zero,
    # because the count is never written to the lake — a fresh process has no
    # history to report.
    key = make_key()
    materialiser.materialise(key, Compute())
    for _ in range(3):
        materialiser.materialise(key, Compute())
    assert materialiser.cache_hit == 3
    other = FeatureMaterialiser(lake_root)
    assert other.cache_hit == 0
    assert other.cache_miss == 0
    result = other.materialise(key, Compute())
    assert result.materialised is False  # the file IS reused across processes
    assert other.cache_hit == 1  # but this process's count is its own
