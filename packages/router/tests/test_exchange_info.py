"""Feature 310's fetched-document half: parsing and narrowing a fetch.

``router.exchange_info`` delegates parsing whole to
``nullius_ingest.exchange_info.parse_exchange_info`` and narrows the result
to the five fields the feature names.  These tests pin the narrowing
(the right fields, read verbatim, absent fields honestly ``None``) and the
error translation (a bad document raises this package's own
``RouterFilterError``, never the ingest member's ``ExchangeInfoParseError``
by name).
"""

from __future__ import annotations

import pytest
from router.errors import RouterFilterError
from router.exchange_info import RouterSymbolFilters, resolve_router_filters


class TestResolveRouterFilters:
    def test_narrows_each_symbol_to_the_five_named_fields(
        self, exchange_info_document: dict
    ) -> None:
        resolved = resolve_router_filters(exchange_info_document)
        assert set(resolved) == {"BTCUSDT", "ETHUSDT"}

        btc = resolved["BTCUSDT"]
        assert isinstance(btc, RouterSymbolFilters)
        assert btc.symbol == "BTCUSDT"
        assert btc.step_size == "0.00001000"
        assert btc.min_qty == "0.00001000"
        assert btc.max_qty == "9000.00000000"
        assert btc.tick_size == "0.01000000"
        assert btc.min_price == "0.01000000"
        assert btc.max_price == "1000000.00000000"
        assert btc.min_notional == "5.00000000"

    def test_falls_back_to_the_older_min_notional_spelling(
        self, exchange_info_document: dict
    ) -> None:
        # ETHUSDT's fixture carries MIN_NOTIONAL rather than NOTIONAL — the
        # older spelling some venues still emit, per the ingest member's
        # own SymbolFilters.min_notional fallback.
        resolved = resolve_router_filters(exchange_info_document)
        assert resolved["ETHUSDT"].min_notional == "10.00000000"

    def test_values_are_kept_verbatim_not_coerced_to_numbers(
        self, exchange_info_document: dict
    ) -> None:
        resolved = resolve_router_filters(exchange_info_document)
        assert isinstance(resolved["BTCUSDT"].step_size, str)
        assert isinstance(resolved["BTCUSDT"].tick_size, str)

    def test_a_symbol_missing_a_filter_type_reads_that_field_as_none(self) -> None:
        document = {
            "symbols": [
                {
                    "symbol": "XRPUSDT",
                    "filters": [
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": "1",
                            "minQty": "1",
                            "maxQty": "1000000",
                        }
                    ],
                }
            ]
        }
        resolved = resolve_router_filters(document)
        filters = resolved["XRPUSDT"]
        assert filters.step_size == "1"
        assert filters.tick_size is None
        assert filters.min_price is None
        assert filters.max_price is None
        assert filters.min_notional is None

    def test_accepts_json_bytes_and_json_text_like_the_ingest_fetch_seam(self) -> None:
        import json

        document = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"}
                    ],
                }
            ]
        }
        text = json.dumps(document)
        assert resolve_router_filters(text)["BTCUSDT"].step_size == "1"
        assert resolve_router_filters(text.encode("utf-8"))["BTCUSDT"].step_size == "1"

    @pytest.mark.parametrize(
        "document",
        [
            "not json at all {{{",
            {"no_symbols_key": True},
            {"symbols": [{"symbol": "BTCUSDT", "filters": []}]},
            {"symbols": [{"symbol": "", "filters": [{"filterType": "LOT_SIZE"}]}]},
            {
                "symbols": [
                    {"symbol": "BTCUSDT", "filters": [{"filterType": "LOT_SIZE"}]},
                    {"symbol": "BTCUSDT", "filters": [{"filterType": "LOT_SIZE"}]},
                ]
            },
        ],
    )
    def test_a_malformed_document_raises_the_routers_own_filter_error(
        self, document
    ) -> None:
        # Translated at the seam: a caller catching this package's one
        # vocabulary must not have to also import nullius_ingest's errors
        # to catch a bad document.
        with pytest.raises(RouterFilterError):
            resolve_router_filters(document)

    def test_an_empty_document_is_refused_not_persisted_as_zero_symbols(self) -> None:
        with pytest.raises(RouterFilterError):
            resolve_router_filters({"symbols": []})


class TestRouterSymbolFilters:
    def test_rejects_a_blank_symbol(self) -> None:
        with pytest.raises(RouterFilterError):
            RouterSymbolFilters(
                symbol="",
                step_size=None,
                min_qty=None,
                max_qty=None,
                tick_size=None,
                min_price=None,
                max_price=None,
                min_notional=None,
            )

    def test_is_frozen(self) -> None:
        import dataclasses

        filters = RouterSymbolFilters(
            symbol="BTCUSDT",
            step_size="1",
            min_qty=None,
            max_qty=None,
            tick_size=None,
            min_price=None,
            max_price=None,
            min_notional=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            filters.step_size = "2"  # type: ignore[misc]
