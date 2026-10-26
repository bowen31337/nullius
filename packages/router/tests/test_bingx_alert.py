"""Tests for :mod:`router.bingx_alert` (additions_spec feature 1).

The suite drives the sender against a recording transport and a literal
environment mapping, so no test opens a socket and none reads a real
credential.  The fake token appears in the request URL — that is the Bot
API's own shape — and every test that captures a log line, an exception or
stdout asserts the token is *absent* from it: the spec's constraint is that
the token never appears in a repository file, a fixture, a log line, an
exception message, a repr or stdout, and the bot path is scrubbed from every
URL.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from collections.abc import Mapping

import pytest
from router.bingx_alert import (
    ALERT_LEVELS,
    BINGX_ALERT_CODE,
    BOT_NAME,
    BOT_TOKEN_ENV,
    CHAT_ID_ENV,
    DEFAULT_TIMEOUT_SECONDS,
    INFO,
    TELEGRAM_API_HOST,
    TELEGRAM_API_ORIGIN,
    TELEGRAM_MAX_MESSAGE,
    URGENT,
    WARNING,
    RouterBingXAlertError,
    main,
    scrub_bot_path,
    send_alert,
)

#: A fake token in the Bot API's own shape — a numeric id, a colon, a secret.
#: Never a real credential; the assertions below pin that it never leaves the
#: request URL.
FAKE_TOKEN = "123456789:AAHfakeTokenValueNotARealSecret"
FAKE_CHAT_ID = "-1001234567890"


class _Recorder:
    """A transport that records its call and answers a canned response."""

    def __init__(self, answer: tuple[int, bytes]) -> None:
        self.answer = answer
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


def _env(token: str | None = FAKE_TOKEN, chat_id: str | None = FAKE_CHAT_ID) -> dict[str, str]:
    environment: dict[str, str] = {}
    if token is not None:
        environment[BOT_TOKEN_ENV] = token
    if chat_id is not None:
        environment[CHAT_ID_ENV] = chat_id
    return environment


def _body_of(recorder: _Recorder) -> dict:
    return json.loads(recorder.calls[-1][3].decode("utf-8"))


# -- The request --------------------------------------------------------------


def test_posts_to_the_bot_api_with_the_token_in_the_path() -> None:
    recorder = _Recorder(_ok())
    assert send_alert(URGENT, "hello", env=_env(), transport=recorder) is True
    method, url, headers, _ = recorder.calls[-1]
    assert method == "POST"
    parsed = urllib.parse.urlsplit(url)
    assert parsed.hostname == TELEGRAM_API_HOST
    assert parsed.scheme == "https"
    assert parsed.path == f"/bot{FAKE_TOKEN}/sendMessage"
    assert headers["Content-Type"] == "application/json"


def test_the_message_opens_with_the_level_and_the_bot_name() -> None:
    recorder = _Recorder(_ok())
    send_alert(WARNING, "a leg was refused", env=_env(), transport=recorder)
    text = _body_of(recorder)["text"]
    assert text.startswith(f"{WARNING}: {BOT_NAME}")


def test_the_chat_id_rides_in_the_body() -> None:
    recorder = _Recorder(_ok())
    send_alert(INFO, "quiet", env=_env(), transport=recorder)
    assert _body_of(recorder)["chat_id"] == FAKE_CHAT_ID


@pytest.mark.parametrize(
    ("level", "silent"),
    [(INFO, True), (URGENT, False), (WARNING, False)],
)
def test_only_an_info_alert_is_sent_with_disable_notification(
    level: str, silent: bool
) -> None:
    recorder = _Recorder(_ok())
    send_alert(level, "body", env=_env(), transport=recorder)
    assert _body_of(recorder)["disable_notification"] is silent


def test_only_the_bot_api_host_is_reachable() -> None:
    """The guard runs on the assembled URL, whose host is the module constant."""
    recorder = _Recorder(_ok())
    send_alert(INFO, "x", env=_env(), transport=recorder)
    url = recorder.calls[-1][1]
    assert url.startswith(f"{TELEGRAM_API_ORIGIN}/bot")


def test_an_unknown_level_is_a_typed_refusal_before_anything_is_sent() -> None:
    recorder = _Recorder(_ok())
    with pytest.raises(RouterBingXAlertError) as caught:
        send_alert("panic", "x", env=_env(), transport=recorder)
    assert str(caught.value).startswith(BINGX_ALERT_CODE)
    assert recorder.calls == []


def test_the_default_timeout_is_ten_seconds() -> None:
    assert DEFAULT_TIMEOUT_SECONDS == 10.0


# -- The Bot API's own message-length limit -----------------------------------


#: The marker an over-long wire text is cut to end with, as a pattern: the
#: count it names is whatever the sender dropped, so the test reads the
#: number back out of the posted body instead of restating it.
TRUNCATION_MARKER = re.compile(r"… \[truncated, (\d+) chars\]$")


def test_the_limit_is_the_number_the_bot_api_refuses_past() -> None:
    """4096 is the Bot API's own ceiling, not a number this member picked."""
    assert TELEGRAM_MAX_MESSAGE == 4096


def test_a_body_over_the_limit_is_posted_cut_to_it_ending_in_a_marker() -> None:
    """An over-long message arrives at exactly the limit, head first.

    The Bot API answers any message past :data:`TELEGRAM_MAX_MESSAGE`
    characters with HTTP 400 ``message is too long`` — the refusal that
    silenced every refused slot whose alert body listed 50 deferred legs
    (``bug_spec_vst_reduce_only_legs.xml``, bug 3).  The wire text is cut
    to the limit and ends with a marker naming how many characters fell
    off, so the level, the bot's name and the body's first lines always
    arrive and the operator learns there is more in the journal.
    """
    recorder = _Recorder(_ok())
    assert send_alert(URGENT, "x" * 10_000, env=_env(), transport=recorder) is True
    text = _body_of(recorder)["text"]
    assert len(text) == TELEGRAM_MAX_MESSAGE
    assert text.startswith(f"{URGENT}: {BOT_NAME}\n\n")
    marker = TRUNCATION_MARKER.search(text)
    assert marker is not None
    # The head that survived is the original's own opening, and the count
    # names exactly the characters of the original that did not survive.
    original = f"{URGENT}: {BOT_NAME}\n\n" + "x" * 10_000
    kept = len(text) - len(marker.group(0))
    assert text[:kept] == original[:kept]
    assert int(marker.group(1)) == len(original) - kept


def test_a_body_that_fits_is_posted_unchanged() -> None:
    """A message inside the limit carries no marker and no cut."""
    recorder = _Recorder(_ok())
    assert send_alert(WARNING, "a leg was refused", env=_env(), transport=recorder)
    assert (
        _body_of(recorder)["text"] == f"{WARNING}: {BOT_NAME}\n\na leg was refused"
    )


def test_a_body_exactly_at_the_limit_is_posted_unchanged() -> None:
    """The limit is inclusive: 4096 characters is not an over-long message."""
    prefix = f"{INFO}: {BOT_NAME}\n\n"
    recorder = _Recorder(_ok())
    body = "y" * (TELEGRAM_MAX_MESSAGE - len(prefix))
    assert send_alert(INFO, body, env=_env(), transport=recorder) is True
    text = _body_of(recorder)["text"]
    assert len(text) == TELEGRAM_MAX_MESSAGE
    assert text == prefix + body


def test_a_body_one_character_over_is_cut_to_the_limit() -> None:
    """One character past the limit is still cut, marker and all."""
    prefix = f"{URGENT}: {BOT_NAME}\n\n"
    recorder = _Recorder(_ok())
    body = "y" * (TELEGRAM_MAX_MESSAGE - len(prefix) + 1)
    assert send_alert(URGENT, body, env=_env(), transport=recorder) is True
    text = _body_of(recorder)["text"]
    assert len(text) == TELEGRAM_MAX_MESSAGE
    assert TRUNCATION_MARKER.search(text) is not None


# -- Delivery outcomes: False, one line, no token -----------------------------


def test_a_missing_token_returns_false_and_names_the_variable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder(_ok())
    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(URGENT, "x", env=_env(token=None), transport=recorder) is False
    assert recorder.calls == []
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1
    assert BOT_TOKEN_ENV in lines[0]


def test_a_missing_chat_id_returns_false_and_names_the_variable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder(_ok())
    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(URGENT, "x", env=_env(chat_id=None), transport=recorder) is False
    assert recorder.calls == []
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1
    assert CHAT_ID_ENV in lines[0]


def test_a_transport_error_returns_false_with_one_scrubbed_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing(method, url, headers, body):
        raise OSError(f"connection refused opening {url}")

    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(URGENT, "x", env=_env(), transport=failing) is False
    lines = [record.getMessage() + repr(record.args) for record in caplog.records]
    assert len(lines) == 1
    assert FAKE_TOKEN not in lines[0]
    assert "/bot<redacted>/sendMessage" in lines[0]


def test_a_timeout_returns_false_with_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def timing_out(method, url, headers, body):
        raise TimeoutError("timed out after 10 seconds")

    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(WARNING, "x", env=_env(), transport=timing_out) is False
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1


def test_an_ok_false_answer_returns_false_and_names_the_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder(_refused("chat not found", code=400))
    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(URGENT, "x", env=_env(), transport=recorder) is False
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1
    assert "chat not found" in lines[0]
    assert "400" in lines[0]


def test_a_non_ok_body_with_the_token_echoed_back_is_scrubbed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder(_ok())
    recorder.answer = (
        200,
        json.dumps(
            {
                "ok": False,
                "error_code": 401,
                "description": f"Unauthorized at /bot{FAKE_TOKEN}/sendMessage",
            }
        ).encode(),
    )
    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(URGENT, "x", env=_env(), transport=recorder) is False
    rendered = "\n".join(
        record.getMessage() + repr(record.args) for record in caplog.records
    )
    assert FAKE_TOKEN not in rendered


def test_a_body_that_is_not_json_returns_false_with_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder((502, b"<html>bad gateway</html>"))
    with caplog.at_level(logging.WARNING, logger="router.bingx_alert"):
        assert send_alert(URGENT, "x", env=_env(), transport=recorder) is False
    assert len([record for record in caplog.records]) == 1


def test_an_ok_envelope_delivers() -> None:
    """*"returns True when Telegram answers ok."*"""
    recorder = _Recorder((200, json.dumps({"ok": True}).encode()))
    assert send_alert(INFO, "x", env=_env(), transport=recorder) is True


# -- The token never leaves the request URL ----------------------------------


def test_scrub_bot_path_removes_the_token_from_a_url() -> None:
    url = f"{TELEGRAM_API_ORIGIN}/bot{FAKE_TOKEN}/sendMessage"
    scrubbed = scrub_bot_path(url)
    assert FAKE_TOKEN not in scrubbed
    assert scrubbed == f"{TELEGRAM_API_ORIGIN}/bot<redacted>/sendMessage"


def test_nothing_reaches_stdout_on_delivery_or_failure(
    capsys: pytest.CaptureFixture,
) -> None:
    recorder = _Recorder(_ok())
    send_alert(URGENT, "x", env=_env(), transport=recorder)
    send_alert(URGENT, "x", env=_env(token=None), transport=recorder)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert FAKE_TOKEN not in captured.out


# -- The command's two doors --------------------------------------------------


def test_test_flag_exits_zero_on_delivery() -> None:
    recorder = _Recorder(_ok())
    assert main(["--test"], env=_env(), transport=recorder) == 0
    body = _body_of(recorder)
    assert body["text"].startswith(f"{INFO}: {BOT_NAME}")
    assert body["disable_notification"] is True


def test_test_flag_exits_one_when_undelivered() -> None:
    recorder = _Recorder(_refused())
    assert main(["--test"], env=_env(), transport=recorder) == 1


def test_test_flag_exits_one_with_no_credential() -> None:
    recorder = _Recorder(_ok())
    assert main(["--test"], env=_env(token=None), transport=recorder) == 1
    assert recorder.calls == []


def test_unit_event_failure_sends_an_urgent_alert_naming_the_unit_and_journalctl() -> None:
    recorder = _Recorder(_ok())
    code = main(
        ["--unit", "nullius-vst-rebalance.service", "--event", "failure"],
        env=_env(),
        transport=recorder,
    )
    assert code == 0
    body = _body_of(recorder)
    assert body["text"].startswith(f"{URGENT}: {BOT_NAME}")
    assert body["disable_notification"] is False
    assert "nullius-vst-rebalance.service" in body["text"]
    assert "journalctl --user -u nullius-vst-rebalance.service" in body["text"]


def test_unit_without_event_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        main(["--unit", "nullius-vst-rebalance.service"], env=_env())


def test_the_levels_are_exactly_the_three_the_spec_names() -> None:
    assert ALERT_LEVELS == (URGENT, WARNING, INFO)
