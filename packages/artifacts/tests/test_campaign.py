"""Feature 174: one campaign's signal returns load as one dense array.

app_spec.xml, "Tree & Artifact Persistence", feature 174: *"System loads one
campaign of signal returns as a single dense float32 array of shape nodes by
periods."*  docs/nullius-tech-architecture.md §9.3 is the section behind the
sentence — the replay bottleneck is I/O, and the answer is to *"load each
campaign's signal returns once as a single dense ``float32`` array of shape
``(nodes × T)``"* so that ``ir_marginal`` becomes array indexing plus a
rank-1 update.

These tests pin the load as six facts, each one a way a careless version of
the feature would silently fail:

* **the shape is the campaign's, and both axes are orderings the store
  already owns** — rows in the store's sorted node listing, columns in the
  sorted union of the priced rebalance dates, however many nodes and
  periods that is, and nothing else riding in the buffer.
* **the cells are float32 and the narrowing is the point** — the file keeps
  the double the evaluator computed (feature 170's stance), the resident
  array keeps the 4 bytes §9.3 sizes its residency by, and a mean that
  cannot survive the narrowing refuses instead of becoming an ``inf``.
* **the value is the T-vector §9.3 says a signal contributes** — the
  equal-weight per-date post-cost return at the pinned horizon, both
  collapses the evaluator's own, not a per-symbol cell and not a
  zero-filled pad.
* **absence is NaN, not zero** — a cell no panel measured is the IEEE
  quiet NaN, the one float32 value that cannot be mistaken for a
  measurement, and a node the pinned horizon does not measure at all
  refuses rather than answering a pure-NaN row.
* **the horizon is a policy, not a guess** — the shortest horizon every
  swept panel covers (the evaluator's ``METRICS_HORIZON`` at campaign
  scale), pinnable by a caller measuring at another axis, and refusing
  both a campaign whose panels share no horizon and a pinned horizon a
  panel covers no date of.
* **the load joins one world** — it reads through feature 170's own read
  side (a file that read refuses, the load refuses — there is no second
  decoder to trust), it sweeps only published nodes (staged writes stay
  invisible), and panels disagreeing on their sealed snapshot or their
  ``(venue, version)`` cost pair refuse, because the load is the seam
  where a per-file identity becomes a per-campaign fact.

The record itself is pinned too: a hand-built :class:`~artifacts.
CampaignReturns` that is not the shape this module answers — a ragged
buffer, a wider typecode, an unsorted or repeated axis, an ``inf`` —
refuses at construction, so the lying spellings cannot be built any more
than they can be loaded.
"""

from __future__ import annotations

import array as _array
import datetime as dt
import io
import math
import struct

import pytest

pytest.importorskip("pyarrow", reason="the §9.3 campaign load requires pyarrow")
import pyarrow as pa
from artifacts import (
    ABSENT,
    CAMPAIGN_LOAD_HORIZON,
    FLOAT32_TYPECODE,
    PARQUET_COMPRESSION,
    SIGNAL_RETURNS_FILENAME,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
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
    *panels: SignalReturns,
) -> None:
    """Persist and commit each panel — the state §9.3's load sweeps."""
    for panel in panels:
        persist_signal_returns(store, campaign_id, panel.node_id, panel)
        store.commit(campaign_id, panel.node_id)


def _narrowed(mean: float) -> float:
    """The float32 a float64 mean narrows to, through struct not array.

    Spelled with :mod:`struct` rather than ``array.array('f', [mean])[0]``
    on purpose: the point of the narrowing assertions below is that the
    *loader* narrowed through its own buffer, and an expected value built
    the same way would agree with any implementation that rounded the same
    corner, not with the narrowing itself.
    """
    return struct.unpack("<f", struct.pack("<f", mean))[0]


def _refuse(fn, *args, **kwargs) -> str:
    """Call ``fn``, require an :class:`ArtifactStoreError`, return its message."""
    with pytest.raises(ArtifactStoreError) as caught:
        fn(*args, **kwargs)
    return str(caught.value)


# -- A two-node campaign, the suite's working shape ---------------------------------

#: Node ``node-a``: two symbols on D1 and D2 at horizon 1 — the panel the
#: equal-weight reduction below is computed against by hand.
A_ROWS = (
    _row(D1, "AAA", 0.010),
    _row(D1, "BBB", -0.004, charge=0.002),
    _row(D2, "AAA", -0.020),
    _row(D2, "BBB", 0.006, charge=0.002),
)

#: Node ``node-b``: horizon 1 on D2 and D3 only — ragged against ``node-a``
#: (it misses D1; ``node-a`` misses D3), which is what makes the union axis
#: and the NaN-absence assertions below honest rather than decorative.
B_ROWS = (
    _row(D2, "AAA", -0.010),
    _row(D3, "BBB", 0.008, charge=0.002),
)

#: The equal-weight per-date post-cost returns of ``node-a`` at horizon 1 —
#: feature 80's own reduction (``fsum`` over the day's nets over their
#: count), computed here once so the value assertions name their terms.
A_D1 = math.fsum((0.010, -0.004)) / 2
A_D2 = math.fsum((-0.020, 0.006)) / 2


def _two_node_campaign(store: ArtifactStore, campaign_id: str) -> None:
    """Publish the working shape: ``node-a`` and ``node-b``, one world."""
    _published(
        store,
        campaign_id,
        _panel("node-a", A_ROWS),
        _panel("node-b", B_ROWS),
    )


# -- The shape, the buffer and the narrowing ----------------------------------------


def test_the_shape_is_nodes_by_periods(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The feature's own words: shape nodes by periods.  Two nodes, whose
    # priced grids cover {D1, D2} and {D2, D3} — the union is three periods,
    # and the load answers exactly that rectangle.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.shape == (2, 3)
    assert loaded.node_ids == ("node-a", "node-b")
    assert loaded.periods == (D1, D2, D3)


def test_the_buffer_is_float32_and_nothing_else_rides_along(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3's arithmetic — 500 nodes × 2000 periods × 4 B = 4 MB — is
    # arithmetic about binary32; the buffer answers the typecode, the item
    # width and not one byte more.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.values.typecode == FLOAT32_TYPECODE
    assert loaded.values.itemsize == 4
    assert len(loaded.values.tobytes()) == 2 * 3 * 4


def test_the_values_are_the_equal_weight_per_date_returns(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The T-vector §9.3 says each signal contributes: the mean over the
    # symbols the date holds of the post-cost returns — the charge stays
    # answerable from the file, which is what the file carrying all three
    # numbers is for.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.cell("node-a", D1) == pytest.approx(A_D1, abs=1e-9)
    assert loaded.cell("node-a", D2) == pytest.approx(A_D2, abs=1e-9)
    assert loaded.cell("node-b", D2) == pytest.approx(-0.010, abs=1e-9)
    assert loaded.cell("node-b", D3) == pytest.approx(0.008, abs=1e-9)


def test_the_file_keeps_the_double_the_array_narrows_once(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The opposite decision for the opposite reason (§9.2 stores float64,
    # §9.3 residents float32): A_D1 is a value whose binary32 spelling
    # differs from its binary64 one, so this pins that the cell holds the
    # narrowed float and not the double the file keeps.
    assert A_D1 != _narrowed(A_D1)  # 0.003 does not survive narrowing exactly
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.cell("node-a", D1) == _narrowed(A_D1)


def test_the_row_axis_is_the_stores_own_listing_order(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Persisted in the opposite order, answered in the one order the store's
    # listing walks — a row's index is a fact about the campaign, not about
    # which readdir or which persist happened first.
    _published(
        store,
        campaign_id,
        _panel("node-b", B_ROWS),
        _panel("node-a", A_ROWS),
    )
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.node_ids == ("node-a", "node-b")
    assert loaded.cell("node-a", D1) == pytest.approx(A_D1, abs=1e-9)


def test_the_column_axis_is_the_sorted_union_of_priced_dates(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A node's grid covers the dates it priced and not the dates it did
    # not; the campaign's period axis is the union, sorted — the market
    # calendar at campaign scale.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.periods == tuple(sorted((D1, D2, D3)))


def test_the_rows_are_contiguous_spans_of_the_buffer(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Row-major, node after node: a node's whole row is one contiguous
    # span, which is what makes the resident array indexable the way
    # §9.3's rank-1 update wants to index it.  The span check is on the
    # bytes, because a row holding the absent NaN cannot be compared with
    # ``==`` entry-wise (NaN ≠ NaN) — the same rule the consumers of the
    # array live by: test, don't read.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    row = loaded.row("node-b")
    assert isinstance(row, type(loaded.values))
    assert row.typecode == FLOAT32_TYPECODE
    width = loaded.shape[1]
    offset = loaded.node_ids.index("node-b") * width
    assert row.tobytes() == loaded.values.tobytes()[
        offset * 4 : (offset + width) * 4
    ]
    assert math.isnan(row[0])  # node-b was never priced on D1
    assert row[1] == loaded.cell("node-b", D2)
    assert row[2] == loaded.cell("node-b", D3)


# -- Absence is not zero ------------------------------------------------------------


def test_absence_is_nan_not_zero(
    store: ArtifactStore, campaign_id: str
) -> None:
    # ``node-b`` was never priced on D1 and ``node-a`` never on D3: those
    # cells carry the IEEE quiet NaN — the one float32 value that cannot
    # be mistaken for a measurement.  Zero would be the lie ("the signal
    # returned nothing"); a caller must test, not read.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert math.isnan(loaded.cell("node-b", D1))
    assert math.isnan(loaded.cell("node-a", D3))
    assert not math.isnan(loaded.cell("node-a", D1))
    assert not math.isnan(loaded.cell("node-b", D3))
    assert loaded.cell("node-a", D1) != 0.0


def test_absence_marks_the_marker_the_module_spells(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The one spelling of the marker: the loader's writer, the consumer's
    # test and the constant are the same value, so a refactor cannot drift
    # them apart — and the marker is NaN whichever way a consumer spells
    # the test for it.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert math.isnan(ABSENT)
    assert loaded.cell("node-b", D1) != loaded.cell("node-b", D1)  # NaN ≠ NaN


# -- The horizon policy -------------------------------------------------------------


def test_the_default_horizon_is_the_shortest_every_panel_covers(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The evaluator's METRICS_HORIZON at campaign scale: ``node-a`` covers
    # horizons 1 and 2, ``node-b`` covers 2 only, and the load pins 2 —
    # the shortest horizon every node's panel covers, a function of the
    # panels rather than a caller's guess.
    _published(
        store,
        campaign_id,
        _panel(
            "node-a",
            A_ROWS + (_row(D1, "AAA", 0.05, horizon=2),),
        ),
        _panel("node-b", (_row(D2, "AAA", 0.02, horizon=2),)),
    )
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.horizon == 2
    assert loaded.cell("node-a", D1) == pytest.approx(0.05, abs=1e-9)


def test_a_caller_may_pin_another_horizon(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The panels are stored in full so another axis can be loaded: the
    # same campaign pinned at horizon 2 answers horizon 2's own values.
    _published(
        store,
        campaign_id,
        _panel(
            "node-a",
            A_ROWS + (_row(D1, "AAA", 0.05, horizon=2),),
        ),
        _panel(
            "node-b",
            B_ROWS + (_row(D2, "BBB", 0.03, horizon=2),),
        ),
    )
    loaded = load_campaign_returns(store, campaign_id, horizon=2)
    assert loaded.horizon == 2
    assert loaded.periods == (D1, D2)
    assert loaded.cell("node-a", D1) == pytest.approx(0.05, abs=1e-9)
    assert loaded.cell("node-b", D2) == pytest.approx(0.03, abs=1e-9)


def test_a_pinned_horizon_a_panel_covers_no_date_of_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Not an absent cell but an unanswerable row: a pinned horizon some
    # panel covers no date of refuses naming the node, because a row of
    # pure NaN would let a caller index a node that was never loaded for.
    _two_node_campaign(store, campaign_id)
    message = _refuse(load_campaign_returns, store, campaign_id, horizon=5)
    assert "node-a" in message
    assert "horizon 5" in message


def test_panels_sharing_no_horizon_refuse(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A dense array is one horizon deep for all its rows at once; panels
    # that share no horizon are measurements no single array is over.
    _published(
        store,
        campaign_id,
        _panel("node-a", (_row(D1, "AAA", 0.01, horizon=1),)),
        _panel("node-b", (_row(D1, "AAA", 0.02, horizon=2),)),
    )
    message = _refuse(load_campaign_returns, store, campaign_id)
    assert "share no horizon" in message
    assert "node-a" in message and "node-b" in message


def test_the_horizon_policy_is_spelled_once() -> None:
    # The policy is a name, not a number, and it is the evaluator's own
    # restated at campaign scale — pinned here so the two docstrings
    # cannot drift apart on which policy the default implements.
    assert CAMPAIGN_LOAD_HORIZON == (
        "the shortest horizon every node of the campaign covers"
    )


# -- One campaign, one world ---------------------------------------------------------


def test_the_load_reads_through_the_nodes_own_read_side(
    store: ArtifactStore, campaign_id: str
) -> None:
    # No second decoder: a file feature 170's read side refuses — a gross
    # edited so the row no longer nets out — refuses the campaign load with
    # the same refusal, naming the node it came from.
    _two_node_campaign(store, campaign_id)
    target = (
        store.root / campaign_id / "node-a" / SIGNAL_RETURNS_FILENAME
    )
    table = pa.parquet.read_table(target)
    body = {name: table.column(name).to_pylist() for name in table.schema.names}
    body["gross_return"][0] += 0.5  # a row that no longer nets out
    buffer = io.BytesIO()
    pa.parquet.write_table(
        pa.Table.from_pydict(body, schema=table.schema), buffer,
        compression=PARQUET_COMPRESSION,
    )
    target.write_bytes(buffer.getvalue())
    with pytest.raises(ArtifactStoreError) as caught:
        load_campaign_returns(store, campaign_id)
    assert "node-a" in str(caught.value)


def test_a_node_without_the_grid_refuses_the_load(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The grid is the key artifact; a load that silently skipped the node
    # would answer an array that under-reports the campaign replay is
    # about to score.
    _two_node_campaign(store, campaign_id)
    store.write(campaign_id, node_id, "code.py", b"def signal(): ...\n")
    store.commit(campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError) as caught:
        load_campaign_returns(store, campaign_id)
    assert node_id in str(caught.value)
    assert SIGNAL_RETURNS_FILENAME in str(caught.value)


def test_a_staged_but_uncommitted_node_is_invisible(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The discipline feature 169 states, holding at campaign scale: staged
    # writes are invisible to every read, so a campaign load never sees a
    # half-written node — the array answers the published campaign, only.
    _published(store, campaign_id, _panel("node-a", A_ROWS))
    persist_signal_returns(
        store, campaign_id, "node-b", _panel("node-b", B_ROWS)
    )  # staged, never committed
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.shape == (1, 2)
    assert loaded.node_ids == ("node-a",)


def test_a_campaign_with_no_nodes_refuses_as_not_found(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A fact about the store's contents, not a breakage: nothing is
    # persisted under the campaign, so there are no returns to load — and
    # an empty array is not a shape any replay could score.
    with pytest.raises(ArtifactNotFoundError) as caught:
        load_campaign_returns(store, campaign_id)
    assert campaign_id in str(caught.value)


def test_the_load_sweeps_only_the_campaign_asked(
    store: ArtifactStore, campaign_id: str, other_campaign_id: str
) -> None:
    # The first key does the separating: each load answers its own
    # campaign's nodes, never the other's.
    _two_node_campaign(store, campaign_id)
    _published(store, other_campaign_id, _panel("node-c", B_ROWS))
    assert load_campaign_returns(store, campaign_id).node_ids == (
        "node-a",
        "node-b",
    )
    assert load_campaign_returns(store, other_campaign_id).node_ids == (
        "node-c",
    )


def test_panels_from_different_sealed_worlds_refuse(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The load is the seam where a per-file identity becomes a
    # per-campaign fact: panels measured in different sealed worlds have
    # "periods" that are different calendars wearing the same dates.
    _published(
        store,
        campaign_id,
        _panel("node-a", A_ROWS, snapshot_name="snap-2026-01"),
        _panel("node-b", B_ROWS, snapshot_name="snap-2026-02"),
    )
    message = _refuse(load_campaign_returns, store, campaign_id)
    assert "snap-2026-01" in message
    assert "snap-2026-02" in message


def test_panels_priced_under_different_schedules_refuse(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Same rule, other half: post-cost returns priced under different fee
    # schedules are different quantities, not one axis.
    _published(
        store,
        campaign_id,
        _panel("node-a", A_ROWS, venue="binance", version="v3"),
        _panel("node-b", B_ROWS, venue="binance", version="v4"),
    )
    message = _refuse(load_campaign_returns, store, campaign_id)
    assert "v3" in message and "v4" in message


def test_the_agreed_identity_is_answered_on_the_record(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A caller holding the resident array also holds the world it was
    # measured in — the snapshot and the cost pair every panel named.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    assert loaded.campaign_id == campaign_id
    assert loaded.snapshot_name == SNAPSHOT
    assert loaded.venue == VENUE
    assert loaded.version == VERSION


def test_two_loads_answer_identical_arrays(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3's determinism contract at the load: the same campaign, loaded
    # twice, answers the same axes and the same bytes — so a replay
    # comparing arrays compares content, never iteration order.
    _two_node_campaign(store, campaign_id)
    first = load_campaign_returns(store, campaign_id)
    second = load_campaign_returns(store, campaign_id)
    assert first.node_ids == second.node_ids
    assert first.periods == second.periods
    assert first.values.tobytes() == second.values.tobytes()


# -- The accessors, and the refusals around them -------------------------------------


def test_a_row_the_array_does_not_hold_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    message = _refuse(loaded.row, "node-z")
    assert "node-z" in message
    assert campaign_id in message


def test_a_period_the_array_does_not_hold_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    message = _refuse(loaded.cell, "node-a", dt.date(2026, 2, 1))
    assert "2026-02-01" in message


def test_a_datetime_period_refuses_rather_than_passing(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A datetime *is* a date in Python and would pass a naive check —
    # the same trap the file layer refuses, restated on the column axis.
    _two_node_campaign(store, campaign_id)
    loaded = load_campaign_returns(store, campaign_id)
    message = _refuse(
        loaded.cell, "node-a", dt.datetime(2026, 1, 5, 12, 0)  # noqa: DTZ001
    )
    assert "datetime" in message


# -- The narrowing's own refusal ------------------------------------------------------


def test_a_mean_too_large_for_float32_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The file refuses non-finite measurements; the load refuses a finite
    # measurement that cannot be narrowed — 1e300 is a finite float64 and
    # an infinity in binary32, and an overflowed return must not ride the
    # resident array as if the evaluator computed it.
    _published(
        store,
        campaign_id,
        _panel("node-a", (_row(D1, "AAA", 1e300),)),
    )
    message = _refuse(load_campaign_returns, store, campaign_id)
    assert "node-a" in message
    assert D1.isoformat() in message
    assert "float32" in message


# -- The record refuses the lying spellings -------------------------------------------


def _record(
    *,
    values: object = None,
    node_ids: object = ("node-a",),
    periods: object = (D1,),
    horizon: int = 1,
    snapshot_name: str = SNAPSHOT,
) -> CampaignReturns:
    """A minimal valid record, with the one thing under test replaced."""
    return CampaignReturns(
        campaign_id="camp",
        snapshot_name=snapshot_name,
        venue=VENUE,
        version=VERSION,
        horizon=horizon,
        node_ids=node_ids,  # type: ignore[arg-type]
        periods=periods,  # type: ignore[arg-type]
        values=(
            values
            if values is not None
            else _array.array(FLOAT32_TYPECODE, [0.01])
        ),
    )


def test_a_buffer_of_the_wrong_typecode_refuses() -> None:
    message = _refuse(_record, values=_array.array("d", [0.01]))
    assert "float32" in message
    assert "'f'" in message


def test_a_buffer_of_the_wrong_length_refuses() -> None:
    message = _refuse(
        _record, values=_array.array(FLOAT32_TYPECODE, [0.01, 0.02])
    )
    assert "cells" in message


def test_a_buffer_that_is_not_an_array_refuses() -> None:
    message = _refuse(_record, values=[0.01])
    assert "array.array" in message


def test_an_infinite_cell_refuses_naming_its_node() -> None:
    message = _refuse(
        _record,
        node_ids=("node-a", "node-b"),
        periods=(D1, D2),
        values=_array.array(FLOAT32_TYPECODE, [0.01, ABSENT, math.inf, 0.02]),
    )
    assert "node-b" in message  # cell 2 is row 1, column 0
    assert D1.isoformat() in message


def test_an_empty_axis_refuses() -> None:
    assert "node_ids" in _refuse(_record, node_ids=())
    assert "periods" in _refuse(_record, periods=())


def test_an_unsorted_or_repeated_axis_refuses() -> None:
    assert "sorted" in _refuse(_record, node_ids=("node-b", "node-a"))
    assert "sorted" in _refuse(_record, node_ids=("node-a", "node-a"))
    assert "sorted" in _refuse(_record, periods=(D2, D1))
    assert "sorted" in _refuse(_record, periods=(D1, D1))


def test_a_period_that_is_not_a_date_refuses() -> None:
    assert "calendar dates" in _refuse(_record, periods=("2026-01-05",))
    assert "calendar dates" in _refuse(
        _record, periods=(dt.datetime(2026, 1, 5),)  # noqa: DTZ001
    )


def test_an_axis_of_the_wrong_type_refuses() -> None:
    assert "node ids" in _refuse(_record, node_ids=(1, 2))


def test_a_missing_identity_refuses() -> None:
    message = _refuse(_record, snapshot_name=" ")
    assert "snapshot" in message


def test_a_horizon_that_is_not_a_period_count_refuses() -> None:
    message = _refuse(_record, horizon=0)
    assert "horizon" in message
