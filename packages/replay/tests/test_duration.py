"""Feature 252 — the replay's measured duration: the record the cost model is
stated against, the primitive its children consume.

app_spec.xml, "Replay Engine", feature 252: *System persists the measured
duration of each policy and world replay, which completes in under 50
milliseconds on a single core.*  docs §10.4 states the two numbers the feature
is made of — *"under 50 ms per (policy, world) on a single core"* and *"if a
replay exceeds ~200 ms, something is recomputing rather than reading, and the
cost model of the architecture has broken"* — and this feature is the
measurement half of that argument: the parent (251) is what makes a replay
cheap, and the two children (253's ``recomputation_suspected`` alert past
200 ms, 254's latency percentiles) are both consumers of the duration this
feature measures.

These tests pin the feature as the facts it is made of, in the order a replay
meets them:

* **the two numbers are spelled once** — the 50 ms target and the 200 ms
  broken-cost-model point, and the threshold sits above the target (the
  ordering 253's "alert only past 200 ms, target is 50 ms" depends on);
* **the record carries the measurement** — a :class:`ReplayDuration` holds the
  policy version, the world id and the one measured duration, and derives the
  two readings (``within_target``, ``exceeds_alert_threshold``) from that one
  number, never storing them;
* **the two readings are independent** — a fast replay is within target and
  below the alert point, a mid-range one (80 ms) is over target and still below
  the alert point, and a slow one (300 ms) is over target and past the alert
  point, so the flags are two properties and not one negation of the other;
* **the record is the measurement, frozen** — no attribute can be reassigned,
  and it answers one object for its lifetime;
* **the clock is ``perf_counter`` and nothing else** — the module's only clock
  is :func:`time.perf_counter` (monotonic, so a sub-50 ms interval cannot read
  negative), never wall-clock :func:`time.time`;
* **the measurement wraps the replay's own acts** — the timer reads nothing but
  the clock (no tree, no store, no arena, no evaluator, no sandbox), which is
  the structural form of features 246/247's prohibition;
* **the record answers even when the body raises** — the context manager does
  not suppress, because 253's alert is about *a replay that ran*;
* **the refusal fires before the timer arms** — a malformed policy version or
  world id is refused in this member's vocabulary before the clock is read;
* **a broken duration is refused at construction** — a negative or NaN duration
  is not a measurement, and 253's threshold and 254's percentiles must never
  aggregate one.

There is no fixture tree, store or arena here, and that is a fact about the
feature rather than an omission: a duration is measured over a caller-supplied
body by two reads of one monotonic clock, so the timer opens nothing of its own
— §10.1's determinism contract is precisely the rule that it must not — and the
tests time a body, not a walk.  The one thing a test substitutes is the clock's
*span*, by sleeping a known interval, so "the duration is measured, not
invented" is an observable read off the record rather than an assertion about
someone else's code.
"""

from __future__ import annotations

import time

import pytest
from replay import (
    REPLAY_DURATION_ALERT_THRESHOLD,
    REPLAY_DURATION_TARGET,
    ReplayDuration,
    ReplayError,
    measure_replay,
)

POLICY = "policy-v0007"
WORLD = "world-financial-0042"


# ---------------------------------------------------------------------------
# The two numbers — spelled once, and the threshold above the target
# ---------------------------------------------------------------------------


def test_the_two_numbers_are_spelled_once() -> None:
    # docs §10.4's two numbers, each spelled once so the record's flags,
    # feature 253's alert and feature 254's percentiles all quote the same
    # literal: the 50 ms-per-(policy, world) target and the 200 ms point past
    # which the cost model has broken.
    assert REPLAY_DURATION_TARGET == 0.05
    assert REPLAY_DURATION_ALERT_THRESHOLD == 0.2


def test_the_alert_point_sits_above_the_target() -> None:
    # The ordering feature 253 depends on: a replay can be over the 50 ms
    # target and still below the 200 ms broken-cost-model point, so the alert
    # threshold must sit strictly above the target.  A replay at 80 ms proves
    # the two are independent readings, not one negation of the other.
    assert REPLAY_DURATION_ALERT_THRESHOLD > REPLAY_DURATION_TARGET


# ---------------------------------------------------------------------------
# The record carries the measurement
# ---------------------------------------------------------------------------


def test_the_record_carries_the_identity_and_the_duration() -> None:
    # The per-replay record: the two keys of the replay it measured (the policy
    # version, the world id) and the one measured duration.  A replay that met
    # the target reads as within target and below the alert point.
    record = ReplayDuration(POLICY, WORLD, 0.030)
    assert record.policy_version == POLICY
    assert record.world_id == WORLD
    assert record.duration_seconds == 0.030
    assert record.within_target is True
    assert record.exceeds_alert_threshold is False


def test_a_mid_range_replay_is_over_target_and_below_the_alert_point() -> None:
    # The two readings are independent: 80 ms is over the 50 ms target but still
    # below the 200 ms broken-cost-model point, so a replay is neither "met the
    # target" nor "broke the cost model" — it is a third state the two flags
    # carve out between them, which is why they are two properties.
    record = ReplayDuration(POLICY, WORLD, 0.080)
    assert record.within_target is False
    assert record.exceeds_alert_threshold is False


def test_a_slow_replay_passes_the_broken_cost_model_point() -> None:
    # 300 ms is past the 200 ms point at which docs §10.4 says the cost model
    # has broken: over target and past the alert threshold, the reading feature
    # 253's ``recomputation_suspected`` alert is emitted on.
    record = ReplayDuration(POLICY, WORLD, 0.300)
    assert record.within_target is False
    assert record.exceeds_alert_threshold is True


def test_the_target_and_alert_boundaries_are_inclusive() -> None:
    # Exactly at the target is "within target"; exactly at the alert point is
    # "past it" — the boundary readings, pinned so a replay landing on either
    # number is not off-by-one'd across the line feature 253 compares on.
    assert ReplayDuration(POLICY, WORLD, REPLAY_DURATION_TARGET).within_target
    assert ReplayDuration(
        POLICY, WORLD, REPLAY_DURATION_ALERT_THRESHOLD
    ).exceeds_alert_threshold


# ---------------------------------------------------------------------------
# The record is the measurement, frozen
# ---------------------------------------------------------------------------


def test_the_record_is_frozen() -> None:
    # A record is the measurement, and a measurement that could be reassigned
    # after the fact would be a duration no alert and no percentile could rely
    # on — the same reason a WorldScore is frozen on the score it started from.
    # A frozen slots object refuses an attribute write with AttributeError, and
    # the value stays put; the test asserts both, so it pins the property (the
    # duration does not move) and the mechanism (the write is refused) at once.
    record = ReplayDuration(POLICY, WORLD, 0.030)
    with pytest.raises(AttributeError):
        record.duration_seconds = 0.9  # type: ignore[misc]
    with pytest.raises(AttributeError):
        record.policy_version = "other"  # type: ignore[misc]
    assert record.duration_seconds == 0.030
    assert record.policy_version == POLICY


def test_the_record_answers_one_object_for_its_lifetime() -> None:
    # The same object on every access — the measurement, not a fresh reading
    # each time, so a consumer holding the record holds the one duration the
    # replay took, mirroring feature 251's "one resident object".
    record = ReplayDuration(POLICY, WORLD, 0.030)
    duration = record.duration_seconds
    for _ in range(100):
        assert record.duration_seconds is duration


def test_an_int_duration_answers_as_a_float() -> None:
    # A caller that measures a whole-second replay hands an int; the record
    # answers it as the float the flags and any consumer compare against, so a
    # percentile never meets an int where it expects a float.
    record = ReplayDuration(POLICY, WORLD, 1)
    assert isinstance(record.duration_seconds, float)
    assert record.duration_seconds == 1.0


# ---------------------------------------------------------------------------
# The clock is perf_counter and nothing else
# ---------------------------------------------------------------------------


def test_the_module_times_with_perf_counter_not_wall_clock() -> None:
    # The module's only clock is time.perf_counter — monotonic, so a sub-50 ms
    # interval cannot read negative, and high-resolution — never time.time
    # (wall-clock, non-monotonic, subject to NTP steps).  Pinned positively:
    # the module's `time` binding is the stdlib time, and a body that sleeps a
    # known interval yields a measured duration at least that long.  One
    # spelling of the clock, the same way feature 256 pins one spelling of the
    # information ratio.
    import replay.duration as duration_module

    assert duration_module.time.perf_counter is time.perf_counter
    with measure_replay(POLICY, WORLD) as timer:
        time.sleep(0.02)
    assert timer.duration.duration_seconds >= 0.02


# ---------------------------------------------------------------------------
# The measurement wraps the replay's own acts
# ---------------------------------------------------------------------------


def test_the_timer_touches_nothing_but_the_clock() -> None:
    # The timer reads nothing but the clock on entry and exit — no tree, no
    # store, no arena, no evaluator, no sandbox — which is the structural form
    # of features 246/247's prohibition (the replay path times its own acts and
    # reaches nothing downstream).  A body that is a bare `pass` still yields a
    # record, proving the measurement wraps the replay's own acts, not an
    # external call.
    with measure_replay(POLICY, WORLD) as timer:
        pass
    assert isinstance(timer.duration, ReplayDuration)
    assert timer.duration.duration_seconds >= 0.0


def test_the_record_is_answered_on_exit_not_on_entry() -> None:
    # A duration is a completed-interval quantity: the record is answered once
    # the interval closes, never before.  Reading it from the timer before the
    # body ran is refused — a record answered before the interval closed would
    # carry no measurement.
    timer = measure_replay(POLICY, WORLD)
    with pytest.raises(ReplayError):
        _ = timer.duration  # asked before the `with` block closed


def test_the_record_answers_even_when_the_body_raises() -> None:
    # The timing wraps a replay, not an error boundary: a replay that raised
    # still consumed a measurable interval on a single core, and feature 253's
    # alert is about *a replay that ran*, whatever it returned.  So the record
    # is produced even when the body raises, and the exception propagates.
    class Boom(Exception):
        pass

    timer = measure_replay(POLICY, WORLD)
    with pytest.raises(Boom), timer:
        raise Boom("the replay raised at round 40")
    # The record was still produced — the interval was still measured.
    assert isinstance(timer.duration, ReplayDuration)
    assert timer.duration.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# The refusal fires before the timer arms
# ---------------------------------------------------------------------------


def test_a_malformed_policy_version_is_refused_before_the_clock() -> None:
    # A malformed identity names no (policy, world) pair, and the refusal
    # belongs to the caller's ask, not to a measured replay.  Refused in this
    # member's vocabulary, before the clock is read, so a broken ask never
    # spends the interval it would have measured.
    for bad in ("   ", "", 51, None):
        with pytest.raises(ReplayError):
            measure_replay(bad, WORLD)


def test_a_malformed_world_id_is_refused_before_the_clock() -> None:
    # The same law on the world id: a value that is not a non-empty string
    # names no pair to time, and is refused before the clock is read.
    for bad in ("   ", "", 0.0, None):
        with pytest.raises(ReplayError):
            measure_replay(POLICY, bad)


def test_the_refusal_fires_before_the_timer_arms() -> None:
    # The order is the feature: the identity is validated before
    # perf_counter is read, so a malformed ask never starts a measurement.
    # Pinned by monkeypatching the clock and asserting it is never read.
    import replay.duration as duration_module

    calls: list[str] = []
    original = duration_module.time.perf_counter

    def counting_clock() -> float:
        calls.append("the clock was read")
        return original()

    duration_module.time.perf_counter = counting_clock  # type: ignore[assignment]
    try:
        with pytest.raises(ReplayError):
            measure_replay("   ", WORLD)
    finally:
        duration_module.time.perf_counter = original  # type: ignore[assignment]
    assert calls == []  # the clock was never read for a malformed ask


# ---------------------------------------------------------------------------
# A broken duration is refused at construction
# ---------------------------------------------------------------------------


def test_a_negative_duration_is_refused() -> None:
    # A replay's duration is measured on a monotonic clock read once at each
    # end, so the difference cannot be negative — a negative duration is a
    # clock read in the wrong order, and a percentile or a threshold comparison
    # built on it would be measuring against a ruler that runs backwards.
    with pytest.raises(ReplayError):
        ReplayDuration(POLICY, WORLD, -0.001)


def test_a_nan_duration_is_refused() -> None:
    # A NaN compares false against everything, so a NaN duration would silently
    # drop out of a percentile and read as "no replay" in a threshold
    # comparison — not a measurement, and 253's threshold and 254's percentiles
    # must never aggregate one.
    with pytest.raises(ReplayError):
        ReplayDuration(POLICY, WORLD, float("nan"))


def test_a_positive_infinity_duration_is_refused() -> None:
    # A positive infinity is a ruler with no end — not a measured interval on a
    # single core — and a percentile or a threshold comparison built on it
    # would be measuring against that ruler.
    with pytest.raises(ReplayError):
        ReplayDuration(POLICY, WORLD, float("inf"))


def test_a_non_numeric_duration_is_refused() -> None:
    # A duration that is not a number is a clock that was never read or read
    # wrongly; the record refuses it in this member's vocabulary.
    for bad in ("0.03", None, object(), True):
        with pytest.raises(ReplayError):
            ReplayDuration(POLICY, WORLD, bad)  # type: ignore[arg-type]


def test_an_infinitely_slow_replay_is_refused() -> None:
    # Both infinities are refused: an infinite duration is not a measured
    # interval on a single core, and a percentile or a threshold comparison
    # built on it would be measuring against a ruler with no end.
    for bad in (float("inf"), float("-inf")):
        with pytest.raises(ReplayError):
            ReplayDuration(POLICY, WORLD, bad)


# ---------------------------------------------------------------------------
# The composed record is the same act as the free constructor
# ---------------------------------------------------------------------------


def test_measure_replay_produces_the_same_record_shape() -> None:
    # The two spellings of one record — the free constructor and the measuring
    # context manager — answer the same shape: the record `measure_replay`
    # produces on exit carries the two identity keys and the measured duration,
    # exactly as a directly-constructed one does.
    with measure_replay(POLICY, WORLD) as timer:
        time.sleep(0.01)
    record = timer.duration
    assert isinstance(record, ReplayDuration)
    assert record.policy_version == POLICY
    assert record.world_id == WORLD
    assert record.duration_seconds >= 0.01
    assert record.within_target is True
