"""Persisting the capacity estimate and the regime attribution — feature 82's other half.

app_spec.xml feature 82: *"System computes a capacity estimate plus regime
attribution, **persisting both into the node artifact directory**."*  The
computation lives in :mod:`evaluator._capacity`; this module writes it
down.  The split is the one this package already uses twice — ``_identity``
computes and ``_store`` persists for feature 70, ``_costs`` and
``_cost_store`` for feature 79 — and for the same reason: a caller that had
to wire the two together at every call site would eventually wire them
together differently at one of them.

**Where "the node artifact directory" is, and who writes the file.**  §9.2
lays the directory out per node:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      regime_attribution.json

and the artifacts member owns that directory (feature 169) and its JSON
files (feature 172) — exactly as it owns ``signal_returns.parquet``
(feature 170).  This module does not write the file: it owns the
*evaluator's* half of the feature — computing the two values and getting
them somewhere durable — and it stores them in the workspace's relational
store, addressed by ``DATABASE_URL``, the same stance feature 79's cost
store takes and argues.  The caller holding a campaign and a node artifact
directory is what later writes ``regime_attribution.json``, reading this
store through :meth:`CapacityStore.load`; that way the artifact and the
row cannot disagree about what was computed, and the two writers of one
evaluation's metrics share one source.

**Both halves persist together, in one transaction.**  The feature's
sentence carries one verb for the pair — *persisting both* — and the pair
is one artifact's content, so the two tables are written in a single
transaction and the reader refuses either half alone.  A capacity row whose
attribution rows are missing is not "an evaluation with capacity but no
regimes": it is a row set that did not come out of this store's writer,
and rebuilding the missing half from anything would invent the split the
feature asks to be *measured*.  The pair must also agree on whose
evaluation it is — one node, one sealed snapshot, one cost model — because
a capacity sized from one bundle's returns and an attribution split from
another's would be an artifact no evaluation ever produced.

**The grain, and what a read-back has to be.**  One row per evaluation per
cost model in ``node_capacity`` — the binding capacity, the horizon that
set it, the per-horizon terms as JSON, and the un-attributed date count —
plus one row per stratum in ``regime_attribution``.  The per-horizon terms
travel on the row because a read-back has to be lossless *and checkable*:
reconstructing :class:`~evaluator.HorizonCapacity` re-solves the closed
form from the stored edge and drag and refuses a row whose capacity is not
its own terms' answer — the same defence ``row_to_return`` applies to a
stored net that does not equal its own gross less its own charge, for the
same reason: what downstream trusts is the stored number, and a store that
could hand back a row disagreeing with itself would launder a tamper.  The
floats round-trip exactly (JSON numbers are Python reprs; SQLite REALs are
IEEE doubles), so the checks are exact, not tolerant.

**Assign-once in effect, though the write is an upsert**, on the same
terms the signal-returns store states: the primary key names the
evaluation (and the cost model, and — for the strata — the stratum), so a
re-computation over the same bundle refreshes the stored numbers rather
than adding a second row, and the upsert rewrites the measured values and
nothing that *names* the row, so it cannot re-key a stored artifact into a
different one.  A *changed* number under an existing key is not refused:
the key names the inputs, so a changed number is a producer that
re-computed, and the last write wins — the capacity record is a pure
function of its terms, and the terms are in the key.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Tuple, Union
from urllib.parse import unquote, urlparse

from ._align import HORIZONS
from ._capacity import (
    CapacityEstimate,
    HorizonCapacity,
    RegimeAttribution,
    StratumAttribution,
    StratumSlice,
)
from ._costs import CostModelRef, cost_model_ref
from ._errors import EvaluatorCapacityError, EvaluatorStoreError

__all__ = [
    "DATABASE_URL_ENV",
    "NODE_CAPACITY_TABLE",
    "REGIME_ATTRIBUTION_TABLE",
    "CapacityStore",
    "load_capacity",
    "persist_capacity",
]

#: The environment variable naming the relational store — the one spelling
#: the identity store and the cost store already use, restated here so each
#: store states its own contract (and so no store imports another's).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the capacity estimate lives in — one row per evaluation per
#: cost model, carrying the binding book and every horizon's terms.
NODE_CAPACITY_TABLE = "node_capacity"

#: The table the regime attribution lives in — one row per stratum, named
#: for §9.2's ``regime_attribution.json`` the way the signal-returns table
#: is named for its artifact.
REGIME_ATTRIBUTION_TABLE = "regime_attribution"

_SCHEMA = f"""
-- Feature 82: the capacity estimate, one row per evaluation per cost model.
--
-- The grain is per-evaluation because the estimate is per-evaluation: one
-- binding book, one horizon that set it, and the per-horizon terms the
-- book was solved from. `(node_id, venue, version)` is the key — the same
-- key the signal-returns grid carries, for the same reason: two fee
-- schedules net different post-cost edges out of the same gross returns,
-- so the cost model is in the identity of the estimate rather than beside
-- it.
--
-- `horizon_capacities` is JSON, one entry per spec horizon: the terms
-- (`dates`, `mean_post_cost_return`, `impact_drag`, `capacity_usd`) or
-- `null` for a horizon the window was too short to measure — absence
-- carried as null, never as zero, the distinction the whole package
-- maintains. The terms are stored (not just the answer) so the read path
-- can re-solve the closed form and refuse a row that disagrees with its
-- own inputs — the tamper defence the signal-returns reader applies to
-- `gross - charge`.
--
-- `unattributed_dates` sits on this row rather than a stratum's because it
-- is one value per evaluation — the grid-row precedent: per-evaluation
-- values live on the per-evaluation row. It counts rebalance dates that
-- carried no regime label, and it is carried rather than dropped so a
-- reader can tell a full-grid attribution from a half-grid one.
CREATE TABLE IF NOT EXISTS {NODE_CAPACITY_TABLE} (
    node_id            TEXT NOT NULL,   -- the evaluation this book sizes
    venue              TEXT NOT NULL,   -- feature 59's cost model pair
    version            TEXT NOT NULL,
    snapshot_name      TEXT NOT NULL,   -- provenance: which sealed world
    capacity_usd       REAL NOT NULL,   -- the binding book, in dollars
    binding_horizon    INTEGER NOT NULL,  -- the horizon that set it
    horizon_capacities TEXT NOT NULL,   -- JSON: per-horizon terms or null
    unattributed_dates INTEGER NOT NULL,  -- grid dates carrying no label
    PRIMARY KEY (node_id, venue, version)
);

-- Feature 82: the regime attribution, one row per stratum per evaluation.
--
-- The grain is the stratum — the artifact is a dict keyed by stratum name,
-- and a stratum is a name the labels spell (feature 283's names), not a
-- row this schema enumerates: the day the stratum set changes is a
-- configuration change in the labeler, not a schema change here (the
-- argument migration 0107 makes for the coverage table).
--
-- `observations` is JSON, one entry per measured horizon: the labeled-date
-- count and the equal-weight mean post-cost return over exactly those
-- dates. A horizon the stratum was not measured at is absent from the
-- object — absence, not zero — and a stratum measured at no horizon at
-- all is carried with an empty object, the "write the zero" discipline
-- §C7's ledger applies: named-but-unmeasured is a fact, distinct from
-- unnamed.
CREATE TABLE IF NOT EXISTS {REGIME_ATTRIBUTION_TABLE} (
    node_id       TEXT NOT NULL,
    venue         TEXT NOT NULL,
    version       TEXT NOT NULL,
    stratum       TEXT NOT NULL,   -- the name the labels spell
    snapshot_name TEXT NOT NULL,   -- provenance, agreeing with the row above
    observations  TEXT NOT NULL,   -- JSON: {{horizon: {{dates, mean}}}}
    PRIMARY KEY (node_id, venue, version, stratum)
);
"""


# -- The JSON spellings ---------------------------------------------------------


def _horizons_to_json(horizons: Mapping[int, Optional[HorizonCapacity]]) -> str:
    """The per-horizon terms as one JSON object.

    Keys are the horizon as a string (JSON object keys are strings), values
    carry the four terms or ``null`` for an un-measured horizon.  Floats
    serialize as their repr, which round-trips exactly, so the read path's
    re-solve is a bitwise comparison rather than a tolerant one.
    """
    return json.dumps(
        {
            str(horizon): (
                None
                if capacity is None
                else {
                    "dates": capacity.dates,
                    "mean_post_cost_return": capacity.mean_post_cost_return,
                    "impact_drag": capacity.impact_drag,
                    "capacity_usd": capacity.capacity_usd,
                }
            )
            for horizon, capacity in sorted(horizons.items())
        }
    )


def _slices_to_json(slices: Mapping[int, StratumSlice]) -> str:
    """One stratum's slices as one JSON object — its own denominators included."""
    return json.dumps(
        {
            str(horizon): {
                "dates": slice_.dates,
                "mean_post_cost_return": slice_.mean_post_cost_return,
            }
            for horizon, slice_ in sorted(slices.items())
        }
    )


def _decode_horizons(payload: Any, *, node_id: str) -> dict[int, Optional[HorizonCapacity]]:
    """The stored per-horizon terms, back as the records they came from.

    Every horizon the spec names must be present — the writer spells all
    five — and each present value must reconstruct: :class:`HorizonCapacity`
    re-solves the closed form from the stored terms and refuses a capacity
    that is not its own terms' answer, so this decode *is* the tamper
    check, not a step before one.
    """
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"the stored horizon capacities for node {node_id!r} are not "
            f"valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict) or set(decoded) != {
        str(horizon) for horizon in HORIZONS
    }:
        raise EvaluatorStoreError(
            f"the stored horizon capacities for node {node_id!r} do not "
            "carry exactly one entry per horizon the spec names; rows are "
            "written with all five, so these did not come out of this "
            "store's writer"
        )
    terms: dict[int, Optional[HorizonCapacity]] = {}
    for horizon in HORIZONS:
        entry = decoded[str(horizon)]
        if entry is None:
            terms[horizon] = None
            continue
        try:
            terms[horizon] = HorizonCapacity(
                horizon=horizon,
                dates=entry["dates"],
                mean_post_cost_return=entry["mean_post_cost_return"],
                impact_drag=entry["impact_drag"],
                capacity_usd=entry["capacity_usd"],
            )
        except (KeyError, TypeError, EvaluatorCapacityError) as exc:
            raise EvaluatorStoreError(
                f"a stored horizon capacity for node {node_id!r} does not "
                f"reconstruct: {exc}; the row was written or edited "
                "outside this package, and a capacity that does not solve "
                "from its own terms is a number the artifact would trust "
                "and be wrong by"
            ) from exc
    return terms


def _decode_observations(
    payload: Any, *, node_id: str, stratum: str
) -> dict[int, StratumSlice]:
    """One stratum's stored observations, back as the slices they came from."""
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"the stored observations for stratum {stratum!r} of node "
            f"{node_id!r} are not valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise EvaluatorStoreError(
            f"the stored observations for stratum {stratum!r} of node "
            f"{node_id!r} are not an object keyed by horizon; rows are "
            "written as one, so these did not come out of this store's "
            "writer"
        )
    slices: dict[int, StratumSlice] = {}
    for key, entry in decoded.items():
        try:
            horizon = int(key)
            slices[horizon] = StratumSlice(
                horizon=horizon,
                dates=entry["dates"],
                mean_post_cost_return=entry["mean_post_cost_return"],
            )
        except (KeyError, TypeError, ValueError, EvaluatorCapacityError) as exc:
            raise EvaluatorStoreError(
                f"a stored observation for stratum {stratum!r} of node "
                f"{node_id!r} does not reconstruct: {exc}; the row was "
                "written or edited outside this package"
            ) from exc
    return slices


def _sqlite_path(database_url: str) -> Optional[Path]:
    """Translate a ``sqlite:///`` URL into a path (``None`` for in-memory).

    The same convention the identity store and the cost store document:
    ``sqlite:///foo.db`` is relative, an absolute path carries its leading
    slash after the triple, and any other scheme is refused loudly rather
    than silently mis-parsed.
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


class CapacityStore:
    """Reads and writes the capacity and attribution tables for one database.

    Bound to a database URL at construction; construction performs no I/O
    (the path is resolved and the schema created on first use), so
    composing an application that carries this store touches no disk — the
    stance every store in this workspace takes.  Unlike the snapshot
    member's manifest store and like the identity and cost stores, it
    refuses rather than degrading when no store is configured: feature 82's
    text is "persisting", and §9.2's artifact is what replay reads back.
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
    ) -> "CapacityStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the way the
        shared fixtures treat an empty ``TEST_DATABASE_URL``.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no store to "
                "persist the capacity estimate and regime attribution "
                f"into (app_spec.xml feature 82); set {DATABASE_URL_ENV} "
                "to the system's database"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The rows -----------------------------------------------------------

    def persist(
        self, estimate: CapacityEstimate, attribution: RegimeAttribution
    ) -> Tuple[CapacityEstimate, RegimeAttribution]:
        """Write one evaluation's two halves; return the pair that was written.

        The pair is checked for agreement *before* any I/O: one node, one
        sealed snapshot, one cost model — a capacity sized from one
        bundle's returns and an attribution split from another's would be
        an artifact no evaluation ever produced, and the write is the last
        place that can be caught.  Both tables are then written in one
        transaction, so a reader never sees either half alone.

        The upsert refreshes the measured values and nothing that *names*
        the rows, so a re-computation over the same bundle cannot re-key a
        stored artifact into a different one.  A store that cannot be
        reached, an unsupported URL scheme, a locked or unwritable database
        — every one surfaces as :class:`~evaluator.EvaluatorStoreError`,
        deliberately not swallowed: values that were computed and never
        landed are the state feature 82's "persisting" exists to rule out.
        """
        _check_pair_agreement(estimate, attribution)
        strata_rows = [
            (
                estimate.node_id,
                estimate.cost_model.venue,
                estimate.cost_model.version,
                name,
                estimate.snapshot_name,
                _slices_to_json(attribution.strata[name].slices),
            )
            for name in attribution.named_strata
        ]
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {NODE_CAPACITY_TABLE} (
                        node_id, venue, version, snapshot_name, capacity_usd,
                        binding_horizon, horizon_capacities, unattributed_dates
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id, venue, version) DO UPDATE SET
                        snapshot_name      = excluded.snapshot_name,
                        capacity_usd       = excluded.capacity_usd,
                        binding_horizon    = excluded.binding_horizon,
                        horizon_capacities = excluded.horizon_capacities,
                        unattributed_dates = excluded.unattributed_dates
                    """,
                    (
                        estimate.node_id,
                        estimate.cost_model.venue,
                        estimate.cost_model.version,
                        estimate.snapshot_name,
                        estimate.capacity_usd,
                        estimate.binding_horizon,
                        _horizons_to_json(estimate.horizons),
                        attribution.unattributed_dates,
                    ),
                )
                connection.executemany(
                    f"""
                    INSERT INTO {REGIME_ATTRIBUTION_TABLE} (
                        node_id, venue, version, stratum, snapshot_name,
                        observations
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id, venue, version, stratum) DO UPDATE SET
                        snapshot_name = excluded.snapshot_name,
                        observations  = excluded.observations
                    """,
                    strata_rows,
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not persist the capacity estimate and regime "
                f"attribution for node {estimate.node_id!r}: {exc}"
            ) from exc
        return estimate, attribution

    def load(
        self,
        node_id: str,
        cost_model: Union[CostModelRef, object],
    ) -> Optional[Tuple[CapacityEstimate, RegimeAttribution]]:
        """Read one evaluation's two halves back, or ``None``.

        The reader the artifacts member's ``regime_attribution.json`` writer
        (feature 172) resolves against: given the node and the cost model a
        score names, answer with the pair that was stored — or ``None``,
        the honest answer for an evaluation this store never sized, on the
        same stance the identity and cost stores' readers take.

        The ``(venue, version)`` the caller names is part of the question,
        not a filter over it: an estimate priced under one fee schedule is
        not a partial answer to a question about another.  And what comes
        back is *checked*, not trusted: the per-horizon terms re-solve the
        closed form, the estimate re-derives its own minimum, and a
        capacity row without its attribution rows — or the reverse — is
        refused as a half-written state this store's single transaction
        cannot produce.
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorStoreError(
                "a node id must be a non-empty string to read a capacity "
                f"estimate by, got {node_id!r}"
            )
        ref = cost_model_ref(cost_model)
        try:
            with closing(self._connect()) as connection:
                capacity_row = connection.execute(
                    f"""
                    SELECT snapshot_name, capacity_usd, binding_horizon,
                           horizon_capacities, unattributed_dates
                    FROM {NODE_CAPACITY_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchone()
                strata_rows = connection.execute(
                    f"""
                    SELECT stratum, snapshot_name, observations
                    FROM {REGIME_ATTRIBUTION_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    ORDER BY stratum
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not read the capacity estimate for node "
                f"{node_id!r} under {ref.reference}: {exc}"
            ) from exc
        if capacity_row is None and not strata_rows:
            return None
        if capacity_row is None:
            # Attribution rows without the capacity row: the two are
            # written in one transaction, so this is a row set edited
            # outside this package — and inventing the missing half would
            # be writing an artifact nobody computed.
            raise EvaluatorStoreError(
                f"the store holds regime attribution rows for node "
                f"{node_id!r} under {ref.reference} but no capacity row; "
                "the two halves are written together, so these rows did "
                "not come out of this store's writer"
            )
        if not strata_rows:
            raise EvaluatorStoreError(
                f"the store holds a capacity row for node {node_id!r} "
                f"under {ref.reference} but no attribution rows; an "
                "evaluation attributed to no stratum was never computed "
                "here — the pair is one artifact's content and is refused "
                "as a half"
            )
        snapshot_name, capacity_usd, binding_horizon, horizon_json, unattributed = (
            capacity_row
        )
        horizons = _decode_horizons(horizon_json, node_id=node_id)
        try:
            estimate = CapacityEstimate(
                node_id=node_id,
                snapshot_name=snapshot_name,
                cost_model=ref,
                capacity_usd=capacity_usd,
                binding_horizon=binding_horizon,
                horizons=horizons,
            )
        except EvaluatorCapacityError as exc:
            raise EvaluatorStoreError(
                f"the stored capacity row for node {node_id!r} under "
                f"{ref.reference} does not reconstruct: {exc}; the row was "
                "written or edited outside this package, and a capacity "
                "that is not the minimum of its own horizons is a number "
                "the artifact would trust and be wrong by"
            ) from exc
        strata: dict[str, StratumAttribution] = {}
        for stratum, stratum_snapshot, observations in strata_rows:
            if stratum_snapshot != snapshot_name:
                raise EvaluatorStoreError(
                    f"the stored attribution for stratum {stratum!r} of "
                    f"node {node_id!r} names snapshot "
                    f"{stratum_snapshot!r} but the capacity row names "
                    f"{snapshot_name!r}; one evaluation reads one sealed "
                    "world, so these rows did not come out of one write"
                )
            strata[stratum] = StratumAttribution(
                stratum=stratum,
                slices=_decode_observations(
                    observations, node_id=node_id, stratum=stratum
                ),
            )
        try:
            attribution = RegimeAttribution(
                node_id=node_id,
                snapshot_name=snapshot_name,
                cost_model=ref,
                strata=strata,
                unattributed_dates=unattributed,
            )
        except EvaluatorCapacityError as exc:
            raise EvaluatorStoreError(
                f"the stored attribution rows for node {node_id!r} under "
                f"{ref.reference} do not reconstruct: {exc}; the rows were "
                "written or edited outside this package"
            ) from exc
        return estimate, attribution

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

        Idempotent on every connect, so a fresh database and an existing
        one take the same path.  The caller owns the connection.
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


def _check_pair_agreement(
    estimate: CapacityEstimate, attribution: RegimeAttribution
) -> None:
    """Refuse a pair computed over two different evaluations.

    The feature persists *both* values as one artifact's content, so the
    pair must be one evaluation's: same node, same sealed snapshot, same
    cost model.  The write is the last place the agreement can be checked —
    once the rows land, a reader has no way to tell a mismatched pair from
    a computed one.
    """
    if not isinstance(estimate, CapacityEstimate):
        raise EvaluatorCapacityError(
            "persist_capacity writes step 8's own result — a "
            f"CapacityEstimate — got {type(estimate).__name__}"
        )
    if not isinstance(attribution, RegimeAttribution):
        raise EvaluatorCapacityError(
            "persist_capacity writes step 8's own result — a "
            f"RegimeAttribution — got {type(attribution).__name__}"
        )
    for field, left, right in (
        ("node", estimate.node_id, attribution.node_id),
        ("sealed snapshot", estimate.snapshot_name, attribution.snapshot_name),
    ):
        if left != right:
            raise EvaluatorCapacityError(
                f"the capacity estimate names {field} {left!r} but the "
                f"regime attribution names {right!r}; the two persist "
                "together as one artifact's content, and a pair computed "
                "over two different evaluations is an artifact no "
                "evaluation ever produced"
            )
    if estimate.cost_model != attribution.cost_model:
        raise EvaluatorCapacityError(
            f"the capacity estimate was priced under "
            f"{estimate.cost_model.reference} but the regime attribution "
            f"under {attribution.cost_model.reference}; the two persist "
            "together, and one evaluation prices one fee schedule"
        )


# -- The module-level spellings the pipeline calls -----------------------------


def persist_capacity(
    estimate: CapacityEstimate,
    attribution: RegimeAttribution,
    database_url: Optional[str] = None,
) -> Tuple[CapacityEstimate, RegimeAttribution]:
    """Persist step 8's two results; return the pair that was written.

    Feature 82's two verbs, joined: :func:`evaluator.estimate_capacity` and
    :func:`evaluator.attribute_regimes` produce the pair and this writes
    both down, in one transaction, after checking the pair agrees on whose
    evaluation it is.  ``database_url`` falls back to ``DATABASE_URL``, and
    a missing store is refused by name rather than silently skipped —
    feature 82 says "persisting", so values that never landed are the gap
    it exists to close.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to "
            "persist the capacity estimate and regime attribution into "
            "(app_spec.xml feature 82); set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return CapacityStore(url.strip()).persist(estimate, attribution)


def load_capacity(
    node_id: str,
    cost_model: Union[CostModelRef, object],
    database_url: Optional[str] = None,
) -> Optional[Tuple[CapacityEstimate, RegimeAttribution]]:
    """Read one evaluation's two results back, or ``None``.

    The functional spelling of :meth:`CapacityStore.load`, for a caller
    that has no store object and only a node and a cost model: the store is
    resolved from ``DATABASE_URL``, and a missing one is refused by name
    rather than answered with a ``None`` that would read as "never sized".
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to read "
            f"the capacity estimate for node {node_id!r} from; set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return CapacityStore(url.strip()).load(node_id, cost_model)
