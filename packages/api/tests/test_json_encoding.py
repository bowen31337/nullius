"""The one JSON spelling: feature 4's codec, held to its own laws.

These tests pin :mod:`nullius_api.json_encoding` to the vocabulary the
transport promises — dataclasses as objects keyed by field name, dates
and datetimes as ISO 8601, UUIDs and Decimals as their exact text,
mappings with text keys, tuples as arrays — and to the refusals that
make the envelope laws hold: a value the vocabulary cannot spell is
refused by name rather than stringified, because ``str()`` of the wrong
thing is exactly how a filesystem path or a repr would reach a body
the spec promises carries neither.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from nullius_api import JsonEncodingError, dumps


@dataclass(frozen=True)
class _Row:
    """A response-shaped value: the fields the members' answers carry."""

    campaign_id: str
    figure: float | None
    computed_at: dt.datetime
    identity: uuid.UUID
    exact: Decimal


@dataclass(frozen=True)
class _Envelope:
    """A nested response: a dataclass inside a dataclass."""

    row: _Row
    history: tuple


class _Opaque:
    """Something the vocabulary cannot spell — an arbitrary object."""


def test_a_dataclass_answers_as_an_object_keyed_by_field_names() -> None:
    """The members spell their values by field name; so does the body."""
    instant = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.UTC)
    row = _Row(
        campaign_id="campaign-1",
        figure=0.5,
        computed_at=instant,
        identity=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        exact=Decimal("0.1"),
    )
    body = json.loads(dumps(row))
    assert body == {
        "campaign_id": "campaign-1",
        "figure": 0.5,
        "computed_at": "2026-09-28T12:00:00+00:00",
        "identity": "12345678-1234-5678-1234-567812345678",
        "exact": "0.1",
    }


def test_nested_dataclasses_and_tuples_encode_recursively() -> None:
    """A response holding a response answers as deeply as it holds."""
    instant = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    envelope = _Envelope(
        row=_Row("c", None, instant, uuid.UUID(int=7), Decimal("2.50")),
        history=(("c", 0.25, "2026-01-01T00:00:00+00:00"), ()),
    )
    body = json.loads(dumps(envelope))
    assert body["row"]["exact"] == "2.50"
    assert body["row"]["figure"] is None  # the honest absence, not 0.0
    assert body["history"][0][1] == 0.25
    assert body["history"][1] == []


def test_an_empty_collection_and_none_stay_honest() -> None:
    """An empty store answers empty and null — never a fabricated zero."""

    @dataclass(frozen=True)
    class _Answer:
        history: tuple = ()
        figure: float | None = None

    body = json.loads(dumps(_Answer()))
    assert body == {"history": [], "figure": None}


def test_a_decimal_answers_its_exact_text_never_a_float() -> None:
    """``float(Decimal("0.1"))`` is a different number; the body is not it."""
    text = dumps({"figure": Decimal("0.1")})
    assert text == '{"figure": "0.1"}'
    # And the exactness generalises: a two-decimal figure a store
    # measured crosses the wire as the text the store stated, not as
    # the nearest binary float's seventeen-digit re-spelling of it.
    assert json.loads(dumps({"figure": Decimal("2.50")}))["figure"] == "2.50"


def test_a_non_finite_float_is_refused() -> None:
    """NaN and the infinities are not figures anyone measured."""
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(JsonEncodingError):
            dumps({"figure": value})


def test_dates_datetimes_and_times_answer_iso_8601() -> None:
    """The one textual instant spelling the workspace already carries."""
    assert dumps(dt.date(2026, 9, 28)) == '"2026-09-28"'
    naive = dt.datetime(  # noqa: DTZ001 - the naive spelling is the point
        2026, 9, 28, 1, 2, 3
    )
    assert dumps(naive) == '"2026-09-28T01:02:03"'
    assert dumps(dt.time(1, 2, 3)) == '"01:02:03"'


def test_a_mapping_with_text_keys_answers_an_object() -> None:
    """``{stratum: count}`` — the shape the coverage route answers."""
    assert json.loads(dumps({"crash": 0, "chop": 14})) == {"crash": 0, "chop": 14}


def test_a_non_text_key_is_refused_by_name() -> None:
    """The members key by campaign id and stratum name; coercion would
    be a second spelling of a key the member chose."""
    with pytest.raises(JsonEncodingError) as raised:
        dumps({1: "count"})
    assert "int" in str(raised.value)


@pytest.mark.parametrize(
    "key",
    [1, 1.5, None, ("a", "b"), b"bytes", Path("/tmp/nowhere.db"), _Opaque(), print],
)
def test_a_key_outside_the_vocabulary_is_refused_rather_than_re_spelled(
    key,
) -> None:
    """``str()`` of a key is how a repr nobody chose — a path, an object,
    a tuple's punctuation — would reach a body one mapping key away from
    the values the codec already refuses for the same reason."""
    with pytest.raises(JsonEncodingError) as raised:
        dumps({key: "value"})
    assert "key" in str(raised.value)


def test_a_date_key_spells_itself_as_the_value_of_the_same_date() -> None:
    """§7.2's target series is keyed by rebalance date, and a JSON
    object's keys are text — so the date spells itself exactly as the
    same date spells *itself* as a value.  One rule, one spelling: a
    body keyed by ``{"2026-01-05": …}`` is what the member's own request
    record accepts back."""
    day = dt.date(2026, 1, 5)
    assert json.loads(dumps({day: 0.01})) == {"2026-01-05": 0.01}
    assert dumps(day) == '"2026-01-05"'


def test_a_uuid_and_a_decimal_key_spell_themselves_too() -> None:
    """The other scalars the vocabulary already spells canonically — a
    UUID's hyphenated text and a Decimal's exact text — spell their keys
    the same way, because it is the same value under the same rule."""
    identity = uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert json.loads(dumps({identity: 1})) == {
        "00000000-0000-0000-0000-000000000001": 1
    }
    # The Decimal keeps its exact text as a key, never a float — the same
    # reasoning the value rule gives.
    assert list(json.loads(dumps({Decimal("0.1"): 1}))) == ["0.1"]


def test_two_keys_that_would_spell_one_text_are_refused() -> None:
    """A date and its own ISO string are one bar stated twice.  Merging
    them would silently drop an entry the member wrote — the same "one
    bar, one answer" rule the null oracle's own record states over the
    same series."""
    with pytest.raises(JsonEncodingError) as raised:
        dumps({dt.date(2026, 1, 5): 0.01, "2026-01-05": 0.02})
    assert "same JSON object key" in str(raised.value)


def test_a_series_keyed_by_dates_answers_the_wire_spelling() -> None:
    """The whole shape §7.2's payload takes: an object per rebalance date,
    each row an object per symbol — the target series a caller parses."""
    series = {
        dt.date(2026, 1, 5): {"BTCUSDT": 0.01, "ETHUSDT": -0.02},
        dt.date(2026, 1, 6): {"BTCUSDT": 0.03, "ETHUSDT": -0.04},
    }
    assert json.loads(dumps({"target_series": series, "charges_budget": True})) == {
        "target_series": {
            "2026-01-05": {"BTCUSDT": 0.01, "ETHUSDT": -0.02},
            "2026-01-06": {"BTCUSDT": 0.03, "ETHUSDT": -0.04},
        },
        "charges_budget": True,
    }


@pytest.mark.parametrize(
    "value",
    [
        {"reading": b"\x00\x01"},
        {"regimes": {"high", "low"}},
        {"path": Path("/tmp/nowhere.db")},
        {"engine": _Opaque()},
        {"halt": print},
    ],
)
def test_the_unspellable_is_refused_naming_the_type(value: dict) -> None:
    """Bytes, sets, paths, objects and callables never reach a body.

    This is the load-bearing refusal: each of these would otherwise
    land in a body as a ``repr`` nobody chose to answer with — the
    filesystem-path leak the spec's envelope law exists to prevent
    among them.
    """
    with pytest.raises(JsonEncodingError) as raised:
        dumps(value)
    message = str(raised.value)
    assert "refused" in message
    # The message names the type (the repair's one glance) and carries
    # neither the value's repr nor a path of its own.
    assert "tmp" not in message


def test_an_unknown_type_message_names_the_vocabulary() -> None:
    """The refusal tells the encoder's author what the vocabulary is."""
    with pytest.raises(JsonEncodingError) as raised:
        dumps(object())
    message = str(raised.value)
    assert "object" in message
    assert "dataclasses" in message
    assert "ISO 8601" in message


def test_bools_and_ints_stay_native() -> None:
    """A lamp answers true or false — never 1 or 0 in disguise."""
    assert dumps({"canary": True, "count": 3, "none": None}) == (
        '{"canary": true, "count": 3, "none": null}'
    )
