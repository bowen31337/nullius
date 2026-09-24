"""Feature 318: the token bucket matched to the venue's weight schedule.

app_spec.xml, "Order Routing & Venue Filters", feature 318: *"System applies
a token-bucket rate limiter matched to the venue weight schedule, which
returns remaining headroom per request."*  The tests below are organised
around the four things that sentence claims, because each is a thing that
can be false while the others are true:

* **the venue weight schedule** — the schedule is the limiter's whole
  vocabulary, so a request is priced by *operation name* through it and an
  operation it does not price is refused rather than charged nothing;
* **a token bucket** — refill is *continuous* (a fixed window would let a
  caller spend two allowances across the boundary), the fill is *capped* at
  the allowance (weight not spent in time is lost, which is what bounds the
  worst-case burst to the venue's own allowance), and a clock that steps
  backwards grants nothing;
* **matched to** — the allowance is the bucket's capacity *and* its refill
  rate, and a schedule the limiter cannot be matched to (an operation
  heavier than the whole bucket, a count limit wearing the weight limit's
  name) is refused at construction rather than producing a plausible wrong
  number;
* **remaining headroom per request** — *every* request answers a
  :class:`RateLimitHeadroom`, the refused one included, and the refused one
  leaves the bucket exactly as it found it.

The bucket lives in the store, because the venue meters weight per API key
and two router processes behind one key share one budget — so the suite
exercises it through a second limiter object over the same database, which
is what "shared" means here, rather than through one object's memory.

``packages/router/tests/conftest.py`` gives every test its own throwaway
``DATABASE_URL``, so no test can write into the real store.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import pytest
import router as member
from router.errors import (
    RATE_LIMITED_CODE,
    WEIGHT_BUCKET_CODE,
    WEIGHT_SCHEDULE_CODE,
    RouterError,
    RouterRateLimitedError,
    RouterRateLimitError,
    RouterStoreError,
    RouterWeightBucketError,
    RouterWeightScheduleError,
)
from router.limiter import (
    DEFAULT_VENUE_WEIGHT_SCHEDULE,
    DEFAULT_WEIGHT_SCOPE,
    OPERATION_ACCOUNT,
    OPERATION_EXCHANGE_INFO,
    OPERATION_PLACE_ORDER,
    VENUE_WEIGHT_ALLOWANCE,
    VENUE_WEIGHT_BUCKET_TABLE,
    VENUE_WEIGHT_WINDOW,
    WEIGHT_LIMIT_TYPE,
    RateLimitHeadroom,
    RouterRateLimiter,
    VenueWeightSchedule,
)

#: A fixed instant the whole suite reasons from, so no test depends on how
#: long it took to run.  Timezone-aware, because the bucket is refilled by
#: wall-clock elapsed time and a naive moment is refused by name.
T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

#: A small schedule for arithmetic a reader can check by hand: ten weight
#: units over a hundred seconds, so one unit comes back every ten seconds.
TEN_OVER_A_HUNDRED = VenueWeightSchedule(
    allowance=10,
    window=timedelta(seconds=100),
    weights={"four": 4, "three": 3, "ten": 10},
)


def _limiter(url: str, schedule: VenueWeightSchedule = TEN_OVER_A_HUNDRED, **kw):
    return RouterRateLimiter(url, schedule=schedule, **kw)


class TestTheVenueWeightSchedule:
    """*"the venue weight schedule"* — the limiter's whole vocabulary."""

    def test_the_shipped_default_prices_the_order_paths_operations(self) -> None:
        # A default, never a hardcoded constant in the order path: the
        # limiter takes whichever schedule its deployment states, and this is
        # the one a caller with nothing to state gets.  Every operation the
        # order path submits is priced, because an unpriced one is refused.
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.allowance == VENUE_WEIGHT_ALLOWANCE
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.window == VENUE_WEIGHT_WINDOW
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.limit_type == WEIGHT_LIMIT_TYPE
        for operation in (
            OPERATION_ACCOUNT,
            OPERATION_EXCHANGE_INFO,
            OPERATION_PLACE_ORDER,
        ):
            assert DEFAULT_VENUE_WEIGHT_SCHEDULE.weight_for(operation) > 0

    def test_the_weights_are_the_venues_and_the_names_are_this_members(self) -> None:
        # The two halves of "matched": the prices are the venue's schedule and
        # the operation names are this member's own spelling of its endpoints.
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.weight_for(OPERATION_EXCHANGE_INFO) == 20
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.weight_for(OPERATION_PLACE_ORDER) == 1
        assert OPERATION_PLACE_ORDER == "place_order"

    def test_an_unpriced_operation_is_refused_rather_than_charged_nothing(self) -> None:
        # The one failure a limiter matched to a schedule exists to prevent: a
        # request that went through free spends the venue's budget unmetered.
        with pytest.raises(RouterWeightScheduleError) as refusal:
            TEN_OVER_A_HUNDRED.weight_for("replace_order")
        assert WEIGHT_SCHEDULE_CODE in str(refusal.value)
        assert "replace_order" in str(refusal.value)
        # ...and the message names what *is* priced, so the repair is an edit
        # to the schedule rather than a hunt through the call sites.
        assert "four" in str(refusal.value)

    def test_a_near_miss_operation_name_is_unpriced_not_a_match(self) -> None:
        # Case is not normalised, because two operations differing only in
        # case are two different venue limits rather than one name spelled
        # carelessly -- the reason ``limit_type`` is case-sensitive too.
        for absent in ("Four", "FOUR", "fOur", "4", "fourr"):
            with pytest.raises(RouterWeightScheduleError):
                TEN_OVER_A_HUNDRED.weight_for(absent)

    def test_surrounding_whitespace_is_normalised_on_both_sides(self) -> None:
        # The one tolerance this lookup has, and it is symmetric: a schedule
        # strips its own keys at construction and the ask is stripped to
        # match, so a name that would otherwise be a near-miss against the
        # schedule's own entry is the entry.
        assert TEN_OVER_A_HUNDRED.weight_for("  four  ") == 4
        schedule = VenueWeightSchedule(allowance=10, weights={" four ": 4})
        assert schedule.weight_for("four") == 4
        assert schedule.price(" four ")[0] == "four"  # the canonical name

    def test_an_operation_must_be_non_empty_text(self) -> None:
        for absent in ("", "   ", None, 4):
            with pytest.raises(RouterWeightScheduleError):
                TEN_OVER_A_HUNDRED.weight_for(absent)

    def test_the_price_returns_the_name_the_schedule_spells_and_the_weight(self) -> None:
        # Both halves are validated once, here, so a caller that must *name*
        # the request it priced holds the string the lookup actually used.
        assert TEN_OVER_A_HUNDRED.price("  four  ") == ("four", 4)

    def test_a_request_heavier_than_the_whole_bucket_is_refused(self) -> None:
        # It can never be satisfied by any state of the bucket, so the
        # schedule would name a request the limiter could only ever refuse --
        # a permanent outage dressed as a rate limit.
        with pytest.raises(RouterWeightScheduleError) as refusal:
            VenueWeightSchedule(allowance=10, weights={"a": 11})
        assert "can never be satisfied" in str(refusal.value)

    def test_a_weight_at_the_allowance_is_allowed(self) -> None:
        # The boundary is inclusive: a request that exactly empties the bucket
        # is satisfiable, and it is the largest one that is.
        schedule = VenueWeightSchedule(allowance=10, weights={"a": 10})
        assert schedule.weight_for("a") == 10

    def test_a_count_limit_wearing_the_weight_limits_name_is_refused(self) -> None:
        # The venue publishes a separate count limit with no weight in it.
        # Pricing weight against that one would let the router exceed the
        # count while its headroom read comfortably.
        with pytest.raises(RouterWeightScheduleError) as refusal:
            VenueWeightSchedule(
                allowance=10, weights={"a": 1}, limit_type="ORDERS"
            )
        assert "ORDERS" in str(refusal.value)
        assert WEIGHT_LIMIT_TYPE in str(refusal.value)

    def test_a_schedule_with_no_operations_is_refused(self) -> None:
        for empty in ({}, None, ()):
            with pytest.raises(RouterWeightScheduleError):
                VenueWeightSchedule(allowance=10, weights=empty)

    def test_a_non_positive_or_non_whole_weight_is_refused(self) -> None:
        # Zero is the typo that spends the budget unmetered; a float is a
        # weight that cannot be spent at all; and ``True`` is refused although
        # it *is* an int, because a weight is a quantity not a truthiness.
        for bad in (0, -1, 1.5, "4", None, True, False):
            with pytest.raises(RouterWeightScheduleError):
                VenueWeightSchedule(allowance=10, weights={"a": bad})

    def test_a_non_positive_or_unusable_allowance_is_refused(self) -> None:
        for bad in (0, -6000, 1.5, "6000", None, True):
            with pytest.raises(RouterWeightScheduleError):
                VenueWeightSchedule(allowance=bad, weights={"a": 1})

    def test_a_window_over_which_no_allowance_is_a_rate_is_refused(self) -> None:
        # Fewer microseconds in the window than weight units in the allowance
        # leaves a refill interval of zero: a bucket that refills instantly is
        # not a limiter.
        with pytest.raises(RouterWeightScheduleError):
            VenueWeightSchedule(
                allowance=10, weights={"a": 1}, window=timedelta(microseconds=9)
            )

    def test_a_window_of_no_time_is_refused(self) -> None:
        for bad in (timedelta(0), timedelta(seconds=-1), 60, None):
            with pytest.raises(RouterWeightScheduleError):
                VenueWeightSchedule(allowance=10, weights={"a": 1}, window=bad)

    def test_the_refill_interval_is_floored_never_rounded_up(self) -> None:
        # 6000 units over a 60 s minute is 10 ms exactly.  A schedule whose
        # division is not exact floors, so the bucket is a hair *slower* than
        # the venue's nominal rate -- the only direction a limiter may err in.
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.refill_interval == timedelta(
            milliseconds=10
        )
        inexact = VenueWeightSchedule(
            allowance=3, weights={"a": 1}, window=timedelta(microseconds=10)
        )
        assert inexact.refill_interval == timedelta(microseconds=3)

    def test_the_refill_rate_is_the_quoted_rate_exactly(self) -> None:
        # Stated for a dashboard to read ("6000 weight units a minute"), and a
        # Fraction so the figure is exact rather than a float near-miss.
        assert DEFAULT_VENUE_WEIGHT_SCHEDULE.refill_rate == Fraction(6000, 60_000_000)
        assert TEN_OVER_A_HUNDRED.refill_rate == Fraction(10, 100_000_000)

    def test_the_weights_are_read_only_once_the_schedule_is_built(self) -> None:
        # A schedule is the law every request in this process is priced
        # against; a caller who can still edit one can change the price of an
        # order after the limiter was built from it.
        schedule = VenueWeightSchedule(allowance=10, weights={"a": 1})
        with pytest.raises(TypeError):
            schedule.weights["a"] = 5  # type: ignore[index]
        # ...and the caller's own mapping cannot be used to edit it either.
        source = {"a": 1}
        built = VenueWeightSchedule(allowance=10, weights=source)
        source["a"] = 9
        assert built.weight_for("a") == 1


class TestTheTokenBucket:
    """*"a token-bucket"* — continuous refill, a capped fill, and no refunds."""

    def test_a_fresh_bucket_starts_full(self, test_database_url: str) -> None:
        # The venue hands a key its whole allowance; the router's first request
        # must not be refused because this member had not written a row yet.
        reading = _limiter(test_database_url).headroom("four", now=T0)
        assert reading.accrued == 10  # the bucket's fill
        assert reading.capacity == 10
        assert reading.allowed is True
        assert reading.remaining == 6  # net of the price four would cost

    def test_spending_deducts_the_operations_weight(self, test_database_url: str) -> None:
        limiter = _limiter(test_database_url)
        assert limiter.acquire("four", now=T0).remaining == 6
        assert limiter.acquire("three", now=T0).remaining == 3
        assert limiter.headroom("four", now=T0).accrued == 3

    def test_refill_is_continuous_rather_than_windowed(self, test_database_url: str) -> None:
        # The property that makes this a bucket and not a counter: a fixed
        # window would hold at 0 until the boundary and then jump to the whole
        # allowance, letting a caller spend two allowances across it -- which
        # the venue, which does not reset on that boundary, would refuse.
        limiter = _limiter(test_database_url)
        limiter.acquire("ten", now=T0)
        assert limiter.headroom("ten", now=T0).accrued == 0
        # One unit every ten seconds, so a hair less than ten seconds buys
        # exactly nothing -- the refill is not a step at the window's edge.
        assert limiter.headroom("ten", now=T0 + timedelta(seconds=9)).accrued == 0
        assert limiter.headroom("ten", now=T0 + timedelta(seconds=10)).accrued == 1
        assert limiter.headroom("ten", now=T0 + timedelta(seconds=35)).accrued == 3

    def test_the_fill_is_capped_at_the_allowance(self, test_database_url: str) -> None:
        # Weight not spent in time is lost.  This is what bounds the
        # worst-case burst to the venue's own allowance: an uncapped bucket
        # would let an idle router bank an hour of weight and spend it in one
        # second, which the venue -- which does not bank -- would refuse.
        limiter = _limiter(test_database_url)
        limiter.acquire("ten", now=T0)
        assert limiter.headroom("ten", now=T0 + timedelta(hours=1)).accrued == 10
        assert limiter.acquire("ten", now=T0 + timedelta(hours=1)).remaining == 0

    def test_the_bucket_is_shared_between_processes(self, test_database_url: str) -> None:
        # The venue meters weight per API key, not per process, so two routers
        # behind one key spend one budget.  A bucket held in either process's
        # memory would let each spend the whole allowance believing it had
        # tracked the other's -- here the second limiter is the second
        # process, over the same database.
        first = _limiter(test_database_url)
        second = _limiter(test_database_url)
        first.acquire("ten", now=T0)
        assert second.headroom("four", now=T0).accrued == 0
        with pytest.raises(RouterRateLimitedError):
            second.acquire("four", now=T0)

    def test_two_scopes_are_two_budgets(self, test_database_url: str) -> None:
        # Feature 321's shadow sub-account has its own key and therefore its
        # own budget: reading two credentials as one bucket would pace the
        # live path to a spend the sub-account never made.
        live = _limiter(test_database_url, scope="live")
        shadow = _limiter(test_database_url, scope="shadow")
        live.acquire("ten", now=T0)
        assert shadow.headroom("ten", now=T0).accrued == 10

    def test_a_scope_and_an_operation_must_be_non_empty_text(
        self, test_database_url: str
    ) -> None:
        for absent in ("", "   ", None, 4):
            with pytest.raises(RouterWeightBucketError):
                _limiter(test_database_url, scope=absent)

    def test_a_scope_is_stripped_so_one_budget_has_one_spelling(
        self, test_database_url: str
    ) -> None:
        # A bucket filed under "live " and read back as "live" would be two
        # budgets for one key -- the double-spend the shared bucket exists to
        # prevent, arriving through whitespace.
        padded = _limiter(test_database_url, scope="  live  ")
        plain = _limiter(test_database_url, scope="live")
        assert padded.scope == plain.scope == "live"
        padded.acquire("ten", now=T0)
        assert plain.headroom("ten", now=T0).accrued == 0

    def test_a_backwards_clock_grants_no_weight(self, test_database_url: str) -> None:
        # An NTP correction on the live host must not reveal weight that never
        # accrued.  Weight is spent against a budget that only refills
        # forward, so a negative elapsed span is the clock disagreeing with
        # itself rather than a refund.
        limiter = _limiter(test_database_url)
        limiter.acquire("four", now=T0)
        assert limiter.headroom("four", now=T0 - timedelta(hours=1)).accrued == 6

    def test_a_backwards_clock_does_not_bank_the_early_moment(
        self, test_database_url: str
    ) -> None:
        # The subtler half of the same fault, and the reason the *clamped*
        # moment is banked rather than the ``now`` that was passed in: writing
        # the early moment back as the accrual origin would make the next read
        # count an interval that has already been counted, handing out weight
        # the venue never granted.  A refused request spends nothing, so it is
        # the clean probe -- an early origin would make the T0 + 30s read a
        # *capped, full* bucket instead of the three units that accrued.
        limiter = _limiter(test_database_url)
        limiter.acquire("ten", now=T0)  # 10 -> 0, banked at T0
        with pytest.raises(RouterRateLimitedError):
            limiter.acquire("ten", now=T0 - timedelta(hours=1))
        assert limiter.headroom("ten", now=T0 + timedelta(seconds=30)).accrued == 3
        assert limiter.headroom("ten", now=T0 + timedelta(seconds=40)).accrued == 4

    def test_a_backwards_clock_still_admits_a_request_it_can_afford(
        self, test_database_url: str
    ) -> None:
        # The clamp is over *refill*, not over admission: a request priced
        # against a moment the clock later disagrees with is still a request
        # that happened and still spends.  (The alternative -- refusing
        # everything while the clock is skewed -- would halt the order path
        # over a bookkeeping discrepancy, which is not this module's call.)
        limiter = _limiter(test_database_url)
        assert limiter.acquire("four", now=T0 - timedelta(seconds=30)).remaining == 6
        # The spend is real *and* the refill is measured from the moment it
        # was banked: six left, three accrued in the thirty seconds since, so
        # nine -- not a full ten, which is what a bucket that had never been
        # spent from would read.
        assert limiter.headroom("four", now=T0).accrued == 9

    def test_a_bucket_that_cannot_be_read_is_refused_not_repaired(
        self, test_database_url: str
    ) -> None:
        # SQLite will accept whatever another tool inserts, and a bucket read
        # as full because its state was unreadable is the direction that
        # over-spends the venue's budget.
        limiter = _limiter(test_database_url)
        limiter.acquire("four", now=T0)  # create the table and write a row
        path = test_database_url.removeprefix("sqlite:///")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                f"UPDATE {VENUE_WEIGHT_BUCKET_TABLE} SET refilled_at = 'yesterday'"
            )
            connection.commit()
        with pytest.raises(RouterWeightBucketError) as refusal:
            limiter.headroom("four", now=T0 + timedelta(seconds=10))
        assert WEIGHT_BUCKET_CODE in str(refusal.value)
        assert DEFAULT_WEIGHT_SCOPE in str(refusal.value)

    def test_a_bucket_holding_a_fill_no_bucket_can_hold_is_refused(
        self, test_database_url: str
    ) -> None:
        # The CHECK constraint is the first line, but it is not the only one:
        # another tool can write a row with the constraint off, and a fill read
        # as a number the schedule cannot produce is the direction that
        # over-spends the venue's budget.  `-5` is below zero and `'lots'` is
        # not a number at all; SQLite is dynamically typed, so both reach the
        # bucket.  (`4.0` is not in this list: INTEGER affinity round-trips it
        # losslessly to `4`, so there is nothing there to refuse.)
        limiter = _limiter(test_database_url)
        limiter.acquire("four", now=T0)  # create the table and write a row
        path = test_database_url.removeprefix("sqlite:///")
        for foreign in (-5, "lots"):
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA ignore_check_constraints = ON")
                connection.execute(
                    f"UPDATE {VENUE_WEIGHT_BUCKET_TABLE} SET available = ?", (foreign,)
                )
                connection.commit()
            with pytest.raises(RouterWeightBucketError) as refusal:
                limiter.headroom("four", now=T0 + timedelta(seconds=10))
            assert WEIGHT_BUCKET_CODE in str(refusal.value)
            assert DEFAULT_WEIGHT_SCOPE in str(refusal.value)

    def test_a_moment_that_is_not_a_moment_is_refused(self, test_database_url: str) -> None:
        limiter = _limiter(test_database_url)
        for bad in (0, "2026-09-25", T0.date(), timedelta(seconds=1)):
            with pytest.raises(RouterWeightBucketError):
                limiter.headroom("four", now=bad)
            with pytest.raises(RouterWeightBucketError):
                limiter.acquire("four", now=bad)

    def test_a_naive_moment_is_refused(self, test_database_url: str) -> None:
        # The bucket is shared with a sibling process and refilled against the
        # wall clock; a naive moment names an offset nobody agreed on.
        limiter = _limiter(test_database_url)
        naive = datetime(2026, 9, 25, 12, 0)  # noqa: DTZ001 - the naive stamp IS the input
        for method in (limiter.headroom, limiter.acquire):
            with pytest.raises(RouterWeightBucketError) as refusal:
                method("four", now=naive)
            assert WEIGHT_BUCKET_CODE in str(refusal.value)

    def test_asking_for_headroom_spends_nothing(self, test_database_url: str) -> None:
        # §16 lists "rate-limit headroom" among the live metrics, and a
        # dashboard asking how much budget is left must not have to make a
        # request to find out -- nor may it, since asking is what spends.
        limiter = _limiter(test_database_url)
        for _ in range(5):
            assert limiter.headroom("ten", now=T0).allowed is True
        assert limiter.headroom("ten", now=T0).accrued == 10

    def test_asking_for_headroom_writes_no_bucket_row(self, test_database_url: str) -> None:
        # The "construction touches no database" promise this member's other
        # stores keep, applied to a read: a deployment that only ever asks
        # leaves no bucket behind, and the figure it reads is the whole
        # allowance -- which is what the venue has actually granted it.
        database = Path(test_database_url.removeprefix("sqlite:///"))
        limiter = _limiter(test_database_url)
        assert not database.exists()  # nothing built the file either
        assert limiter.headroom("four", now=T0).accrued == 10
        with closing(sqlite3.connect(database)) as connection:
            count = connection.execute(
                f"SELECT COUNT(*) FROM {VENUE_WEIGHT_BUCKET_TABLE}"
            ).fetchone()
        assert count[0] == 0


class TestRemainingHeadroomPerRequest:
    """*"returns remaining headroom per request"* — every request, refused included."""

    def test_an_allowed_request_returns_what_is_left_for_the_next_one(
        self, test_database_url: str
    ) -> None:
        # The headline of the sentence: `remaining` is the weight the *next*
        # request has to work with, not the fill this one found.
        limiter = _limiter(test_database_url)
        reading = limiter.acquire("four", now=T0)
        assert reading.remaining == 6
        assert reading.accrued == 10
        assert reading.weight == 4
        assert reading.allowed is True
        assert reading.scope == DEFAULT_WEIGHT_SCOPE
        assert reading.operation == "four"
        assert reading.observed_at == T0
        assert reading.capacity == 10

    def test_the_allowed_reading_names_the_schedule_it_was_taken_against(
        self, test_database_url: str
    ) -> None:
        # `retry_after` is derived from the schedule, so the reading carries
        # it rather than leaving the caller to re-supply the law it was priced
        # under -- but the schedule is excluded from equality, so two readings
        # of the same bucket compare equal whatever priced them.
        limiter = _limiter(test_database_url)
        assert limiter.acquire("four", now=T0).refill_interval == timedelta(seconds=10)

    def test_a_refused_request_returns_headroom_too(self, test_database_url: str) -> None:
        # The whole point of the second clause: "per request" includes the one
        # that did not fit, which is the request a caller most needs a reading
        # for.  Refusal is an exception rather than a flag because the feature
        # *applies* the limiter, and the exception carries the reading so the
        # sentence is still true of it.
        limiter = _limiter(test_database_url)
        limiter.acquire("ten", now=T0)
        with pytest.raises(RouterRateLimitedError) as refusal:
            limiter.acquire("four", now=T0)
        headroom = refusal.value.headroom
        assert isinstance(headroom, RateLimitHeadroom)
        assert headroom.allowed is False
        assert headroom.remaining == headroom.accrued == 0
        assert headroom.weight == 4

    def test_a_refusal_leaves_the_bucket_exactly_as_it_found_it(
        self, test_database_url: str
    ) -> None:
        # Which is also what tells the two readings apart: an allowed request
        # leaves strictly less than it found, a refused one leaves what it
        # found -- and the refusal neither loses nor gains the router weight.
        limiter = _limiter(test_database_url)
        limiter.acquire("four", now=T0)  # 10 -> 6
        with pytest.raises(RouterRateLimitedError):
            limiter.acquire("ten", now=T0)
        assert limiter.headroom("ten", now=T0).accrued == 6
        # ...and the accrual keeps running from the moment it was last banked,
        # so a refusal does not reset the refill clock either.
        assert limiter.headroom("ten", now=T0 + timedelta(seconds=40)).accrued == 10

    def test_the_deficit_is_how_far_short_the_bucket_fell(
        self, test_database_url: str
    ) -> None:
        limiter = _limiter(test_database_url)
        limiter.acquire("four", now=T0)  # 10 -> 6
        with pytest.raises(RouterRateLimitedError) as refusal:
            limiter.acquire("ten", now=T0)  # needs 10, holds 6
        headroom = refusal.value.headroom
        assert headroom.deficit == 4
        assert headroom.shortfall == Fraction(4, 10)
        assert headroom.retry_after == timedelta(seconds=40)  # 4 units × 10 s

    def test_an_allowed_request_has_no_deficit_or_shortfall(
        self, test_database_url: str
    ) -> None:
        # `None` rather than zero for the shortfall: there was nothing to
        # measure, and 0 would be a reading of something that did not happen
        # -- the stance feature 320's empty window takes toward its ratio.
        reading = _limiter(test_database_url).acquire("four", now=T0)
        assert reading.deficit == 0
        assert reading.shortfall is None
        assert reading.retry_after is None

    def test_a_request_that_exactly_empties_the_bucket_spends_it(
        self, test_database_url: str
    ) -> None:
        # The boundary is a spend, not a refusal: `accrued >= weight`.  It is
        # also the one case where the two readings' `remaining` agree at zero,
        # which is why `allowed` is on the record rather than inferred.
        limiter = _limiter(test_database_url)
        reading = limiter.acquire("ten", now=T0)
        assert reading.allowed is True
        assert reading.remaining == 0
        with pytest.raises(RouterRateLimitedError) as refusal:
            limiter.acquire("ten", now=T0)
        assert refusal.value.headroom.remaining == 0
        assert refusal.value.headroom.allowed is False

    def test_the_retry_after_is_the_earliest_moment_not_a_recommendation(
        self, test_database_url: str
    ) -> None:
        # It is the floor feature 319's jittered backoff is chosen *above*: a
        # fleet of routers all waking on this exact microsecond would
        # re-collide, so the jitter is 319's to add.
        limiter = _limiter(test_database_url)
        limiter.acquire("ten", now=T0)
        with pytest.raises(RouterRateLimitedError) as refusal:
            limiter.acquire("four", now=T0)
        wait = refusal.value.retry_after
        assert wait == timedelta(seconds=40)
        # Waiting exactly that long does admit the request, which is what
        # makes it the earliest rather than a guess.
        assert limiter.headroom("four", now=T0 + wait).allowed is True

    def test_the_refusal_is_readable_without_reaching_through_it(
        self, test_database_url: str
    ) -> None:
        # The pass-through exists so the one question a refusal raises can be
        # asked of the exception; it is not a second spelling of the number.
        limiter = _limiter(test_database_url)
        limiter.acquire("ten", now=T0)
        with pytest.raises(RouterRateLimitedError) as refusal:
            limiter.acquire("four", now=T0)
        assert refusal.value.retry_after == refusal.value.headroom.retry_after

    def test_the_refusal_names_the_budget_that_refused_it(
        self, test_database_url: str
    ) -> None:
        # A router pacing itself against a shared budget needs to know *which*
        # budget refused it -- two credentials read as one scope being exactly
        # the misconfiguration DEFAULT_WEIGHT_SCOPE warns about.
        limiter = _limiter(test_database_url, scope="live")
        limiter.acquire("ten", now=T0)
        with pytest.raises(RouterRateLimitedError) as refusal:
            limiter.acquire("four", now=T0)
        message = str(refusal.value)
        assert message.startswith(RATE_LIMITED_CODE)
        assert "live" in message
        assert "four" in message


class TestTheReadingRefusesAShapeNoBucketCanHave:
    """A reading is a public value, so its shape is checked rather than assumed."""

    def _reading(self, **overrides) -> RateLimitHeadroom:
        fields = {
            "scope": "default",
            "operation": "four",
            "weight": 4,
            "allowed": True,
            "remaining": 6,
            "capacity": 10,
            "accrued": 10,
            "observed_at": T0,
        }
        fields.update(overrides)
        return RateLimitHeadroom(**fields)

    def test_a_well_formed_reading_constructs(self) -> None:
        assert self._reading().remaining == 6

    def test_a_negative_bucket_is_refused(self) -> None:
        # A negative fill would hand out weight the budget never had.
        with pytest.raises(RouterWeightBucketError):
            self._reading(remaining=-1, allowed=False)

    def test_a_fill_above_the_capacity_is_refused(self) -> None:
        # The allowance is the ceiling; above it the refill arithmetic is
        # reporting a bug rather than a budget.
        with pytest.raises(RouterWeightBucketError):
            self._reading(accrued=11, remaining=7)

    def test_a_remaining_above_the_fill_is_refused(self) -> None:
        # The direction that over-spends: a request cannot leave more weight
        # than the bucket held.
        with pytest.raises(RouterWeightBucketError):
            self._reading(remaining=11, allowed=False)

    def test_the_allowed_flag_is_pinned_to_the_spend(self) -> None:
        # An allowed request spends its weight and a refused one spends
        # nothing, so a record claiming to be allowed while showing a bucket
        # it did not draw from states two different things about one request.
        with pytest.raises(RouterWeightBucketError):
            self._reading(allowed=True, remaining=10)  # allowed, spent nothing
        with pytest.raises(RouterWeightBucketError):
            self._reading(allowed=False, remaining=6)  # refused, spent four

    def test_a_non_positive_weight_is_refused(self) -> None:
        for bad in (0, -4):
            with pytest.raises(RouterWeightScheduleError):
                self._reading(weight=bad)

    def test_a_naive_moment_is_refused(self) -> None:
        with pytest.raises(RouterWeightBucketError):
            self._reading(observed_at=datetime(2026, 9, 25, 12, 0))  # noqa: DTZ001

    def test_the_schedule_is_the_law_not_part_of_what_was_observed(self) -> None:
        # Carried so ``retry_after`` can name a duration, but excluded from
        # equality and from the repr: two readings of the same bucket are
        # equal whatever schedule priced them, and a caller comparing
        # readings should not have to hold the schedule to do it.
        a = self._reading(schedule=DEFAULT_VENUE_WEIGHT_SCHEDULE)
        b = self._reading(schedule=TEN_OVER_A_HUNDRED)
        assert a == b
        assert "schedule" not in repr(a)
        assert "scope" in repr(a)
        # ...and it defaults, so a reading built without one still answers
        # ``retry_after`` rather than raising on an absent attribute.
        assert self._reading().refill_interval == timedelta(milliseconds=10)

    def test_the_stated_default_is_what_a_bare_reading_is_priced_under(self) -> None:
        # The one schedule the limiter ships, reachable from the reading so
        # ``retry_after`` is derived rather than passed in.
        assert self._reading().schedule is DEFAULT_VENUE_WEIGHT_SCHEDULE


class TestTheLimiterIsNotAComponent:
    """Feature 318's limiter arrives by construction, like the tables it writes."""

    def test_it_resolves_from_the_database_url(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///metered.db")
        limiter = RouterRateLimiter.resolve()
        assert limiter is not None
        assert limiter.database_url == "sqlite:///metered.db"
        assert limiter.scope == DEFAULT_WEIGHT_SCOPE
        assert limiter.schedule is DEFAULT_VENUE_WEIGHT_SCHEDULE

    def test_no_database_url_resolves_no_limiter(self) -> None:
        # Absent is a discoverable deployment state, not an exception.
        assert RouterRateLimiter.resolve({}) is None
        assert RouterRateLimiter.resolve({"DATABASE_URL": "   "}) is None

    def test_it_takes_its_own_schedule_and_scope(self) -> None:
        limiter = RouterRateLimiter.resolve(
            {"DATABASE_URL": "sqlite:///metered.db"},
            schedule=TEN_OVER_A_HUNDRED,
            scope="live",
        )
        assert limiter is not None
        assert limiter.schedule is TEN_OVER_A_HUNDRED
        assert limiter.scope == "live"

    def test_resolving_opens_no_database(self, test_database_url: str) -> None:
        database = Path(test_database_url.removeprefix("sqlite:///"))
        assert RouterRateLimiter.resolve() is not None
        assert not database.exists()

    def test_the_member_still_registers_exactly_one_component(self) -> None:
        # A component's lifetime is the composing process's, and the whole
        # point of keeping the bucket in the database is that a *sibling*
        # process is spending the same budget concurrently.
        assert [
            name for name in dir(member) if name.startswith("build_")
        ] == ["build_router_exchange_info_store"]

    def test_the_member_exports_the_feature_318_names(self) -> None:
        for name in (
            "DEFAULT_VENUE_WEIGHT_SCHEDULE",
            "DEFAULT_WEIGHT_SCOPE",
            "OPERATION_ACCOUNT",
            "OPERATION_CANCEL_ORDER",
            "OPERATION_CANCEL_REPLACE_ORDER",
            "OPERATION_EXCHANGE_INFO",
            "OPERATION_OPEN_ORDERS",
            "OPERATION_PLACE_ORDER",
            "OPERATION_QUERY_ORDER",
            "RATE_LIMITED_CODE",
            "VENUE_WEIGHT_ALLOWANCE",
            "VENUE_WEIGHT_BUCKET_TABLE",
            "VENUE_WEIGHT_WINDOW",
            "WEIGHT_BUCKET_CODE",
            "WEIGHT_LIMIT_TYPE",
            "WEIGHT_SCHEDULE_CODE",
            "RateLimitHeadroom",
            "RouterRateLimiter",
            "RouterRateLimitError",
            "RouterRateLimitedError",
            "RouterWeightBucketError",
            "RouterWeightScheduleError",
            "VenueWeightSchedule",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_exports_exactly_the_one_database_url_constant(self) -> None:
        # Three modules name DATABASE_URL and the member re-exports one, so a
        # caller cannot come to hold three spellings of the same variable.
        assert member.DATABASE_URL_ENV == "DATABASE_URL"

    def test_the_error_taxonomy_splits_by_repair(self) -> None:
        # The rate-limit base is a child of RouterError and of nothing else in
        # the package: a spent weight budget and an unmatchable schedule are
        # both faults of the router's *own* metering, so a caller catching the
        # fetch fault or the health fault must not be told either is theirs.
        assert issubclass(RouterRateLimitError, RouterError)
        assert not issubclass(RouterRateLimitError, RouterStoreError)
        assert issubclass(RouterWeightScheduleError, RouterRateLimitError)
        assert issubclass(RouterWeightBucketError, RouterRateLimitError)
        assert issubclass(RouterRateLimitedError, RouterRateLimitError)
        # ...and the three are siblings of each other, because the repairs
        # differ -- fix the weights, fix the table, or wait.
        assert not issubclass(RouterWeightBucketError, RouterWeightScheduleError)
        assert not issubclass(RouterWeightScheduleError, RouterWeightBucketError)

    def test_an_address_this_member_cannot_speak_stays_a_store_error(self) -> None:
        # An *address* fault and its repair are one fact the member already
        # names once, in RouterStoreError -- the same stance feature 320 takes
        # for its own table, and the reason the scheme refusal is not this
        # feature's own class.
        for bad in (
            "postgresql://host/db",
            "sqlite://host/db",
            "sqlite://",
            "sqlite:////",
        ):
            limiter = RouterRateLimiter(bad)  # construction defers the address
            with pytest.raises(RouterStoreError):
                limiter.headroom(OPERATION_PLACE_ORDER, now=T0)

    def test_a_request_is_priced_before_the_store_is_touched(
        self, test_database_url: str
    ) -> None:
        # An unpriceable request never opens the bucket at all: the schedule
        # is the limiter's whole vocabulary, so a typo in an operation name is
        # reported as a schedule fault without a database round trip -- and,
        # on a fresh deployment, without creating the file either.
        database = Path(test_database_url.removeprefix("sqlite:///"))
        limiter = _limiter(test_database_url)
        with pytest.raises(RouterWeightScheduleError):
            limiter.acquire("placeorder", now=T0)
        with pytest.raises(RouterWeightScheduleError):
            limiter.headroom("placeorder", now=T0)
        assert not database.exists()

    def test_a_malformed_moment_is_refused_before_the_store_is_touched(
        self, test_database_url: str
    ) -> None:
        database = Path(test_database_url.removeprefix("sqlite:///"))
        with pytest.raises(RouterWeightBucketError):
            _limiter(test_database_url).acquire("four", now="noon")
        assert not database.exists()

    def test_construction_defers_the_address_so_building_one_cannot_fail(
        self, test_database_url: str
    ) -> None:
        # The "construction touches no database" promise this member's other
        # stores keep: a limiter costs nothing until a request is metered, so
        # building one is always safe and a bad URL is reported at the moment
        # a request actually needs the budget.
        database = Path(test_database_url.removeprefix("sqlite:///"))
        limiter = RouterRateLimiter("postgresql://host/db")
        assert limiter.database_url == "postgresql://host/db"
        assert not database.exists()

    def test_a_limiter_needs_a_non_empty_url_and_a_real_schedule(self) -> None:
        with pytest.raises(RouterStoreError):
            RouterRateLimiter("")
        with pytest.raises(RouterWeightScheduleError):
            RouterRateLimiter("sqlite:///metered.db", schedule={"a": 1})

    def test_the_greppable_codes_are_one_token_each(self) -> None:
        for code in (RATE_LIMITED_CODE, WEIGHT_SCHEDULE_CODE, WEIGHT_BUCKET_CODE):
            assert code
            assert " " not in code
            assert code == code.lower()


class TestTheSharedBucketHasNoDoubleSpend:
    """The property the bucket lives in the *database* for, exercised for real."""

    def test_concurrent_spends_serialize_rather_than_both_winning(
        self, test_database_url: str
    ) -> None:
        # Two routers behind one API key spend one budget, concurrently.  A
        # deferred transaction would let both read the same headroom and both
        # deduct it, which is the double-spend a *shared* budget must not
        # have -- so every write is taken under BEGIN IMMEDIATE.
        #
        # Each thread gets its own limiter *and* its own connection, which is
        # what a second process is here.  Two spends of ten against an
        # allowance of ten: exactly one may win, whichever order they land in.
        import threading

        limiter = _limiter(test_database_url)
        barrier = threading.Barrier(2)
        outcomes: list[bool] = []
        lock = threading.Lock()

        def spend() -> None:
            mine = _limiter(test_database_url)
            barrier.wait()  # both threads reach the bucket together
            try:
                mine.acquire("ten", now=T0)
                won = True
            except RouterRateLimitedError:
                won = False
            with lock:
                outcomes.append(won)

        threads = [threading.Thread(target=spend) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes) == [False, True]
        # ...and the bucket is empty, not overdrawn: the loser spent nothing.
        assert limiter.headroom("ten", now=T0).accrued == 0

    def test_the_bucket_survives_a_second_limiter_object(
        self, test_database_url: str
    ) -> None:
        # The reading is rebuilt from the row every time -- there is no
        # in-memory mirror to fall out of step with the database.
        _limiter(test_database_url).acquire("four", now=T0)
        for _ in range(3):
            assert _limiter(test_database_url).headroom("four", now=T0).accrued == 6

    def test_a_sub_interval_remainder_is_discarded_never_accumulated(
        self, test_database_url: str
    ) -> None:
        # Documented, and pinned so it cannot drift into a surprise: a spend
        # banks the fill against the moment it happened, so the part of an
        # interval that had not yet become a unit is lost.  The direction
        # matters -- it errs against the *caller*, never against the venue, the
        # same way the floored refill interval does.  Two spends nine seconds
        # apart on a ten-second interval therefore keep nothing, where an
        # exact-origin bucket would have carried 1.8 units of remainder.
        limiter = _limiter(test_database_url)
        limiter.acquire("three", now=T0)                            # 10 -> 7
        limiter.acquire("three", now=T0 + timedelta(seconds=9))     # 7 -> 4
        limiter.acquire("three", now=T0 + timedelta(seconds=18))    # 4 -> 1
        # 27 seconds have passed in total, so 2 units have accrued since the
        # last bank -- not 2 plus a carried remainder.
        assert limiter.headroom("three", now=T0 + timedelta(seconds=18)).accrued == 1
        assert limiter.headroom("three", now=T0 + timedelta(seconds=28)).accrued == 2
