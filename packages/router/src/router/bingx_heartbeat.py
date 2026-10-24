"""Stage 2's heartbeat check: has the scheduled bot finished a slot lately?

``additions_spec_bingx_vst_alerts.xml``, "Telegram alerting for the scheduled
BingX VST bot", feature 3: *System checks the bot's heartbeat from*
``python -m router.bingx_heartbeat --max-age-hours 5``.  It reads the newest
slot completion that feature 2 recorded (in
:data:`router.bingx_rebalance.ROUTER_SLOT_COMPLETION_TABLE`, through
:meth:`router.bingx_rebalance.RouterSlotCompletionStore.newest`).  When there
is none, or the newest is older than the limit, it sends an urgent alert
naming the last slot and its age, and exits 1.  Otherwise it sends nothing and
exits 0.  While a stale slot's stall persists, the alert is repeated every
:data:`REALERT_HOURS` hours, so a bot that is quiet for days keeps being
reported.

**The rebalance timer is the thing that goes quiet, and this is what notices.**
A slot that runs — however badly, exit 0, 1 or 3 — appends a completion; a
machine that is off, a timer that was never enabled, a `run.sh` whose `op`
step now fails: none of those append anything, and every one of feature 2's
per-slot alerts is silent about them, because silence is the absence of a
slot.  The heartbeat is the complement: it reads the *record*, not the slot,
and its one alarm is that no completion has landed within
:data:`DEFAULT_MAX_AGE_HOURS` hours.  The measure is the completion's own
``finished_at`` — when the slot *finished* — so a slow slot still counts as
alive while it runs.

**Stale is an exit code; the alert is a separate, rate-limited act.**  The
sentence ties exit 1 to the staleness itself (*"sends an urgent alert … and
exits 1"*), and dedupes only the *alert* (*"At most one heartbeat alert is
sent per stale slot"*).  So an hourly check that finds the same stale slot
again still exits 1 — the bot is still stale, and that is the truth the
systemd timer's own unit state should carry.  When a *different* slot
finishes and then goes stale, the key changes and the alert fires again.

**The dedupe is a window, not a tombstone.**  A stall that outlives one
recovery window is news again: once the marker for a stale slot is older than
:data:`REALERT_HOURS` — twelve hours, three missed rebalances — the same slot
pages once more, and the marker's instant is pushed forward so the next quiet
window starts from this alert.  One alert per stale slot *ever* paged exactly
once about a slot that then never changed; the venue deadlock recorded in
``docs/preregistration/2026-10-15-shadow-v1.ADDENDUM.md`` Addenda 9 and 10 is
that shape — the newest completion stayed at ``2026-10-22T00:00`` while every
later slot was refused, so the operator was told once, 28 hours before the
second addendum was written, and never again.  Twelve hours is chosen the way
:data:`DEFAULT_MAX_AGE_HOURS` is: three slots, long enough that a
slow-but-working bot is not paged in quick succession and short enough that
an operator who slept is told again in the morning.  A delivery that failed
still leaves no mark, so an unconfigured or refused phone retries on *every*
hourly check — the window governs repeat alerts, never whether the first one
is retried.

**The dedupe lives in the store, not in memory.**  A marker row is appended
to this module's own :data:`ROUTER_HEARTBEAT_ALERT_TABLE` in the same
``DATABASE_URL`` store the completions live in, so the process that sent the
alert and the process that runs an hour later — a *different* systemd
oneshot, a different interpreter — agree on what has been reported.  The
marker is written only when Telegram answered ``ok``: a delivery that failed
leaves no mark, so the next check tries again rather than letting a dropped
message become permanent silence.

**Alerting never changes the verdict, and a fault is one log line.**  A
transport error, a raised alert, a bookkeeping fault — each is caught and
logged, and the exit code stays the one the staleness itself earned.  The
sentence's own stance for feature 2 (a slot's orders, summary line and exit
code are identical whether alerting succeeds, fails or is unconfigured)
applies here too: a phone that cannot be reached must not turn a healthy bot
into a green check, nor a stale one into a fault of the checker.  Only the
*ask* being unanswerable — no ``DATABASE_URL`` to read, a limit that is not a
positive number — is a typed :class:`RouterBingXHeartbeatError`, printed to
stderr and answered with exit 1.

**The verdict itself is printed, not just acted on.**  As soon as the check
reaches a judgement — :data:`VERDICT_FRESH`, :data:`VERDICT_STALE` or
:data:`VERDICT_ABSENT` — it writes one JSON line to stdout naming the
verdict, the newest completion's slot (or ``null`` when absent), the age in
hours (or ``null`` when absent), the ``--max-age-hours`` limit in force and
an ``"alert"`` field.  It does this before the alert is even attempted, so
the line appears whether or not Telegram is configured, whether the alert is
deduped, delivered, refused or raises: an operator running the command by
hand always learns the bot's state, not just whatever the exit code and an
unconfigured phone leave them to guess.  A refusal of the *ask* itself prints
no such line — there is no verdict to report when the check could not run at
all.

**What happened to the message is on the line too.**  The ``"alert"`` field
carries :data:`ALERT_SENT` for a first alert, :data:`ALERT_RESENT` for a
repeat past the window, :data:`ALERT_DEDUPED` when the window still holds,
:data:`ALERT_NOT_CONFIGURED` for a phone with no credential and
:data:`ALERT_FAILED` for a venue refusal — the question the verdict alone
cannot answer, and the one that matters most precisely when the exit code and
the verdict are already known.  It is settled *before* the line is printed,
which costs nothing: the alert attempt catches every fault it can raise, so
the line is never withheld because a phone could not be reached.

``deploy/systemd/`` holds the oneshot service that runs one check, carrying
the rebalance service's own environment (``PATH``, and the token read from
``%h/.config/op/service-token``), and the timer that fires it hourly at
minute 35 with ``Persistent=true``.  Writing those units is this feature's
deliverable; enabling them is an operator step, and nothing here installs or
starts anything.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bingx_alert import BOT_TOKEN_ENV, CHAT_ID_ENV, URGENT, scrub_bot_path, send_alert
from .bingx_rebalance import RouterSlotCompletionStore, SlotCompletion
from .bingx_risk import DATABASE_URL_ENV
from .errors import RouterError

__all__ = [
    "ALERT_DEDUPED",
    "ALERT_FAILED",
    "ALERT_NONE",
    "ALERT_NOT_CONFIGURED",
    "ALERT_RESENT",
    "ALERT_SENT",
    "BINGX_HEARTBEAT_CODE",
    "DEFAULT_MAX_AGE_HOURS",
    "EXIT_OK",
    "EXIT_STALE",
    "NO_COMPLETION_KEY",
    "REALERT_HOURS",
    "ROUTER_HEARTBEAT_ALERT_TABLE",
    "VERDICT_ABSENT",
    "VERDICT_FRESH",
    "VERDICT_STALE",
    "RouterBingXHeartbeatError",
    "RouterHeartbeatAlertStore",
    "main",
]

#: The greppable token this module's own faults open with — no store named, a
#: limit that is not a positive number.  Coined on the module's own name, the
#: convention :data:`router.bingx_mirror.MIRROR_CODE` states and every Stage 2
#: module repeats: an operator greps one word and lands on the module that
#: refused.
BINGX_HEARTBEAT_CODE = "bingx_heartbeat"

#: The spec's own *"--max-age-hours 5"*: how long a bot may go without
#: finishing a slot before the heartbeat calls it stale.  One 4-hour slot plus
#: an hour of slack for a slow slot, spelled once so the command, the unit and
#: the suite cannot disagree.
DEFAULT_MAX_AGE_HOURS = 5

#: The two exits the spec's sentence names: 0 when the newest completion is
#: fresh (nothing sent), 1 when it is stale or absent (the urgent alert, once
#: per stale slot per :data:`REALERT_HOURS`).
EXIT_OK = 0
EXIT_STALE = 1

#: How long one stale slot stays quiet after an alert: twelve hours, three
#: missed rebalances.  The original rule — one alert per stale slot, ever —
#: paged exactly once about a slot that did not change while the bot stayed
#: dead, which is the shape of the venue deadlock in the shadow-v1 addenda
#: (Addenda 9 and 10): the newest completion sat at ``2026-10-22T00:00``
#: while six slots were refused, and the operator heard about it once, 28
#: hours before the second addendum was written.  A window keeps the hourly
#: check from repeating itself, but makes a stall that persists for days keep
#: being reported.  Twelve is chosen as :data:`DEFAULT_MAX_AGE_HOURS` is:
#: three slots, long enough that a slow-but-working bot is not paged in quick
#: succession, short enough that an operator who slept is told again.
REALERT_HOURS = 12

#: The dedupe key used when the store holds *no* completion at all.  Distinct
#: from every real slot key, so a bot that has never finished anything alerts
#: and then stays quiet for one window, like any other stale condition.
NO_COMPLETION_KEY = "no-completion"

#: The three verdicts the one stdout line can carry — the judgement the
#: heartbeat reached about the bot, independent of whether an alert for it
#: could be delivered.
VERDICT_FRESH = "fresh"
VERDICT_STALE = "stale"
VERDICT_ABSENT = "absent"

#: The vocabulary the stdout line's own ``"alert"`` field carries — what
#: happened to the *alert*, beside the verdict about the bot.  ``sent`` is a
#: first alert for this stale key, ``resent`` a repeat past
#: :data:`REALERT_HOURS`, ``deduped`` a marker inside the window,
#: ``not_configured`` a phone that cannot be reached and ``failed`` a delivery
#: Telegram refused.  A caller reads the verdict to learn about the bot and
#: this field to learn whether anyone was told.
ALERT_SENT = "sent"
ALERT_RESENT = "resent"
ALERT_DEDUPED = "deduped"
ALERT_NOT_CONFIGURED = "not_configured"
ALERT_FAILED = "failed"
ALERT_NONE = "none"

#: The table this module's own alert dedupe lands in — a marker per stale slot
#: reported, in the same ``DATABASE_URL`` store as the completions, so a check
#: an hour later (a different process) reads what this one wrote.
ROUTER_HEARTBEAT_ALERT_TABLE = "router_bingx_heartbeat_alert"

#: The dedupe table's DDL, created idempotently beside the code that reads it —
#: the discipline every store in this workspace follows.  ``UNIQUE`` on the key
#: keeps one row per stale slot: a re-alert after :data:`REALERT_HOURS` *updates*
#: that row's ``alerted_at`` rather than appending a second, so an operator
#: inspecting the table reads when each stale slot was last reported, and the
#: row count is *stale slots reported*, not *alerts sent*.
_HEARTBEAT_ALERT_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {ROUTER_HEARTBEAT_ALERT_TABLE} (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    stale_key  TEXT NOT NULL UNIQUE,  -- the stale slot (book_id:slot) or no-completion
    alerted_at TEXT NOT NULL          -- when this key was last reported, ISO 8601 UTC
);
"""

#: The module's logger.  One line per best-effort fault — a store that could
#: not answer, an alert that raised, a marker that could not be written —
#: carrying the greppable module code, and never a token.
log = logging.getLogger("router.bingx_heartbeat")


class RouterBingXHeartbeatError(RouterError):
    """A heartbeat check this command cannot run.

    Raised for a fault of the *ask* — no ``DATABASE_URL`` to read the
    completions from, a ``--max-age-hours`` that is not a positive number,
    an injectable ``now`` that is not callable — never for the bot's own
    staleness: a stale bot is feature 3's *outcome* (exit 1 and an urgent
    alert), not a fault of the checker.  Every message opens with
    :data:`BINGX_HEARTBEAT_CODE` and names the one repair.
    """


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`router.bingx_rebalance` and
    :mod:`router.bingx_risk` each restate in their own words, for the reason
    each of them does: a store reaches into no sibling's private helper.  The
    heartbeat writes its dedupe marker into the *same* store feature 2 writes
    completions to, so it speaks the same address and refuses any other
    scheme in this module's own vocabulary.
    """

    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterBingXHeartbeatError(
            f"{BINGX_HEARTBEAT_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: the heartbeat reads the slot completions and "
            "writes its dedupe marker in the sqlite store the bot uses "
            "(sqlite:///), and an address this module cannot speak holds no "
            "record to check"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterBingXHeartbeatError(
            f"{BINGX_HEARTBEAT_CODE}: sqlite {DATABASE_URL_ENV} must not carry "
            f"a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RouterBingXHeartbeatError(
            f"{BINGX_HEARTBEAT_CODE}: sqlite {DATABASE_URL_ENV} carries no "
            "database path: an in-memory store would die with the connection "
            "that opened it, and a heartbeat whose dedupe vanished would page "
            "the operator every single hour"
        )
    return Path(path)


def _utc_text(moment: datetime) -> str:
    """The table's one canonical moment spelling: aware, UTC, ISO 8601."""

    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: Any, what: str) -> datetime:
    """An aware instant, or a refusal naming the field it was read from."""

    if not isinstance(moment, datetime) or (
        moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None
    ):
        raise RouterBingXHeartbeatError(
            f"{BINGX_HEARTBEAT_CODE}: {what} is an aware instant, got "
            f"{moment!r}; the dedupe marker records when an alert went out, "
            "and an instant that names no timezone names no moment"
        )
    return moment


def _resolve_database_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str | None:
    """The store's address from the argument, else ``DATABASE_URL``."""

    if database_url is not None:
        return database_url.strip() or None
    source = os.environ if env is None else env
    return source.get(DATABASE_URL_ENV, "").strip() or None


class RouterHeartbeatAlertStore:
    """Holds and answers this module's own per-stale-slot alert markers.

    Bound to the same database URL as feature 2's completion store at
    construction; construction performs no I/O, so composing a caller never
    touches the database.  Each operation opens its own connection, creating
    the schema idempotently if absent — the discipline every store in this
    workspace follows, which is what lets an hourly check in a *different*
    process see the marker the previous check wrote.

    Two faces, one table: :meth:`already_alerted` asks whether a stale slot
    was reported *recently*, and :meth:`mark_alerted` records the report,
    moving an existing row's instant rather than adding one.  The mark is
    written only after Telegram answered ``ok``, so the table states what the
    operator was *told*, not merely what the checker attempted.

    *Recently* is :data:`REALERT_HOURS`: a key marked longer ago than that
    answers ``False``, so the same unchanged stale slot is reported again
    rather than silting up an operator's phone once and then going quiet for
    days.  The window is the only reading the table supports — there is no
    "has this ever been alerted" question, because answering it is what made
    a persistent stall a single page.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterBingXHeartbeatError(
                f"{BINGX_HEARTBEAT_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL; the heartbeat's dedupe marker lives "
                "in the store it names, and an address that states nothing "
                "names no store to record in"
            )
        self._database_url = database_url.strip()

    @property
    def database_url(self) -> str:
        """The database URL this table's markers stand in."""
        return self._database_url

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_HEARTBEAT_ALERT_SCHEMA)
        return connection

    def ensure_schema(self) -> None:
        """Bring the dedupe table to shape, idempotently.

        Public so a test seeding a marker can prepare the table without
        reaching for the private :meth:`_connect` — the same door
        :class:`router.bingx_rebalance.RouterSlotCompletionStore` leaves
        open, for the same reason.
        """

        self._connect().close()

    def last_alerted_at(self, stale_key: str) -> datetime | None:
        """When ``stale_key`` was last reported, or ``None`` if never.

        The one read of the marker table, and the shape both questions below
        need: the *window* question is this instant compared against a clock,
        and the *first-or-repeat* question is whether this is ``None`` at all.
        A key never alerted answers ``None``; a marker whose text is not an
        aware instant — a row this store did not write — is refused by name
        rather than silently treated as unalerted, because reading it as
        "never reported" would page an operator about a delivery that did
        happen.
        """

        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT alerted_at FROM {ROUTER_HEARTBEAT_ALERT_TABLE} "
                "WHERE stale_key = ? LIMIT 1",
                (stale_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            moment = datetime.fromisoformat(row[0])
        except (TypeError, ValueError) as exc:
            raise RouterBingXHeartbeatError(
                f"{BINGX_HEARTBEAT_CODE}: the marker for {stale_key!r} carries "
                f"{row[0]!r} as its alert instant, which is not an ISO 8601 "
                "moment; the window that decides whether a stale slot is "
                "reported again is measured from it"
            ) from exc
        return _require_aware(moment, f"the marker for {stale_key!r}")

    def already_alerted(self, stale_key: str, *, now: datetime) -> bool:
        """Whether ``stale_key`` was alerted *within* :data:`REALERT_HOURS` of ``now``.

        ``True`` iff a marker row exists whose ``alerted_at`` is no older than
        the re-alert window, so the caller stays silent on a repeated hourly
        check rather than paging the operator about a slot they were just told
        about — while a slot whose last report is older than the window
        answers ``False`` and is reported again, which is what keeps a stall
        that lasts for days from producing a single page.

        The comparison is made in the store, against the marker's own stored
        instant: the caller supplies its clock and the row supplies the last
        report, and neither has to agree with the other's process.  A row
        whose instant is the window's own boundary counts as *within* it, the
        same inclusive reading :func:`main` gives the staleness limit.
        """

        _require_aware(now, "now")
        last = self.last_alerted_at(stale_key)
        return last is not None and last >= now - timedelta(hours=REALERT_HOURS)

    def mark_alerted(self, stale_key: str, *, alerted_at: datetime) -> None:
        """Record that an alert for ``stale_key`` was delivered now.

        An upsert against the table's ``UNIQUE`` key: the first alert for a
        stale slot inserts the row, and a re-alert past :data:`REALERT_HOURS`
        moves its ``alerted_at`` to the new report rather than adding a second
        row.  So the row always names when this stale slot was *last*
        reported — the window the next check measures from — and an operator
        counting rows counts stale conditions, not pages.
        """

        if not isinstance(stale_key, str) or not stale_key.strip():
            raise RouterBingXHeartbeatError(
                f"{BINGX_HEARTBEAT_CODE}: a heartbeat alert names the stale "
                f"slot it reports, got {stale_key!r}"
            )
        _require_aware(alerted_at, "alerted_at")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {ROUTER_HEARTBEAT_ALERT_TABLE} "
                "(stale_key, alerted_at) VALUES (?, ?) "
                "ON CONFLICT(stale_key) DO UPDATE SET alerted_at = excluded.alerted_at",
                (stale_key.strip(), _utc_text(alerted_at)),
            )


def _alert_once(
    stale_key: str,
    text: str,
    *,
    alert_store: Any,
    sender: Callable[..., bool],
    moment: datetime,
    env: Mapping[str, str] | None,
    transport: Any,
) -> str:
    """Attempt the one alert this check is allowed, and answer what happened.

    The whole best-effort step, in the order it must happen: ask the marker
    store whether this stale key was reported inside :data:`REALERT_HOURS`,
    send when it was not, and record the send once Telegram answered ``ok``.
    A send that is not confirmed leaves no mark, so the next hourly check
    retries regardless of the window — a window that also swallowed failed
    deliveries would let one lost page become permanent silence.

    The answer is the vocabulary the verdict line's ``"alert"`` field carries:
    :data:`ALERT_DEDUPED` when the marker was inside the window,
    :data:`ALERT_RESENT` when it was outside — a repeat of a stall that has
    persisted — :data:`ALERT_SENT` for a first alert, and
    :data:`ALERT_NOT_CONFIGURED` or :data:`ALERT_FAILED` when the sender
    answered ``False``, which :mod:`router.bingx_alert` distinguishes by
    logging either the missing variable or the venue's own refusal.  ``False``
    is the only thing the sender returns for *any* non-delivery, so this
    function resolves the two cases the way an operator would: by whether the
    credential environment names both of feature 1's variables.  Nothing here
    raises: each fault is caught and logged, and a store that cannot answer
    the dedupe question makes the alert be *sent*, never skipped.
    """

    try:
        already = alert_store.already_alerted(stale_key, now=moment)
    except Exception as exc:  # noqa: BLE001 - a fault is one log line
        log.warning(
            "%s: could not tell whether %s was already alerted (%s); "
            "sending the alert anyway",
            BINGX_HEARTBEAT_CODE,
            stale_key,
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )
        already = False
    if already:
        return ALERT_DEDUPED

    try:
        delivered = sender(URGENT, text, env=env, transport=transport)
    except Exception as exc:  # noqa: BLE001 - the alert never changes the verdict
        log.warning(
            "%s: the heartbeat alert for %s raised and was caught (%s)",
            BINGX_HEARTBEAT_CODE,
            stale_key,
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )
        return ALERT_FAILED

    if not delivered:
        return ALERT_NOT_CONFIGURED if _unconfigured(env) else ALERT_FAILED

    # Whether this is a first report or a repeat is read *before* the write
    # below: the upsert moves the row's instant, so afterwards every key looks
    # as though it had been reported.
    reported_before = _reported_before(alert_store, stale_key)

    # Only a delivered alert is recorded: a dropped message leaves no mark, so
    # the next check tries again rather than letting one lost page become
    # permanent silence.
    try:
        alert_store.mark_alerted(stale_key, alerted_at=moment)
    except Exception as exc:  # noqa: BLE001 - the alert already left
        log.warning(
            "%s: the alert for %s was delivered but its marker could not be "
            "written (%s)",
            BINGX_HEARTBEAT_CODE,
            stale_key,
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )
    return ALERT_RESENT if reported_before else ALERT_SENT


def _unconfigured(env: Mapping[str, str] | None) -> bool:
    """Whether feature 1's credential environment is missing a required value.

    ``send_alert`` answers ``False`` both for a phone that is not configured
    and for a delivery Telegram refused, and logs the difference.  The verdict
    line has to carry it too, so this repeats the one question the sender's own
    :func:`router.bingx_alert._credentials` asks — a non-empty Bot API token
    and chat id — reading the same environment the sender was handed.
    """

    source = os.environ if env is None else env
    return not (
        (source.get(BOT_TOKEN_ENV) or "").strip()
        and (source.get(CHAT_ID_ENV) or "").strip()
    )


def _reported_before(alert_store: Any, stale_key: str) -> bool:
    """Whether ``stale_key`` already had a marker when this alert was sent.

    A re-alert is a *repeat*: the key was reported earlier, the window ran
    out, and the operator is being told again.  A first alert is the same key
    with no marker at all.  The distinction is the store's own record, asked
    of :meth:`RouterHeartbeatAlertStore.last_alerted_at` before the write this
    attempt is about to make — after it, every key looks reported, because the
    row's instant no longer says whether it was there beforehand.

    A store that cannot answer is treated as holding no marker: the message
    has already left by the time this is asked, so a bookkeeping fault may
    only cost the stdout vocabulary a word, never the alert.
    """

    try:
        return alert_store.last_alerted_at(stale_key) is not None
    except Exception as exc:  # noqa: BLE001 - the vocabulary never breaks a check
        log.warning(
            "%s: could not tell whether %s had been alerted before (%s); "
            "reporting it as a first alert",
            BINGX_HEARTBEAT_CODE,
            stale_key,
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )
        return False


def _stale_key(completion: SlotCompletion) -> str:
    """The dedupe key for one stale completion: the book and the slot.

    Keying on the *slot* rather than on ``finished_at`` is deliberate: a
    re-run inside one slot appends a second completion with the same slot and
    a later finish, and the operator must not be paged again merely because
    the same dead slot was re-recorded.  The book id is folded in so two books
    sharing a store do not silence each other.
    """

    return f"{completion.book_id}:{completion.slot.isoformat()}"


def _age_text(age: timedelta) -> str:
    """An age in hours, to one decimal — the shape the sentence names."""

    return f"{age.total_seconds() / 3600.0:.1f} hours"


def _timer_command() -> str:
    """The one repair the heartbeat's body offers, the same in every case."""

    return "systemctl --user status nullius-vst-rebalance.timer"


def _stale_alert_text(
    completion: SlotCompletion, age: timedelta, max_age_hours: float
) -> str:
    """The urgent body for a stale completion: the last slot and its age.

    The sentence's own requirement — *naming the last slot and its age* — the
    slot's ``slot`` start, the book, the exit it finished on, the instant it
    finished and the age measured from it, so an operator reading the phone
    knows exactly which slot went quiet and by how much.
    """

    return (
        f"The scheduled BingX VST bot has not finished a slot within the "
        f"{max_age_hours:g} hour heartbeat limit.\n"
        f"The newest slot completion: {completion.slot.isoformat()} "
        f"(book {completion.book_id}, exit {completion.exit_code}), finished "
        f"at {completion.finished_at.isoformat()} — {_age_text(age)} ago.\n"
        f"Read the timer with: {_timer_command()}"
    )


def _print_verdict(
    verdict: str,
    *,
    newest_slot: datetime | None,
    age_hours: float | None,
    max_age_hours: float,
    alert: str = ALERT_NONE,
) -> None:
    """The one line of stdout every reachable verdict prints.

    Whether or not the alert could be delivered, an operator running the
    command by hand learns the bot's state from this line alone — no Telegram
    configuration required to read it.  One JSON object, one line, so it is
    both human-legible and machine-parseable without a flag.

    ``alert`` carries what happened to the message beside the judgement about
    the bot — see :data:`ALERT_SENT` and its siblings.  A verdict with no
    alert to speak of (fresh) leaves it ``"none"``, and the check's alert
    attempt catches every fault, so printing this after that attempt costs the
    line nothing on the paths where the phone is unreachable.
    """

    print(
        json.dumps(
            {
                "verdict": verdict,
                "newest_slot": (
                    newest_slot.isoformat() if newest_slot is not None else None
                ),
                "age_hours": age_hours,
                "max_age_hours": float(max_age_hours),
                "alert": alert,
            }
        )
    )


def _missing_alert_text(max_age_hours: float) -> str:
    """The urgent body when the store holds no completion at all.

    There is no last slot to name — nothing has ever finished — so the body
    says exactly that, rather than inventing a slot or a zero age.  It is the
    same alarm as a stale one: the bot has produced nothing the operator can
    see within the limit.
    """

    return (
        "The scheduled BingX VST bot has never recorded a finished slot.\n"
        f"No slot completion is in the store, so nothing has run within the "
        f"{max_age_hours:g} hour heartbeat limit.\n"
        f"Read the timer with: {_timer_command()}"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Any = None,
    env: Mapping[str, str] | None = None,
    database_url: str | None = None,
    now: Callable[[], datetime] | None = None,
    completion_store: Any = None,
    alert_store: Any = None,
    alert: Callable[..., bool] | None = None,
) -> int:
    """One heartbeat check: ``python -m router.bingx_heartbeat --max-age-hours 5``.

    Reads the newest slot completion feature 2 recorded and judges its age
    against ``--max-age-hours``.  When there is none, or the newest finished
    longer ago than the limit, it sends one :data:`router.bingx_alert.URGENT`
    alert naming the last slot and its age and returns :data:`EXIT_STALE`
    (1); otherwise it sends nothing and returns :data:`EXIT_OK` (0).  One
    alert is sent per stale slot per *window*: a marker in this module's own
    table suppresses the repeat until it is older than :data:`REALERT_HOURS`,
    at which point the same unchanged stale slot pages again — so a bot that
    is quiet for days keeps being reported — while the exit code stays 1 for
    as long as the bot is stale.

    Every delivery or bookkeeping fault is caught and logged — the exit code
    is the staleness's own — so a heartbeat whose alert cannot leave still
    reports the truth about the bot.  The seams — ``transport``, ``env``,
    ``database_url``, ``now``, ``completion_store``, ``alert_store`` and
    ``alert`` — are injectable so the suite drives the command against
    recording doubles with no socket and no real credential; a caller that
    injects nothing gets feature 2's real completion store, this module's
    real marker store, and feature 1's real sender built from the environment.

    Once the verdict is reached — and, on the stale and absent paths, once the
    alert's own attempt has settled — one JSON line goes to stdout naming the
    verdict (``"fresh"``, ``"stale"`` or ``"absent"``), ``newest_slot`` (or
    ``null``), ``age_hours`` (or ``null``), ``max_age_hours`` and ``"alert"``
    (:data:`ALERT_NONE` when there was nothing to send, else what became of
    the message).  The attempt is made first and catches every fault, so this
    happens whether or not Telegram is configured, deduped, delivered or
    refused, and an operator running the command by hand learns both the
    bot's state and whether anyone was told, from stdout alone.  A refusal of
    the *ask* prints no such line — there is no verdict when the check could
    not run at all.
    """

    parser = argparse.ArgumentParser(
        prog="python -m router.bingx_heartbeat",
        description=(
            "Check the scheduled BingX VST bot's heartbeat: read the newest "
            "slot completion and send an urgent Telegram alert (once per "
            "stale slot per 12 hours) when none has finished within "
            "--max-age-hours. Exit 0 when the bot is fresh, 1 when it is "
            "stale or absent."
        ),
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help=(
            "how long the bot may go without finishing a slot before it is "
            f"stale (default {DEFAULT_MAX_AGE_HOURS})"
        ),
    )
    arguments = parser.parse_args(argv)
    max_age_hours = arguments.max_age_hours

    try:
        if max_age_hours <= 0:
            raise RouterBingXHeartbeatError(
                f"{BINGX_HEARTBEAT_CODE}: --max-age-hours must be a positive "
                f"number of hours, got {max_age_hours!r}; a non-positive "
                "limit would call a bot that just finished a slot stale"
            )
        url = _resolve_database_url(database_url, env)
        if url is None:
            raise RouterBingXHeartbeatError(
                f"{DATABASE_URL_ENV} is not set, so the heartbeat has no store "
                "to read the slot completions from; set it to the sqlite "
                "database the rebalance writes its completions to and run "
                "again"
            )
        if now is not None and not callable(now):
            raise RouterBingXHeartbeatError(
                f"{BINGX_HEARTBEAT_CODE}: now must be callable answering the "
                f"check's moment, got {now!r} ({type(now).__name__})"
            )
        moment_fn = now if now is not None else (lambda: datetime.now(UTC))
        moment = moment_fn()

        if completion_store is None:
            completion_store = RouterSlotCompletionStore(url)
        if alert_store is None:
            alert_store = RouterHeartbeatAlertStore(url)
        sender = alert if alert is not None else send_alert

        newest = completion_store.newest()
        if newest is None:
            stale_key = NO_COMPLETION_KEY
            text = _missing_alert_text(max_age_hours)
            verdict = VERDICT_ABSENT
            judged_slot: datetime | None = None
            judged_age: float | None = None
        else:
            age = moment - newest.finished_at
            judged_age = age.total_seconds() / 3600.0
            if age <= timedelta(hours=max_age_hours):
                _print_verdict(
                    VERDICT_FRESH,
                    newest_slot=newest.slot,
                    age_hours=judged_age,
                    max_age_hours=max_age_hours,
                )
                return EXIT_OK
            stale_key = _stale_key(newest)
            text = _stale_alert_text(newest, age, max_age_hours)
            verdict = VERDICT_STALE
            judged_slot = newest.slot

        # One line, printed once the alert's own outcome is known: the verdict
        # names the bot's state and "alert" names what became of the message.
        # The attempt cannot raise — every step inside it is caught — so an
        # unconfigured, refused or faulting phone can never suppress the line.
        outcome = _alert_once(
            stale_key,
            text,
            alert_store=alert_store,
            sender=sender,
            moment=moment,
            env=env,
            transport=transport,
        )
        _print_verdict(
            verdict,
            newest_slot=judged_slot,
            age_hours=judged_age,
            max_age_hours=max_age_hours,
            alert=outcome,
        )
        return EXIT_STALE
    except RouterError as exc:
        message = str(exc)
        prefix = f"{BINGX_HEARTBEAT_CODE}: "
        if not message.startswith(prefix):
            message = prefix + message
        print(message, file=sys.stderr)
        return EXIT_STALE


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
