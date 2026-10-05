"""The gVisor executor — a drop-in sandbox for ``execute_signal``, under ``runsc``.

additions_spec_gvisor_executor.xml, "gVisor Executor", feature 5:
*System executes a signal under gVisor with orchestrator._gvisor.GVisorSandbox(*,
runsc, runtime_root, state_root, limits=None, lake_roots=()). It is the same
drop-in interface as HardenedSubprocessSandbox.*

Where :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox` spawns
feature 1's bootstrap as a bare ``subprocess`` confined by rlimits,
:class:`GVisorSandbox` spawns the *identical* bootstrap inside an OCI
container that ``runsc`` (gVisor's user-space kernel) runs: feature 4's
:func:`~orchestrator._oci_bundle.build_bundle` writes the container's
``config.json`` fresh for every call, and this module is only the launcher
around it — ``runsc run``, the framed request/result exchange over the
container's own stdin/stdout, the wall-clock watchdog, and the two cleanup
calls (``runsc delete -force``, the bundle directory) that run whatever the
run's outcome was.

**Why the envelope decoding is imported, not reimplemented.**  The bootstrap
(feature 1) is the same process either way — the only thing that changed is
what confines it — so the framed JSON result it writes means the same thing
under ``runsc`` as it does under a bare subprocess.
:mod:`orchestrator._hardened_sandbox` already owns that decoding
(:func:`~orchestrator._hardened_sandbox._decode_result_frame`,
:meth:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox._classify_envelope`,
:func:`~orchestrator._hardened_sandbox._classify_silent_death`) and its own
default limits (:func:`~orchestrator._hardened_sandbox._default_limits`), and
this module calls those rather than keeping a second copy that the two
executors' envelopes could quietly drift apart from — the sandbox member's own
"one-provenance" rule, applied across this package's two launchers instead of
within one of its modules.

**Why the request still carries the seed on the wire, not in the bundle's
env.**  Feature 4's bundle bakes feature 2's environment *minus*
``NULLIUS_SIGNAL_SEED`` into ``config.json`` once, because a bundle is a
static file built once per run and the seed is the one value in that list
that varies per run.  So the seed travels the same way the source and the
window payload do — framed on the container's stdin, read by the same
:func:`orchestrator._sandbox_child.decode_request` the subprocess executor's
child reads.

**Why ``sandbox_escape`` exists here and not in the subprocess executor.**
Feature 2's committed syscall allowlist is deliberately not applied to either
executor (it would refuse ``openat``/``clone``/``getrandom`` and kill
CPython+polars outright before a signal ever ran) — under gVisor, ``runsc``'s
own Sentry *is* the syscall boundary, and a process it refuses to let through
can die inside the container before the bootstrap ever gets to write a result.
That is a different fact from "the child exited silently" (feature 2's
``_classify_silent_death``, by signal and rlimit): it is gVisor itself
reporting that the box did something its own confinement does not allow, and
:func:`_reports_sandbox_violation` is this module's best-effort reading of
that report off ``runsc``'s own stderr.  **Honest limit:** there is no
committed, versioned spelling of "gVisor reported a violation" the way
feature 157's ``gvisor_isolation_required`` or feature 167's
``disallowed_import`` are — gVisor's own diagnostics are not this project's
artifact — so the markers below are a heuristic over the text ``runsc``
happens to print, checked only when the bootstrap produced no result at all.
A violation this heuristic misses still lands as ``crash`` via
:func:`~orchestrator._hardened_sandbox._classify_silent_death`, which is a
safe (if less precise) fallback rather than a silent success.

**Why the spawned environment is never the parent's.**  Every ``runsc``
invocation this module makes (``run``, ``kill``, ``delete``) is handed
:data:`_RUNSC_ENV` — a from-scratch, single-key environment — never
``os.environ``: the host process that launches a container runtime is exactly
the place a copied environment would hand ``DATABASE_URL`` or an API key to a
tool that is, in turn, about to run agent-authored code.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import sandbox
from evaluator import EvaluatorSandboxError, SandboxResult

from . import _hardened_sandbox as hs
from . import _oci_bundle as bundle
from . import _sandbox_child as _child
from ._hardened_sandbox import HardenedLimits
from ._oci_bundle import PathLike

__all__ = [
    "GVISOR_UNAVAILABLE_CODE",
    "GVisorSandbox",
    "GVisorUnavailableError",
]

#: The greppable code every construction-time refusal of this module carries —
#: the discipline feature 157's ``gvisor_isolation_required`` and feature
#: 167's ``disallowed_import`` set for theirs.  Spelled ``isolation_required``
#: per feature 5's own sentence rather than reusing feature 157's longer
#: ``gvisor_isolation_required``: that code names a *run's configuration*
#: being refused by a policy; this one names the *executor itself* having
#: nothing to run under — a different failure with a different repair (install
#: or point at ``runsc``, rather than edit a policy document).
GVISOR_UNAVAILABLE_CODE: Final[str] = "isolation_required"

#: The from-scratch environment every ``runsc`` invocation this module makes
#: is spawned with — never ``os.environ``.  This governs the *host-side*
#: ``runsc`` process only; the container's own process environment is the
#: bundle's ``config.json``, built once per run by feature 4.
_RUNSC_ENV: Final[dict[str, str]] = {"PATH": "/usr/bin:/bin"}

#: The signal ``runsc kill`` is sent at the wall-clock watchdog, and the grace
#: period this launcher waits for the container to actually exit afterward —
#: the same shape :meth:`orchestrator._hardened_sandbox.HardenedSubprocessSandbox._kill_group`
#: gives its own ``SIGKILL``/``wait`` pair.
_KILL_SIGNAL: Final[str] = "SIGKILL"
_REAP_GRACE_S: Final[float] = 5.0

#: Substrings checked, case-folded, against ``runsc``'s own stderr when the
#: bootstrap produced no result frame at all — see the module docstring's
#: "why ``sandbox_escape`` exists here" for what this is and is not a
#: guarantee of.
_SANDBOX_VIOLATION_MARKERS: Final[tuple[str, ...]] = (
    "sandbox violation",
    "seccomp violation",
    "bad system call",
    "sigsys",
)


class GVisorUnavailableError(Exception):
    """``runsc`` is missing or not executable — raised at construction.

    Every message begins with :data:`GVISOR_UNAVAILABLE_CODE`
    (``isolation_required``): a :class:`GVisorSandbox` that cannot find a
    working ``runsc`` has nothing to isolate agent-authored code with, and a
    caller that built one anyway would discover that only at the first run —
    turning a configuration mistake into a runtime failure of a signal's own
    evaluation. Refused up front instead, the same "fail at construction,
    not at the subject's expense" stance
    :class:`~sandbox.errors.GVisorIsolationRequired` takes for a drifted
    policy document.
    """


def _require_runsc(runsc: PathLike) -> Path:
    """Resolve ``runsc`` to an executable path, or raise.

    ``shutil.which`` is what does the actual checking — it resolves a bare
    command name against ``PATH`` exactly as it resolves an absolute path
    (checking existence and :data:`os.X_OK` either way), so a caller can hand
    this either ``"runsc"`` or a fully-qualified path (a fake executable a
    test builds) and get the same validation.
    """
    resolved = shutil.which(os.fspath(runsc))
    if resolved is None:
        raise GVisorUnavailableError(
            f"{GVISOR_UNAVAILABLE_CODE}: runsc ({runsc!r}) is missing or not "
            "executable. §5.2's isolation row is gVisor (runsc); a "
            "GVisorSandbox with no working runsc beneath it has nothing to "
            "isolate agent-authored code with, and is refused at "
            "construction rather than at a signal's expense (feature 5)."
        )
    return Path(resolved)


def _reports_sandbox_violation(stderr: bytes) -> bool:
    """Whether ``runsc``'s own stderr names a sandbox violation.

    See the module docstring's "why ``sandbox_escape`` exists here" for what
    this heuristic is (a substring check over ``runsc``'s own diagnostic
    text) and is not (a committed, versioned vocabulary the way feature 157's
    and 167's codes are).
    """
    lowered = stderr.decode("utf-8", errors="replace").casefold()
    return any(marker in lowered for marker in _SANDBOX_VIOLATION_MARKERS)


class GVisorSandbox:
    """Runs a signal inside a ``runsc`` container — a drop-in sandbox executor.

    The same four-argument call shape as
    :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox.run`:
    ``run(code, window, *, seed)`` answers a
    :class:`~evaluator.SandboxResult`. Construction resolves ``runsc`` once
    (raising :class:`GVisorUnavailableError` if it is unusable) and reads the
    sandbox member's default limits once if none are given, so a per-node
    evaluation that calls :meth:`run` repeatedly pays neither cost twice.
    """

    def __init__(
        self,
        *,
        runsc: PathLike,
        runtime_root: PathLike,
        state_root: PathLike,
        limits: HardenedLimits | None = None,
        lake_roots: Sequence[PathLike] = (),
    ) -> None:
        self.runsc: Path = _require_runsc(runsc)
        self.runtime_root = runtime_root
        self.state_root: Path = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.limits: HardenedLimits = limits if limits is not None else hs._default_limits()
        self.lake_roots: tuple[PathLike, ...] = tuple(lake_roots)
        self._imports = sandbox.sandbox_imports()

    def run(self, code: str, window: object, *, seed: int) -> SandboxResult:
        """Execute ``code``'s ``signal`` over ``window`` inside a fresh container.

        Screens ``code``'s imports first, before anything is built or spawned
        — identically to :meth:`HardenedSubprocessSandbox.run`, so a
        disallowed import never reaches a bundle or a container. Otherwise
        builds one OCI bundle (feature 4), launches ``runsc run`` against it,
        and classifies whatever comes back. Never raises for the signal's own
        fate; only a window that cannot be serialized raises
        :class:`~evaluator.EvaluatorSandboxError`.
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
                "GVisorSandbox.run expects a materialized MarketWindow (one "
                "with to_arrow()); serialize the window before running the "
                "signal"
            ) from exc
        payload_bytes = bytes(payload)

        request_body = _child.encode_request(source=code, seed=seed, window_payload=payload_bytes)
        framed_request = io.BytesIO()
        _child.write_framed(framed_request.write, request_body)
        request_bytes = framed_request.getvalue()

        container_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory(prefix="nullius-gvisor-bundle-") as bundle_dir:
            try:
                bundle.build_bundle(
                    bundle_dir,
                    runtime_root=self.runtime_root,
                    child_path=hs._CHILD_PATH,
                    limits=self.limits,
                    lake_roots=self.lake_roots,
                )
                argv = [
                    str(self.runsc),
                    "--rootless",
                    "--network=none",
                    "--root",
                    str(self.state_root),
                    "run",
                    "--bundle",
                    str(bundle_dir),
                    container_id,
                ]
                return self._run_container(argv, container_id, request_bytes, seed=seed)
            finally:
                self._delete(container_id)

    def _run_container(
        self, argv: list[str], container_id: str, request_bytes: bytes, *, seed: int
    ) -> SandboxResult:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_RUNSC_ENV,
        )

        # Drained on their own threads, started before the stdin write, for
        # the identical reason HardenedSubprocessSandbox.run gives: a
        # ``communicate()`` would read both pipes fully into memory before
        # this launcher gets a chance to discard the excess.
        out_box: list[bytes] = [b""]
        err_box: list[bytes] = [b""]
        stdout_thread = threading.Thread(
            target=lambda: out_box.__setitem__(0, hs._drain_capped(proc.stdout, hs._OUTPUT_CAP)),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=lambda: err_box.__setitem__(0, hs._drain_capped(proc.stderr, hs._OUTPUT_CAP)),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            proc.stdin.write(request_bytes)
        except (BrokenPipeError, OSError):
            pass  # a container that died before reading is classified below
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

        try:
            proc.wait(timeout=self.limits.wall_s)
        except subprocess.TimeoutExpired:
            self._kill(container_id)
            try:
                proc.wait(timeout=_REAP_GRACE_S)
            except subprocess.TimeoutExpired:  # pragma: no cover - best-effort reap
                pass
            stdout_thread.join(timeout=_REAP_GRACE_S)
            stderr_thread.join(timeout=_REAP_GRACE_S)
            return SandboxResult(
                scores=None,
                problems=[],
                fail_class="timeout",
                detail=f"signal exceeded the {self.limits.wall_s:g}s wall-clock limit under gVisor",
                seed=seed,
                contract_version="",
            )

        stdout_thread.join(timeout=_REAP_GRACE_S)
        stderr_thread.join(timeout=_REAP_GRACE_S)
        out = out_box[0]
        err = err_box[0]

        envelope = hs._decode_result_frame(out)
        if envelope is None:
            if _reports_sandbox_violation(err):
                detail_err = err.decode("utf-8", errors="replace").strip()
                return SandboxResult(
                    scores=None,
                    problems=[],
                    fail_class=sandbox.SANDBOX_ESCAPE_CLASS,
                    detail=f"runsc reported a sandbox violation: {detail_err[:2000]}",
                    seed=seed,
                    contract_version="",
                )
            fail_class, detail = hs._classify_silent_death(proc.returncode)
            return SandboxResult(
                scores=None, problems=[], fail_class=fail_class, detail=detail, seed=seed, contract_version=""
            )

        return hs.HardenedSubprocessSandbox._classify_envelope(envelope, seed=seed)

    def _kill(self, container_id: str) -> None:
        """The wall-clock watchdog's hard kill — ``runsc kill ... SIGKILL``."""
        try:
            subprocess.run(
                [str(self.runsc), "--rootless", "--root", str(self.state_root), "kill", container_id, _KILL_SIGNAL],
                env=_RUNSC_ENV,
                capture_output=True,
                check=False,
            )
        except OSError:  # pragma: no cover - best-effort cleanup
            pass

    def _delete(self, container_id: str) -> None:
        """Always run, regardless of the container's outcome: ``runsc delete -force``."""
        try:
            subprocess.run(
                [str(self.runsc), "--rootless", "--root", str(self.state_root), "delete", "-force", container_id],
                env=_RUNSC_ENV,
                capture_output=True,
                check=False,
            )
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
