"""The worker registry: the seam later ingest features plug into."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from nullius_ingest import (
    FunctionWorker,
    IngestSupervisor,
    StreamClass,
    WorkerRegistry,
    build_default_workers,
    register_worker,
)
from nullius_ingest.registry import build_supervisor, default_worker_registry


def factory(stream: StreamClass | str, rows: int = 1) -> Callable[[], FunctionWorker]:
    """A worker factory whose worker writes ``rows`` per cycle."""

    def build() -> FunctionWorker:
        return FunctionWorker(stream, lambda: rows)

    return build


def test_register_worker_as_decorator_and_directly() -> None:
    registry = WorkerRegistry()

    @register_worker(StreamClass.KLINES, registry=registry)
    def build_klines() -> FunctionWorker:
        return FunctionWorker(StreamClass.KLINES, lambda: 1)

    register_worker(StreamClass.FUNDING, factory(StreamClass.FUNDING), registry=registry)
    # The stream class accepts its plain string value too.
    register_worker("exchangeInfo", factory(StreamClass.EXCHANGE_INFO), registry=registry)

    assert registry.stream_classes() == (
        StreamClass.EXCHANGE_INFO,
        StreamClass.FUNDING,
        StreamClass.KLINES,
    )
    # Registration is a side effect, not a wrapper: the factory is unchanged.
    assert callable(build_klines)


def test_registry_builds_one_worker_per_registered_class() -> None:
    registry = WorkerRegistry()
    registry.register(StreamClass.BOOK_DIFFS, factory(StreamClass.BOOK_DIFFS, rows=3))
    registry.register(StreamClass.AGG_TRADES, factory(StreamClass.AGG_TRADES, rows=4))

    workers = registry.build_workers()

    assert [w.stream_class for w in workers] == [
        StreamClass.AGG_TRADES,
        StreamClass.BOOK_DIFFS,
    ]  # deterministic order, by stream class


def test_registry_builds_fresh_workers_each_call() -> None:
    # Factories, not instances: every composition gets fresh workers.
    registry = WorkerRegistry()
    registry.register(StreamClass.KLINES, factory(StreamClass.KLINES))

    first = registry.build_workers()
    second = registry.build_workers()
    assert first[0] is not second[0]


def test_re_registration_replaces_the_factory() -> None:
    # Mirrors the module loader: a later registration of the same name
    # wins — a revision of one worker, never a second worker.
    registry = WorkerRegistry()
    registry.register(StreamClass.KLINES, factory(StreamClass.KLINES, rows=1))
    registry.register("klines", factory(StreamClass.KLINES, rows=2))

    assert len(registry) == 1
    workers = registry.build_workers()
    assert workers[0].run_cycle().rows_written == 2


def test_registry_rejects_non_callable_factory() -> None:
    registry = WorkerRegistry()
    with pytest.raises(TypeError, match="must be callable"):
        registry.register(StreamClass.KLINES, "nope")  # type: ignore[arg-type]


def test_a_private_registry_never_leaks_into_the_default() -> None:
    # Tests (and isolated compositions) register into their own registry and
    # cannot pollute what the component builder reads.  An isolated
    # registration is visible only in its own registry: the default carries
    # exactly the stream modules that have actually landed (the raw stream
    # workers, the three derived families, funding and exchangeInfo today)
    # and never a test's or a composition's.
    registry = WorkerRegistry()
    registry.register(StreamClass.EXCHANGE_INFO, factory(StreamClass.EXCHANGE_INFO))

    assert StreamClass.EXCHANGE_INFO in registry
    assert build_default_workers(registry=registry) != []
    # The default registry holds the registered stream modules and nothing
    # else — a private registry's factory never appears in it.
    assert default_worker_registry().build_workers()[0] is not (
        registry.build_workers()[0]
    )
    assert set(default_worker_registry().stream_classes()) == {
        StreamClass.BOOK_DIFFS,
        StreamClass.BOOK_FEATURES,
        StreamClass.EXCHANGE_INFO,
        StreamClass.FUNDING,
        StreamClass.MICROSTRUCTURE,
        StreamClass.TRADE_FLOW,
    }


def test_build_supervisor_composes_one_worker_per_class() -> None:
    registry = WorkerRegistry()
    registry.register(StreamClass.KLINES, factory(StreamClass.KLINES, rows=7))
    registry.register(StreamClass.AGG_TRADES, factory(StreamClass.AGG_TRADES, rows=8))

    supervisor = build_supervisor(registry=registry)

    assert isinstance(supervisor, IngestSupervisor)
    report = supervisor.run_cycle()
    assert report.ok
    assert report.rows_written == 15


def test_default_registry_membership_checks() -> None:
    default = default_worker_registry()
    assert "notAStream" not in default
    assert 7 not in default
