"""Feature 253 — the ``recomputation_suspected`` alert past 200 milliseconds.

app_spec.xml, "Replay Engine", feature 253: *System emits a
``recomputation_suspected`` alert when a replay exceeds 200 milliseconds, because
the cost model has then broken.*  It declares ``depends_on=252`` — the measured
duration — and it is the **one place a slow replay produces a loud thing**.  Its
parent (252) measures one (policy, world) replay's duration and carries it on a
:class:`~replay.duration.ReplayDuration` record, deriving the reading
:attr:`~replay.duration.ReplayDuration.exceeds_alert_threshold` from the one
measured number; its sibling (254) aggregates a *population* of those records
into p50/p99 and persists the slow tail as measured, never refusing it.  This
feature is the judgment on *one* record: when the flag is set, the replay did not
read — something recomputed — and the cost model of the architecture has broken.

**The argument is docs §10.4's third sentence, and it is the whole feature:**

    A replay is pure array arithmetic over cached Parquet. Target: **under 50 ms
    per (policy, world)** on a single core. At 200 worlds × 40 policy revisions
    that is ~400 core-seconds per dreaming cycle, embarrassingly parallel. If a
    replay exceeds ~200 ms, something is recomputing rather than reading, and
    the cost model of the architecture has broken.

The sentence names a *diagnosis*, not a failure of the replay's result: a slow
replay is still a correct replay, and §10.4 does not say to throw it away.  What
it says is that the deployment is no longer running the architecture it thinks it
is — the resident read of feature 251 has stopped being resident, or the walk
stopped being a walk — and an operator has to be told.  So the emission is an
**alert**, never a refusal of the replay.

**The reading is 252's flag, never a second comparison.**  This module compares
nothing itself: it reads ``exceeds_alert_threshold`` off the record — the flag
:mod:`replay.duration` derives from the measured number — and quotes
:data:`~replay.duration.REPLAY_DURATION_ALERT_THRESHOLD` for the record's own
``threshold_seconds`` and for one self-consistency check.  The reason is the one
252's docstring states for having spelled the number once: *"a later feature that
retunes the alert threshold quotes this one spelling"*, so a re-tuned 200 ms
cannot drift between the flag the record derives, the record this module emits
and the message an operator pages on.  A second ``duration >= 0.2`` written here
would be a second place the threshold lives — exactly the duplication
:mod:`replay.metrics` refused on its side (*"not a second place the threshold
could live"*).

**The self-consistency check is what makes the flag trustworthy off a foreign
carrier.**  The seam is duck-typed (the loader's synthetic-name wrinkle, below),
so a carrier this module did not construct owes the proof 252's constructor
stands behind: a carrier whose flag *disagrees with its own duration* is refused.
A carrier claiming "not suspected" at 300 ms would silently drop the alert — the
one failure this feature exists to prevent — and a carrier claiming "suspected"
at 3 ms would page an operator about a replay that read.  Both are refused in
this member's vocabulary rather than believed, the same discipline
:class:`~canary.DreamHalt` applies to a halt that disagrees with its own
arithmetic (``deviation != abs(score - recorded_score)``).

**The emission is a typed raise, and the ``if`` not taken returns ``None``.**
The workspace's alert convention is *build a record, then raise it*
(:func:`canary.halt_dreaming` raising
:class:`~canary.CanaryDeterminismBrokenError`,
:func:`nulloracle.emit_unrecoverable_state` returning
:class:`~nulloracle.UnrecoverableStateError`, :func:`snapshot.corruption_error`
building :class:`~snapshot.SnapshotCorruptionError`).  :func:`canary.halt_dreaming`
is the closest analogue and the shape this feature copies exactly: §12's ``if abs(
score - CANARY_EXPECTED) > 1e-12`` **not** taken returns ``None`` and writes
nothing, and the branch taken persists and raises.  A caller therefore holds one
verb — :func:`emit_recomputation_suspected` — that is silent on a healthy replay
and loud on a broken cost model, and catching the alert by type
(:class:`RecomputationSuspectedError`) still leaves the record on the error for a
log line, a ticket or a monitor.

**The emission is post-hoc, and structurally cannot fire early.**  A duration is
a completed-interval quantity: :attr:`~replay.duration._ReplayTimer.duration`
refuses before the ``with measure_replay(...)`` block closes.  So the earliest
moment this alert can exist is the moment *after* the replay finished, when the
measured number is finally known — which is the honest order for a diagnosis
about a completed interval, and it is why the emission needs no guard of its own.
The alert refuses the **silence** about a broken cost model, never the replay:
252's law (*measures and persists; never refuses a slow replay*) is untouched,
and 254's store still keeps the slow tail as measured.

**No store, and that is a decision rather than an omission.**  Feature 254's
sentence names one (*"into the observability metrics store"*); this feature's
names none — it names an *alert*.  The in-repo precedent for a record plus a
typed raise with no table behind it is :mod:`snapshot`'s corruption alert, which
:func:`snapshot.verify_tree` answers as data and
:func:`snapshot.corruption_error` raises; :func:`emit_unrecoverable_state`
likewise works with ``journal=None`` by design (*"the alert has to survive exactly
the processes that are already unhealthy"*).  Writing a second table here would
also be a second spelling of one fact: the slow replay's ``duration_seconds``
already lands in 254's ``samples`` — the source of truth of the population that
record belongs to — and a second ``DATABASE_URL`` reader in this member would be
a second thing to keep in sync with the store contract the sibling owns.  What
makes the alert durable is the caller's logger or monitor; what makes it
*emitted* is the raise, and that is by construction unmissable.

**What this module deliberately does not do.**  It does not *halt dreaming* — a
broken cost model is §15's *"revert to stored-float artifacts"*, not §12's
``halt_dreaming`` for a determinism break, and stopping the pool for a timing
observation would be a second feature wearing this one's verb.  It does not
*refuse the replay* — 252 explicitly permits a replay to reach 200 ms and only
alerts there; the number is a diagnosis, not a gate.  It does not *aggregate* —
p50/p99 over a population is 254's, and an alert on one record is not a
percentile.  It does not *grade against the 50 ms target* — a replay at 80 ms is
over target and below the alert point, and that third state is 252's two
independent readings, not a second alert kind here.  And it does not *re-measure*
— the duration it judges is the one the caller hands it, so the alert never costs
a replay.

**The clock split, and it is the same split 254 makes.**  The one wall-clock read
here stamps the record's ``detected_at``: *when the alert was emitted*, a label,
never a measurement.  The only clock a *duration* is ever read from remains 252's
:func:`time.perf_counter`, and nothing in this module subtracts two wall-clock
readings or compares a duration against one — a record stamped by NTP is a
mis-labelled alert, while a duration measured on a clock that can jump backwards
is not a measurement at all, and only the second is this feature's parent's law.

**The seam is duck-typed, because a member never imports another member — not
even its own past.**  The durations this module judges are feature 252's records,
but the seam does not ``isinstance`` them: the module loader imports a member
under a synthetic name and re-executes it, so the record a *composed*
application's path produced can be a second class object of the same name and an
``isinstance`` would refuse the very duration the deployment measured.  The seam
reads what a duration *is* — ``duration_seconds``, ``exceeds_alert_threshold``,
``policy_version`` and ``world_id`` — and validates each as it is read.  A bare
number is refused: it names no ``(policy, world)`` replay, and the identity is
half of what 252's record persists.

**No component, and the member's one ``@register`` contribution is untouched.**
A record and a raise are per-replay state, the stance 252's record, 254's report,
251's read and 245's transition all take, so nothing here is composed and nothing
here can spend I/O inside ``create_app()``.

Stdlib only — :mod:`datetime` for the record's label, :mod:`math` for the finite
check, :mod:`typing` for the seam — no numerics, no Polars, no PyArrow, so
importing this member on every factory scan still costs composition nothing, per
§12's rule that the replay path may not grow a numerical stack.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .duration import REPLAY_DURATION_ALERT_THRESHOLD
from .errors import RecomputationSuspectedError, ReplayError

__all__ = [
    "RECOMPUTATION_SUSPECTED",
    "RecomputationSuspected",
    "emit_recomputation_suspected",
    "recomputation_suspected_error",
    "suspected_recomputation",
]

#: The alert's kind — the spec's own spelling, verbatim.  app_spec.xml feature
#: 253: *"System emits a ``recomputation_suspected`` alert"*.  Not a free-form
#: message field and not a paraphrase: the word is what an operator greps for and
#: what a monitor dispatches on, so an alert a reader cannot find by the name the
#: spec gave it is an alert the spec did not get.  The sibling alerts in this
#: workspace spell theirs the same way — :data:`canary.DETERMINISM_BROKEN`,
#: :data:`nulloracle.keyalert.ALERT_KIND` — and for the same reason.
RECOMPUTATION_SUSPECTED = "recomputation_suspected"


# -- the record ---------------------------------------------------------------------------


class RecomputationSuspected:
    """One replay's ``recomputation_suspected`` alert — feature 253's record.

    Built by :func:`suspected_recomputation` and carried on
    :attr:`RecomputationSuspectedError.alert` when
    :func:`emit_recomputation_suspected` raises, so the exception is the emission
    and this is the payload — the shape :class:`~canary.DreamHalt`,
    :class:`~nulloracle.UnrecoverableState` and ``snapshot``'s
    ``CorruptionAlert`` all take, and the reason a caller that catches the alert
    to keep reporting still has everything it needs to log, ticket or dispatch.

    Every field is a fact an operator acts on, and each is one 252's record
    already carries:

    * :attr:`policy_version` and :attr:`world_id` — *which* replay recomputed.
      The pair is the unit a dreaming cycle is measured in (§10.3's 200 worlds ×
      40 policy versions), so it is the pair an operator bisects on;
    * :attr:`duration_seconds` — the measured interval, in the second 252 pinned
      its record in.  The number the diagnosis was made *on*;
    * :attr:`threshold_seconds` — the point it passed, quoted from
      :data:`~replay.duration.REPLAY_DURATION_ALERT_THRESHOLD`.  Carried rather
      than assumed, so an operator reading a record from an older deployment can
      see which threshold the diagnosis was made under if the number is ever
      retuned — the discipline :class:`~canary.DreamHalt`'s ``tolerance`` field
      states for §12's ``1e-12``;
    * :attr:`alert_kind` — always :data:`RECOMPUTATION_SUSPECTED`, carried on the
      thing rather than left to its position in a tuple;
    * :attr:`detected_at` — when the emission was stamped (ISO-8601 UTC).

    Frozen — ``__slots__`` and no setter expose the stored values; the only
    writable path is the constructor — because a record is the *diagnosis*, and a
    diagnosis that could be reassigned after the fact would be an alert no
    monitor could rely on, the same reason 252's record is frozen on the duration
    it started from.

    Usable as the answer :func:`suspected_recomputation` produces, and
    constructible directly by a caller that holds the four facts and wants a
    record — the two spellings of one record, the same pair
    :func:`replay.resident_returns` and :class:`~replay.ReplayReturns` are.  The
    constructor **trusts** the facts it is handed in the sense that it does not
    re-derive them from a duration: the reading lives at the seam that *reads*
    (:func:`_reading_of`), exactly as :class:`~replay.ReplayDuration` trusts the
    identity keys a measuring caller has already validated — but it does defend
    the arithmetic's own consistency, refusing a record whose duration does not
    sit at or past its own threshold, because such a record is not a diagnosis
    any replay produced.

    Per-replay state, not a component and not ``@register``-ed: it belongs to the
    replay that recomputed, the same stance :class:`~replay.ReplayTransition`,
    :class:`~replay.ReplayDuration` and :class:`~replay.ReplayLatency` take, and
    for the same reason — a second slow replay is emitted into its own record.
    """

    __slots__ = (
        "_alert_kind",
        "_detected_at",
        "_duration_seconds",
        "_policy_version",
        "_threshold_seconds",
        "_world_id",
    )

    def __init__(
        self,
        policy_version: str,
        world_id: str,
        duration_seconds: float,
        *,
        alert_kind: str = RECOMPUTATION_SUSPECTED,
        threshold_seconds: float = REPLAY_DURATION_ALERT_THRESHOLD,
        detected_at: str = "",
    ) -> None:
        # The kind is checked first, and it is the spec's one word: a record
        # carrying any other kind would be an alert no reader of
        # recomputation_suspected could find — the refusal every alert record in
        # this workspace states for its own spelling.
        if alert_kind != RECOMPUTATION_SUSPECTED:
            raise ReplayError(
                f"a recomputation alert's kind is the spec's "
                f"{RECOMPUTATION_SUSPECTED!r}, got {alert_kind!r}. Feature 253's "
                "alert has exactly one kind, and a record carrying any other "
                "word is an alert no operator grepping for "
                "recomputation_suspected and no monitor dispatching on it could "
                "find"
            )
        self._alert_kind = alert_kind
        self._policy_version = policy_version
        self._world_id = world_id
        self._threshold_seconds = _threshold(threshold_seconds)
        self._duration_seconds = _measured(duration_seconds, policy_version, world_id)
        if self._duration_seconds < self._threshold_seconds:
            # The record's own arithmetic, defended at construction: a
            # recomputation alert exists because a replay passed the
            # broken-cost-model point, and a record whose duration sits *below*
            # its own threshold is a page about a replay that read — no
            # deployment measured one, and a monitor trusting it would be
            # chasing a cost model that had not broken.
            raise ReplayError(
                f"a recomputation alert claims the replay of policy "
                f"{policy_version!r} against world {world_id!r} recomputed at "
                f"{self._duration_seconds!r} s, which is below its own "
                f"threshold of {self._threshold_seconds!r} s. Feature 253's "
                "alert is emitted on a replay that passed docs §10.4's "
                "broken-cost-model point, so a record whose duration does not "
                "reach its own threshold is a diagnosis no replay produced and "
                "an operator would be paged about a replay that read"
            )
        self._detected_at = _instant(detected_at)

    @property
    def alert_kind(self) -> str:
        """The alert's kind — always :data:`RECOMPUTATION_SUSPECTED`.

        Carried on the record so a reader dispatching on the kind reads it from
        the thing itself rather than from its position in a tuple, and validated
        at construction so a stored or hand-built record wearing another word
        fails loudly instead of paging the wrong channel.
        """
        return self._alert_kind

    @property
    def policy_version(self) -> str:
        """The policy version this replay was measured on — 252's first key."""
        return self._policy_version

    @property
    def world_id(self) -> str:
        """The world this replay was measured against — 252's second key."""
        return self._world_id

    @property
    def duration_seconds(self) -> float:
        """The measured duration the diagnosis was made on, in seconds.

        The very number :attr:`~replay.ReplayDuration.duration_seconds` carried,
        read off the record by :func:`suspected_recomputation` and validated as
        it was read — never re-derived, never re-measured: this feature judges
        the measurement it is handed and costs no replay of its own.
        """
        return self._duration_seconds

    @property
    def threshold_seconds(self) -> float:
        """The broken-cost-model point this replay passed, in seconds.

        Quoted from :data:`~replay.duration.REPLAY_DURATION_ALERT_THRESHOLD` —
        docs §10.4's *"~200 ms"*, spelled once by feature 252 — and carried on
        the record so the threshold a diagnosis was made under travels with it.
        Same role :class:`~canary.DreamHalt`'s ``tolerance`` field plays for
        §12's ``1e-12``.
        """
        return self._threshold_seconds

    @property
    def detected_at(self) -> str:
        """When the alert was emitted (ISO-8601 UTC, second resolution).

        A **label**, never a measurement: the one wall clock this module reads,
        and it stamps the emission rather than timing anything.  The only clock a
        duration is ever read from remains 252's :func:`time.perf_counter`.
        """
        return self._detected_at

    def summary(self) -> str:
        """Render the diagnosis as the line an operator or a monitor reads.

        The kind, the replay's pair, the two numbers in ms — the unit docs §10.4
        states the target and the point in — and then the conclusion §10.4 draws,
        in its own words.  Deterministic for a given record, so two renderings of
        one alert are byte-identical and a log, a diff or a test can compare
        them.
        """
        return (
            f"{self._alert_kind}: the replay of policy "
            f"{self._policy_version!r} against world {self._world_id!r} took "
            f"{self._duration_seconds * 1000:.3f} ms, past the "
            f"{self._threshold_seconds * 1000:.3f} ms point at which docs §10.4 "
            "says something is recomputing rather than reading and the cost "
            "model of the architecture has broken"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Deliberately reads the stored fields and derives nothing that could
        # fail: a repr is a debugging aid, and one that raised while an operator
        # was already looking at the alert would be a second refusal at the worst
        # moment.  Names the pair and the two numbers in ms, as 252's repr does.
        return (
            f"RecomputationSuspected(policy={self._policy_version!r}, "
            f"world={self._world_id!r}, "
            f"duration={self._duration_seconds * 1000:.3f} ms, "
            f"threshold={self._threshold_seconds * 1000:.3f} ms)"
        )


# -- the emission -------------------------------------------------------------------------


def suspected_recomputation(
    duration: Any, *, detected_at: str | None = None
) -> RecomputationSuspected | None:
    """Read one measured replay and answer the alert it warrants, or ``None``.

    Feature 253's reading half, and the whole of its decision: read 252's
    :class:`~replay.duration.ReplayDuration` record — duck-typed, so the record a
    *composed* application's path produced is read exactly like one this module
    imported — and answer a :class:`RecomputationSuspected` when the replay passed
    docs §10.4's broken-cost-model point, ``None`` when it did not.

    ``None`` is the honest answer for a replay that read rather than recomputed,
    and it is the same shape :meth:`~replay.ReplayTransition.transition` answers
    for an unexpanded node and :func:`~replay.ReplayEngine.tree`'s absence has:
    *nothing to report* is a value, not an exception, so a dreaming loop can sweep
    eight thousand replays and act on the ones that returned something.

    **The reading is the flag 252 derives, never a second comparison.**  The
    decision reads ``exceeds_alert_threshold`` off the record — the reading
    :mod:`replay.duration` computes from the one measured number against the one
    spelling of the 200 ms point — and then *checks* it against the duration it
    also read, refusing a carrier whose flag disagrees with its own arithmetic.
    That check is what makes a duck-typed flag trustworthy: a carrier claiming
    "fine" at 300 ms would silently drop the alert this whole feature exists to
    raise, and a carrier claiming "suspected" at 3 ms would page an operator about
    a replay that read.  Either is refused rather than believed, the discipline
    :class:`~canary.DreamHalt` applies to a halt disagreeing with its own
    deviation.

    **The refusal is this member's vocabulary, and it fires before anything is
    built.**  A bare number names no replay and is refused (252's record, not the
    number, is the unit this feature judges); a carrier that answers no
    ``duration_seconds`` is refused naming it; a duration that is not a finite,
    non-negative real is refused (a NaN compares false against every threshold, an
    infinity is a ruler with no end, and a negative duration is a clock read in
    the wrong order); a flag that is not a bool is refused; a carrier disagreeing
    with its own arithmetic is refused.  All in :class:`~replay.ReplayError`, so a
    caller's single ``except ReplayError`` catches every way an alert can fail to
    be one — and the ordering of every refusal in this member holds here too: the
    ask is validated before a record exists, so a broken carrier is never
    reported as a break.

    **A replay over the threshold is *permitted* and this function says so.**
    Nothing here refuses, clips or re-measures the replay: the record it answers
    is a *diagnosis*, and 252's law — a slow replay is measured and persisted, not
    refused — is the parent of this feature.  A caller that wants the replay to
    stop has to decide that itself; §15's recovery for a broken cost model is to
    revert to stored-float artifacts, not to discard the replay.

    Args:
        duration: The measured replay to judge — feature 252's record, read
            duck-typed (see the module docstring).
        detected_at: The instant the alert is stamped with, an ISO-8601 UTC
            string.  Defaults to *now*; a caller that is replaying a stored log
            or a test passes it so the record's label matches the emission it is
            reconstructing rather than the moment of the reconstruction.

    Returns:
        The :class:`RecomputationSuspected` record when the replay passed the
        broken-cost-model point, ``None`` when it did not.
    """
    flag, duration_seconds, policy_version, world_id = _reading_of(duration)
    if not flag:
        # §12's `if` was not taken, read on this feature's side: the replay came
        # in at or under docs §10.4's point, so it read rather than recomputed and
        # there is nothing to alert on.  A quiet return is the whole of the
        # not-taken branch — a dreaming cycle that ran clean must observe nothing
        # but its own loop continuing.
        return None
    return RecomputationSuspected(
        policy_version,
        world_id,
        duration_seconds,
        alert_kind=RECOMPUTATION_SUSPECTED,
        threshold_seconds=REPLAY_DURATION_ALERT_THRESHOLD,
        detected_at=detected_at if detected_at is not None else _isoformat_now(),
    )


def recomputation_suspected_error(
    alert: RecomputationSuspected,
) -> RecomputationSuspectedError:
    """Build the refusal from its record — the one spelling of the emission.

    The spec's kind plus the record's own summary plus the consequence docs §10.4
    draws, so the page an operator reads and the record the caller holds say the
    same thing — the same reason :func:`canary.determinism_broken_error` and
    :func:`snapshot.corruption_error` exist rather than letting every raise site
    compose its own message.  The consequence is spelled once, here, because
    "the cost model of the architecture has broken" is a sentence an operator
    decides against at three in the morning and it must not be paraphrased
    differently at each call site.
    """
    if not isinstance(alert, RecomputationSuspected):
        raise ReplayError(
            f"recomputation_suspected_error takes the RecomputationSuspected "
            f"record of the alert — got {alert!r} "
            f"({type(alert).__name__}). The message is composed from the "
            "record's own fields, and an error built from anything else would be "
            "an emission with no diagnosis behind it"
        )
    return RecomputationSuspectedError(
        f"{alert.summary()} — a replay that recomputes rather than reads "
        "collapses the cost advantage the whole architecture rests on "
        "(docs §1, P5), so the cost model is suspect: check that the campaign "
        "returns read is the resident array (feature 251) and that the walk is "
        "reading recorded children (feature 245) before the next dreaming cycle",
        alert,
    )


def emit_recomputation_suspected(
    duration: Any, *, detected_at: str | None = None
) -> None:
    """Emit feature 253's alert for one measured replay — or return quietly.

    The feature's verb, and the whole sentence of app_spec.xml feature 253:
    *System emits a ``recomputation_suspected`` alert when a replay exceeds 200
    milliseconds, because the cost model has then broken.*  Read the measured
    replay, and when it passed docs §10.4's point, emit the alert — the record,
    then the typed raise carrying it — and when it did not, return ``None`` and
    write nothing.

    **Raising is the emission, and the record is the payload.**  That is the
    stance :mod:`canary._halt` takes for ``determinism_broken`` and
    :mod:`snapshot` takes for its corruption alert, and it is the only shape that
    makes an alert *catchable*: a monitor can ``except
    RecomputationSuspectedError`` and read :attr:`RecomputationSuspectedError.alert`
    to route, log or count it, and a caller that does not know about alerts at all
    still cannot miss one — an alert that could only be observed by opting in
    would be exactly the silence this feature exists to break.

    **The two branches are one verb on purpose.**  Splitting them (`is_suspected`
    plus `alert`) would make it possible to ask the question and forget to act on
    the answer — the failure mode a dreaming loop sweeping thousands of replays
    would find, and the reason :func:`canary.halt_dreaming` folds §12's ``if`` and
    its ``alert(...)`` into one call.  A caller that wants only the record (a
    reporter collecting them, a test) asks :func:`suspected_recomputation`, which
    is the same read without the raise.

    **The alert does not stop anything.**  A slow replay is still a *correct*
    replay: this call refuses the silence about a broken cost model, never the
    replay itself, and it halts no dreaming.  §15's recovery for this row is to
    revert the replay path to stored-float artifacts and re-check the resident
    read, which is an operator's act — the alert's job is to tell them, not to
    decide for them.

    Args:
        duration: The measured replay to judge — feature 252's record, read
            duck-typed and validated by :func:`suspected_recomputation`.
        detected_at: The instant the alert is stamped with, an ISO-8601 UTC
            string; defaults to *now*.

    Raises:
        RecomputationSuspectedError: The alert, when the replay passed the
            broken-cost-model point.  Carries the
            :class:`RecomputationSuspected` record on its ``alert`` attribute.
        ReplayError: When ``duration`` is not a measured replay — a bare number,
            a carrier answering no duration, a duration that is not a finite
            non-negative real, a flag that is not a bool, or a carrier whose flag
            disagrees with its own duration.  This is *not* the alert: a broken
            carrier is a broken ask, and it must not be reported as a cost model
            that broke.
    """
    alert = suspected_recomputation(duration, detected_at=detected_at)
    if alert is None:
        # `return None` spelled out rather than a bare `return`, against RET501:
        # this function's contract is "the alert or nothing", and the explicit
        # value is the not-taken branch's whole content — the same spelling
        # `canary.halt_dreaming` and `nulloracle.emit_unrecoverable_state` use
        # for theirs.  A bare `return` reads as an early exit from something,
        # which is the opposite of what this line means.
        return None
    raise recomputation_suspected_error(alert)


# -- the reads the seam performs ----------------------------------------------------------


def _reading_of(duration: Any) -> tuple[bool, float, str, str]:
    """One record's reading, its duration and its identity — read or refused.

    The one place the seam is touched: the carrier's four facts are read and each
    is defended as it is read — an identity that is a non-empty string, a duration
    that is a finite non-negative real (the three facts 252's constructor
    defends, restated because a duck-typed carrier owes the proof a constructor no
    longer stands behind), and a flag that is a genuine bool agreeing with its own
    duration.  Returned as one tuple so :func:`suspected_recomputation` decides on
    a population of facts that were validated together, never on a read that could
    have changed under it.

    The order is deliberate: the *identity* is validated before the numbers, so a
    refusal about a malformed carrier names the replay it is about wherever it
    can, and 252's own refusal order (identity before the clock) is restated here
    for the same reason.
    """
    policy_version = _identity(duration, "policy_version")
    world_id = _identity(duration, "world_id")
    seconds = _duration_seconds(duration, policy_version, world_id)
    flag = _flag(duration, policy_version, world_id)
    if flag != (seconds >= REPLAY_DURATION_ALERT_THRESHOLD):
        # The flag is a *derived* reading — 252 computes it from the one duration
        # against the one spelled threshold and stores neither — so a carrier
        # whose flag disagrees with its own duration is not a record any
        # measurement produced.  Both directions are load-bearing: a false flag
        # over a slow replay silently drops the alert this feature exists to
        # raise, and a true flag over a fast one pages an operator about a replay
        # that read.
        raise ReplayError(
            f"the measured replay of policy {policy_version!r} against world "
            f"{world_id!r} reports exceeds_alert_threshold={flag!r} at "
            f"{seconds!r} s, which disagrees with its own duration: feature 252 "
            f"derives the reading from the measured number against the "
            f"{REPLAY_DURATION_ALERT_THRESHOLD!r} s point, so at or past it the "
            "flag is True and below it the flag is False. A record that "
            f"contradicts its own arithmetic would either drop feature 253's "
            "recomputation_suspected alert over a replay that recomputed, or "
            "raise it over one that read — and neither is a diagnosis any "
            "measurement produced"
        )
    return (flag, seconds, policy_version, world_id)


def _identity(carrier: Any, name: str) -> str:
    """One of the replay's two identity keys, validated — or refused.

    The policy version and the world id are the keys 252's record carries and the
    pair an operator bisects on (§10.3's 200 worlds × 40 policy versions), so a
    carrier that answers anything but a non-empty string there names no replay
    this alert could be about.  Refused with a message that says which of the two
    was missing, because *which key* is the first thing the caller has to fix.
    """
    value = getattr(carrier, name, None)
    if not isinstance(value, str) or not value.strip():
        raise ReplayError(
            f"the replay a recomputation alert was read from answers no {name}: "
            f"got {value!r} ({type(value).__name__}). Feature 253 alerts on one "
            "measured (policy, world) replay — feature 252's record, keyed by the "
            "policy version and the world id — and a carrier that names no replay "
            "gives an operator nothing to bisect on; a bare number is refused for "
            "the same reason, since it carries no identity at all"
        )
    return value


def _duration_seconds(carrier: Any, policy_version: str, world_id: str) -> float:
    """The carrier's measured duration, validated — or refused.

    The three facts 252's constructor defends, restated for the duck-typed read:
    a duration is a real, finite, non-negative number, or it is not a measured
    interval.  A NaN is the sharpest of the three — it compares false against
    *every* threshold, so a carrier carrying one would read as a replay that
    never exceeded anything — and an infinity is a ruler with no end.
    """
    value = getattr(carrier, "duration_seconds", None)
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise ReplayError(
            f"the replay of policy {policy_version!r} against world {world_id!r} "
            f"answers no measured duration — got {value!r} "
            f"({type(value).__name__}). Feature 253 judges the duration feature "
            "252 measured and persisted on the per-replay record; a carrier that "
            "answers no ``duration_seconds`` was never measured, so there is no "
            "interval for the 200 ms broken-cost-model point to have been passed "
            "and no alert to emit"
        )
    seconds = float(value)
    if not math.isfinite(seconds):
        raise ReplayError(
            f"the measured duration of the replay of policy {policy_version!r} "
            f"against world {world_id!r} is {seconds!r}. A replay's duration is a "
            "finite, real interval on a single core (feature 252), measured by "
            "one monotonic clock read at each end, and a value that is not finite "
            "is not one — a NaN compares false against every threshold and would "
            "read as a replay that never exceeded anything, and an infinity is a "
            "ruler with no end, so neither is a duration feature 253 could raise "
            "an alert on"
        )
    if seconds < 0.0:
        raise ReplayError(
            f"the measured duration of the replay of policy {policy_version!r} "
            f"against world {world_id!r} is negative ({seconds!r}). A replay's "
            "duration is measured on a monotonic clock read once at each end "
            "(feature 252), so the difference cannot be negative — a negative "
            "duration is a clock read in the wrong order, and an alert built on "
            "it would be judging against a ruler that runs backwards"
        )
    return seconds


def _flag(carrier: Any, policy_version: str, world_id: str) -> bool:
    """The carrier's ``exceeds_alert_threshold`` reading, validated.

    The one reading feature 253 decides on, read off the record rather than
    recomputed here (see the module docstring), and defended as a genuine bool:
    a truthy string or a ``1`` smuggled in from a serialised row would decide the
    emission by accident, and *whether a page goes out* is one bit that must not
    be inferred from a value that merely looks true.
    """
    value = getattr(carrier, "exceeds_alert_threshold", None)
    if not isinstance(value, bool):
        raise ReplayError(
            f"the measured replay of policy {policy_version!r} against world "
            f"{world_id!r} answers exceeds_alert_threshold={value!r} "
            f"({type(value).__name__}), which is not a bool. Feature 252's record "
            "derives that reading as the comparison of one measured duration "
            "against the broken-cost-model point, and whether feature 253's alert "
            "goes out is exactly that one bit — a truthy-looking non-bool is the "
            "value that would page an operator, or fail to, by accident"
        )
    return value


def _threshold(value: Any) -> float:
    """The record's threshold, validated — a positive, finite real.

    Always :data:`~replay.duration.REPLAY_DURATION_ALERT_THRESHOLD` when this
    module builds the record, but the constructor is also this seam's own
    spelling (a caller reconstructing an alert from a log), so the number is
    defended: the diagnosis is *a duration at or past a positive point*, and a
    threshold that is not a positive finite real would make the record's own
    consistency check meaningless.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReplayError(
            f"a recomputation alert's threshold is a real number of seconds — "
            f"got {value!r} ({type(value).__name__}). The threshold is docs "
            "§10.4's broken-cost-model point (feature 252's "
            "REPLAY_DURATION_ALERT_THRESHOLD), and a value that is not a number "
            "is not the point a replay passed"
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ReplayError(
            f"a recomputation alert's threshold is a positive, finite real — got "
            f"{number!r}. The threshold is the point past which docs §10.4 says "
            "something is recomputing rather than reading, and a value that is "
            "not a positive finite number bounds no interval a replay could have "
            "passed"
        )
    return number


def _measured(value: Any, policy_version: str, world_id: str) -> float:
    """The record's duration, validated at construction.

    The same three facts the seam's read defends, restated for the direct
    constructor: a caller that hand-builds an alert owes the record a measured
    interval, and a record carrying a NaN or a negative would be a diagnosis no
    duration supports.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReplayError(
            f"the duration of the replay of policy {policy_version!r} against "
            f"world {world_id!r} in a recomputation alert is a real number of "
            f"seconds — got {value!r} ({type(value).__name__}). The alert is a "
            "diagnosis of a measured interval (feature 252), and a value that is "
            "not a number is not one"
        )
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ReplayError(
            f"the duration of the replay of policy {policy_version!r} against "
            f"world {world_id!r} in a recomputation alert is a finite, "
            f"non-negative real — got {number!r}. A replay's duration is a "
            "measured interval on a single core (feature 252), and a value that "
            "is not one is not a measurement an alert could be built on"
        )
    return number


def _instant(value: Any) -> str:
    """The record's label — the caller's, or the wall clock's now.

    ``detected_at`` defaults to *now* (UTC, second resolution — the spelling
    :meth:`~datetime.datetime.isoformat` produces and the one 254's store keys
    its rows under), because a caller reconstructing an alert from a log or a
    test passes the instant it happened so the label matches the emission rather
    than the reconstruction.  An explicit instant must be a non-empty string — it
    is what a monitor orders alerts by, and a label that names no instant orders
    nothing.  This wall-clock read is a **label, never a measurement**: the only
    clock a duration is read from remains 252's :func:`time.perf_counter`.
    """
    if value is None:
        return _isoformat_now()
    if not isinstance(value, str) or not value.strip():
        raise ReplayError(
            f"a recomputation alert's detected_at is an ISO 8601 UTC string — "
            f"got {value!r} ({type(value).__name__}). The instant is what a "
            "monitor orders alerts by and what an operator measures an outage "
            "against (feature 253); pass the instant the alert was emitted, or "
            "nothing and let the record stamp its own"
        )
    return value


def _isoformat_now() -> str:
    """The current instant as ISO-8601 UTC text, second resolution.

    Microseconds are dropped rather than rounded, the same spelling
    :func:`replay.metrics` uses for its snapshot key, so a stamp is never
    *after* the instant it names and two alerts an instant apart still order
    correctly in a monitor's view.
    """
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
