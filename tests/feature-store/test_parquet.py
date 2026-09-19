"""Feature 49's format: a feature's stamped rows as Parquet bytes.

app_spec.xml feature 49 materializes a feature to Parquet; §4.1's stack table
pins the encoding ("Parquet + Zstd, columnar, compressed, portable").  These
tests cover the codec — the row-to-columnar bridge and back — which is the
half of the feature that can be proven without a lake.  The lazy-compute and
persist-and-reuse half is ``test_materialise.py``.

The PyArrow suite's shape is followed here deliberately (``tests/contract/
test_payload.py``): pyarrow is a declared dependency of this member, so under
the canonical invocation (``uv run --all-packages pytest``, which is what the
acceptance gate runs) it is always present, and the guard below keeps a
*partially installed* environment from turning a missing wheel into a
collection error that takes the whole repository suite down with it.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest

pytest.importorskip(
    "pyarrow",
    reason="the Parquet materialisation suite requires pyarrow (a declared dependency)",
)

import pyarrow as pa  # noqa: E402

from feature_store import (  # noqa: E402
    COMPUTED_AS_OF_FIELD,
    FeatureRow,
    ParquetMaterialisationError,
    decode_parquet,
    encode_parquet,
    from_table,
    stamp_rows,
    to_table,
)

T = dt.datetime(2026, 9, 1, 12, 0, 0, 123456, tzinfo=dt.timezone.utc)


def rows_for(*values: dict, computed_as_of: dt.datetime = T) -> tuple[FeatureRow, ...]:
    return stamp_rows(list(values), computed_as_of=computed_as_of)


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


def test_a_rectangular_batch_round_trips_exactly() -> None:
    rows = rows_for({"ret": 0.5, "n": 3, "sym": "BTC"}, {"ret": 0.25, "n": 4, "sym": "ETH"})
    assert decode_parquet(encode_parquet(rows)) == rows


def test_the_stamp_survives_the_round_trip_at_microsecond_resolution() -> None:
    # The stamp is the column every point-in-time question reads, so it is the
    # one that must not drift: microseconds preserved, offset preserved.
    rows = rows_for({"a": 1})
    (back,) = decode_parquet(encode_parquet(rows))
    assert back.computed_as_of == T
    assert back.computed_as_of.tzinfo is not None
    assert back.computed_as_of.utcoffset() == dt.timedelta(0)


def test_an_aware_stamp_in_another_offset_round_trips_as_the_same_instant() -> None:
    # Feature 51 normalises to UTC at construction, so what is written is UTC
    # regardless of the offset the caller named — the instant is what travels.
    other = dt.timezone(dt.timedelta(hours=5, minutes=30))
    rows = rows_for({"a": 1}, computed_as_of=T.astimezone(other))
    (back,) = decode_parquet(encode_parquet(rows))
    assert back.computed_as_of == T


def test_the_encoding_is_deterministic() -> None:
    # The replay path compares payloads byte for byte, and §4.4's cache is
    # addressed by the key alone — so the same rows must always encode to the
    # same bytes or a cached materialisation and a fresh one would differ.
    rows = rows_for({"ret": 0.5}, {"ret": float("nan")})
    assert encode_parquet(rows) == encode_parquet(rows)


def test_row_order_is_preserved() -> None:
    # A series is not a set (feature 51's ordering discipline): sorting the
    # rows away would change what the feature computed.
    rows = rows_for({"i": 3}, {"i": 1}, {"i": 2})
    back = decode_parquet(encode_parquet(rows))
    assert [row.values["i"] for row in back] == [3, 1, 2]


def test_the_output_is_a_zstd_parquet_file() -> None:
    # §4.1's encoding, checked against the format itself rather than the call:
    # the PAR1 frame, and Zstd named in the metadata.
    payload = encode_parquet(rows_for({"a": 1}))
    assert payload[:4] == b"PAR1"
    assert payload[-4:] == b"PAR1"
    metadata = pa.parquet.read_metadata(pa.BufferReader(payload))
    assert metadata.row_group(0).column(0).compression == "ZSTD"


def test_the_stamp_column_is_a_utc_timestamp_in_the_file() -> None:
    # Not incidental: a point-in-time query can only push `computed_as_of <= t`
    # down into the column reader if the column is a real typed timestamp.
    payload = encode_parquet(rows_for({"a": 1}))
    table = pa.parquet.read_table(pa.BufferReader(payload))
    field = table.schema.field(COMPUTED_AS_OF_FIELD)
    assert pa.types.is_timestamp(field.type)
    assert field.type.tz == "UTC"
    assert field.type.unit == "us"


# ---------------------------------------------------------------------------
# Rows whose values are awkward
# ---------------------------------------------------------------------------


def test_an_empty_batch_round_trips_to_an_empty_batch() -> None:
    # A feature computed over an empty window has no rows — a stored feature
    # like any other (feature 48), not a missing one.
    rows = rows_for()
    assert decode_parquet(encode_parquet(rows)) == ()


def test_an_empty_batch_keeps_a_readable_stamp_column() -> None:
    # The pin that earns its keep: with no rows to infer from, an unpinned
    # writer types the stamp column as `null`, and from_table refuses a stamp
    # column that is not a timezone-aware timestamp — so an empty feature would
    # materialise to a file this module's own reader could not read back.
    payload = encode_parquet(rows_for())
    field = pa.parquet.read_table(pa.BufferReader(payload)).schema.field(
        COMPUTED_AS_OF_FIELD
    )
    assert pa.types.is_timestamp(field.type)
    assert field.type.tz == "UTC"
    # And the reader agrees, rather than the assertion being the only witness.
    assert decode_parquet(payload) == ()


def test_an_all_none_column_round_trips_its_nulls() -> None:
    # A column whose values are all None carries no type information at all,
    # so Arrow writes it as a null column.  The ROWS are still preserved
    # exactly — None in, None out — which is what the codec owes; the type of
    # a column that never held a value is not information the row layer has
    # (feature 51 keeps values untyped), so it is not invented here.
    rows = rows_for({"a": None}, {"a": None})
    back = decode_parquet(encode_parquet(rows))
    assert back == rows
    assert [row.values["a"] for row in back] == [None, None]


def test_rows_with_no_values_at_all_round_trip() -> None:
    rows = rows_for({}, {})
    assert decode_parquet(encode_parquet(rows)) == rows


def test_a_nan_value_survives_as_a_nan() -> None:
    # Feature 51: "nan is representable and legal" — an unscored cell is not an
    # absent one, and Parquet must preserve it rather than null it out.
    (back,) = decode_parquet(encode_parquet(rows_for({"a": float("nan")})))
    assert math.isnan(back.values["a"])


def test_a_mixed_int_and_float_column_widens_to_double() -> None:
    # Inference runs over the whole column, so the widest value decides the
    # type instead of the first one met.
    rows = rows_for({"a": 1}, {"a": 2.5})
    back = decode_parquet(encode_parquet(rows))
    assert [row.values["a"] for row in back] == [1.0, 2.5]


def test_nested_values_round_trip() -> None:
    rows = rows_for({"a": [1, 2]}, {"a": [3]})
    assert decode_parquet(encode_parquet(rows)) == rows


def test_unicode_values_round_trip() -> None:
    rows = rows_for({"sym": "日本語"}, {"sym": "x"})
    assert decode_parquet(encode_parquet(rows)) == rows


def test_a_ragged_batch_is_normalized_absence_becomes_null() -> None:
    # Parquet is rectangular by definition, so an omitted column is written as
    # a null in a column that exists.  The law is stated in to_table's
    # docstring; this pins it, because a reader relying on "omitted stays
    # omitted" would be surprised.
    rows = rows_for({"a": 1}, {"b": 2})
    back = decode_parquet(encode_parquet(rows))
    assert [row.values for row in back] == [
        {"a": 1, "b": None},
        {"a": None, "b": 2},
    ]
    # And every row still carries its stamp.
    assert all(row.computed_as_of == T for row in back)
    # The column set is the union, not the intersection: the column only the
    # second row carries is present rather than dropped.
    assert back[0].column_names() == ("a", "b")


def test_a_feature_style_payload_of_many_rows_round_trips() -> None:
    # The realistic shape: a cross-section of 500 symbols with some unscored.
    # Compared field by field rather than with ``==`` on the rows, because a
    # ``NaN`` return is unequal to itself in Python — that is a property of
    # ``NaN``, not a difference the round trip introduced, and the point here
    # is that 500 rows survive intact.
    values = [
        {
            "symbol": f"SYM{i}",
            "close": 100.0 + i,
            "ret": float("nan") if i % 7 == 0 else i / 100,
        }
        for i in range(500)
    ]
    rows = rows_for(*values)
    back = decode_parquet(encode_parquet(rows))
    assert len(back) == len(rows)
    for original, restored in zip(rows, back):
        assert restored.computed_as_of == original.computed_as_of
        assert restored.column_names() == original.column_names()
        for name in original.column_names():
            before, after = original.values[name], restored.values[name]
            if isinstance(before, float) and math.isnan(before):
                assert math.isnan(after)
            else:
                assert after == before


def test_an_unscored_nan_and_an_absent_value_stay_distinguishable() -> None:
    # Feature 51's distinction, carried into the file: NaN is a value the
    # definition computed and could not score; None is a value it did not
    # have.  A codec that conflated them would erase the difference silently.
    rows = rows_for({"a": float("nan"), "b": None}, {"a": 1.0, "b": 2.0})
    first, second = decode_parquet(encode_parquet(rows))
    assert math.isnan(first.values["a"])
    assert first.values["b"] is None
    assert second.values["a"] == 1.0
    assert second.values["b"] == 2.0


# ---------------------------------------------------------------------------
# Refusals: values Parquet cannot carry
# ---------------------------------------------------------------------------


def test_a_heterogeneous_column_is_refused_naming_the_column() -> None:
    # Arrow is a wider type system than JSON, but a column has ONE type for
    # every row — so a bool beside a number has no Parquet representation, and
    # the refusal names the column rather than leaking Arrow's own error.
    rows = rows_for({"a": 1}, {"a": True})
    with pytest.raises(ParquetMaterialisationError, match="'a'"):
        encode_parquet(rows)


def test_an_integer_past_int64_is_refused_naming_the_column() -> None:
    rows = rows_for({"a": 2**70})
    with pytest.raises(ParquetMaterialisationError, match="'a'"):
        encode_parquet(rows)


def test_a_non_row_in_the_batch_is_refused_naming_its_index() -> None:
    with pytest.raises(ParquetMaterialisationError, match="row 1 .*FeatureRow"):
        to_table([rows_for({"a": 1})[0], {"a": 2}])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Refusals: bytes that are not a materialised feature
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"",  # feature 48 blesses empty payloads as "no rows", but these
        # bytes were never a Parquet file — the row layer's no-rows
        # representation is an empty batch, a real zero-row file.
        b"not parquet at all",
        b"PAR1truncated",
    ],
    ids=["empty", "text", "truncated-frame"],
)
def test_bytes_that_are_not_parquet_are_refused(payload: bytes) -> None:
    with pytest.raises(ParquetMaterialisationError, match="not a Parquet"):
        decode_parquet(payload)


def test_a_table_without_a_stamp_column_is_refused() -> None:
    # A file this module wrote always carries the stamp; one that does not is
    # not a feature's rows, and reading it would hand feature 52 rows whose
    # stamps cannot be compared.
    with pytest.raises(ParquetMaterialisationError, match=COMPUTED_AS_OF_FIELD):
        from_table(pa.table({"a": [1]}))


def test_a_naive_stamp_column_is_refused() -> None:
    # The offset is what makes `<=` well-defined at read time (feature 52), so
    # a stamp column without one is refused at the boundary rather than
    # detonating inside a point-in-time query.
    table = pa.table(
        {COMPUTED_AS_OF_FIELD: pa.array([T.replace(tzinfo=None)], pa.timestamp("us"))}
    )
    with pytest.raises(ParquetMaterialisationError, match="timezone-aware"):
        from_table(table)


def test_a_null_stamp_is_refused_naming_the_row() -> None:
    table = pa.table(
        {COMPUTED_AS_OF_FIELD: pa.array([None], pa.timestamp("us", tz="UTC"))}
    )
    with pytest.raises(ParquetMaterialisationError, match="null"):
        from_table(table)


# ---------------------------------------------------------------------------
# The Arrow bridge itself
# ---------------------------------------------------------------------------


def test_to_table_and_from_table_are_inverses_for_a_rectangular_batch() -> None:
    rows = rows_for({"a": 1, "b": "x"}, {"a": 2, "b": "y"})
    assert from_table(to_table(rows)) == rows


def test_to_table_pins_the_stamp_first() -> None:
    # A reader scanning the file meets the point-in-time column before the
    # values it gates.
    assert to_table(rows_for({"a": 1})).schema.names[0] == COMPUTED_AS_OF_FIELD


def test_the_column_set_is_the_union_across_rows_sorted() -> None:
    # Deterministic schema — so the bytes do not depend on row order — and the
    # union, so a column only some rows carry is not silently dropped.
    assert to_table(rows_for({"b": 1}, {"a": 2})).schema.names == [
        COMPUTED_AS_OF_FIELD,
        "a",
        "b",
    ]
