"""Stage 2's Telegram alert: one message, one level, best-effort.

``additions_spec_bingx_vst_alerts.xml``, "Telegram alerting for the scheduled
BingX VST bot", feature 1: *System sends one Telegram alert with a level of
urgent, warning or info through* ``POST
https://api.telegram.org/bot<token>/sendMessage``*, using* ``TELEGRAM_BOT_TOKEN``
*and* ``TELEGRAM_CHAT_ID``.  The message opens with the level and "nullius VST";
an info alert is sent with ``disable_notification`` true; it reaches only
``api.telegram.org`` through a host guard, and returns ``True`` when Telegram
answers ``ok``.  On a missing variable, a transport error, a timeout of 10
seconds or an ``ok:false`` answer, it returns ``False`` and logs one line naming
the failure.  The token never appears in that line, a repr, an exception or
stdout: the bot path is scrubbed from every URL.  ``python -m
router.bingx_alert --test`` sends an info test message and exits 0 on delivery,
1 otherwise; ``python -m router.bingx_alert --unit NAME --event failure`` sends
an urgent "slot could not run" alert naming the unit and the journalctl command
to read it.

**Alerting is best-effort, and that is the whole stance.**  Every failure the
feature names — no token, no chat id, a dead socket, a timeout, Telegram
answering ``ok:false`` — is the *same* outcome: :func:`send_alert` returns
``False`` and writes exactly one log line naming what went wrong.  It never
raises for a delivery fault, because the caller is a rebalance slot whose
outcome must not depend on whether the operator's phone is reachable (feature
2's constraint: a slot's orders, summary line and exit code are identical
whether alerting succeeds, fails or is unconfigured).  A *programming* fault —
an unknown level, a URL whose host is not the venue — is a typed
:class:`RouterBingXAlertError` in this member's vocabulary, raised before any
message is built, so a bug is not silently reported as "Telegram was down".

**The token lives in the URL path, and is scrubbed out of every rendering.**
The Bot API's own shape is ``/bot<token>/sendMessage``, so the secret is not a
header or a body field but a *path segment* of the URL — which means any URL
that reaches a log line, an exception message or a ``repr`` carries the secret
unless it is removed first.  :func:`scrub_bot_path` is that removal: one regular
expression replacing every ``/bot<token>`` path segment with ``/bot<redacted>``,
applied to the transport's own error text, to Telegram's ``description`` and to
anything this module logs.  The transport is still handed the *real* URL (it
must be, or nothing is delivered); it is every *rendering* of that URL that is
scrubbed, which is what the feature's sentence means by *"the bot path is
scrubbed from every URL"*.

**The host guard is structural, the transport is injected.**  The URL is built
from :data:`TELEGRAM_API_ORIGIN`, a module constant naming the one host the
message may reach, and :func:`_guard` refuses any other before the transport is
called — so no flag, setting or environment variable can point an alert
somewhere else.  The transport is a callable ``(method, url, headers, body) ->
(status, body)``, the same contract :mod:`router.bingx_client` uses; the default
is a :mod:`urllib.request` transport with a 10-second timeout, and the suite
passes a recorder, which is what makes *"no test opens a network connection"*
enforceable.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence

from .bingx_client import make_urllib_transport
from .errors import RouterError

__all__ = [
    "ALERT_LEVELS",
    "BINGX_ALERT_CODE",
    "BOT_TOKEN_ENV",
    "CHAT_ID_ENV",
    "DEFAULT_TIMEOUT_SECONDS",
    "EVENT_FAILURE",
    "INFO",
    "SEND_MESSAGE_PATH",
    "TELEGRAM_API_HOST",
    "TELEGRAM_API_ORIGIN",
    "URGENT",
    "WARNING",
    "RouterBingXAlertError",
    "main",
    "scrub_bot_path",
    "send_alert",
]

#: The greppable token this module's own faults open with — an unknown level, a
#: URL whose host is not the venue.  Coined on the module's own name, the
#: convention :data:`router.bingx_mirror.MIRROR_CODE` states and every Stage 2
#: module repeats: an operator greps one word and lands on the module that
#: refused.
BINGX_ALERT_CODE = "bingx_alert"

#: The three levels the spec's sentence names.  Spelled once so the sender, the
#: command and every caller cannot disagree about which word means what.
URGENT = "urgent"
WARNING = "warning"
INFO = "info"
ALERT_LEVELS = (URGENT, WARNING, INFO)

#: The environment variables the Bot API credentials are read from.  A missing
#: one is an *unconfigured* alert rather than a fault: the sender logs the
#: variable's *name* — never its value — and returns ``False``.
BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

#: The one host an alert may reach.  The URL is assembled under this name and
#: :func:`_guard` refuses any other before the transport is called, so a
#: deployment cannot point the alert at a second host.
TELEGRAM_API_HOST = "api.telegram.org"
TELEGRAM_API_ORIGIN = f"https://{TELEGRAM_API_HOST}"

#: The Bot API endpoint, relative to ``/bot<token>``.  ``POST`` is the only
#: method the Bot API documents for a send.
SEND_MESSAGE_PATH = "/sendMessage"

#: The spec's own *"a timeout of 10 seconds"*, spelled once so the sender and
#: its suite cannot disagree about the budget.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: The one ``--event`` this command understands today: the systemd ``OnFailure``
#: hook that fires when a scheduled slot could not run at all.
EVENT_FAILURE = "failure"

#: The prefix every message opens with, after the level.  The spec's *"The
#: message opens with the level and 'nullius VST'"*.
BOT_NAME = "nullius VST"

#: The bot-path scrubber.  One pattern, applied to every rendering of a URL:
#: ``/bot<token>`` becomes ``/bot<redacted>``.  A path segment is terminated by
#: a slash, whitespace, a quote or the end of the string, so the token — which
#: the Bot API spells as ``<numeric id>:<secret>`` — is removed whole and the
#: surviving text stays readable and greppable.
_BOT_PATH = re.compile(r"/bot[^/\s\"'<>]+")

#: The module's logger.  One line per failure, at warning level, naming the
#: failure — and never the token.
log = logging.getLogger("router.bingx_alert")


class RouterBingXAlertError(RouterError):
    """A fault in *this* module's own contract, not a delivery failure.

    The spec gives the delivery outcomes — a missing variable, a transport
    error, a timeout, an ``ok:false`` answer — one behaviour: return ``False``
    and log one line.  This error is the other category: an unknown level, or a
    request URL addressed somewhere other than :data:`TELEGRAM_API_HOST`.  Both
    are programming faults that the caller must *see* rather than have reported
    as "the operator's phone was unreachable", so they are raised in this
    member's vocabulary and caught by the same ``except RouterError`` a caller
    already holds.  :attr:`code` carries the greppable
    :data:`BINGX_ALERT_CODE`-prefixed token the message opens with.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def scrub_bot_path(text: str) -> str:
    """Replace every ``/bot<token>`` path segment of ``text`` with a placeholder.

    The Bot API carries the token in the URL's path, so a URL that reaches a
    log line, an exception message or a ``repr`` carries the secret with it
    unless it is removed first.  This is the one removal: a pure string
    function, applied to the transport's own error text and to anything this
    module logs or renders.  It is exported because the suite asserts against
    it directly — *"the token never appears in any repository file, test
    fixture, log line, exception message, repr or stdout"* — and a caller
    holding a URL of its own should be able to scrub it the same way.
    """
    return _BOT_PATH.sub("/bot<redacted>", text)


def _guard(url: str) -> str:
    """Refuse any URL whose host is not the Bot API — before any send.

    The guard is the whole of *"It reaches only api.telegram.org through a
    host guard"*: it runs on the assembled URL and raises before the transport
    is reached, so a refused address opens no socket.  The URL is built from
    the module's own constant, so this can only fire if a future edit assembles
    it some other way — which is exactly when it must fire.
    """
    host = urllib.parse.urlsplit(url).hostname
    if host != TELEGRAM_API_HOST:
        raise RouterBingXAlertError(
            f"{BINGX_ALERT_CODE}_host_refused",
            f"the alert reaches only {TELEGRAM_API_HOST!r} and {host!r} is not "
            "that host; there is no setting and no environment variable that "
            "changes it, so address the Bot API or inject a transport in a test",
        )
    return url


def _credentials(env: Mapping[str, str]) -> tuple[str, str] | None:
    """The token and chat id, or ``None`` naming the missing variable in one line.

    An unconfigured alert is a supported deployment state, not a fault: a
    process with no ``TELEGRAM_BOT_TOKEN`` simply cannot alert, and the log
    line names the *variable* — never a value — so the repair is obvious.
    """
    token = env.get(BOT_TOKEN_ENV)
    if not isinstance(token, str) or not token.strip():
        log.warning(
            "%s: %s is not set, so no alert was sent",
            BINGX_ALERT_CODE,
            BOT_TOKEN_ENV,
        )
        return None
    chat_id = env.get(CHAT_ID_ENV)
    if not isinstance(chat_id, str) or not chat_id.strip():
        log.warning(
            "%s: %s is not set, so no alert was sent",
            BINGX_ALERT_CODE,
            CHAT_ID_ENV,
        )
        return None
    return token, chat_id


def _format_message(level: str, text: str) -> str:
    """The wire text: the level, the bot's name, then the caller's own body."""
    return f"{level}: {BOT_NAME}\n\n{text}"


def send_alert(
    level: str,
    text: str,
    *,
    env: Mapping[str, str] | None = None,
    transport: Callable[[str, str, Mapping[str, str], bytes], tuple[int, bytes]]
    | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Send one Telegram message at ``level``; ``True`` iff Telegram answered ok.

    ``level`` is one of :data:`URGENT`, :data:`WARNING` or :data:`INFO` — an
    unknown level is a :class:`RouterBingXAlertError`, raised before anything is
    built.  The message opens with the level and :data:`BOT_NAME`.  An
    :data:`INFO` alert is sent with ``disable_notification`` true, so it arrives
    silently; ``urgent`` and ``warning`` ring.

    Every delivery outcome the spec names returns ``False`` and logs exactly one
    line naming the failure: a missing ``TELEGRAM_BOT_TOKEN`` or
    ``TELEGRAM_CHAT_ID``, a transport error, a timeout, or Telegram answering
    ``ok:false``.  The token is scrubbed from every line and from any exception
    rendering.  A caller that injects nothing gets the real credential
    environment and the real :mod:`urllib.request` transport with a 10-second
    timeout; a test injects both and opens no socket.
    """
    if level not in ALERT_LEVELS:
        raise RouterBingXAlertError(
            f"{BINGX_ALERT_CODE}_unknown_level",
            f"the level must be one of {ALERT_LEVELS}, got {level!r}",
        )

    environment = os.environ if env is None else env
    credentials = _credentials(environment)
    if credentials is None:
        return False
    token, chat_id = credentials

    if transport is None:
        transport = make_urllib_transport(timeout)

    url = _guard(f"{TELEGRAM_API_ORIGIN}/bot{token}{SEND_MESSAGE_PATH}")
    body = json.dumps(
        {
            "chat_id": chat_id,
            "text": _format_message(level, text),
            "disable_notification": level == INFO,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    try:
        status, payload = transport("POST", url, headers, body)
    except Exception as exc:  # noqa: BLE001 - every transport fault is one outcome
        log.warning(
            "%s: the POST to the Bot API failed before a response arrived (%s)",
            BINGX_ALERT_CODE,
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )
        return False

    return _read_answer(status, payload)


def _read_answer(status: int, payload: bytes) -> bool:
    """``True`` iff the response says ``ok``; otherwise log one line and ``False``.

    Telegram answers ``{"ok": true, "result": {...}}`` on success and
    ``{"ok": false, "error_code": n, "description": "..."}`` on failure.  A
    non-2xx status or a body that will not decode as that envelope is a
    failure too — the message did not land — and each is named in the one
    line, with the token scrubbed from anything the venue echoed back.
    """
    try:
        answer = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log.warning(
            "%s: the Bot API answered HTTP %s with a body that is not JSON",
            BINGX_ALERT_CODE,
            status,
        )
        return False
    if not isinstance(answer, dict):
        log.warning(
            "%s: the Bot API answered HTTP %s with %s, not a JSON object",
            BINGX_ALERT_CODE,
            status,
            type(answer).__name__,
        )
        return False
    if answer.get("ok") is True:
        return True
    description = scrub_bot_path(str(answer.get("description", "no description")))
    log.warning(
        "%s: the Bot API refused the message (HTTP %s, error_code %s): %s",
        BINGX_ALERT_CODE,
        status,
        answer.get("error_code"),
        description,
    )
    return False


def _failure_text(unit: str) -> str:
    """The urgent body for a slot that could not run, naming how to read it."""
    return (
        f"The scheduled slot for {unit} could not run.\n"
        f"Read it with: journalctl --user -u {unit} -n 100 --no-pager"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: Callable[[str, str, Mapping[str, str], bytes], tuple[int, bytes]]
    | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """The command's two doors: ``--test`` and ``--unit NAME --event failure``.

    ``--test`` sends an :data:`INFO` message and returns 0 when Telegram
    answered ``ok``, 1 otherwise.  ``--unit NAME --event failure`` sends an
    :data:`URGENT` *"slot could not run"* alert naming the unit and the
    ``journalctl`` command that reads it, and takes the same exit codes.  Both
    doors print nothing to stdout: every outcome is logged, one line per
    failure, with the token scrubbed.
    """
    parser = argparse.ArgumentParser(
        prog="python -m router.bingx_alert",
        description=(
            "Send one Telegram alert through the Bot API. Use --test for an "
            "info delivery check, or --unit NAME --event failure for the "
            "urgent alert a systemd OnFailure hook sends when a scheduled "
            "slot could not run."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--test",
        action="store_true",
        help="send an info test message; exit 0 on delivery, 1 otherwise",
    )
    group.add_argument(
        "--unit",
        help="the systemd unit that could not run (with --event failure)",
    )
    parser.add_argument(
        "--event",
        choices=[EVENT_FAILURE],
        help="the event the alert reports; currently only 'failure'",
    )
    arguments = parser.parse_args(argv)

    if arguments.test:
        delivered = send_alert(
            INFO,
            "test message: the alert path is configured and the Bot API answers.",
            env=env,
            transport=transport,
            timeout=timeout,
        )
    else:
        if arguments.event != EVENT_FAILURE:
            parser.error("--unit requires --event failure")
        delivered = send_alert(
            URGENT,
            _failure_text(arguments.unit),
            env=env,
            transport=transport,
            timeout=timeout,
        )
    return 0 if delivered else 1


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
