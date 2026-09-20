"""Persisting the marginal information ratio — feature 83's other half.

app_spec.xml feature 83: *"System computes ir_marginal by orthogonalizing the
candidate against the current book, which returns the incremental information
ratio."*  The computation lives in :mod:`evaluator._marginal`; this module
writes it down.  The split is the one this package already uses five times —
``_identity`` computes and ``_store`` persists for feature 70, ``_costs`` and
``_cost_store`` for 79, ``_capacity`` and ``_capacity_store`` for 82,
``_decay`` and ``_decay_store`` for 81, ``_metrics`` and ``_metrics_store`` for
80 — and for the same reason: a caller that had to wire the two together at
every call site would eventually wire them together differently at one of them.

**What "the node record" is, and why this store does not write it.**  §9.1's
``node`` table is the tree store's own — it carries the node's identity,
provenance triple, code hash, agent fields and the ``ir_marginal`` column
feature 101 adds — and the tree store is written by the tree member (feature
85), not by the evaluator: the evaluator owns the *metric*, the tree member
owns the *table*, and the two meet at one boundary.  This module does not write
the ``node`` table: it owns the *evaluator's* half of the feature — computing
the incremental information ratio and getting it somewhere durable and
checkable — and it stores it in the workspace's relational store, addressed by
``DATABASE_URL``, the same stance feature 79's cost store, feature 81's decay
store, feature 82's capacity store and feature 80's metrics store take and
argue.  The caller holding a node and the tree store is what later writes the
``ir_marginal`` column, reading this store through :meth:`NodeMarginalIRStore.load`,
so the node row and the row this store writes cannot disagree about what was
measured, and the two writers of one evaluation's marginal IR share one source.

**The grain: one row per evaluation per cost model.**  The marginal IR is one
value per evaluation — measured over one pinned horizon (:data:`MARGINAL_IR`'s
shortest the priced panel covers) — so the table is keyed ``(node_id, venue,
version)``, the same key the signal-returns grid, the capacity table, the decay
table and the node-metrics table carry, and for the same reason: two fee
schedules net different post-cost returns out of the same gross ones, so the
marginal IR measured under one is not a partial answer to a question about the
other, and §15 treats a changed cost model as its own failure case rather than
as noise.  There is no second table: the marginal IR is one object, and
splitting it across tables would create a half-written state a reader would
have to refuse rather than a check it could perform — the scalar and the
per-date returns it reduces from travel on one row, in one transaction, and the
single row is either wholly consistent with itself or refused.

**Assign-once in effect, though the write is an upsert**, on the same terms the
signal-returns, capacity, decay and metrics stores state: the primary key names
the evaluation and the cost model, so a re-measurement over the same bundle
refreshes the stored marginal IR rather than adding a second row — and a
duplicate row would read to the live loop as a second observation of the same
signal.  The upsert rewrites the measured values and nothing that *names* the
row, so it cannot re-key a stored marginal IR into a different one.  A *changed*
number under an existing key is not refused: the key names the inputs, so a
changed number is a producer that re-measured, and the last write wins.  What is
refused is a row that cannot be *believed* — a book_ir that is not the
information ratio of its own stored returns, or a marginal IR that is not the
difference of its own two ratios, or a series that does not reconstruct.

**Schema.**  Floats round-trip exactly (JSON numbers are Python reprs; SQLite
TEXT is exact), so the read path's comparisons are exact rather than tolerant,
which is what lets the ratio-versus-returns check be an equality rather than a
tolerance.  The per-date book, combined and candidate returns are stored in full
rather than summarised, because the marginal IR is a difference of two ratios
and each ratio is a function of a per-date series: a ratio alone cannot be
re-read as the series it was measured over, and the stored row could not be
checked against itself without them.  The schema is created idempotently on
connect — ``CREATE TABLE IF NOT EXISTS``, the contract every store in this
package states — so a fresh database and an existing one take one path and no
migration step is needed for this member.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import unquote, urlparse

from ._costs import CostModelRef, cost_model_ref
from ._errors import EvaluatorMarginalError, EvaluatorStoreError
from ._marginal import MarginalIR

__all__ = [
    "DATABASE_URL_ENV",
    "NODE_MARGINAL_IR_TABLE",
    "NodeMarginalIRStore",
    "load_marginal_ir",
    "persist_marginal_ir",
]

#: The environment variable naming the relational store — the one spelling the
#: identity, cost, decay, capacity and metrics stores already use, restated here
#: so each store states its own contract (and so no store imports another's).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the marginal IR lives in — one row per evaluation per cost model,
#: carrying the scalar beside the per-date returns it reduces from.  Named for
#: §9.1's ``node`` record, which the tree member writes from this row.
NODE_MARGINAL_IR_TABLE = "node_marginal_ir"

_SCHEMA = f"""
-- Feature 83: the marginal information ratio, one row per evaluation per cost
-- model.
--
-- The grain is per-evaluation because the marginal IR is one value: the
-- incremental information ratio of the candidate against the current book,
-- IR(book + candidate) minus IR(book), measured over one pinned horizon (the
-- shortest the priced panel covers).  `(node_id, venue, version)` is the key — the key the
-- signal-returns grid, the capacity table, the decay table and the node-metrics
-- table already carry, for the same reason: two fee schedules net different
-- post-cost returns out of the same gross ones, and the marginal IR is measured
-- against those net returns, so the cost model is in the identity of the metric
-- rather than beside it.
--
-- The per-date book, combined and candidate returns are stored in full rather
-- than summarised, because the marginal IR is a difference of two ratios and
-- each ratio is a function of a per-date series: a ratio alone cannot be
-- re-read as the series it was measured over, and the stored row could not be
-- checked against itself without them.  The read path rebuilds the record from
-- the three series and refuses a row whose stored ratios are not their answer —
-- the tamper defence the signal-returns reader applies to `gross − charge`, the
-- capacity reader to a capacity that does not solve from its own terms, and the
-- node-metrics reader to an ic_mean that is not its own series' mean.
-- Each `_returns` maps each ISO date to its equal-weight per-date return.
CREATE TABLE IF NOT EXISTS {NODE_MARGINAL_IR_TABLE} (
    node_id         TEXT NOT NULL,  -- the evaluation this marginal IR measures
    venue           TEXT NOT NULL,  -- feature 59's cost model pair
    version         TEXT NOT NULL,
    snapshot_name   TEXT NOT NULL,  -- provenance: which sealed world
    horizon         INT  NOT NULL,  -- the shortest horizon the priced panel covers
    dates           INT  NOT NULL,  -- the denominator behind every ratio here
    book_size       INT  NOT NULL,  -- how many signals the current book held
    book_ir         REAL NOT NULL,  -- IR(book): the equal-weight book's information ratio
    combined_ir     REAL NOT NULL,  -- IR(book + candidate): book plus candidate
    candidate_ir    REAL NOT NULL,  -- the candidate's standalone information ratio
    ir_marginal     REAL NOT NULL,  -- combined_ir − book_ir: the candidate's increment
    book_returns    TEXT NOT NULL,  -- JSON map of ISO date to equal-weight book return
    combined_returns TEXT NOT NULL, -- JSON map of ISO date to book-plus-candidate return
    candidate_returns TEXT NOT NULL,-- JSON map of ISO date to candidate return
    PRIMARY KEY (node_id, venue, version)
);
"""


# -- The JSON spellings ---------------------------------------------------------


def _series_to_json(returns: Mapping[dt.date, float]) -> str:
    """One per-date return series as a JSON object, keyed by ISO date.

    The series whose information ratio is one of the two ratios the marginal IR
    is defined between.  Floats serialize as their repr, which round-trips
    exactly, so the read path's re-derivation is a bitwise comparison rather
    than a tolerant one.
    """
    return json.dumps({day.isoformat(): returns[day] for day in sorted(returns)})


def _decode_series(payload: Any, *, node_id: str) -> dict[dt.date, float]:
    """One stored per-date return series, back as the dates it came from.

    Every key must be an ISO date and every value a finite number; the series is
    then handed to :class:`MarginalIR`, which re-derives each information ratio
    from the three series and refuses a record that is not its own terms' answer
    — so this decode captures, and the record's construction *is* the tamper
    check.
    """
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"the stored marginal IR for node {node_id!r} carries a return "
            f"series that is not valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict) or not decoded:
        raise EvaluatorStoreError(
            f"the stored marginal IR for node {node_id!r} carries a return "
            "series that is not a non-empty object keyed by ISO date; rows are "
            "written with the series in full, so these did not come out of this "
            "store's writer"
        )
    series: dict[dt.date, float] = {}
    for key, value in decoded.items():
        try:
            day = dt.date.fromisoformat(key)
        except (TypeError, ValueError) as exc:
            raise EvaluatorStoreError(
                f"the stored marginal IR for node {node_id!r} carries {key!r} "
                "in a return series, which is not an ISO 8601 calendar date; "
                "series are written as ISO date strings"
            ) from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluatorStoreError(
                f"the stored marginal IR for node {node_id!r} on {key!r} "
                f"carries {value!r}, which is not a number; a stored per-date "
                "return is a finite number"
            )
        if not math.isfinite(float(value)):
            raise EvaluatorStoreError(
                f"the stored marginal IR for node {node_id!r} on {key!r} "
                f"carries {value!r}, which is not finite; a stored per-date "
                "return is a finite number"
            )
        series[day] = float(value)
    return series


def _sqlite_path(database_url: str) -> Optional[Path]:
    """Translate a ``sqlite:///`` URL into a path (``None`` for in-memory).

    The same convention the identity, cost, decay, capacity and metrics stores
    document: ``sqlite:///foo.db`` is relative, an absolute path carries its
    leading slash after the triple, and any other scheme is refused loudly
    rather than silently mis-parsed.
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


# -- The store -------------------------------------------------------------------


class NodeMarginalIRStore:
    """Reads and writes the ``node_marginal_ir`` table for one database.

    Bound to a database URL at construction; construction performs no I/O (the
    path is resolved and the schema created on first use), so composing an
    application that carries this store touches no disk — the stance every store
    in this workspace takes.  Like the identity, cost, decay, capacity and
    metrics stores and unlike the snapshot member's manifest store, it refuses
    rather than degrading when no store is configured: feature 83 says
    "computes ... which returns the incremental information ratio", and the
    marginal IR is what the node record and the live loop read back.
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
    def resolve(cls, env: Optional[Mapping[str, str]] = None) -> "NodeMarginalIRStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the way the shared
        fixtures treat an empty ``TEST_DATABASE_URL``.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no store to "
                "persist the marginal IR into (app_spec.xml feature 83); set "
                f"{DATABASE_URL_ENV} to the system's database"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The row ------------------------------------------------------------

    def persist(self, marginal_ir: MarginalIR) -> MarginalIR:
        """Write one evaluation's marginal IR; return the record that was written.

        The scalar is written beside the three per-date return series it reduces
        from, in one row and one transaction, so a reader never sees a ratio
        whose terms are missing.  One upsert on the evaluation's key, so a
        re-measurement over the same bundle refreshes the stored marginal IR
        rather than adding a second row — a duplicate would read to the live loop
        as a second observation of the same signal.

        The upsert refreshes the measured values and nothing that *names* the
        row, so a re-measurement cannot re-key a stored marginal IR.  A store
        that cannot be reached, an unsupported URL scheme, a locked or unwritable
        database — every one surfaces as :class:`~evaluator.EvaluatorStoreError`,
        deliberately not swallowed: a marginal IR that was measured and never
        landed is the state feature 83's "computes ... which returns" exists to
        rule out.
        """
        if not isinstance(marginal_ir, MarginalIR):
            raise EvaluatorMarginalError(
                "persist_marginal_ir writes step 9's own result — a "
                f"MarginalIR — got {type(marginal_ir).__name__}; the incremental "
                "information ratio it stores carries the cost model the returns "
                "were priced under, and anything else has none"
            )
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {NODE_MARGINAL_IR_TABLE} (
                        node_id, venue, version, snapshot_name, horizon, dates,
                        book_size, book_ir, combined_ir, candidate_ir,
                        ir_marginal, book_returns, combined_returns,
                        candidate_returns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id, venue, version) DO UPDATE SET
                        snapshot_name   = excluded.snapshot_name,
                        horizon         = excluded.horizon,
                        dates           = excluded.dates,
                        book_size       = excluded.book_size,
                        book_ir         = excluded.book_ir,
                        combined_ir     = excluded.combined_ir,
                        candidate_ir    = excluded.candidate_ir,
                        ir_marginal     = excluded.ir_marginal,
                        book_returns    = excluded.book_returns,
                        combined_returns = excluded.combined_returns,
                        candidate_returns = excluded.candidate_returns
                    """,
                    (
                        marginal_ir.node_id,
                        marginal_ir.cost_model.venue,
                        marginal_ir.cost_model.version,
                        marginal_ir.snapshot_name,
                        marginal_ir.horizon,
                        marginal_ir.dates,
                        marginal_ir.book_size,
                        marginal_ir.book_ir,
                        marginal_ir.combined_ir,
                        marginal_ir.candidate_ir,
                        marginal_ir.ir_marginal,
                        _series_to_json(marginal_ir.book_returns),
                        _series_to_json(marginal_ir.combined_returns),
                        _series_to_json(marginal_ir.candidate_returns),
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not persist the marginal IR for node "
                f"{marginal_ir.node_id!r}: {exc}"
            ) from exc
        return marginal_ir

    def load(
        self,
        node_id: str,
        cost_model: Union[CostModelRef, object],
    ) -> Optional[MarginalIR]:
        """Read one evaluation's marginal IR back, or ``None``.

        The reader the tree member's node-row writer (feature 85) resolves
        against: given the node and the cost model a score names, answer with
        the marginal IR that was stored — or ``None``, the honest answer for an
        evaluation this store never measured, on the same stance the identity,
        cost, decay, capacity and metrics stores' readers take.

        The ``(venue, version)`` the caller names is *part of the question*,
        not a filter over it: a marginal IR measured under one fee schedule is
        not a partial answer to a question about another.

        What comes back is *checked*, not trusted: the three stored series are
        decoded and the record is rebuilt from them, and :class:`MarginalIR`
        re-derives each information ratio from those series and refuses a record
        that is not its own terms' answer — so a row whose scalars were edited
        while its series were left alone is refused here rather than handed back
        as a plausible-looking set of numbers.
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorStoreError(
                "a node id must be a non-empty string to read the marginal IR "
                f"by, got {node_id!r}"
            )
        ref = cost_model_ref(cost_model)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT snapshot_name, horizon, dates, book_size, book_ir,
                           combined_ir, candidate_ir, ir_marginal, book_returns,
                           combined_returns, candidate_returns
                    FROM {NODE_MARGINAL_IR_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not read the marginal IR for node {node_id!r} under "
                f"{ref.reference}: {exc}"
            ) from exc
        if row is None:
            return None
        (
            snapshot_name,
            horizon,
            dates,
            book_size,
            book_ir,
            combined_ir,
            candidate_ir,
            ir_marginal,
            book_returns_json,
            combined_returns_json,
            candidate_returns_json,
        ) = row
        book_returns = _decode_series(book_returns_json, node_id=node_id)
        combined_returns = _decode_series(combined_returns_json, node_id=node_id)
        candidate_returns = _decode_series(candidate_returns_json, node_id=node_id)
        try:
            marginal_ir = MarginalIR(
                node_id=node_id,
                snapshot_name=snapshot_name,
                cost_model=ref,
                horizon=horizon,
                dates=dates,
                book_size=book_size,
                book_ir=book_ir,
                combined_ir=combined_ir,
                candidate_ir=candidate_ir,
                ir_marginal=ir_marginal,
                book_returns=book_returns,
                combined_returns=combined_returns,
                candidate_returns=candidate_returns,
            )
        except EvaluatorMarginalError as exc:
            raise EvaluatorStoreError(
                f"the stored marginal IR row for node {node_id!r} under "
                f"{ref.reference} does not reconstruct: {exc}; the row was "
                "written or edited outside this package, and a ratio that is "
                "not its own series' answer is a number the node record would "
                "trust and be wrong by"
            ) from exc
        return marginal_ir

    # -- Connection ---------------------------------------------------------

    def _resolve_path(self) -> Optional[Path]:
        """Resolve the sqlite path once, refusing schemes this store cannot read.

        Deferred out of ``__init__`` so construction performs no I/O.  An
        in-memory URL resolves to ``None``, which :meth:`_connect` reads as
        "use ``:memory:``" — per-connection, which is why the schema is created
        on every connect rather than cached.
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


# -- The module-level spellings the pipeline calls -----------------------------


def persist_marginal_ir(
    marginal_ir: MarginalIR,
    database_url: Optional[str] = None,
) -> MarginalIR:
    """Persist step 9's marginal IR; return the record that was written.

    Feature 83's two verbs, joined: :func:`evaluator.compute_marginal_ir`
    computes the incremental information ratio and this writes it down.
    ``database_url`` falls back to ``DATABASE_URL``, and a missing store is
    refused by name rather than silently skipped — feature 83 says "computes ...
    which returns the incremental information ratio", so a marginal IR that
    never landed is the gap it exists to close.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to persist "
            "the marginal IR into (app_spec.xml feature 83); set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return NodeMarginalIRStore(url.strip()).persist(marginal_ir)


def load_marginal_ir(
    node_id: str,
    cost_model: Union[CostModelRef, object],
    database_url: Optional[str] = None,
) -> Optional[MarginalIR]:
    """Read one evaluation's marginal IR back, or ``None``.

    The functional spelling of :meth:`NodeMarginalIRStore.load`, for a caller
    that has no store object and only a node and a cost model: the store is
    resolved from ``DATABASE_URL``, and a missing one is refused by name rather
    than answered with a ``None`` that would read as "never measured".
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to read the "
            f"marginal IR for node {node_id!r} from; set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return NodeMarginalIRStore(url.strip()).load(node_id, cost_model)
