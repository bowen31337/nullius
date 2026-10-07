"""Feature 2 of additions_spec_llm_usage_tracking.xml: the dated price table.

*System prices a call from a dated, versioned price table, so that
estimate_cost(model, usage) returns a USD figure or None, never a guessed
price.*  This file is the whole of that feature's test surface: the three
priced models against hand-computed dollar figures, the plain-input
subtraction that keeps a cache-touching call from being double-billed, an
unknown model (including a dated served id the table does not itself list)
answering ``None`` rather than a guess, and the version string that makes
a persisted estimate auditable against the table that produced it.

``_Usage`` is a local stand-in for :class:`providers.Usage` rather than
that class itself, because feature 1 (``cache_write_tokens`` on
``Usage``) is this feature's sibling, not its dependency — the addition's
own integration point is explicit that *"Features 1 and 2 are independent
foundations"*. :func:`providers._prices.estimate_cost` reads a usage by
its four named counts rather than by its class (the double-import remedy
:mod:`providers._cache` and :mod:`providers._served` use for the same
reason), so a plain stand-in carrying the same four names is read
identically to whatever ``Usage`` looks like once both features land.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from providers._prices import (
    CACHE_WRITE_MULTIPLE,
    PRICE_TABLE,
    PRICE_TABLE_VERSION,
    ModelPrice,
    PriceTableError,
    estimate_cost,
    price_for,
)


@dataclass(frozen=True)
class _Usage:
    """A usage stand-in carrying the four counts estimate_cost reads by name."""

    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


# ── The version string ─────────────────────────────────────────────────────


def test_the_price_table_version_is_a_present_date_string():
    # A caller persisting an estimate persists this string beside it
    # (feature 3's price_table_version column), so a report made after
    # the rates have moved can tell which table priced which row.
    assert isinstance(PRICE_TABLE_VERSION, str) and PRICE_TABLE_VERSION
    assert PRICE_TABLE_VERSION == "2026-09-25"


# ── Each priced model against a hand-computed value ─────────────────────────


class TestHandComputedValues:
    """Each of the three Anthropic entries against arithmetic worked by hand.

    One usage shape shared by all three, carrying both cache classes
    alongside plain input and output, so each test exercises all four
    rates of its model at once: ``input_tokens=1_200_000`` of which
    ``100_000`` were a cache write and ``100_000`` a cache read, leaving
    ``1_000_000`` plain, plus ``50_000`` output tokens.
    """

    USAGE = _Usage(
        input_tokens=1_200_000,
        output_tokens=50_000,
        cache_write_tokens=100_000,
        cache_read_tokens=100_000,
    )

    def test_claude_opus_5_5(self):
        # 1.0 * 4.00 + 0.1 * 5.00 + 0.1 * 0.20 + 0.05 * 20.00
        #   = 4.00    + 0.50    + 0.02    + 1.00   = 5.52
        assert estimate_cost("claude-opus-5-5", self.USAGE) == Decimal("5.520000")

    def test_claude_sonnet_5_5(self):
        # 1.0 * 2.00 + 0.1 * 2.50 + 0.1 * 0.20 + 0.05 * 10.00
        #   = 2.00    + 0.25    + 0.02    + 0.50   = 2.77
        assert estimate_cost("claude-sonnet-5-5", self.USAGE) == Decimal("2.770000")

    def test_claude_haiku_4_5(self):
        # 1.0 * 1.00 + 0.1 * 1.25 + 0.1 * 0.10 + 0.05 * 5.00
        #   = 1.00    + 0.125   + 0.01    + 0.25   = 1.385
        assert estimate_cost("claude-haiku-4-5", self.USAGE) == Decimal("1.385000")

    def test_a_call_with_no_cache_activity_prices_input_and_output_only(self):
        # The degenerate case of the same arithmetic: both cache counts
        # zero, so the plain-input class is the whole of input_tokens.
        usage = _Usage(input_tokens=1_000, output_tokens=200)
        # 1000 * 4.00 / 1e6 + 200 * 20.00 / 1e6 = 0.004 + 0.004 = 0.008
        assert estimate_cost("claude-opus-5-5", usage) == Decimal("0.008000")


# ── The plain-input subtraction ──────────────────────────────────────────────


def test_plain_input_is_input_tokens_minus_both_cache_classes():
    # input_tokens is the call's *whole* billed input under Anthropic's own
    # convention (providers._anthropic sets it to input + cache_creation +
    # cache_read), so the two cache counts are a portion of it, not
    # additional to it. Pricing the whole of input_tokens at the plain
    # rate on top of the cache counts' own rates would double-bill the
    # tokens the cache counts are a portion of.
    usage = _Usage(
        input_tokens=100, output_tokens=0, cache_write_tokens=30, cache_read_tokens=20
    )
    # plain input = 100 - 30 - 20 = 50
    #   50 * 4.00 / 1e6  = 0.0002
    # + 30 * 5.00 / 1e6  = 0.00015
    # + 20 * 0.20 / 1e6  = 0.000004
    # -----------------------------
    #                      0.000354
    cost = estimate_cost("claude-opus-5-5", usage)
    assert cost == Decimal("0.000354")
    # The number a reader would get from forgetting the subtraction —
    # pricing the whole 100 input_tokens at the plain rate on top of the
    # cache classes — is a different, larger figure, so this assertion
    # would fail if the subtraction were ever dropped.
    wrong_without_subtraction = (
        Decimal(100) * Decimal("4.00")
        + Decimal(30) * Decimal("5.00")
        + Decimal(20) * Decimal("0.20")
    ) / Decimal(1_000_000)
    assert cost != wrong_without_subtraction


def test_cache_classes_equal_to_input_tokens_leave_no_plain_input_charge():
    # input_tokens == cache_write_tokens + cache_read_tokens is a call
    # that read entirely from or into the cache: the plain-input class is
    # zero, and only the cache and output rates apply.
    usage = _Usage(
        input_tokens=10, output_tokens=0, cache_write_tokens=4, cache_read_tokens=6
    )
    # claude-haiku-4-5's cache_write_price is 1.25, cache_read_price is 0.10:
    # 4 * 1.25 / 1e6 + 6 * 0.10 / 1e6 = 0.000005 + 0.0000006 = 0.0000056,
    # which rounds to 0.000006.
    assert estimate_cost("claude-haiku-4-5", usage) == Decimal("0.000006")


def test_cache_classes_exceeding_input_tokens_cannot_be_priced():
    # The cache counts are a *portion* of input_tokens, so a usage
    # reporting more cache than input is a malformed accounting this
    # module refuses to guess a plain-input class for, rather than
    # pricing it against a negative class.
    usage = _Usage(
        input_tokens=10, output_tokens=0, cache_write_tokens=6, cache_read_tokens=6
    )
    with pytest.raises(PriceTableError):
        estimate_cost("claude-opus-5-5", usage)


# ── An unknown model returns None, never a guess ────────────────────────────


def test_a_model_the_table_does_not_map_exactly_returns_none():
    usage = _Usage(input_tokens=1_000, output_tokens=100)
    assert estimate_cost("gpt-5-nonexistent", usage) is None
    assert price_for("gpt-5-nonexistent") is None


def test_a_dated_served_id_not_listed_exactly_returns_none():
    # claude-haiku-4-5-20251001 is a real served id for claude-haiku-4-5,
    # but it is a *different string* from the table's key, and reading one
    # as the other would be this module guessing that an unstated served
    # version bills at the base model's rate -- exactly the guess the
    # feature exists to refuse.
    usage = _Usage(input_tokens=1_000, output_tokens=100)
    assert estimate_cost("claude-haiku-4-5-20251001", usage) is None
    assert price_for("claude-haiku-4-5-20251001") is None
    # The un-dated id it was derived from is, of course, priced.
    assert price_for("claude-haiku-4-5") is not None


def test_price_for_a_non_string_model_returns_none():
    assert price_for(None) is None
    assert price_for(42) is None


# ── Rounding to six places ───────────────────────────────────────────────────


def test_the_answer_rounds_half_up_at_the_sixth_decimal_place():
    # 5 cache-read tokens at claude-haiku-4-5's $0.10/M rate price to
    # exactly 0.0000005 -- precisely halfway between 0.000000 and
    # 0.000001 -- so this is the one case that tells ROUND_HALF_UP apart
    # from the stdlib Decimal context's default ROUND_HALF_EVEN (which
    # would round this particular halfway value down to zero).
    usage = _Usage(
        input_tokens=5, output_tokens=0, cache_write_tokens=0, cache_read_tokens=5
    )
    assert estimate_cost("claude-haiku-4-5", usage) == Decimal("0.000001")


def test_the_answer_is_always_rounded_to_six_decimal_places():
    cost = estimate_cost("claude-opus-5-5", _Usage(input_tokens=1, output_tokens=0))
    assert cost is not None
    assert -cost.as_tuple().exponent == 6


# ── The table's own invariant ────────────────────────────────────────────────


def test_every_priced_model_states_its_source():
    for price in PRICE_TABLE.values():
        assert isinstance(price.source, str) and price.source


def test_cache_write_is_one_and_a_quarter_times_input_on_every_entry():
    assert CACHE_WRITE_MULTIPLE == Decimal("1.25")
    for price in PRICE_TABLE.values():
        assert price.cache_write_price == price.input_price * CACHE_WRITE_MULTIPLE


def test_a_mistyped_cache_write_rate_is_refused_at_construction():
    # The cross-check is this table's own arithmetic: a transcription
    # slip between a model's input and cache-write rates is caught here,
    # at construction, rather than surfacing as a silently wrong estimate
    # in a spend report later.
    with pytest.raises(PriceTableError):
        ModelPrice(
            model="claude-opus-5-5",
            input_price=Decimal("4.00"),
            cache_write_price=Decimal("4.50"),  # should be 5.00
            cache_read_price=Decimal("0.20"),
            output_price=Decimal("20.00"),
            source="test",
        )
