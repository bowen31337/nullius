"""The downsampled daily return series — §9.3's scaling caveat, feature 180.

app_spec.xml, "Tree & Artifact Persistence", feature 180: *System
downsamples a high-frequency return series to daily for replay-time
computation, retaining the fine series for promotion decisions.*  These
tests hold the downsample to that sentence in the places it can be read:

* **the daily series is the fine grid reduced, not a new measurement** —
  each date's daily value is the equal-weight per-date post-cost return at
  the pinned horizon (``fsum`` over the day's nets over their count,
  feature 80's own reduction), computed by hand against the same panel the
  assertions stage, so a careless version that averaged the wrong axis or
  the wrong number is caught;
* **the fine series is retained, verbatim and undisturbed** — the daily
  file is a *new* name in the node's directory; after the downsample the
  fine grid still reads back with exactly the rows it had, and the daily
  file sits beside it rather than replacing it;
* **the daily file rides feature 169's write path and feature 171's
  codec** — it is float64/date32 and sorted by date, so two equal
  downsamples stage identical bytes, and a refresh re-stages the one name
  without splicing two runs;
* **absence is a missing key, not zero** — a date the grid priced at some
  horizons but not the pinned one is left out of the daily series
  entirely, never a zero dressed as one; a date with no row to reduce has
  no daily return to record;
* **the horizon is a policy, not a guess** — the shortest horizon every
  priced date covers, unless a caller pins another; a node whose grid
  covers no date at the pinned horizon refuses;
* **the read side refuses what the writer cannot have produced** — bytes
  that are not Parquet, the wrong columns, a node other than the one the
  file was read from, all refuse by name, and the daily file is answered by
  the node's same two keys through the store's read surface.

The *metric* is the evaluator's (feature 80): what an equal-weight
per-date return means belongs to that package, and it is not imported here
(the workspace contract — no member imports another).  These tests stage
panels of the shape feature 170 renders and assert only what this layer
owns: the reduction, the file, the read side and the refusals.

pyarrow is a declared dependency of this member (see ``pyproject.toml``),
so under the canonical invocation (``uv run --all-packages pytest``, what
the acceptance gate runs) it is present; the guard below keeps a partially
installed environment from turning a missing wheel into a collection error
that takes the whole suite down with it.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest

pytest.importorskip(
    "pyarrow",
    reason="the §9.3 daily-downsample suite requires pyarrow (a declared dependency)",
)

import pyarrow as pa
from artifacts import (
    DAILY_RETURNS_FILENAME,
    DATE_COLUMN,
    SIGNAL_RETURNS_FILENAME,
    VALUE_COLUMN,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    ReturnRow,
    SignalReturns,
    daily_returns,
    daily_returns_is_persisted,
    persist_daily_returns,
    persist_signal_returns,
    signal_returns,
    signal_returns_is_persisted,
)

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)

SNAPSHOT = "snap-2026-01"
VENUE = "binance"
VERSION = "v3"


# -- Small builders ----------------------------------------------------------------


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
    node_id: str,
    panel: SignalReturns,
) -> None:
    """Persist and commit the node's fine grid — the state §9.3 downsamples."""
    persist_signal_returns(store, campaign_id, node_id, panel)
    store.commit(campaign_id, node_id)


def _downsampled(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    *,
    horizon: int | None = None,
) -> None:
    """Downsample the node's grid and publish it — stage, then commit once.

    ``persist_daily_returns`` stages (feature 169's convention — the caller
    commits), so the daily file is published by the node's one commit,
    exactly as the grid was.
    """
    persist_daily_returns(store, campaign_id, node_id, horizon=horizon)
    store.commit(campaign_id, node_id)


def _refuse(fn, *args, **kwargs) -> str:
    """Call ``fn``, require an :class:`ArtifactStoreError`, return its message."""
    with pytest.raises(ArtifactStoreError) as caught:
        fn(*args, **kwargs)
    return str(caught.value)


# -- The working panel ---------------------------------------------------------------

#: A node whose grid is five horizons deep on some dates and one horizon
#: deep on others — ``D1`` covers {1, 5}, ``D2`` covers {1}, ``D3`` covers
#: {1, 5} — so the default pinned horizon (the shortest every priced date
#: covers) is 1, and ``D2`` is absent at horizon 5, which is what makes the
#: omission and horizon-policy assertions honest rather than decorative.
GRID_ROWS = (
    _row(D1, "AAA", 0.010, horizon=1),
    _row(D1, "BBB", -0.004, horizon=1, charge=0.002),
    _row(D1, "AAA", 0.020, horizon=5),
    _row(D2, "AAA", -0.010, horizon=1),
    _row(D3, "BBB", 0.008, horizon=1, charge=0.002),
    _row(D3, "AAA", 0.030, horizon=5),
)

#: The equal-weight per-date post-cost returns at horizon 1 — feature 80's
#: own reduction, computed here once so the value assertions name their terms.
D1_H1 = math.fsum((0.010, -0.004)) / 2
D2_H1 = -0.010
D3_H1 = 0.008

#: The equal-weight per-date post-cost returns at horizon 5 — ``D2`` has no
#: horizon-5 row, so it is left out of the daily series, not zero-filled.
D1_H5 = 0.020
D3_H5 = 0.030


# -- The reduction -------------------------------------------------------------------


def test_the_daily_series_is_the_equal_weight_per_date_return(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The feature's own words: downsample the fine grid to one equal-weight
    # per-date daily return.  At the default pinned horizon (1, the shortest
    # every priced date covers) the daily value of each date is the mean of
    # that date's post-cost returns over the symbols it holds.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id)
    got = daily_returns(store, campaign_id, node_id)
    assert got[D1] == pytest.approx(D1_H1, abs=1e-9)
    assert got[D2] == pytest.approx(D2_H1, abs=1e-9)
    assert got[D3] == pytest.approx(D3_H1, abs=1e-9)


def test_the_daily_value_is_not_a_per_symbol_cell(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A careless downsample might keep one symbol's return, or sum rather
    # than mean; the daily value is the *mean over the symbols the date
    # holds*, so ``D1`` (two symbols) is the mean of the two, not either
    # one and not their sum.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id)
    got = daily_returns(store, campaign_id, node_id)
    assert got[D1] == pytest.approx(D1_H1, abs=1e-9)
    assert got[D1] != pytest.approx(0.010, abs=1e-9)  # not AAA alone
    assert got[D1] != pytest.approx(0.006, abs=1e-9)  # not the sum


# -- The fine series is retained -----------------------------------------------------


def test_the_fine_grid_is_untouched_and_the_daily_file_sits_beside_it(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The daily file is a *new* name, derived from the grid and persisted
    # beside it, not a replacement: after the downsample the node's
    # directory holds both files, and the fine grid still reads back with
    # exactly the rows it had.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    before = signal_returns(store, campaign_id, node_id)
    _downsampled(store, campaign_id, node_id)
    assert store.files(campaign_id, node_id) == (
        DAILY_RETURNS_FILENAME,
        SIGNAL_RETURNS_FILENAME,
    )
    after = signal_returns(store, campaign_id, node_id)
    assert after.rows == before.rows


def test_the_daily_file_does_not_overwrite_the_grid_on_a_refresh(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Re-persisting the daily file re-stages the one name, keeping the last
    # bytes, never a splice of two runs — and the grid it preserves is never
    # the downsample's to touch.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id, horizon=1)
    _downsampled(store, campaign_id, node_id, horizon=1)
    assert store.files(campaign_id, node_id) == (
        DAILY_RETURNS_FILENAME,
        SIGNAL_RETURNS_FILENAME,
    )
    got = daily_returns(store, campaign_id, node_id)
    assert got[D1] == pytest.approx(D1_H1, abs=1e-9)
    assert len(signal_returns(store, campaign_id, node_id).rows) == len(GRID_ROWS)


def test_a_discard_rolls_the_daily_file_back_without_touching_the_grid(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The staged path's rollback half: a failure before the commit publishes
    # nothing, so the daily file never lands — and the grid the downsample
    # preserved stays published, untouched by the rollback.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    persist_daily_returns(store, campaign_id, node_id)
    store.discard(campaign_id, node_id)
    assert not daily_returns_is_persisted(store, campaign_id, node_id)
    assert signal_returns_is_persisted(store, campaign_id, node_id)


# -- The daily file rides feature 169's path and feature 171's codec ------------------


def test_the_daily_file_is_float64_and_date32(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The daily series is a *stored measurement*, so it keeps the float64 the
    # evaluator computed (§9.3's float32 is the opposite decision for the
    # resident replay array), and its date axis is a real date column — the
    # shape feature 171's series codec pins.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id)
    arrow = pa
    table = arrow.parquet.read_table(
        arrow.BufferReader(store.read(campaign_id, node_id, DAILY_RETURNS_FILENAME))
    )
    assert list(table.schema.names) == [DATE_COLUMN, VALUE_COLUMN]
    assert arrow.types.is_date(table.schema.field(DATE_COLUMN).type)
    assert arrow.types.is_floating(table.schema.field(VALUE_COLUMN).type)


def test_two_equal_downsamples_stage_identical_bytes(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Canonical bytes: entries are sorted by date before they are written, so
    # a replay comparing a stored daily series against the one it is
    # reconstructing compares content and never iteration order.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id)
    first = store.read(campaign_id, node_id, DAILY_RETURNS_FILENAME)
    _downsampled(store, campaign_id, node_id)
    second = store.read(campaign_id, node_id, DAILY_RETURNS_FILENAME)
    assert first == second


def test_the_daily_series_is_answered_in_ascending_date_order(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The read side answers the shape the writer emits: a mapping of calendar
    # dates to values in ascending date order, the one order a series has.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id)
    got = daily_returns(store, campaign_id, node_id)
    assert list(got.keys()) == sorted(got.keys())
    assert list(got.keys()) == [D1, D2, D3]


# -- Absence is a missing key, not zero ----------------------------------------------


def test_a_date_absent_at_the_pinned_horizon_is_omitted_not_zero(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # ``D2`` has a horizon-1 row but no horizon-5 row, so at horizon 5 it is
    # absent — left out of the daily series entirely rather than written as
    # a zero dressed as a measurement: a date with no row to reduce has no
    # daily return to record.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id, horizon=5)
    got = daily_returns(store, campaign_id, node_id)
    assert got[D1] == pytest.approx(D1_H5, abs=1e-9)
    assert got[D3] == pytest.approx(D3_H5, abs=1e-9)
    assert D2 not in got  # no horizon-5 row, so no daily return to record


# -- The horizon is a policy, not a guess --------------------------------------------


def test_the_default_horizon_is_the_shortest_every_date_covers(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The grid covers {1,5}, {1}, {1,5} on D1/D2/D3, so the shortest horizon
    # every priced date covers is 1 — the evaluator's METRICS_HORIZON policy
    # restated for the daily file — and the default downsample lands there.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id)
    got = daily_returns(store, campaign_id, node_id)
    assert got[D1] == pytest.approx(D1_H1, abs=1e-9)
    assert got[D2] == pytest.approx(D2_H1, abs=1e-9)
    assert got[D3] == pytest.approx(D3_H1, abs=1e-9)


def test_a_caller_may_pin_another_horizon(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The grid is on disk in full precisely so another axis can be loaded; a
    # caller measuring at horizon 5 pins it, and the daily series answers the
    # horizon-5 reduction — with ``D2`` absent, since it has no horizon-5 row.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    _downsampled(store, campaign_id, node_id, horizon=5)
    got = daily_returns(store, campaign_id, node_id)
    assert got[D1] == pytest.approx(D1_H5, abs=1e-9)
    assert got[D3] == pytest.approx(D3_H5, abs=1e-9)
    assert D2 not in got  # no horizon-5 row, so no daily return to record


def test_a_pinned_horizon_no_date_covers_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A horizon the grid never priced is not a sparse measurement but a node
    # the pinned axis does not answer, so the downsample refuses rather than
    # answering an all-absent daily series.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    msg = _refuse(
        persist_daily_returns, store, campaign_id, node_id, horizon=20
    )
    assert "covers no rebalance date at horizon 20" in msg


def test_a_node_with_no_grid_refuses_the_downsample(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The daily series is derived from the fine grid, so a node whose grid is
    # absent refuses — not a sparse measurement but a node with no returns to
    # downsample — and answers no empty daily file.
    msg = _refuse(persist_daily_returns, store, campaign_id, node_id)
    assert "has no fine signal-returns grid to downsample" in msg
    assert not daily_returns_is_persisted(store, campaign_id, node_id)


# -- The read side refuses what the writer cannot have produced ----------------------


def test_reading_a_daily_file_that_is_not_parquet_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Bytes this layer's writer cannot have produced refuse rather than
    # answering a stand-in — the same defence feature 171's read side makes.
    store.write(campaign_id, node_id, DAILY_RETURNS_FILENAME, b"not parquet")
    store.commit(campaign_id, node_id)
    msg = _refuse(daily_returns, store, campaign_id, node_id)
    assert "is not a Parquet series" in msg


def test_reading_the_daily_file_from_a_node_with_no_directory_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A daily file asked for by a node that never persisted is a fact about
    # the store's contents, kept apart from a malformed file: the read side
    # answers ``ArtifactNotFoundError`` so a caller can report "no daily file"
    # the way §7.2's route reports its 404, rather than a generic breakage.
    with pytest.raises(ArtifactNotFoundError):
        daily_returns(store, campaign_id, "node-other")


def test_the_daily_file_is_answered_only_by_the_nodes_two_keys(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The daily series is keyed by the node's same two ids — campaign then
    # node — and answered through the store's read surface; a node that never
    # downsampled is ``ArtifactNotFoundError``, kept apart from a malformed
    # file so a caller can report "no daily file" the way §7.2's route
    # reports its 404.
    _published(store, campaign_id, node_id, _panel(node_id, GRID_ROWS))
    with pytest.raises(ArtifactNotFoundError):
        daily_returns(store, campaign_id, node_id)
