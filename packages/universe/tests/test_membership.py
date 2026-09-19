"""Acceptance tests for the point-in-time universe membership table.

Feature 41: ``universe_membership`` rows carrying ``symbol``,
``valid_from``, ``valid_to`` and ``delist_reason`` (app_spec.xml; the
table's shape is fixed by the spec's schema block, and architecture §4.3
gives it its meaning — "any ``MarketWindow`` at time ``t`` resolves
membership as of ``t``, never as of now").

The derivation is a pure function of the persisted builds, so most of what
follows pins that function directly; the persistence tests then pin the
store's part — that the table is written, readable, re-derived on every
persist, and never left disagreeing with the builds it came from.
"""

import datetime as dt

import pytest

from universe import (
    DailyBar,
    MembershipInterval,
    UniverseConfig,
    build_monthly_universe,
    load_all_monthly_universes,
    load_universe_membership,
    membership_intervals,
    persist_monthly_universe,
    persist_universe_membership,
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
    """Bars inside ``month``'s trailing window, one symbol per volume given.

    Volumes are per-build-window, which is how a symbol's liquidity is made
    to rise and fall from one month's trailing window to the next.
    """
    start, end = window(month)
    return [
        bar for symbol, volume in volumes.items() for bar in daily(symbol, start, end, volume)
    ]


def bars_for(months: dict[str, dict[str, float]]) -> list[DailyBar]:
    """Bars covering each named month's trailing window with its volumes."""
    return [bar for month, volumes in months.items() for bar in trades(month, volumes)]


def builds_for(
    months: dict[str, dict[str, float]], config: UniverseConfig = FIVE_SYMBOLS
) -> list:
    """One build per named month, oldest first.

    Sorted rather than left in dict order: tests index the result by
    position (``builds[1]`` is the second month), so the order must be the
    calendar's, not the literal's.
    """
    return [
        build_monthly_universe(bars_for({month: volumes}), month, config)
        for month, volumes in sorted(months.items())
    ]


class TestIntervalShape:
    """An interval is the shape feature 41 names, and nothing else."""

    def test_admitted_symbol_yields_one_open_interval(self) -> None:
        (universe,) = builds_for({"2026-05": {"AAAUSDT": 100.0}})
        (interval,) = membership_intervals([universe])
        assert interval.symbol == "AAAUSDT"
        assert interval.valid_from == dt.date(2026, 5, 1)
        assert interval.valid_to is None
        assert interval.delist_reason is None
        assert interval.is_open

    def test_valid_from_is_the_first_day_of_the_first_admitted_month(self) -> None:
        # Effective-from, not window start: a symbol is a member for the
        # month the build is *for*, so May's build opens on May 1.
        (universe,) = builds_for({"2026-05": {"AAAUSDT": 100.0}})
        (interval,) = membership_intervals([universe])
        assert interval.valid_from == universe.effective_from

    def test_open_interval_carries_no_reason(self) -> None:
        # A reason without an end would assert a departure no build records.
        (universe,) = builds_for({"2026-05": {"AAAUSDT": 100.0}})
        (interval,) = membership_intervals([universe])
        assert (interval.valid_to, interval.delist_reason) == (None, None)

    def test_closed_interval_always_carries_a_reason(self) -> None:
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0}}
        )
        closed = [interval for interval in membership_intervals(builds) if not interval.is_open]
        assert closed, "the departed symbol should have closed an interval"
        assert all(interval.delist_reason for interval in closed)

    def test_valid_to_is_exclusive_and_is_the_closing_months_first_day(self) -> None:
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0}}
        )
        (bbb,) = [i for i in membership_intervals(builds) if i.symbol == "BBBUSDT"]
        assert bbb.valid_from == dt.date(2026, 4, 1)
        assert bbb.valid_to == dt.date(2026, 5, 1)
        # Exclusive: April 30 is inside, May 1 is not.
        assert bbb.covers(dt.date(2026, 4, 30))
        assert not bbb.covers(dt.date(2026, 5, 1))

    def test_covers_is_inclusive_at_the_start(self) -> None:
        interval = MembershipInterval("AAAUSDT", dt.date(2026, 4, 1), dt.date(2026, 5, 1))
        assert interval.covers(dt.date(2026, 4, 1))
        assert not interval.covers(dt.date(2026, 3, 31))

    def test_empty_interval_rejected(self) -> None:
        with pytest.raises(ValueError, match="AAAUSDT"):
            MembershipInterval("AAAUSDT", dt.date(2026, 5, 1), dt.date(2026, 5, 1))

    def test_reversed_interval_rejected(self) -> None:
        with pytest.raises(ValueError, match="AAAUSDT"):
            MembershipInterval("AAAUSDT", dt.date(2026, 5, 1), dt.date(2026, 4, 1))

    def test_blank_symbol_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            MembershipInterval("  ", dt.date(2026, 5, 1))

    def test_datetimes_are_pinned_to_their_calendar_day(self) -> None:
        # An interval bound names a day; a datetime must not smuggle a time
        # component into a column the spec types as DATE.
        interval = MembershipInterval(
            "AAAUSDT",
            dt.datetime(2026, 4, 1, 12, 0),
            dt.datetime(2026, 5, 1, 6, 30),
            "reason",
        )
        assert interval.valid_from == dt.date(2026, 4, 1)
        assert interval.valid_to == dt.date(2026, 5, 1)
        assert type(interval.valid_from) is dt.date

    def test_covers_accepts_iso_strings_and_timestamps(self) -> None:
        interval = MembershipInterval("AAAUSDT", dt.date(2026, 4, 1), dt.date(2026, 5, 1))
        assert interval.covers("2026-04-15")
        assert interval.covers("2026-04-15T00:00:00+00:00")
        assert not interval.covers("2026-05-01")

    def test_non_date_valid_from_rejected(self) -> None:
        # A non-date bound is a caller error, not something to coerce into a
        # plausible-looking interval.
        with pytest.raises(TypeError, match="valid_from"):
            MembershipInterval("AAAUSDT", "2026-04-01")  # type: ignore[arg-type]

    def test_non_date_valid_to_rejected(self) -> None:
        with pytest.raises(TypeError, match="valid_to"):
            MembershipInterval("AAAUSDT", dt.date(2026, 4, 1), 5)  # type: ignore[arg-type]

    def test_interval_is_frozen(self) -> None:
        import dataclasses

        interval = MembershipInterval("AAAUSDT", dt.date(2026, 5, 1))
        with pytest.raises(dataclasses.FrozenInstanceError):
            interval.valid_to = dt.date(2026, 6, 1)  # type: ignore[misc]


class TestRunMerging:
    """Consecutive admitted months are one interval; a gap starts a new one."""

    def test_consecutive_months_merge_into_one_interval(self) -> None:
        builds = builds_for(
            {
                "2026-04": {"AAAUSDT": 100.0},
                "2026-05": {"AAAUSDT": 100.0},
                "2026-06": {"AAAUSDT": 100.0},
            }
        )
        (interval,) = membership_intervals(builds)
        assert interval.valid_from == dt.date(2026, 4, 1)
        assert interval.valid_to is None
        assert interval.is_open

    def test_a_gap_starts_a_second_interval(self) -> None:
        # Member in April and June, not May: two intervals, because
        # flattening that into one would claim a May membership that no
        # persisted build records.
        builds = builds_for({"2026-04": {"AAAUSDT": 100.0}, "2026-06": {"AAAUSDT": 100.0}})
        first, second = membership_intervals(builds)
        assert (first.valid_from, first.valid_to) == (dt.date(2026, 4, 1), dt.date(2026, 5, 1))
        assert (second.valid_from, second.valid_to) == (dt.date(2026, 6, 1), None)

    def test_rejoining_starts_a_new_interval_from_the_rejoin_month(self) -> None:
        builds = builds_for(
            {
                "2026-04": {"AAAUSDT": 100.0},
                "2026-05": {"BBBUSDT": 100.0},
                "2026-06": {"AAAUSDT": 100.0},
            }
        )
        aaa = [i for i in membership_intervals(builds) if i.symbol == "AAAUSDT"]
        assert [(i.valid_from, i.valid_to) for i in aaa] == [
            (dt.date(2026, 4, 1), dt.date(2026, 5, 1)),
            (dt.date(2026, 6, 1), None),
        ]

    def test_a_year_boundary_does_not_break_the_run(self) -> None:
        builds = builds_for({"2026-12": {"AAAUSDT": 100.0}, "2027-01": {"AAAUSDT": 100.0}})
        (interval,) = membership_intervals(builds)
        assert interval.valid_from == dt.date(2026, 12, 1)
        assert interval.is_open


class TestEndReasons:
    """Every closed interval explains itself from the persisted builds."""

    def test_out_ranked_symbol_gets_the_not_admitted_reason(self) -> None:
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0}}
        )
        (bbb,) = [i for i in membership_intervals(builds) if i.symbol == "BBBUSDT"]
        assert bbb.delist_reason == (
            "not admitted to the 2026-05 universe: not among the symbols "
            "its build admitted"
        )

    def test_floor_refused_symbol_gets_the_persisted_floor_reason(self) -> None:
        # BBB is liquid in April's window and thin in May's, so May's build
        # excludes it by the floor — and the interval's reason quotes that
        # persisted exclusion verbatim rather than inventing a second one.
        config = UniverseConfig(top_n=5, min_dollar_volume=10.0)
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0, "BBBUSDT": 5.0}},
            config,
        )
        may = builds[1]
        assert may.excluded_symbols == ("BBBUSDT",)
        (bbb,) = [i for i in membership_intervals(builds) if i.symbol == "BBBUSDT"]
        assert bbb.delist_reason == f"not admitted to the 2026-05 universe: {may.exclusions[0].reason}"
        assert "falls below the configured floor of 10.0" in bbb.delist_reason

    def test_unobserved_month_gets_the_no_build_reason(self) -> None:
        # April then June, with no May build persisted at all: an absence of
        # evidence, recorded as such rather than as an out-ranking.
        builds = builds_for({"2026-04": {"AAAUSDT": 100.0}, "2026-06": {"AAAUSDT": 100.0}})
        first, _ = membership_intervals(builds)
        assert first.delist_reason == (
            "membership unobserved after 2026-04: no universe build was "
            "persisted for 2026-05"
        )

    def test_a_build_that_admits_nobody_still_closes_the_interval(self) -> None:
        # May's build exists and admits nobody; the closure is the build's
        # doing, so the reason names the build rather than claiming a gap.
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0}, "2026-05": {"ZZZUSDT": 1.0}, "2026-06": {"AAAUSDT": 100.0}}
        )
        aaa = [i for i in membership_intervals(builds) if i.symbol == "AAAUSDT"]
        assert aaa[0].delist_reason == (
            "not admitted to the 2026-05 universe: not among the symbols "
            "its build admitted"
        )

    def test_reasons_are_distinct_across_the_three_causes(self) -> None:
        # An audit reading the reason column must be able to tell the three
        # causes apart without the build beside it; identical text would
        # collapse exactly the distinction feature 44 counts on.
        floor_config = UniverseConfig(top_n=5, min_dollar_volume=10.0)
        out_ranked, unobserved = (
            membership_intervals(
                builds_for(
                    {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0}}
                )
            )[1].delist_reason,
            membership_intervals(
                builds_for({"2026-04": {"AAAUSDT": 100.0}, "2026-06": {"AAAUSDT": 100.0}})
            )[0].delist_reason,
        )
        floored = membership_intervals(
            builds_for(
                {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0, "BBBUSDT": 5.0}},
                floor_config,
            )
        )[1].delist_reason
        assert len({out_ranked, unobserved, floored}) == 3


class TestDerivationIsPure:
    """The same builds always give the same rows, in the same order."""

    def test_derivation_is_reproducible(self) -> None:
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0}}
        )
        assert membership_intervals(builds) == membership_intervals(builds)

    def test_derivation_is_independent_of_input_order(self) -> None:
        builds = builds_for(
            {"2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0}, "2026-05": {"AAAUSDT": 100.0}}
        )
        assert membership_intervals(list(reversed(builds))) == membership_intervals(builds)

    def test_rows_are_ordered_by_valid_from_then_symbol(self) -> None:
        builds = builds_for(
            {"2026-05": {"ZZZUSDT": 100.0, "AAAUSDT": 90.0}, "2026-06": {"AAAUSDT": 90.0}}
        )
        keys = [(i.valid_from, i.symbol) for i in membership_intervals(builds)]
        assert keys == sorted(keys)

    def test_no_builds_yields_no_rows(self) -> None:
        assert membership_intervals([]) == ()

    def test_a_duplicated_month_keeps_the_last_build_given(self) -> None:
        first = build_monthly_universe(
            bars_for({"2026-04": {"AAAUSDT": 100.0}}), "2026-05", FIVE_SYMBOLS
        )
        restated = build_monthly_universe(
            bars_for({"2026-04": {"BBBUSDT": 100.0}}), "2026-05", FIVE_SYMBOLS
        )
        assert membership_intervals([first, restated]) == membership_intervals([restated])


def three_months() -> list:
    """April, May, June builds: BBB departs after April."""
    return builds_for(
        {
            "2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0},
            "2026-05": {"AAAUSDT": 100.0},
            "2026-06": {"AAAUSDT": 100.0},
        }
    )


class TestMembershipPersistence:
    """The table is written, readable, and derived from the builds (feature 41)."""

    def test_persist_writes_membership_rows(self, test_database_url: str) -> None:
        for universe in three_months():
            persist_monthly_universe(universe, test_database_url)
        rows = load_universe_membership(test_database_url)
        assert [(r.symbol, r.valid_from, r.valid_to) for r in rows] == [
            ("AAAUSDT", dt.date(2026, 4, 1), None),
            ("BBBUSDT", dt.date(2026, 4, 1), dt.date(2026, 5, 1)),
        ]
        assert [r.delist_reason for r in rows] == [
            None,
            "not admitted to the 2026-05 universe: not among the symbols "
            "its build admitted",
        ]

    def test_persisted_rows_equal_the_derivation(self, test_database_url: str) -> None:
        builds = three_months()
        for universe in builds:
            persist_monthly_universe(universe, test_database_url)
        assert load_universe_membership(test_database_url) == membership_intervals(builds)

    def test_persisted_rows_equal_the_derivation_from_the_store(
        self, test_database_url: str
    ) -> None:
        # Re-reading the builds out of the store and re-deriving must give
        # the persisted table back: that is what makes the table safe for a
        # later replay to resolve against rather than re-author.
        for universe in three_months():
            persist_monthly_universe(universe, test_database_url)
        assert load_universe_membership(test_database_url) == membership_intervals(
            load_all_monthly_universes(test_database_url)
        )

    def test_column_names_match_the_spec(self, test_database_url: str) -> None:
        from contextlib import closing

        from universe.store import connect

        with closing(connect(test_database_url)) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(universe_membership)")
            ]
        assert columns == ["symbol", "valid_from", "valid_to", "delist_reason"]

    def test_dates_are_stored_as_iso_text(self, test_database_url: str) -> None:
        from contextlib import closing

        from universe.store import connect

        persist_monthly_universe(three_months()[0], test_database_url)
        with closing(connect(test_database_url)) as connection:
            rows = connection.execute(
                "SELECT symbol, valid_from, valid_to FROM universe_membership"
            ).fetchall()
        assert ("AAAUSDT", "2026-04-01", None) in rows
        assert all(
            isinstance(row[1], str) for row in rows
        ), "an ISO date string, so the column reads the same in SQLite and Postgres"

    def test_open_interval_persists_null_bounds_and_reason(
        self, test_database_url: str
    ) -> None:
        # April's build admits AAA and BBB and nothing later exists, so both
        # rows are open — and an open row carries neither an end nor a
        # reason, rather than an end no build vouches for.
        persist_monthly_universe(three_months()[0], test_database_url)
        rows = load_universe_membership(test_database_url)
        assert rows
        assert all((row.valid_to, row.delist_reason, row.is_open) == (None, None, True) for row in rows)

    def test_a_later_build_closes_an_open_interval(
        self, test_database_url: str
    ) -> None:
        april, may, _ = three_months()
        persist_monthly_universe(april, test_database_url)
        assert all(row.is_open for row in load_universe_membership(test_database_url))
        persist_monthly_universe(may, test_database_url)
        bbb = [r for r in load_universe_membership(test_database_url) if r.symbol == "BBBUSDT"]
        assert len(bbb) == 1 and not bbb[0].is_open

    def test_a_new_build_extends_a_run_and_reopens_a_departed_symbol(
        self, test_database_url: str
    ) -> None:
        # BBB leaves after April and comes back in July: through the store
        # that is one closed April interval plus a fresh open one, while
        # AAA's unbroken April–July run stays a single interval.
        months = {
            "2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0},
            "2026-05": {"AAAUSDT": 100.0},
            "2026-06": {"AAAUSDT": 100.0},
            "2026-07": {"AAAUSDT": 100.0, "BBBUSDT": 500.0},
        }
        for universe in builds_for(months):
            persist_monthly_universe(universe, test_database_url)
        rows = load_universe_membership(test_database_url)
        assert [r for r in rows if r.symbol == "AAAUSDT"] == [
            MembershipInterval("AAAUSDT", dt.date(2026, 4, 1))
        ]
        assert [r for r in rows if r.symbol == "BBBUSDT"] == [
            MembershipInterval(
                "BBBUSDT",
                dt.date(2026, 4, 1),
                dt.date(2026, 5, 1),
                "not admitted to the 2026-05 universe: not among the symbols "
                "its build admitted",
            ),
            MembershipInterval("BBBUSDT", dt.date(2026, 7, 1)),
        ]
        # Persisting one month at a time and all at once agree, so a live
        # append and a full rebuild produce the same table.
        assert rows == membership_intervals(load_all_monthly_universes(test_database_url))

    def test_restating_a_month_rewrites_membership_atomically(
        self, test_database_url: str
    ) -> None:
        april, may, june = three_months()
        for universe in (april, may, june):
            persist_monthly_universe(universe, test_database_url)
        # April is restated: BBB is gone from it entirely, so its interval
        # must disappear rather than survive as a stale row.
        restated = build_monthly_universe(
            bars_for({"2026-04": {"AAAUSDT": 100.0}}), "2026-04", FIVE_SYMBOLS
        )
        persist_monthly_universe(restated, test_database_url)
        symbols = {row.symbol for row in load_universe_membership(test_database_url)}
        assert symbols == {"AAAUSDT"}
        assert load_universe_membership(test_database_url) == membership_intervals(
            load_all_monthly_universes(test_database_url)
        )

    def test_persisting_the_same_build_twice_is_idempotent(
        self, test_database_url: str
    ) -> None:
        april = three_months()[0]
        persist_monthly_universe(april, test_database_url)
        once = load_universe_membership(test_database_url)
        persist_monthly_universe(april, test_database_url)
        assert load_universe_membership(test_database_url) == once

    def test_rebuild_membership_repairs_a_dropped_table(
        self, test_database_url: str
    ) -> None:
        from contextlib import closing

        from universe.store import connect

        for universe in three_months():
            persist_monthly_universe(universe, test_database_url)
        expected = load_universe_membership(test_database_url)
        with closing(connect(test_database_url)) as connection, connection:
            connection.execute("DELETE FROM universe_membership")
        assert load_universe_membership(test_database_url) == ()
        assert persist_universe_membership(test_database_url) == len(expected)
        assert load_universe_membership(test_database_url) == expected

    def test_rebuild_membership_is_idempotent(self, test_database_url: str) -> None:
        for universe in three_months():
            persist_monthly_universe(universe, test_database_url)
        once = persist_universe_membership(test_database_url)
        assert persist_universe_membership(test_database_url) == once
        assert len(load_universe_membership(test_database_url)) == once

    def test_interval_closes_across_a_year_boundary(
        self, test_database_url: str
    ) -> None:
        # December then January: a run that spans the year end must merge
        # (January is the month after December), and when the symbol then
        # departs, the closing date is the following February — not a
        # rolled-over month number that never arrives.
        for universe in builds_for(
            {
                "2026-12": {"AAAUSDT": 100.0},
                "2027-01": {"AAAUSDT": 100.0},
                "2027-02": {"BBBUSDT": 100.0},
            }
        ):
            persist_monthly_universe(universe, test_database_url)
        (row,) = [
            r for r in load_universe_membership(test_database_url) if r.symbol == "AAAUSDT"
        ]
        assert row.valid_from == dt.date(2026, 12, 1)
        assert row.valid_to == dt.date(2027, 2, 1)
        assert not row.is_open

    def test_persisting_months_out_of_order_converges(
        self, test_database_url: str, tmp_path
    ) -> None:
        # Backfilling an earlier month after a later one is a real
        # workflow (a late bar restatement arrives, the month is rebuilt).
        # Because every persist re-derives from the builds, the order the
        # months land in cannot change the table — the reverse-order store
        # and the chronological one must agree exactly.
        months = {
            "2026-04": {"AAAUSDT": 100.0, "BBBUSDT": 50.0},
            "2026-05": {"AAAUSDT": 100.0},
            "2026-06": {"AAAUSDT": 100.0},
        }
        builds = builds_for(months)
        chronological = f"sqlite:///{tmp_path / 'chronological.db'}"
        reversed_order = f"sqlite:///{tmp_path / 'reversed.db'}"
        for universe in builds:
            persist_monthly_universe(universe, chronological)
        for universe in reversed(builds):
            persist_monthly_universe(universe, reversed_order)
        assert load_universe_membership(reversed_order) == load_universe_membership(
            chronological
        )
        assert load_universe_membership(reversed_order) == membership_intervals(builds)

    def test_empty_store_has_an_empty_membership_table(
        self, test_database_url: str
    ) -> None:
        assert load_universe_membership(test_database_url) == ()
        assert persist_universe_membership(test_database_url) == 0

    def test_membership_table_is_created_with_the_schema(
        self, test_database_url: str
    ) -> None:
        from contextlib import closing

        from universe.store import connect

        with closing(connect(test_database_url)) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "universe_membership" in names

    def test_membership_does_not_leak_between_stores(self, tmp_path) -> None:
        first = f"sqlite:///{tmp_path / 'first.db'}"
        second = f"sqlite:///{tmp_path / 'second.db'}"
        persist_monthly_universe(three_months()[0], first)
        assert load_universe_membership(second) == ()


class TestServiceMembership:
    """The component exposes membership through the service facade."""

    def test_service_persist_loads_membership(self, test_database_url: str) -> None:
        from universe import UniverseService

        service = UniverseService(config=FIVE_SYMBOLS)
        for universe in three_months():
            service.persist(universe)
        rows = service.membership()
        assert [row.symbol for row in rows] == ["AAAUSDT", "BBBUSDT"]
        assert rows == membership_intervals(service.load_all())

    def test_service_rebuild_membership(self, test_database_url: str) -> None:
        from universe import UniverseService

        service = UniverseService(config=FIVE_SYMBOLS)
        for universe in three_months():
            service.persist(universe)
        expected = service.membership()
        assert service.rebuild_membership() == len(expected)
        assert service.membership() == expected

    def test_service_routes_to_an_explicit_store(self, tmp_path) -> None:
        from universe import UniverseService

        other = f"sqlite:///{tmp_path / 'other.db'}"
        service = UniverseService(config=FIVE_SYMBOLS)
        for universe in three_months():
            service.persist(universe, other)
        assert service.membership(other) == membership_intervals(service.load_all(other))
        assert service.load_all() == ()
