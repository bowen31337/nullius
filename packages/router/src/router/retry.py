"""The exponential backoff and jitter that answer a refusal — feature 319.

app_spec.xml, "Order Routing & Venue Filters", feature 319: *System retries
a rate-limited request with exponential backoff plus jitter, which emits one
retry event per attempt.*  ``docs/nullius-tech-architecture.md`` §13.2 states
the whole contract as one line of the execution engine's — *"Token-bucket
rate limiter matched to the venue's weight schedule, with exponential
backoff and jitter."* — and that line is two features with a comma between
them: everything before the comma is feature 318's (the bucket that spends
and refuses, :mod:`router.limiter`), and the clause after it is this
module's.  ``docs/alpha-engine-prd.md`` C9 says the same thing in its own
words: *"Rate-limit-aware order router with exponential backoff."*

**Two features, one seam — and the seam is the refusal.**  318 refuses
without waiting ("a limiter that waited would be that feature arriving early
and invisibly", its own docstring says); this module waits without metering.
They meet at exactly one object: :class:`~router.errors.RouterRateLimitedError`,
which *carries* the :class:`~router.limiter.RateLimitHeadroom` it was refused
by.  Every figure this module paces by is read off that refusal — the
operation, the scope, the deficit, and above all
:attr:`~router.limiter.RateLimitHeadroom.retry_after` — so this module never
opens the bucket, never queries the limiter, and holds no second spelling of
any number the reading already carries.  That is what 318 bought by carrying
the headroom: *"so that the feature that does wait (319's backoff and
jitter) can read how far short the bucket fell without a second query."*

**What retries — only the rate limit, and only the rate limit.**  The
request callable is retried when, and only when, it raises
:class:`~router.errors.RouterRateLimitedError`.  The class hierarchy does
the sorting: the schedule and bucket faults are *siblings* of the refusal
under :class:`~router.errors.RouterRateLimitError`, so they propagate
untouched — a mis-stated weight schedule is wiring, not contention, and
retrying it would sleep out a budget for a request that can never be priced.
Anything else the request raises propagates on the first attempt too: a
venue rejection is feature 320's record, a dead socket is the transport's
own repair, and a retry that swallowed either would answer *"sent"* for a
request that was not.

**Exponential, and exponential off the refusal's own floor.**  The wait for
attempt *n* is ``retry_after × multiplier**(n-1)`` — the *floor* doubling by
default, not a constant this module invented.  Two reasons, and both are the
sentence's.  First, the base of the exponent had to come from somewhere, and
the one number that is already exact, already venue-matched and already on
the refusal is ``retry_after`` — a hardcoded *"one second"* would be a
venue constant the order path was forbidden (feature 311), wearing a
backoff's clothes.  Second, *exponential* rather than constant: a refusal
means the budget is spent, and a caller that re-asks at a fixed pace is
asking a still-spent budget on schedule; each consecutive refusal says the
budget was spent *by more than the last wait covered*, so the wait grows
with every attempt rather than hoping the Nth identical ask finally lands.
The arithmetic is exact — an integer multiplier on a
:class:`~datetime.timedelta`, whole microseconds, no float in the term (the
discipline :mod:`router.limiter` keeps for its refill).

**The floor is a law, and nothing this module does can break it.**  The
jittered delay is chosen *above* the refusal's ``retry_after`` — 318's
docstring states this as the hand-off, and this module pins it three ways:
the exponential term is at least the floor by construction, the jitter is
*added* (never subtracted — see below), and a caller-stated ceiling below
the floor still loses to the floor.  Waking before the floor is a
*guaranteed* re-refusal: the weight the request needs cannot have accrued,
so the attempt is burned on arithmetic that was known before the sleep
started.  A backoff that can wake early is not pacing the venue; it is
spending the retry budget to discover the same refusal.

**The ceiling is the venue's own window, by default.**  A wait longer than
the schedule's window waits for nothing: the allowance is the bucket's
capacity *and* its refill rate, so a fully-drained bucket is whole again
within one window — waiting past it is waiting for a budget that has
already come back.  The default ceiling is therefore read off each refusal's
own schedule (``headroom.schedule.window``), and it always sits above the
floor: ``retry_after`` is the deficit times one unit's interval, the deficit
is strictly less than the allowance (318 refuses a request priced above it),
and the allowance's intervals floor to at most the window.  A deployment may
state its own ceiling; one that states a ceiling *below* a floor gets the
floor anyway, for the reason the paragraph above gives.

**Plus jitter — added above the term, never drawn across it.**  The draw is
uniform in ``[0, jitter_fraction × backoff]`` and it is *added* to the term.
The jitter exists because the exponential term is a computation two routers
can make identically: a fleet refused by one shared budget all doubles the
same floor, and without jitter they wake on the same microsecond and
re-collide — the exact fleet-synchronization argument 318's docstring hands
over ("a fleet of routers all waking on the same exact microsecond would
re-collide, so the jittered delay is 319's to choose").  It is added rather
than spread across ``[0, backoff]`` — the classic "full jitter" — because a
spread can draw *below the floor*, and the floor is a law (see above).  The
draw is floored to whole microseconds, so the realized jitter never exceeds
its own bound.  A jitter fraction of zero is refused at construction: that
is the synchronized wake the sentence's *"plus jitter"* exists to prevent,
not a tuning a deployment is offered.

**The budget is the caller's, and there is no default.**  ``retries`` is
required, exactly as :func:`discovery.retry.retry_interrupted` states its
own: a default would be this module inventing a rate-limit policy, and
§13.2 gives no number.  It is the number of re-sends this call may make —
``retries=3`` means up to four sends and at most three events.  When the
budget is spent and the request is still refused, the standing refusal
**re-raises**: 318's own argument, inherited — it made refusal an error
rather than a flag because *"a record saying 'not allowed' would leave
enforcement to every call site"*, and an exhausted retry that returned a
flagged non-answer would rebuild precisely that at one remove.  The standing
refusal is the *freshest* reading, and it still carries its headroom, so
the caller that must act on it holds the same value it would have caught
without the retry.

**One retry event per attempt.**  The sentence's second clause, and it is
an *emission*, not a return: every attempt this call makes hands exactly
one :class:`RateLimitRetryEvent` to the ``on_retry`` sink before it sleeps
— before, deliberately, so an operator watching the pacing live sees the
wait that is starting, not the one that already happened.  The count law:
a request that succeeds first try emits nothing (no retry happened), a
request refused N times within the budget emits exactly N, and an exhausted
call emits exactly ``retries`` — the terminal refusal re-raises rather
than attempting, so it emits no event either.  The event carries the whole
decision — the operation, the budget's scope, the attempt's number, the
deficit, the floor, the capped exponential term, the drawn jitter, the
total delay, and the reading's own moment — so an operator reading the
pacing never re-derives it, and its kind rides along as data
(:data:`RATE_LIMIT_RETRY_EVENT`) so a sink routing several event kinds
dispatches on the string without importing this class (the rule
``nullius_ingest.gaps`` states for its own events).  :class:`RetryEventLog`
is the standard sink.  The event is built even when no sink is wired, so
the value's own law holds of every attempt, sinked or not.  A sink that
raises stops the retry: the emission is part of the attempt, and a broken
sink is a wiring fault to surface, not a fact to swallow.

**No clock of its own.**  Every moment the event names came off the
refusal's reading (``observed_at``); this module never asks what time it
is.  Time passes through exactly one injectable seam — ``sleep`` — and the
jitter through another — ``jitter_rng`` — so the retry can be reasoned
about, and tested, without waiting, the discipline
:meth:`~router.limiter.RouterRateLimiter.acquire` keeps for its own
``now``.  The defaults are the real ones: :func:`time.sleep` and a
:class:`~random.SystemRandom`, because on the live host this module really
does close its eyes.

**No component, and 244's reason rather than a borrowed one.**  The retry
exists for the length of one call, holds no state between calls, and takes
its whole policy — budget, backoff, sink — from the caller on each ask, so
a builder would have to bake a pacing no deployment stated.  The member
still registers exactly one component (feature 310's exchangeInfo store),
and the order path reaches this verb the only way the spec allows: by
calling it with its own budget and its own sink.

Stdlib only, and import-cheap: nothing at module scope but ``random``,
``threading``, ``time`` and a dataclass over this member's own values, so
the factory's scan pays nothing for the backoff and a composed application
that is never refused never sleeps for one.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import (
    RETRY_BACKOFF_CODE,
    RouterRateLimitedError,
    RouterRetryError,
)

__all__ = [
    "DEFAULT_BACKOFF_SCHEDULE",
    "DEFAULT_JITTER_FRACTION",
    "DEFAULT_MULTIPLIER",
    "RATE_LIMIT_RETRY_EVENT",
    "BackoffSchedule",
    "RateLimitRetryEvent",
    "RetryEventLog",
    "retry_rate_limited",
]

#: The kind of event a retry attempt emits — the spelling an operator or a
#: sink greps and routes on, exactly as ``nullius_ingest.gaps`` fixes
#: ``gap_detected`` for its own events.  It names the *cause* (a rate limit)
#: and the *act* (a retry) rather than either alone, because both halves are
#: load-bearing: a retry event that named only "retry" would be greppable
#: against retries this module never makes, and one that named only
#: "rate_limited" would collide with :data:`~router.errors.RATE_LIMITED_CODE`'s
#: grep, which the *refusal* owns — the two are one pipeline apart and
#: different facts.
RATE_LIMIT_RETRY_EVENT = "rate_limit_retry"

#: The default multiplier: each attempt waits twice the refusal's floor.
#: The classic doubling — not a venue constant (the venue publishes no
#: backoff; §13.2's sentence delegates the pacing to the system) and not a
#: law (a deployment states its own :class:`BackoffSchedule`), only the
#: shape a caller with nothing to state gets.
DEFAULT_MULTIPLIER = 2

#: The default jitter fraction: the draw may add up to half the exponential
#: term.  A fleet doubling the same floor spreads itself across
#: ``[backoff, 1.5 × backoff]``, which is wide enough that two routers
#: refused together do not wake together and narrow enough that the wait
#: still reads as the term rather than as noise.  A bound, never a promise:
#: the draw can be zero microseconds, and a deployment that wants a wider
#: or narrower spread states its own.
DEFAULT_JITTER_FRACTION = 0.5

#: The default source of jitter: the OS's entropy, because the whole point
#: of the draw is that two processes refused by one budget must not make
#: the same one.  A module-level instance rather than a fresh one per call
#: for the same reason :class:`random.SystemRandom` is documented to be
#: safe to share: it holds no seed state to race over.  Injectable all the
#: same, so a test can draw from a seeded stream and pin the delay.
_SYSTEM_RANDOM = random.SystemRandom()


def _sleep(delay: timedelta) -> None:
    """The default sleeper: close this process's eyes for ``delay``.

    :func:`time.sleep` over exact microseconds (``total_seconds()`` on a
    timedelta this module computed in whole microseconds), injectable at the
    call so the retry can be exercised without any of it happening.
    """
    time.sleep(delay.total_seconds())


def _microseconds_of(span: timedelta) -> int:
    """``span`` as a whole number of microseconds, exactly.

    The same rewrite :func:`router.limiter._microseconds_of` states, in this
    module's own words, for the reason every module in this member restates
    its own helpers: reaching into a sibling's private name would couple
    this module to a spelling the limiter never promised.  A
    :class:`~datetime.timedelta` already holds three exact integers, so no
    float ever touches the jitter's bound.
    """
    return span.days * 86_400_000_000 + span.seconds * 1_000_000 + span.microseconds


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    An event's operation and scope are *names* — a request nobody can name
    is a pacing nobody can attribute — the same near-miss rule the member's
    other modules hold their names to.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: {what} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); a retry event names the "
            "request and the budget it paces, and a name that states "
            "nothing attributes the wait to nobody (feature 319)"
        )
    return value.strip()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    The event's moment is the refusal's own reading, and a naive moment
    names an offset nobody agreed on — the same discipline the bucket holds
    its callers to, applied to the record of the wait the bucket caused.
    """
    if not isinstance(moment, datetime):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__}; a retry event is timed against the "
            "refusal's own reading, which is a moment (feature 319)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: {what} must be timezone-aware; the "
            "moment a retry paced itself by is read in another process too "
            "(an operator's sweep, the dashboard's §16 metrics), and a "
            "naive moment names an offset nobody agreed on (feature 319)"
        )
    return moment


def _require_count(value: object, what: str) -> int:
    """Return ``value`` as a genuine positive integer, or refuse it.

    One spelling for the counts this module demands — the ``retries`` budget
    and the event's ``attempt`` — with ``bool`` refused as loudly as
    ``"3"``: ``True`` is not a budget and not an attempt number, and zero is
    refused because a retry of zero re-sends is an ask to retry by not
    retrying (:func:`discovery.retry.retry_interrupted`'s own stance, for
    the same reason).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: {what} must be a whole number, got "
            f"{value!r} ({type(value).__name__}); a retry's counts are "
            "budgets and attempt numbers, and a near-miss count would pace "
            "the order path against arithmetic nobody stated (feature 319)"
        )
    if value < 1:
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: {what} must be at least 1, got "
            f"{value!r}; a retry that never re-sends is not a retry, and a "
            "first attempt is attempt 1 (feature 319)"
        )
    return value


@dataclass(frozen=True)
class BackoffSchedule:
    """How fast the wait grows, how far the jitter spreads, where it stops.

    The retry's own law, in one validated value — the exact role
    :class:`~router.limiter.VenueWeightSchedule` plays for the limiter, and
    the reason this is a value rather than three loose keyword arguments:
    a pacing is a *schedule* a deployment states once and every attempt of
    every call is paced under, and loose numbers could disagree between two
    calls of one order path.  Three fields:

    * ``multiplier`` — the exponential.  Each attempt waits ``multiplier``
      times the previous attempt's *floor-derived* term: with the default
      doubling and a refusal whose ``retry_after`` is forty seconds, the
      waits are 40 s, 80 s, 160 s, … (before jitter and the ceiling).  A
      genuine integer ≥ 2, refused at 1 because a multiplier of one paces
      every attempt identically, which is a constant — the sentence says
      *exponential*, and the whole point of the growth is that consecutive
      refusals must cost consecutively more.  An integer so the term stays
      exact whole microseconds: a float multiplier would put a binary
      approximation into the one arithmetic this module keeps float-free
      (the jitter is the only deliberate float, and it is floored).
    * ``jitter_fraction`` — the bound on the draw, as a fraction of the
      term.  The jitter added to an attempt's term is drawn uniformly from
      ``[0, jitter_fraction × term]`` — *added*, never subtracted, so the
      floor law survives the draw (see the module docstring).  Strictly
      inside ``(0, 1]``: zero is the synchronized wake the jitter exists
      to prevent, and above one the noise would lead the pacing.
    * ``cap`` — the ceiling on the exponential term, or ``None`` for the
      default: each refusal's *own* schedule window, the horizon in which
      the venue's whole allowance has come back.  A ceiling the caller
      states below a refusal's floor still loses to the floor — see
      :meth:`exponential`.

    Frozen and validated in ``__post_init__`` because a schedule is the law
    every attempt of the call is paced under, the same reason the weight
    schedule freezes its weights: a caller who could edit one mid-flight
    could change what an attempt already slept meant.
    """

    multiplier: int = DEFAULT_MULTIPLIER
    jitter_fraction: float = DEFAULT_JITTER_FRACTION
    cap: timedelta | None = None

    def __post_init__(self) -> None:
        if isinstance(self.multiplier, bool) or not isinstance(self.multiplier, int):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: the multiplier must be a whole "
                f"number, got {self.multiplier!r} "
                f"({type(self.multiplier).__name__}); the term is the floor "
                "times the multiplier, and a multiplier that is not an "
                "exact number would put a float into the one arithmetic "
                "this module keeps float-free (feature 319)"
            )
        if self.multiplier < 2:
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: the multiplier must be at least 2, "
                f"got {self.multiplier!r}; a multiplier of one paces every "
                "attempt identically, which is a constant backoff — the "
                "sentence says exponential, and consecutive refusals must "
                "cost consecutively more (feature 319)"
            )
        if isinstance(self.jitter_fraction, bool) or not isinstance(
            self.jitter_fraction, (int, float)
        ):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: the jitter fraction must be a "
                f"number, got {self.jitter_fraction!r} "
                f"({type(self.jitter_fraction).__name__}); it bounds the "
                "draw as a fraction of the term, and a near-miss bound "
                "would pace the fleet against nothing (feature 319)"
            )
        if not 0 < self.jitter_fraction <= 1:
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: the jitter fraction must be within "
                f"(0, 1], got {self.jitter_fraction!r}; zero is the "
                "synchronized wake 'plus jitter' exists to prevent, and "
                "above one the noise would lead the pacing it decorates "
                "(feature 319)"
            )
        if self.cap is not None and (
            not isinstance(self.cap, timedelta) or self.cap <= timedelta(0)
        ):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: the cap must be a positive "
                f"timedelta, got {self.cap!r} ({type(self.cap).__name__}); a "
                "ceiling is the horizon past which the wait waits for "
                "nothing, and a horizon that admits no time at all is not "
                "one (feature 319)"
            )

    def ceiling(self, window: timedelta) -> timedelta:
        """The effective ceiling for a refusal whose schedule quotes ``window``.

        The caller's stated ``cap`` when one was stated; otherwise the
        refusal's own schedule window — the default that keeps the ceiling
        venue-matched rather than a number this module invented.  The window
        is an argument rather than a field because the default is *each
        refusal's own*: two refusals from two schedules pace under two
        ceilings, and a schedule that held one window would be a third
        spelling of a fact the weight schedule already owns.
        """
        return window if self.cap is None else self.cap

    def exponential(self, floor: timedelta, attempt: int, *, ceiling: timedelta) -> timedelta:
        """The exponential term for ``attempt`` — capped, and never below ``floor``.

        ``floor × multiplier**(attempt-1)``, then two laws applied in a
        fixed order:

        * **the ceiling** first — a term past the horizon in which the
          venue's whole allowance has come back waits for nothing, so it is
          held at the ceiling;
        * **the floor** last, and last on purpose — it wins.  A ceiling a
          caller stated below this refusal's floor cannot wake the retry
          before the weight it needs: the floor is the venue's own
          arithmetic (the deficit times one unit's interval), and honouring
          a smaller ceiling over it would burn the attempt on a refusal
          that was known to be coming.  The order is the law: clamp to the
          ceiling, then lift to the floor.

        Exact throughout — an integer multiplier on whole microseconds, and
        comparisons between :class:`~datetime.timedelta` values this module
        computed without a float.
        """
        if not isinstance(floor, timedelta) or floor <= timedelta(0):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: the floor must be a positive "
                f"timedelta, got {floor!r}; it is the refusal's own "
                "retry_after — the earliest moment the weight can be there "
                "— and a backoff paced from any other number would not be "
                "paced from the venue (feature 319)"
            )
        attempt = _require_count(attempt, "an attempt")
        term = floor * self.multiplier ** (attempt - 1)
        # Clamp to the ceiling first, then lift to the floor — and the order
        # is the law: a ceiling a caller stated below this refusal's floor
        # still loses to the floor, which is the venue's own arithmetic
        # rather than a preference (see the docstring above).
        return max(min(term, ceiling), floor)

    def jitter(self, term: timedelta, jitter_rng: random.Random) -> timedelta:
        """The drawn addition to ``term`` — uniform in ``[0, fraction × term]``.

        *Added*, never spread across the term: a draw that could land below
        the floor would violate the one law this pacing has (see the module
        docstring).  Floored to whole microseconds after the draw, so the
        realized jitter never exceeds its own bound even where the bound
        itself is not representable exactly — the jitter is the one
        deliberate float in this module, and the floor keeps its error in
        the only direction that is safe: short.
        """
        bound = self.jitter_fraction * _microseconds_of(term)
        return timedelta(microseconds=int(jitter_rng.uniform(0.0, bound)))


#: The pacing this module ships: double the refusal's floor per attempt,
#: jitter up to half the term above it, ceiling at the venue's own window.
#: A *default*, never a law — the retry is constructed with whichever
#: schedule its deployment states, exactly as the limiter takes whichever
#: weight schedule it is handed.  Declared after :class:`BackoffSchedule`
#: because it *is* one, so the shipped default cannot be a shape this
#: module would refuse from a caller.
DEFAULT_BACKOFF_SCHEDULE = BackoffSchedule()


@dataclass(frozen=True)
class RateLimitRetryEvent:
    """One retry attempt, as the system emits it — the feature's own record.

    Feature 319's second clause: *"which emits one retry event per
    attempt."*  One of these exists per attempt this call makes, and every
    field on it is a figure the decision already computed, so an operator
    reading the pacing never re-derives it:

    * ``operation`` and ``scope`` — *which* request and *whose* budget, read
      off the refusal's reading, because a pacing a log cannot attribute is
      a wait nobody can act on;
    * ``attempt`` — which retry this is, 1-based among the retries this call
      makes (attempt 1 is the first re-send);
    * ``weight`` and ``deficit`` — what the request cost and how short the
      bucket fell, the two halves of the refusal's size;
    * ``floor`` — the refusal's ``retry_after``, restated as the law the
      delay is chosen above;
    * ``backoff`` — the capped exponential term;
    * ``jitter`` — the drawn addition, so the delay reads as the two things
      it is rather than one opaque number;
    * ``delay`` — what this attempt actually waits: ``backoff + jitter``,
      and pinned to that sum at construction;
    * ``observed_at`` — the refusal's own reading moment.  This module has
      no clock of its own; the moment is the reading's, which is the moment
      the figures above were true at;
    * ``event`` — the kind, as data, always :data:`RATE_LIMIT_RETRY_EVENT`,
      so a sink routing several event kinds dispatches on the string.

    Frozen and validated in ``__post_init__`` because the event is a public
    value a caller may construct and a log may replay — the discipline
    :class:`~router.limiter.RateLimitHeadroom` states for itself — and the
    validation pins this feature's own laws *inside* the value: the floor
    law (``backoff`` at or above ``floor``), the additive jitter
    (``delay == backoff + jitter``, exactly), and the fact that a retry
    event names a *refused* attempt (``deficit`` at least one — a deficit
    of zero would be a retry paced by a reading that refused nothing).
    """

    operation: str
    scope: str
    attempt: int
    weight: int
    deficit: int
    floor: timedelta
    backoff: timedelta
    jitter: timedelta
    delay: timedelta
    observed_at: datetime
    event: str = RATE_LIMIT_RETRY_EVENT

    def __post_init__(self) -> None:
        _require_text(self.operation, "an operation")
        _require_text(self.scope, "a scope")
        _require_count(self.attempt, "an attempt")
        if isinstance(self.weight, bool) or not isinstance(self.weight, int):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's weight is the "
                f"refused request's price, got {self.weight!r} "
                f"({type(self.weight).__name__}); the venue spends whole "
                "weight units and the event states what it does (feature 319)"
            )
        if self.weight < 1:
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's weight must be "
                f"positive, got {self.weight!r}; a request priced at "
                "nothing is a request the schedule refused to price, not "
                "one a budget refused to serve (feature 319)"
            )
        if isinstance(self.deficit, bool) or not isinstance(self.deficit, int):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's deficit is how far "
                f"short the bucket fell, got {self.deficit!r} "
                f"({type(self.deficit).__name__}); weight is spent in whole "
                "units and so is the shortfall (feature 319)"
            )
        if self.deficit < 1:
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event names a refused "
                f"attempt, but the deficit is {self.deficit}; a bucket that "
                "fell zero units short served the request, and a retry "
                "paced by that reading would be a retry of nothing "
                "(feature 319)"
            )
        if not isinstance(self.floor, timedelta) or self.floor <= timedelta(0):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's floor must be a "
                f"positive timedelta, got {self.floor!r}; it is the "
                "refusal's retry_after, and a refusal names a wait (feature 319)"
            )
        if not isinstance(self.backoff, timedelta) or self.backoff < self.floor:
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's backoff ({self.backoff!r}) "
                f"cannot sit below its floor ({self.floor!r}); the floor is "
                "the earliest moment the weight can possibly be there, and "
                "a delay under it buys a refusal that was known to be "
                "coming (feature 319)"
            )
        if not isinstance(self.jitter, timedelta) or self.jitter < timedelta(0):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's jitter is added "
                f"above the term, got {self.jitter!r}; a negative draw is "
                "not jitter but a floor violation wearing its hat (feature 319)"
            )
        if self.delay != self.backoff + self.jitter:
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event's delay must be its "
                f"backoff plus its jitter exactly, got {self.delay!r} for "
                f"{self.backoff!r} + {self.jitter!r}; the delay is the one "
                "number this attempt sleeps, and it is spelled as the two "
                "things it is or not at all (feature 319)"
            )
        _require_aware(self.observed_at, "observed_at")

    def render(self) -> str:
        """One line an operator reads and knows what is being waited for.

        The operation, the budget, how short it fell, which retry this is,
        and the wait decomposed into its term, its floor and its jitter —
        the facts of the pacing, none re-derived.
        """
        return (
            f"{self.event}: {self.operation} fell {self.deficit} of "
            f"{self.weight} weight units short on the budget "
            f"{self.scope!r} — retry {self.attempt} in {self.delay} "
            f"(backoff {self.backoff} above the floor {self.floor}, "
            f"jitter {self.jitter})"
        )


class RetryEventLog:
    """An append-only record of retry events, safe to share across callers.

    The standard ``on_retry`` sink: every :class:`RateLimitRetryEvent` a
    retry emits is recorded here in emission order — attempt by attempt,
    which is the shape the feature's clause fixes ("one retry event per
    attempt") — and replayed in full or per operation.  This is the seam an
    operator's sweep or a dashboard reads to learn how the order path is
    *pacing*, which no refusal alone can show: a stream of refusals says
    the budget was spent, and only the retry events say what the router
    did about it.

    Locked, deliberately, for the reason ``nullius_ingest.gaps.GapEventLog``
    locks: the retry itself is one call with one caller, but a log wired as
    several retries' sink receives events from several threads, so the log
    is the shared object and the log carries the guard.  Reads snapshot
    under the same lock — an :meth:`events` result is an immutable tuple,
    never a live view a concurrent append could tear.
    """

    def __init__(self) -> None:
        self._events: list[RateLimitRetryEvent] = []
        self._lock = threading.Lock()

    def record(self, event: RateLimitRetryEvent) -> RateLimitRetryEvent:
        """Append ``event`` to the log, returning it for pass-through wiring.

        The natural sink is ``retry_rate_limited(..., on_retry=log.record)``:
        the record returns its argument so composition keeps flowing, the
        pass-through :meth:`nullius_ingest.gaps.GapEventLog.record` also
        offers.  A non-event is a wiring bug and fails loudly, not a silent
        row a reader would later trip over.
        """
        if not isinstance(event, RateLimitRetryEvent):
            raise RouterRetryError(
                f"{RETRY_BACKOFF_CODE}: a retry event log records "
                f"RateLimitRetryEvent events, got {type(event).__name__}; a "
                "row that is not a retry event is a wiring bug, and a log "
                "that took it would answer for pacing that never happened "
                "(feature 319)"
            )
        with self._lock:
            self._events.append(event)
        return event

    def events(self, operation: str | None = None) -> tuple[RateLimitRetryEvent, ...]:
        """The recorded events, in emission order.

        With ``operation`` given, only that operation's events — a retry of
        one request is never reported under another's name, the per-request
        isolation the event itself carries.  Without it, every recorded
        event, still in the order they were emitted, which is the order the
        attempts happened in.
        """
        if operation is None:
            with self._lock:
                return tuple(self._events)
        wanted = _require_text(operation, "an operation")
        with self._lock:
            return tuple(event for event in self._events if event.operation == wanted)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def __iter__(self):
        return iter(self.events())


def retry_rate_limited[T](
    request: Callable[[], T],
    *,
    retries: object,
    on_retry: Callable[[RateLimitRetryEvent], object] | None = None,
    backoff: BackoffSchedule = DEFAULT_BACKOFF_SCHEDULE,
    sleep: Callable[[timedelta], object] = _sleep,
    jitter_rng: random.Random = _SYSTEM_RANDOM,
) -> T:
    """Send ``request``, retrying it while the venue's budget refuses it.

    Feature 319's verb: *System retries a rate-limited request with
    exponential backoff plus jitter, which emits one retry event per
    attempt.*  ``request`` is the request — any zero-argument callable the
    order path composes, which is expected to price its call through the
    limiter (feature 318) and therefore to raise
    :class:`~router.errors.RouterRateLimitedError` when the bucket cannot
    serve it; this module catches nothing else.  ``retries`` is the budget
    the caller states for how many re-sends the call may make; there is no
    default, because §13.2 gives no number and this module invents none.

    **What happens.**  The request is sent.  A refusal is caught, its
    carried reading is read — never a second query to the bucket — and the
    next attempt is scheduled ``retry_after × multiplier**(n-1)`` (capped,
    see :meth:`BackoffSchedule.exponential`) plus a drawn jitter (see
    :meth:`BackoffSchedule.jitter`), one retry event is emitted to
    ``on_retry`` for that attempt, the delay is slept, and the request is
    sent again.  A request that answers returns its own answer untouched.
    Any exception that is not the refusal propagates on the attempt it
    happened on — the schedule and bucket faults included, which are
    siblings of the refusal and not it.

    **Exhaustion re-raises the standing refusal.**  When ``retries``
    re-sends have all been refused, the last :class:`RouterRateLimitedError`
    — the freshest reading, headroom and all — is re-raised, exactly as the
    caller would have caught it without the retry.  318's argument, made
    again: *"was it sent?"* is not a flag for every call site to check.

    **The emission, precisely.**  Exactly one :class:`RateLimitRetryEvent`
    per re-send this call makes, handed to ``on_retry`` before the attempt
    sleeps.  A request that succeeds first try emits nothing; an exhausted
    call emits exactly ``retries`` — the terminal refusal re-raises rather
    than attempts, so it emits no event.  The event is built even with no
    sink wired, so its law holds of every attempt; a sink's return value is
    ignored, and a sink that raises stops the retry — the emission is part
    of the attempt, and a broken sink is a wiring fault, not a fact to
    swallow.

    ``backoff`` is the pacing (see :class:`BackoffSchedule`); ``sleep`` and
    ``jitter_rng`` are the two injectable seams this module's time passes
    through, so the retry can be exercised without any of it happening.
    The defaults are the real ones.

    Refuses :class:`~router.errors.RouterRetryError` — eagerly, before the
    request is sent even once, so a malformed ask never touches the caller's
    request — for a ``request`` that is not callable, a ``retries`` that is
    not a genuine positive integer, an ``on_retry`` that is not callable, a
    ``backoff`` that is not a :class:`BackoffSchedule`, a ``sleep`` that is
    not callable, a ``jitter_rng`` that is not a :class:`random.Random`, and
    — when a refusal arrives carrying a reading that names no wait — for
    the refusal that cannot be paced.
    """
    if not callable(request):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: request must be callable taking no "
            f"arguments, got {request!r} ({type(request).__name__}); the "
            "retry re-sends the request the refusal named, and an ask to "
            "retry something that cannot be called is a retry no attempt "
            "could begin (feature 319)"
        )
    retries = _require_count(retries, "the retries budget")
    if on_retry is not None and not callable(on_retry):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: on_retry must be callable receiving one "
            f"RateLimitRetryEvent, got {on_retry!r} "
            f"({type(on_retry).__name__}); the sink is how the system "
            "emits, and a sink that cannot receive is a pacing nobody "
            "observes (feature 319)"
        )
    if not isinstance(backoff, BackoffSchedule):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: a retry is paced by a BackoffSchedule, "
            f"got {backoff!r} ({type(backoff).__name__}); the schedule is "
            "the whole pacing law — the growth, the jitter's bound, the "
            "ceiling — so the retry cannot be paced through three loose "
            "numbers that two calls might disagree over (feature 319)"
        )
    if not callable(sleep):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: sleep must be callable receiving one "
            f"timedelta, got {sleep!r} ({type(sleep).__name__}); the backoff "
            "is only ever *done* by the sleeper, and a wait that cannot be "
            "slept is a number (feature 319)"
        )
    if not isinstance(jitter_rng, random.Random):
        raise RouterRetryError(
            f"{RETRY_BACKOFF_CODE}: jitter_rng must be a random.Random, "
            f"got {jitter_rng!r} ({type(jitter_rng).__name__}); the jitter "
            "is drawn, not computed, and the source it is drawn from is "
            "the one seam the draw comes through (feature 319)"
        )
    attempt = 0
    while True:
        try:
            return request()
        except RouterRateLimitedError as refusal:
            # The freshest reading is the law this attempt paces under: the
            # bucket has kept refilling since the last bank, so a refusal
            # read now can be milder than the one before it, and the floor
            # the retry waits above is *this* refusal's.
            attempt += 1
            if attempt > retries:
                # The budget is spent and the request still stands refused:
                # the refusal re-raises — the caller catches the same value
                # it would have caught without the retry, headroom and all,
                # rather than a flagged non-answer every call site must
                # enforce (318's own argument, inherited).
                raise
            headroom = refusal.headroom
            floor = headroom.retry_after
            if not isinstance(floor, timedelta) or floor <= timedelta(0):
                raise RouterRetryError(
                    f"{RETRY_BACKOFF_CODE}: the refusal of "
                    f"{headroom.operation!r} names no wait a backoff could "
                    f"read a floor from ({floor!r}); retry_after is the "
                    "refusal's own arithmetic — the deficit times one "
                    "unit's interval — and a refused reading always names "
                    "one, so this is a refusal wearing a reading that "
                    "refused nothing (feature 319)"
                ) from refusal
            term = backoff.exponential(
                floor,
                attempt,
                ceiling=backoff.ceiling(headroom.schedule.window),
            )
            jitter = backoff.jitter(term, jitter_rng)
            # Built before the sink is consulted, and built even when no
            # sink is wired: the value's own law — the floor above, the
            # additive jitter, the delay as the exact sum — holds of every
            # attempt, observed or not.
            event = RateLimitRetryEvent(
                operation=headroom.operation,
                scope=headroom.scope,
                attempt=attempt,
                weight=headroom.weight,
                deficit=headroom.deficit,
                floor=floor,
                backoff=term,
                jitter=jitter,
                delay=term + jitter,
                observed_at=headroom.observed_at,
            )
            if on_retry is not None:
                # The return is ignored, and an exception is deliberately
                # not caught: the emission is part of the attempt, and a
                # broken sink is a wiring fault to surface, not swallow.
                on_retry(event)
            sleep(event.delay)
