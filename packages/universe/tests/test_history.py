"""Acceptance tests for the retained price history.

Feature 43 (app_spec.xml, "Universe & Survivorship Integrity"): the system
retains delisted symbols with their full price history, so a window covering a
symbol's listed period returns it whether or not it is still a universe member.
The price store keeps every symbol's daily closes — members and delisted names
alike — and a window query returns the symbols present in it, sorted.

The store is a pure function of the bars it is handed and the database it writes
to, so most of what follows pins that behaviour directly; the persistence tests
then pin that the bars are written, readable, replaced on a restate, and never
pruned to current members.
"""

import datetime as dt

import pytest

from universe import PriceBar, PriceHistoryStore, persist_price_history

APRIL = [(2026, 4, d) for d in range(1, 31)]
MAY = [(2026, 5, d) for d in range(1, 29)]
JUNE = [(2026, 6, d) for d in range(1, 29)]


def daily(symbol: str, month: list[tuple[int, int, int]], close: float) -> list[PriceBar]:
    return [
        PriceBar(symbol, dt.date(y, m, d), close)
        for y, m, d in month
    ]


def history(url: str) -> PriceHistoryStore:
    return PriceHistoryStore(url)


class TestPriceBarValidation:
    """A price bar is a validated, frozen fact at the boundary."""

    def test_non_positive_close_rejected(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            PriceBar("AAAUSDT", dt.date(2026, 4, 1), 0.0)
        with pytest.raises(ValueError, match="> 0"):
            PriceBar("AAAUSDT", dt.date(2026, 4, 1), -1.0)

    def test_non_finite_close_rejected(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            PriceBar("AAAUSDT", dt.date(2026, 4, 1), float("nan"))
        with pytest.raises(ValueError, match="finite"):
            PriceBar("AAAUSDT", dt.date(2026, 4, 1), float("inf"))

    def test_blank_symbol_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            PriceBar("  ", dt.date(2026, 4, 1), 10.0)

    def test_datetime_date_is_pinned_to_its_calendar_day(self) -> None:
        bar = PriceBar("AAAUSDT", dt.datetime(2026, 4, 1, 23, 59), 10.0)
        assert bar.date == dt.date(2026, 4, 1)
        assert type(bar.date) is dt.date

    def test_bar_is_frozen(self) -> None:
        import dataclasses

        bar = PriceBar("AAAUSDT", dt.date(2026, 4, 1), 10.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            bar.close = 20.0  # type: ignore[misc]


class TestRetention:
    """Every symbol is retained, delisted names included — never pruned."""

    def test_ingest_returns_the_bar_count(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", APRIL, 10.0)
        assert history(test_database_url).ingest(bars) == len(APRIL)

    def test_all_symbols_retained_regardless_of_membership(
        self, test_database_url: str
    ) -> None:
        # AAA is a member; BBB and CCC are not members of any universe — but
        # the price store retains all three, because it is not pruned to
        # membership.
        bars = (
            daily("AAAUSDT", APRIL, 10.0)
            + daily("BBBUSDT", APRIL, 20.0)
            + daily("CCCUSDT", APRIL, 30.0)
        )
        history(test_database_url).ingest(bars)
        assert history(test_database_url).all_symbols() == (
            "AAAUSDT",
            "BBBUSDT",
            "CCCUSDT",
        )

    def test_listed_range_spans_the_bars_present(self, test_database_url: str) -> None:
        bars = daily("BBBUSDT", APRIL, 20.0) + daily("BBBUSDT", MAY, 20.0)
        history(test_database_url).ingest(bars)
        assert history(test_database_url).listed_range("BBBUSDT") == (
            dt.date(2026, 4, 1),
            dt.date(2026, 5, 28),
        )

    def test_listed_range_none_for_unknown_symbol(self, test_database_url: str) -> None:
        assert history(test_database_url).listed_range("ZZZUSDT") is None

    def test_empty_history_returns_empty_symbol_list(self, test_database_url: str) -> None:
        assert history(test_database_url).all_symbols() == ()


class TestWindowQueries:
    """A window returns the symbols present in it, sorted and stable."""

    def test_symbols_in_window_are_sorted(self, test_database_url: str) -> None:
        bars = (
            daily("CCCUSDT", MAY, 30.0)
            + daily("AAAUSDT", MAY, 10.0)
            + daily("BBBUSDT", MAY, 20.0)
        )
        history(test_database_url).ingest(bars)
        assert history(test_database_url).symbols_in_window(
            dt.date(2026, 5, 1), dt.date(2026, 5, 28)
        ) == ("AAAUSDT", "BBBUSDT", "CCCUSDT")

    def test_window_is_inclusive_on_both_bounds(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", MAY, 10.0)
        history(test_database_url).ingest(bars)
        # The first and last day of the range both count.
        assert history(test_database_url).symbols_in_window(
            dt.date(2026, 5, 1), dt.date(2026, 5, 1)
        ) == ("AAAUSDT",)
        assert history(test_database_url).symbols_in_window(
            dt.date(2026, 5, 28), dt.date(2026, 5, 28)
        ) == ("AAAUSDT",)

    def test_window_excludes_symbols_outside_it(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", APRIL, 10.0) + daily("BBBUSDT", JUNE, 20.0)
        history(test_database_url).ingest(bars)
        # May has neither symbol.
        assert history(test_database_url).symbols_in_window(
            dt.date(2026, 5, 1), dt.date(2026, 5, 28)
        ) == ()

    def test_count_matches_distinct_symbols(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", MAY, 10.0) + daily("BBBUSDT", MAY, 20.0)
        history(test_database_url).ingest(bars)
        assert history(test_database_url).count_symbols_in_window(
            dt.date(2026, 5, 1), dt.date(2026, 5, 28)
        ) == 2

    def test_accepts_iso_date_strings(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", MAY, 10.0)
        history(test_database_url).ingest(bars)
        assert history(test_database_url).symbols_in_window("2026-05-01", "2026-05-28") == (
            "AAAUSDT",
        )

    def test_bars_for_symbol_are_oldest_first(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", MAY, 10.0)
        history(test_database_url).ingest(bars)
        returned = history(test_database_url).bars(
            "AAAUSDT", dt.date(2026, 5, 1), dt.date(2026, 5, 3)
        )
        assert [b.date for b in returned] == [
            dt.date(2026, 5, 1),
            dt.date(2026, 5, 2),
            dt.date(2026, 5, 3),
        ]
        assert [b.close for b in returned] == [10.0, 10.0, 10.0]


class TestDelistedSymbolReturnsFromWindow:
    """The feature-43 contract: a delisted name still answers to its period."""

    def test_symbol_delisted_after_window_still_returns_when_window_covers_it(
        self, test_database_url: str
    ) -> None:
        # BBBUSDT trades April–June, then is delisted (removed from the
        # universe) in July. A May window covers its listed period, so the
        # window returns it even though it is no longer a member.
        bars = daily("BBBUSDT", APRIL, 20.0) + daily("BBBUSDT", MAY, 20.0)
        history(test_database_url).ingest(bars)
        assert "BBBUSDT" in history(test_database_url).symbols_in_window(
            dt.date(2026, 5, 1), dt.date(2026, 5, 28)
        )

    def test_window_entirely_after_last_bar_does_not_return_it(
        self, test_database_url: str
    ) -> None:
        # BBBUSDT's last close is end of June; a window wholly after that —
        # August, say — covers no listed day, so it does not return BBBUSDT.
        bars = daily("BBBUSDT", APRIL, 20.0) + daily("BBBUSDT", MAY, 20.0)
        history(test_database_url).ingest(bars)
        assert history(test_database_url).symbols_in_window(
            dt.date(2026, 8, 1), dt.date(2026, 8, 28)
        ) == ()

    def test_window_overlapping_the_listed_period_returns_it(
        self, test_database_url: str
    ) -> None:
        # BBBUSDT traded April–June; a window spanning June–July overlaps its
        # listed period on June, so it returns BBBUSDT.
        bars = daily("BBBUSDT", JUNE, 20.0)
        history(test_database_url).ingest(bars)
        assert "BBBUSDT" in history(test_database_url).symbols_in_window(
            dt.date(2026, 6, 15), dt.date(2026, 7, 15)
        )


class TestIdempotencyAndRestates:
    """Re-ingesting replaces a day in place; nothing is duplicated."""

    def test_reingest_same_day_is_idempotent(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", APRIL, 10.0)
        history(test_database_url).ingest(bars)
        history(test_database_url).ingest(bars)
        assert len(history(test_database_url).bars(
            "AAAUSDT", dt.date(2026, 4, 1), dt.date(2026, 4, 30)
        )) == len(APRIL)

    def test_restated_close_replaces_the_day(self, test_database_url: str) -> None:
        first = [PriceBar("AAAUSDT", dt.date(2026, 4, 15), 10.0)]
        restated = [PriceBar("AAAUSDT", dt.date(2026, 4, 15), 99.0)]
        history(test_database_url).ingest(daily("AAAUSDT", APRIL, 10.0))
        history(test_database_url).ingest(restated)
        (bar,) = history(test_database_url).bars(
            "AAAUSDT", dt.date(2026, 4, 15), dt.date(2026, 4, 15)
        )
        assert bar.close == 99.0

    def test_days_do_not_leak_between_symbols(self, test_database_url: str) -> None:
        history(test_database_url).ingest(daily("AAAUSDT", APRIL, 10.0))
        assert history(test_database_url).bars(
            "BBBUSDT", dt.date(2026, 4, 1), dt.date(2026, 4, 30)
        ) == ()


class TestPriceHistoryPersistence:
    """The bars are written, readable, and replaced on a restate."""

    def test_persist_then_query_round_trips(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", MAY, 10.0)
        persist_price_history(bars, test_database_url)
        returned = PriceHistoryStore(test_database_url).bars(
            "AAAUSDT", dt.date(2026, 5, 1), dt.date(2026, 5, 28)
        )
        assert returned[0] == PriceBar("AAAUSDT", dt.date(2026, 5, 1), 10.0)

    def test_persist_counts_bars_written(self, test_database_url: str) -> None:
        bars = daily("AAAUSDT", MAY, 10.0)
        assert persist_price_history(bars, test_database_url) == len(MAY)

    def test_prices_do_not_leak_between_stores(self, tmp_path) -> None:
        first = f"sqlite:///{tmp_path / 'first.db'}"
        second = f"sqlite:///{tmp_path / 'second.db'}"
        persist_price_history(daily("AAAUSDT", MAY, 10.0), first)
        assert PriceHistoryStore(second).all_symbols() == ()

    def test_price_history_table_is_created(self, test_database_url: str) -> None:
        from contextlib import closing

        from universe.store import connect

        with closing(connect(test_database_url)) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "universe_price_history" in names

    def test_dates_are_stored_as_iso_text(self, test_database_url: str) -> None:
        from contextlib import closing

        from universe.store import connect

        persist_price_history(daily("AAAUSDT", MAY, 10.0), test_database_url)
        with closing(connect(test_database_url)) as connection:
            (value,) = connection.execute(
                "SELECT date FROM universe_price_history LIMIT 1"
            ).fetchone()
        assert value == "2026-05-01"
