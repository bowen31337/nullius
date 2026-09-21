"""The information-coefficient and turnover series — §9.2's two Parquet files.

app_spec.xml, "Tree & Artifact Persistence", feature 171: *System
persists ic_series and turnover_series as Parquet files inside the node
artifact directory.*  docs/nullius-tech-architecture.md §9.2 draws the
two lines that sentence names, side by side in the node's one
directory:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet         ← the edge per date
      turnover_series.parquet   ← the book per date
      decay_profile.json
      regime_attribution.json
      exec_trace.json
      code.py

**One shape, two metrics.**  Every other §9.2 line has a shape of its
own: ``signal_returns.parquet`` is a *grid* (symbol × period, feature
170), the two JSON documents are a positional array and a per-stratum
split (feature 172), and the execution pair is text and a fingerprint
(feature 173).  These two are the same thing twice: **a date-keyed
scalar series** — one number per rebalance date, the information
coefficient the signal earned on that date and the fraction of the
equal-weight book that had to be traded to hold it.  That is what makes
them one module rather than two, and it is why they carry one schema
and are written, read and checked by one codec: the *metric* is the
filename's to say, the *shape* is the columns'.

**The columns are ``date`` and ``value``, and the date column is a
real date.**  A Parquet file is read in place by DuckDB without a
server (§4.1's analytics row, the reason feature 49 materialises to
this format at all), so the column types are what a scan filters and
aggregates on.  A ``date32`` column makes "the IC on or after the
rebalance” a pushable predicate rather than a string comparison, and
makes the read side answer :class:`datetime.date` keys directly — the
parse step JSON would have re-introduced is exactly what the columnar
format exists to remove (the argument feature 49 makes for typing its
stamp column rather than carrying ISO text).  The value column is
``float64``: the series is a *stored measurement*, so it keeps the
double the evaluator computed rather than narrowing to a float32 on the
way to disk.  §9.3's ``float32`` is the opposite decision for the
opposite reason — that one is the *resident replay array*, where 500
nodes × 2000 periods must fit in 4 MB, and a value read once per replay
is not a value read once per node.

**Both columns are pinned, and here that is a statement rather than a
defence.**  Feature 49 has to pin its stamp column because an empty
batch infers a ``null`` type, which its own reader then refuses; this
layer refuses an empty series outright (see below), so no such batch
can reach the writer.  The pin buys the two files one declared schema —
a reader needs no inference to know what it is holding — and it is what
makes the bytes deterministic by construction rather than by Arrow's
inference happening to agree with itself.

**A series with no dates is refused.**  ``ic_series`` is the
information coefficient *at each rebalance*, so a series of zero
entries measured nothing; ``turnover_series`` is one entry per
rebalance *with a predecessor*, so a series of zero entries likewise
means no book was ever turned over.  Neither is a state the evaluator
can hand this layer: its metrics refuse an empty ``ic_series`` by name,
and a panel with too few priced dates to compute a per-date spread is
refused a step earlier still (``ic_tstat`` and ``ir_standalone`` both
divide by a standard deviation they will not take to be zero).  So an
empty series is not a sparse measurement to persist honestly — it is a
document no writer of this step produced, and refusals here name that
rather than staging a zero-row file a reader would have to interpret.
This is feature 172's stance on an empty profile, for the same reason.

**Keys: a calendar date, spelled either way the renderers spell it.**
The evaluator's two renderers answer their series in two different key
types — its metrics carry ``Mapping[dt.date, float]`` and its turnover
renderer answers ``dict[str, float]`` keyed by ``date.isoformat()``,
because that is the spelling each record happens to hold — and both
land *here*, in the one layer that writes the artifact.  So this module
accepts either: a :class:`datetime.date`, or the ISO-8601 date text
:meth:`datetime.date.isoformat` produces.  What it refuses is every
other key, and a :class:`datetime.datetime` is the case worth naming —
it *is* a :class:`~datetime.date` in Python, so it would pass a naive
``isinstance`` check and then key a series by an instant that no other
date in the series can be compared with.  The evaluator's own records
refuse a datetime key for the same reason, and the refusal is repeated
here because this is the boundary a caller the evaluator never saw can
reach.

**The bytes are canonical, so a stored series is a fingerprint.**
Entries are sorted by date before they are written, so two equal series
built in different insertion orders stage *identical bytes* — the same
discipline the canonical-JSON writers of this member state, restated
for a row-oriented format.  A caller that hands this layer a mapping
built by walking a dict therefore cannot make the file's bytes depend
on the walk's order, and a replay comparing a stored series against the
one it is reconstructing compares content and never key order.  Sort
order is also the only order a series has: a series is a function from
date to value, and the file states it in the one order every reader
would have to impose anyway.

**Non-finite values are refused, and this is not pedantry.**  ``nan``
and ``±inf`` are what a correlation produces when a cross-section is
constant, and a stored coefficient that is not a number is a
measurement a reader would trust and be wrong by.  The evaluator
refuses a non-finite coefficient at construction and its JSON reader
refuses one on the way back in; this layer refuses one on the way to
disk, so a series that could not be read back is never written down.
The refusal names the *date* it was found on, which is the only
information that makes it findable in a series of two thousand entries.

**Both ride feature 169's write path; neither is a second one.**
:func:`persist_ic_series` and :func:`persist_turnover_series` stage
their file through :meth:`~artifacts.ArtifactStore.write` and the node's
:meth:`~artifacts.ArtifactStore.commit` publishes everything staged for
the node as one directory.  There is no second commit point and no
sidecar: a failure before the commit publishes nothing, a
:meth:`~artifacts.ArtifactStore.discard` rolls both back with every
other staged file, and a refresh replaces them wholesale — so a
re-persisted node never carries the retry's IC series beside the first
attempt's turnover.  Every refusal lands *before the first staged
byte*, because the payload is rendered in memory and validated there:
a refused series leaves the staged set exactly as it was.

**The read side answers the shape this writer emits, and refuses what
it cannot.**  :func:`ic_series` and :func:`turnover_series` answer
``{date: value}`` by the node's same two keys and through the store's
read surface — the one §1 grants the replay engine, and nothing else.
The two shapes are identical by design, so nothing but the filename
distinguishes them: a reader that asked for the wrong one would get the
other's numbers without complaint, and the only defence is that a
caller comes for the name it wants.  That is stated rather than
engineered around, because the alternative — a discriminator column, a
metric tag in a file whose name already carries it — would be a second
spelling of the filename.  Bytes that are not Parquet, a file whose
columns are not this layer's, a null or non-finite entry, and a
duplicate date all refuse with
:class:`~artifacts._errors.ArtifactStoreError` rather than answering a
stand-in.  A duplicate date is worth naming: a series is one value per
date, and a file carrying two would silently collapse to the last one
read, which is a number the writer never wrote.

**pyarrow is imported lazily, on the seam the rest of the workspace
uses.**  The member is imported by the factory's workspace scan, so
anything imported at module scope is imported during composition; a
hard ``import pyarrow`` here would make pyarrow a precondition for
*composing the application*, a much larger blast radius than these two
files need — feature 169's keying, write path and read side need no
Arrow at all, and neither does the JSON half of this category.  So
:func:`require_arrow` defers the import to first use, exactly as
:func:`contract._arrow.require_arrow` and
:func:`feature_store.parquet.require_arrow` do, and names the missing
dependency when it is reached without one.  The parquet *dependency* is
declared in this member's ``pyproject.toml`` all the same: the seam
lives in the member that declares it.
"""

from __future__ import annotations

import datetime as dt
import io
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._errors import ArtifactStoreError
from ._keys import (
    validate_campaign_id,
    validate_node_id,
)
from ._store import ArtifactStore

__all__ = [
    "DATE_COLUMN",
    "IC_SERIES_FILENAME",
    "PARQUET_COMPRESSION",
    "TURNOVER_SERIES_FILENAME",
    "VALUE_COLUMN",
    "decode_series",
    "encode_series",
    "ic_series",
    "ic_series_is_persisted",
    "persist_ic_series",
    "persist_turnover_series",
    "require_arrow",
    "turnover_series",
    "turnover_series_is_persisted",
]

#: The §9.2 name of the information-coefficient series — the node's edge
#: per rebalance date.  Spelled once here so the write path, the read side
#: and the tests this feature owns cannot drift apart on what the file is
#: called.
IC_SERIES_FILENAME = "ic_series.parquet"

#: The §9.2 name of the turnover series — the equal-weight book's
#: fractional turnover per rebalance date.  The same single spelling, for
#: the same reason.
TURNOVER_SERIES_FILENAME = "turnover_series.parquet"

#: The date column's name, shared by both files — the series' axis.
#: ``date`` rather than a metric-flavoured name because the two files have
#: the same shape and the filename already says which metric it holds: one
#: ``date``/``value`` schema means one codec, one reader and one set of
#: refusals for both, and a DuckDB scan of either file spells the same two
#: columns.
DATE_COLUMN = "date"

#: The value column's name, shared by both files — the series' ordinate.
#: The same reasoning as :data:`DATE_COLUMN`: the shape is one shape, and
#: the name of the metric is the name of the file.
VALUE_COLUMN = "value"

#: The compression §4.1's stack table names ("Parquet + Zstd, columnar,
#: compressed, portable"), and the codec feature 49's materialiser already
#: writes with.  Zstd rather than snappy: the ratio matters for a store
#: §9.2 sizes in gigabytes, and it is what the architecture pins.
PARQUET_COMPRESSION = "zstd"


def require_arrow():
    """Import and return the ``pyarrow`` module, or raise a named error.

    The one place in :mod:`artifacts._series` that reaches for Arrow — see
    the module docstring for why the import is deferred rather than taken
    at module scope.  Imported lazily on every call rather than cached in a
    module global: the cost after the first import is a ``sys.modules``
    lookup, and a cache would be a lie in the one environment where it
    matters — a test that installs, removes or monkeypatches pyarrow
    mid-process.

    The root module is what is returned, not the ``pyarrow.parquet``
    submodule: the codec needs both halves — ``pyarrow`` for the type system
    (``field``/``schema``/``Table``) and ``pyarrow.parquet`` for the file
    format (``write_table``/``read_table``) — and the submodule does not
    re-export its parent, so returning the submodule alone would leave every
    caller reaching back through ``sys.modules`` for the types.  Importing
    the submodule here is what registers ``pyarrow.parquet`` on the parent,
    so ``arrow.parquet`` is available to callers of this function.

    A missing pyarrow raises :class:`ModuleNotFoundError` naming the fix,
    following the same shape as :func:`contract._arrow.require_arrow` and
    :func:`feature_store.parquet.require_arrow` — the seam lives in the
    member that declares the dependency.
    """
    try:
        import pyarrow
        import pyarrow.parquet
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "the §9.2 series files require pyarrow, which is a declared "
            "dependency of the artifacts member but is not installed in this "
            "environment; run `uv sync` (or `pip install pyarrow`) in the "
            "workspace root"
        ) from exc
    return pyarrow


def _series_schema(arrow) -> Any:
    """The Arrow schema both series files are written and read through.

    ``date32`` and ``float64``, pinned rather than inferred — see the module
    docstring for what the pin buys and for why the value column is a
    double rather than a float32.  One function rather than two constants so
    the writer and the reader cannot disagree: the read side checks the
    file's columns against *this* schema, so a writer that grew a column
    would be refused by the reader sitting beside it.
    """
    return arrow.schema(
        [
            arrow.field(DATE_COLUMN, arrow.date32()),
            arrow.field(VALUE_COLUMN, arrow.float64()),
        ]
    )


# -- The write half: one operation per metric -------------------------------------


def persist_ic_series(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    series: Any,
) -> Path:
    """Stage the node's information-coefficient series as ``ic_series.parquet``.

    The feature's first file, staged through feature 169's write path: the
    Parquet bytes join whatever else the writer has staged for the node,
    invisible to every read until the node's
    :meth:`~artifacts.ArtifactStore.commit` publishes the staged set — at
    which point it sits inside the node's one directory, keyed by the same
    two ids every reader joins on.  Returns the staged path for a caller
    that wants to name what it staged; the commit, not this call, is the
    publication.

    ``series`` is the date-keyed coefficient map — the evaluator's metrics
    carry exactly this as ``Mapping[dt.date, float]``, and a mapping keyed
    by ISO date text is accepted for the reason the module docstring gives.
    Every refusal — a malformed key, a series with no dates, a key that is
    not a calendar date, a value that is not a finite number — lands before
    the first staged byte, so a refused series leaves the staged set
    exactly as it was.  Staging the file again re-stages the one name,
    keeping the last bytes, exactly as re-staging any filename does; a
    commit then publishes the latest series, never a splice of two runs.
    """
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    payload = encode_series(
        series,
        filename=IC_SERIES_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )
    return store.write(campaign_id, node_id, IC_SERIES_FILENAME, payload)


def persist_turnover_series(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    series: Any,
) -> Path:
    """Stage the node's turnover series as ``turnover_series.parquet``.

    The feature's second file, and the same discipline as the first: staged
    through feature 169's write path, published by the node's one commit,
    invisible until then.  Returns the staged path.

    ``series`` is the per-rebalance fractional turnover — the evaluator's
    turnover renderer answers exactly this as ``dict[str, float]`` keyed by
    ``date.isoformat()``, one entry per rebalance with a predecessor, so an
    empty one means the book never turned over and is refused (see the
    module docstring).  The same shape, the same codec and the same
    refusals as :func:`persist_ic_series`: the two files differ in which
    numbers they hold, not in what a series is.
    """
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    payload = encode_series(
        series,
        filename=TURNOVER_SERIES_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )
    return store.write(campaign_id, node_id, TURNOVER_SERIES_FILENAME, payload)


# -- The read half: the series, answered by the same keys --------------------------


def ic_series(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> dict[dt.date, float]:
    """The node's information-coefficient series, read back by date.

    The read side of the feature's first file: the bytes persisted as
    ``ic_series.parquet``, decoded and answered as ``{date: coefficient}``
    in ascending date order — the per-date series the evaluator's metrics
    reduce to ``ic_mean`` and ``ic_tstat``, and the one the promotion path
    and replay read to ask *on which dates did this edge exist?* without
    reaching the evaluator (§1).

    Refuses with :class:`~artifacts._errors.ArtifactNotFoundError` when the
    node holds no directory or its directory holds no
    ``ic_series.parquet``, the refusal naming which half is missing — so a
    node that never persisted stays distinguishable from one persisted
    without its series.  Bytes this layer's writer cannot have produced —
    not Parquet, the wrong columns, a null or non-finite entry, a duplicate
    date — refuse with :class:`~artifacts._errors.ArtifactStoreError`
    rather than answering a stand-in.

    This answers whatever date-keyed series the file holds, and the
    turnover file has the same shape: a caller that wants the turnover asks
    :func:`turnover_series`, and the two are told apart by the name that
    was read, not by what comes back.
    """
    raw = store.read(campaign_id, node_id, IC_SERIES_FILENAME)
    return decode_series(
        raw,
        filename=IC_SERIES_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )


def turnover_series(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> dict[dt.date, float]:
    """The node's turnover series, read back by date.

    The read side of the feature's second file, and the same codec as the
    first: the bytes persisted as ``turnover_series.parquet``, decoded and
    answered as ``{date: fractional turnover}`` in ascending date order —
    the per-rebalance series the evaluator's metrics reduce to the single
    ``turnover`` scalar, kept in full because §9.2 files the series and not
    the mean.  Refuses with
    :class:`~artifacts._errors.ArtifactNotFoundError` when the node holds no
    directory or its directory holds no ``turnover_series.parquet``, naming
    the missing half; bytes this layer's writer cannot have produced refuse
    with :class:`~artifacts._errors.ArtifactStoreError`.
    """
    raw = store.read(campaign_id, node_id, TURNOVER_SERIES_FILENAME)
    return decode_series(
        raw,
        filename=TURNOVER_SERIES_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )


def ic_series_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries its IC series.

    The feature's first file as a fact: the node's directory is published
    *and* holds ``ic_series.parquet``.  ``False`` for a node nothing was
    published for — staged-but-uncommitted is invisible by design, the
    discipline feature 169 states — and ``False`` for a directory published
    without the series, which is the state a reconciliation sweep exists to
    find.  Presence, not validity: a file this writer did not render is
    still a file at the name, and a sweep that wants its *content* checked
    asks :func:`ic_series` and gets the refusal that names what is wrong.
    """
    return _is_persisted(
        store, campaign_id, node_id, IC_SERIES_FILENAME
    )


def turnover_series_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries its turnover series.

    The second file's invariant, answered the same way and kept *separate*
    from the first's: the two are written by two calls and each is
    independently readable — a node whose IC series landed and whose
    turnover file did not is a fact a sweep may legitimately meet, and
    asking one question here must not silently answer for the other.  The
    pair is not a contract the way feature 173's source-and-trace is: the
    feature's sentence says *and*, and neither file is unreadable without
    the other.
    """
    return _is_persisted(
        store, campaign_id, node_id, TURNOVER_SERIES_FILENAME
    )


# -- The codec, shared by both metric files ---------------------------------------


def encode_series(
    series: Any, *, filename: str, campaign_id: str, node_id: str
) -> bytes:
    """Render a date-keyed series to one Zstd-compressed Parquet file.

    The whole of this feature's format at its seam: a mapping of calendar
    dates (or ISO date text) to numbers in, Parquet bytes out — the bytes
    :func:`persist_ic_series` and :func:`persist_turnover_series` stage, and
    the bytes a DuckDB scan reads in place (§4.1) or a replay reads through
    :func:`decode_series`.  Both metric files go through this one function
    because they are one shape; ``filename`` is what the refusals name, so
    a caller told its series is malformed knows *which* of the node's files
    it was rendering.

    Every entry is validated before a byte is produced: the key must be a
    calendar date (a :class:`datetime.datetime` is refused by name, since
    it would pass a naive check and then key the series by an instant), the
    value a finite number (``nan`` and ``±inf`` are refused, naming the
    date they sit on), and the series must carry at least one entry (see
    the module docstring for why an empty one is not a sparse measurement
    but a document no writer of this step produced).  Every refusal names
    the file, the node *and* the campaign, so a message is actionable on
    its own: a node has more than one series, and "a series is malformed"
    without the address is not enough to find which node's.

    Deterministic: entries are sorted by date before they are written, so
    two equal series stage byte-identical output regardless of the order
    their mapping was built in — which is what lets replay compare a stored
    series against the one it is reconstructing.
    """
    entries = _validated_series(
        series, filename=filename, campaign_id=campaign_id, node_id=node_id
    )
    arrow = require_arrow()
    table = arrow.Table.from_pydict(
        {
            DATE_COLUMN: [day for day, _ in entries],
            VALUE_COLUMN: [value for _, value in entries],
        },
        schema=_series_schema(arrow),
    )
    buffer = io.BytesIO()
    try:
        arrow.parquet.write_table(
            table, buffer, compression=PARQUET_COMPRESSION
        )
    except Exception as exc:
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} could not be written as Parquet: {exc}; the "
            "series is one node's per-date measurements, and bytes a reader "
            "cannot parse back are not a series that can be stored"
        ) from exc
    return buffer.getvalue()


def decode_series(
    payload: bytes, *, filename: str, campaign_id: str, node_id: str
) -> dict[dt.date, float]:
    """Rebuild the date-keyed series :func:`encode_series` wrote.

    The read half of the codec: Parquet bytes in, ``{date: value}`` out in
    ascending date order.  Strict about what it will answer, because the
    alternative is handing a caller a measurement no writer of this layer
    produced: bytes that are not a Parquet file at all, a file whose
    columns are not ``date32``/``float64``, a null entry, a non-finite
    entry, and a date appearing twice each refuse by name.  The duplicate
    date is the one worth spelling out — a series is one value per date, so
    a file carrying two would collapse to whichever row a dict was built
    last from, which is a number nobody wrote.

    The date column arrives as :class:`datetime.date` keys rather than the
    ISO text the file's shape would allow, because that is what the
    ``date32`` column *is* (see the module docstring): the typed column and
    the typed answer are one decision, and a reader that had to parse text
    would be paying for a column type it did not use.
    """
    arrow = require_arrow()
    try:
        table = arrow.parquet.read_table(arrow.BufferReader(payload))
    except Exception as exc:
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} is not a Parquet series "
            f"({type(exc).__name__}: {exc}); the file is the Zstd-compressed "
            "Parquet feature 171's write path stages, and bytes no writer of "
            "this member emitted are a file it never staged"
        ) from exc
    _check_columns(table, arrow, filename, campaign_id, node_id)
    dates = table.column(DATE_COLUMN).to_pylist()
    values = table.column(VALUE_COLUMN).to_pylist()
    series: dict[dt.date, float] = {}
    for position, (day, value) in enumerate(zip(dates, values)):
        if day is None:
            raise ArtifactStoreError(
                f"row {position} of the {filename!r} of node {node_id!r} of "
                f"campaign {campaign_id!r} carries a null date; a series is "
                "keyed by the rebalance date each measurement belongs to, and "
                "a measurement belonging to no date belongs to no node"
            )
        if value is None:
            raise ArtifactStoreError(
                f"the {filename!r} of node {node_id!r} of campaign "
                f"{campaign_id!r} carries a null value on "
                f"{day.isoformat()}; a series entry is a measurement, and a "
                "missing one is an absent row rather than a row holding null "
                "— the writer of this member emits neither"
            )
        if not math.isfinite(value):
            raise ArtifactStoreError(
                f"the {filename!r} of node {node_id!r} of campaign "
                f"{campaign_id!r} carries the non-finite value {value!r} on "
                f"{day.isoformat()}; nan and inf are what a correlation "
                "produces over a constant cross-section, not a measurement, "
                "and the writer of this member refuses them"
            )
        if day in series:
            raise ArtifactStoreError(
                f"the {filename!r} of node {node_id!r} of campaign "
                f"{campaign_id!r} carries {day.isoformat()} twice; a series "
                "is one value per date, and a file with two would answer with "
                "whichever row was read last — a number this member's writer "
                "never wrote"
            )
        series[day] = float(value)
    return dict(sorted(series.items()))


# -- The series' validation, spelled once for every seam above --------------------


def _validated_series(
    series: Any, *, filename: str, campaign_id: str, node_id: str
) -> list[tuple[dt.date, float]]:
    """Return ``series`` as a sorted list of ``(date, value)``, or refuse it.

    One validator for both metric files, because they are one shape: a
    mapping of calendar dates to finite numbers.  Text and sequences are
    refused by name rather than coerced — ``json.dumps`` would happily
    render a string, and a series handed in as a list of numbers has no
    dates at all, so a caller that made either mistake needs to be told
    which one it made rather than handed a file keyed by nothing.

    The refusals name the *date* a bad value sits on, which is the only
    handle that finds it in a series of a few thousand entries, and they
    name the file and the node, because a node has more than one series and
    "a series is malformed" is not actionable on its own.

    Two keys that name one date — :func:`_validated_date` accepts a
    :class:`datetime.date` and its ISO text as the same key — are refused
    here rather than at the encode.  A mapping holding both is two keys to
    Python and one row to Parquet, so accepting it would encode a file
    carrying that date twice, which this layer's own reader refuses: the
    writer would have produced bytes it cannot read back.  Accepting either
    spelling means colliding across the two is this layer's to catch.

    Sorted by date on the way out, which is what makes the encoded bytes
    independent of the caller's mapping order.
    """
    if isinstance(series, (str, bytes, bytearray)):
        raise ArtifactStoreError(
            f"a series is a mapping of dates to measurements — got "
            f"{type(series).__name__} {series!r} for the {filename!r} of "
            f"node {node_id!r} of campaign {campaign_id!r}; a series is "
            "keyed by the rebalance date each measurement belongs to, and "
            "the text of one is not the mapping"
        )
    if not isinstance(series, Mapping):
        raise ArtifactStoreError(
            f"a series is a mapping of dates to measurements — got "
            f"{type(series).__name__} {series!r} for the {filename!r} of "
            f"node {node_id!r} of campaign {campaign_id!r}; the IC and "
            "turnover series are keyed by rebalance date, and a value that "
            "is not a mapping carries no dates to key by"
        )
    entries: list[tuple[dt.date, float]] = []
    seen: dict[dt.date, Any] = {}
    for key, value in series.items():
        day = _validated_date(
            key, filename=filename, campaign_id=campaign_id, node_id=node_id
        )
        # Two spellings of one date are two keys to a mapping but one row to
        # a Parquet file, so ``{date(2026, 1, 5): 0.1, "2026-01-05": 0.2}``
        # would encode a file carrying that date twice — and this layer's own
        # reader refuses a duplicate date, so the writer would produce bytes
        # it cannot read back.  Refused here instead, naming both spellings:
        # accepting either key type means colliding across the two is this
        # layer's job to catch, not the caller's to avoid.
        if day in seen:
            raise ArtifactStoreError(
                f"the {filename!r} of node {node_id!r} of campaign "
                f"{campaign_id!r} carries {day.isoformat()} twice — under the "
                f"key {seen[day]!r} and again under {key!r}; this layer "
                "accepts a calendar date and its ISO text as the same key, so "
                "a mapping spelling one date both ways would encode a row per "
                "spelling, and a series is one value per date"
            )
        seen[day] = key
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ArtifactStoreError(
                f"a series' measurements are numbers — got {value!r} "
                f"({type(value).__name__}) on {day.isoformat()} of the "
                f"{filename!r} of node {node_id!r} of campaign "
                f"{campaign_id!r}; an information coefficient and a "
                "fractional turnover are both numbers, and a value that is "
                "not one is not a measurement of the node"
            )
        number = float(value)
        if not math.isfinite(number):
            raise ArtifactStoreError(
                f"a series' measurements are finite — got {number!r} on "
                f"{day.isoformat()} of the {filename!r} of node {node_id!r} "
                f"of campaign {campaign_id!r}; nan and inf are what a "
                "correlation produces over a constant cross-section, not a "
                "measurement, and a coefficient a reader must be able to "
                "compare is one a reader must be able to parse"
            )
        entries.append((day, number))
    if not entries:
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} cannot be an empty series; the file holds one "
            "measurement per rebalance date, so a series with no dates "
            "measured nothing at all — the evaluator's own record cannot "
            "produce one (its metrics refuse an empty IC series, and a "
            "panel too short to carry a per-date spread is refused a step "
            "before that), which makes an empty series a document this "
            "step's writer never produced"
        )
    return sorted(entries)


def _validated_date(
    key: Any, *, filename: str, campaign_id: str, node_id: str
) -> dt.date:
    """Return ``key`` as the calendar date it must be, or refuse it.

    The series' axis is a *rebalance date*, so the key is a
    :class:`datetime.date` or the ISO-8601 date text
    :meth:`datetime.date.isoformat` produces — the two spellings the
    evaluator's renderers answer, for the reason the module docstring
    gives.  A :class:`datetime.datetime` is refused **before** the
    :class:`~datetime.date` check, because it is a subclass and would
    otherwise pass: a series keyed by instants is a series no reader can
    compare against a series keyed by dates, and the mistake would show up
    far from here.  Every other key — an int, a ``None``, a timestamp
    string, a non-date string — is refused by name.
    """
    if isinstance(key, dt.datetime):
        raise ArtifactStoreError(
            f"a series is keyed by calendar dates — got the datetime "
            f"{key!r} in the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r}; a datetime is a date in Python and would "
            "pass a naive check, but a series keyed by instants cannot be "
            "compared against one keyed by dates, and the rebalance grid "
            "the measurements were taken on is made of dates"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise ArtifactStoreError(
                f"a series is keyed by calendar dates — got the text "
                f"{key!r} in the {filename!r} of node {node_id!r} of "
                f"campaign {campaign_id!r}, which is not an ISO-8601 date "
                "(YYYY-MM-DD); the text spelling a renderer answers is "
                "date.isoformat(), and anything else is a key no reader can "
                "join back to a rebalance"
            ) from exc
    raise ArtifactStoreError(
        f"a series is keyed by calendar dates — got {key!r} "
        f"({type(key).__name__}) in the {filename!r} of node {node_id!r} "
        f"of campaign {campaign_id!r}; the axis is the rebalance date each "
        "measurement was taken on, and a key that is not a date is a "
        "measurement belonging to no rebalance"
    )


def _check_columns(
    table: Any, arrow: Any, filename: str, campaign_id: str, node_id: str
) -> None:
    """Refuse a table that is not the series schema this layer writes.

    Both columns are required and both types are checked, rather than left
    to fail at the ``to_pylist`` below: a ``date32`` column hands back
    :class:`datetime.date` values and a ``float64`` column hands back
    floats, so a file carrying the right *names* and the wrong *types*
    would decode into keys and values of the wrong shape and be answered as
    a series.  This is the check feature 49's ``from_table`` makes on its
    stamp column, restated for both of this layer's.
    """
    names = list(table.schema.names)
    for column in (DATE_COLUMN, VALUE_COLUMN):
        if column not in names:
            raise ArtifactStoreError(
                f"the {filename!r} of node {node_id!r} of campaign "
                f"{campaign_id!r} carries no {column!r} column — it carries "
                f"{', '.join(names) or 'no columns'}; a series file is the "
                f"{DATE_COLUMN!r}/{VALUE_COLUMN!r} pair this member's writer "
                "emits, and a file without both is one it never staged"
            )
    date_type = table.schema.field(DATE_COLUMN).type
    if not arrow.types.is_date(date_type):
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} types its {DATE_COLUMN!r} column as "
            f"{date_type}; a series is keyed by calendar dates, and a column "
            "that is not a date is one no rebalance can be joined to"
        )
    value_type = table.schema.field(VALUE_COLUMN).type
    if not arrow.types.is_floating(value_type):
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} types its {VALUE_COLUMN!r} column as "
            f"{value_type}; a series' measurements are floating-point "
            "numbers, and a column of another type is not the series this "
            "member's writer emits"
        )


def _is_persisted(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    filename: str,
) -> bool:
    """Whether a published node's directory holds ``filename``.

    Presence, shared by both invariant checks so the two answer the
    identical question about different names: the node's artifact is
    published *and* the file is in it.  Staged-but-uncommitted answers
    ``False``, which is the write path's invisibility rather than a missing
    file.
    """
    if not store.has_node(campaign_id, node_id):
        return False
    return filename in store.files(campaign_id, node_id)
