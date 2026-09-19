"""Acceptance tests for persisting monthly universe builds.

The persistence contract under test: a build is a durable fact with its
provenance (window bounds, config, per-member median), rebuilds replace
atomically and idempotently, and "built but empty" is distinguishable from
"never built".
"""

import datetime as dt
from contextlib import closing
from pathlib import Path

import pytest

from universe import (
    DailyBar,
    UniverseConfig,
    build_monthly_universe,
    load_monthly_universe,
    persist_monthly_universe,
)
from universe.store import _sqlite_path, connect

APRIL_1 = dt.date(2026, 4, 1)
MAY_1 = dt.date(2026, 5, 1)


def april_days() -> list[dt.date]:
    return [APRIL_1 + dt.timedelta(days=offset) for offset in range(30)]


def bars_for(symbols_volumes: dict[str, float]) -> list[DailyBar]:
    return [
        DailyBar(symbol, day, volume)
        for symbol, volume in symbols_volumes.items()
        for day in april_days()
    ]


def rows(database_url: str, sql: str) -> list[tuple]:
    with closing(connect(database_url)) as connection:
        return list(connection.execute(sql).fetchall())


class TestRoundTrip:
    def test_persist_then_load_is_lossless(self, test_database_url: str) -> None:
        bars = bars_for({"AAAUSDT": 100.0, "BBBUSDT": 300.0, "CCCUSDT": 200.0})
        universe = build_monthly_universe(bars, MAY_1, UniverseConfig(top_n=2))
        written = persist_monthly_universe(universe, test_database_url)
        assert written == 2
        assert load_monthly_universe("2026-05", test_database_url) == universe

    def test_load_normalizes_month_before_looking_up(
        self, test_database_url: str
    ) -> None:
        universe = build_monthly_universe(bars_for({"AAAUSDT": 10.0}), MAY_1)
        persist_monthly_universe(universe, test_database_url)
        assert load_monthly_universe(dt.date(2026, 5, 17), test_database_url) == universe

    def test_load_absent_month_returns_none(self, test_database_url: str) -> None:
        assert load_monthly_universe("1999-01", test_database_url) is None

    def test_built_empty_persists_and_loads_as_empty_not_absent(
        self, test_database_url: str
    ) -> None:
        universe = build_monthly_universe([], MAY_1)
        assert persist_monthly_universe(universe, test_database_url) == 0
        loaded = load_monthly_universe("2026-05", test_database_url)
        assert loaded is not None
        assert loaded.members == ()

    def test_build_row_carries_provenance(self, test_database_url: str) -> None:
        universe = build_monthly_universe(
            bars_for({"AAAUSDT": 10.0}), MAY_1, UniverseConfig(top_n=7, min_observations=3)
        )
        persist_monthly_universe(universe, test_database_url)
        build_rows = rows(
            test_database_url,
            "SELECT month, effective_from, window_start, window_end, top_n, "
            "window_days, min_observations, member_count, computed_at "
            "FROM universe_monthly_build",
        )
        assert len(build_rows) == 1
        (row,) = build_rows
        assert row[0] == "2026-05"
        assert row[1] == "2026-05-01"
        assert row[2] == "2026-04-01"
        assert row[3] == "2026-04-30"
        assert (row[4], row[5], row[6], row[7]) == (7, 30, 3, 1)
        assert dt.datetime.fromisoformat(row[8]).tzinfo is not None  # UTC-aware

    def test_member_rows_carry_rank_and_median(
        self, test_database_url: str
    ) -> None:
        universe = build_monthly_universe(
            bars_for({"AAAUSDT": 100.0, "BBBUSDT": 300.0}), MAY_1
        )
        persist_monthly_universe(universe, test_database_url)
        member_rows = rows(
            test_database_url,
            "SELECT symbol, rank, median_dollar_volume "
            "FROM universe_monthly_member ORDER BY rank",
        )
        assert member_rows == [("BBBUSDT", 1, 300.0), ("AAAUSDT", 2, 100.0)]


class TestRebuild:
    def test_persist_twice_is_idempotent(self, test_database_url: str) -> None:
        universe = build_monthly_universe(
            bars_for({"AAAUSDT": 100.0, "BBBUSDT": 300.0}), MAY_1
        )
        persist_monthly_universe(universe, test_database_url)
        persist_monthly_universe(universe, test_database_url)
        assert len(rows(test_database_url, "SELECT * FROM universe_monthly_build")) == 1
        assert len(rows(test_database_url, "SELECT * FROM universe_monthly_member")) == 2

    def test_restated_bars_replace_membership_atomically(
        self, test_database_url: str
    ) -> None:
        first = build_monthly_universe(
            bars_for({"AAAUSDT": 500.0, "BBBUSDT": 100.0}), MAY_1
        )
        persist_monthly_universe(first, test_database_url)
        # April is restated: AAA's turnover vanishes, CCC's appears.
        restated = build_monthly_universe(
            bars_for({"BBBUSDT": 100.0, "CCCUSDT": 900.0}), MAY_1
        )
        persist_monthly_universe(restated, test_database_url)
        assert load_monthly_universe("2026-05", test_database_url) == restated
        symbols = rows(
            test_database_url,
            "SELECT symbol FROM universe_monthly_member ORDER BY rank",
        )
        assert symbols == [("CCCUSDT",), ("BBBUSDT",)]

    def test_months_do_not_leak_into_each_other(
        self, test_database_url: str
    ) -> None:
        may = build_monthly_universe(bars_for({"AAAUSDT": 10.0}), MAY_1)
        june = build_monthly_universe(bars_for({"BBBUSDT": 20.0}), dt.date(2026, 6, 1))
        persist_monthly_universe(may, test_database_url)
        persist_monthly_universe(june, test_database_url)
        assert load_monthly_universe("2026-05", test_database_url) == may
        assert load_monthly_universe("2026-06", test_database_url) == june


class TestDatabaseRouting:
    def test_uses_database_url_env_by_default(self, test_database_url: str) -> None:
        universe = build_monthly_universe(bars_for({"AAAUSDT": 10.0}), MAY_1)
        persist_monthly_universe(universe)  # no explicit URL
        assert load_monthly_universe("2026-05") == universe

    def test_rejects_non_sqlite_scheme(self) -> None:
        universe = build_monthly_universe(bars_for({"AAAUSDT": 10.0}), MAY_1)
        with pytest.raises(ValueError, match="postgres"):
            persist_monthly_universe(universe, "postgres://u:p@h:5432/nullius")
        with pytest.raises(ValueError, match="postgresql"):
            load_monthly_universe("2026-05", "postgresql://u:p@h:5432/nullius")

    def test_relative_and_absolute_sqlite_urls(self) -> None:
        # SQLAlchemy convention: three slashes then a name is relative;
        # an absolute path adds its own leading slash (four in total).
        assert _sqlite_path("sqlite:///scratch.db") == Path("scratch.db")
        assert _sqlite_path("sqlite:////abs/path/universe.db") == Path(
            "/abs/path/universe.db"
        )
        assert _sqlite_path("sqlite:////abs/universe.db").is_absolute()

    def test_host_in_sqlite_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="host"):
            _sqlite_path("sqlite://elsewhere/db.sqlite")

    def test_schema_creation_is_idempotent(self, test_database_url: str) -> None:
        with closing(connect(test_database_url)) as first:
            first.execute("SELECT 1").fetchone()
        with closing(connect(test_database_url)) as second:  # creates nothing new
            names = {
                row[0]
                for row in second.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
                )
            }
        assert {
            "universe_monthly_build",
            "universe_monthly_member",
            "universe_monthly_member_month_rank",
        } <= names

    def test_writes_isolated_database_file(
        self, test_database_url: str, tmp_path: Path
    ) -> None:
        universe = build_monthly_universe(bars_for({"AAAUSDT": 10.0}), MAY_1)
        persist_monthly_universe(universe, test_database_url)
        database_file = Path(test_database_url.removeprefix("sqlite:///"))
        assert database_file.is_absolute()
        assert database_file.is_relative_to(tmp_path)
        assert database_file.exists()
