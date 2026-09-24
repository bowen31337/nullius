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

* :class:`RouterClientOrderIdError` — feature 316's derived-identity
  contract, and a *sibling* of the four classes above rather than a child
  of any of them.  Its noun is the order's own name — the idempotent
  resubmission key hashed out of a book, a rebalance and a symbol — which
  is not a fetched document (:class:`RouterFilterError`), not a persisted
  filter version (:class:`RouterStoreError`) and not the router's liveness
  (:class:`RouterSubmissionHealthError`): a ``book_id`` or ``symbol`` that
  states no name, a ``rebalance_ts`` that is naive or not a moment, a
  presented key that is not the 64 hex characters a derived one is, or a
  value whose stated key disagrees with its own terms, are none of those
  repairs — and every one of them is a way to derive *two* keys for one
  order, which is the one state the feature exists to make impossible.

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

* :class:`RouterSubmissionResultError` — feature 317's fault, and a *sibling*
  of every class above rather than a child of any of them.  Its noun is the
  order the sentence is *about*: a duplicate test reads one key and one
  placement record, and a value that cannot be either — a ``place`` the store
  cannot call, an order that is not named by feature 316's key, a stored row
  whose outcome is not a placement or whose moment no parser accepts — leaves
  the sentence with nothing to compare, so a caller told it was a bad fetch
  (:class:`RouterFilterError`), a filter version that did not land
  (:class:`RouterStoreError`), the router's liveness
  (:class:`RouterSubmissionHealthError`) or a pacing fault
  (:class:`RouterRateLimitError`) would repair the wrong thing.  It is
  deliberately **not** :class:`RouterClientOrderIdError`: a key that is not 64
  hex characters is refused in that class by feature 316's own function, and
  this class is for the faults one step further along — the *ask to place* and
  the *stored result* — whose repair is to fix the call or the row rather than
  to fix the derivation.

* :class:`RouterCrossMarginError` — feature 315's fault, and a *sibling* of
  every class above rather than a child of any of them.  Its noun is the
  *arrangement a book's positions settle under* — the margin mode and the
  account those positions live in — which is not a fetched document
  (:class:`RouterFilterError`), not a persisted filter version
  (:class:`RouterStoreError`), not the router's liveness
  (:class:`RouterSubmissionHealthError`), not the order's own name
  (:class:`RouterClientOrderIdError`), not a pacing fault
  (:class:`RouterRateLimitError`) and not the placement being asked about
  (:class:`RouterSubmissionResultError`): a configuration that merges two
  books' positions is none of those repairs, and a caller told any of them
  would go and fix the wrong thing while the venue kept one position with N
  legs.  It is deliberately **not** :class:`RouterClientOrderIdError` even
  though both judge a ``book_id``: that class refuses a name it cannot hash
  *into a key*, while this one refuses an arrangement *that name's book* is
  configured with — the book is spelled perfectly well in the fault this
  class reports, and it is the margin around it that is wrong.

Every message names the offending value and the contract it broke, because
these are operational signals for a pipeline the order path trusts for its
step size and tick size, not debugging aids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, and limiter imports this
    from .limiter import RateLimitHeadroom

__all__ = [
    "CLIENT_ORDER_ID_CODE",
    "CROSS_MARGIN_CODE",
    "ORDER_SUBMISSION_UNHEALTHY_CODE",
    "RATE_LIMITED_CODE",
    "RETRY_BACKOFF_CODE",
    "SUBMISSION_RESULT_CODE",
    "WEIGHT_BUCKET_CODE",
    "WEIGHT_SCHEDULE_CODE",
    "RouterClientOrderIdError",
    "RouterCrossMarginError",
    "RouterError",
    "RouterFilterError",
    "RouterRateLimitedError",
    "RouterRetryError",
    "RouterStoreError",
    "RouterSubmissionHealthError",
    "RouterSubmissionResultError",
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

#: Feature 316's greppable token, for the derivation of the order path's
#: idempotent resubmission key.  Every
#: :class:`RouterClientOrderIdError` message opens with it, so a malformed
#: derive ask — and a presented key that is not one — is one grep apart
#: from the submission outcomes feature 320 records (whose
#: ``client_order_id`` column *joins* on this key but is never this
#: module's to interpret) and from the rejections the venue itself sends,
#: which feature 320 writes down and this module never does.
CLIENT_ORDER_ID_CODE = "client_order_id"

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

#: Feature 317's greppable token, for the derivation of the order path's
#: duplicate answer.  Every :class:`RouterSubmissionResultError` message opens
#: with it, so a malformed place ask — and a stored placement row this store
#: cannot report — is one grep apart from the *identifier* faults feature 316
#: names (:data:`CLIENT_ORDER_ID_CODE`, whose derivation this feature reads
#: but never owns) and from the submission outcomes feature 320 records
#: (whose ``client_order_id`` column *joins* on the same key and is never
#: this module's to interpret).  It deliberately does not spell ``duplicate``:
#: a duplicate is this feature's *success* — the sentence's answer, not a
#: fault — and a token that named it would send an operator grepping for
#: faults to the rows that are working.
SUBMISSION_RESULT_CODE = "submission_result"

#: Feature 315's greppable token, for a *margin arrangement* this system will
#: not trade under.  Every :class:`RouterCrossMarginError` message opens with
#: it, so a configuration fault is one grep apart from the venue's own
#: rejections (which feature 320 records and this member never writes) and
#: from the *identifier* faults feature 316 names
#: (:data:`CLIENT_ORDER_ID_CODE`), which also judge a ``book_id`` but refuse a
#: name rather than an arrangement.  It deliberately does not spell ``margin``
#: on its own: ``isolated`` is the mode this system uses and the mode a
#: correct configuration states, so a token that named the noun would send an
#: operator grepping for faults to every configuration that mentions it.
CROSS_MARGIN_CODE = "cross_margin"


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


class RouterClientOrderIdError(RouterError):
    """A client order identifier this module cannot derive or recognize.

    app_spec.xml, "Order Routing & Venue Filters", feature 316: *System
    derives a client order identifier by hashing book id, rebalance
    timestamp and symbol, which returns an idempotent resubmission key.*
    This is the failure of that sentence's *derives*: a ``book_id`` or a
    ``symbol`` that states no name, a ``rebalance_ts`` that is naive or not
    a moment at all, a presented key that is not the 64 hex characters a
    derived one is, or a value whose stated key disagrees with the terms it
    carries.  Idempotence is the feature's whole output, and every one of
    those faults is a way to end up with *two* keys for one order — the
    exact state the feature exists to make impossible, so it is raised
    rather than shrugged into a near-miss identity.

    A sibling of the fetch fault (:class:`RouterFilterError`), the record
    fault (:class:`RouterStoreError`) and the health fault
    (:class:`RouterSubmissionHealthError`) rather than a child of any of
    them, because the noun is the order's own name — none of those three
    repairs repairs it, and a caller told the wrong one would edit the
    wrong file.

    Every message opens with :data:`CLIENT_ORDER_ID_CODE` and names the
    offending value, because an order path that cannot name its order
    cannot resubmit it, and the operator's grep is the first place that
    fact has to reach.
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


class RouterCrossMarginError(RouterError):
    """A margin arrangement that would merge two books' independent positions.

    app_spec.xml, "Order Routing & Venue Filters", feature 315: *System uses
    isolated margin per book, which rejects a cross-margin configuration that
    would merge independent positions.*  This is the failure of that
    sentence's *rejects*: a book configured to settle its positions under
    cross margin — the whole account's balance standing behind every leg —
    when the sentence requires each book's positions to be margined on their
    own.  ``docs/nullius-tech-architecture.md`` §13.2 and
    ``docs/alpha-engine-prd.md`` C9 state the reason in one line each: *"Cross
    margin converts N independent positions into one position with N legs, and
    a single leg's liquidation cascades into the rest."*

    **The noun is the arrangement, not the book's spelling.**  A sibling of
    the fetch fault (:class:`RouterFilterError`), the record fault
    (:class:`RouterStoreError`), the health fault
    (:class:`RouterSubmissionHealthError`), the derived-identity fault
    (:class:`RouterClientOrderIdError`), the rate-limit tree
    (:class:`RouterRateLimitError`) and the duplicate-submission fault
    (:class:`RouterSubmissionResultError`) rather than a child of any of
    them, because none of those repairs repairs a merged margin account.  The
    split from :class:`RouterClientOrderIdError` is the fine one: both judge
    a ``book_id``, and that class refuses a name it cannot *hash into a key*
    while this one refuses the *arrangement that name's book* is configured
    with — the name in this fault is perfectly well formed, and a caller sent
    to fix its spelling instead of its margin mode would leave the venue
    holding one position with N legs.

    Every message opens with :data:`CROSS_MARGIN_CODE`, and names the book,
    the account and the mode that was supplied, because a deployment editing
    its book configuration is the audience and the repair — *margin this
    book on its own* — is one line of a config file, not a stack trace.
    """


class RouterSubmissionResultError(RouterError):
    """A duplicate-submission ask this store cannot answer or record.

    app_spec.xml, "Order Routing & Venue Filters", feature 317: *System
    returns the prior result for a duplicate client order identifier rather
    than placing a second order.*  This is the failure of that sentence's
    *judgment*: a placement the store cannot call, an order it cannot name by
    feature 316's key, an outcome that is not a placement (a venue rejection
    in particular — that placed nothing, and a second attempt at it is the
    *retry* the order path is entitled to make rather than a duplicate), or a
    stored row whose outcome or moment is not one a placement can have.  In
    every one of those the sentence has nothing to compare, so this is raised
    rather than shrugged into a near-miss answer that would report an order
    as placed — or as a duplicate — on evidence that cannot support either.

    A sibling of the fetch fault (:class:`RouterFilterError`), the record
    fault (:class:`RouterStoreError`), the health fault
    (:class:`RouterSubmissionHealthError`), the derived-identity fault
    (:class:`RouterClientOrderIdError`) and the rate-limit tree
    (:class:`RouterRateLimitError`) rather than a child of any of them: the
    noun is *the placement being asked about*, and none of those repairs
    repairs it.  The split from :class:`RouterClientOrderIdError` is the fine
    one and is deliberate — a key that is not 64 hex characters is refused in
    *that* class by feature 316's own validation, which this module reads
    rather than re-implements, so a caller catching the identifier's fault
    still catches it by name; this class is for the ask and the row one step
    further along.

    Every message opens with :data:`SUBMISSION_RESULT_CODE` and names the
    offending value — the key, the symbol, the outcome — because a store that
    cannot name the order it refused cannot be repaired by anyone but its
    author.
    """
