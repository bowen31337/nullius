"""Feature 319: the exponential backoff and jitter that answer a refusal.

app_spec.xml, "Order Routing & Venue Filters", feature 319: *"System retries
a rate-limited request with exponential backoff plus jitter, which emits one
retry event per attempt."*  The tests below are organised around the four
things that sentence claims, because each is a thing that can be false while
the others are true:

* **retries a rate-limited request** — the request is re-sent after a
  refusal, and *only* after a refusal: the schedule and bucket faults are
  siblings of :class:`~router.errors.RouterRateLimitedError` under the
  rate-limit base, and a request raising either propagates on the first
  attempt rather than being slept out;
* **exponential backoff** — each attempt waits the refusal's own
  ``retry_after`` times a growing integer power, capped at the venue's
  window, and never below the floor (waking early buys a refusal that was
  known to be coming);
* **plus jitter** — a draw *added* above the term, so the floor law
  survives it, and bounded by the stated fraction;
* **one retry event per attempt** — exactly one event per re-send the call
  makes: none for a first-try success, ``retries`` for an exhausted call
  (the terminal refusal re-raises rather than attempts), and the event
  arrives before the attempt sleeps.

No test sleeps.  The two seams this module's time passes through — the
sleeper and the jitter source — are injected everywhere, so the suite pins
exact microsecond delays (the whole arithmetic is exact except the one
deliberate float, the draw, which a fixed-draw stub pins) and never waits
for one of them.  The composition tests at the bottom drive a *real*
:class:`~router.limiter.RouterRateLimiter` over the shared ``DATABASE_URL``
fixture, because the point of the carried headroom is that this module
paces by a reading it never queries itself.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
import router as member
from router.errors import (
    RATE_LIMITED_CODE,
    RETRY_BACKOFF_CODE,
    RouterError,
    RouterRateLimitedError,
    RouterRateLimitError,
    RouterRetryError,
    RouterStoreError,
    RouterWeightBucketError,
)
from router.limiter import (
    DEFAULT_WEIGHT_SCOPE,
    RateLimitHeadroom,
    RouterRateLimiter,
    VenueWeightSchedule,
)
from router.retry import (
    DEFAULT_BACKOFF_SCHEDULE,
    DEFAULT_JITTER_FRACTION,
    DEFAULT_MULTIPLIER,
    RATE_LIMIT_RETRY_EVENT,
    BackoffSchedule,
    RateLimitRetryEvent,
    RetryEventLog,
    retry_rate_limited,
)

#: A fixed instant the whole suite reasons from — and, deliberately, the
#: same one ``test_limiter.py`` reasons from, because the events this suite
#: pins carry the reading's own moment and the two suites describe one
#: pipeline.
T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

#: The same small schedule ``test_limiter.py`` uses: ten weight units over a
#: hundred seconds, so one unit comes back every ten seconds and every floor
#: in this suite is arithmetic a reader can check by hand (a deficit of four
#: is a floor of forty seconds).
TEN_OVER_A_HUNDRED = VenueWeightSchedule(
    allowance=10,
    window=timedelta(seconds=100),
    weights={"four": 4, "three": 3, "ten": 10},
)

SECOND = timedelta(seconds=1)


def _refused_reading(
    *,
    weight: int = 4,
    accrued: int = 3,
    operation: str = "four",
    scope: str = DEFAULT_WEIGHT_SCOPE,
    schedule: VenueWeightSchedule = TEN_OVER_A_HUNDRED,
    observed_at: datetime = T0,
) -> RateLimitHeadroom:
    """A well-formed *refused* reading: ``remaining`` equals ``accrued``."""
    return RateLimitHeadroom(
        scope=scope,
        operation=operation,
        weight=weight,
        allowed=False,
        remaining=accrued,
        capacity=schedule.allowance,
        accrued=accrued,
        observed_at=observed_at,
        schedule=schedule,
    )


def _refusal(**kwargs) -> RouterRateLimitedError:
    """A refusal carrying a refused reading, as the limiter raises them.

    With the defaults (``four`` priced 4, held 3) the floor is one unit's
    interval — ten seconds — which is the figure most of the suite's
    arithmetic starts from.
    """
    return RouterRateLimitedError(
        f"{RATE_LIMITED_CODE}: refused (test)", headroom=_refused_reading(**kwargs)
    )


class _Request:
    """The order path's request, scripted: raise these, then answer this.

    Counts its calls (the retry's budget is a count of *sends*, and the
    suite pins that count everywhere) and keeps the very exception objects
    it raised, so an exhausted retry can be pinned to re-raise the standing
    refusal itself — the freshest reading — rather than a copy.
    """

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls = 0
        self.raised: list[BaseException] = []

    def __call__(self) -> object:
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            self.raised.append(step)
            raise step
        return step


class _Sleeper:
    """The injected sleeper: records every delay, closes no eyes."""

    def __init__(self) -> None:
        self.slept: list[timedelta] = []

    def __call__(self, delay: timedelta) -> None:
        self.slept.append(delay)


class _FixedDraw(random.Random):
    """A :class:`random.Random` whose draw always lands at ``at`` of the bound.

    ``at=0.0`` draws the empty jitter (delays read as the bare exponential
    term, exactly); ``at=1.0`` draws the bound itself.  A subclass of
    ``Random`` rather than a bare stub, because the retry takes its jitter
    through that one seam and refuses anything else.
    """

    def __init__(self, at: float) -> None:
        super().__init__()
        self.at = at

    def uniform(self, a: float, b: float) -> float:
        return a + self.at * (b - a)


def _retry(
    request: Callable[[], object],
    *,
    retries: int = 5,
    at: float = 0.0,
    on_retry: object | None = None,
    jitter_rng: random.Random | None = None,
    **kw: object,
) -> tuple[object, list[RateLimitRetryEvent], list[timedelta]]:
    """Run one retry with the sleeper and the draw pinned, gathering events.

    The default draw is the empty jitter, so ``slept`` reads as the bare
    capped exponential term — the arithmetic the suite checks by hand.
    """
    events: list[RateLimitRetryEvent] = []
    sleeper = _Sleeper()
    sink = on_retry if on_retry is not None else events.append
    answer = retry_rate_limited(
        request,
        retries=retries,
        on_retry=sink,
        sleep=sleeper,
        jitter_rng=_FixedDraw(at) if jitter_rng is None else jitter_rng,
        **kw,
    )
    return answer, events, sleeper.slept


# -- "retries a rate-limited request" ---------------------------------


class TestRetriesARateLimitedRequest:
    """The first clause: the request is re-sent after a refusal — and only one."""

    def test_a_request_that_answers_first_try_is_sent_once_and_never_sleeps(self) -> None:
        # No refusal, no retry: nothing to emit, nothing to wait, and the
        # request's own answer comes back untouched.
        request = _Request(["filled"])
        answer, events, slept = _retry(request)
        assert answer == "filled"
        assert request.calls == 1
        assert events == []
        assert slept == []

    def test_a_refused_request_is_resent_until_it_answers(self) -> None:
        request = _Request([_refusal(), _refusal(), "filled"])
        answer, events, slept = _retry(request, retries=3)
        assert answer == "filled"
        assert request.calls == 3  # the original send plus two re-sends
        assert len(events) == 2
        assert len(slept) == 2

    def test_the_answer_flows_through_untouched(self) -> None:
        # The retry is transparent to the request's own value: whatever the
        # order path's send returns, the caller receives that object.
        sentinel = object()
        request = _Request([_refusal(), sentinel])
        assert _retry(request)[0] is sentinel

    def test_only_the_rate_limit_retries(self) -> None:
        # The class hierarchy does the sorting: the schedule and bucket
        # faults are siblings of the refusal, so a request raising either
        # propagates on the first attempt.  Sleeping out a mis-stated weight
        # schedule would pace a request that can never be priced at all.
        for other in (
            RouterWeightBucketError("weight_bucket: refused (test)"),
            RouterStoreError("could not read (test)"),
            ValueError("not a rate limit at all"),
        ):
            request = _Request([other])
            with pytest.raises(type(other)) as caught:
                _retry(request, retries=3)
            assert caught.value is other
            assert request.calls == 1  # no re-send, and no sleep spent on one

    def test_an_exhausted_budget_reraises_the_standing_refusal_itself(self) -> None:
        # 318's argument, inherited: "was it sent?" is not a flag for every
        # call site to check, so an exhausted retry re-raises rather than
        # answering a non-send.  And the refusal it re-raises is the very
        # exception the last send raised — the freshest reading, headroom
        # and all, not a copy or a summary.
        request = _Request([_refusal(), _refusal(), _refusal()])
        with pytest.raises(RouterRateLimitedError) as caught:
            _retry(request, retries=2)
        assert caught.value is request.raised[-1]
        assert request.calls == 3  # the original send plus both re-sends

    def test_the_reraised_refusal_carries_the_freshest_reading(self) -> None:
        # Each refusal is read when it arrives, so the one that stands is
        # the last one's — not the first, which a retry that cached its
        # reading would answer with.
        moments = [
            _refusal(observed_at=T0 + timedelta(seconds=i)) for i in range(3)
        ]
        request = _Request(moments)
        with pytest.raises(RouterRateLimitedError) as caught:
            _retry(request, retries=2)
        assert caught.value.headroom.observed_at == moments[-1].headroom.observed_at

    def test_the_budget_is_required_and_has_no_default(self) -> None:
        # §13.2 gives no number and this module invents none: a caller that
        # did not state a budget is an ask Python itself refuses, before
        # anything is sent.
        with pytest.raises(TypeError):
            retry_rate_limited(_Request(["filled"]))  # type: ignore[call-arg]


# -- "exponential backoff" --------------------------------------------


class TestExponentialBackoff:
    """The second clause's spine: the floor, the growth, the ceiling."""

    def test_each_attempt_waits_the_floor_doubled_per_refusal(self) -> None:
        # The default pacing with the empty draw: the refusal's own
        # retry_after (ten seconds for a deficit of one), then twice it,
        # then four times it.  The base is read off each refusal — never a
        # constant this module invented — and the arithmetic is exact whole
        # microseconds throughout.
        request = _Request([_refusal(), _refusal(), _refusal(), "filled"])
        _, events, slept = _retry(request, retries=3)
        assert slept == [10 * SECOND, 20 * SECOND, 40 * SECOND]
        assert [event.backoff for event in events] == slept

    def test_a_stated_multiplier_scales_the_growth(self) -> None:
        request = _Request([_refusal(), _refusal(), _refusal(), "filled"])
        _, _, slept = _retry(request, retries=3, backoff=BackoffSchedule(multiplier=3))
        assert slept == [10 * SECOND, 30 * SECOND, 90 * SECOND]

    def test_each_refusal_paces_by_its_own_floor(self) -> None:
        # The bucket keeps refilling while the retry waits, so successive
        # refusals read milder deficits — and each attempt's term is its own
        # refusal's floor times the growth, which can *shrink* when the
        # venue's arithmetic says the wait is shorter now.  Floors of 40,
        # 30 and 10 seconds double to 40, 60 and 40.
        refusals = [
            _refusal(weight=10, accrued=6, operation="ten"),
            _refusal(weight=10, accrued=7, operation="ten"),
            _refusal(weight=10, accrued=9, operation="ten"),
        ]
        request = _Request([*refusals, "filled"])
        _, events, slept = _retry(request, retries=3)
        assert [event.floor for event in events] == [
            refusal.headroom.retry_after for refusal in refusals
        ]
        assert slept == [40 * SECOND, 60 * SECOND, 40 * SECOND]

    def test_the_default_ceiling_is_the_venues_own_window(self) -> None:
        # A wait past the schedule's window waits for nothing: the allowance
        # is the capacity and the refill rate, so a drained bucket is whole
        # again within one window.  The ceiling is read off each refusal's
        # own schedule — here 100 seconds, reached on the fifth attempt.
        request = _Request([_refusal()] * 5 + ["filled"])
        _, _, slept = _retry(request, retries=5)
        assert slept == [
            10 * SECOND,
            20 * SECOND,
            40 * SECOND,
            80 * SECOND,
            100 * SECOND,  # 160 s held at the window
        ]

    def test_a_stated_ceiling_is_honoured(self) -> None:
        request = _Request([_refusal()] * 3 + ["filled"])
        _, _, slept = _retry(
            request, retries=3, backoff=BackoffSchedule(cap=15 * SECOND)
        )
        assert slept == [10 * SECOND, 15 * SECOND, 15 * SECOND]

    def test_a_ceiling_below_the_floor_still_loses_to_the_floor(self) -> None:
        # The floor is the venue's own arithmetic — the earliest moment the
        # weight can possibly be there — and honouring a smaller ceiling
        # over it would burn the attempt on a refusal that was known to be
        # coming.  Clamp to the ceiling, then lift to the floor.
        request = _Request([_refusal(), _refusal(), "filled"])
        _, events, slept = _retry(
            request, retries=2, backoff=BackoffSchedule(cap=2 * SECOND)
        )
        assert slept == [10 * SECOND, 10 * SECOND]
        for event in events:
            assert event.backoff == event.floor

    def test_the_floor_is_a_law_no_delay_can_break(self) -> None:
        # Every delay, jittered or not, sits at or above its own refusal's
        # retry_after — the hand-off 318's docstring states and this module
        # is built to keep, across the whole draw range.
        for at in (0.0, 0.25, 0.5, 0.75, 1.0):
            request = _Request([_refusal(), _refusal(), _refusal(), "filled"])
            _, events, slept = _retry(request, retries=3, at=at)
            assert len(slept) == 3
            for event in events:
                assert event.delay >= event.floor
                assert event.floor == 10 * SECOND

    def test_a_multiplier_of_one_is_refused(self) -> None:
        # It paces every attempt identically, which is a constant backoff —
        # the sentence says exponential, and consecutive refusals must cost
        # consecutively more.
        with pytest.raises(RouterRetryError) as refused:
            BackoffSchedule(multiplier=1)
        assert RETRY_BACKOFF_CODE in str(refused.value)
        assert "exponential" in str(refused.value)

    def test_the_exponential_term_is_validated_on_its_own(self) -> None:
        # The pure term seam, stated where the law lives: a floor that is
        # not a positive timedelta and an attempt that is not a genuine
        # count are refused by name.
        schedule = BackoffSchedule()
        assert schedule.exponential(10 * SECOND, 2, ceiling=100 * SECOND) == 20 * SECOND
        for bad_floor in (timedelta(0), -SECOND, 10, None):
            with pytest.raises(RouterRetryError):
                schedule.exponential(bad_floor, 1, ceiling=100 * SECOND)  # type: ignore[arg-type]
        for bad_attempt in (0, -1, True, "2", 1.0, None):
            with pytest.raises(RouterRetryError):
                schedule.exponential(10 * SECOND, bad_attempt, ceiling=100 * SECOND)  # type: ignore[arg-type]


# -- "plus jitter" ----------------------------------------------------


class TestPlusJitter:
    """The draw: added above the term, bounded by the fraction, never below the floor."""

    def test_the_jitter_is_added_above_the_term(self) -> None:
        # "Plus" is the shape: the draw lands *on top of* the capped
        # exponential term, never inside it — a spread across [0, term]
        # could draw below the floor, which is the one law this pacing has.
        request = _Request([_refusal(), _refusal(), "filled"])
        _, events, slept = _retry(request, retries=2, at=1.0)
        # Half the term, at the bound, on both attempts:
        assert slept == [15 * SECOND, 30 * SECOND]
        for event in events:
            assert event.jitter == event.backoff / 2
            assert event.delay == event.backoff + event.jitter

    def test_the_draw_stays_within_its_bound(self) -> None:
        # A seeded stream through the real bound: jitter ∈ [0, fraction ×
        # term], and never a microsecond more.
        schedule = BackoffSchedule(jitter_fraction=0.5)
        rng = random.Random(20260925)
        term = 10 * SECOND
        for _ in range(200):
            jitter = schedule.jitter(term, rng)
            assert timedelta(0) <= jitter <= 5 * SECOND

    def test_the_draw_is_floored_to_whole_microseconds(self) -> None:
        # Where the bound itself is fractional — half of three microseconds
        # — the realized jitter is floored to the whole microsecond below
        # it, so the draw never exceeds the stated fraction of the term.
        schedule = BackoffSchedule(jitter_fraction=0.5)
        rng = _FixedDraw(1.0)  # always draws the bound itself
        for _ in range(10):
            assert schedule.jitter(timedelta(microseconds=3), rng) == timedelta(
                microseconds=1
            )

    def test_two_seeds_do_not_wake_together(self) -> None:
        # The reason the draw exists: two routers refused by one shared
        # budget compute the same exponential term, and without jitter they
        # wake on the same microsecond and re-collide.
        refusals = [_refusal(), _refusal(), _refusal()]
        first = _retry(_Request([*refusals, "filled"]), jitter_rng=random.Random(1))
        second = _retry(_Request([*refusals, "filled"]), jitter_rng=random.Random(2))
        assert first[2] != second[2]  # same floors, different wakes

    def test_the_fraction_bounds_the_spread_and_zero_is_refused(self) -> None:
        # A fraction of zero is the synchronized wake "plus jitter" exists
        # to prevent — not a tuning offered — and above one the noise would
        # lead the pacing it decorates.
        assert BackoffSchedule(jitter_fraction=1).jitter_fraction == 1
        for bad in (0, -0.1, 1.5, float("inf"), float("nan"), True, "0.5", None):
            with pytest.raises(RouterRetryError) as refused:
                BackoffSchedule(jitter_fraction=bad)
            assert RETRY_BACKOFF_CODE in str(refused.value)

    def test_the_shipped_default_states_its_own_law(self) -> None:
        # A default, never a law: doubling, up to half the term of jitter,
        # ceiling at the venue's own window (a cap of None is the refusal's
        # schedule window, resolved per refusal).
        assert DEFAULT_BACKOFF_SCHEDULE.multiplier == DEFAULT_MULTIPLIER == 2
        assert DEFAULT_BACKOFF_SCHEDULE.jitter_fraction == DEFAULT_JITTER_FRACTION == 0.5
        assert DEFAULT_BACKOFF_SCHEDULE.cap is None

    def test_the_schedule_is_frozen_once_built(self) -> None:
        # The pacing is the law every attempt of the call is paced under;
        # a caller who could edit one mid-flight could change what an
        # attempt already slept meant.
        with pytest.raises(dataclasses.FrozenInstanceError):
            DEFAULT_BACKOFF_SCHEDULE.multiplier = 3  # type: ignore[misc]

    def test_a_ceiling_that_admits_no_time_is_refused(self) -> None:
        for bad in (timedelta(0), -SECOND, 60, "60s"):
            with pytest.raises(RouterRetryError):
                BackoffSchedule(cap=bad)  # type: ignore[arg-type]


# -- "one retry event per attempt" ------------------------------------


class TestOneRetryEventPerAttempt:
    """The sentence's own clause: the emission, and its exact count."""

    def test_a_first_try_success_emits_nothing(self) -> None:
        # No retry happened, so no retry event exists: the count law starts
        # at zero, not at one-per-send.
        _, events, _ = _retry(_Request(["filled"]))
        assert events == []

    def test_exactly_one_event_per_resend(self) -> None:
        # Refused twice, answered third: two re-sends, two events — one
        # each, numbered in order from the first re-send.
        request = _Request([_refusal(), _refusal(), "filled"])
        _, events, _ = _retry(request, retries=3)
        assert [event.attempt for event in events] == [1, 2]

    def test_an_exhausted_call_emits_the_budget_not_the_budget_plus_one(self) -> None:
        # The terminal refusal re-raises rather than attempting, so it
        # emits no event: ``retries`` re-sends, ``retries`` events.  One
        # more would be an event for an attempt that never happened.
        request = _Request([_refusal(), _refusal(), _refusal(), _refusal()])
        events: list[RateLimitRetryEvent] = []
        with pytest.raises(RouterRateLimitedError):
            retry_rate_limited(
                request,
                retries=3,
                on_retry=events.append,
                sleep=_Sleeper(),
                jitter_rng=_FixedDraw(0.0),
            )
        assert len(events) == 3

    def test_the_event_arrives_before_the_attempt_sleeps(self) -> None:
        # An operator watching the pacing live sees the wait that is
        # starting, not the one that already happened.
        journal: list[tuple[str, int]] = []

        def sink(event: RateLimitRetryEvent) -> object:
            journal.append(("event", event.attempt))
            return "ignored"  # the return is not the emission's business

        def sleep(delay: timedelta) -> None:
            journal.append(("sleep", len(journal)))

        request = _Request([_refusal(), _refusal(), "filled"])
        retry_rate_limited(
            request, retries=2, on_retry=sink, sleep=sleep, jitter_rng=_FixedDraw(0.0)
        )
        assert [kind for kind, _ in journal] == ["event", "sleep", "event", "sleep"]

    def test_the_event_carries_the_whole_decision(self) -> None:
        # Every field is a figure the decision already computed, read off
        # the refusal's own reading — so an operator reading the pacing
        # never re-derives it, and no figure is a second spelling.
        refusal = _refusal(weight=4, accrued=2, observed_at=T0 + timedelta(minutes=5))
        request = _Request([refusal, "filled"])
        _, events, _ = _retry(request, retries=1, at=0.0)
        (event,) = events
        assert event.event == RATE_LIMIT_RETRY_EVENT
        assert event.operation == "four"
        assert event.scope == DEFAULT_WEIGHT_SCOPE
        assert event.attempt == 1
        assert event.weight == 4
        assert event.deficit == 2
        assert event.floor == refusal.headroom.retry_after == 20 * SECOND
        assert event.backoff == 20 * SECOND
        assert event.jitter == timedelta(0)
        assert event.delay == 20 * SECOND
        assert event.observed_at == refusal.headroom.observed_at

    def test_a_sink_that_raises_stops_the_retry(self) -> None:
        # The emission is part of the attempt, and a broken sink is a
        # wiring fault to surface, not a fact to swallow.
        def broken(event: RateLimitRetryEvent) -> object:
            raise RuntimeError("sink is broken")

        request = _Request([_refusal(), "filled"])
        with pytest.raises(RuntimeError, match="sink is broken"):
            retry_rate_limited(
                request, retries=2, on_retry=broken, sleep=_Sleeper(),
                jitter_rng=_FixedDraw(0.0),
            )
        assert request.calls == 1  # the attempt never happened

    def test_no_sink_still_paces(self) -> None:
        # The event is built even with no sink wired, so its law holds of
        # every attempt, observed or not — and a caller that wants only the
        # pacing, not the emission, still gets the retry the sentence
        # promises.
        request = _Request([_refusal(), "filled"])
        sleeper = _Sleeper()
        answer = retry_rate_limited(
            request, retries=2, on_retry=None, sleep=sleeper,
            jitter_rng=_FixedDraw(0.0),
        )
        assert answer == "filled"
        assert request.calls == 2
        assert sleeper.slept == [10 * SECOND]


# -- the event's own law ----------------------------------------------


class TestTheRetryEvent:
    """The value is public; its law is pinned inside it."""

    def test_a_well_formed_event_constructs_and_is_frozen(self) -> None:
        event = RateLimitRetryEvent(
            operation="four",
            scope=DEFAULT_WEIGHT_SCOPE,
            attempt=1,
            weight=4,
            deficit=1,
            floor=10 * SECOND,
            backoff=10 * SECOND,
            jitter=timedelta(0),
            delay=10 * SECOND,
            observed_at=T0,
        )
        assert event.event == RATE_LIMIT_RETRY_EVENT
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.attempt = 2  # type: ignore[misc]

    def _event(self, **overrides: object) -> RateLimitRetryEvent:
        fields: dict[str, object] = {
            "operation": "four",
            "scope": DEFAULT_WEIGHT_SCOPE,
            "attempt": 1,
            "weight": 4,
            "deficit": 1,
            "floor": 10 * SECOND,
            "backoff": 10 * SECOND,
            "jitter": timedelta(0),
            "delay": 10 * SECOND,
            "observed_at": T0,
        }
        fields.update(overrides)
        return RateLimitRetryEvent(**fields)  # type: ignore[arg-type]

    def test_the_delay_must_be_the_term_plus_the_jitter_exactly(self) -> None:
        with pytest.raises(RouterRetryError) as refused:
            self._event(jitter=5 * SECOND, delay=10 * SECOND)
        assert RETRY_BACKOFF_CODE in str(refused.value)
        assert "exactly" in str(refused.value)

    def test_a_term_below_the_floor_is_refused(self) -> None:
        # The floor law, pinned inside the value: a backoff under the
        # refusal's retry_after buys a refusal that was known to be coming.
        with pytest.raises(RouterRetryError) as refused:
            self._event(backoff=9 * SECOND, delay=9 * SECOND)
        assert RETRY_BACKOFF_CODE in str(refused.value)
        assert "floor" in str(refused.value)

    def test_an_event_names_a_refused_attempt(self) -> None:
        # A deficit of zero is a reading that refused nothing — a retry
        # paced by it would be a retry of nothing.
        for bad in (0, -1, True, "2", 2.0):
            with pytest.raises(RouterRetryError):
                self._event(deficit=bad)

    def test_the_counts_and_names_are_genuine(self) -> None:
        for bad_attempt in (0, -1, True, "1", 1.0, None):
            with pytest.raises(RouterRetryError):
                self._event(attempt=bad_attempt)
        for bad_weight in (0, -4, True, "4", 4.0):
            with pytest.raises(RouterRetryError):
                self._event(weight=bad_weight)
        for bad_name in ("", "   ", None, 4):
            for field in ("operation", "scope"):
                with pytest.raises(RouterRetryError):
                    self._event(**{field: bad_name})

    def test_a_naive_or_non_moment_is_refused(self) -> None:
        naive = datetime(2026, 9, 25, 12, 0)  # noqa: DTZ001 - the naive stamp IS the input
        for bad in (naive, T0.date(), 0, None):
            with pytest.raises(RouterRetryError):
                self._event(observed_at=bad)

    def test_render_names_the_facts_of_the_pacing(self) -> None:
        line = self._event().render()
        assert RATE_LIMIT_RETRY_EVENT in line
        assert "four" in line
        assert "retry 1" in line
        assert "0:00:10" in line  # the delay, as the reading's own spelling


# -- the ask, refused eagerly -----------------------------------------


class TestTheBudgetIsTheCallers:
    """No number this module invented — and no send before the ask is checked."""

    def test_the_budget_must_be_a_genuine_count(self) -> None:
        for bad in (0, -1, True, "3", 3.0, None):
            with pytest.raises(RouterRetryError) as refused:
                retry_rate_limited(_Request(["filled"]), retries=bad)
            assert RETRY_BACKOFF_CODE in str(refused.value)

    def test_every_refusal_fires_before_the_request_is_sent(self) -> None:
        # A retry that began sleeping before its ask was checked would have
        # a caller believe a malformed retry was accepted — so every
        # refusal here is eager, and the request is never touched by one.
        request = _Request([_refusal(), "filled"])
        with pytest.raises(RouterRetryError):
            retry_rate_limited(request, retries=0)
        with pytest.raises(RouterRetryError):
            retry_rate_limited(None, retries=2)  # type: ignore[arg-type]
        with pytest.raises(RouterRetryError):
            retry_rate_limited(request, retries=2, on_retry=42)  # type: ignore[arg-type]
        with pytest.raises(RouterRetryError):
            retry_rate_limited(request, retries=2, backoff={"multiplier": 2})  # type: ignore[arg-type]
        with pytest.raises(RouterRetryError):
            retry_rate_limited(request, retries=2, sleep=None)  # type: ignore[arg-type]
        with pytest.raises(RouterRetryError):
            retry_rate_limited(request, retries=2, jitter_rng=random)  # type: ignore[arg-type]
        assert request.calls == 0

    def test_a_refusal_that_names_no_wait_cannot_be_paced(self) -> None:
        # RouterRateLimitedError carries its reading, and a refused reading
        # always names a retry_after — so one that does not is a refusal
        # wearing a reading that refused nothing, refused here by name.
        allowed = RateLimitHeadroom(
            scope=DEFAULT_WEIGHT_SCOPE,
            operation="four",
            weight=4,
            allowed=True,
            remaining=6,
            capacity=10,
            accrued=10,
            observed_at=T0,
            schedule=TEN_OVER_A_HUNDRED,
        )
        request = _Request([RouterRateLimitedError("rate_limited: (test)", headroom=allowed)])
        with pytest.raises(RouterRetryError) as refused:
            _retry(request, retries=2)
        assert RETRY_BACKOFF_CODE in str(refused.value)
        assert request.calls == 1


# -- the standard sink ------------------------------------------------


class TestTheStandardSink:
    """``RetryEventLog`` — the how of "emits", for a caller with no sink of their own."""

    def test_it_records_in_emission_order_and_flows_through(self) -> None:
        log = RetryEventLog()
        request = _Request([_refusal(), _refusal(), "filled"])
        retry_rate_limited(
            request, retries=2, on_retry=log.record, sleep=_Sleeper(),
            jitter_rng=_FixedDraw(0.0),
        )
        assert len(log) == 2
        assert [event.attempt for event in log] == [1, 2]
        assert [event.attempt for event in log.events()] == [1, 2]

    def test_it_filters_by_operation_never_across_names(self) -> None:
        # A retry of one request is never reported under another's name.
        log = RetryEventLog()
        request = _Request(
            [_refusal(operation="four"), _refusal(operation="ten", weight=10, accrued=0), "filled"]
        )
        retry_rate_limited(
            request, retries=2, on_retry=log.record, sleep=_Sleeper(),
            jitter_rng=_FixedDraw(0.0),
        )
        assert [event.attempt for event in log.events("four")] == [1]
        assert [event.attempt for event in log.events("ten")] == [2]
        assert log.events("Three") == ()  # a near miss is not a match

    def test_it_refuses_what_is_not_a_retry_event(self) -> None:
        # A row that is not a retry event is a wiring bug, and a log that
        # took it would answer for pacing that never happened.
        log = RetryEventLog()
        with pytest.raises(RouterRetryError) as refused:
            log.record("rate_limit_retry")  # type: ignore[arg-type]
        assert RETRY_BACKOFF_CODE in str(refused.value)
        assert len(log) == 0

    def test_the_pass_through_returns_the_event_for_wiring(self) -> None:
        log = RetryEventLog()
        event = RateLimitRetryEvent(
            operation="four",
            scope=DEFAULT_WEIGHT_SCOPE,
            attempt=1,
            weight=4,
            deficit=1,
            floor=10 * SECOND,
            backoff=10 * SECOND,
            jitter=timedelta(0),
            delay=10 * SECOND,
            observed_at=T0,
        )
        assert log.record(event) is event


# -- the composition with 318 -----------------------------------------


class TestWithTheLimiterItself:
    """The seam, exercised for real: pace by the carried headroom, never a second query.

    A real :class:`RouterRateLimiter` over the suite's throwaway
    ``DATABASE_URL``; the request is the order path's own composition (price
    the call through the limiter, then send); the sleeper is a clock that
    advances by exactly the delay this module chose — which is what a real
    sleeper does to the wall clock the bucket refills against.
    """

    def test_the_retry_paces_until_the_bucket_can_serve_it(
        self, test_database_url: str
    ) -> None:
        limiter = RouterRateLimiter(test_database_url, schedule=TEN_OVER_A_HUNDRED)
        # Drain to two units: a ``four`` is then refused by exactly two
        # units, so the floor is two intervals — twenty seconds.
        limiter.acquire("four", now=T0)
        limiter.acquire("four", now=T0)
        clock = {"now": T0}
        slept: list[timedelta] = []

        def request() -> RateLimitHeadroom:
            return limiter.acquire("four", now=clock["now"])

        def sleep(delay: timedelta) -> None:
            slept.append(delay)
            clock["now"] = clock["now"] + delay

        answer, events, _ = _harness(request, sleep)
        assert answer.allowed is True
        assert answer.remaining == 0  # two banked + two accrued = four, spent
        # The one event's floor is the refusal's own arithmetic — deficit 2
        # × interval 10 s — read off the carried headroom, and the delay
        # waited exactly long enough for those two units to accrue.
        (event,) = events
        assert event.deficit == 2
        assert event.floor == 20 * SECOND
        assert event.delay == 20 * SECOND
        assert slept == [20 * SECOND]
        assert clock["now"] == T0 + 20 * SECOND

    def test_an_exhausted_retry_stands_refused_with_its_reading(
        self, test_database_url: str
    ) -> None:
        # A sleeper that does not advance the clock is a retry whose waits
        # buy nothing: the bucket cannot refill, the budget spends, and the
        # standing refusal re-raises carrying the freshest reading.
        limiter = RouterRateLimiter(test_database_url, schedule=TEN_OVER_A_HUNDRED)
        limiter.acquire("ten", now=T0)  # drain the bucket to zero

        def request() -> RateLimitHeadroom:
            return limiter.acquire("ten", now=T0)

        events: list[RateLimitRetryEvent] = []
        with pytest.raises(RouterRateLimitedError) as caught:
            retry_rate_limited(
                request,
                retries=1,
                on_retry=events.append,
                sleep=_Sleeper(),
                jitter_rng=_FixedDraw(0.0),
            )
        assert len(events) == 1  # one re-send made, one event for it
        assert events[0].floor == 100 * SECOND  # ten units × ten seconds
        assert caught.value.headroom.deficit == 10
        assert caught.value.headroom.retry_after == 100 * SECOND


def _harness(
    request: Callable[[], object],
    sleep: Callable[[timedelta], object],
    *,
    retries: int = 3,
) -> tuple[object, list[RateLimitRetryEvent], list[timedelta]]:
    """The composition-test harness: a real retry, the given sleeper, no draw."""
    events: list[RateLimitRetryEvent] = []
    answer = retry_rate_limited(
        request,
        retries=retries,
        on_retry=events.append,
        sleep=sleep,
        jitter_rng=_FixedDraw(0.0),
    )
    return answer, events, []


# -- the member's surface ---------------------------------------------


class TestTheRetryIsNotAComponent:
    """A verb, per call — not a fourth table, not a second builder."""

    def test_the_member_exports_the_feature_319_names(self) -> None:
        for name in (
            "DEFAULT_BACKOFF_SCHEDULE",
            "RATE_LIMIT_RETRY_EVENT",
            "RETRY_BACKOFF_CODE",
            "BackoffSchedule",
            "RateLimitRetryEvent",
            "RetryEventLog",
            "RouterRetryError",
            "retry_rate_limited",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_still_registers_exactly_one_component(self) -> None:
        assert [
            name for name in dir(member) if name.startswith("build_")
        ] == ["build_router_exchange_info_store"]

    def test_the_error_taxonomy_splits_by_repair(self) -> None:
        # The retry is the limiter's own answer to its own refusal, so a
        # caller asking "is the rate-limited path unhappy?" catches one
        # base — and a caller catching only the *refusal* does not have a
        # malformed retry ask land in that except.
        assert issubclass(RouterRetryError, RouterRateLimitError)
        assert issubclass(RouterRetryError, RouterError)
        assert not issubclass(RouterRetryError, RouterRateLimitedError)
        assert not issubclass(RouterRetryError, RouterWeightBucketError)
        assert not issubclass(RouterRetryError, RouterStoreError)
        # ...and the refusal is not a retry fault either, so the two greps
        # the operator owns stay one pipeline apart.
        assert not issubclass(RouterRateLimitedError, RouterRetryError)

    def test_the_greppable_codes_are_one_token_each(self) -> None:
        for code in (RETRY_BACKOFF_CODE, RATE_LIMIT_RETRY_EVENT):
            assert code
            assert " " not in code
            assert code == code.lower()
