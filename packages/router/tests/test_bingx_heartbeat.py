"""Tests for :mod:`router.bingx_heartbeat` (additions_spec feature 3).

The heartbeat of ``additions_spec_bingx_vst_alerts.xml``, the Telegram
alerting spec for the scheduled BingX VST bot: *the system checks the bot's
heartbeat from* ``python -m router.bingx_heartbeat --max-age-hours 5``.  It
reads the newest slot completion feature 2 recorded; when there is none, or
the newest is older than the limit, it sends an urgent alert naming the last
slot and its age and exits 1; otherwise it sends nothing and exits 0.  At most
one alert is sent per stale slot.

Three things are pinned here:

* **The judgement.**  Fresh, exactly at the boundary, stale and never-finished
  each take the exit the sentence gives them, measured against the
  completion's own ``finished_at``.
* **The dedupe.**  The second hourly check of the *same* stale slot sends
  nothing but still exits 1; a *different* stale slot — and a store that has
  never seen a completion — alerts again.  The marker is written only after
  Telegram answers ``ok``, so a dropped message is retried rather than lost.
* **The units.**  The oneshot service carries the rebalance service's own
  ``PATH`` and token-file load and runs ``run.sh vst-heartbeat
  --max-age-hours 5``; the timer fires hourly at minute 35 with
  ``Persistent=true``.  One test runs the shipped ExecStart under ``env -i``
  with ``run.sh`` stubbed, proving the environment reaches the child.

Every test drives a recording transport and a literal environment mapping, so
no test opens a socket, reads 1Password or a real credential, and none of
them installs or reloads a unit.  The fake token appears in the request URL —
the Bot API's own shape — and every test that captures a log line or stdout
asserts it is *absent* from it.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from router.bingx_alert import (
    BOT_NAME,
    BOT_TOKEN_ENV,
    CHAT_ID_ENV,
    TELEGRAM_API_HOST,
    URGENT,
    send_alert,
)
from router.bingx_heartbeat import (
    BINGX_HEARTBEAT_CODE,
    DEFAULT_MAX_AGE_HOURS,
    EXIT_OK,
    EXIT_STALE,
    NO_COMPLETION_KEY,
    ROUTER_HEARTBEAT_ALERT_TABLE,
    VERDICT_ABSENT,
    VERDICT_FRESH,
    VERDICT_STALE,
    RouterBingXHeartbeatError,
    RouterHeartbeatAlertStore,
    main,
)
from router.bingx_rebalance import (
    EXIT_DAILY_LOSS_HALT,
    EXIT_REFUSED,
    RouterSlotCompletionStore,
)

#: A fake token in the Bot API's own shape — a numeric id, a colon, a secret.
#: Never a real credential; the assertions below pin that it never leaves the
#: request URL or a captured stream.
FAKE_TOKEN = "123456789:AAHfakeTokenValueNotARealSecret"
FAKE_CHAT_ID = "-1001234567890"

#: The check's own moment, and the slot the completions below belong to.
MOMENT = datetime(2026, 10, 4, 12, 37, tzinfo=UTC)
SLOT_NOON = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
SLOT_MORNING = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)

DEPLOY_SYSTEMD = Path(__file__).resolve().parents[3] / "deploy" / "systemd"
HEARTBEAT_SERVICE_PATH = DEPLOY_SYSTEMD / "nullius-vst-heartbeat.service"
HEARTBEAT_TIMER_PATH = DEPLOY_SYSTEMD / "nullius-vst-heartbeat.timer"
REBALANCE_UNIT_PATH = DEPLOY_SYSTEMD / "nullius-vst-rebalance.service"

#: The token file the operator's own ``~/.zshrc`` loads the 1Password
#: service-account token from (mode 0600, outside the repository).
TOKEN_FILE_SUFFIX = "/.config/op/service-token"


class _Recorder:
    """A transport that records its call and answers a canned response."""

    def __init__(self, answer: tuple[int, bytes] | None = None) -> None:
        self.answer = answer if answer is not None else _ok()
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, dict(headers), body))
        return self.answer


def _ok() -> tuple[int, bytes]:
    return 200, json.dumps({"ok": True, "result": {"message_id": 7}}).encode()


def _refused(description: str = "chat not found", code: int = 400) -> tuple[int, bytes]:
    return (
        200,
        json.dumps(
            {"ok": False, "error_code": code, "description": description}
        ).encode(),
    )


def _env() -> dict[str, str]:
    return {BOT_TOKEN_ENV: FAKE_TOKEN, CHAT_ID_ENV: FAKE_CHAT_ID}


def _body_of(recorder: _Recorder) -> dict:
    return json.loads(recorder.calls[-1][3].decode("utf-8"))


def _verdict_of(out: str) -> dict:
    """Parse stdout as the one JSON verdict line the check prints."""
    lines = out.splitlines()
    assert len(lines) == 1, out
    return json.loads(lines[0])


def _seed(
    url: str,
    *,
    book_id: str = "synthetic-vst-0",
    slot: datetime = SLOT_NOON,
    finished_at: datetime,
    exit_code: int = 0,
) -> None:
    """Append one completion through feature 2's own record door."""

    RouterSlotCompletionStore(url).record(
        book_id=book_id,
        slot=slot,
        finished_at=finished_at,
        exit_code=exit_code,
    )


def _run(url: str, **overrides) -> tuple[int, _Recorder]:
    recorder = overrides.pop("transport", None) or _Recorder()
    code = main(
        overrides.pop("argv", ["--max-age-hours", "5"]),
        database_url=url,
        env=overrides.pop("env", _env()),
        now=overrides.pop("now", lambda: MOMENT),
        transport=recorder,
        **overrides,
    )
    return code, recorder


def _assert_no_token(*streams: object) -> None:
    for stream in streams:
        rendered = getattr(stream, "text", None)
        if rendered is None:
            rendered = getattr(stream, "out", "")
        assert FAKE_TOKEN not in rendered


# -- The judgement: fresh, boundary, stale, never-finished ----------------------


def test_a_fresh_completion_sends_nothing_and_exits_zero(
    test_database_url, capsys, caplog
) -> None:
    """The healthy case sends no Telegram message, but still prints the verdict."""
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=4))
    with caplog.at_level(logging.WARNING, logger="router.bingx_heartbeat"):
        code, recorder = _run(test_database_url)
    assert code == EXIT_OK
    assert recorder.calls == []
    assert caplog.records == []
    assert _verdict_of(capsys.readouterr().out) == {
        "verdict": VERDICT_FRESH,
        "newest_slot": SLOT_NOON.isoformat(),
        "age_hours": 4.0,
        "max_age_hours": 5.0,
    }


def test_a_completion_exactly_at_the_limit_is_still_fresh(
    test_database_url, capsys
) -> None:
    """The boundary belongs to the bot: an age of exactly the limit passes.

    Five hours is the sentence's own slack for one 4-hour slot; a check that
    called the exact boundary stale would page on the hour the slot is merely
    late, which is the false alarm the limit exists to avoid.
    """
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=5))
    code, recorder = _run(test_database_url)
    assert code == EXIT_OK
    assert recorder.calls == []
    assert _verdict_of(capsys.readouterr().out) == {
        "verdict": VERDICT_FRESH,
        "newest_slot": SLOT_NOON.isoformat(),
        "age_hours": 5.0,
        "max_age_hours": 5.0,
    }


def test_a_stale_completion_sends_one_urgent_alert_naming_slot_and_age(
    test_database_url, capsys, caplog
) -> None:
    """*"sends an urgent alert naming the last slot and its age, and exits 1"*.

    The body names the slot's own start, the book, the exit it finished on,
    the instant it finished and the age measured from that instant, so an
    operator reading the phone knows the bot is six hours behind.  The same
    facts — the verdict, the slot and the age — land on stdout too.
    """
    _seed(
        test_database_url,
        finished_at=MOMENT - timedelta(hours=6),
        exit_code=EXIT_REFUSED,
    )
    with caplog.at_level(logging.WARNING, logger="router.bingx_heartbeat"):
        code, recorder = _run(test_database_url)

    assert code == EXIT_STALE
    assert len(recorder.calls) == 1
    body = _body_of(recorder)
    assert body["text"].startswith(f"{URGENT}: {BOT_NAME}")
    assert body["disable_notification"] is False
    assert SLOT_NOON.isoformat() in body["text"]
    assert "synthetic-vst-0" in body["text"]
    assert "6.0 hours" in body["text"]
    captured = capsys.readouterr()
    assert _verdict_of(captured.out) == {
        "verdict": VERDICT_STALE,
        "newest_slot": SLOT_NOON.isoformat(),
        "age_hours": 6.0,
        "max_age_hours": 5.0,
    }
    _assert_no_token(captured)


def test_no_completion_at_all_alerts_once_and_exits_one(
    test_database_url, capsys
) -> None:
    """*"When there is none ... it sends an urgent alert ... and exits 1."*

    There is no last slot to name, so the body says nothing has ever
    finished rather than inventing one — but the alarm and the exit are the
    same as a stale one: the bot has produced nothing the operator can see.
    Stdout carries the same "absent" verdict, with no slot and no age.
    """
    code, recorder = _run(test_database_url)
    assert code == EXIT_STALE
    assert len(recorder.calls) == 1
    body = _body_of(recorder)
    assert body["text"].startswith(f"{URGENT}: {BOT_NAME}")
    assert "never recorded a finished slot" in body["text"]
    assert _verdict_of(capsys.readouterr().out) == {
        "verdict": VERDICT_ABSENT,
        "newest_slot": None,
        "age_hours": None,
        "max_age_hours": 5.0,
    }


def test_the_newest_completion_is_the_one_judged(test_database_url) -> None:
    """A fresh newest wins even when an older completion is stale.

    The sentence reads *the newest slot completion*; an old stale row below a
    fresh one is history, not a live alarm.
    """
    _seed(
        test_database_url,
        slot=SLOT_MORNING,
        finished_at=MOMENT - timedelta(hours=9),
    )
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=1))
    code, recorder = _run(test_database_url)
    assert code == EXIT_OK
    assert recorder.calls == []


def test_a_halted_slot_going_stale_is_still_a_heartbeat_alert(
    test_database_url,
) -> None:
    """Exit 3 is a *finish*: the bot ran, and now it has gone quiet.

    A halted slot is a slot the bot ran and recorded; the heartbeat's alarm
    is only that nothing has finished lately, so the halt's own exit reaches
    the body without changing the heartbeat's verdict.
    """
    _seed(
        test_database_url,
        finished_at=MOMENT - timedelta(hours=7),
        exit_code=EXIT_DAILY_LOSS_HALT,
    )
    code, recorder = _run(test_database_url)
    assert code == EXIT_STALE
    assert len(recorder.calls) == 1
    assert "exit 3" in _body_of(recorder)["text"]


# -- The dedupe: at most one alert per stale slot -------------------------------


def test_a_second_check_of_the_same_stale_slot_sends_nothing_but_still_exits_one(
    test_database_url, capsys
) -> None:
    """*"At most one heartbeat alert is sent per stale slot."*

    The first hourly check pages; the next three stay silent — the operator
    was already told about this very slot — yet every one still exits 1,
    because the bot is still stale and that is what the unit state should
    say.  Every one of the four still prints the verdict line, deduped or
    not: the dedupe governs the Telegram message, never stdout.
    """
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    expected_verdict = {
        "verdict": VERDICT_STALE,
        "newest_slot": SLOT_NOON.isoformat(),
        "age_hours": 7.0,
        "max_age_hours": 5.0,
    }

    first, first_recorder = _run(test_database_url)
    assert first == EXIT_STALE
    assert len(first_recorder.calls) == 1
    assert _verdict_of(capsys.readouterr().out) == expected_verdict

    for _ in range(3):
        again, recorder = _run(test_database_url)
        assert again == EXIT_STALE
        assert recorder.calls == []
        assert _verdict_of(capsys.readouterr().out) == expected_verdict


def test_a_new_stale_slot_alerts_again(test_database_url) -> None:
    """The dedupe is per stale slot, not forever: a later dead slot pages.

    A bot that recovers, finishes one slot, then goes quiet again must be
    reported again — the marker for the earlier slot does not cover the new
    one.
    """
    _seed(
        test_database_url,
        slot=SLOT_MORNING,
        finished_at=MOMENT - timedelta(hours=9),
    )
    first, first_recorder = _run(test_database_url)
    assert first == EXIT_STALE
    assert len(first_recorder.calls) == 1

    _seed(test_database_url, slot=SLOT_NOON, finished_at=MOMENT - timedelta(hours=8))
    second, second_recorder = _run(test_database_url)
    assert second == EXIT_STALE
    assert len(second_recorder.calls) == 1
    assert SLOT_NOON.isoformat() in _body_of(second_recorder)["text"]


def test_the_never_finished_state_is_its_own_dedupe_key(test_database_url) -> None:
    """An empty store and a stale slot do not silence each other."""
    first, first_recorder = _run(test_database_url)
    assert first == EXIT_STALE
    assert len(first_recorder.calls) == 1

    # A slot now exists and is stale: a *new* condition, so it alerts.
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    second, second_recorder = _run(test_database_url)
    assert second == EXIT_STALE
    assert len(second_recorder.calls) == 1


def test_the_marker_is_only_written_after_telegram_answers_ok(
    test_database_url,
) -> None:
    """A dropped message leaves no mark, so the next check retries it.

    The marker states what the operator was *told*.  An ``ok:false`` answer
    delivered nothing, so the store stays empty and the following check sends
    again — a lost page is retried, never silently swallowed.
    """
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    store = RouterHeartbeatAlertStore(test_database_url)

    refused = _Recorder(_refused())
    code, _ = _run(test_database_url, transport=refused)
    assert code == EXIT_STALE
    assert not store.already_alerted(f"synthetic-vst-0:{SLOT_NOON.isoformat()}")

    retried = _Recorder()
    code, _ = _run(test_database_url, transport=retried)
    assert code == EXIT_STALE
    assert len(retried.calls) == 1
    assert store.already_alerted(f"synthetic-vst-0:{SLOT_NOON.isoformat()}")


def test_a_missing_credential_leaves_the_exit_stale_and_no_marker(
    test_database_url, capsys
) -> None:
    """An unconfigured alert is not a healthy bot: exit 1 either way.

    With no Bot API credential the message cannot leave, so nothing is
    marked and the check repeats next hour — but the exit still reports the
    staleness, because the bot's health does not depend on the phone.  Nor
    does the printed verdict: an operator with no Telegram configured still
    learns the bot is stale from stdout alone.
    """
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    recorder = _Recorder()
    code = main(
        ["--max-age-hours", "5"],
        database_url=test_database_url,
        env={},
        now=lambda: MOMENT,
        transport=recorder,
    )
    assert code == EXIT_STALE
    assert recorder.calls == []
    store = RouterHeartbeatAlertStore(test_database_url)
    assert not store.already_alerted(f"synthetic-vst-0:{SLOT_NOON.isoformat()}")
    captured = capsys.readouterr()
    assert _verdict_of(captured.out) == {
        "verdict": VERDICT_STALE,
        "newest_slot": SLOT_NOON.isoformat(),
        "age_hours": 7.0,
        "max_age_hours": 5.0,
    }
    _assert_no_token(captured)


# -- Faults are one log line and never change the verdict -----------------------


def test_an_alert_that_raises_is_caught_and_logged(
    test_database_url, caplog, capsys
) -> None:
    """A raised alert never changes the exit code, and the token is scrubbed."""
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))

    def raising_alert(level, text, **kwargs):
        raise RuntimeError(
            f"connection error posting "
            f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
        )

    with caplog.at_level(logging.WARNING, logger="router.bingx_heartbeat"):
        code = main(
            ["--max-age-hours", "5"],
            database_url=test_database_url,
            env=_env(),
            now=lambda: MOMENT,
            alert=raising_alert,
        )
    assert code == EXIT_STALE
    assert "raised and was caught" in caplog.text
    assert "/bot<redacted>" in caplog.text
    _assert_no_token(capsys.readouterr())
    assert FAKE_TOKEN not in caplog.text


def test_a_marker_store_that_cannot_answer_still_sends_the_alert(
    test_database_url, caplog, capsys
) -> None:
    """A bookkeeping fault is logged, not allowed to silence a stale bot."""

    class _BrokenStore:
        def already_alerted(self, _key):
            raise RuntimeError("disk I/O error")

    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    recorder = _Recorder()
    with caplog.at_level(logging.WARNING, logger="router.bingx_heartbeat"):
        code = main(
            ["--max-age-hours", "5"],
            database_url=test_database_url,
            env=_env(),
            now=lambda: MOMENT,
            transport=recorder,
            alert_store=_BrokenStore(),
        )
    assert code == EXIT_STALE
    assert len(recorder.calls) == 1
    assert "could not tell whether" in caplog.text
    _assert_no_token(capsys.readouterr())


def test_a_marker_that_cannot_be_written_is_logged_after_delivery(
    test_database_url, caplog, capsys
) -> None:
    """The message already left, so a marker fault is only a log line."""

    class _BrokenStore:
        def already_alerted(self, _key):
            return False

        def mark_alerted(self, _key, *, alerted_at):
            raise RuntimeError("disk I/O error")

    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    recorder = _Recorder()
    with caplog.at_level(logging.WARNING, logger="router.bingx_heartbeat"):
        code = main(
            ["--max-age-hours", "5"],
            database_url=test_database_url,
            env=_env(),
            now=lambda: MOMENT,
            transport=recorder,
            alert_store=_BrokenStore(),
        )
    assert code == EXIT_STALE
    assert len(recorder.calls) == 1
    assert "could not be written" in caplog.text
    _assert_no_token(capsys.readouterr())


# -- The ask: what a heartbeat cannot run --------------------------------------


def test_no_database_url_is_a_typed_refusal(capsys) -> None:
    """The check reads a store; with none named it cannot answer, and says so."""
    recorder = _Recorder()
    code = main(
        ["--max-age-hours", "5"],
        env=_env(),
        transport=recorder,
    )
    assert code == EXIT_STALE
    assert recorder.calls == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "DATABASE_URL" in captured.err
    assert BINGX_HEARTBEAT_CODE in captured.err


def test_a_non_positive_limit_is_a_typed_refusal(test_database_url, capsys) -> None:
    """A zero or negative limit would call a just-finished bot stale."""
    recorder = _Recorder()
    code = main(
        ["--max-age-hours", "0"],
        database_url=test_database_url,
        env=_env(),
        now=lambda: MOMENT,
        transport=recorder,
    )
    assert code == EXIT_STALE
    assert recorder.calls == []
    captured = capsys.readouterr()
    assert "positive" in captured.err
    _assert_no_token(captured)


def test_the_default_limit_is_the_specs_five_hours() -> None:
    """*"--max-age-hours 5"* is the spelling, and the default."""
    assert DEFAULT_MAX_AGE_HOURS == 5


def test_the_default_argument_matches_the_constant(test_database_url) -> None:
    """No ``--max-age-hours`` on the command line means the spec's five."""
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=5, minutes=1))
    code, recorder = _run(test_database_url, argv=[])
    assert code == EXIT_STALE
    assert len(recorder.calls) == 1
    assert "5 hour" in _body_of(recorder)["text"]


# -- The store: the marker table itself ----------------------------------------


def test_the_marker_store_is_idempotent(test_database_url) -> None:
    """``mark_alerted`` twice is one row: a slot reported is reported once."""
    store = RouterHeartbeatAlertStore(test_database_url)
    store.mark_alerted("k", alerted_at=MOMENT)
    store.mark_alerted("k", alerted_at=MOMENT + timedelta(hours=1))
    assert store.already_alerted("k") is True


def test_the_marker_store_refuses_an_empty_url() -> None:
    with pytest.raises(RouterBingXHeartbeatError) as refusal:
        RouterHeartbeatAlertStore("  ")
    assert str(refusal.value).startswith(BINGX_HEARTBEAT_CODE)


def test_the_marker_store_refuses_a_non_sqlite_url() -> None:
    """It speaks the same address as feature 2's completions, and refuses any
    other scheme — at the first connect, as every store here does."""
    with pytest.raises(RouterBingXHeartbeatError) as refusal:
        RouterHeartbeatAlertStore("postgresql://localhost/db").ensure_schema()
    assert str(refusal.value).startswith(BINGX_HEARTBEAT_CODE)


def test_the_alert_table_is_this_modules_own() -> None:
    """The dedupe lives in its own table, not in feature 2's completion table."""
    assert ROUTER_HEARTBEAT_ALERT_TABLE == "router_bingx_heartbeat_alert"


def test_the_no_completion_key_is_not_a_slot_key() -> None:
    assert NO_COMPLETION_KEY == "no-completion"


def test_the_heartbeat_never_touches_the_venue(test_database_url) -> None:
    """Every request goes to the Bot API host and nowhere else."""
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))
    import urllib.parse

    _code, recorder = _run(test_database_url)
    for _method, url, _headers, _body in recorder.calls:
        assert urllib.parse.urlsplit(url).hostname == TELEGRAM_API_HOST


# -- The systemd units ----------------------------------------------------------
#
# The shipped units, not copies: the files the operator links into
# ~/.config/systemd/user/ are the ones pinned here.  Nothing is installed,
# enabled or reloaded, and no test reads a real credential.


def _unit_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _directive(path: Path, name: str) -> str:
    matches = [
        line
        for line in _unit_text(path).splitlines()
        if line.startswith(f"{name}=")
    ]
    assert matches, f"{path.name} declares no {name}="
    assert len(matches) == 1, f"{path.name} declares {name}= more than once"
    return matches[0]


def _expand(command: str, *, home: str) -> str:
    return command.replace("$$", "$").replace("%h", home)


def test_the_service_is_a_oneshot_that_runs_the_heartbeat_command() -> None:
    assert _directive(HEARTBEAT_SERVICE_PATH, "Type") == "Type=oneshot"
    exec_start = _directive(HEARTBEAT_SERVICE_PATH, "ExecStart")
    assert exec_start.removeprefix("ExecStart=").startswith("/bin/sh -c ")
    assert "run.sh vst-heartbeat --max-age-hours 5" in exec_start


def test_the_service_carries_the_rebalance_units_own_path() -> None:
    """Same environment as the rebalance service: ``uv`` must be reachable."""
    environment = _directive(HEARTBEAT_SERVICE_PATH, "Environment")
    assert environment == _directive(REBALANCE_UNIT_PATH, "Environment")
    entries = environment.removeprefix("Environment=PATH=").split(":")
    assert entries[:4] == ["%h/.local/bin", "/usr/local/bin", "/usr/bin", "/bin"]


def test_the_service_loads_the_token_file_like_the_rebalance_unit() -> None:
    """The token prologue is the rebalance unit's own, byte for byte."""
    heartbeat_exec = _directive(HEARTBEAT_SERVICE_PATH, "ExecStart")
    rebalance_exec = _directive(REBALANCE_UNIT_PATH, "ExecStart")

    def prologue(exec_start: str) -> str:
        return exec_start.removeprefix("ExecStart=").split("exec ", 1)[0]

    assert prologue(heartbeat_exec) == prologue(rebalance_exec)
    assert "$$(cat" in heartbeat_exec
    expanded = _expand(
        heartbeat_exec.removeprefix("ExecStart="), home="/home/operator"
    )
    assert f"$(cat /home/operator{TOKEN_FILE_SUFFIX})" in expanded


def test_the_service_treats_a_stale_bot_as_a_successful_check() -> None:
    """Exit 1 is the check's own outcome, not a unit fault."""
    success = _directive(HEARTBEAT_SERVICE_PATH, "SuccessExitStatus")
    codes = {int(code) for code in success.removeprefix("SuccessExitStatus=").split()}
    assert codes == {0, 1}


def test_the_timer_fires_hourly_at_minute_thirty_five() -> None:
    """*"a timer that fires it hourly at minute 35"* — in UTC."""
    calendar = _directive(HEARTBEAT_TIMER_PATH, "OnCalendar")
    assert calendar == "OnCalendar=*-*-* *:35:00 UTC"


def test_the_timer_is_persistent() -> None:
    assert _directive(HEARTBEAT_TIMER_PATH, "Persistent") == "Persistent=true"


def test_the_timer_is_wanted_by_timers_target() -> None:
    assert _directive(HEARTBEAT_TIMER_PATH, "WantedBy") == "WantedBy=timers.target"


def test_no_unit_carries_a_literal_service_account_token() -> None:
    for path in (HEARTBEAT_SERVICE_PATH, HEARTBEAT_TIMER_PATH):
        text = _unit_text(path)
        assert "ops_" not in text, path.name
        for index, line in enumerate(text.splitlines(), start=1):
            if line.startswith("#") or "OP_SERVICE_ACCOUNT_TOKEN" not in line:
                continue
            assert "OP_SERVICE_ACCOUNT_TOKEN=" in line, (
                f"{path.name} line {index} mentions the token without "
                "assigning it from the file"
            )
            assert "cat" in line and TOKEN_FILE_SUFFIX in line


# -- The service's own environment, exercised as systemd would give it ----------


def _heartbeat_environment(home: Path) -> dict[str, str]:
    """The environment systemd would give the service's ``ExecStart``.

    Only the keys ``Environment=PATH`` declares, plus ``HOME`` (how ``%h``
    resolves) and ``USER``: ``subprocess.run(env=…)`` replaces the whole
    environment, which is the ``env -i`` proof the spec asks for.
    """
    path = _directive(HEARTBEAT_SERVICE_PATH, "Environment").removeprefix(
        "Environment=PATH="
    )
    return {
        "PATH": _expand(path, home=str(home)),
        "HOME": str(home),
        "USER": "operator",
    }


def _run_service(tmp_path: Path, *, token: str | None) -> subprocess.CompletedProcess:
    """Exercise the shipped service ExecStart in a systemd-like environment.

    ``%h`` is the temporary home, so ``%h/projects/nullius/run.sh`` is a stub
    written here.  The stub records what it was handed *to a file* — never to
    stdout — so a passing run asserts the token arrived without it entering
    any captured output.
    """
    home = tmp_path / "home"
    repo = home / "projects" / "nullius"
    repo.mkdir(parents=True)
    marker = tmp_path / "stub-env.txt"
    stub = repo / "run.sh"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "ARGV=%s\\nTOKEN=%s\\nPATH=%s\\n" "$*" '
        f'"$OP_SERVICE_ACCOUNT_TOKEN" "$PATH" > "{marker}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    if token is not None:
        token_file = home / ".config" / "op" / "service-token"
        token_file.parent.mkdir(parents=True)
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)

    exec_start = _expand(
        _directive(HEARTBEAT_SERVICE_PATH, "ExecStart").removeprefix("ExecStart="),
        home=str(home),
    )
    return subprocess.run(
        ["/bin/sh", "-c", exec_start],
        cwd=repo,
        env=_heartbeat_environment(home),
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_missing_token_file_fails_the_heartbeat_closed(tmp_path: Path) -> None:
    """No token file means the check stops, it does not run ``op``."""
    result = _run_service(tmp_path, token=None)
    assert result.returncode != 0, result.stdout
    assert TOKEN_FILE_SUFFIX in result.stderr
    assert "unreadable" in result.stderr
    assert not (tmp_path / "stub-env.txt").exists()


def test_the_expanded_exec_start_hands_path_token_and_args_to_run_sh(
    tmp_path: Path,
) -> None:
    """The whole clause, on the command the service actually ships."""
    token = "token-value-read-from-the-operators-file"
    result = _run_service(tmp_path, token=token)

    assert result.returncode == 0, result.stderr
    assert token not in result.stdout
    assert token not in result.stderr
    recorded = (tmp_path / "stub-env.txt").read_text(encoding="utf-8")
    assert "ARGV=vst-heartbeat --max-age-hours 5\n" in recorded
    assert f"TOKEN={token}\n" in recorded
    path_line = next(
        line for line in recorded.splitlines() if line.startswith("PATH=")
    )
    first_entry = path_line.removeprefix("PATH=").split(":")[0]
    assert first_entry == str(tmp_path / "home" / ".local" / "bin")


# -- The delivery path itself, re-pinned here for the heartbeat's own use -------


def test_a_real_send_through_feature_one_scrubs_the_token(
    test_database_url, caplog, capsys
) -> None:
    """The heartbeat's own alert rides feature 1's sender, scrubbed as ever."""
    _seed(test_database_url, finished_at=MOMENT - timedelta(hours=7))

    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        code = main(
            ["--max-age-hours", "5"],
            database_url=test_database_url,
            env=_env(),
            now=lambda: MOMENT,
            alert=send_alert,
            transport=lambda method, url, headers, body: (
                200,
                json.dumps({"ok": True}).encode(),
            ),
        )
    assert code == EXIT_STALE
    captured = capsys.readouterr()
    assert _verdict_of(captured.out) == {
        "verdict": VERDICT_STALE,
        "newest_slot": SLOT_NOON.isoformat(),
        "age_hours": 7.0,
        "max_age_hours": 5.0,
    }
    _assert_no_token(captured)
    assert FAKE_TOKEN not in caplog.text
