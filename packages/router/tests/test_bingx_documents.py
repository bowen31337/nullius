"""Feature 1's venue documents: BingX contracts and BingX mark prices.

``router.bingx_documents`` is a second, BingX-specific constructor of feature
310's ``RouterSymbolFilters`` — ``router.exchange_info`` stays
Binance-shaped and unchanged — plus the reader that turns a premiumIndex
document into a ``Decimal`` mark price per symbol.

The recorded fixtures under ``tests/fixtures/bingx_vst/`` are the primary
evidence and are asserted exactly, as ``Decimal`` strings: they were
captured verbatim from ``open-api-vst.bingx.com`` and are inputs, never
edited.  Every refusal path is pinned against small inline documents, so a
defect names itself instead of hiding behind the capture.

The shape of the translator's answer is itself part of what the recorded
fixture settles.  That document holds six tradable contracts *and* one the
venue has closed, so the feature's worked example — the six grid values and
the ``not_tradable`` refusal, from one call — can only be satisfied by an
answer that carries both.  ``BingXContracts`` is that answer, and these
tests pin that the two halves come back together.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest
from router.bingx_documents import (
    MARK_PRICE_CODE,
    NOT_TRADABLE_CODE,
    BingXContracts,
    RouterMarkPriceError,
    RouterNotTradableError,
    RouterVehicleDocumentError,
    resolve_bingx_filters,
    resolve_bingx_mark_prices,
)
from router.errors import RouterError
from router.exchange_info import RouterSymbolFilters

FIXTURES = Path(__file__).parent / "fixtures" / "bingx_vst"

#: The six contracts the recorded document lists as tradable, with the
#: values the feature sentence promises: step size as ten to the minus
#: ``quantityPrecision``, tick size as ten to the minus ``pricePrecision``,
#: ``min_qty`` from ``tradeMinQuantity`` and ``min_notional`` from
#: ``tradeMinUSDT``.
TRADABLE = {
    "BTC-USDT": ("0.0001", "0.1", "0.0001", "2"),
    "ETH-USDT": ("0.001", "0.01", "0.001", "2"),
    "SOL-USDT": ("0.01", "0.001", "0.02", "2"),
    "DOGE-USDT": ("1", "0.00001", "22", "2"),
    "1000PEPE-USDT": ("1", "0.0000001", "464", "2"),
    "AGLD-USDT": ("0.01", "0.0001", "9.7", "2"),
}

#: The one contract the recorded document lists but will not trade:
#: ``status`` 25, and no mark price in the premiumIndex capture.
NOT_TRADABLE_SYMBOL = "NCFXUSD2ARS-USDT"


def _fixture(name: str) -> dict:
    """Load a recorded fixture as decoded JSON.  Never written to."""

    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def contracts_document() -> dict:
    return _fixture("contracts.json")


@pytest.fixture
def premium_index_document() -> dict:
    return _fixture("premium_index.json")


@pytest.fixture
def synthetic_book() -> dict:
    return _fixture("synthetic_book.json")


def _contract(**overrides: object) -> dict:
    """A minimal, tradable BingX contract row, shaped as the wire format is.

    Small enough that one overridden field is visibly the defect under test.
    """

    row = {
        "symbol": "TEST-USDT",
        "size": "0.01",
        "quantityPrecision": 2,
        "pricePrecision": 3,
        "tradeMinQuantity": 0.5,
        "tradeMinUSDT": 2,
        "status": 1,
        "apiStateOpen": "true",
    }
    row.update(overrides)
    return row


def _documents(*rows: dict) -> dict:
    return {"code": 0, "msg": "", "data": list(rows)}


def _translate(*rows: dict) -> BingXContracts:
    """Translate a document built from rows, for the inline-document tests."""

    return resolve_bingx_filters(_documents(*rows))


class TestTheRecordedContractsFixture:
    """The feature's own worked example, asserted exactly."""

    def test_every_tradable_symbol_carries_the_promised_grids(
        self, contracts_document: dict
    ) -> None:
        translated = resolve_bingx_filters(contracts_document)
        assert set(translated.filters) == set(TRADABLE)
        for symbol, (step, tick, min_qty, min_notional) in TRADABLE.items():
            filters = translated.filters[symbol]
            assert isinstance(filters, RouterSymbolFilters)
            assert filters.symbol == symbol
            # Asserted as the exact strings the feature's own example
            # spells: a grid is a decimal spelling, and Decimal("0.001") ==
            # Decimal("0.0010") — or an exponent like 1E-7 — would hide a
            # re-spelling.  Decimal() then checks the value too.
            assert filters.step_size == step
            assert filters.tick_size == tick
            assert filters.min_qty == min_qty
            assert filters.min_notional == min_notional
            assert Decimal(filters.step_size) == Decimal(step)

    def test_btc_usdt_is_step_four_tick_one(
        self, contracts_document: dict
    ) -> None:
        btc = resolve_bingx_filters(contracts_document).filters["BTC-USDT"]
        assert btc.step_size == "0.0001"
        assert btc.tick_size == "0.1"
        assert btc.min_qty == "0.0001"
        assert btc.min_notional == "2"

    def test_eth_usdt_is_step_three_tick_two_min_qty_three(
        self, contracts_document: dict
    ) -> None:
        eth = resolve_bingx_filters(contracts_document).filters["ETH-USDT"]
        assert eth.step_size == "0.001"
        assert eth.tick_size == "0.01"
        assert eth.min_qty == "0.001"
        assert eth.min_notional == "2"

    def test_the_six_grids_and_the_refusal_come_back_from_one_call(
        self, contracts_document: dict
    ) -> None:
        # The whole of feature 1's worked example, from the recorded fixture:
        # BTC-USDT step 0.0001 tick 0.1, ETH-USDT step 0.001 tick 0.01
        # min_qty 0.001, and a not_tradable refusal for NCFXUSD2ARS-USDT.
        translated = resolve_bingx_filters(contracts_document)
        assert translated.filters["BTC-USDT"].step_size == "0.0001"
        assert translated.filters["BTC-USDT"].tick_size == "0.1"
        assert translated.filters["ETH-USDT"].step_size == "0.001"
        assert translated.filters["ETH-USDT"].tick_size == "0.01"
        assert translated.filters["ETH-USDT"].min_qty == "0.001"
        assert set(translated.refusals) == {NOT_TRADABLE_SYMBOL}

    def test_bounds_bingx_does_not_publish_are_honestly_none(
        self, contracts_document: dict
    ) -> None:
        for filters in resolve_bingx_filters(contracts_document).filters.values():
            assert filters.max_qty is None
            assert filters.min_price is None
            assert filters.max_price is None

    def test_min_qty_keeps_the_venue_spelling_not_a_float(
        self, contracts_document: dict
    ) -> None:
        # AGLD-USDT's tradeMinQuantity is the JSON number 9.7; the value
        # recorded is the venue's own decimal spelling, never a binary
        # approximation of it.
        agld = resolve_bingx_filters(contracts_document).filters["AGLD-USDT"]
        assert agld.min_qty == "9.7"
        assert isinstance(agld.min_qty, str)

    def test_the_not_tradable_contract_is_refused_naming_itself(
        self, contracts_document: dict
    ) -> None:
        refusal = resolve_bingx_filters(contracts_document).refusals[
            NOT_TRADABLE_SYMBOL
        ]
        assert isinstance(refusal, RouterNotTradableError)
        assert refusal.symbol == NOT_TRADABLE_SYMBOL
        assert str(refusal).startswith(NOT_TRADABLE_CODE)
        assert NOT_TRADABLE_SYMBOL in str(refusal)
        assert refusal.code == NOT_TRADABLE_CODE

    def test_the_refused_contract_is_not_also_translated(
        self, contracts_document: dict
    ) -> None:
        translated = resolve_bingx_filters(contracts_document)
        assert NOT_TRADABLE_SYMBOL not in translated.filters

    def test_symbols_lists_the_whole_document_in_order(
        self, contracts_document: dict
    ) -> None:
        translated = resolve_bingx_filters(contracts_document)
        assert translated.symbols == tuple(
            row["symbol"] for row in contracts_document["data"]
        )

    def test_lookup_by_symbol_answers_filters_or_the_refusal(
        self, contracts_document: dict
    ) -> None:
        # The feature's shape is one answer per symbol: ask by the symbol
        # the book holds, branch on what comes back.
        translated = resolve_bingx_filters(contracts_document)
        assert isinstance(translated["BTC-USDT"], RouterSymbolFilters)
        assert translated["BTC-USDT"].step_size == "0.0001"
        assert isinstance(
            translated[NOT_TRADABLE_SYMBOL], RouterNotTradableError
        )
        assert translated[NOT_TRADABLE_SYMBOL].symbol == NOT_TRADABLE_SYMBOL

    def test_lookup_membership_and_iteration_span_both_halves(
        self, contracts_document: dict
    ) -> None:
        translated = resolve_bingx_filters(contracts_document)
        assert NOT_TRADABLE_SYMBOL in translated
        assert "BTC-USDT" in translated
        assert "NEVER-LISTED-USDT" not in translated
        assert tuple(translated) == translated.symbols
        assert len(translated) == len(translated.symbols)

    def test_a_symbol_the_document_never_named_is_a_key_error(
        self, contracts_document: dict
    ) -> None:
        # An absent symbol must not look answered just because the answer is
        # split across two fields.
        translated = resolve_bingx_filters(contracts_document)
        with pytest.raises(KeyError):
            translated["NEVER-LISTED-USDT"]

    def test_a_plan_walking_the_book_branches_on_the_answer_type(
        self, contracts_document: dict, synthetic_book: dict
    ) -> None:
        # What feature 4 will do: walk the book's own symbols in the book's
        # own order and sort each into an order or a refusal.
        translated = resolve_bingx_filters(contracts_document)
        ordered, refused = [], []
        for symbol in synthetic_book["weights"]:
            answer = translated[symbol]
            if isinstance(answer, RouterNotTradableError):
                refused.append(answer.symbol)
            else:
                ordered.append(answer.symbol)
        assert ordered == [
            "BTC-USDT",
            "ETH-USDT",
            "SOL-USDT",
            "DOGE-USDT",
            "1000PEPE-USDT",
            "AGLD-USDT",
        ]
        assert refused == [NOT_TRADABLE_SYMBOL]


class TestTheSizeFieldIsNeverTheStep:
    """The constraint the recorded fixture exists to catch."""

    def test_eth_usdt_step_is_the_precision_not_the_size_field(
        self, contracts_document: dict
    ) -> None:
        row = next(
            r for r in contracts_document["data"] if r["symbol"] == "ETH-USDT"
        )
        # The trap, stated as a test: size is 0.01, the step is 0.001.
        assert row["size"] == "0.01"
        assert row["quantityPrecision"] == 3
        assert _translate(row).filters["ETH-USDT"].step_size == "0.001"

    def test_every_recorded_symbol_takes_the_step_from_the_precision(
        self, contracts_document: dict
    ) -> None:
        for row in contracts_document["data"]:
            if row["status"] != 1:
                continue
            step = Decimal(_translate(row).filters[row["symbol"]].step_size)
            assert step == Decimal(10) ** -row["quantityPrecision"]

    def test_every_recorded_symbol_takes_the_tick_from_the_price_precision(
        self, contracts_document: dict
    ) -> None:
        for row in contracts_document["data"]:
            if row["status"] != 1:
                continue
            tick = Decimal(_translate(row).filters[row["symbol"]].tick_size)
            assert tick == Decimal(10) ** -row["pricePrecision"]

    def test_sol_usdt_size_of_one_is_not_a_step_of_one(
        self, contracts_document: dict
    ) -> None:
        row = next(
            r for r in contracts_document["data"] if r["symbol"] == "SOL-USDT"
        )
        assert row["size"] == "1"
        assert _translate(row).filters["SOL-USDT"].step_size == "0.01"

    def test_a_zero_precision_is_a_step_of_one(self) -> None:
        # DOGE-USDT and 1000PEPE-USDT are both quantityPrecision 0, and the
        # step there is exactly one contract — not zero, and not absent.
        translated = _translate(_contract(quantityPrecision=0))
        assert translated.filters["TEST-USDT"].step_size == "1"

    def test_the_size_field_could_be_anything_and_the_step_is_unchanged(
        self,
    ) -> None:
        # ``size`` is not read at all: whatever it says, the grid is the
        # precision's.  This is the constraint made mechanical.
        for size in ("0.01", "1", "999", None):
            translated = _translate(_contract(size=size))
            assert translated.filters["TEST-USDT"].step_size == "0.01"


class TestNotTradableRefusals:
    def test_a_status_other_than_one_is_not_tradable(self) -> None:
        translated = _translate(_contract(status=25))
        refusal = translated.refusals["TEST-USDT"]
        assert refusal.symbol == "TEST-USDT"
        assert "25" in str(refusal)
        assert translated.filters == {}

    def test_a_closed_api_state_is_not_tradable(self) -> None:
        translated = _translate(_contract(apiStateOpen="false"))
        assert set(translated.refusals) == {"TEST-USDT"}

    def test_the_json_boolean_true_is_not_the_string_the_feature_states(
        self,
    ) -> None:
        translated = _translate(_contract(apiStateOpen=True))
        assert set(translated.refusals) == {"TEST-USDT"}

    def test_a_status_spelled_as_a_string_is_not_the_number_one(self) -> None:
        translated = _translate(_contract(status="1"))
        assert set(translated.refusals) == {"TEST-USDT"}

    def test_the_boolean_true_is_not_the_number_one(self) -> None:
        translated = _translate(_contract(status=True))
        assert set(translated.refusals) == {"TEST-USDT"}

    def test_a_refusal_does_not_stop_the_rest_of_the_document(self) -> None:
        translated = _translate(
            _contract(symbol="AAA-USDT", status=25),
            _contract(symbol="BBB-USDT", status=1),
        )
        assert set(translated.refusals) == {"AAA-USDT"}
        assert set(translated.filters) == {"BBB-USDT"}

    def test_document_order_is_kept_across_both_halves(self) -> None:
        translated = _translate(
            _contract(symbol="AAA-USDT", status=1),
            _contract(symbol="BBB-USDT", status=25),
            _contract(symbol="CCC-USDT", status=1),
        )
        assert tuple(translated.filters) == ("AAA-USDT", "CCC-USDT")
        assert tuple(translated.refusals) == ("BBB-USDT",)
        assert translated.symbols == ("AAA-USDT", "BBB-USDT", "CCC-USDT")

    def test_the_refusal_is_a_router_error_and_a_value_error(self) -> None:
        refusal = _translate(_contract(status=25)).refusals["TEST-USDT"]
        assert isinstance(refusal, RouterError)
        assert isinstance(refusal, ValueError)

    def test_the_refusal_can_be_raised_by_a_caller_that_wants_one(
        self,
    ) -> None:
        # The value is an exception, so a caller walking the book's own
        # symbols raises it rather than re-spelling the message.
        refusal = _translate(_contract(status=25)).refusals["TEST-USDT"]
        with pytest.raises(RouterNotTradableError) as caught:
            raise refusal
        assert caught.value.symbol == "TEST-USDT"


class TestMalformedContractsDocuments:
    def test_not_json(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_filters(b"{not json")

    def test_not_an_object(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_filters([1, 2, 3])

    def test_no_data_list(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_filters({"code": 0, "msg": "", "data": {}})

    def test_a_row_that_is_not_an_object(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_filters({"code": 0, "data": ["BTC-USDT"]})

    def test_a_row_that_states_no_symbol(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_filters(_documents({**_contract(), "symbol": None}))

    def test_a_row_that_states_no_status(self) -> None:
        row = _contract()
        del row["status"]
        with pytest.raises(RouterVehicleDocumentError):
            _translate(row)

    def test_a_row_that_states_no_api_state(self) -> None:
        row = _contract()
        del row["apiStateOpen"]
        with pytest.raises(RouterVehicleDocumentError):
            _translate(row)

    def test_a_missing_quantity_precision_is_refused(self) -> None:
        row = _contract()
        del row["quantityPrecision"]
        with pytest.raises(RouterVehicleDocumentError):
            _translate(row)

    def test_a_missing_price_precision_is_refused(self) -> None:
        row = _contract()
        del row["pricePrecision"]
        with pytest.raises(RouterVehicleDocumentError):
            _translate(row)

    def test_a_negative_precision_is_not_a_grid(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            _translate(_contract(quantityPrecision=-1))

    def test_a_boolean_precision_is_not_a_precision(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            _translate(_contract(quantityPrecision=True))

    def test_a_fractional_precision_is_not_a_precision(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            _translate(_contract(pricePrecision=2.5))

    def test_a_missing_min_quantity_is_refused(self) -> None:
        row = _contract()
        del row["tradeMinQuantity"]
        with pytest.raises(RouterVehicleDocumentError):
            _translate(row)

    def test_a_missing_min_notional_is_refused(self) -> None:
        row = _contract()
        del row["tradeMinUSDT"]
        with pytest.raises(RouterVehicleDocumentError):
            _translate(row)

    def test_a_min_notional_that_is_not_a_decimal_is_refused(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            _translate(_contract(tradeMinUSDT="two dollars"))

    def test_a_malformed_document_error_is_a_router_error(self) -> None:
        with pytest.raises(RouterError):
            resolve_bingx_filters(b"{not json")

    def test_the_malformed_refusal_is_not_the_not_tradable_refusal(self) -> None:
        # Different repairs: a bad fetch is not a closed contract, and a
        # caller that catches only the latter must not swallow the former.
        with pytest.raises(RouterVehicleDocumentError) as caught:
            resolve_bingx_filters(b"{not json")
        assert not isinstance(caught.value, RouterNotTradableError)

    def test_a_bad_row_before_a_closed_contract_still_refuses_the_fetch(
        self,
    ) -> None:
        # A malformed document raises; it never comes back as a carried
        # refusal, because there is no answer to carry.
        with pytest.raises(RouterVehicleDocumentError):
            _translate(
                _contract(symbol="AAA-USDT", quantityPrecision="two"),
                _contract(symbol="BBB-USDT", status=25),
            )

    def test_a_duplicated_symbol_is_refused(self) -> None:
        # The ingest member's exchangeInfo parser refuses a duplicated
        # symbol too; keeping the last row would let two answers to one
        # question both stand.
        with pytest.raises(RouterVehicleDocumentError):
            _translate(_contract(symbol="AAA-USDT"), _contract(symbol="AAA-USDT"))

    def test_a_duplicated_symbol_is_refused_even_when_only_one_row_is_closed(
        self,
    ) -> None:
        # Without the refusal this symbol would land in *both* halves of the
        # translation, leaving __getitem__ to pick a winner the document
        # never chose.
        with pytest.raises(RouterVehicleDocumentError):
            _translate(
                _contract(symbol="AAA-USDT", status=1),
                _contract(symbol="AAA-USDT", status=25),
            )

    def test_an_empty_data_list_translates_to_two_empty_mappings(self) -> None:
        translated = resolve_bingx_filters({"code": 0, "data": []})
        assert translated.filters == {}
        assert translated.refusals == {}
        assert translated.symbols == ()


class TestDocumentSpellings:
    def test_accepts_the_recorded_json_bytes(self) -> None:
        raw = (FIXTURES / "contracts.json").read_bytes()
        translated = resolve_bingx_filters(raw)
        assert set(translated.filters) == set(TRADABLE)
        assert set(translated.refusals) == {NOT_TRADABLE_SYMBOL}

    def test_accepts_the_document_as_a_json_string(self) -> None:
        text = json.dumps(_documents(_contract()))
        assert set(resolve_bingx_filters(text).filters) == {"TEST-USDT"}

    def test_accepts_the_document_as_a_mapping(
        self, contracts_document: dict
    ) -> None:
        assert resolve_bingx_filters(contracts_document).filters


class TestTheRecordedPremiumIndexFixture:
    def test_btc_and_doge_are_the_feature_s_own_example(
        self, premium_index_document: dict
    ) -> None:
        marks = resolve_bingx_mark_prices(premium_index_document)
        assert marks["BTC-USDT"] == Decimal("83137.3")
        assert str(marks["BTC-USDT"]) == "83137.3"
        assert marks["DOGE-USDT"] == Decimal("0.09381")
        assert str(marks["DOGE-USDT"]) == "0.09381"

    def test_every_priced_symbol_is_returned_as_an_exact_decimal(
        self, premium_index_document: dict
    ) -> None:
        marks = resolve_bingx_mark_prices(premium_index_document)
        assert set(marks) == {
            "BTC-USDT",
            "ETH-USDT",
            "SOL-USDT",
            "DOGE-USDT",
            "AGLD-USDT",
            "1000PEPE-USDT",
        }
        assert all(isinstance(mark, Decimal) for mark in marks.values())
        assert marks["1000PEPE-USDT"] == Decimal("0.0043199")

    def test_the_capture_prices_no_not_tradable_symbol(
        self, premium_index_document: dict
    ) -> None:
        # Stage 0's two documents agree: the contract the venue will not
        # trade is also the one it publishes no mark for.
        assert NOT_TRADABLE_SYMBOL not in resolve_bingx_mark_prices(
            premium_index_document
        )

    def test_the_tradable_symbols_are_exactly_the_priced_ones(
        self, contracts_document: dict, premium_index_document: dict
    ) -> None:
        translated = resolve_bingx_filters(contracts_document)
        marks = resolve_bingx_mark_prices(premium_index_document)
        assert set(translated.filters) == set(marks)

    def test_the_book_s_held_symbols_are_all_priced(
        self, premium_index_document: dict, synthetic_book: dict
    ) -> None:
        held = set(synthetic_book["weights"])
        checked = resolve_bingx_mark_prices(
            premium_index_document, held - {NOT_TRADABLE_SYMBOL}
        )
        assert held - {NOT_TRADABLE_SYMBOL} <= set(checked)


class TestMissingMarkPriceRefusals:
    def test_a_held_symbol_with_no_mark_names_itself(
        self, premium_index_document: dict
    ) -> None:
        with pytest.raises(RouterMarkPriceError) as caught:
            resolve_bingx_mark_prices(
                premium_index_document, [NOT_TRADABLE_SYMBOL]
            )
        assert caught.value.symbol == NOT_TRADABLE_SYMBOL
        assert str(caught.value).startswith(MARK_PRICE_CODE)
        assert NOT_TRADABLE_SYMBOL in str(caught.value)
        assert caught.value.code == MARK_PRICE_CODE

    def test_the_first_missing_held_symbol_in_order_wins(
        self, premium_index_document: dict
    ) -> None:
        with pytest.raises(RouterMarkPriceError) as caught:
            resolve_bingx_mark_prices(
                premium_index_document, ["DOGE-USDT", "AAA-USDT", "BBB-USDT"]
            )
        assert caught.value.symbol == "AAA-USDT"

    def test_a_held_symbol_whose_mark_is_null_is_missing(self) -> None:
        document = _documents({"symbol": "AAA-USDT", "markPrice": None})
        with pytest.raises(RouterMarkPriceError) as caught:
            resolve_bingx_mark_prices(document, ["AAA-USDT"])
        assert caught.value.symbol == "AAA-USDT"

    def test_no_held_symbols_means_no_check(
        self, premium_index_document: dict
    ) -> None:
        # ``None`` is "no check asked for"; the whole priced document comes
        # back rather than an empty mapping.
        marks = resolve_bingx_mark_prices(premium_index_document, None)
        assert "BTC-USDT" in marks

    def test_an_empty_held_collection_is_a_real_ask(
        self, premium_index_document: dict
    ) -> None:
        marks = resolve_bingx_mark_prices(premium_index_document, [])
        assert marks["BTC-USDT"] == Decimal("83137.3")

    def test_symbols_the_book_does_not_hold_are_still_returned(self) -> None:
        document = _documents(
            {"symbol": "AAA-USDT", "markPrice": "1.5"},
            {"symbol": "BBB-USDT", "markPrice": "2.5"},
        )
        marks = resolve_bingx_mark_prices(document, ["AAA-USDT"])
        assert marks == {"AAA-USDT": Decimal("1.5"), "BBB-USDT": Decimal("2.5")}

    def test_a_held_symbol_with_no_row_at_all_is_missing(self) -> None:
        document = _documents({"symbol": "AAA-USDT", "markPrice": "1"})
        with pytest.raises(RouterMarkPriceError):
            resolve_bingx_mark_prices(document, ["NEVER-LISTED-USDT"])

    def test_a_held_symbol_that_cannot_be_one_is_a_bad_ask_not_a_bad_fetch(
        self,
    ) -> None:
        # Handing the book *document* rather than the symbols it holds is a
        # caller's bug: iterating that mapping would walk its fields and
        # report the venue as having no mark for "book_id", sending the
        # caller to re-fetch a document that was never wrong.
        held = {"book_id": "synthetic-vst-0", "weights": {"BTC-USDT": 0.2}}
        with pytest.raises(RouterVehicleDocumentError) as caught:
            resolve_bingx_mark_prices(_documents(), held)
        assert not isinstance(caught.value, RouterMarkPriceError)
        assert "dict" in str(caught.value)

    def test_a_bare_symbol_string_is_chars_not_one_symbol(self) -> None:
        # ``symbols`` is a collection; a string iterates its characters and
        # the first one cannot be a held symbol, so the bad ask is refused
        # rather than answered with a missing_mark_price for "B".
        document = _documents({"symbol": "BTC-USDT", "markPrice": "1"})
        with pytest.raises(RouterVehicleDocumentError) as caught:
            resolve_bingx_mark_prices(document, "BTC-USDT")
        assert not isinstance(caught.value, RouterMarkPriceError)

    def test_a_single_held_symbol_is_a_one_element_collection(self) -> None:
        # The right way to ask about one symbol — and the answer is the
        # whole priced document, as for any other ask.
        document = _documents(
            {"symbol": "AAA-USDT", "markPrice": "1"},
            {"symbol": "BBB-USDT", "markPrice": "2"},
        )
        marks = resolve_bingx_mark_prices(document, ["AAA-USDT"])
        assert marks == {"AAA-USDT": Decimal(1), "BBB-USDT": Decimal(2)}

    def test_the_refusal_is_a_router_error_and_a_value_error(self) -> None:
        document = _documents({"symbol": "AAA-USDT", "markPrice": "1"})
        with pytest.raises(RouterError):
            resolve_bingx_mark_prices(document, ["ZZZ-USDT"])
        with pytest.raises(ValueError):
            resolve_bingx_mark_prices(document, ["ZZZ-USDT"])

    def test_the_refusal_is_not_the_not_tradable_refusal(self) -> None:
        document = _documents({"symbol": "AAA-USDT", "markPrice": "1"})
        with pytest.raises(RouterMarkPriceError) as caught:
            resolve_bingx_mark_prices(document, ["ZZZ-USDT"])
        assert not isinstance(caught.value, RouterNotTradableError)


class TestMalformedPremiumIndexDocuments:
    def test_not_json(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices("{oops")

    def test_no_data_list(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices({"code": 0, "data": None})

    def test_a_row_that_is_not_an_object(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices({"code": 0, "data": [3]})

    def test_a_row_that_states_no_symbol(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices(_documents({"markPrice": "1"}))

    def test_a_mark_that_is_not_a_decimal_is_refused(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices(
                _documents({"symbol": "AAA-USDT", "markPrice": "cheap"})
            )

    def test_a_mark_that_is_a_collection_is_refused(self) -> None:
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices(
                _documents({"symbol": "AAA-USDT", "markPrice": ["1"]})
            )

    def test_the_malformed_refusal_is_not_the_missing_mark_refusal(self) -> None:
        with pytest.raises(RouterVehicleDocumentError) as caught:
            resolve_bingx_mark_prices("{oops")
        assert not isinstance(caught.value, RouterMarkPriceError)

    def test_a_duplicated_symbol_is_refused(self) -> None:
        document = _documents(
            {"symbol": "AAA-USDT", "markPrice": "1"},
            {"symbol": "AAA-USDT", "markPrice": "2"},
        )
        with pytest.raises(RouterVehicleDocumentError):
            resolve_bingx_mark_prices(document)

    def test_an_empty_data_list_reads_as_no_marks(self) -> None:
        assert resolve_bingx_mark_prices({"code": 0, "data": []}) == {}


class TestPurity:
    """The constraints: no socket, no secret, no environment, no store."""

    FORBIDDEN: ClassVar[frozenset[str]] = frozenset({
        "http",
        "http.client",
        "urllib",
        "urllib.request",
        "socket",
        "ssl",
        "hmac",
        "ccxt",
        "httpx",
        "requests",
        "aiohttp",
        "os",
        "subprocess",
    })

    def _imported_modules(self) -> set[str]:
        source = (
            Path(__file__).parents[1] / "src" / "router" / "bingx_documents.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        return imported

    def test_no_network_or_secret_module_is_imported(self) -> None:
        assert not (self._imported_modules() & self.FORBIDDEN)

    def test_the_translation_consults_no_environment(
        self, contracts_document: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A translation that read an environment variable would change with
        # the deployment; this one is a pure function of the document.
        monkeypatch.setenv("BINGX_API_KEY", "should-never-be-read")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///does-not-matter.db")
        translated = resolve_bingx_filters(contracts_document)
        assert set(translated.filters) == set(TRADABLE)

    def test_the_same_document_answers_the_same_translation_twice(
        self, contracts_document: dict
    ) -> None:
        first = resolve_bingx_filters(contracts_document)
        second = resolve_bingx_filters(contracts_document)
        assert {
            s: f.step_size for s, f in first.filters.items()
        } == {s: f.step_size for s, f in second.filters.items()}
        assert tuple(first.refusals) == tuple(second.refusals)

    def test_the_same_index_answers_the_same_marks_twice(
        self, premium_index_document: dict
    ) -> None:
        assert resolve_bingx_mark_prices(
            premium_index_document
        ) == resolve_bingx_mark_prices(premium_index_document)
