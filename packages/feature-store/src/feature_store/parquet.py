"""Feature 49's format: a feature's stamped rows as Parquet bytes.

app_spec.xml, "Point-in-Time Feature Store", feature 49: *System materializes
a feature to Parquet lazily on first request, persisting the result for later
reuse.*  docs/nullius-tech-architecture.md §4.4 states the same contract in
six words — "Materialized as Parquet, lazily on first request, then cached" —
and §4.1's storage table fixes the encoding: "Parquet + Zstd, columnar,
compressed, portable".

Three words in that sentence each own a module, and this is the first:

* **Parquet** — the columnar file format a feature's bytes are written in.
  This module.  :func:`encode_parquet` and :func:`decode_parquet` are the
  codec, plus the :func:`to_table`/:func:`from_table` pair that bridges
  feature 51's :class:`~feature_store.rows.FeatureRow` to Arrow.
* **lazily on first request** — when a materialisation happens at all, and
  the fact that it happens once.  :mod:`feature_store.materialise`.
* **then cached** — the persisted result being found and reused rather than
  recomputed.  :mod:`feature_store.materialise` again (feature 50 measures
  the reuse with its ``cache_hit`` counter).

**Why Parquet and not the JSON envelope feature 51 already writes.**  The
row layer's :func:`~feature_store.rows.encode_rows` envelope is the *store*
representation — opaque bytes under a key, small, and read whole.  Parquet is
the *analysis* representation §4.1 pins: columnar, Zstd-compressed, and
readable in place by DuckDB without a server (§4.1's "DuckDB querying Parquet
in place", the analytics row of the stack table).  A feature store whose
payload could only be read by its own decoder would make every downstream
query go through this package; a feature store whose rows are Parquet lets
the analysis path read them directly.  Both representations exist because they
answer different questions, and neither replaces the other: the key still
addresses the record, and the Parquet file is what the record's payload *is*
once materialised.

**The stamp is a real column, typed, not a string.**  Feature 51's stamp
travels as ISO-8601 text inside the JSON envelope, which is right for a payload
a process reads whole.  In Parquet it becomes a ``timestamp[us, tz=UTC]``
column, because that is what makes a point-in-time query *pushable down*: a
DuckDB scan of the file can filter ``computed_as_of <= t`` in the column
reader, without decoding every row.  Storing the stamp as text would force
every query to parse it as a string, which is exactly the leakage-shaped cost
§4.4 exists to avoid — and the stamp is the one column every point-in-time
question reads.

The timestamp is pinned to microseconds, UTC, matching both Parquet's own
logical type and :func:`feature_store.rows.utc_now`'s second-resolution
default, so a stamp round-trips exactly rather than through a lossy
nanosecond-to-microsecond narrowing that pyarrow would otherwise pick for us.
The timezone is carried in the column type, so a naive instant cannot be read
back out of a file this module wrote — feature 52's ``<=`` comparison needs an
aware stamp, and a file whose stamp column lost its offset would put the
``TypeError`` back at read time, far from the write that could have named it.

**The stamp column's type is pinned by this module, not inferred.**  A Parquet
writer infers a column's type from the values it is given, and for the stamp
that inference has one failure mode that matters, silently: **an empty batch
infers the stamp column as ``null``.**  A feature computed over an empty window
has no rows, so an unpinned writer would produce a file whose
``computed_as_of`` column is a null type — and this module's own
:func:`from_table` refuses exactly that, because a stamp column without an
offset is one feature 52 cannot compare.  So the pin is load-bearing, not
defensive: without it, materialising an empty feature would write a file that
nothing — including the reader sitting next to it — could read back.  Pinning
microsecond-resolution UTC also fixes the exactness of the round trip, since
pyarrow would otherwise be free to choose the unit.

**Value columns are inferred, once, over the whole column.**  Inference is
sound there and only there: run over a column's full set of values, the widest
value decides the type, so ``1`` and ``2.5`` in one column settle on ``double``
and ``{"x": 1}`` and ``{"y": 2}`` settle on a two-field struct rather than
either one alone — with all values present, inference cannot see a type that
the column's own data contradicts.

The one case where it cannot help is a column whose values are *all* ``None``
or the batch is empty: there is genuinely no type information to infer, and
such a column is written as Arrow's ``null`` type.  That is stated rather than
worked around, because the alternative would be guessing — a row layer knows a
column's name and its values, and knows nothing about its declared type
(feature 51 deliberately keeps values untyped).  The consequence is bounded:
``None`` in round-trips as ``None`` out, so the *rows* are preserved exactly;
what a downstream DuckDB scan sees is a column it cannot type, which is the
truth about a column that never held a value.  A feature that must pin a
column's type across an empty snapshot registers a schema in the definition,
not in the payload.

**A value Parquet cannot carry is refused here, at the encode.**  The row
layer already refuses what JSON cannot represent (``bytes``, a set); Arrow is
a *wider* type system than JSON but not a superset of what JSON accepts, so a
value can pass feature 51 and still fail here — a heterogeneous column, an
integer past ``int64``, a mapping whose keys are not strings.  pyarrow reports
each of these as its own ``ArrowException`` from deep inside a conversion, and
this module re-raises it as :class:`ParquetMaterialisationError` naming the
column, so a caller catches one type and reads which column was the problem.
The alternative — letting Arrow's error escape — would make "the feature store
could not materialise this feature" and "pyarrow had a bad day" the same
exception to a caller who can act on only the first.

**Bytes in, bytes out.**  The codec is deliberately file-free: it takes and
returns ``bytes``, and where those bytes land is the materialisation module's
decision (it mounts them under the lake, at the path the key's own
:meth:`~feature_store.keys.FeatureKey.to_path` spells).  Keeping the codec
pure is what lets the format contract be tested without a lake, and lets the
one caller that does touch disk own all the I/O in one place.

**Determinism.**  §4.4's cache is keyed by the feature's five components, and
the replay path compares payloads, so the same rows must always encode to
byte-identical Parquet.  Parquet's own writer is deterministic for a fixed
table, schema and compression; what this module must hold up its end of is
*row order* (a series is not a set — feature 51's ordering discipline,
preserved rather than sorted away) and the schema, since either drifting would
change the bytes for identical data.

**pyarrow is imported lazily, on the same seam :mod:`contract._arrow` uses.**
The member is imported by the factory's workspace scan, so anything imported
at module scope is imported during composition; a hard ``import pyarrow`` here
would make pyarrow a precondition for *composing the application*, a much
larger blast radius than the feature needs — the keying contract, the row
layer and the point-in-time read all need no Arrow at all.  Deferring the
import keeps the package import-safe in the environments the workspace
contract promises one will be (factory scan, test sandbox, deterministic
replay), while the materialisation paths that genuinely need Arrow raise a
named error the moment they are reached without it.
"""

from __future__ import annotations

import datetime as dt
import io
from collections.abc import Iterable, Mapping
from typing import Any

from .rows import COMPUTED_AS_OF_FIELD, FeatureRow, FeatureRowError

__all__ = [
    "PARQUET_COMPRESSION",
    "ParquetMaterialisationError",
    "decode_parquet",
    "encode_parquet",
    "from_table",
    "require_arrow",
    "to_table",
]


#: The compression §4.1's stack table names ("Parquet + Zstd, columnar,
#: compressed, portable").  Zstd rather than snappy: the ratio matters for a
#: lake sized in terabytes, and Zstd is the codec the architecture pins.
PARQUET_COMPRESSION = "zstd"


class ParquetMaterialisationError(ValueError):
    """A feature's rows could not be written to, or read back from, Parquet.

    Subclasses :class:`ValueError` because every cause is a caller bug or a
    corrupt stored file, never a runtime condition to retry: rows whose values
    Arrow cannot type, or bytes that are not a Parquet file this module wrote.
    A *missing* dependency is deliberately **not** raised as this type — it is
    :class:`ModuleNotFoundError` from :func:`require_arrow`, because an
    environment problem is not a malformed feature.
    """


def require_arrow():
    """Import and return the ``pyarrow`` module, or raise a named error.

    The one place in this package that reaches for Arrow (see the module
    docstring for why the import is deferred).  Imported lazily on every call
    rather than cached in a module global: the cost after the first import is
    a ``sys.modules`` lookup, and a cache would be a lie in the one environment
    where it matters — a test that installs, removes or monkeypatches pyarrow
    mid-process.

    The root module is what is returned, not the ``pyarrow.parquet`` submodule:
    the codec needs both halves — ``pyarrow`` for the type system
    (``field``/``schema``/``array``/``Table``) and ``pyarrow.parquet`` for the
    file format (``write_table``/``read_table``) — and the submodule does not
    re-export its parent, so returning the submodule alone would leave every
    caller reaching back through ``sys.modules`` for the types.  Importing the
    submodule here is what registers ``pyarrow.parquet`` on the parent, so
    ``arrow.parquet`` is available to callers of this function.

    A missing pyarrow raises :class:`ModuleNotFoundError` naming the fix,
    following the same shape as :func:`contract._arrow.require_arrow` — the
    seam lives in the member that declares the dependency.
    """
    try:
        import pyarrow
        import pyarrow.parquet  # noqa: F401 - registers the ``.parquet`` submodule
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "Parquet materialisation requires pyarrow, which is a declared "
            "dependency of the nullius-feature-store member but is not "
            "installed in this environment; run `uv sync` (or `pip install "
            "pyarrow`) in the workspace root"
        ) from exc
    return pyarrow


def _stamp_field(arrow) -> Any:
    """The Arrow field type of the ``computed_as_of`` column.

    Pinned to microsecond-resolution, UTC-aware timestamps — see the module
    docstring for why both halves of that are load-bearing.
    """
    return arrow.field(
        COMPUTED_AS_OF_FIELD, arrow.timestamp("us", tz="UTC")
    )


def _derive_schema(arrow, column_names: Iterable[str], rows: list[FeatureRow]):
    """The Arrow schema for a batch: the stamp pinned, the values inferred.

    Inference runs over a column's *full* set of values rather than row by row,
    so the widest value in the column decides its type: ``1`` and ``2.5``
    settle on ``double``, and ``{"x": 1}`` and ``{"y": 2}`` settle on a struct
    carrying both fields rather than either one alone.  Inference is sound
    precisely because it sees the whole column; a row-by-row type would have to
    commit to the first value it met and then refuse the rest.

    The stamp is pinned rather than inferred because inferring it is *wrong* for
    an empty batch — pyarrow infers a ``null`` column, which
    :func:`from_table` refuses, so an unpinned empty feature would materialise
    to a file nothing could read back.  See the module docstring; the value
    columns cannot be pinned the same way, because the row layer carries no
    declared types for them.

    **A batch's column set is the union across its rows, and the schema is
    rectangular.**  That is a property of the format, not a choice this
    function could make differently: a Parquet column has one type for every
    row in the file, so a row that omits a column and a row that carries
    ``null`` for it become the same fact once written.  The union (rather than
    the intersection, or the first row's keys) is what keeps the file from
    silently dropping a column some row did carry.  See :func:`to_table` for
    what that means for reading back the rows that went in.

    The stamp column comes first, so a reader scanning the file meets the
    point-in-time column before the values it gates (features 51/52).
    """
    fields = [_stamp_field(arrow)]
    for name in column_names:
        values = [row.values.get(name) for row in rows]
        # ``arrow.array`` infers from the whole list and refuses a
        # heterogeneous one (``True`` beside ``1``, a mapping whose keys are
        # not strings, an integer past int64) rather than guessing.  Named by
        # column here, because Arrow's own message reports the types and not
        # which feature column they came from.
        try:
            inferred = arrow.array(values, type=None).type
        except Exception as exc:  # noqa: BLE001 - Arrow raises several shapes here
            raise ParquetMaterialisationError(
                f"column {name!r} cannot be typed as a Parquet column: {exc}. "
                "A Parquet column has one type for every row, so a column "
                "mixing incompatible values — a bool beside a number, an "
                "integer past int64, a mapping whose keys are not strings — "
                "has no Parquet representation. Split it into two columns, or "
                "coerce the values to one type before materialising"
            ) from exc
        fields.append(arrow.field(name, inferred))
    return arrow.schema(fields)


def _column_names(rows: list[FeatureRow]) -> tuple[str, ...]:
    """Every column name any row in the batch carries, sorted.

    The union rather than the intersection: a row that omits a column is a row
    with no value *for that column* (feature 51's "absent is a normal miss"),
    not a row proposing a different column set — an intersection would drop a
    column that only some rows carry, which is data loss.  Sorted, so the
    schema — and therefore the file's bytes — does not depend on row order, the
    same determinism discipline :meth:`FeatureRow.column_names` follows.
    """
    return tuple(sorted({name for row in rows for name in row.values}))


def to_table(rows: Iterable[FeatureRow]):
    """Build the Arrow table feature 49's Parquet file carries.

    The row-to-columnar bridge: feature 51's stamped rows in (a series, order
    preserved), an Arrow table out.  The schema is derived by
    :func:`_derive_schema` and the table is built *through* it, so a column
    this batch left entirely empty keeps the type its own values would have
    had rather than collapsing to ``null``, and a batch of zero rows keeps the
    column set instead of losing it (see the module docstring for both).

    **The round-trip law, stated exactly.**  A *rectangular* batch — every row
    carrying the same column set, and every nested mapping the same keys —
    round-trips exactly: ``decode_parquet(encode_parquet(rows)) == rows``.  A
    *ragged* batch does not, and cannot: Parquet is rectangular by definition,
    so an omitted column (or an omitted struct field) is written as a null in a
    column that exists, and reads back as a null rather than as an absence.
    The rule is one rule at every level — **absence becomes null** — and it is
    a normalization rather than a loss, because feature 51 already treats the
    two as the same fact at the seam (``value()`` returns ``None`` for a column
    a row does not carry, exactly as it does for one it carries as ``None``).
    A caller that needs the distinction keeps it in the row layer, where
    :meth:`FeatureRow.column_names` can still tell the two apart; a caller
    materialising to Parquet is asking for the rectangular form.

    (The law is exact equality of the decoded rows, so it is stated in the
    terms :class:`~feature_store.rows.FeatureRow` already compares by.  A
    ``NaN`` value compares unequal to itself before any encoding happens, so a
    batch carrying one is not a counterexample to the law — it is a value whose
    equality is reflexive-false in Python, and Parquet preserves it bit for
    bit, which is what matters: feature 51's "``nan`` is representable and
    legal" survives the round-trip as the same ``nan``.)

    Every element must be a :class:`~feature_store.rows.FeatureRow`; a batch
    is a value handed to this function within one import graph, so the instance
    check is honest and buys the by-construction guarantee that each stamp is
    aware UTC — which is what lets the pinned timestamp column be sound.
    """
    arrow = require_arrow()
    batch = list(rows)
    for index, row in enumerate(batch):
        if not isinstance(row, FeatureRow):
            raise ParquetMaterialisationError(
                f"row {index} of a Parquet materialisation must be a "
                f"FeatureRow; got {type(row).__name__}. Materialisation "
                "writes stamped rows — stamp the batch first "
                "(feature_store.stamp_rows)"
            )
    schema = _derive_schema(arrow, _column_names(batch), batch)
    columns: dict[str, list[Any]] = {
        COMPUTED_AS_OF_FIELD: [row.computed_as_of for row in batch]
    }
    for name in schema.names[1:]:
        columns[name] = [row.values.get(name) for row in batch]
    try:
        return arrow.Table.from_pydict(columns, schema=schema)
    except Exception as exc:  # noqa: BLE001 - Arrow raises several shapes here
        raise ParquetMaterialisationError(
            f"the rows cannot be typed as Arrow columns ({exc}). A Parquet "
            "column has one type for every row, so a column mixing "
            "incompatible values — a bool beside a number, an integer past "
            "int64, a mapping whose keys are not strings — has no Parquet "
            f"representation"
        ) from exc


def from_table(table) -> tuple[FeatureRow, ...]:
    """Rebuild feature 51's stamped rows from an Arrow table.

    The inverse of :func:`to_table`, and the half that has to be *strict*:
    a table this module writes always carries a UTC-aware stamp column, so a
    table that does not is not a feature's Parquet — and rebuilding rows from
    it would hand feature 52 rows whose stamps it cannot compare.  So the
    stamp column is required, and its type is checked before any row is built,
    rather than left to fail later inside a ``<=``.

    Every row revalidates through :meth:`FeatureRow.__post_init__`, which is
    where a stamp that somehow lost its offset is refused by name.  Row order
    is the order the table recorded.
    """
    arrow = require_arrow()
    schema = table.schema
    if COMPUTED_AS_OF_FIELD not in schema.names:
        raise ParquetMaterialisationError(
            f"a materialised feature's Parquet must carry a "
            f"{COMPUTED_AS_OF_FIELD!r} column; this file's columns are "
            f"{schema.names}. Every feature row is stamped at write time "
            "(feature 51), so a stamp-less file is not a feature's rows"
        )
    stamp_index = schema.names.index(COMPUTED_AS_OF_FIELD)
    stamp_type = schema.field(stamp_index).type
    if not (arrow.types.is_timestamp(stamp_type) and stamp_type.tz):
        raise ParquetMaterialisationError(
            f"a materialised feature's {COMPUTED_AS_OF_FIELD!r} must be a "
            f"timezone-aware timestamp column; this file's is {stamp_type}. "
            "A stamp without an offset cannot be compared with '<=' at read "
            "time (feature 52), so it is refused here rather than detonating "
            "inside a point-in-time query"
        )
    value_names = [name for name in schema.names if name != COMPUTED_AS_OF_FIELD]
    value_columns = {
        name: table.column(name).to_pylist() for name in value_names
    }
    stamps = table.column(COMPUTED_AS_OF_FIELD).to_pylist()
    rows: list[FeatureRow] = []
    for index, stamp in enumerate(stamps):
        # A null stamp is a row that was never stamped, which feature 51
        # refuses — and _validated_instant would report it as a non-datetime,
        # naming the type rather than the state.  Named here instead.
        if stamp is None:
            raise ParquetMaterialisationError(
                f"row {index} of a materialised feature carries a null "
                f"{COMPUTED_AS_OF_FIELD}; every row is stamped at write time "
                "(feature 51)"
            )
        values = {name: value_columns[name][index] for name in value_names}
        try:
            rows.append(FeatureRow(computed_as_of=stamp, values=values))
        except FeatureRowError as exc:
            raise ParquetMaterialisationError(
                f"row {index} of a materialised feature is not a valid "
                f"feature row: {exc}"
            ) from exc
    return tuple(rows)


def encode_parquet(rows: Iterable[FeatureRow]) -> bytes:
    """Encode stamped rows as one Zstd-compressed Parquet file in memory.

    The whole of feature 49's format at its seam: feature 51's rows in,
    Parquet bytes out.  The bytes are what a :class:`~feature_store.store.FeatureRecord`
    carries as its payload once materialised, and what a DuckDB scan reads in
    place (§4.1) — the store's opaque-``bytes`` seam and the columnar analysis
    format are the same bytes, which is the point of materialising at all.

    Deterministic: the same rows in the same order encode to byte-identical
    output, so the replay path's payload comparison holds and a re-materialised
    feature is indistinguishable from the one already cached.
    """
    parquet = require_arrow().parquet
    table = to_table(rows)
    buffer = io.BytesIO()
    try:
        parquet.write_table(table, buffer, compression=PARQUET_COMPRESSION)
    except Exception as exc:  # noqa: BLE001 - Arrow raises several shapes here
        raise ParquetMaterialisationError(
            f"the rows cannot be written as Parquet: {exc}"
        ) from exc
    return buffer.getvalue()


def decode_parquet(payload: bytes) -> tuple[FeatureRow, ...]:
    """Rebuild the stamped rows :func:`encode_parquet` wrote.

    The read half of the codec: Parquet bytes in, feature 51's rows out.  Bytes
    that are not a Parquet file — truncated, foreign, empty — are refused as
    :class:`ParquetMaterialisationError` rather than escaping as pyarrow's own
    ``ArrowException``, so a caller catching "the materialised feature could
    not be read" catches one type.  Empty bytes are included in that refusal
    on purpose: feature 48 blesses an empty payload as "a feature with no
    rows", but those bytes were never a Parquet file, and the row layer's
    representation of no rows is an empty *batch* (which encodes to a real,
    zero-row Parquet file) — the same distinction
    :mod:`feature_store.point_in_time` draws for the JSON envelope.
    """
    arrow = require_arrow()
    try:
        table = arrow.parquet.read_table(arrow.BufferReader(payload))
    except Exception as exc:  # noqa: BLE001 - Arrow raises several shapes here
        raise ParquetMaterialisationError(
            f"not a Parquet feature payload ({type(exc).__name__}: {exc}); "
            "materialised features are Zstd-compressed Parquet files written "
            "by feature_store.encode_parquet"
        ) from exc
    return from_table(table)
