"""Feature 67 — the empirical latency distribution, measured and persisted.

app_spec.xml, "Cost Model & Fill Simulation", feature 67: *System persists
an empirical p50, p95 and p99 latency distribution measured from shadow
runs rather than an assumed constant.*  The sentence is a rejection and an
assertion, and each word can fail independently, so the tests take them one
at a time:

* **empirical … rather than an assumed constant** — the distribution is the
  order statistics of a sample, not a fitted family and never a default
  number.  There is no ``DEFAULT_LATENCY_MS`` to fall back to: building a
  distribution without samples is refused, not defaulted.
* **p50, p95 and p99** — three quantiles, the centre and the tail, each
  computed the same way and each able to be wrong on its own.
* **measured from shadow runs** — the distribution keeps the sample it was
  measured from, so a reader can see how many shadow runs it is based on
  and what the observed extremes were, not just a summary of them.
* **persists** — the samples land as the source of truth and the p50/p95/p99
  as a derived view over them, keyed by the cost model's ``(venue, version)``
  identity and the instant the latency was measured, so a cost model's
  latency is a history that accumulates.

:mod:`cost_model.latency` owns the measurement (the distribution and its
quantiles); :mod:`cost_model.latency_store` owns the persistence; the
service tests at the end pin that the two run in the feature's order.
"""

from __future__ import annotations

import json
from contextlib import closing

import pytest
from cost_model import (
    DEFAULT_QUANTILES,
    LATENCY_TABLE,
    EmpiricalLatencyDistribution,
    load_latency_distributions,
    load_latest_latency_distribution,
    persist_latency_distribution,
)
from cost_model.errors import CostModelConfigError, CostModelStoreError
from cost_model.latency import QUANTILE_METHOD, quantile
from cost_model.store import connect

# A representative sample of shadow-run round-trip latencies (ms): a body of
# fast fills with a heavy tail, the shape a passive-order cost is set by.
SAMPLES = [
    41.2, 43.8, 45.0, 46.1, 47.5, 48.9, 50.2, 51.7, 53.3, 55.0,
    56.8, 58.4, 60.1, 62.5, 65.0, 68.2, 72.0, 77.5, 84.0, 93.6,
    108.4, 127.0, 152.5, 188.0, 241.6,
]


def raw_rows(database_url: str) -> list[tuple]:
    """Every latency row of the table, straight from the store.

    A raw read on a fresh connection, so an assertion is about the bytes on
    disk rather than about the writer's return value.
    """
    with closing(connect(database_url)) as connection:
        return connection.execute(
            f"SELECT venue, version, measured_at, source, n, samples, "
            f"p50, p95, p99 FROM {LATENCY_TABLE}"
        ).fetchall()


class TestTheDistributionIsEmpiricalNotAssumed:
    """A distribution is measured from samples, never a constant."""

    def test_a_distribution_keeps_the_sample_it_was_measured_from(self) -> None:
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        assert distribution.samples == tuple(SAMPLES)
        assert distribution.n == len(SAMPLES)

    def test_there_is_no_assumed_constant_to_fall_back_to(self) -> None:
        # Feature 67 is a rejection of the assumed constant, so the module
        # must not offer one: no default latency, and no way to build a
        # distribution out of nothing.  A distribution with no samples is
        # refused by name, and the refusal names exactly the thing it
        # refuses to become.
        with pytest.raises(CostModelConfigError, match="assumed constant"):
            EmpiricalLatencyDistribution(samples=[])

    def test_a_single_sample_is_a_valid_distribution(self) -> None:
        # One shadow run is a thin basis, but it is a measurement, not an
        # assumption — so it is admitted, and every quantile is that one
        # value, the honest answer when there is no spread to interpolate.
        distribution = EmpiricalLatencyDistribution(samples=[73.0])
        assert distribution.p50 == 73.0
        assert distribution.p95 == 73.0
        assert distribution.p99 == 73.0

    def test_the_sample_is_frozen_after_construction(self) -> None:
        # The distribution is a record of what the shadow runs showed; a
        # caller that could mutate it would be changing what was measured.
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        with pytest.raises(AttributeError):
            distribution.samples = [1.0]  # type: ignore[misc]


class TestTheThreeQuantiles:
    """p50, p95 and p99 — the centre and the tail, each on its own."""

    def test_the_three_named_quantiles_are_reported(self) -> None:
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        summary = distribution.summary()
        assert set(summary) >= {"p50", "p95", "p99"}
        # The centre is below the body of the tail, which is below the
        # extreme tail: a latency story that does not collapse to its median.
        assert summary["p50"] < summary["p95"] < summary["p99"]

    def test_the_default_quantiles_are_p50_p95_p99(self) -> None:
        assert DEFAULT_QUANTILES == (50.0, 95.0, 99.0)
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        assert set(distribution.percentiles().keys()) == {50.0, 95.0, 99.0}

    def test_the_median_is_the_centre_of_the_sample(self) -> None:
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        # The median of 25 sorted values is the 13th (index 12): 60.1.
        assert distribution.p50 == pytest.approx(60.1)

    def test_the_tail_quantiles_exceed_the_median(self) -> None:
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        # p95: rank 0.95 * 24 = 22.8, between index 22 (152.5) and 23 (188.0).
        # p99: rank 0.99 * 24 = 23.76, between index 23 (188.0) and 24 (241.6).
        assert distribution.p95 == pytest.approx(180.9)
        assert distribution.p99 == pytest.approx(228.736)

    def test_the_observed_extremes_are_reported_beside_the_quantiles(self) -> None:
        # A p99 is a quantile, not the maximum, and a p50 is not the
        # minimum: a reader comparing "the tail" to "the worst case" must be
        # able to see both.
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        assert distribution.observed_minimum == pytest.approx(41.2)
        assert distribution.observed_maximum == pytest.approx(241.6)
        assert distribution.observed_minimum < distribution.p50
        assert distribution.p99 < distribution.observed_maximum


class TestTheQuantileMethod:
    """The quantile convention is named and reproduced exactly."""

    def test_the_method_is_linear(self) -> None:
        # numpy.percentile's default: the rank of the p-th percentile is
        # p/100 * (n - 1), interpolated linearly between order statistics.
        assert QUANTILE_METHOD == "linear"

    def test_the_quantile_matches_numpy_linear_interpolation(self) -> None:
        # The one numerical choice in the feature, pinned against the
        # convention it reproduces.  ``numpy`` is not a dependency of this
        # member, so the expected values are computed by hand from the
        # definition rather than imported — the test asserts the arithmetic,
        # not a library we happen to have installed.
        n = len(SAMPLES)
        ordered = sorted(SAMPLES)

        def expected(p: float) -> float:
            rank = (p / 100.0) * (n - 1)
            lower = int(rank)
            if lower == rank:
                return ordered[lower]
            fraction = rank - lower
            return ordered[lower] + fraction * (ordered[lower + 1] - ordered[lower])

        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        for p in (50.0, 95.0, 99.0):
            assert distribution.percentile(p) == pytest.approx(expected(p))

    def test_a_rank_landing_between_two_order_statistics_interpolates(self) -> None:
        # p99 of 25 samples: rank = 0.99 * 24 = 23.76, between the order
        # statistics at index 23 (188.0) and index 24 (241.6).
        assert quantile(sorted(SAMPLES), 99.0) == pytest.approx(
            188.0 + 0.76 * (241.6 - 188.0)
        )

    def test_a_rank_landing_on_an_order_statistics_returns_it(self) -> None:
        # p50 of 25 samples: rank = 0.5 * 24 = 12.0, exactly index 12.
        assert quantile(sorted(SAMPLES), 50.0) == sorted(SAMPLES)[12]

    @pytest.mark.parametrize("p", [-1.0, 101.0, 150.0])
    def test_a_percentile_outside_zero_to_hundred_is_refused(self, p: float) -> None:
        with pytest.raises(CostModelConfigError, match="within"):
            quantile(sorted(SAMPLES), p)


class TestRefusingABadSample:
    """Every unusable sample is refused by name before any number is reported."""

    def test_a_non_numeric_sample_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="real numbers"):
            EmpiricalLatencyDistribution(samples=[41.2, "fast", 45.0])

    def test_a_boolean_sample_is_refused_not_coerced(self) -> None:
        # bool is an int subclass; a ``True`` latency is a mistake, not a
        # one-millisecond measurement, and must be refused rather than
        # silently accepted as ``1``.
        with pytest.raises(CostModelConfigError, match="real numbers"):
            EmpiricalLatencyDistribution(samples=[True])

    def test_a_non_finite_sample_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="finite"):
            EmpiricalLatencyDistribution(samples=[41.2, float("inf")])

    def test_a_nan_sample_is_refused(self) -> None:
        with pytest.raises(CostModelConfigError, match="finite"):
            EmpiricalLatencyDistribution(samples=[float("nan")])

    def test_a_negative_sample_is_refused(self) -> None:
        # A negative round-trip latency is a clock error, not a tail.
        with pytest.raises(CostModelConfigError, match="non-negative"):
            EmpiricalLatencyDistribution(samples=[41.2, -3.0])


class TestTheDistributionIsPersisted:
    """The samples land as the source of truth, the quantiles as a view."""

    def test_a_measured_distribution_lands_in_the_store(
        self, test_database_url: str
    ) -> None:
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        persist_latency_distribution(
            distribution, "binance_spot", "2026.09.1", database_url=test_database_url
        )
        (row,) = raw_rows(test_database_url)
        assert row[0] == "binance_spot"
        assert row[1] == "2026.09.1"
        assert row[4] == len(SAMPLES)

    def test_the_samples_are_the_source_of_truth(self, test_database_url: str) -> None:
        # The row stores the samples as a JSON array; the p50/p95/p99 are a
        # derived view over them.  A reader rebuilding the distribution from
        # the samples gets back exactly what was written.
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        persist_latency_distribution(
            distribution, "binance_spot", "2026.09.1", database_url=test_database_url
        )
        (row,) = raw_rows(test_database_url)
        stored_samples = json.loads(row[5])
        assert stored_samples == sorted(SAMPLES)
        assert len(stored_samples) == len(SAMPLES)

    def test_the_derived_columns_match_the_distribution(self, test_database_url: str) -> None:
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        persist_latency_distribution(
            distribution, "binance_spot", "2026.09.1", database_url=test_database_url
        )
        (row,) = raw_rows(test_database_url)
        assert row[6] == pytest.approx(distribution.p50)
        assert row[7] == pytest.approx(distribution.p95)
        assert row[8] == pytest.approx(distribution.p99)

    def test_the_round_trip_is_lossless(self, test_database_url: str) -> None:
        # Rebuilt from the samples on read, so the distribution that comes
        # back is the one that was written — same n, same quantiles, same
        # extremes.
        written = EmpiricalLatencyDistribution(samples=SAMPLES)
        persist_latency_distribution(
            written, "binance_spot", "2026.09.1", database_url=test_database_url
        )
        back = load_latest_latency_distribution(
            "binance_spot", "2026.09.1", test_database_url
        )
        assert back is not None
        assert back.n == written.n
        assert back.p50 == pytest.approx(written.p50)
        assert back.p95 == pytest.approx(written.p95)
        assert back.p99 == pytest.approx(written.p99)
        assert back.observed_maximum == pytest.approx(written.observed_maximum)

    def test_the_stamp_is_a_utc_instant(self, test_database_url: str) -> None:
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "binance_spot",
            "2026.09.1",
            database_url=test_database_url,
        )
        (row,) = raw_rows(test_database_url)
        assert row[2].endswith("+00:00")

    def test_the_source_column_records_provenance(self, test_database_url: str) -> None:
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "binance_spot",
            "2026.09.1",
            source="/shadow/runs/2026-09-01/latency.log",
            database_url=test_database_url,
        )
        (row,) = raw_rows(test_database_url)
        assert row[3] == "/shadow/runs/2026-09-01/latency.log"


class TestTheLatencyIsAHistory:
    """One row per (venue, version, measured_at): latency accumulates."""

    def test_two_measurements_at_two_instants_are_two_rows(
        self, test_database_url: str
    ) -> None:
        first = EmpiricalLatencyDistribution(samples=SAMPLES[:10])
        second = EmpiricalLatencyDistribution(samples=SAMPLES)
        persist_latency_distribution(
            first, "binance_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        persist_latency_distribution(
            second, "binance_spot", "2026.09.1",
            measured_at="2026-09-02T00:00:00+00:00", database_url=test_database_url,
        )
        # ``raw_rows`` is a raw read with no ordering — the newest-first
        # ordering is the loader's contract, tested in TestReadingTheLatest —
        # so this asserts only what a raw read can: two distinct snapshots,
        # one per instant.
        rows = raw_rows(test_database_url)
        assert len(rows) == 2
        assert {row[2] for row in rows} == {
            "2026-09-01T00:00:00+00:00",
            "2026-09-02T00:00:00+00:00",
        }

    def test_the_same_instant_upserts_onto_one_row(self, test_database_url: str) -> None:
        # The same snapshot written twice is one row — the honest answer for
        # the same measurement at the same instant.
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES[:10]),
            "binance_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "binance_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        rows = raw_rows(test_database_url)
        assert len(rows) == 1
        assert rows[0][4] == len(SAMPLES)

    def test_the_same_version_at_two_venues_is_two_histories(
        self, test_database_url: str
    ) -> None:
        # The whole reason the pair is the key: "2026.09.1" is one cost
        # model per venue, and each venue's shadow runs have their own
        # latency.
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "binance_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "kraken_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        assert len(raw_rows(test_database_url)) == 2

    def test_all_snapshots_for_a_cost_model_are_listed(
        self, test_database_url: str
    ) -> None:
        for i, size in enumerate((5, 15, len(SAMPLES)), start=1):
            persist_latency_distribution(
                EmpiricalLatencyDistribution(samples=SAMPLES[:size]),
                "binance_spot", "2026.09.1",
                measured_at=f"2026-09-0{i}T00:00:00+00:00",
                database_url=test_database_url,
            )
        snapshots = load_latency_distributions(
            "binance_spot", "2026.09.1", test_database_url
        )
        assert [measured_at for measured_at, _, _ in snapshots] == [
            "2026-09-03T00:00:00+00:00",
            "2026-09-02T00:00:00+00:00",
            "2026-09-01T00:00:00+00:00",
        ]
        assert [distribution.n for _, distribution, _ in snapshots] == [
            len(SAMPLES), 15, 5
        ]


class TestReadingTheLatest:
    """The reader a latency-aware cost computation resolves against."""

    def test_a_miss_is_none(self, test_database_url: str) -> None:
        # A cost model whose latency has never been measured is a
        # discoverable state, not an exception — and the signal that pricing
        # against it must not fall back to an assumed constant.
        assert (
            load_latest_latency_distribution(
                "binance_spot", "2026.09.1", test_database_url
            )
            is None
        )

    def test_the_latest_snapshot_is_returned(self, test_database_url: str) -> None:
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES[:10]),
            "binance_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "binance_spot", "2026.09.1",
            measured_at="2026-09-02T00:00:00+00:00", database_url=test_database_url,
        )
        latest = load_latest_latency_distribution(
            "binance_spot", "2026.09.1", test_database_url
        )
        assert latest is not None
        assert latest.n == len(SAMPLES)
        assert latest.p99 == pytest.approx(EmpiricalLatencyDistribution(samples=SAMPLES).p99)

    def test_a_miss_for_one_venue_is_not_a_miss_for_another(
        self, test_database_url: str
    ) -> None:
        persist_latency_distribution(
            EmpiricalLatencyDistribution(samples=SAMPLES),
            "binance_spot", "2026.09.1",
            measured_at="2026-09-01T00:00:00+00:00", database_url=test_database_url,
        )
        assert (
            load_latest_latency_distribution(
                "kraken_spot", "2026.09.1", test_database_url
            )
            is None
        )


class TestTheStoreRefusesWhatItCannotHonor:
    def test_an_unconfigured_store_is_refused_by_name(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(CostModelStoreError, match="DATABASE_URL"):
            persist_latency_distribution(
                EmpiricalLatencyDistribution(samples=SAMPLES),
                "binance_spot", "2026.09.1",
            )

    def test_a_non_sqlite_url_is_refused_by_scheme(self) -> None:
        with pytest.raises(CostModelStoreError, match="postgres"):
            persist_latency_distribution(
                EmpiricalLatencyDistribution(samples=SAMPLES),
                "binance_spot", "2026.09.1",
                database_url="postgres://u:p@h:5432/nullius",
            )

    def test_a_read_of_an_unreachable_store_is_a_store_error(self, tmp_path) -> None:
        # A regular file where the store's database must be cannot be opened
        # as a database; the reader raises the same store error a failed
        # write does, rather than a bare sqlite error the caller must happen
        # to catch.
        blocker = tmp_path / "not-a-database.db"
        blocker.write_text("not a database", encoding="utf-8")
        with pytest.raises(CostModelStoreError):
            load_latest_latency_distribution(
                "binance_spot",
                "2026.09.1",
                database_url=f"sqlite:///{blocker}",
            )


class TestTheServiceRunsTheSentenceInOrder:
    """measure → persist → read back, through the composed service."""

    def test_the_service_persists_and_reads_a_measured_distribution(
        self, test_database_url: str
    ) -> None:
        from cost_model import CostModelService

        service = CostModelService(database_url=test_database_url)
        distribution = EmpiricalLatencyDistribution(samples=SAMPLES)
        written = service.persist_latency(
            distribution, "binance_spot", "2026.09.1"
        )
        assert written.p99 == pytest.approx(distribution.p99)
        back = service.latency("binance_spot", "2026.09.1")
        assert back is not None
        assert back.n == distribution.n

    def test_the_service_returns_none_for_an_unmeasured_cost_model(
        self, test_database_url: str
    ) -> None:
        from cost_model import CostModelService

        service = CostModelService(database_url=test_database_url)
        assert service.latency("binance_spot", "2026.09.1") is None
