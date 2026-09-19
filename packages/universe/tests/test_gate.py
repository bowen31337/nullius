"""Acceptance tests for the survivorship gate.

Feature 45 (app_spec.xml, "Universe & Survivorship Integrity"): the system
rejects a universe build whose delisted-symbol count is 0 across a period
known to contain delistings. The knowledge is the store's own — a closed
membership interval (feature 41) overlapping the build's trailing window
places a since-departed name inside the period — and the count is
feature 44's audit over the retained price history (feature 43). When the
period is known to contain delistings, the window's history is populated,
and yet none of the delisted names is in it, the zero is not honest: it is
the signature of a history pruned to the survivors, and the build is
refused.

The two honest zeros are pinned as carefully as the rejection, because
they are what keeps the gate precise: a clean period — no delistings the
membership table places inside the window — counts 0 and passes, and an
unpopulated window — no bars at all, prices not yet landed — counts 0 and
passes, an absence of evidence rather than proof of pruning. The gate
fires only when bars are present and the delisted names are not.

The scenarios keep the audit suite's calendar straight: a build effective
in month M reads the 30 days ending the day before M starts, so the
``2026-05`` build's window is April 1–30, and a symbol admitted by April's
build and dropped by May's build was a member of that whole window — the
period the gate must defend.
"""

import datetime as dt

import pytest

from universe import (
    DailyBar,
    MembershipInterval,
    MonthlyUniverse,
    PriceBar,
    SurvivorshipGap,
    UniverseBuildRejected,
    UniverseConfig,
    build_monthly_universe,
    known_delistings,
    month_key,
    month_start,
    reject_survivorship_gaps,
    survivorship_gaps,
)
from universe.service import UniverseService

# top_n=1 so the lower-volume symbol is dropped from a month's build.
TOP_ONE = UniverseConfig(top_n=1)

APRIL = [(2026, 4, d) for d in range(1, 31)]

APRIL_1 = dt.date(2026, 4, 1)
MAY_1 = dt.date(2026, 5, 1)

# The canonical delisting: BBB is admitted by April's build, dropped by
# May's, so its interval runs [Apr 1, May 1) — closed — and covers the
# whole of May's trailing window (April 1–30). AAA stays across both.
BBB_CLOSED = MembershipInterval(
    "BBBUSDT", APRIL_1, MAY_1, "not admitted to the 2026-05 universe"
)
AAA_OPEN = MembershipInterval("AAAUSDT", APRIL_1)


def daily_price(symbol: str, close: float) -> list[PriceBar]:
    return [PriceBar(symbol, dt.date(y, m, d), close) for y, m, d in APRIL]


def universe_for(month: str) -> MonthlyUniverse:
    """A build carrying only what the gate reads: the month and its window."""
    first = month_start(month)
    return MonthlyUniverse(
        month=month_key(first),
        effective_from=first,
        window_start=first - dt.timedelta(days=30),
        window_end=first - dt.timedelta(days=1),
        config=UniverseConfig(),
        members=(),
    )


def bars_build(month: str, winner: str, loser: str) -> MonthlyUniverse:
    """A real build effective in ``month`` where ``winner`` outranks ``loser``.

    Bars are laid across the build's trailing window with the winner's
    volume above the loser's, so at ``top_n=1`` the winner is admitted and
    the loser is not — persisting two of these in sequence is what closes
    the loser's membership interval.
    """
    window_start = month_start(month) - dt.timedelta(days=30)
    window_end = month_start(month) - dt.timedelta(days=1)
    bars = [
        DailyBar(winner, window_start + dt.timedelta(days=offset), 100.0)
        for offset in range((window_end - window_start).days + 1)
    ] + [
        DailyBar(loser, window_start + dt.timedelta(days=offset), 50.0)
        for offset in range((window_end - window_start).days + 1)
    ]
    return build_monthly_universe(bars, month, TOP_ONE)


class _HistoryStub:
    """A price-history stand-in answering from a fixed window→symbols map.

    Speaks only the one method the gate asks of a store — the same window
    query :meth:`universe.history.PriceHistoryStore.symbols_in_window`
    offers — so the pure tests state the history as data instead of
    laying bars down in a database.
    """

    def __init__(self, present: dict[tuple[dt.date, dt.date], tuple[str, ...]]):
        self._present = present

    def symbols_in_window(self, start, end, database_url=None):
        return self._present.get((start, end), ())


def _history(present: dict[tuple[dt.date, dt.date], tuple[str, ...]]) -> _HistoryStub:
    return _HistoryStub(present)


MAY_UNIVERSE = universe_for("2026-05")
MAY_WINDOW = (MAY_UNIVERSE.window_start, MAY_UNIVERSE.window_end)


class TestKnownDelistings:
    """"Known to contain delistings" is a closed interval overlapping the window."""

    def test_closed_interval_overlapping_the_window_is_known(self) -> None:
        # BBB was a member through the whole of May's window (April) and
        # left after it: the period is known to contain its delisting.
        assert known_delistings([BBB_CLOSED, AAA_OPEN], *MAY_WINDOW) == ("BBBUSDT",)

    def test_open_interval_is_not_known(self) -> None:
        # A current member has not left; its membership is not a delisting.
        assert known_delistings([AAA_OPEN], *MAY_WINDOW) == ()

    def test_departure_before_the_window_is_not_known(self) -> None:
        # Membership ended exactly when the window began: the delisting
        # belongs to the period before the window, not to the window.
        left_in_march = MembershipInterval(
            "CCCUSDT", dt.date(2026, 3, 1), APRIL_1, "left"
        )
        assert known_delistings([left_in_march], *MAY_WINDOW) == ()

    def test_membership_after_the_window_is_not_known(self) -> None:
        # Joined after the window ended and left again later: neither the
        # membership nor the departure is inside the window.
        joined_in_june = MembershipInterval(
            "CCCUSDT", dt.date(2026, 6, 1), dt.date(2026, 7, 1), "left"
        )
        assert known_delistings([joined_in_june], *MAY_WINDOW) == ()

    def test_partial_overlap_is_known(self) -> None:
        # A member for the last third of the window that then left.
        straddler = MembershipInterval(
            "CCCUSDT", dt.date(2026, 4, 20), MAY_1, "left"
        )
        assert known_delistings([straddler], *MAY_WINDOW) == ("CCCUSDT",)

    def test_accepts_iso_strings_and_returns_sorted_names(self) -> None:
        intervals = [
            MembershipInterval("ZZZUSDT", APRIL_1, MAY_1, "left"),
            MembershipInterval("BBBUSDT", APRIL_1, MAY_1, "left"),
        ]
        known = known_delistings(
            intervals, "2026-04-01", "2026-04-30"
        )
        assert known == ("BBBUSDT", "ZZZUSDT")


class TestSurvivorshipGaps:
    """The gap is the one zero no honest store produces."""

    def test_populated_window_missing_the_delisted_name_is_a_gap(self) -> None:
        # April's bars exist — for the survivor only. The membership table
        # says BBB belonged to April and left; its absence from a populated
        # window is the pruning signature.
        (gap,) = survivorship_gaps(
            _history({MAY_WINDOW: ("AAAUSDT",)}),  # history holds the survivor
            [BBB_CLOSED, AAA_OPEN],
            [MAY_UNIVERSE],
        )
        assert gap.month == "2026-05"
        assert gap.window_start == MAY_UNIVERSE.window_start
        assert gap.window_end == MAY_UNIVERSE.window_end
        assert gap.missing == ("BBBUSDT",)

    def test_delisted_name_present_is_no_gap(self) -> None:
        # The retained history holds BBB's April closes: the audit counts
        # it, and the window's non-zero count is exactly what it should be.
        assert (
            survivorship_gaps(
                _history({MAY_WINDOW: ("AAAUSDT", "BBBUSDT")}),
                [BBB_CLOSED, AAA_OPEN],
                [MAY_UNIVERSE],
            )
            == ()
        )

    def test_clean_period_is_no_gap(self) -> None:
        # Nobody left: a zero count is the honest answer for a clean period.
        assert (
            survivorship_gaps(
                _history({MAY_WINDOW: ("AAAUSDT",)}),
                [AAA_OPEN],
                [MAY_UNIVERSE],
            )
            == ()
        )

    def test_unpopulated_window_is_no_gap(self) -> None:
        # No bars at all in the window — prices have not landed. A zero
        # here is an absence of evidence, not proof of pruning, and the
        # gate leaves it to the sweep's own skip reporting.
        assert (
            survivorship_gaps(
                _history({}),
                [BBB_CLOSED, AAA_OPEN],
                [MAY_UNIVERSE],
            )
            == ()
        )

    def test_gaps_follow_month_order_regardless_of_input(self) -> None:
        # June's window needs its own delisting to under-report: CCC's
        # membership straddles May and closed on June 1, while BBB's ended
        # before June's window began (May 2) and is not known to it.
        june = universe_for("2026-06")
        ccc_closed_in_june = MembershipInterval(
            "CCCUSDT", dt.date(2026, 5, 10), dt.date(2026, 6, 1), "left"
        )
        gaps = survivorship_gaps(
            _history(
                {
                    MAY_WINDOW: ("AAAUSDT",),
                    (june.window_start, june.window_end): ("AAAUSDT",),
                }
            ),
            [BBB_CLOSED, AAA_OPEN, ccc_closed_in_june],
            [june, MAY_UNIVERSE],  # handed over out of order
        )
        assert [gap.month for gap in gaps] == ["2026-05", "2026-06"]
        assert gaps[1].missing == ("CCCUSDT",)

    def test_unsorted_missing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            SurvivorshipGap("2026-05", APRIL_1, dt.date(2026, 4, 30), ("ZZZ", "AAA"))


class TestRejectSurvivorshipGaps:
    """The verdict: quiet when every zero is honest, loud otherwise."""

    def test_quiet_when_there_are_no_gaps(self) -> None:
        assert reject_survivorship_gaps(()) is None

    def test_raises_naming_the_window_and_the_missing_names(self) -> None:
        gap = SurvivorshipGap("2026-05", APRIL_1, dt.date(2026, 4, 30), ("BBBUSDT",))
        with pytest.raises(UniverseBuildRejected) as raised:
            reject_survivorship_gaps((gap,))
        message = str(raised.value)
        assert "2026-05" in message
        assert "[2026-04-01, 2026-04-30]" in message
        assert "BBBUSDT" in message
        assert "delisted=0" in message
        assert "ingest" in message

    def test_every_gap_is_named_in_one_rejection(self) -> None:
        gaps = (
            SurvivorshipGap("2026-05", APRIL_1, dt.date(2026, 4, 30), ("BBBUSDT",)),
            SurvivorshipGap("2026-06", dt.date(2026, 5, 2), dt.date(2026, 5, 31), ("CCCUSDT",)),
        )
        with pytest.raises(UniverseBuildRejected, match="2026-05.*2026-06"):
            reject_survivorship_gaps(gaps)

    def test_the_rejection_is_a_value_error(self) -> None:
        assert issubclass(UniverseBuildRejected, ValueError)


class TestPersistGate:
    """The persist path refuses a build on pruned history; nothing lands."""

    def _service(self, url: str) -> UniverseService:
        return UniverseService(config=TOP_ONE, database_url=url)

    def test_a_build_on_pruned_history_is_rejected(
        self, test_database_url: str
    ) -> None:
        # April: BBB wins and is the member. The survivor AAA's April
        # closes land in the history. May's build then drops BBB — and its
        # window (April) is populated, known to contain BBB's delisting,
        # and missing BBB's bars: the build is rejected, nothing lands.
        service = self._service(test_database_url)
        service.persist(bars_build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.ingest_prices(daily_price("AAAUSDT", 10.0))

        with pytest.raises(UniverseBuildRejected, match="BBBUSDT"):
            service.persist(bars_build("2026-05", "AAAUSDT", "BBBUSDT"))

        # The whole transaction rolled back: no May build, and BBB's
        # membership is still open — no later build exists to close it.
        assert service.load("2026-05") is None
        bbb = [
            interval
            for interval in service.membership()
            if interval.symbol == "BBBUSDT"
        ]
        assert len(bbb) == 1
        assert bbb[0].is_open

    def test_the_same_build_passes_once_the_missing_history_lands(
        self, test_database_url: str
    ) -> None:
        # The rejection is a refusal, not a deletion: ingest BBB's April
        # closes and re-present the identical build — it is accepted, and
        # the audit counts the delisted name in the window it defends.
        service = self._service(test_database_url)
        april = bars_build("2026-04", "BBBUSDT", "AAAUSDT")
        may = bars_build("2026-05", "AAAUSDT", "BBBUSDT")
        service.persist(april)
        service.ingest_prices(daily_price("AAAUSDT", 10.0))
        with pytest.raises(UniverseBuildRejected):
            service.persist(may)

        service.ingest_prices(daily_price("BBBUSDT", 20.0))
        assert service.persist(may) == 1

        audits = service.survivorship_audit(months=["2026-05"])
        assert audits[0].delisted_present == ("BBBUSDT",)

    def test_builds_before_prices_are_not_rejected(
        self, test_database_url: str
    ) -> None:
        # The canonical order — builds land first, prices after — never
        # trips the gate: an unpopulated window is an absence of evidence,
        # and the audit's zero for it is honest (feature 44 pins that too).
        service = self._service(test_database_url)
        assert service.persist(bars_build("2026-04", "BBBUSDT", "AAAUSDT")) == 1
        assert service.persist(bars_build("2026-05", "AAAUSDT", "BBBUSDT")) == 1
        may = [a for a in service.survivorship_audit() if a.month == "2026-05"]
        assert may[0].delisted_count == 0

    def test_a_restated_build_over_a_pruned_window_is_rejected_atomically(
        self, test_database_url: str
    ) -> None:
        # May was legitimately persisted before any prices landed. The
        # survivor's April closes then arrive — and BBB's do not — so
        # restating May over the now-pruned window is refused, and the
        # rollback leaves the previously persisted build intact.
        service = self._service(test_database_url)
        may = bars_build("2026-05", "AAAUSDT", "BBBUSDT")
        service.persist(bars_build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(may)
        service.ingest_prices(daily_price("AAAUSDT", 10.0))

        with pytest.raises(UniverseBuildRejected):
            service.persist(may)

        assert service.load("2026-05") == may

    def test_a_clean_store_persists_with_prices_present(
        self, test_database_url: str
    ) -> None:
        # One month, prices in its window, nobody delisted: a populated
        # window with no delistings to expect is not the gate's business.
        service = self._service(test_database_url)
        may = bars_build("2026-05", "AAAUSDT", "BBBUSDT")
        service.ingest_prices(daily_price("AAAUSDT", 10.0))
        assert service.persist(may) == 1
        assert service.survivorship_gaps() == ()


class TestServiceGate:
    """The sweep: inspect the gaps, or raise on them, across the store."""

    def _gappy_store(self, url: str) -> UniverseService:
        """A store whose May window is populated and missing its delisting.

        Built the honest way — builds land first (quiet: unpopulated),
        then only the survivor's April closes arrive — so the pruning is
        in the *history*, exactly the state an operator must be able to
        see without tripping.
        """
        service = UniverseService(config=TOP_ONE, database_url=url)
        service.persist(bars_build("2026-04", "BBBUSDT", "AAAUSDT"))
        service.persist(bars_build("2026-05", "AAAUSDT", "BBBUSDT"))
        service.ingest_prices(daily_price("AAAUSDT", 10.0))
        return service

    def test_survivorship_gaps_names_the_under_reporting_window(
        self, test_database_url: str
    ) -> None:
        service = self._gappy_store(test_database_url)
        (gap,) = service.survivorship_gaps()
        assert gap.month == "2026-05"
        assert gap.missing == ("BBBUSDT",)

    def test_reject_survivorship_gaps_raises_listing_the_month(
        self, test_database_url: str
    ) -> None:
        service = self._gappy_store(test_database_url)
        with pytest.raises(UniverseBuildRejected, match="2026-05.*BBBUSDT"):
            service.reject_survivorship_gaps()

    def test_a_months_filter_over_honest_windows_is_quiet(
        self, test_database_url: str
    ) -> None:
        # April's window (March 2–31) contains no delisting the membership
        # table knows: BBB only joined on April 1, so asking the gate about
        # April alone passes quietly.
        service = self._gappy_store(test_database_url)
        assert service.survivorship_gaps(months=["2026-04"]) == ()
        assert service.reject_survivorship_gaps(months=["2026-04"]) is None

    def test_ingesting_the_missing_name_clears_the_gap(
        self, test_database_url: str
    ) -> None:
        service = self._gappy_store(test_database_url)
        service.ingest_prices(daily_price("BBBUSDT", 20.0))
        assert service.survivorship_gaps() == ()
        assert service.reject_survivorship_gaps() is None
