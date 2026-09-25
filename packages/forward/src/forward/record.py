"""Feature 332's act: POST /forward/promote opens one forward record.

app_spec.xml, "Forward-Test Tracking", feature 332: *System exposes POST
/forward/promote, which creates a forward_record carrying the promotion
timestamp.*  The spec's API summary spells the route's one line —
``POST /forward/promote — Register a promoted signal and start its forward
window`` — and docs/alpha-engine-prd.md §5 Loop 3 states why the record exists
at all: *"Every promoted signal is timestamped and its live forward IC tracked
from the promotion date forward.  After 90 days, that signal has a track record
on data that **did not exist when the hypothesis was formed**."*  Feature 332
is the *timestamped* half of that sentence; features 333-340 are the tracking.

**The route is the act, and the act is one row.**  A promotion is decided —
feature 293's stamp on the registry row — and this endpoint opens the record
that says *this signal's out-of-sample life began here*.  Everything else on
the row is either derived from that instant or deliberately absent:

* ``promoted_at`` — **read**, never derived.  It is feature 293's
  ``decided_at``, carried out of the promotion member by feature 300's
  ``promotion_window`` (see :mod:`forward.window` for the three derived
  alternatives this member refuses, and why each is worse than the read).
* ``observed_on`` — the promotion instant's own UTC date.  Not a second
  fact about the row: 0108's docstring makes the ``promoted_at`` /
  ``observed_on`` pair *the vintage*, and the first date a forward record can
  honestly name is the day its window opened.  Forcing the caller to state it
  would let a caller state a day that disagrees with the instant beside it,
  which is a vintage nobody's calendar supports.
* ``live_ic``, ``backtest_ic``, ``realized_cost_bps`` — **NULL**, and this
  is the migration's own decision rather than an omission.  0108's comment
  says it in as many words: *"The three REAL columns are nullable because a
  freshly promoted signal has no observation yet — a NOT NULL here would force
  a fabricated zero on the day of promotion, which would read as 'measured,
  and it was zero'."*  Feature 333 (:mod:`forward.observation`) fills
  ``live_ic`` over time, feature 337 reads it, feature 340 reconciles
  ``realized_cost_bps``.  A writer that
  stamped a zero here would be answering for three features that have not run.

**The signal is the key, and there is exactly one record per signal.**  §13.4
makes the promotion instant the boundary between backtest and out-of-sample,
and a signal has one such boundary.  So the store is idempotent on the node:
the second ``POST /forward/promote`` for a signal that already holds a record
is answered by the standing row, exactly as :meth:`ledger.store.
TrialLedger.debit` answers a retry by its prior sequence — the worker died
after the row landed but before the response made it back, and the worker that
takes over posts again.  A request that *disagrees* with the standing record
about the promotion is refused by name (:class:`~forward.errors.
ForwardIdentityError`), because the alternative is moving a boundary that is
fixed by construction.

**This is the route's contract as a Python seam, not an HTTP server.**  The
workspace's operations surface is its composed components — every "exposes"
feature in the spec landed as one — and this endpoint follows:
:meth:`PromoteEndpoint.post` takes a :class:`ForwardRecordRequest` (the body)
and returns a :class:`ForwardRecordResponse`, with :data:`FORWARD_PROMOTE_ROUTE`
spelling the route once so the endpoint, the spec's summary and whatever HTTP
adapter lands later cannot drift apart on the name.  The endpoint delegates
every storage decision to :meth:`ForwardRecords.open_record`, which holds the
check-and-insert inside one transaction on one connection.

**The store authors no DDL.**  :func:`forward.schema.bootstrap_schema` runs
the *owning migration's* own ``statements("sqlite")`` — ``0108``, the file the
spec's feature 108 gave ``forward_record`` to — and the parent table ``node``
is created by ``0118``, for the reason the sibling member's schema module
states at length: SQLite resolves a foreign key's parent **when a row is
written through the child table**, so a database holding ``forward_record``
but not ``node`` refuses every ``INSERT`` with ``no such table: main.node``.
The two files' statements are the whole of this member's schema involvement,
and not one line of ``CREATE TABLE`` is authored here.

**An absent store composes no endpoint, and no component either.**
:meth:`ForwardRecords.resolve` answers ``None`` when no ``DATABASE_URL`` is
set, the same degrade-don't-break stance every store in this workspace takes:
an unconfigured deployment is a discoverable state, not an exception, while
the pipeline that has just promoted a signal is, again, the caller that must
not find itself in it.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import (
    FORWARD_IDENTITY_ERROR_CODE,
    FORWARD_PROMOTION_ERROR_CODE,
    FORWARD_RECORD_ERROR_CODE,
    ForwardError,
    ForwardIdentityError,
    ForwardPromotionError,
    ForwardRecordError,
    ForwardStoreError,
)
from .schema import FORWARD_RECORD_TABLE, bootstrap_schema
from .window import read_promotion_window

__all__ = [
    "DATABASE_URL_ENV",
    "FORWARD_PROMOTE_ROUTE",
    "LIVE_IC_BOUND",
    "LIVE_IC_COLUMN",
    "NODE_ID_COLUMN",
    "OBSERVED_ON_COLUMN",
    "PROMOTED_AT_COLUMN",
    "ForwardRecord",
    "ForwardRecordRequest",
    "ForwardRecordResponse",
    "ForwardRecords",
    "PromoteEndpoint",
    "forward_record",
    "utc_now",
]

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (promotion, ledger, universe, snapshot) —
#: the same spelling, because one deployment names one database.
DATABASE_URL_ENV = "DATABASE_URL"

#: The route this endpoint serves — app_spec.xml's API summary row for the
#: Forward Test domain, spelled once: ``POST /forward/promote — Register a
#: promoted signal and start its forward window``.  Carried on the class
#: (:attr:`PromoteEndpoint.route`) so a composed deployment can state its
#: routes from the components it holds rather than from a string that lives
#: somewhere else.
FORWARD_PROMOTE_ROUTE = "/forward/promote"

#: The signal this record is about — the row's key, and the column
#: ``forward_record`` shares with every other table in the data spine.
NODE_ID_COLUMN = "node_id"

#: When the signal was promoted: feature 293's stamp, read through feature
#: 300's window rather than re-derived here.  Named for what it *is* on this
#: table — the promotion timestamp the feature's own sentence promises.
PROMOTED_AT_COLUMN = "promoted_at"

#: The day the row carries — the promotion instant's own UTC date, derived at
#: the write from the instant beside it (see the module docstring for why the
#: caller states neither).
OBSERVED_ON_COLUMN = "observed_on"

#: The live information coefficient — the column feature 333's writer
#: (:mod:`forward.observation`) fills, one observation row at a time, over the
#: life feature 332's row opens.  Named here beside the three columns the
#: opening write names because this module is the table's vocabulary — the
#: ``_READ_SQL`` and :meth:`ForwardRecord.row` spellings of the observation
#: columns already live here — so the one literal has one home, beside its
#: siblings, for whichever act binds it into a statement.
LIVE_IC_COLUMN = "live_ic"

#: The bounds a live information coefficient lives in, as the largest
#: magnitude one can reach.
#:
#: An information coefficient is a **correlation** — the evaluator's per-date
#: figures are Spearman rank correlations, prd §6.1's ``metrics.ic_mean`` is
#: their mean — so the live one this member persists is bounded in
#: ``[−1, 1]`` by construction, whatever the estimator.  The constant is that
#: fact spelled once, not a tolerance: a figure of ``2.5`` is not a large IC,
#: it is a number that has stopped being one, and its presence means the
#: caller handed something else — a z-score, a hit rate, an information ratio —
#: under the right field name.  Restated here rather than read off the
#: ``scoring`` member's own :data:`~scoring._divergence.IC_BOUND` because a
#: member never imports another; the bound is a fact about the quantity, and
#: facts outlive whichever module spells them.
LIVE_IC_BOUND: float = 1.0

#: The column list the insert names, in the order the placeholders bind.  Six
#: of the table's seven columns: ``id`` is absent because ``0108`` declares a
#: ``DEFAULT`` that mints a UUID on both dialects, and ``live_ic`` /
#: ``backtest_ic`` / ``realized_cost_bps`` are absent because feature 332
#: measures nothing — 0108's own comment makes them nullable precisely so a
#: freshly promoted signal need not fabricate a zero on the day of promotion.
_INSERT_SQL = (
    f"INSERT INTO {FORWARD_RECORD_TABLE} "
    f"({NODE_ID_COLUMN}, {PROMOTED_AT_COLUMN}, {OBSERVED_ON_COLUMN}) "
    "VALUES (?, ?, ?)"
)

#: The node's rows, column by column rather than ``SELECT *``: the order
#: :func:`_record_from_row` unpacks must be the order this names, so a future
#: migration that appends a column cannot silently shift the fields.  The
#: third REAL column is named last, so the three observed-but-nullable columns
#: travel together in the order 0108 declares them.
_READ_SQL = (
    f"SELECT id, {NODE_ID_COLUMN}, {PROMOTED_AT_COLUMN}, {OBSERVED_ON_COLUMN}, "
    "live_ic, backtest_ic, realized_cost_bps "
    f"FROM {FORWARD_RECORD_TABLE} WHERE {NODE_ID_COLUMN} = ? "
    f"ORDER BY {OBSERVED_ON_COLUMN}"
)

#: The parent probe.  It names the table it reads rather than trusting a
#: foreign key to complain, because the repair is the caller's to make and
#: SQLite's own ``IntegrityError`` names neither the column nor the value —
#: the same probe, for the same reason, that
#: :data:`promotion.pre_register._NODE_EXISTS_SQL` runs one member over.
_NODE_EXISTS_SQL = 'SELECT 1 FROM "node" WHERE id = ? LIMIT 1'


def utc_now() -> dt.datetime:
    """The current instant, timezone-aware UTC — second resolution.

    The clock this member reads in exactly two places, and neither of them
    stamps a promotion: the *parent probe* is about a node's existence, and
    :meth:`ForwardRecords.open_record` calls this only through the promotion
    seam's own default when a caller supplies no clock at all.  It is spelled
    here for the one thing it honestly does on this member's behalf —
    translate a URL's path, open a connection — and for the tests and replays
    that route their own time through the same seam the sibling members offer.

    Second resolution, microseconds dropped rather than rounded, the same
    stamp the promotion member's own clock mints and for the same reason: the
    figure orders one instant against another and nothing reads finer than a
    second out of it.  Dropping — not rounding — keeps the stamp never *after*
    the instant observed, which matters because §13 item 7's law and this
    feature's own idempotence comparison are both inequalities between
    instants.
    """
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


# -- Validation -------------------------------------------------------------------


def _validated_uuid(value: Any, field_name: str) -> str:
    """Validate an identity column, returning its canonical UUID spelling.

    Accepts a :class:`~uuid.UUID` or any text :func:`uuid.UUID` parses
    (hyphenated or not, any case), and returns the one spelling the table
    stores: hyphenated lowercase.  Restated here rather than imported, because
    a member never imports another — and because a forward record that cannot
    be joined to its node is a record no later reader can attribute to the
    signal it measures.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError) as exc:
            raise ForwardRecordError(
                f"{field_name} must be a UUID — got {value!r}: {exc}. A forward "
                f"record names the signal it measures, and "
                f"{FORWARD_RECORD_TABLE}.{NODE_ID_COLUMN} is a foreign key to "
                "the node table: an identity that is not a UUID names no signal "
                "whose out-of-sample life this row could be the boundary of "
                "(feature 332)"
            ) from exc
    raise ForwardRecordError(
        f"{field_name} must be a UUID — got {value!r} "
        f"({type(value).__name__}); a forward record names the signal it "
        "measures, and a record no node can be joined to measures nothing "
        "(feature 332)"
    )


def _validated_instant(value: Any, field_name: str) -> dt.datetime:
    """Validate a stamp, returning it aware-UTC.

    Accepts a timezone-aware :class:`~datetime.datetime` (any offset — an
    aware instant in another offset names the same instant, so it is
    normalised rather than rejected) or its ISO-8601 text, the form the table
    stores, so a row read back revalidates through this same check.  A naive
    datetime is refused rather than defaulted, and the refusal is sharper here
    than anywhere else in the workspace: this value is the boundary between
    backtest and out-of-sample, and a naive boundary is one no later
    comparison can place on a calendar — the date derived from it would depend
    on the reader's own offset, so two processes reading one row would
    disagree about which day the signal went out of sample.
    """
    instant: dt.datetime
    if isinstance(value, dt.datetime):
        instant = value
    elif isinstance(value, str):
        try:
            instant = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise ForwardRecordError(
                f"{field_name} must be an ISO-8601 datetime or a datetime — "
                f"got {value!r}: {exc}. The promotion instant is the boundary "
                "between backtest and out-of-sample, and text that does not "
                "parse is not an instant anything can be ranged against "
                "(feature 332)"
            ) from exc
    else:
        raise ForwardRecordError(
            f"{field_name} must be a timezone-aware datetime — got {value!r} "
            f"({type(value).__name__}); a forward record's whole subject is the "
            "instant its signal went out of sample, and a value that is not an "
            "instant is no boundary at all (feature 332)"
        )
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise ForwardRecordError(
            f"{field_name} must be timezone-aware — got the naive datetime "
            f"{instant.isoformat()!r}. The day this row carries is derived from "
            "this instant in UTC, so a naive stamp has no day to derive: two "
            "readers in two offsets would disagree about which day the signal "
            "went out of sample. Pass an aware UTC instant (see utc_now()) "
            "(feature 332)"
        )
    return instant.astimezone(dt.UTC)


def _validated_date(value: Any, field_name: str) -> dt.date:
    """Validate the row's day, returning it as the table spells it.

    A :class:`~datetime.date` or its ISO-8601 text, which is what the ``DATE``
    column holds.  A :class:`~datetime.datetime` is **refused by name**, and
    that refusal is the point of this validator: ``datetime`` is a subclass of
    ``date``, so an isinstance check alone would accept an instant and silently
    truncate it — and truncating an instant to a day is only honest if you know
    its offset, which is exactly the information a raw ``datetime`` in this
    position has not been checked for.  The near-miss is refused rather than
    resolved, the discipline every validator in this workspace follows.
    """
    if isinstance(value, dt.datetime):
        raise ForwardRecordError(
            f"{field_name} must be a date, not a datetime — got "
            f"{value.isoformat()!r}. The forward record's ``{OBSERVED_ON_COLUMN}`` "
            "is a calendar day, and truncating an instant to one is a choice "
            "about which offset the day is read in; pass the day itself "
            "(``datetime.date``) or its ISO-8601 text, and let the instants on "
            "this row stay instants (feature 332)"
        )
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ForwardRecordError(
                f"{field_name} must be an ISO-8601 date or a date — got "
                f"{value!r}: {exc}. A forward record's day is half of the "
                "vintage pair 0108's docstring makes the whole value of this "
                "table, and text that does not parse is not a day (feature 332)"
            ) from exc
    raise ForwardRecordError(
        f"{field_name} must be a date — got {value!r} "
        f"({type(value).__name__}); the row's day is the observed half of the "
        "vintage pair, and a value that is not a date names no day (feature 332)"
    )


def _validated_live_ic(value: Any) -> float:
    """Return ``value`` as a live information coefficient, or refuse it.

    The rule is three gates, each refused rather than resolved:

    * **A finite real.** ``bool`` is refused first, for the reason every
      numeric validator in this workspace refuses it: ``True`` is ``1``, and a
      flag where a correlation belongs would persist a perfect coefficient
      nobody measured.  Anything that is not a :class:`~numbers.Real` is
      refused with it — text, ``None``, a sequence — because a coefficient is
      one number, not a thing to be coerced.
    * **Finite.** A NaN would make feature 337's retention ratio a NaN and
      feature 334's decay curve a gap that *looks* like a measurement, and an
      infinity is not a coefficient at all; SQLite stores either happily,
      which is exactly why the gate belongs here rather than in the column.
    * **Bounded by :data:`LIVE_IC_BOUND`.** An information coefficient is a
      correlation, so it lives in ``[−1, 1]`` by construction whatever the
      estimator.  A figure outside the interval is not a large IC — it is a
      number that has stopped being one, and the likeliest thing wearing its
      name is a z-score, a hit rate or an information ratio handed over under
      this field name.  Refused rather than clamped: clamping ``2.5`` to one
      would persist the *maximum* coefficient for a figure that may be an
      honest something-else, and every later reader (feature 334's curve,
      feature 337's ratio, §C10's demotion line) would account with a number
      nobody measured.

    Returns the value narrowed to ``float`` — the type the REAL column holds —
    so a caller's ``int`` coefficient and the row's read-back of it compare
    equal, and so the retry comparison in :mod:`forward.observation` is a
    comparison of two floats rather than of a float and whatever the caller's
    library handed over.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardRecordError(
            f"{LIVE_IC_COLUMN} must be the live information coefficient as a "
            f"real number — got {value!r} ({type(value).__name__}); the "
            "coefficient is what a forward record exists to carry (prd §5's "
            "*\"its live forward IC tracked from the promotion date "
            "forward\"*), and a value that is not one number is not a "
            "measurement any later reader can account with. Pass the "
            "correlation the observation measured (feature 333)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardRecordError(
            f"{LIVE_IC_COLUMN} must be finite — got {narrowed!r}; a NaN would "
            "make feature 337's retention ratio a NaN and feature 334's decay "
            "curve a gap that reads as measured, and an infinity is not an "
            "information coefficient at all — the record's whole value is "
            "that its figures were measured, and a value that is not a "
            "measurement cannot be one of them (feature 333)"
        )
    if not -LIVE_IC_BOUND <= narrowed <= LIVE_IC_BOUND:
        raise ForwardRecordError(
            f"{LIVE_IC_COLUMN} must be an information coefficient in "
            f"[{-LIVE_IC_BOUND!r}, {LIVE_IC_BOUND!r}] — got {narrowed!r}; an "
            "information coefficient is a correlation, so it is bounded by "
            "construction whatever the estimator, and a figure outside the "
            "bound is not a large coefficient but a number that has stopped "
            "being one — the likeliest thing wearing its name is a z-score, a "
            "hit rate or an information ratio. Clamping it to the bound would "
            "persist a coefficient nobody measured, so the figure is refused "
            "instead (feature 333)"
        )
    return narrowed


def _translated(refusal: BaseException, what: str) -> ForwardStoreError:
    """Re-frame a sibling's refusal in this member's store vocabulary.

    The seam rule this workspace states at every member boundary, applied to
    the one place this module calls out of the member: the schema adapter's
    :class:`~forward.errors.ForwardError` for a checkout missing the migration
    tree, SQLite's own errors for a database that could not be opened, and the
    promotion seam's own refusals.  A caller whose single ``except
    ForwardStoreError`` guards the write it just asked for must not be
    defeated by a neighbouring module's class.
    """
    return ForwardStoreError(
        f"{FORWARD_RECORD_ERROR_CODE}: the forward record could not be served "
        f"— the {what} refused: {refusal}. This store runs the owning "
        f"migration's own statements for {FORWARD_RECORD_TABLE} (``0108``) and "
        "its parent table (``0118``) and authors none of its own, so every "
        "failure here is a fact about the database or the checkout rather than "
        "about the row — and the original refusal is chained so the database's "
        "own words survive (feature 332)"
    )


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same convention every store in this workspace restates — the
    SQLAlchemy spelling ``DATABASE_URL`` already uses, with this member's own
    refusal vocabulary, because a caller's ``except ForwardStoreError`` must
    not be defeated by a translation error raised in another member's words.
    A non-SQLite scheme and a pathless URL are refused by name; an in-memory
    database is refused because the whole point of the row is that it outlives
    the call that wrote it — §5's loop measures over 90 days, and a record
    that died with its connection would leave a signal with no boundary at all.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: unsupported {DATABASE_URL_ENV} "
            f"scheme {parsed.scheme!r}. This store speaks sqlite:/// (the "
            "spec's single-machine allowance); the Postgres schema arrives with "
            "the versioned migration tree, and pretending to speak it here "
            "would hide a misrouted URL behind a mysterious file (feature 332)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 332)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: sqlite {DATABASE_URL_ENV} carries no "
            "database path. An in-memory store would lose the record with the "
            "connection that opened it, and a forward record must outlive the "
            "call that wrote it — §5's track record is read 90 days later, by "
            "another process entirely (feature 332)"
        )
    return Path(path)


# -- The record -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForwardRecord:
    """One ``forward_record`` row, as the table holds it.

    The seven fields are the table's seven columns, in 0108's own order.  The
    three observation columns default to ``None`` — the NULLs a freshly
    promoted signal carries — so the constructor states the shape the
    promotion write produces, while a row read back from a later feature's
    write carries whatever it filled in.

    **Frozen**, because this value *is* the boundary between backtest and
    out-of-sample: a caller who could edit ``promoted_at`` in memory would move
    the one line every later reader depends on, which is precisely the edit
    0108's docstring says the table exists to prevent.  Frozen also buys
    *equality over the seven stored fields*, which is what makes two reads of
    one promotion comparable — and what makes the store's retry test
    (*"is the standing row the one this request would have written?"*) a
    comparison of values rather than of columns read by hand.

    Validated in :meth:`__post_init__` rather than only through the store, for
    the reason every sibling record states: ``dataclasses.replace`` and
    unpickling both rebuild instances past a factory's nose, and the *read*
    path needs the same check the write path does — SQLite's columns are
    dynamically typed, so a hand-edited row is reachable here, and a record
    rebuilt from one without revalidation would report a vintage nobody wrote.
    """

    #: The row's own identity, as the table minted it (``0108``'s ``DEFAULT``).
    id: Any
    #: The promoted signal this record measures.
    node_id: Any
    #: When the signal was promoted — feature 293's stamp, read through
    #: feature 300's window.  The feature's own noun.
    promoted_at: Any
    #: The day this row carries — the promotion instant's UTC date on the row
    #: feature 332 writes, and feature 333's observation date on the rows it
    #: appends later.
    observed_on: Any
    #: The live information coefficient, or ``None`` before anything has been
    #: observed.  Feature 333's column, and this feature's alone to validate:
    #: present values go through :func:`_validated_live_ic` (a finite real in
    #: ``[−1, 1]``) so a row read back carries the same check a row written
    #: did, while ``backtest_ic`` and ``realized_cost_bps`` stay unvalidated
    #: here — their features' laws are not this one's to guess.
    live_ic: Any = None
    #: The in-sample coefficient the live one is read against.  Feature 337's
    #: ratio is ``live_ic / backtest_ic``; NULL until it is read.
    backtest_ic: Any = None
    #: The realized fill cost in basis points.  Feature 340's column.
    realized_cost_bps: Any = None

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the same
        # discipline the criteria value, the registry record and every sibling
        # in this workspace follow.
        object.__setattr__(self, "id", _validated_uuid(self.id, "id"))
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, NODE_ID_COLUMN)
        )
        object.__setattr__(
            self,
            "promoted_at",
            _validated_instant(self.promoted_at, PROMOTED_AT_COLUMN),
        )
        object.__setattr__(
            self,
            "observed_on",
            _validated_date(self.observed_on, OBSERVED_ON_COLUMN),
        )
        # The one observation column validated on the record — feature 333's
        # own — and only when present: the opening row's NULL is the honest
        # state 0108's comment protects, not a value to refuse.  The other two
        # REAL columns are left exactly as held, for the reason their field
        # comments state.
        if self.live_ic is not None:
            object.__setattr__(
                self, "live_ic", _validated_live_ic(self.live_ic)
            )

    @property
    def observed(self) -> bool:
        """Whether anything has been measured on this row yet.

        ``False`` for every row feature 332 writes — the insert cannot name
        the three REAL columns — and ``True`` once feature 333 has filled the
        live coefficient in.  A *fact about the row* rather than a judgement
        over it: whether the measurement is any good is feature 337's ratio and
        feature 334's curve, and whether it landed over data the hypothesis
        never saw is the vintage pair's business, already on this record.

        The readable name for the state 0108's comment describes — *"a freshly
        promoted signal has no observation yet"* — so a caller does not have to
        spell ``live_ic is None`` to ask the question the comment answers.
        """
        return self.live_ic is not None

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline every record in
        this workspace follows: a rendered mapping names the same things the
        same way the row does.
        """
        return {
            "id": self.id,
            NODE_ID_COLUMN: self.node_id,
            PROMOTED_AT_COLUMN: self.promoted_at,
            OBSERVED_ON_COLUMN: self.observed_on,
            "live_ic": self.live_ic,
            "backtest_ic": self.backtest_ic,
            "realized_cost_bps": self.realized_cost_bps,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"{PROMOTED_AT_COLUMN}={self.promoted_at!r}, "
            f"{OBSERVED_ON_COLUMN}={self.observed_on!r})"
        )


# -- The request and the response -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForwardRecordRequest:
    """The body of one POST /forward/promote: the signal, and its horizon.

    **Two fields, and the short list is the design.**  Everything else the row
    carries is either read from the promotion or absent by construction:

    * ``node_id`` — the promoted signal.  The row's key, and the identity the
      whole category is about.
    * ``forward_days`` — the horizon the forward window runs for, in whole
      days.  Required, with **no default**, and for the reason feature 300
      states one member over: ``promotion_registry`` holds the criteria'
      *hash* and sha256 is one-way, so ``min_forward_days`` cannot be
      recovered from the row.  The horizon is the caller's figure, and the
      seam needs it to read the window at all — a default here would be this
      member inventing a horizon and then measuring the signal over it.

    There is deliberately **no ``promoted_at`` field**.  The feature's whole
    sentence is *"creates a forwar[ d_record] carrying the promotion
    timestamp"*, and a body that could state the timestamp would let a caller
    write a row whose boundary is wherever it liked — the one fabrication this
    table exists to prevent, and the reason :mod:`forward.window` reads the
    instant from the member that owns it.  The store refuses the derivation as
    firmly as it refuses the invention.

    There is likewise **no ``observed_on`` field**: the day this row carries is
    derived from the instant, so that the vintage pair 0108 calls the point of
    the table cannot disagree with itself.  Feature 333 — which appends
    *observation* rows rather than opening the record — is where an
    observation date is stated, and it states it beside the observation it
    belongs to.

    Frozen, because a request is a fact the caller stated; editing one in
    flight would be opening a record for a different horizon than was
    validated.
    """

    #: The promoted signal, canonical UUID spelling.
    node_id: str
    #: How long the forward window runs, in whole days — the promotion's
    #: pre-registered ``min_forward_days``.  Required: a window with no stated
    #: length has no end, and §5's *"after 90 days"* is the length.
    forward_days: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, NODE_ID_COLUMN)
        )
        object.__setattr__(
            self, "forward_days", _validated_forward_days(self.forward_days)
        )


def _validated_forward_days(value: Any) -> int:
    """Return ``value`` as the window's length in days, or refuse what is not one.

    A **positive** count of whole days, restated here rather than imported:
    a member never imports another, and the rule's own boundary is the
    interesting half.  Zero is not a *bad* window, it is **not a window** —
    ``closes_at`` would equal ``opened_at``, the half-open interval would be
    empty, and a forward record opened against it could never hold a single
    observation (§5's whole loop is a measurement over a span).  Negative
    lengths are refused by the same check.

    ``bool`` is refused first, for the reason every count validator in this
    workspace refuses it: ``True`` is ``1`` in Python, and a flag where a
    horizon belongs would silently open a one-day window — the shortest a
    window can be, and a length nobody stated.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardRecordError(
            f"forward_days must be a positive integer number of days — got "
            f"{value!r} ({type(value).__name__}); the forward window is the span "
            "a promoted signal is measured over on data that did not exist when "
            "the hypothesis was formed, and a horizon that is a flag or a "
            "fraction names no span a record could be opened against. Read it "
            "from the promotion's pre-registered ``min_forward_days`` (feature "
            "291's criteria) (feature 332)"
        )
    if value <= 0:
        raise ForwardRecordError(
            f"forward_days must be positive — got {value!r}; a window of zero "
            "days opens and closes at the same instant, so it holds no "
            "observation and is not a measurement window at all. The horizon is "
            "the promotion's pre-registered ``min_forward_days`` (feature 291's "
            "criteria): read it from the criteria the promotion was registered "
            "under, and do not invent one the registration does not carry "
            "(feature 332)"
        )
    return value


@dataclass(frozen=True, slots=True)
class ForwardRecordResponse:
    """The answer to one POST /forward/promote: the record, and whose it is.

    ``created`` is whether *this* call opened the row; a retry is a call where
    it is ``False`` — the signal already held a forward record for this
    promotion, and this POST changed nothing.  ``record`` is the signal's row
    in full: freshly written on the first POST, the standing one on every
    retry, exactly as :class:`~ledger.debit.DebitResponse` carries the prior
    row one member over.

    ``promoted_at`` (a property, so it cannot drift from the record) is the
    figure the feature's own sentence promises — *"creates a forward_record
    carrying the promotion timestamp"* — and it is the *row's* stamp rather
    than anything this endpoint computed, so a caller that posts twice finds
    the same instant both times however long apart the two calls ran.

    Frozen, because the response is the endpoint's testimony about the
    record's state at one moment; two responses that differ in ``promoted_at``
    for one request would be the endpoint revising when a signal went out of
    sample, which is the one revision this table exists to make impossible.
    """

    #: Whether this call opened the row — ``False`` on a retry.
    created: bool
    #: The signal's row: freshly opened, or the standing one a retry is
    #: answered by.
    record: ForwardRecord

    @property
    def promoted_at(self) -> dt.datetime:
        """When the signal was promoted — feature 293's stamp, read."""
        return self.record.promoted_at

    @property
    def observed_on(self) -> dt.date:
        """The day the record carries — the promotion instant's UTC date."""
        return self.record.observed_on

    @property
    def node_id(self) -> str:
        """The signal this record belongs to."""
        return self.record.node_id

    @property
    def retry(self) -> bool:
        """Whether this POST was a retry — answered by a row already held.

        The readable spelling of ``not created``, named for the clause it
        asserts, exactly as :attr:`~ledger.debit.DebitResponse.retry` and
        :attr:`~promotion.pre_register.PreRegistrationResponse.retry` are.
        """
        return not self.created


# -- The store --------------------------------------------------------------------


class ForwardRecords:
    """Opens one forward record per promoted signal — feature 332's act.

    Constructed with the database URL the records live in;
    :meth:`open_record` reads the promotion instant through feature 300's
    window and writes the row that carries it.  The class resolves its path
    lazily, so constructing one performs no I/O: composition-time work must not
    touch the disk, the contract every store in this workspace states.

    **Duck-checked at the seam, never isinstance-guarded.**  The store reaches
    the promotion member through :func:`forward.window.read_promotion_window`,
    which resolves the verb at call time; the endpoint's constructor checks for
    a callable ``open_record`` rather than a class, for the reason every
    endpoint in this workspace states: the factory's scan imports a member
    under a synthetic module name, so the composed store is structurally a
    ``ForwardRecords`` but never the same class object a direct import yields.

    **There is no cache.**  A memo of opened signals would make *when did this
    signal go out of sample?* a question about this process's history — and the
    readers that ask it (feature 334's decay endpoint, feature 337's retention
    ratio, an operator a quarter later) all run somewhere else entirely.  The
    row is the only record, so it is the only thing an answer is drawn from, on
    every call, in every process.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the forward records live in.

        The URL is validated here, before any call, because it is a fact about
        the *store* rather than about any one record: a URL that is not a
        non-empty string names no table, and a store that accepted one would
        fail identically on every promotion — the wrong place for a deployment
        to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. A forward record is a row in the "
                "database the deployment names, and a store pointed at nothing "
                "has nowhere to write the boundary between backtest and "
                "out-of-sample (feature 332)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> ForwardRecords | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the way every store
        in this workspace treats its configuration.  Absent is not an error: it
        is a deployment without a relational store, which composes no
        ``forward`` component — a discoverable state, not an exception — while
        the pipeline that has just promoted a signal is the caller that must
        not find itself in it.  A promotion whose record never opened is a
        signal whose out-of-sample life began unrecorded, and no later reader
        can recover the instant it should have carried.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store records into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name, in *this* member's
        vocabulary) the first time an operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the records' database, bringing the two tables it names up.

        One statement of intent.  :func:`forward.schema.bootstrap_schema` runs
        the *owning migrations'* own ``statements("sqlite")`` — ``0118`` for
        ``node`` and ``0108`` for ``forward_record`` — so this store authors no
        DDL, spells no column and cannot drift from the schema's owner.  Every
        statement is ``CREATE TABLE IF NOT EXISTS``, so a fresh database, a
        fully migrated one and one a store in this member created earlier all
        take the same path.  The order is the chain's, not SQLite's demand —
        SQLite defers a foreign key's parent *table* to the first row written,
        so a records-only database is declared happily and then refuses every
        ``INSERT`` with ``no such table: main.node``.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, so a store that skipped this would insert a record
        naming a node that does not exist and discover it never.  The parent
        *row* is checked by name before the insert regardless (see
        :meth:`open_record`); the pragma is what makes the check a redundancy
        rather than the only guard, and it is what makes the constraint hold
        against a hand that reaches past this store with a raw connection.

        The caller owns the connection; use it as a context manager to commit,
        which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_schema(connection)
        except ForwardError:
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise _translated(exc, "database") from exc
        return connection

    # -- Feature 332: the record --------------------------------------------

    def open_record(
        self,
        node_id: Any,
        *,
        forward_days: Any,
        database_url: str | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> tuple[ForwardRecord, bool]:
        """Open one signal's forward record — feature 332's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity and the horizon as a
           positive count of days, *before* anything is read or opened, so a
           malformed body is refused without touching a database and a refused
           call leaves no row and no file behind.
        2. **Read the promotion instant** through feature 300's window, which
           is the promotion member's own read of feature 293's stamp.  Every
           refusal it raises arrives as
           :class:`~forward.errors.ForwardPromotionError`: the node was never
           pre-registered, its deciding evaluation has not run, or its row
           could not be read as a decision.  All three mean the same thing
           here — *there is no instant* — and none of them can be repaired by
           this member.
        3. **Derive the row's day** from that instant, in UTC.  The vintage
           pair is then internally consistent by construction: nobody stated
           the day, so nobody could state one that disagrees with the instant.
        4. **Answer the retry, or refuse the disagreement, or write.**  A
           standing record for this signal is the same promotion arriving
           twice when it carries *this* instant — returned untouched, with
           ``created=False``.  A standing record carrying a *different*
           instant is refused (:class:`~forward.errors.ForwardIdentityError`),
           because §13.4 makes the boundary fixed.  An absent record takes the
           insert.
        5. **Read back and answer with the row**, inside the same transaction
           as the write, so the minted ``id`` and the stamps in the answer are
           the table's own.

        ``forward_days`` is required and is used for exactly one thing: asking
        feature 300 for the window.  It is not stored — ``forward_record`` has
        no horizon column, and this member authors no DDL to add one — so the
        row carries the *instant* the feature's sentence promises and the
        window's length stays where feature 300 keeps it: on the caller's
        value, beside the criteria hash the row was read under.

        ``database_url`` and ``env`` are passed through to the seam, so a
        caller holding an explicit URL reads the promotion from *that*
        database rather than from whatever ``DATABASE_URL`` happens to say.
        ``clock`` is accepted for parity with the sibling stores' seam and for
        the replay path; it is **not** a way to stamp a promotion.  The
        instant written is always the one read.

        Refuses, in this order, each naming what it is about: a malformed
        identity or horizon (:class:`~forward.errors.ForwardRecordError`, the
        ask face); a promotion with no instant
        (:class:`~forward.errors.ForwardPromotionError`, the promotion's
        repair); and a store this member cannot speak, an absent node row, a
        record that already exists carrying a different promotion, or a row
        that could not be read back
        (:class:`~forward.errors.ForwardStoreError` and
        :class:`~forward.errors.ForwardIdentityError`).
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        horizon = _validated_forward_days(forward_days)
        window = read_promotion_window(
            node,
            forward_days=horizon,
            database_url=self._promotion_database(database_url),
            env=env,
        )
        promoted_at = _validated_instant(
            _attribute_of(window, "opened_at", node), PROMOTED_AT_COLUMN
        )
        observed_on = promoted_at.date()
        with closing(self._connect()) as connection, connection:
            standing = self._node_records(connection, node)
            if standing:
                return self._answer_standing(standing[0], node, promoted_at), False
            self._require_node(connection, node)
            try:
                connection.execute(
                    _INSERT_SQL,
                    (node, promoted_at.isoformat(), observed_on.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ForwardStoreError(
                    f"{FORWARD_RECORD_ERROR_CODE}: the forward record for node "
                    f"{node} could not be written: {exc}. The row names one node "
                    "by foreign key and this store checked it before writing — "
                    "so a constraint that refused anyway is a database whose "
                    "tables are not the ones this deployment migrated (feature "
                    "332)"
                ) from exc
            written = self._node_records(connection, node)
        if not written:
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: the forward record for node "
                f"{node} could not be read back after the write. A record has "
                "to be accounted for — §5's forward loop measures the signal "
                "from this instant forward, and every later reader (feature "
                "334's curve, feature 337's ratio) starts from this row — and a "
                "row that cannot be re-read is a record this store cannot "
                "vouch for (feature 332)"
            )
        return written[0], True

    # -- The words ----------------------------------------------------------

    def _promotion_database(self, database_url: str | None) -> str:
        """Where the promotion instant is read from — this store's own database.

        An explicit ``database_url`` wins, and otherwise the store reads the
        promotion out of **the database it writes records into**.  That default
        is the whole of the two members' agreement in a real deployment: the
        registry row feature 293 stamped and the forward record feature 332
        opens are rows in one database, named once by ``DATABASE_URL``, so a
        store constructed with a URL and asked to act is asking *this*
        deployment's promotion member — not whichever database the ambient
        environment happens to name.

        The alternative — passing ``None`` through and letting feature 300
        resolve ``DATABASE_URL`` itself — reads correctly only when the two
        happen to agree, and fails in exactly the case that matters: a caller
        that built a store over an explicit URL (the backfill, the replay, the
        suite) would have its *writes* land in one database while its *reads*
        went to another, and the refusal would be a promotion-unstamped error
        about a signal that is in fact promoted.
        """
        return self._database_url if database_url is None else database_url

    def _node_records(
        self, connection: sqlite3.Connection, node: str
    ) -> list[ForwardRecord]:
        """Every forward record this node holds, oldest day first.

        Feature 332 opens at most one of these; features 333-340 append
        observation rows, so more than one is the *expected* shape of a
        measured signal rather than a corruption.  The **ordering** is what
        makes the list useful before those features land: ``ORDER BY
        observed_on`` puts the promotion-day row first, so a caller reading the
        list sees the record's opening vintage at ``[0]`` without knowing how
        many observations have accumulated behind it.

        Note what is *not* asserted here: that there is exactly one row.  A
        uniqueness law spelled in this reader would be this feature legislating
        the shape of rows three sibling features have yet to write — the
        judgement belongs to the store's write path (see
        :meth:`_answer_standing`), which is where this member's one-signal law
        is enforced, and to nothing else.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [_record_from_row(row, node) for row in rows]

    def _answer_standing(
        self, standing: ForwardRecord, node: str, promoted_at: dt.datetime
    ) -> ForwardRecord:
        """Resolve a signal that already holds a record: the retry, or the refusal.

        The two outcomes are the same row read two ways and the difference is
        the instant.  The *same* promotion arriving twice is a retry — the
        worker died after the row landed but before the response made it back,
        and the worker that takes over posts again — which is not an error and
        must not move anything: the standing row is returned exactly as it is,
        ``id`` and stamps included, because the boundary did not move and so
        nothing about it did either.

        A *different* instant is two claims about one signal's vintage, and the
        store refuses to choose between them.  Both silent resolutions are
        wrong: last-wins would move the boundary between backtest and
        out-of-sample, which §13.4 fixes at promotion; first-wins would leave
        the caller holding a response whose ``promoted_at`` contradicts the
        promotion it just decided, which is worse than a refusal because it
        looks like success.

        The comparison is over the *instant* and not over the whole row, and
        that is deliberate: features 333-340 fill the three observation columns
        after this write, so a caller re-posting the same promotion long after
        its record has been annotated must not be refused for disagreeing about
        columns this act never writes.
        """
        if standing.promoted_at == promoted_at:
            return standing
        raise ForwardIdentityError(
            f"{FORWARD_IDENTITY_ERROR_CODE}: node {node} already holds a forward "
            f"record promoted at {standing.promoted_at.isoformat()} "
            f"(day {standing.observed_on.isoformat()}), and this request would "
            f"open one at {promoted_at.isoformat()}. A signal has exactly one "
            "boundary between backtest and out-of-sample: §13.4 makes the "
            "promotion instant that boundary, and 0108's own docstring says a "
            "row that lost its promotion timestamp would be *an observation "
            "with no vintage* — so a second record would leave every later "
            "reader of this signal (feature 334's decay curve, feature 337's "
            "retention ratio) with two instants and no way to choose between "
            "them. Nothing is wrong with the body or the store: the repair is "
            "to stop asking, and to reconcile the two promotions that disagree "
            "about this signal's instant (feature 332)"
        )

    def _require_node(self, connection: sqlite3.Connection, node: str) -> None:
        """Refuse a record whose signal the tree does not hold, naming it.

        ``node`` is the row's one foreign key, and the repair is the caller's:
        the identity is wrong, or the discovery loop has not written the node
        yet.  SQLite's own ``IntegrityError`` names neither the column nor the
        value, so this probe does, and the refusal is the *store's* class
        rather than the ask's — the body is well-formed and the database is not
        in the state the write needs.

        The node's existence is a genuinely separate fact from the promotion's,
        and it is checked separately for that reason: feature 300's read
        already refuses a node nobody *pre-registered*, but a pre-registration
        can outlive its node only by a hand on the table, and the foreign key
        is the one thing that makes the row joinable to the tree the whole
        category measures against.
        """
        cursor = connection.execute(_NODE_EXISTS_SQL, (node,))
        try:
            present = cursor.fetchone() is not None
        finally:
            cursor.close()
        if not present:
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: node holds no row for "
                f"{NODE_ID_COLUMN} {node!r}, so this forward record has no "
                "signal to be the boundary of. "
                f"{FORWARD_RECORD_TABLE}.{NODE_ID_COLUMN} is a foreign key: a "
                "record must be joinable to the hypothesis it measures, and a "
                "record naming a row the database does not hold is a record no "
                "later reader can attribute to anything (feature 332)"
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _attribute_of(window: Any, name: str, node: str) -> Any:
    """Read one attribute off the window feature 300 answered with, or refuse.

    The seam asks for the *one* attribute this feature needs — ``opened_at``,
    the promotion instant — rather than unpacking or re-shaping the sibling
    member's value, which is the discipline :func:`regime.origins._world_id_of`
    states for the same kind of reach: *ask the surface the act needs*.

    A window without the attribute is refused in this member's promotion
    vocabulary, because that is what is missing from where this member stands:
    without the instant there is nothing honest to stamp the row with, and the
    alternative — falling back to the clock — is the fabrication the whole
    feature exists to prevent.
    """
    value = getattr(window, name, None)
    if value is None:
        raise ForwardPromotionError(
            f"{FORWARD_PROMOTION_ERROR_CODE}: node {node!r} has a promotion "
            f"window, but it carries no {name!r} — got "
            f"{type(window).__name__}. The forward record's whole subject is the "
            "instant the signal went out of sample, which feature 293 stamps and "
            "feature 300 reads back as ``opened_at``; a window without it leaves "
            "this member nothing honest to write, and stamping the row with the "
            "clock at hand would place the boundary wherever this call happened "
            "to run (feature 332)"
        )
    return value


def _record_from_row(row: tuple[Any, ...], node: str) -> ForwardRecord:
    """Build a :class:`ForwardRecord` from a row, with the node named.

    The read path's one constructor, so every read-back in the store builds the
    value the same way.  A validation refusal raised from the row names the
    node it came off — the difference between an operator learning *this
    record is corrupt* and learning only that some row somewhere is not a
    record.  A store refusal is re-framed in the same class with the node in
    front of it, for the same reason.
    """
    try:
        return ForwardRecord(
            id=row[0],
            node_id=row[1],
            promoted_at=row[2],
            observed_on=row[3],
            live_ic=row[4],
            backtest_ic=row[5],
            realized_cost_bps=row[6],
        )
    except ForwardRecordError as exc:
        raise ForwardRecordError(
            f"the {FORWARD_RECORD_TABLE} row for node {node} could not be read "
            f"as a forward record: {exc}"
        ) from exc


# -- The endpoint -----------------------------------------------------------------


class PromoteEndpoint:
    """Serves POST /forward/promote over one :class:`ForwardRecords`.

    Constructed with the store it writes into; :meth:`post` is the route.  The
    endpoint holds no state of its own — no memo of promoted signals, no cache
    of instants — because a record remembered in the endpoint would be one a
    second process, a restart or a recycled worker silently loses sight of, and
    the promotion that decided the signal ran in another process entirely.  The
    row in the table is the only record of where the boundary fell, so it is
    the only thing the answer is drawn from, on every request, in every
    process.
    """

    #: The route this endpoint serves — :data:`FORWARD_PROMOTE_ROUTE`, pinned
    #: as a class attribute so ``PromoteEndpoint.route`` states the contract
    #: without an instance.
    route = FORWARD_PROMOTE_ROUTE

    def __init__(self, records: ForwardRecords) -> None:
        # Duck-checked rather than isinstance-guarded: the factory's scan
        # imports this member under an alias module, so the *composed* store is
        # structurally a ForwardRecords but never the same class object a
        # direct import yields — an isinstance here would refuse the very
        # component the factory hands out.  The contract is the open_record
        # seam, and that is what is checked.
        if not callable(getattr(records, "open_record", None)):
            raise TypeError(
                "PromoteEndpoint speaks a ForwardRecords (something with an "
                f"open_record(node_id, forward_days=...) seam); got "
                f"{type(records).__name__}"
            )
        self._records = records

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> PromoteEndpoint | None:
        """The endpoint over the store ``DATABASE_URL`` names, or ``None``.

        Resolves the store exactly as the member's own builder does
        (:meth:`ForwardRecords.resolve`), so the endpoint and the composed
        ``forward`` component always point at the same database.  No
        ``DATABASE_URL`` composes no endpoint — an unconfigured store is a
        discoverable state, not an error — while the pipeline that has just
        promoted a signal is, again, the one that must not find itself in it.
        """
        records = ForwardRecords.resolve(env)
        return None if records is None else cls(records)

    @property
    def records(self) -> ForwardRecords:
        """The store this endpoint opens records in."""
        return self._records

    # -- The route ----------------------------------------------------------

    def post(
        self,
        request: ForwardRecordRequest,
        *,
        database_url: str | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> ForwardRecordResponse:
        """Answer one POST /forward/promote: open the record, or return the standing one.

        The whole of feature 332 at its seam.  The signal's promotion instant
        is read from the promotion member's own registry row — feature 293's
        stamp, through feature 300's window — and the row is written carrying
        it, with the three observation columns left NULL because nothing has
        been observed on the day of promotion.

        A signal that already holds a record for *this* promotion is a retry:
        nothing is written, and the response carries the standing row and
        ``created=False``, so the caller sees the instant the boundary actually
        fell at rather than the instant its retry happened to fire.  A signal
        whose standing record carries a *different* instant is refused — see
        :meth:`ForwardRecords._answer_standing`, where the argument is.

        ``database_url`` and ``env`` reach the store's own resolution and the
        promotion seam behind it, so an endpoint built over one database reads
        the promotion from that same one unless a caller overrides it
        deliberately.

        Refusals are the request's own (a malformed body never reaches the
        store), the promotion's (a signal with no instant to open at), and the
        store's (an absent node row, a record already open at another instant,
        a store that cannot be reached or brought to the revision the row
        needs).
        """
        record, created = self._records.open_record(
            request.node_id,
            forward_days=request.forward_days,
            database_url=database_url,
            env=env,
            clock=clock,
        )
        return ForwardRecordResponse(created=created, record=record)


# -- The module-level spelling ----------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardRecords:
    """The store the module-level spelling writes through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that names
    neither is refused *by name* rather than silently answering nothing.  The
    silence would be the dangerous failure here and not the refusal: a
    deployment that could not say where forward records live would leave the
    promotion that just ran with no boundary written at all, and §5's 90-day
    track record would begin — unrecorded — the moment nobody was looking.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), so "
            "the forward record cannot be opened. A promoted signal's boundary "
            "between backtest and out-of-sample is a row, and a store resolved "
            "from nothing is a refusal rather than a silent answer of the "
            "caller's own choosing (feature 332)"
        )
    return ForwardRecords(url)


def forward_record(
    node_id: Any,
    *,
    forward_days: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> ForwardRecord:
    """Open one signal's forward record — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the record
    without holding a store — the pipeline step that runs the moment a
    promotion is decided, an operator backfilling a signal whose record never
    opened, a test.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`promotion.forward.promotion_window`
    resolves the window it reads, so a caller reading through one spelling and
    the other is reading and writing the same database.

    The answer is the **row the table holds** rather than a ``(record,
    created)`` pair, which is the one way this spelling differs from
    :meth:`ForwardRecords.open_record`: an act asked for as one call has
    nobody to tell about a retry, and the record it returns is the same value
    either way.  A caller that needs to know whether *this* call opened the
    row asks the store, or reads :attr:`ForwardRecordResponse.created` off the
    endpoint's answer.
    """
    return _resolved_store(database_url, env).open_record(
        node_id,
        forward_days=forward_days,
        database_url=database_url,
        env=env,
        clock=clock,
    )[0]
