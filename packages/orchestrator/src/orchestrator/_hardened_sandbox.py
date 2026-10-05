"""The hardened subprocess executor — a drop-in sandbox for ``execute_signal``.

additions_spec_gvisor_executor.xml, "Hardened Child", feature 2:
*System creates each signal's result in a hardened subprocess with
orchestrator._hardened_sandbox.HardenedSubprocessSandbox(limits=None). It is a
drop-in for execute_signal's sandbox argument: run(code, window, *, seed)
answers an object with scores, problems, seed, contract_version, fail_class
and detail.*

:class:`HardenedSubprocessSandbox` spawns feature 1's bootstrap
(:mod:`orchestrator._sandbox_child`, run as ``python -I _sandbox_child.py``)
as a real child process and answers an :class:`evaluator.SandboxResult` — the
exact type :func:`evaluator.execute_signal` already reads
(``result.scores``, ``result.problems``, ``result.seed``,
``result.contract_version``) — so it can replace
:class:`evaluator.SignalSandbox` at that call site with no change to the
caller.

**Why the parent's own ``stdout`` pipe *is* the bootstrap's "private
descriptor".**  :func:`orchestrator._sandbox_child._redirect_stdio` duplicates
whatever fd 1 is at process start *before* repointing fd 1 and fd 2 at
``/dev/null`` — so the OS-level pipe this launcher gets from
``subprocess.Popen(stdout=PIPE)`` is exactly the channel the bootstrap's
duplicate still writes the one framed result to; nothing else can reach it,
because the agent's own prints go to the freshly-opened ``/dev/null`` fd
instead.  This is the same wiring ``test_sandbox_child.py`` already proves (see
its module docstring), so this launcher needs no extra fd plumbing: it reads
the framed result the same way that suite's own ``_spawn`` helper does.
``stderr`` is drained on its own thread and discarded; both channels are
bounded at 64 KiB by :func:`_drain_capped` (not merely sliced after an
unbounded read), so a child that is chatty before it ever reaches feature 1's
own redirect cannot grow this launcher's memory with it.

**Why the environment is built from scratch.**  ``os.environ`` is never
copied: a signal that could read ``DATABASE_URL`` or an API key out of the
parent's shell would be a sandbox escape with a return value, so the six keys
this module writes (``PATH``, the two BLAS thread pins, the polars pool
floor, the hash seed, and the signal's own seed) are the *entire* environment
the child receives — built fresh, every call.

**Why a silent child is classified by signal rather than left ``crash``.**
The bootstrap installs no ``SIGXCPU`` handler (unlike
``evaluator._sandbox``'s embedded child), so an exhausted ``RLIMIT_CPU``
budget kills the process outright before it can write an envelope — the
launcher, not the child, is what turns that into ``fail_class="timeout"``
(see :func:`_classify_silent_death`).  The CPU soft limit is kept strictly
below the hard limit for the same reason ``evaluator._sandbox`` keeps them
apart: with soft equal to hard the kernel can escalate straight to an
unattributable ``SIGKILL`` before ``SIGXCPU`` is even delivered.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sandbox
from evaluator import EvaluatorSandboxError, SandboxResult

from . import _sandbox_child as _child

__all__ = [
    "HardenedLimits",
    "HardenedSubprocessSandbox",
]

#: The bootstrap script this executor spawns — a sibling file in this same
#: package, run as ``python -I _sandbox_child.py`` per feature 1's own
#: contract.
_CHILD_PATH: Path = Path(_child.__file__)

#: The fixed, from-scratch ``PATH`` every child runs under — just enough for
#: the interpreter itself; nothing the parent's shell exported.
_ENV_PATH: str = "/usr/bin:/bin"

#: Caps on how much of the child's stdout/stderr this launcher will hold onto.
#: The bootstrap's own contract writes at most one small JSON envelope to the
#: channel that matters (see the module docstring); this is a safety margin
#: against a child that fails before reaching that contract, not a budget
#: anything here is expected to spend.
_OUTPUT_CAP: int = 64 * 1024

#: Signals correlated with the two numeric limits this executor applies, for
#: classifying a child that died without writing a result (see
#: :func:`_classify_silent_death`).  ``SIGXCPU`` is what an exhausted
#: ``RLIMIT_CPU`` delivers with no handler installed; ``SIGSEGV``/``SIGBUS``
#: are how an ``RLIMIT_AS`` allocation failure surfaces when it does not
#: arrive as a catchable Python ``MemoryError`` (the ordinary path, already
#: handled as an ``oom`` envelope by the bootstrap itself).
_CPU_LIMIT_SIGNAL: int = signal.SIGXCPU
_MEMORY_LIMIT_SIGNALS: tuple[int, ...] = (signal.SIGSEGV, signal.SIGBUS)


@dataclass(frozen=True)
class HardenedLimits:
    """The resource envelope one hardened child run is confined to.

    Named after the four knobs feature 2's sentence lists — ``RLIMIT_CPU``,
    ``RLIMIT_AS``, ``RLIMIT_NPROC`` and the wall-clock watchdog —
    ``RLIMIT_FSIZE`` is not a field here because it is not a policy value:
    it is always zero (see :func:`_apply_rlimits`), the structural "this box
    writes no files" posture rather than a budget a deployment tunes.
    """

    #: ``RLIMIT_CPU``'s soft budget, in seconds.
    cpu_s: float
    #: ``RLIMIT_AS``'s cap, in megabytes — the host runner's portable
    #: address-space fallback (``sandbox.RUNNER_MEM_MB``), not the cgroup's
    #: own ``mem_mb``; see that constant's own docstring for why the two
    #: differ.
    runner_mem_mb: int
    #: ``RLIMIT_NPROC``'s cap on the child's process count.
    pids: int
    #: The wall-clock budget, in seconds, the watchdog kills the process
    #: group at.
    wall_s: float


def _default_limits() -> HardenedLimits:
    """§5.2's budgets, read fresh from the sandbox member's committed policies.

    Reads the cgroup budget (``cpu_s``, ``pids``) and the timeout policy
    (``wall_s``) through their compiled, drift-checked artifacts, and takes
    the memory figure from :data:`sandbox.RUNNER_MEM_MB` directly — the
    portable ``RLIMIT_AS`` fallback the budget document merely *publishes*
    rather than stores on its compiled policy (see
    ``sandbox.budget.CgroupPolicy``).
    """
    budget = sandbox.committed_budget_policy()
    timeout = sandbox.committed_timeout_policy()
    return HardenedLimits(
        cpu_s=budget.value("cpu_s"),
        runner_mem_mb=sandbox.RUNNER_MEM_MB,
        pids=budget.value("pids"),
        wall_s=timeout.wall_s,
    )


def _child_env(seed: int, *, pins: dict[str, str]) -> dict[str, str]:
    """The six-key environment the child runs under — built fresh, every call.

    ``pins`` is the thread-pinning law's own declaration
    (``sandbox.SandboxThreads.pins()``: ``OMP_NUM_THREADS``/``MKL_NUM_THREADS``
    at :data:`sandbox.SINGLE_THREADED`); the pool floor and the hash seed are
    written here because neither is a *pin* that law owns — the floor is a
    value this executor sets rather than one the law merely watches for, and
    the hash seed has no sandbox-member constant of its own.
    """
    return {
        "PATH": _ENV_PATH,
        **pins,
        sandbox.POOL_FLOOR_VARIABLE: sandbox.SINGLE_THREADED,
        "PYTHONHASHSEED": "0",
        sandbox.ENV_SIGNAL_SEED: str(int(seed)),
    }


def _ambient_task_count(uid: int) -> int:
    """A best-effort count of tasks (processes and their threads) the real
    UID already has live on this host, read from ``/proc``.

    ``RLIMIT_NPROC`` is enforced against the *real UID's* total live task
    count across every process on the machine, not against one invocation
    (the same fact ``evaluator._sandbox`` documents for why its own runner
    does not set it at all).  On a host where that UID already runs
    hundreds of threads — an editor, a browser, a test runner's own
    workers — an *absolute* ceiling of ``pids`` would refuse the very first
    thread polars itself spawns on import, before the signal ever runs.
    Reading the ambient figure here is what lets :func:`_apply_rlimits` grant
    *this run* a budget of ``pids`` tasks on top of whatever already exists,
    which is the only reading of "a process count of 32" that is enforceable
    outside a PID namespace (gVisor's own job; see feature 5's sibling
    executor).  Undercounting (a ``/proc`` entry that vanishes mid-scan) is
    the conservative failure, which is why the scan is best-effort rather
    than raising for one.
    """
    total = 0
    try:
        entries = os.listdir("/proc")
    except OSError:
        return 0
    for name in entries:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/status", encoding="utf-8") as handle:
                status_uid: int | None = None
                threads = 1
                for line in handle:
                    if line.startswith("Uid:"):
                        status_uid = int(line.split()[1])
                    elif line.startswith("Threads:"):
                        threads = int(line.split()[1])
                if status_uid == uid:
                    total += threads
        except (OSError, ValueError):
            continue
    return total


def _drain_capped(stream: Any, cap: int) -> bytes:
    """Read ``stream`` to EOF, keeping only its first ``cap`` bytes.

    Loops rather than issuing one ``read(cap)``, so a child that writes past
    the cap is still drained to EOF — its excess bytes discarded, never
    retained — instead of leaving a full pipe the child would block writing
    to forever.  Run on its own thread per stream (see
    :meth:`HardenedSubprocessSandbox.run`), so this is the actual bound on
    what this launcher ever holds in memory for stdout or stderr, not a
    slice taken after an unbounded read.
    """
    chunks: list[bytes] = []
    kept = 0
    while True:
        try:
            chunk = stream.read(65536)
        except (OSError, ValueError):
            break
        if not chunk:
            break
        if kept < cap:
            chunks.append(chunk[: cap - kept])
        kept += len(chunk)
    return b"".join(chunks)


def _apply_rlimits(limits: HardenedLimits) -> None:
    """The ``preexec_fn``: bind every numeric limit before the child execs.

    ``RLIMIT_CPU``'s soft bound is ``cpu_s``; the hard bound is the wider of
    ``cpu_s`` and ``wall_s`` rather than the same value, so an exhausted CPU
    budget is reported by the kernel as ``SIGXCPU`` (which this executor can
    attribute to the right limit) instead of being escalated straight to an
    unattributable ``SIGKILL`` in the same accounting tick — the same
    reasoning ``evaluator._sandbox._apply_limits`` states for its own pair.
    ``RLIMIT_NPROC`` is set to the host's ambient task count for this UID
    plus ``pids`` (see :func:`_ambient_task_count`), not to ``pids`` alone.
    ``RLIMIT_FSIZE`` is pinned at zero unconditionally: the box writes no
    files, structurally rather than by budget.  The new session itself is
    not set up here: ``Popen(start_new_session=True)`` already calls
    ``setsid()`` before this hook runs, and calling it twice in one process
    raises ``EPERM`` — a second ``setsid()`` here would crash every spawn.
    """
    import resource

    cpu_s = max(1, int(limits.cpu_s))
    hard_cpu_s = max(cpu_s, int(limits.wall_s))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, hard_cpu_s))

    mem_bytes = int(limits.runner_mem_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    nproc_limit = _ambient_task_count(os.getuid()) + int(limits.pids)
    resource.setrlimit(resource.RLIMIT_NPROC, (nproc_limit, nproc_limit))

    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def _decode_result_frame(out: bytes) -> dict[str, Any] | None:
    """Parse one length-framed JSON envelope off the child's stdout bytes.

    Reuses :func:`orchestrator._sandbox_child.read_framed` over an in-memory
    buffer, so the parent and the child read the identical wire format
    rather than a second, hand-rolled copy of it.  ``None`` — never an
    exception — for anything short of a complete, well-formed frame: that is
    exactly "a child that exits without writing a result", which the caller
    classifies by signal and limit instead (see
    :func:`_classify_silent_death`).
    """
    buf = io.BytesIO(out)
    try:
        body = _child.read_framed(buf.read)
    except EOFError:
        return None
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    return envelope


def _decode_scores(encoded: str) -> Any:
    """The base64-JSON score payload, rebuilt as a positional ``polars.Series``.

    Imported lazily: this module's own import surface stays stdlib-plus-
    ``sandbox``-plus-``evaluator`` so that a caller composing the application
    pays no polars cost merely for importing the executor, the same layering
    note :mod:`evaluator._sandbox` states for its own deferred import.
    """
    import base64

    import polars as pl

    values = json.loads(base64.b64decode(encoded).decode("utf-8"))
    return pl.Series(values, dtype=pl.Float64)


def _decode_problems(detail: str) -> list[Any]:
    """The violation envelope's JSON problem list, rebuilt as
    ``contract.signal.SignalReturnProblem`` values — the shape
    :func:`evaluator.execute_signal` reads off ``result.problems``.
    """
    from contract.signal import SignalReturnProblem

    raw = json.loads(detail)
    return [
        SignalReturnProblem(kind=item["kind"], message=item["message"], symbol=item.get("symbol"))
        for item in raw
    ]


def _classify_silent_death(returncode: int | None) -> tuple[str, str]:
    """A child that wrote no result: the fail class the signal (and the limit
    it correlates with) implies — ``crash`` for anything else, by name.
    """
    if returncode is not None and returncode < 0:
        killed_by = -returncode
        if killed_by == _CPU_LIMIT_SIGNAL:
            return (
                "timeout",
                f"the child died to SIGXCPU ({killed_by}) before producing a result; its RLIMIT_CPU budget was exceeded",
            )
        if killed_by in _MEMORY_LIMIT_SIGNALS:
            return (
                "oom",
                f"the child died to signal {killed_by} before producing a result; its RLIMIT_AS budget was likely exceeded",
            )
        return (
            "crash",
            f"the child died to signal {killed_by} before producing a result",
        )
    return (
        "crash",
        f"the child exited (code {returncode}) without writing a result envelope",
    )


class HardenedSubprocessSandbox:
    """Runs a signal in a hardened child process — a drop-in sandbox executor.

    Constructed once and reused across runs: every policy read
    (:func:`_default_limits`, the import allowlist, the thread pins) happens
    at construction, so a per-node evaluation that calls :meth:`run` once per
    rebalance date pays that cost exactly once rather than once per date.
    """

    def __init__(self, limits: HardenedLimits | None = None) -> None:
        self.limits: HardenedLimits = limits if limits is not None else _default_limits()
        self._imports = sandbox.sandbox_imports()
        self._thread_pins = sandbox.sandbox_threads().pins()

    def run(self, code: str, window: Any, *, seed: int) -> SandboxResult:
        """Execute ``code``'s ``signal`` over ``window`` in a hardened child.

        Screens ``code``'s imports first, before anything is spawned: a
        disallowed import answers ``fail_class="crash"`` with a detail
        naming ``disallowed_import`` (feature 167's own code word), and no
        process is created for it.  Otherwise spawns feature 1's bootstrap
        under this executor's limits and env, and classifies whatever comes
        back — a framed result envelope, or (by signal and limit) a child
        that produced none at all.  Never raises for the signal's own
        fate; only a window that cannot be serialized raises
        :class:`~evaluator.EvaluatorSandboxError`, a failure of the runner
        rather than of the signal it would have run.
        """
        decision = self._imports.screen(code)
        if not decision.admitted:
            return SandboxResult(
                scores=None,
                problems=[],
                fail_class="crash",
                detail=decision.detail,
                seed=seed,
                contract_version="",
            )

        try:
            payload = window.to_arrow()
        except AttributeError as exc:
            raise EvaluatorSandboxError(
                "HardenedSubprocessSandbox.run expects a materialized "
                "MarketWindow (one with to_arrow()); serialize the window "
                "before running the signal"
            ) from exc
        payload_bytes = bytes(payload)

        request_body = _child.encode_request(source=code, seed=seed, window_payload=payload_bytes)
        framed_request = io.BytesIO()
        _child.write_framed(framed_request.write, request_body)

        env = _child_env(seed, pins=self._thread_pins)
        limits = self.limits

        with tempfile.TemporaryDirectory(prefix="nullius-hardened-") as cwd:
            proc = subprocess.Popen(
                [sys.executable, "-I", str(_CHILD_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
                preexec_fn=lambda: _apply_rlimits(limits),  # noqa: PLW1509 - the same fork-hook pattern evaluator._sandbox._spawn already uses
            )

            # Draining stdout/stderr on their own threads, started before the
            # stdin write, is what makes the write below safe regardless of
            # how much the child eventually writes back: a plain
            # ``communicate()`` would read both pipes fully into memory
            # before this launcher gets a chance to discard them, so a child
            # that is chatty before it reaches feature 1's own redirect (a
            # start-up traceback, say) could be read without bound.  Each
            # thread keeps only the first 64 KiB and drains the rest
            # unretained, so the channel is capped at the OS level, not sliced
            # off afterward.
            out_box: list[bytes] = [b""]
            err_box: list[bytes] = [b""]
            stdout_thread = threading.Thread(
                target=lambda: out_box.__setitem__(0, _drain_capped(proc.stdout, _OUTPUT_CAP)),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=lambda: err_box.__setitem__(0, _drain_capped(proc.stderr, _OUTPUT_CAP)),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                proc.stdin.write(framed_request.getvalue())
            except (BrokenPipeError, OSError):
                pass  # a child that died before reading is classified below
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass

            try:
                proc.wait(timeout=limits.wall_s)
            except subprocess.TimeoutExpired:
                self._kill_group(proc)
                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)
                return SandboxResult(
                    scores=None,
                    problems=[],
                    fail_class="timeout",
                    detail=f"signal exceeded the {limits.wall_s:g}s wall-clock limit",
                    seed=seed,
                    contract_version="",
                )

            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            out = out_box[0]

        envelope = _decode_result_frame(out)
        if envelope is None:
            fail_class, detail = _classify_silent_death(proc.returncode)
            return SandboxResult(
                scores=None, problems=[], fail_class=fail_class, detail=detail, seed=seed, contract_version=""
            )

        return self._classify_envelope(envelope, seed=seed)

    @staticmethod
    def _kill_group(proc: subprocess.Popen[bytes]) -> None:
        """The wall-clock watchdog's hard kill — the whole process group.

        ``start_new_session=True`` makes the child a session (and process
        group) leader, so a signal it forked before hanging dies with it
        rather than surviving as an orphan.  Reaps with ``wait``, not
        ``communicate``: the stdout/stderr pipes are already being drained
        by :func:`_drain_capped`'s own threads, and a second reader on the
        same pipes would race them.
        """
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - best-effort cleanup
            pass

    @staticmethod
    def _classify_envelope(envelope: dict[str, Any], *, seed: int) -> SandboxResult:
        """Turn one well-formed result envelope into a :class:`SandboxResult`."""
        fail_class = envelope.get("fail_class")
        detail = envelope.get("detail", "") or ""

        if fail_class is None:
            try:
                scores = _decode_scores(envelope["scores"])
            except Exception as exc:  # noqa: BLE001 - a corrupt success is a runner bug
                return SandboxResult(
                    scores=None,
                    problems=[],
                    fail_class="crash",
                    detail=f"success envelope could not be decoded: {exc}",
                    seed=seed,
                    contract_version="",
                )
            return SandboxResult(
                scores=scores,
                problems=[],
                fail_class=None,
                detail="",
                seed=seed,
                contract_version=envelope.get("contract_version", ""),
            )

        if fail_class == "violation":
            try:
                problems = _decode_problems(detail)
            except Exception as exc:  # noqa: BLE001 - a corrupt problem list is a runner bug
                return SandboxResult(
                    scores=None,
                    problems=[],
                    fail_class="crash",
                    detail=f"violation envelope could not be decoded: {exc}",
                    seed=seed,
                    contract_version="",
                )
            return SandboxResult(
                scores=None,
                problems=problems,
                fail_class="violation",
                detail=detail or "signal return violated the contract",
                seed=seed,
                contract_version="",
            )

        if fail_class in _child.RESULT_FAIL_CLASSES:
            return SandboxResult(
                scores=None, problems=[], fail_class=fail_class, detail=detail, seed=seed, contract_version=""
            )

        return SandboxResult(
            scores=None,
            problems=[],
            fail_class="crash",
            detail=f"unknown sandbox failure class {fail_class!r}",
            seed=seed,
            contract_version="",
        )
