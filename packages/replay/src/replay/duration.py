"""Feature 252 — the replay's measured duration: the record the cost model is
stated against, the primitive its children consume.

app_spec.xml, "Replay Engine", feature 252: *System persists the measured
duration of each policy and world replay, which completes in under 50
milliseconds on a single core.*  It declares ``depends_on=251`` — the resident
read that makes a replay cheap — and it is the *measurement* half of the cost
argument the category is made of.  Its parent (feature 251) is what lets a
replay finish in tens of milliseconds rather than re-sweeping Parquet per run;
its two children are both *consumers of the duration this feature measures*:

* feature 253 — *System emits a ``recomputation_suspected`` alert when a replay
  exceeds 200 milliseconds, because the cost model has then broken* — compares
  a measured duration against the broken-cost-model point;
* feature 254 — *System persists replay latency at p50 and p99 into the
  observability metrics store* — aggregates a population of measured durations
  into percentiles.

Neither child can be written until a duration is measured and carried by the
replay first, which is precisely what this feature is: the timing primitive and
the per-replay record they both read.  The whole argument rests on docs
§10.4's two numbers —

    A replay is pure array arithmetic over cached Parquet. Target: **under 50
    ms per (policy, world)** on a single core. … If a replay exceeds ~200 ms,
    something is recomputing rather than reading, and the cost model of the
    architecture has broken.

— and this module spells both once, as the constants the children quote:
:data:`REPLAY_DURATION_TARGET` (the 50 ms the target is) and
:data:`REPLAY_DURATION_ALERT_THRESHOLD` (the 200 ms past which the cost model
has broken).

**This feature measures and persists; it never refuses.**  That is the load-
bearing half of the sentence, and it is worth being exact about why, because the
opposite reading — *a replay that runs over 50 ms is refused* — is the natural
one and it is wrong.  A feature that *refused* a slow replay would contradict
its own children: feature 253 explicitly *permits* a replay to reach 200 ms and
only *alerts* there, and feature 254 persists the whole latency distribution,
slow tail included.  So this module times the replay's own acts and carries the
number, and the enforcement of the number — the alert, the percentile — is the
children's, later.  A :class:`ReplayDuration` answers a duration of any size;
the flags it derives (:attr:`ReplayDuration.within_target`,
:attr:`ReplayDuration.exceeds_alert_threshold`) are readings, not gates.

**What "persists" means here.**  There is no observability member in this
workspace yet — feature 254 would be the first to write one, and this feature
does not build it — so the persistence this feature owns is the *per-replay
record*: a value object that holds the measured duration and the identity of the
replay it measured (the policy version and the world id, the two keys of a
dreaming cycle's ``(policy, world)`` pair) and answers them for the record's
whole lifetime.  It is the same sense in which feature 240 "persists" the
committed pick by carrying it and feature 256's :class:`~scoring.WorldScore`
"persists" its score: the record *is* the persisted value, and the aggregation
of many such records into a store (254's p50/p99) and the alert on one such
record (253) are the consumers that land later.  This feature is the record they
read.

**The clock is ``time.perf_counter()`` and nothing else.**  The measurement is
taken over the whole replay — from the moment the replay opens its transition
over the tree to the moment it produces its result — by reading
:func:`time.perf_counter` at the interval's two ends and subtracting.
:func:`time.perf_counter` is the stdlib clock for elapsed-time measurement:
monotonic, so a sub-50 ms interval cannot read negative, and high-resolution, so
it resolves the interval rather than rounding it to the wall-clock tick.  The
deliberately *not* used clock is :func:`time.time` — wall-clock, non-monotonic,
subject to NTP steps — because a duration measured on a clock that can jump
backwards is not a measurement and 253's threshold comparison and 254's
percentiles would each be measuring against a ruler that moves.  One spelling of
the clock, pinned in this module's single import and in the tests, the same way
feature 256 pins one spelling of the information ratio.

**What this module deliberately does not do.**  It does not *score* — the
per-world objective is feature 256, in the separate ``scoring`` member, and a
duration is not a score.  It does not *aggregate* — the p50/p99 over a
population of replays is feature 254, and a percentile computed here would be a
population this module does not hold.  It does not *alert* — feature 253 emits
the ``recomputation_suspected`` alert, reading the flag this module derives.  It
does not *widen* ``replay_score`` (migration 0109, feature 255) — that table
carries ``policy_version, world_id, beta, score, committed_pick`` and belongs to
a *separate lineage* (``depends_on=250``, not 252), so adding a duration column
there would couple this feature to 255's migration and to scoring's value at a
point this feature does not touch; the record stays this module's own.  And it
does not *time anything downstream of the replay* — the evaluator, the sandbox
and the agent are exactly what features 246 and 247 forbid the replay path from
reaching, so the interval this module measures wraps the replay's own acts (the
walk, the resident read, the scoring arithmetic) and nothing outside them.  The
timer arms and closes over a caller-supplied body and reads no tree, no store,
no arena, no evaluator and no sandbox of its own — which is the structural form
of that prohibition, pinned in a test.

Stdlib only — :mod:`time` for the clock, :mod:`math` for the finite check,
:mod:`typing` for the seam — so importing this member on every factory scan
costs composition nothing, per §12's rule that the replay path may not grow a
numerical stack, and the record it answers carries no numerical dependency a
replay would have to import to be timed.
"""

from __future__ import annotations

import math
import time
from typing import Any, Self

from .errors import ReplayError

__all__ = [
    "REPLAY_DURATION_ALERT_THRESHOLD",
    "REPLAY_DURATION_TARGET",
    "ReplayDuration",
    "measure_replay",
]

#: The per-(policy, world) replay target — docs §10.4's *"under 50 ms per
#: (policy, world) on a single core"*, spelled once as seconds.  This is the
#: number the cost model is stated against and the reading
#: :attr:`ReplayDuration.within_target` compares to; feature 254's latency
#: percentiles are the deployment's report of how close to it the replays run.
#: A later feature that retunes the target quotes this one spelling rather than
#: restating the literal, so the target cannot drift between the record and the
#: percentile.
REPLAY_DURATION_TARGET: float = 0.05

#: The point past which the cost model has broken — docs §10.4's *"if a replay
#: exceeds ~200 ms, something is recomputing rather than reading, and the cost
#: model of the architecture has broken"*, spelled once as seconds.  This is the
#: reading :attr:`ReplayDuration.exceeds_alert_threshold` compares to and the
#: number feature 253's ``recomputation_suspected`` alert quotes; it is four
#: times :data:`REPLAY_DURATION_TARGET`, which is the ordering the alert depends
#: on (a replay can be over target and still below the broken-cost-model point).
#: A later feature that retunes the alert threshold quotes this one spelling.
REPLAY_DURATION_ALERT_THRESHOLD: float = 0.2


# -- the record ---------------------------------------------------------------------------


class ReplayDuration:
    """One (policy, world) replay's measured duration — feature 252.

    The per-replay record the cost model is stated against and features 253 and
    254 consume: it carries the two keys of the replay it measured — the policy
    version and the world id — and the **one measured duration** the replay took
    on a single core, and derives from that one number the two readings the
    children read — :attr:`within_target` (the duration is at or under the 50 ms
    target) and :attr:`exceeds_alert_threshold` (the duration is at or over the
    200 ms point past which the cost model has broken).  The flags are derived,
    never stored: a record that carried a duration *and* a separately-set flag
    could carry the two in contradiction, and a percentile or an alert reading a
    contradictory record would be reading a measurement no one could trust.

    Frozen — ``__slots__`` and no setter expose the stored values; the only
    writable path is the constructor, and the derived flags are read-only
    properties — so a record is the *measurement*, and a measurement that could
    be reassigned after the fact would be a duration no alert and no percentile
    could rely on, the same reason a :class:`~scoring.WorldScore` is frozen on
    the score it started from.  The constructor **trusts** the identity keys it
    is handed — it does not re-validate them — because the caller that
    constructs one directly has already measured; the validation lives at the
    seam that *measures* (:func:`measure_replay`), exactly as
    :class:`~replay.ReplayReturns` trusts a hold the free function has already
    validated.  A caller that hands a negative or non-finite duration here is
    handed a refusal in return, because a duration that is negative or NaN is not
    a measurement — it is a broken clock or a mis-read — and 253's threshold and
    254's percentiles must never aggregate one.

    Usable as the answer :func:`measure_replay` produces, and constructible
    directly by a caller that holds a measured duration and the two keys — the
    two spellings of one record, the same pair :func:`replay.resident_returns`
    and :class:`~replay.ReplayReturns` are.

    Per-replay state, not a component and not ``@register``-ed: it belongs to
    the replay that was timed, the same stance :class:`~replay.ReplayTransition`
    and :class:`~replay.ReplayReturns` take, and for the same reason — a second
    replay is timed into its own record.
    """

    __slots__ = ("_duration_seconds", "_policy_version", "_world_id")

    def __init__(
        self,
        policy_version: str,
        world_id: str,
        duration_seconds: float,
    ) -> None:
        # The constructor trusts the identity keys (they were validated at the
        # measuring seam) but defends the measurement itself: a duration is a
        # completed-interval quantity and must be a real, non-negative number,
        # or the alert and the percentile would be aggregating a value that is
        # not one.  Refused in this member's vocabulary, naming the replay.
        self._policy_version = policy_version
        self._world_id = world_id
        if not isinstance(duration_seconds, (int, float)) or isinstance(
            duration_seconds, bool
        ):
            raise ReplayError(
                f"the measured duration of the replay of policy "
                f"{policy_version!r} against world {world_id!r} is not a "
                f"number — got {duration_seconds!r} "
                f"({type(duration_seconds).__name__}). A replay's duration is "
                "the interval the replay's own acts took on a single core "
                "(feature 252), measured by one monotonic clock read at each end; "
                "a value that is not a number is a clock that was never read or "
                "read wrongly, and feature 253's alert and feature 254's "
                "percentiles must never aggregate a duration that is not one"
            )
        duration = float(duration_seconds)
        if not math.isfinite(duration):  # NaN or either infinity: a duration
            # that is not a finite real number is not a measured interval — a
            # NaN compares false against everything (dropping out of a
            # percentile, reading as "no replay" in a threshold comparison) and
            # an infinity is a ruler with no end — and 253's threshold and
            # 254's percentiles must never aggregate one.
            raise ReplayError(
                f"the measured duration of the replay of policy "
                f"{policy_version!r} against world {world_id!r} is "
                f"{duration!r}. A replay's duration is a finite, real interval "
                "on a single core (feature 252), measured by one monotonic clock "
                "read at each end, and a value that is not finite is not one — "
                "it would compare false against feature 253's threshold or drop "
                "out of feature 254's percentile, so a non-finite duration is a "
                "measurement no alert and no percentile can read"
            )
        if duration < 0.0:
            raise ReplayError(
                f"the measured duration of the replay of policy "
                f"{policy_version!r} against world {world_id!r} is "
                f"negative ({duration!r}). A replay's duration is measured on a "
                "monotonic clock read once at the interval's start and once at "
                "its end (feature 252), so the difference cannot be negative — a "
                "negative duration is a clock read in the wrong order, and a "
                "percentile or a threshold comparison built on it would be "
                "measuring against a ruler that runs backwards"
            )
        # Stored as the validated float so an int literal (a caller that
        # measured a whole-second replay) answers as the float the flags and
        # any consumer compare against.
        self._duration_seconds = duration

    @property
    def policy_version(self) -> str:
        """The policy version this replay was timed on — the ask's first key."""
        return self._policy_version

    @property
    def world_id(self) -> str:
        """The world this replay was timed against — the ask's own spelling."""
        return self._world_id

    @property
    def duration_seconds(self) -> float:
        """The one measured duration the replay took on a single core.

        The interval the replay's own acts took, measured by one monotonic
        clock read at each end.  Never negative, never NaN — the constructor
        refuses both — so a percentile or a threshold comparison reading it can
        trust it.
        """
        return self._duration_seconds

    @property
    def within_target(self) -> bool:
        """Whether this replay met the 50 ms-per-(policy, world) target.

        Derived from the one measured duration against
        :data:`REPLAY_DURATION_TARGET` — at or under it — never stored, so the
        record cannot carry a duration and a contradictory flag.  The reading
        feature 254's latency percentiles are the deployment's report of how
        often this is true.
        """
        return self._duration_seconds <= REPLAY_DURATION_TARGET

    @property
    def exceeds_alert_threshold(self) -> bool:
        """Whether this replay passed the broken-cost-model point.

        Derived from the one measured duration against
        :data:`REPLAY_DURATION_ALERT_THRESHOLD` — at or over the 200 ms point
        past which docs §10.4 says something is recomputing rather than reading
        — never stored.  This is the reading feature 253's
        ``recomputation_suspected`` alert is emitted on; it is independent of
        :attr:`within_target` (a replay at, say, 80 ms is over target and still
        below the alert point), which is why the two are two properties and not
        one negation of the other.
        """
        return self._duration_seconds >= REPLAY_DURATION_ALERT_THRESHOLD

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Deliberately reads the stored fields and derives nothing that could
        # fail: a repr is a debugging aid, and one that raised while an operator
        # was already looking at the duration would be a second refusal at the
        # worst moment.  Names the two keys and the duration in ms, the unit an
        # operator reads the target in.
        return (
            f"ReplayDuration(policy={self._policy_version!r}, "
            f"world={self._world_id!r}, "
            f"duration={self._duration_seconds * 1000:.3f} ms)"
        )


# -- the measurement ----------------------------------------------------------------------


class _ReplayTimer:
    """The armed timer behind :func:`measure_replay` — feature 252's clock half.

    What :func:`measure_replay` hands back from ``__enter__``: it holds the two
    identity keys (validated before the timer was armed) and the clock reading
    taken on entry.  It does nothing on entry but read the clock once — it opens
    no tree, no store, no arena, no evaluator and no sandbox, which is the
    structural form of features 246/247's prohibition (the replay path times its
    own acts and reaches nothing downstream) — and it answers the record only on
    exit, when the interval it measured has closed.  Usable as a context manager
    because the measurement *is* a scope: the block is the replay, the block's
    exit closes the interval and produces the record.
    """

    __slots__ = ("_duration", "_policy_version", "_start", "_world_id")

    def __init__(self, policy_version: str, world_id: str, start: float) -> None:
        # Constructed by `measure_replay`, which has validated the identity
        # keys and read the clock once; the timer holds that one start reading
        # and the record it will answer, unmeasured, until the interval closes.
        self._policy_version = policy_version
        self._world_id = world_id
        self._start = start
        self._duration: ReplayDuration | None = None

    @property
    def duration(self) -> ReplayDuration:
        """The record this timer produced — answered once the interval closed.

        The :class:`ReplayDuration` carrying the measured duration and the two
        identity keys, built on the timer's exit from the single clock reading
        taken there minus the one taken on entry.  Refuses if asked before the
        body ran — a duration is a completed-interval quantity, and a record
        answered before the interval closed would carry no measurement — so the
        record is answered on exit, never on entry.
        """
        if self._duration is None:
            raise ReplayError(
                f"the duration of the replay of policy {self._policy_version!r} "
                f"against world {self._world_id!r} was asked for before the "
                "replay finished. A replay's duration is a completed-interval "
                "quantity (feature 252) — measured by one monotonic clock read at "
                "the interval's end minus the read at its start — and a record "
                "answered before the body ran would carry no measurement; read it "
                "from the timer after the `with` block closes"
            )
        return self._duration

    def __enter__(self) -> Self:
        """The scope's binding — the armed timer, while the replay runs.

        Answers the timer itself, so the block body runs and the record is read
        from :attr:`duration` once the block exits.  It does not read the clock
        a second time here — the entry reading was taken by
        :func:`measure_replay`, before this object existed — and it touches
        nothing but the clock.
        """
        return self

    def __exit__(self, *_exc: object) -> None:
        """The scope's exit — close the interval and produce the record.

        Reads :func:`time.perf_counter` once, subtracts the entry reading, and
        builds the :class:`ReplayDuration` record carrying that measured
        duration and the two identity keys.  Never suppresses (returns
        ``None``): the timing wraps a replay, not an error boundary — a replay
        that raised still consumed a measurable interval on a single core, and
        feature 253's alert is about *a replay that ran*, whatever it returned —
        so the record is produced even when the body raised, and the exception,
        if any, propagates.
        """
        elapsed = time.perf_counter() - self._start
        self._duration = ReplayDuration(
            self._policy_version, self._world_id, elapsed
        )


def measure_replay(policy_version: Any, world_id: Any) -> _ReplayTimer:
    """Time one (policy, world) replay and answer its measured duration — 252.

    The replay path's timing primitive: validate the two identity keys — the
    policy version and the world id, the two keys of a dreaming cycle's
    ``(policy, world)`` pair — and arm a monotonic-clock timer over the replay
    body, so the record the timer produces on exit carries the measured duration
    the cost model is stated against and features 253 and 254 consume.

    ::

        with measure_replay(policy_version, world_id) as timer:
            result = replay(policy, tree, book, epoch)   # the walk, the read, the score
        duration = timer.duration                        # the measured duration

    **The refusal, and it fires before the timer arms.**  ``policy_version`` and
    ``world_id`` are each validated as a non-empty string *before*
    :func:`time.perf_counter` is read — a malformed identity names no
    ``(policy, world)`` pair, and the refusal belongs to the caller's ask, not to
    a measured replay.  Refused in this member's vocabulary, the same law the
    transition and the returns read state, and refused before the clock is read
    so a broken ask never spends the interval it would have measured.

    **The clock is read once here, on entry, and once on the timer's exit.**
    :func:`time.perf_counter` — monotonic, so a sub-50 ms interval cannot read
    negative, and high-resolution, so it resolves the interval — is the only
    clock this module touches; :func:`time.time` (wall-clock, non-monotonic) is
    deliberately not used, for the reason the module docstring gives.  The timer
    this function returns reads nothing but the clock: no tree, no store, no
    arena, no evaluator, no sandbox — the measurement wraps the replay's own
    acts and reaches nothing downstream (features 246/247's prohibition, in the
    timing's structural form).

    Returns the armed :class:`_ReplayTimer`; the :class:`ReplayDuration` record
    is read from its :attr:`~_ReplayTimer.duration` property once the ``with``
    block closes.
    """
    policy = _nonempty_str(policy_version, what="the policy version")
    world = _nonempty_str(world_id, what="the world id")
    start = time.perf_counter()
    return _ReplayTimer(policy, world, start)


def _nonempty_str(value: Any, *, what: str) -> str:
    """A non-empty identity, validated — or refused naming what carried it.

    The ask's first key — the policy version, the world id — and the value every
    refusal of the record carries, so a value that cannot be the id is refused
    here, before the timer arms and before the clock is read, rather than being
    timed and silently answering a record no ``(policy, world)`` pair names.
    """
    if not isinstance(value, str) or not value.strip():
        raise ReplayError(
            f"{what} is a non-empty string — got {value!r} "
            f"({type(value).__name__}), which names no replay. A replay's "
            "duration is measured for one (policy, world) pair (feature 252), "
            "keyed by the policy version and the world id, and a value that is "
            "not a non-empty string names no pair to time; the refusal fires "
            "before the clock is read, so a malformed ask never spends the "
            "interval it would have measured"
        )
    return value
