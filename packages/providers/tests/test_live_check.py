"""Tests for ``python -m providers.live_check`` — feature 6's command.

The command makes one real model call through feature 4's registry and
prints one JSON line describing what came back, or refuses with one line on
stderr. No test here opens a socket: every test that drives a call injects a
scripted transport of feature 1's shape and a fake, key-shaped credential —
never the ambient environment — so the suite that proves the key never
reaches a rendering is hunting for a value that would be a real leak if it
were ever printed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from providers import FixtureStore, Message, Request
from providers.live_check import CONTENT_PREVIEW_LENGTH, DEFAULT_PROMPT, main

#: A fake credential — key-shaped, not key-real. The point is that a suite
#: can hunt for the literal value in every captured rendering and prove it
#: never escaped.
FAKE_KEY = "fake-nullius-key-not-a-credential"

#: The variable this pin's vendor reads its credential from.
ANTHROPIC_KEY_ENV = "NULLIUS_ANTHROPIC_API_KEY"

#: The pin a successful call is driven against, as the CLI's own spelling.
PIN = "anthropic/claude-opus-5/20260401"


def _ok(body: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    """A 2xx transport answer carrying ``body`` as UTF-8 JSON."""
    return 200, {}, json.dumps(body).encode("utf-8")


def _anthropic_answer(
    *,
    model: str = "claude-opus-5",
    text: str = "ok",
    stop_reason: str = "end_turn",
    input_tokens: int = 3,
    output_tokens: int = 1,
) -> dict[str, Any]:
    """A Messages-API success body carrying ``model`` as the serving model."""
    return {
        "content": [{"type": "text", "text": text}],
        "model": model,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "stop_reason": stop_reason,
    }


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording sends.

    The calls list is the backend seen from outside — URL, headers and body
    bytes of every send — which is how a test reads what left the "machine"
    without opening a socket. When the script runs out the last entry
    repeats.
    """
    calls: list[dict[str, Any]] = []

    def _send(url: str, headers: dict[str, str], body_bytes: bytes, timeout: float):
        calls.append(
            {"url": url, "headers": dict(headers), "body": body_bytes, "timeout": timeout}
        )
        answer = script[min(len(calls), len(script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    _send.calls = calls
    return _send


def _sent_body(transport: Any, *, index: int = 0) -> dict[str, Any]:
    """Decode the JSON body of one of ``transport``'s recorded sends."""
    return json.loads(transport.calls[index]["body"])


def _clock(*readings: float) -> Any:
    """An injectable clock answering ``readings`` in order, one per call."""
    values = iter(readings)
    return lambda: next(values)


# ── A successful call ──────────────────────────────────────────────────────


def test_successful_call_prints_one_json_line_with_every_field():
    """The summary line carries every field the sentence names."""
    transport = _transport(_ok(_anthropic_answer()))
    lines: list[str] = []
    code = main(
        ["--pin", PIN],
        env={ANTHROPIC_KEY_ENV: FAKE_KEY},
        transport=transport,
        emit=lines.append,
        clock=_clock(10.0, 10.25),
    )
    assert code == 0
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {
        "pin": PIN,
        "served_model": "claude-opus-5",
        "finish_reason": "stop",
        "input_tokens": 3,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "latency_ms": 250.0,
        "content": "ok",
    }


def test_default_prompt_is_sent_as_the_one_user_message():
    """``--prompt`` defaults to the sentence's own text, sent as one turn."""
    transport = _transport(_ok(_anthropic_answer()))
    main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport, emit=lambda _: None)
    sent = _sent_body(transport)
    assert len(sent["messages"]) == 1
    assert sent["messages"][0]["role"] == "user"
    assert sent["messages"][0]["content"][0]["text"] == DEFAULT_PROMPT


def test_custom_prompt_overrides_the_default():
    """``--prompt`` replaces the default text, not adds to it."""
    transport = _transport(_ok(_anthropic_answer()))
    main(
        ["--pin", PIN, "--prompt", "say hi"],
        env={ANTHROPIC_KEY_ENV: FAKE_KEY},
        transport=transport,
        emit=lambda _: None,
    )
    sent = _sent_body(transport)
    assert sent["messages"][0]["content"][0]["text"] == "say hi"


def test_max_tokens_defaults_to_the_interfaces_own():
    """Omitting ``--max-tokens`` leaves the request's own default untouched."""
    transport = _transport(_ok(_anthropic_answer()))
    main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport, emit=lambda _: None)
    assert _sent_body(transport)["max_tokens"] == Request(
        messages=(Message("user", "x"),), model="m"
    ).max_tokens


def test_max_tokens_is_forwarded_when_given():
    """``--max-tokens`` is read as an int and sent on the wire."""
    transport = _transport(_ok(_anthropic_answer()))
    main(
        ["--pin", PIN, "--max-tokens", "16"],
        env={ANTHROPIC_KEY_ENV: FAKE_KEY},
        transport=transport,
        emit=lambda _: None,
    )
    assert _sent_body(transport)["max_tokens"] == 16


def test_content_is_truncated_to_the_preview_length():
    """A long answer's summary line carries only the first 200 characters."""
    long_text = "a" * 300
    transport = _transport(_ok(_anthropic_answer(text=long_text)))
    lines: list[str] = []
    main(
        ["--pin", PIN],
        env={ANTHROPIC_KEY_ENV: FAKE_KEY},
        transport=transport,
        emit=lines.append,
    )
    payload = json.loads(lines[0])
    assert payload["content"] == long_text[:CONTENT_PREVIEW_LENGTH]
    assert len(payload["content"]) == CONTENT_PREVIEW_LENGTH


# ── --record: the exchange becomes a fixture ────────────────────────────────


def test_record_files_the_checked_exchange_as_a_fixture(tmp_path):
    """``--record DIR`` writes the request and completion through FixtureStore."""
    transport = _transport(_ok(_anthropic_answer()))
    record_dir = tmp_path / "fixtures"
    code = main(
        ["--pin", PIN, "--record", str(record_dir)],
        env={ANTHROPIC_KEY_ENV: FAKE_KEY},
        transport=transport,
        emit=lambda _: None,
    )
    assert code == 0
    files = FixtureStore(record_dir).files()
    assert len(files) == 1
    assert files[0].request.model == "claude-opus-5"
    assert files[0].completion.content == "ok"
    assert files[0].completion.model == "claude-opus-5"


def test_without_record_nothing_is_filed(tmp_path):
    """No ``--record`` means no directory is touched at all."""
    transport = _transport(_ok(_anthropic_answer()))
    record_dir = tmp_path / "fixtures"
    main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport, emit=lambda _: None)
    assert not record_dir.exists()


def test_a_mismatch_is_never_recorded(tmp_path):
    """A served-model refusal happens before the exchange would be filed."""
    transport = _transport(_ok(_anthropic_answer(model="some-other-model")))
    record_dir = tmp_path / "fixtures"
    code = main(
        ["--pin", PIN, "--record", str(record_dir)],
        env={ANTHROPIC_KEY_ENV: FAKE_KEY},
        transport=transport,
        emit=lambda _: None,
    )
    assert code == 1
    assert not record_dir.exists()


# ── Exit 1: any ProviderError, one stderr line ──────────────────────────────


def test_served_model_mismatch_exits_1_naming_both_models(capsys):
    """The §14.1 finding: a vendor serving a model the pin never named."""
    transport = _transport(_ok(_anthropic_answer(model="deepseek-chat")))
    code = main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport, emit=lambda _: None)
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("served_model_mismatch:")
    assert "claude-opus-5" in err and "deepseek-chat" in err


def test_missing_credential_exits_1_naming_the_variable(capsys):
    """No vendor key is a ProviderNotConfiguredError, not a crash."""
    code = main(["--pin", PIN], env={}, transport=_transport(), emit=lambda _: None)
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("ProviderNotConfiguredError:")
    assert ANTHROPIC_KEY_ENV in err


def test_vendor_http_refusal_exits_1_with_its_own_code(capsys):
    """A non-retryable vendor status is refused with the door's own code."""
    transport = _transport(
        (400, {}, json.dumps({"error": {"message": "bad request shape"}}).encode())
    )
    code = main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport, emit=lambda _: None)
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("provider_http:")
    assert "bad request shape" in err


# ── Exit 2: bad arguments ───────────────────────────────────────────────────


def test_missing_pin_exits_2():
    """``--pin`` is required; omitting it is argparse's own door."""
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2


def test_malformed_pin_exits_2():
    """A pin that is not a clean provider/model/version triple is a bad argument."""
    with pytest.raises(SystemExit) as caught:
        main(["--pin", "deepseek-chat"])
    assert caught.value.code == 2


def test_non_integer_max_tokens_exits_2():
    """``--max-tokens`` is parsed as an int; anything else is a bad argument."""
    with pytest.raises(SystemExit) as caught:
        main(["--pin", PIN, "--max-tokens", "not-a-number"])
    assert caught.value.code == 2


# ── The key never reaches a rendering ───────────────────────────────────────


def test_the_key_never_reaches_stdout_on_success(capsys):
    """A successful run's real stdout carries the summary, never the key."""
    transport = _transport(_ok(_anthropic_answer()))
    main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport)
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err
    assert "claude-opus-5" in captured.out


def test_the_key_never_reaches_stdout_or_stderr_on_refusal(capsys):
    """A refused run's stderr line names the refusal, never the key."""
    transport = _transport(_ok(_anthropic_answer(model="another-model")))
    main(["--pin", PIN], env={ANTHROPIC_KEY_ENV: FAKE_KEY}, transport=transport)
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err


def test_env_defaults_to_os_environ(monkeypatch):
    """``env=None`` reads the process environment at call time, as live_provider does."""
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, FAKE_KEY)
    transport = _transport(_ok(_anthropic_answer()))
    code = main(["--pin", PIN], transport=transport, emit=lambda _: None)
    assert code == 0
