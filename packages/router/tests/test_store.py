"""Feature 310's persisted-record half: the exchangeInfo version store.

``RouterExchangeInfoStore`` persists every fetch as a new version — never
overwriting a prior one — and serves two reads: the whole version
(``current``/``version``) and the order path's fast, symbol-keyed lookup
(``filters_for``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from router.errors import RouterFilterError, RouterStoreError
from router.store import RouterExchangeInfoStore

FETCHED_AT = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def store(test_database_url: str) -> RouterExchangeInfoStore:
    return RouterExchangeInfoStore(test_database_url)


class TestResolve:
    def test_resolves_from_database_url(self, test_database_url: str) -> None:
        resolved = RouterExchangeInfoStore.resolve()
        assert resolved is not None
        assert resolved.database_url == test_database_url

    def test_an_absent_database_url_resolves_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert RouterExchangeInfoStore.resolve() is None

    def test_an_empty_database_url_counts_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "   ")
        assert RouterExchangeInfoStore.resolve() is None

    def test_construction_rejects_a_blank_url(self) -> None:
        with pytest.raises(RouterStoreError):
            RouterExchangeInfoStore("   ")


class TestRecord:
    def test_persists_a_version_carrying_every_named_field(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        version = store.record(
            exchange_info_document, fetched_at=FETCHED_AT, source="test-fetch"
        )
        assert version.version == 1
        assert version.fetched_at == FETCHED_AT
        assert version.source == "test-fetch"
        assert version.symbol_count == 2

        btc = version.filters_for("BTCUSDT")
        assert btc is not None
        assert btc.step_size == "0.00001000"
        assert btc.tick_size == "0.01000000"
        assert btc.min_notional == "5.00000000"

    def test_each_fetch_is_a_new_version_never_overwriting_a_prior_one(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        first = store.record(exchange_info_document, fetched_at=FETCHED_AT)
        second = store.record(
            exchange_info_document, fetched_at=FETCHED_AT + timedelta(days=1)
        )
        assert second.version == first.version + 1
        # The first version is still readable, unchanged.
        assert store.version(first.version).fetched_at == FETCHED_AT

    def test_a_repeated_fetch_with_identical_filters_still_lands_a_new_version(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        # "Persists the fetched version" names the fetch, not a change in
        # content: a quiet refresh is still a version, the same discipline
        # the ingest member's own log keeps.
        first = store.record(exchange_info_document, fetched_at=FETCHED_AT)
        second = store.record(
            exchange_info_document, fetched_at=FETCHED_AT + timedelta(days=1)
        )
        assert first.version != second.version
        assert first.symbols["BTCUSDT"] == second.symbols["BTCUSDT"]

    def test_a_malformed_document_writes_no_version(
        self, store: RouterExchangeInfoStore
    ) -> None:
        with pytest.raises(RouterFilterError):
            store.record({"symbols": []}, fetched_at=FETCHED_AT)
        assert store.current() is None

    def test_fetched_at_must_be_timezone_aware(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        naive = datetime(2026, 9, 24, 12, 0, 0)  # noqa: DTZ001 - the point of the test
        with pytest.raises(ValueError):
            store.record(exchange_info_document, fetched_at=naive)

    def test_source_defaults_to_none(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        version = store.record(exchange_info_document, fetched_at=FETCHED_AT)
        assert version.source is None


class TestReading:
    def test_current_is_none_for_an_empty_log(
        self, store: RouterExchangeInfoStore
    ) -> None:
        assert store.current() is None

    def test_current_returns_the_most_recent_version(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        store.record(exchange_info_document, fetched_at=FETCHED_AT)
        second_document = {
            "symbols": [
                {
                    "symbol": "SOLUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "0.1", "minQty": "0.1"}
                    ],
                }
            ]
        }
        store.record(second_document, fetched_at=FETCHED_AT + timedelta(days=1))

        current = store.current()
        assert current.version == 2
        assert current.symbol_count == 1
        assert current.filters_for("SOLUSDT") is not None
        assert current.filters_for("BTCUSDT") is None

    def test_version_reads_a_specific_past_version(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        first = store.record(exchange_info_document, fetched_at=FETCHED_AT)
        store.record(exchange_info_document, fetched_at=FETCHED_AT + timedelta(days=1))
        reread = store.version(first.version)
        assert reread.version == first.version
        assert reread.symbol_count == first.symbol_count

    def test_version_is_none_for_a_version_never_recorded(
        self, store: RouterExchangeInfoStore
    ) -> None:
        assert store.version(999) is None

    def test_filters_for_reads_only_the_current_versions_symbol(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        store.record(exchange_info_document, fetched_at=FETCHED_AT)
        filters = store.filters_for("BTCUSDT")
        assert filters is not None
        assert filters.step_size == "0.00001000"
        assert filters.min_notional == "5.00000000"

    def test_filters_for_is_none_when_the_log_is_empty(
        self, store: RouterExchangeInfoStore
    ) -> None:
        assert store.filters_for("BTCUSDT") is None

    def test_filters_for_does_not_fall_back_to_an_older_version(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        # A symbol the venue stopped listing must not be tradeable off a
        # stale grid: the newest version's absence of a symbol is answered
        # honestly, not papered over with a prior version's value.
        store.record(exchange_info_document, fetched_at=FETCHED_AT)
        delisted_document = {
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"}
                    ],
                }
            ]
        }
        store.record(delisted_document, fetched_at=FETCHED_AT + timedelta(days=1))
        assert store.filters_for("BTCUSDT") is None
        assert store.filters_for("ETHUSDT") is not None

    def test_values_round_trip_verbatim(
        self, store: RouterExchangeInfoStore, exchange_info_document: dict
    ) -> None:
        store.record(exchange_info_document, fetched_at=FETCHED_AT)
        reread = store.current().filters_for("BTCUSDT")
        assert reread.step_size == "0.00001000"
        assert reread.max_qty == "9000.00000000"
        assert reread.max_price == "1000000.00000000"


class TestUnsupportedDatabaseUrl:
    def test_a_non_sqlite_scheme_is_refused_by_name(
        self, exchange_info_document: dict
    ) -> None:
        store = RouterExchangeInfoStore("postgresql://localhost/nullius")
        with pytest.raises(RouterStoreError):
            store.record(exchange_info_document, fetched_at=FETCHED_AT)
