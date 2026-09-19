"""Persisting the post-cost signal return series — feature 79's other half.

app_spec.xml feature 79: *"System applies the cost model to the aligned
returns, **persisting a post-cost signal return series per symbol**."*  The
arithmetic lives in :mod:`evaluator._costs`; this module writes it down.
The split is the one this package already uses for feature 70 — ``_identity``
computes, ``_store`` persists — and for the same reason: a caller that had to
wire the two together at every call site would eventually wire them together
differently at one of them.

**Why the series is kept in full, and why that is the feature.**  §9.2 names
the artifact this table becomes and states what its completeness buys:

.. code-block:: text

    signal_returns.parquet    # per-symbol, per-period, post-cost  ← enables ir_marginal

*"Because it is stored in full, marginal contribution against any book can be
recomputed at replay time, so the same node scores differently depending on
the path a policy took to reach it, while replay stays fully deterministic."*
A table that stored one averaged cost per node would satisfy a careless
reading of "persisting a post-cost return series" and would make feature 83's
``ir_marginal``, §9.3's resident campaign arrays and feature 174's dense
``nodes × periods`` load all impossible.  So the grain here is the finest one
the feature names: **one row per ``(node, cost model, horizon, rebalance
date, symbol)``**.  Nothing is reduced, aggregated or summarised on the way
in, because every consumer downstream is defined over the per-symbol series
and none of them can recover it from a summary.

**The gross return is stored beside the net, and that is not redundancy.**
It is not even this module's number: the gate supplied it, and re-running the
pipeline to fetch it back is exactly what §6.2's shared library and feature
60's hash exist to make unnecessary rather than merely possible — the fee
assumption being re-read may have moved since.  With both halves on the row,
the artifact answers *what the signal predicted*, *what the schedule took*
and *what was left* from one read, and "the schedule was applied to these
returns" becomes a fact about stored data rather than a claim about a code
path.

**Two tables, because a read-back has to be lossless.**  The series rows
carry what was charged; a second, one-row-per-evaluation table carries the
evaluation's *grid*, its snapshot and §7.2's budget directive — everything
that is one value per evaluation rather than one per symbol.
The grid has to be stored rather than
recovered: a horizon's series is shorter than the grid it was scored on (the
last ``h`` dates have no ``h``-period future), so the union of the stored
dates is a strict subset of the grid, and a reader that rebuilt the grid from
the rows would hand back an evaluation scored over fewer dates than it
actually was — an understatement in the direction of "this signal traded less
than it did".  The directive is stored for a sharper reason: it is the bit
features 80, 83 and 84 read off step 7's record, and feature 84's trial
charge is the write that must happen *even when the evaluation went wrong* —
so a value lost on the read path is one no later step can go back for.  One
small JSON row per evaluation makes the read-back return exactly the value
that was written, which is what §9.2's artifact round trip requires.

**Assign-once in effect, though the write is an upsert.**  The primary key is
the full grain, and a re-persist refreshes the stored numbers rather than
adding a second row.  It has to: applying the same schedule over the same
evaluation twice must leave one row per symbol per period, because §9.2's
artifact is loaded as a single dense ``nodes × periods`` array (feature 174)
and a duplicated period would read to every consumer as a longer history.
The upsert is deliberately narrow — it rewrites the three numbers and the
provenance and nothing that *names* the row — so it cannot re-key a stored
series into a different one.  Unlike the identity table, a *changed* number
under an existing key is not refused: the key names the evaluation and the
fee schedule, both of which are in it, so a re-application of the same
schedule over the same evaluation producing different numbers is a producer
that drifted and the last write wins.  What is refused instead is a stored
row that cannot be *believed* — a net that does not equal its own gross less
its own charge — see :func:`row_to_return`.

**Schema.**  §9.2's artifact is Parquet, written by the artifacts member
(feature 170, ``plugin="artifacts"``, which owns the node artifact directory
of feature 169).  This module does not write that file: it owns the
*evaluator's* half of the feature — computing the series and getting it
somewhere durable — and it stores it in the workspace's relational store,
addressed by ``DATABASE_URL`` exactly as the identity store and the universe
and snapshot members are.  The caller holding a campaign and a node artifact
directory is what later writes the Parquet, reading this table through
:meth:`PostCostStore.load`; that way the artifact and the row cannot disagree
about what was computed, and the two writers of one evaluation's returns
share one source.  The schema is created idempotently on connect —
``CREATE TABLE IF NOT EXISTS``, the contract the identity store states — so a
fresh database and an existing one take one path and no migration step is
needed for this member.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import unquote, urlparse

from ._align import HORIZONS
from ._costs import CostModelRef, PostCostReturns, PostCostSeries, cost_model_ref
from ._errors import EvaluatorCostError, EvaluatorStoreError

__all__ = [
    "DATABASE_URL_ENV",
    "SIGNAL_RETURNS_GRID_TABLE",
    "SIGNAL_RETURNS_TABLE",
    "PostCostStore",
    "cost_series_from_rows",
    "load_signal_returns",
    "persist_signal_returns",
    "row_to_return",
]

#: The environment variable naming the relational store, shared with the rest
#: of the workspace (the universe, snapshot and cost-model members read the
#: same one; the repository-level conftest points it at a per-test database).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the post-cost signal returns live in.
#:
#: Named for §9.2's artifact — ``signal_returns.parquet`` — rather than for
#: the step that fills it, because the thing stored is the artifact's content
#: and the artifact is what §9.2's comment is about.
SIGNAL_RETURNS_TABLE = "signal_returns"

#: The companion table: one row per evaluation, carrying the grid it was
#: scored on.  Separate from the series table because it is per-*evaluation*
#: rather than per-symbol-per-period, and because the grid cannot be
#: recovered from the series (see the module docstring).
SIGNAL_RETURNS_GRID_TABLE = "signal_returns_grid"

_SCHEMA = f"""
-- Feature 79: the post-cost signal return series, one row per symbol per
-- period per horizon per node per cost model.
--
-- The grain is the feature's own ("per symbol") and it is deliberately the
-- finest one the feature names: §9.2's signal_returns.parquet is read back in
-- full so `ir_marginal` can be recomputed at replay time, and a summary would
-- make that impossible.
--
-- `(node_id, venue, version, horizon, rebalance_date, symbol)` is the key.
-- The (venue, version) pair is feature 59's cost model identity and it is
-- *in* the key, not beside it: the same node's returns priced under two fee
-- schedules are two series, and collapsing them would file one schedule's
-- numbers under another's provenance — §15 treats a changed cost model as
-- its own failure case.
--
-- The three REAL columns are the whole point of the row, and the gross one is
-- carried on purpose: with `gross_return` and `charge` beside
-- `post_cost_return` the artifact answers what the signal predicted, what the
-- schedule took and what was left, from one read, without re-running a fee
-- assumption that may have moved.
CREATE TABLE IF NOT EXISTS {SIGNAL_RETURNS_TABLE} (
    node_id          TEXT NOT NULL,  -- the evaluation these returns belong to
    venue            TEXT NOT NULL,  -- feature 59's cost model pair
    version          TEXT NOT NULL,
    horizon          INTEGER NOT NULL,  -- one of the five spec horizons
    rebalance_date   TEXT NOT NULL,  -- ISO 8601 date: the bar the return is for
    symbol           TEXT NOT NULL,  -- the instrument the return belongs to
    gross_return     REAL NOT NULL,  -- pre-cost, as the null gate supplied it
    charge           REAL NOT NULL,  -- the deduction the cost schedule applied
    post_cost_return REAL NOT NULL,  -- gross_return - charge, stored as applied
    snapshot_name    TEXT NOT NULL,  -- provenance: which sealed world
    PRIMARY KEY (node_id, venue, version, horizon, rebalance_date, symbol)
);

CREATE INDEX IF NOT EXISTS {SIGNAL_RETURNS_TABLE}_node
    ON {SIGNAL_RETURNS_TABLE} (node_id, venue, version, horizon);

-- One row per evaluation. `rebalance_dates` is the grid the evaluation was
-- scored on — what was scored, not what any single horizon could measure —
-- and it is stored because it cannot be recovered from the series rows: the
-- union of the stored dates is a strict subset of the grid, since the last
-- `horizon` dates have no forward return at that horizon. A reader that
-- rebuilt the grid from the rows would hand back an evaluation scored over
-- fewer dates than it was, which is an understatement of what the signal did.
--
-- `charges_budget` lives here rather than on the series rows because it is
-- one bit per evaluation, not per symbol: §7.2 lets it cross the barrier as a
-- directive and §8 stores it on the trial-ledger row (FALSE for a null node),
-- which features 80, 83 and 84 read from *this* record. It is persisted for
-- the same reason the grid is: dropping it on the way back would hand the
-- later steps a record that cannot say whether statistical budget was
-- consumed, and feature 84's trial charge is the write that must happen even
-- when an evaluation went wrong.
CREATE TABLE IF NOT EXISTS {SIGNAL_RETURNS_GRID_TABLE} (
    node_id          TEXT NOT NULL,
    venue            TEXT NOT NULL,
    version          TEXT NOT NULL,
    snapshot_name    TEXT NOT NULL,  -- provenance: one evaluation, one world
    rebalance_dates  TEXT NOT NULL,  -- the grid, as a JSON array of ISO dates
    charges_budget   INTEGER NOT NULL,  -- §7.2's directive: 0 or 1
    PRIMARY KEY (node_id, venue, version)
);
"""

# The series row's columns, in insertion order.  Kept as one string so the
# writer and the reader cannot drift apart in column order — the failure that
# would silently swap a gross return for a net one.
_COLUMNS = (
    "node_id, venue, version, horizon, rebalance_date, symbol, "
    "gross_return, charge, post_cost_return, snapshot_name"
)

# The reader's column list, in the order :func:`row_to_return` unpacks it.
_RETURN_COLUMNS = (
    "rebalance_date, horizon, symbol, gross_return, charge, post_cost_return"
)


def row_to_return(row: Any) -> tuple[Any, int, str, float, float, float]:
    """Reconstruct one stored return from a row, checking it against itself.

    ``row`` is a ``(rebalance_date, horizon, symbol, gross_return, charge,
    post_cost_return)`` tuple as this store reads it.  The post-cost value is
    *recomputed from its own terms* rather than trusted: the row stores the
    gross, the charge and the net computed from them, so a row where the three
    disagree has been edited outside this package — a net rewritten while its
    inputs were left alone — and it fails here instead of loading as a
    plausible-looking lie.  That is the same defence the identity store's read
    path applies, for the same reason: what the metrics trust is the stored
    number, and a store that could hand back a row disagreeing with itself
    would launder a tamper.

    Returns ``(rebalance_date, horizon, symbol, gross_return, charge,
    post_cost_return)`` with the date parsed and the numbers as floats.
    """
    import datetime as dt

    (
        rebalance_date,
        horizon,
        symbol,
        gross_return,
        charge,
        post_cost_return,
    ) = row
    try:
        day = dt.date.fromisoformat(rebalance_date)
    except (TypeError, ValueError) as exc:
        raise EvaluatorStoreError(
            "a stored signal return carries a rebalance date this store did "
            f"not write ({rebalance_date!r}); rows are keyed by ISO 8601 "
            "calendar dates"
        ) from exc
    if isinstance(horizon, bool) or not isinstance(horizon, int):
        raise EvaluatorStoreError(
            f"a stored signal return for {symbol!r} on {day.isoformat()} "
            f"carries horizon {horizon!r}, which is not an integer period "
            "count"
        )
    gross = float(gross_return)
    deduction = float(charge)
    net = gross - deduction
    if net != float(post_cost_return):
        raise EvaluatorStoreError(
            f"the stored signal return for {symbol!r} on {day.isoformat()} "
            f"at horizon {horizon} says gross {gross_return!r} less charge "
            f"{charge!r} is {post_cost_return!r}; the row disagrees with "
            "itself, so it was written or edited outside this package — a "
            "post-cost series that does not net out is a number the metrics "
            "would trust and be wrong by"
        )
    return day, horizon, symbol, gross, deduction, net


def cost_series_from_rows(
    rows: Any, ref: CostModelRef, snapshot_name: str
) -> dict[int, PostCostSeries]:
    """Fold stored rows into the five per-horizon series they came from.

    The inverse of what :func:`persist_signal_returns` wrote, so a caller that
    reads an evaluation's returns back holds the same value the pipeline
    produced rather than a second, parallel spelling of it.  A horizon with no
    rows comes back as the empty series :class:`PostCostSeries` carries —
    feature 75's five-horizon shape promise, kept on the read path too, so a
    consumer iterating the horizons of a decay profile finds five.
    """
    values: dict[int, dict[Any, dict[str, float]]] = {
        horizon: {} for horizon in HORIZONS
    }
    charges: dict[int, dict[Any, dict[str, float]]] = {
        horizon: {} for horizon in HORIZONS
    }
    for row in rows:
        day, horizon, symbol, _gross, charge, net = row_to_return(row)
        if horizon not in values:
            raise EvaluatorStoreError(
                f"stored signal returns carry horizon {horizon} for "
                f"{symbol!r} on {day.isoformat()}; the set is the spec's — "
                f"{', '.join(str(h) for h in HORIZONS)} — and a row outside "
                "it did not come out of this store's writer"
            )
        values[horizon].setdefault(day, {})[symbol] = net
        charges[horizon].setdefault(day, {})[symbol] = charge
    return {
        horizon: PostCostSeries(
            horizon=horizon,
            snapshot_name=snapshot_name,
            venue=ref.venue,
            version=ref.version,
            values=values[horizon],
            charges=charges[horizon],
        )
        for horizon in HORIZONS
    }


def _sqlite_path(database_url: str) -> Optional[Path]:
    """Translate a ``sqlite:///`` URL into a path (``None`` for in-memory).

    The same convention the identity store and the cost-model member document:
    ``sqlite:///foo.db`` is relative, an absolute path carries its leading
    slash after the triple, and any other scheme is refused loudly rather than
    silently mis-parsed.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise EvaluatorStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise EvaluatorStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    return Path(path) if path else None


class PostCostStore:
    """Reads and writes the ``signal_returns`` tables for one database.

    Bound to a database URL at construction, and — like the identity store,
    and unlike the snapshot member's manifest store — it refuses rather than
    degrading when no store is configured: feature 79's text is "persisting",
    and §9.2's artifact is what replay reads back.  A service that reported
    success for a write it did not perform would leave an evaluation whose
    returns exist only until the process exits, which is precisely the gap the
    feature closes.

    Construction performs no I/O.  The path is resolved and the schema created
    on first use, so composing an application that carries this store touches
    no disk — the same stance every store in this workspace takes.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None
        self._resolved = False

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "PostCostStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the way the shared
        fixtures treat an empty ``TEST_DATABASE_URL``.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no store to "
                "persist the post-cost signal returns into (app_spec.xml "
                f"feature 79); set {DATABASE_URL_ENV} to the system's "
                "database"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The rows -----------------------------------------------------------

    def persist(self, returns: PostCostReturns) -> PostCostReturns:
        """Write one evaluation's post-cost series; return the record.

        One upsert per row on the full grain, so applying the same schedule
        over the same evaluation twice leaves one row per symbol per period
        rather than two interleaved copies — §9.2's artifact is loaded as a
        single dense ``nodes × periods`` array (feature 174), and a doubled
        period would read to every consumer as a longer history.

        The upsert refreshes the three numbers and the provenance and nothing
        that *names* the row, so a re-application cannot re-key a stored
        series.  A store that cannot be reached, an unsupported URL scheme, a
        locked or unwritable database — every one surfaces as
        :class:`~evaluator.EvaluatorStoreError`, deliberately not swallowed: a
        series that was computed and never landed is the state feature 79's
        "persisting" exists to rule out.
        """
        if not isinstance(returns, PostCostReturns):
            raise EvaluatorCostError(
                "persist_signal_returns writes step 7's own result — a "
                "PostCostReturns — got "
                f"{type(returns).__name__}; the series it persists carry the "
                "cost model that priced them, and anything else has none"
            )
        rows: list[tuple[Any, ...]] = []
        for horizon, series in sorted(returns.series.items()):
            for day in series.dates():
                for symbol, net in sorted(series.at(day).items()):
                    deduction = series.charge_at(day)[symbol]
                    rows.append(
                        (
                            returns.node_id,
                            returns.cost_model.venue,
                            returns.cost_model.version,
                            horizon,
                            day.isoformat(),
                            symbol,
                            net + deduction,
                            deduction,
                            net,
                            series.snapshot_name,
                        )
                    )
        if not rows:
            raise EvaluatorCostError(
                "refusing to persist an empty post-cost series for node "
                f"{returns.node_id!r}: the bundle carries no computable "
                "return at any horizon, so there is nothing for replay to "
                "read back"
            )
        grid = json.dumps(
            [day.isoformat() for day in returns.rebalance_dates]
        )
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {SIGNAL_RETURNS_GRID_TABLE} (
                        node_id, venue, version, snapshot_name,
                        rebalance_dates, charges_budget
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id, venue, version) DO UPDATE SET
                        snapshot_name   = excluded.snapshot_name,
                        rebalance_dates = excluded.rebalance_dates,
                        charges_budget  = excluded.charges_budget
                    """,
                    (
                        returns.node_id,
                        returns.cost_model.venue,
                        returns.cost_model.version,
                        returns.snapshot_name,
                        grid,
                        int(returns.charges_budget),
                    ),
                )
                connection.executemany(
                    f"""
                    INSERT INTO {SIGNAL_RETURNS_TABLE} ({_COLUMNS})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        node_id, venue, version, horizon, rebalance_date, symbol
                    ) DO UPDATE SET
                        gross_return     = excluded.gross_return,
                        charge           = excluded.charge,
                        post_cost_return = excluded.post_cost_return,
                        snapshot_name    = excluded.snapshot_name
                    """,
                    rows,
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not persist the post-cost signal returns for node "
                f"{returns.node_id!r}: {exc}"
            ) from exc
        return returns

    def load(
        self,
        node_id: str,
        cost_model: Union[CostModelRef, object],
    ) -> Optional[PostCostReturns]:
        """Read one evaluation's post-cost series back, or ``None``.

        The reader §9.2's artifact and feature 83's ``ir_marginal`` resolve
        against: given the node and the cost model a score names, answer with
        the series that were stored — or ``None``, which is the honest answer
        for an evaluation this store never costed, on the same stance the
        identity store's reader takes.

        The ``(venue, version)`` the caller names is *part of the question*,
        not a filter over it: returns priced under one fee schedule are not a
        partial answer to a question about another, which is the whole reason
        the pair is in the primary key.

        What comes back is the value that was written — including the
        evaluation's own grid, read from the companion row rather than
        rebuilt from the series, which is narrower than the grid by
        construction (see the module docstring).
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorStoreError(
                "a node id must be a non-empty string to read post-cost "
                f"signal returns by, got {node_id!r}"
            )
        ref = cost_model_ref(cost_model)
        try:
            with closing(self._connect()) as connection:
                grid_row = connection.execute(
                    f"""
                    SELECT snapshot_name, rebalance_dates, charges_budget
                    FROM {SIGNAL_RETURNS_GRID_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchone()
                rows = connection.execute(
                    f"""
                    SELECT {_RETURN_COLUMNS}
                    FROM {SIGNAL_RETURNS_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    ORDER BY horizon, rebalance_date, symbol
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not read the post-cost signal returns for node "
                f"{node_id!r} under {ref.reference}: {exc}"
            ) from exc
        if grid_row is None and not rows:
            return None
        if grid_row is None:
            # A series without its grid row: the two are written in one
            # transaction, so this is a row set that was edited outside this
            # package, and rebuilding a grid from the series would silently
            # understate what the evaluation scored.
            raise EvaluatorStoreError(
                f"the store holds post-cost signal returns for node "
                f"{node_id!r} under {ref.reference} but no grid row; the two "
                "are written together, so this row set did not come out of "
                "this store's writer — rebuilding the grid from the series "
                "would report an evaluation scored over fewer dates than it "
                "was"
            )
        snapshot_name, grid_json, budget_flag = grid_row
        if not rows:
            # A grid with no series: the evaluation was costed and had no
            # computable return.  Refused rather than returned as five empty
            # series, on the same terms apply_costs refuses that bundle.
            raise EvaluatorStoreError(
                f"the store holds a grid row for node {node_id!r} under "
                f"{ref.reference} but no post-cost returns; a costed "
                "evaluation has a return at some horizon, so these rows were "
                "not written by one of ours"
            )
        try:
            grid = tuple(
                _parse_day(day) for day in json.loads(grid_json)
            )
        except ValueError as exc:
            raise EvaluatorStoreError(
                f"the stored grid for node {node_id!r} under "
                f"{ref.reference} is not valid JSON: {exc}"
            ) from exc
        if budget_flag not in (0, 1):
            # Stored as an INTEGER because sqlite has no boolean, but the
            # directive is a bit: a stored value that is neither 0 nor 1 is a
            # row this package did not write, and coercing it with bool()
            # would read "2" as a statement about statistical budget.
            raise EvaluatorStoreError(
                f"the stored grid for node {node_id!r} under {ref.reference} "
                f"carries charges_budget={budget_flag!r}, which is not the "
                "0-or-1 §7.2's directive is stored as"
            )
        return PostCostReturns(
            node_id=node_id,
            snapshot_name=snapshot_name,
            rebalance_dates=grid,
            cost_model=ref,
            series=cost_series_from_rows(rows, ref, snapshot_name),
            charges_budget=bool(budget_flag),
        )

    # -- Connection ---------------------------------------------------------

    def _resolve_path(self) -> Optional[Path]:
        """Resolve the sqlite path once, refusing schemes this store cannot read.

        Deferred out of ``__init__`` so construction performs no I/O.  An
        in-memory URL resolves to ``None``, which :meth:`_connect` reads as
        "use ``:memory:``" — per-connection, which is why the schema is
        created on every connect rather than cached.
        """
        if self._resolved:
            return self._path
        self._path = _sqlite_path(self._database_url)
        self._resolved = True
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store and ensure its schema exists.

        Idempotent on every connect, so a fresh database and an existing one
        take the same path.  The caller owns the connection.
        """
        self._resolve_path()
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
        else:
            connection = sqlite3.connect(":memory:")
        with connection:
            connection.executescript(_SCHEMA)
        return connection


def _parse_day(value: Any) -> Any:
    """One ISO date string from a stored grid, as a calendar date."""
    import datetime as dt

    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise EvaluatorStoreError(
            f"the stored grid carries {value!r}, which is not an ISO 8601 "
            "calendar date; grids are written as ISO date strings"
        ) from exc


# -- The module-level spellings the pipeline calls -----------------------------


def persist_signal_returns(
    returns: PostCostReturns,
    database_url: Optional[str] = None,
) -> PostCostReturns:
    """Persist step 7's result; return the record that was written.

    Feature 79's two verbs, joined: :func:`evaluator.apply_costs` produces the
    post-cost series and this writes them down.  ``database_url`` falls back to
    ``DATABASE_URL``, and a missing store is refused by name rather than
    silently skipped — feature 79 says "persisting", so a series that never
    landed is the gap it exists to close.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to persist "
            "the post-cost signal returns into (app_spec.xml feature 79); set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return PostCostStore(url.strip()).persist(returns)


def load_signal_returns(
    node_id: str,
    cost_model: Union[CostModelRef, object],
    database_url: Optional[str] = None,
) -> Optional[PostCostReturns]:
    """Read one evaluation's post-cost series back, or ``None``.

    The functional spelling of :meth:`PostCostStore.load`, for a caller that
    has no store object and only a node and a cost model: the store is
    resolved from ``DATABASE_URL``, and a missing one is refused by name
    rather than answered with a ``None`` that would read as "never costed".
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to read the "
            f"post-cost signal returns for node {node_id!r} from; set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return PostCostStore(url.strip()).load(node_id, cost_model)
