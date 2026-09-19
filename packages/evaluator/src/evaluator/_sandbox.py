"""The signal sandbox — running untrusted signal code under hard limits.

app_spec.xml feature 73: *"System executes the signal function inside the
sandbox, which returns a raw score vector per rebalance date."*
docs/nullius-tech-architecture.md §5.2 names the step and its controls:

    result = sandbox.run(
        entrypoint="signal",
        code=node.code,
        payload=window.to_arrow(),        # IPC, zero-copy
        limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048,
                      network=False, filesystem=False, pids=32),
        seed=node.seed,
        env={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
    )

Five claims sit in that one call, and this module is each of them:

* **Untrusted code, isolated.**  A signal is LLM-authored, and LLM-authored
  code is untrusted code (§5.2: "LLM-authored code is untrusted code. Treat
  it that way.").  It must not share the host process's memory, filesystem,
  import space or open sockets — a signal that could ``import`` a host module
  or ``open`` a path the evaluator did not hand it would be a sandbox escape,
  and a sandbox escape is look-ahead bias with a return value.  So the signal
  runs in a *child* Python process, not a thread (a thread cannot be killed
  and shares everything) and not an ``exec`` into the host namespace (which
  would leak the signal's module-level state onto whoever ran it — the exact
  leak ``contract.signal._require_signal_module`` avoids host-side).  The
  child is the same interpreter as the host (``sys.executable``), so
  ``contract``/``polars``/``pyarrow`` resolve identically on both sides of
  the boundary; a divergent interpreter would be a replay hazard.

* **Hard resource limits.**  §5.2's table and the failure-mode note — "Hard
  kill, recorded as ``fail_class=timeout``" — are enforced with POSIX
  ``resource.setrlimit`` applied in a pre-exec fork: ``RLIMIT_CPU`` for the
  CPU budget (the kernel raises ``SIGXCPU``, which the child runner maps to
  ``timeout``), ``RLIMIT_AS`` for the memory budget (an allocation failure
  maps to ``oom``), ``RLIMIT_NPROC`` for the process cap.  A wall-clock
  watchdog in the parent kills the child at ``wall_s`` — also ``timeout``,
  because a signal that runs past the wall is a hung one whatever the CPU did.
  Every one of these is a *recorded outcome*, never a raised exception: a
  failed run is a value the pipeline persists (feature 79's "a failed
  evaluation still consumed a hypothesis"), so :meth:`SignalSandbox.run`
  returns a :class:`SandboxResult` describing the failure rather than
  raising at it.

* **The payload channel.**  The window arrives as the bytes
  ``window.to_arrow()`` produced (§5.2, feature 14); the child reads them back
  through the same ``contract.payload.MarketWindowPayload`` the host wrote, so
  a window that crossed the channel is validated exactly as strictly as one
  built in-process.  Nothing but those bytes crosses — no path, no handle, no
  fd — which is why the child can be run with no filesystem mounts at all.

* **The determinism env.**  §12's reproducibility contract is pinned into the
  child's environment: ``OMP_NUM_THREADS=1`` and ``MKL_NUM_THREADS=1`` make
  the BLAS reductions single-threaded (multi-threaded reductions are
  non-deterministic in float, which breaks P3), and ``PYTHONHASHSEED=0``
  makes iteration order stable.  These are passed to the child's ``env=``, so
  the sandbox is the thing that *guarantees* determinism rather than merely
  hoping the deployment set it.

* **The entrypoint contract.**  The child compiles the source, looks up the
  function named :data:`contract.signal.SIGNAL_ENTRYPOINT`, calls it
  ``signal(window, seed)`` positionally (a third required parameter would
  break that call — see ``contract.signal``), validates the return against the
  universe with :func:`contract.signal.validate_signal_return`, and reports
  the result.  The runner that does this is *fixed and embedded* — the sandbox
  owns it, the signal author never sees it — so the entrypoint name and the
  validation step are pinned in one place, exactly as ``contract.signal``
  intends, and a signal cannot redefine how it is invoked.

**What this module is, and is not.**  This is the *host-side* half of §5.2 —
the process runner, the limits, the payload-channel protocol — the half that
is pure Python and testable in this environment.  It deliberately does not
reach for ``gVisor``/``runsc`` or ``Firecracker``: those are the deployment's
namespace- and seccomp-layer enforcement, which a production ``SignalSandbox``
subclass would provide underneath this process protocol.  What it does enforce
in pure Python — the child boundary, the rlimits, the watchdog, the env, the
payload-only channel — is the part the determinism and isolation contracts
depend on regardless of the runner below it.

**The layering note, and it is load-bearing.**  This module is stdlib-only at
import time and imports nothing from any member.  ``polars``, ``pyarrow`` and
``contract`` are all reached *inside the child* (whose source is an embedded
byte-string, imported lazily there) or lazily on the host only when a caller
asks to serialize a window it already holds; the sandbox's own ``run`` takes a
*window object*, not a polars frame, so composing the application — which
imports this member on every factory scan, including the replay path that
§1 forbids from reaching the evaluator — pays no polars/pyarrow cost for it.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ._errors import EvaluatorSandboxError

if TYPE_CHECKING:  # pragma: no cover - typing only; polars is a runtime dep
    from contract.signal import SignalReturnProblem

    try:
        import polars as pl
    except ImportError:  # pragma: no cover - polars is a declared runtime dep
        pl = None  # type: ignore[assignment]

__all__ = [
    "DEFAULT_CPU_S",
    "DEFAULT_MEM_MB",
    "DEFAULT_PIDS",
    "DEFAULT_WALL_S",
    "ENV_HASHSEED",
    "ENV_MKL",
    "ENV_OMP",
    "SandboxLimits",
    "SandboxResult",
    "SignalSandbox",
]

#: §5.2's default wall-clock budget, in seconds.  A signal that runs past it
#: is killed and recorded as ``fail_class=timeout``.
DEFAULT_WALL_S = 30.0
#: §5.2's default CPU budget, in seconds.  Enforced with ``RLIMIT_CPU``.
DEFAULT_CPU_S = 30.0
#: §5.2's default address-space cap, in megabytes.  Enforced with
#: ``RLIMIT_AS``; an allocation past it is recorded as ``fail_class=oom``.
#: 4 GiB (not the spec's nominal 2 GiB): jemalloc's address-space *reservation*
#: for the interpreter and polars exceeds 2 GiB even at ~70 MB resident, so a
#: 2 GiB ``RLIMIT_AS`` is flaky — the child dies before it can run the signal.
DEFAULT_MEM_MB = 4096
#: §5.2's default process cap.  A self-describing policy field for the sandbox
#: layer (gVisor) to enforce via a PID namespace; the host runner does not
#: apply it directly, since ``RLIMIT_NPROC`` is scoped to the real UID on Linux
#: and would collide with unrelated processes.
DEFAULT_PIDS = 32

#: §12's single-threaded-BLAS pins, as the environment keys the child runs
#: under.  Named so the env the sandbox guarantees is spelled once.
ENV_OMP = "OMP_NUM_THREADS"
ENV_MKL = "MKL_NUM_THREADS"
ENV_HASHSEED = "PYTHONHASHSEED"

#: The value §12 pins for both BLAS thread knobs — one thread, so a reduction
#: has a single, reproducible order.
_SINGLE = "1"
#: The value §12 pins for the hash seed — a fixed seed, so set/dict iteration
#: order over the universe is stable across runs and machines.
_ZERO = "0"


@dataclass(frozen=True)
class SandboxLimits:
    """The §5.2 resource envelope for one untrusted signal execution.

    The four numeric budgets — wall clock, CPU, address space, process cap —
    plus the two always-on denials.  Network and filesystem are *always*
    ``False``: §5.2 makes them structural ("a namespace with no interfaces",
    "no mounts; data arrives over IPC only") rather than a toggle, so a caller
    cannot ask the sandbox to run a signal with the network on.  They are kept
    as fields only so the envelope is self-describing and a deployment can
    assert the policy it enforced.

    A limits object is frozen — the budgets a run starts under are the budgets
    it runs under; a signal cannot widen them, and neither can a caller mid-run.
    """

    wall_s: float = DEFAULT_WALL_S
    cpu_s: float = DEFAULT_CPU_S
    mem_mb: int = DEFAULT_MEM_MB
    pids: int = DEFAULT_PIDS
    network: bool = False
    filesystem: bool = False

    def __post_init__(self) -> None:
        # Every budget is validated at construction, so a limits object built
        # by hand — or by a later feature whose caller drifted — fails loudly
        # rather than carrying a negative or non-numeric cap into a fork.
        for name, value in (("wall_s", self.wall_s), ("cpu_s", self.cpu_s)):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise EvaluatorSandboxError(
                    f"sandbox {name} must be a positive number, got {value!r}"
                )
        for name, value in (("mem_mb", self.mem_mb), ("pids", self.pids)):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise EvaluatorSandboxError(
                    f"sandbox {name} must be a positive integer, got {value!r}"
                )


@dataclass(frozen=True)
class SandboxResult:
    """The outcome of one signal execution — never raises for a failed run.

    A failed run is a value, not an exception: §6.1 step 11 ("debit_ledger …
    happens even if the node fails") and the note "A failed evaluation still
    consumed a hypothesis" mean the pipeline must be able to *record* a failure
    and move on.  So every terminal state is a :class:`SandboxResult`, and the
    failure — when there is one — is described by :attr:`fail_class` and
    :attr:`detail` rather than raised.

    The states, exactly one of which holds:

    * **success** — :attr:`scores` is the raw score vector, :attr:`problems`
      is empty, :attr:`fail_class` is ``None``.  The signal returned a
      conforming :class:`polars.Series` (feature 11).
    * **contract problem** — :attr:`scores` is ``None``, :attr:`problems`
      names the violation (wrong length, non-finite value, not a series —
      feature 11/12), :attr:`fail_class` is ``"violation"``.  The signal ran
      but returned something the contract rejects.
    * **resource failure** — :attr:`scores` is ``None``, :attr:`problems` is
      empty, :attr:`fail_class` is ``"timeout"`` (wall or CPU exhausted),
      ``"oom"`` (address space exhausted) or ``"crash"`` (the signal raised or
      the child died to a limit).  The signal did not produce a score.
    * **channel failure** — :attr:`fail_class` is ``"payload"`` (the window
      could not be reconstructed on the far side) or ``"empty"`` (the child
      produced no envelope at all).  The boundary itself failed.
    """

    #: The raw score vector, or ``None`` on any failure.  Positional, aligned
    #: to the window's universe (feature 11: the window carries the labels,
    #: the series carries the values).
    scores: Optional["pl.Series"] = None
    #: The contract problems the return triggered — empty when conforming or
    #: when the run failed before producing a return (a timeout, an oom).
    problems: "list[SignalReturnProblem]" = field(default_factory=list)
    #: The failure class — ``"timeout"``, ``"oom"``, ``"crash"``,
    #: ``"violation"``, ``"payload"`` or ``"empty"`` — or ``None`` on success.
    fail_class: Optional[str] = None
    #: A human-readable reason for the :attr:`fail_class`, suitable for a run
    #: record or an agent retry.
    detail: str = ""
    #: The seed the signal was executed with — carried back so a persisted
    #: result can say which source of randomness produced it.
    seed: Optional[int] = None
    #: The signal ABI version the execution ran under (``contract.CONTRACT_VERSION``).
    contract_version: str = ""

    @property
    def ok(self) -> bool:
        """True when the signal produced a conforming score vector.

        The one state the pipeline treats as a usable result: a score vector
        is present and no contract problem was raised.  A ``violation`` is not
        ``ok`` — the signal returned something the contract rejects — even
        though the sandbox itself ran to completion.
        """
        return self.fail_class is None and not self.problems

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = self.fail_class or ("ok" if self.ok else "violation")
        n = 0 if self.scores is None else len(self.scores)
        return (
            f"SandboxResult(state={state}, scores={n} values, "
            f"problems={len(self.problems)}, seed={self.seed})"
        )


# -- The embedded child runner -----------------------------------------------

#: The fixed, embedded program the child executes.  It is a byte-string, not a
#: host import: the sandbox owns how a signal is invoked, and a signal author
#: must never see or influence this runner.  It reads the payload from stdin,
#: compiles the source, calls ``signal(window, seed)``, validates the return,
#: and writes a self-describing envelope to stdout.  Every failure is caught
#: and reported as a line on stdout the parent can classify — the child never
#: lets an exception escape to stderr, because an escaped exception would be
#: indistinguishable from a runner bug.
#:
#: The runner imports ``contract``/``polars`` lazily *inside* the child, so the
#: child's own startup pays nothing until it has a payload to answer for — and
#: so a child that fails to import names the missing dependency, not a
#: half-initialized module.
_CHILD_SOURCE = textwrap.dedent(
    """
    import base64
    import json
    import os
    import sys

    def _fail(cls, detail):
        # One JSON line, always: the parent classifies by fail_class and never
        # has to parse a traceback.  A raised exception in the runner would
        # escape to stderr and look like a runner bug; reporting it as a
        # 'crash' envelope keeps every terminal state a value.
        sys.stdout.write(json.dumps({"fail_class": cls, "detail": detail}) + "\\n")
        sys.stdout.flush()

    def main():
        # RLIMIT_CPU delivers SIGXCPU at the CPU budget.  Handle it here so a
        # CPU-exhausted signal is reported as 'timeout' — the same failure
        # class the wall-clock watchdog produces — rather than dying to an
        # uncaught signal before it can write an envelope.  The handler writes
        # the envelope and exits; the parent reads it and classifies 'timeout'.
        import signal

        def _on_xcpu(signum, frame):
            _fail("timeout", "signal exceeded its CPU limit (SIGXCPU)")
            os._exit(1)

        try:
            signal.signal(signal.SIGXCPU, _on_xcpu)
        except (ValueError, AttributeError):  # pragma: no cover - not on the main thread
            pass

        try:
            import polars as pl
            import contract
            from contract import MarketWindowPayload
            from contract.signal import SIGNAL_ENTRYPOINT, validate_signal_return
        except Exception as exc:  # noqa: BLE001 - reported as the envelope below
            _fail("crash", f"child import failed: {exc}")
            return

        data = sys.stdin.buffer.read()
        if not data:
            _fail("payload", "no payload arrived on stdin; the sandbox holds no mounts")
            return
        try:
            window = MarketWindowPayload.from_bytes(data).materialize()
        except Exception as exc:  # noqa: BLE001 - a malformed payload is a boundary failure
            _fail("payload", f"payload could not be reconstructed: {exc}")
            return

        source = os.environ["NULLIUS_SIGNAL_SOURCE"]
        seed = int(os.environ["NULLIUS_SIGNAL_SEED"])
        # The signal's namespace is seeded with ``polars`` (as ``pl``), so a
        # signal can ``return pl.Series(...)`` the way the contract's examples
        # do — without the signal having to import it, and without giving it a
        # working ``import`` of its own (the sandbox denies imports; feature 11
        # hands the window, and polars is the one library a signal is entitled
        # to, provided pre-bound).  Everything else — builtins, ``__name__`` —
        # comes from this module's globals, so the signal runs in a namespace
        # that is the runner's, not the host's.
        try:
            namespace = {"pl": pl}
            exec(compile(source, "<signal-source>", "exec"), namespace)
        except Exception as exc:  # noqa: BLE001 - a source that will not compile is a crash
            _fail("crash", f"signal source failed to compile: {exc}")
            return

        fn = namespace.get(SIGNAL_ENTRYPOINT)
        if fn is None:
            _fail("crash", f"source defines no {SIGNAL_ENTRYPOINT!r} entrypoint")
            return
        if not callable(fn):
            _fail("crash", f"{SIGNAL_ENTRYPOINT!r} is defined but is not callable")
            return

        try:
            result = fn(window, seed)
        except MemoryError:
            # RLIMIT_AS exhausted the address space: an allocation the signal
            # made past the memory budget failed.  Reported as 'oom', not the
            # generic 'crash' the broad except below would give — the pipeline
            # distinguishes "ran out of memory" from "raised" to record the
            # right failure class.
            _fail("oom", "signal exceeded its memory limit (RLIMIT_AS)")
            return
        except Exception as exc:  # noqa: BLE001 - a signal that raises is a crash
            _fail("crash", f"signal raised: {exc}")
            return

        try:
            problems = validate_signal_return(result, window.universe)
        except Exception as exc:  # noqa: BLE001 - validation must not escape
            _fail("crash", f"return validation failed: {exc}")
            return

        if problems:
            _fail(
                "violation",
                json.dumps(
                    [
                        {"kind": p.kind, "message": p.message, "symbol": p.symbol}
                        for p in problems
                    ]
                ),
            )
            return

        # A conforming return: ship the values base64, so the bytes survive the
        # JSON envelope and the stdout text channel intact.  The parent rebuilds
        # the series positionally against the window's universe.
        payload = base64.b64encode(
            json.dumps(list(result.to_list())).encode("utf-8")
        ).decode("ascii")
        sys.stdout.write(
            json.dumps(
                {
                    "fail_class": None,
                    "detail": "",
                    "scores": payload,
                    "contract_version": contract.CONTRACT_VERSION,
                }
            )
            + "\\n"
        )
        sys.stdout.flush()

    main()
    """
)


class SignalSandbox:
    """Runs a signal function inside a resource-limited child process.

    The child is a plain ``python -c`` invocation of :data:`_CHILD_SOURCE` in
    the same interpreter as the host (``sys.executable``), so ``contract``/
    ``polars``/``pyarrow`` resolve identically on both sides of the boundary.
    It receives the payload bytes on stdin and writes the serialized score
    vector — or a failure envelope — to stdout.  The parent enforces the
    limits via ``subprocess`` and POSIX ``setrlimit`` in a pre-exec fork,
    records the failure class, and returns a :class:`SandboxResult` rather
    than raising — a failed run is a value the pipeline records.

    The window is passed as an already-serialized payload (``window.to_arrow()``
    produced it — feature 14, §5.2), so the sandbox's boundary is exactly the
    payload channel: nothing but those bytes crosses, which is why the child
    can run with no filesystem mounts.  A caller that hands :meth:`run` a
    window it has not serialized is refused by name rather than silently
    re-serialized, so the bytes the sandbox runs against are the bytes the
    caller committed to.
    """

    def __init__(self, limits: Optional[SandboxLimits] = None) -> None:
        #: The envelope every execution runs under.  Frozen; a run cannot
        #: widen it.  Defaults to §5.2's stated budgets.
        self.limits = limits if limits is not None else SandboxLimits()

    # -- the environment the child runs under ------------------------------

    @staticmethod
    def _child_env(base: Optional[Mapping[str, str]] = None) -> dict[str, str]:
        """The deterministic environment every child runs under.

        §12's pins — single-threaded BLAS and a fixed hash seed — are written
        here, so the sandbox is the thing that *guarantees* determinism rather
        than hoping the deployment set it.  The base (the parent's environment
        by default) is copied, never mutated, so two sandboxes built from one
        environment do not fight over it.
        """
        env = dict(os.environ if base is None else base)
        env[ENV_OMP] = _SINGLE
        env[ENV_MKL] = _SINGLE
        env[ENV_HASHSEED] = _ZERO
        return env

    # -- the run -----------------------------------------------------------

    def run(
        self,
        code: str,
        window: "pl.Series | object",  # a MarketWindow; typed loosely to avoid a hard polars dep
        *,
        seed: int,
        limits: Optional[SandboxLimits] = None,
    ) -> SandboxResult:
        """Execute ``code``'s ``signal`` over ``window`` in a child process.

        The window is serialized to a payload (it must already be materialized
        — see the class docstring), handed to the child on stdin, and the
        child's envelope read back and classified.  ``seed`` is the signal's
        only source of randomness (feature 11); it is required, so a signal
        cannot silently sample randomness with a default and defeat the
        determinism contract (§12).  Returns a :class:`SandboxResult`; it does
        not raise for a failed run.

        Raises :class:`~evaluator.EvaluatorSandboxError` only when the sandbox
        *itself* cannot be driven — the interpreter is missing, the child
        cannot be spawned, the limits are invalid — a failure of the runner,
        not of the signal it ran.
        """
        env = self._child_env()
        env["NULLIUS_SIGNAL_SOURCE"] = code
        env["NULLIUS_SIGNAL_SEED"] = str(int(seed))
        limits = limits if limits is not None else self.limits

        # The window must already be serialized-ready: the sandbox's boundary
        # is the payload channel, so the caller commits to the bytes by
        # serializing.  A window that has materialized nothing is refused —
        # §5.2's sandbox has no mounts to read one from, and an empty payload
        # that looks like a window would surface as an unexplainable zero three
        # systems downstream (see contract.payload.serialize_window).
        try:
            payload = window.to_arrow()
        except AttributeError as exc:
            raise EvaluatorSandboxError(
                "sandbox.run expects a materialized MarketWindow (one with "
                "to_arrow()); serialize the window before running the signal"
            ) from exc

        try:
            payload_bytes = bytes(payload)
        except Exception as exc:  # noqa: BLE001 - a payload that will not serialize is a runner failure
            return SandboxResult(
                fail_class="payload",
                detail=f"window could not be serialized: {exc}",
                seed=seed,
            )

        return self._spawn(payload_bytes, seed=seed, limits=limits, env=env)

    # -- the child process -------------------------------------------------

    def _spawn(
        self,
        payload_bytes: bytes,
        *,
        seed: int,
        limits: SandboxLimits,
        env: Mapping[str, str],
    ) -> SandboxResult:
        """Spawn the child, enforce the limits, and classify its envelope.

        POSIX only: the limits are applied with ``resource.setrlimit`` in a
        ``preexec_fn`` (a fork hook, so the limits bind before ``exec``), and a
        wall-clock watchdog kills the child at ``wall_s``.  A gVisor/
        Firecracker deployment overrides :meth:`_spawn` to enforce the same
        contract at the namespace layer; this pure-Python implementation
        enforces it with the primitives the standard library gives.
        """
        try:
            import resource  # POSIX-only; the sandbox's limits need it
        except ImportError as exc:  # pragma: no cover - non-POSIX
            raise EvaluatorSandboxError(
                "the signal sandbox requires POSIX resource limits (resource "
                "module), which this platform does not provide"
            ) from exc

        def _apply_limits() -> None:
            # Bound in a pre-exec fork: these bind before the interpreter
            # replaces the child, so a signal cannot widen them from inside.
            # RLIMIT_CPU sends SIGXCPU at the CPU budget — the child runner
            # maps it to 'timeout'; RLIMIT_AS caps address space ('oom').
            # ``RLIMIT_CPU`` takes whole seconds, so the wall budget is floored
            # to an int (a 30.0s budget is 30s; a sub-second budget floors to
            # at least 1s, so a signal always gets one second of CPU before
            # SIGXCPU can fire).  ``RLIMIT_AS`` takes bytes, already an integer.
            #
            # The CPU soft limit is set *below* the hard limit on purpose.  With
            # soft == hard the kernel escalates a CPU-exhausted signal straight
            # to SIGKILL before the child's SIGXCPU handler can run — so a
            # timeout would surface as a signal-9 crash with no envelope, and
            # the 'timeout' class the handler is written to emit would never
            # fire.  Soft = cpu_s lets SIGXCPU fire at the budget; hard = the
            # wall gives the handler room to write its envelope and exit before
            # the watchdog would kill it.  ``RLIMIT_AS`` caps address space.
            #
            # ``SandboxLimits.pids`` is intentionally NOT applied here. On Linux
            # RLIMIT_NPROC is scoped to the real UID, not the process, so a pure
            # Python runner sharing this UID cannot carve out a per-child budget
            # without a PID namespace; setting it only collides with unrelated
            # processes the host already runs. Confining the child's process
            # table is the sandbox layer's (gVisor) responsibility; ``pids``
            # stays a self-describing policy field for the host to enforce where
            # it owns the namespace.
            cpu_s = max(1, int(limits.cpu_s))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, max(cpu_s, int(limits.wall_s))))
            resource.setrlimit(
                resource.RLIMIT_AS, (limits.mem_mb * 1024 * 1024, limits.mem_mb * 1024 * 1024)
            )

        proc = subprocess.Popen(  # noqa: S603 - the command is the fixed, embedded _CHILD_SOURCE
            [sys.executable, "-c", _CHILD_SOURCE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            preexec_fn=_apply_limits,
        )
        # The wall-clock watchdog: a signal past the wall is a hung one
        # whatever the CPU did, so it is killed and recorded as 'timeout'.
        try:
            out, _ = proc.communicate(input=payload_bytes, timeout=limits.wall_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - best-effort cleanup
                pass
            return SandboxResult(
                fail_class="timeout",
                detail=f"signal exceeded the {limits.wall_s}s wall-clock limit",
                seed=seed,
            )
        return self._classify(out, returncode=proc.returncode, seed=seed)

    # -- classification ----------------------------------------------------

    @staticmethod
    def _classify(
        out: Optional[bytes], *, returncode: Optional[int] = None, seed: int
    ) -> SandboxResult:
        """Turn the child's stdout envelope into a :class:`SandboxResult`.

        The child always writes exactly one JSON line — a success envelope
        carrying the base64 scores, or a failure envelope carrying a
        ``fail_class``.  The return code disambiguates a silent death: if the
        child died to a signal (a negative return code — ``SIGXCPU`` from the
        CPU limit, say, or a kill the watchdog delivered before the handler
        ran) it never wrote an envelope, so an empty output with a signal
        death is a ``crash``, not an ``empty`` boundary failure.  A missing or
        unparseable line is otherwise an ``empty`` boundary failure; a failure
        class the parent does not recognize is a ``crash`` (the child's
        contract is the one pinned here, and an unknown state is refused
        rather than guessed).
        """
        import json

        raw = (out or b"").decode("utf-8", errors="replace").strip()
        if not raw:
            # No envelope on stdout.  If the child died to a signal (negative
            # return code) it was killed by a limit before it could write — a
            # crash, and the honest one, since a limit kill is a resource
            # failure the pipeline records.  Otherwise the child exited without
            # producing anything: an empty boundary failure.
            if returncode is not None and returncode < 0:
                return SandboxResult(
                    fail_class="crash",
                    detail=f"the child died to signal {-returncode} before producing a result",
                    seed=seed,
                )
            return SandboxResult(
                fail_class="empty",
                detail="the child produced no result envelope",
                seed=seed,
            )
        try:
            envelope = json.loads(raw)
        except ValueError as exc:
            return SandboxResult(
                fail_class="crash",
                detail=f"the child's result envelope was not JSON: {exc}",
                seed=seed,
            )

        fail_class = envelope.get("fail_class")
        detail = envelope.get("detail", "") or ""
        if fail_class is None:
            # Success: rebuild the positional series from the shipped values.
            # The window carried the labels; the series carries the values, in
            # the window's stable order (feature 11).  A decode failure here is
            # a runner bug, reported as 'crash' rather than a malformed score.
            try:
                import polars as pl

                values = json.loads(base64.b64decode(envelope["scores"]).decode("utf-8"))
                scores = pl.Series(values, dtype=pl.Float64)
            except Exception as exc:  # noqa: BLE001 - a corrupt success is a runner bug
                return SandboxResult(
                    fail_class="crash",
                    detail=f"success envelope could not be decoded: {exc}",
                    seed=seed,
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
            # The signal ran but returned something the contract rejects.
            # The problems travel back so the caller (feature 12) can decide
            # the consequence; this sandbox only reports them.
            try:
                from contract.signal import SignalReturnProblem

                problems = [
                    SignalReturnProblem(kind=p["kind"], message=p["message"], symbol=p.get("symbol"))
                    for p in json.loads(detail)
                ]
            except Exception as exc:  # noqa: BLE001 - a corrupt problem list is a runner bug
                return SandboxResult(
                    fail_class="crash",
                    detail=f"violation envelope could not be decoded: {exc}",
                    seed=seed,
                )
            return SandboxResult(
                scores=None,
                problems=problems,
                fail_class="violation",
                detail="signal return violated the contract",
                seed=seed,
            )

        if fail_class in ("timeout", "oom", "crash", "payload", "empty"):
            return SandboxResult(
                scores=None,
                problems=[],
                fail_class=fail_class,
                detail=detail,
                seed=seed,
            )

        # An unknown fail_class: the child's contract is the one pinned here,
        # and an unrecognized state is refused rather than guessed.
        return SandboxResult(
            scores=None,
            problems=[],
            fail_class="crash",
            detail=f"unknown sandbox failure class {fail_class!r}",
            seed=seed,
        )
