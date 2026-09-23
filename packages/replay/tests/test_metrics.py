"""Feature 254 — replay latency at p50 and p99, into the observability metrics store.

app_spec.xml, "Replay Engine", feature 254: *System persists replay latency at
p50 and p99 into the observability metrics store.*  The parent (252) measures
one replay's duration on :func:`time.perf_counter`; the sibling (253) alerts
when one duration passes docs §10.4's ~200 ms point; this feature aggregates a
*population* of the parent's records into the two percentiles docs §16 names
among the research metrics (*"replay latency p50/p99"*) and writes them into
the store §16 states the shape of — *"a single Postgres metrics table"*, the
simpler option the section defends at this scale, spelled in this workspace
as the one relational store every member store addresses by ``DATABASE_URL``.

These tests pin the feature as the facts it is made of, in the order a
deployment meets them:

* **the two percentiles are spelled once** — p50 and p99 (two, not the
  cost-model member's three, because this feature's sentence names two), the
  linear method, and the member's own table in the store ``DATABASE_URL``
  names;
* **the summary is the linear method** — the rank of the p-th percentile is
  ``p/100 * (n - 1)`` over the sorted sample, interpolated between order
  statistics: a mid-range rank interpolates, a landing rank answers the
  statistic, a one-replay population answers its one duration, and the
  population's *order* is not trusted (it is sorted, not believed);
* **the slow tail is summarised, never censored** — a population containing a
  300 ms replay keeps it, its p99 carries the tail past the 200 ms point, and
  nothing is refused, clipped or re-centred: 252's law (*measures and
  persists; never refuses*) carried into the store, because the alert on the
  tail is 253's and a store that dropped its own tail would defeat it;
* **the population is read duck-typed** — a carrier is a duration if it
  *answers* one (``duration_seconds``, a finite non-negative real), never an
  ``isinstance`` (the loader's synthetic module name would make the check
  refuse the very record the deployment measured); a bare number names no
  replay and an empty population names no latency — both refused;
* **the report is frozen and self-consistent** — no attribute moves, and a
  report claiming a p50 above its p99 is not a summary of any one sample
  under a monotone method and is refused at construction;
* **the write lands, and the row is the sample** — the durations land as a
  JSON array (the source of truth), the p50/p99 as a derived view over them,
  one row per summarising instant, newest first, upserting onto the same
  instant; reading back rebuilds the report *from the samples*, so the row
  round-trips losslessly;
* **the store is addressed the way every store here is** — ``DATABASE_URL``
  by default, an explicit URL over it, a missing one refused by name and a
  non-sqlite scheme refused loudly;
* **a write that did not land is surfaced, never swallowed** — a store that
  cannot take the write raises in this member's vocabulary, chained to the
  database's own refusal;
* **the ask is validated before the store is touched** — a broken population
  is refused without opening so much as a connection, the ordering of every
  other refusal in this member;
* **no component** — a store addressed by ``DATABASE_URL`` is never composed:
  the member's one ``@register`` contribution stays feature 245's facade.

The store under test is a per-test SQLite file under pytest's temporary
directory, spelled as a ``sqlite:///`` URL the way the root conftest spells
its own isolation — the member suite has no ambient ``DATABASE_URL`` to lean
on, and leaning on one would make the suite's answers depend on the
environment it ran in rather than the feature.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from replay import (
    REPLAY_LATENCY_METHOD,
    REPLAY_LATENCY_QUANTILES,
    REPLAY_LATENCY_TABLE,
    ReplayDuration,
    ReplayError,
    ReplayLatency,
    ReplayMetricsError,
    load_latest_replay_latency,
    load_replay_latency,
    persist_replay_latency,
    replay_latency,
)

POLICY = "policy-v0007"
WORLD = "world-financial-0042"

#: docs §10.4's two numbers, restated for the assertions that read against
#: them: the 50 ms target and the ~200 ms broken-cost-model point.
TARGET = 0.05
ALERT = 0.2


def durations(*seconds: float) -> list[ReplayDuration]:
    """A population of measured durations — 252's records, one per replay.

    The unit this feature aggregates: each carrier is the record the parent
    feature persists, carrying the two identity keys and the one measured
    duration, exactly as a dreaming cycle's loop would hold them between the
    replay and the report.
    """
    return [
        ReplayDuration(f"{POLICY}-{index:04d}", f"{WORLD}-{index:04d}", value)
        for index, value in enumerate(seconds)
    ]


class ForeignDuration:
    """A carrier that *is* a measured duration without being 252's record.

    The duck-typed half of the seam's promise: the summary reads what a
    duration is (``duration_seconds``), never which module defined it, so a
    record produced under the loader's synthetic module name — a second class
    object of the same name — is summarised exactly like this one.
    """

    __slots__ = ("_seconds",)

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    @property
    def duration_seconds(self) -> float:
        return self._seconds


def store_url(tmp_path: Path) -> str:
    """The observability metrics store's URL — a per-test SQLite file.

    Four slashes in total (``sqlite:///`` plus the absolute path's own),
    the SQLAlchemy convention the workspace's ``DATABASE_URL`` uses.
    """
    return f"sqlite:///{tmp_path / 'metrics.db'}"


# ---------------------------------------------------------------------------
# The two percentiles are spelled once
# ---------------------------------------------------------------------------


def test_the_two_percentiles_are_spelled_once() -> None:
    # The feature's sentence names two — p50 and p99 — and docs §16 names the
    # same pair among the research metrics, so the tuple is spelled once for
    # the report, the persistence and every caller that reads the latency.
    # Two, not the cost-model member's three: that feature's sentence named
    # p50/p95/p99, this one names p50/p99.
    assert REPLAY_LATENCY_QUANTILES == (50.0, 99.0)


def test_the_method_and_the_table_are_named_constants() -> None:
    # The quantile convention (numpy's default "linear": rank p/100 * (n - 1),
    # interpolated) is a visible constant rather than a buried arithmetic
    # choice, and the observability metrics store is this member's own table
    # in the relational store DATABASE_URL names — created idempotently on
    # connect, so no migration step and no shared schema file is touched.
    assert REPLAY_LATENCY_METHOD == "linear"
    assert REPLAY_LATENCY_TABLE == "replay_latency_metrics"


# ---------------------------------------------------------------------------
# The summary is the linear method
# ---------------------------------------------------------------------------


def test_a_mid_range_rank_interpolates_linearly() -> None:
    # Ten replays at 10..100 ms: the p50's rank is 0.5 * 9 = 4.5, so it
    # interpolates halfway between the 5th and 6th order statistics (50 ms
    # and 60 ms → 55 ms); the p99's rank is 0.99 * 9 = 8.91, so it
    # interpolates 91% of the way from the 9th to the 10th (90 ms → 99.1 ms).
    # The tail reads above the target and below the alert point — the body of
    # the distribution a deployment supervises.
    report = replay_latency(durations(0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10))
    assert report.n == 10
    assert report.p50_seconds == pytest.approx(0.055)
    assert report.p99_seconds == pytest.approx(0.0991)


def test_a_landing_rank_answers_the_order_statistic() -> None:
    # Five replays: the p50's rank is 0.5 * 4 = 2, which lands exactly on the
    # third order statistic — no interpolation, the statistic itself.  The
    # p99's rank 3.96 interpolates 96% of the way from the 4th to the 5th.
    report = replay_latency(durations(0.01, 0.02, 0.03, 0.04, 0.05))
    assert report.p50_seconds == 0.03
    assert report.p99_seconds == pytest.approx(0.0496)


def test_a_one_replay_population_answers_its_one_duration() -> None:
    # A single observation has no spread to interpolate over: every quantile
    # is that one value, the honest answer for a one-replay population (and
    # the reason the report carries n — a p99 over one replay is a number a
    # reader must be able to distrust).
    report = replay_latency(durations(0.042))
    assert report.n == 1
    assert report.p50_seconds == 0.042
    assert report.p99_seconds == 0.042


def test_the_population_is_sorted_not_believed() -> None:
    # The order statistics are read off the *sorted* sample, so a caller that
    # holds its durations in arrival order (or reverse, or shuffled) gets the
    # same percentiles: the summary is a function of the population, not of
    # the order it was handed in.
    forward = durations(0.01, 0.02, 0.03, 0.04, 0.30)
    backward = list(reversed(forward))
    assert replay_latency(backward).p50_seconds == replay_latency(forward).p50_seconds
    assert replay_latency(backward).p99_seconds == replay_latency(forward).p99_seconds


def test_a_rank_outside_the_sample_is_refused() -> None:
    # The pure arithmetic seam defends its own bounds: a p101 would read one
    # past the last order statistic and a negative percentile names no rank,
    # and a latency quantile built on a silently clamped rank would be a
    # tail the numbers do not support.
    from replay.metrics import quantile

    for bad in (101.0, -0.5):
        with pytest.raises(ReplayMetricsError):
            quantile([0.01, 0.02], bad)


# ---------------------------------------------------------------------------
# The slow tail is summarised, never censored
# ---------------------------------------------------------------------------


def test_the_slow_tail_is_summarised_never_censored() -> None:
    # Four replays, one of them 300 ms — past docs §10.4's ~200 ms point, the
    # reading feature 253's recomputation_suspected alert exists for.  The
    # summary keeps it: nothing is refused, clipped or re-centred, and the
    # p99 (interpolating 97% of the way from 40 ms to 300 ms) carries the
    # tail past the alert point where a plain average would have buried it.
    # 252's law — measures and persists, never refuses — carried into the
    # store, because the alert on this tail is 253's and a store that dropped
    # its own tail would defeat the alert beside it.
    report = replay_latency(durations(0.02, 0.03, 0.04, 0.30))
    assert report.p50_seconds == pytest.approx(0.035)
    assert report.p99_seconds == pytest.approx(0.2922)
    assert report.p99_seconds > ALERT
    assert report.p50_seconds < TARGET


# ---------------------------------------------------------------------------
# The population is read duck-typed
# ---------------------------------------------------------------------------


def test_a_measured_replay_is_summarised_off_its_own_timer() -> None:
    # The parent's own spelling of a duration — measure_replay over a body —
    # produces records this feature summarises, so the measurement and the
    # report are one lineage: the record the timer answers is the unit the
    # percentiles aggregate, not a shape the summary re-derives.
    from replay import measure_replay

    measured: list[ReplayDuration] = []
    for index in range(3):
        with measure_replay(f"{POLICY}-{index:04d}", f"{WORLD}-{index:04d}") as timer:
            pass  # the body is the replay; a bare one still measures a span
        measured.append(timer.duration)
    report = replay_latency(measured)
    assert report.n == 3
    assert 0.0 <= report.p50_seconds <= report.p99_seconds


def test_a_foreign_carrier_answering_a_duration_is_summarised() -> None:
    # The seam reads what a duration *is* — a duration_seconds answering a
    # finite non-negative real — never which module defined it, because the
    # loader imports a member under a synthetic name and re-executes it: the
    # record a composed application's path produced is a second class object
    # of the same name, and an isinstance would refuse the very duration the
    # deployment measured.
    report = replay_latency([ForeignDuration(0.02), ForeignDuration(0.04)])
    assert report.n == 2
    assert report.p50_seconds == pytest.approx(0.03)
    assert report.p99_seconds == pytest.approx(0.0398)  # rank 0.99 interpolates 99% of 0.02→0.04


def test_a_bare_number_is_refused_as_a_population() -> None:
    # A number names no (policy, world) replay: 252's record — the
    # measurement *and* the identity it was measured for — is the unit this
    # feature aggregates, so a bare number (or a string, or nothing) is not
    # a population of them.
    for bad in (42, 0.03, "0.03", None, True):
        with pytest.raises(ReplayMetricsError):
            replay_latency(bad)  # type: ignore[arg-type]


def test_an_empty_population_is_refused() -> None:
    # p50/p99 over zero replays is not a latency, it is the absence of one —
    # persisting such a figure would be the fabricated latency feature 67's
    # sentence refuses to fall back to and this one inherits the refusal of.
    with pytest.raises(ReplayMetricsError) as raised:
        replay_latency([])
    assert "empty population" in str(raised.value)


def test_a_carrier_that_is_not_a_duration_is_refused() -> None:
    # A bare float inside the population, a bare object, a string: none
    # answers a measured duration, so none names a replay the population
    # could be summarised over.  The refusal names the position, which is
    # what a caller holding a thousand durations needs to find the one that
    # is not a measurement.
    for bad in ([0.03], [object()], ["0.03"]):
        with pytest.raises(ReplayMetricsError) as raised:
            replay_latency(bad)  # type: ignore[list-item]
        assert "position 0" in str(raised.value)


def test_a_broken_duration_is_refused_as_it_is_read() -> None:
    # The three facts 252's constructor defends, restated for the duck-typed
    # read: a duration that is not a number, not finite, or negative is not a
    # measurement, and a percentile must never aggregate one — a NaN would
    # compare false against every rank, an infinity is a ruler with no end,
    # and a negative duration is a clock read in the wrong order.
    class Carrier:
        __slots__ = ("_seconds",)

        def __init__(self, seconds: object) -> None:
            self._seconds = seconds

        @property
        def duration_seconds(self) -> object:
            return self._seconds

    for bad in (float("nan"), float("inf"), -0.001, "0.03", None, True):
        with pytest.raises(ReplayMetricsError):
            replay_latency([Carrier(bad)])


# ---------------------------------------------------------------------------
# The report is frozen and self-consistent
# ---------------------------------------------------------------------------


def test_the_report_is_frozen() -> None:
    # A report is a measurement of a population, and a measurement that could
    # be reassigned after the fact would be a latency no dashboard and no
    # alert could rely on — the same reason 252's record is frozen on the
    # duration it started from.  The write is refused and the values stay.
    report = replay_latency(durations(0.02, 0.04))
    with pytest.raises(AttributeError):
        report.p50_seconds = 0.9  # type: ignore[misc]
    with pytest.raises(AttributeError):
        report.n = 40  # type: ignore[misc]
    assert report.n == 2
    assert report.p50_seconds == pytest.approx(0.03)


def test_a_report_claiming_p50_above_p99_is_refused() -> None:
    # The linear method interpolates a monotone rank over a sorted sample, so
    # the median of a population cannot exceed its 99th percentile — a report
    # claiming the reverse is not a summary of any one sample, and the
    # constructor (the seam's own spelling, for a caller holding computed
    # percentiles) refuses it.
    with pytest.raises(ReplayMetricsError):
        ReplayLatency(2, 0.300, 0.030)


def test_a_broken_report_is_refused_at_construction() -> None:
    # The constructor's own invariants, defended for the reader that rebuilds
    # from persisted samples and the caller that computes its own: a count
    # that is not a positive integer names no population, and a percentile
    # that is not a finite non-negative real is not an order statistic of
    # measured durations.
    for bad_n in (0, -1, "4", 2.0, True, None):
        with pytest.raises(ReplayMetricsError):
            ReplayLatency(bad_n, 0.03, 0.04)  # type: ignore[arg-type]
    for bad_p in (float("nan"), float("inf"), -0.001, "0.03", None, True):
        with pytest.raises(ReplayMetricsError):
            ReplayLatency(2, bad_p, 0.04)  # type: ignore[arg-type]
        with pytest.raises(ReplayMetricsError):
            ReplayLatency(2, 0.03, bad_p)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The write lands, and the row is the sample
# ---------------------------------------------------------------------------


def test_the_report_lands_in_the_observability_metrics_table(tmp_path: Path) -> None:
    # The feature's sentence, made concrete: one row in the member's own
    # table in the store DATABASE_URL names — the durations as a JSON array
    # (the source of truth, sorted, in seconds), the count beside them, and
    # the p50/p99 as the derived view over them.  Read off the raw table so
    # the assertion is about what *landed*, not what the reader reconstructs.
    url = store_url(tmp_path)
    report = persist_replay_latency(
        durations(0.04, 0.02, 0.06),
        measured_at="2026-09-23T12:00:00+00:00",
        source="dreaming-cycle-0031",
        database_url=url,
    )
    with sqlite3.connect(tmp_path / "metrics.db") as connection:
        rows = connection.execute(
            f"SELECT measured_at, source, n, samples, p50, p99 "
            f"FROM {REPLAY_LATENCY_TABLE}"
        ).fetchall()
    assert len(rows) == 1
    measured_at, source, count, samples_json, p50, p99 = rows[0]
    assert measured_at == "2026-09-23T12:00:00+00:00"
    assert source == "dreaming-cycle-0031"
    assert count == 3
    assert json.loads(samples_json) == [0.02, 0.04, 0.06]  # sorted, seconds
    assert p50 == report.p50_seconds == pytest.approx(0.04)
    assert p99 == report.p99_seconds == pytest.approx(0.0596)  # rank 1.98: 0.04 + 0.98 * 0.02
    assert report.n == 3


def test_the_row_round_trips_from_the_samples(tmp_path: Path) -> None:
    # Reading back rebuilds the report from the samples — the source of
    # truth — never from the denormalised p50/p99 columns, so the report a
    # caller reads is the summary of the population that was written and
    # cannot drift from it.  The round trip is lossless: same count, same
    # two percentiles, recomputed by the same method.
    url = store_url(tmp_path)
    written = persist_replay_latency(
        durations(0.01, 0.02, 0.03, 0.04, 0.30),
        measured_at="2026-09-23T12:00:00+00:00",
        database_url=url,
    )
    history = load_replay_latency(url)
    assert [instant for instant, _, _ in history] == ["2026-09-23T12:00:00+00:00"]
    _, read_back, source = history[0]
    assert source is None
    assert read_back.n == written.n
    assert read_back.p50_seconds == written.p50_seconds
    assert read_back.p99_seconds == written.p99_seconds


def test_the_table_is_a_history_newest_first(tmp_path: Path) -> None:
    # One row per summarising instant: a deployment's replay latency is
    # re-measured every dreaming cycle, so each cycle's percentiles are a
    # distinct snapshot and the table accumulates them in time order —
    # ISO 8601 keys make the string order chronological, and the reader
    # answers newest first.
    url = store_url(tmp_path)
    persist_replay_latency(
        durations(0.02, 0.04), measured_at="2026-09-23T12:00:00+00:00", database_url=url
    )
    persist_replay_latency(
        durations(0.03, 0.05), measured_at="2026-09-23T18:00:00+00:00", database_url=url
    )
    instants = [instant for instant, _, _ in load_replay_latency(url)]
    assert instants == ["2026-09-23T18:00:00+00:00", "2026-09-23T12:00:00+00:00"]


def test_the_same_instant_upserts_onto_the_one_row(tmp_path: Path) -> None:
    # A re-summarise at the same instant is the same snapshot written twice,
    # and the honest answer is one row refreshed — not a second row a reader
    # would count as a second measurement.  The rewrite touches the measured
    # values and never the key, so it cannot re-key a stored report.
    url = store_url(tmp_path)
    instant = "2026-09-23T12:00:00+00:00"
    persist_replay_latency(
        durations(0.02, 0.04), measured_at=instant, database_url=url
    )
    second = persist_replay_latency(
        durations(0.30, 0.32), measured_at=instant, database_url=url
    )
    history = load_replay_latency(url)
    assert len(history) == 1
    assert history[0][0] == instant
    assert history[0][1].p50_seconds == second.p50_seconds


def test_the_schema_is_created_idempotently(tmp_path: Path) -> None:
    # CREATE TABLE IF NOT EXISTS on connect — the contract every store in
    # this workspace states — so a fresh database and an existing one take
    # one path, and writing twice (or reading a database this member has
    # never touched) creates nothing new and breaks nothing existing.
    url = store_url(tmp_path)
    persist_replay_latency(
        durations(0.02), measured_at="2026-09-23T12:00:00+00:00", database_url=url
    )
    persist_replay_latency(
        durations(0.02), measured_at="2026-09-23T12:00:01+00:00", database_url=url
    )
    assert load_latest_replay_latency(url) is not None
    # And a second store, fresh, answers None rather than raising: an absent
    # history is a discoverable state, not an exception.
    assert load_latest_replay_latency(store_url(tmp_path) + ".fresh") is None


def test_load_latest_answers_the_newest_snapshot(tmp_path: Path) -> None:
    # The reader a dashboard or an operator resolves against: the newest
    # snapshot in the history.  None is the honest answer for a deployment
    # that has never summarised a population — a signal the caller must
    # handle, never a zero to paper over, because a zero would be the
    # fabricated latency the feature refuses to produce.
    url = store_url(tmp_path)
    assert load_latest_replay_latency(url) is None
    persist_replay_latency(
        durations(0.02, 0.04), measured_at="2026-09-23T12:00:00+00:00", database_url=url
    )
    latest = persist_replay_latency(
        durations(0.03, 0.05), measured_at="2026-09-23T18:00:00+00:00", database_url=url
    )
    read_back = load_latest_replay_latency(url)
    assert read_back is not None
    assert read_back.p50_seconds == latest.p50_seconds
    assert read_back.n == latest.n


# ---------------------------------------------------------------------------
# The store is addressed the way every store here is
# ---------------------------------------------------------------------------


def test_database_url_is_the_default_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one ambient the workspace's stores share: without an explicit URL
    # the write and the read both go to DATABASE_URL, so a deployment
    # configures its observability metrics store exactly once and every
    # member's store resolves the same way.
    url = store_url(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    written = persist_replay_latency(
        durations(0.02, 0.04), measured_at="2026-09-23T12:00:00+00:00"
    )
    assert load_latest_replay_latency() is not None
    assert load_latest_replay_latency().p50_seconds == written.p50_seconds


def test_an_unconfigured_store_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A missing DATABASE_URL — and no explicit URL — is refused by name
    # rather than by a bare KeyError: the caller asked for a store it did
    # not configure, and the message says which variable would have named
    # one.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ReplayMetricsError) as raised:
        persist_replay_latency(
            durations(0.02), measured_at="2026-09-23T12:00:00+00:00"
        )
    assert "DATABASE_URL" in str(raised.value)
    with pytest.raises(ReplayMetricsError):
        load_replay_latency()


def test_a_non_sqlite_scheme_is_refused_loudly(tmp_path: Path) -> None:
    # The store speaks sqlite:/// (the spec's single-machine allowance), and
    # any other scheme is refused loudly rather than silently mis-parsed —
    # a misrouted Postgres URL cannot hide behind a mysterious file.  The
    # same refusal the cost-model member's stores document for theirs.
    for url in ("postgres://metrics/nullius", "mysql://metrics/nullius"):
        with pytest.raises(ReplayMetricsError) as raised:
            persist_replay_latency(
                durations(0.02), measured_at="2026-09-23T12:00:00+00:00", database_url=url
            )
        assert "scheme" in str(raised.value)


def test_a_store_that_cannot_take_the_write_is_surfaced(tmp_path: Path) -> None:
    # A latency that measured but never landed is the state the feature
    # exists to rule out: the database's own refusal (here, a database file
    # that is actually a directory) is translated into this member's
    # vocabulary, chained to the original so the operator still sees the
    # database's words — surfaced, never swallowed.
    with pytest.raises(ReplayMetricsError) as raised:
        persist_replay_latency(
            durations(0.02, 0.04),
            measured_at="2026-09-23T12:00:00+00:00",
            database_url=f"sqlite:///{tmp_path}",  # a directory, not a file
        )
    assert isinstance(raised.value.__cause__, sqlite3.Error)


# ---------------------------------------------------------------------------
# The ask is validated before the store is touched
# ---------------------------------------------------------------------------


def test_the_population_is_validated_before_the_store_is_touched(tmp_path: Path) -> None:
    # The ordering of every refusal in this member (245's before the tree is
    # read, 251's before the arena is touched, 252's before the clock is
    # read), restated for the write: a broken population is the caller's to
    # repair and the store should never see it — pinned by handing both a
    # broken population *and* a URL whose scheme would itself refuse, and
    # reading which refusal answered.
    with pytest.raises(ReplayMetricsError) as raised:
        persist_replay_latency([], database_url="postgres://metrics/nullius")
    assert "empty population" in str(raised.value)
    with pytest.raises(ReplayMetricsError) as raised:
        persist_replay_latency(
            [object()], database_url="postgres://metrics/nullius"
        )
    assert "position 0" in str(raised.value)


def test_a_malformed_instant_is_refused_before_the_store_is_touched(
    tmp_path: Path,
) -> None:
    # The instant is the row's key, and a key that is not a nameable instant
    # would upsert onto nothing nameable — refused as part of the ask, before
    # a connection is opened (pinned the same way: over a URL that would
    # itself refuse).
    with pytest.raises(ReplayMetricsError) as raised:
        persist_replay_latency(
            durations(0.02), measured_at="   ", database_url="postgres://x/y"
        )
    assert "instant" in str(raised.value)


def test_a_corrupt_row_is_refused_by_name(tmp_path: Path) -> None:
    # The tamper defence that keeps the history trustworthy: a row whose
    # samples do not read back as the population they claim — not JSON, not
    # a non-empty array of finite non-negative reals, or a count that
    # disagrees with them — is refused by name rather than quietly answered
    # with a fabricated percentile.  The rows are written by hand, which is
    # exactly the hand a corrupt row would arrive by.
    url = store_url(tmp_path)
    persist_replay_latency(
        durations(0.02, 0.04), measured_at="2026-09-23T12:00:00+00:00", database_url=url
    )
    database = tmp_path / "metrics.db"
    corrupt_samples = [
        "not json at all",
        "[]",
        "[0.01, null]",
        "[-0.01, 0.02]",
        '"a string, not an array"',
    ]
    with sqlite3.connect(database) as connection:
        for index, bad in enumerate(corrupt_samples):
            connection.execute(
                f"INSERT INTO {REPLAY_LATENCY_TABLE} "
                f"(measured_at, source, n, samples, p50, p99) "
                f"VALUES (?, ?, ?, ?, ?, ?)",
                (f"2026-09-24T12:00:{index:02d}+00:00", None, 2, bad, 0.01, 0.02),
            )
    with pytest.raises(ReplayMetricsError):
        load_replay_latency(url)
    # And a row whose stored count disagrees with its own samples: the count
    # is the one figure the samples already determine, so a disagreement is
    # a row that disagrees with its own truth.
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"DELETE FROM {REPLAY_LATENCY_TABLE} "
            f"WHERE measured_at != '2026-09-23T12:00:00+00:00'"
        )
        connection.execute(
            f"UPDATE {REPLAY_LATENCY_TABLE} SET n = 7 "
            f"WHERE measured_at = '2026-09-23T12:00:00+00:00'"
        )
    with pytest.raises(ReplayMetricsError) as raised:
        load_replay_latency(url)
    assert "count" in str(raised.value)


# ---------------------------------------------------------------------------
# The vocabulary and the composed surface
# ---------------------------------------------------------------------------


def test_the_refusals_are_this_members_vocabulary() -> None:
    # The report's failures join the member's one base class — a caller's
    # single ``except ReplayError`` catches every way a latency report can
    # fail to be one — and the class is a sibling of the read's and the
    # tree's, not nested under either: a caller skipping a bad campaign must
    # not silently skip a broken report, and vice versa.
    assert issubclass(ReplayMetricsError, ReplayError)
    from replay import ReplayReturnsError, ReplayTreeError

    assert not issubclass(ReplayMetricsError, ReplayTreeError)
    assert not issubclass(ReplayMetricsError, ReplayReturnsError)
    with pytest.raises(ReplayError):
        replay_latency([])


def test_the_observability_surface_is_the_members_public_surface() -> None:
    # The package fronts the whole feature — the record, the summary, the
    # write, the two readers — the way it fronts 252's timer and record, so
    # a caller (the dreaming loop, a benchmark, a dashboard's loader) holds
    # one import and no private module path.
    import replay

    for name in (
        "ReplayLatency",
        "replay_latency",
        "persist_replay_latency",
        "load_replay_latency",
        "load_latest_replay_latency",
        "ReplayMetricsError",
        "REPLAY_LATENCY_QUANTILES",
        "REPLAY_LATENCY_METHOD",
        "REPLAY_LATENCY_TABLE",
    ):
        assert name in replay.__all__, name
        assert getattr(replay, name, None) is not None, name


def test_the_feature_registers_no_component() -> None:
    # A store addressed by DATABASE_URL is never composed — the stance every
    # store in this workspace takes — so the member's one @register
    # contribution stays feature 245's stateless facade, and composition
    # still spends no I/O on the observability path.  A fresh registry, not
    # the process default: the question is exactly *what does this member
    # register?*
    import replay as replay_module

    from app.module_loader import Registration, scan_components

    member_src = Path(replay_module.__file__).resolve().parent.parent
    components = scan_components(member_src, registry=Registration())
    assert [component.name for component in components] == ["replay"]
