"""Tests for :mod:`router.sizing` — the book's weights become order deltas.

Feature 2 of additions_spec_bingx_dry_run.xml: *System sizes final
target weights into signed contract quantity deltas against
RouterSymbolFilters and a Decimal mark per symbol: equity times weight
divided by mark price, truncated toward zero onto the symbol's step
grid, minus the position currently held.*  These tests hold the verb to
that sentence over the recorded VST fixtures — the exact six deltas the
spec spells, as exact Decimal strings — and to the refusals that keep
the join honest: a held symbol the venue's documents cannot size is
named, never silently skipped, and a zero delta ships no order.

The fixtures under ``fixtures/bingx_vst/`` are inputs and are never
edited here.  The ``RouterSymbolFilters`` each test hands the sizer are
built inline from ``contracts.json`` the way feature 1's translator
(:mod:`router.bingx_documents`) builds them at runtime — step as ten to
the minus ``quantityPrecision``, never the contract's ``size`` field —
so this suite stays independent of that parallel module while asserting
the same translation's arithmetic.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from book import final_target_weights
from router.errors import RouterError
from router.exchange_info import RouterSymbolFilters
from router.sizing import (
    ORDER_SIZING_CODE,
    RouterOrderSizingError,
    size_contract_deltas,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: The six symbols the recorded VST documents make sizeable — status 1
#: with a mark price.  NCFXUSD2ARS-USDT is held by the synthetic book
#: but status 25 and unmarked, and the spec records it as a refused leg
#: rather than an order.
TRADABLE = {
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "DOGE-USDT",
    "1000PEPE-USDT",
    "AGLD-USDT",
}


def _fixture(name: str) -> dict:
    """One recorded VST fixture, decoded verbatim from disk."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _synthetic_book() -> dict:
    """The hand-written Stage 0 book, as captured."""
    return _fixture("synthetic_book.json")


def _vst_filters() -> dict[str, RouterSymbolFilters]:
    """The tradable symbols' filters, built as feature 1 translates them.

    Step is ten to the minus ``quantityPrecision`` and tick ten to the
    minus ``pricePrecision`` — the ``size`` field is never read as the
    step, the constraint the spec states for ETH-USDT, SOL-USDT and
    five other symbols where the two differ.  A contract whose status is
    not 1 is not translated at all: feature 1 answers ``not_tradable``
    for it and the dry run records the refused leg, so what reaches the
    sizer is the six symbols the venue's own documents make sizeable.
    """
    filters: dict[str, RouterSymbolFilters] = {}
    for row in _fixture("contracts.json")["data"]:
        if row["status"] != 1:
            continue
        filters[row["symbol"]] = RouterSymbolFilters(
            symbol=row["symbol"],
            step_size=str(Decimal(1).scaleb(-int(row["quantityPrecision"]))),
            min_qty=str(row["tradeMinQuantity"]),
            max_qty=None,
            tick_size=str(Decimal(1).scaleb(-int(row["pricePrecision"]))),
            min_price=None,
            max_price=None,
            min_notional=str(row["tradeMinUSDT"]),
        )
    return filters


def _vst_marks() -> dict[str, Decimal]:
    """The Decimal mark per symbol, as feature 1's premiumIndex reader answers."""
    return {
        row["symbol"]: Decimal(row["markPrice"])
        for row in _fixture("premium_index.json")["data"]
    }


def _published(symbols: set[str]) -> object:
    """Publish the synthetic book's weights through feature 305's own seam.

    Only the seam, never a bare dict: ``final_target_weights`` is the
    act the spec's integration points name, and publishing through it is
    what makes these tests read the same floats — validated, frozen —
    that the dry run's order path reads.
    """
    raw = {
        symbol: weight
        for symbol, weight in _synthetic_book()["weights"].items()
        if symbol in symbols
    }
    return final_target_weights(SimpleNamespace(weights=raw))


def _one_filter(symbol: str, step: str | None) -> RouterSymbolFilters:
    """One symbol's filters with a hand-stated step grid and no other bounds.

    ``step=None`` is the translated document's own statement that it
    carries no quantity grid for the symbol — a fact the order path
    must be able to hand the sizer apart from a grid of any size.
    """
    return RouterSymbolFilters(
        symbol=symbol,
        step_size=step,
        min_qty=None,
        max_qty=None,
        tick_size=None,
        min_price=None,
        max_price=None,
        min_notional=None,
    )


def _filters_for(symbol: str, step: str) -> dict[str, RouterSymbolFilters]:
    """A one-symbol filters mapping with a hand-stated step grid."""
    return {symbol: _one_filter(symbol, step)}


def _publish_inline(weights: dict) -> object:
    """Publish a hand-written book through the same seam."""
    return final_target_weights(SimpleNamespace(weights=weights))


def test_synthetic_book_sizes_the_recorded_deltas() -> None:
    """The spec's own six numbers, exactly, as Decimal strings.

    Equity 10000 against the recorded marks: BTC-USDT's 0.2 weight is
    2000 ÷ 83137.3 ≈ 0.02406 contracts, truncated toward zero onto the
    0.0001 grid to 0.0240, minus the 0.0100 already held — the +0.0140
    the spec spells, trailing zero and all, because the grid's own
    spelling is the answer's.  DOGE-USDT's −0.05 is −5329.92… truncated
    *toward zero* onto the unit grid to −5329, not floored to −5330: a
    short target shrinks in magnitude the same way a long target is
    rounded down, and neither order exceeds its target.
    """
    book = _synthetic_book()
    deltas = size_contract_deltas(
        weights=_published(TRADABLE),
        equity=Decimal(book["equity_usdt"]),
        marks=_vst_marks(),
        filters=_vst_filters(),
        positions={
            symbol: Decimal(quantity)
            for symbol, quantity in book["positions"].items()
        },
    )
    assert deltas == {
        "BTC-USDT": Decimal("0.0140"),
        "ETH-USDT": Decimal("-0.558"),
        "SOL-USDT": Decimal("8.44"),
        "DOGE-USDT": Decimal(-5329),
        "1000PEPE-USDT": Decimal(69446),
        "AGLD-USDT": Decimal("4.84"),
    }
    # Exactly as Decimal strings — the spec's own spellings, including
    # BTC-USDT's trailing zero and the two integer-grid legs.
    assert {symbol: str(delta) for symbol, delta in deltas.items()} == {
        "BTC-USDT": "0.0140",
        "ETH-USDT": "-0.558",
        "SOL-USDT": "8.44",
        "DOGE-USDT": "-5329",
        "1000PEPE-USDT": "69446",
        "AGLD-USDT": "4.84",
    }
    # Symbols are answered in sorted order, so two sizings of one book
    # answer byte-identical mappings.
    assert list(deltas) == sorted(deltas)


def test_a_held_symbol_the_documents_cannot_size_is_refused_not_skipped() -> None:
    """The seven-weight publication against the six-symbol documents is refused.

    NCFXUSD2ARS-USDT is held at 0.02 by the synthetic book but its
    contract is status 25 and it carries no mark price, so the tradable
    documents cover six symbols.  Handing the sizer the full seven-weight
    publication against those six raises :class:`RouterOrderSizingError`
    naming the symbol — the leg the venue's own documents refuse is
    recorded where the documents were read (feature 1's
    ``not_tradable`` / ``missing_mark_price``), and sizing refuses
    rather than silently dropping a held weight or inventing a grid or
    a price for it.  The refusal is a :class:`RouterError`, this
    addition's new vocabulary subclassing the router's own base.
    """
    book = _synthetic_book()
    with pytest.raises(RouterOrderSizingError) as raised:
        size_contract_deltas(
            weights=_published(set(book["weights"])),
            equity=Decimal(book["equity_usdt"]),
            marks=_vst_marks(),
            filters=_vst_filters(),
            positions={},
        )
    assert issubclass(RouterOrderSizingError, RouterError)
    message = str(raised.value)
    assert message.startswith(f"{ORDER_SIZING_CODE}: ")
    assert "NCFXUSD2ARS-USDT" in message
    # The repair is named: record the refused leg, size what remains.
    assert "not_tradable" in message
    assert "missing_mark_price" in message


def test_a_held_symbol_with_no_mark_is_refused_by_name() -> None:
    """A leg the filters cover but the marks do not is refused, not priced at zero.

    A weight becomes a quantity only through a price; a mark invented
    here would be a hardcoded venue constant, and a skipped leg would be
    a held weight that silently never trades.
    """
    with pytest.raises(RouterOrderSizingError, match="no mark price is held") as raised:
        size_contract_deltas(
            weights=_publish_inline({"X-USDT": 0.1}),
            equity=Decimal(100),
            marks={},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )
    assert "X-USDT" in str(raised.value)


def test_a_zero_delta_ships_no_order() -> None:
    """A leg already at its target is omitted from the answer.

    Two ways to answer zero: a weight of 0.0 over a flat leg, and a
    held position that already sits exactly on the truncated target
    (BTC-USDT at 0.0240 against the recorded mark and grid).  Neither
    produces an order, and an all-flat book answers no deltas at all —
    the absence of a key, never a zero quantity an order would carry.
    """
    at_target = size_contract_deltas(
        weights=_publish_inline({"BTC-USDT": 0.2, "SOL-USDT": 0.1}),
        equity=Decimal(10000),
        marks={"BTC-USDT": Decimal("83137.3"), "SOL-USDT": Decimal("118.392")},
        filters={
            "BTC-USDT": _vst_filters()["BTC-USDT"],
            "SOL-USDT": _vst_filters()["SOL-USDT"],
        },
        # The position is the book's own string spelling, read verbatim.
        positions={"BTC-USDT": "0.0240"},
    )
    assert at_target == {"SOL-USDT": Decimal("8.44")}

    flat = size_contract_deltas(
        weights=_publish_inline({"FLAT-USDT": 0.0}),
        equity=Decimal(10000),
        marks={"FLAT-USDT": Decimal(1)},
        filters=_filters_for("FLAT-USDT", "1"),
        positions={},
    )
    assert flat == {}


def test_quantities_truncate_toward_zero_so_an_order_never_exceeds_its_target() -> None:
    """Both signs truncate toward zero: +10.05 becomes +10 and −10.05 becomes −10.

    Equity 100 at weight ±1.0 against a 9.95 mark is ±10.0502… contracts;
    the 2-contract grid keeps ±10, the neighbour nearer zero on both
    sides.  Flooring instead of truncating would answer −12 for the
    short leg — one grid step *more* short than the book decided — and
    rounding to nearest could answer +12; the sentence's truncation
    toward zero is what makes an order never exceed its target on
    either side.
    """
    deltas = size_contract_deltas(
        weights=_publish_inline({"LONG-USDT": 1.0, "SHORT-USDT": -1.0}),
        equity=Decimal(100),
        marks={"LONG-USDT": Decimal("9.95"), "SHORT-USDT": Decimal("9.95")},
        filters={
            "LONG-USDT": _one_filter("LONG-USDT", "2"),
            "SHORT-USDT": _one_filter("SHORT-USDT", "2"),
        },
        positions={},
    )
    assert deltas == {
        "LONG-USDT": Decimal(10),
        "SHORT-USDT": Decimal(-10),
    }


def test_weights_are_decimalized_from_their_shortest_spelling() -> None:
    """A float weight is read as the number the book wrote, never as its binary expansion.

    The seam publishes weights as floats, so the sizer decimalizes them
    once, through ``str``: 0.1 is exactly ``Decimal("0.1")``.  On a
    10⁻¹⁸ grid the distinction is observable — three times the *decimal*
    0.1 against a 1 mark is exactly 0.3, while the binary expansion the
    float also carries would leave a 0.3000000000000000166… tail.  A
    weight spelled with an exponent (``1e-09``) decimalizes the same
    way.
    """
    decimal_spelling = size_contract_deltas(
        weights=_publish_inline({"W-USDT": 0.1}),
        equity=Decimal(3),
        marks={"W-USDT": Decimal(1)},
        filters=_filters_for("W-USDT", "0.000000000000000001"),
        positions={},
    )
    assert decimal_spelling == {"W-USDT": Decimal("0.3")}

    exponent_spelling = size_contract_deltas(
        weights=_publish_inline({"E-USDT": 1e-09}),
        equity=Decimal(1000000000),
        marks={"E-USDT": Decimal(1)},
        filters=_filters_for("E-USDT", "1"),
        positions={},
    )
    assert exponent_spelling == {"E-USDT": Decimal(1)}


def test_an_unpublished_book_of_bare_dicts_is_refused() -> None:
    """A bare dict is a book nothing published, and sizing refuses it.

    The spec's integration points are explicit that the weights arrive
    *"through feature 305's seam rather than as a bare dict"*: the seam
    is what stands between the order layer and arithmetic no
    construction answered for.
    """
    with pytest.raises(RouterOrderSizingError) as raised:
        size_contract_deltas(
            weights={"X-USDT": 0.1},
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )
    message = str(raised.value)
    assert message.startswith(f"{ORDER_SIZING_CODE}: ")
    assert "final_target_weights" in message


def test_a_blank_symbol_in_the_book_is_refused() -> None:
    """A weight keyed by no name routes nowhere, so it is refused.

    The seam's own publication refuses a blank symbol; the sizer judges
    the surface it reads independently, because it reads the record
    duck-typed rather than trusting the publisher.
    """
    with pytest.raises(
        RouterOrderSizingError, match="non-empty symbol names"
    ):
        size_contract_deltas(
            weights=SimpleNamespace(weights={"   ": 0.1}),
            equity=Decimal(100),
            marks={"   ": Decimal(1)},
            filters=_filters_for("   ", "1"),
            positions={},
        )


def test_an_empty_publication_is_refused() -> None:
    """A book covering no symbols is the absence of an instruction, not a flat one."""
    with pytest.raises(RouterOrderSizingError, match="at least one symbol"):
        size_contract_deltas(
            weights=SimpleNamespace(weights={}),
            equity=Decimal(100),
            marks={},
            filters={},
            positions={},
        )


def test_filters_for_another_symbol_are_refused() -> None:
    """A quantity truncated onto another symbol's grid is a size about the wrong instrument."""
    with pytest.raises(RouterOrderSizingError) as raised:
        size_contract_deltas(
            weights=_publish_inline({"X-USDT": 0.1}),
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            # Filed under X-USDT but carrying another symbol's own name:
            # the entry exists, and it is the wrong instrument's.
            filters={"X-USDT": _one_filter("OTHER-USDT", "1")},
            positions={},
        )
    message = str(raised.value)
    assert "X-USDT" in message
    assert "OTHER-USDT" in message


def test_a_symbol_with_no_step_grid_is_refused() -> None:
    """A leg the venue states no quantity grid for cannot be sized onto one.

    ``step_size=None`` is the translated document's own statement that
    it carries no grid for the symbol; defaulting one here would be the
    hardcoded venue constant feature 311 forbids.
    """
    with pytest.raises(
        RouterOrderSizingError, match="states no step size"
    ):
        size_contract_deltas(
            weights=_publish_inline({"X-USDT": 0.1}),
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            filters={"X-USDT": _one_filter("X-USDT", None)},
            positions={},
        )


def test_a_nonpositive_mark_is_refused() -> None:
    """A mark at or below zero is not a price any venue can mark at."""
    for bad in ("0", "-1"):
        with pytest.raises(RouterOrderSizingError, match="must be positive"):
            size_contract_deltas(
                weights=_publish_inline({"X-USDT": 0.1}),
                equity=Decimal(100),
                marks={"X-USDT": Decimal(bad)},
                filters=_filters_for("X-USDT", "1"),
                positions={},
            )


def test_float_terms_are_refused_by_name() -> None:
    """Equity and positions are read exactly, and a float is refused naming it.

    The one float the seam legitimately carries — a weight — is
    decimalized by name; every other term is the book's or the venue's
    own spelling, and binary approximation never enters the arithmetic.
    """
    with pytest.raises(RouterOrderSizingError) as raised:
        size_contract_deltas(
            weights=_publish_inline({"X-USDT": 0.1}),
            equity=10000.0,
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )
    assert "float" in str(raised.value)

    with pytest.raises(RouterOrderSizingError) as raised:
        size_contract_deltas(
            weights=_publish_inline({"X-USDT": 0.1}),
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={"X-USDT": 0.5},
        )
    assert "float" in str(raised.value)


def test_negative_equity_is_refused_and_zero_equity_flattens() -> None:
    """A negative equity is a book no account holds; a zero equity is the flatten book.

    Zero is sized: every target is zero and every delta is the negative
    of the position held, which is what closing out means.
    """
    with pytest.raises(RouterOrderSizingError, match="must not be negative"):
        size_contract_deltas(
            weights=_publish_inline({"X-USDT": 0.5}),
            equity=Decimal(-1),
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )

    flattening = size_contract_deltas(
        weights=_publish_inline({"X-USDT": 0.5, "Y-USDT": -0.25}),
        equity=Decimal(0),
        marks={"X-USDT": Decimal(1), "Y-USDT": Decimal(1)},
        filters={
            "X-USDT": _filters_for("X-USDT", "1")["X-USDT"],
            "Y-USDT": _filters_for("Y-USDT", "1")["Y-USDT"],
        },
        positions={"X-USDT": Decimal(7), "Y-USDT": Decimal(0)},
    )
    assert flattening == {"X-USDT": Decimal(-7)}


def test_positions_and_documents_beyond_the_book_are_left_alone() -> None:
    """Extra marks, extra filters and unheld positions neither trade nor refuse.

    A position in a symbol the published weights do not carry is left
    where it stands: the instruction names no weight for it, and
    inventing a flatten would be a position decision the construction
    never made.  Marks and filters for symbols the book does not hold
    are simply unused.
    """
    deltas = size_contract_deltas(
        weights=_publish_inline({"X-USDT": 0.5}),
        equity=Decimal(100),
        marks={"X-USDT": Decimal(1), "EXTRA-USDT": Decimal(5)},
        filters={
            "X-USDT": _filters_for("X-USDT", "1")["X-USDT"],
            "EXTRA-USDT": _filters_for("EXTRA-USDT", "1")["EXTRA-USDT"],
        },
        positions={"X-USDT": Decimal(0), "GHOST-USDT": Decimal(123)},
    )
    assert deltas == {"X-USDT": Decimal(50)}


def test_a_weight_that_is_not_a_finite_real_is_refused() -> None:
    """A NaN dressed as a number and a weight spelled as a string are both refused.

    Publication itself refuses these; the sizer reads the surface
    duck-typed and holds it to the same terms, because a weight that is
    not a finite real is not a size any venue could hold.  The NaN is
    refused in both spellings it could arrive in — a float off a book
    something else assembled, and an exact ``Decimal("NaN")`` — since a
    non-finite weight would otherwise decimalize into a delta that
    compares false against zero and ships as an order.
    """
    with pytest.raises(RouterOrderSizingError, match="not finite"):
        size_contract_deltas(
            weights=SimpleNamespace(weights={"X-USDT": float("nan")}),
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )

    with pytest.raises(RouterOrderSizingError, match="not finite"):
        size_contract_deltas(
            weights=SimpleNamespace(weights={"X-USDT": Decimal("NaN")}),
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )

    with pytest.raises(RouterOrderSizingError, match="finite real"):
        size_contract_deltas(
            weights=SimpleNamespace(weights={"X-USDT": "0.5"}),
            equity=Decimal(100),
            marks={"X-USDT": Decimal(1)},
            filters=_filters_for("X-USDT", "1"),
            positions={},
        )
