"""The post-cost signal returns — §9.2's grid, feature 170.

app_spec.xml, "Tree & Artifact Persistence", feature 170: *System persists
signal_returns as Parquet per symbol and period after costs, which is what
lets replay recompute marginal contribution.*
docs/nullius-tech-architecture.md §9.2 draws the line that sentence names,
first in the node's one directory:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet
      turnover_series.parquet
      decay_profile.json
      regime_attribution.json
      exec_trace.json
      code.py

**This is the key artifact, and §9.2 says why in one line.**  *"Because it
is stored in full, marginal contribution against any book can be recomputed
at replay time, so the same node scores differently depending on the path a
policy took to reach it, while replay stays fully deterministic."*  Every
other file in the directory is something replay can *read a scalar or a
curve* out of; this one is the node's returns **kept whole**, at the finest
grain the evaluator computed them — one row per ``(rebalance date, horizon,
symbol)``.  The distinction is load-bearing rather than stylistic: a file
carrying one averaged number per node satisfies a careless reading of
"persists signal_returns", and it makes ``ir_marginal`` (feature 83),
§9.3's resident campaign arrays and feature 174's dense ``nodes × periods``
load all impossible.  So nothing is reduced on the way in, and the reader
answers the rows back.

**Three numbers per row, and the third is not redundancy.**  ``charge`` is
what the fee schedule deducted, ``post_cost_return`` is what was left, and
``gross_return`` is what the signal predicted before the schedule touched it.
The gross is carried for the reason the evaluator's own store states when it
stores the same three numbers: a series storing only the net cannot answer
the first question anyone asks of a cost-adjusted number — *how much did the
schedule eat?* — without re-running a schedule whose assumption may have
moved, and §6.2's shared library and feature 60's hash exist to make
re-running it *unnecessary* rather than merely possible.  With all three on
the row the artifact answers what the signal predicted, what the schedule
took and what was left from one read, and "the schedule was applied to these
returns" is a fact about stored data rather than a claim about a code path.
Keeping the third column also keeps the file *checkable against itself*: the
read side recomputes the gross from the file's own charge plus its own net, so
a row edited outside this package fails instead of loading as a
plausible-looking lie — the defence :func:`evaluator.row_to_return` applies to
the store's rows, restated for the row-oriented file.  The check is made in
that direction and not the other on purpose: the gross is the *derived* value
(it is ``charge + post_cost_return`` and nothing else), so adding is exact
about which number is a consequence of the other two, and because
floating-point addition is not reversible — ``(x + y) - y != x`` for many
doubles — checking ``gross - charge == net`` would refuse rows this layer's own
writer produced from values like ``0.001`` and ``0.01``.  The direction of the
identity is therefore part of the contract, not an implementation detail.

Two of the three numbers are therefore *inputs* and the third is derived, and
the split runs through the whole module: :class:`ReturnRow` takes the charge
and the net (the two the evaluator's own series record treats as primary,
recovering the gross by adding them) and computes the gross, so the writer
cannot be handed a row whose gross disagrees with its own terms and stage bytes
its own reader would refuse.  The file still holds all three, because that is
what §9.2's artifact *is* — three columns a DuckDB scan can subtract without
trusting anyone.

**One file, every horizon.**  A row is one ``(date, horizon, symbol)``, and
the five horizons sit side by side in the one file — which is what the
``horizon`` column buys.  Feature 171's two series are one shape twice and so
carry no metric column at all (the *filename* says which metric the file
holds); here the filename says nothing about the horizon, so the horizon has
to be a column, and once it is, one file holds the whole priced panel.  That
is also what makes the grid honest about its own edges: a horizon's series is
shorter than the rebalance grid it was scored on — the last ``h`` dates have
no ``h``-period future — so the file carries *what was priced*, and a reader
that wants to know what was *scored* asks the node's ``ic_series`` (feature
171), which is measured over the shortest covered horizon and so spans a
strict subset of the same grid.

**The columns are typed, because a Parquet file is read in place.**  §4.1's
analytics row reads these files through DuckDB without a server, which is one
of the reasons feature 49 materialises to this format at all, so the column
types are what a scan filters and aggregates on.  A ``date32`` column makes
"the returns on or after the rebalance" a pushable predicate rather than a
string comparison, and makes the read side answer :class:`datetime.date` keys
directly — the parse step JSON would have re-introduced is exactly what the
columnar format exists to remove (the argument feature 171's series make for
typing their date column rather than carrying ISO text).  ``horizon`` is
``int32``: the spec's horizons are 1, 2, 5, 10 and 20 periods, a signed
32-bit integer holds any period count anyone will rebalance at, and the
narrower column is what the format is for.  ``symbol`` is Arrow ``string``:
the cross-sections the spec sizes (100 symbols) are small enough that
dictionary encoding buys little, while a dictionary column is one more thing
a scan has to decode, and no other typed column in this category is
dictionary-encoded.  The three measurements are ``float64`` — the series is a
*stored measurement*, so it keeps the double the evaluator computed rather
than narrowing to a float32 on the way to disk (§9.3's ``float32`` is the
opposite decision for the opposite reason: that one is the *resident replay
array*, where 500 nodes × 2000 periods must fit in 4 MB).

**The panel's identity rides in the schema's metadata, not on its rows.**
The node, the sealed snapshot and feature 59's ``(venue, version)`` cost model
pair are each one value per *file*: a node's directory holds one
``signal_returns.parquet``, and that file is one node's returns priced under
one schedule, so a column would repeat each of them on every row and give a
row the chance to disagree with its own file.  Arrow schema metadata costs one
entry each and travels with the schema the reader checks.  The cost model pair
is there because §15 treats a changed cost model as its own failure case — a
file that does not say which schedule priced it cannot tell a re-priced venue
from a changed evaluator — and the snapshot is there because a panel that
cannot say which sealed world it was measured in cannot be compared against
one that can.  The node is there so a grid decoded out of a directory can be
checked against the node it was read from rather than merely assumed to be
its.

**A symbol must be text, a horizon an integer, a date a date.**  Arrow would
happily store an instrument named by an ``int``, and it would be a symbol
nothing downstream could join back to, because the panel, the store and
feature 179's tree all name instruments with strings.  Same for the counts and
the dates: a horizon that is a ``bool`` (``True`` is ``1`` in Python), a date
that is really a :class:`datetime.datetime` — which *is* a
:class:`~datetime.date` and would pass a naive ``isinstance`` check before
keying a row by an instant no other row shares an axis with — and a number
that is ``nan`` or ``±inf`` (what a correlation produces over a constant
cross-section, and a measurement a reader would trust and be wrong by) all
refuse, on the write side *before the first staged byte* and on the read side
before a single row is answered.

**The rows are sorted, so a stored grid is a fingerprint.**  Rows are ordered
by ``(date, horizon, symbol)`` before they are written — the discipline
feature 171's series state for their one axis, restated for three: two equal
panels built in different insertion orders stage *identical bytes*, so a
replay comparing a stored grid against the one it is reconstructing compares
content and never iteration order.  Sort order is also the only order the file
needs, because the reader answers a panel and every consumer re-groups by
whichever axis it is measuring over.  This is the same canonical-bytes
discipline the canonical-JSON writers of this member state, restated for a
row-oriented format.

**One node's panel, keyed by that node's two ids.**  A :class:`SignalReturns`
names the node its rows belong to, and :func:`persist_signal_returns` refuses
a panel whose name disagrees with the directory it is being staged under — a
grid filed under a node it does not measure is a misfiling every later reader
would trust, replay recomputing marginal contribution above all.  The record
also refuses an empty panel and a panel carrying one cell twice: a grid
addresses one measurement per ``(date, horizon, symbol)``, and a file with two
rows in one cell would answer with whichever was read last — a number nobody
wrote, at the one grain feature 174 densifies by.  A panel never names a
campaign: the campaign is the directory's first key and the store validates it
on its own, and a second spelling of it on the record would be a value that
could disagree with the key the file sits under.

**Both ride feature 169's write path; neither is a second one.**
:func:`persist_signal_returns` stages its file through
:meth:`~artifacts.ArtifactStore.write` and the node's
:meth:`~artifacts.ArtifactStore.commit` publishes everything staged for the
node as one directory.  There is no second commit point and no sidecar: a
failure before the commit publishes nothing, a
:meth:`~artifacts.ArtifactStore.discard` rolls the grid back with every other
staged file, and a refresh replaces it wholesale — so a re-persisted node never
carries the retry's panel beside the first attempt's IC series.  Every refusal
lands before the first staged byte, because the payload is rendered in memory
and validated there.

**The read side answers the shape this writer emits, and refuses what it
cannot.**  :func:`signal_returns` answers a :class:`SignalReturns` by the
node's same two keys and through the store's read surface — the one §1 grants
the replay engine, and nothing else.  Bytes that are not Parquet, a file whose
columns or metadata are not this layer's, a null or non-finite entry, a
mistyped column, a cell written twice and a file naming a node other than the
one it was read from all refuse with
:class:`~artifacts._errors.ArtifactStoreError` rather than answering a
stand-in.  Nothing is reduced on the way out: every row and every horizon is
answered, because a caller that asks for a node's returns is asking for the
returns.

**pyarrow is imported lazily, on the seam the rest of this category uses.**
The member is imported by the factory's workspace scan, so anything imported
at module scope is imported during composition; a hard ``import pyarrow`` here
would make pyarrow a precondition for *composing the application*, a much
larger blast radius than this file needs — feature 169's keying, write path and
read side need no Arrow at all, and neither does the JSON half of this
category.  So :func:`require_arrow` defers the import to first use, exactly as
feature 171's series module does, and names the missing dependency when it is
reached without one.  The parquet *dependency* is declared in this member's
``pyproject.toml`` all the same: the seam lives in the member that declares it.
"""

from __future__ import annotations

import datetime as dt
import io
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._errors import ArtifactStoreError
from ._keys import (
    validate_campaign_id,
    validate_node_id,
)
from ._series import DATE_COLUMN, PARQUET_COMPRESSION
from ._store import ArtifactStore

__all__ = [
    "CHARGE_COLUMN",
    "DATE_COLUMN",
    "GROSS_COLUMN",
    "HORIZON_COLUMN",
    "NET_COLUMN",
    "PARQUET_COMPRESSION",
    "SIGNAL_RETURNS_FILENAME",
    "SYMBOL_COLUMN",
    "ReturnRow",
    "SignalReturns",
    "decode_signal_returns",
    "encode_signal_returns",
    "persist_signal_returns",
    "require_arrow",
    "signal_returns",
    "signal_returns_is_persisted",
]

#: The §9.2 name of the node's post-cost return grid — the artifact §9.2 calls
#: "the key artifact" and the one feature 174 loads into a dense
#: ``nodes × periods`` array.  Spelled once here so the write path, the read
#: side and the tests this feature owns cannot drift apart on what the file is
#: called.
SIGNAL_RETURNS_FILENAME = "signal_returns.parquet"

#: The grid's horizon column — a row's place on feature 75's target axis.  A
#: column here and not in feature 171's series files, because the *filename*
#: there says which metric the file holds while this file holds all five
#: horizons at once (see the module docstring).
HORIZON_COLUMN = "horizon"

#: The grid's instrument axis — the symbol each return belongs to.
SYMBOL_COLUMN = "symbol"

#: The pre-cost return, as the gate supplied it.  Stored, and not redundancy:
#: with it beside the deduction and the net the artifact answers what the
#: signal predicted, what the schedule took and what was left from one read,
#: and the read side can check a row against its own terms (see the module
#: docstring).
GROSS_COLUMN = "gross_return"

#: The deduction the cost schedule applied to a row — the half of "after
#: costs" that is not the net itself, and what lets the artifact answer *how
#: much did the schedule eat?* without re-running a fee assumption that may
#: have moved (§6.2's shared library, feature 60's hash).
CHARGE_COLUMN = "charge"

#: The post-cost return itself — ``gross − charge``, the number the feature's
#: "after costs" names and the one every downstream metric reduces over and
#: feature 174 densifies.
NET_COLUMN = "post_cost_return"

# Note on the two names above: ``DATE_COLUMN`` and ``PARQUET_COMPRESSION`` are
# feature 171's, imported from :mod:`artifacts._series` and re-exported here
# rather than spelled a second time.  There is no second date column name and no
# second codec: the series files and this grid key their rows by the one
# rebalance calendar and are written with the one Zstd setting §4.1's stack
# table names, so a caller of the grid asks this module for them and gets the
# values the series files are written with.

#: The Arrow schema-metadata key carrying the node a file's rows belong to.
#: Metadata rather than a column: one value per file, and the reason a grid
#: decoded out of a node's directory can be checked against the node it was
#: read from rather than merely assumed to be its.
NODE_METADATA_KEY = b"node_id"

#: The Arrow schema-metadata key carrying the sealed snapshot a file's rows
#: were measured in — the same one-value-per-file reasoning.
SNAPSHOT_METADATA_KEY = b"snapshot_name"

#: The Arrow schema-metadata key carrying feature 59's venue — which fee
#: schedule priced the panel.  One value per file because a node's directory
#: holds one returns artifact and that artifact is one panel priced under one
#: schedule, so a column would only give a row the chance to disagree with its
#: own file.
VENUE_METADATA_KEY = b"venue"

#: The Arrow schema-metadata key carrying feature 59's version — the other half
#: of the same schedule identity, for the same reason.
VERSION_METADATA_KEY = b"version"


def require_arrow():
    """Import and return the ``pyarrow`` module, or raise a named error.

    The one place in :mod:`artifacts._returns` that reaches for Arrow — see the
    module docstring for why the import is deferred rather than taken at module
    scope.  Imported lazily on every call rather than cached in a module global,
    the seam feature 171's series module states: the cost after the first import
    is a ``sys.modules`` lookup, and a cache would be a lie in the one
    environment where it matters — a test that installs, removes or monkeypatches
    pyarrow mid-process.

    The root module is what is returned, not the ``pyarrow.parquet`` submodule:
    the codec needs both halves — ``pyarrow`` for the type system
    (``field``/``schema``/``Table``) and ``pyarrow.parquet`` for the file format
    (``write_table``/``read_table``) — and the submodule does not re-export its
    parent, so returning the submodule alone would leave every caller reaching
    back through ``sys.modules`` for the types.  Importing the submodule here is
    what registers ``pyarrow.parquet`` on the parent.

    A missing pyarrow raises :class:`ModuleNotFoundError` naming the fix,
    following the same shape as :func:`artifacts._series.require_arrow`,
    :func:`contract._arrow.require_arrow` and
    :func:`feature_store.parquet.require_arrow` — the seam lives in the member
    that declares the dependency.
    """
    try:
        import pyarrow
        import pyarrow.parquet
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "the §9.2 signal-returns grid requires pyarrow, which is a declared "
            "dependency of the artifacts member but is not installed in this "
            "environment; run `uv sync` (or `pip install pyarrow`) in the "
            "workspace root"
        ) from exc
    return pyarrow


# -- The grid, as a value ----------------------------------------------------------


@dataclass(frozen=True)
class ReturnRow:
    """One cell of the grid — a symbol's return on one date at one horizon.

    The grain feature 170's "per symbol and period" names, and the finest one
    the evaluator computes: what the schedule deducted (``charge``) and what
    was left (``post_cost_return``), on the date and at the horizon they were
    measured.

    **Two numbers are carried and the third is derived, and that is the point.**
    §9.2's file holds ``gross_return``, ``charge`` and ``post_cost_return``, but
    only two of the three are independent — the gross *is* the charge plus the
    net — and this record takes the two the evaluator's own store treats as
    primary (:class:`~evaluator.PostCostSeries` keeps ``values`` and
    ``charges`` and recovers the gross by adding them), deriving
    :attr:`gross_return` rather than accepting it.  That is what makes the
    writer *unable* to stage a file its own reader refuses: the read side checks
    every stored gross against its own charge plus its own net — the identity
    :func:`evaluator.row_to_return` enforces on the store's rows, restated here
    for the row-oriented file — and a record that could be handed a gross
    disagreeing with its own terms would be a record that could produce bytes
    this layer cannot read back, which is the failure feature 171's writer
    refuses a colliding pair of date spellings to avoid.

    Deriving it also keeps the identity exactness out of a caller's hands.  The
    check is float equality, so a caller that typed three decimal literals —
    ``0.011``, ``0.001``, ``0.01`` — would fail an identity that is true in
    decimal and false in binary floating point; a caller that hands over the net
    and the deduction has no such trap, and the gross the file carries is the
    one this layer computed from them.

    The date is accepted as a :class:`datetime.date` or as the ISO-8601 text
    :meth:`datetime.date.isoformat` produces, and normalized to the date: the
    evaluator's records key their series by calendar dates while its *rows* are
    stored and read back as ISO text, and both spellings land here, in the one
    layer that renders the artifact.  A :class:`datetime.datetime` is refused
    by name (see :func:`_validated_date`).

    Validated at construction, so a row built by hand or by a producer that
    drifted fails loudly here rather than being staged into a file: the horizon
    is a positive period count, the symbol non-empty text, and both numbers
    finite.
    """

    #: The rebalance date the return was taken on.
    rebalance_date: dt.date
    #: The horizon the return measures, in periods — feature 75's axis.
    horizon: int
    #: The instrument the return belongs to — non-empty text.
    symbol: str
    #: The deduction the cost schedule applied — the "after costs" half that is
    #: not the net itself.
    charge: float
    #: ``gross − charge``, as applied.
    post_cost_return: float

    def __post_init__(self) -> None:
        # object.__setattr__ for the date: frozen dataclass, and this is a
        # normalization of an argument the constructor accepted (ISO text is
        # one of the two spellings a caller may hand in).
        day = _validated_date(self.rebalance_date)
        horizon = _validated_horizon(self.horizon)
        symbol = _validated_symbol(self.symbol)
        where = (
            f"the signal return for {symbol!r} on {day.isoformat()} at "
            f"horizon {horizon}"
        )
        object.__setattr__(self, "rebalance_date", day)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self, "charge", _validated_number(self.charge, "charge", where=where)
        )
        object.__setattr__(
            self,
            "post_cost_return",
            _validated_number(
                self.post_cost_return, "post-cost return", where=where
            ),
        )

    @property
    def gross_return(self) -> float:
        """The pre-cost return — :attr:`charge` plus :attr:`post_cost_return`.

        The third of §9.2's three numbers, computed rather than carried (see the
        class docstring for why), and the value the file's ``gross_return``
        column holds.  A caller that had the gross and the charge in hand can
        check this against its own — and if it disagrees, the row it built is
        not the row it meant to build, which is a fact worth meeting here rather
        than in a file a replay would read.
        """
        return self.charge + self.post_cost_return

    @property
    def cell(self) -> tuple[dt.date, int, str]:
        """The address of this row in the grid — ``(date, horizon, symbol)``.

        The grid's key, spelled once so the writer's duplicate check and any
        caller grouping the panel walk the same triple in the same order.
        """
        return (self.rebalance_date, self.horizon, self.symbol)


@dataclass(frozen=True)
class SignalReturns:
    """One node's priced panel — the rows §9.2's key artifact is made of.

    The node whose signal was charged, the sealed world the returns were
    measured in, the cost model that priced them, and one :class:`ReturnRow`
    per ``(rebalance date, horizon, symbol)`` the evaluation priced.  This is
    the value :func:`persist_signal_returns` writes down and
    :func:`signal_returns` answers back, so a caller that produced a panel and
    a caller that read one out of a node's directory hold the same shape rather
    than two parallel spellings of it.

    Validated at construction: a panel with no rows is refused (a grid with no
    measurements priced nothing at all — the evaluator's own store refuses the
    same value before it writes a single row), and a panel carrying one cell
    twice is refused too, because a grid addresses one measurement per
    ``(date, horizon, symbol)`` and a file with two rows in one cell would
    answer with whichever was read last.  Both refusals exist here rather than
    only on the read side for the reason feature 171's writer states about its
    own two spellings colliding: this layer's *reader* refuses a duplicate
    cell, so accepting one would mean the writer could produce bytes it cannot
    read back.

    The rows are held as a tuple in the order the caller supplied them, and are
    *not* reordered here: sorting is the codec's job (it is what makes the
    staged bytes canonical), and a record that silently reordered its own
    content would hide from a caller that its panel was never in date order.
    """

    #: The node whose signal these returns belong to — §9.2's second key.
    node_id: str
    #: The canonical name of the sealed snapshot the returns were measured in.
    snapshot_name: str
    #: Feature 59's venue — the fee schedule these returns were priced under.
    venue: str
    #: Feature 59's version — that schedule's version.
    version: str
    #: The priced rows, one per ``(date, horizon, symbol)``.
    rows: tuple[ReturnRow, ...]

    def __post_init__(self) -> None:
        for field in ("node_id", "snapshot_name", "venue", "version"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ArtifactStoreError(
                    f"a signal-returns panel names the {field.replace('_', ' ')} "
                    f"its rows belong to — got {value!r}; §9.2's artifact is one "
                    "node's returns as a sealed snapshot measured them under one "
                    "fee schedule, and a panel missing any of the three cannot "
                    "say what it is a panel of"
                )
        rows = self.rows
        if isinstance(rows, (str, bytes, bytearray)) or not isinstance(
            rows, Iterable
        ):
            raise ArtifactStoreError(
                f"a signal-returns panel's rows are ReturnRow values — got "
                f"{type(rows).__name__}; the grid's rows are the measurements "
                "themselves, and a value that is not a collection of them "
                "carries no measurements"
            )
        rows = tuple(rows)
        for position, row in enumerate(rows):
            if not isinstance(row, ReturnRow):
                raise ArtifactStoreError(
                    f"a signal-returns panel's rows are ReturnRow values — got "
                    f"{type(row).__name__} at position {position}; a row of the "
                    "grid is a return with its date, horizon, symbol and fee "
                    "arithmetic, and a value that is not one is not a "
                    "measurement of this node"
                )
        if not rows:
            raise ArtifactStoreError(
                f"the {SIGNAL_RETURNS_FILENAME!r} of node {self.node_id!r} "
                "cannot be an empty panel; the grid holds one measurement per "
                "symbol per period per horizon, so a panel with no rows priced "
                "nothing at all — the evaluator refuses the same value one step "
                "earlier, which makes an empty grid a document this step's "
                "writer never produced"
            )
        seen: dict[tuple[dt.date, int, str], int] = {}
        for position, row in enumerate(rows):
            if row.cell in seen:
                day, horizon, _ = row.cell
                raise ArtifactStoreError(
                    f"the panel of node {self.node_id!r} carries "
                    f"{row.symbol!r} on {day.isoformat()} at horizon {horizon} "
                    f"twice — at positions {seen[row.cell]} and {position}; the "
                    "grid is one measurement per symbol per period per horizon, "
                    "and a panel with two rows in one cell would answer with "
                    "whichever was read last — a number this member's writer "
                    "never wrote"
                )
            seen[row.cell] = position
        object.__setattr__(self, "rows", rows)


# -- The write half ----------------------------------------------------------------


def persist_signal_returns(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    returns: SignalReturns,
) -> Path:
    """Stage the node's post-cost returns as ``signal_returns.parquet``.

    The feature's sentence as one call over feature 169's staged write path:
    the Parquet bytes join whatever else the writer has staged for the node,
    invisible to every read until the node's
    :meth:`~artifacts.ArtifactStore.commit` publishes the staged set — at which
    point the grid sits inside the node's one directory, keyed by the same two
    ids every reader joins on.  Returns the staged path for a caller that wants
    to name what it staged; the commit, not this call, is the publication.

    Every refusal — a malformed key, a value that is not a panel, a panel whose
    ``node_id`` is not the node it is being staged under, a row that is not a
    calendar date, a horizon, a symbol or a number, a row that does not net
    out, a cell written twice — lands before the first staged byte, so a
    refused panel leaves the staged set exactly as it was.  Staging the file
    again re-stages the one name, keeping the last bytes, exactly as re-staging
    any filename does; a commit then publishes the latest grid, never a splice
    of two runs.
    """
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    _check_panel_address(returns, campaign_id=campaign_id, node_id=node_id)
    payload = encode_signal_returns(returns)
    return store.write(campaign_id, node_id, SIGNAL_RETURNS_FILENAME, payload)


# -- The read half -----------------------------------------------------------------


def signal_returns(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> SignalReturns:
    """The node's post-cost return grid, read back as rows.

    The read side §1 grants the replay engine: the bytes persisted as
    ``signal_returns.parquet``, decoded and answered as the
    :class:`SignalReturns` they were written from — the panel marginal
    contribution against any book is recomputed over, and the one feature 174's
    dense ``nodes × periods`` load reads through.  Nothing is reduced on the
    way back out: every row, and every horizon, is answered, because a caller
    that asks for a node's returns is asking for the returns and not for a
    summary of them.

    Refuses with :class:`~artifacts._errors.ArtifactNotFoundError` when the
    node holds no directory or its directory holds no
    ``signal_returns.parquet``, the refusal naming which half is missing — so a
    node that never persisted stays distinguishable from one persisted without
    its grid.  Bytes this layer's writer cannot have produced — not Parquet,
    the wrong columns or metadata, a null or non-finite number, a mistyped
    column, a row that does not net out, a cell written twice, a file naming a
    node other than the one it was read from — refuse with
    :class:`~artifacts._errors.ArtifactStoreError` rather than answering a
    stand-in.
    """
    raw = store.read(campaign_id, node_id, SIGNAL_RETURNS_FILENAME)
    return decode_signal_returns(
        raw, campaign_id=campaign_id, node_id=node_id
    )


def signal_returns_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries its return grid.

    The feature's file as a fact: the node's directory is published *and* holds
    ``signal_returns.parquet``.  ``False`` for a node nothing was published for
    — staged-but-uncommitted is invisible by design, the discipline feature 169
    states — and ``False`` for a directory published without the grid, which is
    the state a reconciliation sweep exists to find.  Presence, not validity: a
    file this writer did not render is still a file at the name, and a sweep
    that wants its *content* checked asks :func:`signal_returns` and gets the
    refusal that names what is wrong.

    Worth asking on its own because this file is the one §9.2 calls the key
    artifact: a node whose directory is complete *except* for
    ``signal_returns.parquet`` is a node replay cannot recompute marginal
    contribution for, whatever else landed beside it.
    """
    if not store.has_node(campaign_id, node_id):
        return False
    return SIGNAL_RETURNS_FILENAME in store.files(campaign_id, node_id)


# -- The codec ---------------------------------------------------------------------


def encode_signal_returns(returns: SignalReturns) -> bytes:
    """Render a priced panel to one Zstd-compressed Parquet file.

    The whole of this feature's format at its seam: a :class:`SignalReturns`
    in, Parquet bytes out — the bytes :func:`persist_signal_returns` stages, and
    the bytes a DuckDB scan reads in place (§4.1) or a replay reads through
    :func:`decode_signal_returns`.  Both the columns and the schema's four
    metadata entries are pinned rather than inferred (see
    :func:`_returns_schema`), so the file's shape is a fact about this layer's
    format rather than about which pyarrow version happened to infer what.

    Deterministic: rows are ordered by ``(date, horizon, symbol)`` before they
    are written, so two equal panels stage byte-identical output regardless of
    the order their rows were built in — which is what lets replay compare a
    stored grid against the one it is reconstructing.

    Refuses a value that is not a panel, and an empty one, by name: both are
    documents this step's writer never produces, and a zero-row file would be
    one a reader had to interpret.
    """
    rows = _sorted_rows(returns)
    arrow = require_arrow()
    table = arrow.Table.from_pydict(
        {
            DATE_COLUMN: [row.rebalance_date for row in rows],
            HORIZON_COLUMN: [row.horizon for row in rows],
            SYMBOL_COLUMN: [row.symbol for row in rows],
            GROSS_COLUMN: [row.gross_return for row in rows],
            CHARGE_COLUMN: [row.charge for row in rows],
            NET_COLUMN: [row.post_cost_return for row in rows],
        },
        schema=_returns_schema(arrow, returns),
    )
    buffer = io.BytesIO()
    try:
        arrow.parquet.write_table(
            table, buffer, compression=PARQUET_COMPRESSION
        )
    except Exception as exc:
        raise ArtifactStoreError(
            f"the {SIGNAL_RETURNS_FILENAME!r} of node {returns.node_id!r} "
            f"could not be written as Parquet: {exc}; the grid is one node's "
            "per-symbol, per-period post-cost returns, and bytes a reader "
            "cannot parse back are not a panel that can be stored"
        ) from exc
    return buffer.getvalue()


def decode_signal_returns(
    payload: bytes, *, campaign_id: str, node_id: str
) -> SignalReturns:
    """Rebuild the priced panel :func:`encode_signal_returns` wrote.

    The read half of the codec: Parquet bytes in, a :class:`SignalReturns` out.
    Strict about what it will answer, because the alternative is handing a
    caller a measurement no writer of this layer produced: bytes that are not a
    Parquet file at all, a file whose columns or metadata are not this layer's
    or are typed differently, a null entry, a non-finite number, a symbol or a
    date of the wrong type, a row that does not net out, and a cell appearing
    twice each refuse by name.

    Each row's numbers are checked against their *own terms* rather than
    trusted — the gross must be its own charge plus its own net, the direction
    the module docstring gives the reasoning for — which is the defence
    :func:`evaluator.row_to_return` applies to the store's rows, restated here
    because this is the boundary a caller the evaluator never saw can reach,
    and because the two layers store the same three numbers.

    The file's metadata supplies the panel's identity, and the node it names
    must be the node the bytes were read from: a grid answering another node's
    identity than the directory it sits in is a misfiling every later reader
    would trust, and one this layer *can* detect rather than merely assume
    away.
    """
    arrow = require_arrow()
    try:
        table = arrow.parquet.read_table(arrow.BufferReader(payload))
    except Exception as exc:
        raise ArtifactStoreError(
            f"the {SIGNAL_RETURNS_FILENAME!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} is not a Parquet panel "
            f"({type(exc).__name__}: {exc}); the file is the Zstd-compressed "
            "Parquet feature 170's write path stages, and bytes no writer of "
            "this member emitted are a file it never staged"
        ) from exc
    _check_columns(table, arrow, campaign_id=campaign_id, node_id=node_id)
    dates = table.column(DATE_COLUMN).to_pylist()
    horizons = table.column(HORIZON_COLUMN).to_pylist()
    symbols = table.column(SYMBOL_COLUMN).to_pylist()
    grosses = table.column(GROSS_COLUMN).to_pylist()
    charges = table.column(CHARGE_COLUMN).to_pylist()
    nets = table.column(NET_COLUMN).to_pylist()
    rows: list[ReturnRow] = []
    for position, values in enumerate(
        zip(dates, horizons, symbols, grosses, charges, nets)
    ):
        rows.append(
            _stored_row(
                position=position,
                values=values,
                campaign_id=campaign_id,
                node_id=node_id,
            )
        )
    return SignalReturns(
        node_id=_metadata_text(
            table,
            NODE_METADATA_KEY,
            label="node",
            campaign_id=campaign_id,
            node_id=node_id,
            expected=node_id,
        ),
        snapshot_name=_metadata_text(
            table,
            SNAPSHOT_METADATA_KEY,
            label="sealed snapshot",
            campaign_id=campaign_id,
            node_id=node_id,
        ),
        venue=_metadata_text(
            table,
            VENUE_METADATA_KEY,
            label="cost model venue",
            campaign_id=campaign_id,
            node_id=node_id,
        ),
        version=_metadata_text(
            table,
            VERSION_METADATA_KEY,
            label="cost model version",
            campaign_id=campaign_id,
            node_id=node_id,
        ),
        rows=tuple(rows),
    )


# -- The schema, spelled once for the writer and the reader ------------------------


def _returns_schema(arrow: Any, returns: SignalReturns) -> Any:
    """The Arrow schema the grid is written through, with the panel's identity.

    Six pinned columns and four metadata entries.  Pinned rather than inferred,
    because every column of this file can be named before a row is seen: a date
    is a ``date32``, a period count an ``int32``, a symbol text, and the three
    measurements doubles — the module docstring gives the reasoning for each.
    The pin is what makes the bytes deterministic by construction rather than by
    Arrow's inference happening to agree with itself.

    The *identity* rides as schema metadata: the node, the sealed snapshot and
    feature 59's ``(venue, version)`` pair, each one value per file (see the
    module docstring for why none of them is a column).  The values are encoded
    UTF-8 here and decoded on the read side, so the file's metadata is text in
    the one encoding the rest of this member writes with.
    """
    return arrow.schema(
        [
            arrow.field(DATE_COLUMN, arrow.date32()),
            arrow.field(HORIZON_COLUMN, arrow.int32()),
            arrow.field(SYMBOL_COLUMN, arrow.string()),
            arrow.field(GROSS_COLUMN, arrow.float64()),
            arrow.field(CHARGE_COLUMN, arrow.float64()),
            arrow.field(NET_COLUMN, arrow.float64()),
        ],
        metadata={
            NODE_METADATA_KEY: returns.node_id.encode("utf-8"),
            SNAPSHOT_METADATA_KEY: returns.snapshot_name.encode("utf-8"),
            VENUE_METADATA_KEY: returns.venue.encode("utf-8"),
            VERSION_METADATA_KEY: returns.version.encode("utf-8"),
        },
    )


def _check_columns(
    table: Any, arrow: Any, *, campaign_id: str, node_id: str
) -> None:
    """Refuse a table that is not the grid schema this layer writes.

    Every column is required and every type is checked, rather than left to
    fail at the ``to_pylist`` below: a ``date32`` column hands back
    :class:`datetime.date` values and a ``string`` column hands back strings, so
    a file carrying the right *names* and the wrong *types* would decode into
    rows of the wrong shape and be answered as a panel.  This is the check
    feature 171's series module makes on its two columns, extended to this
    file's six.
    """
    names = list(table.schema.names)
    expected = (
        DATE_COLUMN,
        HORIZON_COLUMN,
        SYMBOL_COLUMN,
        GROSS_COLUMN,
        CHARGE_COLUMN,
        NET_COLUMN,
    )
    for column in expected:
        if column not in names:
            raise ArtifactStoreError(
                f"the {SIGNAL_RETURNS_FILENAME!r} of node {node_id!r} of "
                f"campaign {campaign_id!r} carries no {column!r} column — it "
                f"carries {', '.join(names) or 'no columns'}; a signal-returns "
                f"file is the {', '.join(expected)} row this member's writer "
                "emits, and a file without all six is one it never staged"
            )
    checks = (
        (DATE_COLUMN, arrow.types.is_date, "a return is keyed by a calendar date"),
        (
            HORIZON_COLUMN,
            arrow.types.is_integer,
            "a horizon is an integer period count",
        ),
        (
            SYMBOL_COLUMN,
            arrow.types.is_string,
            "a symbol is an instrument's name",
        ),
        (
            GROSS_COLUMN,
            arrow.types.is_floating,
            "a gross return is a floating-point number",
        ),
        (
            CHARGE_COLUMN,
            arrow.types.is_floating,
            "a charge is a floating-point number",
        ),
        (
            NET_COLUMN,
            arrow.types.is_floating,
            "a post-cost return is a floating-point number",
        ),
    )
    for column, predicate, why in checks:
        column_type = table.schema.field(column).type
        if not predicate(column_type):
            raise ArtifactStoreError(
                f"the {SIGNAL_RETURNS_FILENAME!r} of node {node_id!r} of "
                f"campaign {campaign_id!r} types its {column!r} column as "
                f"{column_type}; {why}, and a column of another type is not the "
                "panel this member's writer emits"
            )


def _metadata_text(
    table: Any,
    key: bytes,
    *,
    label: str,
    campaign_id: str,
    node_id: str,
    expected: str | None = None,
) -> str:
    """The text a schema-metadata entry carries, or a refusal naming it.

    The four entries the writer stamps are the panel's identity, and each is
    one value per file — so this answers the value and refuses a file whose
    entry is missing, is not UTF-8 text, or names a node other than the one the
    bytes were read from.  ``expected`` is given only for the node entry: it is
    the one whose value the reader can check against something it already
    knows, and the check is worth making rather than assuming away, because a
    grid answering another node's identity than the directory it sits in is a
    misfiling every later reader would trust.
    """
    raw = (table.schema.metadata or {}).get(key)
    if raw is None:
        raise ArtifactStoreError(
            f"the {SIGNAL_RETURNS_FILENAME!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} names no {label}; the panel's identity travels in "
            "the Parquet schema's metadata rather than on every row, and a file "
            "without it is one this member's writer never staged — a panel that "
            "cannot say what it is a panel of is one nothing can be compared "
            "against"
        )
    try:
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, AttributeError) as exc:
        raise ArtifactStoreError(
            f"the {SIGNAL_RETURNS_FILENAME!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} spells its {label} with bytes that are not UTF-8 "
            f"({raw!r}); every writer of this member spells it as text"
        ) from exc
    if expected is not None and text != expected:
        raise ArtifactStoreError(
            f"the {SIGNAL_RETURNS_FILENAME!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} names {label} {text!r}, but it was read from node "
            f"{expected!r}; §9.2 keys the artifact directory by campaign then "
            "node, and a grid filed under a node it does not measure is one "
            "every later reader — replay recomputing marginal contribution "
            "above all — would join to the wrong signal"
        )
    return text


# -- The panel's validation, spelled once for every seam above ---------------------


def _check_panel_address(
    returns: Any, *, campaign_id: str, node_id: str
) -> str:
    """Return the panel's node id, or refuse the panel by name.

    Two questions, both of which outrank rendering: is this a panel at all, and
    is it *this* node's?  A grid filed under another node's key is a misfiling
    every later reader would trust — the directory's two ids are how §1's replay
    joins a node to its returns, and a file that disagrees with the key it sits
    under is provenance the store cannot repair.  The campaign is not asked of
    the panel: a panel never names one, and the store's own key validation
    answers for it.
    """
    if not isinstance(returns, SignalReturns):
        raise ArtifactStoreError(
            "persist_signal_returns writes one node's priced panel — a "
            f"SignalReturns — got {type(returns).__name__}; the grid's rows are "
            "the post-cost returns and their provenance, and a value that is not "
            "the panel carries none of them"
        )
    if returns.node_id != node_id:
        raise ArtifactStoreError(
            f"the panel measures node {returns.node_id!r} but is being staged "
            f"under node {node_id!r} of campaign {campaign_id!r}; §9.2 keys the "
            "artifact directory by campaign then node, and a grid filed under a "
            "node it does not measure is one every later reader — replay "
            "recomputing marginal contribution above all — would join to the "
            "wrong signal"
        )
    return returns.node_id


def _sorted_rows(returns: Any) -> list[ReturnRow]:
    """Return ``returns``' rows, sorted by ``(date, horizon, symbol)``.

    The write side's whole contribution to determinism, and the reason
    :func:`encode_signal_returns` stages canonical bytes: the rows come back in
    the one order every reader would have to impose anyway.

    The validation itself lives on the records (:class:`SignalReturns` and
    :class:`ReturnRow`), so a panel is never *constructed* in a state the writer
    would refuse; what is repeated here is the two questions a caller reaching
    the codec directly would otherwise skip — is this a panel, and does it carry
    a row — because the codec is a public seam in its own right and the
    constructor's checks are not on its path.
    """
    if not isinstance(returns, SignalReturns):
        raise ArtifactStoreError(
            "a signal-returns file is rendered from one node's priced panel — a "
            f"SignalReturns — got {type(returns).__name__}; the codec's argument "
            "is the grid itself, and anything else has no rows to encode"
        )
    if not returns.rows:
        raise ArtifactStoreError(
            f"the {SIGNAL_RETURNS_FILENAME!r} of node {returns.node_id!r} "
            "cannot be an empty panel; the grid holds one measurement per symbol "
            "per period per horizon, so a panel with no rows priced nothing at "
            "all — the evaluator refuses the same value one step earlier, which "
            "makes an empty grid a document this step's writer never produced"
        )
    return sorted(returns.rows, key=lambda row: row.cell)


def _stored_row(
    *,
    position: int,
    values: tuple[Any, ...],
    campaign_id: str,
    node_id: str,
) -> ReturnRow:
    """One stored row, checked and rebuilt, or a refusal naming the row.

    Where the read side's per-row strictness lives.  The values arrive from the
    Arrow columns — already typed by the schema check above, but not *trusted*
    for it: an Arrow ``date32`` column can carry nulls, and a null is not a type
    error, so each is checked here rather than left to fail inside a
    constructor with a message that could not say which row it came from.

    The three numbers are checked against *each other* here and this is the
    only place that check can live, because the record derives the gross rather
    than accepting one (see :class:`ReturnRow`).  The stretched file is refused
    by name instead of loaded as a plausible-looking lie: the row says gross
    less charge is the net, and this recomputes the difference from the file's
    own two numbers — the identity :func:`evaluator.row_to_return` enforces on
    the store's rows, restated for the file, and the reason a ``gross_return``
    edited outside this package cannot survive a read.

    Every refusal names the row's *position* as well as its address, because a
    grid is a hundred thousand rows and "a value is not finite" without a handle
    on the row is not findable.
    """
    where = (
        f"row {position} of the {SIGNAL_RETURNS_FILENAME!r} of node "
        f"{node_id!r} of campaign {campaign_id!r}"
    )
    day, horizon, symbol, gross, charge, net = values
    _require_present(day, "date", where)
    _require_present(horizon, "horizon", where)
    _require_present(symbol, "symbol", where)
    for label, value in (
        (GROSS_COLUMN, gross),
        (CHARGE_COLUMN, charge),
        (NET_COLUMN, net),
    ):
        _require_present(value, label, where)
    try:
        row = ReturnRow(
            rebalance_date=day,
            horizon=horizon,
            symbol=symbol,
            charge=charge,
            post_cost_return=net,
        )
    except ArtifactStoreError as exc:
        raise ArtifactStoreError(f"{where} is not a return: {exc}") from exc
    if row.gross_return != _validated_number(gross, GROSS_COLUMN, where=where):
        raise ArtifactStoreError(
            f"{where} says gross {gross!r} less charge {charge!r} is {net!r}; "
            "the row disagrees with itself, so it was written or edited outside "
            "this package — a post-cost return that does not net out is a "
            "number the metrics and replay would trust and be wrong by"
        )
    return row


def _require_present(value: Any, label: str, where: str) -> None:
    """Refuse a null entry, naming the row it sits on.

    A Parquet column may carry nulls whatever its type, so the schema check
    above cannot rule them out and the presence of every entry is checked on
    its own.  A missing measurement is an *absent row* rather than a row
    holding null — the distinction every layer of this category maintains — and
    the writer of this member emits neither.
    """
    if value is None:
        raise ArtifactStoreError(
            f"{where} carries a null {label}; a row of the grid is a "
            "measurement — a symbol's return on a rebalance date at a horizon — "
            "and a missing one is an absent row rather than a row holding null, "
            "which is the one thing this member's writer never emits"
        )


def _validated_date(value: Any) -> dt.date:
    """Return ``value`` as the calendar date it must be, or refuse it.

    The series' axis is a *rebalance date*, so the value is a
    :class:`datetime.date` or the ISO-8601 date text
    :meth:`datetime.date.isoformat` produces — the two spellings the evaluator
    answers with, since its records key their series by calendar dates while
    its stored rows are read back as ISO text.  A :class:`datetime.datetime` is
    refused **before** the :class:`~datetime.date` check, because it is a
    subclass and would otherwise pass: a grid keyed by instants is one no other
    row can be joined against, and the mistake would show up far from here.
    """
    if isinstance(value, dt.datetime):
        raise ArtifactStoreError(
            f"a signal return is keyed by a calendar date — got the datetime "
            f"{value!r}; a datetime is a date in Python and would pass a naive "
            "check, but a grid keyed by instants cannot be joined against one "
            "keyed by dates, and the rebalance grid the returns were taken on "
            "is made of dates"
        )
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ArtifactStoreError(
                f"a signal return is keyed by a calendar date — got the text "
                f"{value!r}, which is not an ISO-8601 date (YYYY-MM-DD); the "
                "text spelling a renderer answers is date.isoformat(), and "
                "anything else is a key no reader can join back to a rebalance"
            ) from exc
    raise ArtifactStoreError(
        f"a signal return is keyed by a calendar date — got {value!r} "
        f"({type(value).__name__}); the axis is the rebalance date each return "
        "was taken on, and a key that is not a date is a measurement belonging "
        "to no rebalance"
    )


def _validated_horizon(value: Any) -> int:
    """Return ``value`` as the positive period count it must be, or refuse it.

    A ``bool`` is refused even though it is an :class:`int` in Python: ``True``
    is ``1``, and a flag where a period count belongs would silently measure
    the shortest horizon of the spec — the kind of mistake that produces a
    plausible number rather than an error.

    What this layer does *not* do is demand one of the spec's five horizons.
    That set is feature 75's and the evaluator's, and this module does not
    restate the evaluator's vocabulary: a panel's horizon is validated as the
    shape the column needs, and whether it is a horizon the pipeline measures
    at is the step that produced it.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactStoreError(
            f"a signal return's horizon is an integer period count — got "
            f"{value!r} ({type(value).__name__}); the horizon is feature 75's "
            "target axis, and a row that does not name one belongs to no "
            "horizon any metric is measured over"
        )
    if value < 1:
        raise ArtifactStoreError(
            f"a signal return's horizon is a positive period count — got "
            f"{value!r}; a return is measured *forward* from its rebalance "
            "date, and a horizon of zero or fewer periods measures the bar it "
            "is already on"
        )
    return value


def _validated_symbol(value: Any) -> str:
    """Return ``value`` as the non-empty symbol text it must be, or refuse it.

    Text rather than coerced, because ``str()`` would happily render an
    ``int`` instrument code — and it would be a symbol nothing downstream could
    join back to, since the panel, the evaluator's store and feature 179's tree
    all name instruments with strings.
    """
    if not isinstance(value, str) or not value:
        raise ArtifactStoreError(
            f"a signal return's symbol is an instrument's name — got {value!r} "
            f"({type(value).__name__}); the grid's third axis is the symbol, "
            "and a return belonging to no instrument belongs to no book the "
            "replay could recompute marginal contribution against"
        )
    return value


def _validated_number(value: Any, label: str, *, where: str) -> float:
    """Return ``value`` as the finite float it must be, or refuse it.

    One validator for the three measurements, so the gross, the charge and the
    net cannot drift into different rules.  A ``bool`` is refused (it is an
    :class:`int` in Python, and a flag is not a return), and ``nan`` and ``±inf``
    are refused by name: they are what a correlation produces over a constant
    cross-section, and they would reach every downstream metric dressed as a
    measurement — the argument the evaluator's own row validator makes for the
    same three columns.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactStoreError(
            f"{where} carries the {label} {value!r} ({type(value).__name__}); a "
            "gross return, a charge and a post-cost return are all numbers, and "
            "a value that is not one is not a measurement of the node"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ArtifactStoreError(
            f"{where} carries the non-finite {label} {number!r}; nan and inf "
            "are what a correlation produces over a constant cross-section, not "
            "a measurement, and a return a reader must be able to compare is "
            "one a reader must be able to parse"
        )
    return number
