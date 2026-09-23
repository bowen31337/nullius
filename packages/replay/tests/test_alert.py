"""Feature 253 — the ``recomputation_suspected`` alert past 200 milliseconds.

app_spec.xml, "Replay Engine", feature 253: *System emits a
``recomputation_suspected`` alert when a replay exceeds 200 milliseconds,
because the cost model has then broken.*  docs §10.4's third sentence is the
whole feature — *"If a replay exceeds ~200 ms, something is recomputing rather
than reading, and the cost model of the architecture has broken"* — and it
names a **diagnosis**, not a failure of the replay's result.  The parent (252)
measures one replay and derives the reading; the sibling (254) aggregates a
population and keeps the slow tail as measured; this feature is the judgment on
*one* record, and it is the one place a slow replay produces a loud thing.

These tests pin the feature as the facts it is made of, in the order a replay
meets them:

* **the kind is the spec's spelling** — ``recomputation_suspected``, verbatim,
  because the word is what an operator greps for and what a monitor dispatches
  on;
* **the numbers are quoted, not restated** — the threshold the record carries is
  252's :data:`REPLAY_DURATION_ALERT_THRESHOLD`, the one spelling of §10.4's
  ~200 ms, and this module holds no literal of its own;
* **a replay that read emits nothing** — a fast replay answers ``None`` and
  raising emits nothing, so a dreaming cycle that ran clean observes only its own
  loop continuing;
* **the boundary is inclusive** — exactly 200 ms emits, the same reading 252's
  ``exceeds_alert_threshold`` gives, so the two cannot be off by one across the
  line;
* **the record carries the diagnosis** — the replay's pair (the two keys of
  §10.3's ``(policy, world)`` cycle), the measured duration, the threshold it
  passed, the kind and the instant;
* **the record is frozen and self-consistent** — no attribute moves, and a record
  whose duration sits below its own threshold is refused at construction;
* **the flag is the reading, and a carrier contradicting its own arithmetic is
  refused** — the decision reads 252's derived flag (never a second comparison),
  and a duck-typed carrier claiming "fine" at 300 ms would silently drop the
  alert this feature exists to raise while one claiming "suspected" at 3 ms would
  page an operator about a replay that read;
* **a broken carrier is a broken ask, not an alert** — a bare number, a missing
  duration, a NaN, an infinity, a negative duration, a non-bool flag and a
  malformed instant are all refused in this member's vocabulary *rather than*
  being reported as a cost model that broke;
* **the emission is a typed raise carrying its record** — catching
  ``RecomputationSuspectedError`` still leaves the caller something to log,
  ticket or dispatch;
* **the emission is post-hoc** — the alert cannot exist inside the measured
  region, because 252's timer refuses to answer a duration before the interval
  closed;
* **it does not refuse the replay** — a 300 ms replay is still measured, still
  persisted, still correct: 252's law is the parent's and 254's store keeps the
  tail;
* **no component and no store** — a record and a raise are per-replay state, so
  the member's one ``@register`` contribution stays feature 245's facade, and the
  alert depends on no database and no report.

There is no fixture tree, arena or store here, and that is a fact about the
feature rather than an omission: the alert judges a duration a caller measured,
so nothing is opened and nothing is written.  The one thing a test substitutes
is the clock's *span*, by sleeping a known interval, so "the alert is about a
replay that actually ran" is read off a real timer rather than asserted about
someone else's code.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import replay
from replay import (
    RECOMPUTATION_SUSPECTED,
    REPLAY_DURATION_ALERT_THRESHOLD,
    REPLAY_DURATION_TARGET,
    RecomputationSuspected,
    RecomputationSuspectedError,
    ReplayDuration,
    ReplayError,
    emit_recomputation_suspected,
    measure_replay,
    recomputation_suspected_error,
    suspected_recomputation,
)

POLICY = "policy-v0007"
WORLD = "world-financial-0042"


def measured(seconds: float) -> ReplayDuration:
    """One measured replay — 252's record, the unit this feature judges.

    Built through the parent's own record rather than a hand-rolled carrier,
    because the record *is* the thing feature 253 reads: the alert's decision is
    a function of a 252 measurement, and a fixture that invented its own shape
    would let the seam drift from the class the deployment actually holds.
    """
    return ReplayDuration(POLICY, WORLD, seconds)


#: The default for :class:`ForeignDuration`'s ``flag`` — *derive it from the
#: duration*, the way 252's record does.  A sentinel rather than ``None``,
#: because ``None`` is itself a broken flag worth handing the seam, and a default
#: that doubled as "no flag" would have made that case untestable.
_DERIVED = object()


class ForeignDuration:
    """A carrier that *is* a measured replay without being 252's record.

    The duck-typed half of the seam's promise: the reading is read by what the
    carrier *answers* (``duration_seconds``, ``exceeds_alert_threshold`` and the
    two identity keys), never by which module defined it — so a record produced
    under the loader's synthetic module name, a second class object of the same
    name, is judged exactly like this one.

    ``flag`` defaults to the derivation 252's record performs, and may be set to
    anything — including a lie or a non-bool — because the seam's refusal of a
    carrier that contradicts its own arithmetic is one of the facts under test.
    """

    __slots__ = ("_flag", "_seconds", "policy_version", "world_id")

    def __init__(
        self,
        seconds: float,
        *,
        flag: object = _DERIVED,
        policy_version: str = POLICY,
        world_id: str = WORLD,
    ) -> None:
        self._seconds = seconds
        # The derivation is only attempted when the flag was left alone: a
        # deliberately broken duration (a string, a ``None``) would raise out of
        # the comparison rather than reaching the seam that is supposed to refuse
        # it, and a test that failed in its own fixture would be testing nothing.
        self._flag = (
            seconds >= REPLAY_DURATION_ALERT_THRESHOLD
            if flag is _DERIVED
            else flag
        )
        self.policy_version = policy_version
        self.world_id = world_id

    @property
    def duration_seconds(self) -> float:
        return self._seconds

    @property
    def exceeds_alert_threshold(self) -> bool:
        return self._flag


# ---------------------------------------------------------------------------
# The kind is the spec's spelling, and the numbers are quoted
# ---------------------------------------------------------------------------


def test_the_kind_is_the_specs_spelling() -> None:
    # app_spec.xml feature 253 says ``recomputation_suspected``, and that word is
    # the whole of the alert's machine-readable identity: an operator greps for
    # it and a monitor dispatches on it, so a paraphrase would be an alert the
    # spec did not get.  Every record carries it, validated at construction.
    assert RECOMPUTATION_SUSPECTED == "recomputation_suspected"
    alert = suspected_recomputation(measured(0.30))
    assert alert is not None
    assert alert.alert_kind == RECOMPUTATION_SUSPECTED


def test_the_threshold_is_quoted_from_the_parent_not_restated() -> None:
    # docs §10.4's ~200 ms is spelled once, by feature 252, and this feature
    # quotes it: the record carries the parent's constant, and a re-tuned
    # threshold cannot drift between the flag 252 derives, the record 253 emits
    # and the message an operator pages on.
    alert = suspected_recomputation(measured(REPLAY_DURATION_ALERT_THRESHOLD))
    assert alert is not None
    assert alert.threshold_seconds == REPLAY_DURATION_ALERT_THRESHOLD
    assert alert.threshold_seconds > REPLAY_DURATION_TARGET  # the ordering 252 pins


# ---------------------------------------------------------------------------
# A replay that read emits nothing
# ---------------------------------------------------------------------------


def test_a_replay_that_read_emits_nothing() -> None:
    # The not-taken branch is as much the feature as the taken one: a replay at
    # or under §10.4's point read rather than recomputed, so there is nothing to
    # alert on and a dreaming cycle that ran clean must observe nothing but its
    # own loop continuing.  None is that fact as a value, not an exception.
    assert suspected_recomputation(measured(0.030)) is None
    assert emit_recomputation_suspected(measured(0.030)) is None


def test_a_mid_range_replay_is_over_target_and_still_silent() -> None:
    # 80 ms is over the 50 ms target and still below the 200 ms point: the third
    # state 252's two independent readings carve out.  Feature 253 alerts only on
    # the *broken cost model*, never on a missed target — so a replay that was
    # slower than we would like is not a cost model that broke, and this feature
    # does not turn 252's target into a second alert of its own.
    assert suspected_recomputation(measured(0.080)) is None


def test_the_boundary_is_inclusive() -> None:
    # Exactly at the threshold emits, matching 252's ``exceeds_alert_threshold``
    # (``>=``, pinned in the parent's suite): the two readings must not be
    # off-by-one across the same line, or a replay landing exactly on 200 ms
    # would be flagged by the record and silently ignored by the alert.
    alert = suspected_recomputation(measured(0.200))
    assert alert is not None
    assert alert.duration_seconds == REPLAY_DURATION_ALERT_THRESHOLD


def test_a_replay_just_below_the_point_is_silent() -> None:
    # One microsecond below the point is a replay that read: the reading is
    # exactly the parent's comparison, so the alert cannot be one step wider than
    # the flag it claims to read.
    assert suspected_recomputation(measured(0.199999)) is None


# ---------------------------------------------------------------------------
# The record carries the diagnosis
# ---------------------------------------------------------------------------


def test_the_record_carries_the_pair_the_duration_and_the_threshold() -> None:
    # The four facts an operator acts on, each already carried by 252's record:
    # *which* replay recomputed (the pair §10.3's cycle is measured in), the
    # number the diagnosis was made on, and the point it passed.
    alert = suspected_recomputation(measured(0.310))
    assert alert is not None
    assert alert.policy_version == POLICY
    assert alert.world_id == WORLD
    assert alert.duration_seconds == 0.310
    assert alert.threshold_seconds == REPLAY_DURATION_ALERT_THRESHOLD
    assert alert.detected_at  # stamped on emission


def test_the_record_is_frozen() -> None:
    # A record is the diagnosis, and a diagnosis that could be reassigned after
    # the fact would be an alert no monitor could rely on — the same reason 252's
    # record is frozen on the duration it started from.  The write is refused and
    # the values stay put.
    alert = suspected_recomputation(measured(0.310))
    assert alert is not None
    with pytest.raises(AttributeError):
        alert.duration_seconds = 0.001  # type: ignore[misc]
    with pytest.raises(AttributeError):
        alert.alert_kind = "something_else"  # type: ignore[misc]
    assert alert.duration_seconds == 0.310
    assert alert.alert_kind == RECOMPUTATION_SUSPECTED


def test_the_summary_spells_the_pair_the_numbers_and_the_conclusion() -> None:
    # The line an operator or a monitor reads: the kind, the pair, both numbers
    # in ms (the unit §10.4 states them in) and §10.4's own conclusion.
    alert = suspected_recomputation(measured(0.310))
    assert alert is not None
    summary = alert.summary()
    assert RECOMPUTATION_SUSPECTED in summary
    assert POLICY in summary
    assert WORLD in summary
    assert "310.000 ms" in summary
    assert "200.000 ms" in summary
    assert "recomputing rather than reading" in summary


def test_the_same_record_summarises_identically_twice() -> None:
    # Deterministic rendering, so two summaries of one alert are byte-identical
    # and a log, a diff or a test can compare them — the property the canary's
    # halt summary and the cost model's reports both state for theirs.
    alert = suspected_recomputation(measured(0.310), detected_at="2026-09-23T12:00:00+00:00")
    assert alert is not None
    assert alert.summary() == alert.summary()


# ---------------------------------------------------------------------------
# The record is self-consistent
# ---------------------------------------------------------------------------


def test_a_record_whose_duration_is_below_its_threshold_is_refused() -> None:
    # A recomputation alert exists because a replay *passed* the point, so a
    # record whose duration sits below its own threshold is a page about a replay
    # that read — no deployment measured one, and a monitor trusting it would be
    # chasing a cost model that had not broken.
    with pytest.raises(ReplayError):
        RecomputationSuspected(POLICY, WORLD, 0.030)


def test_a_record_wearing_another_kind_is_refused() -> None:
    # Feature 253's alert has exactly one kind, and a record carrying any other
    # word is an alert no reader of ``recomputation_suspected`` could find — the
    # refusal every alert record in this workspace states for its own spelling.
    for bad in ("determinism_broken", "unrecoverable_state", "", None):
        with pytest.raises(ReplayError):
            RecomputationSuspected(POLICY, WORLD, 0.310, alert_kind=bad)  # type: ignore[arg-type]


def test_a_broken_threshold_is_refused_at_construction() -> None:
    # The constructor is also this seam's own spelling (a caller reconstructing
    # an alert from a log), so the threshold is defended: the diagnosis is *a
    # duration at or past a positive point*, and a threshold that is not a
    # positive finite real makes the record's own consistency check meaningless.
    for bad in (float("nan"), float("inf"), -0.2, 0.0, "0.2", None, True):
        with pytest.raises(ReplayError):
            RecomputationSuspected(POLICY, WORLD, 0.310, threshold_seconds=bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The flag is the reading, and a carrier contradicting itself is refused
# ---------------------------------------------------------------------------


def test_the_reading_is_the_parents_flag_not_a_second_comparison() -> None:
    # The decision reads ``exceeds_alert_threshold`` off the record — the reading
    # feature 252 derives from the one measured number against the one spelling
    # of §10.4's point — rather than recomputing ``duration >= 0.2`` here.  The
    # proof is a carrier that lies: a flag of False at 300 ms drops the alert, and
    # because a lying carrier is refused rather than believed, the only way to get
    # an answer either way is through the flag the parent derived.
    with pytest.raises(ReplayError) as raised:
        suspected_recomputation(ForeignDuration(0.300, flag=False))
    assert "exceeds_alert_threshold" in str(raised.value)


def test_a_carrier_claiming_suspicion_over_a_fast_replay_is_refused() -> None:
    # The other direction, and it is as load-bearing as the first: a flag of True
    # at 3 ms would page an operator about a replay that read.  Both are
    # contradictions with the carrier's own arithmetic, so both are refused
    # rather than either silently dropping the alert or raising a false one.
    with pytest.raises(ReplayError) as raised:
        suspected_recomputation(ForeignDuration(0.003, flag=True))
    assert "disagrees with its own duration" in str(raised.value)


def test_a_non_bool_flag_is_refused() -> None:
    # Whether an alert goes out is exactly one bit, and a truthy string or a 1
    # smuggled in from a serialised row would decide the emission by accident.
    for bad in (1, 0, "yes", None, 1.0, ""):
        with pytest.raises(ReplayError):
            suspected_recomputation(ForeignDuration(0.300, flag=bad))  # type: ignore[arg-type]


def test_a_carrier_answering_no_flag_is_refused() -> None:
    # A carrier that answers no reading has not been measured by feature 252, and
    # feature 253 judges nothing else — a bare duration would be a second
    # comparison of this module's own, which is exactly what the seam refuses.
    class NoFlag:
        __slots__ = ()
        policy_version = POLICY
        world_id = WORLD
        duration_seconds = 0.300

    with pytest.raises(ReplayError):
        suspected_recomputation(NoFlag())


# ---------------------------------------------------------------------------
# A broken carrier is a broken ask, not an alert
# ---------------------------------------------------------------------------


def test_a_bare_number_is_refused_as_a_replay() -> None:
    # A number names no ``(policy, world)`` replay, and 252's record — the
    # measurement *and* the identity it was measured for — is the unit this
    # feature judges.  Refused as a broken ask, never reported as a cost model
    # that broke.
    for bad in (0.300, 1, 0.0):
        with pytest.raises(ReplayError):
            suspected_recomputation(bad)


def test_a_carrier_answering_no_duration_is_refused() -> None:
    # A carrier that answers no ``duration_seconds`` was never measured, so there
    # is no interval for the 200 ms point to have been passed.
    class NoDuration:
        __slots__ = ()
        policy_version = POLICY
        world_id = WORLD
        exceeds_alert_threshold = True

    with pytest.raises(ReplayError) as raised:
        suspected_recomputation(NoDuration())
    assert "measured duration" in str(raised.value)


def test_a_broken_duration_is_refused_as_it_is_read() -> None:
    # The three facts 252's constructor defends, restated for the duck-typed
    # read: a NaN compares false against every threshold and would read as a
    # replay that never exceeded anything, an infinity is a ruler with no end,
    # and a negative duration is a clock read in the wrong order.  The flag is
    # stated rather than derived here so the *duration* is what is refused: the
    # seam reads the duration before the flag, so a fixture deriving its own flag
    # from a duration that is a string would fail inside the fixture and test
    # nothing about the seam.
    for bad in (float("nan"), float("inf"), float("-inf"), -0.001, "0.3", None, True):
        with pytest.raises(ReplayError):
            suspected_recomputation(ForeignDuration(bad, flag=False))  # type: ignore[arg-type]


def test_a_carrier_naming_no_replay_is_refused() -> None:
    # The pair is what an operator bisects on, so a carrier that answers no
    # policy version or no world id gives them nothing to act on — refused with a
    # message naming which of the two was missing.
    for field in ("policy_version", "world_id"):
        carrier = ForeignDuration(0.300)
        setattr(carrier, field, "   ")
        with pytest.raises(ReplayError) as raised:
            suspected_recomputation(carrier)
        assert field in str(raised.value)


def test_a_malformed_instant_is_refused() -> None:
    # The instant is what a monitor orders alerts by; a label that names no
    # instant orders nothing.
    for bad in ("   ", "", 51, object()):
        with pytest.raises(ReplayError):
            suspected_recomputation(measured(0.300), detected_at=bad)  # type: ignore[arg-type]


def test_the_ask_is_validated_before_a_record_exists() -> None:
    # The ordering of every refusal in this member (245's before the tree is
    # read, 251's before the arena is touched, 252's before the clock is read,
    # 254's before the store is opened), restated here: a broken carrier is the
    # caller's to repair, and it must never be reported as a cost model that
    # broke.  Pinned by handing both a broken carrier *and* a malformed instant
    # and reading which refusal answered.
    with pytest.raises(ReplayError) as raised:
        suspected_recomputation(ForeignDuration(0.300, flag=False), detected_at="   ")
    assert "exceeds_alert_threshold" in str(raised.value)


# ---------------------------------------------------------------------------
# The emission is a typed raise carrying its record
# ---------------------------------------------------------------------------


def test_the_emission_raises_the_alert_with_its_record() -> None:
    # Raising *is* the emission, the workspace's alert convention (canary's
    # determinism_broken, nulloracle's unrecoverable_state, snapshot's corruption
    # alert): the caller that catches the alert by type still has the structured
    # record to log, ticket or dispatch — and a caller that knows nothing about
    # alerts cannot miss one.
    with pytest.raises(RecomputationSuspectedError) as raised:
        emit_recomputation_suspected(measured(0.310))
    alert = raised.value.alert
    assert alert is not None
    assert alert.policy_version == POLICY
    assert alert.duration_seconds == 0.310


def test_the_error_carries_the_specs_kind_and_the_consequence() -> None:
    # The message spells the spec's kind, the record's own summary, and §10.4's
    # conclusion with where to look — so an operator paged at three in the
    # morning reads the diagnosis and the next step in one line, composed in one
    # place rather than paraphrased at each raise site.
    with pytest.raises(RecomputationSuspectedError) as raised:
        emit_recomputation_suspected(measured(0.310))
    message = str(raised.value)
    assert RECOMPUTATION_SUSPECTED in message
    assert "cost model" in message
    assert "recomputing rather than reading" in message


def test_the_error_is_the_members_vocabulary_and_not_the_reports() -> None:
    # A caller's single ``except ReplayError`` catches the alert, so the one loud
    # thing a broken cost model produces cannot escape a dreaming loop as an
    # uncaught exception and end the cycle in place of telling the operator.  And
    # it is deliberately *not* a ReplayMetricsError: a caller skipping a bad
    # report must not silently skip the alert — the two have different repairs
    # and the alert must reach an operator from a deployment with no store at all.
    from replay import ReplayMetricsError, ReplayReturnsError, ReplayTreeError

    assert issubclass(RecomputationSuspectedError, ReplayError)
    assert not issubclass(RecomputationSuspectedError, ReplayMetricsError)
    assert not issubclass(RecomputationSuspectedError, ReplayTreeError)
    assert not issubclass(RecomputationSuspectedError, ReplayReturnsError)
    with pytest.raises(ReplayError):
        emit_recomputation_suspected(measured(0.310))


def test_the_error_builder_refuses_anything_but_a_record() -> None:
    # The message is composed from the record's own fields, so an error built
    # from anything else would be an emission with no diagnosis behind it.
    for bad in (0.310, None, "recomputation_suspected", object()):
        with pytest.raises(ReplayError):
            recomputation_suspected_error(bad)  # type: ignore[arg-type]


def test_a_hand_built_error_with_no_record_is_allowed() -> None:
    # The record is present on every emission this module raises; ``None`` is the
    # shape a hand-built error takes, and it must still be constructible — a
    # monitor building its own alert from a log line is not an error case.
    error = RecomputationSuspectedError("a hand-built alert")
    assert error.alert is None


# ---------------------------------------------------------------------------
# The emission is post-hoc, and does not refuse the replay
# ---------------------------------------------------------------------------


def test_the_alert_is_about_a_replay_that_actually_ran() -> None:
    # The measurement and the alert are one lineage: a duration measured off the
    # parent's real timer — over a body that slept a known interval — is the
    # thing this feature judges, and the alert's numbers are that measurement's,
    # not a shape re-derived here.
    with measure_replay(POLICY, WORLD) as timer:
        time.sleep(0.02)  # a replay that read: well under the point
    assert suspected_recomputation(timer.duration) is None
    # And a body long enough to pass the point emits, with the measured span on
    # the record — the whole feature end to end, off the real clock.
    with measure_replay(POLICY, WORLD) as slow:
        time.sleep(0.21)
    alert = suspected_recomputation(slow.duration)
    assert alert is not None
    assert alert.duration_seconds >= 0.21
    assert alert.duration_seconds == slow.duration.duration_seconds


def test_the_alert_cannot_be_emitted_inside_the_measured_region() -> None:
    # A duration is a completed-interval quantity: 252's timer refuses to answer
    # one before the ``with`` block closes, so there is no way to judge a replay
    # mid-flight and the emission is structurally post-hoc.  The alert is a
    # diagnosis about a finished interval, never a gate on a running one.
    timer = measure_replay(POLICY, WORLD)
    with pytest.raises(ReplayError) as raised:
        _ = timer.duration  # asked before the interval closed
    assert "before the replay finished" in str(raised.value)


def test_the_alert_does_not_refuse_the_slow_replay() -> None:
    # 252's law is the parent of this feature — a slow replay is measured and
    # persisted, never refused — and 254 keeps the slow tail as measured.  So the
    # alert is a *diagnosis*: the record exists, the replay's own duration is
    # untouched, and the caller who wants to stop has to decide that itself.
    with measure_replay(POLICY, WORLD) as slow:
        time.sleep(0.21)
    record = slow.duration
    with pytest.raises(RecomputationSuspectedError):
        emit_recomputation_suspected(record)
    # The replay was not refused: its record still answers its measurement and
    # still carries the parent's own two readings.
    assert record.duration_seconds >= 0.21
    assert record.exceeds_alert_threshold is True
    assert record.within_target is False


# ---------------------------------------------------------------------------
# The seam is duck-typed
# ---------------------------------------------------------------------------


def test_a_foreign_carrier_answering_a_measured_replay_is_judged() -> None:
    # The loader imports a member under a synthetic name and re-executes it, so
    # the record a *composed* application's path produced can be a second class
    # object of the same name — an ``isinstance`` would refuse the very duration
    # the deployment measured.  The seam reads what a replay *answers*, so a
    # carrier that answers the four facts is judged exactly like 252's record.
    alert = suspected_recomputation(ForeignDuration(0.310))
    assert alert is not None
    assert alert.policy_version == POLICY
    assert alert.duration_seconds == 0.310
    assert suspected_recomputation(ForeignDuration(0.020)) is None


# ---------------------------------------------------------------------------
# No component, no store, and the public surface
# ---------------------------------------------------------------------------


def test_the_alert_registers_no_component() -> None:
    # A record and a raise are per-replay state, so the member's one @register
    # contribution stays feature 245's stateless facade — and the alert depends
    # on no database and no report, which is why it must be reachable from a
    # deployment that configured neither.  A fresh registry, not the process
    # default: the question is exactly *what does this member register?*
    import replay as replay_module

    from app.module_loader import Registration, scan_components

    member_src = Path(replay_module.__file__).resolve().parent.parent
    components = scan_components(member_src, registry=Registration())
    assert [component.name for component in components] == ["replay"]


def test_the_alert_surface_is_the_members_public_surface() -> None:
    # The package fronts the whole feature — the kind, the record, the reading,
    # the emission and the error — the way it fronts 252's timer and 254's
    # report, so a caller holds one import and no private module path.
    for name in (
        "RECOMPUTATION_SUSPECTED",
        "RecomputationSuspected",
        "RecomputationSuspectedError",
        "emit_recomputation_suspected",
        "recomputation_suspected_error",
        "suspected_recomputation",
    ):
        assert name in replay.__all__, name
        assert getattr(replay, name, None) is not None, name


def test_the_alert_module_holds_no_second_spelling_of_the_threshold() -> None:
    # The threshold lives once, in the parent.  Read off the compiled module's
    # *code* rather than behaviour-tested, because the failure this guards
    # against is a second *spelling of §10.4's point* — a copy of the number that
    # happens to equal it today: once 252's constant is retuned, a copy here
    # would keep alerting at 200 ms and the record, the flag and the page would
    # disagree, the drift the parent's docstring exists to prevent.  Only
    # executable constants count, so the prose above may quote §10.4 freely;
    # what may not exist is a second place the point *decides* anything.  The
    # zero the module does spell is the arithmetic identity in its finiteness and
    # non-negativity checks — a bound, not the point — so it is excluded by
    # value; everything else must arrive by name.
    import ast

    import replay.alert as alert_module

    tree = ast.parse(Path(alert_module.__file__).read_text())
    numbers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and node.value != 0.0
    ]
    assert numbers == [], numbers
    # And the one number it does use arrives by name, from the one spelling.
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "REPLAY_DURATION_ALERT_THRESHOLD" in imported
