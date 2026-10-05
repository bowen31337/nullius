"""Feature 3 (Hardened Child): the hostile-signal suite.

additions_spec_gvisor_executor.xml, "Hardened Child", feature 3: *System
emits a contained, named result for every hostile signal in the hardened
sandbox, as shown by orchestrator tests/test_hostile_signals.py with real
subprocesses. Each case answers its named fail_class, or a clean result, and
leaves no side effect on the host*:

* reading ``os.environ``, with secrets planted in the parent's environment:
  the child sees none, and ``import os`` is refused;
* opening a planted host file or a planted lake path: refused (no open);
* a socket connection: ``import socket`` is refused;
* printing a forged success line to stdout: ignored, and the real result
  stands;
* an infinite loop: timeout;
* allocating 10 GB: oom;
* forking repeatedly: refused or killed, and the parent survives;
* reading the wall clock (``import time`` or ``datetime.now``): refused by
  the guard;
* a signal that writes a sentinel file at module level: no file appears;
* a benign momentum signal: scores, identical across two runs.

Every case runs through :class:`orchestrator._hardened_sandbox.
HardenedSubprocessSandbox` against a real child subprocess (the same
discipline ``test_sandbox_child.py`` and ``test_hardened_sandbox.py`` already
apply to features 1 and 2) rather than calling the bootstrap's internals
directly, because feature 3's own claim is about the contained *result* a
hostile signal produces end to end, launcher included.

**Why ``import time``, not ``datetime.now``, is the wall-clock case actually
exercised.**  ``datetime`` is on the committed agent allowlist
(``packages/sandbox/src/sandbox/imports_allowlist.json``) — a datetime built
from explicit arguments is a deterministic value, so the *module* is
admitted.  The allowlist's own committed comment is explicit that the
*call-level* floor, "the clock constructors inside them (``datetime.now``,
unseeded draws) are policed at the search seam by feature 139's floor" — a
different member, outside this spec's scope (``packages/sandbox/src/
sandbox/imports.py``'s own module docstring: "this member deliberately holds
no copy of that floor"). So a signal that imports ``datetime`` and calls
``.now()`` is not refused by this guard at all; it runs, and fails the
*contract* instead (``not_a_series``, since ``datetime.now()`` is not a
``polars.Series``) — a different fail_class than the one this guard's own
refusal carries. ``time`` has no sanctioned spelling at all — it is absent
from the ceiling outright — so ``import time`` is the wall-clock read this
guard actually refuses, and is what :func:`test_reading_the_wall_clock_via_import_time_is_refused`
exercises.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory; no third-party dependency is added.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
import time
from pathlib import Path

import pyarrow as pa
import pytest
from contract.window import MarketWindow
from orchestrator._hardened_sandbox import HardenedLimits, HardenedSubprocessSandbox

_UNIVERSE = ("AAA", "BBB")


def _window(universe: tuple[str, ...] = _UNIVERSE) -> MarketWindow:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({sym: [1.0] for sym in universe})}
    return MarketWindow(t, universe=universe, frames=frames)


def _fast_limits(**overrides: object) -> HardenedLimits:
    """A limits object that keeps the suite fast — see ``test_hardened_sandbox.py``'s
    own helper of the same name for why 4096 MiB (not a tighter cap) is the
    production memory figure: polars needs real address space just to import.
    """
    base: dict[str, object] = {"cpu_s": 10.0, "runner_mem_mb": 4096, "pids": 64, "wall_s": 10.0}
    base.update(overrides)
    return HardenedLimits(**base)


# -- reading os.environ, with secrets planted in the parent's environment ----


def test_planted_environment_secret_is_unreachable_and_import_os_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Planted in *this* process's environment — the parent the launcher
    # spawns from — so the only way the secret could leak is if the child's
    # environment were copied rather than built fresh (feature 2) or if
    # `import os` slipped past the guard.
    monkeypatch.setenv("NULLIUS_TEST_SECRET", "do-not-leak")
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import os\ndef signal(ctx, seed):\n    return os.environ.get('NULLIUS_TEST_SECRET')\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert "'os'" in result.detail
    assert result.scores is None


# -- opening a planted host file or a planted lake path: refused (no open) ---


def test_planted_host_file_is_refused_and_never_opened(tmp_path: Path) -> None:
    secret_file = tmp_path / "host_secret.txt"
    secret_file.write_text("do-not-leak")
    code = textwrap.dedent(
        f"""
        def signal(ctx, seed):
            f = open({str(secret_file)!r})
            return None
        """
    )
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "open" in result.detail
    assert result.scores is None
    assert secret_file.read_text() == "do-not-leak"  # untouched: open never ran


def test_planted_lake_path_is_refused_and_never_opened(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    lake_dir.mkdir()
    lake_file = lake_dir / "trades.parquet"
    lake_file.write_bytes(b"not-really-parquet-but-planted")
    code = textwrap.dedent(
        f"""
        def signal(ctx, seed):
            f = open({str(lake_file)!r}, 'rb')
            return None
        """
    )
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "open" in result.detail
    assert result.scores is None
    assert lake_file.read_bytes() == b"not-really-parquet-but-planted"  # untouched


# -- a socket connection: `import socket` is refused --------------------------


def test_socket_connection_is_refused_naming_socket() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = (
        "import socket\n"
        "def signal(ctx, seed):\n"
        "    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    return None\n"
    )
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert "'socket'" in result.detail
    assert result.scores is None


# -- a forged success line on stdout is ignored; the real result stands ------


def test_forged_stdout_success_line_is_ignored_and_the_real_result_stands() -> None:
    forged = json.dumps(
        {"fail_class": None, "detail": "", "scores": "Zm9yZ2Vk", "contract_version": "evil"}
    )
    code = (
        "import polars as pl\n"
        f"print({forged!r})\n"
        "def signal(ctx, seed):\n"
        "    return pl.Series([float(len(sym)) for sym in ctx.universe])\n"
    )
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class is None
    assert result.ok
    assert result.contract_version != "evil"
    assert result.scores.to_list() == [3.0, 3.0]  # len("AAA"), len("BBB") — the real result


# -- an infinite loop: timeout -------------------------------------------------


def test_an_infinite_loop_is_killed_at_the_wall_and_named_timeout() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits(cpu_s=30.0, wall_s=1.0))
    code = "def signal(ctx, seed):\n    while True:\n        pass\n"
    started = time.monotonic()
    result = sandbox_instance.run(code, _window(), seed=1)
    elapsed = time.monotonic() - started

    assert result.fail_class == "timeout"
    assert result.scores is None
    assert elapsed < 10.0  # killed promptly, not left to hang


# -- allocating 10 GB: oom -----------------------------------------------------


def test_allocating_ten_gigabytes_is_a_clean_oom() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "def signal(ctx, seed):\n    x = bytearray(10 * 1024 ** 3)\n    return None\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "oom"
    assert result.scores is None


# -- forking repeatedly: refused, and the parent survives ---------------------


def test_repeated_forking_is_refused_and_the_parent_survives() -> None:
    # `os` is outside the committed allowlist, so a fork bomb cannot even get
    # as far as its first os.fork(): the import itself is refused before a
    # child is spawned at all.
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import os\ndef signal(ctx, seed):\n    for _ in range(50):\n        os.fork()\n    return None\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert "'os'" in result.detail

    # The parent survives: this same launcher can still run another signal
    # afterward, in this same test process.
    follow_up = sandbox_instance.run(_BENIGN, _window(), seed=7)
    assert follow_up.fail_class is None
    assert follow_up.scores.to_list() == [3.0, 3.0]


# -- reading the wall clock: `import time` is refused by the guard -----------


def test_reading_the_wall_clock_via_import_time_is_refused() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import time\ndef signal(ctx, seed):\n    return time.time()\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert "'time'" in result.detail
    assert result.scores is None


def test_datetime_now_is_out_of_this_guards_scope_and_fails_the_contract_instead() -> None:
    # `datetime` itself is on the committed allowlist (a datetime built from
    # explicit arguments is a deterministic value), so this import is
    # admitted — the call-level floor on `.now()` is a different member's law
    # (see the module docstring). The read still never reaches the caller as
    # a usable wall-clock value: it fails the signal contract instead, as
    # `violation`, because `datetime.now()` is not a `polars.Series`.
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import datetime\ndef signal(ctx, seed):\n    return datetime.datetime.now()\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "violation"
    assert result.scores is None


# -- a sentinel file written at module level: no file appears -----------------


def test_module_level_sentinel_write_leaves_no_file(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel_should_not_appear.txt"
    code = textwrap.dedent(
        f"""
        open({str(sentinel)!r}, 'w').write('pwned')

        def signal(ctx, seed):
            return None
        """
    )
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "open" in result.detail
    assert not os.path.exists(sentinel)


# -- a benign momentum signal: scores, identical across two runs -------------

_BENIGN = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([float(len(sym)) for sym in ctx.universe])
"""


def test_benign_momentum_signal_scores_identically_across_two_runs() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result_1 = sandbox_instance.run(_BENIGN, _window(), seed=7)
    result_2 = sandbox_instance.run(_BENIGN, _window(), seed=7)

    for result in (result_1, result_2):
        assert result.fail_class is None
        assert result.ok
        assert result.scores is not None

    assert result_1.scores.to_list() == [3.0, 3.0]  # len("AAA"), len("BBB")
    assert result_1.scores.to_list() == result_2.scores.to_list()
