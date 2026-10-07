"""bug_spec_first_scored_campaign.xml, "native lazy imports": the sandbox
child's import guard must admit a stdlib import a trusted dependency's own
native (Rust, via PyO3) code triggers lazily, even when that native call
leaves no trusted Python frame — or no Python frame at all — on the stack for
``orchestrator._sandbox_child._trusted_root_in_stack`` to find.

Root cause (see ``_sandbox_child.py``'s module docstring and
``_trusted_root_in_stack``'s own docstring for the full argument): polars'
Rust core calls CPython's ``PyImport_Import`` directly, which reaches this
process's patched ``builtins.__import__`` straight from native code, with no
Python frame belonging to ``polars``/``pyarrow``/``contract`` interposed —
sometimes with *no* Python frame at all, when the call happens on a thread
the dependency's own parallelism started. Before the fix,
``_trusted_root_in_stack`` returned ``False`` whenever its walk ran out of
frames without finding a trusted root, and ``_admit`` returned ``False`` when
``sys._getframe(2)`` had no frame to find at all — both misreading "found no
evidence this is the agent" as "refuse" rather than as the only thing it can
mean: an import the agent's own (always Python-frame-bearing) code could
never have triggered.

Two kinds of test here:

* a real signal, run through the actual child subprocess exactly as feature
  2's hardened executor will invoke it, exercising polars operations whose
  native lazy-import paths are named in the bug (repr/format, string
  casting, an Arrow round trip) — proving the fix does not regress ordinary
  signals, and that a signal's own direct ``import os``/``import io`` is
  still refused;
* a direct, deterministic reproduction of the refused-native-import shape
  itself, run in its own ``-I`` subprocess against the real (unmodified)
  ``orchestrator._sandbox_child`` guard functions: a bare OS thread (via
  ``_thread.start_new_thread``, which calls its target directly with no
  Python frame scaffolding — precisely the shape PyO3's own native-to-Python
  call takes) requesting a term outside the agent's ceiling. This is the
  regression test for the bug itself: it fails before the fix (the import is
  refused) and passes after (the import succeeds), independent of which
  polars operation happens to schedule a lazy import on a background thread
  in any given polars release.

No test opens a network connection or writes outside a pytest temporary
directory; no third-party dependency is added.
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
from contract.payload import serialize_window
from contract.window import MarketWindow
from orchestrator import _sandbox_child as child

CHILD_PATH = Path(child.__file__)


def _window_payload(universe: tuple[str, ...] = ("AAA", "BBB")) -> bytes:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({symbol: [1.0] for symbol in universe})}
    window = MarketWindow(t, universe=universe, frames=frames)
    return bytes(serialize_window(window))


def _spawn(stdin_bytes: bytes, *, timeout: float = 30.0) -> tuple[int, bytes, bytes]:
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
    timeout: float = 30.0,
) -> tuple[dict, int, bytes]:
    request = child.encode_request(source=source, seed=seed, window_payload=_window_payload(universe))
    frame = struct.pack("<Q", len(request)) + request
    returncode, out, err = _spawn(frame, timeout=timeout)
    return _decode_result_frame(out), returncode, err


# -- real signals through the real child subprocess --------------------------


def test_native_lazy_import_paths_are_admitted_through_the_real_child() -> None:
    # repr/format, string casting, and an Arrow round trip are the three
    # shapes the bug names as exercising polars' native lazy-import paths.
    # None of them is special-cased by the fix (it changes only the guard's
    # admission logic, never AGENT_IMPORTS_ALLOWLIST) — this pins that a
    # conforming signal using them scores cleanly rather than crashing with
    # disallowed_import partway through evaluation.
    source = textwrap.dedent(
        """
        import polars as pl

        def signal(ctx, seed):
            s = pl.Series([float(len(sym)) for sym in ctx.universe])
            _ = repr(s)
            _ = str(s)
            df = pl.DataFrame({"x": s})
            _ = repr(df)
            _ = str(df)
            casted = s.cast(pl.Utf8).cast(pl.Float64)
            roundtripped = pl.from_arrow(df.to_arrow())
            return roundtripped.get_column("x") + (casted - casted)
        """
    )
    result, rc, err = run_signal(source, universe=("AAA", "BBBB"))
    assert rc == 0
    assert err == b""
    assert result["fail_class"] is None, result["detail"]
    decoded = json.loads(base64.b64decode(result["scores"]).decode("utf-8"))
    assert decoded == [3.0, 4.0]


def test_direct_import_os_is_still_refused_through_the_real_child() -> None:
    source = "import os\ndef signal(ctx, seed):\n    return None\n"
    result, rc, err = run_signal(source)
    assert rc == 0
    assert err == b""
    assert result["fail_class"] == "crash"
    assert "disallowed_import" in result["detail"]
    assert "'os'" in result["detail"]
    assert result["scores"] is None


def test_direct_import_io_is_still_refused_through_the_real_child() -> None:
    source = "import io\ndef signal(ctx, seed):\n    return None\n"
    result, rc, err = run_signal(source)
    assert rc == 0
    assert err == b""
    assert result["fail_class"] == "crash"
    assert "disallowed_import" in result["detail"]
    assert "'io'" in result["detail"]
    assert result["scores"] is None


def test_direct_import_sys_and_socket_are_still_refused_through_the_real_child() -> None:
    for name in ("sys", "socket"):
        source = f"import {name}\ndef signal(ctx, seed):\n    return None\n"
        result, rc, err = run_signal(source)
        assert rc == 0
        assert err == b""
        assert result["fail_class"] == "crash"
        assert "disallowed_import" in result["detail"]
        assert f"'{name}'" in result["detail"]


# -- the bug itself: an import with no agent frame on the stack --------------
#
# ``_thread.start_new_thread`` calls its target directly as the very first
# frame on a brand-new OS thread, with no ``Thread``-class bootstrap frames
# in between — the same shape PyO3 produces when polars' native core acquires
# the GIL fresh on a thread it started itself and calls straight into
# ``PyImport_Import``. Run inside its own ``-I`` subprocess (matching the real
# child's own invocation flags) against the unmodified guard functions, not a
# reimplementation, so this is a true regression test against the shipped
# code: it fails before the fix (refused) and passes after (admitted).

_NATIVE_IMPORT_HARNESS = """
import sys, _thread, time, builtins
from orchestrator import _sandbox_child as child
import polars  # a real trusted root, loaded before the guard goes up

child._install_import_guard()

outcome = {{"admitted": True, "detail": ""}}

# A thread ``_thread.start_new_thread`` spawns has no ``Thread``-class
# bootstrap frames; an uncaught exception from its target is reported through
# ``sys.unraisablehook`` rather than propagating anywhere this process can
# ``except`` directly, so that hook is how the bare-entrypoint case (where the
# target *is* ``builtins.__import__`` itself, with nothing of ours in between
# to wrap a ``try`` around) observes a refusal.
def _unraisable(unraisable):
    outcome["admitted"] = False
    outcome["detail"] = str(unraisable.exc_value)

sys.unraisablehook = _unraisable

def worker():
    try:
        builtins.__import__({name!r}, None, None, (), 0)
    except ImportError as exc:
        outcome["admitted"] = False
        outcome["detail"] = str(exc)

{spawn_line}
time.sleep(1.0)
print("ADMITTED" if outcome["admitted"] else "REFUSED:" + outcome["detail"])
"""


def _run_native_import_harness(name: str, *, bare_entrypoint: bool) -> str:
    # bare_entrypoint=True puts ``builtins.__import__`` itself as the thread's
    # target (zero Python frames below the call: ``_admit``'s
    # ``sys._getframe(2)`` has nothing to find). bare_entrypoint=False wraps
    # it in one native-ish trampoline frame first (``worker``'s own frame
    # exists, but it is neither a trusted root nor the signal source) — the
    # other shape the fix must also admit.
    if bare_entrypoint:
        spawn_line = f"_thread.start_new_thread(builtins.__import__, ({name!r}, None, None, (), 0))"
    else:
        spawn_line = "_thread.start_new_thread(worker, ())"
    script = _NATIVE_IMPORT_HARNESS.format(name=name, spawn_line=spawn_line)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout.decode("utf-8").strip()


def test_import_with_zero_python_frames_is_admitted_for_a_native_term() -> None:
    assert _run_native_import_harness("_io", bare_entrypoint=True) == "ADMITTED"


def test_import_via_a_bare_native_trampoline_frame_is_admitted_for_a_native_term() -> None:
    assert _run_native_import_harness("io", bare_entrypoint=False) == "ADMITTED"
