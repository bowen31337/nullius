"""The declared stream schema and the drift rejection at the ingest gate.

docs/nullius-tech-architecture.md §15 names the failure this module
exists to catch — *exchange schema change* — and fixes both halves of
the response in one row:

    | Exchange schema change | Parquet schema validation | Halt ingest
    for that stream; alert; patch |

app_spec.xml feature 27 states the detection as behaviour: *"System
rejects an incoming Parquet batch whose columns drifted from the
declared schema."*  An exchange that renames, adds, removes or re-types
a field changes every batch after it; without a gate that drift flows
silently into the staging log, into the next sealed snapshot and its
``snapshot_hash``, and into every score computed over it — the moment
it is cheapest to stop is the moment the batch arrives, which is the
only moment this module acts on.

Three pieces, each load-bearing:

* **The declared schema** — :class:`DeclaredSchema`, one per stream
  class, naming every column that stream's batches must carry, no more
  and no less.  Ours: a malformed declaration is a bug in our wiring,
  so it is refused at construction (the codebase's fail-loudly-at-
  construction convention), never at ingest time.

* **The incoming batch** — :class:`ParquetBatch`, carrying the columns
  a Parquet reader finds in the file's footer, one ``(name, dtype)``
  leaf per column, beside the payload bytes a *conforming* batch brings
  into the store.  Theirs: an incoming batch is foreign data, so a
  malformed one (a repeated column name, an empty footer) is never a
  construction error — it is exactly the drift :meth:`DeclaredSchema.validate`
  exists to reject.

* **The rejection** — :class:`SchemaDrift`, raised by ``validate`` with
  the drift as structured data (missing, unexpected, retyped and
  duplicated columns), so the alert names precisely what changed rather
  than that something did.  Under the supervisor the raise *is* the
  halt: the stream boundary (feature 16) converts it into that stream's
  failure record while every other stream keeps ingesting — §15's
  "halt ingest *for that stream*; alert; patch", inherited rather than
  re-implemented.

What counts as drift, stated once so the gate's stance is unambiguous:

* a **missing** column — declared, absent from the batch;
* an **unexpected** column — present, undeclared; an exchange *adding*
  a field is a schema change too, and §15's answer to it is halt and
  patch, not silently ignore;
* a **retyped** column — same name, different dtype, compared
  *verbatim*; the declared schema is the canonical spelling, and a
  differently-spelled type is drift in the safe direction (halt and
  patch) rather than a silent match;
* a **duplicated** column — the batch names one column twice; the
  columnar formats address columns by name, so a name appearing twice
  cannot match any declared schema.

What deliberately does *not* count: **order**.  Parquet is name-addressed
and every reader (DuckDB included) projects by name, so a batch whose
columns arrive reordered but otherwise agree with the declaration has
not drifted, and rejecting it would cry wolf at the operator.

:class:`SchemaValidatingWorker` composes the gate into the worker shape
feature 16 fixed: each cycle fetches the next batch past the store's
watermark, gates it, and commits it only if it conforms — a
:class:`~nullius_ingest.staging.StagingArea` is a batch store, so what
passes lands in ``staging/<stream>/<seq>.bin`` and what drifts never
touches the append-only log.  The gate sits *before* the write, so a
rejected batch does not advance the watermark either: once the schema
is patched, the re-fetched batch claims the very sequence the drifted
one would have — the log keeps no hole and no drift.

The member stays stdlib-only: comparing two column sets needs no Parquet
reader.  The batch's columns arrive as data — exactly what a footer
exposes — and the stream workers of features 17–24 feed this gate from
their own readers, declaring this member's dependencies when they land.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from .streams import StreamClass, coerce_stream_class
from .watermark import Batch, SequenceStoreBase
from .worker import CycleResult

__all__ = [
    "ColumnSpec",
    "DeclaredSchema",
    "ParquetBatch",
    "SchemaDrift",
    "SchemaValidatingWorker",
]


@dataclass(frozen=True)
class ColumnSpec:
    """One column of a schema or an incoming batch, by name and dtype.

    ``name`` is the Parquet field name; ``dtype`` is its type token —
    the physical or logical type a reader reports for the leaf, spelled
    exactly as the declaring schema spells it (dtypes are compared
    verbatim by :meth:`DeclaredSchema.validate`, because a mismatch the
    gate quietly forgave is a schema change the system quietly ingested).
    """

    name: str
    dtype: str


def _coerce_columns(columns: object) -> tuple[ColumnSpec, ...]:
    # Normalise every accepted spelling of "a list of columns" — ColumnSpec
    # instances, (name, dtype) pairs, or a mapping in declaration order —
    # into the one tuple shape both schema kinds reason over.  Narrowed by
    # capability, not by declared type: a mapping maps names to dtypes, a
    # sequence yields columns, and anything else is refused by name.
    entries: Iterable[ColumnSpec | tuple[str, str]]
    if isinstance(columns, Mapping):
        entries = list(columns.items())
    elif isinstance(columns, Iterable):
        entries = columns
    else:
        raise TypeError(
            f"columns must be a mapping of name to dtype or an iterable "
            f"of ColumnSpec or (name, dtype) pairs, got "
            f"{type(columns).__name__}"
        )
    coerced: list[ColumnSpec] = []
    for entry in entries:
        if isinstance(entry, ColumnSpec):
            coerced.append(entry)
        elif isinstance(entry, tuple) and len(entry) == 2:
            name, dtype = entry
            coerced.append(ColumnSpec(name=name, dtype=dtype))
        else:
            raise TypeError(
                f"a column is a ColumnSpec or a (name, dtype) pair, "
                f"got {entry!r}"
            )
    return tuple(coerced)


@dataclass(frozen=True)
class ParquetBatch:
    """One incoming Parquet batch: the columns its footer claims, plus rows.

    ``columns`` is what a Parquet reader reads off the file's footer —
    one :class:`ColumnSpec` per leaf, normalised from specs, pairs or a
    mapping (accepted at construction; stored as the tuple) and
    preserved in footer order.  It may be empty or repeat a name: an
    incoming batch is foreign data, and malformations are for
    :meth:`DeclaredSchema.validate` to reject as drift, never for the
    constructor to forbid — the split between *our* wiring bugs (fail at
    construction) and *their* drift (reject at the gate) is the module's
    whole error posture.

    ``payload`` is the batch's bytes and ``rows`` its row count — what a
    conforming batch carries into the batch store once it passes the
    gate.  Neither carries a sequence: a batch's position in the stream
    log is assigned by ingest, not by the exchange.
    """

    columns: tuple[ColumnSpec, ...]
    payload: bytes = b""
    rows: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", _coerce_columns(self.columns))

    @property
    def column_names(self) -> tuple[str, ...]:
        """The batch's column names, in footer order."""
        return tuple(column.name for column in self.columns)


@dataclass(frozen=True)
class DeclaredSchema:
    """The columns one stream's Parquet batches must carry — no more, no less.

    A stream worker declares its schema once, up front, and every batch
    the stream ingests is gated on it.  The schema names its stream so a
    drift rejection (and a wiring mistake) points at the stream whose
    ingest is halted, and it is frozen because a declaration that could
    drift mid-run would leave the gate arguing with itself.  ``columns``
    accepts :class:`ColumnSpec` instances, ``(name, dtype)`` pairs or a
    mapping (see :meth:`from_mapping`) and is stored as the declaration
    tuple, in the order given.

    The declaration is *ours*, so it must be well-formed before anything
    is gated on it: no columns, a repeated column, or a blank name or
    dtype is refused with :class:`ValueError` at construction — a bug in
    our wiring, failed now, not an ingest-time surprise three layers
    deeper.
    """

    stream: StreamClass
    columns: tuple[ColumnSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", coerce_stream_class(self.stream))
        columns = _coerce_columns(self.columns)
        if not columns:
            raise ValueError(
                "a declared schema needs at least one column; an empty "
                "declaration would reject every batch as drift while "
                "asserting the stream had agreed to send nothing"
            )
        for column in columns:
            if not isinstance(column.name, str) or not column.name:
                raise ValueError(
                    f"declared schema for {self.stream} has a column with "
                    f"no name: {column!r}"
                )
            if not isinstance(column.dtype, str) or not column.dtype:
                raise ValueError(
                    f"declared column {column.name!r} for {self.stream} "
                    f"has no dtype; declare one, even if it is opaque"
                )
        names = [column.name for column in columns]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(
                f"declared schema for {self.stream} repeats column(s) "
                f"{', '.join(repr(name) for name in repeated)}; a stream "
                f"declares each column exactly once"
            )
        object.__setattr__(self, "columns", columns)

    @classmethod
    def from_mapping(
        cls, stream: "StreamClass | str", dtypes: Mapping[str, str]
    ) -> "DeclaredSchema":
        """Declare a schema from a ``{column: dtype}`` mapping, in order.

        The mapping's insertion order is the declaration order — the
        order ``columns`` preserves — which keeps a schema written as a
        literal reading in the same order as the stream table it came
        from.
        """
        return cls(
            coerce_stream_class(stream),
            tuple(ColumnSpec(name, dtype) for name, dtype in dtypes.items()),
        )

    @property
    def column_names(self) -> tuple[str, ...]:
        """The declared column names, in declaration order."""
        return tuple(column.name for column in self.columns)

    def validate(self, batch: ParquetBatch) -> None:
        """Gate ``batch``: return when its columns are the declared ones.

        The batch's column set must equal the declaration's — every
        declared column present with its declared dtype, nothing extra,
        nothing named twice.  Order is *not* compared: Parquet columns
        are addressed by name, so a reordered batch has not drifted.

        Any difference raises :class:`SchemaDrift` naming the stream and
        exactly what changed; a conforming batch returns ``None`` and
        proceeds to the store.
        """
        declared = {column.name: column.dtype for column in self.columns}
        batch_dtypes: dict[str, str] = {}
        duplicated: list[str] = []
        for column in batch.columns:
            if column.name in batch_dtypes and column.name not in duplicated:
                duplicated.append(column.name)
            batch_dtypes[column.name] = column.dtype
        missing = tuple(name for name in declared if name not in batch_dtypes)
        unexpected = tuple(name for name in batch_dtypes if name not in declared)
        retyped = tuple(
            (name, declared[name], batch_dtypes[name])
            for name in declared
            if name in batch_dtypes and batch_dtypes[name] != declared[name]
        )
        if missing or unexpected or retyped or duplicated:
            raise SchemaDrift(
                self.stream,
                missing=missing,
                unexpected=unexpected,
                retyped=retyped,
                duplicated=tuple(duplicated),
            )


class SchemaDrift(Exception):
    """An incoming batch's columns drifted from the declared schema.

    Raised by :meth:`DeclaredSchema.validate` — never constructed
    elsewhere — and carrying the drift as structured data so an alert
    can name exactly what changed, not merely that something did:

    * :attr:`missing` — declared columns the batch does not carry;
    * :attr:`unexpected` — columns the batch carries but nothing declared;
    * :attr:`retyped` — ``(name, declared_dtype, batch_dtype)`` for each
      column present under a different dtype;
    * :attr:`duplicated` — column names the batch repeats.

    Under the supervisor this exception *is* §15's response: the stream
    boundary converts it into that stream's failure record — the alert —
    and ingest halts for that stream alone while every other stream
    keeps running.  The recovery is the row's third word, *patch*: fix
    the declaration (or the feed), and the re-fetched batch claims the
    sequence the drifted one never took.
    """

    stream: StreamClass
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    retyped: tuple[tuple[str, str, str], ...]
    duplicated: tuple[str, ...]

    def __init__(
        self,
        stream: "StreamClass | str",
        *,
        missing: Iterable[str] = (),
        unexpected: Iterable[str] = (),
        retyped: Iterable[tuple[str, str, str]] = (),
        duplicated: Iterable[str] = (),
    ) -> None:
        self.stream = coerce_stream_class(stream)
        self.missing = tuple(missing)
        self.unexpected = tuple(unexpected)
        self.retyped = tuple(retyped)
        self.duplicated = tuple(duplicated)
        super().__init__(self._render())

    def _render(self) -> str:
        # One line an operator reads in a failure record and knows what to
        # patch: the stream, then every drift category that fired, each
        # with the names (and, for retypes, the two dtypes) involved.
        parts: list[str] = []
        if self.missing:
            names = ", ".join(repr(name) for name in self.missing)
            parts.append(f"missing column(s) {names}")
        if self.unexpected:
            names = ", ".join(repr(name) for name in self.unexpected)
            parts.append(f"unexpected column(s) {names}")
        if self.retyped:
            retypes = ", ".join(
                f"{name!r} (declared {declared!r}, batch {actual!r})"
                for name, declared, actual in self.retyped
            )
            parts.append(f"retyped column(s) {retypes}")
        if self.duplicated:
            names = ", ".join(repr(name) for name in self.duplicated)
            parts.append(f"duplicated column(s) {names}")
        return (
            f"{self.stream} batch drifted from the declared schema: "
            + "; ".join(parts)
        )


@dataclass(frozen=True)
class SchemaValidatingWorker:
    """A worker that gates its stream's batches on its declared schema.

    Composed exactly like
    :class:`~nullius_ingest.worker.ResumableFunctionWorker` — stream
    class, batch store, and a factory that, given the sequence to resume
    from, returns the next :class:`ParquetBatch` (``None`` for an empty
    fetch) — with the gate inserted between fetch and commit:

    * a conforming batch is committed under the next sequence past the
      store's watermark, as the resumable worker commits it;
    * a drifted batch raises :class:`SchemaDrift` *before any write*: its
      bytes never reach the append-only log and the watermark does not
      advance, so after the declaration is patched the re-fetched batch
      claims the very sequence the drifted one would have — the log
      carries no hole and no drift.

    A :class:`~nullius_ingest.staging.StagingArea` is a batch store (a
    :class:`~nullius_ingest.watermark.SequenceStoreBase`), so the same
    worker gates for staging: what passes lands in
    ``staging/<stream>/<seq>.bin``; what drifts is rejected at the gate.

    Raising is the halt.  The worker needs no error handling of its own
    to keep the system up: the supervisor's boundary (feature 16)
    converts the raise into this stream's failure record — the alert —
    while every other stream keeps ingesting.
    """

    stream_class: StreamClass
    schema: DeclaredSchema
    store: SequenceStoreBase
    build_batch: "Callable[[int], ParquetBatch | None]"

    def __post_init__(self) -> None:
        # Validate at construction, exactly as the other function workers
        # do: a mis-wired gate must fail here, not inside a cycle.
        object.__setattr__(
            self, "stream_class", coerce_stream_class(self.stream_class)
        )
        if not isinstance(self.schema, DeclaredSchema):
            raise TypeError(
                f"validating worker for {self.stream_class} needs a "
                f"DeclaredSchema, got {type(self.schema).__name__}"
            )
        if self.schema.stream != self.stream_class:
            raise TypeError(
                f"the declared schema for {self.schema.stream} cannot gate "
                f"{self.stream_class}; a schema belongs to exactly one "
                f"stream, and gating on another stream's declaration would "
                f"reject honest batches for drift they do not have"
            )
        if not isinstance(self.store, SequenceStoreBase):
            raise TypeError(
                f"validating worker for {self.stream_class} needs a batch "
                f"store (a SequenceStore or StagingArea), got "
                f"{type(self.store).__name__}"
            )
        if not callable(self.build_batch):
            raise TypeError(
                f"validating worker for {self.stream_class} needs a "
                f"callable batch factory, got "
                f"{type(self.build_batch).__name__}"
            )

    @property
    def sequence_store(self) -> SequenceStoreBase:
        """The batch store conforming batches are committed into."""
        return self.store

    def run_cycle(self) -> CycleResult:
        """Fetch the next batch past the watermark, gate it, commit if it passes.

        The gate is the first thing a fetched batch meets and the last
        thing before the store: ``validate`` either returns — and the
        batch is committed atomically under ``sequence``, one past the
        watermark — or raises :class:`SchemaDrift`, and nothing is
        written and nothing advances.  An empty fetch (``None``) commits
        nothing and reports ``sequence=0``, the same honest no-progress
        cycle the resumable worker reports.
        """
        stream = self.stream_class
        sequence = self.store.current(stream) + 1
        produced = self.build_batch(sequence)
        if produced is None:
            return CycleResult(sequence=0)
        if not isinstance(produced, ParquetBatch):
            raise TypeError(
                f"build_batch for {stream} returned "
                f"{type(produced).__name__}; the contract is a ParquetBatch "
                f"or None"
            )
        self.schema.validate(produced)
        self.store.commit(
            stream,
            Batch(sequence=sequence, payload=produced.payload, rows=produced.rows),
        )
        return CycleResult(rows_written=produced.rows, sequence=sequence)
