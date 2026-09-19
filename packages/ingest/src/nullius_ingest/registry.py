"""The registration seam later ingest features plug workers into.

The ingest features that follow feature 16 (klines, aggTrades, L2 diffs,
derived book features, funding, exchangeInfo — app_spec.xml features
17–29) each contribute *one worker for one stream class*.  They do that
by registering a **worker factory** here as an import side effect, the
same idiom the application factory itself uses
(:func:`app.module_loader.register`): a worker module is imported, its
``@register_worker`` decorator fires, and the ingest component builder
(:func:`nullius_ingest.build_ingest`) later asks
:func:`build_default_workers` for one worker per registered class and
hands them to a fresh :class:`~nullius_ingest.supervisor.IngestSupervisor`.

To add a stream worker, later features therefore:

1. create a module (convention: ``nullius_ingest/streams/<name>.py``)
   whose worker satisfies :class:`~nullius_ingest.worker.IngestWorker`,
2. register its zero-argument factory::

       @register_worker(StreamClass.KLINES)
       def build_klines_worker() -> IngestWorker:
           return KlinesWorker(...)

3. import that module from ``nullius_ingest/__init__.py`` so a scan of
   the package fires the registration.

Factories, not worker instances, are registered because composition
must be able to build a fresh supervisor — with fresh workers — each
time the application is composed; a factory keeps workers
composition-scoped instead of process-global.  A later registration
for the same stream class replaces the earlier one, mirroring the
module loader's "last import of the same name wins"; a re-registered
class is a revision of the same worker, never a second worker.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from .streams import StreamClass, coerce_stream_class
from .supervisor import IngestSupervisor
from .worker import IngestWorker

__all__ = [
    "WorkerFactory",
    "WorkerRegistry",
    "build_default_workers",
    "default_worker_registry",
    "register_worker",
]

#: A worker factory: builds a fresh worker for one stream class.
WorkerFactory = Callable[[], IngestWorker]


class WorkerRegistry:
    """A mutable map of stream class to worker factory.

    Registries are first-class objects rather than one hidden global, so
    tests (and anything else wanting an isolated set of workers) can
    register into their own instance and never touch the default.  The
    default registry below is what the component builder reads.
    """

    def __init__(self) -> None:
        self._factories: dict[StreamClass, WorkerFactory] = {}

    def register(
        self, stream_class: StreamClass | str, factory: WorkerFactory
    ) -> WorkerFactory:
        """Record ``factory`` for ``stream_class``; a re-registration replaces."""
        stream = coerce_stream_class(stream_class)
        if not callable(factory):
            raise TypeError(
                f"worker factory for {stream} must be callable, "
                f"got {type(factory).__name__}"
            )
        self._factories[stream] = factory
        return factory

    def stream_classes(self) -> tuple[StreamClass, ...]:
        """The registered stream classes, in deterministic order."""
        return tuple(sorted(self._factories, key=str))

    def build_workers(self) -> list[IngestWorker]:
        """Build one worker per registered class, in deterministic order."""
        return [self._factories[stream]() for stream in self.stream_classes()]

    def __len__(self) -> int:
        return len(self._factories)

    def __contains__(self, stream: object) -> bool:
        try:
            return coerce_stream_class(stream) in self._factories
        except TypeError:
            return False


#: The process-wide registry the component builder reads from.
_default_registry = WorkerRegistry()


def default_worker_registry() -> WorkerRegistry:
    """The default registry :func:`register_worker` writes to."""
    return _default_registry


def register_worker(
    stream_class: StreamClass | str,
    factory: Optional[WorkerFactory] = None,
    *,
    registry: Optional[WorkerRegistry] = None,
) -> Callable[[WorkerFactory], WorkerFactory]:
    """Register a worker factory for a stream class.

    Usable directly::

        register_worker(StreamClass.FUNDING, build_funding_worker)

    or as a decorator over the factory::

        @register_worker(StreamClass.FUNDING)
        def build_funding_worker() -> IngestWorker: ...

    ``registry`` defaults to the process-wide registry the component
    builder reads; pass an explicit one to keep registrations isolated
    (tests do).  Returns the factory unchanged, like the module loader's
    own ``register`` — registration is a side effect, not a wrapper.
    """
    target = registry if registry is not None else _default_registry

    def decorator(fn: WorkerFactory) -> WorkerFactory:
        target.register(stream_class, fn)
        return fn

    if factory is not None:
        decorator(factory)
    return decorator


def build_default_workers(
    registry: Optional[WorkerRegistry] = None,
) -> list[IngestWorker]:
    """Build the workers for the composed supervisor, one per registered class.

    With no stream classes registered the list is empty, and
    :class:`IngestSupervisor` composes over it unchanged: an ingest layer
    with no streams yet is a valid, running (if idle) state — the plugin
    registers with the factory from the moment it exists, and streams
    attach to it as later features land.
    """
    target = registry if registry is not None else _default_registry
    return target.build_workers()


def build_supervisor(
    registry: Optional[WorkerRegistry] = None,
) -> IngestSupervisor:
    """Compose a supervisor over the registry's workers (one per class)."""
    return IngestSupervisor(build_default_workers(registry))
