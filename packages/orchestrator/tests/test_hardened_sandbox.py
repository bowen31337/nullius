"""Feature 2 (Hardened Child): the hardened subprocess executor.

additions_spec_gvisor_executor.xml, "Hardened Child", feature 2:
*System creates each signal's result in a hardened subprocess with
orchestrator._hardened_sandbox.HardenedSubprocessSandbox(limits=None). It is a
drop-in for execute_signal's sandbox argument: run(code, window, *, seed)
answers an object with scores, problems, seed, contract_version, fail_class
and detail.*

One test per claim the feature sentence makes, against real subprocesses
(the same discipline ``test_sandbox_child.py`` applies to feature 1):

* a benign signal scores, deterministically, through a real child;
* a disallowed import never spawns a process, and answers ``fail_class
  "crash"`` naming ``disallowed_import``;
* the environment handed to the child is exactly the six keys the feature
  names — built fresh, not copied from a planted ``os.environ`` secret;
* a signal that raises, or returns the wrong shape, is ``crash``/``violation``
  rather than raised to the caller;
* a signal that exhausts its address space is ``oom``, as a clean envelope;
* a signal that never yields is killed at the wall and named ``timeout``;
* a signal that exhausts its CPU budget dies to ``SIGXCPU`` with no envelope,
  and the launcher — not the child, which installs no handler — is what
  names that ``timeout``;
* the silent-death classifier itself, unit-tested against synthetic
  ``returncode``s, since reliably forcing a real ``SIGSEGV``/``SIGBUS`` out of
  ``RLIMIT_AS`` is not portable.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory; no third-party dependency is added.
"""

from __future__ import annotations

import datetime as dt
import shutil
import signal
import subprocess
import sys
import time

import pyarrow as pa
import pytest
from contract.window import MarketWindow
from evaluator import EvaluatorSandboxError, SandboxResult
from orchestrator import _hardened_sandbox as hs
from orchestrator._hardened_sandbox import HardenedLimits, HardenedSubprocessSandbox

#: SEC-1: HardenedSubprocessSandbox has no bare-subprocess fallback — every
#: construction resolves bwrap (bug_spec_unisolated_os_boundary.xml) and
#: raises when it is missing, so a host without it skips this whole module
#: with a reason, the same discipline test_gvisor_runsc.py gives its own
#: real-runsc dependency, rather than failing every test here.
pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is not on PATH")

_UNIVERSE = ("AAA", "BBB")


def _window(universe: tuple[str, ...] = _UNIVERSE) -> MarketWindow:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({sym: [1.0] for sym in universe})}
    return MarketWindow(t, universe=universe, frames=frames)


def _fast_limits(**overrides: object) -> HardenedLimits:
    """A limits object that keeps the suite fast: a short wall and CPU budget,
    the production memory cap (polars needs real address space to import —
    see ``evaluator._sandbox.DEFAULT_MEM_MB``'s own comment) and a generous
    pid headroom so the suite is not sensitive to how busy the host is.
    """
    base: dict[str, object] = {"cpu_s": 10.0, "runner_mem_mb": 4096, "pids": 64, "wall_s": 10.0}
    base.update(overrides)
    return HardenedLimits(**base)


# -- construction: limits default to the sandbox member's own policies -------


def test_default_limits_come_from_the_sandbox_member_policies() -> None:
    import sandbox

    sandbox_instance = HardenedSubprocessSandbox()
    budget = sandbox.committed_budget_policy()
    timeout = sandbox.committed_timeout_policy()
    assert sandbox_instance.limits == HardenedLimits(
        cpu_s=budget.value("cpu_s"),
        runner_mem_mb=sandbox.RUNNER_MEM_MB,
        pids=budget.value("pids"),
        wall_s=timeout.wall_s,
    )


# -- the environment is built from scratch -----------------------------------


def test_child_env_is_exactly_the_six_named_keys() -> None:
    import sandbox

    pins = sandbox.sandbox_threads().pins()
    env = hs._child_env(42, pins=pins)
    assert env == {
        "PATH": "/usr/bin:/bin",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "POLARS_MAX_THREADS": "1",
        "PYTHONHASHSEED": "0",
        "NULLIUS_SIGNAL_SEED": "42",
    }


def test_planted_host_secret_never_reaches_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    # The environment is never copied from os.environ, so a secret planted in
    # the parent's own environment cannot leak even through a signal that
    # tries to read it — and `import os` is refused before anything spawns,
    # so this is refused for the same reason test_sandbox_child.py's own
    # planted-secret test is: the guard, not luck, is what stops it.
    monkeypatch.setenv("NULLIUS_TEST_SECRET", "do-not-leak")
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import os\ndef signal(ctx, seed):\n    return os.environ.get('NULLIUS_TEST_SECRET')\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail


# -- disallowed imports never spawn -------------------------------------------


def test_disallowed_import_answers_crash_naming_disallowed_import_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_popen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a disallowed import must be refused before any process is spawned")

    monkeypatch.setattr(hs.subprocess, "Popen", _unexpected_popen)
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import os\ndef signal(ctx, seed):\n    return None\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert result.scores is None
    assert result.seed == 1


# -- SEC-1: the child is spawned under bwrap, not as a bare subprocess -------


def test_bwrap_is_required_and_refused_at_construction_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hs.shutil, "which", lambda name: None)
    with pytest.raises(hs.BwrapUnavailableError) as record:
        HardenedSubprocessSandbox(limits=_fast_limits())
    assert str(record.value).startswith(hs.BWRAP_UNAVAILABLE_CODE)
    assert "bwrap" in str(record.value)


def test_the_child_runs_under_bwrap_with_the_sec1_sandbox_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []
    real_popen = hs.subprocess.Popen

    def _capturing_popen(argv: list[str], *args: object, **kwargs: object) -> subprocess.Popen:
        captured.append(list(argv))
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(hs.subprocess, "Popen", _capturing_popen)
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result = sandbox_instance.run(_BENIGN, _window(), seed=7)

    assert result.fail_class is None
    assert len(captured) == 1
    argv = captured[0]

    assert argv[0] == str(sandbox_instance._bwrap)
    assert "bwrap" in argv[0]
    assert "--unshare-all" in argv  # a private user/ipc/pid/net/uts/cgroup namespace
    assert "--die-with-parent" in argv
    assert "--clearenv" in argv
    assert "--proc" in argv and argv[argv.index("--proc") + 1] == "/proc"
    assert "--dev" in argv and argv[argv.index("--dev") + 1] == "/dev"
    assert "--ro-bind" in argv
    assert sys.executable in argv
    assert "-I" in argv
    assert str(hs._CHILD_PATH) in argv

    # The six child env keys still ride as --setenv pairs — never copied
    # from this launcher's own os.environ (feature 2's own promise, now
    # enforced a second time by bwrap's own --clearenv).
    for key in (
        "PATH",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "POLARS_MAX_THREADS",
        "PYTHONHASHSEED",
        "NULLIUS_SIGNAL_SEED",
    ):
        assert key in argv


# -- a benign signal scores, deterministically --------------------------------

_BENIGN = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([float(len(sym)) for sym in ctx.universe])
"""


def test_benign_signal_scores_and_is_deterministic() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result_1 = sandbox_instance.run(_BENIGN, _window(), seed=7)
    result_2 = sandbox_instance.run(_BENIGN, _window(), seed=7)

    for result in (result_1, result_2):
        assert isinstance(result, SandboxResult)
        assert result.fail_class is None
        assert result.ok
        assert result.detail == ""
        assert result.seed == 7
        assert result.contract_version

    assert result_1.scores.to_list() == [3.0, 3.0]  # len("AAA"), len("BBB")
    assert result_1.scores.to_list() == result_2.scores.to_list()


def test_scores_are_positional_against_the_universe() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    result = sandbox_instance.run(_BENIGN, _window(("AAA", "BBBB", "C")), seed=1)
    assert result.scores.to_list() == [3.0, 4.0, 1.0]


# -- the signal contract runs in the child, as values, not raises ------------


def test_a_signal_that_raises_is_a_crash() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "def signal(ctx, seed):\n    raise ValueError('boom')\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "crash"
    assert result.scores is None
    assert "boom" in result.detail


def test_a_wrong_length_return_is_a_violation_with_problems() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import polars as pl\ndef signal(ctx, seed):\n    return pl.Series([1.0])\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "violation"
    assert result.scores is None
    assert [p.kind for p in result.problems] == ["wrong_length"]
    assert all(hasattr(p, "message") for p in result.problems)


def test_a_non_series_return_is_a_violation() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "def signal(ctx, seed):\n    return [1.0, 2.0]\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "violation"
    assert result.problems and result.problems[0].kind == "not_a_series"


# -- resource failures are values, never exceptions ---------------------------


def test_an_address_space_exhausting_signal_is_an_oom() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "def signal(ctx, seed):\n    x = bytearray(10 ** 10)\n    return None\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "oom"
    assert result.scores is None


def test_a_signal_that_never_yields_is_killed_at_the_wall() -> None:
    sandbox_instance = HardenedSubprocessSandbox(
        limits=_fast_limits(cpu_s=30.0, wall_s=1.0)
    )
    code = "def signal(ctx, seed):\n    while True:\n        pass\n"
    started = time.monotonic()
    result = sandbox_instance.run(code, _window(), seed=1)
    elapsed = time.monotonic() - started

    assert result.fail_class == "timeout"
    assert result.scores is None
    assert elapsed < 10.0  # killed promptly, not left to hang


def test_a_cpu_bound_signal_dies_to_sigxcpu_and_is_named_timeout() -> None:
    # The hardened bootstrap installs no SIGXCPU handler (unlike
    # evaluator._sandbox's embedded child), so the kernel kills it outright —
    # the launcher attributes that silent death to the CPU limit rather than
    # leaving it a bare "crash".  The wall is kept well above the CPU budget
    # so the CPU limit is what actually fires.
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits(cpu_s=1.0, wall_s=20.0))
    code = "def signal(ctx, seed):\n    while True:\n        pass\n"
    started = time.monotonic()
    result = sandbox_instance.run(code, _window(), seed=1)
    elapsed = time.monotonic() - started

    assert result.fail_class == "timeout"
    assert "SIGXCPU" in result.detail
    assert elapsed < 20.0


# -- a window that cannot be serialized is the runner's own failure -----------


def test_a_window_without_to_arrow_raises_evaluator_sandbox_error() -> None:
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    with pytest.raises(EvaluatorSandboxError):
        sandbox_instance.run("def signal(ctx, seed):\n    return None\n", object(), seed=1)


# -- the silent-death classifier, unit-tested against synthetic returncodes --


@pytest.mark.parametrize(
    ("returncode", "expected_class"),
    [
        (-signal.SIGXCPU, "timeout"),
        (-signal.SIGSEGV, "oom"),
        (-signal.SIGBUS, "oom"),
        (-signal.SIGKILL, "crash"),
        (-signal.SIGABRT, "crash"),
        (1, "crash"),
        (0, "crash"),
        (None, "crash"),
    ],
)
def test_classify_silent_death_by_signal_and_limit(returncode: int | None, expected_class: str) -> None:
    fail_class, detail = hs._classify_silent_death(returncode)
    assert fail_class == expected_class
    assert detail


# -- the result frame decoder ignores a short, truncated or malformed read ---


def test_decode_result_frame_is_none_for_anything_short_of_one_full_frame() -> None:
    assert hs._decode_result_frame(b"") is None
    assert hs._decode_result_frame(b"\x00\x00\x00") is None
    # A declared length longer than what actually follows.
    import struct

    assert hs._decode_result_frame(struct.pack("<Q", 100) + b"short") is None


def test_decode_result_frame_reads_a_real_framed_envelope() -> None:
    import io
    import json as _json

    from orchestrator import _sandbox_child as child

    body = _json.dumps({"fail_class": None, "detail": "", "scores": "W10=", "contract_version": "0.1.0"}).encode(
        "utf-8"
    )
    buf = io.BytesIO()
    child.write_framed(buf.write, body)
    envelope = hs._decode_result_frame(buf.getvalue())
    assert envelope == {
        "fail_class": None,
        "detail": "",
        "scores": "W10=",
        "contract_version": "0.1.0",
    }
