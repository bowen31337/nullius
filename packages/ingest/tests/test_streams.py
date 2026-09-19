"""The stream classes: a closed set drawn from §4.1, and nothing invented."""

from __future__ import annotations

import pytest

from nullius_ingest import StreamClass, coerce_stream_class


def test_stream_classes_are_the_section_4_1_streams() -> None:
    # One value per §4.1 stream, plus one per *derived family* — §4.1's single
    # "Book features (derived)" row is a family, and the enum is the isolation
    # unit rather than the documentation unit, so each derived family that lands
    # takes its own value.  The set stays closed either way: nothing here is
    # invented, and a wire-format stream still maps one-to-one onto a row.
    assert {member.value for member in StreamClass} == {
        "klines",
        "aggTrades",
        "bookDiffs",
        "bookFeatures",  # §4.1 "Book features (derived)" — feature 20's depth ladder
        "tradeFlow",  # §4.1 same row — feature 22's cancel-replace rate and moments
        "funding",
        "exchangeInfo",
    }


def test_every_wire_stream_maps_onto_exactly_one_section_4_1_row() -> None:
    # The one-to-one direction that must never drift: each venue-fed stream is
    # exactly one row of §4.1's table, with the exchange-facing spelling.  The
    # derived families are the documented exception, and only they.
    wire = {
        "klines",
        "aggTrades",
        "bookDiffs",
        "funding",
        "exchangeInfo",
    }
    derived = {"bookFeatures", "tradeFlow"}

    assert {member.value for member in StreamClass} == wire | derived
    assert not (wire & derived)


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
