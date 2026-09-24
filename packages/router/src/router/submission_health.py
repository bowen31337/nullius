"""Feature 320: the router's own submission health, persisted independently.

app_spec.xml, "Order Routing & Venue Filters", feature 320: *"System
persists order submission health independently of feed health, running the
router in its own process."*  ``docs/nullius-tech-architecture.md`` §13.2
gives that sentence its reason in six words (line 706): *"``asyncio`` +
websockets for market data; separate process for the order router."*  §14
states the operational stake: *"Live trading — 24/7 stateful ... **Never on
spot.** Separate VPC, separate credentials"*, and §17 adds the one thing
that makes the separation load-bearing rather than tidy — *"No inbound
ports on the live trading host."*

Read together, those lines say something narrower and harder than *"record
whether orders went through"*: **the router's liveness must be observable
from a state that a dead or wedged router cannot take with it.**  A health
flag held in the router's own memory is unreadable at exactly the moment it
is wanted — the process is hung, the feed is stalled, the machine is gone —
and a health flag derived from the *market-data feed* is not the router's
health at all: it reports the websocket's liveness and goes quiet for
reasons that have nothing to do with whether orders are reaching the venue.
So this module does the two things the sentence's own words do, and nothing
else:

* **It persists.**  Every submission attempt the router's order path takes —
  accepted or rejected by the venue — lands as one row in this member's own
  table in the workspace's relational store (``DATABASE_URL``), the same
  address feature 310's exchangeInfo version log uses and for the same
  reason: the database, not any process's memory, is the coordination point.
* **It is independent of feed health.**  The *only* input to this module is
  a submission outcome the order path observed.  Nothing here reads a
  websocket, a heartbeat, a market-data watermark, a staleness clock or the
  ingest member's own streams (:mod:`nullius_ingest.streams`,
  :mod:`nullius_ingest.gaps`) — a router that never receives a quote but
  keeps placing accepted orders reports *healthy*, because that is the truth
  about order submission, and a router receiving a perfect feed whose every
  order is rejected reports *unhealthy*, because that is the other truth.
  The feed has its own features and its own member; this module does not
  restate, subscribe to or infer from any of them.

**The process identity is what makes "independently" checkable.**  A health
reading is only independent of the feed's if a reader can tell *which
process* produced it — otherwise one number from one router is silently
attributed to the deployment, which is the failure ``docs`` §17's
no-inbound-ports stance and §14's separate-host rule both exist to keep
visible.  So every row carries the identity of the process that took the
observation, derived by :func:`process_identity` from the host and the pid
(``<host>/<pid>``) rather than accepted from the caller: a health record is
a statement about *this* process, and a caller-supplied label would let two
processes' submissions be filed under one name.  The identity is a *label*,
not a measurement — it is not an address, and nothing here opens a
connection, resolves a hostname or asks another process anything; it is the
token :meth:`RouterSubmissionHealthStore.health` groups by, so a reader can
ask either *"is this process submitting successfully?"* (one identity) or
*"is anything submitting successfully?"* (every identity, the default) and
tell the two answers apart.

**The reading is a window, and the window is the whole sample-size control.**
:meth:`RouterSubmissionHealthStore.health` reads the submissions recorded in
a half-open-in-neither-direction window ending at ``now`` and answers a
three-valued verdict:

* ``None`` — the window holds **no submissions at all**.  This is
  *unmeasured*, and it is deliberately not spelled ``False``: a router that
  has not yet attempted an order is not a router whose orders are failing,
  and a reader that collapsed the two would page on every quiet window and
  stop trusting the alarm.  The distinction is the one the workspace states
  everywhere it refuses to zero an empty denominator (feature 236's
  measured-barren versus unmeasured; :mod:`scoring._switches`' unlabelled
  horizon; :mod:`bootstrap`'s empty class).
* ``False`` — the window holds submissions and the venue rejected fewer than
  :data:`SUBMISSION_HEALTH_FAILURE_RATIO` of them.
* ``True`` — the window holds submissions and the venue rejected at least
  that proportion of them.

**No minimum-sample rule is stated here, and that is deliberate.**  A
*statistically meaningful observation window* before an automatic demotion
fires is declared as its own feature (327, "Risk Supervisor & Kill
Switches"), with its own member and its own repair; restating a floor here
would be a second, disagreeing spelling of one law, and it would put a
statistical threshold in front of an operator's liveness signal — the one
reading that must not be gated behind a sample the router may die before
accumulating.  The window is the control this feature offers; the bar on
the rate within it is a single, greppable constant
(:data:`SUBMISSION_HEALTH_FAILURE_RATIO`, a
:class:`~fractions.Fraction` so the comparison is exact rather than a float
near-miss), and a deployment that wants a different bar passes its own
``window`` and reads the ratio off the record itself.

**Rejections are the signal, and only rejections are.**  A venue refusing an
order is the router's problem — a stale filter grid, an unauthorised live
flag, a rate-limit blow-through, an account in the wrong margin mode — and
every one of those is a feature of *this* category.  So the record keeps the
two outcomes apart rather than storing a boolean, and the health verdict is
computed from the pair on the read: a later feature that wants to separate
"rejected for insufficient margin" from "rejected for a step-size mismatch"
has the raw rows to do it with, and this module does not have to guess which
distinction will matter.

**The outcome vocabulary is closed, and a row outside it is refused rather
than counted.**  SQLite columns are dynamically typed, so a raw ``INSERT``
from another tool — an operator at a sqlite3 prompt, a backfill script —
can land anything in the ``outcome`` column, including a spelling this
module never writes.  Counting an unrecognised outcome as *accepted* would
understate the rejection rate, which is the one direction that lets a router
that is failing look well (the same argument :mod:`scoring._deflation` makes
for refusing an understated ``K``), so a stored row whose outcome is outside
:data:`ORDER_SUBMISSION_OUTCOMES` is refused by name when it is read, naming
the process and the moment it came from.

**What this module deliberately does not do.**  It does not *halt*, *flatten*
or *throttle* anything: halting on a threshold is the risk supervisor's kill
instruction (feature 322) and the daily-loss and staleness triggers belong to
its own features (325, 328), so this module answers a reading and leaves
every consequence to the features that own one.  It does not *decide whether
an order is authorised* — that is feature 321's live flag, a different
question with a different error.  It does not *record the venue's response
text* or an order's fill: this is a liveness ledger, not an order log, and
feature 316/317's client order id is carried only so an operator can join
back to the order path's own record, never interpreted here.  And it does
not *prune*: retention is an operator's policy over elapsed time, and a
``DELETE`` in this module would be a second writer of the one table whose
completeness the reading depends on.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as this member's exchangeInfo log is, and the schema is created
idempotently on connect, so no migration step is needed.  A URL whose scheme
is not ``sqlite`` is refused by name — as an *address* fault, in
:class:`~router.errors.RouterStoreError`, the member's existing vocabulary
for that fault, rather than in this feature's own class; see
:meth:`RouterSubmissionHealthStore.health`.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse

from ._identity import process_identity
from .errors import (
    ORDER_SUBMISSION_UNHEALTHY_CODE,
    RouterStoreError,
    RouterSubmissionHealthError,
)

__all__ = [
    "DATABASE_URL_ENV",
    "ORDER_SUBMISSION_ACCEPTED",
    "ORDER_SUBMISSION_HEALTH_TABLE",
    "ORDER_SUBMISSION_OUTCOMES",
    "ORDER_SUBMISSION_REJECTED",
    "SUBMISSION_HEALTH_FAILURE_RATIO",
    "SUBMISSION_HEALTH_WINDOW",
    "RouterSubmissionHealthStore",
    "SubmissionHealth",
    "SubmissionObservation",
    "process_identity",
]

#: The workspace-wide environment variable naming the relational store.
DATABASE_URL_ENV = "DATABASE_URL"

#: One row per submission attempt the router's order path observed.
ORDER_SUBMISSION_HEALTH_TABLE = "router_order_submission_health"

#: The venue took the order.  The greppable token the row stores.
ORDER_SUBMISSION_ACCEPTED = "accepted"

#: The venue refused the order.  The greppable token the row stores.
ORDER_SUBMISSION_REJECTED = "rejected"

#: The closed outcome vocabulary — exactly the two states a submission
#: attempt can be in, and the set the stored ``CHECK`` constraint is built
#: from so the table and the value layer cannot drift.
ORDER_SUBMISSION_OUTCOMES = frozenset(
    {ORDER_SUBMISSION_ACCEPTED, ORDER_SUBMISSION_REJECTED}
)

#: The proportion of rejections in a window at or above which the window's
#: submissions read as *unhealthy*.  A :class:`~fractions.Fraction` rather
#: than a float so ``rejected / total >= ratio`` is an exact comparison: a
#: binary-float half would make a window of two submissions with one
#: rejection a near-miss whose verdict depended on rounding, and the whole
#: point of a greppable bar is that it decides.  One half is the natural
#: bar — a router whose orders fail as often as they succeed is not
#: trading — and a deployment that wants another passes its own window and
#: reads :attr:`SubmissionHealth.rejection_ratio` itself.
SUBMISSION_HEALTH_FAILURE_RATIO = Fraction(1, 2)

#: The default window a health reading covers: the recent past, long enough
#: to hold a rebalance's worth of attempts and short enough that a router
#: which has just been fixed stops reading unhealthy promptly.  A readonly
#: default rather than a law — every read may pass its own — and quoted by
#: the tests and by the order path's own call site so the number lives once.
SUBMISSION_HEALTH_WINDOW = timedelta(minutes=5)

#: The ``CHECK`` constraint the outcome column carries, built from
#: :data:`ORDER_SUBMISSION_OUTCOMES` in sorted order so the DDL is
#: deterministic and a third outcome added to the set cannot land a table
#: that accepts it while the value layer refuses it.
_OUTCOME_CHECK = ", ".join(f"'{outcome}'" for outcome in sorted(ORDER_SUBMISSION_OUTCOMES))

_SCHEMA = f"""
-- Feature 320: one row per submission attempt the router's order path took.
--
-- No surrogate key and no AUTOINCREMENT: a submission attempt is not a
-- sequence and nothing addresses one row individually -- the reading is a
-- window over the table, which is what the index below is for.  This is the
-- shape difference between this table and feature 310's version log, whose
-- AUTOINCREMENT *is* the version number.
CREATE TABLE IF NOT EXISTS {ORDER_SUBMISSION_HEALTH_TABLE} (
    observed_at     TEXT NOT NULL,  -- ISO 8601 UTC: when the attempt happened
    process_id      TEXT NOT NULL,  -- the router process that took it
    outcome         TEXT NOT NULL CHECK (outcome IN ({_OUTCOME_CHECK})),
    symbol          TEXT,           -- the symbol the order was for, if known
    client_order_id TEXT            -- feature 316's id, for joining only
);

-- The read is always a time window, so the time column is what is indexed.
-- A reader may narrow further to one process, which the window scan already
-- carries; a second index on the pair would cost a write per attempt to
-- save a filter over rows the window has already bounded.
CREATE INDEX IF NOT EXISTS {ORDER_SUBMISSION_HEALTH_TABLE}_observed_at
    ON {ORDER_SUBMISSION_HEALTH_TABLE} (observed_at);
"""


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation this member's own :func:`router.store._sqlite_path`
    states, in this module's own words, for the reason every store in this
    workspace restates it: a store reaches into no sibling's private helper,
    so a later change to one table's address handling cannot silently move
    another's.  ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is
    absolute, and any other scheme is refused by name.

    Raises :class:`~router.errors.RouterStoreError`, **not** this feature's
    own class: an address this member cannot speak is an *address* fault
    with an address repair — point the deployment at a database this store
    can open — which is the face :class:`~router.errors.RouterStoreError`
    already carries for this variable.  The member keeps one vocabulary for
    one fault, and this feature's own class is reserved for the faults whose
    noun is the router's liveness (see :mod:`router.errors`).
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "router's submission-health store speaks sqlite:/// (the spec's "
            "single-machine allowance); point "
            f"{DATABASE_URL_ENV} at the sqlite database the router's own "
            "health is recorded in (feature 320)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 320)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path (feature 320)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    The window reads compare these strings lexicographically, which is
    correct exactly because every row this store writes goes through here:
    one UTC offset, one format, one width.  A row written by another tool in
    another form is not silently mis-ordered — it is read back through
    :meth:`RouterSubmissionHealthStore._observation_from_row`, which refuses
    what :func:`datetime.fromisoformat` will not parse.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* a submission happened,
    and a health window built from one would put two processes' attempts in
    one order or none — the same discipline feature 310's store holds its
    caller to, and the reason it is checked here rather than assumed.
    """
    if not isinstance(moment, datetime):
        raise RouterSubmissionHealthError(
            f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: {what} must be a datetime, "
            f"not {type(moment).__name__} (feature 320)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterSubmissionHealthError(
            f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: {what} must be "
            "timezone-aware; a submission health record must say "
            "unambiguously when the attempt happened (feature 320)"
        )
    return moment


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    The identity and the optional join columns are all *names*, and a name
    that states nothing names no process and no order to attribute an
    attempt to — the same near-miss rule :func:`regime.origins.
    _validated_world_id` takes toward an id with a trailing newline, which
    would be a second identity against a table keyed by the first.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterSubmissionHealthError(
            f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: {what} must be non-empty "
            f"text, got {value!r} ({type(value).__name__}); a health record "
            "that cannot be attributed to a process and a moment is not a "
            "health record (feature 320)"
        )
    return value.strip()


def _require_outcome(value: object) -> str:
    """Return ``value`` as one of the two outcomes, or refuse it by name.

    Membership is tested against the *string* the value would have to be
    rather than against the value itself, because the set membership a
    ``frozenset`` offers raises :class:`TypeError` on an unhashable argument
    — ``[] in ORDER_SUBMISSION_OUTCOMES`` is a crash, not a ``False`` — and a
    caller passing a list to a column of tokens deserves this package's
    refusal naming the value, not a bare ``TypeError`` from a set lookup.
    The ``isinstance`` test is the same one :func:`SubmissionObservation.
    __post_init__` needs anyway: a stored row's outcome arrives as whatever
    the driver handed back, and a non-string there is a typo in the table,
    not a third outcome.
    """
    if not isinstance(value, str) or value not in ORDER_SUBMISSION_OUTCOMES:
        raise RouterSubmissionHealthError(
            f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: a submission outcome is one "
            f"of {sorted(ORDER_SUBMISSION_OUTCOMES)}, got {value!r}; a router "
            "that recorded an attempt under a third spelling has a row no "
            "rejection rate can be read off (feature 320)"
        )
    return value


@dataclass(frozen=True)
class SubmissionObservation:
    """One submission attempt, as the router's own process observed it.

    ``process_id`` is the identity of the process that took the attempt (see
    :func:`process_identity`) — never the order's or the venue's — and
    ``observed_at`` is when the attempt happened, timezone-aware.

    ``symbol`` and ``client_order_id`` are carried so an operator can join a
    spike in the rejection rate back to the order path's own record (feature
    316's idempotent key names the book, the rebalance and the symbol), and
    are deliberately **not** interpreted anywhere in this module: the
    verdict is computed from the outcome pair alone, so a missing symbol or
    an unrecognised client id changes no reading.
    """

    process_id: str
    observed_at: datetime
    outcome: str
    symbol: str | None = None
    client_order_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "process_id", _require_text(self.process_id, "process_id")
        )
        _require_aware(self.observed_at, "observed_at")
        _require_outcome(self.outcome)
        if self.symbol is not None:
            object.__setattr__(self, "symbol", _require_text(self.symbol, "symbol"))
        if self.client_order_id is not None:
            object.__setattr__(
                self,
                "client_order_id",
                _require_text(self.client_order_id, "client_order_id"),
            )

    @property
    def rejected(self) -> bool:
        """Whether the venue refused this attempt.

        The one question the verdict is built from, asked once here so the
        spelling ``outcome == ORDER_SUBMISSION_REJECTED`` has a single home.
        """
        return self.outcome == ORDER_SUBMISSION_REJECTED


@dataclass(frozen=True)
class SubmissionHealth:
    """What the router's own submissions looked like over one window.

    Every figure is derived from the window's rows, never stored beside
    them: the caller holds the counts *and* the pair they were computed
    from, so a reader can audit the verdict against the numbers it came
    from rather than trusting a persisted boolean.

    ``process_id`` names the single process this reading is about, or is
    ``None`` when the reading spans every process that submitted in the
    window — the default, and the reading a supervisor watching the live
    host wants.  ``processes`` lists the distinct identities the window
    actually carried, sorted, so the two cases are distinguishable from the
    record itself and an operator can see a router that has restarted (a new
    pid) without leaving the record.
    """

    process_id: str | None
    since: datetime
    until: datetime
    total: int
    rejected: int
    processes: tuple[str, ...]

    def __post_init__(self) -> None:
        # The counts are derived by the store and by nothing else, but this
        # type is a public value a caller may construct -- and a reading
        # whose rejections exceed its attempts has no ratio, no verdict and
        # no meaning, while every one of its properties would still answer a
        # plausible wrong number (a negative ``accepted``, a ratio above one,
        # a verdict computed from arithmetic that cannot describe a window).
        # Refusing the shape at construction is what keeps the claim that a
        # reader can audit these figures against the rows they came from
        # true of every record, not only the ones this store built.
        if self.rejected < 0 or self.total < 0 or self.rejected > self.total:
            raise RouterSubmissionHealthError(
                f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: a health reading of "
                f"{self.rejected} rejections over {self.total} submissions "
                "is not a shape any window can have; the counts are derived "
                "from the window's rows and a rejection is a subset of an "
                "attempt (feature 320)"
            )
        if self.until < self.since:
            raise RouterSubmissionHealthError(
                f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: a health reading's "
                f"window ends before it begins ({self.until} < {self.since}) "
                "(feature 320)"
            )
        object.__setattr__(self, "processes", tuple(self.processes))

    @property
    def accepted(self) -> int:
        """How many attempts in the window the venue took."""
        return self.total - self.rejected

    @property
    def rejection_ratio(self) -> Fraction | None:
        """Rejected over total, exactly — or ``None`` for an empty window.

        ``None`` rather than ``Fraction(0, 1)`` for the unmeasured case, the
        same stance :attr:`unhealthy` takes and for the same reason: a rate
        over no submissions is undefined, not zero, and a reader that
        substituted zero would read a quiet router as a perfectly clean one.
        """
        if self.total == 0:
            return None
        return Fraction(self.rejected, self.total)

    @property
    def unhealthy(self) -> bool | None:
        """The verdict: ``True``, ``False``, or ``None`` when unmeasured.

        ``None`` means the window carried no submissions at all — *nobody
        tried*, which is not the same fact as *the attempts succeeded* and
        must not be told as one.  Otherwise the window is unhealthy exactly
        when the venue rejected at least
        :data:`SUBMISSION_HEALTH_FAILURE_RATIO` of its attempts.
        """
        if self.total == 0:
            return None
        return Fraction(self.rejected, self.total) >= SUBMISSION_HEALTH_FAILURE_RATIO

    @property
    def measured(self) -> bool:
        """Whether the window carried any submission to judge at all.

        The complement of :attr:`unmeasured`, spelled as its own name
        because the two readings a caller actually writes are *"was this
        measured?"* and *"is this broken?"*, and neither should have to be
        a double negative to ask.
        """
        return self.total > 0

    @property
    def unmeasured(self) -> bool:
        """Whether the window was empty — nobody tried in it.

        ``True`` exactly when :attr:`unhealthy` is ``None``.  A caller that
        must not act on an unmeasured window — a pager, a kill-switch
        evaluation — asks this rather than testing ``unhealthy is None``,
        so the three-valued verdict is one fact with two readable faces.
        """
        return self.total == 0


class RouterSubmissionHealthStore:
    """Reads and appends the router's own submission-health log.

    Bound to a database URL at construction; construction performs no I/O,
    so composing an application never touches the database and a store costs
    nothing until an attempt is recorded.  Each operation opens its own
    connection (creating the schema idempotently if absent), the discipline
    :class:`~router.store.RouterExchangeInfoStore` and every other store in
    this workspace follows — which is what makes the log readable from a
    *different* process than the one that wrote it, the property feature
    320's own sentence is about.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._process_id: str | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RouterSubmissionHealthStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, and composes no
        health store at all, the stance this member's exchangeInfo store and
        every other store here take.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and writes."""
        return self._database_url

    @property
    def process_id(self) -> str:
        """This process's identity — the label its rows are filed under.

        Resolved once, on first use, rather than at construction, so a store
        built during composition does not read the host or the pid before a
        caller has asked it anything; the value cannot change for the life
        of the process, so caching it is a fact about the process rather
        than about the store.
        """
        if self._process_id is None:
            self._process_id = process_identity()
        return self._process_id

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Writing ----------------------------------------------------------------

    def record(
        self,
        *,
        outcome: str,
        observed_at: datetime | None = None,
        symbol: str | None = None,
        client_order_id: str | None = None,
        process_id: str | None = None,
    ) -> SubmissionObservation:
        """Persist one submission attempt; never overwrite or amend a prior one.

        One verb, and it names the one act this feature performs: an attempt
        the order path observed lands in the log.  The caller hands the
        outcome it observed and nothing else is required — ``observed_at``
        defaults to this instant, and ``process_id`` to *this* process's
        identity.

        ``process_id`` is a keyword rather than the default spelling for a
        reason: a caller on the router's own path should not pass it at all,
        and the one caller that *does* — a replay of a recorded session, an
        operator repairing a mislabelled row — has to say so explicitly.

        Returns the value that landed, with the process identity and the
        timestamp resolved, so a caller logging the attempt holds the record
        rather than a re-derivation of it.  Fails with
        :class:`~router.errors.RouterStoreError` when the configured store
        could not take the row: an attempt that was observed and not
        recorded is exactly the gap this feature closes.

        Attempts recorded in one call in the same microsecond are ordered by
        insertion (`rowid`), so a batch of same-instant attempts has a real
        order rather than an arbitrary one; see
        :meth:`_observation_from_row`'s docstring on the ordering the reads
        rely on.
        """
        observation = SubmissionObservation(
            process_id=self.process_id if process_id is None else process_id,
            observed_at=(
                datetime.now(UTC) if observed_at is None else observed_at
            ),
            outcome=outcome,
            symbol=symbol,
            client_order_id=client_order_id,
        )
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {ORDER_SUBMISSION_HEALTH_TABLE} (
                        observed_at, process_id, outcome, symbol,
                        client_order_id
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        _isoformat_utc(observation.observed_at),
                        observation.process_id,
                        observation.outcome,
                        observation.symbol,
                        observation.client_order_id,
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not persist the order submission attempt taken by "
                f"{observation.process_id} at "
                f"{_isoformat_utc(observation.observed_at)}: {exc}"
            ) from exc
        return observation

    # -- Reading ------------------------------------------------------------

    def observations(
        self,
        *,
        since: datetime,
        until: datetime,
        process_id: str | None = None,
    ) -> tuple[SubmissionObservation, ...]:
        """Every attempt recorded in the closed window ``[since, until]``.

        Both bounds are inclusive, the workspace's window convention, and
        both must be timezone-aware.  ``process_id`` narrows the read to one
        process's attempts; left out, the window spans every process that
        submitted — which is the read that makes the log a *deployment's*
        health record rather than any one process's, and the reason it lives
        in the database at all.

        Returned oldest first, ordered by the stored timestamp so two
        processes' rows interleave in the order the attempts happened.

        **The window is a filter over the stored spelling.**  Bounds are
        compared as the strings the table holds, which is correct exactly
        because every row *this store* writes goes through
        :func:`_isoformat_utc` — one UTC offset, one format, one width.  A
        row another tool wrote in another spelling may therefore sort
        outside a window it "should" fall in, and that is the safe
        direction: such a row is simply not counted, rather than being
        counted into a verdict on a comparison the reader cannot justify.
        Rows that *are* inside the window are parsed by
        :meth:`_observation_from_row`, which refuses a spelling no parser
        accepts, so nothing survives into a verdict unparsed.
        """
        since_utc = _require_aware(since, "since")
        until_utc = _require_aware(until, "until")
        if until_utc < since_utc:
            raise RouterSubmissionHealthError(
                f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: a health window ends "
                f"before it begins ({_isoformat_utc(until_utc)} < "
                f"{_isoformat_utc(since_utc)}); an inverted window holds no "
                "submissions and would read as an unmeasured one (feature 320)"
            )
        clause = ""
        parameters: list[object] = [_isoformat_utc(since_utc), _isoformat_utc(until_utc)]
        if process_id is not None:
            clause = " AND process_id = ?"
            parameters.append(_require_text(process_id, "process_id"))
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT observed_at, process_id, outcome, symbol,
                           client_order_id
                    FROM {ORDER_SUBMISSION_HEALTH_TABLE}
                    WHERE observed_at >= ? AND observed_at <= ?{clause}
                    ORDER BY observed_at, rowid
                    """,
                    parameters,
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the order submission health window "
                f"[{_isoformat_utc(since_utc)}, {_isoformat_utc(until_utc)}]: "
                f"{exc}"
            ) from exc
        return tuple(self._observation_from_row(row) for row in rows)

    def health(
        self,
        *,
        now: datetime | None = None,
        window: timedelta = SUBMISSION_HEALTH_WINDOW,
        process_id: str | None = None,
    ) -> SubmissionHealth:
        """Judge the router's own submission health over the recent window.

        The one reading this feature exists to answer, and it is computed
        from :meth:`observations` and from nothing else — no feed state, no
        heartbeat, no clock but the one that bounds the window.  ``now``
        defaults to this instant and is a *label* (the moment the reading was
        taken), never a measurement; the attempts themselves carry their own
        timestamps, so a reading taken on an NTP-corrected clock still
        orders the attempts by when they happened.

        ``window`` is a positive :class:`~datetime.timedelta`, backward from
        ``now``; a zero or negative one is refused rather than answered as an
        empty window, because the empty window already means something here
        (:attr:`SubmissionHealth.unhealthy` is ``None``, *unmeasured*) and
        overloading it with a caller's arithmetic slip would quietly turn a
        misconfigured sweep into a silent one.

        ``process_id`` narrows the reading to one process; left out it spans
        every process that submitted, which is how a supervisor watching the
        live host reads it.  See :class:`SubmissionHealth` for what the
        returned verdict does and does not mean.
        """
        instant = _require_aware(
            datetime.now(UTC) if now is None else now, "now"
        )
        if not isinstance(window, timedelta):
            raise RouterSubmissionHealthError(
                f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: a health window must be "
                f"a timedelta, not {type(window).__name__} (feature 320)"
            )
        if window <= timedelta(0):
            raise RouterSubmissionHealthError(
                f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: a health window must be "
                f"positive, got {window}; a non-positive window holds no "
                "submissions and would read as an unmeasured one rather than "
                "as the mistake it is (feature 320)"
            )
        # Validated once, here, so the narrowing passed to the read and the
        # identity carried on the record are the same stripped string — a
        # record naming "host/7 " while the read filtered on "host/7" would
        # be a reading whose own two halves disagree.
        wanted = (
            None if process_id is None else _require_text(process_id, "process_id")
        )
        since = instant - window
        observations = self.observations(
            since=since, until=instant, process_id=wanted
        )
        return SubmissionHealth(
            process_id=wanted,
            since=since,
            until=instant,
            total=len(observations),
            rejected=sum(1 for one in observations if one.rejected),
            processes=tuple(sorted({one.process_id for one in observations})),
        )

    def latest_for_process(
        self, process_id: str | None = None
    ) -> SubmissionObservation | None:
        """The most recent attempt this process recorded, or ``None``.

        The liveness read: a supervisor that has the router's identity but
        not a window asks *"when did this process last see an order through,
        and how did it go?"* — and ``None`` is the honest answer for a
        process that has recorded nothing at all, deliberately not a default
        or a zeroed observation, since a router that has never submitted is
        a different fact from one whose last submission was rejected.
        """
        wanted = self.process_id if process_id is None else _require_text(
            process_id, "process_id"
        )
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT observed_at, process_id, outcome, symbol,
                           client_order_id
                    FROM {ORDER_SUBMISSION_HEALTH_TABLE}
                    WHERE process_id = ?
                    ORDER BY observed_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (wanted,),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the latest submission recorded by "
                f"{wanted}: {exc}"
            ) from exc
        if row is None:
            return None
        return self._observation_from_row(row)

    def _observation_from_row(
        self, row: tuple
    ) -> SubmissionObservation:
        """Rebuild one stored row, refusing a value no observation can be.

        The refusal is the point: this table is written by this store, but
        SQLite will accept anything another tool inserts, and a row carrying
        an outcome outside :data:`ORDER_SUBMISSION_OUTCOMES` would be counted
        into the verdict — the direction that understates.  The refusal names
        the process and the moment the row came from, so an operator can find
        the offending row without a second query.

        **Ordering is ``(observed_at, rowid)``, and the ``rowid`` half is
        load-bearing.**  The stored moment has microsecond resolution, and a
        router draining a rebalance submits several orders inside one — so
        ordering by the timestamp alone would order two same-instant
        attempts arbitrarily, and :meth:`latest_for_process` would answer
        *"the most recent"* with whichever of a same-instant pair SQLite
        happened to reach first.  ``rowid`` is the insertion order, which is
        the order the attempts were actually taken in, and it is available
        because this table deliberately declares no ``WITHOUT ROWID`` and no
        primary key of its own (see the schema): a submission attempt is not
        addressed individually, but it is still *ordered*, and this is where
        that order is read from.
        """
        observed_at_raw, process_id, outcome, symbol, client_order_id = row
        try:
            moment = datetime.fromisoformat(observed_at_raw)
        except ValueError as exc:
            raise RouterSubmissionHealthError(
                f"{ORDER_SUBMISSION_UNHEALTHY_CODE}: the submission row filed "
                f"under {process_id!r} carries {observed_at_raw!r}, which is "
                f"not an ISO 8601 moment this store can order attempts by "
                "(feature 320)"
            ) from exc
        try:
            return SubmissionObservation(
                process_id=process_id,
                observed_at=moment,
                outcome=outcome,
                symbol=symbol,
                client_order_id=client_order_id,
            )
        except RouterSubmissionHealthError as refusal:
            # The value layer validates the row, and this re-raise is what
            # makes the refusal *findable*: ``SubmissionObservation`` sees one
            # row and cannot know which one, while a reader holding the whole
            # window can name the process and the moment the bad outcome came
            # from — so an operator gets the row to repair rather than a
            # complaint about a value with no address.
            raise RouterSubmissionHealthError(
                f"{refusal} — the row this came from is the submission filed "
                f"under {process_id!r} at {observed_at_raw!r} (feature 320)"
            ) from refusal
