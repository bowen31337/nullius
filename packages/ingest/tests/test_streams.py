"""The stream classes: the closed §4.1 table, and nothing invented."""

from __future__ import annotations

import pytest

from nullius_ingest import StreamClass, coerce_stream_class


def test_stream_classes_are_the_section_4_1_table() -> None:
    # One value per row of the §4.1 stream table; no more, no fewer.
    assert {member.value for member in StreamClass} == {
        "klines",
        "aggTrades",
        "bookDiffs",
        "bookFeatures",
        "funding",
        "exchangeInfo",
    }


def test_stream_class_values_are_persistable_strings() -> None:
    # The values are log/staging identifiers; they must serialise and
    # round-trip through their plain string form.
    for member in StreamClass:
        assert isinstance(member, str)
        assert StreamClass(str(member)) is member


def test_coerce_accepts_member_and_string() -> None:
    assert coerce_stream_class(StreamClass.KLINES) is StreamClass.KLINES
    assert coerce_stream_class("klines") is StreamClass.KLINES
    assert coerce_stream_class("exchangeInfo") is StreamClass.EXCHANGE_INFO


def test_coerce_rejects_unknown_string_with_the_known_set() -> None:
    with pytest.raises(TypeError, match="unknown stream class 'tickData'"):
        coerce_stream_class("tickData")


def test_coerce_rejects_non_string_junk() -> None:
    with pytest.raises(TypeError, match="StreamClass or its string value"):
        coerce_stream_class(42)
