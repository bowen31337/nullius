"""nullius.ingest — market-data ingest workers, one per stream class.

This package is the ``ingest`` workspace member (``packages/ingest``),
implementing app_spec.xml feature 16 — *"System isolates each stream
class in its own ingest worker, which returns a per-stream failure
rather than halting all ingest"* — and the §4.1 data-layer rule it
restates: *"separate worker per stream class."*

What lives where:

* :mod:`nullius_ingest.streams` — :class:`StreamClass`, the six stream
  classes from §4.1 and the unit of isolation.
* :mod:`nullius_ingest.worker` — the :class:`IngestWorker` contract, a
  worker's result types, and :class:`StreamFailure` (a failure as data,
  never an escaping exception).
* :mod:`nullius_ingest.supervisor` — :class:`IngestSupervisor`, which
  runs every worker on its own thread and returns an
  :class:`IngestReport` carrying per-stream outcomes; a failing stream
  becomes a failure record in the report while every other stream keeps
  ingesting.
* :mod:`nullius_ingest.registry` — the seam the later ingest features
  (features 17–29) register stream workers into.
* :mod:`nullius_ingest.schema` — :class:`DeclaredSchema` and the drift
  rejection (:class:`SchemaDrift`) that gates each incoming Parquet
  batch on its stream's declared columns, plus the
  :class:`SchemaValidatingWorker` that composes the gate into a cycle
  (feature 27; §15's "exchange schema change" row).
* :mod:`nullius_ingest.watermark` — :class:`SequenceStore`, the durable
  per-stream batch store feature 29 resumes from, and its in-memory
  stand-in.
* :mod:`nullius_ingest.staging` — :class:`StagingArea`, the append-only
  staging area feature 28 writes into, and the write side of the seal
  boundary: staging is a sibling of ``snapshots/``, never on the
  evaluator mount path.
* :mod:`nullius_ingest.gaps` — :class:`GapDetector`, the per-stream
  sequence tracker that detects a websocket gap on reconnect and emits a
  ``gap_detected`` event naming the affected stream (feature 25; §15's
  "WS gap / reconnect" row), and the :class:`GapEventLog` the backfill
  (feature 26) reads.

The package self-registers with the application factory: scanning this
workspace member runs this module, the ``@register`` decorator below
fires, and ``create_app()`` composes the ingest component — a
supervisor with one worker per registered stream class.  The factory
never learns this package's name; like every component, this package
opts in by importing :func:`app.module_loader.register` and nothing else.
"""

from __future__ import annotations

from app.module_loader import register

from .gaps import GAP_DETECTED_EVENT, GapDetected, GapDetector, GapEventLog
from .registry import (
    WorkerFactory,
    WorkerRegistry,
    build_default_workers,
    build_supervisor,
    register_worker,
)
from .schema import (
    ColumnSpec,
    DeclaredSchema,
    ParquetBatch,
    SchemaDrift,
    SchemaValidatingWorker,
)
from .staging import (
    StagedBatch,
    StagingArea,
    StagingRootError,
)
from .streams import StreamClass, coerce_stream_class
from .supervisor import IngestReport, IngestSupervisor
from .watermark import Batch, InMemorySequenceStore, SequenceStore
from .worker import (
    CycleResult,
    FunctionWorker,
    IngestWorker,
    ResumableFunctionWorker,
    ResumableWorker,
    StreamFailure,
    StreamOutcome,
)

__all__ = [
    "GAP_DETECTED_EVENT",
    "Batch",
    "ColumnSpec",
    "CycleResult",
    "DeclaredSchema",
    "FunctionWorker",
    "GapDetected",
    "GapDetector",
    "GapEventLog",
    "InMemorySequenceStore",
    "IngestReport",
    "IngestSupervisor",
    "IngestWorker",
    "ParquetBatch",
    "ResumableFunctionWorker",
    "ResumableWorker",
    "SchemaDrift",
    "SchemaValidatingWorker",
    "SequenceStore",
    "StagedBatch",
    "StagingArea",
    "StagingRootError",
    "StreamClass",
    "StreamFailure",
    "StreamOutcome",
    "WorkerFactory",
    "WorkerRegistry",
    "build_default_workers",
    "build_ingest",
    "build_supervisor",
    "coerce_stream_class",
    "register_worker",
]

__version__ = "0.1.0"

#: The component name this plugin registers under with the factory.
COMPONENT_NAME = "ingest"


@register(COMPONENT_NAME)
def build_ingest() -> IngestSupervisor:
    """Compose the ingest component: one worker per registered stream class.

    Called by the application factory (never imported by name): the
    registry's worker factories — registered by the stream modules that
    later features contribute — each build one worker, and the
    supervisor takes exactly one per stream class.  With no streams
    registered yet the supervisor is empty and valid: composition
    succeeds today, and every later ingest feature lands as a
    registration, not a wiring change.
    """
    return build_supervisor()
