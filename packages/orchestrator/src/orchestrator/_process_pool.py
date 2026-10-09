"""Process-pool evaluation — a campaign's nodes, evaluated off the GIL.

bug_spec_evaluation_throughput.xml / additions_spec_process_pool_evaluation:
``orchestrator._campaign``'s thread pools (feature 238's ``discovery.run_batch``
and this member's own root-evaluation pool) already bound how many
evaluations run at once to ``evaluation_workers`` — but every one of those
threads still ran :func:`orchestrator._evaluate.evaluate_node`'s own window
materialization, metrics computation and tripwire probes on the parent
interpreter's one GIL.  A sandboxed subprocess already isolates the
*signal's own code*; nothing isolated the orchestration around it.
:class:`ProcessEvaluator` is the fix: the same ``.evaluate(node_id,
campaign_id, depth, code) -> NodeEvaluation`` shape
:class:`~orchestrator.LiveEvaluator` already answers, but every call is
dispatched to a :class:`~concurrent.futures.ProcessPoolExecutor` worker —
a real OS process, so a campaign's evaluation work spends as many cores as
``evaluation_workers`` names instead of one.

**Construct once per worker, not once per node.**  A worker's own
initializer (:func:`_init_worker`) loads the
:class:`~orchestrator._context.EvaluationContext` once
(:func:`~orchestrator._context.load_evaluation_context`, over the parent's
own captured environment — explicit, never the worker's ambient
``os.environ``, so a worker spawned under ``spawn`` sees exactly what the
parent saw at construction time) and composes the application once
(:func:`~app.module_loader.create_app`), resolving the same
``"nulloracle-target-route"``/``"nulloracle"``/``"ledger"`` siblings
:meth:`orchestrator.LiveEvaluator.evaluate` resolves per call — so the
sidecar, the target route and the ledger are each built once per worker
process and reused for every node that worker ever evaluates, not rebuilt
per node.

**Every task answers a picklable :class:`~orchestrator._evaluate.NodeEvaluation`.**
``evaluator.NodeMetrics`` normalizes its three per-date mapping fields into
``types.MappingProxyType`` (Z0's own invariant, never changed from this
member — see the module-level :data:`_METRICS_PROXY_FIELDS` note below), and
a ``mappingproxy`` does not survive :mod:`pickle`.  Rather than touch the
evaluator member, this module teaches :mod:`multiprocessing`'s own pickler
a reduction for :class:`~evaluator.NodeMetrics` (:func:`_register_node_metrics_reducer`,
called once at import time): the three fields cross as plain ``dict``
and are rewrapped in ``MappingProxyType`` on the receiving side, so a
:class:`~evaluator.NodeMetrics` built on one side of the pool is
byte-for-byte the same value read back on the other.  Every other field
reachable from :class:`~orchestrator._evaluate.NodeEvaluation` (the
:class:`signal_agent.ScoreRecord`, the :class:`~evaluator.DebitedTrial`
debit, :class:`~orchestrator._evaluate.NodePersistence`) is already plain
dataclasses and primitives and needs no help.

**SQLite writes stay in the worker, and every one of them waits rather than
fails.**  ``evaluate_node`` persists the node row, the tripwire verdicts, the
ledger debit and the proposal history exactly where it always has — inside
the call, now running in the worker process rather than a parent thread,
through stores this member does not own (the tree writer, the trial ledger,
discovery's attempt log, the proposal store) and so cannot edit a
``busy_timeout`` into one at a time. "Process" mode turns what used to be
GIL-interleaved writes from one interpreter into genuinely concurrent writes
from several OS processes against the same SQLite file, which only widens
the window a transient lock can be held in — not something those stores'
own, pre-existing five-second ``sqlite3`` default was ever asked to survive.
:func:`_init_worker` therefore wraps :func:`sqlite3.connect` itself, once per
worker process, so every connection any store opens from inside that
worker — however many members' worth of them, named or not — waits at
least :data:`_MIN_BUSY_TIMEOUT_SECONDS` for a lock before raising, the same
"teach the cross-cutting behaviour from the calling side" shape
:func:`_register_node_metrics_reducer` already uses for the identical
reason: Z0 is called, never edited.  This module opens no database
connection of its own.

**The pool sizes itself to the host, not just the campaign's own request.**
``max_workers`` is ``min(context.evaluation_workers, cpu_count - 2)``,
never below one — leaving two cores free for the parent's own authoring,
LLM I/O and event-loop threads, the ones a saturated pool would otherwise
starve.  The chosen count is logged once, at construction.

**Shutdown is explicit and idempotent.**  :meth:`ProcessEvaluator.shutdown`
tears the pool down (default: waits for in-flight work); it is registered
with :mod:`atexit` and, in the main thread, as a ``SIGTERM`` handler, so a
killed campaign process does not orphan its workers — and
``orchestrator._campaign`` calls it itself once a campaign's round loop and
root evaluation are done (see ``_continue_campaign``), so a long-lived
process that runs several campaigns never accumulates one pool per
campaign.
"""

from __future__ import annotations

import atexit
import dataclasses
import logging
import os
import signal
import sqlite3
import threading
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from multiprocessing.reduction import ForkingPickler
from types import MappingProxyType
from typing import Any, Final

from evaluator import NodeMetrics

from ._context import EvaluationContext, load_evaluation_context

__all__ = ["ProcessEvaluator"]

_logger = logging.getLogger(__name__)

#: The three :class:`evaluator.NodeMetrics` fields its own ``__post_init__``
#: wraps in ``types.MappingProxyType`` — restated here (this member's
#: restates-rather-than-reaches-into-Z0 convention, the same stance
#: :mod:`orchestrator._evaluate`'s ``_TreeNodeRow`` already takes toward
#: :class:`~evaluator.NodeMetrics`' own field names) so this module can
#: rewrap them without importing anything private from the evaluator
#: member.
_METRICS_PROXY_FIELDS: tuple[str, ...] = ("ic_series", "book_returns", "turnover_series")


def _reduce_node_metrics(obj: NodeMetrics) -> tuple[Any, tuple[type, dict[str, Any]]]:
    """``NodeMetrics``'s pickle reduction: the proxy fields as plain ``dict``.

    Registered with :class:`multiprocessing.reduction.ForkingPickler`
    (:func:`_register_node_metrics_reducer`) rather than edited into the
    evaluator member — Z0 is called and never changed, and a reduction
    registered from the calling side is exactly what :mod:`copyreg` and
    :mod:`multiprocessing.reduction` exist for: teaching :mod:`pickle` how
    to carry a type it does not own, without that type's own module ever
    knowing a reduction was registered for it.
    """
    state = {field.name: getattr(obj, field.name) for field in dataclasses.fields(obj)}
    for name in _METRICS_PROXY_FIELDS:
        value = state.get(name)
        if isinstance(value, MappingProxyType):
            state[name] = dict(value)
    return _rebuild_node_metrics, (type(obj), state)


def _rebuild_node_metrics(cls: type[NodeMetrics], state: dict[str, Any]) -> NodeMetrics:
    """The other half of :func:`_reduce_node_metrics`: rewrap, then rebuild.

    Bypasses ``__init__``/``__post_init__`` entirely (``cls.__new__`` plus
    ``object.__setattr__`` per field, the same construction shape a frozen
    dataclass's own ``copy.replace`` avoids by never calling): ``__init__``
    would re-run every one of :class:`~evaluator.NodeMetrics`' own
    validations against values that already passed them once, on the
    sending side, and a worker process is not the place to repeat work Z0
    already did.
    """
    instance = cls.__new__(cls)
    for name, value in state.items():
        if name in _METRICS_PROXY_FIELDS and isinstance(value, dict):
            value = MappingProxyType(value)
        object.__setattr__(instance, name, value)
    return instance


def _register_node_metrics_reducer() -> None:
    """Register :func:`_reduce_node_metrics` with the pickler
    :mod:`multiprocessing` actually uses.

    ``ForkingPickler.register`` (not the stdlib ``copyreg.dispatch_table``
    directly) is the documented seam for teaching a process pool how to
    carry a type it does not own; called once, at import time, so both the
    parent (sending tasks' arguments — plain primitives, so this never
    actually fires there) and every worker (sending its own
    :class:`~orchestrator._evaluate.NodeEvaluation` back) carry the same
    registration, since both import this module to find the functions
    :mod:`multiprocessing` pickles by reference.
    """
    ForkingPickler.register(NodeMetrics, _reduce_node_metrics)


_register_node_metrics_reducer()


# -- The worker: built once, reused for every node that worker evaluates -------

#: Set once per worker process by :func:`_init_worker`; read by
#: :func:`_evaluate_in_worker`.  Module-level and per-process by
#: construction — a ``spawn``-context worker is a fresh interpreter, so
#: this is never shared across workers and never needs a lock.
_WORKER_CONTEXT: EvaluationContext | None = None
_WORKER_ENDPOINT: Any = None
_WORKER_LEDGER: Any = None


#: The floor every ``sqlite3.connect`` call in a worker process waits for a
#: lock before raising ``sqlite3.OperationalError: database is locked`` —
#: ``sqlite3``'s own default is five seconds, chosen for one interpreter's
#: worth of GIL-interleaved writers; "process" mode can have as many as
#: ``evaluation_workers`` real processes genuinely writing the same file at
#: once, so the window a transient lock holds for is wider than five
#: seconds was ever asked to survive.
_MIN_BUSY_TIMEOUT_SECONDS: Final[float] = 30.0

_BUSY_TIMEOUT_ENFORCED = False


def _enforce_minimum_busy_timeout() -> None:
    """Wrap :func:`sqlite3.connect` so every call waits at least
    :data:`_MIN_BUSY_TIMEOUT_SECONDS` for a lock, in this process only.

    Every store ``evaluate_node`` writes through (the tree writer, the
    trial ledger, discovery's attempt log, the proposal store, this
    module's own tripwire-verdict table) opens its own
    ``sqlite3.connect(path)`` call, and none of them are this member's to
    edit a ``busy_timeout`` into one at a time — they belong to other
    workspace members, several of them Z0's. Wrapping the stdlib function
    itself, once, in :func:`_init_worker`, reaches every one of them
    without touching a line any of those members own: a caller that asked
    for no timeout, or fewer than :data:`_MIN_BUSY_TIMEOUT_SECONDS`
    seconds, gets this floor instead; a caller that explicitly asked for
    *more* keeps what it asked for. Idempotent — safe to call more than
    once per process — because a second worker task must never find
    ``sqlite3.connect`` wrapped twice over.
    """
    global _BUSY_TIMEOUT_ENFORCED
    if _BUSY_TIMEOUT_ENFORCED:
        return
    original_connect = sqlite3.connect

    def connect_with_minimum_timeout(
        database: Any, *args: Any, **kwargs: Any
    ) -> sqlite3.Connection:
        if args:
            positional = list(args)
            positional[0] = max(positional[0], _MIN_BUSY_TIMEOUT_SECONDS)
            args = tuple(positional)
        elif kwargs.get("timeout", 0.0) < _MIN_BUSY_TIMEOUT_SECONDS:
            kwargs["timeout"] = _MIN_BUSY_TIMEOUT_SECONDS
        return original_connect(database, *args, **kwargs)

    sqlite3.connect = connect_with_minimum_timeout
    _BUSY_TIMEOUT_ENFORCED = True


def _init_worker(env: Mapping[str, str]) -> None:
    """One worker's own setup: load the context, compose the app, resolve
    the two siblings — exactly once, before this worker answers its first
    task.

    ``env`` is the parent's own environment, captured at
    :class:`ProcessEvaluator` construction time and handed through
    explicitly (``ProcessPoolExecutor``'s ``initargs``) rather than read
    off this worker's ambient ``os.environ`` — a ``spawn``-context child
    inherits the OS environment it was launched with, which is usually the
    same thing, but a test that wants a worker to see an environment the
    live process never actually exported (a stub sandbox, a scratch
    ``DATABASE_URL``) needs the explicit path, and the production path
    costs nothing extra by taking it too.

    ``orchestrator`` is imported here, lazily, rather than at this
    module's top level: :mod:`orchestrator` imports
    :class:`ProcessEvaluator` from this very module
    (``orchestrator/__init__.py``'s own ``build_live_evaluator``), so a
    top-level ``import orchestrator`` here would be circular at *import*
    time.  By the time this function actually *runs* — in a freshly
    spawned worker, after :mod:`multiprocessing` has already fully
    imported ``orchestrator._process_pool`` (which first fully imports
    ``orchestrator`` itself, the parent package) to find this very
    function — :mod:`orchestrator` is already complete in ``sys.modules``,
    so the import is instant and never partial.  The same deferral
    :meth:`orchestrator.LiveEvaluator.evaluate` already uses for
    :func:`app.module_loader.create_app`, for the analogous reason stated
    there.
    """
    global _WORKER_CONTEXT, _WORKER_ENDPOINT, _WORKER_LEDGER

    _enforce_minimum_busy_timeout()

    import orchestrator
    from app.module_loader import create_app

    context = load_evaluation_context(env)
    if context is None:
        raise RuntimeError(
            "orchestrator._process_pool worker started with no "
            "NULLIUS_EVALUATION_CONFIG in its handed-through environment; "
            "ProcessEvaluator is only ever built from an already-loaded "
            "context, so this worker's own reload must answer the same "
            "configuration the parent process already validated"
        )

    composed = create_app()
    endpoint = composed.get("nulloracle-target-route")
    if orchestrator._route_carries_no_targets(endpoint):
        sidecar = composed.get("nulloracle")
        if sidecar is not None:
            endpoint = orchestrator._sidecar_backed_endpoint(sidecar, context)

    _WORKER_CONTEXT = context
    _WORKER_ENDPOINT = endpoint
    _WORKER_LEDGER = composed.get("ledger")


def _evaluate_in_worker(node_id: str, campaign_id: str, depth: int, code: str) -> Any:
    """One node, evaluated against this worker's already-built siblings.

    The worker-process counterpart of
    :meth:`orchestrator.LiveEvaluator.evaluate`: the same
    :class:`~orchestrator._oracle.SubtreeOracle` built fresh per call
    (construction performs no I/O — see that class's own docstring), but
    ``context``, ``endpoint`` and ``ledger`` are this worker's own,
    resolved once by :func:`_init_worker` rather than rebuilt here.
    """
    from orchestrator._evaluate import evaluate_node
    from orchestrator._oracle import SubtreeOracle

    if _WORKER_CONTEXT is None:
        raise RuntimeError(
            "orchestrator._process_pool._evaluate_in_worker ran before "
            "_init_worker set up this worker's context; ProcessPoolExecutor "
            "is always constructed with initializer=_init_worker, so this "
            "is this module's own invariant having broken"
        )

    oracle = SubtreeOracle(_WORKER_ENDPOINT, database_url=_WORKER_CONTEXT.database_url)
    return evaluate_node(
        node_id,
        campaign_id,
        depth,
        code,
        context=_WORKER_CONTEXT,
        oracle=oracle,
        ledger=_WORKER_LEDGER,
    )


# -- The evaluator: one pool, sized to the host, shut down cleanly -------------


def _pool_worker_count(evaluation_workers: int) -> int:
    """``min(evaluation_workers, cpu_count - 2)``, never below one.

    Leaves two cores free for the parent's own authoring, LLM I/O and
    event-loop threads — the ones a pool that claimed every core would
    starve.  ``os.cpu_count()`` answering ``None`` (a host that cannot
    report its own core count) is treated as one core, the most
    conservative reading.
    """
    cpu_count = os.cpu_count() or 1
    capped = max(1, cpu_count - 2)
    workers = max(1, min(evaluation_workers, capped))
    if workers < evaluation_workers:
        _logger.info(
            "orchestrator._process_pool: capped at %d worker process(es) "
            "(evaluation_workers=%d, cpu_count=%d, cap=cpu_count-2)",
            workers,
            evaluation_workers,
            cpu_count,
        )
    else:
        _logger.info(
            "orchestrator._process_pool: starting %d worker process(es)",
            workers,
        )
    return workers


def _real_module() -> Any:
    """This module, reached by its real, absolutely-importable name.

    ``app.module_loader.create_app`` imports each member's ``__init__.py``
    fresh, under a synthetic package name (``_nullius_scanned_orchestrator``),
    on every call — so when :func:`orchestrator.build_live_evaluator` builds
    a :class:`ProcessEvaluator` from *that* copy's own relative ``from
    ._process_pool import ProcessEvaluator``, this very module is running as
    ``_nullius_scanned_orchestrator._process_pool``, and every function
    defined in it carries that synthetic name as its own ``__module__`` —
    a name no freshly spawned worker process can ``import`` from scratch,
    because it was never a real path, only a ``sys.modules`` entry this
    already-running process invented for its own scan.
    :class:`~concurrent.futures.ProcessPoolExecutor` pickles a plain
    function by reference (module name plus qualified name), so handing it
    one of *that* copy's functions is exactly the ``ModuleNotFoundError:
    No module named '_nullius_scanned_orchestrator'`` a worker would raise
    the moment it tried to unpickle its own initializer.

    :func:`importlib.import_module` on this module's own real dotted name
    always resolves (or performs) a normal, absolute import — orchestrator
    is a real installed workspace member regardless of whether a synthetic
    copy of it also happens to exist in ``sys.modules`` under a different
    key — so the functions read off *that* answer always carry the one
    module name a fresh ``import orchestrator._process_pool`` can find.
    """
    import importlib

    return importlib.import_module("orchestrator._process_pool")


class ProcessEvaluator:
    """The process-pool evaluator — same shape as
    :class:`orchestrator.LiveEvaluator`, dispatched to worker processes.

    Built with the already-loaded ``context`` (the same
    :class:`~orchestrator._context.EvaluationContext`
    ``build_live_evaluator`` loaded to decide ``evaluation_mode`` in the
    first place — loaded once, never reloaded in the parent) and,
    optionally, the environment each worker should load its own context
    from (the process environment, captured once at construction, when
    ``env`` is not given).  Exposes ``.context`` — the same attribute
    :class:`~orchestrator.LiveEvaluator` carries, read by
    ``orchestrator.campaign``'s CLI door — and ``.evaluate(node_id,
    campaign_id, depth, code) -> NodeEvaluation``, submitted to the pool
    and blocked on: the calling thread (one of ``orchestrator._campaign``'s
    own thread-pool slots, or ``discovery.run_batch``'s) waits for the
    worker's answer, so authoring and LLM I/O on sibling threads are never
    touched by this call.
    """

    def __init__(
        self,
        context: EvaluationContext,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.context = context
        self._env: dict[str, str] = dict(os.environ if env is None else env)
        self._lock = threading.Lock()
        self._shut_down = False

        # Always the real orchestrator._process_pool, never whatever
        # synthetically-named copy of this module happened to construct
        # this instance — see _real_module's own docstring.
        real = _real_module()
        self._evaluate_in_worker = real._evaluate_in_worker

        workers = _pool_worker_count(context.evaluation_workers)
        self._pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=get_context("spawn"),
            initializer=real._init_worker,
            initargs=(self._env,),
        )

        atexit.register(self._shutdown_quietly)
        self._prior_sigterm: Any = None
        if threading.current_thread() is threading.main_thread():
            try:
                self._prior_sigterm = signal.signal(signal.SIGTERM, self._on_sigterm)
            except (ValueError, OSError):  # pragma: no cover - platform/thread quirks
                self._prior_sigterm = None

    def evaluate(self, node_id: str, campaign_id: str, depth: int, code: str) -> Any:
        """Evaluate one node in a worker process; block for its answer."""
        future = self._pool.submit(self._evaluate_in_worker, node_id, campaign_id, depth, code)
        return future.result()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut the pool down — idempotent, safe to call more than once.

        ``wait=True`` (the default, used at a campaign's own end) lets
        every already-submitted task finish before the workers exit;
        ``wait=False`` (used from the ``SIGTERM`` handler) cancels
        whatever has not yet started and does not block the signal
        handler.
        """
        with self._lock:
            if self._shut_down:
                return
            self._shut_down = True
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

    def _shutdown_quietly(self) -> None:
        """``atexit``'s own call: never raise during interpreter shutdown."""
        try:
            self.shutdown(wait=True)
        except Exception:
            _logger.warning(
                "orchestrator._process_pool: shutdown at exit raised",
                exc_info=True,
            )

    def _on_sigterm(self, signum: int, frame: Any) -> None:
        """Shut the pool down before this process actually terminates.

        Without this, a bare ``SIGTERM`` (the default handler) kills this
        process immediately, before any ``atexit`` hook runs, which would
        leave every worker process orphaned. Shuts down without waiting
        (every in-flight evaluation is abandoned, the same as any other
        signal-terminated process), then restores whatever handler stood
        before this one and re-raises the signal so this process still
        exits the way a ``SIGTERM`` is expected to.
        """
        self.shutdown(wait=False)
        if callable(self._prior_sigterm):
            self._prior_sigterm(signum, frame)
            return
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(context={self.context!r})"
