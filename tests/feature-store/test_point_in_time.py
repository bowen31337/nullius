"""Feature 52's read contract: a query at ``t`` sees only rows computed by ``t``.

app_spec.xml feature 52: *System returns only rows whose computed_as_of is
at or before the query time, so a point-in-time read cannot see a later
computation.*  §4.4 of the architecture doc states it as the rule the
category hangs on — "every row carries ``computed_as_of``, and a query at
``t`` may only return rows with ``computed_as_of <= t``" — and closes by
calling the feature store the single most common source of subtle leakage
in real quant systems.  Feature 51 (``test_rows.py``) pinned the write
half: the stamp, fixed at write time, one instant per batch.  This suite
pins the read half.

The tests are organised around the three claims the sentence makes:

* **at or before the query time** — the boundary is ``<=``, inclusive, and
  it is drawn on ``computed_as_of`` alone;
* **only rows** — the visible subset comes back verbatim, in its written
  order, never restamped;
* **cannot see a later computation** — a row stamped after the query is
  dropped however correct it is, a stored-but-later record reads as empty
  rather than as missing, and a malformed query fails at the query rather
  than deep inside a comparison.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from feature_store import (
    FeatureKey,
    FeatureRecord,
    FeatureStore,
    PointInTimeError,
    decode_rows,
    decode_rows_as_of,
    encode_rows,
    read_rows_as_of,
    rows_as_of,
    stamp_rows,
)

UTC = dt.timezone.utc

#: One trading day, told as a story: a morning computation, a query at
#: noon, and an afternoon recompute.  Naming the instants keeps every test
#: an assertion about *time*, not an observation of the clock.
MORNING = dt.datetime(2026, 4, 30, 9, 0, 0, tzinfo=UTC)
NOON = dt.datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
AFTERNOON = dt.datetime(2026, 4, 30, 17, 0, 0, tzinfo=UTC)


def make_key(name: str = "daily_closes") -> FeatureKey:
    """A well-formed five-component key, so store-level reads address something."""
    return FeatureKey(
        feature_name=name,
        feature_version="1",
        snapshot_hash="a" * 64,
        symbol="BTCUSDT",
        frequency="1d",
    )


def make_values(count: int = 3) -> list[dict[str, object]]:
    return [{"symbol": f"S{i}", "close": 100.0 + i} for i in range(count)]


# ---------------------------------------------------------------------------
# The boundary: at or before, on the stamp alone
# ---------------------------------------------------------------------------


def test_rows_computed_before_the_query_time_are_returned() -> None:
    rows = stamp_rows(make_values(3), computed_as_of=MORNING)
    assert rows_as_of(rows, as_of=NOON) == rows


def test_a_row_computed_exactly_at_the_query_time_is_returned() -> None:
    # "At or before" is <=, so equality is on the visible side of the edge:
    # a row stamped exactly at the query instant had been computed by then.
    # (The universe plugin draws the same edge the same way — valid_from is
    # inclusive — because a fact that begins at an instant is in effect at
    # that instant.)
    rows = stamp_rows(make_values(2), computed_as_of=NOON)
    assert rows_as_of(rows, as_of=NOON) == rows


def test_a_row_computed_after_the_query_time_is_not_returned() -> None:
    # The heart of the feature: the afternoon recompute is invisible at noon,
    # however correct its numbers turn out to be.
    rows = stamp_rows(make_values(2), computed_as_of=AFTERNOON)
    assert rows_as_of(rows, as_of=NOON) == ()


def test_the_boundary_is_one_second_wide() -> None:
    # 12:00:00 is visible at 12:00:00; 12:00:01 is not.  The edge has no
    # grey zone a flaky test could land astride.
    visible = stamp_rows([{"close": 1.0}], computed_as_of=NOON)
    later = stamp_rows(
        [{"close": 2.0}], computed_as_of=NOON + dt.timedelta(seconds=1)
    )
    assert rows_as_of(visible + later, as_of=NOON) == visible


def test_a_query_sees_the_visible_subset_in_its_written_order() -> None:
    # A series is not a set: the morning rows keep their written order even
    # with later computations interleaved in the batch, rather than being
    # sorted or re-ordered by the filter.
    morning = stamp_rows(make_values(2), computed_as_of=MORNING)
    afternoon = stamp_rows(make_values(2), computed_as_of=AFTERNOON)
    batch = (afternoon[0], morning[0], afternoon[1], morning[1])
    seen = rows_as_of(batch, as_of=NOON)
    assert seen == (morning[0], morning[1])


def test_values_describing_any_time_gate_on_the_stamp_alone() -> None:
    # The stamp is the only clock a read consults: a row whose *values*
    # name a date after the query is still visible if it was computed
    # before the query, and a row naming a past date is still invisible if
    # it was computed after.  Gating on the values would be the layer
    # quietly deciding what a feature's columns mean.
    forecast = stamp_rows(
        [{"as_of_date": "2026-12-31", "forecast": 42.0}], computed_as_of=MORNING
    )
    hindsight = stamp_rows(
        [{"as_of_date": "2020-01-01", "restated": True}], computed_as_of=AFTERNOON
    )
    seen = rows_as_of(forecast + hindsight, as_of=NOON)
    assert seen == forecast


def test_rows_with_different_stamps_in_one_payload_filter_row_by_row() -> None:
    # One record can carry rows from more than one write (a deliberate
    # replace=True rewrite that appends the recompute); the filter applies
    # per row, not per record.
    morning = stamp_rows(make_values(2), computed_as_of=MORNING)
    afternoon = stamp_rows(make_values(2), computed_as_of=AFTERNOON)
    payload = encode_rows(morning + afternoon)
    assert decode_rows_as_of(payload, as_of=NOON) == morning
    assert decode_rows_as_of(payload, as_of=AFTERNOON) == morning + afternoon


# ---------------------------------------------------------------------------
# Only rows: verbatim, ordered, never restamped
# ---------------------------------------------------------------------------


def test_rows_come_back_verbatim_not_restamped() -> None:
    # The same objects, carrying the stamps that were written: a read is a
    # question about the past and must not restate when the answer was
    # computed as when it was asked.
    rows = stamp_rows(make_values(2), computed_as_of=MORNING)
    seen = rows_as_of(rows, as_of=AFTERNOON)
    assert all(returned is written for returned, written in zip(seen, rows))
    assert all(row.computed_as_of == MORNING for row in seen)


def test_a_generator_of_rows_reads_like_a_list() -> None:
    rows = stamp_rows(make_values(3), computed_as_of=MORNING)
    assert rows_as_of(iter(rows), as_of=NOON) == rows


def test_reading_twice_gives_the_same_answer() -> None:
    # Nothing here reads a wall clock: the answer is a pure function of the
    # rows and the query instant, so the replay path reproduces it exactly.
    rows = stamp_rows(make_values(2), computed_as_of=MORNING)
    first = rows_as_of(rows, as_of=AFTERNOON)
    later = rows_as_of(rows, as_of=AFTERNOON)
    assert first == later == rows


def test_the_result_is_an_immutable_tuple() -> None:
    rows = stamp_rows(make_values(1), computed_as_of=MORNING)
    seen = rows_as_of(rows, as_of=NOON)
    assert isinstance(seen, tuple)
    with pytest.raises((AttributeError, TypeError)):
        seen.append(rows[0])  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The query time is validated like a stamp
# ---------------------------------------------------------------------------


def test_a_naive_query_time_is_refused_at_the_query() -> None:
    # The <= comparison of a naive as_of against every aware stamp would
    # raise TypeError deep inside the read; refusing it here puts the
    # failure on the caller who could have named the offset.
    rows = stamp_rows(make_values(1), computed_as_of=MORNING)
    with pytest.raises(PointInTimeError, match="timezone-aware"):
        rows_as_of(rows, as_of=dt.datetime(2026, 4, 30, 12, 0, 0))  # type: ignore[arg-type]


def test_a_non_datetime_query_time_is_refused() -> None:
    # A string that looks like an instant still is not one, and a bare
    # date names a day, not an instant.
    rows = stamp_rows(make_values(1), computed_as_of=MORNING)
    for bad in ("2026-04-30T12:00:00+00:00", dt.date(2026, 4, 30), None, 0):
        with pytest.raises(PointInTimeError, match="must be a datetime"):
            rows_as_of(rows, as_of=bad)  # type: ignore[arg-type]


def test_a_naive_query_time_is_refused_even_against_empty_rows() -> None:
    # The question is validated before anything is filtered, so a malformed
    # query is reported as such even when no row would ever be compared.
    with pytest.raises(PointInTimeError, match="timezone-aware"):
        rows_as_of((), as_of=dt.datetime(2026, 4, 30))  # type: ignore[arg-type]


def test_an_offset_query_time_names_the_same_instant() -> None:
    # An aware query in another offset is normalised to UTC, not rejected:
    # 22:00+10:00 IS 12:00Z, and the row stamped 12:00Z is visible at it —
    # inclusive across offsets, because both spell one instant.
    offset = dt.timezone(dt.timedelta(hours=10))
    rows = stamp_rows([{"close": 1.0}], computed_as_of=NOON)
    assert rows_as_of(rows, as_of=dt.datetime(2026, 5, 1, 8, 0, 0, tzinfo=offset)) == rows


def test_a_sub_second_query_time_sees_whole_second_stamps() -> None:
    # Stamps are second-resolved (utc_now drops microseconds); a query
    # carrying them is not truncated to match, because truncation would
    # move the query instant and 12:00:00.5 is unambiguously after 12:00:00.
    rows = stamp_rows([{"close": 1.0}], computed_as_of=NOON)
    query = NOON + dt.timedelta(milliseconds=500)
    assert rows_as_of(rows, as_of=query) == rows


# ---------------------------------------------------------------------------
# The rows layer guards its input
# ---------------------------------------------------------------------------


def test_a_non_row_element_is_refused_naming_its_index() -> None:
    # A raw mapping has no stamp to compare; without this check the failure
    # would be an AttributeError from row.computed_as_of, naming an
    # attribute the caller never spelled.
    rows = stamp_rows(make_values(2), computed_as_of=MORNING)
    with pytest.raises(PointInTimeError, match=r"row 1 .*must be a FeatureRow"):
        rows_as_of((rows[0], {"close": 1.0}), as_of=NOON)  # type: ignore[dict-item]


def test_empty_rows_read_as_empty() -> None:
    # A feature computed over an empty window has nothing to hide and
    # nothing to show; that is a read like any other.
    assert rows_as_of((), as_of=NOON) == ()


# ---------------------------------------------------------------------------
# The payload layer: one record's opaque bytes
# ---------------------------------------------------------------------------


def test_a_payload_filters_after_decoding() -> None:
    # decode_rows_as_of is decode-then-filter, exactly the composition a
    # caller would write by hand — so the two paths cannot disagree.
    morning = stamp_rows(make_values(2), computed_as_of=MORNING)
    afternoon = stamp_rows(make_values(2), computed_as_of=AFTERNOON)
    payload = encode_rows(morning + afternoon)
    assert decode_rows_as_of(payload, as_of=NOON) == rows_as_of(
        decode_rows(payload), as_of=NOON
    )


def test_a_malformed_payload_is_refused_as_a_point_in_time_error() -> None:
    # One error type for a failed read: the row layer's error is chained
    # under this layer's, never surfaced bare, and never answered with an
    # empty tuple that would read as "nothing was computed by as_of".
    with pytest.raises(PointInTimeError, match="cannot filter this payload"):
        decode_rows_as_of(b"not json", as_of=NOON)


def test_a_payload_carrying_a_naive_stamp_is_refused() -> None:
    # The decode revalidates every stamp through the row's own
    # construction, so disk cannot smuggle a naive stamp past the write
    # check and into the comparison — and the failure surfaces as this
    # layer's error.
    payload = json.dumps(
        {"version": 1, "rows": [{"computed_as_of": "2026-04-30T09:00:00"}]}
    ).encode("utf-8")
    with pytest.raises(PointInTimeError, match="timezone-aware"):
        decode_rows_as_of(payload, as_of=NOON)


def test_empty_bytes_are_not_a_rows_payload() -> None:
    # The record layer blesses an empty payload as "a feature with no
    # rows", but the rows layer's spelling of no rows is a valid empty
    # envelope, not zero bytes; reinterpreting b"" as data would make
    # "never a rows payload" and "no rows visible at t" the same answer.
    with pytest.raises(PointInTimeError, match="cannot filter this payload"):
        decode_rows_as_of(b"", as_of=NOON)
    # The legal empty write, for contrast: an envelope, reading as empty.
    assert decode_rows_as_of(encode_rows([]), as_of=NOON) == ()


# ---------------------------------------------------------------------------
# The store layer: a point-in-time read under a key
# ---------------------------------------------------------------------------


def test_a_point_in_time_read_through_the_store() -> None:
    # End-to-end at the store layer: put a stamped record, read it back at
    # a query time, get only what had been computed by then — with feature
    # 48's keying contract entirely unchanged.
    key = make_key()
    rows = stamp_rows(make_values(3), computed_as_of=MORNING)
    store = FeatureStore()
    store.put(FeatureRecord(key=key, payload=encode_rows(rows)))

    assert read_rows_as_of(store, key, as_of=AFTERNOON) == rows


def test_a_stored_but_later_record_reads_as_empty_not_as_missing() -> None:
    # The distinction this feature guarantees, kept observable: None means
    # nothing is stored under the key; () means the record exists and every
    # row in it was computed after the query.  Collapsing the two would
    # hide the later computation this read declines to see.
    key = make_key()
    store = FeatureStore()
    store.put(
        FeatureRecord(
            key=key, payload=encode_rows(stamp_rows(make_values(2), computed_as_of=AFTERNOON))
        )
    )
    assert read_rows_as_of(store, key, as_of=NOON) == ()
    assert read_rows_as_of(store, key, as_of=AFTERNOON) != ()
    assert read_rows_as_of(store, key, as_of=AFTERNOON + dt.timedelta(seconds=1)) != ()


def test_a_later_computation_is_invisible_until_its_own_instant() -> None:
    # The headline scenario, told once through the store: a morning write,
    # an afternoon recompute appended under the same key (a deliberate
    # replace), and a noon query that sees only the morning rows — then an
    # evening query that sees both.  What did we know at noon is not what
    # is true by evening.
    key = make_key()
    morning = stamp_rows(
        [{"symbol": "S0", "close": 100.0}], computed_as_of=MORNING
    )
    recompute = stamp_rows(
        [{"symbol": "S0", "close": 101.5}], computed_as_of=AFTERNOON
    )
    store = FeatureStore()
    store.put(FeatureRecord(key=key, payload=encode_rows(morning)))
    store.put(
        FeatureRecord(key=key, payload=encode_rows(morning + recompute)),
        replace=True,
    )

    assert read_rows_as_of(store, key, as_of=NOON) == morning
    assert read_rows_as_of(store, key, as_of=AFTERNOON) == morning + recompute


def test_a_key_the_store_does_not_hold_is_a_normal_miss() -> None:
    # The store layer's miss discipline is get()'s own: an absent record is
    # None, never an error, exactly as an unaddressed feature is a
    # discoverable state everywhere else in the store.
    assert read_rows_as_of(FeatureStore(), make_key(), as_of=NOON) is None


def test_the_read_composes_with_the_store_query_surface() -> None:
    # Feature 48's records() reaches every record under a name; feature 52
    # reads each point-in-time.  Composed, a caller can ask "what did any
    # version of this feature know at t?" without a new seam.
    morning = stamp_rows(make_values(1), computed_as_of=MORNING)
    afternoon = stamp_rows(make_values(1), computed_as_of=AFTERNOON)
    store = FeatureStore()
    store.put(FeatureRecord(key=make_key("daily_closes"), payload=encode_rows(morning)))
    store.put(FeatureRecord(key=make_key("daily_closes_v2"), payload=encode_rows(afternoon)))

    visible = tuple(
        row
        for record in store.records("daily_closes")
        for row in decode_rows_as_of(record.payload, as_of=NOON)
    )
    assert visible == morning  # the afternoon record contributes nothing at noon


def test_the_store_is_duck_typed_on_get() -> None:
    # The composed feature-store component is imported by the factory under
    # a scan alias, so it is structurally a store but never the same module
    # object a direct import yields — an isinstance check here would reject
    # the legitimate composed case.  A stand-in exposing get() is accepted.
    rows = stamp_rows(make_values(1), computed_as_of=MORNING)
    key = make_key()
    payload = encode_rows(rows)

    class StandIn:
        """The surface read_rows_as_of actually uses: get()."""

        def get(self, feature_key: FeatureKey) -> FeatureRecord | None:
            return FeatureRecord(key=feature_key, payload=payload)

    assert read_rows_as_of(StandIn(), key, as_of=NOON) == rows  # type: ignore[arg-type]


def test_an_object_without_get_is_refused() -> None:
    with pytest.raises(TypeError, match="exposing get"):
        read_rows_as_of(object(), make_key(), as_of=NOON)  # type: ignore[arg-type]


def test_a_malformed_query_time_fails_before_the_store_is_asked() -> None:
    # A naive as_of against a missing key is still an error, not None:
    # the question is validated before anything is read.
    with pytest.raises(PointInTimeError, match="timezone-aware"):
        read_rows_as_of(
            FeatureStore(), make_key(), as_of=dt.datetime(2026, 4, 30)
        )  # type: ignore[arg-type]
