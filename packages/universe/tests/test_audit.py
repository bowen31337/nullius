"""Acceptance tests for the survivorship audit.

Feature 44 (app_spec.xml, "Universe & Survivorship Integrity"): the system
emits a survivorship audit report counting the delisted symbols present in each
historical window. A symbol is "delisted" here when its membership interval has
closed (the store's own record that it left the universe); it is "present" in a
window when the retained price history still holds a bar for it inside that
window. Counting the delisted-but-present names per window is the survivorship
number — the names a current-universe-only view would silently lose.

The audit is a pure function of the price history and the membership intervals,
so most of what follows pins that function directly; the persistence tests then
pin that the audit is written, readable, and re-derived on ingest.

One thing every scenario here keeps straight: a build effective in month M reads
its *trailing* window — the 30 days ending the day before M starts — so a build
for ``2026-05`` is computed from April's bars and its window is April 1–30. A
delisted symbol is "present" in that window only if the price history holds a
bar for it in April.
"""

import datetime as dt

import pytest

from universe import (
    DailyBar,
    MembershipInterval,
    MonthlyUniverse,
    PriceBar,
    UniverseConfig,
    WindowAudit,
    build_monthly_universe,
    delisted_symbols,
    persist_monthly_universe,
    persist_price_history,
    persist_survivorship_audit,
    render_report,
    survivorship_audit,
)
from universe.history import PriceHistoryStore
from universe.store import load_survivorship_audit

# top_n=1 so the lower-volume symbol is dropped from a month's build.
TOP_ONE = UniverseConfig(top_n=1)

APRIL = [(2026, 4, d) for d in range(1, 31)]
MAY = [(2026, 5, d) for d in range(1, 29)]


def daily_price(symbol: str, month: list[tuple[int, int, int]], close: float) -> list[PriceBar]:
    return [PriceBar(symbol, dt.date(y, m, d), close) for y, m, d in month]


def build(month: str, winner: str, loser: str, config: UniverseConfig = TOP_ONE) -> MonthlyUniverse:
    """A build effective in ``month`` where ``winner`` outranks ``loser``.

    Bars are laid across the build's trailing window (the 30 days before the
    month starts), with the winner's volume above the loser's so that at
    ``top_n=1`` the winner is admitted and the loser is not.
    """
    year, number = (int(part) for part in month.split("-"))
    first = dt.date(year, number, 1)
    window_start = first - dt.timedelta(days=30)
    window_end = first - dt.timedelta(days=1)
    bars = [
        DailyBar(winner, window_start + dt.timedelta(days=offset), 100.0)
        for offset in range((window_end - window_start).days + 1)
    ] + [
        DailyBar(loser, window_start + dt.timedelta(days=offset), 50.0)
        for offset in range((window_end - window_start).days + 1)
    ]
    return build_monthly_universe(bars, month, config)


class TestDelistedSet:
    """"Delisted" is a closed membership interval."""

    def test_open_interval_is_not_delisted(self) -> None:
        assert delisted_symbols([MembershipInterval("AAAUSDT", dt.date(2026, 4, 1))]) == frozenset()

    def test_closed_interval_is_delisted(self) -> None:
        assert delisted_symbols([
            MembershipInterval("BBBUSDT", dt.date(2026, 4, 1), dt.date(2026, 5, 1), "left")
        ]) == frozenset({"BBBUSDT"})

    def test_mixed_intervals_report_only_the_closed(self) -> None:
        intervals = [
            MembershipInterval("AAAUSDT", dt.date(2026, 4, 1)),  # still a member
            MembershipInterval("BBBUSDT", dt.date(2026, 4, 1), dt.date(2026, 5, 1), "left"),
            MembershipInterval("CCCUSDT", dt.date(2026, 6, 1), dt.date(2026, 7, 1), "left"),
        ]
        assert delisted_symbols(intervals) == frozenset({"BBBUSDT", "CCCUSDT"})


class TestAuditWindow:
    """A delisted symbol counts only when the history has it in the window."""

    def _store(self, url: str) -> PriceHistoryStore:
        return PriceHistoryStore(url)

    def test_delisted_symbol_present_when_history_in_window(
        self, test_database_url: str
    ) -> None:
        # BBB was a member in April (won April's build) and dropped in May
        # (lost May's build to AAA). Its interval therefore closes on May 1.
        # May's window is April 1–30; BBB has a close there, so it is present.
        persist_monthly_universe(build("2026-04", "BBBUSDT", "AAAUSDT"), test_database_url)
        persist_monthly_universe(build("2026-05", "AAAUSDT", "BBBUSDT"), test_database_url)
        persist_price_history(daily_price("BBBUSDT", APRIL, 20.0), test_database_url)

        audits = survivorship_audit(
            self._store(test_database_url),
            _membership(test_database_url),
            _builds(test_database_url),
        )
        may = [a for a in audits if a.month == "2026-05"]
        assert len(may) == 1
        assert may[0].delisted_present == ("BBBUSDT",)
        assert may[0].delisted_count == 1

    def test_delisted_symbol_absent_when_no_history_in_window(
        self, test_database_url: str
    ) -> None:
        # BBB left the universe but has no price bars in May's window (April).
        persist_monthly_universe(build("2026-04", "BBBUSDT", "AAAUSDT"), test_database_url)
        persist_monthly_universe(build("2026-05", "AAAUSDT", "BBBUSDT"), test_database_url)

        audits = survivorship_audit(
            self._store(test_database_url),
            _membership(test_database_url),
            _builds(test_database_url),
        )
        may = [a for a in audits if a.month == "2026-05"]
        assert may[0].delisted_present == ()
        assert may[0].delisted_count == 0

    def test_current_member_is_not_counted_as_delisted(
        self, test_database_url: str
    ) -> None:
        # AAA stays a member across both months; its interval is open, so it is
        # never a delisting.
        persist_monthly_universe(build("2026-04", "AAAUSDT", "BBBUSDT"), test_database_url)
        persist_monthly_universe(build("2026-05", "AAAUSDT", "BBBUSDT"), test_database_url)
        persist_price_history(daily_price("AAAUSDT", APRIL, 10.0), test_database_url)

        audits = survivorship_audit(
            self._store(test_database_url),
            _membership(test_database_url),
            _builds(test_database_url),
        )
        assert all(a.delisted_present == () for a in audits)

    def test_audit_window_bounds_are_the_builds_trailing_window(
        self, test_database_url: str
    ) -> None:
        persist_monthly_universe(build("2026-05", "AAAUSDT", "BBBUSDT"), test_database_url)
        (universe,) = _builds(test_database_url)
        audits = survivorship_audit(
            self._store(test_database_url), _membership(test_database_url), _builds(test_database_url)
        )
        (audit,) = audits
        assert audit.window_start == universe.window_start
        assert audit.window_end == universe.window_end
        assert audit.month == "2026-05"

    def test_window_audit_raises_on_unsorted_names(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            WindowAudit("2026-05", dt.date(2026, 4, 1), dt.date(2026, 4, 30), ("ZZZ", "AAA"))


class TestRenderReport:
    """One line per window, with the count and the names."""

    def test_report_lists_delisted_names(self) -> None:
        audits = (
            WindowAudit("2026-05", dt.date(2026, 4, 1), dt.date(2026, 4, 30), ("BBBUSDT", "CCCUSDT")),
        )
        (line,) = render_report(audits)
        assert line == "2026-05 [2026-04-01, 2026-04-30] delisted=2: BBBUSDT, CCCUSDT"

    def test_report_clean_window_has_no_names(self) -> None:
        audits = (
            WindowAudit("2026-05", dt.date(2026, 4, 1), dt.date(2026, 4, 30), ()),
        )
        (line,) = render_report(audits)
        assert line == "2026-05 [2026-04-01, 2026-04-30] delisted=0"

    def test_report_one_line_per_window_in_order(self) -> None:
        audits = (
            WindowAudit("2026-05", dt.date(2026, 4, 1), dt.date(2026, 4, 30), ("BBBUSDT",)),
            WindowAudit("2026-06", dt.date(2026, 5, 1), dt.date(2026, 5, 31), ()),
        )
        lines = render_report(audits)
        assert [line[:7] for line in lines] == ["2026-05", "2026-06"]


def _builds(url: str) -> tuple[MonthlyUniverse, ...]:
    from universe.store import load_all_monthly_universes

    return load_all_monthly_universes(url)


def _membership(url: str) -> tuple[MembershipInterval, ...]:
    from universe.store import load_universe_membership

    return load_universe_membership(url)


class TestAuditEndToEnd:
    """A period known to contain a delisting reports a non-zero count; a clean
    period reports zero — the feature-44 discriminator."""

    def _service(self, url: str):
        from universe.service import UniverseService

        return UniverseService(database_url=url)

    def test_nonzero_count_across_a_period_with_a_delisting(
        self, test_database_url: str
    ) -> None:
        # April: BBB wins (member). May: AAA wins (BBB dropped — interval
        # closes on May 1). BBB keeps trading into April, so its price history
        # is retained there, inside May's window.
        service = self._service(test_database_url)
        service.persist(build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("BBBUSDT", APRIL, 20.0))

        audits = service.survivorship_audit()
        may = [a for a in audits if a.month == "2026-05"]
        assert len(may) == 1
        assert may[0].delisted_present == ("BBBUSDT",)

    def test_zero_count_across_a_clean_period(
        self, test_database_url: str
    ) -> None:
        # AAA wins both months; nobody is dropped, so no window has a delisted
        # name present.
        service = self._service(test_database_url)
        service.persist(build("2026-04", "AAAUSDT", "BBBUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("AAAUSDT", APRIL, 10.0))
        audits = service.survivorship_audit()
        assert all(a.delisted_count == 0 for a in audits)

    def test_report_end_to_end(self, test_database_url: str) -> None:
        service = self._service(test_database_url)
        service.persist(build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("BBBUSDT", APRIL, 20.0))
        (line,) = service.render_survivorship_report(months=["2026-05"])
        assert line == "2026-05 [2026-04-01, 2026-04-30] delisted=1: BBBUSDT"


class TestAuditPersistence:
    """The audit is written, readable, and re-derived on ingest."""

    def _service(self, url: str):
        from universe.service import UniverseService

        return UniverseService(database_url=url)

    def test_load_round_trips(self, test_database_url: str) -> None:
        service = self._service(test_database_url)
        service.persist(build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("BBBUSDT", APRIL, 20.0))
        expected = service.survivorship_audit()
        assert load_survivorship_audit(test_database_url) == expected

    def test_audit_table_is_created(self, test_database_url: str) -> None:
        from contextlib import closing

        from universe.store import connect

        with closing(connect(test_database_url)) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "universe_survivorship_audit" in names

    def test_restate_prices_rederives_audit(self, test_database_url: str) -> None:
        # BBB member in April, dropped in May; prices ingested after the builds.
        service = self._service(test_database_url)
        service.persist(build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("BBBUSDT", APRIL, 20.0))
        may = [a for a in service.survivorship_audit() if a.month == "2026-05"]
        assert may[0].delisted_present == ("BBBUSDT",)

    def test_persist_survivorship_audit_is_idempotent(
        self, test_database_url: str
    ) -> None:
        service = self._service(test_database_url)
        service.persist(build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("BBBUSDT", APRIL, 20.0))
        once = service.survivorship_audit()
        persist_survivorship_audit(service.load_all(), service.membership(), test_database_url)
        persist_survivorship_audit(service.load_all(), service.membership(), test_database_url)
        assert load_survivorship_audit(test_database_url) == once

    def test_audit_months_can_be_filtered(self, test_database_url: str) -> None:
        service = self._service(test_database_url)
        service.persist(build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("BBBUSDT", APRIL, 20.0))
        audits = service.survivorship_audit(months=["2026-05"])
        assert [a.month for a in audits] == ["2026-05"]
