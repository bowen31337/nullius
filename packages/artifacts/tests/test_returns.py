"""The post-cost signal returns — §9.2's key artifact, feature 170.

app_spec.xml, "Tree & Artifact Persistence", feature 170: *System persists
signal_returns as Parquet per symbol and period after costs, which is what
lets replay recompute marginal contribution.*  docs/nullius-tech-architecture.md
§9.2 is what makes the "which is what" clause load-bearing: the file is *"the
key artifact"*, and *"because it is stored in full, marginal contribution
against any book can be recomputed at replay time"*.  These tests hold the
layer to that sentence in the places it can be read:

* **inside the node artifact directory** — the file stages through feature
  169's write path and publishes by the node's one commit, so it sits inside
  the node's single directory beside every other §9.2 file, rolls back with
  everything else on a discard, and is replaced wholesale by a refresh;
* **as Parquet** — real Zstd-compressed Parquet bytes carrying the
  ``date32``/``int32``/``string``/``float64`` columns this layer pins, sorted
  by ``(date, horizon, symbol)`` so two equal panels stage identical bytes and
  insertion order is never part of a stored panel's identity;
* **per symbol and period after costs** — every row of the priced panel is
  answered, at every horizon, with the schedule's deduction and the post-cost
  return on the row; nothing is averaged, summarised or dropped on either side
  of the seam, because that reduction is exactly what would make replay unable
  to recompute marginal contribution;
* **the refusals** — a value that is not a panel, a panel filed under another
  node's key, a row that is not a date, a period count, a symbol or a finite
  number, an empty panel and a panel with two rows in one cell all refuse
  *before the first staged byte*; the read side refuses bytes this member's
  writer cannot have produced and names what is wrong with them.

The *metric* is the evaluator's: what a post-cost return means, how a horizon
is chosen and how marginal contribution is scored belong to that package, and
it is not imported here (the workspace contract — no member imports another).
These tests build panels of the shape step 7 produces and assert only what
this layer owns: the name, the schema, the canonical row order, the metadata,
the read side and the refusals.

pyarrow is a declared dependency of this member (see ``pyproject.toml``), so
under the canonical invocation (``uv sync --all-packages`` then ``uv run
pytest``) it is present; the guard below keeps a partially installed
environment from turning a missing wheel into a collection error that takes
the whole suite down with it, the same guard ``test_series.py`` takes.
"""

from __future__ import annotations

import ast
import datetime as dt
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pyarrow",
    reason="the §9.2 signal-returns suite requires pyarrow (a declared dependency)",
)

import pyarrow as pa
from artifacts import (
    CHARGE_COLUMN,
    DATE_COLUMN,
    GROSS_COLUMN,
    HORIZON_COLUMN,
    NET_COLUMN,
    PARQUET_COMPRESSION,
    SIGNAL_RETURNS_FILENAME,
    SYMBOL_COLUMN,
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    ReturnRow,
    SignalReturns,
    decode_signal_returns,
    encode_signal_returns,
    persist_signal_returns,
    signal_returns,
    signal_returns_is_persisted,
)

#: conftest.py -> packages/artifacts/tests -> packages/artifacts -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)

SNAPSHOT = "snap-2026-01"
VENUE = "binance"
VERSION = "v3"

#: The schema, in the order every assertion below spells it — the module's own
#: column constants, so a rename of any of them is a failure here rather than a
#: silent drift between the writer and the reader.
COLUMNS = (
    DATE_COLUMN,
    HORIZON_COLUMN,
    SYMBOL_COLUMN,
    GROSS_COLUMN,
    CHARGE_COLUMN,
    NET_COLUMN,
)


# -- Small builders ----------------------------------------------------------------


def _row(
    day: dt.date,
    symbol: str,
    net: float,
    *,
    horizon: int = 1,
    charge: float = 0.001,
) -> ReturnRow:
    """One priced row, built the way step 7 hands a panel over.

    The charge and the net are the two numbers given and the gross is the
    record's own derivation — which is the point of the record's shape (see
    :class:`~artifacts.ReturnRow`), so the helper names the two the evaluator's
    series treat as primary.
    """
    return ReturnRow(
        rebalance_date=day,
        horizon=horizon,
        symbol=symbol,
        charge=charge,
        post_cost_return=net,
    )


def _panel(
    *,
    node_id: str = "node_1",
    rows: tuple[ReturnRow, ...] | None = None,
    snapshot_name: str = SNAPSHOT,
    venue: str = VENUE,
    version: str = VERSION,
) -> SignalReturns:
    """A small two-symbol, two-date panel at one horizon — step 7's shape."""
    if rows is None:
        rows = (
            _row(D1, "AAA", 0.010),
            _row(D1, "BBB", -0.004, charge=0.002),
            _row(D2, "AAA", -0.020),
            _row(D2, "BBB", 0.006, charge=0.002),
        )
    return SignalReturns(
        node_id=node_id,
        snapshot_name=snapshot_name,
        venue=venue,
        version=version,
        rows=rows,
    )


def _read_parquet(payload: bytes) -> pa.Table:
    """Read raw Parquet bytes back as an Arrow table, for shape assertions."""
    return pa.parquet.read_table(pa.BufferReader(payload))


def _refuse(fn, *args, **kwargs) -> str:
    """Call ``fn``, require an :class:`ArtifactStoreError`, return its message."""
    with pytest.raises(ArtifactStoreError) as caught:
        fn(*args, **kwargs)
    return str(caught.value)


# -- Re-staging helpers: bytes this member's writer cannot have produced -----------
#
# The read side's strictness is only testable against files the *writer* would
# not emit, so each helper below rebuilds a valid panel's body through Arrow by
# hand, with one thing about it changed.  ``pa.parquet`` is used directly rather
# than through :func:`encode_signal_returns` for exactly that reason: the point
# of each tamper is that its bytes do not come from this layer.


def _restaged(panel: SignalReturns) -> tuple[dict[str, list], pa.Schema, dict]:
    """A valid panel's body, schema and metadata, ready to be changed."""
    table = _read_parquet(encode_signal_returns(panel))
    return (
        {name: table.column(name).to_pylist() for name in table.schema.names},
        table.schema,
        table.schema.metadata,
    )


def _stage(
    body: dict[str, list],
    *,
    schema: pa.Schema,
    metadata: dict[bytes, bytes] | None,
) -> bytes:
    """Write one body out under the given column types and metadata."""
    pinned = pa.schema(
        [pa.field(name, schema.field(name).type) for name in schema.names],
        metadata=metadata,
    )
    buffer = io.BytesIO()
    pa.parquet.write_table(
        pa.Table.from_pydict(body, schema=pinned),
        buffer,
        compression=PARQUET_COMPRESSION,
    )
    return buffer.getvalue()


# -- The §9.2 name, the schema and the codec ---------------------------------------


def test_the_grid_name_is_the_layouts() -> None:
    # §9.2 spells the line "signal_returns.parquet"; the layer spells it once,
    # and this is that spelling — pinned so a rename on either side of the seam
    # shows up here rather than as a directory silently carrying the wrong name.
    assert SIGNAL_RETURNS_FILENAME == "signal_returns.parquet"


def test_the_date_column_is_spelled_with_the_series_files() -> None:
    # Three files in one directory key their rows by the same rebalance
    # calendar, so they spell that column the same way: a scan joining a node's
    # returns to its IC series should not have to learn a second name for the
    # same axis.
    from artifacts._returns import DATE_COLUMN as returns_date_column

    assert returns_date_column == DATE_COLUMN == "date"


def test_the_compression_is_the_stack_tables() -> None:
    # §4.1's stack table pins Parquet + Zstd, and this file is one of the files
    # that pin is about.  The written file's own codec is checked in
    # ``test_the_bytes_are_zstd_compressed_parquet`` below.
    assert PARQUET_COMPRESSION == "zstd"


def test_the_schema_is_the_six_pinned_columns() -> None:
    # The shape is this layer's to state: two axes of identity (the rebalance
    # date and the horizon), the instrument, and the three numbers of the fee
    # arithmetic.  Both halves of the date decision matter — ``date32`` rather
    # than text makes a rebalance a pushable predicate for the DuckDB scan
    # §4.1 reads these files with, and ``float64`` keeps the double the
    # evaluator computed rather than narrowing it on the way to disk.
    schema = _read_parquet(encode_signal_returns(_panel())).schema
    assert schema.names == list(COLUMNS)
    assert schema.field(DATE_COLUMN).type == pa.date32()
    assert schema.field(HORIZON_COLUMN).type == pa.int32()
    assert schema.field(SYMBOL_COLUMN).type == pa.string()
    assert schema.field(GROSS_COLUMN).type == pa.float64()
    assert schema.field(CHARGE_COLUMN).type == pa.float64()
    assert schema.field(NET_COLUMN).type == pa.float64()


def test_the_panels_identity_rides_in_the_schema_metadata() -> None:
    # The node, the sealed snapshot and feature 59's cost model pair are each
    # one value per *file* — a node's directory holds one returns artifact and
    # that artifact is one panel priced under one schedule — so they travel as
    # Arrow schema metadata rather than as columns that would repeat them on
    # every row and give a row the chance to disagree with its own file.
    table = _read_parquet(encode_signal_returns(_panel(node_id="node_7")))
    metadata = table.schema.metadata
    assert metadata[b"node_id"] == b"node_7"
    assert metadata[b"snapshot_name"] == SNAPSHOT.encode()
    assert metadata[b"venue"] == VENUE.encode()
    assert metadata[b"version"] == VERSION.encode()
    # No column repeats any of them: the identity is metadata and only
    # metadata, which is what keeps the file's columns the panel's rows.
    assert "node_id" not in table.schema.names


def test_the_bytes_are_zstd_compressed_parquet(tmp_path: Path) -> None:
    # Not merely "Arrow could read it back": the file is a real Parquet file
    # whose columns are Zstd-compressed, because §4.1's stack table pins the
    # codec and the sizing note behind that choice is about a store measured in
    # gigabytes.  Read from the footer rather than from the bytes, since the
    # claim is about what the file says it is.
    path = tmp_path / SIGNAL_RETURNS_FILENAME
    path.write_bytes(encode_signal_returns(_panel()))
    metadata = pa.parquet.read_metadata(path)
    assert metadata.num_columns == len(COLUMNS)
    assert metadata.num_rows == 4
    for index in range(metadata.num_columns):
        column = metadata.row_group(0).column(index)
        assert column.compression == "ZSTD", column.path_in_schema


# -- Per symbol and period: the panel is kept whole --------------------------------


def test_every_row_of_the_panel_is_answered_back() -> None:
    # The feature's "per symbol and period" read from the read side: what went
    # in comes back out, row for row, with the deduction and the post-cost
    # return beside each other.  This is the property §9.2's "stored in full"
    # is about — a file answering one averaged number per node would satisfy
    # "persists signal_returns" and make marginal contribution impossible to
    # recompute, so the count and the contents are both asserted.
    panel = _panel()
    got = decode_signal_returns(
        encode_signal_returns(panel), campaign_id="c", node_id="node_1"
    )
    assert got.rows == panel.rows
    assert len(got.rows) == len(panel.rows) == 4


def test_every_horizon_is_kept_in_the_one_file() -> None:
    # The horizon is a column rather than a filename, and this is why it has to
    # be: one target series per horizon is aligned upstream, and one node's
    # directory holds one returns artifact — so every horizon lives side by
    # side in the one grid.  A panel whose horizons were written to separate
    # files would be several artifacts where §9.2 draws one.
    rows = tuple(
        _row(D1, symbol, net, horizon=horizon)
        for horizon, net in ((1, 0.01), (5, -0.02), (20, 0.03))
        for symbol in ("AAA", "BBB")
    )
    panel = _panel(rows=rows)
    got = decode_signal_returns(
        encode_signal_returns(panel), campaign_id="c", node_id="node_1"
    )
    assert sorted({row.horizon for row in got.rows}) == [1, 5, 20]
    assert len(got.rows) == 6


def test_the_gross_is_written_and_is_its_own_two_terms() -> None:
    # The file carries three numbers where the evaluator's series carry two.
    # The gross is not redundancy: with it beside the deduction and the net the
    # artifact answers what the signal predicted, what the schedule took and
    # what was left from one read, and a DuckDB scan can subtract the two
    # columns it needs without trusting anything.
    row = _row(D1, "AAA", 0.010, charge=0.0025)
    assert row.gross_return == 0.0125
    table = _read_parquet(encode_signal_returns(_panel(rows=(row,))))
    assert table.column(GROSS_COLUMN).to_pylist() == [0.0125]
    assert table.column(CHARGE_COLUMN).to_pylist() == [0.0025]
    assert table.column(NET_COLUMN).to_pylist() == [0.010]


def test_a_stored_gross_is_checked_against_the_rows_own_terms() -> None:
    # The read side recomputes the net from the file's own gross less its own
    # charge, so a ``gross_return`` edited outside this package fails rather
    # than loading as a plausible-looking lie — the defence the evaluator's own
    # row reader applies to its store's rows, restated for the file.
    body, schema, metadata = _restaged(_panel())
    body[GROSS_COLUMN][1] = body[GROSS_COLUMN][1] + 0.5  # row 1 is (D1, BBB)
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=schema, metadata=metadata),
        campaign_id="c",
        node_id="node_1",
    )
    assert "disagrees with itself" in message
    assert "row 1" in message  # the tampered row, by position
    assert "-0.004" in message  # ... and by the terms it disagrees with


def test_the_write_side_cannot_produce_a_row_its_read_side_refuses() -> None:
    # The two halves of the identity check, and why the record derives the
    # gross instead of accepting one: a caller that typed three decimal
    # literals — 0.011, 0.001, 0.01 — would fail an identity that is true in
    # decimal and false in binary floating point, and the writer would have
    # staged bytes its own reader refuses.  Taking the two numbers the
    # evaluator's series treat as primary removes the trap: whatever a caller
    # hands over, the gross on the file is this layer's own derivation, so the
    # round trip holds for values that do not add exactly in binary.
    row = _row(D1, "AAA", 0.01, charge=0.001)
    assert row.gross_return == 0.001 + 0.01
    panel = _panel(rows=(row,))
    assert decode_signal_returns(
        encode_signal_returns(panel), campaign_id="c", node_id="node_1"
    ).rows == panel.rows


def test_the_identity_is_checked_in_the_one_direction_that_is_exact() -> None:
    # The direction of the identity is part of the contract rather than an
    # implementation detail, so it is pinned.  ``gross`` is the derived value
    # (``charge + net``), so the read side checks ``gross == charge + net`` —
    # and *not* ``gross - charge == net``, which floating point does not
    # guarantee: subtraction is not the inverse of addition for most doubles,
    # so the reversed form would refuse rows this layer's own writer produced
    # from ordinary values.  Both halves of that are asserted, because a later
    # "simplification" to the subtraction form would otherwise pass the row
    # round trip above and fail only on the values nobody happened to test.
    row = _row(D1, "AAA", 0.01, charge=0.001)
    assert row.gross_return == row.charge + row.post_cost_return
    assert (row.gross_return - row.charge) != row.post_cost_return


# -- The canonical row order -------------------------------------------------------


def test_rows_are_sorted_so_a_panel_is_a_fingerprint() -> None:
    # Rows are ordered by (date, horizon, symbol) before they are written, so
    # two equal panels built in different insertion orders stage identical
    # bytes — which is what lets a reader compare a stored grid against the one
    # it is reconstructing, and what makes key order never part of a stored
    # panel's identity.
    rows = (
        _row(D2, "BBB", 0.006, charge=0.002),
        _row(D1, "BBB", -0.004, charge=0.002),
        _row(D2, "AAA", -0.020),
        _row(D1, "AAA", 0.010),
    )
    shuffled = _panel(rows=rows)
    ordered = _panel(rows=tuple(reversed(rows)))

    assert encode_signal_returns(shuffled) == encode_signal_returns(ordered)

    table = _read_parquet(encode_signal_returns(shuffled))
    assert table.column(DATE_COLUMN).to_pylist() == [D1, D1, D2, D2]
    assert table.column(SYMBOL_COLUMN).to_pylist() == ["AAA", "BBB", "AAA", "BBB"]


def test_the_sort_is_by_date_then_horizon_then_symbol() -> None:
    # Three axes, and the order is all three: a panel handed over in any order
    # is read back in the canonical one, and the tie-breaks matter because one
    # date carries every horizon and every symbol.
    rows = (
        _row(D2, "AAA", 0.01, horizon=1),
        _row(D1, "BBB", 0.01, horizon=5),
        _row(D2, "AAA", 0.01, horizon=5),
        _row(D1, "AAA", 0.01, horizon=5),
    )
    table = _read_parquet(encode_signal_returns(_panel(rows=rows)))
    assert list(
        zip(
            table.column(DATE_COLUMN).to_pylist(),
            table.column(HORIZON_COLUMN).to_pylist(),
            table.column(SYMBOL_COLUMN).to_pylist(),
        )
    ) == [
        (D1, 5, "AAA"),
        (D1, 5, "BBB"),
        (D2, 1, "AAA"),
        (D2, 5, "AAA"),
    ]


# -- Inside the node artifact directory (feature 169's write path) -----------------


def test_the_grid_publishes_inside_the_nodes_one_directory(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The feature read literally: the file stages invisibly and the node's one
    # commit publishes it at exactly §9.2's address, keyed campaign then node.
    panel = _panel(node_id=node_id)
    staged = persist_signal_returns(store, campaign_id, node_id, panel)
    assert staged.is_file()  # staged, not published
    assert not store.has_node(campaign_id, node_id)

    published = store.commit(campaign_id, node_id)
    assert published == store.root / campaign_id / node_id
    assert store.files(campaign_id, node_id) == (SIGNAL_RETURNS_FILENAME,)
    assert store.read(campaign_id, node_id, SIGNAL_RETURNS_FILENAME) == (
        encode_signal_returns(panel)
    )


def test_the_grid_sits_beside_the_other_artifact_files(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # One node, one directory, many files: the grid is one line of §9.2's
    # layout, and staging it must not give the node a second directory or
    # displace what another writer staged.
    store.write(campaign_id, node_id, "code.py", b"def signal(): ...\n")
    persist_signal_returns(store, campaign_id, node_id, _panel(node_id=node_id))
    store.commit(campaign_id, node_id)

    assert store.files(campaign_id, node_id) == (
        "code.py",
        SIGNAL_RETURNS_FILENAME,
    )


def test_a_discard_rolls_the_grid_back_with_everything_else(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The staged path's other half: a failure before the commit publishes
    # nothing, so a reader walking the store cannot see a half-written node —
    # and the grid rolls back with every other staged file rather than
    # surviving a retry's failure.
    persist_signal_returns(store, campaign_id, node_id, _panel(node_id=node_id))
    store.discard(campaign_id, node_id)

    assert not store.has_node(campaign_id, node_id)
    assert not signal_returns_is_persisted(store, campaign_id, node_id)


def test_a_refresh_replaces_the_panel_wholesale(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A re-persist is a refresh, not a splice: after staging a second panel the
    # node carries the second one's rows and never the first attempt's beside
    # them — the retry discipline feature 169 states for a directory that is
    # one unit.
    persist_signal_returns(store, campaign_id, node_id, _panel(node_id=node_id))
    store.commit(campaign_id, node_id)

    second = _panel(node_id=node_id, rows=(_row(D3, "AAA", 0.05),))
    persist_signal_returns(store, campaign_id, node_id, second)
    store.commit(campaign_id, node_id)

    got = signal_returns(store, campaign_id, node_id)
    assert got == second
    assert got.rows == second.rows
    assert len(got.rows) == 1


def test_the_two_key_levels_still_key_the_grid(
    store: ArtifactStore,
    campaign_id: str,
    other_campaign_id: str,
    node_id: str,
) -> None:
    # Campaign first, then node — the same address the store's other files are
    # keyed by, so a grid read out of one campaign can never be another's.
    persist_signal_returns(store, campaign_id, node_id, _panel(node_id=node_id))
    persist_signal_returns(
        store, other_campaign_id, node_id, _panel(node_id=node_id)
    )
    store.commit(campaign_id, node_id)
    store.commit(other_campaign_id, node_id)

    assert signal_returns_is_persisted(store, campaign_id, node_id)
    assert signal_returns_is_persisted(store, other_campaign_id, node_id)
    assert signal_returns(store, campaign_id, node_id) == signal_returns(
        store, other_campaign_id, node_id
    )


# -- The invariant: presence, not validity ----------------------------------------


def test_a_node_with_nothing_published_carries_no_panel(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Staged-but-uncommitted is invisible by design, so the invariant answers
    # False — and it is a *fact about the publication*, not about the file's
    # content: a sweep asking whether the key artifact landed asks this.
    persist_signal_returns(store, campaign_id, node_id, _panel(node_id=node_id))
    assert not signal_returns_is_persisted(store, campaign_id, node_id)


def test_a_directory_published_without_the_grid_says_so(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The state a reconciliation sweep exists to find: the node is published
    # but its key artifact is not in it.  That is distinguishable from "the
    # node never persisted", which is why the invariant is asked of the node's
    # directory rather than of the store's contents — and the read refuses by
    # naming the half that is missing.
    store.write(campaign_id, node_id, "code.py", b"pass\n")
    store.commit(campaign_id, node_id)

    assert store.has_node(campaign_id, node_id)
    assert not signal_returns_is_persisted(store, campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError) as caught:
        signal_returns(store, campaign_id, node_id)
    assert "holds no 'signal_returns.parquet'" in str(caught.value)


def test_presence_is_not_validity(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A collection of *unreadable* bytes at the name answers True to the
    # invariant and refuses on the read — deliberately: the sweep that wants to
    # know whether the file landed and the caller that wants the panel are two
    # different questions, and a layer that conflated them would have to decide
    # which failure a sweep should hear about.
    store.write(campaign_id, node_id, SIGNAL_RETURNS_FILENAME, b"not parquet")
    store.commit(campaign_id, node_id)

    assert signal_returns_is_persisted(store, campaign_id, node_id)
    assert _refuse(signal_returns, store, campaign_id, node_id)


# -- The read side's refusals -----------------------------------------------------


def test_a_missing_node_refuses_as_not_found(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A node the store holds no directory for is a fact, not a failure:
    # ArtifactNotFoundError, kept apart from the payload complaints below so a
    # caller can report "unknown node" the way §7.2's route reports its 404.
    with pytest.raises(ArtifactNotFoundError):
        signal_returns(store, campaign_id, node_id)


def test_a_published_node_without_the_grid_refuses_as_not_found(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The other missing half, and the distinction a reconciliation sweep rests
    # on: a node that never persisted stays distinguishable from one published
    # without its grid, because the refusal names which half is absent.
    store.write(campaign_id, node_id, "code.py", b"pass\n")
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactNotFoundError):
        signal_returns(store, campaign_id, node_id)


def test_bytes_that_are_not_parquet_refuse_by_name() -> None:
    # The read side refuses what this member's writer cannot have emitted
    # rather than answering a stand-in, and names the file it was asked for.
    message = _refuse(
        decode_signal_returns,
        b"this is not a parquet file",
        campaign_id="campaign_x",
        node_id="node_x",
    )
    assert "node_x" in message
    assert "campaign_x" in message
    assert "not a Parquet panel" in message


def test_a_file_with_the_wrong_columns_refuses() -> None:
    # A Parquet file that parses but is not this schema — the failure a reader
    # that only checked "is it Parquet" would answer with a panel of the wrong
    # shape.  ``date`` is present and ``horizon`` is the first column the
    # schema requires and the file does not carry.
    buffer = io.BytesIO()
    pa.parquet.write_table(
        pa.Table.from_pydict({"date": [D1], "value": [0.5]}), buffer
    )
    message = _refuse(
        decode_signal_returns, buffer.getvalue(), campaign_id="c", node_id="n"
    )
    assert "no 'horizon' column" in message
    assert "it carries date, value" in message  # names what the file does carry


def test_a_column_of_the_wrong_type_refuses() -> None:
    # The right *names* and the wrong *types*: a ``symbol`` column typed as an
    # integer would decode into keys nothing downstream could join back to the
    # panel, which is why the check is made rather than left to fail later.
    body, schema, metadata = _restaged(_panel())
    body[SYMBOL_COLUMN] = [1, 2, 3, 4]
    retyped = pa.schema(
        [
            pa.field(
                name,
                pa.int32() if name == SYMBOL_COLUMN else schema.field(name).type,
            )
            for name in schema.names
        ]
    )
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=retyped, metadata=metadata),
        campaign_id="c",
        node_id="node_1",
    )
    assert f"{SYMBOL_COLUMN!r} column" in message
    assert "instrument's name" in message


def test_a_null_entry_refuses_naming_the_row() -> None:
    # A Parquet column carries nulls whatever its type, so presence is checked
    # on its own — and the refusal names the row it sits on, because a grid is
    # a hundred thousand rows and "a value is absent" without a handle on the
    # row is not findable.
    body, schema, metadata = _restaged(_panel())
    body[CHARGE_COLUMN][1] = None
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=schema, metadata=metadata),
        campaign_id="c",
        node_id="node_1",
    )
    assert "row 1" in message
    assert "null charge" in message


def test_a_non_finite_return_refuses_naming_the_row() -> None:
    # nan and inf are what a correlation produces over a constant
    # cross-section: a measurement a reader would trust and be wrong by.  The
    # writer refuses them and so does the reader, on the same reasoning — a
    # series that could not be read back is never written down.
    body, schema, metadata = _restaged(_panel())
    body[NET_COLUMN][0] = float("nan")
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=schema, metadata=metadata),
        campaign_id="c",
        node_id="node_1",
    )
    assert "row 0" in message
    assert "non-finite" in message


def test_a_duplicate_cell_refuses() -> None:
    # A grid addresses one measurement per (date, horizon, symbol), so a file
    # carrying two rows in one cell would collapse to whichever was read last —
    # a number nobody wrote.  The write side refuses the same panel (below),
    # which is why such a file is one this member never staged.
    body, schema, metadata = _restaged(_panel())
    for column in body:
        body[column] = body[column] + [body[column][0]]
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=schema, metadata=metadata),
        campaign_id="c",
        node_id="node_1",
    )
    assert D1.isoformat() in message
    assert "twice" in message


def test_a_file_naming_another_node_refuses() -> None:
    # The node's identity rides in the metadata, so the read side *can* check
    # it against the directory the bytes came from rather than assuming it —
    # and a grid filed under a node it does not measure is a misfiling every
    # later reader, replay recomputing marginal contribution above all, would
    # join to the wrong signal.
    payload = encode_signal_returns(_panel(node_id="node_1"))
    message = _refuse(
        decode_signal_returns, payload, campaign_id="c", node_id="node_2"
    )
    assert "'node_1'" in message
    assert "'node_2'" in message


def test_a_file_without_its_identity_metadata_refuses() -> None:
    # The panel's identity is metadata and only metadata, so a file without it
    # is one this member's writer never staged: a panel that cannot say which
    # sealed world it was measured in is one no other panel can be compared
    # against.  The node entry is checked first because it is the one the
    # reader can hold against something it already knows.
    body, schema, _ = _restaged(_panel())
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=schema, metadata=None),
        campaign_id="c",
        node_id="node_1",
    )
    assert "names no node" in message
    assert "schema's metadata" in message


def test_a_file_missing_only_its_snapshot_refuses() -> None:
    # The same refusal for one entry rather than all four: the metadata is the
    # panel's identity and every term of it is required — a panel priced in an
    # unnamed world is one no second panel can be compared against, which is
    # exactly the comparison marginal contribution is.
    body, schema, metadata = _restaged(_panel())
    stripped = {key: value for key, value in metadata.items() if key != b"snapshot_name"}
    message = _refuse(
        decode_signal_returns,
        _stage(body, schema=schema, metadata=stripped),
        campaign_id="c",
        node_id="node_1",
    )
    assert "names no sealed snapshot" in message


def test_an_empty_parquet_file_refuses() -> None:
    # The reader refuses a zero-row file rather than answering an empty panel:
    # a grid with no measurements priced nothing at all, and the writer refuses
    # the same value, so such a file is one this member never staged.
    _, schema, metadata = _restaged(_panel())
    empty = {name: [] for name in schema.names}
    message = _refuse(
        decode_signal_returns,
        _stage(empty, schema=schema, metadata=metadata),
        campaign_id="c",
        node_id="node_1",
    )
    assert "cannot be an empty panel" in message


# -- The write side's refusals, all before the first staged byte -------------------


def test_a_value_that_is_not_a_panel_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The codec's argument is the grid itself; anything else carries no rows.
    # Both spellings are refused — the operation's and the codec's — because
    # the codec is a public seam a caller can reach without the store.
    message = _refuse(
        persist_signal_returns, store, campaign_id, node_id, {"rows": []}
    )
    assert "SignalReturns" in message
    assert "SignalReturns" in _refuse(encode_signal_returns, {"rows": []})


def test_a_panel_filed_under_another_nodes_key_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The panel names the node it measures and the directory names the node it
    # is filed under; the two must agree, because a grid filed under a node it
    # does not measure is provenance the store cannot repair.
    message = _refuse(
        persist_signal_returns,
        store,
        campaign_id,
        node_id,
        _panel(node_id="someone_else"),
    )
    assert "'someone_else'" in message
    assert node_id in message
    # And nothing was staged: the refusal lands before the first byte.
    assert not store.has_node(campaign_id, node_id)
    assert store.staged(campaign_id, node_id) == ()


def test_an_empty_panel_refuses() -> None:
    # A grid with no rows priced nothing — the evaluator refuses the same value
    # one step earlier, which makes an empty grid a document this step's writer
    # never produced rather than a sparse measurement to persist honestly.
    message = _refuse(
        SignalReturns,
        node_id="n",
        snapshot_name=SNAPSHOT,
        venue=VENUE,
        version=VERSION,
        rows=(),
    )
    assert "cannot be an empty panel" in message


def test_a_short_identity_refuses() -> None:
    # A panel names the node, the snapshot and the cost model its rows belong
    # to; one missing any of the three cannot say what it is a panel of.
    for field in ("node_id", "snapshot_name", "venue", "version"):
        kwargs = {
            "node_id": "n",
            "snapshot_name": SNAPSHOT,
            "venue": VENUE,
            "version": VERSION,
            "rows": (_row(D1, "AAA", 0.01),),
        }
        kwargs[field] = "  "
        message = _refuse(SignalReturns, **kwargs)
        assert field.replace("_", " ") in message


def test_a_row_of_the_wrong_type_refuses() -> None:
    # The rows are ReturnRow values: a mapping with the right keys is not a
    # return, and the refusal names the position it sits at.
    message = _refuse(
        SignalReturns,
        node_id="n",
        snapshot_name=SNAPSHOT,
        venue=VENUE,
        version=VERSION,
        rows=({"symbol": "AAA"},),
    )
    assert "position 0" in message


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        pytest.param(
            {"horizon": True},
            "integer period count",
            id="a-bool-is-not-a-horizon",
        ),
        pytest.param(
            {"horizon": 1.5},
            "integer period count",
            id="a-float-is-not-a-horizon",
        ),
        pytest.param(
            {"horizon": 0},
            "positive period count",
            id="zero-periods-measure-nothing-forward",
        ),
        pytest.param(
            {"horizon": -5},
            "positive period count",
            id="a-negative-horizon-is-not-a-horizon",
        ),
        pytest.param(
            {"symbol": ""},
            "instrument's name",
            id="an-empty-symbol-is-not-an-instrument",
        ),
        pytest.param(
            {"symbol": 7},
            "instrument's name",
            id="an-int-symbol-would-not-join-back",
        ),
        pytest.param(
            {"charge": True},
            "charge",
            id="a-bool-is-not-a-charge",
        ),
        pytest.param(
            {"charge": float("inf")},
            "non-finite charge",
            id="inf-is-not-a-measurement",
        ),
        pytest.param(
            {"post_cost_return": float("nan")},
            "non-finite post-cost return",
            id="nan-is-not-a-measurement",
        ),
        pytest.param(
            {"post_cost_return": "0.01"},
            "post-cost return",
            id="text-is-not-a-number",
        ),
    ],
)
def test_a_malformed_row_refuses(kwargs: dict, expected: str) -> None:
    # Every value the grid's columns cannot hold, refused by name — the layer's
    # own validation, before a byte is produced.
    fields = {
        "rebalance_date": D1,
        "symbol": "AAA",
        "charge": 0.001,
        "post_cost_return": 0.01,
        **kwargs,
    }
    message = _refuse(
        ReturnRow,
        rebalance_date=fields["rebalance_date"],
        horizon=fields.get("horizon", 1),
        symbol=fields["symbol"],
        charge=fields["charge"],
        post_cost_return=fields["post_cost_return"],
    )
    assert expected in message


def test_a_refusal_names_the_row_it_is_about() -> None:
    # The row's own address — symbol, date, horizon — is in the message, so a
    # malformed row of a panel of a hundred thousand is findable.  (The symbol
    # refusal alone cannot name it: the symbol is the value being refused.)
    message = _refuse(
        ReturnRow,
        rebalance_date=D1,
        horizon=5,
        symbol="AAA",
        charge=0.001,
        post_cost_return=float("inf"),
    )
    assert "'AAA'" in message
    assert D1.isoformat() in message
    assert "horizon 5" in message


def test_a_datetime_key_refuses_by_name() -> None:
    # A datetime *is* a date in Python and would pass a naive isinstance check,
    # but a grid keyed by instants cannot be joined against one keyed by dates
    # — and the rebalance grid the returns were taken on is made of dates.
    #
    # The naive datetime is the fixture, not an oversight: this layer refuses a
    # datetime key whatever its tzinfo, and a tz-aware one would leave "is it
    # the naive case only?" untested — so the linter's tz-awareness rule, which
    # is aimed at datetimes a caller constructs to *use*, is waived here.
    message = _refuse(
        ReturnRow,
        rebalance_date=dt.datetime(2026, 1, 5, 9, 30),  # noqa: DTZ001
        horizon=1,
        symbol="AAA",
        charge=0.001,
        post_cost_return=0.01,
    )
    assert "datetime" in message


def test_iso_date_text_is_accepted_as_the_same_date() -> None:
    # Both spellings a caller answers with land here — the evaluator's records
    # key their series by calendar dates while its *stored rows* are read back
    # as ISO text — and the normalized value is the calendar date, so a panel
    # built either way stages the same bytes.
    text = _row("2026-01-05", "AAA", 0.01)  # type: ignore[arg-type]
    date = _row(D1, "AAA", 0.01)
    assert text == date
    assert text.rebalance_date == D1
    assert encode_signal_returns(_panel(rows=(text,))) == encode_signal_returns(
        _panel(rows=(date,))
    )


def test_a_date_that_is_not_a_date_refuses() -> None:
    # An int, a None, a spelled-out date — none is a rebalance.
    for value in (20260105, None, "5 January 2026"):
        message = _refuse(
            ReturnRow,
            rebalance_date=value,
            horizon=1,
            symbol="AAA",
            charge=0.001,
            post_cost_return=0.01,
        )
        assert "calendar date" in message


def test_a_duplicate_cell_in_a_panel_refuses() -> None:
    # The writer's own duplicate check, and the reason it exists: this layer's
    # *reader* refuses a duplicate cell, so accepting one would mean the writer
    # could produce bytes it cannot read back.  Both positions are named so the
    # collision is findable in a panel of thousands of rows.
    message = _refuse(
        SignalReturns,
        node_id="n",
        snapshot_name=SNAPSHOT,
        venue=VENUE,
        version=VERSION,
        rows=(
            _row(D1, "AAA", 0.01),
            _row(D2, "AAA", 0.01),
            _row(D1, "AAA", 0.02),
        ),
    )
    assert "twice" in message
    assert "positions 0 and 2" in message


def test_a_malformed_key_refuses_as_a_key_failure(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The two-segment key is the layout (feature 169) and it outranks
    # everything staged through it: a bad key refuses as a key failure rather
    # than as a payload complaint, and names the address that broke.
    with pytest.raises(ArtifactKeyError):
        persist_signal_returns(store, campaign_id, "a/b", _panel(node_id="a/b"))
    with pytest.raises(ArtifactKeyError):
        persist_signal_returns(store, ".staging", node_id, _panel(node_id=node_id))


def test_a_key_failure_refuses_before_the_panel_is_even_looked_at(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Ordering, pinned: a key that cannot serve as a path segment is refused
    # before the payload is examined, so the refusal a caller gets names the
    # key rather than whatever was wrong with a panel it never should have
    # built.
    with pytest.raises(ArtifactKeyError):
        persist_signal_returns(store, campaign_id, "", {"not": "a panel"})


# -- The layering note: pyarrow is not a composition cost ---------------------------


def test_importing_the_package_does_not_import_pyarrow() -> None:
    # This member is imported by the application factory's workspace scan, so a
    # module-scope ``import pyarrow`` anywhere in the package would make
    # pyarrow a precondition for *composing the application* — a much larger
    # blast radius than this file needs, since feature 169's keying, write path
    # and read side need no Arrow at all and neither does the JSON half of this
    # category.
    #
    # Asserted in a subprocess, because this suite's own imports have already
    # loaded pyarrow into this interpreter.  PYTHONPATH is set from the repo
    # layout rather than inherited, so the check does not depend on the
    # workspace member having been installed into the venv — the seam under
    # test is exactly the one that must survive a bare ``uv run``.
    script = (
        "import sys; import artifacts, artifacts._returns, artifacts._series;"
        "assert 'pyarrow' not in sys.modules, 'pyarrow imported at module scope';"
        "print('deferred')"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO_ROOT / "src"),
                str(REPO_ROOT / "packages" / "artifacts" / "src"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "deferred"


def test_this_module_has_one_deferred_arrow_seam_too() -> None:
    # The other half of the same contract: within ``artifacts._returns``,
    # ``require_arrow`` is the one function that imports pyarrow, so the
    # deferral is a seam rather than a coincidence of which submodules happen
    # to be imported.  Read as AST rather than as text, because the import
    # under test is *indented* (it sits inside ``require_arrow``'s ``try``) —
    # a textual search for a column-zero import would find nothing and pass for
    # the wrong reason.
    import artifacts._returns as returns_module

    def imports_pyarrow(node: ast.stmt) -> bool:
        """Whether this statement imports pyarrow, by either import form."""
        if isinstance(node, ast.Import):
            return any(
                alias.name == "pyarrow" or alias.name.startswith("pyarrow.")
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom):
            return (node.module or "").startswith("pyarrow")
        return False

    tree = ast.parse(Path(returns_module.__file__).read_text())
    assert [node for node in tree.body if imports_pyarrow(node)] == [], (
        "pyarrow is imported at module scope, which makes it a precondition "
        "for composing the application"
    )
    importers = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(imports_pyarrow(inner) for inner in ast.walk(node))
    ]
    assert importers == ["require_arrow"]
