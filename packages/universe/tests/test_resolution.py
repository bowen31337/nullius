"""Acceptance tests for resolving membership as of a decision time.

Feature 42: "System resolves universe membership as of a requested
decision time, which returns the symbols tradable then rather than now"
(app_spec.xml). Architecture §4.3 gives the rule its force: "Any
``MarketWindow`` at time ``t`` resolves membership as of ``t``, never as
of now." Feature 41 built the point-in-time table those resolutions read;
this file pins the resolution itself.

Two things are under test. First the *semantics*: a symbol answers for a
decision time exactly when an interval covers it — inclusive where the
interval opens, exclusive where it closes, absent through the gap of a
split history, present past the newest build while its interval stays
open. Second the *honesty*: the decision time is the only time consulted.
The scenarios deliberately persist builds newer than the decision time
being asked about — the "now" that must not leak — and assert the answer
still names the names that were tradable *then*.
"""

import datetime as dt

import pytest

from universe import (
    DailyBar,
    MembershipInterval,
    UniverseConfig,
    UniverseService,
    build_monthly_universe,
    membership_intervals,
    month_start,
    resolve_membership,
)

FIVE_SYMBOLS = UniverseConfig(top_n=5)


def daily(symbol: str, start: dt.date, end: dt.date, volume: float) -> list[DailyBar]:
    return [
        DailyBar(symbol, start + dt.timedelta(days=offset), volume)
        for offset in range((end - start).days + 1)
    ]


def window(month: str) -> tuple[dt.date, dt.date]:
    """The trailing 30-day window a build effective in ``month`` reads."""
    year, number = (int(part) for part in month.split("-"))
    first = dt.date(year, number, 1)
    return first - dt.timedelta(days=30), first - dt.timedelta(days=1)


def trades(month: str, volumes: dict[str, float]) -> list[DailyBar]:
    """Bars inside ``month``'s trailing window, one symbol per volume given."""
    start, end = window(month)
    return [
        bar for symbol, volume in volumes.items() for bar in daily(symbol, start, end, volume)
    ]


def builds_for(
    months: dict[str, dict[str, float]], config: UniverseConfig = FIVE_SYMBOLS
) -> list:
    """One build per named month, oldest first, from bars covering each
    month's trailing window with its volumes."""
    bars = [bar for month, volumes in months.items() for bar in trades(month, volumes)]
    return [
        build_monthly_universe(bars, month, config)
        for month, volumes in sorted(months.items())
    ]


def roster_shift_months() -> dict[str, dict[str, float]]:
    """April admits AAA and BBB; from May on, AAA alone — BBB departs May 1.

    The canonical then-versus-now scenario: the store's newest build (June)
    knows only AAA, yet April's decision times must still return BBB.
    """
    return {
        "2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0},
        "2026-05": {"AAAUSDT": 100.0},
        "2026-06": {"AAAUSDT": 100.0},
    }


def roster_shift_intervals() -> tuple[MembershipInterval, ...]:
    return membership_intervals(builds_for(roster_shift_months()))


def mid_month(month: str) -> dt.date:
    """A day unambiguously inside ``month`` (never a boundary)."""
    return month_start(month) + dt.timedelta(days=14)


class TestAsOfTheDecisionTime:
    """The answer is the roster at ``when``, not the roster of the newest build."""

    def test_symbols_resolve_inside_their_intervals(self) -> None:
        intervals = roster_shift_intervals()
        assert resolve_membership(intervals, dt.date(2026, 4, 15)) == (
            "AAAUSDT",
            "BBBUSDT",
        )

    def test_a_departed_symbol_answers_for_a_time_inside_its_interval(self) -> None:
        # The newest build is June and admits AAA alone — that is "now".
        # Asked as of mid-April, BBB still answers: its interval covers the
        # decision time, so "then" returns it however the roster has moved.
        builds = builds_for(roster_shift_months())
        assert builds[-1].symbols == ("AAAUSDT",)
        assert "BBBUSDT" in resolve_membership(
            membership_intervals(builds), dt.date(2026, 4, 15)
        )

    def test_a_departed_symbol_does_not_answer_past_its_departure(self) -> None:
        intervals = roster_shift_intervals()
        assert resolve_membership(intervals, dt.date(2026, 5, 15)) == ("AAAUSDT",)

    def test_before_any_membership_the_answer_is_empty(self) -> None:
        assert resolve_membership(roster_shift_intervals(), dt.date(2026, 1, 1)) == ()

    def test_the_first_day_of_an_interval_is_included(self) -> None:
        # valid_from is inclusive: April 1 itself is April's membership.
        assert resolve_membership(roster_shift_intervals(), dt.date(2026, 4, 1)) == (
            "AAAUSDT",
            "BBBUSDT",
        )

    def test_the_day_before_an_interval_opens_excludes_the_symbol(self) -> None:
        assert resolve_membership(roster_shift_intervals(), dt.date(2026, 3, 31)) == ()

    def test_the_day_an_interval_closes_is_the_day_it_stops_answering(self) -> None:
        # valid_to is exclusive, and May 1 is the handoff: BBB's interval
        # ends exactly where AAA's continues, so the May 1 roster is the
        # May build's — BBB has left before the day begins.
        assert resolve_membership(roster_shift_intervals(), dt.date(2026, 5, 1)) == (
            "AAAUSDT",
        )

    def test_the_last_day_of_an_interval_still_answers(self) -> None:
        assert resolve_membership(roster_shift_intervals(), dt.date(2026, 4, 30)) == (
            "AAAUSDT",
            "BBBUSDT",
        )


class TestSplitAndRejoinedHistories:
    """A gap is a real history: absent through it, present again after."""

    def intervals(self) -> tuple[MembershipInterval, ...]:
        # April and June admitted AAA; May's build was never persisted.
        return membership_intervals(
            builds_for({"2026-04": {"AAAUSDT": 100.0}, "2026-06": {"AAAUSDT": 100.0}})
        )

    def test_the_gap_month_resolves_no_membership(self) -> None:
        assert resolve_membership(self.intervals(), dt.date(2026, 5, 15)) == ()

    def test_the_rejoin_month_resolves_again(self) -> None:
        assert resolve_membership(self.intervals(), dt.date(2026, 6, 15)) == (
            "AAAUSDT",
        )

    def test_the_month_before_the_gap_still_resolves(self) -> None:
        assert resolve_membership(self.intervals(), dt.date(2026, 4, 15)) == (
            "AAAUSDT",
        )


class TestTheOpenHorizon:
    """An open interval is the edge of what the store knows — and answers."""

    def test_the_newest_builds_month_resolves(self) -> None:
        intervals = roster_shift_intervals()
        assert resolve_membership(intervals, dt.date(2026, 6, 15)) == ("AAAUSDT",)

    def test_past_the_newest_build_the_open_interval_still_answers(self) -> None:
        # July has no build, so nothing observed has closed AAA's interval:
        # covers() answers for it, and the resolution says so rather than
        # silently returning nothing. What a decision time beyond the
        # evidence deserves is the caller's call — this test pins that the
        # edge behaves as documented, not that it is safe to lean on.
        intervals = membership_intervals(builds_for({"2026-06": {"AAAUSDT": 100.0}}))
        assert resolve_membership(intervals, dt.date(2030, 1, 1)) == ("AAAUSDT",)

    def test_a_closed_interval_does_not_reach_past_its_end(self) -> None:
        # The same far-future decision time against the roster-shift table:
        # BBB's closed interval must not reach for it the way AAA's open
        # one does — an end is an end.
        assert resolve_membership(roster_shift_intervals(), dt.date(2030, 1, 1)) == (
            "AAAUSDT",
        )


class TestDecisionTimeCoercion:
    """One decision time, spelled any way a caller plausibly spells it."""

    def test_date_datetime_and_iso_strings_agree(self) -> None:
        intervals = roster_shift_intervals()
        expected = ("AAAUSDT", "BBBUSDT")
        assert resolve_membership(intervals, dt.date(2026, 4, 15)) == expected
        assert (
            resolve_membership(intervals, dt.datetime(2026, 4, 15, 23, 59, 59))
            == expected
        )
        assert resolve_membership(intervals, "2026-04-15") == expected
        assert (
            resolve_membership(intervals, "2026-04-15T00:00:00+00:00") == expected
        )

    def test_a_malformed_decision_time_is_refused_loudly(self) -> None:
        with pytest.raises(ValueError, match="not an ISO date"):
            resolve_membership(roster_shift_intervals(), "April 15th")

    def test_a_malformed_decision_time_is_refused_even_on_an_empty_table(self) -> None:
        # The hazard specific to a filter: an empty table would swallow a
        # typo'd decision time and answer "nothing tradable" — a wrong
        # answer wearing the shape of a right one. Coercion happens before
        # the walk, so the refusal does not depend on the rows.
        with pytest.raises(ValueError, match="not an ISO date"):
            resolve_membership((), "2026-13-99")

    def test_a_non_date_decision_time_is_refused(self) -> None:
        with pytest.raises(TypeError, match="cannot coerce"):
            resolve_membership(roster_shift_intervals(), 20260415)  # type: ignore[arg-type]


class TestDeterminism:
    """The same table and decision time give the same answer, sorted, once each."""

    def test_the_answer_is_sorted(self) -> None:
        # ZZZ was admitted a month before AAA, so the table's own order —
        # (valid_from, symbol) — puts ZZZ first; the resolution is
        # alphabetical regardless, because a consumer must be able to zip
        # two resolutions without re-sorting either.
        intervals = membership_intervals(
            builds_for(
                {"2026-04": {"ZZZUSDT": 100.0}, "2026-05": {"ZZZUSDT": 100.0, "AAAUSDT": 50.0}}
            )
        )
        assert resolve_membership(intervals, dt.date(2026, 5, 15)) == (
            "AAAUSDT",
            "ZZZUSDT",
        )

    def test_a_symbol_appears_once_even_if_two_intervals_cover(self) -> None:
        # The derivation never emits overlapping intervals of one symbol,
        # but a hand-authored table could; a symbol is in or out, never in
        # twice, and the answer stays a usable index.
        twice = (
            MembershipInterval("AAAUSDT", dt.date(2026, 4, 1), dt.date(2026, 6, 1)),
            MembershipInterval("AAAUSDT", dt.date(2026, 5, 1)),
        )
        assert resolve_membership(twice, dt.date(2026, 5, 15)) == ("AAAUSDT",)

    def test_input_order_does_not_change_the_answer(self) -> None:
        intervals = roster_shift_intervals()
        assert resolve_membership(
            tuple(reversed(intervals)), dt.date(2026, 4, 15)
        ) == resolve_membership(intervals, dt.date(2026, 4, 15))

    def test_resolution_is_reproducible(self) -> None:
        intervals = roster_shift_intervals()
        assert resolve_membership(intervals, dt.date(2026, 4, 15)) == resolve_membership(
            intervals, dt.date(2026, 4, 15)
        )

    def test_an_empty_table_resolves_empty(self) -> None:
        assert resolve_membership((), dt.date(2026, 4, 15)) == ()


class TestResolutionMatchesTheBuilds:
    """For a day inside a month, the resolution *is* that month's roster."""

    def test_every_month_resolves_to_its_own_builds_roster(self) -> None:
        # The property a MarketWindow's universe tuple consumes: asking as
        # of any day in May returns exactly the May build's symbols — not
        # June's, not the union, not today's.
        builds = builds_for(roster_shift_months())
        intervals = membership_intervals(builds)
        for universe in builds:
            assert resolve_membership(intervals, mid_month(universe.month)) == tuple(
                sorted(universe.symbols)
            )

    def test_resolving_a_sweep_of_days_never_leaks_a_later_roster(self) -> None:
        # Every day from April 1 to June 30, resolved: BBB appears exactly
        # on April's days and never after, even once June's build exists.
        builds = builds_for(roster_shift_months())
        intervals = membership_intervals(builds)
        day = dt.date(2026, 4, 1)
        last = dt.date(2026, 6, 30)
        while day <= last:
            answer = resolve_membership(intervals, day)
            if day < dt.date(2026, 5, 1):
                assert answer == ("AAAUSDT", "BBBUSDT"), day
            else:
                assert answer == ("AAAUSDT",), day
            day += dt.timedelta(days=1)


class TestResolveThroughTheService:
    """The facade binds the pure resolution to the persisted table."""

    def service(self, url: "str | None" = None) -> UniverseService:
        # ``url`` omitted means the service's own store: the conftest has
        # pointed DATABASE_URL at this test's isolated database.
        return UniverseService(config=FIVE_SYMBOLS, database_url=url)

    def persisted(self, url: "str | None" = None) -> UniverseService:
        service = self.service(url)
        for universe in builds_for(roster_shift_months()):
            service.persist(universe)
        return service

    def test_a_decision_time_reads_the_roster_of_then_not_of_now(
        self, test_database_url: str
    ) -> None:
        service = self.persisted(test_database_url)
        # "Now": the newest build the store holds is June, AAA alone.
        assert service.load("2026-06") is not None
        assert service.load("2026-06").symbols == ("AAAUSDT",)
        # "Then": asked as of mid-April, BBB answers.
        assert service.resolve(dt.date(2026, 4, 15)) == ("AAAUSDT", "BBBUSDT")
        assert service.resolve(dt.date(2026, 5, 15)) == ("AAAUSDT",)

    def test_the_facade_agrees_with_the_pure_resolution(
        self, test_database_url: str
    ) -> None:
        # One spelling: the service must answer exactly what resolving
        # against the table it loaded answers, for decision times across
        # the whole history.
        service = self.persisted(test_database_url)
        intervals = service.membership()
        for when in (
            dt.date(2026, 1, 1),
            dt.date(2026, 4, 1),
            dt.date(2026, 4, 15),
            dt.date(2026, 4, 30),
            dt.date(2026, 5, 1),
            dt.date(2026, 6, 15),
            "2026-05-15",
        ):
            assert service.resolve(when) == resolve_membership(intervals, when)

    def test_a_decision_time_before_any_build_is_empty(
        self, test_database_url: str
    ) -> None:
        service = self.persisted(test_database_url)
        assert service.resolve(dt.date(2026, 1, 1)) == ()

    def test_an_empty_store_resolves_empty(self, test_database_url: str) -> None:
        assert self.service(test_database_url).resolve(dt.date(2026, 4, 15)) == ()

    def test_a_backfilled_month_corrects_the_answer_retroactively(
        self, test_database_url: str
    ) -> None:
        # May and June land first (AAA alone); with no April build, April
        # resolves empty — an absence of evidence. Backfilling April's
        # build re-derives the table, and the same decision time now
        # returns the roster April actually had.
        service = self.service(test_database_url)
        for universe in builds_for(
            {"2026-05": {"AAAUSDT": 100.0}, "2026-06": {"AAAUSDT": 100.0}}
        ):
            service.persist(universe)
        assert service.resolve(dt.date(2026, 4, 15)) == ()
        april = build_monthly_universe(
            trades("2026-04", {"AAAUSDT": 100.0, "BBBUSDT": 50.0}),
            "2026-04",
            FIVE_SYMBOLS,
        )
        service.persist(april)
        assert service.resolve(dt.date(2026, 4, 15)) == ("AAAUSDT", "BBBUSDT")
        assert service.resolve(dt.date(2026, 6, 15)) == ("AAAUSDT",)

    def test_resolve_routes_to_an_explicit_store(self, tmp_path) -> None:
        other = f"sqlite:///{tmp_path / 'other.db'}"
        service = self.service()
        for universe in builds_for(roster_shift_months()):
            service.persist(universe, other)
        assert service.resolve(dt.date(2026, 4, 15), other) == ("AAAUSDT", "BBBUSDT")
        # The service's own store was never written: no leakage of "then"
        # into a store that holds no history at all.
        assert service.resolve(dt.date(2026, 4, 15)) == ()
