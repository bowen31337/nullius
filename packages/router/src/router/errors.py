"""The router plugin's error taxonomy.

One base class (:class:`RouterError`) so a caller — the order path built on
this member, an operator tool — can catch every failure of this package
with a single ``except``.  The subclasses split by *which contract* was
violated, not by which line of code failed:

* :class:`RouterFilterError` — the fetched-document contract.  Feature 310
  persists *the fetched exchangeInfo version*, and a payload that
  :mod:`nullius_ingest.exchange_info` will not parse as one (not JSON, no
  ``symbols`` list, a symbol with no filters, a duplicated symbol) is not a
  version at all.  Raised at the seam that receives the fetch, translated
  from :class:`nullius_ingest.exchange_info.ExchangeInfoParseError` rather
  than let through by name — a caller catching this package's one
  vocabulary must not have to also import the ingest member's own errors to
  catch a bad document (see the "error vocabulary at member seams"
  discipline this workspace follows elsewhere: a shared parser raising its
  own module's error type defeats the caller's ``except``).
* :class:`RouterStoreError` — the persisted-record contract.  Feature 310
  says the fetched version is *persisted*, so a store that was configured
  and then failed to take the row is an error rather than a shrug: the
  alternative is an exchangeInfo version that resolved but never landed,
  which is exactly the "hardcoded venue constant" state feature 311 exists
  to prevent downstream. A store that was never configured at all is not
  this error — see :mod:`router.store` for the stance that separates the
  two.
* :class:`RouterSubmissionHealthError` — feature 320's persisted-health
  contract, and a *sibling* of the three classes above rather than a child
  of any of them.  Its noun is the router's own liveness, not a fetched
  document (:class:`RouterFilterError`) and not a stored filter version
  (:class:`RouterStoreError`): a submission observation that cannot be
  recorded — because the identity it names states no process, the moment it
  names states no time, the window it is read against cannot be a window, or
  the row that came back states something a submission outcome cannot be —
  is none of those repairs, so a caller catching it must not be told it is.
  This is the same split :mod:`regime.errors` states for its own category
  (*"a caller catching them together would read the wrong repair"*), and the
  same vocabulary :mod:`regime.origins` inherits: a bad *address*
  (a ``DATABASE_URL`` this member cannot speak) stays
  :class:`RouterStoreError` in both features, because that fault and its
  repair — point the deployment at a database this store can open — are one
  fact the member already names once.

* :class:`RouterWeightScheduleError` and :class:`RouterWeightBucketError` —
  feature 318's two faults, which share the intermediate base
  :class:`RouterRateLimitError` because they are two repairs to one system:
  *fix the weights you stated* and *fix the bucket you wrote*.  They are
  separate classes rather than one because a caller told the wrong one would
  edit the wrong file, and a base rather than two more siblings because *"did
  the limiter refuse me?"* is a question a caller asks as one thing.  A
  *refusal* — the bucket could not serve the request — is the third class
  under that base, :class:`RouterRateLimitedError`, and it is the one class in
  this module that carries a value (see its own docstring on why: the reading
  the feature returns is what a caller must act on).

* :class:`RouterRetryError` — feature 319's fault, and the fourth class under
  :class:`RouterRateLimitError`: a retry this module cannot pace.  Its noun is
  the *waiting* the refusal asked for — a budget that is not a count, a
  backoff that is not exponential, a jitter that is not a bound, a request
  that cannot be called, a sink that cannot receive.  It sits under the
  rate-limit base because the retry is the limiter's own answer to its own
  refusal, so a caller asking *"is the rate-limited path unhappy?"* catches
  one base — and it is deliberately **not** a
  :class:`RouterRateLimitedError`, because the bucket refused nothing: the
  *ask to wait on it* was the malformed thing.

Every message names the offending value and the contract it broke, because
these are operational signals for a pipeline the order path trusts for its
step size and tick size, not debugging aids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, and limiter imports this
    from .limiter import RateLimitHeadroom

__all__ = [
    "ORDER_SUBMISSION_UNHEALTHY_CODE",
    "RATE_LIMITED_CODE",
    "RETRY_BACKOFF_CODE",
    "WEIGHT_BUCKET_CODE",
    "WEIGHT_SCHEDULE_CODE",
    "RouterError",
    "RouterFilterError",
    "RouterRateLimitedError",
    "RouterRetryError",
    "RouterStoreError",
    "RouterSubmissionHealthError",
    "RouterWeightBucketError",
    "RouterWeightScheduleError",
]

#: The greppable one word every :class:`RouterSubmissionHealthError` message
#: opens with, following the ``pool_frozen`` (feature 270) /
#: ``illegal_theme`` (feature 241) / ``no_origin`` (feature 288) precedent:
#: an operator scanning a log for submission-health refusals greps one token
#: rather than a sentence.  It deliberately does not spell ``feed`` — the
#: whole point of feature 320 is that this health is not the feed's — and it
#: does not spell ``live``, which is feature 321's authority vocabulary and a
#: different refusal with a different repair.
ORDER_SUBMISSION_UNHEALTHY_CODE = "order_submission_unhealthy"

#: Feature 318's greppable token, for the refusal a *spent budget* produces.
#: Every :class:`RouterRateLimitedError` message opens with it, so a rate
#: limiter's refusals are one grep apart from the venue's own rejections —
#: which feature 320 records and which this module never writes.
RATE_LIMITED_CODE = "rate_limited"

#: Feature 318's greppable token for a *schedule* this limiter cannot be
#: matched to: an allowance that is not a positive whole number of weight
#: units, a window over which no allowance is a rate, a limit type that is
#: not the venue's weight limit, or a request priced outside the schedule.
WEIGHT_SCHEDULE_CODE = "weight_schedule"

#: Feature 318's greppable token for a *bucket* that cannot be read or
#: refilled: a scope that names nothing, a moment that is naive or is not a
#: moment, or a stored bucket whose state is not one a bucket can be in.
WEIGHT_BUCKET_CODE = "weight_bucket"

#: Feature 319's greppable token for a *retry* this module cannot pace: a
#: budget that is not a count, a backoff that is not exponential, a jitter
#: that is not a bound, a request that cannot be called, or a sink that
#: cannot receive the retry event.  Every
#: :class:`RouterRetryError` message opens with it, so a malformed retry ask
#: is one grep apart from the refusal that prompted it — which is
#: :data:`RATE_LIMITED_CODE`, feature 318's, and a different fault with a
#: different repair.
RETRY_BACKOFF_CODE = "retry_backoff"


class RouterError(Exception):
    """Base class for every failure of the router package."""


class RouterFilterError(ValueError, RouterError):
    """A fetched payload is not a well-formed exchangeInfo document.

    Dual-inherited: a malformed fetch is a :class:`ValueError` the way the
    ingest member's own parse failures are, and it is also a
    :class:`RouterError`, so a caller catching this package's single
    vocabulary catches a bad document along with a failed persist.

    Raised for the document's own defects — not JSON, no ``symbols`` list, a
    symbol with no filters, a duplicated symbol, a filter with no type — and
    never for a store failure, which is :class:`RouterStoreError`.
    """


class RouterStoreError(RouterError):
    """The fetched exchangeInfo version could not be persisted or read back.

    Feature 310: *"System persists the fetched exchangeInfo version carrying
    lot size, notional, price filter, step size and tick size."*  This is
    the failure of that sentence's verb: the document parsed, and the
    version that records it did not land (or a persisted version could not
    be read back).  Raised rather than swallowed — a version that resolved
    but was never persisted is exactly the gap the feature closes.

    A store that is merely *absent* (no ``DATABASE_URL``, and no explicit
    URL passed) is not this error: this package treats "no relational store
    configured" as a supported state and refuses the operation with this
    error only at the moment a caller actually asks for one, naming the
    variable that would have named the store.
    """


class RouterSubmissionHealthError(RouterError):
    """The router's own submission health could not be recorded or read back.

    app_spec.xml, "Order Routing & Venue Filters", feature 320: *"System
    persists order submission health independently of feed health, running
    the router in its own process."*  This is the failure of that sentence's
    verb, and it is deliberately **not** a failure of the venue or of the
    order path: a submission observation the router's own process took and
    could not write down is a fact about the router's bookkeeping, not a bad
    fetch (:class:`RouterFilterError`) and not a filter version that failed
    to land (:class:`RouterStoreError`).  The noun is *the router's own
    liveness*, which is the one noun feature 320 adds.

    Raised for the ask (an identity that names no process, a moment that is
    naive, a window that cannot be a window), for the row (a stored outcome
    that is not one of the two a submission can have) and for the read (a
    window read out of a store this member cannot open).  A store that is
    merely *absent* is not this error, for the same reason it is not
    :class:`RouterStoreError`: no configured store is a supported deployment
    state, and the refusal belongs to the caller that demands an observation
    anyway.

    Every message opens with :data:`ORDER_SUBMISSION_UNHEALTHY_CODE` so an
    operator greps one token, and names the process and the moment it is
    about, because a health record that cannot be attributed to a process and
    an instant is not a health record — which is the whole subject of this
    feature.
    """


class RouterRateLimitError(RouterError):
    """Base class for feature 318's two weight-metering faults.

    Not raised directly — it exists so a caller that cares only about *"did
    the limiter refuse me?"* catches one class, whatever the reason, while a
    caller that must repair the *cause* catches the subclass that names it.
    That is the split :class:`~nullius_ingest.ExchangeInfoParseError` and its
    own siblings keep, and the reason the two subclasses below share a base
    rather than being siblings of each other.

    A child of :class:`RouterError` and of nothing else in this package: a
    spent weight budget and an unmatchable schedule are both faults of the
    router's *own* metering, so a caller catching the fetch fault
    (:class:`RouterFilterError`) or the submission-health fault
    (:class:`RouterSubmissionHealthError`) must not be told either is theirs.
    """


class RouterWeightScheduleError(RouterRateLimitError):
    """A weight schedule this limiter cannot be matched to.

    app_spec.xml, "Order Routing & Venue Filters", feature 318: *"System
    applies a token-bucket rate limiter matched to the venue weight
    schedule."*  A schedule is the sentence's noun, so a schedule that cannot
    be one — an allowance that is not a positive whole number of weight units,
    a window over which no allowance is a rate, a limit type that is the
    venue's *count* limit rather than its weight budget, or a request priced
    outside the schedule — is the failure of its *match*.

    Raised when a schedule is constructed and when a request is priced against
    one; every message opens with :data:`WEIGHT_SCHEDULE_CODE` and names the
    offending value, because a deployment editing its venue weights is the
    audience and it needs the line, not a stack.
    """


class RouterWeightBucketError(RouterRateLimitError):
    """The weight bucket could not be refilled, read or banked.

    The fault whose noun is the *bucket* rather than the schedule: a scope
    that names no budget, a moment that is naive or is not a moment, or a
    stored bucket holding a state no bucket can be in (a negative fill, an
    unparseable accrual moment).  Split from
    :class:`RouterWeightScheduleError` because the repairs differ — one is
    *fix the table you wrote*, the other *fix the weights you stated* — and a
    caller told the wrong one would edit the wrong file.

    Every message opens with :data:`WEIGHT_BUCKET_CODE`.  An *address* fault
    (a ``DATABASE_URL`` this member cannot speak) is deliberately **not** this
    error: it stays :class:`RouterStoreError`, the member's existing
    vocabulary for that fault, exactly as :mod:`router.submission_health`
    states for its own table.
    """


class RouterRateLimitedError(RouterRateLimitError):
    """The venue's weight budget cannot serve the request that asked.

    Feature 318: *"System applies a token-bucket rate limiter matched to the
    venue weight schedule, which returns remaining headroom per request."*
    This is the sentence's *applying* — the bucket held less than the request
    is priced at, so the request was not allowed through.  It is an error
    rather than a ``False`` because the feature's verb is *applies*: a record
    saying "not allowed" would put enforcement at every call site, and the
    one place the venue's budget is known is here.

    **It carries the headroom.**  :attr:`headroom` is the
    :class:`~router.limiter.RateLimitHeadroom` the refused request read off
    the bucket — so *"returns remaining headroom per request"* is true of a
    refused request too, and feature 319's backoff reads how far short the
    bucket fell (``.headroom.deficit``, ``.headroom.shortfall``,
    ``.headroom.retry_after``) without a second query.  That is why this
    class carries a value at all, where every other class in this module
    carries only a message: the reading is the feature's own output and a
    caller that must act on the refusal is its audience.

    Every message opens with :data:`RATE_LIMITED_CODE` and names the scope,
    the operation and the weight that was asked for, because a router pacing
    itself against a shared budget needs to know *which* budget refused it —
    two credentials read as one scope being exactly the misconfiguration
    :data:`~router.limiter.DEFAULT_WEIGHT_SCOPE` warns about.
    """

    def __init__(self, message: str, *, headroom: RateLimitHeadroom) -> None:
        super().__init__(message)
        self.headroom = headroom

    @property
    def retry_after(self) -> object:
        """The wait feature 319 needs, read off the carried headroom.

        A straight pass-through, deliberately: the arithmetic belongs to
        :attr:`~router.limiter.RateLimitHeadroom.retry_after` — which is
        exact and derived from the schedule — and this property exists only
        so a caller catching the refusal can ask the exception the one
        question a refusal raises without reaching through it first.  It is
        *not* a second spelling of the number, and nothing here waits on it.
        """
        return self.headroom.retry_after


class RouterRetryError(RouterRateLimitError):
    """A retry this module cannot pace — the ask, not the bucket.

    app_spec.xml, "Order Routing & Venue Filters", feature 319: *"System
    retries a rate-limited request with exponential backoff plus jitter."*
    This is the failure of that sentence's ask rather than of its request: a
    ``retries`` budget that is not a genuine count, a backoff schedule that
    is not exponential (a multiplier of one) or not bounded (a jitter that is
    no fraction at all), a request that cannot be called, an event sink that
    cannot receive, or a refusal that names no wait a backoff could read a
    floor from.  All of them are refused **eagerly** — before the request is
    sent even once — because a retry that began sleeping before its ask was
    checked would have a caller believe a malformed retry was accepted.

    A child of :class:`RouterRateLimitError` and of nothing else: the retry
    is the limiter's own answer to its own refusal, so a caller catching the
    rate-limit base catches this along with the three faults above.  It is
    deliberately **not** a :class:`RouterRateLimitedError`, because nothing
    was refused — the bucket did its job, the schedule did its job, and the
    thing that came in wrong is the *waiting* the caller asked this module
    to do about them.  A caller that catches only
    :class:`RouterRateLimitedError` (the refusal) must not have a malformed
    retry ask land in that ``except`` — the two repairs are unrelated: one
    is *wait or shed load*, the other is *fix the retry you asked for*.

    Every message opens with :data:`RETRY_BACKOFF_CODE`, so an operator
    greps one token for retry faults — a token that is not
    :data:`RATE_LIMITED_CODE`, whose grep the refusal itself owns.
    """
