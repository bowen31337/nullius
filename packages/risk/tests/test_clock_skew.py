"""Feature 329: the measured clock skew that halted trading, persisted.

The suite is organised around the sentence's four claims, because they
are the four things that can silently stop being true:

* **Measured.**  :func:`measure_clock_skew` is a pure function over two
  caller-supplied readings, and its result is *signed* — the direction is
  the repair, so a magnitude that dropped the sign sends an operator to
  the wrong correction.  The module reads no clock to measure one: the
  only instant it mints is ``recorded_at``.
* **When it exceeded the threshold.**  The comparison is strictly ``>``,
  on both sides of zero.  This is pinned at the boundary rather than
  approximated: a skew of exactly the threshold is *inside* the band, and
  the test that passes one asserts ``None``, no row, and no kill — the
  store is not even opened.  The threshold is configuration with no
  default, so the validation tests are the other half of this claim.
* **Against exchange server time.**  The venue's reading is a *field* on
  the record, beside this clock's reading of the same probe, so the skew
  can be re-derived by a reader who trusts neither the writer nor its
  arithmetic.  ``halted_at`` is the standing kill instruction's own
  ``sent_at``, read back from feature 322's channel — never a moment this
  module stamped — so the halt moment and the channel's row are one fact.
* **Persists.**  Only a *halting* measurement lands, every halt leaves
  exactly one row, and a halt that could not be recorded is raised rather
  than shrugged past.  The retry law is the ``UNIQUE`` probe pair: the
  same probe measured twice is one row, a different probe is a second.

The refusals are the fifth subject: a reading that is naive or not a
moment, a threshold that states no band, a stored row whose skew
disagrees with its own instants or never actually exceeded its own band
(including past a ``PRAGMA ignore_check_constraints`` edit, which is why
the value layer is the law and the ``CHECK`` is only the belt), and a
module-level halt that names no store.  Each in its own class, each named
by the grep token its messages open with.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from risk._identity import process_identity
from risk.clock_skew import (
    DATABASE_URL_ENV,
    RISK_CLOCK_SKEW_TABLE,
    RiskClockSkewStore,
    halt_on_clock_skew,
    measure_clock_skew,
    measured_clock_skews,
)
from risk.errors import (
    CLOCK_SKEW_CODE,
    RiskClockSkewError,
    RiskError,
    RiskStoreError,
)
from risk.kill import RISK_ORDER_KILL_TABLE, RiskKillSwitch

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The probe both sides of the measurement read.  A fixed instant, so
#: every assertion about a stored string or a recomputed skew is exact.
PROBE = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
LATER = PROBE + timedelta(hours=1)
EARLIER = PROBE - timedelta(hours=1)

#: A band wide enough that the probes below are unambiguously outside it
#: when the test means them to be, and unambiguously inside it otherwise.
BAND = 2.0


@pytest.fixture
def store(test_database_url: str) -> RiskClockSkewStore:
    return RiskClockSkewStore(test_database_url)


def _iso(moment: datetime) -> str:
    """The store's own canonical spelling, for asserting on stored strings.

    Restated rather than imported from the module's private helper, so
    these tests measure the stored spelling rather than a copy of the
    function that writes it: if the canonical form changed, a test that
    imported it would change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _row_count(database_url: str) -> int:
    """How many rows the table holds, read with the driver directly."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_CLOCK_SKEW_TABLE}"
            ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return count


def _rows(database_url: str) -> list[tuple]:
    """Every raw row, so a test can assert on what is actually stored."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute(
                f"SELECT sequence, measured_skew_seconds, threshold_seconds, "
                f"exchange_server_time, local_time, halted_at, "
                f"supervisor_process_id, recorded_at "
                f"FROM {RISK_CLOCK_SKEW_TABLE} ORDER BY sequence"
            ).fetchall()
    except sqlite3.OperationalError:
        return []


def _edit(
    database_url: str, statement: str, parameters: tuple = (), *, checks: bool = True
) -> None:
    """Rewrite the table with the driver directly — the tamper path.

    ``checks=False`` turns the schema's ``CHECK``\\ s off for the edit,
    which is what an out-of-band tool (or anyone who knows the pragma)
    can do.  The tests that use it are asserting the *value* layer
    refuses the row anyway — the reason this module treats the ``CHECK``
    as belt rather than law.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection, connection:
        if not checks:
            connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(statement, parameters)


# -- Measured ---------------------------------------------------------------------


class TestTheMeasurement:
    def test_a_clock_that_agrees_reads_zero(self) -> None:
        # The reading that is not a fault: same instant, same zone.
        assert measure_clock_skew(exchange_server_time=PROBE, local_time=PROBE) == 0.0

    def test_the_skew_is_signed_and_positive_means_ahead(self) -> None:
        # The direction is the repair.  A clock ahead of the venue's is
        # corrected backward, one behind forward, and a magnitude that
        # dropped the sign would send an operator to the wrong one.
        ahead = measure_clock_skew(
            exchange_server_time=PROBE, local_time=PROBE + timedelta(seconds=3)
        )
        behind = measure_clock_skew(
            exchange_server_time=PROBE, local_time=PROBE - timedelta(seconds=3)
        )
        assert ahead == 3.0
        assert behind == -3.0

    def test_the_skew_is_exactly_the_difference_of_the_two_readings(self) -> None:
        # The two readings *are* the measurement; the number is their
        # arithmetic and nothing else.  Fractional seconds included, so a
        # truncation anywhere in the path would show.
        skew = measure_clock_skew(
            exchange_server_time=PROBE,
            local_time=PROBE + timedelta(seconds=1, microseconds=250_000),
        )
        assert skew == 1.25

    def test_two_zones_are_the_same_instant_compared_correctly(self) -> None:
        # A venue stamping in +00:00 and a host reading in +09:00 need no
        # normalisation here: both readings are aware, so the subtraction
        # is by their offsets.
        tokyo = PROBE.astimezone(timezone(timedelta(hours=9)))
        assert measure_clock_skew(exchange_server_time=PROBE, local_time=tokyo) == 0.0
        assert measure_clock_skew(
            exchange_server_time=tokyo, local_time=PROBE + timedelta(seconds=5)
        ) == 5.0

    def test_the_measurement_never_reads_a_clock_of_its_own(self) -> None:
        # Feature 329's first word is *measured*, and a function that
        # stamped its own instant would not be reproducible from the two
        # values a later reconciliation holds.  Called twice, the same
        # probe answers the same number -- which a `datetime.now()` in the
        # path would make impossible at microsecond resolution.
        first = measure_clock_skew(
            exchange_server_time=PROBE, local_time=PROBE + timedelta(seconds=3)
        )
        second = measure_clock_skew(
            exchange_server_time=PROBE, local_time=PROBE + timedelta(seconds=3)
        )
        assert first == second == 3.0

    @pytest.mark.parametrize("what", ["local_time", "exchange_server_time"])
    def test_a_naive_reading_is_refused(self, what: str) -> None:
        # A skew measured against a naive instant is a skew against no
        # instant, and the halt it caused could not be ordered against
        # anything -- the same discipline kill.py holds `sent_at` to.
        naive = PROBE.replace(tzinfo=None)
        readings = {"local_time": PROBE, "exchange_server_time": PROBE}
        readings[what] = naive
        with pytest.raises(RiskClockSkewError) as refused:
            measure_clock_skew(**readings)
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert what in str(refused.value)

    @pytest.mark.parametrize("what", ["local_time", "exchange_server_time"])
    def test_a_reading_that_is_not_a_moment_is_refused(self, what: str) -> None:
        readings = {"local_time": PROBE, "exchange_server_time": PROBE}
        readings[what] = "2026-09-25T12:00:00+00:00"
        with pytest.raises(RiskClockSkewError) as refused:
            measure_clock_skew(**readings)
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "not str" in str(refused.value)

    def test_the_refusal_is_the_members_own_class(self) -> None:
        # Every face of feature 329 is catchable by the base class, so a
        # supervisor wrapping its whole halt path catches them all.
        with pytest.raises(RiskError):
            measure_clock_skew(exchange_server_time=PROBE, local_time=None)


# -- When it exceeded the threshold -----------------------------------------------


class TestTheThresholdBoundary:
    def test_a_skew_inside_the_band_is_not_a_halt(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # §13.3's trigger is `>`, strictly, so a probe inside the band is
        # not this feature's business: no record, no kill, and the store
        # is not so much as opened -- which the row count and the empty
        # channel both state.
        assert (
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=1),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
            )
            is None
        )
        assert _row_count(test_database_url) == 0
        assert RiskKillSwitch(test_database_url).standing() is None

    def test_a_skew_exactly_at_the_threshold_is_inside_the_band(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # The boundary pinned exactly, not approximated: `>` excludes
        # equality, which is the convention feature 312's neighbour rule,
        # canary._halt.DreamHalt's `deviation <= tolerance` refusal and
        # feature 314's strict `<` all state.
        assert (
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=BAND),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
            )
            is None
        )
        assert _row_count(test_database_url) == 0

    def test_the_boundary_is_the_same_on_the_other_side_of_zero(
        self, store: RiskClockSkewStore
    ) -> None:
        # A clock running behind is as dangerous as one running ahead, so
        # the comparison is on the magnitude -- and its boundary is just
        # as strict.
        assert (
            store.halt_on_skew(
                local_time=PROBE - timedelta(seconds=BAND),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
            )
            is None
        )

    def test_a_skew_just_past_the_threshold_halts(
        self, store: RiskClockSkewStore
    ) -> None:
        # One microsecond is enough, in either direction: the boundary is
        # a strict comparison, not a tolerance.
        ahead = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=BAND, microseconds=1),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        behind = store.halt_on_skew(
            local_time=PROBE - timedelta(seconds=BAND, microseconds=1),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert ahead is not None and behind is not None
        assert ahead.direction == "ahead"
        assert behind.direction == "behind"

    @pytest.mark.parametrize("band", [0, -1, -0.5])
    def test_a_band_that_is_not_a_band_is_refused(
        self, store: RiskClockSkewStore, band: float
    ) -> None:
        # Every skew other than exactly zero exceeds a non-positive band,
        # so a threshold of zero or less is a supervisor that halts on
        # every probe rather than on a clock fault.
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=band,
            )
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "greater than zero" in str(refused.value)

    @pytest.mark.parametrize("band", [True, False])
    def test_a_bool_band_is_refused_by_name(
        self, store: RiskClockSkewStore, band: bool
    ) -> None:
        # `isinstance(True, int)` is true in Python, so a naive numeric
        # check would accept `threshold_seconds=True` and halt on a band
        # of one second -- the reason ops.live_metrics refuses bools
        # before it looks at the number.
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=band,
            )
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "bool" in str(refused.value)

    @pytest.mark.parametrize("band", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_band_is_refused(
        self, store: RiskClockSkewStore, band: float
    ) -> None:
        # `nan` compares false against everything, so a `nan` threshold
        # would answer "inside the band" for a skew of any size -- the one
        # direction this feature must never fail in.
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=band,
            )
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "finite" in str(refused.value)

    def test_a_band_that_is_not_a_number_is_refused(
        self, store: RiskClockSkewStore
    ) -> None:
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds="2.0",
            )
        assert CLOCK_SKEW_CODE in str(refused.value)

    def test_the_threshold_has_no_default(self, store: RiskClockSkewStore) -> None:
        # §13.3 says "threshold" and names no number, so the band is
        # configuration: a supervisor that guessed one would halt on a
        # skew nobody configured it to halt on.
        with pytest.raises(TypeError):
            store.halt_on_skew(  # type: ignore[call-arg]
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
            )

    def test_a_band_that_is_not_positive_never_reaches_the_channel(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # The band is judged before anything is sent or written, so a
        # misconfigured deployment does not leave a kill standing that
        # nothing accounts for.
        with pytest.raises(RiskClockSkewError):
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=0,
            )
        assert RiskKillSwitch(test_database_url).standing() is None
        assert _row_count(test_database_url) == 0


# -- Against exchange server time, and the halt -----------------------------------


class TestTheHalt:
    def test_the_halt_sends_the_kill_and_stops_the_order_layer(
        self, store: RiskClockSkewStore
    ) -> None:
        # Halting is feature 322's channel, not a verb of this module: the
        # skew halt stops trading through the instruction the order layer
        # already refuses under.
        record = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        standing = store.switch.standing()
        assert standing is not None
        assert standing.instruction == "kill"
        # The order layer's own guard, over the same store: the receipt of
        # the kill the skew halt sent.
        with pytest.raises(RiskError):
            store.switch.require_orders_allowed()
        assert store.switch.killed() is True

    def test_halted_at_is_the_channels_own_sent_at(
        self, store: RiskClockSkewStore
    ) -> None:
        # The record's halt moment and the channel's row are one fact
        # rather than two that could drift: `halted_at` is read back from
        # the instruction that stands, never stamped by this module.
        record = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        standing = store.switch.standing()
        assert standing is not None
        assert record.halted_at == standing.sent_at

    def test_a_second_halting_probe_keeps_the_first_halt_moment(
        self, store: RiskClockSkewStore
    ) -> None:
        # The channel is first-write-wins, so the second send writes
        # nothing and returns the first instruction -- which is the moment
        # trading actually stopped, and therefore the honest `halted_at`
        # for the second row too.  Two probes, two rows, one halt moment.
        first = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        second = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=4),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert first is not None and second is not None
        assert second.halted_at == first.halted_at
        assert len(store.skews()) == 2

    def test_the_halt_does_not_flatten(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # Feature 330 owns the flatten and feature 323's door drives it.
        # A clock-skew halt stops new orders through the channel and
        # leaves the open book to the feature that owns closing it -- so
        # this module exposes no flatten verb at all.
        assert not hasattr(store, "flatten")
        assert not hasattr(store, "flatten_positions")

    def test_the_record_names_the_process_that_recorded_it(
        self, store: RiskClockSkewStore
    ) -> None:
        # Read from the kernel rather than accepted from the caller, the
        # same label and for the same reason the kill switch's send
        # refuses a caller-supplied one.
        record = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        assert record.supervisor_process_id == process_identity()
        assert record.supervisor_process_id == store.process_id

    def test_a_label_states_a_process_or_is_refused(
        self, store: RiskClockSkewStore
    ) -> None:
        # Keyword-only, so a caller on the supervisor's own path does not
        # pass it -- and the one that does must say something.
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
                supervisor_process_id="   ",
            )
        assert CLOCK_SKEW_CODE in str(refused.value)

    def test_the_record_is_frozen(self, store: RiskClockSkewStore) -> None:
        record = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        with pytest.raises(FrozenInstanceError):
            record.measured_skew_seconds = 0.0  # type: ignore[misc]

    def test_the_record_says_which_way_the_clock_was_off(
        self, store: RiskClockSkewStore
    ) -> None:
        # The repair, named: a magnitude alone sends an operator to the
        # wrong correction.
        record = store.halt_on_skew(
            local_time=PROBE - timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        assert record.direction == "behind"
        assert "behind" in record.summary
        assert "-3.0" in record.summary or "3.000000" in record.summary


# -- Persists ---------------------------------------------------------------------


class TestTheRecording:
    def test_every_column_lands_with_its_own_value(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        local = PROBE + timedelta(seconds=3)
        record = store.halt_on_skew(
            local_time=local,
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        (
            sequence,
            measured,
            threshold,
            exchange,
            stored_local,
            halted_at,
            sender,
            recorded_at,
        ) = _rows(test_database_url)[0]
        assert sequence == record.sequence == 1
        assert measured == 3.0
        assert threshold == BAND
        assert exchange == _iso(PROBE)
        assert stored_local == _iso(local)
        assert halted_at == _iso(record.halted_at)
        assert sender == process_identity()
        assert recorded_at == _iso(record.recorded_at)

    def test_the_venue_reading_is_a_field_beside_this_clocks(
        self, store: RiskClockSkewStore
    ) -> None:
        # The sentence's *"against exchange server time"*: both readings
        # are on the record, so the skew can be re-derived by a reader who
        # trusts neither the writer nor the number it wrote.
        record = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        assert record.exchange_server_time == PROBE
        assert record.local_time == PROBE + timedelta(seconds=3)
        assert (
            record.local_time - record.exchange_server_time
        ).total_seconds() == record.measured_skew_seconds

    def test_the_band_that_fired_is_stored_not_re_read(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # A deployment that retunes its threshold must not silently
        # re-judge the halts it already took: whether *this* halt was
        # justified is decided against the band in force at the time.
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=2.5,
        )
        assert _rows(test_database_url)[0][2] == 2.5

    def test_the_stored_instants_are_the_canonical_utc_spelling(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # One UTC offset, one format, one width policy -- so the reader's
        # window is a comparison over rows this store wrote.
        tokyo = PROBE.astimezone(timezone(timedelta(hours=9)))
        store.halt_on_skew(
            local_time=tokyo + timedelta(seconds=3),
            exchange_server_time=tokyo,
            threshold_seconds=BAND,
        )
        row = _rows(test_database_url)[0]
        assert row[3].endswith("+00:00") and row[4].endswith("+00:00")
        assert "+09:00" not in row[3] and "+09:00" not in row[4]

    def test_a_halt_that_could_not_be_written_is_raised_not_shrugged(
        self, store: RiskClockSkewStore, test_database_url: str, monkeypatch
    ) -> None:
        # The row is the record of why trading stopped; a halt with
        # nothing on disk to account for it is indistinguishable from a
        # supervisor that died for an unrelated reason.  The store's own
        # *write* connection is what fails here -- the pre-read for the
        # probe has already succeeded, so this is exactly the "check
        # passed, insert failed" interleaving, and the refusal must come
        # from the module's own vocabulary.
        store.ensure_schema()
        real_connect = RiskClockSkewStore._connect
        calls = {"n": 0}

        def fail_the_write(self):
            calls["n"] += 1
            if calls["n"] > 1:  # the first call is the pre-read
                raise sqlite3.OperationalError("disk I/O error")
            return real_connect(self)

        monkeypatch.setattr(RiskClockSkewStore, "_connect", fail_the_write)
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
            )
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "could not be recorded" in str(refused.value)
        # The halt fired and the channel says so; only the record is
        # missing, which is what a retry over the same probe repairs.
        assert RiskKillSwitch(test_database_url).killed() is True
        monkeypatch.undo()
        retried = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert retried is not None and retried.sequence == 1
        assert _row_count(test_database_url) == 1

    def test_a_refused_insert_is_this_features_own_refusal(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # A tampered table can grow a constraint this store's own insert
        # then trips -- and a *bare* IntegrityError leaking out of a halt
        # would send an operator to the driver for a fault whose noun is
        # the measurement.
        store.ensure_schema()
        _edit(
            test_database_url,
            f"CREATE TRIGGER refuse_skew_rows BEFORE INSERT ON "
            f"{RISK_CLOCK_SKEW_TABLE} BEGIN SELECT RAISE(ABORT, 'no'); END",
        )
        with pytest.raises(RiskClockSkewError) as refused:
            store.halt_on_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
            )
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "could not be recorded" in str(refused.value)


class TestTheRetryLaw:
    def test_the_same_probe_measured_twice_is_one_row(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # A supervisor restarting after a crash re-measures the same probe
        # -- and re-filing it would report one clock fault as two halts.
        first = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        again = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert first is not None and again is not None
        assert again.sequence == first.sequence
        assert again.recorded_at == first.recorded_at
        assert _row_count(test_database_url) == 1

    def test_a_different_probe_is_a_different_row(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # Because it is a different measurement.
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=4),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert _row_count(test_database_url) == 2
        assert [row[0] for row in _rows(test_database_url)] == [1, 2]

    def test_the_same_probe_moments_apart_is_still_one_row(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # The key is the probe pair, not the moment of recording: the same
        # two readings recorded an hour later are the same measurement.
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=5.0,
        )
        assert _row_count(test_database_url) == 1

    def test_the_law_is_a_constraint_not_a_convention(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # A raw insert of the same probe pair -- a second writer that
        # knows nothing of this module -- is refused by the schema, so the
        # retry law holds against anything that can reach the table.
        store.ensure_schema()
        columns = (
            "measured_skew_seconds, threshold_seconds, exchange_server_time, "
            "local_time, halted_at, supervisor_process_id, recorded_at"
        )
        values = (
            3.0,
            BAND,
            _iso(PROBE),
            _iso(PROBE + timedelta(seconds=3)),
            _iso(LATER),
            "other/host",
            _iso(LATER),
        )
        _edit(
            test_database_url,
            f"INSERT INTO {RISK_CLOCK_SKEW_TABLE} ({columns}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _edit(
                test_database_url,
                f"INSERT INTO {RISK_CLOCK_SKEW_TABLE} ({columns}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def test_a_raced_insert_re_reads_the_winners_row(
        self, store: RiskClockSkewStore, test_database_url: str, monkeypatch
    ) -> None:
        # Another process records the same probe between this call's check
        # and its insert.  One probe is one measurement, so the other
        # process's row *is* this measurement's record: the loser re-reads
        # it rather than reporting a conflict where there is none.
        local = PROBE + timedelta(seconds=3)
        store.ensure_schema()
        _edit(
            test_database_url,
            f"INSERT INTO {RISK_CLOCK_SKEW_TABLE} (measured_skew_seconds, "
            "threshold_seconds, exchange_server_time, local_time, halted_at, "
            "supervisor_process_id, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                3.0,
                BAND,
                _iso(PROBE),
                _iso(local),
                _iso(LATER),
                "other/host",
                _iso(LATER),
            ),
        )
        # The check sees nothing -- simulating the race's interleaving --
        # and the insert then hits the UNIQUE pair, exactly as it would if
        # the other writer had committed a moment earlier.
        real_row_at = RiskClockSkewStore._row_at

        def raced(self, local, exchange, *, plain=False):
            return None if plain else real_row_at(self, local, exchange)

        monkeypatch.setattr(RiskClockSkewStore, "_row_at", raced)
        record = store.halt_on_skew(
            local_time=local,
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None
        assert record.supervisor_process_id == "other/host"
        assert record.sequence == 1
        assert _row_count(test_database_url) == 1


# -- The read ---------------------------------------------------------------------


class TestTheRead:
    def test_the_sweep_orders_by_the_probes_own_moment(
        self, store: RiskClockSkewStore
    ) -> None:
        # The two readings *are* the moment the halts happened, so the
        # sweep answers *when did the clocks disagree*, not *when did we
        # find out*.
        store.halt_on_skew(
            local_time=LATER + timedelta(seconds=3),
            exchange_server_time=LATER,
            threshold_seconds=BAND,
        )
        store.halt_on_skew(
            local_time=EARLIER + timedelta(seconds=3),
            exchange_server_time=EARLIER,
            threshold_seconds=BAND,
        )
        skews = store.skews()
        assert [record.local_time for record in skews] == [
            EARLIER + timedelta(seconds=3),
            LATER + timedelta(seconds=3),
        ]

    def test_same_instant_ties_break_by_the_tables_own_order(
        self, store: RiskClockSkewStore
    ) -> None:
        # Two different exchange readings at the same local instant: the
        # sequence is the only order they have.
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE - timedelta(seconds=1),
            threshold_seconds=BAND,
        )
        assert [record.sequence for record in store.skews()] == [1, 2]

    def test_the_anchor_is_inclusive(self, store: RiskClockSkewStore) -> None:
        # The workspace's window convention: an operator reconciling
        # "what has happened since the kill at T?" must not have the halt
        # at T excluded by a boundary they did not choose.
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        store.halt_on_skew(
            local_time=LATER + timedelta(seconds=3),
            exchange_server_time=LATER,
            threshold_seconds=BAND,
        )
        assert len(store.skews(since=PROBE + timedelta(seconds=3))) == 2
        assert len(store.skews(since=PROBE + timedelta(seconds=4))) == 1

    def test_the_anchor_must_state_a_moment(self, store: RiskClockSkewStore) -> None:
        with pytest.raises(RiskClockSkewError) as refused:
            store.skews(since=PROBE.replace(tzinfo=None))
        assert CLOCK_SKEW_CODE in str(refused.value)

    def test_an_empty_record_reads_as_an_empty_tuple(
        self, store: RiskClockSkewStore
    ) -> None:
        # A deployment whose clock is fine holds no rows, and the empty
        # answer is truthful rather than a clean bill of health -- which
        # is why the module-level spelling keeps it distinct from the
        # unconfigured case below.
        assert store.skews() == ()

    def test_a_record_reads_back_as_the_value_that_was_written(
        self, store: RiskClockSkewStore
    ) -> None:
        # The write path and the read path are judged by one rule, so a
        # record an operator reconciles against and the row the table
        # holds cannot be two things that disagree.
        written = store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        (read,) = store.skews()
        assert read == written

    def test_the_read_refuses_a_row_no_measurement_can_be(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # A skipped row is a halt an operator would never learn about.
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET local_time = ?",
            ("not a moment",),
        )
        with pytest.raises(RiskClockSkewError) as refused:
            store.skews()
        assert CLOCK_SKEW_CODE in str(refused.value)
        assert "not a moment" in str(refused.value)


# -- The value layer is the law, not the CHECK ------------------------------------


class TestTheRowIsJudgedOnTheWayBack:
    """Every stored-row defect fails to reconstruct rather than loading."""

    def _seed(self, database_url: str) -> None:
        """One well-formed halting measurement, then hand back for tampering."""
        RiskClockSkewStore(database_url).ensure_schema()
        _edit(
            database_url,
            f"INSERT INTO {RISK_CLOCK_SKEW_TABLE} (measured_skew_seconds, "
            "threshold_seconds, exchange_server_time, local_time, halted_at, "
            "supervisor_process_id, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                3.0,
                BAND,
                _iso(PROBE),
                _iso(PROBE + timedelta(seconds=3)),
                _iso(LATER),
                "host/1",
                _iso(LATER),
            ),
        )

    def test_the_seed_is_well_formed(self, test_database_url: str) -> None:
        # The control: the row this class tampers with reads back cleanly
        # before it is edited, so every refusal below is the tamper's and
        # not the seed's.
        self._seed(test_database_url)
        (record,) = RiskClockSkewStore(test_database_url).skews()
        assert record.measured_skew_seconds == 3.0

    def test_a_skew_that_disagrees_with_its_own_instants_is_refused(
        self, test_database_url: str
    ) -> None:
        # The two readings are the measurement and the number beside them
        # is their difference: a row where they disagree is one no halt
        # can be reconstructed as.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET measured_skew_seconds = 99.0",
        )
        with pytest.raises(RiskClockSkewError) as refused:
            RiskClockSkewStore(test_database_url).skews()
        assert "disagrees with its own instants" in str(refused.value)
        assert "clock skew record 1" in str(refused.value)

    def test_a_row_that_never_exceeded_its_own_band_is_refused(
        self, test_database_url: str
    ) -> None:
        # A probe inside the band is not a halt, and a row filed for one
        # reports a halt that never fired.  The edit below leaves the
        # arithmetic *self-consistent* -- the instants are moved with the
        # number -- so the only thing wrong with it is that it is not a
        # halting measurement, which is the judgement this asserts.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET measured_skew_seconds = 1.0, "
            "local_time = ?",
            (_iso(PROBE + timedelta(seconds=1)),),
            checks=False,
        )
        with pytest.raises(RiskClockSkewError) as refused:
            RiskClockSkewStore(test_database_url).skews()
        assert "does not exceed its threshold" in str(refused.value)

    @pytest.mark.parametrize("column", ["threshold_seconds", "measured_skew_seconds"])
    def test_a_non_numeric_value_is_refused(
        self, test_database_url: str, column: str
    ) -> None:
        # A numeric string is coerced by the column's REAL affinity, so
        # the tamper has to be one affinity cannot rescue: a word.  SQLite
        # stores it as-is (TEXT in a REAL column), and the value layer is
        # what refuses it.  The band is moved aside only when the skew
        # itself is the column being replaced, so the row stays
        # *arithmetically* consistent and the type is the only defect.
        self._seed(test_database_url)
        assignments = f"{column} = 'three'"
        if column != "threshold_seconds":
            assignments += ", threshold_seconds = 0.5"
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET {assignments}",
            checks=False,
        )
        with pytest.raises(RiskClockSkewError) as refused:
            RiskClockSkewStore(test_database_url).skews()
        assert CLOCK_SKEW_CODE in str(refused.value)

    def test_a_row_with_no_recording_process_is_refused(
        self, test_database_url: str
    ) -> None:
        # A halt nobody can attribute is the one thing this record cannot
        # leave an operator to guess at.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET supervisor_process_id = '  '",
        )
        with pytest.raises(RiskClockSkewError) as refused:
            RiskClockSkewStore(test_database_url).skews()
        assert CLOCK_SKEW_CODE in str(refused.value)

    def test_a_sequence_the_table_never_minted_is_refused(
        self, test_database_url: str
    ) -> None:
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET sequence = 0",
        )
        with pytest.raises(RiskClockSkewError) as refused:
            RiskClockSkewStore(test_database_url).skews()
        assert CLOCK_SKEW_CODE in str(refused.value)

    def test_the_refusal_names_the_row_to_repair(
        self, test_database_url: str
    ) -> None:
        # An operator gets the row rather than a complaint about a value
        # with no address.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_CLOCK_SKEW_TABLE} SET halted_at = 'whenever'",
        )
        with pytest.raises(RiskClockSkewError) as refused:
            RiskClockSkewStore(test_database_url).skews()
        message = str(refused.value)
        assert "whenever" in message
        assert "numbered 1" in message


# -- The module-level spellings ---------------------------------------------------


class TestTheModuleLevelSpellings:
    def test_a_halting_probe_records_through_the_named_store(
        self, test_database_url: str
    ) -> None:
        record = halt_on_clock_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
            database_url=test_database_url,
        )
        assert record is not None
        assert (measured_clock_skews(database_url=test_database_url)) == (record,)

    def test_the_environment_names_the_store_when_no_url_does(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, test_database_url)
        record = halt_on_clock_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert record is not None and record.sequence == 1

    def test_an_explicit_url_wins_over_the_environment(
        self, test_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'ignored.db'}")
        record = halt_on_clock_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
            database_url=test_database_url,
        )
        assert record is not None
        assert _row_count(test_database_url) == 1

    def test_a_probe_inside_the_band_needs_no_store(self) -> None:
        # Nothing halted, so there is nothing to account for: an
        # unconfigured deployment that merely polls is not an error.
        assert (
            halt_on_clock_skew(
                local_time=PROBE + timedelta(seconds=1),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
                env={},
            )
            is None
        )

    def test_a_halting_probe_with_no_store_is_refused_by_name(self) -> None:
        # From this moment trading must stop and nothing would record why:
        # an operator would be left a standing kill they cannot attribute
        # to a clock, which is the hole this feature exists to fill.
        with pytest.raises(RiskClockSkewError) as refused:
            halt_on_clock_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
                env={},
            )
        message = str(refused.value)
        assert message.startswith(CLOCK_SKEW_CODE)
        assert DATABASE_URL_ENV in message

    def test_a_blank_environment_value_counts_as_unset(self) -> None:
        # Absent is a discoverable deployment state, not an exception --
        # the stance every store in this workspace takes.
        with pytest.raises(RiskClockSkewError):
            halt_on_clock_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
                env={DATABASE_URL_ENV: "   "},
            )

    def test_the_band_is_judged_before_the_store_is_demanded(self) -> None:
        # A threshold of zero is a misconfiguration, not a halt: judging
        # it first is what keeps the no-store refusal about the *halt*.
        with pytest.raises(RiskClockSkewError) as refused:
            halt_on_clock_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=0,
                env={},
            )
        assert "greater than zero" in str(refused.value)

    def test_the_readers_absence_answers_the_empty_truth(self) -> None:
        # Recording refuses without a store, so a deployment that names
        # none holds no halting measurements and the empty answer is
        # truthful -- kept distinct because a caller that mistook an
        # unconfigured deployment for an empty record would read a table
        # with no halts in it and call it a clock that has never drifted.
        assert measured_clock_skews(env={}) == ()

    def test_the_readers_absence_is_not_the_recorders_refusal(self) -> None:
        # The asymmetry, in one test: the same absent store refuses a halt
        # and answers a read.
        with pytest.raises(RiskClockSkewError):
            halt_on_clock_skew(
                local_time=PROBE + timedelta(seconds=3),
                exchange_server_time=PROBE,
                threshold_seconds=BAND,
                env={},
            )
        assert measured_clock_skews(env={}) == ()

    def test_the_read_sweeps_the_named_store(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, test_database_url)
        halt_on_clock_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        halt_on_clock_skew(
            local_time=LATER + timedelta(seconds=3),
            exchange_server_time=LATER,
            threshold_seconds=BAND,
        )
        assert len(measured_clock_skews()) == 2
        assert len(measured_clock_skews(since=LATER)) == 1


class TestTheStoreConstruction:
    def test_an_empty_url_is_refused(self) -> None:
        with pytest.raises(RiskStoreError):
            RiskClockSkewStore("   ")

    def test_a_non_sqlite_url_is_an_address_fault_by_name(self) -> None:
        # Not this feature's own class: an address this member cannot
        # speak has an address repair, and a caller sent from a malformed
        # probe to a bad URL would edit the wrong file.
        store = RiskClockSkewStore("postgresql://host/db")
        with pytest.raises(RiskStoreError) as refused:
            store.ensure_schema()
        assert "postgresql" in str(refused.value)

    def test_an_in_memory_url_is_refused(self) -> None:
        # A measurement that vanished would leave a halt this feature
        # exists to account for with nothing on disk to account for it.
        with pytest.raises(RiskStoreError):
            RiskClockSkewStore("sqlite:///:memory:").ensure_schema()

    def test_resolve_names_the_store_or_none(self, test_database_url: str) -> None:
        assert RiskClockSkewStore.resolve(env={}) is None
        assert RiskClockSkewStore.resolve(env={DATABASE_URL_ENV: "  "}) is None
        resolved = RiskClockSkewStore.resolve(env={DATABASE_URL_ENV: test_database_url})
        assert resolved is not None
        assert resolved.database_url == test_database_url

    def test_construction_opens_nothing(self, tmp_path: Path) -> None:
        # Composing an application never touches the database, and a store
        # costs nothing until a halt is recorded or the table is read.
        database = tmp_path / "untouched.db"
        RiskClockSkewStore(f"sqlite:///{database}")
        assert not database.exists()

    def test_the_switch_is_composed_over_the_stores_own_url(
        self, test_database_url: str
    ) -> None:
        # The channel and the record are two tables in one database, which
        # is the only arrangement in which `halted_at` can be read off the
        # channel in the same breath as the row is written.
        store = RiskClockSkewStore(test_database_url)
        assert store.switch.database_url == test_database_url
        assert store.switch is store.switch

    def test_the_path_is_the_file_the_url_names(self, test_database_url: str) -> None:
        assert RiskClockSkewStore(test_database_url).path == Path(
            test_database_url.removeprefix("sqlite:///")
        )

    def test_the_table_and_the_channel_are_different_tables(
        self, store: RiskClockSkewStore, test_database_url: str
    ) -> None:
        # The channel is a *state* (one row, first-write-wins); this is a
        # *measurement* (two instants and the arithmetic between them).
        # Forcing either into the other's shape would break the law the
        # other exists to hold.
        assert RISK_CLOCK_SKEW_TABLE != RISK_ORDER_KILL_TABLE
        store.halt_on_skew(
            local_time=PROBE + timedelta(seconds=3),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert _row_count(test_database_url) == 1
        path = test_database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            (kills,) = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_ORDER_KILL_TABLE}"
            ).fetchone()
        assert kills == 1


# -- Two processes ----------------------------------------------------------------


class TestAcrossProcesses:
    def test_a_halt_another_supervisor_measured_is_one_this_process_reads(
        self, tmp_path: Path
    ) -> None:
        # The database, not any process's memory, is the coordination
        # point -- and §17 leaves no port to serve a socket on.  The
        # supervisor is an actual second interpreter.
        database = tmp_path / "cross-process.db"
        url = f"sqlite:///{database}"
        script = (
            "import sys;"
            "from datetime import UTC, datetime, timedelta;"
            "from risk.clock_skew import RiskClockSkewStore;"
            "from risk._identity import process_identity;"
            "probe = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC);"
            "record = RiskClockSkewStore(sys.argv[1]).halt_on_skew("
            "local_time=probe + timedelta(seconds=3),"
            "exchange_server_time=probe, threshold_seconds=2.0);"
            "print(record.sequence, record.measured_skew_seconds,"
            " record.supervisor_process_id == process_identity(),"
            " process_identity())"
        )
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "risk" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        sequence, measured, same_process, theirs = result.stdout.strip().split(" ", 3)
        assert sequence == "1" and measured == "3.0" and same_process == "True"

        (record,) = RiskClockSkewStore(url).skews()
        assert record.measured_skew_seconds == 3.0
        assert record.supervisor_process_id == theirs
        assert record.supervisor_process_id != process_identity()
        # Their halt stopped the order layer for this process too: the
        # channel and the record are two tables in one database.
        standing = RiskKillSwitch(url).standing()
        assert standing is not None
        assert record.halted_at == standing.sent_at

    def test_this_process_records_after_theirs_without_colliding(
        self, tmp_path: Path
    ) -> None:
        # A different probe is a different measurement, so the second
        # process appends rather than re-reading the first's row.
        database = tmp_path / "two-supervisors.db"
        url = f"sqlite:///{database}"
        script = (
            "import sys;"
            "from datetime import UTC, datetime, timedelta;"
            "from risk.clock_skew import RiskClockSkewStore;"
            "probe = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC);"
            "RiskClockSkewStore(sys.argv[1]).halt_on_skew("
            "local_time=probe + timedelta(seconds=3),"
            "exchange_server_time=probe, threshold_seconds=2.0)"
        )
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "risk" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        ours = RiskClockSkewStore(url).halt_on_skew(
            local_time=PROBE + timedelta(seconds=4),
            exchange_server_time=PROBE,
            threshold_seconds=BAND,
        )
        assert ours is not None and ours.sequence == 2
        assert _row_count(url) == 2
