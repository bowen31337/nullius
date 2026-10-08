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

import hashlib
import io
import json
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
from ._oci_bundle import CHILD_BOOTSTRAP_PATH, PathLike

__all__ = [
    "GVISOR_RUNTIME_STALE_CODE",
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

#: The greppable code word a construction-time refusal carries when the
#: runtime root's baked contract, app or sandbox-child source no longer
#: matches the host's own copies (bug_spec_gvisor_runtime_staleness.xml) —
#: distinct from :data:`GVISOR_UNAVAILABLE_CODE` because the remedy differs:
#: re-provision the root, not install or point at ``runsc``.
GVISOR_RUNTIME_STALE_CODE: Final[str] = "gvisor_runtime_stale"

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


def _require_child_bootstrap(runtime_root: PathLike) -> None:
    """Raise unless ``runtime_root`` already carries the baked-in child.

    bug_spec_gvisor_bind_boot.xml: the child bootstrap reaches the
    container only by being part of the read-only runtime root
    (``deploy/gvisor/provision_runtime.sh`` bakes it in at
    :data:`~orchestrator._oci_bundle.CHILD_BOOTSTRAP_PATH`), never by a
    bind mount. Checked once, at construction, rather than discovered at
    the first signal's expense — the same "fail at construction" stance
    :func:`_require_runsc` already takes for a missing ``runsc``.
    """
    child = Path(runtime_root) / CHILD_BOOTSTRAP_PATH.lstrip("/")
    if not child.is_file():
        raise GVisorUnavailableError(
            f"{GVISOR_UNAVAILABLE_CODE}: the runtime root ({runtime_root!r}) "
            f"carries no {CHILD_BOOTSTRAP_PATH} — deploy/gvisor/provision_runtime.sh "
            "bakes the child bootstrap into the runtime root at that path; a "
            "GVisorSandbox has nothing to run a signal with until it is "
            "provisioned there."
        )


#: The suffix ``<runtime_root>.manifest.json`` is read from — a sibling of
#: the root, never a file under it, so the manifest is never itself part of
#: the tree digest it describes. The same spelling
#: ``deploy/gvisor/provision_runtime.sh`` writes to (``$ROOT.manifest.json``).
_MANIFEST_SUFFIX: Final[str] = ".manifest.json"


def _manifest_path(runtime_root: PathLike) -> Path:
    return Path(f"{os.fspath(runtime_root)}{_MANIFEST_SUFFIX}")


def _tree_sha256(runtime_root: PathLike) -> str:
    """The provisioning script's own tree digest, recomputed in Python.

    Mirrors ``deploy/gvisor/provision_runtime.sh``'s
    ``find . -type f -perm -004 -print0 | LC_ALL=C sort -z | xargs -0
    sha256sum | sha256sum`` pipeline exactly, so the two agree on a freshly
    provisioned root: every *world-readable* regular file under
    ``runtime_root`` (symlinks excluded, the same as ``find -type f``; a
    file whose mode lacks the other-read bit is skipped by its ``stat()``
    alone, never opened — the same selection ``find -perm -004`` makes) gets
    its own sha256; those are written one per line as ``sha256sum`` itself
    would (``"<hex>  ./<relative path>\\n"``, two spaces), in ``LC_ALL=C``
    path order (plain codepoint order — what :func:`sorted` already gives
    for these paths); the concatenation of those lines is hashed again, and
    that is the tree digest.

    Restricting to world-readable files is what lets the non-root launcher
    recompute the identical digest a root-run provisioning script
    committed to the manifest: a debootstrap root carries a handful of
    root-only files (``/etc/shadow``, ``/etc/.pwd.lock`` and the like,
    mode ``0600``) that only root can read, and none of them is part of the
    executable runtime a sandboxed signal actually runs under. The rule is
    a property of each file's own mode, so root (the provisioner) and an
    ordinary user (the verifier) always select the same set.
    """
    root = Path(runtime_root)
    relpaths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune directories a non-root user cannot traverse (other-exec bit
        # clear), by mode alone — so the digest selects the same files
        # whether root (the provisioner) or an ordinary user (the verifier)
        # walks the tree. A root-run ``find`` would otherwise descend into a
        # 0700 dir such as ``/root`` and hash a world-readable file inside it
        # (``/root/.bashrc``) that the non-root launcher can never reach. The
        # provisioning script prunes the same dirs with ``-perm -001``.
        dirnames[:] = [
            d
            for d in dirnames
            if (Path(dirpath) / d).is_symlink()
            or ((Path(dirpath) / d).stat().st_mode & 0o001)
        ]
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not candidate.stat().st_mode & 0o004:
                continue  # not world-readable — skipped by stat alone, never opened
            relpaths.append(candidate.relative_to(root).as_posix())
    relpaths.sort()

    lines = []
    for rel in relpaths:
        digest = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{rel}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _require_matching_manifest(runtime_root: PathLike) -> None:
    """Raise unless ``<runtime_root>.manifest.json``'s ``tree_sha256`` matches.

    A :class:`GVisorSandbox` is about to run agent-authored code confined
    only by whatever is actually on disk under ``runtime_root`` — so a
    partial debootstrap, a root some other process is still writing, or a
    root someone tampered with after provisioning must be refused here,
    before any container is built, rather than discovered mid-run as a
    missing interpreter or an import that behaves differently than the
    pinned version the manifest names. The manifest is
    ``deploy/gvisor/provision_runtime.sh``'s own output; this is the other
    half of that script's contract, read back at construction.
    """
    manifest_path = _manifest_path(runtime_root)
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GVisorUnavailableError(
            f"{GVISOR_UNAVAILABLE_CODE}: the runtime root ({runtime_root!r}) carries "
            f"no manifest at {manifest_path} — deploy/gvisor/provision_runtime.sh "
            "writes one beside every root it provisions, and a GVisorSandbox refuses "
            "to run agent code in a root it cannot verify against one."
        ) from exc

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GVisorUnavailableError(
            f"{GVISOR_UNAVAILABLE_CODE}: the manifest at {manifest_path} for runtime "
            f"root ({runtime_root!r}) is not valid JSON: {exc}"
        ) from exc

    expected = manifest.get("tree_sha256") if isinstance(manifest, dict) else None
    if not isinstance(expected, str) or not expected:
        raise GVisorUnavailableError(
            f"{GVISOR_UNAVAILABLE_CODE}: the manifest at {manifest_path} for runtime "
            f"root ({runtime_root!r}) carries no tree_sha256 — a GVisorSandbox has "
            "nothing to verify the root's own contents against."
        )

    actual = _tree_sha256(runtime_root)
    if actual != expected:
        raise GVisorUnavailableError(
            f"{GVISOR_UNAVAILABLE_CODE}: the runtime root ({runtime_root!r}) does not "
            f"match its manifest ({manifest_path}) — manifest tree_sha256={expected!r} "
            f"but the root's own contents hash to {actual!r}. Refused rather than run "
            "agent code in a partial or tampered root."
        )


#: The manifest keys ``deploy/gvisor/provision_runtime.sh`` writes beside
#: ``tree_sha256``, each recomputed by :func:`_require_current_runtime_sources`
#: from the host's own sources and compared against the manifest's recording
#: of it. A manifest written before this guard existed (such as a root
#: provisioned before bug_spec_gvisor_runtime_staleness.xml) carries none of
#: these, and is refused the same way as a mismatch — never passed silently.
_STALENESS_MANIFEST_FIELDS: Final[tuple[str, ...]] = (
    "contract_source_sha256",
    "app_source_sha256",
    "child_bootstrap_sha256",
    "contract_version",
)


def _source_tree_sha256(root: PathLike) -> str:
    """sha256 over sorted (relpath, file sha256) lines of every non-__pycache__ file.

    The same per-file line shape :func:`_tree_sha256` uses (``"<hex>
    ./<relpath>\\n"``, two spaces, plain codepoint sort), but for a plain
    source tree rather than a debootstrap runtime root: ``__pycache__`` is
    pruned (a host checkout that has imported its own packages carries
    bytecode caches a freshly baked copy never does) instead of filtering by
    world-readable permission, which has nothing to do with a git-tracked
    source tree. Mirrors ``deploy/gvisor/provision_runtime.sh``'s own
    pipeline over the staged ``site/contract`` and ``site/app`` directories.
    """
    root = Path(root)
    relpaths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relpaths.append(candidate.relative_to(root).as_posix())
    relpaths.sort()

    lines = [f"{hashlib.sha256((root / rel).read_bytes()).hexdigest()}  ./{rel}\n" for rel in relpaths]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _host_contract_dir() -> Path:
    """``packages/contract/src/contract``, from the imported package's own ``__file__``.

    Never a hard-coded path: a workspace member can be reached under the
    module loader's synthetic scan name, and the only thing that is always
    true of ``contract`` is that it is a real, already-importable package
    with a ``__file__`` pointing at its own ``__init__.py``.
    """
    import contract

    return Path(contract.__file__).parent


def _host_app_dir() -> Path:
    """``src/app``, from the imported namespace package's own ``__path__``.

    ``app`` has no ``__init__.py`` (a PEP 420 namespace package), so it has
    no ``__file__`` to anchor on — ``__path__`` is where ``sys.path`` landed
    it instead.
    """
    import app

    return Path(next(iter(app.__path__)))


def _host_child_bootstrap_path() -> Path:
    """``orchestrator/_sandbox_child.py``, from its own ``__file__``."""
    return Path(_child.__file__)


def _require_current_runtime_sources(runtime_root: PathLike) -> None:
    """Raise unless the root's baked contract, app and child match the host's own.

    :func:`_require_matching_manifest` only proves the root is internally
    intact — that its contents still hash to what its own manifest recorded
    at provisioning time. A root provisioned from an older checkout passes
    that check forever, even once the host's own ``packages/contract``,
    ``src/app`` and ``orchestrator/_sandbox_child.py`` have moved on
    (bug_spec_gvisor_runtime_staleness.xml): this is the other half of the
    manifest's contract, comparing the three source digests
    ``deploy/gvisor/provision_runtime.sh`` writes beside ``tree_sha256``
    against a fresh recomputation over the host's own sources.

    Called after :func:`_require_matching_manifest`, never before it: a root
    that fails the tree digest is refused for that reason first, regardless
    of whether it would also fail this one.
    """
    manifest_path = _manifest_path(runtime_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing = [field for field in _STALENESS_MANIFEST_FIELDS if field not in manifest]
    if missing:
        raise GVisorUnavailableError(
            f"{GVISOR_RUNTIME_STALE_CODE}: the manifest at {manifest_path} for runtime "
            f"root ({runtime_root!r}) is missing {', '.join(missing)} — provisioned "
            "before the staleness guard; re-provision with "
            "deploy/gvisor/provision_runtime.sh (needs sudo)."
        )

    host_digests = {
        "contract": (_source_tree_sha256(_host_contract_dir()), "contract_source_sha256"),
        "app": (_source_tree_sha256(_host_app_dir()), "app_source_sha256"),
        "child": (
            hashlib.sha256(_host_child_bootstrap_path().read_bytes()).hexdigest(),
            "child_bootstrap_sha256",
        ),
    }
    stale = [name for name, (host_digest, key) in host_digests.items() if host_digest != manifest.get(key)]
    if stale:
        import contract

        raise GVisorUnavailableError(
            f"{GVISOR_RUNTIME_STALE_CODE}: the runtime root ({runtime_root!r}) was "
            f"provisioned from an older checkout and no longer matches the host's own "
            f"sources — stale: {', '.join(stale)}; manifest contract_version="
            f"{manifest.get('contract_version')!r}, host contract_version="
            f"{contract.CONTRACT_VERSION!r}. Re-provision with "
            "deploy/gvisor/provision_runtime.sh (needs sudo)."
        )


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
    (raising :class:`GVisorUnavailableError` if it is unusable), verifies
    ``runtime_root`` against its own ``<runtime_root>.manifest.json`` (see
    :func:`_require_matching_manifest` — a missing manifest, malformed JSON,
    a missing ``tree_sha256``, or a digest mismatch all refuse construction
    rather than run agent code in a root that cannot be trusted), then
    verifies that root is not merely intact but *current* (see
    :func:`_require_current_runtime_sources` — a root provisioned from an
    older checkout still matches its own manifest forever, so this
    recomputes the contract, app and child digests from the host's own
    sources and refuses a mismatch with :data:`GVISOR_RUNTIME_STALE_CODE`),
    and reads
    the sandbox member's default limits once if none are given, so a
    per-node evaluation that calls :meth:`run` repeatedly pays none of those
    costs twice.
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
        _require_child_bootstrap(runtime_root)
        _require_matching_manifest(runtime_root)
        _require_current_runtime_sources(runtime_root)
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
                    child_path=CHILD_BOOTSTRAP_PATH,
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
