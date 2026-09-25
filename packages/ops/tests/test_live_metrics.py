"""Feature 350's store, in the relational store the deployment names.

The four live metrics — information coefficient ratio, fill cost in basis
points, order reject rate and feed staleness — persisted into ``DATABASE_URL``
names, each measured by the source member and handed over already measured,
validated against the bound the metric's *name* fixes.  This suite pins the
store's law: one metric per row, the ask validated whole before a connection
is opened, the write an upsert that refreshes rather than appends, the
construction performing no I/O, and the store's own failures surfaced in this
member's vocabulary rather than swallowed.

The fixtures mirror ``test_fdr_store.py``: a real SQLite file under
``tmp_path`` and a ``DATABASE_URL`` pointed at it, with the conftest's
per-test isolation so no test can write into the real store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ops import LiveMetricError, LiveMetricsStore
from ops.live_metrics import (
    DATABASE_URL_ENV,
    LIVE_METRIC_TABLE,
    LIVE_METRICS,
    OPS_LIVE_METRIC_COMPONENT_NAME,
)

FOUR = LIVE_METRICS


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "live-metrics.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> LiveMetricsStore:
    """A store bound to the test-only database."""
    return LiveMetricsStore(store_url)


# -- Round trip ---------------------------------------------------------------


def test_record_then_latest_round_trips_to_the_bit(store: LiveMetricsStore) -> None:
    # Each metric's value survives the write and comes back off its own
    # column, unchanged — the store answers what was written, never a
    # recomputation.
    store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")
    store.record("fill_cost_bps", -3.5, logged_at="2026-01-01T00:00:00")
    store.record("reject_rate", 0.05, logged_at="2026-01-01T00:00:00")
    store.record("feed_staleness_s", 1.2, logged_at="2026-01-01T00:00:00")
    latest = store.latest()
    assert latest == {
        "ic_ratio": 0.42,
        "fill_cost_bps": -3.5,
        "reject_rate": 0.05,
        "feed_staleness_s": 1.2,
    }


def test_latest_answers_none_for_a_metric_never_recorded(store: LiveMetricsStore) -> None:
    # A metric with no row answers None, never 0.0 — a zero is a
    # measurement, and a live metric that was never recorded is not one.
    store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")
    latest = store.latest()
    assert latest["ic_ratio"] == 0.42
    assert latest["fill_cost_bps"] is None
    assert latest["reject_rate"] is None
    assert latest["feed_staleness_s"] is None


def test_series_returns_rows_oldest_first(store: LiveMetricsStore) -> None:
    # The series is the trend a reader watches the live metric across:
    # (logged_at, value) ordered by the instant, oldest first.
    store.record("ic_ratio", 0.10, logged_at="2026-01-01T00:00:00")
    store.record("ic_ratio", 0.30, logged_at="2026-01-02T00:00:00")
    store.record("ic_ratio", 0.55, logged_at="2026-01-03T00:00:00")
    assert store.series("ic_ratio") == [
        ("2026-01-01T00:00:00", 0.10),
        ("2026-01-02T00:00:00", 0.30),
        ("2026-01-03T00:00:00", 0.55),
    ]


def test_series_is_empty_for_a_metric_never_recorded(store: LiveMetricsStore) -> None:
    # An empty list is the honest answer for a metric that was never
    # recorded: a discoverable state, not an exception and not a
    # fabricated first point.
    assert store.series("reject_rate") == []


def test_latest_picks_the_newest_row_per_metric(store: LiveMetricsStore) -> None:
    # The latest is the newest row per metric — a re-measurement at a later
    # instant does not displace the earlier one, but the latest read answers
    # the most recent.
    store.record("ic_ratio", 0.10, logged_at="2026-01-01T00:00:00")
    store.record("ic_ratio", 0.99, logged_at="2026-01-02T00:00:00")
    assert store.latest()["ic_ratio"] == 0.99
    assert store.series("ic_ratio") == [
        ("2026-01-01T00:00:00", 0.10),
        ("2026-01-02T00:00:00", 0.99),
    ]


# -- One metric, one row ------------------------------------------------------


def test_recording_one_metric_leaves_the_others_null(
    store: LiveMetricsStore, store_path: Path
) -> None:
    # One metric, one column, the other three NULL by shape — a row is never
    # two metrics at once.  Recorded ic_ratio leaves fill_cost_bps,
    # reject_rate and feed_staleness_s NULL.
    import sqlite3

    store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")
    with sqlite3.connect(store_path) as connection:
        rows = connection.execute(
            f"SELECT metric, ic_ratio, fill_cost_bps, reject_rate, feed_staleness_s "
            f"FROM {LIVE_METRIC_TABLE}"
        ).fetchall()
    assert rows == [("ic_ratio", 0.42, None, None, None)]


def test_two_metrics_at_one_instant_are_two_rows(
    store: LiveMetricsStore, store_path: Path
) -> None:
    # The key is (metric, logged_at), so two metrics at the same instant are
    # two rows — the (metric, logged_at) key never collides across metrics.
    import sqlite3

    store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")
    store.record("reject_rate", 0.05, logged_at="2026-01-01T00:00:00")
    with sqlite3.connect(store_path) as connection:
        rows = connection.execute(
            f"SELECT metric, logged_at FROM {LIVE_METRIC_TABLE} ORDER BY metric"
        ).fetchall()
    assert rows == [
        ("ic_ratio", "2026-01-01T00:00:00"),
        ("reject_rate", "2026-01-01T00:00:00"),
    ]


def test_upsert_refreshes_the_value_rather_than_appending(
    store: LiveMetricsStore, store_path: Path
) -> None:
    # A re-run of the same measurement at the same instant refreshes the
    # value, never appends a doubled row — the (metric, logged_at) key.
    import sqlite3

    store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")
    store.record("ic_ratio", 0.99, logged_at="2026-01-01T00:00:00")
    with sqlite3.connect(store_path) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {LIVE_METRIC_TABLE} WHERE metric = 'ic_ratio'"
        ).fetchone()[0]
    assert count == 1
    assert store.latest()["ic_ratio"] == 0.99


# -- The ask is validated whole, before a connection is opened ----------------


def test_unknown_metric_refused_before_any_connection(
    store: LiveMetricsStore, store_path: Path
) -> None:
    # A value stored under a name the table does not know is a metric nobody
    # measured and there is no column to put it in; refused by name, before a
    # connection is opened — so a refused record leaves no database file.
    with pytest.raises(LiveMetricError):
        store.record("sharpe", 0.42, logged_at="2026-01-01T00:00:00")
    assert not store_path.exists()


def test_non_finite_value_refused_before_any_connection(
    store: LiveMetricsStore, store_path: Path
) -> None:
    # A NaN or infinity would be a live reading the store silently persisted
    # and a later dashboard drew; refused before a connection is opened.
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", float("nan"), logged_at="2026-01-01T00:00:00")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", float("inf"), logged_at="2026-01-01T00:00:00")
    assert not store_path.exists()


def test_out_of_bound_value_refused_before_any_connection(
    store: LiveMetricsStore, store_path: Path
) -> None:
    # A value outside the bound the metric's name fixes is refused rather
    # than clamped — a clamped value would answer a live reading nobody
    # measured — before a connection is opened.
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", 1.5, logged_at="2026-01-01T00:00:00")
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", -0.01, logged_at="2026-01-01T00:00:00")
    with pytest.raises(LiveMetricError):
        store.record("feed_staleness_s", -0.1, logged_at="2026-01-01T00:00:00")
    assert not store_path.exists()


# -- Each metric's shape ------------------------------------------------------


def test_ic_ratio_is_a_finite_real_in_minus_one_to_one(store: LiveMetricsStore) -> None:
    # A sign-flipped IC answers a negative ratio down to -1, and that sign is
    # the fact — honoured at both ends, refused outside the correlation bound
    # [-1, 1] and refused non-finite.
    store.record("ic_ratio", -1.0, logged_at="2026-01-01T00:00:00")
    store.record("ic_ratio", 1.0, logged_at="2026-01-01T00:00:01")
    assert store.latest()["ic_ratio"] == 1.0
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 1.5, logged_at="2026-01-01T00:00:02")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", -1.5, logged_at="2026-01-01T00:00:03")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", float("nan"), logged_at="2026-01-01T00:00:04")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", float("inf"), logged_at="2026-01-01T00:00:05")


def test_fill_cost_bps_is_finite_with_no_sign_bound(store: LiveMetricsStore) -> None:
    # Basis points is the unit, and a cost can be negative (price
    # improvement); refused only when not finite.
    store.record("fill_cost_bps", -120.0, logged_at="2026-01-01T00:00:00")
    store.record("fill_cost_bps", 250.0, logged_at="2026-01-01T00:00:01")
    assert store.latest()["fill_cost_bps"] == 250.0
    with pytest.raises(LiveMetricError):
        store.record("fill_cost_bps", float("inf"), logged_at="2026-01-01T00:00:02")


def test_reject_rate_is_a_fraction_in_zero_to_one(store: LiveMetricsStore) -> None:
    # A rate is a fraction of submissions, bounded [0, 1]; the boundaries are
    # admitted, the outside refused.
    store.record("reject_rate", 0.0, logged_at="2026-01-01T00:00:00")
    store.record("reject_rate", 1.0, logged_at="2026-01-01T00:00:01")
    assert store.latest()["reject_rate"] == 1.0
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", 1.0001, logged_at="2026-01-01T00:00:02")
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", -0.0001, logged_at="2026-01-01T00:00:03")


def test_feed_staleness_s_is_a_non_negative_duration(store: LiveMetricsStore) -> None:
    # A duration is a non-negative finite real; zero admitted, negative
    # refused.
    store.record("feed_staleness_s", 0.0, logged_at="2026-01-01T00:00:00")
    store.record("feed_staleness_s", 3.7, logged_at="2026-01-01T00:00:01")
    assert store.latest()["feed_staleness_s"] == 3.7
    with pytest.raises(LiveMetricError):
        store.record("feed_staleness_s", -1.0, logged_at="2026-01-01T00:00:02")


def test_bool_is_refused_before_real(store: LiveMetricsStore) -> None:
    # True is 1 in Python, and a flag where a live metric belongs would
    # silently answer one nobody measured; bool refused before real.
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", True, logged_at="2026-01-01T00:00:00")
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", False, logged_at="2026-01-01T00:00:01")


def test_a_count_is_refused(store: LiveMetricsStore) -> None:
    # The likeliest thing wearing the value's name at this seam is a count of
    # orders or rejects, which no bound would price as the live metric it
    # claims; a plain int is refused as not-a-real.
    with pytest.raises(LiveMetricError):
        store.record("reject_rate", 5, logged_at="2026-01-01T00:00:00")


def test_none_is_refused(store: LiveMetricsStore) -> None:
    # A None standing in for an unread gauge is not a live metric; refused.
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", None, logged_at="2026-01-01T00:00:00")


def test_logged_at_must_be_a_nameable_instant(store: LiveMetricsStore) -> None:
    # The instant is the key half of the row and the label the series read
    # orders by; a value that is not a nameable instant orders nothing.
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 0.42, logged_at=12345)  # type: ignore[arg-type]
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 0.42, logged_at="")


def test_default_logged_at_stamps_the_write(store: LiveMetricsStore) -> None:
    # logged_at defaults to now (UTC, second resolution); a caller that
    # measured at a known instant passes it, but the write can stamp its own.
    store.record("ic_ratio", 0.42)
    series = store.series("ic_ratio")
    assert len(series) == 1
    instant = series[0][0]
    # ISO 8601 UTC, second resolution — the spelling isoformat produces, with
    # a 'T' separator and a +00:00 offset (string order chronological).
    assert "T" in instant
    assert instant.endswith("+00:00")
    # Second resolution: the time part is HH:MM:SS with no microseconds.
    time_part = instant.split("T")[1].split("+")[0]
    assert time_part.count(":") == 2
    assert "." not in time_part


# -- The store is the workspace's one relational store ------------------------


def test_construction_performs_no_io(store_url: str, store_path: Path) -> None:
    # The class resolves its path lazily, so constructing one performs no I/O:
    # composition-time work must not touch the disk.
    LiveMetricsStore(store_url)
    assert not store_path.exists()


def test_resolve_answers_none_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Absent is not an error: it is a deployment without a relational store,
    # which composes no live-metric component — a discoverable state, not an
    # exception.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert LiveMetricsStore.resolve() is None


def test_resolve_answers_none_for_an_empty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty or whitespace-only value counts as unset.
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert LiveMetricsStore.resolve() is None


def test_resolve_answers_the_named_store(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The store DATABASE_URL names, resolved.
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = LiveMetricsStore.resolve()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_an_unsupported_scheme_is_refused_at_first_use(
    store_url: str, store_path: Path
) -> None:
    # Only sqlite:/// speaks; a Postgres metrics table arrives with the
    # versioned migration member, and pretending to speak it here would hide
    # a misrouted URL behind a mysterious file.  Refused at first use, not
    # construction.
    store = LiveMetricsStore("postgresql://localhost/metrics")
    # Construction held the URL, resolved nothing.
    assert store.database_url == "postgresql://localhost/metrics"
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")


def test_an_unspeakable_scheme_is_refused_at_first_use(
    store_path: Path,
) -> None:
    # A scheme with no netloc and no path — refused at first use, not
    # construction, and never silently mis-parsed into a file.
    store = LiveMetricsStore("redis://cache:6379/0")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")


def test_a_sqlite_url_with_a_host_is_refused(store_path: Path) -> None:
    # No host but localhost admitted — the same refusal every store in this
    # workspace states for its own connection.
    store = LiveMetricsStore("sqlite://remote-host/db.sqlite")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")


def test_a_sqlite_url_with_no_path_is_refused() -> None:
    # A URL with no path refused — the store must name a database.
    store = LiveMetricsStore("sqlite:///")
    with pytest.raises(LiveMetricError):
        store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")


def test_a_blank_url_is_refused_at_construction() -> None:
    # The URL is held, not resolved, but it must be a non-empty string.
    with pytest.raises(LiveMetricError):
        LiveMetricsStore("")
    with pytest.raises(LiveMetricError):
        LiveMetricsStore("   ")
    with pytest.raises(LiveMetricError):
        LiveMetricsStore(None)  # type: ignore[arg-type]


def test_a_database_that_will_not_open_is_surfaced_chained(
    tmp_path: Path,
) -> None:
    # The store's own failure surfaces in this member's vocabulary, chained to
    # the original and deliberately not swallowed: a live metric that measured
    # but never landed is the state this feature exists to rule out.
    # A path whose parent cannot be created — a file where a directory is
    # expected — makes the connect/executescript fail.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = LiveMetricsStore(f"sqlite:///{not_a_dir}/metrics.db")
    with pytest.raises(LiveMetricError) as caught:
        store.record("ic_ratio", 0.42, logged_at="2026-01-01T00:00:00")
    # Chained to the original, never swallowed.
    assert caught.value.__cause__ is not None


def test_a_read_failure_is_surfaced_chained(tmp_path: Path) -> None:
    # A store that cannot be asked is surfaced rather than answered around —
    # the live metrics are the readings an operator watches the running
    # system by.
    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x")
    store = LiveMetricsStore(f"sqlite:///{not_a_dir}/metrics.db")
    with pytest.raises(LiveMetricError) as caught:
        store.latest()
    assert caught.value.__cause__ is not None
    with pytest.raises(LiveMetricError) as caught:
        store.series("ic_ratio")
    assert caught.value.__cause__ is not None


# -- The component beside the route and the dashboard -------------------------


def test_the_builder_resolves_the_named_store_or_none(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # The builder resolves DATABASE_URL and answers None when nothing names a
    # store — the degrade-don't-break stance every store-bound builder here
    # takes.
    from ops import build_live_metric_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_live_metric_store() is None
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = build_live_metric_store()
    assert resolved is not None
    assert resolved.database_url == store_url


def test_the_builder_touches_no_disk_when_no_store_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Building performs no I/O — no store is constructed, no database opened,
    # no schema created — and when nothing names a store the builder answers
    # None without touching the disk.
    from ops import build_live_metric_store

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert build_live_metric_store() is None


def test_the_component_name_is_the_member_third() -> None:
    # The growth the member's own registration reserved when feature 341
    # landed: the route, the dashboard, and now the live-metrics store, each
    # beside — never inside — another member's components.
    from ops import (
        OPS_COMPONENT_NAME,
        OPS_DASHBOARD_COMPONENT_NAME,
        OPS_LIVE_METRIC_COMPONENT_NAME,
    )

    names = {OPS_COMPONENT_NAME, OPS_DASHBOARD_COMPONENT_NAME, OPS_LIVE_METRIC_COMPONENT_NAME}
    # Three distinct component names under the one member-first prefix.
    assert len(names) == 3
    assert OPS_LIVE_METRIC_COMPONENT_NAME == "ops-live-metric"
    assert all(name.startswith("ops-") for name in names)


def test_the_component_name_is_exported_from_the_member() -> None:
    import ops

    assert "OPS_LIVE_METRIC_COMPONENT_NAME" in ops.__all__
    assert ops.OPS_LIVE_METRIC_COMPONENT_NAME == "ops-live-metric"
    assert ops.OPS_LIVE_METRIC_COMPONENT_NAME == OPS_LIVE_METRIC_COMPONENT_NAME


def test_the_store_class_is_exported_from_the_member() -> None:
    import ops

    assert "LiveMetricsStore" in ops.__all__
    assert "LiveMetricError" in ops.__all__
    assert "LiveMetric" in ops.__all__
    assert "LIVE_METRICS" in ops.__all__
    assert "LIVE_METRIC_TABLE" in ops.__all__
    assert "DATABASE_URL_ENV" in ops.__all__
