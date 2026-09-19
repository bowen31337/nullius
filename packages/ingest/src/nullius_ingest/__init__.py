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
* :mod:`nullius_ingest.backfill` — :class:`GapBackfiller`, which fills the
  gaps that log records over an injected REST fetch into staging, and
  :class:`SealGate`, which wraps the sealing service and refuses a seal
  while any gap stays open (feature 26; §15's "REST backfill the gap
  before sealing the next snapshot" row).
* :mod:`nullius_ingest.exchange_info` — :class:`ExchangeInfoVersionStore`,
  the append-only version log each daily ``exchangeInfo`` fetch is persisted
  into as a *new* version rather than an overwrite, and
  :class:`DailyExchangeInfoWorker`, the stream worker that owns the daily
  cadence (§4.1's "exchangeInfo filters | REST | daily | forever, versioned"
  row, §13.2's "never hardcoded" rule; feature 24).  It registers itself as
  the ``exchangeInfo`` stream's worker, so importing this package is the
  whole wiring.
* :mod:`nullius_ingest.funding` — :class:`FundingRateStore`, the append-only
  log each 60-second funding/borrow poll is persisted into and retained
  permanently rather than expired, and :class:`FundingRateWorker`, the stream
  worker that owns the 60-second cadence (§4.1's "Funding / borrow rate |
  REST | 1m | forever" row; feature 23).  It registers itself as the
  ``funding`` stream's worker, so importing this package is the whole wiring.
* :mod:`nullius_ingest.book_diffs` — :class:`BookDiffStore`, the append-only log
  of raw L2 book diffs and the rolling 90 day window that retires whole records
  out of it, and :class:`BookDiffWorker`, the stream worker that flushes diffs
  onto the 100 millisecond grid and rolls the window each cycle (§4.1's "L2 book
  diffs | WS @100ms | continuous | rolling 90 days only" row; feature 19).  It is
  the one stream whose retention window *removes* data, which it does through
  :meth:`~nullius_ingest.staging.StagingArea.retire` — whole batches only, so
  append-only survives retention.  It registers itself as the ``bookDiffs``
  stream's worker, so importing this package is the whole wiring.

The package self-registers with the application factory: scanning this
workspace member runs this module, the ``@register`` decorator below
fires, and ``create_app()`` composes the ingest component — a
supervisor with one worker per registered stream class.  The factory
never learns this package's name; like every component, this package
opts in by importing :func:`app.module_loader.register` and nothing else.
"""

from __future__ import annotations

from app.module_loader import register

from .backfill import (
    GAP_FILLED_EVENT,
    GapBackfiller,
    GapFetch,
    GapFilled,
    GapNotFilledError,
    SealGate,
)
from .book_diffs import (
    BIDS,
    ASKS,
    BOOK_DIFFS_STREAM,
    RETENTION,
    RETENTION_DAYS,
    SLICE,
    SLICE_MILLISECONDS,
    BookDiffBatch,
    BookDiffCorruptError,
    BookDiffError,
    BookDiffFetch,
    BookDiffParseError,
    BookDiffRecord,
    BookDiffRow,
    BookDiffStore,
    BookDiffWorker,
    PriceLevel,
    RetentionReport,
    Side,
    align_to_window,
    build_book_diff_worker,
    parse_book_diffs,
    register_book_diff_worker,
    window_start_for,
)
from .exchange_info import (
    EXCHANGE_INFO_STREAM,
    DailyExchangeInfoWorker,
    ExchangeInfoCorruptError,
    ExchangeInfoDocument,
    ExchangeInfoError,
    ExchangeInfoFetch,
    ExchangeInfoParseError,
    ExchangeInfoVersion,
    ExchangeInfoVersionStore,
    FilterType,
    SymbolFilters,
    build_exchange_info_worker,
    parse_exchange_info,
    register_exchange_info_worker,
)
from .funding import (
    CADENCE,
    FUNDING_STREAM,
    FundingCorruptError,
    FundingDocument,
    FundingError,
    FundingFetch,
    FundingParseError,
    FundingRateStore,
    FundingRateWorker,
    FundingReading,
    FundingRecord,
    SIXTY_SECONDS,
    StampedReading,
    build_funding_worker,
    parse_funding,
    register_funding_worker,
)
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
    "ASKS",
    "BIDS",
    "BOOK_DIFFS_STREAM",
    "EXCHANGE_INFO_STREAM",
    "GAP_DETECTED_EVENT",
    "GAP_FILLED_EVENT",
    "Batch",
    "BookDiffBatch",
    "BookDiffCorruptError",
    "BookDiffError",
    "BookDiffFetch",
    "BookDiffParseError",
    "BookDiffRecord",
    "BookDiffRow",
    "BookDiffStore",
    "BookDiffWorker",
    "ColumnSpec",
    "CycleResult",
    "DailyExchangeInfoWorker",
    "DeclaredSchema",
    "ExchangeInfoCorruptError",
    "ExchangeInfoDocument",
    "ExchangeInfoError",
    "ExchangeInfoFetch",
    "ExchangeInfoParseError",
    "CADENCE",
    "ExchangeInfoVersion",
    "ExchangeInfoVersionStore",
    "FilterType",
    "FUNDING_STREAM",
    "FundingCorruptError",
    "FundingDocument",
    "FundingError",
    "FundingFetch",
    "FundingParseError",
    "FundingRateStore",
    "FundingRateWorker",
    "FundingReading",
    "FundingRecord",
    "FunctionWorker",
    "GapBackfiller",
    "GapDetected",
    "GapDetector",
    "GapEventLog",
    "GapFetch",
    "GapFilled",
    "GapNotFilledError",
    "InMemorySequenceStore",
    "IngestReport",
    "IngestSupervisor",
    "IngestWorker",
    "ParquetBatch",
    "PriceLevel",
    "RETENTION",
    "RETENTION_DAYS",
    "ResumableFunctionWorker",
    "ResumableWorker",
    "RetentionReport",
    "SLICE",
    "SLICE_MILLISECONDS",
    "SchemaDrift",
    "SchemaValidatingWorker",
    "SequenceStore",
    "SealGate",
    "Side",
    "SIXTY_SECONDS",
    "StampedReading",
    "StagedBatch",
    "StagingArea",
    "StagingRootError",
    "StreamClass",
    "StreamFailure",
    "StreamOutcome",
    "SymbolFilters",
    "WorkerFactory",
    "WorkerRegistry",
    "align_to_window",
    "build_book_diff_worker",
    "build_default_workers",
    "build_exchange_info_worker",
    "build_funding_worker",
    "build_ingest",
    "build_supervisor",
    "coerce_stream_class",
    "parse_book_diffs",
    "parse_exchange_info",
    "parse_funding",
    "register_book_diff_worker",
    "register_exchange_info_worker",
    "register_funding_worker",
    "register_worker",
    "window_start_for",
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
