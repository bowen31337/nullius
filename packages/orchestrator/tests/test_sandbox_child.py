"""Feature 1 (Hardened Child): the sandbox child bootstrap, run as a real
subprocess.

additions_spec_gvisor_executor.xml, "Hardened Child", feature 1: the
bootstrap at ``orchestrator/_sandbox_child.py``, run as ``python -I
_sandbox_child.py``, reads one length-framed request on stdin (the signal
source, the seed, the NLSWIPC window payload), runs the signal under an
import guard and a restricted builtins namespace, and writes exactly one
framed JSON result to a private descriptor — never to stdout.

These tests drive the bootstrap exactly as its eventual caller (feature 2's
hardened subprocess executor) will: a plain ``subprocess.Popen`` with framed
bytes on stdin, reading the framed result back off the process's stdout pipe
(the "private descriptor" the bootstrap writes to is a duplicate of the
*original* fd 1 — the same pipe this test's ``stdout=subprocess.PIPE``
already reads — so no special fd plumbing is needed on this side; see
``orchestrator._sandbox_child``'s module docstring).

One test per claim the feature sentence makes:

* a conforming signal scores, deterministically, across two runs;
* an import outside the committed ceiling never executes, and the refusal
  names ``disallowed_import``;
* ``open``/``eval``/``exec`` are gone from the signal's builtins;
* a signal that raises, defines no entrypoint, or returns the wrong shape is
  classified ``crash``/``violation`` rather than crashing the bootstrap;
* a forged ``print`` to stdout cannot reach or corrupt the result channel;
* a malformed request, or a request whose window segment is not a window,
  answers ``fail_class="payload"``;
* the committed agent allowlist this module carries agrees, term for term,
  with ``packages/sandbox/src/sandbox/imports_allowlist.json``.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory; no third-party dependency is added.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pyarrow as pa
import pytest
from contract.payload import serialize_window
from contract.window import MarketWindow
from orchestrator import _sandbox_child as child

CHILD_PATH = Path(child.__file__)
_SANDBOX_ALLOWLIST_PATH = (
    Path(__file__).resolve().parents[2] / "sandbox" / "src" / "sandbox" / "imports_allowlist.json"
)


def _window_payload(universe: tuple[str, ...] = ("AAA", "BBB")) -> bytes:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({symbol: [1.0] for symbol in universe})}
    window = MarketWindow(t, universe=universe, frames=frames)
    return bytes(serialize_window(window))


def _spawn(stdin_bytes: bytes, *, timeout: float = 20.0) -> tuple[int, bytes, bytes]:
    proc = subprocess.Popen(
        [sys.executable, "-I", str(CHILD_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate(input=stdin_bytes, timeout=timeout)
    return proc.returncode, out, err


def _decode_result_frame(out: bytes) -> dict:
    assert len(out) >= 8, f"expected at least an 8-byte length prefix, got {len(out)} byte(s)"
    (length,) = struct.unpack("<Q", out[:8])
    assert len(out) == 8 + length, "the child must write exactly one frame and nothing else"
    return json.loads(out[8 : 8 + length])


def run_signal(
    source: str,
    *,
    seed: int = 7,
    universe: tuple[str, ...] = ("AAA", "BBB"),
    timeout: float = 20.0,
) -> tuple[dict, int, bytes]:
    """Run ``source`` as a signal through a real child subprocess.

    Returns ``(result, returncode, stderr)`` so a test can assert on the
    envelope while still being able to inspect the process's own exit and
    stderr for cases that should be entirely silent.
    """
    request = child.encode_request(source=source, seed=seed, window_payload=_window_payload(universe))
    frame = struct.pack("<Q", len(request)) + request
    returncode, out, err = _spawn(frame, timeout=timeout)
    return _decode_result_frame(out), returncode, err


# -- wire format (unit-level) -------------------------------------------------


def test_request_round_trips() -> None:
    payload = _window_payload()
    body = child.encode_request(source="def signal(ctx, seed):\n    return None\n", seed=42, window_payload=payload)
    request = child.decode_request(body)
    assert request.seed == 42
    assert "def signal" in request.source
    assert request.window_payload == payload


def test_framed_read_write_round_trip() -> None:
    import io

    buf = io.BytesIO()
    child.write_framed(buf.write, b"hello world")
    buf.seek(0)
    assert child.read_framed(buf.read) == b"hello world"


def test_decode_request_refuses_short_header() -> None:
    with pytest.raises(child.ChildRequestError):
        child.decode_request(b"\x00\x01\x02\x03")


def test_decode_request_refuses_bad_magic() -> None:
    body = child.encode_request(source="x = 1\n", seed=1, window_payload=b"abc")
    corrupted = b"XXXXXXXX" + body[8:]
    with pytest.raises(child.ChildRequestError):
        child.decode_request(corrupted)


# -- the agent import ceiling, pinned against sandbox's committed document ---


def test_agent_allowlist_matches_committed_sandbox_document() -> None:
    document = json.loads(_SANDBOX_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert document["policy"] == "sandbox-imports"
    assert set(document["allow"]) == set(child.AGENT_IMPORTS_ALLOWLIST)


# -- end-to-end: a real subprocess, framed requests --------------------------


_BENIGN_MOMENTUM = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([float(len(sym)) for sym in ctx.universe])
"""


def test_benign_signal_scores_and_is_deterministic() -> None:
    result_1, rc_1, err_1 = run_signal(_BENIGN_MOMENTUM, universe=("AAA", "BBBB"))
    result_2, rc_2, err_2 = run_signal(_BENIGN_MOMENTUM, universe=("AAA", "BBBB"))

    for result, rc, err in ((result_1, rc_1, err_1), (result_2, rc_2, err_2)):
        assert rc == 0
        assert err == b""
        assert result["fail_class"] is None
        assert result["detail"] == ""
        assert result["contract_version"] == "0.1.0"

    # The scores field is base64 of a JSON array of floats, positional
    # against the window's universe — decode it and check the actual
    # values, not just that two runs agree with each other.
    decoded = json.loads(base64.b64decode(result_1["scores"]).decode("utf-8"))
    assert decoded == [3.0, 4.0]  # len("AAA"), len("BBBB")
    assert result_1["scores"] == result_2["scores"]


def test_disallowed_import_is_refused_and_named() -> None:
    source = "import os\ndef signal(ctx, seed):\n    return None\n"
    result, rc, err = run_signal(source)
    assert rc == 0
    assert err == b""
    assert result["fail_class"] == "crash"
    assert "disallowed_import" in result["detail"]
    assert "'os'" in result["detail"]
    assert result["scores"] is None


def test_os_environ_is_unreachable_even_with_planted_secrets() -> None:
    # `import os` is refused outright, so a signal cannot reach os.environ at
    # all — planting a secret in the subprocess's own environment and
    # asserting the refusal still names `disallowed_import` (not some other
    # failure) is the check that the guard, not luck, is what stopped it.
    import os as _os

    source = "import os\ndef signal(ctx, seed):\n    return os.environ.get('NULLIUS_TEST_SECRET')\n"
    request = child.encode_request(source=source, seed=1, window_payload=_window_payload())
    frame = struct.pack("<Q", len(request)) + request
    proc = subprocess.Popen(
        [sys.executable, "-I", str(CHILD_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**_os.environ, "NULLIUS_TEST_SECRET": "do-not-leak"},
    )
    out, _err = proc.communicate(input=frame, timeout=20)
    result = _decode_result_frame(out)
    assert result["fail_class"] == "crash"
    assert "disallowed_import" in result["detail"]


@pytest.mark.parametrize("builtin_name", ["open", "exec", "eval", "compile", "input", "breakpoint"])
def test_dangerous_builtins_are_absent(builtin_name: str) -> None:
    source = f"def signal(ctx, seed):\n    {builtin_name}\n    return None\n"
    result, _rc, _err = run_signal(source)
    assert result["fail_class"] == "crash"
    assert f"'{builtin_name}' is not defined" in result["detail"] or "NameError" in result["detail"]


def test_signal_that_raises_is_a_crash() -> None:
    source = "def signal(ctx, seed):\n    raise ValueError('boom')\n"
    result, _rc, _err = run_signal(source)
    assert result["fail_class"] == "crash"
    assert "boom" in result["detail"]


def test_missing_entrypoint_is_a_crash() -> None:
    result, _rc, _err = run_signal("x = 1\n")
    assert result["fail_class"] == "crash"
    assert "signal" in result["detail"]


def test_non_callable_entrypoint_is_a_crash() -> None:
    result, _rc, _err = run_signal("signal = 42\n")
    assert result["fail_class"] == "crash"


def test_wrong_length_return_is_a_violation() -> None:
    source = "import polars as pl\ndef signal(ctx, seed):\n    return pl.Series([1.0])\n"
    result, _rc, _err = run_signal(source, universe=("AAA", "BBB"))
    assert result["fail_class"] == "violation"
    problems = json.loads(result["detail"])
    assert problems and problems[0]["kind"] == "wrong_length"


def test_non_series_return_is_a_violation() -> None:
    source = "def signal(ctx, seed):\n    return [1.0, 2.0]\n"
    result, _rc, _err = run_signal(source)
    assert result["fail_class"] == "violation"
    problems = json.loads(result["detail"])
    assert problems and problems[0]["kind"] == "not_a_series"


def test_forged_stdout_print_cannot_reach_the_result_channel() -> None:
    forged = json.dumps({"fail_class": None, "detail": "", "scores": "Zm9yZ2Vk", "contract_version": "evil"})
    source = (
        "import polars as pl\n"
        f"print({forged!r})\n"
        "def signal(ctx, seed):\n"
        "    return pl.Series([1.0, 2.0])\n"
    )
    result, _rc, _err = run_signal(source)
    assert result["fail_class"] is None
    assert result["contract_version"] != "evil"
    assert result["scores"] != "Zm9yZ2Vk"


def test_redirect_stdio_moves_both_fd_1_and_fd_2_to_devnull() -> None:
    # A focused, process-isolated check on the fd dance itself: fd 2 (not
    # just fd 1) must land on /dev/null, and the *duplicated* descriptor —
    # not fd 1 itself — is what still reaches this test's stdout pipe. Run
    # in its own subprocess (not in-process) so it cannot touch the test
    # runner's own stdio.
    probe = textwrap.dedent(
        """
        import os
        from orchestrator._sandbox_child import _redirect_stdio

        result_fd = _redirect_stdio()
        os.write(2, b"stderr-should-vanish")
        os.write(1, b"fd1-should-vanish-too")
        os.write(result_fd, b"MARKER")
        os.close(result_fd)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", probe],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate(timeout=20)
    assert out == b"MARKER"
    assert err == b""


def test_malformed_request_bytes_answer_payload_fail_class() -> None:
    _returncode, out, _err = _spawn(struct.pack("<Q", 4) + b"\x00\x01\x02\x03")
    result = _decode_result_frame(out)
    assert result["fail_class"] == "payload"


def test_window_payload_that_is_not_a_window_answers_payload_fail_class() -> None:
    request = child.encode_request(
        source="def signal(ctx, seed):\n    return None\n",
        seed=1,
        window_payload=b"not a window payload",
    )
    frame = struct.pack("<Q", len(request)) + request
    _returncode, out, _err = _spawn(frame)
    result = _decode_result_frame(out)
    assert result["fail_class"] == "payload"


def test_empty_stdin_answers_payload_fail_class() -> None:
    _returncode, out, _err = _spawn(b"")
    result = _decode_result_frame(out)
    assert result["fail_class"] == "payload"
