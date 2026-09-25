"""Feature 328: new orders refused while holding positions, on a stale feed.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 328: *"System
rejects new orders while holding positions when data feed staleness
exceeds the configured threshold."*  ``docs/nullius-tech-architecture.md``
§13.3 line 717 puts the supervisor *"as a separate process with kill
authority over the execution engine"*, and the trigger table directly
below it names this feature's row in four words: **Data feed staleness >
threshold — Halt new orders, hold positions.**  ``docs/alpha-engine-prd.md``
line 476 names the same subject from the product side — *"Staleness
watchdog on the data feed."*

The row is deliberately the *middle* one of the five.  The row above it
(daily loss) flattens; the row below it (clock skew) halts.  This row does
neither, and the difference is the whole feature:

* **It rejects new orders.**  Not by a verb of its own and not through the
  kill channel — by a *live judgement* the order layer performs on its own
  submission path, through
  :meth:`RiskFeedStalenessGuard.require_fresh` (and its module-level
  spelling :func:`require_feed_fresh`).  The feed's silence is not a
  supervisor's decision, it is a fact about a socket, and the process that
  must act on it is the one about to submit.  So the refusal is derived at
  the moment of submission from two readings — when the feed last spoke,
  and what this process's clock says now — and it stops being true by
  itself: §13.3's row is a *watchdog*, and a watchdog that needed an
  operator to clear it would hold the order path shut long after the
  socket recovered.
* **While holding positions.**  The book is left *exactly as it stands*.
  This module flattens nothing, closes nothing, cancels nothing and holds
  no engine face at all — the sentence's own clause *"while holding
  positions"* is a statement about what the system is doing when the
  refusal fires (it is long, not flat), and it is precisely why the action
  cannot be a flatten: a feed that will not tell you what anything is
  worth is the worst moment to sell a book into it, and a supervisor that
  closed every position because a websocket went quiet has converted a
  temporary blindness into a permanent realized loss.  Feature 330's
  flatten and feature 323's halt door are *not* reachable from here; the
  row of §13.3's table that owns them is the daily-loss row above this one.
* **When the staleness exceeds the configured threshold.**  The comparison
  is strictly ``>`` — §13.3's own symbol, and the workspace's boundary
  convention beside it (feature 312's neighbour rule,
  :func:`risk.clock_skew._exceeds`'s ``abs(...) > threshold``, feature
  314's strict ``<``): a feed silent for exactly the band is *inside* it,
  and is not this feature's business.  The threshold is *configuration*,
  not a constant of this module: §13.3 says "threshold" and names no
  number, so it arrives as a required keyword with no default — a watchdog
  that guessed a band would refuse submissions on a silence nobody
  configured it to refuse on.

**The measurement is a pure function over two caller-supplied instants.**
:func:`measure_feed_staleness` takes ``last_message_at`` (when the feed's
most recent message arrived, read off whatever the caller's subscriber
records) and ``now`` (this process's reading of the current instant), and
answers their difference in seconds — so the staleness is reproducible by
any later reader holding the two values, and this module *never reads a
clock to measure one*.  A **negative** age — the feed's last message
stamped after the instant that asked how long it had been silent — is
refused rather than clamped to zero: it is not a silence at all, it is a
reading from a different clock or a different feed, and a clamped zero
would pass every band while the two ends of the measurement disagreed
about what time it was.

**Nothing here is persisted, and that absence is the design.**  This
module owns no table and writes nowhere.  Two reasons, and both are
load-bearing.  First, the *ordering*: a guard that persisted a row per
submission would put a store write on the hot path of every order, which
is exactly the coupling the order layer's process separation exists to
avoid — and a store that cannot be written must not be able to refuse a
submission, because the feed's staleness is a fact about a socket and not
about a database.  Second, the *ownership*: the retention of measured
staleness is feature 350's row in the ``ops`` member (``feed_staleness_s``
in its live-metrics table), and that store's own docstring states the
barrier this module keeps from the other side — it *"computes none of the
four; it accepts a ``(metric, value)`` pair handed over already measured"*,
naming *"the risk member's halt quantity"* as the staleness it is handed.
So the figure travels one way: this module measures, the caller hands it
over.  Feature 329's ``risk_clock_skew`` is likewise not this feature's
table — that is the *clock's* measurement, one row per halting skew, and a
feed's silence is neither a halting nor a clock.

**What this module deliberately does not do.**  It does not *hold the
book*: nothing here knows a position from a price, and the sentence's
clause is the caller's situation rather than a field this module could
check.  It does not *flatten*: that is feature 330's act under feature
323's door, and §13.3's row for it is the daily-loss row, not this one.
It does not *send the kill*: feature 322's channel carries a supervisor's
instruction — a state that stands until a door owns a reset — whereas this
refusal is re-judged on every submission and lifts by itself, so routing
the feed's silence through the monotone channel would leave the order path
killed long after the socket recovered, which is a different feature's
failure mode entirely.  It does not *record*: see the paragraph above.  And
it does not *watch the socket*: nothing here opens a connection,
subscribes to a stream or reads the ingest member's watermark — the
last-message instant is *handed in* by whoever holds the subscription, the
same "hand over, never derive" barrier feature 350 states for its own
staleness metric.

**The band has no environment spelling, deliberately.**  §13.3 says
"threshold" and names no number, and a band that arrived from an
environment variable would be a band a deployment could silently retune
under a running order path — while the *fact* of which band was in force
when a submission was refused is what an operator reconstructs a halt
from.  So the band is passed to the call that judges against it, exactly
as feature 329 requires its own, and the reading carries the band it was
judged against so a later retune cannot re-judge a refusal already taken.

**The absence of a watchdog passes vacuously, and there is only one such
absence.**  A submission path built with no source and no reading is a
deployment with no watchdog wired into it, and :func:`require_feed_fresh`
answers ``None`` for it — the same *"no store, no status"* stance
:func:`risk.require_orders_allowed` takes on an unconfigured channel,
answered as an absence rather than a fabricated zero reading because an
unwatched feed is not a *fresh* feed.  The direction is not split the way
the channel's is, and the reason is structural: this guard is the order
path's own act on its own process's submission path, so there is no second
process whose record would have to be consulted and therefore no second
absence to cut.  A guard that was handed *half* a watchdog — a band with
nothing to read, or a reading with no band — is refused by name instead,
because that caller believes it is watched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .errors import (
    FEED_STALENESS_CODE,
    ORDERS_STALE_CODE,
    RiskFeedStalenessError,
    RiskOrdersStaleError,
)

__all__ = [
    "FALLBACK_FEED_READING_ATTRIBUTES",
    "FeedStaleness",
    "FeedStalenessGuard",
    "FeedStalenessSource",
    "RiskFeedStalenessGuard",
    "measure_feed_staleness",
    "orders_stale_error",
    "read_feed_staleness",
    "require_feed_fresh",
]

#: The attribute names a *caller-supplied* feed source is asked for its
#: last-message instant under, tried in this order.  A source that carries
#: its own reading method wins (see :func:`read_feed_staleness`); these are
#: the duck-typed fallbacks for the plain objects a subscriber, a
#: heartbeat record or the ingest member's own watermark exposes.  Spelled
#: out here rather than imported from any sibling, for the reason every
#: module in this member restates its environment constant: this module
#: reaches into no other member's private vocabulary.  The set is *open* —
#: a caller with a differently-named attribute passes the instant
#: explicitly and uses no source at all.
FALLBACK_FEED_READING_ATTRIBUTES = (
    "last_message_at",
    "last_tick_at",
    "last_seen_at",
)

#: The attribute names a source is looked *through* for its reading, one
#: level down.  A subscriber wrapped in a record, a client wrapped in a
#: session: the two spellings of "the thing that holds the feed" this
#: workspace's members most often expose.
_NESTED_SOURCE_ATTRIBUTES = ("source", "feed")

#: The sentinel :func:`_find_reading` answers for "nothing found" — a
#: distinct object rather than ``None``, because ``None`` is a value a
#: source can legitimately hold and a *missing* reading is a different
#: fact from a reading that is absent.
_NO_READING = object()


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the member's one canonical spelling.

    The same form the channel, the ledger and the clock-skew table store,
    restated here so a refusal's message composes with the instants the
    member's other records already hold rather than deriving a second
    spelling from a sibling's helper.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* the feed last spoke
    or *when* the question was asked, and an age computed from an
    ambiguous instant is a number with no meaning — the same discipline
    :mod:`risk.kill` holds its ``sent_at`` and :mod:`risk.clock_skew` its
    two probe readings to, and the reason it is checked here rather than
    assumed.
    """
    if not isinstance(moment, datetime):
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 328)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: {what} must be timezone-aware; a "
            "staleness measured against a naive reading is a staleness "
            "against no particular instant, and the refusal it caused could "
            "not be ordered against anything (feature 328)"
        )
    return moment


def _require_real(value: object, what: str) -> float:
    """Return ``value`` as a finite real number, or refuse it by name.

    ``bool`` is refused *before* the number check, deliberately and for the
    reason :mod:`risk.clock_skew` and :mod:`ops.live_metrics` refuse it:
    ``isinstance(True, int)`` is true in Python, so a
    ``threshold_seconds=True`` would pass a naive numeric check and refuse
    submissions on a band of one second.  Non-finite values are refused
    too — ``nan`` compares false against everything, so a ``nan`` band
    would make the judgement below answer "inside the band" for a silence
    of any length, which is the one direction a watchdog must never fail
    in.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: {what} must be a real number of seconds, "
            f"got {value!r} ({type(value).__name__}) (feature 328)"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: {what} must be finite, got {value!r}; a "
            "band that is not a number band cannot be exceeded, and a feed "
            "judged against it would be judged against nothing (feature 328)"
        )
    return number


def _require_threshold(value: object) -> float:
    """Return ``value`` as a strictly positive band, or refuse it by name.

    §13.3 says *threshold* and names no number, so the band is
    configuration — but a band of zero or less is not configuration, it is
    a watchdog that refuses every submission: every silence other than
    exactly zero exceeds a non-positive threshold, so a deployment that
    passed one has configured a refusal rather than a tolerance.  The
    refusal is here, in the value layer, and not only at a schema's
    ``CHECK`` (this module owns no schema at all), because this judgement
    is the one that decides whether an order may be submitted.
    """
    number = _require_real(value, "threshold_seconds")
    if number <= 0:
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: threshold_seconds must be greater than "
            f"zero, got {value!r}; every silence other than exactly zero "
            "exceeds a non-positive band, so a threshold of "
            f"{value!r} refuses every submission rather than a stale feed "
            "(feature 328)"
        )
    return number


def _require_bool(value: object, what: str) -> bool:
    """Return ``value`` as a bool, or refuse it by name.

    The one bit on a reading that is *not* arithmetic, and the reason this
    check exists at all is the module's oldest trap: ``isinstance(1,
    bool)`` is false but ``1 == True`` is true, so a truthy-looking
    non-bool would compare equal to a verdict while being a different
    fact — the same near-miss rule :class:`risk.kill.KillInstruction`
    applies to its own ``changed``.
    """
    if not isinstance(value, bool):
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: {what} must be a bool, got {value!r} "
            f"({type(value).__name__}); whether a reading exceeded its band "
            "is one bit, and a truthy-looking non-bool is the value that "
            "would silently misreport a stale feed as a fresh one "
            "(feature 328)"
        )
    return value


# -- The measurement ------------------------------------------------------------


def measure_feed_staleness(*, last_message_at: datetime, now: datetime) -> float:
    """How long, in seconds, the feed has been silent — the measurement.

    Feature 328's first word, and deliberately a *pure function over two
    readings*: ``last_message_at`` is when the feed's most recent message
    arrived (the caller's subscriber, heartbeat or watermark holds it) and
    ``now`` is this process's reading of the current instant, so the result
    is reproducible by any later reader holding the two values — and this
    module never reads a clock to measure one, the same stance
    :func:`risk.measure_clock_skew` takes toward its own two readings.

    The result is ``now - last_message_at`` and it is **non-negative by
    law**.  A last message stamped *after* the instant that asked how long
    the feed had been silent is refused rather than clamped to zero: the
    two ends of the measurement disagree about what time it is, which means
    a different clock or a different feed, and neither is a silence this
    watchdog may certify as safe — a clamped zero would pass every band
    there is.

    Both readings must be timezone-aware.  Two aware readings in different
    zones are the same instant compared correctly — Python subtracts them
    by their UTC offsets — so a feed stamping in ``+00:00`` and a host
    reading in ``+09:00`` need no normalisation here.

    Raises :class:`~risk.errors.RiskFeedStalenessError` for a reading that
    is naive, not a moment at all, or stamped ahead of the question.
    """
    last = _require_aware(last_message_at, "last_message_at")
    moment = _require_aware(now, "now")
    age = (moment - last).total_seconds()
    if age < 0:
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: the feed's last message is stamped "
            f"{_isoformat_utc(last)}, *after* the instant that asked how long "
            f"it had been silent ({_isoformat_utc(moment)}) — an age of "
            f"{age!r}s. A negative age is not a silence: the two ends of the "
            "measurement disagree about what time it is, so they are readings "
            "of different clocks or different feeds, and clamping this to "
            "zero would certify the quietest possible feed as safe "
            "(feature 328)"
        )
    return age


def _exceeds(staleness_seconds: float, threshold_seconds: float) -> bool:
    """Whether a measured staleness exceeds the band — §13.3's ``>``.

    Strictly greater: a feed silent for exactly the band is *inside* it and
    is not this feature's business.  The workspace's boundary convention
    beside it — feature 312's neighbour rule,
    :func:`risk.clock_skew._exceeds`'s own ``abs(...) > threshold``, feature
    314's strict ``<`` — and the reason the boundary tests in this member's
    suite pin equality rather than approximating it.

    There is no absolute value here, where the clock skew's judgement takes
    one: a duration has one direction, and its negative one is refused
    upstream as a contradictory reading rather than measured as a
    magnitude.
    """
    return staleness_seconds > threshold_seconds


# -- The reading ----------------------------------------------------------------


@dataclass(frozen=True)
class FeedStaleness:
    """One staleness reading: how long the feed was quiet, and the verdict.

    A *value* — frozen, self-describing — carrying the whole of feature
    328's condition: the feed's most recent message arrived at
    ``last_message_at``, this process read the current instant at
    ``observed_at``, the difference was ``staleness_seconds``, and the band
    ``threshold_seconds`` was (``exceeded``) or was not broken by it.  It
    is what :func:`measure_feed_staleness`'s result is carried in, what
    :meth:`RiskFeedStalenessGuard.require_fresh` answers for a passing
    feed, and what the raised :class:`~risk.errors.RiskOrdersStaleError`
    rides on — one type for all three, so the refusal's message and the
    measurement behind it cannot be two things that disagree.

    **The arithmetic is re-derived, not trusted.**  ``__post_init__``
    computes ``observed_at - last_message_at`` and refuses a reading whose
    ``staleness_seconds`` disagrees with it, *and* refuses one whose
    ``exceeded`` disagrees with :func:`_exceeds` over its own two numbers.
    There is no table behind this type — the module persists nothing (see
    the module docstring) — and the re-derivation is here anyway, for the
    reason every value in this member re-derives its own terms: a reading
    is *handed around* (to a refusal, to a dashboard, to a fixture in a
    suite) and a hand-built one that disagreed with its own instants would
    launder a stale feed into a fresh one, or a refusal into an
    unjustified stop, at exactly the point where the numbers are the only
    testimony.

    ``exceeded`` is carried rather than being a property, and the pair of
    instants is kept beside the age, both deliberately.  The carried
    verdict is the question a reader of a refusal actually asks — *was this
    submission refused under a band it broke?* — and it is checked rather
    than computed so the reading cannot *become* a different verdict by
    being read; the instants are kept as the pair feature 329 keeps its two
    probe readings, so a reader who trusts neither the writer nor its
    subtraction can re-derive the age themselves.
    """

    #: When the feed's most recent message arrived, timezone-aware — the
    #: half of the measurement the caller's subscriber holds, and the
    #: instant the refusal's message renders so an operator can see *since
    #: when* the socket has been quiet.
    last_message_at: datetime
    #: When the current instant was read, timezone-aware — the caller's
    #: half of the measurement, passed to the guard once per judgement and
    #: used for both the subtraction and the reading's own label, so the
    #: measurement and the judgement cannot be microseconds apart.
    observed_at: datetime
    #: The measured silence: ``observed_at - last_message_at``, in seconds,
    #: non-negative by law, re-derived in :meth:`__post_init__`.
    staleness_seconds: float
    #: The configured band the reading was judged against.  §13.3 says
    #: "threshold" and names no number, so this is configuration the caller
    #: supplied — strictly positive — carried on the reading so a later
    #: retune cannot re-judge a refusal already taken.
    threshold_seconds: float
    #: Whether this reading broke its band.  The verdict: ``True`` is the
    #: refusal's precondition, ``False`` is the passing half the guard
    #: answers normally.  Carried and *checked* rather than derived on
    #: read — see this class's docstring.
    exceeded: bool

    def __post_init__(self) -> None:
        last = _require_aware(self.last_message_at, "last_message_at")
        moment = _require_aware(self.observed_at, "observed_at")
        object.__setattr__(
            self, "threshold_seconds", _require_threshold(self.threshold_seconds)
        )
        staleness = _require_real(self.staleness_seconds, "staleness_seconds")
        if staleness < 0:
            raise RiskFeedStalenessError(
                f"{FEED_STALENESS_CODE}: staleness_seconds must be "
                f"non-negative, got {self.staleness_seconds!r}; a negative "
                "silence is not a silence, and a reading wearing one could "
                "not have been taken from a feed at all (feature 328)"
            )
        expected = (moment - last).total_seconds()
        if staleness != expected:
            raise RiskFeedStalenessError(
                f"{FEED_STALENESS_CODE}: staleness_seconds {staleness!r} "
                f"disagrees with its own instants — observed_at "
                f"{_isoformat_utc(moment)} minus last_message_at "
                f"{_isoformat_utc(last)} is {expected!r}; the two readings are "
                "the measurement and the number beside them is their "
                "difference, so a reading where they disagree is one no "
                "refusal can be reconstructed as (feature 328)"
            )
        object.__setattr__(self, "staleness_seconds", staleness)
        exceeded = _require_bool(self.exceeded, "exceeded")
        judged = _exceeds(staleness, self.threshold_seconds)
        if exceeded != judged:
            raise RiskFeedStalenessError(
                f"{FEED_STALENESS_CODE}: a reading of {staleness!r}s against "
                f"the {self.threshold_seconds!r}s band is "
                f"{'outside' if judged else 'inside'} it, but this reading "
                f"states exceeded={self.exceeded!r}; the verdict and the "
                "arithmetic are one fact, and a reading where they disagree "
                "would either refuse a submission on a feed inside its band "
                "or wave one through past it (feature 328)"
            )
        object.__setattr__(self, "exceeded", exceeded)

    @property
    def summary(self) -> str:
        """One sentence: how long the feed was quiet, and against what band.

        Composed rather than stored, for the reason every ``summary`` in
        this member composes: every part is already a field, and a stored
        copy would disagree with an edited one.  The verdict is spelled
        explicitly and the last message's own instant is rendered in the
        canonical UTC form, so an operator reading a log line can answer
        *how long*, *since when* and *was it over the band* without a
        second query — the three questions a stalled socket raises, in the
        order they are asked.
        """
        verdict = "exceeded" if self.exceeded else "within"
        return (
            f"the data feed has been silent for "
            f"{self.staleness_seconds:.6f}s — its last message was at "
            f"{_isoformat_utc(self.last_message_at)}, read at "
            f"{_isoformat_utc(self.observed_at)} — {verdict} the "
            f"{self.threshold_seconds:.6f}s band"
        )


# -- The source -----------------------------------------------------------------


@runtime_checkable
class FeedStalenessSource(Protocol):
    """What this module asks for *when the feed last spoke*.

    A caller-supplied, duck-typed seam — the same shape :mod:`risk.flatten`
    gives its execution engine face and feature 350 gives the figure it is
    handed: this module imports no subscriber, no websocket client and no
    ingest member, so the contract is checked where it is used rather than
    by an ``isinstance`` against a class no deployment could satisfy.

    One method, because one fact is wanted.  A source that can answer
    :func:`read_feed_staleness` *is* a source, at any nesting; a source
    that cannot is asked for its last-message instant under each name in
    :data:`FALLBACK_FEED_READING_ATTRIBUTES`.  The protocol is
    ``runtime_checkable`` so a caller can ask; nothing inside this module
    gates on it, because a plain object carrying the right attribute is
    every bit as good as one that declares the method, and refusing the
    former would be this module enforcing a spelling rather than a fact.
    """

    def read_feed_staleness(self) -> datetime:
        """When the feed's most recent message arrived, timezone-aware."""
        ...  # pragma: no cover - protocol declaration


def _call_reading(found: object) -> object:
    """Return a found reading, calling it when it is a callable fact.

    A source exposing ``last_message_at`` as a *method* is the same fact in
    a different spelling, and a callable that answers a moment is a moment.
    A ``datetime`` that happens to be callable — it is not, but a subclass
    could be — is the moment itself and is left alone, because calling the
    moment would be this module inventing a second question.
    """
    if isinstance(found, datetime) or not callable(found):
        return found
    return found()


def _find_reading(source: object) -> object:
    """The reading ``source`` carries, or :data:`_NO_READING`.

    Nearest wins, and a method beats an attribute at each level:
    :func:`read_feed_staleness` states the order and why.  Spelled once so
    the resolution order lives in one place: a second spelling would be a
    second order, and the two would drift apart on the first source that
    carried two of the names at once.
    """
    reader = getattr(source, "read_feed_staleness", None)
    if callable(reader):
        return reader
    for name in FALLBACK_FEED_READING_ATTRIBUTES:
        found = getattr(source, name, _NO_READING)
        if found is not _NO_READING:
            return found
    for nested_name in _NESTED_SOURCE_ATTRIBUTES:
        nested = getattr(source, nested_name, _NO_READING)
        if nested is _NO_READING or nested is None:
            continue
        nested_reading = _find_reading(nested)
        if nested_reading is not _NO_READING:
            return nested_reading
    return _NO_READING


def read_feed_staleness(source: object) -> datetime:
    """Ask ``source`` when the feed last spoke — the one resolution.

    Feature 328's guard is handed *something* that knows the feed's
    liveness — a subscriber, a heartbeat record, the ingest member's own
    watermark — and this function is how that thing is asked, so the
    question is spelled once rather than at every call site.

    The resolution order, and the reason for it:

    * **nearest wins.**  The object handed in is asked before anything it
      holds: a wrapper answering for itself has answered, and reaching
      through it to a nested object would be asking a different object the
      question the caller aimed at this one.
    * **at each level, a method beats an attribute.**  A
      ``read_feed_staleness()`` method wins outright, because a source that
      answers the question itself has answered it and its answer is by
      construction the one it meant to give; otherwise each name in
      :data:`FALLBACK_FEED_READING_ATTRIBUTES` is read in order — the
      plain shape a subscriber or a heartbeat record most often wears.
    * **then one level down**, through a ``source`` or ``feed`` attribute,
      by the same two rules.
    * a value that is callable and is not a ``datetime`` is *called*,
      because a source exposing ``last_message_at`` as a method is the same
      fact in a different spelling.

    The nesting is one level deep and no further, deliberately: a
    recursive walk would make *"which object did this reading come from?"*
    unanswerable in a log line, and a caller with a deeper structure passes
    the instant explicitly — the guard's ``last_message_at`` keyword, the
    escape hatch every duck-typed seam in this workspace leaves open.

    Raises :class:`~risk.errors.RiskFeedStalenessError` when the source
    carries no reading this module can find, naming the attributes it
    looked for: a source that cannot say when the feed last spoke is not a
    source, and a guard that silently answered "fresh" for it would be the
    one failure this feature exists to prevent.
    """
    found = _find_reading(source)
    if found is _NO_READING:
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: a feed staleness source must be able to "
            "say when the feed's most recent message arrived — a "
            "read_feed_staleness() method, or one of "
            f"{list(FALLBACK_FEED_READING_ATTRIBUTES)} (at this level or one "
            "level down through a 'source'/'feed' attribute); got "
            f"{source!r} ({type(source).__name__}), which answers none of "
            "them. A source that cannot say when the feed last spoke cannot "
            "be judged, and a watchdog that passed its submissions vacuously "
            "would trade through the silence it exists to catch "
            "(feature 328)"
        )
    return _require_aware(_call_reading(found), "last_message_at")


# -- The refusal ----------------------------------------------------------------


def orders_stale_error(staleness: FeedStaleness) -> RiskOrdersStaleError:
    """Build the order path's refusal from its reading — the one spelling.

    The refusal's message is composed from the reading's own fields, so the
    log line an operator reads and the reading the guard took say the same
    thing — the same reason :func:`risk.orders_killed_error` exists rather
    than letting every caller compose its own message.  The consequence is
    stated in the operator's terms and in §13.3's own words: new orders are
    refused **while the positions held stand**, and the feed's recovery is
    what lifts the refusal — no operator action, no reset, no door.

    That last clause is the difference between this refusal and the kill's,
    and it is spelled out in the message deliberately: an operator paged by
    this error must not go looking for the halt door, because the door
    sends a monotone kill and this socket will recover on its own.
    """
    if not isinstance(staleness, FeedStaleness):
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: orders_stale_error takes a FeedStaleness "
            "— the reading of how long the feed has been silent — got "
            f"{staleness!r} ({type(staleness).__name__}); the refusal's "
            "message is composed from the reading's own fields, and an error "
            "built from anything else would be a refusal with no measurement "
            "behind it (feature 328)"
        )
    return RiskOrdersStaleError(
        f"{ORDERS_STALE_CODE}: {staleness.summary}; new order submission is "
        "refused while the positions held stand — §13.3's *halt new orders, "
        "hold positions* — and the refusal lifts by itself the moment the "
        "feed speaks again, because this is a live reading of the socket "
        "rather than a kill that stands until a door resets it. The book is "
        "left exactly as it stands: selling into a feed that cannot tell you "
        "what anything is worth is the worst moment to flatten (feature 328)",
        staleness,
    )


# -- The guard ------------------------------------------------------------------


class RiskFeedStalenessGuard:
    """Refuses new orders while the data feed is stale; holds the book.

    Constructed with the band in force and, optionally, the source it reads
    the feed's liveness from.  The guard holds no state beyond those two —
    no memo of the last reading, no flag that a staleness was once seen —
    because a refusal remembered in a guard would be a refusal the next
    submission would not re-derive: the feed's silence ends by itself, and
    the only honest answer to *"may I submit now?"* is the one taken from
    the socket's own last message at the moment the question is asked.

    That statelessness is the whole difference between this guard and
    feature 322's :func:`risk.require_orders_allowed`, and the reason
    §13.3's table needs both rows: the kill is a *state*, so the guard that
    reads it answers the same thing forever until a door clears it; the
    staleness is a *reading*, so the guard that takes it answers something
    different on the very next call.  Neither is the other's special case,
    and a caller that must trade consults both.
    """

    def __init__(
        self,
        threshold_seconds: float,
        *,
        source: object | None = None,
    ) -> None:
        """Hold the configured band, and the source the feed is read from.

        The band is validated *here*, at construction, rather than only at
        each judgement: a guard built with a band that is not a band is a
        guard that cannot judge anything, and an order path that discovered
        that at its first submission would have refused or traded on a
        number nobody could evaluate.

        With no ``source`` the guard still answers — a caller that passes
        ``last_message_at`` to each call (a replay, a test, a caller whose
        own structure is deeper than :func:`read_feed_staleness` reaches)
        needs no source at all.  A guard with neither a source on it nor a
        reading at the call is refused at the call, by name; see
        :meth:`read`.
        """
        self._threshold_seconds = _require_threshold(threshold_seconds)
        self._source = source

    # -- Construction -------------------------------------------------------

    @property
    def threshold_seconds(self) -> float:
        """The band this guard judges the feed's silence against."""
        return self._threshold_seconds

    @property
    def source(self) -> object | None:
        """The feed liveness this guard reads, or ``None`` when unwatched."""
        return self._source

    # -- The judgement -------------------------------------------------------

    def read(
        self, *, now: datetime, last_message_at: datetime | None = None
    ) -> FeedStaleness:
        """Take one staleness reading — the guard's eyes, without refusing.

        The measurement half of :meth:`require_fresh`, exposed on its own
        so a caller that wants the number — a dashboard tile, a log line, a
        test pinning the arithmetic — can have it without a refusal, and so
        that the *same* reading is what a refusal rides on rather than a
        second one taken a moment later.  A caller measuring for feature
        350's ``feed_staleness_s`` row reads here and hands the figure over;
        this module never writes it.

        ``now`` is required rather than defaulted to ``datetime.now()``, and
        that is the feature rather than an inconvenience: this module never
        reads a clock to measure a staleness (see the module docstring), so
        the caller that judges is the one holding the instant it judged at
        — and a caller that wants the bank of the world's clock passes what
        it holds.  ``last_message_at`` overrides the source — the escape
        hatch a caller with a deeper structure than
        :func:`read_feed_staleness` can reach uses, and the one a replay of
        a recorded session needs.

        Raises :class:`~risk.errors.RiskFeedStalenessError` for a reading
        that is naive, not a moment, or stamped ahead of the question; for
        a guard that has neither a source nor a ``last_message_at`` to read
        from; and for a source that carries no reading at all.  The band's
        own terms were judged at construction.
        """
        moment = _require_aware(now, "now")
        last = (
            _require_aware(last_message_at, "last_message_at")
            if last_message_at is not None
            else self._read_source()
        )
        age = measure_feed_staleness(last_message_at=last, now=moment)
        return FeedStaleness(
            last_message_at=last,
            observed_at=moment,
            staleness_seconds=age,
            threshold_seconds=self._threshold_seconds,
            exceeded=_exceeds(age, self._threshold_seconds),
        )

    def require_fresh(
        self, *, now: datetime, last_message_at: datetime | None = None
    ) -> FeedStaleness:
        """The guard: pass while the feed is inside the band, refuse outside.

        The read-time judgement the order layer's submission path consults,
        and the whole of feature 328's sentence at its seam.  A feed silent
        for longer than the configured band raises
        :class:`~risk.errors.RiskOrdersStaleError` carrying the reading, so
        the caller that reaches for an order learns *how long* the feed has
        been quiet, *since when*, and *against what band* — without a second
        query.  A feed inside the band answers normally, with its reading,
        so the caller that wants to log the gauge has it.

        **The book is not touched, and that is the sentence's own clause.**
        Nothing in this call closes a position, cancels an order or reads an
        engine: *"while holding positions"* describes what the caller is
        doing, and §13.3's action for this row is *halt new orders, hold
        positions* precisely because a feed that cannot price a book is the
        worst moment to sell one.  A caller that flattens on this refusal
        has skipped the row of the trigger table that owns it.

        **Nothing is recorded.**  This module holds no table and writes
        nowhere, deliberately: a guard that persisted a row per submission
        would put a store write on the hot path of every order, and the
        retention of measured staleness is feature 350's row in the ``ops``
        member — handed the figure by whoever measured it.  What a caller
        wants recorded, it hands over.
        """
        reading = self.read(now=now, last_message_at=last_message_at)
        if reading.exceeded:
            raise orders_stale_error(reading)
        return reading

    # -- The source plumbing -------------------------------------------------

    def _read_source(self) -> datetime:
        """The last-message instant this guard's source carries.

        Refused by name when the guard holds no source, because the
        alternative — asking :func:`read_feed_staleness` about ``None`` —
        would answer with a message about an object the caller never
        supplied, and the repair here is a different sentence entirely:
        *build the guard with a source, or pass the reading*.
        """
        if self._source is None:
            raise RiskFeedStalenessError(
                f"{FEED_STALENESS_CODE}: this guard holds no feed staleness "
                "source, and the call passed no last_message_at, so there is "
                "no reading to judge; build the guard with the subscriber, "
                "heartbeat record or watermark that knows when the feed last "
                "spoke, or pass the instant itself — a watchdog with a band "
                "and nothing to read cannot see the feed (feature 328)"
            )
        return read_feed_staleness(self._source)


#: The guard's shorter handle.  A second name for one class is normally a
#: second thing to keep in sync, and it is stated here deliberately:
#: ``RiskFeedStalenessGuard`` is the class's own name, and
#: ``FeedStalenessGuard`` is the handle the member's package surface and
#: this module's docstrings use.  The alias is *the same class*, not a
#: subclass, so ``isinstance`` agrees across both spellings.
FeedStalenessGuard = RiskFeedStalenessGuard


# -- The module-level spelling ---------------------------------------------------


def require_feed_fresh(
    *,
    now: datetime,
    threshold_seconds: float | None = None,
    last_message_at: datetime | None = None,
    source: object | None = None,
) -> FeedStaleness | None:
    """The guard, opening its own reading — the order path's one call.

    Feature 328's refusal at the seam a submission path consults, in the
    shape :func:`risk.require_orders_allowed` gives feature 322's: a caller
    that must submit asks one function and either gets the reading back or
    catches :class:`~risk.errors.RiskOrdersStaleError`.

    **With no threshold and nothing to read, this passes vacuously** and
    answers ``None`` — a deployment with no watchdog wired into its order
    path has no band to judge a silence against, and passing is the same
    *"no store, no status"* stance the kill guard takes on an unconfigured
    channel.  The answer is ``None`` rather than a fabricated zero reading,
    deliberately: an unwatched feed is not a *fresh* feed, and a caller that
    mistook one for the other would trade believing a watchdog had been
    running — so the reading's absence has to be visible in the return
    value, for exactly that reason.

    With a threshold, the judgement is the guard's own: the band is
    validated (a band that is not a band refuses every submission, so it is
    refused here rather than judged against), the source is asked for the
    feed's last message — or ``last_message_at`` is used directly — and a
    silence past the band raises.  ``now`` is required and never defaulted,
    because this module reads no clock to measure a staleness, so a caller
    always states the instant it judged at and a refusal is always orderable
    against it.

    **Half a watchdog is refused, not silently completed.**  A band with
    nothing to read, a source with no band, a reading with no band: each is
    a caller that believes it is watched, and each is refused by name
    rather than judged against nothing or answered "fresh" from a last
    message this function invented.
    """
    if threshold_seconds is None:
        if source is not None or last_message_at is not None:
            raise RiskFeedStalenessError(
                f"{FEED_STALENESS_CODE}: require_feed_fresh was handed "
                f"{'a feed staleness source' if source is not None else 'a last_message_at'}"
                " and no threshold_seconds, so there is no band to judge the "
                "silence against; §13.3 says 'threshold' and names no number, "
                "so the band is configuration the caller supplies — a "
                "watchdog with a reading and no band is half a watchdog, and "
                "judging against nothing would leave the submissions it "
                "believes are watched entirely unguarded (feature 328)"
            )
        return None
    guard = RiskFeedStalenessGuard(threshold_seconds, source=source)
    if source is None and last_message_at is None:
        raise RiskFeedStalenessError(
            f"{FEED_STALENESS_CODE}: require_feed_fresh was handed the "
            f"{threshold_seconds!r}s band and nothing to judge — no source "
            "and no last_message_at; a watchdog with a band and no reading "
            "cannot see the feed, and answering 'fresh' for it would be this "
            "function inventing a last message it was never given "
            "(feature 328)"
        )
    return guard.require_fresh(now=now, last_message_at=last_message_at)
