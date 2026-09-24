"""Feature 318: the token bucket matched to the venue's weight schedule.

app_spec.xml, "Order Routing & Venue Filters", feature 318: *System applies a
token-bucket rate limiter matched to the venue weight schedule, which returns
remaining headroom per request.*  ``docs/nullius-tech-architecture.md`` §13.2
states the same rule as one line of the execution engine's contract —
*"Token-bucket rate limiter matched to the venue's weight schedule, with
exponential backoff and jitter."* — and §16 lists *"rate-limit headroom"*
among the live metrics a dashboard reads.  The clause after the comma in
§13.2 is feature 319's (the backoff and the retry event); everything before it
is this module's.

**The venue meters *weight*, not requests.**  Its published limit is a budget
of weight units per window, and its endpoints are priced differently against
it: placing an order costs a unit or two, fetching ``exchangeInfo`` costs
twenty.  So a request *count* limiter is not a near miss but the wrong meter —
a router paced to one request per second would still blow the budget on a
burst of refreshes and still waste most of it on nothing but order placements.
This module meters the budget the venue actually enforces.

**A bucket, not a window.**  A fixed-window counter resets to zero on the
boundary, so a caller that spends the whole allowance at the end of one window
and the whole allowance at the start of the next spends twice the allowance in
an arbitrarily short span — and the venue, which does not reset on that
boundary, refuses the second burst.  A token bucket refills *continuously*, so
the weight a request needs comes back at the venue's own rate rather than all
at once, and the worst-case burst a caller can produce is the bucket's
capacity, which is the venue's own allowance.  Spending is in whole weight
units; refill is continuous — see
:attr:`VenueWeightSchedule.refill_interval`.

**"Matched to the venue weight schedule" is structural, not decorative.**  The
schedule is not a number this module multiplies by: it is a
:class:`VenueWeightSchedule` — the allowance, the window it is quoted over,
which venue limit it is (see :data:`WEIGHT_LIMIT_TYPE`), and a weight per
*operation* — and it is the limiter's entire vocabulary.  A caller names an
operation (``place_order``) and never a bare weight, so a request the schedule
does not price is refused by name rather than charged nothing: a free request
would spend the venue's budget unmetered, which is the one failure a limiter
matched to a schedule exists to prevent.  The schedule refuses three shapes
for the same reason — an operation priced heavier than the whole bucket, a
window over which no allowance is a rate, and a schedule built for the venue's
*count* limit (``ORDERS``) rather than its weight budget.

**The reading is per request, and the refused request gets one too.**  Every
:meth:`RouterRateLimiter.acquire` answers a :class:`RateLimitHeadroom` whose
headline is ``remaining`` — the weight left for the next request once this one
is accounted for.  A request that does not fit is *refused* rather than
answered with a flag: the applying of the limiter is the feature, and a record
saying "not allowed" would leave enforcement to every call site.  The refusal
is :class:`~router.errors.RouterRateLimitedError` and it *carries* the
headroom, so the sentence's *"returns remaining headroom per request"* is true
of the refused request as well — and so that the feature that *does* wait
(319's backoff and jitter) can read how far short the bucket fell without a
second query.  Waiting is deliberately not done here: this module spends and
refuses, and 319 decides what to do about a refusal.

**The bucket lives in the database, because the budget belongs to the key.**
The venue meters weight per API key, not per process — so two router processes
behind one key share one budget, and a bucket held in either process's memory
would let each spend the whole allowance believing it had tracked the other's.
The same argument :mod:`router.submission_health` makes for the router's
liveness, made here for its spend: the relational store is where the two
processes agree.  That also fixes the clock.  The bucket is refilled by
*elapsed time*, and the only clock two processes can agree on is the wall
clock, so ``now`` is a timezone-aware :class:`~datetime.datetime` and never
``time.monotonic`` — a monotonic clock has no common origin between processes,
and a bucket refilled against one process's origin would read as some other
age entirely in the next process.  Every write is taken under ``BEGIN
IMMEDIATE``: a deferred transaction would let two routers read the same
headroom and both spend it, which is precisely the double-spend a *shared*
budget must not have.

**The arithmetic is exact and conservatively slow.**  Refill is expressed as
an integer number of microseconds per weight unit —
``refill_interval = window / allowance``, floored — so no float ever enters
the decision, the discipline this member's sibling features keep for their own
rates (feature 320's :class:`~fractions.Fraction` bar).  Flooring makes the
bucket refill a hair *slower* than the venue's nominal rate (at most one
microsecond per unit — some 6 ms of a 6000-unit minute), never faster: a
limiter that is a hair pessimistic spends a hair less of the venue's budget,
and the other direction is the refusal this feature exists to avoid.  A clock
that steps backwards — an NTP correction on the live host — cannot create
weight either: elapsed time is clamped at zero, so the bucket holds still
rather than refilling.

**What this module deliberately does not do.**  It does not *wait*, *pace* or
*sleep*: a refusal is answered immediately and the backoff belongs to feature
319, whose sentence adds it and whose feature emits the retry event.  It does
not *meter the venue's other limit*: the published count limit has no weight
in it, and enforcing one while believing it tracked the other is the mistake
:data:`WEIGHT_LIMIT_TYPE`'s refusal catches.  It does not *halt* anything,
does not *record a submission attempt* (:mod:`router.submission_health` is
that log, written by the order path, not by the limiter), and does not *prune*
its own rows — a bucket is one row per scope, and a ``DELETE`` here would be a
second writer of the state every request is decided against.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as this member's other two tables are, and the schema is created
idempotently on connect, so no migration step is needed.  A URL whose scheme
is not ``sqlite`` is refused by name — as an *address* fault, in
:class:`~router.errors.RouterStoreError`, the member's existing vocabulary for
that fault, rather than in this feature's own class; see
:meth:`RouterRateLimiter.headroom`.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote, urlparse

from .errors import (
    RATE_LIMITED_CODE,
    WEIGHT_BUCKET_CODE,
    WEIGHT_SCHEDULE_CODE,
    RouterRateLimitedError,
    RouterStoreError,
    RouterWeightBucketError,
    RouterWeightScheduleError,
)

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_VENUE_WEIGHT_SCHEDULE",
    "DEFAULT_WEIGHT_SCOPE",
    "OPERATION_ACCOUNT",
    "OPERATION_CANCEL_ORDER",
    "OPERATION_CANCEL_REPLACE_ORDER",
    "OPERATION_EXCHANGE_INFO",
    "OPERATION_OPEN_ORDERS",
    "OPERATION_PLACE_ORDER",
    "OPERATION_QUERY_ORDER",
    "VENUE_WEIGHT_ALLOWANCE",
    "VENUE_WEIGHT_BUCKET_TABLE",
    "VENUE_WEIGHT_WINDOW",
    "WEIGHT_LIMIT_TYPE",
    "RateLimitHeadroom",
    "RouterRateLimiter",
    "VenueWeightSchedule",
]

#: The workspace-wide environment variable naming the relational store.
DATABASE_URL_ENV = "DATABASE_URL"

#: The venue's own name for the limit this feature meters.  A weight budget is
#: what §13.2's sentence is about, and the venue publishes at least one other
#: limit beside it — a *count* of orders per window, with no weight in it —
#: under a different name.  A schedule claims which one it is, and
#: :class:`VenueWeightSchedule` refuses a claim that is not this: charging
#: weight against a count limit would let the router exceed the count while
#: its headroom read comfortably.
WEIGHT_LIMIT_TYPE = "REQUEST_WEIGHT"

#: The venue's published spot weight allowance per window, in weight units.  A
#: readonly default rather than a law — every limiter may be handed its own
#: schedule — and it is the *schedule's* number, not an order-path constant:
#: feature 311's prohibition is over the filter grid (step size, tick size,
#: minimum notional), which the venue serves in ``exchangeInfo`` and which
#: §13.2 says must never be hardcoded.  A weight allowance the venue serves in
#: no document this member parses has to be stated somewhere, and stating it
#: once, in the schedule every request is priced against, is the one place it
#: can be changed.
VENUE_WEIGHT_ALLOWANCE = 6000

#: The window :data:`VENUE_WEIGHT_ALLOWANCE` is quoted over — the venue's own
#: ``interval`` (``MINUTE``) times its ``intervalNum`` (``1``).  A
#: :class:`~datetime.timedelta` rather than seconds so the schedule reads as
#: the venue states it.
VENUE_WEIGHT_WINDOW = timedelta(minutes=1)

#: One row per metered budget: how much weight the bucket holds and the moment
#: its accrual was last banked to.  Keyed by *scope* and not by process — see
#: the module docstring: the venue meters the key, so the bucket is per key.
VENUE_WEIGHT_BUCKET_TABLE = "router_venue_weight_bucket"

#: The default scope: the budget a deployment meters when it states only one
#: set of venue credentials.  A deployment that meters more than one — feature
#: 321's shadow sub-account has its own key and therefore its own budget —
#: passes its own scope, because two credentials read as one bucket would pace
#: the live path to a spend the sub-account never made.  That error is
#: conservative rather than dangerous (it under-spends the live key), which is
#: why a default is defensible at all; it is still an error, and a named scope
#: per credential set is the repair.
DEFAULT_WEIGHT_SCOPE = "default"

#: The operations this member prices, named as this member spells them.  The
#: *names* are this member's and the *weights* are the venue's; a deployment
#: that reaches an endpoint not listed here extends its own schedule rather
#: than borrowing a weight from a neighbouring row.
OPERATION_ACCOUNT = "account"
OPERATION_CANCEL_ORDER = "cancel_order"
OPERATION_CANCEL_REPLACE_ORDER = "cancel_replace_order"
OPERATION_EXCHANGE_INFO = "exchange_info"
OPERATION_OPEN_ORDERS = "open_orders"
OPERATION_PLACE_ORDER = "place_order"
OPERATION_QUERY_ORDER = "query_order"

#: The default schedule's weights: the venue's published per-request weight for
#: each operation above, keyed by this member's name for it.  Private because
#: it is a *starting point*, not a law — a deployment states its own weights on
#: its own :class:`VenueWeightSchedule` — and reading them from one mapping is
#: what keeps :data:`DEFAULT_VENUE_WEIGHT_SCHEDULE` from being a second
#: spelling of the table.
_DEFAULT_OPERATION_WEIGHTS = {
    OPERATION_ACCOUNT: 10,
    OPERATION_CANCEL_ORDER: 1,
    OPERATION_CANCEL_REPLACE_ORDER: 1,
    OPERATION_EXCHANGE_INFO: 20,
    OPERATION_OPEN_ORDERS: 3,
    OPERATION_PLACE_ORDER: 1,
    OPERATION_QUERY_ORDER: 2,
}

#: How long a bucket write waits for another process's write before refusing.
#: The bucket is the one table two router processes contend on, so a write that
#: waits forever would wedge the order path behind a sibling, and one that does
#: not wait at all would refuse an order because a sibling happened to be
#: mid-write.  Five seconds is long enough that ordinary contention never
#: surfaces as a refusal and short enough that a genuinely stuck writer is
#: reported rather than waited behind.
_BUSY_TIMEOUT_SECONDS = 5.0

_SCHEMA = f"""
-- Feature 318: one row per metered budget -- the token bucket itself.
--
-- The primary key is the *scope*, never the process: the venue meters weight
-- per API key, so two router processes behind one key share one row and the
-- database is where they agree (see the module docstring).  ``available`` is
-- whole weight units and ``refilled_at`` is the moment its accrual is exact
-- to; together they are the whole bucket, which is why the table holds no
-- history and no second row per scope.
--
-- The CHECK repeats the value layer's floor rather than trusting it: a
-- negative bucket would hand out weight it never had, and SQLite will accept
-- whatever another tool inserts into this column (feature 320's argument for
-- its own outcome CHECK, applied to a quantity).
CREATE TABLE IF NOT EXISTS {VENUE_WEIGHT_BUCKET_TABLE} (
    scope        TEXT PRIMARY KEY,
    available    INTEGER NOT NULL CHECK (available >= 0),
    refilled_at  TEXT NOT NULL  -- ISO 8601 UTC: when the accrual was banked
);
"""


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation this member's own :func:`router.store._sqlite_path`
    states, in this module's own words, for the reason every store in this
    workspace restates it: a store reaches into no sibling's private helper, so
    a later change to one table's address handling cannot silently move
    another's.  ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is
    absolute, and any other scheme is refused by name.

    Raises :class:`~router.errors.RouterStoreError`, **not** this feature's own
    class: an address this member cannot speak is an *address* fault with an
    address repair — point the deployment at a database this store can open —
    which is the face :class:`~router.errors.RouterStoreError` already carries
    for this variable.  The member keeps one vocabulary for one fault (see
    :mod:`router.errors`), exactly as :mod:`router.submission_health` states
    for its own table.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "router's venue weight bucket speaks sqlite:/// (the spec's "
            f"single-machine allowance); point {DATABASE_URL_ENV} at the "
            "sqlite database the rate limiter's bucket is kept in (feature 318)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 318)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path (feature 318)"
        )
    return Path(path)


def _microseconds_of(span: timedelta) -> int:
    """``span`` as a whole number of microseconds, exactly.

    ``timedelta.total_seconds()`` would answer a float, and the whole point of
    the refill arithmetic is that no float enters it: a bucket refilled through
    binary floats can drift by a unit over a long window, and the direction of
    that drift is not a property anybody can state.  A
    :class:`~datetime.timedelta` already holds three exact integers, so this is
    a rewrite rather than a measurement.
    """
    return span.days * 86_400_000_000 + span.seconds * 1_000_000 + span.microseconds


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores."""
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive moment cannot say unambiguously *when* a request happened, and the
    bucket is refilled by elapsed time between exactly such moments — so a
    naive ``now`` would either crash the subtraction or, worse, be read against
    a different process's offset and hand out weight that has not accrued.  The
    same discipline this member's other two stores hold their callers to, and
    the reason it is checked here rather than assumed.
    """
    if not isinstance(moment, datetime):
        raise RouterWeightBucketError(
            f"{WEIGHT_BUCKET_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__}; a bucket is refilled by the time between "
            "two moments, so it cannot be read at a non-moment (feature 318)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterWeightBucketError(
            f"{WEIGHT_BUCKET_CODE}: {what} must be timezone-aware; a bucket "
            "shared by two processes is refilled against the wall clock, and a "
            "naive moment names an offset nobody agreed on (feature 318)"
        )
    return moment


def _require_text(
    value: object,
    what: str,
    *,
    error: type[Exception],
    code: str,
) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    Every string in this feature is a *name* — a scope, an operation — and a
    name that states nothing names no budget and no request to price, the same
    near-miss rule :func:`regime.origins._validated_world_id` takes toward an
    id with a trailing newline.  The error class and the greppable code are the
    caller's, because the same helper serves the schedule's vocabulary and the
    bucket's addressing and those are two different repairs.
    """
    if not isinstance(value, str) or not value.strip():
        raise error(
            f"{code}: {what} must be non-empty text, got {value!r} "
            f"({type(value).__name__}) (feature 318)"
        )
    return value.strip()


def _require_weight(value: object, what: str) -> int:
    """Return ``value`` as a positive whole number of weight units, or refuse it.

    ``bool`` is refused explicitly although it *is* an ``int`` in Python: a
    schedule that priced an operation ``True`` weight units would read as a
    weight of one and a truthiness in the same cell, and the one place a weight
    comes from should say which it means.  Zero is refused too — a free
    operation would let the router spend the venue's budget unmetered, which is
    the failure the schedule exists to make impossible.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouterWeightScheduleError(
            f"{WEIGHT_SCHEDULE_CODE}: {what} must be a whole number of weight "
            f"units, got {value!r} ({type(value).__name__}); the venue spends "
            "weight in whole units, and a fractional or non-numeric one cannot "
            "be spent at all (feature 318)"
        )
    if value <= 0:
        raise RouterWeightScheduleError(
            f"{WEIGHT_SCHEDULE_CODE}: {what} must be positive, got {value}; a "
            "venue charges weight for every request it serves, so a zero here "
            "is a typo that would spend the budget unmetered (feature 318)"
        )
    return value


@dataclass(frozen=True)
class VenueWeightSchedule:
    """The venue's weight budget, and what each operation costs against it.

    Feature 318's *"the venue weight schedule"*: the allowance, the window it
    is quoted over, which of the venue's published limits it is, and a weight
    per operation.  A limiter is constructed with one and is *matched* to it in
    the only sense that can be checked — the schedule is the limiter's whole
    vocabulary (see :meth:`weight_for`) and its allowance is the bucket's
    capacity and refill rate (see :attr:`refill_interval`).

    Nothing here is fetched.  The venue publishes its weight allowance in the
    same ``exchangeInfo`` document the router fetches for its filters, but this
    member deliberately does not grow a second parser of that response to reach
    its ``rateLimits`` array — the one-parser rule
    ``docs/nullius-tech-architecture.md`` §6.2 states for the cost model, which
    :mod:`router.exchange_info` already honours for the filter grid.  So the
    schedule is *stated to* this member, once, by the deployment; what this
    member guarantees is that the statement is internally consistent and that
    no request is priced outside it.

    Four shapes are refused at construction, each because it would make the
    limiter answer a plausible wrong number rather than because it is untidy:

    * an operation priced heavier than the whole allowance can never be
      satisfied by any state of the bucket, so the schedule would name a
      request the limiter can only ever refuse;
    * a weight that is not a positive whole number (see :func:`_require_weight`)
      — a free operation spends the venue's budget unmetered;
    * a ``limit_type`` that is not :data:`WEIGHT_LIMIT_TYPE`: the venue's count
      limit is a different meter wearing this one's name;
    * a window over which the allowance leaves less than a microsecond per
      unit, which is a bucket that refills instantly and therefore is not a
      limiter.
    """

    allowance: int
    weights: Mapping[str, int]
    window: timedelta = VENUE_WEIGHT_WINDOW
    limit_type: str = WEIGHT_LIMIT_TYPE

    def __post_init__(self) -> None:
        _require_weight(self.allowance, "the allowance")
        if self.limit_type != WEIGHT_LIMIT_TYPE:
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: this schedule meters "
                f"{self.limit_type!r}, and feature 318's limiter meters "
                f"{WEIGHT_LIMIT_TYPE!r} — the venue's *weight* budget.  The "
                "venue publishes a separate count limit with no weight in it, "
                "and pricing weight against that one would let the router "
                "exceed the count while its headroom read comfortably "
                "(feature 318)"
            )
        if not isinstance(self.window, timedelta):
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: the window must be a timedelta, not "
                f"{type(self.window).__name__} (feature 318)"
            )
        if self.window <= timedelta(0):
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: the window must be positive, got "
                f"{self.window}; an allowance quoted over no time is not a rate "
                "(feature 318)"
            )
        if not isinstance(self.weights, Mapping) or not self.weights:
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: a weight schedule must name the "
                f"operations it prices, got {self.weights!r}; a schedule with "
                "no operations prices nothing, so every request would be "
                "refused as unpriced — or, worse, charged nothing by a lenient "
                "lookup (feature 318)"
            )
        narrowed: dict[str, int] = {}
        for operation, weight in self.weights.items():
            name = _require_text(
                operation,
                "an operation name",
                error=RouterWeightScheduleError,
                code=WEIGHT_SCHEDULE_CODE,
            )
            narrowed[name] = _require_weight(weight, f"the weight of {name!r}")
        heaviest = max(narrowed, key=lambda name: narrowed[name])
        if narrowed[heaviest] > self.allowance:
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: the schedule prices {heaviest!r} at "
                f"{narrowed[heaviest]} weight units against an allowance of "
                f"{self.allowance}; a request heavier than the whole bucket can "
                "never be satisfied, whatever the bucket holds, so this "
                "schedule names a request the limiter could only ever refuse "
                "(feature 318)"
            )
        if _microseconds_of(self.window) < self.allowance:
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: an allowance of {self.allowance} "
                f"units over {self.window} leaves less than a microsecond for "
                "one unit to come back, which is a bucket that refills "
                "instantly rather than a rate (feature 318)"
            )
        # Read-only rather than merely copied: a schedule is the law every
        # request in this process is priced against, and a caller who can still
        # edit one can change the price of an order after the limiter was built
        # from it — the class-level equivalent of the mutation
        # ``router.exchange_info`` freezes its nested filter maps against.
        object.__setattr__(self, "weights", MappingProxyType(narrowed))

    @property
    def refill_interval(self) -> timedelta:
        """How long one weight unit takes to come back — floored, exactly.

        ``window / allowance`` as a whole number of microseconds, rounded
        *down*, so the bucket refills a hair slower than the venue's nominal
        rate and never faster.  The error is bounded and tiny (at most one
        microsecond per unit — some 6 ms of a 6000-unit minute) and it is in
        the only direction a limiter may be wrong in: spending a hair less of
        the venue's budget costs a hair of throughput, while spending a hair
        more is the refusal this feature exists to avoid.

        Feature 319's backoff reads this to know how long a refused request
        must wait before the weight it needs can possibly be there; nothing in
        *this* module waits on it.
        """
        return timedelta(
            microseconds=_microseconds_of(self.window) // self.allowance
        )

    @property
    def refill_rate(self) -> Fraction:
        """The allowance per window, exactly, as a :class:`~fractions.Fraction`.

        The rate the venue quotes, spelled so a deployment or a dashboard can
        read *"6000 weight units a minute"* off the schedule rather than
        recomputing it from the interval — and a :class:`~fractions.Fraction`
        so the figure is exact, the discipline feature 320 keeps for its own
        bar.  It is deliberately **not** what the bucket refills by: the bucket
        accrues in whole units at :attr:`refill_interval`, which is this rate
        floored to whole microseconds.
        """
        return Fraction(self.allowance, _microseconds_of(self.window))

    def price(self, operation: str) -> tuple[str, int]:
        """``operation``'s canonical name and its weight, or refuse it by name.

        The whole of *"matched to the venue weight schedule"*, and the one
        seam the limiter prices a request through: it returns the name
        *as the schedule spells it* beside the weight, so a caller that must
        name the request it priced (every message and every reading this
        feature produces does) holds the same string the lookup used instead
        of re-deriving it — the argument
        :meth:`~router.submission_health.RouterSubmissionHealthStore.health`
        makes for validating its ``process_id`` once.

        An operation this schedule does not price is **refused** rather than
        charged zero: an unpriced request that went through free would spend
        the venue's budget unmetered, which is the one failure a limiter
        matched to a schedule exists to prevent, and a silent zero would hide
        which endpoint a deployment had forgotten to state.

        The refusal is a :class:`~router.errors.RouterWeightScheduleError`, the
        same class a malformed schedule raises and for the same reason: the
        repair is *state this operation's weight*, which is an edit to the
        schedule, not to the bucket.
        """
        # Whitespace is *normalised*, not rejected, on both sides of the
        # lookup: the schedule strips its own keys at construction and this
        # strips the ask, so ``" place_order"`` and ``"place_order "`` name the
        # one operation ``"place_order"`` does.  Case is not, because ``ORDERS``
        # and ``orders`` are two different venue limits rather than one name
        # spelled carelessly (see ``limit_type``).
        name = _require_text(
            operation,
            "an operation",
            error=RouterWeightScheduleError,
            code=WEIGHT_SCHEDULE_CODE,
        )
        try:
            return name, self.weights[name]
        except KeyError:
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: the schedule prices "
                f"{sorted(self.weights)} and {name!r} is not one of them; a "
                "request this schedule does not price would spend the venue's "
                "weight budget unmetered, so it is refused rather than charged "
                "nothing (feature 318)"
            ) from None

    def weight_for(self, operation: str) -> int:
        """What ``operation`` costs against this budget, or refuse it by name.

        The weight alone, for a caller that does not need to name the request
        it priced (a deployment reading its own schedule, a dashboard costing
        an operation it has not sent).  The limiter prices through
        :meth:`price`, which is this method's own seam and the only place the
        lookup is stated.
        """
        return self.price(operation)[1]


#: The venue's spot weight schedule as this member ships it: the published
#: allowance over its published window, priced against this member's operation
#: names.  A *default*, never a hardcoded venue constant in the order path —
#: the limiter is constructed with whichever schedule its deployment states,
#: and this is only the one a caller with nothing to state gets.  It is
#: declared after :class:`VenueWeightSchedule` because it *is* one: the
#: allowance, the window and the weights are checked by the same
#: ``__post_init__`` every deployment's schedule goes through, so the shipped
#: default cannot be a shape this member would refuse from a caller.
DEFAULT_VENUE_WEIGHT_SCHEDULE = VenueWeightSchedule(
    allowance=VENUE_WEIGHT_ALLOWANCE,
    window=VENUE_WEIGHT_WINDOW,
    limit_type=WEIGHT_LIMIT_TYPE,
    weights=_DEFAULT_OPERATION_WEIGHTS,
)


@dataclass(frozen=True)
class RateLimitHeadroom:
    """What one request read off the bucket — the feature's own return value.

    Feature 318's *"returns remaining headroom per request"*: every request,
    allowed or refused, produces exactly one of these.  ``remaining`` is the
    headline — the weight the bucket holds for the next request, *after* this
    one's own weight was either spent or found to be missing — and the rest of
    the record is there so the headline can be read rather than trusted:

    * ``operation`` and ``weight`` name the request that was priced, so a log
      line or a dashboard can attribute headroom to the endpoint that spent it
      — a number with no request attached is a number nobody can act on;
    * ``allowed`` says which of the two things happened, because ``remaining``
      alone cannot: a refused request and an allowed one can read the same
      headroom when the bucket was exactly empty either way (see below);
    * ``capacity`` and ``accrued`` are the refill the request saw — how much
      weight the bucket may hold at most, and how much had come back since its
      accrual was banked.  They are *figures from the refill arithmetic*, not
      stored values, which is why the bucket's own row needs no history;
    * ``scope`` names the budget, and ``observed_at`` when the reading was
      taken — an operator reading *"rate-limit headroom"* off a dashboard
      (§16) needs both to know *whose* budget and *how stale*.

    **Why a refused request still carries a reading.**  Refusal is
    :class:`~router.errors.RouterRateLimitedError`, and it *carries* one of
    these rather than an error message: *"remaining headroom per request"* is
    the sentence, and a refused request is a request.  Feature 319's backoff
    then reads :attr:`deficit`, :attr:`shortfall` and :attr:`retry_after` — all
    derived here, from the schedule and the bucket — instead of re-deriving
    them from a bucket it would otherwise have to query itself.

    **A refusal leaves the bucket exactly as it found it.**  This is the
    property that makes the two readings distinguishable: an allowed request
    spends its weight, so its ``remaining`` is *strictly* less than the
    ``accrued`` it saw, while a refused request spends nothing, so its
    ``remaining`` equals that ``accrued``.  :attr:`allowed` is pinned to that
    comparison at construction, so the two faces of the fact cannot disagree
    — and a reader that wants *"how much did this request cost?"* reads
    ``weight`` through :attr:`allowed` rather than relying on a third spelling
    of the same subtraction.

    **``headroom`` and ``acquire`` return the same type and mean the same
    thing by it.**  A reading is what the bucket held, what the request's
    price was, and what happened; it is not a claim that the request was
    *sent*.  A caller that needs to know whether the weight actually came out
    of the budget should ask :meth:`RouterRateLimiter.acquire`, which is the
    only method that writes — :meth:`RouterRateLimiter.headroom` writes
    nothing and its readings describe a hypothetical, with ``remaining``
    already net of a spend that did not happen.
    """

    scope: str
    operation: str
    weight: int
    allowed: bool
    remaining: int
    capacity: int
    accrued: int
    observed_at: datetime
    schedule: VenueWeightSchedule = field(
        default=DEFAULT_VENUE_WEIGHT_SCHEDULE, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        # The shape this record cannot have, checked rather than assumed: a
        # reading is a public value a caller may construct, and one whose
        # remaining exceeds its capacity or its own accrual would have every
        # property below answer a plausible wrong number -- a negative
        # deficit, a retry_after of zero for work that is not there.  The
        # counts are derived by the limiter and by nothing else; refusing the
        # shape is what keeps that true of every record, not only the ones it
        # built (the argument feature 320's SubmissionHealth makes).
        if self.weight <= 0:
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: a priced request costs a positive "
                f"whole number of weight units, got {self.weight} (feature 318)"
            )
        if self.remaining < 0 or self.accrued < 0 or self.capacity <= 0:
            raise RouterWeightBucketError(
                f"{WEIGHT_BUCKET_CODE}: the bucket metering {self.scope!r} "
                f"holds {self.remaining} of {self.accrued} accrued under a "
                f"capacity of {self.capacity}, which is not a state any bucket "
                "can be in; weight is what the venue's budget has left, and it "
                "cannot be negative (feature 318)"
            )
        if self.accrued > self.capacity:
            raise RouterWeightBucketError(
                f"{WEIGHT_BUCKET_CODE}: the bucket metering {self.scope!r} "
                f"cannot have accrued {self.accrued} weight units under a "
                f"capacity of {self.capacity}; the allowance is the ceiling, "
                "so a reading "
                "above it is the refill arithmetic reporting a bug rather than "
                "a budget (feature 318)"
            )
        if self.remaining > self.accrued:
            raise RouterWeightBucketError(
                f"{WEIGHT_BUCKET_CODE}: a request cannot leave {self.remaining} "
                f"weight units in a bucket that held {self.accrued}; a request "
                "spends weight or it does not, and one that appears to add it "
                "is the direction that over-spends the venue's budget "
                "(feature 318)"
            )
        if self.allowed != (self.remaining < self.accrued):
            raise RouterWeightBucketError(
                f"{WEIGHT_BUCKET_CODE}: a reading that is "
                f"{'allowed' if self.allowed else 'refused'} with "
                f"{self.remaining} of {self.accrued} weight units left states "
                "two different things about the same request; an allowed "
                "request spends its weight and a refused one spends nothing, "
                "so the two halves of this record cannot both be true "
                "(feature 318)"
            )
        _require_aware(self.observed_at, "observed_at")

    @property
    def deficit(self) -> int:
        """How short of the request's weight the bucket fell — zero if allowed.

        What *"the bucket could not serve this"* means as a number: a refused
        request weighing five read a bucket holding three and fell two short.
        Feature 319's backoff waits for this much weight to accrue, which is
        why it is stated as a figure rather than left to be subtracted at the
        call site.
        """
        if self.allowed:
            return 0
        return self.weight - self.accrued

    @property
    def shortfall(self) -> Fraction | None:
        """The fraction of the request's weight that was missing, or ``None``.

        ``None`` when the request was allowed — there was no shortfall to
        measure, and ``0`` would be a reading of something that did not happen,
        the same stance feature 320's empty window takes toward
        ``rejection_ratio``.  Otherwise the missing weight over the weight
        asked for, exactly: a request priced at twenty that found ten has a
        shortfall of one half, whichever venue it was for.
        """
        if self.allowed:
            return None
        return Fraction(self.deficit, self.weight)

    @property
    def retry_after(self) -> timedelta | None:
        """How long until the bucket could serve this request, or ``None``.

        ``None`` when it already did.  Otherwise the missing weight times the
        schedule's refill interval — the *earliest* moment this request could
        be admitted, computed from the bucket's own figures and the schedule
        the limiter was matched to, with no float and no rounding of its own.

        **An estimate of the bucket, not a promise about the venue.**  It says
        when *this limiter* would admit the request; it says nothing about
        whether the venue would accept it, which is the ceremony that follows
        feature 319's backoff rather than this reading.  And it is
        deliberately the shortest possible wait, not a recommended one: 319's
        sentence adds exponential backoff and jitter precisely because a fleet
        of routers all waking on the same exact microsecond would re-collide,
        so the jittered delay is 319's to choose and this is the floor it is
        chosen above.
        """
        if self.allowed:
            return None
        return self.refill_interval * self.deficit

    @property
    def refill_interval(self) -> timedelta:
        """The schedule's interval for one weight unit — see
        :attr:`VenueWeightSchedule.refill_interval`.

        A pass-through with no arithmetic of its own, so :attr:`retry_after`
        reads as the one multiplication it is and the interval stays the
        schedule's single spelling.
        """
        return self.schedule.refill_interval


class RouterRateLimiter:
    """Applies the venue's weight budget to the order path's requests.

    Constructed with the store's address, the schedule it is *matched to* and
    the scope whose budget it meters; construction performs no I/O, so building
    a limiter costs nothing and the bucket is read on the first
    :meth:`acquire`.  Each operation opens its own connection, the discipline
    every store in this member follows — which is what makes the bucket
    readable by a *second* router process, the property the module docstring
    argues from.

    **One limiter is one budget.**  ``scope`` is not a parameter of
    :meth:`acquire`, because a limiter *is* the budget for one set of venue
    credentials: a deployment that meters two keys (feature 321's shadow
    sub-account beside the live one) builds two limiters rather than passing a
    different scope per call.  A per-call scope would be a second place the
    same fact is stated, and the failure it invites — one call site forgetting
    to pass it and charging the live key for the shadow path's spend — is
    exactly the mis-pricing :data:`DEFAULT_WEIGHT_SCOPE` warns about.
    """

    def __init__(
        self,
        database_url: str,
        *,
        schedule: VenueWeightSchedule = DEFAULT_VENUE_WEIGHT_SCHEDULE,
        scope: str = DEFAULT_WEIGHT_SCOPE,
    ) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        if not isinstance(schedule, VenueWeightSchedule):
            raise RouterWeightScheduleError(
                f"{WEIGHT_SCHEDULE_CODE}: a limiter is matched to a "
                f"VenueWeightSchedule, got {type(schedule).__name__}; the "
                "schedule is the limiter's whole vocabulary, so it cannot be "
                "reached through an object that merely carries numbers "
                "(feature 318)"
            )
        self._database_url = database_url.strip()
        self._schedule = schedule
        self._scope = _require_text(
            scope,
            "the scope",
            error=RouterWeightBucketError,
            code=WEIGHT_BUCKET_CODE,
        )

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        schedule: VenueWeightSchedule = DEFAULT_VENUE_WEIGHT_SCHEDULE,
        scope: str = DEFAULT_WEIGHT_SCOPE,
    ) -> RouterRateLimiter | None:
        """The limiter ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, the stance this
        member's exchangeInfo store and submission-health store both take.

        Resolved from the environment rather than registered with the factory,
        and for the reason :mod:`router.submission_health` gives in its own
        words: a budget addressed by ``DATABASE_URL`` and shared by every
        process behind one key is *not* something a composed application hands
        out, because a component's lifetime is the composing process's — and
        the whole point of keeping the bucket in the database is that the other
        process is spending the same budget concurrently.  So this member still
        registers exactly one component (feature 310's exchangeInfo store), and
        the limiter arrives by construction, like the tables it writes.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw, schedule=schedule, scope=scope)

    @property
    def database_url(self) -> str:
        """The database URL this limiter's bucket is kept in."""
        return self._database_url

    @property
    def schedule(self) -> VenueWeightSchedule:
        """The venue weight schedule this limiter is matched to."""
        return self._schedule

    @property
    def scope(self) -> str:
        """The budget this limiter meters — one set of venue credentials."""
        return self._scope

    def _connect(self) -> sqlite3.Connection:
        """Open the store, creating the bucket table idempotently if absent.

        ``isolation_level=None`` puts the driver in autocommit mode so this
        module's transactions are the ones it writes by hand: the driver's
        implicit ``BEGIN`` would otherwise fire before a ``SELECT`` and turn
        :meth:`acquire`'s explicit ``BEGIN IMMEDIATE`` into a nested-transaction
        error.  ``timeout`` is the busy timeout — how long the connection waits
        for a sibling process's write before giving up — and is set here rather
        than passed to each statement so a contended bucket behaves the same
        way whichever operation hit the contention.
        """
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            path, timeout=_BUSY_TIMEOUT_SECONDS, isolation_level=None
        )
        connection.executescript(_SCHEMA)
        return connection

    # -- The bucket -----------------------------------------------------------

    def _accrual(
        self, available: int, refilled_at: datetime, now: datetime
    ) -> tuple[int, datetime]:
        """The bucket at ``now``: its fill, and the moment that fill is exact to.

        Two answers rather than one, and the second is load-bearing: a bucket's
        state is *both* numbers, so a caller that refills the fill and then
        banks it against a moment it did not measure has written a state that
        never existed.  Returning them together is what keeps the clamp below
        from being stated twice — once in the arithmetic and once in the write
        — where the two spellings could disagree.

        The fill is what the bucket held plus what has accrued, capped at the
        allowance, because that is what a bucket *is*: weight not spent in time
        is lost, so a router idle for an hour has a full bucket and not sixty
        minutes' worth of budget.  That ceiling is what makes the worst-case
        burst a caller can produce the venue's own allowance — an uncapped
        bucket would let an idle router bank an hour of weight and spend it in
        one second, which the venue, which does not bank, would refuse.

        **Elapsed time is clamped at zero, and the clamped moment comes back
        with the fill.**  A clock that steps *backwards* — an NTP correction on
        the live host — has measured a negative span, which is not a refund but
        the clock disagreeing with itself; the bucket holds still rather than
        refilling.  Banking the early ``now`` back would be worse than a
        misread: it would move the accrual origin *behind* the moment weight
        was last spent, so the next read would count an interval that has
        already been counted and hand out weight the venue never granted.  So
        the moment returned is the stored one whenever the clock went
        backwards, and ``now`` otherwise — one rule, and :meth:`acquire` writes
        exactly what this returned.

        **A sub-interval remainder is discarded when the bucket is banked**,
        and that is stated rather than left to be discovered: a spend banks the
        fill against ``now`` rather than against
        ``refilled_at + units_spent × interval``, so the fraction of an
        interval that had not yet become a whole unit is lost.  It is bounded
        by one interval per spend — some 10 ms on the venue's own schedule, so
        tens of milliseconds over a minute of order placement — and it errs the
        same way :attr:`VenueWeightSchedule.refill_interval`'s floor does:
        against the caller, never against the venue.  The exact-origin
        alternative would make the accrual origin a *derived* moment rather
        than an observed one, and the backwards-clock rule above would then
        have nothing concrete to clamp against.
        """
        elapsed = _microseconds_of(now - refilled_at)
        if elapsed <= 0:
            return available, refilled_at
        interval = _microseconds_of(self._schedule.refill_interval)
        accrued = available + elapsed // interval
        # ``min`` rather than a comparison so the ceiling is stated once: the
        # allowance is the capacity, and nothing above it is a bucket.
        return min(accrued, self._schedule.allowance), now

    def _banked(
        self, connection: sqlite3.Connection, now: datetime
    ) -> tuple[int, datetime]:
        """Read this scope's bucket, created full when it does not exist yet.

        A scope with no row is a budget nobody has spent against, so it starts
        **full** — the venue hands a key its whole allowance and the router's
        first request must not be refused because this member had not written a
        row yet.  The row is *not* written here: :meth:`acquire` writes when it
        spends, so a read-only :meth:`headroom` on a fresh deployment leaves no
        trace, the same "construction touches no database" promise this
        member's other stores keep.

        A stored row whose fill is negative or whose accrual moment this store
        cannot parse is refused by name rather than repaired into a plausible
        bucket: SQLite will accept whatever another tool inserts, and a bucket
        read as full because its state was unreadable is the direction that
        over-spends the venue's budget.  The refusal names the scope, so an
        operator can find the row.
        """
        row = connection.execute(
            f"""
            SELECT available, refilled_at
            FROM {VENUE_WEIGHT_BUCKET_TABLE}
            WHERE scope = ?
            """,
            (self._scope,),
        ).fetchone()
        if row is None:
            return self._schedule.allowance, now
        available, refilled_at_raw = row
        if not isinstance(available, int) or isinstance(available, bool):
            raise RouterWeightBucketError(
                f"{WEIGHT_BUCKET_CODE}: the bucket metering {self._scope!r} "
                f"holds {available!r} ({type(available).__name__}); weight is "
                "spent in whole units, so a bucket that holds something else is "
                "not a bucket this limiter can spend from (feature 318)"
            )
        try:
            refilled_at = datetime.fromisoformat(refilled_at_raw)
        except (TypeError, ValueError) as exc:
            raise RouterWeightBucketError(
                f"{WEIGHT_BUCKET_CODE}: the bucket metering {self._scope!r} "
                f"carries {refilled_at_raw!r}, which is not an ISO 8601 moment "
                "this limiter can measure elapsed time from; a bucket whose "
                "accrual moment is unreadable cannot be refilled without "
                "guessing how much weight has come back (feature 318)"
            ) from exc
        return available, refilled_at

    def _reading(
        self,
        operation: str,
        weight: int,
        now: datetime,
        available: int,
        refilled_at: datetime,
    ) -> RateLimitHeadroom:
        """Assemble this request's reading from the bucket's banked state.

        One place where the request's weight meets the bucket's fill, so the
        allowed and refused arms of :meth:`acquire` cannot disagree about what
        they measured: both hand their (possibly written, possibly not) state
        here, and :class:`RateLimitHeadroom` refuses the record if the two
        halves of it tell different stories.

        Returns the reading *and* the bucket state the request leaves behind —
        the fill and the moment it is exact to, straight from
        :meth:`_accrual`.  A refused request leaves the bucket as it found it,
        which is why its ``remaining`` equals its ``accrued`` and why
        :meth:`acquire` writes nothing for it.
        """
        accrued, banked_at = self._accrual(available, refilled_at, now)
        allowed = accrued >= weight
        return (
            RateLimitHeadroom(
                scope=self._scope,
                operation=operation,
                weight=weight,
                allowed=allowed,
                remaining=accrued - weight if allowed else accrued,
                capacity=self._schedule.allowance,
                accrued=accrued,
                observed_at=now,
                schedule=self._schedule,
            ),
            banked_at,
        )

    # -- The one verb ---------------------------------------------------------

    def acquire(self, operation: str, *, now: datetime | None = None) -> RateLimitHeadroom:
        """Price ``operation`` against the bucket and spend it, or refuse.

        Feature 318's verb: the request is *applied* to the limiter here, and
        the answer is what the sentence asks for — a
        :class:`RateLimitHeadroom` whose ``remaining`` is the weight left for
        the next request once this one is accounted for.  ``operation`` is a
        name from the schedule (``OPERATION_PLACE_ORDER`` and its siblings),
        never a bare number of weight units: see the module docstring on why
        the schedule is the limiter's whole vocabulary.

        ``now`` defaults to this instant and is the moment the request is
        priced at — a timezone-aware wall-clock moment, because the bucket is
        shared with a sibling process and a monotonic clock has no common
        origin between them (see the module docstring).  It is injectable so
        the rate limiter can be reasoned about and tested without waiting, the
        discipline :class:`~router.submission_health.RouterSubmissionHealthStore.health`
        keeps for its own ``now``.

        **Allowed.**  The request's weight is deducted and the bucket's new
        state is banked in one ``BEGIN IMMEDIATE`` transaction, so two
        processes spending concurrently serialize rather than both reading the
        same headroom and both deducting it.  The reading's ``accrued`` is the
        fill the request found and ``remaining`` is what it left.

        **Refused.**  Raised as :class:`~router.errors.RouterRateLimitedError`,
        which *carries* the reading — so *"returns remaining headroom per
        request"* holds for the refused request too, and feature 319 can read
        ``retry_after`` off the refusal.  Nothing is written: the bucket is left
        exactly as it was found, so its accrual keeps running from the moment
        it was last banked and a refused request neither loses nor gains the
        router any weight.  That is also what tells the two readings apart — an
        allowed request leaves strictly less than it found, a refused one
        leaves exactly what it found.

        **This method never waits.**  A refusal is answered immediately; the
        sleeping, the exponential backoff and the jitter are feature 319's, and
        a limiter that waited would be that feature arriving early and
        invisibly.
        """
        instant = _require_aware(
            datetime.now(UTC) if now is None else now, "now"
        )
        name, weight = self._schedule.price(operation)
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    available, refilled_at = self._banked(connection, instant)
                    reading, banked_at = self._reading(
                        name, weight, instant, available, refilled_at
                    )
                    if reading.allowed:
                        connection.execute(
                            f"""
                            INSERT INTO {VENUE_WEIGHT_BUCKET_TABLE} (
                                scope, available, refilled_at
                            ) VALUES (?, ?, ?)
                            ON CONFLICT(scope) DO UPDATE SET
                                available = excluded.available,
                                refilled_at = excluded.refilled_at
                            """,
                            (
                                self._scope,
                                reading.remaining,
                                _isoformat_utc(banked_at),
                            ),
                        )
                    connection.execute("COMMIT")
                except BaseException:
                    # Rolled back defensively, and a rollback that itself
                    # fails is swallowed rather than raised: if ``BEGIN
                    # IMMEDIATE`` was what failed there is no transaction to
                    # roll back, and letting the rollback's "no transaction is
                    # active" replace the *real* failure would report a
                    # contention symptom in place of its cause.
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not meter {name!r} against the venue weight budget "
                f"metered as {self._scope!r}: {exc} (feature 318)"
            ) from exc
        if not reading.allowed:
            raise RouterRateLimitedError(
                f"{RATE_LIMITED_CODE}: {name!r} costs {weight} weight units "
                f"and the budget metered as {self._scope!r} holds "
                f"{reading.accrued} of {self._schedule.allowance}; the request "
                f"was refused rather than sent, and it leaves the bucket "
                f"untouched — {reading.retry_after} brings the weight it needs "
                "back (feature 318)",
                headroom=reading,
            )
        return reading

    def headroom(
        self, operation: str, *, now: datetime | None = None
    ) -> RateLimitHeadroom:
        """What ``operation`` would read off the bucket, without spending it.

        The read-only twin of :meth:`acquire`, and a genuinely different
        question rather than a second spelling of the same one: §16 lists
        *"rate-limit headroom"* among the live metrics, and a dashboard asking
        *how much budget is left?* must not have to make a request to find out
        — nor may it, since asking is what spends the weight.

        The reading's ``allowed`` is whether the operation *would* be admitted
        right now, and its ``remaining`` is what the bucket would hold after
        the spend if it were — that is, the answer to *"how much budget is
        left?"* for a caller about to make this request.  A question costs the
        venue nothing: this writes nothing either, so the bucket's accrual
        keeps running from the moment it was last banked rather than being
        reset by a read, and this never creates the scope's row — a deployment
        that only ever asks leaves no bucket behind, and the figure a fresh
        deployment reads is the whole allowance, which is exactly what the
        venue has granted it.

        Nothing here waits, refuses or raises for a spent budget: the answer
        *is* the budget, and a caller that wants the refusal asks
        :meth:`acquire`.  A defect in the *addressing* or the stored bucket
        still raises — see :meth:`_banked`.
        """
        instant = _require_aware(
            datetime.now(UTC) if now is None else now, "now"
        )
        name, weight = self._schedule.price(operation)
        try:
            with closing(self._connect()) as connection:
                available, refilled_at = self._banked(connection, instant)
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the venue weight budget metered as "
                f"{self._scope!r}: {exc} (feature 318)"
            ) from exc
        reading, _ = self._reading(name, weight, instant, available, refilled_at)
        return reading
