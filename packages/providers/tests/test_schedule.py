"""Feature 202: scheduling depth campaigns outside the peak pricing window.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 202: *System
schedules depth campaigns outside a configured peak pricing window,
persisting the chosen window with each run.*  The lever is architecture
§14.2's second of its *"two free levers worth ~50%"* — *"DeepSeek prices by
time of day — peak is 01:00–04:00 and 06:00–10:00 UTC, off-peak is 50%
lower. Schedule campaigns outside those windows."* — and the tests below
hold each half of the sentence to its word: the **choice** half asks
whether the arithmetic really waits out the peak and refuses a run that
cannot fit; the **persistence** half asks whether the chosen window —
and the card it was chosen against — lands in a row with the run.

The suite's fixture card is §14.2's own (01:00–04:00 and 06:00–10:00
UTC), whose off-peak day is a two-hour gap at 04:00–06:00 and a
fifteen-hour one at 10:00–01:00 — two gaps of very different sizes,
which is what makes it a good card to test a scheduler on: the earliest
fitting gap is not always the first gap met, and only a card like this
can tell the two behaviours apart.  It is test data, not a default the
module carries; §14.2's own preamble (*"rates move monthly … the numbers
are not"*) is why the module holds the arithmetic and never the windows.

Every scheduling instant in the suite is fixed and stated (a Wednesday
in September 2026), never ``now()`` — a scheduler's output is a function
of its inputs, and a test that read the clock would be testing a
different question every time it ran.  The ``now`` argument exists for
exactly this: the deployment supplies the moment, the suite supplies a
known one, and the same arithmetic answers both.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from conftest import sqlite_path_of
from providers import (
    CAMPAIGN_TABLE,
    DEPTH_RUN_WINDOW_TABLE,
    DepthRunWindows,
    DepthScheduleError,
    NoOffPeakWindowError,
    PeakPricing,
    PeakWindow,
    RunWindow,
    RunWindowConflictError,
    ScheduledRun,
    UnknownCampaignError,
    choose_run_window,
    schedule_depth_run,
)

#: The Wednesday every fixed instant in this suite lands on — 2026-09-23,
#: the month §14.2's own verification date (2026-09-19) sits in, so a
#: suite's dates read like the deployment's.
WEDNESDAY = 23

#: The aware UTC instant builder: ``_at(2, 30)`` is Wednesday 02:30 UTC.
#: Every instant in the suite is UTC-aware because the chooser refuses
#: naive ones — the suite is not in the business of testing what the
#: module refuses before it begins.


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, WEDNESDAY, hour, minute, second, tzinfo=UTC)


#: A Thursday instant, for the answers that cross midnight.
def _thursday(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, WEDNESDAY + 1, hour, minute, tzinfo=UTC)


#: A Friday instant, for the answers that cross two of them.
def _friday(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, WEDNESDAY + 2, hour, minute, tzinfo=UTC)


#: The spine's ISO-8601 UTC text shape — millisecond precision, ``Z``
#: (``0111``'s own ``strftime`` form), which the row's three instant
#: columns all carry.
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ── The configuration ─────────────────────────────────────────────────────────


class TestPeakWindow:
    """The configuration's unit: one daily UTC time-of-day interval."""

    def test_accepts_the_card_the_document_states(self):
        # §14.2's two windows, spelled as the record expects them: whole
        # hours, naive, UTC by definition.  Constructing them is not the
        # gate — a window is a description, and describing a card is not
        # scheduling against it (the same split a 262K DepthModel enjoys).
        early = PeakWindow(start=time(1, 0), end=time(4, 0))
        late = PeakWindow(start=time(6, 0), end=time(10, 0))
        assert early.minutes == 3 * 60
        assert late.minutes == 4 * 60
        assert early.text() == "01:00-04:00"
        assert late.text() == "06:00-10:00"

    def test_a_window_may_cross_midnight(self):
        # The card whose peak wraps midnight — 22:00–02:00 — is one window
        # spelled exactly that way, not two synthetic ones: the card states
        # one peak and the configuration says what the card says.  Its
        # length is the complement of the same-day difference.
        wrap = PeakWindow(start=time(22, 0), end=time(2, 0))
        assert wrap.minutes == 4 * 60

    @pytest.mark.parametrize("field", ["start", "end"])
    def test_refuses_an_end_that_is_not_a_time_of_day(self, field):
        # Config noise — a string off a YAML file, a bare count — is
        # refused rather than guessed at: a window nobody described cannot
        # be waited out.
        kwargs = {"start": time(1, 0), "end": time(4, 0)}
        kwargs[field] = "01:00"
        with pytest.raises(DepthScheduleError, match=field):
            PeakWindow(**kwargs)

    @pytest.mark.parametrize("field", ["start", "end"])
    def test_refuses_a_zoned_time_of_day(self, field):
        # A time of day carrying a zone names no instant, and offsetting it
        # would schedule against a window the card never stated.
        zoned = time(1, 0, tzinfo=UTC)
        kwargs = {"start": time(1, 0), "end": time(4, 0)}
        kwargs[field] = zoned
        with pytest.raises(DepthScheduleError, match="naive UTC"):
            PeakWindow(**kwargs)

    @pytest.mark.parametrize("field", ["start", "end"])
    def test_refuses_second_granularity(self, field):
        # Pricing windows are minute-granular; a time carrying seconds
        # would be silently truncated by the minute arithmetic, which is a
        # window the caller described and the scheduler refused to honour.
        kwargs = {"start": time(1, 0), "end": time(4, 0)}
        kwargs[field] = time(1, 0, 30)
        with pytest.raises(DepthScheduleError, match="minute-granular"):
            PeakWindow(**kwargs)

    def test_refuses_coincident_ends(self):
        # A zero-length window prices nothing — and is one keystroke from
        # the window that means the whole day, so it is refused as
        # ambiguous rather than interpreted as flat.
        with pytest.raises(DepthScheduleError, match="must not coincide"):
            PeakWindow(start=time(1, 0), end=time(1, 0))


class TestPeakPricing:
    """The configuration: the card's windows, as one frozen value."""

    def test_empty_is_the_flat_by_time_of_day_card(self):
        # A provider with no peak/off-peak split never enters peak, and
        # that is a stated configuration — the positive fact flat_pricing()
        # names for surcharge-free cards — not a missing one.
        card = PeakPricing()
        assert card.windows == ()
        assert card.flat_by_time_of_day is True
        assert card.text() == ""

    def test_accepts_any_iterable_and_answers_one_tuple(self):
        # A config file's list is as good as a tuple, and a card stated in
        # either order is one value: the record canonicalizes to the sorted
        # order its own text and column spellings use, so equality means
        # "the same windows" and not "the same windows, listed alike".
        from_list = PeakPricing(
            windows=[
                PeakWindow(start=time(6, 0), end=time(10, 0)),
                PeakWindow(start=time(1, 0), end=time(4, 0)),
            ]
        )
        from_tuple = PeakPricing(
            windows=(
                PeakWindow(start=time(1, 0), end=time(4, 0)),
                PeakWindow(start=time(6, 0), end=time(10, 0)),
            )
        )
        assert from_list == from_tuple
        assert from_list.windows == from_tuple.windows
        assert not from_list.flat_by_time_of_day
        # The canonical text is sorted, so two configurations stating the
        # same windows in different orders spell the same.
        assert from_list.text() == "01:00-04:00, 06:00-10:00"

    def test_re_makes_windows_recognised_by_their_parts(self):
        # The double-import remedy, applied at the constructor: a stub
        # carrying start and end is a window, whatever class it was built
        # from, and the answer is this module's class — so a record built
        # through the loader's other class copy still compares equal to
        # one built here.
        class StubWindow:
            def __init__(self, start, end):
                self.start = start
                self.end = end

        card = PeakPricing(windows=[StubWindow(time(1, 0), time(4, 0))])
        assert card.windows[0] == PeakWindow(start=time(1, 0), end=time(4, 0))
        assert type(card.windows[0]) is PeakWindow

    def test_refuses_an_item_that_is_not_a_window(self):
        # A bare string or int carries no times of day, and padding the
        # missing parts with guesses would be scheduling against a window
        # nobody described.
        with pytest.raises(DepthScheduleError, match="must be a PeakWindow"):
            PeakPricing(windows=["01:00-04:00"])
        with pytest.raises(DepthScheduleError):
            PeakPricing(windows=[60])


class TestRunWindow:
    """The choice's answer: two aware UTC instants, half-open."""

    def test_holds_its_bounds_and_derives_its_length(self):
        window = RunWindow(start_at=_at(10, 0), end_at=_at(13, 0))
        assert window.duration == timedelta(hours=3)
        with pytest.raises(dataclasses.FrozenInstanceError):
            # The record of a decision is frozen — a caller who kept a
            # reference cannot retype the schedule in memory.
            window.start_at = _at(11, 0)  # type: ignore[misc]

    def test_converts_an_aware_offset_bound_to_utc(self):
        # An instant is an instant: 14:30 at +10:00 *is* 04:30 UTC, and the
        # record holds the UTC spelling so every reader compares one form.
        window = RunWindow(
            start_at=datetime(2026, 9, WEDNESDAY, 14, 30, tzinfo=timezone(
                timedelta(hours=10)
            )),
            end_at=_at(6, 0),
        )
        assert window.start_at == _at(4, 30)
        assert window.start_at.utcoffset() == timedelta(0)

    @pytest.mark.parametrize("bounds", [
        # Naive bounds name no instant — refused rather than zoned by guess.
        # (Deliberately naive: the refusal under test is the one the record
        # raises about exactly this value.)
        (datetime(2026, 9, WEDNESDAY, 10), datetime(2026, 9, WEDNESDAY, 13)),  # noqa: DTZ001
        # A window that ends when it starts contains no run; one that ends
        # before it starts is not a window at all.
        (_at(10), _at(10)),
        (_at(13), _at(10)),
    ])
    def test_refuses_bounds_that_name_no_window(self, bounds):
        with pytest.raises(DepthScheduleError):
            RunWindow(start_at=bounds[0], end_at=bounds[1])


# ── The choice ────────────────────────────────────────────────────────────────


class TestChooseRunWindow:
    """§14.2's instruction as an arithmetic: wait out the peak, then run."""

    def test_waits_out_a_peak_it_is_scheduled_inside(self, deepseek_peaks):
        # Scheduled at 02:30, inside the card's first peak: the two-hour
        # gap at 04:00 cannot hold three hours, so the answer is the
        # fifteen-hour gap — 10:00 the same morning.  Waiting is free
        # (§14.2: nothing waits on the depth role), and 10:00 is the
        # earliest window the card allows.
        window = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        assert window.start_at == _at(10, 0)
        assert window.end_at == _at(13, 0)

    def test_starts_immediately_when_off_peak_has_room(self, deepseek_peaks):
        # 11:00 is off the card's peaks and 11:00–14:00 stays off them, so
        # the earliest legal window is the instant itself — the scheduler
        # delays only when the card makes it.
        window = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=3), now=_at(11, 0)
        )
        assert window.start_at == _at(11, 0)
        assert window.end_at == _at(14, 0)

    def test_a_run_that_would_cross_into_overnight_peak_waits_for_the_gap(
        self, deepseek_peaks
    ):
        # 23:00 plus three hours is 02:00 — inside the 01:00–04:00 peak —
        # and the two-hour 04:00 gap still cannot hold three, so the answer
        # crosses a whole day to the next 10:00.  The candidate set is the
        # peak *ends*, and the chooser walks them in order until one fits.
        window = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=3), now=_at(23, 0)
        )
        assert window.start_at == _thursday(10, 0)
        assert window.end_at == _thursday(13, 0)

    def test_fits_the_exact_two_hour_gap_when_the_run_is_two_hours(
        self, deepseek_peaks
    ):
        # A two-hour run at 23:30 cannot finish before the 01:00 peak, and
        # the two-hour 04:00–06:00 gap holds it exactly — a duration equal
        # to the gap admits, because the window is half-open at its end.
        window = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=2), now=_at(23, 30)
        )
        assert window.start_at == _thursday(4, 0)
        assert window.end_at == _thursday(6, 0)

    def test_a_run_may_end_at_the_minute_a_peak_starts(self, deepseek_peaks):
        # 22:00–01:00 touches the 01:00 peak's first minute not at all:
        # half-open bounds, so ending exactly at a peak's start is
        # off-peak by the card's own arithmetic.
        window = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=3), now=_at(22, 0)
        )
        assert window.start_at == _at(22, 0)
        assert window.end_at == _thursday(1, 0)

    def test_the_whole_fifteen_hour_gap_admits_a_fifteen_hour_run(
        self, deepseek_peaks
    ):
        # The card's largest gap, taken whole — 10:00 to 01:00 is exactly
        # fifteen hours, and a run of exactly that length fits it.
        window = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=15), now=_at(10, 0)
        )
        assert window.start_at == _at(10, 0)
        assert window.end_at == _thursday(1, 0)

    def test_a_midnight_crossing_peak_is_waited_out_like_any_other(self):
        # The card whose peak is 22:00–02:00 — one window, wrapping —
        # leaves 02:00–22:00 off-peak, so a 03:00 scheduling of a
        # five-hour run starts immediately.  The wrap is a configuration
        # spelling, not a case the arithmetic special-cases.
        card = PeakPricing(windows=(PeakWindow(start=time(22, 0), end=time(2, 0)),))
        window = choose_run_window(card, duration=timedelta(hours=5), now=_at(3, 0))
        assert window.start_at == _at(3, 0)
        assert window.end_at == _at(8, 0)

    def test_a_run_longer_than_the_largest_gap_is_refused(self, deepseek_peaks):
        # Fifteen hours and one minute exceeds the card's largest gap, and
        # the refusal names the gap — the number the duration has to come
        # under and the one the repair turns on.
        with pytest.raises(NoOffPeakWindowError, match="15 hours"):
            choose_run_window(
                deepseek_peaks,
                duration=timedelta(hours=15, minutes=1),
                now=_at(10, 0),
            )

    def test_a_card_whose_peaks_cover_the_day_refuses_any_run(self):
        # Peak all day — 00:00–12:00 and a wrapping 12:00–00:00 — leaves a
        # largest gap of zero minutes, and the refusal says so: a fact a
        # caller can act on rather than a search that silently never ends.
        card = PeakPricing(
            windows=(
                PeakWindow(start=time(0, 0), end=time(12, 0)),
                PeakWindow(start=time(12, 0), end=time(0, 0)),
            )
        )
        with pytest.raises(NoOffPeakWindowError, match="0 minutes"):
            choose_run_window(card, duration=timedelta(minutes=1), now=_at(9, 0))

    def test_a_flat_by_time_of_day_card_schedules_immediately(self):
        # No peaks configured: every window is off-peak, so the earliest
        # legal start is the scheduling instant — for any duration,
        # including one larger than any card's largest gap, because a card
        # with no peaks constrains nothing.
        window = choose_run_window(
            PeakPricing(), duration=timedelta(days=20), now=_at(5, 0)
        )
        assert window.start_at == _at(5, 0)
        assert window.duration == timedelta(days=20)

    def test_the_start_is_ceiled_to_the_minute(self):
        # An instant at 11:00:30 cannot start a run at 11:00 — that minute
        # is half gone — so the candidate is 11:01.  Pricing is
        # minute-granular and so are the bounds.
        window = choose_run_window(
            PeakPricing(), duration=timedelta(hours=1), now=_at(11, 0, 30)
        )
        assert window.start_at == _at(11, 1)
        assert window.end_at == _at(12, 1)

    def test_an_aware_scheduling_instant_of_any_offset_is_taken_as_utc(self):
        # 14:30 at +10:00 is 04:30 UTC; the chooser compares instants, not
        # wall clocks, and the answer is the UTC one.  (The card is
        # §14.2's, so 04:30 sits inside the first peak and the answer
        # demonstrates the conversion in the waiting, not just the
        # bookkeeping.)
        deepseek = PeakPricing(
            windows=(
                PeakWindow(start=time(1, 0), end=time(4, 0)),
                PeakWindow(start=time(6, 0), end=time(10, 0)),
            )
        )
        window = choose_run_window(
            deepseek,
            duration=timedelta(hours=1),
            now=datetime(2026, 9, WEDNESDAY, 14, 30, tzinfo=timezone(
                timedelta(hours=10)
            )),
        )
        # 04:30 UTC is off-peak with room before 06:00 — the run starts at
        # once, in UTC.
        assert window.start_at == _at(4, 30)
        assert window.end_at == _at(5, 30)

    def test_a_naive_scheduling_instant_is_refused(self, deepseek_peaks):
        # A naive datetime names no instant, and assigning it a zone by
        # guess would schedule against a wall clock nobody stated.
        with pytest.raises(DepthScheduleError, match="timezone-aware"):
            choose_run_window(
                deepseek_peaks,
                duration=timedelta(hours=1),
                now=datetime(2026, 9, WEDNESDAY, 2, 30),  # noqa: DTZ001 - the refusal's subject
            )

    @pytest.mark.parametrize(
        ("duration", "word"),
        [
            # Not a timedelta: a bare number is a unit the caller left
            # unstated, and guessing it is scheduling a run of the wrong
            # length by however far the guess is out.
            (3, "timedelta"),
            ("3h", "timedelta"),
            # Zero and negative lengths contain no run to schedule.
            (timedelta(0), "positive"),
            (timedelta(minutes=-90), "positive"),
            # Sub-minute lengths: the pricing is minute-granular and the
            # bounds are minute-aligned, so seconds would round-trip to a
            # different length than the one declared.
            (timedelta(seconds=90), "whole number of minutes"),
            (timedelta(minutes=90.5), "whole number of minutes"),
        ],
    )
    def test_refuses_a_length_that_is_not_one(self, deepseek_peaks, duration, word):
        with pytest.raises(DepthScheduleError, match=word):
            choose_run_window(deepseek_peaks, duration=duration, now=_at(11, 0))

    def test_recognises_a_card_by_its_parts(self, deepseek_peaks):
        # The double-import remedy at the gate: anything carrying a
        # ``windows`` iterable of ``(start, end)``-shaped items is the
        # configuration, whatever class it was built from, and the answer
        # is the one the member-built card would give.
        class StubCard:
            def __init__(self, windows):
                self.windows = windows

        class StubWindow:
            def __init__(self, start, end):
                self.start = start
                self.end = end

        stub = StubCard(
            [
                StubWindow(time(6, 0), time(10, 0)),
                StubWindow(time(1, 0), time(4, 0)),
            ]
        )
        stub_answer = choose_run_window(
            stub, duration=timedelta(hours=3), now=_at(2, 30)
        )
        member_answer = choose_run_window(
            deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        assert stub_answer == member_answer

    def test_refuses_a_value_that_is_not_a_card(self):
        # A bare string or a list carries no windows to wait out, and
        # guessing at one would be scheduling against a card nobody stated.
        with pytest.raises(DepthScheduleError, match="must be a PeakPricing"):
            choose_run_window("01:00-04:00", duration=timedelta(hours=1), now=_at(2))
        with pytest.raises(DepthScheduleError):
            choose_run_window(None, duration=timedelta(hours=1), now=_at(2))

    def test_a_multi_day_run_waits_out_every_day_it_spans(self):
        # A card with a single two-hour peak: its off-peak day is one
        # twenty-two-hour gap (06:00 to 04:00), and a thirty-hour run
        # cannot fit inside a day that has a peak in it — the refusal is
        # the largest-gap one, because the span is checked as spans, not
        # as one day.
        card = PeakPricing(windows=(PeakWindow(start=time(4, 0), end=time(6, 0)),))
        with pytest.raises(NoOffPeakWindowError, match="22 hours"):
            choose_run_window(card, duration=timedelta(hours=30), now=_at(7, 0))
        # A twenty-two-hour run — exactly the gap — starting at 07:00
        # Wednesday would carry through to 05:00 Thursday, straight into
        # the 04:00 peak, so it waits for the next gap's first minute and
        # runs Thursday 06:00 to Friday 04:00: two midnights crossed, and
        # the far bound lands on the peak's own start minute, which the
        # half-open window allows.
        window = choose_run_window(card, duration=timedelta(hours=22), now=_at(7, 0))
        assert window.start_at == _thursday(6, 0)
        assert window.end_at == _friday(4, 0)


# ── The persistence ───────────────────────────────────────────────────────────


class TestDepthRunWindowsSchedule:
    """The store: one call that chooses, proves, inserts and reads back."""

    def test_persists_the_chosen_window_with_the_run(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # Feature 202's second half: the chosen window lands in a row with
        # the campaign it was chosen for, as the spine's own instant text
        # and the configuration's canonical JSON — read straight from the
        # table, not through the store, so the assertion is about what was
        # written rather than about what the store says it wrote.
        campaign = plant_campaign(campaign_database)
        record = DepthRunWindows(campaign_database).schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as conn:
            row = conn.execute(
                f"SELECT campaign_id, start_at, end_at, peak_windows, "
                f"scheduled_at FROM {DEPTH_RUN_WINDOW_TABLE} "
                f"WHERE campaign_id = ?",
                (campaign,),
            ).fetchone()
        assert row is not None, "the schedule wrote no row"
        assert row[0] == campaign
        # The spine's ISO-8601 UTC spelling, on all three instant columns.
        for column in row[1:3] + (row[4],):
            assert _ISO_UTC.match(column), column
        assert row[1] == "2026-09-23T10:00:00.000Z"
        assert row[2] == "2026-09-23T13:00:00.000Z"
        assert row[4] == "2026-09-23T02:30:00.000Z"
        # The premise beside the decision: the card the choice was made
        # against, as one canonical spelling, sorted, so two configurations
        # stating the same windows write the same column.
        assert json.loads(row[3]) == [["01:00", "04:00"], ["06:00", "10:00"]]
        assert row[3] == '[["01:00","04:00"],["06:00","10:00"]]'
        # One campaign, one run, one row — the answer is not a second row.
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {DEPTH_RUN_WINDOW_TABLE}"
            ).fetchone()[0]
        assert count == 1
        assert record.recorded is True
        assert record.window == choose_run_window(
            deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )

    def test_the_row_is_the_record_the_store_answers(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # The record is built from the row, not from the arguments — the
        # discipline the campaign planner states for its own read-back — so
        # the caller holds the table's instants and the table's card, not a
        # parallel value the caller supplied.
        campaign = plant_campaign(campaign_database)
        record = DepthRunWindows(campaign_database).schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=2), now=_at(23, 30)
        )
        assert record.campaign_id == campaign
        assert record.recorded is True
        assert record.window.start_at == _thursday(4, 0)
        assert record.window.end_at == _thursday(6, 0)
        assert record.scheduled_at == _at(23, 30)
        assert record.pricing == deepseek_peaks
        # ...and the row() rendering names the table's own columns.
        rendered = record.row()
        assert set(rendered) == {
            "campaign_id", "start_at", "end_at", "peak_windows", "scheduled_at"
        }
        assert rendered["start_at"] == "2026-09-24T04:00:00.000Z"

    def test_get_reads_the_decision_back_and_wrote_nothing(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # get() answers the row the table holds, marked recorded=False
        # because a read wrote nothing — and a campaign never scheduled
        # answers None, which is "unscheduled", not "broken": an
        # unreachable store raises, so the two can never be confused.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        scheduled = store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=1), now=_at(11, 0)
        )
        other = plant_campaign(campaign_database)
        read = store.get(campaign)
        assert read == ScheduledRun(
            campaign_id=campaign,
            window=scheduled.window,
            pricing=deepseek_peaks,
            scheduled_at=scheduled.scheduled_at,
            recorded=False,
        )
        assert store.get(other) is None

    def test_get_creates_no_table_and_answers_none_on_a_fresh_database(
        self, database_url
    ):
        # The member-owned table is brought into being by the store's
        # first *write* and by nothing else — a read on a store that has
        # never scheduled finds no table and answers None, the same
        # degrade-don't-break stance every store here takes.
        store = DepthRunWindows(database_url)
        assert store.get(str(_uuid4())) is None
        with closing(sqlite3.connect(sqlite_path_of(database_url))) as conn:
            tables = {
                name for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert DEPTH_RUN_WINDOW_TABLE not in tables

    def test_schedule_refuses_a_campaign_nobody_planned(
        self, campaign_database, deepseek_peaks
    ):
        # The campaign table exists and holds no such row: a window
        # scheduled for an id no planned campaign holds is a run that will
        # never happen, persisted beside campaigns that did.
        stranger = str(_uuid4())
        with pytest.raises(UnknownCampaignError, match=stranger):
            DepthRunWindows(campaign_database).schedule(
                stranger, deepseek_peaks,
                duration=timedelta(hours=1), now=_at(11, 0),
            )

    def test_schedule_refuses_a_campaign_when_nothing_was_ever_planned(
        self, database_url, deepseek_peaks
    ):
        # A database with no campaign table at all is the same fact about
        # the id — no campaign has ever been planned in it — stated in the
        # wording that names the other repair (the migrations).
        with pytest.raises(UnknownCampaignError, match=CAMPAIGN_TABLE):
            DepthRunWindows(database_url).schedule(
                str(_uuid4()), deepseek_peaks,
                duration=timedelta(hours=1), now=_at(11, 0),
            )

    def test_schedule_never_creates_the_campaign_table(self, database_url, deepseek_peaks):
        # The probe is read-only and the campaign table is a core
        # migration's: refusing an unknown campaign is not licence to
        # invent the table the campaign would have lived in.
        store = DepthRunWindows(database_url)
        with pytest.raises(UnknownCampaignError):
            store.schedule(
                str(_uuid4()), deepseek_peaks,
                duration=timedelta(hours=1), now=_at(11, 0),
            )
        with closing(sqlite3.connect(sqlite_path_of(database_url))) as conn:
            tables = {
                name for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert CAMPAIGN_TABLE not in tables
        # The member's *own* table is created by the write attempt all the
        # same — it is this feature's to bring into being.
        assert DEPTH_RUN_WINDOW_TABLE in tables

    @pytest.mark.parametrize("campaign_id", ["not-a-uuid", "", None, 123])
    def test_schedule_refuses_a_campaign_id_that_joins_nothing(
        self, campaign_database, deepseek_peaks, campaign_id
    ):
        # The id is the value the campaign table keys by and every reader
        # of this row joins by; one that cannot join it names no campaign
        # whose runs could be scheduled.
        with pytest.raises(DepthScheduleError, match="not a UUID"):
            DepthRunWindows(campaign_database).schedule(
                campaign_id, deepseek_peaks,
                duration=timedelta(hours=1), now=_at(11, 0),
            )

    def test_accepts_a_uuid_object_as_the_campaign_id(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # The planner's own spelling of an id is the UUID object; the store
        # canonicalizes it to the text the table holds.
        import uuid as uuid_module

        campaign = plant_campaign(campaign_database)
        record = DepthRunWindows(campaign_database).schedule(
            uuid_module.UUID(campaign), deepseek_peaks,
            duration=timedelta(hours=1), now=_at(11, 0),
        )
        assert record.campaign_id == campaign

    def test_a_retry_answers_the_stored_decision(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # The identical scheduling arriving twice — a reclaimed spot
        # instance, a loop that re-ran its first step — is one decision:
        # the second call answers the row the table holds, recorded=False,
        # with the original decision instant and the original card, and
        # the row count stays one.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        first = store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        second = store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        assert second.recorded is False
        assert second.scheduled_at == first.scheduled_at
        assert second.pricing == first.pricing
        assert second.window == first.window
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {DEPTH_RUN_WINDOW_TABLE} "
                f"WHERE campaign_id = ?",
                (campaign,),
            ).fetchone()[0]
        assert count == 1

    def test_a_retry_does_not_remake_the_decision_against_a_moved_card(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # §14.2's rates move monthly, and the row persists the card
        # precisely so the decision keeps its own premise.  A retry that
        # arrives with a *different* card and still lands on the same
        # window answers the stored decision with the stored card — the
        # retry did not re-make the choice against a card that moved.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        first = store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=3), now=_at(11, 0)
        )
        assert first.pricing == deepseek_peaks
        # Same window on the flat card (11:00 is off-peak on both), so the
        # ask agrees on *when*; the premise is the row's.
        retried = store.schedule(
            campaign, PeakPricing(), duration=timedelta(hours=3), now=_at(11, 0)
        )
        assert retried.recorded is False
        assert retried.pricing == deepseek_peaks
        assert retried.scheduled_at == first.scheduled_at

    def test_a_retry_naming_a_different_window_is_a_conflict(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # One campaign is one run, and the row is the scheduling decision:
        # a second ask that lands on a different window (a shorter run,
        # here) is two schedules wearing one campaign, and the refusal
        # names both windows — the actionable shape, not a complaint.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        with pytest.raises(RunWindowConflictError) as refusal:
            store.schedule(
                campaign, deepseek_peaks, duration=timedelta(hours=1), now=_at(2, 30)
            )
        # Both windows, spelled, so the caller learns which is stored —
        # the stored 10:00 start and the ask's 04:00 one — and nothing
        # else a caller could mistake for either.
        assert "10:00" in str(refusal.value) and "04:00" in str(refusal.value)
        # And the stored row did not move.
        read = store.get(campaign)
        assert read.window.duration == timedelta(hours=3)

    def test_the_read_side_refuses_a_row_that_contradicts_its_own_premise(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # The laundering check: a stored window sitting inside the very
        # peaks stored beside it is refused on read, naming the campaign —
        # the read side is where corruption would otherwise pass as a
        # valid schedule, and the campaign that paid peak rate for it is
        # the one the refusal names.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=3), now=_at(2, 30)
        )
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as conn, conn:
            conn.execute(
                f"UPDATE {DEPTH_RUN_WINDOW_TABLE} SET start_at = ? "
                f"WHERE campaign_id = ?",
                ("2026-09-23T06:30:00.000Z", campaign),
            )
        with pytest.raises(DepthScheduleError, match="overlaps"):
            store.get(campaign)

    @pytest.mark.parametrize(
        ("column", "value", "word"),
        [
            # An instant column that is not the spine's text: a row this
            # feature did not write.  (A NULL cannot even land — the column
            # is NOT NULL, the schema protecting itself before the read
            # path ever sees it — so the corrupt spellings are text ones.)
            ("end_at", "yesterday", "parse"),
            # A premise column that is not the canonical JSON: not JSON at
            # all, JSON that is not the array, an array that is not of
            # pairs.
            ("peak_windows", "not json", "JSON"),
            ("peak_windows", "null", "canonical"),
            ("peak_windows", '["01:00"]', "pairs"),
        ],
    )
    def test_the_read_side_refuses_a_row_it_could_not_have_written(
        self, campaign_database, plant_campaign, deepseek_peaks, column, value, word
    ):
        # The read path re-parses every value through the row-shaped
        # readers, so a hand-edited row surfaces as a refusal naming the
        # campaign rather than as a ScheduledRun built from garbage.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        store.schedule(
            campaign, deepseek_peaks, duration=timedelta(hours=1), now=_at(11, 0)
        )
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as conn, conn:
            conn.execute(
                f"UPDATE {DEPTH_RUN_WINDOW_TABLE} SET {column} = ? "
                f"WHERE campaign_id = ?",
                (value, campaign),
            )
        with pytest.raises(DepthScheduleError, match=word):
            store.get(campaign)

    def test_the_read_side_accepts_a_flat_row_without_a_premise(
        self, campaign_database, plant_campaign
    ):
        # A campaign scheduled on a flat-by-time-of-day card stores an
        # empty premise, and the re-verification skips what it has nothing
        # to check against — every window is off-peak on that card, and
        # the read says so rather than refusing for lacking peaks.
        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        record = store.schedule(
            campaign, PeakPricing(), duration=timedelta(hours=2), now=_at(5, 0)
        )
        with closing(sqlite3.connect(sqlite_path_of(campaign_database))) as conn:
            premise = conn.execute(
                f"SELECT peak_windows FROM {DEPTH_RUN_WINDOW_TABLE} "
                f"WHERE campaign_id = ?",
                (campaign,),
            ).fetchone()[0]
        assert premise == "[]"
        assert store.get(campaign) == dataclasses.replace(record, recorded=False)

    def test_schedules_a_card_recognised_by_its_parts(
        self, campaign_database, plant_campaign
    ):
        # The store's entry point duck-types the configuration exactly as
        # the chooser does, so a caller holding the loader's other class
        # copy schedules — and the column still lands in one canonical
        # spelling.
        class StubCard:
            def __init__(self, windows):
                self.windows = windows

        class StubWindow:
            def __init__(self, start, end):
                self.start = start
                self.end = end

        store = DepthRunWindows(campaign_database)
        campaign = plant_campaign(campaign_database)
        record = store.schedule(
            campaign,
            StubCard([StubWindow(time(1, 0), time(4, 0))]),
            duration=timedelta(hours=3),
            now=_at(2, 0),
        )
        assert record.window.start_at == _at(4, 0)
        assert record.pricing == PeakPricing(
            windows=(PeakWindow(start=time(1, 0), end=time(4, 0)),)
        )

    def test_the_ask_is_validated_before_any_database_is_opened(
        self, campaign_database, deepseek_peaks
    ):
        # A malformed id, card or length is refused without touching the
        # database — asserted by a URL that cannot even be opened, which
        # would raise SQLite's own error if the store got that far.
        unreachable = DepthRunWindows("sqlite:///../denied/schedule.db")
        with pytest.raises(DepthScheduleError, match="not a UUID"):
            unreachable.schedule(
                "not-a-uuid", deepseek_peaks,
                duration=timedelta(hours=1), now=_at(11, 0),
            )
        with pytest.raises(NoOffPeakWindowError):
            unreachable.schedule(
                str(_uuid4()), deepseek_peaks,
                duration=timedelta(hours=16), now=_at(10, 0),
            )


class TestDepthRunWindowsStore:
    """The store's own contract: lazy, resolvable, honest about its URL."""

    def test_construction_touches_no_disk(self, database_url):
        # Building the store is composition-time work and must not touch
        # the disk: the URL is held, the path resolved on first use, and
        # the database file does not exist until an operation needs it.
        store = DepthRunWindows(database_url)
        assert store.database_url == database_url
        assert not sqlite_path_of(database_url).exists()

    def test_a_url_the_store_cannot_speak_is_refused_by_name(self):
        # Not at construction — composing the application must not fail on
        # a deployment's URL — but at the first operation that needs the
        # path, with the scheme named.
        store = DepthRunWindows("postgres://localhost/x")
        with pytest.raises(DepthScheduleError, match="postgres"):
            store.get(str(_uuid4()))

    def test_an_in_memory_url_is_refused(self):
        # A scheduled window must outlive the scheduling call — the
        # launcher and the auditor read it in another process — so a
        # database that dies with its connection is refused by name.
        store = DepthRunWindows("sqlite:///:memory:")
        with pytest.raises(DepthScheduleError, match="in-memory"):
            store.get(str(_uuid4()))

    def test_resolve_names_the_store_or_none(self, monkeypatch, database_url):
        # The degrade-don't-break resolution every store here takes: unset
        # (or blank) composes no store — a discoverable state, not an
        # exception — and a named URL composes the store for it.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert DepthRunWindows.resolve() is None
        assert DepthRunWindows.resolve({"DATABASE_URL": "  "}) is None
        monkeypatch.setenv("DATABASE_URL", database_url)
        resolved = DepthRunWindows.resolve()
        assert isinstance(resolved, DepthRunWindows)
        assert resolved.database_url == database_url

    def test_an_empty_url_is_refused_at_construction(self):
        # resolve()'s None is for an *unset* store; an explicitly empty URL
        # handed to the constructor is a caller's mistake about the value,
        # and is refused rather than read as "somewhere".
        with pytest.raises(DepthScheduleError, match="non-empty"):
            DepthRunWindows("  ")


class TestScheduleDepthRun:
    """The module-level spelling, for the caller without a store."""

    def test_schedules_through_the_environment(
        self, campaign_database, plant_campaign, deepseek_peaks
    ):
        # The one-call spelling resolves DATABASE_URL and performs the
        # act — the same shape create_campaign gives the planner.
        campaign = plant_campaign(campaign_database)
        record = schedule_depth_run(
            campaign, deepseek_peaks,
            duration=timedelta(hours=3), now=_at(2, 30),
            env={"DATABASE_URL": campaign_database},
        )
        assert record.recorded is True
        assert record.window.start_at == _at(10, 0)

    def test_nothing_naming_a_store_is_refused_by_name(self, monkeypatch, deepseek_peaks):
        # A scheduling call that quietly skipped its write would leave the
        # launcher waiting on a window nobody recorded — refused by name
        # rather than silently doing nothing.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(DepthScheduleError, match="nothing names a store"):
            schedule_depth_run(
                str(_uuid4()), deepseek_peaks, duration=timedelta(hours=1)
            )


def _uuid4():
    """A fresh campaign-shaped id, for the asks that should be refused.

    The ids that must *fail* are fresh UUIDs rather than reused ones, so a
    refusal fires for the reason under test (nothing planned this id) and
    not because the id is malformed — the two refusals this suite keeps
    apart.
    """
    import uuid

    return uuid.uuid4()
