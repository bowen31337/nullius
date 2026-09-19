"""Acceptance tests for the monthly top-N-by-median-dollar-volume build.

The invariants under test are the ones the system's honesty rests on:

* causality — a bar dated inside the effective month (or later) cannot
  move that month's universe, because the trailing window ends the day
  before the month starts;
* the median, not the mean — one spike day must not buy a thin symbol a
  month of top-N membership;
* determinism — equal inputs give equal members, ranks and medians, with
  symbol-ascending tie-breaks making the ranking a total order.
"""

import datetime as dt

import pytest

from universe import (
    DailyBar,
    UniverseConfig,
    build_monthly_universe,
    build_monthly_universes,
    median_dollar_volumes,
    month_key,
    month_start,
)

APRIL_1 = dt.date(2026, 4, 1)
MAY_1 = dt.date(2026, 5, 1)


def april_days() -> list[dt.date]:
    # April 2026 has 30 days: exactly the default trailing window for May.
    return [APRIL_1 + dt.timedelta(days=offset) for offset in range(30)]


def steady_bars(symbol: str, volume: float, days: list[dt.date]) -> list[DailyBar]:
    return [DailyBar(symbol, day, volume) for day in days]


class TestSingleMonthBuild:
    def test_top_n_ranks_by_median_dollar_volume(self) -> None:
        bars = (
            steady_bars("AAAUSDT", 100.0, april_days())
            + steady_bars("BBBUSDT", 200.0, april_days())
            + steady_bars("CCCUSDT", 50.0, april_days())
        )
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=2))
        assert universe.month == "2026-05"
        assert universe.symbols == ("BBBUSDT", "AAAUSDT")
        assert [member.rank for member in universe.members] == [1, 2]
        assert universe.members[0].median_dollar_volume == 200.0
        assert universe.members[1].median_dollar_volume == 100.0

    def test_median_not_mean_spike_does_not_dominate(self) -> None:
        # One liquidation-cascade day gives BBBB a far higher *mean* dollar
        # volume, but a lower *median*. The universe ranks by the median.
        spiky = [
            DailyBar("BBBUSDT", day, 1.0) for day in april_days()[:-1]
        ] + [DailyBar("BBBUSDT", april_days()[-1], 1_000_000.0)]
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + spiky
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=2))
        assert universe.symbols[0] == "AAAUSDT"
        assert universe.members[1].symbol == "BBBUSDT"
        assert universe.members[1].median_dollar_volume == 1.0

    def test_window_is_trailing_thirty_days_ending_before_month(self) -> None:
        universe = build_monthly_universe(steady_bars("AAAUSDT", 1.0, april_days()), MAY_1)
        assert universe.effective_from == MAY_1
        assert universe.window_start == dt.date(2026, 4, 1)
        assert universe.window_end == dt.date(2026, 4, 30)

    def test_window_is_a_plain_thirty_day_lookback_not_a_calendar_month(self) -> None:
        # A 30-day window only coincides with a calendar month when that
        # month has exactly 30 days (July's window is precisely June).
        # Otherwise it is a plain 30-day lookback: March's window reaches
        # back into January ([Jan 30, Feb 28]), and April's starts on
        # March 2 because March has 31 days.
        march = build_monthly_universe([], dt.date(2026, 3, 1))
        assert (march.window_start, march.window_end) == (
            dt.date(2026, 1, 30),
            dt.date(2026, 2, 28),
        )
        april = build_monthly_universe([], dt.date(2026, 4, 1))
        assert (april.window_start, april.window_end) == (
            dt.date(2026, 3, 2),
            dt.date(2026, 3, 31),
        )
        july = build_monthly_universe([], dt.date(2026, 7, 1))
        assert (july.window_start, july.window_end) == (
            dt.date(2026, 6, 1),
            dt.date(2026, 6, 30),
        )

    def test_month_input_normalized_to_first_of_month(self) -> None:
        bars = steady_bars("AAAUSDT", 10.0, april_days())
        by_date = build_monthly_universe(bars, dt.date(2026, 5, 17))
        by_string = build_monthly_universe(bars, "2026-05")
        assert by_date.month == "2026-05"
        assert by_date.effective_from == MAY_1
        assert by_date == by_string

    def test_in_month_bars_cannot_influence_membership(self) -> None:
        # DDD trades a fortune *inside* May and nothing before it: May's
        # universe must not admit it, because at 00:00 on May 1 nobody
        # could have known.
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + [
            DailyBar("DDDUSDT", dt.date(2026, 5, 15), 10_000_000.0),
            DailyBar("DDDUSDT", dt.date(2026, 6, 1), 10_000_000.0),
        ]
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=10))
        assert "DDDUSDT" not in universe.symbols
        assert universe.symbols == ("AAAUSDT",)

    def test_bars_just_outside_window_ignored_but_boundary_counts(self) -> None:
        # March 31 sits one day before the window opens; April 1 and
        # April 30 are the window's inclusive ends.
        bars = [
            DailyBar("EEEUSDT", dt.date(2026, 3, 31), 999_999.0),
            DailyBar("FFFUSDT", dt.date(2026, 4, 1), 1.0),
            DailyBar("GGGUSDT", dt.date(2026, 4, 30), 2.0),
        ]
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=10))
        assert universe.symbols == ("GGGUSDT", "FFFUSDT")

    def test_exact_float_tie_broken_by_symbol_ascending(self) -> None:
        bars = steady_bars("ZZZUSDT", 100.0, april_days()[:2]) + steady_bars(
            "AAAUSDT", 100.0, april_days()[:2]
        )
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=5))
        assert universe.symbols == ("AAAUSDT", "ZZZUSDT")
        assert [m.rank for m in universe.members] == [1, 2]

    def test_top_n_larger_than_eligible_count_admits_all(self) -> None:
        bars = steady_bars("AAAUSDT", 10.0, april_days()[:3])
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=50))
        assert len(universe.members) == 1
        assert universe.members[0].rank == 1

    def test_min_observations_excludes_thin_history(self) -> None:
        bars = steady_bars("AAAUSDT", 1_000.0, april_days()[:5]) + steady_bars(
            "BBBUSDT", 1.0, april_days()
        )
        strict = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=10, min_observations=5)
        )
        lenient = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=10))
        assert "AAAUSDT" in strict.symbols  # exactly at the floor: eligible
        bars_thinner = steady_bars("AAAUSDT", 1_000.0, april_days()[:4]) + steady_bars(
            "BBBUSDT", 1.0, april_days()
        )
        excluded = build_monthly_universe(
            bars_thinner, MAY_1, UniverseConfig(top_n=10, min_observations=5)
        )
        assert "AAAUSDT" not in excluded.symbols
        assert "AAAUSDT" in lenient.symbols

    def test_duplicate_symbol_date_collapses_to_last_value(self) -> None:
        day = april_days()[0]
        bars = [
            DailyBar("AAAUSDT", day, 1.0),
            DailyBar("AAAUSDT", day, 3.0),  # restated bar wins
            DailyBar("AAAUSDT", april_days()[1], 3.0),
        ]
        medians = median_dollar_volumes(
            bars, dt.date(2026, 4, 1), dt.date(2026, 4, 30)
        )
        assert medians == {"AAAUSDT": 3.0}

    def test_empty_window_yields_empty_but_well_formed_universe(self) -> None:
        universe = build_monthly_universe([], MAY_1)
        assert universe.month == "2026-05"
        assert universe.members == ()
        assert universe.symbols == ()
        assert len(universe) == 0

    def test_rebuild_is_bit_identical(self) -> None:
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + steady_bars(
            "BBBUSDT", 150.0, april_days()
        )
        config = UniverseConfig(top_n=1)
        assert build_monthly_universe(bars, MAY_1, config) == build_monthly_universe(
            bars, MAY_1, config
        )

    def test_input_iterable_consumed_once_is_enough(self) -> None:
        # A generator, not a list: the build must not require re-iteration.
        bars = (bar for bar in steady_bars("AAAUSDT", 5.0, april_days()))
        universe = build_monthly_universe(bars, MAY_1)
        assert universe.symbols == ("AAAUSDT",)

    def test_config_defaults_apply_when_omitted(self) -> None:
        universe = build_monthly_universe(
            steady_bars("AAAUSDT", 1.0, april_days()), MAY_1
        )
        assert universe.config == UniverseConfig()


class TestLiquidityFloor:
    """The eligibility floor (feature 47): below it, excluded with a reason."""

    def test_below_floor_symbol_excluded_even_with_room_in_top_n(self) -> None:
        # top_n=10 seats everyone eligible; the floor still refuses BBB.
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + steady_bars(
            "BBBUSDT", 5.0, april_days()
        )
        universe = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=10, min_dollar_volume=10.0)
        )
        assert universe.symbols == ("AAAUSDT",)
        assert universe.excluded_symbols == ("BBBUSDT",)
        assert universe.exclusions[0].median_dollar_volume == 5.0

    def test_symbol_exactly_at_the_floor_stays_eligible(self) -> None:
        # "Falls below" is strict: the boundary belongs to the tradable
        # side, or every floor would silently exclude its own threshold.
        universe = build_monthly_universe(
            steady_bars("AAAUSDT", 100.0, april_days()),
            MAY_1,
            UniverseConfig(top_n=10, min_dollar_volume=100.0),
        )
        assert universe.symbols == ("AAAUSDT",)
        assert universe.exclusions == ()

    def test_floor_applies_before_ranking(self) -> None:
        # Ranks are conferred among the eligible only: CCC never reaches
        # the ranking, so AAA and BBB hold ranks 1 and 2, not 1 and 3.
        bars = (
            steady_bars("AAAUSDT", 300.0, april_days())
            + steady_bars("BBBUSDT", 100.0, april_days())
            + steady_bars("CCCUSDT", 50.0, april_days())
        )
        universe = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=2, min_dollar_volume=60.0)
        )
        assert universe.symbols == ("AAAUSDT", "BBBUSDT")
        assert [member.rank for member in universe.members] == [1, 2]
        assert universe.excluded_symbols == ("CCCUSDT",)

    def test_exclusion_reason_names_the_median_and_the_floor(self) -> None:
        universe = build_monthly_universe(
            steady_bars("AAAUSDT", 5.0, april_days()),
            MAY_1,
            UniverseConfig(top_n=10, min_dollar_volume=10.0),
        )
        (exclusion,) = universe.exclusions
        assert exclusion.symbol == "AAAUSDT"
        assert exclusion.reason == (
            "trailing-window median dollar volume 5.0 falls below "
            "the configured floor of 10.0"
        )

    def test_exclusions_are_sorted_by_symbol_regardless_of_bar_order(self) -> None:
        # Exclusions carry no rank; determinism still demands a total
        # order, and it must not inherit the order bars arrived in.
        reversed_bars = steady_bars("ZZZUSDT", 1.0, april_days()) + steady_bars(
            "MMMUSDT", 2.0, april_days()
        ) + steady_bars("AAAUSDT", 3.0, april_days())
        forward_bars = list(reversed(reversed_bars))
        config = UniverseConfig(top_n=10, min_dollar_volume=10.0)
        for bars in (reversed_bars, forward_bars):
            universe = build_monthly_universe(bars, MAY_1, config)
            assert universe.excluded_symbols == ("AAAUSDT", "MMMUSDT", "ZZZUSDT")

    def test_floor_zero_by_default_excludes_nothing(self) -> None:
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + steady_bars(
            "BBBUSDT", 0.5, april_days()
        )
        explicit = build_monthly_universe(
            bars, MAY_1, UniverseConfig(min_dollar_volume=0.0)
        )
        assert explicit == build_monthly_universe(bars, MAY_1, UniverseConfig())
        assert explicit.exclusions == ()
        assert explicit.symbols == ("AAAUSDT", "BBBUSDT")

    def test_floor_judges_the_median_not_the_mean(self) -> None:
        # One liquidation-cascade day gives BBBB a towering mean but a
        # floor-reading median: the spike must not buy eligibility.
        spiky = [
            DailyBar("BBBUSDT", day, 1.0) for day in april_days()[:-1]
        ] + [DailyBar("BBBUSDT", april_days()[-1], 1_000_000_000.0)]
        universe = build_monthly_universe(
            steady_bars("AAAUSDT", 100.0, april_days()) + spiky,
            MAY_1,
            UniverseConfig(top_n=5, min_dollar_volume=100.0),
        )
        assert universe.symbols == ("AAAUSDT",)
        assert universe.excluded_symbols == ("BBBUSDT",)

    def test_thin_symbol_has_no_median_so_is_absent_not_floored(self) -> None:
        # min_observations and the floor are different doors out: a symbol
        # with too few bars never earns a median, so it cannot be judged
        # against the floor — it is simply not a candidate, and it must
        # not appear among the floor's exclusions.
        bars = steady_bars("AAAUSDT", 1_000_000.0, april_days()[:1]) + steady_bars(
            "BBBUSDT", 100.0, april_days()
        )
        universe = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=10, min_observations=5, min_dollar_volume=10.0)
        )
        assert universe.symbols == ("BBBUSDT",)
        assert universe.exclusions == ()
        assert "AAAUSDT" not in universe.excluded_symbols

    def test_floor_is_judged_on_the_trailing_window_only(self) -> None:
        # DDD trades a fortune inside May and nothing before it: the floor
        # cannot see May any more than the ranking can — causality binds
        # the eligibility rule exactly as it binds the ranking rule.
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + [
            DailyBar("DDDUSDT", dt.date(2026, 5, 15), 1_000_000.0)
        ]
        universe = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=10, min_dollar_volume=10.0)
        )
        assert universe.symbols == ("AAAUSDT",)
        assert universe.excluded_symbols == ()

    def test_rebuild_with_a_floor_is_bit_identical(self) -> None:
        bars = steady_bars("AAAUSDT", 100.0, april_days()) + steady_bars(
            "BBBUSDT", 5.0, april_days()
        )
        config = UniverseConfig(top_n=5, min_dollar_volume=10.0)
        assert build_monthly_universe(bars, MAY_1, config) == build_monthly_universe(
            bars, MAY_1, config
        )

    def test_raising_the_floor_can_only_shrink_the_universe(self) -> None:
        # A stricter floor admits a subset and never invents members.
        bars = (
            steady_bars("AAAUSDT", 300.0, april_days())
            + steady_bars("BBBUSDT", 100.0, april_days())
            + steady_bars("CCCUSDT", 50.0, april_days())
        )
        lax = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=10, min_dollar_volume=40.0)
        )
        strict = build_monthly_universe(
            bars, MAY_1, UniverseConfig(top_n=10, min_dollar_volume=200.0)
        )
        assert set(strict.symbols) < set(lax.symbols)
        assert lax.exclusions == ()
        assert strict.symbols == ("AAAUSDT",)
        assert strict.excluded_symbols == ("BBBUSDT", "CCCUSDT")

    def test_sweep_reports_the_floor_when_it_empties_a_month(self) -> None:
        # May's window (April) holds bars, but the only symbol's median is
        # below the floor: the skip must name the floor, not the
        # observation minimum — the reason is the audit trail. (The May 1
        # bar exists so the sweep enumerates May at all; it sits outside
        # May's own window and cannot rescue the symbol.)
        bars = steady_bars("AAAUSDT", 5.0, april_days()) + [
            DailyBar("AAAUSDT", dt.date(2026, 5, 1), 1_000_000.0)
        ]
        result = build_monthly_universes(
            bars, UniverseConfig(top_n=10, min_dollar_volume=10.0)
        )
        assert result.builds == ()
        reasons = {skip.month: skip.reason for skip in result.skipped}
        assert "floor" in reasons["2026-05"]
        assert "minimum" not in reasons["2026-05"]
        # April itself is a plain data gap: its March window holds nothing.
        assert "no daily bars" in reasons["2026-04"]

    def test_sweep_still_reports_the_observation_minimum_when_no_medians_exist(self) -> None:
        # Two thin April days: nothing reaches min_observations, so no
        # median exists for the floor to judge — the older reason applies.
        bars = [
            DailyBar("AAAUSDT", dt.date(2026, 4, 1), 5.0),
            DailyBar("AAAUSDT", dt.date(2026, 4, 2), 5.0),
            DailyBar("AAAUSDT", dt.date(2026, 5, 1), 5.0),
        ]
        result = build_monthly_universes(
            bars, UniverseConfig(top_n=10, min_observations=5, min_dollar_volume=1.0)
        )
        reasons = {skip.month: skip.reason for skip in result.skipped}
        assert "minimum of 5" in reasons["2026-05"]
        assert "floor" not in reasons["2026-05"]


class TestMedianHelper:
    def test_median_over_window_only(self) -> None:
        bars = steady_bars("AAAUSDT", 10.0, april_days())
        medians = median_dollar_volumes(
            bars, dt.date(2026, 4, 1), dt.date(2026, 4, 30)
        )
        assert medians == {"AAAUSDT": 10.0}

    def test_even_count_median_is_average_of_middles(self) -> None:
        bars = [
            DailyBar("AAAUSDT", dt.date(2026, 4, 1), 1.0),
            DailyBar("AAAUSDT", dt.date(2026, 4, 2), 2.0),
            DailyBar("AAAUSDT", dt.date(2026, 4, 3), 10.0),
            DailyBar("AAAUSDT", dt.date(2026, 4, 4), 4.0),
        ]
        medians = median_dollar_volumes(
            bars, dt.date(2026, 4, 1), dt.date(2026, 4, 30)
        )
        assert medians == {"AAAUSDT": 3.0}

    def test_inverted_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window_end"):
            median_dollar_volumes(
                [], dt.date(2026, 4, 30), dt.date(2026, 4, 1)
            )


class TestMonthHelpers:
    def test_month_key_formats(self) -> None:
        assert month_key(dt.date(2026, 5, 17)) == "2026-05"
        assert month_key("2026-12") == "2026-12"

    def test_month_start_normalizes(self) -> None:
        assert month_start(dt.date(2026, 12, 31)) == dt.date(2026, 12, 1)
        assert month_start("2026-05") == dt.date(2026, 5, 1)
        assert month_start(dt.datetime(2026, 5, 17, 12)) == dt.date(2026, 5, 1)

    def test_invalid_month_raises(self) -> None:
        with pytest.raises(ValueError):
            month_start("2026-13")


class TestBatchSweep:
    def test_sweep_enumerates_months_containing_bars(self) -> None:
        # Data runs Mar 15 .. May 10. March is enumerated (it contains
        # bars) but its trailing window is empty, so it is skipped with
        # the gap reason; April and May build. June is beyond the data
        # and not invented.
        days = [
            dt.date(2026, 3, 15) + dt.timedelta(days=offset)
            for offset in range((dt.date(2026, 5, 10) - dt.date(2026, 3, 15)).days + 1)
        ]
        bars = steady_bars("AAAUSDT", 100.0, days)
        result = build_monthly_universes(bars, UniverseConfig(top_n=10))
        assert [universe.month for universe in result.builds] == ["2026-04", "2026-05"]
        assert [skip.month for skip in result.skipped] == ["2026-03"]
        assert "no daily bars" in result.skipped[0].reason

    def test_skip_reasons_distinguish_gap_from_eligibility(self) -> None:
        # Two thin April days plus one May day: April's trailing window
        # (March) is a data gap; May's window holds the April bars, but
        # with min_observations=5 nothing reaches eligibility.
        bars = [
            DailyBar("AAAUSDT", dt.date(2026, 4, 1), 1.0),
            DailyBar("AAAUSDT", dt.date(2026, 4, 2), 1.0),
            DailyBar("AAAUSDT", dt.date(2026, 5, 1), 1.0),
        ]
        result = build_monthly_universes(
            bars, UniverseConfig(top_n=10, min_observations=5)
        )
        assert result.builds == ()
        reasons = {skip.month: skip.reason for skip in result.skipped}
        assert "no daily bars" in reasons["2026-04"]
        assert "minimum of 5" in reasons["2026-05"]

    def test_explicit_months_build_including_empty_ones(self) -> None:
        bars = steady_bars("AAAUSDT", 100.0, april_days())
        result = build_monthly_universes(
            bars, UniverseConfig(top_n=10), months=["2026-01", "2026-05"]
        )
        # January has no window data, but it was asked for by name: the
        # sweep returns the true (empty) answer rather than skipping.
        assert [universe.month for universe in result.builds] == ["2026-01", "2026-05"]
        assert [len(universe.members) for universe in result.builds] == [0, 1]
        assert result.skipped == ()

    def test_explicit_months_are_deduplicated_and_sorted(self) -> None:
        bars = steady_bars("AAAUSDT", 100.0, april_days())
        result = build_monthly_universes(
            bars,
            UniverseConfig(top_n=10),
            months=[dt.date(2026, 5, 9), "2026-04", "2026-05"],
        )
        assert [universe.month for universe in result.builds] == ["2026-04", "2026-05"]

    def test_no_bars_sweeps_nothing(self) -> None:
        result = build_monthly_universes([])
        assert result.builds == ()
        assert result.skipped == ()

    def test_sweep_is_deterministic(self) -> None:
        days = [dt.date(2026, 3, 20) + dt.timedelta(days=i) for i in range(40)]
        bars = steady_bars("AAAUSDT", 10.0, days) + steady_bars("BBBUSDT", 20.0, days)
        config = UniverseConfig(top_n=1)
        assert build_monthly_universes(bars, config) == build_monthly_universes(
            bars, config
        )
