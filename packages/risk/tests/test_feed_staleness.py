"""Feature 328: new orders refused on a stale feed, positions held.

The suite is organised around the sentence's three claims, because they
are the three things that can silently stop being true, plus the two
absences the feature's *shape* claims:

* **Rejects new orders.**  The refusal is a *live judgement* taken at the
  submission path — :meth:`RiskFeedStalenessGuard.require_fresh` and its
  module-level spelling :func:`require_feed_fresh` — not a state some
  other process set.  So the tests here are about a *call*: a stale feed
  raises, a fresh one answers, and the very next call re-judges from the
  socket rather than from a flag the last one left behind.  The tests that
  matter most are the ones that make the refusal lift by itself.
* **While holding positions.**  The clause is why this feature may not
  flatten, and the suite pins the *absence*: the module holds no engine
  face, exposes no verb of closure, and a refused submission leaves every
  other table in the member's store exactly as it was.  A test that only
  asserted "it raises" would pass just as well for a module that sold the
  book on the way out.
* **When the staleness exceeds the configured threshold.**  The comparison
  is strictly ``>`` and is pinned at equality rather than approximated: a
  feed silent for exactly the band is *inside* it — no refusal.  The band
  is configuration with no default, so the validation tests are the other
  half of this claim, and each of the four near-misses (``bool``,
  non-finite, non-positive, non-number) is refused by name rather than
  judged against.
* **Nothing is persisted.**  The module owns no table; a refusal writes
  nowhere, and — the stronger form — the whole feature works against a
  ``DATABASE_URL`` that names no database that could be opened at all.
  That test is the one that would fail for a guard that had quietly put a
  store write on the order path.
* **Nothing is killed.**  The refusal does not travel through feature
  322's monotone channel: a halting guard leaves the channel's table
  empty, so an operator who read the refusal as a kill and waited for a
  door to clear it would be waiting for a state that was never set.  The
  complementary half — that the refusal lifts when the feed recovers — is
  what makes the channel the wrong medium, and it is asserted directly.

The refusals are the last subject: a reading that is naive, not a moment,
or stamped ahead of the question; a band that is not a band; a source that
cannot say when the feed last spoke; and the two half-watchdog shapes.  Each
is named by the grep token its messages open with.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from risk.errors import (
    FEED_STALENESS_CODE,
    ORDERS_STALE_CODE,
    RiskError,
    RiskFeedStalenessError,
    RiskOrdersKilledError,
    RiskOrdersStaleError,
)
from risk.feed_staleness import (
    FALLBACK_FEED_READING_ATTRIBUTES,
    FeedStaleness,
    FeedStalenessGuard,
    RiskFeedStalenessGuard,
    measure_feed_staleness,
    orders_stale_error,
    read_feed_staleness,
    require_feed_fresh,
)
from risk.kill import RISK_ORDER_KILL_TABLE, RiskKillSwitch

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The instant the feed last spoke, and the instant the question is asked.
#: Fixed instants, so every assertion about a message or an age is exact.
LAST = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
NOW = LAST + timedelta(seconds=10)

#: A band the readings below sit unambiguously inside or outside of.
BAND = 5.0


def _iso(moment: datetime) -> str:
    """The module's own canonical spelling, for asserting on messages.

    Restated rather than imported from the module's private helper, so
    these tests measure the spelling a message carries rather than a copy
    of the function that composes it: if the canonical form changed, a
    test that imported it would change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _tables(database_url: str) -> set[str]:
    """Every table the member's store holds, read with the driver directly."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {name for (name,) in rows}


def _kills(database_url: str) -> int:
    """How many rows feature 322's channel holds — the monotone state."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_ORDER_KILL_TABLE}"
            ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return count


class _Subscriber:
    """A feed liveness source that answers the module's own question."""

    def __init__(self, last_message_at: datetime) -> None:
        self._last_message_at = last_message_at

    def read_feed_staleness(self) -> datetime:
        return self._last_message_at


class _Record:
    """A plain object wearing one of the duck-typed fallback names."""

    def __init__(self, last_tick_at: datetime) -> None:
        self.last_tick_at = last_tick_at


class _Nested:
    """A client wrapped in a session: the one-level-down shape."""

    def __init__(self, feed: object) -> None:
        self.feed = feed


# -- Measured ---------------------------------------------------------------------


class TestTheMeasurement:
    def test_a_feed_speaking_now_reads_zero(self) -> None:
        # The reading that is not a fault: the feed's last message is the
        # instant the question is asked.
        assert measure_feed_staleness(last_message_at=LAST, now=LAST) == 0.0

    def test_the_staleness_is_exactly_the_difference_of_the_two_readings(
        self,
    ) -> None:
        # The two readings *are* the measurement; the number is their
        # arithmetic and nothing else.  Fractional seconds included, so a
        # truncation anywhere in the path would show.
        assert (
            measure_feed_staleness(
                last_message_at=LAST,
                now=LAST + timedelta(seconds=2, microseconds=500_000),
            )
            == 2.5
        )

    def test_the_staleness_has_one_direction_and_is_never_negative(self) -> None:
        # No absolute value anywhere in the path: a duration has one
        # direction, and its other one is refused below rather than
        # measured as a magnitude.
        assert measure_feed_staleness(last_message_at=LAST, now=NOW) == 10.0

    def test_a_last_message_ahead_of_the_question_is_refused(self) -> None:
        # The ordering law.  The feed's last message stamped *after* the
        # instant that asked how long it had been silent is not a silence
        # at all -- the two ends disagree about what time it is -- and a
        # clamped zero would certify the quietest possible feed as safe by
        # passing every band there is.
        with pytest.raises(RiskFeedStalenessError) as refused:
            measure_feed_staleness(last_message_at=NOW + timedelta(seconds=1), now=NOW)
        message = str(refused.value)
        assert FEED_STALENESS_CODE in message
        assert "the feed's last message is stamped" in message
        assert _iso(NOW + timedelta(seconds=1)) in message
        assert "negative age" in message

    def test_a_reading_ahead_of_the_question_is_refused_at_exactly_one_microsecond(
        self,
    ) -> None:
        # The boundary pinned exactly: the refusal is on `< 0`, so a
        # difference of exactly zero is a measurement and the smallest
        # possible one the wrong way is not.
        assert measure_feed_staleness(last_message_at=NOW, now=NOW) == 0.0
        with pytest.raises(RiskFeedStalenessError):
            measure_feed_staleness(
                last_message_at=NOW + timedelta(microseconds=1), now=NOW
            )

    def test_the_measurement_never_reads_a_clock_of_its_own(self) -> None:
        # Feature 328's *measured* claim, and the reason the guard's `now`
        # is a required keyword with no default: a function that stamped
        # its own instant would not be reproducible from the two values a
        # later reader holds.  Called twice with the same pair, the same
        # number -- which a `datetime.now()` in the path would make
        # impossible at microsecond resolution.
        first = measure_feed_staleness(last_message_at=LAST, now=NOW)
        second = measure_feed_staleness(last_message_at=LAST, now=NOW)
        assert first == second == 10.0

    def test_two_zones_are_the_same_instant_compared_correctly(self) -> None:
        # A feed stamping in +09:00 and a host reading in +00:00 need no
        # normalisation here: both readings are aware, so the subtraction
        # is by their offsets.
        tokyo = LAST.astimezone(timezone(timedelta(hours=9)))
        assert measure_feed_staleness(last_message_at=tokyo, now=LAST) == 0.0
        assert (
            measure_feed_staleness(
                last_message_at=LAST, now=LAST + timedelta(seconds=4)
            )
            == 4.0
        )

    @pytest.mark.parametrize("what", ["last_message_at", "now"])
    def test_a_naive_reading_is_refused(self, what: str) -> None:
        # A staleness measured against a naive instant is a staleness
        # against no particular instant, and the refusal it caused could
        # not be ordered against anything -- the same discipline
        # kill.py holds `sent_at` to.
        readings = {"last_message_at": LAST, "now": NOW}
        readings[what] = LAST.replace(tzinfo=None)
        with pytest.raises(RiskFeedStalenessError) as refused:
            measure_feed_staleness(**readings)
        assert FEED_STALENESS_CODE in str(refused.value)
        assert what in str(refused.value)

    @pytest.mark.parametrize("what", ["last_message_at", "now"])
    def test_a_reading_that_is_not_a_moment_is_refused(self, what: str) -> None:
        readings = {"last_message_at": LAST, "now": NOW}
        readings[what] = "2026-09-25T12:00:00+00:00"
        with pytest.raises(RiskFeedStalenessError) as refused:
            measure_feed_staleness(**readings)
        assert FEED_STALENESS_CODE in str(refused.value)
        assert "not str" in str(refused.value)

    def test_the_refusal_is_the_members_own_class(self) -> None:
        # Every face of feature 328 is catchable by the base class, so a
        # supervisor wrapping its whole submission path catches them all.
        with pytest.raises(RiskError):
            measure_feed_staleness(last_message_at=LAST, now=None)


# -- The reading ------------------------------------------------------------------


class TestTheReading:
    def test_a_reading_carries_its_own_terms(self) -> None:
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        assert reading.last_message_at == LAST
        assert reading.observed_at == NOW
        assert reading.staleness_seconds == 10.0
        assert reading.threshold_seconds == BAND
        assert reading.exceeded is True

    def test_the_reading_is_frozen(self) -> None:
        # A reading is a value: the number a refusal rides on cannot be
        # edited after the fact by whoever is holding it.
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        with pytest.raises(FrozenInstanceError):
            reading.exceeded = False  # type: ignore[misc]

    def test_the_reading_carries_both_instants_beside_their_difference(
        self,
    ) -> None:
        # The pair is kept, not just the age, so a reader who trusts
        # neither the writer nor its subtraction can re-derive the number
        # -- the same testimony feature 329 keeps on its own row.
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        assert (
            reading.observed_at - reading.last_message_at
        ).total_seconds() == reading.staleness_seconds

    def test_the_summary_answers_how_long_since_when_and_against_what(
        self,
    ) -> None:
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        summary = reading.summary
        assert "10.000000s" in summary
        assert _iso(LAST) in summary
        assert _iso(NOW) in summary
        assert "exceeded" in summary
        assert "5.000000s" in summary

    def test_a_reading_inside_its_band_says_so_in_the_summary(self) -> None:
        # The two readings differ in one bit, and the summary is where an
        # operator sees which -- a verdict that only ever read "exceeded"
        # would make the gauge useless on the passing side.
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        inside = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=20.0,
            exceeded=False,
        )
        assert "exceeded" in reading.summary
        assert "within" in inside.summary

    def test_the_summary_is_composed_and_not_stored(self) -> None:
        # Every part of it is already a field; a stored copy would
        # disagree with an edited one, which is why the member's other
        # `summary` properties compose too.
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        assert reading.summary == reading.summary
        assert set(reading.__dataclass_fields__) == {
            "last_message_at",
            "observed_at",
            "staleness_seconds",
            "threshold_seconds",
            "exceeded",
        }

    def test_the_arithmetic_is_re_derived_not_trusted(self) -> None:
        # A hand-built reading whose number disagrees with its own two
        # instants would launder a stale feed into a fresh one at exactly
        # the point where the numbers are the only testimony.
        with pytest.raises(RiskFeedStalenessError) as refused:
            FeedStaleness(
                last_message_at=LAST,
                observed_at=NOW,
                staleness_seconds=99.0,
                threshold_seconds=BAND,
                exceeded=True,
            )
        assert FEED_STALENESS_CODE in str(refused.value)
        assert "disagrees with its own instants" in str(refused.value)

    def test_a_verdict_that_disagrees_with_the_arithmetic_is_refused(self) -> None:
        # The bit is *checked* rather than computed on read, so a reading
        # cannot become a different verdict by being read -- and a reading
        # that claimed `exceeded=False` under a band it broke would wave
        # through the very submission the feature exists to stop.
        with pytest.raises(RiskFeedStalenessError) as refused:
            FeedStaleness(
                last_message_at=LAST,
                observed_at=NOW,
                staleness_seconds=10.0,
                threshold_seconds=BAND,
                exceeded=False,
            )
        assert FEED_STALENESS_CODE in str(refused.value)
        assert "exceeded" in str(refused.value)

    def test_a_verdict_that_is_not_a_bool_is_refused(self) -> None:
        # `isinstance(1, bool)` is false but `1 == True` is true, so a
        # truthy-looking non-bool would compare equal to a verdict while
        # being a different fact.
        with pytest.raises(RiskFeedStalenessError) as refused:
            FeedStaleness(
                last_message_at=LAST,
                observed_at=NOW,
                staleness_seconds=10.0,
                threshold_seconds=BAND,
                exceeded=1,  # type: ignore[arg-type]
            )
        assert "must be a bool" in str(refused.value)

    def test_a_negative_age_is_refused_even_when_its_instants_agree(self) -> None:
        #  the instants must agree *and* the number must be a duration;
        # a reading cannot buy a negative silence by being internally
        # consistent about it.
        with pytest.raises(RiskFeedStalenessError) as refused:
            FeedStaleness(
                last_message_at=NOW,
                observed_at=LAST,
                staleness_seconds=-10.0,
                threshold_seconds=BAND,
                exceeded=False,
            )
        assert "non-negative" in str(refused.value)

    def test_the_reading_judges_its_own_band(self) -> None:
        # A reading carrying a band that is not a band is refused here as
        # well as at the guard, because a reading is constructible by
        # anybody -- and a reading judged against nothing is the shape a
        # fabricated verdict rides in on.
        with pytest.raises(RiskFeedStalenessError):
            FeedStaleness(
                last_message_at=LAST,
                observed_at=NOW,
                staleness_seconds=10.0,
                threshold_seconds=0.0,
                exceeded=True,
            )

    def test_the_reading_carries_the_band_it_was_judged_against(self) -> None:
        # Carried, not looked up: a later retune of the band cannot
        # re-judge a refusal already taken.
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        assert reading.threshold_seconds == BAND


# -- When the staleness exceeded the threshold ------------------------------------


class TestTheThresholdBoundary:
    def test_staleness_exactly_at_the_threshold_is_inside_the_band(self) -> None:
        # §13.3's trigger is `>`, strictly, so a feed silent for exactly
        # the band is not this feature's business -- the boundary pinned
        # exactly rather than approximated, and the reading says so.
        guard = RiskFeedStalenessGuard(BAND)
        reading = guard.require_fresh(
            now=LAST + timedelta(seconds=BAND), last_message_at=LAST
        )
        assert reading.exceeded is False
        assert reading.staleness_seconds == BAND

    def test_a_microsecond_past_the_threshold_is_outside_it(self) -> None:
        # The other side of the same boundary: the comparison is `>`, so
        # the smallest possible step past the band refuses.
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError):
            guard.require_fresh(
                now=LAST + timedelta(seconds=BAND, microseconds=1),
                last_message_at=LAST,
            )

    def test_a_stale_feed_refuses(self) -> None:
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError) as refused:
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        assert ORDERS_STALE_CODE in str(refused.value)

    def test_a_fresh_feed_answers_with_its_reading(self) -> None:
        # The passing half is not `None`: the caller that wants to log the
        # gauge has the number it was judged on.
        guard = RiskFeedStalenessGuard(BAND)
        reading = guard.require_fresh(
            now=LAST + timedelta(seconds=1), last_message_at=LAST
        )
        assert isinstance(reading, FeedStaleness)
        assert reading.staleness_seconds == 1.0
        assert reading.exceeded is False

    def test_a_band_of_zero_is_refused(self) -> None:
        # Every silence other than exactly zero exceeds a non-positive
        # band, so a deployment that passed one configured a refusal
        # rather than a tolerance.  §13.3 says *threshold* and names no
        # number, but it does not name *any* number.
        with pytest.raises(RiskFeedStalenessError) as refused:
            RiskFeedStalenessGuard(0.0)
        assert FEED_STALENESS_CODE in str(refused.value)
        assert "greater than zero" in str(refused.value)

    def test_a_negative_band_is_refused(self) -> None:
        with pytest.raises(RiskFeedStalenessError):
            RiskFeedStalenessGuard(-1.0)

    @pytest.mark.parametrize("band", [True, False])
    def test_a_bool_band_is_refused(self, band: bool) -> None:
        # `isinstance(True, int)` is true in Python, so a naive numeric
        # check would pass a band of one second -- a watchdog nobody
        # configured, refusing submissions on a silence of two.
        with pytest.raises(RiskFeedStalenessError) as refused:
            RiskFeedStalenessGuard(band)
        assert "bool" in str(refused.value)

    @pytest.mark.parametrize("band", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_band_is_refused(self, band: float) -> None:
        # `nan` compares false against everything, so a `nan` band would
        # answer "inside the band" for a silence of any length -- the one
        # direction a watchdog must never fail in.
        with pytest.raises(RiskFeedStalenessError) as refused:
            RiskFeedStalenessGuard(band)
        assert "finite" in str(refused.value)

    @pytest.mark.parametrize("band", ["5", None, object()])
    def test_a_band_that_is_not_a_number_is_refused(self, band: object) -> None:
        with pytest.raises(RiskFeedStalenessError) as refused:
            RiskFeedStalenessGuard(band)  # type: ignore[arg-type]
        assert FEED_STALENESS_CODE in str(refused.value)

    def test_the_band_has_no_default(self) -> None:
        # §13.3 says "the configured threshold", so a guard that guessed a
        # band would refuse submissions on a silence nobody configured it
        # to refuse on -- construction without one is a TypeError, not a
        # default.
        with pytest.raises(TypeError):
            RiskFeedStalenessGuard()  # type: ignore[call-arg]

    def test_the_band_is_judged_at_construction_rather_than_at_the_call(
        self,
    ) -> None:
        # An order path that discovered its band was not a band at its
        # first submission would have refused or traded on a number nobody
        # could evaluate; the refusal is here, where the guard is built.
        with pytest.raises(RiskFeedStalenessError):
            RiskFeedStalenessGuard("5")  # type: ignore[arg-type]

    def test_the_guard_carries_its_band(self) -> None:
        guard = RiskFeedStalenessGuard(BAND)
        assert guard.threshold_seconds == BAND

    def test_the_band_survives_on_every_reading_it_judges(self) -> None:
        guard = RiskFeedStalenessGuard(BAND)
        reading = guard.require_fresh(
            now=LAST + timedelta(seconds=1), last_message_at=LAST
        )
        assert reading.threshold_seconds == guard.threshold_seconds


# -- The source -------------------------------------------------------------------


class TestTheSource:
    def test_a_source_answering_the_method_is_read(self) -> None:
        assert read_feed_staleness(_Subscriber(LAST)) == LAST

    def test_a_source_wearing_a_fallback_attribute_is_read(self) -> None:
        # The plain shape a subscriber or a heartbeat record most often
        # wears.  Nothing here imports the ingest member: the last-message
        # instant is *handed in* by whoever holds the subscription.
        assert read_feed_staleness(_Record(LAST)) == LAST

    def test_a_source_is_looked_through_one_level_down(self) -> None:
        # A client wrapped in a session: the nesting is one level deep
        # and no further, so *which object did this reading come from?*
        # stays answerable.
        assert read_feed_staleness(_Nested(_Record(LAST))) == LAST
        assert read_feed_staleness(_Nested(_Subscriber(LAST))) == LAST

    def test_the_method_wins_over_a_fallback_attribute(self) -> None:
        # A source that answers the question itself has answered it, and
        # its answer is by construction the one it meant to give.
        other = LAST + timedelta(seconds=30)
        source = _Subscriber(LAST)
        source.last_message_at = other  # type: ignore[attr-defined]
        assert read_feed_staleness(source) == LAST

    def test_a_source_is_asked_before_anything_it_holds(self) -> None:
        # Nearest wins: a wrapper answering for itself has answered, and
        # reaching through it to a nested object would be asking a
        # different object the question the caller aimed at this one.
        near = LAST + timedelta(seconds=30)
        wrapper = _Nested(_Record(LAST))
        wrapper.last_seen_at = near  # type: ignore[attr-defined]
        assert read_feed_staleness(wrapper) == near

    def test_at_a_level_a_method_beats_a_fallback_attribute(self) -> None:
        # The second half of the order, pinned on a nested object, since
        # the top-level case is the test above.
        class _Both:
            def read_feed_staleness(self) -> datetime:
                return LAST

            last_tick_at = LAST + timedelta(seconds=30)

        assert read_feed_staleness(_Both()) == LAST
        assert read_feed_staleness(_Nested(_Both())) == LAST

    def test_a_callable_reading_is_called(self) -> None:
        # A source exposing `last_message_at` as a *method* is the same
        # fact in a different spelling.
        class _Method:
            def last_message_at(self) -> datetime:
                return LAST

        assert read_feed_staleness(_Method()) == LAST

    def test_a_source_carrying_no_reading_is_refused_by_name(self) -> None:
        # A source that cannot say when the feed last spoke is not a
        # source, and a guard that silently answered "fresh" for it would
        # be the one failure this feature exists to prevent.
        with pytest.raises(RiskFeedStalenessError) as refused:
            read_feed_staleness(object())
        message = str(refused.value)
        assert FEED_STALENESS_CODE in message
        assert "read_feed_staleness" in message
        assert all(name in message for name in FALLBACK_FEED_READING_ATTRIBUTES)

    def test_a_nested_source_carrying_no_reading_is_refused_by_name(self) -> None:
        # The refusal reaches through the nesting too, so a wrapper around
        # nothing is refused rather than mistaken for a wrapper around a
        # reading.
        with pytest.raises(RiskFeedStalenessError):
            read_feed_staleness(_Nested(object()))

    def test_a_sources_reading_is_still_required_to_be_aware(self) -> None:
        # The duck-typed seam does not launder a naive instant: what comes
        # out of a source is held to the same terms as what is passed in.
        with pytest.raises(RiskFeedStalenessError):
            read_feed_staleness(_Record(LAST.replace(tzinfo=None)))

    def test_the_guard_reads_the_source_it_holds(self) -> None:
        guard = RiskFeedStalenessGuard(BAND, source=_Subscriber(LAST))
        reading = guard.read(now=LAST + timedelta(seconds=10))
        assert reading.last_message_at == LAST
        assert reading.staleness_seconds == 10.0
        assert reading.exceeded is True

    def test_the_guard_carries_the_source_it_was_built_with(self) -> None:
        subscriber = _Subscriber(LAST)
        assert RiskFeedStalenessGuard(BAND, source=subscriber).source is subscriber

    def test_a_guard_with_no_source_carries_none(self) -> None:
        # Not a fault: a caller that passes `last_message_at` to each call
        # needs no source at all.
        assert RiskFeedStalenessGuard(BAND).source is None

    def test_a_guard_with_a_band_and_nothing_to_read_is_refused_by_name(
        self,
    ) -> None:
        # A watchdog with a band and nothing to read cannot see the feed.
        # Refused rather than answered "fresh", because answering would be
        # inventing a last message nobody supplied.
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskFeedStalenessError) as refused:
            guard.require_fresh(now=NOW)
        message = str(refused.value)
        assert FEED_STALENESS_CODE in message
        assert "holds no feed staleness source" in message

    def test_the_call_supplied_reading_overrides_the_source(self) -> None:
        # The escape hatch a caller with a deeper structure than
        # `read_feed_staleness` reaches uses, and the one a replay of a
        # recorded session needs.
        guard = RiskFeedStalenessGuard(BAND, source=_Subscriber(LAST))
        other = LAST - timedelta(seconds=100)
        reading = guard.read(now=LAST, last_message_at=other)
        assert reading.last_message_at == other
        assert reading.staleness_seconds == 100.0


# -- Rejects new orders -----------------------------------------------------------


class TestTheRefusal:
    def test_a_stale_feed_refuses_through_the_guard(self) -> None:
        guard = RiskFeedStalenessGuard(BAND, source=_Subscriber(LAST))
        with pytest.raises(RiskOrdersStaleError) as refused:
            guard.require_fresh(now=LAST + timedelta(seconds=60))
        assert ORDERS_STALE_CODE in str(refused.value)

    def test_the_refusal_carries_the_reading_it_was_taken_from(self) -> None:
        # The caller that reaches for an order learns *how long* the feed
        # has been quiet, *since when* and *against what band*, without a
        # second query -- and the reading it holds is the same object the
        # message was composed from, not a copy that could disagree.
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError) as refused:
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        reading = refused.value.staleness
        assert isinstance(reading, FeedStaleness)
        assert reading.staleness_seconds == 60.0
        assert reading.threshold_seconds == BAND
        assert reading.exceeded is True

    def test_the_refusal_names_the_cause_and_what_is_left_standing(self) -> None:
        # The message is the operator's whole instruction: what happened,
        # what is refused, what is *not* touched, and what clears it.
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError) as refused:
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        message = str(refused.value)
        assert "60.000000s" in message
        assert _iso(LAST) in message
        assert "halt new orders, hold positions" in message
        assert "lifts by itself" in message

    def test_the_refusal_is_a_sibling_of_the_killed_receipt(self) -> None:
        # Not a child: the kill is a state that stands until a door resets
        # it, the staleness is a live reading that stops being true by
        # itself.  Two facts, two classes, one base to catch both.
        assert not issubclass(RiskOrdersStaleError, RiskOrdersKilledError)
        assert not issubclass(RiskOrdersKilledError, RiskOrdersStaleError)
        assert issubclass(RiskOrdersStaleError, RiskError)

    def test_the_refusal_is_catchable_by_the_base_class(self) -> None:
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskError):
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)

    def test_the_refusal_is_composed_by_one_function(self) -> None:
        # One spelling for the message, so the log line an operator reads
        # and the reading the guard took say the same thing.
        reading = FeedStaleness(
            last_message_at=LAST,
            observed_at=NOW,
            staleness_seconds=10.0,
            threshold_seconds=BAND,
            exceeded=True,
        )
        error = orders_stale_error(reading)
        assert isinstance(error, RiskOrdersStaleError)
        assert error.staleness is reading
        assert reading.summary in str(error)

    def test_the_refusal_builder_refuses_anything_but_a_reading(self) -> None:
        # An error built from anything else would be a refusal with no
        # measurement behind it.
        with pytest.raises(RiskFeedStalenessError) as refused:
            orders_stale_error("stale")  # type: ignore[arg-type]
        assert FEED_STALENESS_CODE in str(refused.value)

    def test_the_refusal_lifts_by_itself_when_the_feed_speaks_again(
        self,
    ) -> None:
        # The whole difference from the kill channel, asserted directly:
        # the same guard, one call later, answers because the socket said
        # something -- no door, no reset, no operator.  A guard that
        # memoised its last reading would refuse here forever.
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError):
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        reading = guard.require_fresh(
            now=LAST + timedelta(seconds=61),
            last_message_at=LAST + timedelta(seconds=60),
        )
        assert reading.exceeded is False

    def test_the_guard_holds_no_memo_of_a_staleness_it_once_saw(self) -> None:
        # The state that would make the refusal stick, asserted against
        # the guard's own surface: nothing but the band and the source.
        guard = RiskFeedStalenessGuard(BAND, source=_Subscriber(LAST))
        with pytest.raises(RiskOrdersStaleError):
            guard.require_fresh(now=LAST + timedelta(seconds=60))
        assert set(vars(guard)) == {"_threshold_seconds", "_source"}

    def test_the_read_face_measures_without_refusing(self) -> None:
        # So that the number a caller wants -- a dashboard tile, a log
        # line, feature 350's `feed_staleness_s` row -- can be had without
        # a refusal, and so the reading a refusal rides on is the same one
        # rather than a second taken a moment later.
        guard = RiskFeedStalenessGuard(BAND)
        reading = guard.read(now=LAST + timedelta(seconds=600), last_message_at=LAST)
        assert reading.exceeded is True


# -- While holding positions ------------------------------------------------------


class TestTheBookIsLeftStanding:
    def test_the_module_exposes_no_verb_of_closure(self) -> None:
        # The sentence's own clause is why this feature may not flatten,
        # and the absence is the assertion: §13.3's row above this one --
        # daily loss -- owns *flatten, halt until manual reset*, and the
        # feature that sells a book into a feed that cannot price it has
        # skipped a row of the trigger table.
        import risk.feed_staleness as module

        forbidden = ("flatten", "close", "cancel", "liquidate")
        public = {name for name in module.__all__}
        for name in public:
            assert not any(word in name.lower() for word in forbidden), name

    def test_the_guard_holds_no_engine_face(self) -> None:
        # No composition can supply a supervisor's hold on the execution
        # engine, and this feature never wanted one: nothing here closes a
        # position, cancels an order or reads an engine.
        guard = RiskFeedStalenessGuard(BAND, source=_Subscriber(LAST))
        assert set(vars(guard)) == {"_threshold_seconds", "_source"}

    def test_the_refusal_writes_no_row_anywhere_in_the_members_store(
        self, test_database_url: str
    ) -> None:
        # Retention of measured staleness is feature 350's row in the
        # `ops` member; this module measures and judges, and writes
        # nothing.  A guard that persisted a row per submission would put
        # a store write on the hot path of every order.
        before = _tables(test_database_url)
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError):
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        assert _tables(test_database_url) == before

    def test_the_refusal_sends_no_kill(self, test_database_url: str) -> None:
        # The refusal must not travel through feature 322's monotone
        # channel: an operator who read this as a kill would wait for a
        # door to clear a state that was never set.
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError):
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        assert _kills(test_database_url) == 0
        assert RiskKillSwitch(test_database_url).standing() is None

    def test_the_whole_feature_works_with_no_database_at_all(
        self, tmp_path: Path
    ) -> None:
        # The strongest form of the absence: a `DATABASE_URL` naming a
        # directory that is not a database cannot be opened, and the
        # feature does not notice -- measure, judge, refuse, all of it.
        # A guard that had quietly put a store write on the order path
        # fails here and nowhere else.
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}"
        guard = RiskFeedStalenessGuard(BAND)
        with pytest.raises(RiskOrdersStaleError):
            guard.require_fresh(now=LAST + timedelta(seconds=60), last_message_at=LAST)
        reading = guard.require_fresh(
            now=LAST + timedelta(seconds=1), last_message_at=LAST
        )
        assert reading.exceeded is False

    def test_the_module_names_no_table_of_its_own(self) -> None:
        # This member's modules that own a table name it in a `RISK_*_TABLE`
        # constant.  This one does not, and the absence is the design
        # rather than an omission -- asserted so a later feature cannot add
        # one here without the suite noticing what it changed.
        import risk.feed_staleness as module

        assert not [name for name in dir(module) if name.endswith("_TABLE")]

    def test_the_module_reads_no_store_at_all(self) -> None:
        # This member's other modules each restate `DATABASE_URL` and open
        # a connection with it.  This one does neither, and the absence is
        # the design: the judgement is a pure function of the feed's
        # liveness and the band, so a `DATABASE_URL` that names nothing
        # openable cannot affect it -- asserted against the source rather
        # than the behaviour, because the behaviour would survive a store
        # read that happened to be swallowed.
        import risk.feed_staleness as module

        source = Path(module.__file__).read_text()
        assert "DATABASE_URL" not in source
        assert "os.environ" not in source
        assert "sqlite3" not in source


# -- The module-level spelling ----------------------------------------------------


class TestTheModuleLevelSpelling:
    def test_a_stale_feed_refuses_at_the_one_call(self) -> None:
        with pytest.raises(RiskOrdersStaleError) as refused:
            require_feed_fresh(
                now=LAST + timedelta(seconds=60),
                threshold_seconds=BAND,
                last_message_at=LAST,
            )
        assert ORDERS_STALE_CODE in str(refused.value)

    def test_a_fresh_feed_answers_with_its_reading(self) -> None:
        reading = require_feed_fresh(
            now=LAST + timedelta(seconds=1),
            threshold_seconds=BAND,
            last_message_at=LAST,
        )
        assert reading is not None
        assert reading.exceeded is False

    def test_a_source_can_be_handed_instead_of_a_reading(self) -> None:
        with pytest.raises(RiskOrdersStaleError):
            require_feed_fresh(
                now=LAST + timedelta(seconds=60),
                threshold_seconds=BAND,
                source=_Subscriber(LAST),
            )

    def test_a_deployment_with_no_watchdog_passes_vacuously(self) -> None:
        # No band and nothing to read is a deployment with no watchdog
        # wired into its order path -- the same "no store, no status"
        # stance `require_orders_allowed` takes on an unconfigured channel.
        assert require_feed_fresh(now=NOW) is None

    def test_an_unwatched_feed_is_not_a_fresh_feed(self) -> None:
        # The answer is `None` rather than a fabricated zero reading,
        # deliberately: a caller that mistook an unwatched feed for a
        # fresh one would trade believing a watchdog had been running --
        # so the reading's absence has to be visible in the return value.
        passed = require_feed_fresh(now=NOW)
        assert passed is None
        assert not isinstance(passed, FeedStaleness)

    def test_a_reading_with_no_band_is_refused_by_name(self) -> None:
        # Half a watchdog: a caller that believes it is watched.  Judging
        # against nothing would leave the submissions it believes are
        # guarded entirely unguarded.
        with pytest.raises(RiskFeedStalenessError) as refused:
            require_feed_fresh(now=NOW, last_message_at=LAST)
        message = str(refused.value)
        assert FEED_STALENESS_CODE in message
        assert "no threshold_seconds" in message

    def test_a_source_with_no_band_is_refused_by_name(self) -> None:
        with pytest.raises(RiskFeedStalenessError) as refused:
            require_feed_fresh(now=NOW, source=_Subscriber(LAST))
        assert "no threshold_seconds" in str(refused.value)

    def test_a_band_with_nothing_to_read_is_refused_by_name(self) -> None:
        # The other half of the same shape, refused rather than answered
        # "fresh" from a last message this function invented.
        with pytest.raises(RiskFeedStalenessError) as refused:
            require_feed_fresh(now=NOW, threshold_seconds=BAND)
        message = str(refused.value)
        assert FEED_STALENESS_CODE in message
        assert "nothing to judge" in message

    def test_the_band_is_validated_at_the_one_call_too(self) -> None:
        # The module-level spelling does not bypass the value layer: a
        # band that is not a band is refused here as well.
        with pytest.raises(RiskFeedStalenessError):
            require_feed_fresh(now=NOW, threshold_seconds=0.0, last_message_at=LAST)

    def test_now_is_required_and_never_defaulted(self) -> None:
        # This module reads no clock to measure a staleness, so a caller
        # always states the instant it judged at -- and a refusal is
        # always orderable against it.
        with pytest.raises(TypeError):
            require_feed_fresh(threshold_seconds=BAND, last_message_at=LAST)  # type: ignore[call-arg]


# -- The guard's own surface ------------------------------------------------------


class TestTheGuardConstruction:
    def test_the_two_spellings_are_one_class(self) -> None:
        # `isinstance` has to agree across both names, which a subclass
        # alias would break.
        assert FeedStalenessGuard is RiskFeedStalenessGuard
        assert isinstance(RiskFeedStalenessGuard(BAND), FeedStalenessGuard)

    def test_the_guard_takes_the_band_positionally_and_the_source_by_keyword(
        self,
    ) -> None:
        subscriber = _Subscriber(LAST)
        assert RiskFeedStalenessGuard(BAND, source=subscriber).source is subscriber

    def test_the_guard_is_a_plain_object_with_no_component_registration(
        self,
    ) -> None:
        # Feature 328 registers nothing with the application factory: the
        # judgement is the order path's own act on its own submission
        # path, and it must be constructible in one line by the process
        # about to submit -- a process that must not be required to have
        # composed anything.
        import risk.feed_staleness as module

        assert not [name for name in dir(module) if name.startswith("build_")]
        assert "register" not in dir(module)


# -- Across processes -------------------------------------------------------------


class TestAcrossProcesses:
    def test_another_processes_refusal_is_this_processes_refusal(
        self, tmp_path: Path
    ) -> None:
        # Feature 328 needs no shared medium -- there is no table and no
        # channel between the two processes -- and that is the assertion.
        # Two interpreters, the same two readings, the same verdict,
        # nothing written anywhere: the judgement is a pure function of
        # the feed's liveness and the band, so any process holding those
        # reaches it alone.
        database = tmp_path / "unused.db"
        url = f"sqlite:///{database}"
        script = textwrap.dedent(
            """
            import sys
            from datetime import UTC, datetime, timedelta
            from risk.errors import ORDERS_STALE_CODE, RiskOrdersStaleError
            from risk.feed_staleness import require_feed_fresh
            last = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
            now = last + timedelta(seconds=60)
            try:
                require_feed_fresh(
                    now=now, threshold_seconds=5.0, last_message_at=last
                )
            except RiskOrdersStaleError as refused:
                print(
                    ORDERS_STALE_CODE in str(refused),
                    refused.staleness.staleness_seconds,
                )
            else:
                print("passed")
            """
        )
        env = {
            **os.environ,
            "DATABASE_URL": url,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "risk" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "True 60.0"
        # Nothing was written by the other process, and nothing is written
        # by this one: the whole exchange happened in the argument list.
        # The database file does not exist -- checked *before* any helper
        # connects, because a `sqlite3.connect` would create it.
        assert not database.exists()
        with pytest.raises(RiskOrdersStaleError):
            require_feed_fresh(
                now=LAST + timedelta(seconds=60),
                threshold_seconds=BAND,
                last_message_at=LAST,
            )
        assert not database.exists()
        assert _kills(url) == 0
