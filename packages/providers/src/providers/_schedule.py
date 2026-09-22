"""Scheduling depth campaigns outside the peak pricing window — feature 202.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 202: *System
schedules depth campaigns outside a configured peak pricing window,
persisting the chosen window with each run.*  docs/nullius-tech-
architecture.md §14.2 states the lever this module implements, as the
second of its *"two free levers worth ~50%"*:

    2. **DeepSeek prices by time of day** — peak is 01:00–04:00 and
       06:00–10:00 UTC, off-peak is 50% lower. Schedule campaigns outside
       those windows.

The depth role is *"pure asynchronous batch work.  Nothing waits on it"*
— §14.2's own words for why the lever is free — so the campaign launcher
can wait out the peak hours, and this module is the decision it waits on:
given the rate card's peak windows, the moment of scheduling and the
declared run length, **choose the earliest window that touches no peak
minute**, and persist that window with the run.

Why the windows are configured, not constant
--------------------------------------------

No peak window is spelled in this module's code, and that is deliberate.
§14.2's own preamble is *"Verified 2026-09-19.  Rates move monthly and
several below are explicitly promotional.  Re-verify before budgeting;
the **selection logic** is stable, the numbers are not."* — and the peak
hours are numbers, not logic.  Its volatility list even carries the
relevant event: *"DeepSeek moved to peak/off-peak billing on 2026-08-17."*
A peak window baked into code would therefore be wrong on a schedule the
document already publishes, which is the same reason feature 198's record
carries no price at all: a field the decision reads is a field the
deployment states, and §14.2's 01:00–04:00 / 06:00–10:00 pair is the
*spelling of an example*, not a law.  The tests use that pair as their
data for the same reason :data:`packages.providers.tests.conftest.DEFAULT_AUTHOR`
uses §14.1's ids — so a fixture reads like the deployment it stands in for
— while the module holds only the arithmetic.

The one sentence, three records and one gate
--------------------------------------------

The feature's sentence decomposes into a configuration, a choice and a
persistence, and the module's public surface is exactly those three:

* :class:`PeakWindow` — **the configuration's unit**: one peak pricing
  window as a daily UTC time-of-day interval ``[start, end)``, whole
  minutes, where ``start`` past ``end`` is the card whose peak crosses
  midnight (a 22:00–02:00 peak is spelled exactly that way).  Shape-
  validated on construction: the two ends are :class:`datetime.time`
  values, naive (a time of day is already UTC by definition here —
  §14.2's windows are stated in UTC), minute-granular (a rate card states
  pricing windows to the minute; seconds are config noise this module
  would otherwise silently truncate), and not coincident (a zero-length
  window is a window that contains no time — refusing it as data nonsense
  rather than reading it as "flat" is the same move
  :func:`providers._depth._require_token_count` makes for a threshold of
  zero: hiding a malformation inside a decision it does not belong to).

* :class:`PeakPricing` — **the configuration**: the frozen tuple of the
  card's peak windows, and the answer to why the feature's sentence says
  *"a configured peak pricing window"* in the singular while §14.2's own
  card carries two — the sentence names the category (as feature 212's
  *"legal set"* names a set), and the record holds however many windows
  the card states.  Empty is legal and means *flat by time of day* — a
  provider with no peak/off-peak split, on which every window is
  off-peak — the same positive fact :func:`providers.flat_pricing` names
  for a card with no surcharge threshold, and the reason an empty
  configuration schedules immediately rather than refusing: a card that
  never enters peak has no window for a run to avoid.

* :func:`choose_run_window` — **the choice**: the earliest minute-aligned
  window ``[start, end)`` with ``start`` no earlier than the scheduling
  instant, the declared length, and not one minute of it inside any peak
  window — §14.2's *"schedule campaigns outside those windows"* as an
  arithmetic.  Refused, as
  :class:`~providers.NoOffPeakWindowError`, when the declared length
  exceeds the largest off-peak gap the card leaves, naming the gap: the
  one number the caller's duration has to come under.

* :class:`RunWindow` — **the choice's answer**: the chosen window as two
  aware UTC instants, frozen and value-equal, ``end_at`` exactly
  ``start_at`` plus the declared length.  The bounds are minute-aligned
  because the pricing they avoid is minute-granular and the candidates
  the arithmetic examines are minute instants.

* :class:`DepthRunWindows` — **the persistence**: the store that schedules
  one campaign's runs and answers the record the table holds, and the
  module's registered component (see
  :data:`providers.DEPTH_RUN_WINDOW_COMPONENT`).  Its
  :meth:`~providers.DepthRunWindows.schedule` is the feature's sentence
  as one call — choose the window, prove the campaign was planned, insert
  the row, read it back — because a window chosen and not persisted is
  the sentence with its second half missing.

The persistence is a member-owned table
---------------------------------------

The row lands in ``depth_run_window``, a table **this member owns and
creates lazily** (``CREATE TABLE IF NOT EXISTS`` on first use) — the
contract :mod:`bootstrap._pool` states for its own ``bootstrap_world``
table, not the one :mod:`providers._pin_store` follows for ``node``.
The difference is which feature owns the schema: the pin store writes
one column of a row two core migrations declare, so the migration is the
authority and the store refuses to invent the table; this feature's row
is *this feature's own record* — no migration declares it, exactly as no
migration declared the bootstrap pool's worlds — and a member that
refused to create its own table would be refusing its own feature.  The
shared-migration chain is still not edited: the table's shape is a fact
about this feature and its history, not about the database's, which is
the stated ground the bootstrap member widens its table on.

Two tables beside it are **probed, never created**.  ``campaign`` is
feature 104's (``migrations/versions/0111_campaign_table.py``), planned
rows written by feature 232's :class:`~discovery.CampaignRecords`; this
store reads it for exactly one question — *was this campaign ever
planned?* — through a read-only ``sqlite_master`` lookup, the idiom
:mod:`discovery.campaign` uses for ``node`` and :mod:`bootstrap._census`
uses for its own absent-table refusal.  An id the table does not hold is
refused as :class:`~providers.UnknownCampaignError`, and a database with
no ``campaign`` table at all is refused the same way: it is a database
where no campaign has ever been planned, which is the same fact about
the id rather than a different one.

One campaign, one run, one row
------------------------------

The table's key is ``campaign_id`` — one chosen window per run, because
one campaign is one run of the discovery loop (§5: *"one campaign = one
discovery tree"*).  The idempotence that follows is the one
:class:`~discovery.CampaignRecords` states, with both halves deliberate:

* *re-issuing the identical scheduling* — same campaign, and a fresh ask
  that lands on the same window — returns the stored record, including
  its original ``scheduled_at`` and the peak windows it was first chosen
  against.  A retry is the same scheduling call arriving twice, and the
  row *is* the decision: the retry did not move the moment it was made,
  and it did not re-make it against a card that has since moved.  §14.2
  publishes rate movements monthly; a retry that refreshed the premise
  would let the same campaign carry two different auditable reasons for
  the same window.

* *a scheduling that names a different window* is refused as
  :class:`~providers.RunWindowConflictError`, naming both windows — two
  schedules wearing one campaign, with the stored decision as the fact
  and the repair (read it with :meth:`~providers.DepthRunWindows.get`,
  or plan the next run under its own campaign id) stated in the refusal.

What the row carries, and why
-----------------------------

* ``campaign_id`` — the planned campaign's id, the key every reader of a
  run's window joins by, spelled ``NOT NULL PRIMARY KEY`` for the reason
  ``0111`` spells its own key that way: SQLite accepts NULL — and several
  of them — in a bare ``PRIMARY KEY``, and a second NULL-keyed window row
  would split a run's schedule from its campaign exactly as ``0111``'s
  docstring refuses for the campaign's own identity.

* ``start_at`` / ``end_at`` — the chosen window, as ISO-8601 UTC instant
  text in the spine's own spelling (``0111``'s
  ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` default: same wall-clock
  form, millisecond precision, ``Z``-suffixed), because that is how the
  rest of the spine's timestamps read back — text on SQLite, the twin of
  Postgres's ``timestamptz``.

* ``peak_windows`` — the configuration the choice was made against, as
  canonical JSON (an array of ``["HH:MM", "HH:MM"]`` pairs, sorted, one
  compact spelling — the discipline :class:`providers.AgentSampling`
  brings to its column).  Persisted beside the window because the window
  alone answers *when* and not *why*: §14.2's *"rates move monthly"*
  means the same window is off-peak on one card and peak on next
  month's, and a row that recorded only the window would let an auditor
  verify nothing.  It is also the premise the read path re-checks the
  window against — see below.

* ``scheduled_at`` — the instant of the decision, writer-stamped (no
  engine ``DEFAULT``, for the reason :mod:`bootstrap._pool` gives: a
  caller-stamped column never meets SQLite's ``DEFAULT`` grammar, so
  there is no dialect split to carry).  The value is the scheduling
  instant the caller stated (or the real now), which makes the row the
  record of one decision made at one moment, not a merge of several.

The record read back is re-verified, not merely re-parsed
---------------------------------------------------------

:meth:`~providers.DepthRunWindows.get` builds its answer from the row,
and refuses a row that contradicts its own premise: a stored window that
overlaps the very peak windows stored beside it is refused as the base
:class:`~providers.DepthScheduleError`, naming the campaign.  The read
side is where corruption would otherwise be laundered — the same stance
:meth:`providers.AgentModelPins.load` takes for a stored rolling alias,
stated in as many words ("the read side is where §14.1's corruption
would otherwise be laundered") — and here the laundering would be worse
than a bad identity: a window that reads as scheduled-off-peak while
sitting inside the recorded peaks is a campaign that paid double for a
decision the row claims was never made.

Recognition across the workspace's double import
------------------------------------------------

Every entry point (:func:`choose_run_window`,
:meth:`DepthRunWindows.schedule`, :class:`PeakPricing` itself)
recognises a caller's configuration **by its parts, not its class**, and
re-makes it from this module's classes — the move
:func:`providers.require_depth_model` makes for candidates and
:func:`providers.require_agent_model_id` makes for pins, for the same
load-bearing reason: the module loader imports every member twice (once
by file path under ``_nullius_scanned_<dir>``, once as the importable
member), so two ``PeakPricing`` classes exist over one source file, a
dataclass's generated ``__eq__`` answers ``False`` between them for
every value, and an ``isinstance`` gate would refuse the very record the
caller legitimately built.  Anything carrying a ``windows`` iterable of
``(start, end)``-shaped items is the configuration; the answer is always
this module's classes, so equality downstream means what it says.

Stdlib only, and import-cheap: ``sqlite3``, ``json``, ``uuid`` and
``datetime``; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for this module.  The store resolves its path lazily and opens
nothing until an operation needs it, so composing an application never
touches a database, and nothing is written until a caller schedules a
run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._schedule_errors import (
    DepthScheduleError,
    NoOffPeakWindowError,
    RunWindowConflictError,
    UnknownCampaignError,
)

__all__ = [
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TABLE_ID_COLUMN",
    "DATABASE_URL_ENV",
    "DEPTH_RUN_WINDOW_TABLE",
    "END_AT_COLUMN",
    "MINUTES_PER_DAY",
    "PEAK_WINDOWS_COLUMN",
    "SCHEDULED_AT_COLUMN",
    "START_AT_COLUMN",
    "DepthRunWindows",
    "PeakPricing",
    "PeakWindow",
    "RunWindow",
    "ScheduledRun",
    "choose_run_window",
    "schedule_depth_run",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the null
#: oracle's seven, the bootstrap pool's, the campaign planner's, the pin
#: store's), restated here so this store states its own contract and
#: imports nobody else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the chosen window lands in — **this member's own**, created
#: lazily by the store and by nobody else.  Contrast :data:`CAMPAIGN_TABLE`
#: below: that table is a core migration's and is probed read-only, while
#: this one is feature 202's own record, on the ``bootstrap_world``
#: precedent (a member-owned table for a member-owned fact, no edit to the
#: shared migration chain).
DEPTH_RUN_WINDOW_TABLE = "depth_run_window"

#: The planned-campaign table — feature 104's, created by
#: ``migrations/versions/0111_campaign_table.py``, its rows written by
#: feature 232's planner.  Read here for exactly one question — *was this
#: campaign ever planned?* — through a read-only ``sqlite_master`` lookup,
#: and never created: the same probe-not-create discipline
#: :mod:`discovery.campaign` follows for ``node``.
CAMPAIGN_TABLE = "campaign"

#: The column the campaign table's rows are keyed by — ``0111``'s ``id``,
#: the identity the planner mints and every reader of a campaign joins by.
#: Spelled here so the probe's ``SELECT`` and its refusal name the column
#: the migration owns, not a local invention.
CAMPAIGN_TABLE_ID_COLUMN = "id"

#: The run-window row's key: the planned campaign's id, as canonical UUID
#: text.  One campaign is one run, so one row per campaign — the whole
#: idempotence story of :class:`DepthRunWindows` hangs off this key.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The chosen window's start instant, as ISO-8601 UTC text.
START_AT_COLUMN = "start_at"

#: The chosen window's end instant, as ISO-8601 UTC text.
END_AT_COLUMN = "end_at"

#: The peak windows the choice was made against, as canonical JSON — an
#: array of ``["HH:MM", "HH:MM"]`` pairs, sorted, compact.  The premise
#: persisted beside the decision, so a row can be audited against the card
#: that was current when the decision was made (§14.2: *"rates move
#: monthly"*) and re-verified on read.
PEAK_WINDOWS_COLUMN = "peak_windows"

#: The instant the scheduling decision was made — writer-stamped, no
#: engine ``DEFAULT`` (the bootstrap pool's ground: a caller-stamped
#: column never meets SQLite's ``DEFAULT`` grammar, so there is no dialect
#: split to carry).
SCHEDULED_AT_COLUMN = "scheduled_at"

#: The length of one UTC day in minutes — the modulus the whole arithmetic
#: turns on, declared as data because the coverage walk, the gap
#: measurement and the candidate search all walk the same cycle and a
#: cycle two places spell is a cycle that can drift.
MINUTES_PER_DAY = 24 * 60

#: The parts a peak window is recognised by, in declaration order — duck
#: typing across the module loader's double import (see the module
#: docstring), the same tuple :mod:`providers._depth` declares for its
#: candidates.
_PEAK_PARTS: tuple[str, ...] = ("start", "end")

#: The parts a peak-pricing configuration is recognised by.
_PRICING_PARTS: tuple[str, ...] = ("windows",)

#: The read-only probe that answers *does this database hold this table?*
#: — ``sqlite_master`` is read (never the rows), which makes the check
#: safe on a database this process has no business writing to; the idiom
#: :mod:`discovery.campaign` uses for ``node`` and :mod:`bootstrap._census`
#: uses for its own absent-table refusal.  Parameterised, so the table
#: name is a bound value rather than interpolated text.
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"

#: The member-owned table, in one idempotent statement.  Every column is
#: ``NOT NULL`` — a run's schedule is written whole or not at all, and a
#: row with a window but no premise, or a premise but no decision instant,
#: is half a decision an auditor could not act on.  The key carries
#: ``NOT NULL`` explicitly beside ``PRIMARY KEY`` for the reason
#: ``0111``'s docstring spells at length: SQLite accepts NULL — and
#: several — in a bare ``PRIMARY KEY``, and a second NULL-keyed row would
#: split a run's schedule from its campaign.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {DEPTH_RUN_WINDOW_TABLE} (
    {CAMPAIGN_ID_COLUMN}  TEXT NOT NULL PRIMARY KEY,
    {START_AT_COLUMN}     TEXT NOT NULL,
    {END_AT_COLUMN}       TEXT NOT NULL,
    {PEAK_WINDOWS_COLUMN} TEXT NOT NULL,
    {SCHEDULED_AT_COLUMN} TEXT NOT NULL
)
"""

#: The parts of one second, in microseconds — the unit the minute
#: arithmetic rounds in, so a scheduling instant at 10:15:30.999 is ceiled
#: to 10:16 exactly rather than approximately.
_MICROS_PER_MINUTE = 60 * 1_000_000


# ── The configuration ─────────────────────────────────────────────────────────


def _require_time_of_day(value: object, which: str) -> time:
    """Return ``value`` as a minute-granular naive UTC time of day.

    One guard for the record's two ends, because they fail the same way
    and owe the caller the same explanation.  Three refusals, each naming
    what it refuses:

    * a non-:class:`~datetime.time` — the configuration states times of
      day, and ``"01:00"`` (a string) or ``60`` (an int) is config noise
      that guessing at would silently schedule against a window nobody
      described;
    * a time with ``tzinfo`` — a time of day in this module *is* UTC by
      definition (§14.2 states its windows in UTC), and a zone attached
      to a wall-clock time is a category error: ``time(1, 0, tzinfo=...)``
      names no instant and offsetting it would be inventing a window the
      card never stated;
    * a time carrying seconds or microseconds — pricing windows are
      minute-granular, and accepting ``time(1, 0, 30)`` would store a
      window whose text spelling round-trips to a different time of day
      than the caller's value, the drift a canonical column exists to
      prevent.

    Left as the base :class:`DepthScheduleError` rather than a subclass,
    on the grounds :mod:`providers._depth_errors` states for its own
    trivia: a malformed description is not a failed scheduling, and the
    taxonomy splits by question rather than by call site.
    """
    if not isinstance(value, time):
        raise DepthScheduleError(
            f"a peak window's {which} must be a datetime.time, got "
            f"{value!r} ({type(value).__name__}). The peak pricing "
            "configuration states times of day in UTC (architecture §14.2 "
            "spells its own windows 01:00–04:00 and 06:00–10:00), and a "
            "value that is not a time of day is config noise this "
            "scheduler would otherwise be guessing a window out of."
        )
    if value.tzinfo is not None:
        raise DepthScheduleError(
            f"a peak window's {which} must be a naive UTC time of day, got "
            f"{value!r} with tzinfo={value.tzinfo!r}. Times of day in this "
            "configuration are UTC by definition, and a time of day "
            "carrying a zone names no instant — offsetting it would "
            "silently schedule against a window the rate card never "
            "stated. State the wall-clock time in UTC and leave the zone "
            "off; convert at the call site if the source is local."
        )
    if value.second or value.microsecond:
        raise DepthScheduleError(
            f"a peak window's {which} must be minute-granular, got "
            f"{value!r}. A rate card states pricing windows to the minute "
            "(architecture §14.2's own are whole hours), and a time "
            "carrying seconds would be silently truncated by the "
            "scheduler's minute arithmetic — a window the caller described "
            "and the scheduler refused to honour. Drop the seconds."
        )
    return value


@dataclass(frozen=True)
class PeakWindow:
    """One peak pricing window: a daily UTC time-of-day interval ``[start, end)``.

    The two facts §14.2's lever is configured with, and no others: the
    time of day peak pricing ``start``s at (inclusive) and the time of day
    it ``end``s at (exclusive) — both whole-minute, naive, UTC.  A window
    with ``start`` before ``end`` is an ordinary same-day interval
    (01:00–04:00); a window with ``start`` *past* ``end`` is the card
    whose peak crosses midnight (22:00–02:00), spelled exactly that way
    rather than as two synthetic windows, because the card states one
    peak and the configuration should say what the card says.

    Construction validates shape only — the ends are times of day, naive,
    minute-granular, and not coincident.  Whether a configuration's
    windows leave room for a run is :func:`choose_run_window`'s question,
    asked with the run length in hand, for the same reason a 262K-window
    :class:`~providers.DepthModel` constructs happily and only the gate
    refuses it: describing a card is not scheduling against it.

    Frozen and value-equal for the reasons this package's other records
    are: a pricing window is a fact about a rate card, not a field a
    caller tunes, and equality by value is what lets a stored row's
    canonical JSON be compared to a freshly configured card without
    holding the same objects.
    """

    start: time
    end: time

    def __post_init__(self) -> None:
        # Field by field in declaration order, then the one cross-field
        # law, so a window malformed in several places is refused for the
        # first one a reader would meet.
        object.__setattr__(self, "start", _require_time_of_day(self.start, "start"))
        object.__setattr__(self, "end", _require_time_of_day(self.end, "end"))
        if self.start == self.end:
            raise DepthScheduleError(
                f"a peak window's start and end must not coincide, got "
                f"{self.start.isoformat()} for both. A zero-length interval "
                "contains no time, so it prices nothing at peak — but it is "
                "also one keystroke from the window that means the whole "
                "day, and a value this ambiguous is a misconfiguration to "
                "refuse rather than a fact to interpret."
            )

    @property
    def minutes(self) -> int:
        """The window's length in minutes per day, wrapping midnight.

        A same-day window's plain difference; a midnight-crossing one's
        complement.  Derived, never stored: the row holds the two ends and
        this is their difference — the same derived-not-stored split
        :meth:`discovery.CampaignRecord.planted_nulls` makes for ``φ · W``.
        """
        start = _minute_of_day(self.start)
        end = _minute_of_day(self.end)
        return end - start if start < end else end + MINUTES_PER_DAY - start

    def text(self) -> str:
        """The window's canonical ``"HH:MM-HH:MM"`` spelling.

        The form refusals quote and humans read; the column's JSON form
        (:func:`_pricing_json`) carries the two ends separately.
        """
        return f"{self.start.strftime('%H:%M')}-{self.end.strftime('%H:%M')}"


@dataclass(frozen=True)
class PeakPricing:
    """A rate card's peak pricing windows — feature 202's configuration.

    The frozen tuple of the card's :class:`PeakWindow`s.  §14.2's own card
    carries two (01:00–04:00 and 06:00–10:00 UTC) — the feature's sentence
    says *"a configured peak pricing window"* in the singular because it
    names the category, the way feature 212's *"legal set"* names a set —
    and the record holds however many the card states, in any order: the
    arithmetic reads them as a union of peak minutes, so overlapping or
    duplicate windows are legal configuration and mean what they say.

    **Empty is the flat-by-time-of-day card, not a missing one.**  A
    provider with no peak/off-peak split never enters peak, every window
    is off-peak, and :func:`choose_run_window` schedules immediately —
    the same positive fact :func:`providers.flat_pricing` names for a
    card with no surcharge threshold, and the reason the empty
    configuration is not refused: refusing it would make "my provider
    doesn't price by time of day" an unstatable configuration, when it is
    the *common* case (§14.2's surcharge table carries one provider that
    prices by time of day and several that do not).

    Construction accepts any iterable of windows, re-makes each one from
    this module's class (recognised **by its parts** — ``start`` and ``end``
    attributes — the double-import remedy the module docstring states,
    applied at the constructor so that every path through the configuration
    single-sources validation here, the way :func:`require_depth_model`
    re-makes candidates at the gate), and **canonicalizes the order**: the
    tuple is stored sorted by the windows' canonical spelling, so two
    configurations stating the same windows in different orders are one
    value — the same discipline the canonical text and the row's JSON
    column already follow, and the reason a record read back from a row
    compares equal to the card that scheduled it, whatever order that card
    was stated in.  Frozen and value-equal so a card configured twice
    compares equal.
    """

    windows: tuple[PeakWindow, ...] = ()

    def __post_init__(self) -> None:
        # Any iterable is accepted (a config file's list, a tuple a caller
        # built) and answered as this module's immutable tuple of this
        # module's windows, in the canonical sorted order — one class and
        # one order, so equality downstream means what it says and the
        # value a caller configured compares equal to the value the row
        # reads back.
        object.__setattr__(
            self,
            "windows",
            tuple(
                sorted(
                    (_window_from_parts(w) for w in self.windows),
                    key=PeakWindow.text,
                )
            ),
        )

    @property
    def flat_by_time_of_day(self) -> bool:
        """Whether this card never enters peak — no windows configured.

        The named fact, offered as a property for the same reason
        :func:`providers.flat_pricing` exists as a function: the empty
        configuration is a decision a caller may have *meant* or may never
        have thought about, and the answer's spelling should say which
        question it answers.  Here the property *reports* the configured
        card (and :func:`choose_run_window` schedules immediately on it),
        while the caller who means it states it by configuring no windows
        — there is no ``None`` to disambiguate, so there is no helper to
        spell.
        """
        return not self.windows

    def text(self) -> str:
        """The configuration's canonical spelling — windows joined, sorted.

        Sorted by the windows' canonical text so two configurations
        stating the same windows in different orders spell the same and
        compare the same — the determinism the stored JSON column relies
        on.
        """
        return ", ".join(sorted(w.text() for w in self.windows))


# ── The choice's answer ───────────────────────────────────────────────────────


def _require_instant(value: object, what: str) -> datetime:
    """Return ``value`` as an aware UTC ``datetime``, refusing the rest.

    Aware datetimes of any offset are accepted and converted — an instant
    is an instant, and a caller holding local time states it honestly.
    Naive datetimes are refused by name: a naive value names no instant,
    and guessing a zone would schedule a run against a wall clock nobody
    stated, which for a feature whose whole point is *which side of a
    UTC boundary the run lands on* is the one guess this module must not
    make.  The same split :meth:`providers.AgentModelPins`' callers get
    nowhere and its store gets always: shape is the caller's business,
    instants are this module's.
    """
    if not isinstance(value, datetime):
        raise DepthScheduleError(
            f"{what} must be a datetime, got {value!r} "
            f"({type(value).__name__}). Scheduling compares instants "
            "against a rate card's daily windows, and a value that is not "
            "an instant cannot be compared to one."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise DepthScheduleError(
            f"{what} must be timezone-aware, got {value!r}: a naive "
            "datetime names no instant, and assigning it a zone by guess "
            "would schedule the run against a wall clock nobody stated — "
            "the one guess a scheduler whose subject is which side of a "
            "UTC boundary a run lands on must not make."
        )
    return value.astimezone(UTC)


@dataclass(frozen=True)
class RunWindow:
    """The chosen window: two aware UTC instants, ``[start_at, end_at)``.

    The answer :func:`choose_run_window` returns and the row persists.
    Both bounds are minute-aligned (the pricing they avoid is
    minute-granular), aware, UTC; ``end_at`` is exactly ``start_at`` plus
    the declared length, so :attr:`duration` is derived rather than
    carried.  Half-open: a run may start at the minute a peak ends and
    may end at the minute a peak starts, and touches neither peak —
    the arithmetic's own convention, stated on the record because it is
    the boundary a caller will ask about first.

    Frozen and value-equal: the record of a decision, like every record
    in this package — a mutable one would let a caller retype a schedule
    in memory while the row said otherwise.
    """

    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        start = _require_instant(self.start_at, "a run window's start_at")
        end = _require_instant(self.end_at, "a run window's end_at")
        object.__setattr__(self, "start_at", start)
        object.__setattr__(self, "end_at", end)
        if end <= start:
            raise DepthScheduleError(
                f"a run window's end_at must be after its start_at, got "
                f"{end.isoformat()} against {start.isoformat()}. A window "
                "that ends when it starts contains no run, and one that "
                "ends before it starts is not a window at all."
            )

    @property
    def duration(self) -> timedelta:
        """The window's length — derived, never stored.

        ``end_at - start_at``, the same derived-not-stored split the
        campaign record makes for its ``planted_nulls``: the row holds the
        two bounds and this is their difference.
        """
        return self.end_at - self.start_at


# ── The arithmetic ────────────────────────────────────────────────────────────


def _minute_of_day(moment: time) -> int:
    """A time of day as minutes since UTC midnight — ``time(1, 30)`` is 90."""
    return moment.hour * 60 + moment.minute


def _abs_minute(moment: datetime) -> int:
    """An aware UTC instant ceiled to whole minutes since the Unix epoch.

    Ceiled rather than floored, because the arithmetic asks for the first
    minute *at or after* the scheduling instant that a run may start in:
    an instant at 10:15:30 cannot start a run at 10:15 (that minute is
    half gone), so the candidate is 10:16.  Integer microseconds
    throughout, so the ceiling is exact and no float rounding ever moves
    a boundary.
    """
    micros = round(moment.timestamp() * 1_000_000)
    minutes, remainder = divmod(micros, _MICROS_PER_MINUTE)
    return minutes + (1 if remainder else 0)


def _instant_of_minute(minute: int) -> datetime:
    """The aware UTC instant of an absolute minute since the epoch."""
    return datetime.fromtimestamp(minute * 60, tz=UTC)


def _window_from_parts(value: object) -> PeakWindow:
    """Recognise a peak window by its parts and re-make it, or refuse it.

    Duck-typed across the workspace's double import (see the module
    docstring): anything carrying ``start`` and ``end`` is a window, and
    the constructor's shape guard is the single validation — so a stub
    carrying ``start="01:00"`` is told its start is not a time of day,
    not that it is "not a window".  ``object.__getattribute__`` rather
    than ``getattr`` so an arbitrary object's ``__getattr__`` cannot
    fabricate a window, the same guard
    :func:`providers._depth._candidate_parts_or_none` states for its
    candidates.
    """
    if isinstance(value, PeakWindow):
        return value
    try:
        parts = tuple(object.__getattribute__(value, part) for part in _PEAK_PARTS)
    except AttributeError:
        parts = None
    if parts is None:
        raise DepthScheduleError(
            f"a peak window must be a PeakWindow ({', '.join(_PEAK_PARTS)}), "
            f"got {value!r} ({type(value).__name__}). The configuration "
            "states times of day, and a value carrying none cannot be "
            "checked against a run — padding the missing parts with "
            "guesses would be scheduling against a window nobody described."
        )
    return PeakWindow(start=parts[0], end=parts[1])


def _require_pricing(value: object) -> PeakPricing:
    """Recognise a peak-pricing configuration by its parts, or refuse it.

    The same duck-typed recognition :func:`_window_from_parts` makes for
    windows, applied one level up and re-making the whole configuration
    from this module's class — so a caller holding the loader's other
    class copy is answered with one whose equality means what it says,
    and every entry point (``choose_run_window``, the store's
    ``schedule``) single-sources validation in the constructor.
    """
    if isinstance(value, PeakPricing):
        return value
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _PRICING_PARTS
        )
    except AttributeError:
        parts = None
    if parts is None:
        raise DepthScheduleError(
            f"a peak pricing configuration must be a PeakPricing "
            f"({', '.join(_PRICING_PARTS)}), got {value!r} "
            f"({type(value).__name__}). Feature 202 schedules against a "
            "configured card, and a value carrying no windows is not a "
            "configuration to schedule against — an empty card is "
            "PeakPricing(), stated, not an arbitrary value guessed at."
        )
    return PeakPricing(windows=parts[0])


def _require_run_minutes(value: object) -> int:
    """Return ``value`` as a positive whole-minute run length, or refuse it.

    The declared expected length of the run, as the campaign launcher
    states it.  Three refusals, each about a different non-length:

    * not a :class:`~datetime.timedelta` — a bare int of "hours" or a
      float of minutes is a unit the caller left unstated, and guessing
      the unit would schedule a run of the wrong length by up to sixty;
    * not positive — a run that takes no time is not a run, and the
      window it would ask for contains nothing to schedule;
    * not a whole number of minutes — the pricing the window avoids is
      minute-granular and the window's bounds are minute-aligned, so a
      90-second length would persist a window whose stored text
      round-trips to a different length than the caller declared.
    """
    if isinstance(value, bool) or not isinstance(value, timedelta):
        raise DepthScheduleError(
            f"a run's duration must be a timedelta, got {value!r} "
            f"({type(value).__name__}). The length is stated with its "
            "unit — timedelta(hours=3), timedelta(minutes=90) — and a "
            "bare number is a unit this scheduler would have to guess, "
            "scheduling a run of the wrong length by however far the "
            "guess is out."
        )
    if value <= timedelta(0):
        raise DepthScheduleError(
            f"a run's duration must be positive, got {value!r}. A run "
            "that takes no time is not a run, and there is no window to "
            "schedule one into — a caller meaning 'start as soon as "
            "off-peak allows' passes the real expected length and lets "
            "the scheduler find the earliest legal start."
        )
    total = value.total_seconds()
    if total % 60:
        raise DepthScheduleError(
            f"a run's duration must be a whole number of minutes, got "
            f"{value!r}. Pricing windows are minute-granular and the "
            "chosen window's bounds are minute-aligned, so a length "
            "carrying seconds would persist a window whose stored "
            "spelling round-trips to a different length than the one "
            "declared."
        )
    return int(total // 60)


def _covers(window: PeakWindow, minute_of_day: int) -> bool:
    """Whether ``window`` covers a minute of the day, midnight-wrap included.

    A same-day window covers ``[start, end)``; a midnight-crossing one
    covers ``[start, 24:00) ∪ [00:00, end)``.  Half-open at both ends in
    both cases, matching :class:`RunWindow`'s own convention.
    """
    start = _minute_of_day(window.start)
    end = _minute_of_day(window.end)
    if start < end:
        return start <= minute_of_day < end
    return minute_of_day >= start or minute_of_day < end


def _largest_off_peak_gap(windows: tuple[PeakWindow, ...]) -> int:
    """The largest run of consecutive off-peak minutes on the card, in minutes.

    Measured on the *circle* of one UTC day — a gap may wrap midnight
    (on §14.2's card, 10:00–01:00 is one fifteen-hour gap, not a
    fourteen-hour one truncated by the clock) — by rotating the coverage
    walk to start at a peak minute, which turns the circular longest gap
    into a linear one.  Zero when peak covers the whole day, which is the
    honest answer rather than an error: it is a configuration whose
    refusal (:class:`~providers.NoOffPeakWindowError`) names a largest
    gap of zero minutes, a fact a caller can act on.
    """
    covered = bytearray(MINUTES_PER_DAY)
    for window in windows:
        start = _minute_of_day(window.start)
        end = _minute_of_day(window.end)
        if start < end:
            covered[start:end] = b"\x01" * (end - start)
        else:
            covered[start:] = b"\x01" * (MINUTES_PER_DAY - start)
            covered[:end] = b"\x01" * end
    if all(covered):
        return 0
    # Rotate so the walk starts inside a peak minute: the run of
    # off-peak minutes that crosses midnight is then one run in the walk
    # rather than two half-runs at its ends.
    rotation = covered.index(1)
    longest = 0
    run = 0
    for offset in range(MINUTES_PER_DAY):
        if covered[(rotation + offset) % MINUTES_PER_DAY]:
            run = 0
        else:
            run += 1
            longest = max(longest, run)
    return longest


def _fits(start: int, minutes: int, windows: tuple[PeakWindow, ...]) -> bool:
    """Whether ``[start, start + minutes)`` touches no peak minute, any day.

    Interval arithmetic rather than a minute-by-minute walk: each window's
    day-instances that the run's span could reach are enumerated (the
    days from the run's first to its last, one either side for the
    windows that wrap midnight), and each instance is intersected with
    the run.  A run of hours costs a handful of comparisons; one of days
    costs one per day per window — bounded by the run itself, which is
    the only thing that can make it large.
    """
    end = start + minutes
    first_day = start // MINUTES_PER_DAY
    last_day = (end - 1) // MINUTES_PER_DAY
    for window in windows:
        peak_start = _minute_of_day(window.start)
        peak_end = _minute_of_day(window.end)
        for day in range(first_day - 1, last_day + 2):
            base = day * MINUTES_PER_DAY
            # A midnight-crossing window occupies two chunks per day; a
            # same-day one occupies the single interval.  Both half-open.
            chunks = (
                ((peak_start + base, peak_end + base),)
                if peak_start < peak_end
                else (
                    (peak_start + base, MINUTES_PER_DAY + base),
                    (base, peak_end + base),
                )
            )
            for low, high in chunks:
                if low < end and start < high:
                    return False
    return True


def choose_run_window(
    pricing: object,
    *,
    duration: timedelta,
    now: datetime | None = None,
) -> RunWindow:
    """Choose the earliest window outside every configured peak — feature 202's gate.

    §14.2's instruction — *"Schedule campaigns outside those windows"* —
    as an arithmetic.  Given the card's peak windows, the declared run
    length and the scheduling instant, the answer is the **earliest**
    minute-aligned window ``[start, start + duration)`` with ``start`` no
    earlier than ``now`` that touches no peak minute of the card, on any
    day the run spans.  Earliest is the whole point: off-peak is 50%
    lower, waiting costs nothing (§14.2: the depth role *"is pure
    asynchronous batch work. Nothing waits on it"*), and the first legal
    window is therefore the cheapest window that does not waste the
    campaign's lead time.

    The search is over candidate starts, and the candidates are the only
    starts a fit can begin at: the scheduling instant itself (ceiled to
    the minute), and the minute each peak window *ends* within one day of
    it.  Every off-peak gap on the card begins either at a peak's end or
    has always been open (the instant's own gap), so a fitting window
    exists exactly when the declared length fits the largest gap, and the
    first fitting candidate is the answer — no scanning of minutes, no
    missing a fit the card allowed.

    * An **empty configuration** (a card flat by time of day) answers
      immediately at the scheduling instant: every window is off-peak,
      and there is nothing to wait out.
    * A declared length **larger than the largest off-peak gap** is
      refused as :class:`~providers.NoOffPeakWindowError`, naming the
      gap in hours and minutes — the number the duration has to come
      under, and the one the repair turns on.
    * A run may **start at the minute a peak ends** and **end at the
      minute a peak starts**: the window is half-open, and both boundary
      placements are off-peak by the card's own arithmetic.

    ``duration`` is the caller's declared expected run length, taken as
    an argument because the scheduler has no length of its own to know:
    §14.2 prices the depth role in tokens and dollars, not wall-clock,
    and the launcher that knows its own expected span is the caller that
    states it.  ``now`` is the moment of scheduling — an aware datetime
    of any offset, converted to UTC, defaulting to the current instant —
    and a naive value is refused by name, because a value that names no
    instant cannot be placed against UTC windows.

    Recognises the configuration by its parts and re-makes it from this
    module's class (see the module docstring), so the double-import's
    twin classes both schedule, and the answer is always one
    :class:`RunWindow`.
    """
    peaks = _require_pricing(pricing)
    minutes = _require_run_minutes(duration)
    moment = (
        _require_instant(datetime.now(UTC), "the scheduling instant")
        if now is None
        else _require_instant(now, "the scheduling instant")
    )
    earliest = _abs_minute(moment)
    if not peaks.windows:
        # Flat by time of day: every window is off-peak, the earliest
        # legal start is the scheduling instant, and no gap measurement
        # could name a constraint the card does not have.
        return _window_between(earliest, earliest + minutes)
    gap = _largest_off_peak_gap(peaks.windows)
    if minutes > gap:
        raise NoOffPeakWindowError(
            f"a run of {_describe_minutes(minutes)} does not fit outside "
            f"the configured peak windows ({peaks.text()}), whose largest "
            f"off-peak gap is {_describe_minutes(gap)}. Architecture "
            "§14.2's lever — schedule campaigns outside the peak window, "
            "at 50% lower off-peak input — only reaches a run that fits "
            "where the pricing is cheap, and this declared length cannot. "
            "Shorten the declared run, configure the card whose peaks "
            "leave a wider gap, or accept the peak rate — the one thing "
            "this scheduler will not do is persist a window the card "
            "contradicts."
        )
    # Candidate starts: the scheduling instant, and every peak end within
    # one day after it — the first minute of each off-peak gap the card
    # will open over the next cycle.  A peak end at exactly one day's
    # remove is the same gap's start the cycle before; including both is
    # harmless (the same fit answers) and keeps the set simple to reason
    # about.
    candidates = {earliest}
    for window in peaks.windows:
        end = _minute_of_day(window.end)
        # The first occurrence of this end at or after the scheduling
        # minute — one ceil-div, not a loop of days.
        occurrence = end + MINUTES_PER_DAY * (
            (earliest - end + MINUTES_PER_DAY - 1) // MINUTES_PER_DAY
        )
        if earliest <= occurrence <= earliest + MINUTES_PER_DAY:
            candidates.add(occurrence)
    for start in sorted(candidates):
        if _fits(start, minutes, peaks.windows):
            return _window_between(start, start + minutes)
    # Unreachable while the largest-gap refusal stands — a gap at least
    # as long as the run always opens a candidate within one day — and
    # kept as the honest guard rather than an ``assert``, because the
    # reasoning that makes it unreachable lives here in the docstring and
    # not in the type system.
    raise NoOffPeakWindowError(
        f"no window of {_describe_minutes(minutes)} fits outside the "
        f"configured peak windows ({peaks.text()}) within a day of the "
        f"scheduling instant, though the card's largest off-peak gap is "
        f"{_describe_minutes(gap)}. This is a scheduler defect, not a "
        "configuration one — report it with the card and the declared "
        "length."
    )


def _window_between(start: int, end: int) -> RunWindow:
    """The :class:`RunWindow` of two absolute minutes — the arithmetic's exit."""
    return RunWindow(start_at=_instant_of_minute(start), end_at=_instant_of_minute(end))


def _describe_minutes(minutes: int) -> str:
    """A length in minutes as the hours-and-minutes spelling a refusal quotes.

    ``90`` is "an hour and 30 minutes", ``120`` is "2 hours", ``45`` is
    "45 minutes" — the words a caller schedules in, rather than the raw
    count the arithmetic keeps.
    """
    hours, remainder = divmod(minutes, 60)
    if not hours:
        return f"{remainder} minute{'s' if remainder != 1 else ''}"
    if not remainder:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} and {remainder} minutes"


# ── The persistence ───────────────────────────────────────────────────────────


def _format_instant(moment: datetime) -> str:
    """An instant as the spine's ISO-8601 UTC text — ``0111``'s own spelling.

    ``%Y-%m-%dT%H:%M:%S`` plus a three-digit millisecond field and a
    ``Z``, which is byte-for-byte the form SQLite's
    ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` writes for the campaign
    table's ``created_at`` — the same wall-clock form, read back as text
    rather than as a typed timestamp, which is how the rest of the spine
    stores its timestamps.  The milliseconds are written by hand because
    :meth:`datetime.strftime`'s ``%f`` is six digits and the spine's is
    three; a format two spellings wide is a format that reads back
    inconsistently.
    """
    utc = moment.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _parse_instant(text: object, campaign: str, column: str) -> datetime:
    """Read back one of the row's instants, refusing a value that is not one.

    The read path's one instant parser, so ``schedule``'s read-back and
    ``get`` cannot disagree about the form.  Anything the spine's spelling
    round-trips is accepted; anything else — text another dialect wrote,
    a truncated column, an editing accident — is refused naming the
    campaign and the column, because a window whose bound does not parse
    is a row this feature cannot report.
    """
    if not isinstance(text, str) or not text.strip():
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{column} {text!r}, which is not an ISO-8601 UTC instant. The "
            "row was not written by this feature — its window columns are "
            "the spine's own timestamp text, and one that does not parse "
            "is a row this record cannot report."
        )
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{column} {text!r}, which does not parse as an ISO-8601 "
            "instant. The row was not written by this feature, and a "
            "bound that cannot be read is a decision this record cannot "
            "report."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{column} {text!r} without a UTC offset: it names no instant, "
            "and a run window that names no instant cannot be audited "
            "against the card it was chosen from."
        )
    return parsed.astimezone(UTC)


def _pricing_json(pricing: PeakPricing) -> str:
    """The configuration's canonical column text.

    An array of ``["HH:MM", "HH:MM"]`` pairs, sorted by the windows'
    canonical spelling, rendered compact — one spelling of one card, so
    two configurations stating the same windows in different orders
    write the same column and a retry's read-back compares equal.  The
    sorted-compact-JSON discipline :class:`providers.AgentSampling`
    brings to its own column, restated for a configuration that has no
    natural key order of its own.
    """
    pairs = sorted(
        (w.start.strftime("%H:%M"), w.end.strftime("%H:%M")) for w in pricing.windows
    )
    return json.dumps(pairs, separators=(",", ":"))


def _pricing_from_json(text: object, campaign: str) -> PeakPricing:
    """Read back the row's configuration, refusing a value that is not one.

    The premise is read back as it was written — every pair re-made
    through the constructor, so the stored text and the configured card
    answer equal objects — and anything else is refused naming the
    campaign: a premise that does not parse is a row this feature cannot
    re-verify the window against, which is the whole reason the column
    exists.
    """
    if not isinstance(text, str) or not text.strip():
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{PEAK_WINDOWS_COLUMN} {text!r}, which is not the canonical "
            "JSON this feature writes. The row was not written by this "
            "feature, and a window without a readable premise is a "
            "decision that cannot be audited."
        )
    try:
        pairs = json.loads(text)
    except ValueError as exc:
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{PEAK_WINDOWS_COLUMN} {text!r}, which does not parse as "
            "JSON. The row was not written by this feature."
        ) from exc
    if not isinstance(pairs, list) or not all(
        isinstance(pair, list)
        and len(pair) == 2
        and all(isinstance(bound, str) for bound in pair)
        for pair in pairs
    ):
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{PEAK_WINDOWS_COLUMN} {text!r}, which is not the canonical "
            "array of [\"HH:MM\", \"HH:MM\"] pairs this feature writes. "
            "The row was not written by this feature."
        )
    try:
        return PeakPricing(
            windows=tuple(
                PeakWindow(
                    start=time.fromisoformat(pair[0]),
                    end=time.fromisoformat(pair[1]),
                )
                for pair in pairs
            )
        )
    except (DepthScheduleError, ValueError) as exc:
        raise DepthScheduleError(
            f"the run window scheduled for campaign {campaign!r} carries "
            f"{PEAK_WINDOWS_COLUMN} {text!r}, whose windows are not "
            f"minute-granular UTC times of day: {exc}"
        ) from exc


@dataclass(frozen=True)
class ScheduledRun:
    """One campaign's scheduled depth runs: the chosen window, and its record.

    The row's five facts as one value: the ``campaign_id`` the window was
    scheduled for (the planned campaign's canonical UUID text), the
    ``window`` (:class:`RunWindow`), the ``pricing`` the choice was made
    against (:class:`PeakPricing` — the premise, persisted so the
    decision can be audited against the card that was current when it
    was made), the ``scheduled_at`` instant of the decision, and
    ``recorded`` — this call's answer state, the same field
    :class:`providers.NodePin` and :class:`providers.NodeProvenance`
    carry: ``True`` when the call that returned this record wrote the
    row, ``False`` when it answered the row that was already there (an
    idempotent retry, or any read from :meth:`DepthRunWindows.get`, which
    never writes).

    Frozen, so a record that has been read back cannot be edited into a
    different schedule by a caller who kept a reference — the record of
    a decision, like every record in this package.
    """

    campaign_id: str
    window: RunWindow
    pricing: PeakPricing
    scheduled_at: datetime
    recorded: bool = False

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`discovery.CampaignRecord.row` states: a rendered mapping
        names the same things the same way the store does.  ``recorded``
        is deliberately absent — it is this call's answer state, not a
        fact of the row.
        """
        return {
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            START_AT_COLUMN: _format_instant(self.window.start_at),
            END_AT_COLUMN: _format_instant(self.window.end_at),
            PEAK_WINDOWS_COLUMN: _pricing_json(self.pricing),
            SCHEDULED_AT_COLUMN: _format_instant(self.scheduled_at),
        }


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning canonical UUID text.

    The same canonicalization :func:`discovery.campaign._validated_campaign_id`
    applies, restated rather than imported (no member imports another):
    the value joins the campaign table's ``id`` and every reader of a
    run's window, so a mixed-case key would make one campaign look like
    two.  Unlike the planner's write path there is no ``None`` case here
    to let a table mint — this table's key is the campaign's own id, and
    a scheduling with no campaign names no run to schedule.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise DepthScheduleError(
        f"campaign_id {value!r} is not a UUID; a run's window is scheduled "
        "for a campaign, and the campaign's id is the value "
        f"{CAMPAIGN_TABLE_ID_COLUMN} the campaign table holds and every "
        "reader of this row joins by — an id that cannot join it names "
        "no campaign whose runs could be scheduled"
    )


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The convention every store in this workspace uses, restated here so
    this store states its own contract and the refusal is this module's
    own error class.  A non-SQLite scheme is refused by name (the spec's
    single-machine allowance is what a stdlib store can speak), and an
    in-memory URL is refused too: a scheduled window must outlive the
    scheduling call — the campaign launcher that reads it back, and the
    auditor that re-verifies it, run in another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise DepthScheduleError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the campaign "
            "table already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise DepthScheduleError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise DepthScheduleError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a scheduled window must outlive the scheduling call — "
            "the launcher that waits for the window and the auditor that "
            "re-verifies it against the card both read it in another "
            "process"
        )
    return Path(path)


class DepthRunWindows:
    """The store that schedules campaigns' depth runs and persists the window.

    Constructed with the database URL it writes to; :meth:`schedule` is
    feature 202's sentence as one call — choose the window, prove the
    campaign was planned, insert the row, read it back — and :meth:`get`
    reads one campaign's scheduled window.  The class resolves its path
    lazily, so constructing one performs no I/O: composition-time work
    must not touch the disk, the contract every store in this workspace
    states.  The table (:data:`DEPTH_RUN_WINDOW_TABLE`) is this member's
    own, created lazily on the store's **first write** — :meth:`get` on a
    store that has never scheduled reads ``sqlite_master``, finds no
    table, and answers ``None``, so a read never brings a schema into
    being.

    The store holds no cache of the decisions it wrote: the row is the
    only record of what was scheduled, so it is the only thing an answer
    is drawn from — the same stance :class:`discovery.CampaignRecords`
    states, for the same reason.  A memo of scheduled campaigns would
    make *"was this run scheduled, and against which card?* a question
    about this process's history rather than about the world.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise DepthScheduleError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> DepthRunWindows | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not
        an error: it is a deployment without a relational store, which
        composes no run-window component — a discoverable state, not an
        exception — while the launcher that must persist a run's chosen
        window is the caller that must not find itself in it, for the
        reason :func:`providers.build_agent_model_pins` states on its own
        ``None``: the caller that needs this row treats it as a refusal
        to proceed rather than as a store that happened to find nothing.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time
        an operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to
        commit, which is what :meth:`schedule` does — the campaign probe,
        the row read and the ``INSERT`` are one unit of work, so a
        campaign planned by a concurrent process between the probe and
        the insert is seen, and two schedulers of one campaign cannot
        interleave a read and a write.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        """Create this member's own table, idempotently.

        The one act that separates this store from
        :class:`providers.AgentModelPins`: that store writes a column a
        core migration owns and refuses to invent the table; this one's
        table is its own feature's record, on the ``bootstrap_world``
        precedent, and creating it lazily is the store's business.
        ``IF NOT EXISTS``, so a database that already holds it — a second
        schedule, a restarted process — passes through untouched.
        """
        connection.execute(_SCHEMA)

    # -- Feature 202: the schedule ------------------------------------------

    def schedule(
        self,
        campaign_id: Any,
        pricing: Any,
        *,
        duration: timedelta,
        now: datetime | None = None,
    ) -> ScheduledRun:
        """Schedule one campaign's depth runs outside the peak windows.

        Feature 202's sentence as one call: the campaign id, the card and
        the declared length in, the stored scheduled run out — the choice
        and its persistence as one act, because a window chosen and not
        persisted is the sentence with its second half missing.  The
        steps, and why each is where it is:

        1. **Validate the ask** — the id as a UUID, the card by its
           parts, the length as a positive whole number of minutes, the
           instant as aware — before anything is opened, so a malformed
           ask is refused without touching a database.
        2. **Choose the window** (:func:`choose_run_window`) — the
           earliest window at or after the scheduling instant that
           touches no configured peak minute.  The one fact this feature
           exists to decide, and the reason the refusal for a length that
           fits no gap is the *chooser's* to raise: it is the choice that
           failed, before any campaign was asked about.
        3. **Create the table**, lazily and idempotently — the row's
           first write brings its schema into being, and nothing else
           ever does.
        4. **Prove the campaign was planned** — the ``campaign`` table,
           probed read-only, holds a row with this id.  A run scheduled
           for an id no campaign row holds is a run that will never
           happen, persisted beside campaigns that did, and
           :class:`~providers.UnknownCampaignError` is its refusal.
        5. **Return the stored row if the campaign is already
           scheduled** — an identical re-issue answers the row it finds
           (``recorded=False``, the original ``scheduled_at`` and the
           original card, which a retry does not move or re-make) — or
           **refuse** when the fresh choice lands on a different window
           (:class:`~providers.RunWindowConflictError`, naming both).
        6. **Insert, then read back**, and return what the table holds:
           the window, the card and the decision instant are the row's,
           re-parsed through the same readers ``get`` uses, so a caller
           holds one record shape from one source of truth.

        Refuses, in this order, each naming what it is about: a
        malformed id, card, length or instant (the base
        :class:`~providers.DepthScheduleError`); a length that fits no
        off-peak gap (:class:`~providers.NoOffPeakWindowError`); an
        unknown campaign (:class:`~providers.UnknownCampaignError`); a
        re-scheduling that names a different window
        (:class:`~providers.RunWindowConflictError`).
        """
        campaign = _validated_campaign_id(campaign_id)
        peaks = _require_pricing(pricing)
        # One instant for both roles the scheduling moment plays: the
        # floor the chooser's candidates start at, and the instant the
        # row stamps as the decision's own.  Computed once here so the
        # two can never differ — a row stamped microseconds after the
        # window it chose would be two clocks narrating one decision.
        decision_at = (
            _require_instant(datetime.now(UTC), "the scheduling instant")
            if now is None
            else _require_instant(now, "the scheduling instant")
        )
        window = choose_run_window(peaks, duration=duration, now=decision_at)
        with closing(self._connect()) as connection, connection:
            self._ensure_schema(connection)
            self._require_campaign(connection, campaign)
            stored = self._read_row(connection, campaign)
            if stored is not None:
                return self._reissued(stored, window, campaign)
            connection.execute(
                f"INSERT INTO {DEPTH_RUN_WINDOW_TABLE} "
                f"({CAMPAIGN_ID_COLUMN}, {START_AT_COLUMN}, {END_AT_COLUMN}, "
                f"{PEAK_WINDOWS_COLUMN}, {SCHEDULED_AT_COLUMN}) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    campaign,
                    _format_instant(window.start_at),
                    _format_instant(window.end_at),
                    _pricing_json(peaks),
                    _format_instant(decision_at),
                ),
            )
            row = self._read_row(connection, campaign)
        if row is None:
            raise DepthScheduleError(
                f"the run window scheduled for campaign {campaign!r} could "
                "not be read back after the insert; the row is the "
                "decision, and a decision that cannot be re-read is one "
                "this store cannot vouch for"
            )
        return self._record_from_row(row, recorded=True)

    def get(self, campaign_id: Any) -> ScheduledRun | None:
        """One campaign's scheduled run, or ``None`` when it holds none.

        ``None`` means *this campaign's runs were never scheduled* —
        nothing has recorded a window for it — which is the honest answer
        for a campaign no row holds, and the answer on a database whose
        ``depth_run_window`` table does not exist yet (a store that has
        never scheduled created nothing, and a read does not create it).
        It does **not** mean the read failed: an unreachable database
        raises, so a caller can never mistake a broken store for an
        unscheduled campaign — the same distinction
        :meth:`discovery.CampaignRecords.get` draws.

        The record is **re-verified, not merely re-parsed**: a stored
        window that overlaps the very peak windows stored beside it is
        refused as the base :class:`~providers.DepthScheduleError`,
        naming the campaign — the read side is where corruption would
        otherwise be laundered, and a window that reads as
        scheduled-off-peak while sitting inside the recorded peaks is a
        campaign that paid peak rate for a decision the row claims was
        never made.  ``recorded`` is always ``False`` here: a read wrote
        nothing.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    _TABLE_EXISTS_SQL, (DEPTH_RUN_WINDOW_TABLE,)
                ).fetchone()
                is None
            ):
                return None
            row = self._read_row(connection, campaign)
        if row is None:
            return None
        return self._record_from_row(row, recorded=False)

    # -- The words ----------------------------------------------------------

    def _read_row(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[Any, ...] | None:
        """One campaign's row as the table holds it, or ``None`` when absent.

        Selected column by column rather than with ``SELECT *``, the
        discipline :meth:`discovery.CampaignRecords._read_row` states: the
        order :meth:`_record_from_row` reads must be the order this
        names, and a column appended later must not silently shift the
        fields.
        """
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_ID_COLUMN}, {START_AT_COLUMN}, "
            f"{END_AT_COLUMN}, {PEAK_WINDOWS_COLUMN}, {SCHEDULED_AT_COLUMN} "
            f"FROM {DEPTH_RUN_WINDOW_TABLE} WHERE {CAMPAIGN_ID_COLUMN} = ?",
            (campaign,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _record_from_row(
        self, row: tuple[Any, ...], *, recorded: bool
    ) -> ScheduledRun:
        """Build a :class:`ScheduledRun` from a row, re-verified.

        The read path's one constructor, so :meth:`get` and
        :meth:`schedule`'s read-back cannot disagree about which column is
        which.  Every value is re-parsed through the row-shaped readers
        (instants, the card's JSON) rather than trusted, and the window
        is then **re-verified against the card beside it** — the premise
        the column exists to make checkable.  A refusal from here names
        the campaign it came off, which is the difference between an
        operator learning *this campaign's schedule is corrupt* and
        learning that some value somewhere does not parse.
        """
        campaign = _validated_campaign_id(row[0])
        window = RunWindow(
            start_at=_parse_instant(row[1], campaign, START_AT_COLUMN),
            end_at=_parse_instant(row[2], campaign, END_AT_COLUMN),
        )
        pricing = _pricing_from_json(row[3], campaign)
        if not pricing.flat_by_time_of_day and not _fits(
            _abs_minute(window.start_at),
            int(window.duration.total_seconds() // 60),
            pricing.windows,
        ):
            raise DepthScheduleError(
                f"the run window scheduled for campaign {campaign!r} "
                f"({window.start_at.isoformat()} to "
                f"{window.end_at.isoformat()}) overlaps the peak windows "
                f"recorded beside it ({pricing.text()}), so the row "
                "contradicts its own premise. The row was not written by "
                "this feature — the chooser never returns a window inside "
                "the card it was given — and reading it back as a valid "
                "schedule would launder it into a campaign that paid peak "
                "rate for a decision the row claims was never made."
            )
        return ScheduledRun(
            campaign_id=campaign,
            window=window,
            pricing=pricing,
            scheduled_at=_parse_instant(row[4], campaign, SCHEDULED_AT_COLUMN),
            recorded=recorded,
        )

    def _reissued(
        self, row: tuple[Any, ...], window: RunWindow, campaign: str
    ) -> ScheduledRun:
        """Answer a re-issued scheduling: the stored record, or a conflict.

        The identical scheduling — a fresh ask that lands on the same
        window — returns the row the table holds, **including its
        original ``scheduled_at`` and the card it was first chosen
        against**.  A retry is the same scheduling call arriving twice,
        and the row *is* the decision: the retry did not move the moment
        it was made, and — §14.2's rates moving monthly being the stated
        reason the card is persisted at all — it did not re-make the
        decision against a card that has since moved.

        A fresh ask that lands on a **different** window is refused, and
        the refusal names both windows, because that is the difference
        between an actionable refusal and a complaint: the caller learns
        which window is stored and which its own ask computed.  The
        comparison is on the window alone — two asks that agree on *when*
        need not have agreed on *why*, and the stored premise stays the
        record's whatever the new card says, for the retry reason above.
        """
        stored = self._record_from_row(row, recorded=False)
        if stored.window.start_at == window.start_at and (
            stored.window.end_at == window.end_at
        ):
            return stored
        raise RunWindowConflictError(
            f"campaign {campaign!r} is already scheduled to run "
            f"{stored.window.start_at.isoformat()} to "
            f"{stored.window.end_at.isoformat()}, and this ask would "
            f"schedule it {window.start_at.isoformat()} to "
            f"{window.end_at.isoformat()}. One campaign is one run, and "
            "the row is the scheduling decision — a second scheduling "
            "naming a different window is two schedules wearing one "
            "campaign. Read the stored window with get(), or plan the "
            "next run under its own campaign id."
        )

    def _require_campaign(
        self, connection: sqlite3.Connection, campaign: str
    ) -> None:
        """Refuse to schedule a campaign the campaign table does not hold.

        The store schedules *runs of a campaign*, and a campaign is a
        planned row — feature 232's record, created before any node is
        expanded, is the row every reader of a campaign joins by id.  The
        probe is read-only (``sqlite_master``, then one ``SELECT`` by the
        table's own key), and the ``campaign`` table is **never created**
        here: it is ``0111``'s, and a store that invented it would be
        writing a schema it does not own — the probe-not-create
        discipline :mod:`discovery.campaign` follows for ``node``.

        An **absent** ``campaign`` table is the same refusal as an absent
        row, not a different one: it is a database where no campaign has
        ever been planned, so the id necessarily names nothing.  The
        wording differs so an operator reading it learns which repair
        applies — run the migrations, or plan the campaign.
        """
        if (
            connection.execute(_TABLE_EXISTS_SQL, (CAMPAIGN_TABLE,)).fetchone()
            is None
        ):
            raise UnknownCampaignError(
                f"the store at {self.path} holds no {CAMPAIGN_TABLE} "
                "table, so no campaign has ever been planned in it and "
                f"campaign {campaign!r} cannot have been either: a run's "
                "window is scheduled for a campaign feature 232's planner "
                "recorded first. Run the migrations, plan the campaign, "
                "then schedule its runs."
            )
        cursor = connection.execute(
            f"SELECT 1 FROM {CAMPAIGN_TABLE} "
            f"WHERE {CAMPAIGN_TABLE_ID_COLUMN} = ?",
            (campaign,),
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise UnknownCampaignError(
                f"there is no campaign {campaign!r} in the store at "
                f"{self.path}: a run's window is scheduled for a campaign "
                "feature 232's planner recorded before any node was "
                "expanded, and an id the campaign table does not hold "
                "names a run that will never happen. Plan the campaign, "
                "then schedule its runs."
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def schedule_depth_run(
    campaign_id: Any,
    pricing: Any,
    *,
    duration: timedelta,
    now: datetime | None = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ScheduledRun:
    """Schedule one campaign's depth runs — the module-level spelling.

    Feature 202's sentence as one call, for the caller that wants the act
    without holding a store: the campaign id, the card and the declared
    length in, the stored scheduled run out.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``; a deployment that names
    neither is refused *by name* rather than silently doing nothing,
    because a scheduling call that quietly skipped its write would leave
    the launcher waiting on a window nobody recorded — and the auditor
    re-verifying it against the card would find nothing to re-verify.

    A :class:`~providers.DepthScheduleError` from the store is left to
    propagate unwrapped: the refusal already names the campaign and the
    fact, and re-wrapping it here would put a second message in front of
    the one an operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise DepthScheduleError(
            "schedule_depth_run schedules a run's window and nothing names "
            f"a store: {DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the chosen window could not be recorded. "
            "Feature 202's record is a fact that must actually land in the "
            "table — a launcher that waited on a window nobody persisted "
            "would run a campaign no auditor could re-verify against the "
            "card it was scheduled on."
        )
    return DepthRunWindows(url).schedule(
        campaign_id, pricing, duration=duration, now=now
    )
