"""The hardened child bootstrap — run as ``python -I _sandbox_child.py``.

additions_spec_gvisor_executor.xml, "Hardened Child", feature 1: this module
*is* the bootstrap it names.  It is never imported by host-side orchestrator
code for its side effects; it is a standalone script a sandbox launcher spawns
(``python -I _sandbox_child.py`` — isolated mode, but not ``-S``: the runtime's
``contract``/``polars``/``pyarrow`` packages live in ``dist-packages``, which
only ``site`` processing adds, and ``-I`` keeps that while still dropping
``PYTHON*`` env vars, the user site and the script-directory ``sys.path``
entry).  It reads one length-framed request on stdin — the signal source, the
seed, and the NLSWIPC window payload — and writes exactly one framed JSON
result to a private descriptor, never to stdout.

Before a byte of agent-authored source is compiled, the bootstrap, in order:

1. duplicates fd 1 to a private descriptor and points fd 1 and fd 2 at
   ``/dev/null``, so a signal's ``print`` cannot reach or corrupt the result
   channel (:func:`_redirect_stdio`);
2. installs an import guard — a ``sys.meta_path`` finder plus a
   ``builtins.__import__`` wrapper — admitting only :data:`AGENT_IMPORTS_ALLOWLIST`
   (:func:`_install_import_guard`);
3. builds a restricted ``__builtins__`` for the signal's execution namespace,
   withholding ``open``, ``exec``, ``eval``, ``compile``, ``input`` and
   ``breakpoint`` (:func:`_agent_builtins`);
4. materializes the :class:`~contract.window.MarketWindow` from the payload.

Only then does it compile the source into a fresh module namespace, call
``signal(window, seed)``, and validate the return.

**Why the import guard admits rather than removes ``__import__``.**  The
obvious reading of "removes ... ``__import__`` access from the builtins the
signal sees" is to pop the name entirely, the way ``open``/``exec``/``eval``
are popped.  That reading is wrong for ``__import__`` specifically, and the
difference is not stylistic: CPython's ``IMPORT_NAME`` bytecode looks up
``__import__`` in the *executing frame's own builtins* and, when the name is
entirely absent, raises ``ImportError: __import__ not found`` **without ever
consulting ``sys.meta_path``** — so a signal with no ``__import__`` at all
could not perform *any* import, including an admitted one like ``import
math``, which contradicts "the agent's own top-level imports are still
checked by name" (an admitted import must succeed).  So what is actually
removed is the agent's access to the *unrestricted* ``__import__``: this
module replaces ``builtins.__import__`` itself, process-wide, with the guarded
wrapper (:func:`_install_import_guard`), and the restricted builtins the
signal's namespace is given is a copy taken *after* that replacement — so the
``__import__`` the signal finds there is already the gate, not the original.
There is no path left to the real one.

**Why there are two hooks, not one.**  The wrapper is the primary gate: every
``import`` statement whose executing frame still has ``__import__`` in its
builtins — the bootstrap's own code, ``polars``/``pyarrow``/``contract``'s own
modules, which keep the ordinary (now-patched) ``builtins`` module as their
``__builtins__`` — goes through it once per statement, with the statement's
own frame as the direct, reliable caller.  The meta-path finder is
defense-in-depth for paths that bypass ``__import__`` outright: a signal whose
namespace lacks the name falls through to the bare import machinery (the
``ImportError`` above describes the case where that machinery gives up
entirely; a module *resolution* — ``importlib.import_module``, a C extension's
own ``PyImport_Import*`` — reaches ``sys.meta_path`` directly instead), and a
transitive submodule load several frames below the statement that triggered it
also reaches the finder before the wrapper sees it again.  Both hooks answer
the identical question (:func:`_admit`), so they cannot disagree about a term.

**Why a trusted root, not a cache check.**  ``polars`` and ``pyarrow`` are
declared allowlist terms already, but what *they* import internally to load
themselves is not: ``polars/__init__.py`` and
``contract``'s own modules reach for stdlib terms this list does not carry
(``os``, ``re``, ``warnings``, ``struct``, ...), and refusing those would
refuse the dependency rather than the agent.  Exempting "whatever is already
in ``sys.modules``" is the wrong fix — ``os`` is resident in every interpreter
before this script even starts, so that rule would hand the agent a working
``import os``.  The right fact to check is *who is asking*: :data:`
_TRUSTED_IMPORT_ROOTS` names the packages the bootstrap itself depends on, and
:func:`_trusted_root_in_stack` walks the call stack looking for one of them —
not just the immediate frame, because ``polars``'s own import of some stdlib
helper can itself trigger that helper's further imports several frames deeper,
and trust has to survive the whole chain, not just the first hop. The agent's
own frame is never one of these names, so its own top-level imports are always
judged by the allowlist alone — "checked by name" exactly as the feature says.

**Why a frame-less or frame-exhausted walk also counts as trusted.**  Some of
what ``polars``'s native (Rust) core imports lazily is triggered with no
``polars`` *Python* frame on the stack at all — its compiled core calls
``PyImport_Import`` directly from Rust, sometimes on a thread it started for
its own parallelism, and CPython does not stitch one thread's frame chain
onto another's. :func:`_trusted_root_in_stack` and :func:`_admit` both treat
that absence as proof of origin rather than as a reason to refuse: the agent
has no way to reach the import machinery without its own compiled frame
somewhere on the walk (see their docstrings), so a walk that never finds it —
whether it runs off the end of the stack, hits ``limit``, or has no frame to
start from — was never asking on the agent's behalf.

**Output.**  One framed JSON result: ``fail_class`` (``None`` on success, else
one of :data:`RESULT_FAIL_CLASSES`), ``detail``, ``scores`` (base64 JSON array
of floats, or ``None``) and ``contract_version``.  This bootstrap only ever
*produces* a subset of that vocabulary itself — ``None`` (success),
``"payload"``, ``"crash"``, ``"oom"`` and ``"violation"`` — because ``"timeout"``
and ``"empty"`` describe what a *launcher* concludes when this process never
gets to write anything at all (hung, or killed outright); a dead child cannot
report its own silence.  The six words are the same vocabulary the evaluator's
own sandbox already uses (``evaluator._sandbox.SandboxResult``), repeated here
by spelling rather than by import — this bootstrap depends on nothing but the
standard library, ``polars``, ``pyarrow`` and ``contract``'s ``payload`` and
``signal`` modules, so the orchestrator's own ``pyproject.toml`` gains no new
dependency for it.

**Honest limits.**  This is the admission layer, not the enforcement layer —
a defense this thorough still cannot stop a compiled extension loaded before
the guard went up from reaching an already-resident module by some path this
script never observes. The actual isolation boundary is the sandbox beneath
it (a hardened subprocess's rlimits, or gVisor's Sentry under a later
feature); what this module guarantees is that *its own* admission decision is
computed from one table, consulted by both hooks, rather than hand-waved at
each call site.
"""

from __future__ import annotations

import base64
import builtins
import json
import os
import struct
import sys
from collections.abc import Callable
from typing import Any, Final

import contract

# Imported eagerly, before the import guard goes up, so every module these
# three need to load themselves is already resident — or, for anything loaded
# lazily later, recognised by the guard's trusted-root check (see
# ``_TRUSTED_IMPORT_ROOTS`` above).  This is the whole of what the bootstrap
# itself imports: the standard library, polars, pyarrow, and the two contract
# modules below (feature 1's own sentence).
import polars
import pyarrow  # noqa: F401  (ditto)
from contract.payload import MarketWindowPayload
from contract.signal import SIGNAL_ENTRYPOINT, validate_signal_return

__all__ = [
    "AGENT_IMPORTS_ALLOWLIST",
    "REQUEST_MAGIC",
    "REQUEST_VERSION",
    "RESULT_FAIL_CLASSES",
    "SIGNAL_SOURCE_FILENAME",
    "ChildRequest",
    "ChildRequestError",
    "decode_request",
    "encode_request",
    "main",
    "read_framed",
    "run_signal",
    "write_framed",
]

# -- the agent import ceiling -------------------------------------------------

#: Restated, by value, from ``packages/sandbox/src/sandbox/imports_allowlist.json``'s
#: ``"allow"`` list — this bootstrap depends on no member but ``contract``
#: (feature 1's own constraint: "the bootstrap imports only the standard
#: library, polars, pyarrow and the contract member's payload and signal
#: modules"), so it cannot *import* ``sandbox.imports`` to read the committed
#: document.  One provenance, pinned by a test on both sides (the suite reads
#: the actual JSON file and asserts the two agree) rather than shared by
#: import — the same discipline :mod:`sandbox.transfer` and
#: :mod:`sandbox.seed` each state for a value they restate from elsewhere.
#:
#: ``numpy`` is deliberately absent, unlike the committed document it
#: restates: that document also governs the static admission screen for
#: submitted policy modules, a check with no installed runtime to answer to,
#: while this ceiling gates code this bootstrap is about to *execute* under
#: the evaluation runtime (the gVisor runtime root, and the evaluator's own
#: environment) — and neither installs numpy.  Admitting a term the runtime
#: cannot import would let a signal pass the guard only to fail with a
#: ``ModuleNotFoundError`` at execution, wasting a trial; refusing it here
#: instead answers with the same deterministic ``disallowed_import`` as any
#: other refused term (campaign-driver gaps, "import-allowlist consistency").
AGENT_IMPORTS_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "math",
        "decimal",
        "fractions",
        "statistics",
        "itertools",
        "functools",
        "datetime",
        "random",
        "typing",
        "collections",
        "dataclasses",
        "__future__",
        "polars",
        "pyarrow",
    }
)

#: Package roots the bootstrap itself depends on.  An import whose call stack
#: passes through one of these is judged to be part of *loading that
#: dependency*, not an agent import, and is admitted regardless of whether the
#: specific term it names is in :data:`AGENT_IMPORTS_ALLOWLIST` — see the
#: module docstring's "why a trusted root, not a cache check".  ``numpy`` is
#: not one of these roots: the bootstrap never imports it eagerly (see the
#: import block above this table), and it is not in
#: :data:`AGENT_IMPORTS_ALLOWLIST` either, so there is no load of it to trust.
_TRUSTED_IMPORT_ROOTS: Final[frozenset[str]] = frozenset({"polars", "pyarrow", "contract"})

#: Builtins withheld from the signal's execution namespace outright — no
#: legitimate signal needs a filesystem handle, a second compiler, or a way to
#: read from stdin or drop into a debugger.  ``__import__`` is deliberately
#: not in this tuple; see the module docstring.
_FORBIDDEN_BUILTINS: Final[tuple[str, ...]] = (
    "open",
    "exec",
    "eval",
    "compile",
    "input",
    "breakpoint",
)

#: The compile filename for agent-emitted source — spelled identically (by
#: convention, not by import) in ``contract.signal._require_signal_module``
#: and in ``evaluator._sandbox``'s embedded child runner, so a traceback or a
#: diagnosis naming a line in "the signal's own source" means one place
#: regardless of which runner produced it.
SIGNAL_SOURCE_FILENAME: Final[str] = "<signal-source>"

#: The full fail-class vocabulary this bootstrap's result envelope may carry —
#: matching the evaluator's own six (``evaluator._sandbox.SandboxResult``).
#: This process only ever *writes* a subset of them; see the module
#: docstring's "Output" section for which, and why the rest are a launcher's
#: conclusion rather than this script's.
RESULT_FAIL_CLASSES: Final[tuple[str, ...]] = (
    "timeout",
    "oom",
    "crash",
    "violation",
    "payload",
    "empty",
)


def _allowlist_covers(name: object) -> bool:
    """Prefix coverage of :data:`AGENT_IMPORTS_ALLOWLIST` — ``polars`` admits
    ``polars.utils``, never the reverse.  Mirrors
    ``sandbox.imports.ImportsAllowlist.covers``, restated rather than imported
    for the reason :data:`AGENT_IMPORTS_ALLOWLIST` itself gives.
    """
    if not isinstance(name, str) or not name:
        return False
    parts = name.split(".")
    return any(".".join(parts[:depth]) in AGENT_IMPORTS_ALLOWLIST for depth in range(1, len(parts) + 1))


def _root(name: str) -> str:
    """The top-level package segment of a dotted name."""
    return name.partition(".")[0]


def _trusted_root_in_stack(frame: Any, *, limit: int = 128) -> bool:
    """Whether any frame from ``frame`` upward belongs to a trusted root, or
    the walk never finds the signal source at all — unless the signal source
    itself sits somewhere in the chain first, which poisons it outright.

    Walks ``frame.f_back`` rather than stopping at the immediate caller,
    because a trusted package's own import of some helper can itself trigger
    that helper's further imports several frames deeper — trust has to survive
    the whole chain a dependency's own loading creates, not just the first
    hop (see the module docstring).  ``limit`` bounds a pathological stack
    rather than walking forever; a dependency chain this deep has never been
    observed and the bound is a safety margin, not a tuned constant.

    A frame compiled from :data:`SIGNAL_SOURCE_FILENAME` poisons the walk the
    moment it is seen: a signal that hands a trusted library a callback —
    ``df.map_elements(cb)`` and the like — runs that callback with the
    library's own frames still on the stack, so without this check a trusted
    root found *above* the callback (nearer the signal's own call into the
    library) would wrongly vouch for an import the callback performs itself.
    The signal source frame is always the asker in that shape, no matter which
    trusted frames sit above or below it, so it must decide the outcome before
    any later frame gets a chance to.

    **Why running out of frames without poisoning also admits.**  A trusted
    dependency's native (Rust, via PyO3) code can trigger a stdlib import with
    *no* Python frame of its own on the stack — polars' Rust core calls
    ``PyImport_Import`` directly, which reaches this process's (already
    patched) ``builtins.__import__`` straight from native code, sometimes on a
    thread the dependency's own parallelism spun up, whose frame chain never
    ran a single line of the agent's code and so never reaches back to
    anything the signal called. The agent, by contrast, can *never* trigger an
    import without its own compiled, filename-tagged frame sitting somewhere
    on this exact walk — there is no path from agent code into the import
    machinery that does not pass through a frame this function would poison on
    first. So a walk that exhausts (by running off the top of the stack, or by
    hitting ``limit``) without ever seeing that poison is conclusive: whatever
    asked was never the agent, which leaves only the bootstrap's own trusted
    dependencies as the asker.
    """
    depth = 0
    while frame is not None and depth < limit:
        if frame.f_code.co_filename == SIGNAL_SOURCE_FILENAME:
            return False
        name = frame.f_globals.get("__name__", "")
        if isinstance(name, str) and _root(name) in _TRUSTED_IMPORT_ROOTS:
            return True
        frame = frame.f_back
        depth += 1
    return True


def _admit(name: str) -> bool:
    """The one decision both import hooks consult — never re-derived twice.

    Admitted when the term itself is on the agent's ceiling, or when the call
    originates from loading a trusted dependency.  Called from exactly one
    frame below the hook (``_GuardedImport`` or ``_GuardedFinder.find_spec``),
    so ``sys._getframe(2)`` from here — skip this function, skip the hook —
    lands on the actual caller.

    When that frame does not exist at all (``sys._getframe(2)`` raises
    ``ValueError``), the import is reached from native code that holds no
    Python frame whatsoever beneath this call — a trusted dependency's own
    PyO3 code calling into Python fresh on a thread it started itself. The
    agent can never produce this shape: the shortest possible agent-triggered
    chain is three frames deep (this function, the hook, and the agent's own
    executing frame), so fewer than that is conclusive proof the asker was
    never the agent (see :func:`_trusted_root_in_stack`'s docstring for the
    same argument applied to a frame chain that exists but never poisons).
    """
    if _allowlist_covers(name):
        return True
    try:
        frame = sys._getframe(2)
    except ValueError:
        return True
    return _trusted_root_in_stack(frame)


def _disallowed_import_error(name: str) -> ImportError:
    return ImportError(
        f"disallowed_import: {name!r} is outside the sandbox's configured "
        f"import allowlist (Hardened Child, feature 1); the committed ceiling "
        f"admits {sorted(AGENT_IMPORTS_ALLOWLIST)!r}"
    )


class _GuardedFinder:
    """``sys.meta_path`` defense-in-depth: gates resolution that bypasses
    ``builtins.__import__`` (an agent namespace with no ``__import__`` at
    all, or a caller that reaches ``importlib``/an extension's own import
    machinery directly).  Inserted at the front of ``sys.meta_path`` so it is
    consulted before any real finder resolves the name; returning ``None``
    defers to those finders for an admitted term, exactly as a well-behaved
    finder must.
    """

    def find_spec(self, name: str, path: object, target: object = None) -> None:
        if _admit(name):
            return
        raise _disallowed_import_error(name)


def _install_import_guard() -> None:
    """Replace ``builtins.__import__`` and install the meta-path finder.

    Process-wide and irreversible from the agent's side: there is no saved
    reference to the original ``__import__`` anywhere the signal's namespace
    can reach, because the restricted builtins handed to it
    (:func:`_agent_builtins`) are copied *after* this call.
    """
    real_import = builtins.__import__

    def _guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple = (),
        level: int = 0,
    ) -> Any:
        if not _admit(name):
            raise _disallowed_import_error(name)
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _guarded_import
    sys.meta_path.insert(0, _GuardedFinder())


def _agent_builtins() -> dict[str, Any]:
    """A restricted ``__builtins__`` dict for the signal's execution namespace.

    A copy of the (by now already-guarded) ``builtins`` module's own
    namespace, with :data:`_FORBIDDEN_BUILTINS` withheld.  Must be called
    *after* :func:`_install_import_guard`: the copy carries whatever
    ``builtins.__import__`` currently is, and the whole point is that it is
    the gate, not the original (see the module docstring).
    """
    restricted = dict(vars(builtins))
    for name in _FORBIDDEN_BUILTINS:
        restricted.pop(name, None)
    return restricted


# -- the request wire format ---------------------------------------------------

#: Eight bytes at the head of the request frame.  Distinct from
#: ``contract.payload.PAYLOAD_MAGIC`` (``b"NLSWIPC\\x00"``), which travels
#: *inside* this frame as the window segment, so a reader cannot mistake one
#: container for the other.
REQUEST_MAGIC: Final[bytes] = b"NLSCHREQ"

#: This request container's own version — independent of
#: ``contract.payload.PAYLOAD_VERSION`` and ``contract.CONTRACT_VERSION``,
#: neither of which this framing concerns itself with.
REQUEST_VERSION: Final[int] = 1

#: magic(8s) + version(I) + seed(Q) + source_len(Q) + window_len(Q)
_REQUEST_HEADER: Final[struct.Struct] = struct.Struct("<8sIQQQ")
_LENGTH_PREFIX: Final[struct.Struct] = struct.Struct("<Q")


class ChildRequestError(ValueError):
    """The bytes offered to the bootstrap are not a well-formed request."""


class ChildRequest:
    """One decoded request: the signal source, its seed, and the window payload."""

    __slots__ = ("seed", "source", "window_payload")

    def __init__(self, *, source: str, seed: int, window_payload: bytes) -> None:
        self.source = source
        self.seed = seed
        self.window_payload = window_payload

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"ChildRequest(seed={self.seed!r}, source={len(self.source)} char(s), "
            f"window_payload={len(self.window_payload)} byte(s))"
        )


def encode_request(*, source: str, seed: int, window_payload: bytes) -> bytes:
    """Build the request body (the bytes a launcher frames onto stdin).

    The companion of :func:`decode_request`, kept in this module rather than
    only in the test suite: feature 2's hardened subprocess executor is the
    eventual real sender, and a wire format with one writer and one reader
    living in different places would be two things to keep in sync.
    """
    if not isinstance(source, str):
        raise ChildRequestError(f"source must be str, got {type(source).__name__}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ChildRequestError(f"seed must be a non-negative int, got {seed!r}")
    source_bytes = source.encode("utf-8")
    window_bytes = bytes(window_payload)
    header = _REQUEST_HEADER.pack(
        REQUEST_MAGIC, REQUEST_VERSION, seed, len(source_bytes), len(window_bytes)
    )
    return header + source_bytes + window_bytes


def decode_request(data: bytes) -> ChildRequest:
    """Parse a request body (without its outer length prefix).

    Refuses — by raising :class:`ChildRequestError` — a buffer too short for
    the header, a bad magic or version, or one whose declared segment lengths
    disagree with what actually follows, before any of the agent's own code is
    reached.
    """
    if len(data) < _REQUEST_HEADER.size:
        raise ChildRequestError(
            f"request is {len(data)} byte(s), too short for the "
            f"{_REQUEST_HEADER.size}-byte header"
        )
    magic, version, seed, source_len, window_len = _REQUEST_HEADER.unpack_from(data, 0)
    if magic != REQUEST_MAGIC:
        raise ChildRequestError(
            f"request does not begin with the child request magic {REQUEST_MAGIC!r}; "
            f"these bytes are not a sandbox child request"
        )
    if version != REQUEST_VERSION:
        raise ChildRequestError(
            f"request version {version} is not supported; this bootstrap understands "
            f"version {REQUEST_VERSION}"
        )
    body = data[_REQUEST_HEADER.size :]
    expected = source_len + window_len
    if len(body) != expected:
        raise ChildRequestError(
            f"request declares {source_len} source byte(s) and {window_len} window "
            f"byte(s) ({expected} total) but {len(body)} byte(s) follow the header"
        )
    source_bytes = body[:source_len]
    window_bytes = body[source_len:]
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChildRequestError(f"request source is not valid utf-8: {exc}") from exc
    return ChildRequest(source=source, seed=int(seed), window_payload=bytes(window_bytes))


def _read_exact(read: Callable[[int], bytes], n: int) -> bytes:
    """Read exactly ``n`` bytes through a ``read(size) -> bytes`` callable.

    Loops rather than trusting one call: a pipe may hand back fewer bytes than
    requested even when more are coming, and a reader that treated a short
    read as the whole frame would misparse a request that arrived in pieces.
    """
    chunks: list[bytes] = []
    remaining = n
    while remaining:
        chunk = read(remaining)
        if not chunk:
            raise EOFError(
                f"expected {n} byte(s) but the stream closed after "
                f"{n - remaining} byte(s)"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_framed(read: Callable[[int], bytes]) -> bytes:
    """Read one length-framed blob: an 8-byte little-endian length, then that
    many bytes.  ``read`` is anything shaped like ``read(size) -> bytes``
    (``sys.stdin.buffer.read``, ``os.read`` bound to a descriptor, a test's
    in-memory stub).
    """
    (length,) = _LENGTH_PREFIX.unpack(_read_exact(read, _LENGTH_PREFIX.size))
    return _read_exact(read, length)


def write_framed(write: Callable[[bytes], int], data: bytes) -> None:
    """Write one length-framed blob through a ``write(bytes) -> int`` callable.

    Loops on short writes for the same reason :func:`_read_exact` loops on
    short reads: a pipe is free to accept fewer bytes than offered.
    """
    _write_exact(write, _LENGTH_PREFIX.pack(len(data)))
    _write_exact(write, data)


def _write_exact(write: Callable[[bytes], int], data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = write(view[offset:])
        if not written:
            raise EOFError("the result channel accepted zero bytes; it is closed")
        offset += written


# -- running the signal --------------------------------------------------------


def _fail(fail_class: str, detail: str) -> dict[str, Any]:
    return {
        "fail_class": fail_class,
        "detail": detail,
        "scores": None,
        "contract_version": "",
    }


def _ok(scores: polars.Series) -> dict[str, Any]:
    encoded = base64.b64encode(json.dumps(list(scores.to_list())).encode("utf-8")).decode("ascii")
    return {
        "fail_class": None,
        "detail": "",
        "scores": encoded,
        "contract_version": contract.CONTRACT_VERSION,
    }


def run_signal(source: str, seed: int, window_payload: bytes) -> dict[str, Any]:
    """Build the window, run the signal, and return the result envelope.

    Assumes the import guard and the fd redirection are already in place —
    this is the step the bootstrap docstring calls "running agent code", and
    every failure here is caught and reported as a value: nothing this
    function does may let an exception escape to the caller, because an
    escaped exception here would crash the bootstrap before it could write
    its one result.
    """
    # Builtins restriction before the window materializes, in the bootstrap's
    # own stated order (restrict, then build the window, then run the
    # source) — functionally independent of each other, but matching the
    # feature's own bullet order keeps the code and its own docstring from
    # silently drifting apart.
    namespace: dict[str, Any] = {
        "__name__": "_nullius_signal_source",
        "__builtins__": _agent_builtins(),
    }

    try:
        window = MarketWindowPayload.from_bytes(window_payload).materialize()
    except Exception as exc:  # noqa: BLE001 - a malformed payload is a boundary failure
        return _fail("payload", f"window could not be reconstructed: {exc}")

    try:
        compiled = compile(source, SIGNAL_SOURCE_FILENAME, "exec")
        exec(compiled, namespace)  # noqa: S102 - the sandbox child's own load path
    except Exception as exc:  # noqa: BLE001 - a source that will not run is a crash
        return _fail("crash", f"signal source failed to compile or execute: {exc}")

    fn = namespace.get(SIGNAL_ENTRYPOINT)
    if fn is None:
        return _fail("crash", f"source defines no {SIGNAL_ENTRYPOINT!r} entrypoint")
    if not callable(fn):
        return _fail("crash", f"{SIGNAL_ENTRYPOINT!r} is defined but is not callable")

    try:
        result = fn(window, seed)
    except MemoryError:
        return _fail("oom", "signal exceeded its memory limit")
    except Exception as exc:  # noqa: BLE001 - a signal that raises is a crash
        return _fail("crash", f"signal raised: {exc}")

    try:
        problems = validate_signal_return(result, window.universe)
    except Exception as exc:  # noqa: BLE001 - validation must not escape
        return _fail("crash", f"return validation failed: {exc}")

    if problems:
        detail = json.dumps(
            [{"kind": p.kind, "message": p.message, "symbol": p.symbol} for p in problems]
        )
        return _fail("violation", detail)

    return _ok(result)


# -- the process boundary ------------------------------------------------------


def _redirect_stdio() -> int:
    """Duplicate fd 1 to a private descriptor; point fd 1 and fd 2 at ``/dev/null``.

    Done before anything else in :func:`main`, so no agent print — however it
    gets written, a bare ``print()``, a library flushing to the real stdout
    fd behind Python's back — can reach the descriptor the result is written
    to.  Returns the private descriptor the result frame is written to.
    """
    result_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
    finally:
        os.close(devnull_fd)
    return result_fd


def main() -> None:
    """The bootstrap's entry point — one request in, one result out."""
    result_fd = _redirect_stdio()
    try:
        try:
            raw_request = read_framed(sys.stdin.buffer.read)
            request = decode_request(raw_request)
        except Exception as exc:  # noqa: BLE001 - a malformed request is a boundary failure
            result = _fail("payload", f"the request could not be read: {exc}")
        else:
            _install_import_guard()
            result = run_signal(request.source, request.seed, request.window_payload)

        body = json.dumps(result).encode("utf-8")
        write_framed(lambda data: os.write(result_fd, bytes(data)), body)
    finally:
        os.close(result_fd)


if __name__ == "__main__":
    main()
