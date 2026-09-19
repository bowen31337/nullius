"""Feature 51's stamping contract: every feature row carries ``computed_as_of``.

app_spec.xml feature 51: *System stamps every feature row with
computed_as_of at write time.*  docs/nullius-tech-architecture.md §4.4 gives
the reason the stamp exists — "every row carries ``computed_as_of``, and a
query at ``t`` may only return rows with ``computed_as_of <= t``" — and
feature 52 is that read filter.  This suite pins only the *write* half:
feature 51.

The tests are organised around the three claims the sentence makes:

* **every row** — a batch is stamped row by row, not just its first row;
* **with ``computed_as_of``** — the field is named, validated, and reads back
  as what was written rather than as whatever the clock says later;
* **at write time** — the instant is fixed when the rows are written, and
  *one* instant serves the whole batch, so a query can never catch half a
  write.

Feature 52 is deliberately not exercised here; the rows this suite produces
are what it will filter.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import FrozenInstanceError

import pytest

from feature_store import (
    COMPUTED_AS_OF_FIELD,
    FeatureKey,
    FeatureRecord,
    FeatureRow,
    FeatureRowError,
    FeatureStore,
    decode_rows,
    encode_rows,
    stamp_rows,
    utc_now,
)

UTC = dt.timezone.utc

#: A fixed instant, so the tests name a stamp rather than observe one.
INSTANT = dt.datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


def make_clock(*instants: dt.datetime):
    """A clock callable that returns each instant once, then keeps the last.

    Recording each call is what lets a test prove *how many times* the clock
    was read — the difference between one stamp per write and one per row.
    """
    remaining = list(instants)
    calls: list[int] = []

    def clock() -> dt.datetime:
        calls.append(len(calls))
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    # ``calls`` is exposed on the function so a test can assert the read count.
    clock.calls = calls  # type: ignore[attr-defined]
    return clock


def make_values(count: int = 3) -> list[dict[str, object]]:
    return [{"symbol": f"S{i}", "close": 100.0 + i} for i in range(count)]


# ---------------------------------------------------------------------------
# Every row, stamped
# ---------------------------------------------------------------------------


def test_stamp_rows_stamps_every_row_in_the_batch() -> None:
    # The first word of feature 51 is "every": a batch of rows is stamped row
    # by row, not merely given a stamp somewhere it can be found.
    rows = stamp_rows(make_values(3), computed_as_of=INSTANT)
    assert len(rows) == 3
    for row in rows:
        assert isinstance(row, FeatureRow)
        assert row.computed_as_of == INSTANT


def test_an_empty_batch_is_a_legal_write() -> None:
    # A feature computed over an empty window has no rows; that is a write
    # like any other, and it stamps nothing rather than failing.
    assert stamp_rows([], computed_as_of=INSTANT) == ()


def test_the_stamp_is_readable_under_its_spec_name() -> None:
    # §4.4 names the field computed_as_of; the row carries it under exactly
    # that name so the spec word and the code word cannot drift.
    row = stamp_rows([{"close": 1.0}], computed_as_of=INSTANT)[0]
    assert COMPUTED_AS_OF_FIELD == "computed_as_of"
    assert getattr(row, COMPUTED_AS_OF_FIELD) == INSTANT


def test_row_values_are_carried_verbatim() -> None:
    rows = stamp_rows([{"symbol": "BTCUSDT", "close": 42.5}], computed_as_of=INSTANT)
    assert rows[0].value("symbol") == "BTCUSDT"
    assert rows[0].value("close") == 42.5
    # An absent column is a normal miss, like a key the store does not hold.
    assert rows[0].value("volume") is None


def test_stamped_rows_keep_their_input_order() -> None:
    # A feature's row order is part of what it computed — a series is not a
    # set — so stamping must not sort it away.
    rows = stamp_rows(make_values(4), computed_as_of=INSTANT)
    assert [row.value("symbol") for row in rows] == ["S0", "S1", "S2", "S3"]


# ---------------------------------------------------------------------------
# At write time: one instant per write
# ---------------------------------------------------------------------------


def test_every_row_in_a_batch_carries_the_identical_stamp() -> None:
    # The heart of "at write time": the clock is read ONCE, so a batch that
    # would have straddled a tick still carries a single instant.  The clock
    # here advances on every call, so a per-row read is visible as two
    # different stamps — and would let a <= t query return half a write.
    clock = make_clock(
        dt.datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC),
        dt.datetime(2026, 4, 30, 12, 0, 1, tzinfo=UTC),
        dt.datetime(2026, 4, 30, 12, 0, 2, tzinfo=UTC),
    )
    rows = stamp_rows(make_values(3), clock=clock)
    stamps = {row.computed_as_of for row in rows}
    assert len(stamps) == 1
    assert len(clock.calls) == 1  # read once, for the whole batch


def test_the_clock_is_not_consulted_when_the_stamp_is_given() -> None:
    # A backfill or a replay names the instant it is reproducing; the wall
    # clock must not leak into that write.
    def exploding_clock() -> dt.datetime:
        raise AssertionError("the clock must not be read when a stamp is given")

    rows = stamp_rows(make_values(2), computed_as_of=INSTANT, clock=exploding_clock)
    assert all(row.computed_as_of == INSTANT for row in rows)


def test_an_explicit_stamp_is_honoured_verbatim() -> None:
    # A backfill stamps the historical instant it is backfilling, not now.
    historical = dt.datetime(2021, 1, 1, tzinfo=UTC)
    rows = stamp_rows(make_values(2), computed_as_of=historical)
    assert all(row.computed_as_of == historical for row in rows)


def test_the_default_clock_stamps_the_current_instant() -> None:
    before = utc_now()
    rows = stamp_rows(make_values(1))
    after = utc_now()
    stamp = rows[0].computed_as_of
    assert before <= stamp <= after
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == dt.timedelta(0)


def test_utc_now_is_timezone_aware_and_second_resolved() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(0)
    assert now.microsecond == 0


def test_the_stamp_persists_across_reads_rather_than_being_restamped() -> None:
    # "At write time" is a claim about *when* the value is fixed: reading a
    # row back returns the instant that was written, never the instant of the
    # read.  A row whose stamp moved on every access could not be compared
    # against a query time at all.
    rows = stamp_rows(make_values(1), computed_as_of=INSTANT)
    assert rows[0].computed_as_of == rows[0].computed_as_of == INSTANT


def test_a_non_callable_clock_is_refused() -> None:
    with pytest.raises(FeatureRowError, match="clock must be callable"):
        stamp_rows(make_values(1), clock="not callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stamp validation
# ---------------------------------------------------------------------------


def test_a_naive_stamp_is_refused_at_write_time() -> None:
    # Feature 52 compares the stamp with <=; a naive datetime compared against
    # an aware one raises TypeError.  Refusing it here puts the failure on the
    # write that could name the missing offset, not deep inside a later query.
    with pytest.raises(FeatureRowError, match="timezone-aware"):
        stamp_rows(make_values(1), computed_as_of=dt.datetime(2026, 4, 30, 12, 0, 0))


def test_a_naive_stamp_from_the_clock_is_refused_too() -> None:
    def naive_clock() -> dt.datetime:
        return dt.datetime(2026, 4, 30, 12, 0, 0)

    with pytest.raises(FeatureRowError, match="timezone-aware"):
        stamp_rows(make_values(1), clock=naive_clock)


def test_a_row_constructed_directly_rejects_a_naive_stamp() -> None:
    with pytest.raises(FeatureRowError, match="timezone-aware"):
        FeatureRow(computed_as_of=dt.datetime(2026, 4, 30), values={})


def test_a_non_datetime_stamp_is_refused() -> None:
    # A string that *looks* like an instant is still not one: the stamp is a
    # datetime, and parsing a string into one is the caller's decision (it
    # might name a naive instant, which is refused below).
    for bad in ("2026-04-30T12:00:00+00:00", 0, 1.0):
        with pytest.raises(FeatureRowError, match="must be a datetime"):
            stamp_rows(make_values(1), computed_as_of=bad)  # type: ignore[arg-type]


def test_none_means_use_the_clock_rather_than_being_a_stamp() -> None:
    # computed_as_of=None is the "no explicit stamp given" sentinel, so the
    # clock supplies the instant — it is not an attempt to stamp with None.
    rows = stamp_rows(make_values(1), computed_as_of=None, clock=lambda: INSTANT)
    assert rows[0].computed_as_of == INSTANT


def test_an_offset_stamp_is_normalised_to_utc_not_rejected() -> None:
    # An aware instant in another offset names the same moment, so it is
    # canonicalised rather than refused — only the *unaware* instant is a bug.
    # Canonicalisation is what makes <= well-defined regardless of who wrote.
    offset = dt.timezone(dt.timedelta(hours=10))
    stamp = dt.datetime(2026, 5, 1, 8, 0, 0, tzinfo=offset)  # = 2026-04-30T22:00Z
    row = stamp_rows([{}], computed_as_of=stamp)[0]
    assert row.computed_as_of == dt.datetime(2026, 4, 30, 22, 0, 0, tzinfo=UTC)
    assert row.computed_as_of.utcoffset() == dt.timedelta(0)


def test_values_must_be_a_mapping() -> None:
    with pytest.raises(FeatureRowError, match="mapping of column name"):
        stamp_rows([("symbol", "BTCUSDT")], computed_as_of=INSTANT)  # type: ignore[list-item]


def test_a_single_row_mapping_is_refused_with_a_usable_message() -> None:
    # A natural misuse: "here are the columns".  Without this, the mapping
    # iterates as its *keys* and the caller is told a str must be a mapping —
    # a message that names the wrong thing, since they did pass one.
    with pytest.raises(FeatureRowError, match="Pass a list"):
        stamp_rows({"symbol": "BTCUSDT"}, computed_as_of=INSTANT)  # type: ignore[arg-type]


def test_a_single_empty_mapping_does_not_silently_stamp_nothing() -> None:
    # The dangerous version of the same misuse: an empty dict iterates as
    # nothing, so "one row with no columns" would silently become zero rows —
    # a write that looks accepted and stores no data.
    with pytest.raises(FeatureRowError, match="Pass a list"):
        stamp_rows({}, computed_as_of=INSTANT)  # type: ignore[arg-type]


def test_column_names_must_be_valid_names() -> None:
    # Column names double as payload keys and, once feature 49 materialises,
    # as Parquet column names — so they follow feature 48's key-component rule.
    for bad in ("", "  padded  ", "a/b", "."):
        with pytest.raises(FeatureRowError, match="column name"):
            stamp_rows([{bad: 1.0}], computed_as_of=INSTANT)


def test_non_string_column_names_are_refused() -> None:
    with pytest.raises(FeatureRowError, match="column names must be strings"):
        stamp_rows([{1: 1.0}], computed_as_of=INSTANT)  # type: ignore[dict-item]


def test_the_stamp_field_name_is_reserved_and_cannot_be_a_column() -> None:
    # A column named computed_as_of would collide with the stamp in the
    # serialised row: whichever won, the payload would be lying about one of
    # them — and a stamp shadowed by feature data is a point-in-time guarantee
    # quietly replaced.  Refusing at the write is the only place it is still
    # explainable, so the collision is an error rather than a silent override.
    with pytest.raises(FeatureRowError, match="reserved"):
        stamp_rows(
            [{"computed_as_of": "spoofed", "close": 1.0}], computed_as_of=INSTANT
        )


def test_the_stamp_is_never_shadowed_in_the_serialised_row() -> None:
    # The invariant behind the reservation, asserted directly: whatever a row
    # carries, to_dict()'s stamp slot holds the stamp.
    row = stamp_rows([{"close": 1.0, "symbol": "BTCUSDT"}], computed_as_of=INSTANT)[0]
    body = row.to_dict()
    assert body[COMPUTED_AS_OF_FIELD] == "2026-04-30T12:00:00+00:00"
    assert decode_rows(encode_rows([row]))[0].computed_as_of == INSTANT


def test_a_value_the_payload_cannot_carry_is_refused_at_the_write() -> None:
    # The payload IS JSON, so an unserialisable value is a row that cannot be
    # stored.  Refusing it here keeps the failure in this layer's error type
    # rather than leaving it to surface as a bare TypeError from json.dumps.
    for bad in (b"raw bytes", {1, 2}, object()):
        with pytest.raises(FeatureRowError, match="cannot carry"):
            stamp_rows([{"blob": bad}], computed_as_of=INSTANT)


def test_encoding_a_hand_built_unserialisable_row_raises_this_layers_error() -> None:
    # A row built around the validator still cannot encode as a bare TypeError.
    sneaky = FeatureRow(computed_as_of=INSTANT, values={})
    object.__setattr__(sneaky, "values", {"blob": b"raw"})
    with pytest.raises(FeatureRowError, match="cannot be encoded"):
        encode_rows([sneaky])


def test_nan_and_infinity_are_representable_values() -> None:
    # The member's own metric payloads carry NaN for an uncomputable value, so
    # an unscored cell is legal here too — the serialisability check must not
    # narrow the value set the rest of the member already relies on.
    nan, inf = float("nan"), float("inf")
    row = stamp_rows([{"a": nan, "b": inf}], computed_as_of=INSTANT)[0]
    back = decode_rows(encode_rows([row]))[0]
    assert back.value("a") != back.value("a")  # NaN is not equal to itself
    assert back.value("b") == inf


def test_nested_lists_and_dicts_round_trip() -> None:
    values = {"window": [1, 2, 3], "params": {"k": 3, "fit": "rolling"}}
    row = stamp_rows([values], computed_as_of=INSTANT)[0]
    assert decode_rows(encode_rows([row]))[0].values == values


def test_rows_compare_by_value_but_are_deliberately_unhashable() -> None:
    # A frozen dataclass synthesises __hash__, but values may hold a list or
    # nested dict, so that hash would raise "unhashable type: 'dict'" later —
    # naming a dict the caller never passed.  Unhashable-by-declaration makes
    # the failure honest and names the row instead.
    a = stamp_rows([{"close": 1.0}], computed_as_of=INSTANT)[0]
    b = stamp_rows([{"close": 1.0}], computed_as_of=INSTANT)[0]
    assert a == b  # equality still works
    assert a != stamp_rows([{"close": 2.0}], computed_as_of=INSTANT)[0]
    with pytest.raises(TypeError, match="unhashable type"):
        hash(a)


def test_rows_are_frozen() -> None:
    # A stamped row records a past computation; editing it in place would
    # rewrite history rather than supersede it.  Same contract, and the same
    # assertion, that test_keys.py pins for FeatureKey.
    row = stamp_rows([{"close": 1.0}], computed_as_of=INSTANT)[0]
    with pytest.raises(FrozenInstanceError):
        row.computed_as_of = INSTANT  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        row.values = {}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Deterministic traversal
# ---------------------------------------------------------------------------


def test_column_names_and_to_dict_are_sorted_and_insertion_independent() -> None:
    # Same values, different construction order: the same row, traversed the
    # same way — the determinism discipline keys() and records() already hold.
    forward = stamp_rows([{"a": 1, "b": 2, "c": 3}], computed_as_of=INSTANT)[0]
    reverse = stamp_rows([{"c": 3, "b": 2, "a": 1}], computed_as_of=INSTANT)[0]
    assert forward.column_names() == ("a", "b", "c")
    assert forward.column_names() == reverse.column_names()
    assert forward.to_dict() == reverse.to_dict()


def test_to_dict_carries_the_stamp_under_its_spec_name() -> None:
    row = stamp_rows([{"close": 1.0}], computed_as_of=INSTANT)[0]
    body = row.to_dict()
    assert body[COMPUTED_AS_OF_FIELD] == "2026-04-30T12:00:00+00:00"
    assert body["close"] == 1.0


# ---------------------------------------------------------------------------
# The payload bridge (feature 48's opaque-bytes contract)
# ---------------------------------------------------------------------------


def test_encode_decode_round_trips_every_row_and_its_stamp() -> None:
    original = stamp_rows(make_values(3), computed_as_of=INSTANT)
    assert decode_rows(encode_rows(original)) == original


def test_round_trip_preserves_row_order() -> None:
    original = stamp_rows(make_values(5), computed_as_of=INSTANT)
    restored = decode_rows(encode_rows(original))
    assert [row.value("symbol") for row in restored] == ["S0", "S1", "S2", "S3", "S4"]


def test_encoding_is_byte_deterministic_and_insertion_independent() -> None:
    # The replay path compares payloads, so the same rows must always encode
    # to byte-identical bytes — including across differing construction order.
    forward = stamp_rows([{"a": 1, "b": 2}], computed_as_of=INSTANT)
    reverse = stamp_rows([{"b": 2, "a": 1}], computed_as_of=INSTANT)
    assert encode_rows(forward) == encode_rows(forward)
    assert encode_rows(forward) == encode_rows(reverse)


def test_the_payload_stamps_each_row_on_disk() -> None:
    # One write gives the batch one instant, and that instant is written onto
    # each row — a reader of the payload alone can see when every row was
    # computed without consulting anything else.
    payload = encode_rows(stamp_rows(make_values(3), computed_as_of=INSTANT))
    body = json.loads(payload)
    assert len(body["rows"]) == 3
    for row in body["rows"]:
        assert row[COMPUTED_AS_OF_FIELD] == "2026-04-30T12:00:00+00:00"


def test_decoding_refuses_a_payload_carrying_a_naive_stamp() -> None:
    # A payload that wandered in from disk revalidates through the row's own
    # construction, so it cannot smuggle a naive stamp past the write check.
    payload = json.dumps(
        {"version": 1, "rows": [{"computed_as_of": "2026-04-30T12:00:00", "close": 1.0}]}
    ).encode("utf-8")
    with pytest.raises(FeatureRowError, match="timezone-aware"):
        decode_rows(payload)


def test_decoding_refuses_a_row_with_no_stamp_at_all() -> None:
    # Feature 51 says *every* row carries the stamp; a row without one is not
    # a row this layer will hand back.
    payload = json.dumps({"version": 1, "rows": [{"close": 1.0}]}).encode("utf-8")
    with pytest.raises(FeatureRowError, match="carries no 'computed_as_of'"):
        decode_rows(payload)


def test_decoding_refuses_an_unparseable_stamp() -> None:
    payload = json.dumps(
        {"version": 1, "rows": [{"computed_as_of": "not-a-date"}]}
    ).encode("utf-8")
    with pytest.raises(FeatureRowError, match="unparseable"):
        decode_rows(payload)


def test_decoding_refuses_a_later_envelope_version() -> None:
    # A changed row representation is a different stored feature, not a
    # payload this decoder reinterprets — the same rule the metric decoders
    # apply to a version bump.
    payload = json.dumps({"version": 99, "rows": []}).encode("utf-8")
    with pytest.raises(FeatureRowError, match="version 99"):
        decode_rows(payload)


def test_decoding_refuses_a_malformed_envelope() -> None:
    for bad in (b"not json", b"[]", b'{"version":1}', b'{"version":1,"rows":{}}'):
        with pytest.raises(FeatureRowError):
            decode_rows(bad)


def test_decoding_refuses_a_non_object_row() -> None:
    payload = json.dumps({"version": 1, "rows": ["nope"]}).encode("utf-8")
    with pytest.raises(FeatureRowError, match="row 0"):
        decode_rows(payload)


# ---------------------------------------------------------------------------
# The layer plugs into feature 48's seam
# ---------------------------------------------------------------------------


def test_stamped_rows_travel_through_a_real_feature_store() -> None:
    # The end-to-end claim: the row layer is a payload layer, so its output
    # goes into the store feature 48 already defines — put, get, decode — with
    # every stamp intact.  Nothing about the keying contract had to change.
    key = FeatureKey(
        feature_name="daily_closes",
        feature_version="1",
        snapshot_hash="a" * 64,
        symbol="BTCUSDT",
        frequency="1d",
    )
    rows = stamp_rows(make_values(3), computed_as_of=INSTANT)
    store = FeatureStore()
    store.put(FeatureRecord(key=key, payload=encode_rows(rows)))

    record = store.get(key)
    assert record is not None
    restored = decode_rows(record.payload)
    assert restored == rows
    assert all(row.computed_as_of == INSTANT for row in restored)


def test_two_writes_of_the_same_values_record_different_instants() -> None:
    # What the stamp is for: identical numbers computed at two different times
    # are distinguishable in the payload, which is exactly what feature 52
    # needs to answer "what did we know at t?" rather than "what is true now?".
    first = stamp_rows(make_values(2), computed_as_of=dt.datetime(2026, 1, 1, tzinfo=UTC))
    second = stamp_rows(
        make_values(2), computed_as_of=dt.datetime(2026, 6, 1, tzinfo=UTC)
    )
    assert encode_rows(first) != encode_rows(second)
    assert decode_rows(encode_rows(first))[0].computed_as_of < decode_rows(
        encode_rows(second)
    )[0].computed_as_of
