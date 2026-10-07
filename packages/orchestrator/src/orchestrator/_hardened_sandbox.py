"""The hardened subprocess executor — a drop-in sandbox for ``execute_signal``.

additions_spec_gvisor_executor.xml, "Hardened Child", feature 2:
*System creates each signal's result in a hardened subprocess with
orchestrator._hardened_sandbox.HardenedSubprocessSandbox(limits=None). It is a
drop-in for execute_signal's sandbox argument: run(code, window, *, seed)
answers an object with scores, problems, seed, contract_version, fail_class
and detail.*

:class:`HardenedSubprocessSandbox` spawns feature 1's bootstrap
(:mod:`orchestrator._sandbox_child`, run as ``python -I _sandbox_child.py``)
inside a ``bwrap`` (bubblewrap) sandbox and answers an
:class:`evaluator.SandboxResult` — the exact type
:func:`evaluator.execute_signal` already reads (``result.scores``,
``result.problems``, ``result.seed``, ``result.contract_version``) — so it
can replace :class:`evaluator.SignalSandbox` at that call site with no change
to the caller.

**bug_spec_unisolated_os_boundary.xml (SEC-1): the Python import guard is
defense-in-depth, not a security boundary.** :mod:`orchestrator._sandbox_child`
screens the agent's own ``import`` statements, but allowlisted modules
re-export disallowed ones as plain attributes of an already-loaded module
object — ``dataclasses.sys`` and ``typing.sys`` are the real :mod:`sys`,
reachable with no further import-time check at all, because attribute access
is not an import statement and the guard was never meant to catch it. A bare
subprocess has nothing else standing between that bypass and the host: the
host network, the host's own ``/proc`` (and the secrets a sibling or parent
process's environment carries), and the filesystem are all one namespace with
the agent code. ``bwrap`` is what actually contains that bypass: a private
network namespace with no route out, a private PID and mount namespace, a
cleared environment and a private ``/proc`` mean a signal that reaches
``os``/``sys`` this way still cannot open a socket, still cannot read a
parent's environment, and still cannot see any host process at all. There is
no bare-subprocess fallback — :meth:`HardenedSubprocessSandbox.__init__`
resolves ``bwrap`` on ``PATH`` and refuses to construct without it (see
:func:`_require_bwrap`).

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

**bug_spec_hardened_nproc_race.xml (NPROC-1): the process-tree budget is a
cgroup v2 ``pids.max`` on a delegated cgroup, never a UID-wide
``RLIMIT_NPROC``.**  ``RLIMIT_NPROC`` is enforced by the kernel against the
*real UID's* total live task count across the whole host, not against one
process tree — so a limit derived from an ambient ``/proc`` snapshot plus a
headroom constant is only ever correct for the instant it was read: any
thread or process the same user spawns afterward (another worker's own
sandbox, an editor, a browser) consumes the same shared counter and can tip
a perfectly healthy child over its budget.  :func:`_pids_mechanism` probes,
once per process, whether this process's own cgroup v2 leaf
(``/proc/self/cgroup``) has the ``pids`` controller delegated to its
children and is writable; if so, :meth:`HardenedSubprocessSandbox.run`
creates one throwaway child cgroup per run, writes ``pids.max`` to
``limits.pids`` in it, and the ``preexec_fn`` moves the about-to-exec child
into it before ``bwrap`` ever runs — a limit scoped to *that run's* tree,
enforced by the kernel regardless of what else the UID is doing elsewhere.
Where no such cgroup is writable (the common case off a host with no
systemd delegation), no process-count rlimit is applied at all: the
containment then rests on what the executor already has independently of
NPROC — ``bwrap``'s own PID namespace (``--unshare-all``, so a forking
child can never see or signal anything outside its own tree), ``RLIMIT_AS``
bounding the memory a forking child can allocate, and the wall-clock
watchdog (:meth:`HardenedSubprocessSandbox._kill_group`) bounding how long
it can run at all. Which of the two this process landed on is logged once,
at construction of the first sandbox in the process, through this module's
own logger.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import sandbox
from evaluator import EvaluatorSandboxError, SandboxResult

from . import _sandbox_child as _child

_logger = logging.getLogger(__name__)

__all__ = [
    "BWRAP_BINARY",
    "BWRAP_UNAVAILABLE_CODE",
    "BwrapUnavailableError",
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

#: The system binary every unisolated run is wrapped in — see the module
#: docstring's SEC-1 paragraph.  A system binary, not a Python dependency:
#: resolved fresh off ``PATH`` through :func:`shutil.which`, the same idiom
#: :func:`orchestrator._gvisor._require_runsc` uses for ``runsc``.
BWRAP_BINARY: Final[str] = "bwrap"

#: The greppable code word a missing ``bwrap`` refusal carries — the same
#: word :mod:`orchestrator._context` names when the ``"unisolated"`` gate's
#: own ``bwrap`` check fails, and :mod:`orchestrator._gvisor` names for a
#: missing ``runsc`` (:data:`orchestrator._gvisor.GVISOR_UNAVAILABLE_CODE`):
#: one word for "this executor has nothing to isolate agent code with."
BWRAP_UNAVAILABLE_CODE: Final[str] = "isolation_required"


class BwrapUnavailableError(Exception):
    """``bwrap`` is missing or not executable — raised at construction.

    :class:`HardenedSubprocessSandbox` has no bare-subprocess fallback (SEC-1):
    a sandbox that cannot find a working ``bwrap`` has nothing to isolate
    agent-authored code with, and refuses to be built at all rather than
    silently running the child unconfined at the first signal's expense — the
    same "fail at construction" stance
    :class:`orchestrator._gvisor.GVisorUnavailableError` takes for a missing
    ``runsc``.
    """


def _require_bwrap() -> Path:
    """Resolve ``bwrap`` to an executable path, or raise.

    Looked up fresh through :func:`shutil.which` at every construction — never
    cached across instances — so a deployment that installs ``bwrap`` need not
    restart anything already running to start working, the same freshness
    :func:`orchestrator._context._sandbox_runtime` gives its own ``runsc``
    lookup.
    """
    resolved = shutil.which(BWRAP_BINARY)
    if resolved is None:
        raise BwrapUnavailableError(
            f"{BWRAP_UNAVAILABLE_CODE}: {BWRAP_BINARY!r} is missing or not "
            "executable. The unisolated executor's only OS boundary is bwrap "
            "(bubblewrap); a HardenedSubprocessSandbox with no working bwrap "
            "beneath it has nothing to isolate agent-authored code with, and "
            "there is no bare-subprocess fallback — install bwrap, or run "
            "under sandbox_runtime 'gvisor' instead."
        )
    return Path(resolved)


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
    #: The cap on the child's process-tree task count — a cgroup v2
    #: ``pids.max`` on a delegated cgroup when one is writable, the only
    #: enforcement scoped to *this run's* tree rather than to the real UID
    #: host-wide (see the module docstring's NPROC-1 paragraph). Unused
    #: (no process-count limit applied at all) when no such cgroup is
    #: available.
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


def _bwrap_argv(bwrap: Path, env: dict[str, str], cwd: str) -> list[str]:
    """The ``bwrap`` command line the child actually runs under (SEC-1).

    Every namespace ``bug_spec_unisolated_os_boundary.xml``'s own "Expected"
    section names, in one invocation: ``--unshare-all`` (a private user, IPC,
    PID, network, UTS and cgroup namespace — a strict superset of the
    ``--unshare-net``/``--unshare-pid`` the spec calls out by name) plus
    ``--die-with-parent`` so a killed launcher never orphans the child.
    ``--clearenv`` wipes whatever ``bwrap`` itself was spawned with, and the
    six ``--setenv`` pairs restate exactly ``env`` (:func:`_child_env`'s own
    six keys) — never ``os.environ`` — so the environment inside the sandbox
    is, structurally, the same from-scratch six keys the bare subprocess
    executor always built, now enforced twice over.  ``--proc /proc`` is a
    *fresh* procfs for the new PID namespace: the host's own ``/proc`` (and
    every other process's environment and file descriptors on it) is
    unreachable from inside, closing the exact ``/proc`` route the bug names.
    ``--ro-bind / /`` gives the child's own interpreter and site-packages
    (wherever the host actually keeps them) read-only, identity-mapped access
    — the host filesystem is readable, never writable (``RLIMIT_FSIZE`` is
    already zero; this is the second, OS-level door on the same fact).
    ``--dev /dev`` is load-bearing, not decorative: the bootstrap's own
    ``_redirect_stdio`` opens ``/dev/null`` for *writing* before anything else
    runs, and a plain ``--ro-bind``'d ``/dev/null`` refuses that open with
    ``EROFS`` — a fresh, writable ``/dev`` is what keeps that first line of
    the bootstrap from crashing every single run.  ``--tmpfs``/``--chdir``
    give the child the one writable (if useless, given ``RLIMIT_FSIZE=0``)
    directory the spec calls "a tmpfs working directory," shadowing the
    read-only root for that one path.
    """
    argv = [
        str(bwrap),
        "--unshare-all",
        "--die-with-parent",
        "--clearenv",
    ]
    for key, value in env.items():
        argv += ["--setenv", key, value]
    argv += [
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        cwd,
        "--chdir",
        cwd,
        "--",
        sys.executable,
        "-I",
        str(_CHILD_PATH),
    ]
    return argv


#: The standard cgroup v2 unified-hierarchy mount point — universal on any
#: host running only cgroup v2 (no ``hybrid``/``legacy`` mode), which is what
#: :func:`_own_unified_cgroup_path` itself detects via ``/proc/self/cgroup``'s
#: own ``0::`` convention before this constant is ever consulted.
_CGROUP_ROOT: Final[Path] = Path("/sys/fs/cgroup")

#: How many times :func:`_remove_cgroup` retries an ``rmdir`` that raced a
#: just-killed process tree's own kernel-side cleanup, and the pause between
#: each — generous enough to absorb that race, small enough that a launcher
#: cleaning up after thousands of runs over a campaign never notices it.
_CGROUP_CLEANUP_ATTEMPTS: Final[int] = 20
_CGROUP_CLEANUP_DELAY_S: Final[float] = 0.05


@dataclass(frozen=True)
class _PidsMechanism:
    """Which boundary this process landed on for the process-tree budget.

    ``cgroup_base`` is the delegated cgroup directory a run's own throwaway
    child is created under, or ``None`` when no such cgroup is writable —
    the two branches :func:`_pids_mechanism` logs once per process, and the
    module docstring's NPROC-1 paragraph names in full.
    """

    cgroup_base: Path | None
    detail: str

    @property
    def available(self) -> bool:
        """Whether a delegated cgroup is usable for this process's runs."""
        return self.cgroup_base is not None


def _own_unified_cgroup_path() -> str | None:
    """This process's own cgroup v2 path, or ``None`` off anything else.

    ``/proc/self/cgroup`` carries one ``hierarchy-id:controller-list:path``
    line per hierarchy; the unified (cgroup v2) hierarchy is always
    hierarchy id ``0`` with an empty controller list, which is what
    distinguishes it from a ``hybrid`` mount's legacy (cgroup v1) lines —
    this executor only ever trusts that one line, never a v1 hierarchy's own
    (differently-scoped) ``pids`` controller.
    """
    try:
        lines = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            return parts[2]
    return None


def _probe_pids_mechanism() -> _PidsMechanism:
    """Probe, once, whether this process has a writable delegated cgroup.

    Read-only unless the final write-access check: this executor never tries
    to *enable* the ``pids`` controller itself (writing ``+pids`` to a
    parent's own ``cgroup.subtree_control``), because a cgroup this process
    lives in directly cannot enable controllers for children while it still
    holds processes of its own (cgroup v2's "no internal processes" rule) —
    delegation is something a systemd unit's ``Delegate=`` already grants
    *before* this process starts, and this probe only ever consumes it.
    """
    path = _own_unified_cgroup_path()
    if path is None:
        return _PidsMechanism(
            None, "no cgroup v2 unified hierarchy at /proc/self/cgroup (hybrid or legacy mode)"
        )
    base = _CGROUP_ROOT if path in ("", "/") else _CGROUP_ROOT / path.lstrip("/")
    try:
        if not base.is_dir():
            return _PidsMechanism(None, f"{base} is not a directory")
        controllers = (base / "cgroup.subtree_control").read_text(encoding="utf-8").split()
    except OSError as exc:
        return _PidsMechanism(None, f"could not read {base}/cgroup.subtree_control: {exc}")
    if "pids" not in controllers:
        return _PidsMechanism(
            None,
            f"the pids controller is not delegated to children of {base} "
            "(absent from cgroup.subtree_control)",
        )
    probe_dir = base / f".nullius-hardened-probe-{os.getpid()}"
    try:
        probe_dir.mkdir()
        probe_dir.rmdir()
    except OSError as exc:
        return _PidsMechanism(None, f"{base} is not writable: {exc}")
    return _PidsMechanism(base, f"cgroup v2 pids delegation confirmed writable at {base}")


_pids_mechanism_lock = threading.Lock()
_pids_mechanism_cache: _PidsMechanism | None = None


def _pids_mechanism() -> _PidsMechanism:
    """The cached, process-wide answer to :func:`_probe_pids_mechanism`.

    Probed once and logged once — the first :class:`HardenedSubprocessSandbox`
    built in this process pays the ``/proc`` and cgroupfs reads, and every
    run after it (in this process, including every later instance) reuses
    the answer, the same one-probe-per-process posture
    :func:`orchestrator._gvisor._require_runsc`-style launchers take for
    their own runtime checks.
    """
    global _pids_mechanism_cache
    with _pids_mechanism_lock:
        if _pids_mechanism_cache is None:
            _pids_mechanism_cache = _probe_pids_mechanism()
            if _pids_mechanism_cache.available:
                _logger.info(
                    "HardenedSubprocessSandbox: process-tree budget enforced via cgroup v2 "
                    "pids.max (%s)",
                    _pids_mechanism_cache.detail,
                )
            else:
                _logger.info(
                    "HardenedSubprocessSandbox: no delegated cgroup pids controller available "
                    "(%s); falling back to the bwrap PID namespace, RLIMIT_AS and the "
                    "wall-clock watchdog for process-tree containment",
                    _pids_mechanism_cache.detail,
                )
        return _pids_mechanism_cache


def _create_leaf_cgroup(base: Path, pids: int) -> Path | None:
    """Create one throwaway child cgroup under ``base``, capped at ``pids``.

    One cgroup per run rather than one shared cgroup for the executor's
    whole lifetime, so two runs dispatched back to back (or concurrently,
    from two launchers in the same process) never share a ``pids.max`` —
    each run gets the full budget the policy names, the same per-run
    isolation :func:`_child_env` gives each run's environment.  ``None`` on
    any failure (the directory vanished, a permission changed mid-run): the
    caller treats that exactly like :attr:`_PidsMechanism.available` being
    ``False`` for this one run, rather than raising and losing the signal's
    result to a defense-in-depth mechanism's own hiccup.
    """
    try:
        leaf = Path(tempfile.mkdtemp(prefix="nullius-hardened-", dir=str(base)))
    except OSError:
        return None
    try:
        (leaf / "pids.max").write_text(str(int(pids)), encoding="ascii")
    except OSError:
        _remove_cgroup(leaf)
        return None
    return leaf


def _remove_cgroup(path: Path) -> None:
    """Remove a leaf cgroup, retrying past the kernel's own async cleanup.

    A cgroup cannot be ``rmdir``'d while a task is still attached to it, and
    the kernel detaches a just-killed process's task from its cgroup
    asynchronously relative to :meth:`HardenedSubprocessSandbox._kill_group`
    reaping it — so the first attempt racing that detachment is expected,
    not a bug, and is retried rather than leaked.  Best-effort past
    :data:`_CGROUP_CLEANUP_ATTEMPTS`: an empty cgroup directory left behind
    wastes nothing a kernel cares about and is not worth raising over.
    """
    for _ in range(_CGROUP_CLEANUP_ATTEMPTS):
        try:
            path.rmdir()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(_CGROUP_CLEANUP_DELAY_S)


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
    """The ``preexec_fn``: bind the host-portable numeric limits before exec.

    ``RLIMIT_CPU``'s soft bound is ``cpu_s``; the hard bound is the wider of
    ``cpu_s`` and ``wall_s`` rather than the same value, so an exhausted CPU
    budget is reported by the kernel as ``SIGXCPU`` (which this executor can
    attribute to the right limit) instead of being escalated straight to an
    unattributable ``SIGKILL`` in the same accounting tick — the same
    reasoning ``evaluator._sandbox._apply_limits`` states for its own pair.
    ``RLIMIT_FSIZE`` is pinned at zero unconditionally: the box writes no
    files, structurally rather than by budget. **No ``RLIMIT_NPROC`` is set
    here** (NPROC-1, see the module docstring): that limit is per real UID,
    host-wide, not per process tree, so no value computed from an ambient
    snapshot is ever safe to apply to one run — the process-tree budget is
    instead a cgroup v2 ``pids.max`` applied by :func:`_join_cgroup`, when a
    delegated cgroup is available (see :meth:`HardenedSubprocessSandbox.run`).
    The new session itself is not set up here: ``Popen(start_new_session=True)``
    already calls ``setsid()`` before this hook runs, and calling it twice in
    one process raises ``EPERM`` — a second ``setsid()`` here would crash
    every spawn.
    """
    import resource

    cpu_s = max(1, int(limits.cpu_s))
    hard_cpu_s = max(cpu_s, int(limits.wall_s))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, hard_cpu_s))

    mem_bytes = int(limits.runner_mem_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def _join_cgroup(cgroup_path: Path) -> None:
    """Move the current (about-to-exec) process into ``cgroup_path``.

    Called from the ``preexec_fn``, strictly before ``exec`` — the only point
    at which this is race-free: a pid added to a cgroup *after* it has
    already exec'd into ``bwrap`` could have forked ``bwrap``'s own
    namespace-init child first, and that grandchild would have inherited the
    *old* cgroup rather than this run's leaf, escaping ``pids.max``
    entirely. Failures are swallowed rather than raised: this hook runs
    forked but not yet exec'd, where raising would abort the spawn over a
    defense-in-depth mechanism that :func:`_pids_mechanism` already confirmed
    was best-effort — the run still gets the PID namespace, ``RLIMIT_AS`` and
    the wall-clock watchdog either way.
    """
    try:
        with open(cgroup_path / "cgroup.procs", "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
    except OSError:
        pass


def _preexec_hardening(limits: HardenedLimits, cgroup_path: Path | None) -> None:
    """The full ``preexec_fn``: rlimits, then this run's cgroup if it has one."""
    _apply_rlimits(limits)
    if cgroup_path is not None:
        _join_cgroup(cgroup_path)


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


def _signal_from_returncode(returncode: int | None) -> int | None:
    """The signal that killed a process, read off either exit convention.

    A bare ``subprocess`` reports a negative ``returncode`` for a process the
    kernel killed by signal directly (Python's own convention, and what the
    parametrized unit test below still exercises). ``bwrap``, under
    ``--unshare-all``, forks its own PID-1-equivalent for the new namespace
    (a consequence of ``--unshare-pid``), and that process reports the
    grandchild's signal death by *exiting normally* with the shell's
    ``128 + signal`` convention rather than dying by the same signal itself —
    so ``bwrap``'s own ``returncode`` (what :meth:`HardenedSubprocessSandbox.run`
    actually observes once every spawn goes through SEC-1's fix) is positive.
    Reading both conventions here, in one place, is what lets
    :func:`_classify_silent_death` stay the single thing that names a signal a
    fail class, regardless of which process reported it.
    """
    if returncode is None:
        return None
    if returncode < 0:
        return -returncode
    if returncode >= 128:
        return returncode - 128
    return None


def _classify_silent_death(returncode: int | None) -> tuple[str, str]:
    """A child that wrote no result: the fail class the signal (and the limit
    it correlates with) implies — ``crash`` for anything else, by name.
    """
    killed_by = _signal_from_returncode(returncode)
    if killed_by is not None:
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

    ``bwrap`` is resolved once, here, at construction (:func:`_require_bwrap`)
    — raising :class:`BwrapUnavailableError` rather than building a sandbox
    with no OS boundary beneath it (SEC-1's own "no bare-subprocess fallback"
    constraint). The same "fail at construction, not at a signal's expense"
    stance :class:`orchestrator._gvisor.GVisorSandbox` already takes for its
    own ``runsc``.
    """

    def __init__(self, limits: HardenedLimits | None = None) -> None:
        self.limits: HardenedLimits = limits if limits is not None else _default_limits()
        self._imports = sandbox.sandbox_imports()
        self._thread_pins = sandbox.sandbox_threads().pins()
        self._bwrap: Path = _require_bwrap()

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

        # NPROC-1: a cgroup v2 pids.max on a throwaway per-run leaf cgroup,
        # when a delegated one is writable — never a UID-wide RLIMIT_NPROC
        # (see the module docstring and _apply_rlimits's own note). ``None``
        # when unavailable, which _preexec_hardening reads as "apply no
        # process-count limit; the PID namespace, RLIMIT_AS and the
        # wall-clock watchdog are this run's containment instead."
        mechanism = _pids_mechanism()
        leaf_cgroup = _create_leaf_cgroup(mechanism.cgroup_base, limits.pids) if mechanism.available else None

        try:
            with tempfile.TemporaryDirectory(prefix="nullius-hardened-") as cwd:
                proc = subprocess.Popen(
                    _bwrap_argv(self._bwrap, env, cwd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    start_new_session=True,
                    preexec_fn=lambda: _preexec_hardening(limits, leaf_cgroup),  # noqa: PLW1509 - the same fork-hook pattern evaluator._sandbox._spawn already uses
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
        finally:
            if leaf_cgroup is not None:
                _remove_cgroup(leaf_cgroup)

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
