"""Stage 2's daily-loss guard — feature 2 of the VST Stage 2 spec.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 2:
*System guards each rebalance with a daily-loss check before anything is
placed.  The first check of each UTC day records the account's equity as
that day's opening equity, in its own table in the DATABASE_URL store.
Each check computes daily_loss as opening equity minus current equity.
When daily_loss reaches 3% of the book's equity_usdt, it trips
risk.daily_loss.halt_on_daily_loss, flattens through feature 1 and returns
a daily_loss_halt refusal.  While a halt stands,
require_within_daily_loss_limit refuses every later check with
orders_halted, places nothing, and keeps refusing until
risk.daily_loss.manual_reset.  A profit or a smaller loss passes.*

**The door before any placement, and the sentence's own order.**  A
rebalance slot runs this guard first (feature 4's step 1), because every
clause after the first assumes it: the check that passes is the check that
lets a single order be thought about.  The check itself runs in the
sentence's own order — the standing halt is asked first (a halt that
stands refuses the check before the venue is asked anything, so a halted
bot places nothing and reads nothing), then the account's equity is read,
then the day's opening equity is recorded or found, then the day is
judged, and only a judged breach reaches the halt, the flatten and the
refusal, in that order.

**The opening equity is this feature's own datum, in its own table.**
The day's opening equity is a fact nobody else records: the venue answers
the account's equity *now*, and the risk member's halt is handed its
figures rather than deriving them (feature 325's own law — *"the figure is
handed over, never derived"*), so somebody must own *opening equity minus
current equity*'s first term.  That is
:data:`ROUTER_DAILY_OPENING_EQUITY_TABLE` — one row per UTC day, keyed by
the day, carrying the venue's own decimal spelling verbatim — created
idempotently on connect in the same ``DATABASE_URL`` store the
rebalance's placements and the halt itself live in, first-write-wins so
two supervisors checking a new day concurrently land one row between them
and every later check of that day measures against the first check's
figure.  The row is never rewritten: an opening equity that moved would
move the day's loss with it, and the day's loss is a measurement, not a
preference.

**The judgement, the halt and the reset are the risk member's own.**  The
breach is judged by :func:`risk.daily_loss.halt_on_daily_loss` — the
comparison is that function's own strict ``>`` (a day sitting exactly at
its limit is a day at the line, not past it, the law feature 325 pinned
and this module inherits rather than re-states), the halt it records is
that feature's standing state, and the refusal that stands on it is
lifted by nobody but :func:`risk.daily_loss.manual_reset` — no calendar,
no restart, no recovery in the day's loss figure.  The limit handed over
is the sentence's own configured figure: :data:`DAILY_LOSS_LIMIT_FRACTION`
of the book's ``equity_usdt``, exact decimal arithmetic from the book's
own spelling.  A day inside its limit — a profit, a smaller loss, or a
loss sitting exactly at the line — is not this feature's business, and
risk answers ``None`` without the store being asked for a halt.

**The flatten is feature 1's verb, reached directly.**  On a breach the
account is flattened through :func:`router.bingx_flatten.flatten_account`
— the one function in this package that closes positions, the door this
feature's own constraint names ("Flatten acts only through ``--confirm``
or through the daily-loss guard") — with the guard's ``emit`` handed
through so an operator watching a halted run watches the flatten happen.
The refusal is raised whatever the flatten answered: the halt stands in
the store before the flatten runs, so a flatten the venue refused (its
report carries the refused targets and the final read's verdict) or a
flatten that could not even read the account is stated inside the
``daily_loss_halt`` refusal rather than allowed to replace it — a caller
that only learned the flatten's fault would not learn that the order
layer had halted.

**Two code words, one vocabulary.**  A breach raises
:class:`RouterBingXDailyLossHaltError`, whose message opens with
:data:`DAILY_LOSS_HALT_CODE` and names the one repair (the manual reset).
A standing halt raises :class:`RouterBingXOrdersHaltedError` — the
*translation* of :func:`risk.daily_loss.require_within_daily_loss_limit`'s
own :class:`~risk.errors.RiskOrdersHaltedError` into this member's
vocabulary, exactly the translation :mod:`router.bingx_preflight` performs
for the kill channel's refusal, for the same reason: a caller catching
``RouterError`` must not have a standing halt pass it by, and the code
word stays the one the risk member's own refusal opens with
(:data:`ORDERS_HALTED_CODE`) so an operator greps one word across both
members' logs.  It carries the standing halt record verbatim — which day,
which line, which breach moment — without a second query.  Faults of the
*ask* (no store named, a book that states no equity, a balance row the
venue's documents cannot be read into, a client that exposes no
``balance()``) refuse in this module's own
:class:`RouterBingXRiskError`, and the risk member's store faults are
translated there too, naming the seam.

**The injected client, and no socket.**  ``client`` is feature 1's
:class:`~router.bingx_client.BingXClient` in a deployment and a recording
double in the suite; the only venue read this guard makes is the one
``balance()`` call, answered from ``live/balance.json``'s recorded row
(equity ``"9999.2781"`` — the figure the suite pins the opening equity
against).  On a breach the flatten makes its own reads through the same
client.  Nothing here opens a socket, reads a credential or consults a
wall clock the caller cannot pin; the check's moment is injectable
because the UTC day it names decides which day's opening equity the
check measures against.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bingx_flatten import FlattenReport, flatten_account
from .errors import RouterError

__all__ = [
    "BALANCE_ASSET",
    "BINGX_RISK_CODE",
    "DAILY_LOSS_HALT_CODE",
    "DAILY_LOSS_LIMIT_FRACTION",
    "DATABASE_URL_ENV",
    "EQUITY_FIELD",
    "ORDERS_HALTED_CODE",
    "ROUTER_DAILY_OPENING_EQUITY_TABLE",
    "DailyLossCheck",
    "DailyOpeningEquity",
    "RouterBingXDailyLossHaltError",
    "RouterBingXOrdersHaltedError",
    "RouterBingXRiskError",
    "RouterDailyOpeningEquityStore",
    "guard_daily_loss",
]

#: The greppable token every refusal this module raises opens with, coined
#: on the module's own name the way :mod:`router.bingx_flatten` coins
#: ``bingx_flatten`` and :mod:`router.bingx_reconcile` coins
#: ``bingx_reconcile``, so an operator greps one word and lands on the
#: guard that refused.  The two refusals the spec's sentence names carry
#: their own words (:data:`DAILY_LOSS_HALT_CODE`,
#: :data:`ORDERS_HALTED_CODE`); this one is for the faults of the *ask*
#: and the seams — no store named, a book that states no equity, a
#: balance row that cannot be read, a risk member that cannot answer.
BINGX_RISK_CODE = "bingx_risk"

#: The breach refusal's own word — the spec's sentence says the guard
#: *"returns a daily_loss_halt refusal"*, so the refusal a tripped halt
#: raises opens with exactly that token, and an operator greps it to land
#: on the halt that was judged, not on a fault of the ask.
DAILY_LOSS_HALT_CODE = "daily_loss_halt"

#: The standing-halt refusal's own word — the spec's sentence says a
#: standing halt refuses *"with orders_halted"*, which is the word the
#: risk member's own :class:`~risk.errors.RiskOrdersHaltedError` already
#: opens with (:data:`risk.errors.ORDERS_HALTED_CODE`): one word across
#: both members' logs, restated here rather than imported because the
#: cross-member import is deferred past module scope and a code word is a
#: fact of this module's vocabulary, not of the risk member's presence.
ORDERS_HALTED_CODE = "orders_halted"

#: The workspace-wide environment variable naming the relational store,
#: restated here so this module states its own contract and imports no
#: sibling's — the same spelling :mod:`router.store` and
#: :mod:`risk.daily_loss` restate for theirs.
DATABASE_URL_ENV = "DATABASE_URL"

#: The daily loss limit as a fraction of the book's ``equity_usdt`` — the
#: sentence's own configured figure: *"When daily_loss reaches 3% of the
#: book's equity_usdt"*.  An exact decimal, never a float, because the
#: limit it scales is compared against a loss built from the venue's own
#: decimal strings and the house rule is that no binary approximation
#: ever touches money; the fraction is a constant of this feature rather
#: than a term a caller configures, because the sentence configures it.
DAILY_LOSS_LIMIT_FRACTION = Decimal("0.03")

#: The settlement asset the balance row is labelled by in the endpoint's
#: array spelling — the same term :mod:`router.bingx_preflight` reads for
#: its available-balance row, restated here because the discovery of
#: *the account's row* is one law this module re-states rather than a
#: helper it reaches into another module's privates for.
BALANCE_ASSET = "USDT"

#: The venue's own field name for the account's equity inside the balance
#: row — the recorded VST answer (``live/balance.json``) spells the fact
#: ``"equity": "9999.2781"``, and the row is the object the endpoint's
#: object spelling nests under ``"balance"`` (see :func:`_equity`).
EQUITY_FIELD = "equity"

#: This feature's own table — one row per UTC day, the day's opening
#: equity as the venue spelled it when the day's first check read it.
#: Deliberately not a column on the risk member's halt table and not a
#: row of any Stage 1 table: the halt is the risk member's state (handed
#: figures, lifted by its own reset door), while the opening equity is
#: the *measurement* this guard owns — the first term of *"opening equity
#: minus current equity"* — and no other module in the workspace records
#: it.  Keyed by the day itself (``TEXT`` ISO date, the primary key):
#: there is no second row per day to number, and first-write-wins over
#: the key is the whole concurrency story — two supervisors checking a
#: new UTC day at once land one row between them, and every check after
#: them measures against whichever landed first.
ROUTER_DAILY_OPENING_EQUITY_TABLE = "router_daily_opening_equity"

#: The table's DDL, authored here beside its only writer and reader,
#: created idempotently on connect — the member-owned-table stance
#: :mod:`router.store` and :mod:`risk.daily_loss` take for theirs, and
#: deliberately not a migration: the versioned tree owns the workspace's
#: shared schema, and this table has exactly one writer and one reader,
#: both in this module.
#:
#: Every value is ``TEXT`` and the equity is the venue's own string
#: spelling, verbatim — the discipline :mod:`router.store` states for its
#: filter rows: a decimal re-rendered by a store would be a decimal the
#: venue never sent, and the day's loss is measured against the figure
#: the first check actually read.
_SCHEMA = f"""
-- Feature 2 (VST Stage 2): one row per UTC day, the day's opening equity
-- as the venue spelled it at the day's first check.  Written once,
-- never rewritten: an opening equity that moved would move the day's
-- loss with it, and the day's loss is a measurement, not a preference.
-- The day is the primary key because there is no second row per day —
-- first-write-wins over the key is the whole concurrency story.
CREATE TABLE IF NOT EXISTS {ROUTER_DAILY_OPENING_EQUITY_TABLE} (
    day            TEXT PRIMARY KEY,  -- the UTC day, one ISO date spelling
    opening_equity TEXT NOT NULL,     -- the venue's own decimal spelling
    recorded_at    TEXT NOT NULL      -- the day's first check, ISO 8601 UTC
);
"""

#: The columns the read-back unpacks, in the order :meth:`RouterDailyOpeningEquityStore`
#: names them — spelled once so the write and the read cannot drift apart
#: on a column order, the failure a positional ``SELECT *`` invites.
_COLUMNS = "day, opening_equity, recorded_at"


class RouterBingXRiskError(RouterError):
    """A daily-loss check this module cannot make.

    Raised for a fault of the *ask* or of a seam, never for a fact about
    the day: no store named (the opening equity is recorded in the
    ``DATABASE_URL`` store, so a check with nowhere to record it is a
    guard that would silently measure nothing), a store whose address
    this module cannot speak, a book that states no ``equity_usdt`` or
    states one no limit can be drawn from, a balance payload the venue's
    own documents cannot be read into, a client that exposes no
    ``balance()``, a clock that answers no moment a UTC day can be taken
    from, or the risk member's own door refusing to answer.  Every
    message opens with :data:`BINGX_RISK_CODE` and names the one repair.

    The two refusals the spec's sentence names are *not* this class's
    direct spelling: a breach raises
    :class:`RouterBingXDailyLossHaltError` and a standing halt raises
    :class:`RouterBingXOrdersHaltedError`, both children of this one, so
    a caller catching the module's vocabulary catches the guard's whole
    vocabulary while an operator grepping a log still lands on the exact
    word the refusal carried.
    """


class RouterBingXOrdersHaltedError(RouterBingXRiskError):
    """A daily-loss halt stands; the check refuses before anything else.

    The first question every check asks, and the only one it asks while
    a halt stands: :func:`risk.daily_loss.require_within_daily_loss_limit`
    raised the risk member's own
    :class:`~risk.errors.RiskOrdersHaltedError`, and this module
    re-raises it in the router's vocabulary so a caller catching
    ``RouterError`` cannot have a standing halt pass it by — exactly the
    translation :class:`router.bingx_preflight.RouterBingXOrdersKilledError`
    performs for the kill channel's refusal, for the same reason and in
    the same place: before a single venue request is made, because the
    sentence says the halted check *"places nothing"* and a check that
    had read the balance first would have asked the venue a question a
    halted bot may not ask.

    The refusal does not lift by itself and nothing in this module lifts
    it: no calendar, no clock, no recovery in the day's loss figure —
    only ``risk.daily_loss.manual_reset``, which is what *"until a
    manual reset"* means, and the message closes by naming that door
    because the operator's next question is always *"how do I re-open
    the order layer?"*.

    :attr:`halt` carries the standing
    :class:`~risk.daily_loss.DailyLossHalt` the guard read, verbatim —
    the day's loss, the limit it broke, the breach moment and the
    process that judged the day — so the caller learns which day, which
    line and which door without a second query.
    """

    def __init__(self, refusal: BaseException) -> None:
        self.halt = getattr(refusal, "halt", None)
        summary = getattr(self.halt, "summary", None)
        detail = (
            summary if isinstance(summary, str) and summary.strip() else str(refusal)
        )
        super().__init__(
            f"{ORDERS_HALTED_CODE}: {detail}; the daily-loss guard "
            "refuses while a halt stands, and it refuses before anything "
            "is placed — nothing is read, nothing is recorded and "
            "nothing is sent. The halt stands until an operator closes it "
            "through the manual reset (risk.daily_loss.manual_reset, "
            "feature 325); no other door lifts this refusal, and nothing "
            "lifts it by itself"
        )


class RouterBingXDailyLossHaltError(RouterBingXRiskError):
    """The day's loss reached the limit; the halt was tripped, the
    account flattened and the rebalance refused.

    The breach refusal the spec's sentence names: *"it trips
    risk.daily_loss.halt_on_daily_loss, flattens through feature 1 and
    returns a daily_loss_halt refusal"* — the three acts, in that order,
    and the refusal is raised only after all three, because the halt
    standing in the store and the account's flatten are facts the caller
    must learn however the refusal reaches them.  The refusal is raised
    whatever the flatten answered: a flatten the venue refused leaves
    :attr:`flatten_report` describing what still stands on the account,
    and a flatten that could not even be read leaves
    :attr:`flatten_fault` — the halt stands in either case, and a caller
    that only learned the flatten's fault would not learn that the order
    layer had halted.

    :attr:`check` carries the measurement the refusal was judged on —
    the day, the opening equity, the current equity, the loss and the
    limit — and :attr:`halt` carries the halt record risk's own door
    answered with.  The message opens with :data:`DAILY_LOSS_HALT_CODE`
    and closes with the one repair, the manual reset, because *"until a
    manual reset"* is the sentence's own clock.
    """

    def __init__(
        self,
        *,
        check: DailyLossCheck,
        halt: Any,
        flatten_report: FlattenReport | None = None,
        flatten_fault: BaseException | None = None,
    ) -> None:
        self.check = check
        self.halt = halt
        self.flatten_report = flatten_report
        self.flatten_fault = flatten_fault
        opened = (
            f"{DAILY_LOSS_HALT_CODE}: the day's loss {check.daily_loss} "
            f"USDT passed the daily loss limit {check.daily_loss_limit} "
            "— 3% of the book's equity_usdt — against an opening equity "
            f"of {check.opening_equity} on {check.day.isoformat()}; "
            "risk.daily_loss.halt_on_daily_loss has recorded the halt"
        )
        if flatten_report is not None:
            if flatten_report.succeeded:
                flatten_clause = (
                    " and the account has been flattened through router.bingx_flatten"
                )
            else:
                refused = flatten_report.refused
                flatten_clause = (
                    " and the flatten through router.bingx_flatten left "
                    f"{len(flatten_report.remaining_open_orders)} open "
                    f"order(s) and {len(flatten_report.remaining_positions)} "
                    "position(s) standing"
                    + (" — the venue refused a target" if refused else "")
                    + "; the halt stands regardless, and the account needs "
                    "an operator's eye"
                )
        else:
            flatten_clause = (
                " and the flatten through router.bingx_flatten could not "
                f"be performed: {flatten_fault}; the halt stands "
                "regardless, and the account needs an operator's eye"
            )
        super().__init__(
            f"{opened}{flatten_clause}; orders are refused until an "
            "operator closes the halt through the manual reset "
            "(risk.daily_loss.manual_reset, feature 325) — nothing is "
            "placed"
        )


# -- The values -----------------------------------------------------------------


def _require_decimal(value: Any, what: str, ground: str) -> Decimal:
    """Return ``value`` as an exact decimal, or refuse it by name.

    The two spellings this module reads are the speaker's own string and
    an exact :class:`~decimal.Decimal`; a whole ``int`` is exact and is
    read for the venue's side of the ledger only where the caller names
    it (:func:`_equity`).  A ``float`` is refused by name — a binary
    approximation of a decimal no venue ever sent, the house rule
    :func:`router.sizing._as_decimal` states for the book's terms and
    :func:`router.bingx_preflight._venue_decimal` for the venue's — and
    ``NaN`` and the two infinities are refused separately because they
    *parse* as decimals and a loss built from one could never be
    compared against a limit.
    """
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: {what} {value!r} is not a decimal the "
                f"day's loss can be measured in; {ground}"
            ) from exc
    else:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: {what} must be a decimal string or a "
            f"Decimal, got {value!r} ({type(value).__name__}); a float is "
            "a binary approximation of a decimal no venue ever sent, and "
            f"a term read approximately would measure the day approximately; {ground}"
        )
    if not number.is_finite():
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: {what} must be a finite decimal, got "
            f"{number!r}; a value that is not a number cannot measure a "
            f"day's loss, and {ground}"
        )
    return number


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it.

    The check's moment names the UTC day whose opening equity the check
    measures against, and a naive timestamp cannot say unambiguously
    *which day* it is — the same discipline
    :func:`risk.daily_loss._require_aware` holds the breach moment to,
    for the same reason: a fact that cannot be ordered cannot name a day.
    """
    if not isinstance(moment, datetime):
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__}; the check's moment names the UTC "
            "day whose opening equity the check measures against, and a "
            "value that is not a moment names no day (feature 2)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: {what} must be timezone-aware; the first "
            "check of each UTC day records that day's opening equity, and "
            "a naive moment cannot say which day it is (feature 2)"
        )
    return moment


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    One UTC offset, one format, one width policy — the spelling every
    row this store writes goes through, so a reader orders and compares
    the stored moments on the string the table holds.
    """
    return moment.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class DailyOpeningEquity:
    """One UTC day's opening equity, as the day's first check read it.

    The first term of the guard's measurement — *opening equity minus
    current equity* — and the whole content of
    :data:`ROUTER_DAILY_OPENING_EQUITY_TABLE`'s row for that day: the
    day, the equity in the venue's own spelling (an exact
    :class:`~decimal.Decimal`, never a float), the moment the first
    check recorded it, and whether *this call* wrote the row — the bit
    that tells a supervisor logging the day the act from the
    observation, the same purpose ``changed`` serves on the risk
    member's halt record.

    Validated in :meth:`__post_init__` rather than only where it is
    built, because the read path reconstructs one from every stored row:
    a row another tool wrote — an equity that is not a decimal, a
    recorded moment no parser accepts — fails to reconstruct rather than
    loading as a plausible-looking opening, so a tampered row cannot
    quietly re-baseline a day's loss.
    """

    day: date
    equity: Decimal
    recorded_at: datetime
    changed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.day, date) or isinstance(self.day, datetime):
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: an opening equity's day is a date, "
                f"got {self.day!r} ({type(self.day).__name__}); the row is "
                "one per UTC day and the day is its key, so a value that "
                "cannot be one names no day an equity could open "
                "(feature 2)"
            )
        if not isinstance(self.equity, Decimal) or not self.equity.is_finite():
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: an opening equity is a finite Decimal "
                f"— the venue's own spelling of what the account held — "
                f"got {self.equity!r} ({type(self.equity).__name__}); a "
                "day's loss is measured against the figure the first "
                "check actually read, and a value that is not one "
                "measures nothing (feature 2)"
            )
        _require_aware(self.recorded_at, "an opening equity's recorded_at")
        if not isinstance(self.changed, bool):
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: an opening equity's changed bit must "
                f"be a bool, got {self.changed!r} "
                f"({type(self.changed).__name__}); the bit tells a caller "
                "whether the act wrote the row, and a value that cannot "
                "be one tells it nothing (feature 2)"
            )


@dataclass(frozen=True)
class DailyLossCheck:
    """One daily-loss check that passed: the day's whole measurement.

    What :func:`guard_daily_loss` answers when the day is inside its
    limit — the two equities the loss was taken between, the loss
    itself, the limit it was judged against (3% of the book's
    ``equity_usdt``) and whether *this* check wrote the day's opening
    row.  A frozen value so the rebalance slot that ran the guard can
    carry the measurement into its summary line unchanged.

    ``daily_loss`` may be negative — a day the account gained is a day
    whose loss is a gain wearing the loss's name, and the guard states
    the figure rather than clamping it, because the caller logging the
    day wants the measurement, not a flattering one.  A negative loss
    never reaches the risk member's judgement: a gain cannot breach a
    positive limit, and the figure the halt door is handed must be a
    loss (feature 325's own law).
    """

    day: date
    opening_equity: Decimal
    current_equity: Decimal
    daily_loss: Decimal
    daily_loss_limit: Decimal
    recorded_opening: bool

    def __post_init__(self) -> None:
        for name in (
            "opening_equity",
            "current_equity",
            "daily_loss",
            "daily_loss_limit",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise RouterBingXRiskError(
                    f"{BINGX_RISK_CODE}: a check's {name} is a finite "
                    f"Decimal, got {value!r} "
                    f"({type(value).__name__}); the measurement is exact "
                    "decimal arithmetic from the venue's own strings, and "
                    "a term that is not one measures no day (feature 2)"
                )
        if not isinstance(self.day, date) or isinstance(self.day, datetime):
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: a check's day is a date, got "
                f"{self.day!r} ({type(self.day).__name__}); the check "
                "measures one UTC day, and a value that cannot be one "
                "measures none (feature 2)"
            )
        if not isinstance(self.recorded_opening, bool):
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: a check's recorded_opening bit must "
                f"be a bool, got {self.recorded_opening!r} "
                f"({type(self.recorded_opening).__name__}); the bit says "
                "whether this check wrote the day's opening row, and a "
                "value that cannot be one says nothing (feature 2)"
            )


# -- The opening-equity store ---------------------------------------------------


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`router.store` and :mod:`risk.daily_loss`
    each restate in their own words, for the reason each of them does: a
    store reaches into no sibling's private helper, and a module that
    states its own address handling cannot be silently moved by a change
    to another table's.  ``sqlite:///foo.db`` is relative,
    ``sqlite:////foo.db`` is absolute, and any other scheme is refused
    by name in this module's own vocabulary — an address this guard
    cannot speak has no opening-equity table in it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: the daily-loss guard's opening equity is "
            "recorded in the sqlite store the spec's single-machine "
            "allowment names (sqlite:///), and an address this module "
            "cannot speak holds no table to record the day in (feature 2)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: sqlite {DATABASE_URL_ENV} must not carry "
            f"a host, got {parsed.netloc!r} (feature 2)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: sqlite {DATABASE_URL_ENV} carries no "
            "database path: an in-memory database would die with the "
            "connection that opened it, and a day whose opening equity "
            "vanished would re-baseline the next check's loss against a "
            "figure nobody recorded (feature 2)"
        )
    return Path(path)


class RouterDailyOpeningEquityStore:
    """Opens, holds and answers the guard's own opening-equity table.

    Bound to a database URL at construction; construction performs no
    I/O, so composing a caller never touches the database and the store
    costs nothing until a day is asked about.  Each operation opens its
    own connection, creating the schema idempotently if absent — the
    discipline every store in this workspace follows, which is what
    makes an opening equity a *separate supervisor process* recorded
    readable from the process that judges the day: the database, not any
    process's memory, is the coordination point.

    Two faces, one table: the guard asks what a day opened at
    (:meth:`opening`) and records what it opened at when nothing does
    (:meth:`record`) — first-write-wins, so the row a day's *first*
    check wrote is the row every later check measures against, whichever
    of two concurrent supervisors landed it.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL; the daily-loss guard records the "
                "day's opening equity in the store it names, and an "
                "address that states nothing names no store to record in "
                "(feature 2)"
            )
        self._database_url = database_url.strip()

    @property
    def database_url(self) -> str:
        """The database URL this table's days stand in."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The filesystem path behind the URL, for a caller backing the
        store up before an operator's retune — the same door
        :class:`risk.daily_loss.RiskDailyLossHaltStore` leaves open."""
        return _sqlite_path(self._database_url)

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    def ensure_schema(self) -> None:
        """Bring the table to the shape this store reads, idempotently.

        Public so a test seeding a day can prepare the table without
        reaching for the private :meth:`_connect` — the same door
        :class:`risk.daily_loss.RiskDailyLossHaltStore` and
        :class:`router.store.RouterExchangeInfoStore` leave open, for the
        same reason.  Every statement is ``CREATE … IF NOT EXISTS``, so a
        fresh database and one this module already prepared take the same
        path.
        """
        self._connect().close()

    def opening(self, day: date) -> DailyOpeningEquity | None:
        """The day's opening equity, or ``None`` when no check opened it.

        The guard's first question about a day, answered from the table
        rather than from any process's memory — the opening a restarted
        supervisor must find exactly as its predecessor left it, because
        the day's loss is measured against it.  A row that cannot be
        reconstructed (an equity that is not a decimal, a recorded moment
        no parser accepts) is refused by name with the day it came from,
        so another tool's tamper cannot quietly re-baseline a day.
        """
        if not isinstance(day, date) or isinstance(day, datetime):
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: the day asked about is a date, got "
                f"{day!r} ({type(day).__name__}); the table holds one row "
                "per UTC day keyed by the day, and a value that cannot be "
                "one names no row (feature 2)"
            )
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT {_COLUMNS}
                    FROM {ROUTER_DAILY_OPENING_EQUITY_TABLE}
                    WHERE day = ?
                    """,
                    (day.isoformat(),),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: could not read {day.isoformat()}'s "
                f"opening equity from the store: {exc}; the day's loss is "
                "measured against the figure the first check recorded, "
                "and a day whose opening cannot be asked about cannot be "
                "judged (feature 2)"
            ) from exc
        if row is None:
            return None
        return self._from_row(row, changed=False)

    def record(
        self, day: date, *, equity: Decimal, recorded_at: datetime
    ) -> DailyOpeningEquity:
        """Record the day's opening equity — first-write-wins.

        The first check of a UTC day performs this with the equity the
        venue just answered, and every other writer of the row is a
        supervisor racing it across the midnight boundary: the insert
        lands nothing when the day already holds a row (``ON CONFLICT
        DO NOTHING`` over the day's own primary key), and the answer is
        always the row the table holds afterwards, with ``changed``
        saying whether *this* call wrote it.  The equity is never
        rewritten — an opening equity that moved would move the day's
        loss with it, and the day's loss is a measurement, not a
        preference.
        """
        if not isinstance(day, date) or isinstance(day, datetime):
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: the day recorded is a date, got "
                f"{day!r} ({type(day).__name__}); the table holds one row "
                "per UTC day keyed by the day, and a value that cannot be "
                "one keys no row (feature 2)"
            )
        if not isinstance(equity, Decimal) or not equity.is_finite():
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: the equity recorded for "
                f"{day.isoformat()} is a finite Decimal — the venue's own "
                f"spelling of what the account held — got {equity!r} "
                f"({type(equity).__name__}); the day's loss is measured "
                "against this figure, and a value that is not one "
                "measures nothing (feature 2)"
            )
        _require_aware(recorded_at, "the opening equity's recorded_at")
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {ROUTER_DAILY_OPENING_EQUITY_TABLE} (
                        {_COLUMNS}
                    ) VALUES (?, ?, ?)
                    ON CONFLICT (day) DO NOTHING
                    """,
                    (
                        day.isoformat(),
                        str(equity),
                        _isoformat_utc(recorded_at),
                    ),
                )
                changed = cursor.rowcount == 1
                row = connection.execute(
                    f"""
                    SELECT {_COLUMNS}
                    FROM {ROUTER_DAILY_OPENING_EQUITY_TABLE}
                    WHERE day = ?
                    """,
                    (day.isoformat(),),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: could not record {day.isoformat()}'s "
                f"opening equity {equity!r} in the store: {exc}; a day "
                "whose opening equity went unrecorded would measure "
                "tomorrow's loss against nothing (feature 2)"
            ) from exc
        if row is None:
            # The insert reported success and the row it names is not
            # there to be read back — the one state a committed write
            # cannot be in, and the one a guard must never shrug past.
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: {day.isoformat()}'s opening equity "
                "landed without leaving a row to read back; a day whose "
                "opening cannot be read back cannot be judged tomorrow "
                "(feature 2)"
            )
        return self._from_row(row, changed=changed)

    @staticmethod
    def _from_row(row: tuple, *, changed: bool) -> DailyOpeningEquity:
        """Rebuild one stored row, refusing a value no opening can be.

        The refusal is the point: this table is written by this store,
        but SQLite will accept anything another tool inserts, and a row
        wearing a day no parser accepts or an equity that is not a
        decimal would otherwise stand as an opening nobody recorded.  The
        refusal names the day it came from, so an operator gets the row
        to repair rather than a complaint about a value with no address.
        """
        day_raw, equity_raw, recorded_at_raw = row
        try:
            day = date.fromisoformat(day_raw)
        except (TypeError, ValueError) as exc:
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: the opening-equity row keyed "
                f"{day_raw!r} is not an ISO date a UTC day can be read "
                "from (feature 2)"
            ) from exc
        try:
            recorded_at = datetime.fromisoformat(recorded_at_raw)
        except (TypeError, ValueError) as exc:
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: the opening-equity row for "
                f"{day_raw!r} carries recorded_at {recorded_at_raw!r}, "
                "which is not an ISO 8601 moment a check can be ordered "
                "by (feature 2)"
            ) from exc
        try:
            return DailyOpeningEquity(
                day=day,
                equity=_require_decimal(
                    equity_raw,
                    f"the opening equity recorded for {day.isoformat()}",
                    "the day's loss is measured against the figure the "
                    "first check actually read (feature 2)",
                ),
                recorded_at=recorded_at,
                changed=changed,
            )
        except RouterBingXRiskError as refusal:
            raise RouterBingXRiskError(
                f"{refusal} — the row this came from is the opening "
                f"equity keyed {day_raw!r}, recorded at {recorded_at_raw!r} "
                "(feature 2)"
            ) from refusal


# -- The venue's equity and the book's ------------------------------------------


def _equity(payload: Any) -> Decimal:
    """Read the account's equity out of the venue's balance payload.

    The venue has spelled this one account read two ways across the
    endpoint's versions, and both are read rather than one guessed at —
    the same two spellings :func:`router.bingx_preflight._available_usdt`
    reads for the available row, for the same reason: the v2 document
    the client's own ``BALANCE_PATH`` pins answers ``data`` as an object
    carrying the account's one row under ``balance`` (the shape the
    recorded ``live/balance.json`` carries), while the v3 document
    answers ``data`` as an array of rows keyed by ``asset``.  Within the
    row, the equity is the ``equity`` field both versions' documents
    spell — the recorded account answers ``"9999.2781"`` — read as an
    exact decimal from the venue's own spelling.  A payload naming no
    account row, or a row naming no equity, is refused: it describes no
    account whose day could be measured, and a zero read invented for it
    would re-baseline every later day against an equity nobody held.
    """
    row: Mapping[str, Any] | None = None
    if isinstance(payload, Mapping):
        candidate = payload.get("balance")
        if isinstance(candidate, Mapping):
            row = candidate
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        labelled = [
            entry
            for entry in payload
            if isinstance(entry, Mapping) and entry.get("asset") == BALANCE_ASSET
        ]
        if labelled:
            row = labelled[0]
        elif (
            len(payload) == 1
            and isinstance(payload[0], Mapping)
            and not str(payload[0].get("asset", "")).strip()
        ):
            # The venue's one unlabelled row is the swap account's own —
            # the array spelling with the asset field left empty, the
            # answer the v3 document gives an account settled in the one
            # asset the endpoint is about.
            row = payload[0]
    if row is None:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the balance payload carries the "
            f"account's {BALANCE_ASSET} row — the object under 'balance' "
            f"or the array entry whose asset is {BALANCE_ASSET!r} — got "
            f"{payload!r} ({type(payload).__name__}); a document naming "
            "no account row names no equity a day could be measured "
            "against, and the guard will not read an account into it "
            "(feature 2)"
        )
    if EQUITY_FIELD not in row or row[EQUITY_FIELD] is None:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the balance row names no {EQUITY_FIELD!r} "
            f"— got {dict(row)!r}; the day's loss is the distance between "
            "two equities, and a row carrying none cannot answer the "
            "first term of one (feature 2)"
        )
    value = row[EQUITY_FIELD]
    if isinstance(value, bool):
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the balance row's {EQUITY_FIELD} must be "
            f"the venue's decimal spelling of an amount, got {value!r} "
            "(bool); a boolean names a fact about a gate, not a quantity "
            "of money the account holds (feature 2)"
        )
    if isinstance(value, int):
        # An integer JSON number is exact — no venue ever sent 0.1 as an
        # integer — so it is read directly rather than through the
        # string parser, the one allowance
        # :func:`router.bingx_preflight._venue_decimal` makes for the
        # venue's side of a money comparison.
        return Decimal(value)
    return _require_decimal(
        value,
        f"the balance row's {EQUITY_FIELD}",
        "the equity is the venue's own answer for what the account "
        "holds, and the day's loss is measured between two of its "
        "spellings (feature 2)",
    )


def _book_equity(book: Any) -> Decimal:
    """The book's ``equity_usdt``, as one positive exact decimal.

    The limit the day is judged against is 3% of this figure, so it is
    read exactly — the venue's own spelling, a string or a
    :class:`~decimal.Decimal`, a ``float`` refused by name — and it must
    be strictly positive: a book of zero or negative equity draws a
    daily loss limit of zero or less, and feature 325 refuses such a
    limit as *"a refusal somebody configured rather than a tolerance
    anybody chose"* — a halt door that would refuse the day's first
    check before any loss existed.  This module refuses the figure in
    its own vocabulary, naming the repair, because the fault is the
    guard's own term, not the risk member's.
    """
    if not isinstance(book, Mapping):
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the book is a mapping of the book "
            f"document's own fields, got {book!r} "
            f"({type(book).__name__}); the daily loss limit is 3% of the "
            "book's equity_usdt, and a value that is not the book names "
            "no equity to draw a limit from (feature 2)"
        )
    if "equity_usdt" not in book or book["equity_usdt"] is None:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the book document states no "
            "equity_usdt; the daily loss limit is 3% of that figure, and "
            "a book that states none of it draws no limit a day could be "
            "judged against (feature 2)"
        )
    equity = _require_decimal(
        book["equity_usdt"],
        "the book's equity_usdt",
        "the daily loss limit is 3% of this figure, and a limit drawn "
        "from a term that is not a decimal would be a tolerance nobody "
        "configured (feature 2)",
    )
    if equity <= 0:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the book's equity_usdt must be strictly "
            f"positive to draw a daily loss limit from, got {equity!r}; "
            "3% of a non-positive equity is a non-positive limit, and a "
            "limit of zero or less is breached by the day's first check "
            "— a refusal the book configured rather than a tolerance "
            "anybody chose (feature 2)"
        )
    return equity


def _risk_daily_loss() -> tuple[Any, Any, Any, Any]:
    """Import the risk member's daily-loss door, deferred past module
    scope.

    The same door :func:`router.bingx_preflight._kill_guard` opens for
    the kill channel and :func:`router.bingx_reconcile._forward_reconcile`
    opens for the forward member, for the same reason: the factory's
    workspace scan imports one member's ``src/`` at a time, so a
    module-scope ``import risk`` here would make the router member's
    importability depend on scan order.  Deferred, the module is
    import-safe everywhere, while a caller that genuinely cannot reach
    the risk member is told which wheel is missing rather than shown a
    bare :class:`ImportError`.

    Returns the two verbs this guard reaches the risk member through and
    the two error classes the translations below branch on: the
    standing-halt refusal and the stem every risk-side failure
    subclasses.
    """
    try:
        from risk.daily_loss import (
            halt_on_daily_loss,
            require_within_daily_loss_limit,
        )
        from risk.errors import RiskError, RiskOrdersHaltedError
    except ModuleNotFoundError as exc:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the daily-loss guard trips and asks "
            "feature 325 through the risk member "
            "(risk.daily_loss.halt_on_daily_loss and "
            "risk.daily_loss.require_within_daily_loss_limit), and that "
            "member is not importable in this environment; run `uv sync "
            "--all-packages` in the workspace root (or put "
            "packages/risk/src on sys.path) so the halt this guard trips "
            "can be recorded and asked (feature 2)"
        ) from exc
    return (
        require_within_daily_loss_limit,
        halt_on_daily_loss,
        RiskOrdersHaltedError,
        RiskError,
    )


# -- The guard -------------------------------------------------------------------


def guard_daily_loss(
    *,
    client: Any,
    book: Mapping[str, Any],
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
    emit: Callable[[str], None] = print,
) -> DailyLossCheck:
    """Feature 2's verb: guard one rebalance with a daily-loss check.

    The door a rebalance slot runs before anything is placed (feature
    4's step 1), in the spec sentence's own order:

    1. **The standing halt is asked first.**
       :func:`risk.daily_loss.require_within_daily_loss_limit` refuses
       with :class:`RouterBingXOrdersHaltedError` — code word
       ``orders_halted`` — while a halt stands: the check refuses before
       the venue is asked anything, places nothing, records nothing for
       the day, and keeps refusing until
       ``risk.daily_loss.manual_reset``.
    2. **The account's equity is read** through one ``client.balance()``
       call, from the row the venue's balance document carries, as an
       exact decimal of the venue's own spelling.
    3. **The day's opening equity is recorded or found.**  The first
       check of a UTC day records the equity it just read as that day's
       opening, in :data:`ROUTER_DAILY_OPENING_EQUITY_TABLE` in the
       ``DATABASE_URL`` store, first-write-wins; every later check of
       the day finds it and measures against it.
    4. **The day is judged** by :func:`risk.daily_loss.halt_on_daily_loss`
       with ``daily_loss`` — the opening minus the current equity — and
       ``daily_loss_limit`` — :data:`DAILY_LOSS_LIMIT_FRACTION` of the
       book's ``equity_usdt``.  A profit (a negative loss) never reaches
       the judgement: a gain cannot breach a positive limit, and the
       figure the halt door is handed must be a loss.  The comparison is
       the risk member's own strict ``>`` — a day exactly at its limit
       passes, the law feature 325 pinned and this guard inherits by
       delegating rather than re-judging.
    5. **A breach trips, flattens and refuses.**  The halt the risk
       member records stands; the account is flattened through feature
       1's :func:`~router.bingx_flatten.flatten_account` — the one door
       this guard may close positions through, with ``emit`` handed
       through so an operator watches it happen — and the check raises
       :class:`RouterBingXDailyLossHaltError`, code word
       ``daily_loss_halt``, whatever the flatten answered, because the
       halt stands in the store before the flatten runs.

    A profit or a smaller loss passes, and the check answers the day's
    whole measurement as a :class:`DailyLossCheck`.

    ``client`` is feature 1's :class:`~router.bingx_client.BingXClient`
    in a deployment and a recording double in the suite; ``book`` is the
    rebalance's own book document (the mapping ``--book`` reads); the
    store is resolved from ``database_url``, else ``DATABASE_URL``, and
    a deployment that names neither is refused by name — the opening
    equity is recorded in that store, so a check with nowhere to record
    it would be a guard that silently measured nothing.  ``now`` answers
    the check's moment (the UTC day it names decides which day's opening
    the check measures against; the default is the instant of the call),
    and ``emit`` receives the flatten's lines when a breach runs one.

    Refuses :class:`RouterBingXRiskError` for the faults this act adds;
    the venue's own refusals keep feature 1's classes and propagate
    unchanged, and the halt's own terms keep feature 325's, translated
    at this seam into the router's vocabulary so a caller catching
    ``RouterError`` cannot have a halt pass it by.
    """
    # The ask's own terms, judged first and in a fixed order — the client
    # face, the clock, the book's equity — so a caller refused on its own
    # values is refused before any store or venue is reached.
    balance = getattr(client, "balance", None)
    if not callable(balance):
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the injected client exposes no callable "
            "balance(); the daily-loss check reads the account's equity "
            "through feature 1's client, and a client that cannot ask "
            "for the balance document cannot have its day measured "
            "(feature 2)"
        )
    if now is not None and not callable(now):
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: now must be callable answering the "
            f"check's moment, got {now!r} ({type(now).__name__}); the "
            "moment names the UTC day whose opening equity the check "
            "measures against, and a value that is not a callable names "
            "no moment to take a day from (feature 2)"
        )
    clock = now if now is not None else (lambda: datetime.now(UTC))
    moment = _require_aware(clock(), "the check's moment")
    book_equity = _book_equity(book)

    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: guard_daily_loss records the UTC day's "
            f"opening equity in its own table in the store {DATABASE_URL_ENV} "
            "names, and nothing names one (DATABASE_URL is unset and no "
            "database_url was supplied); a check with nowhere to record "
            "the day's opening would measure every later day's loss "
            "against nothing — set DATABASE_URL (or hand database_url) "
            "and run again (feature 2)"
        )

    # 1 — the standing halt, asked before the venue is asked anything.
    require_open, halt_on_loss, orders_halted, risk_stem = _risk_daily_loss()
    try:
        require_open(database_url=url, env=env)
    except orders_halted as refusal:
        raise RouterBingXOrdersHaltedError(refusal) from refusal
    except risk_stem as refusal:
        # The halt's own store could not answer — not "no halt", and
        # never read as one: a store that cannot be asked whether a halt
        # stands must not read as a store that answered no, so the guard
        # refuses rather than letting the rebalance run unguarded.
        raise RouterBingXRiskError(
            f"{BINGX_RISK_CODE}: the risk member's daily loss halt could "
            f"not be read — {refusal}; a store that cannot be asked "
            "whether a halt stands must not read as one that answered "
            "no, so the rebalance is refused rather than run unguarded "
            "(feature 2)"
        ) from refusal

    # 2 — the account's equity, one read.
    current = _equity(balance())

    # 3 — the day's opening equity, recorded by the day's first check
    # and found by every later one, first-write-wins.
    day = moment.astimezone(UTC).date()
    store = RouterDailyOpeningEquityStore(url)
    opening = store.opening(day)
    if opening is None:
        opening = store.record(day, equity=current, recorded_at=moment)
        recorded_opening = opening.changed
    else:
        recorded_opening = False
    daily_loss = opening.equity - current

    # 4 — the judgement, handed to the risk member's own door.  A profit
    # never reaches it: a negative figure is a gain wearing the loss's
    # name (feature 325's own refusal), and a gain cannot breach a
    # strictly positive limit.
    daily_loss_limit = book_equity * DAILY_LOSS_LIMIT_FRACTION
    halted: Any = None
    if daily_loss > 0:
        try:
            halted = halt_on_loss(
                daily_loss=float(daily_loss),
                daily_loss_limit=float(daily_loss_limit),
                database_url=url,
                env=env,
                breached_at=moment,
            )
        except risk_stem as refusal:
            raise RouterBingXRiskError(
                f"{BINGX_RISK_CODE}: the breach could not be recorded "
                f"through risk.daily_loss.halt_on_daily_loss — "
                f"{refusal}; a halt that silently went nowhere would "
                "leave an order layer believing itself stopped while it "
                "traded, so the check refuses rather than pass the day "
                "(feature 2)"
            ) from refusal

    check = DailyLossCheck(
        day=day,
        opening_equity=opening.equity,
        current_equity=current,
        daily_loss=daily_loss,
        daily_loss_limit=daily_loss_limit,
        recorded_opening=recorded_opening,
    )

    # 5 — a breach trips, flattens through feature 1's one door, and
    # refuses — in that order, and the refusal is raised whatever the
    # flatten answered, because the halt stood in the store before the
    # flatten ran.
    if halted is not None:
        try:
            report = flatten_account(client=client, emit=emit)
        except RouterError as fault:
            raise RouterBingXDailyLossHaltError(
                check=check,
                halt=halted,
                flatten_fault=fault,
            ) from fault
        raise RouterBingXDailyLossHaltError(
            check=check, halt=halted, flatten_report=report
        )
    return check
