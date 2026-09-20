"""The final pipeline step — artifact to ART, scalars to TREE — feature 85.

app_spec.xml feature 85: *"System persists the full artifact to the artifact
store plus the scalar metrics to the tree store as the final pipeline step."*
docs/nullius-tech-architecture.md §6.1 names this as the last line of the
pipeline — ``12. persist   artifact → ART, scalars → TREE`` — and §9 lays out
the two destinations this step feeds: §9.2's artifact store (one directory per
node, holding the Parquet and JSON files replay needs) and §9.1's tree store
(the ``node`` table's scalar columns).

Steps 7–11 already produce — and have already persisted into the workspace's
relational store — everything this step writes down: step 7's
:class:`~evaluator.PostCostReturns` (feature 79), step 8's
:class:`~evaluator.NodeMetrics` / :class:`~evaluator.DecayProfile` /
:class:`~evaluator.CapacityEstimate` + :class:`~evaluator.RegimeAttribution`
(features 80, 81, 82), step 9's :class:`~evaluator.MarginalIR` (feature 83), and
step 11's debit (feature 84). Each wrote its own half into the store this member
reads back through the paired store modules — ``_cost_store``, ``_metrics_store``,
``_decay_store``, ``_capacity_store``, ``_marginal_store``.

**What feature 85 adds is the final pipeline step that ties those two halves
together into one node-scoped, one-shot, idempotent write.** It is not a new
metric and not a new store. It is the orchestration the other steps deliberately
do not do: gather the node's persisted pieces, render each into its §9.2
artifact file, and copy the scalar metrics onto the §9.1 ``node`` row — under one
contract that says the write is keyed by the node, refuses a half-written node,
and can be retried safely.

**This member owns the orchestration, and two seams it does not.** The artifact
store is written through an injected :class:`~evaluator.ArtifactWriter` — the
artifacts member owns the Parquet encoding and the on-disk path (features 170,
172); this member renders the *content* of each file from the measured records
and hands it across. The tree store is written through an injected
``TreeNodeWriter`` — the tree member owns the ``node`` table's DDL and its
non-metric columns (``code_hash``, ``agent_model_id``, ``parent_id``,
``created_at``); this member assembles the ``node`` row's metric columns from the
measured records and hands it across. Both seams are structural — satisfied by
duck typing, read back where the answer matters, their own failures propagating
unwrapped — the same way feature 73's sandbox, feature 76's oracle and feature
84's ledger are injected.

**The records are the values; the store re-reads the canonical rows from
``DATABASE_URL`` to render the artifacts.** :meth:`NodeArtifactStore.persist`
takes the node's identity plus the records steps 7–9 produced — the same objects
the pipeline already holds — checks they agree on one node and one cost model,
and then reads the canonical rows back from the evaluator's own stores
(:func:`load_signal_returns`, :func:`load_node_metrics`, :func:`load_decay_profile`,
:func:`load_capacity`, :func:`load_marginal_ir`), refusing a record the store does
not hold. That is the precedent every store module states — "the caller holding a
campaign and a node artifact directory is what later writes the file, reading this
store through ``X.load``" — and it is what keeps the artifact and the row from
disagreeing about what was computed: the artifact is rendered from what actually
persisted, not from a value the pipeline happened to hold.

**One node, one write, one transaction — and the refusal of a half.** The
artifact files and the ``node`` row are written under one call. The artifact
writer's :meth:`~evaluator.ArtifactWriter.flush` is the commit point, and the
tree write precedes it: the artifacts are written (staged), the tree node row is
written, and ``flush`` commits the directory. A failure in either half before the
commit leaves nothing half-written — on a tree failure the artifacts are never
flushed, so the writer rolls them back. The orchestration table
(:data:`NODE_PERSIST_TABLE`) records that the write happened, with one flag per
half (``tree_written``, ``artifact_written``); :meth:`load` refuses a node whose
two flags disagree — a directory without a row, or a row without a directory —
because the two halves are one artifact's content and a reader must never see one
without the other (the defence :mod:`evaluator._capacity_store` applies to a
capacity row without its attribution).

**Idempotent by ``node_id``.** Re-persisting the same node refreshes the artifact
files and the row's metric columns rather than appending a second node — the same
assign-once-in-effect the stores use, and the same idempotency §14 demands of the
workers this runs on. The ``TreeNodeWriter`` answers ``(node_id, appended)`` so a
retry is distinguishable from a first write, and the returned
:class:`NodePersistence` carries ``tree_appended`` so the caller sees whether this
call wrote the row or was answered by the prior one.

**Stdlib-only, import-cheap.** No polars/pyarrow/lake/HTTP at import; the records
arrive as values, the Parquet boundary is the injected writer's, and the replay
path §1 forbids from reaching the evaluator. The module imports the store readers
lazily inside :meth:`persist` (not at import), so importing this member costs
composition nothing and the readers it needs are the evaluator's own.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, Tuple
from urllib.parse import unquote, urlparse

from ._align import HORIZONS
from ._artifact import (
    ArtifactWriter,
    render_decay_profile,
    render_exec_trace,
    render_regime_attribution,
)
from ._costs import CostModelRef, PostCostReturns, cost_model_ref
from ._decay import DecayProfile
from ._errors import EvaluatorArtifactError
from ._metrics import NodeMetrics

__all__ = [
    "NODE_PERSIST_TABLE",
    "NodeArtifactStore",
    "NodePersistence",
    "NodeRow",
    "persist_node",
]

#: The environment variable naming the relational store — the one spelling every
#: store in this package uses, restated here so this step states its own
#: contract (and so the orchestration ledger does not import another store's).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table this step owns — one row per node, the orchestration ledger that
#: records that feature 85's one-shot write happened for a node. It is **not**
#: the tree ``node`` table (the tree member's) and **not** the artifact files
#: (the artifacts member's) — it is this step's own record that it did its job,
#: the way :data:`evaluator.IDENTITY_TABLE` is feature 70's record that the hash
#: landed. ``tree_written`` and ``artifact_written`` are one flag per half, so a
#: half-written node is discoverable and :meth:`NodeArtifactStore.load` can
#: refuse it.
NODE_PERSIST_TABLE = "node_persist"

#: The §9.2 files, in the order they are written — the artifact half's content,
#: rendered from the records and handed to the writer. ``code.py`` is written
#: only when the caller supplies the signal source.
_ARTIFACT_ORDER: Tuple[str, ...] = (
    "signal_returns.parquet",
    "ic_series.parquet",
    "turnover_series.parquet",
    "decay_profile.json",
    "regime_attribution.json",
    "exec_trace.json",
)

_MISSING: Any = object()


class TreeNodeWriter(Protocol):
    """The tree store's seam — how the ``node`` row's scalars reach the tree.

    Injected, not imported: the workspace contract keeps this member from
    reaching the tree member, so the writer is an object exposing the one method
    the tree member's node writer speaks, satisfied structurally with no adapter
    — the same way feature 85's :class:`~evaluator.ArtifactWriter` and feature
    84's ledger are injected.

    .. py:method:: write_node(node_row) -> (node_id, appended)

        Write (or refresh) one node's row in the ``node`` table. The tree member
        owns the DDL and the non-metric columns; this member hands over the
        identity and the metric columns in a :class:`NodeRow`. Answers the
        node's identity and whether *this* call appended the row — ``False`` on
        an idempotent refresh answered by the prior row, so a retry is
        distinguishable from a first write.
    """

    def write_node(self, node_row: "NodeRow") -> Tuple[str, bool]:
        """Write or refresh one node's row; answer ``(node_id, appended)``."""
        ...


@dataclass(frozen=True)
class NodeRow:
    """The ``node`` row as this member hands it to the tree seam.

    The identity columns this member measures (node, campaign, snapshot, the
    evaluator that produced it, the fee schedule that priced it) and the metric
    columns the records carry. The tree member owns the rest of the ``node``
    table — ``code_hash``, ``agent_model_id``, ``parent_id``, ``created_at`` and
    every non-metric column — and fills them in from its own side of the seam.

    ``perturb_stability`` is carried as ``None``, not defaulted: it is step 10's
    tripwire metric, and step 10 is not this step's input, so the honest value is
    "not measured by this step" rather than a zero that would read as a
    measurement. The tree member writes the absence as it sees fit.
    """

    #: The node's identity — the row's key.
    node_id: str
    #: The campaign the node belongs to — the tree member joins the node to it.
    campaign_id: str
    #: The sealed snapshot the node was measured in.
    snapshot_name: str
    #: The evaluator image's hash — feature 70's identity, stamped on the row.
    evaluator_hash: str
    #: The fee schedule that priced the node — the ``venue/version`` reference.
    cost_model: str
    #: The four node metrics — feature 80's scalars.
    ic_mean: float
    ic_tstat: float
    ir_standalone: float
    turnover: float
    #: The marginal information ratio — feature 83's scalar.
    ir_marginal: float
    #: The mean post-cost edge of the equal-weight book — the cost-adjusted axis.
    cost_adjusted_ir: float
    #: Step 10's tripwire metric — ``None`` because step 10 is not this step.
    perturb_stability: Optional[float]


@dataclass(frozen=True)
class NodePersistence:
    """The final-step write's answer — what feature 85 left for one node.

    The node's identity, the evaluator that produced it and the fee schedule that
    priced it, the records steps 7–9 measured (as read back from the store, so
    the answer is what actually persisted), the artifact files that were written,
    and the two idempotency signals: ``tree_appended`` (whether *this* call wrote
    the ``node`` row, or was answered by the prior one) and ``artifact_written``
    (whether the artifact directory was committed). Carried so a caller — or the
    live loop on a retry — can see exactly what the write did and whether it was
    a first write or a refresh.
    """

    #: The node's identity.
    node_id: str
    #: The campaign the node belongs to.
    campaign_id: str
    #: The sealed snapshot the node was measured in.
    snapshot_name: str
    #: The evaluator image's hash.
    evaluator_hash: str
    #: The fee schedule that priced the node.
    cost_model: CostModelRef
    #: The records steps 7–9 measured, as read back from the store.
    returns: PostCostReturns
    metrics: NodeMetrics
    profile: DecayProfile
    #: The capacity estimate and regime attribution, read back as one pair.
    capacity: object
    attribution: object
    marginal: object
    #: The §9.2 files that were written, in write order.
    artifact_paths: Tuple[str, ...]
    #: Whether *this* call appended the ``node`` row (``False`` on a refresh).
    tree_appended: bool
    #: Whether the artifact directory was committed.
    artifact_written: bool


_SCHEMA = f"""
-- Feature 85: the orchestration ledger, one row per node.
--
-- This is not the tree `node` table (the tree member's) and not the artifact
-- files (the artifacts member's). It is this step's own record that feature
-- 85's one-shot write happened for a node, so a retry is a refresh and a
-- half-written node is discoverable — the way `evaluator_identity` is feature
-- 70's record that the hash landed.
--
-- The grain is one row per node: the write is keyed by the node, idempotent by
-- `node_id`, so a re-persist refreshes rather than appends. `tree_written` and
-- `artifact_written` are one flag per half — the `node` row and the artifact
-- directory — set as each half commits, so a crash between them leaves a
-- detectable half that `load` refuses rather than serving a node whose two
-- halves cannot both be accounted for.
CREATE TABLE IF NOT EXISTS {NODE_PERSIST_TABLE} (
    node_id          TEXT PRIMARY KEY,  -- the node this write is keyed by
    campaign_id      TEXT NOT NULL,     -- the campaign the node belongs to
    snapshot_name    TEXT NOT NULL,     -- the sealed snapshot it was measured in
    evaluator_hash   TEXT NOT NULL,     -- the evaluator that produced the node
    cost_venue       TEXT NOT NULL,     -- the fee schedule's venue
    cost_version     TEXT NOT NULL,     -- the fee schedule's version
    artifact_dir     TEXT,              -- the §9.2 directory, per the layout
    tree_written     INTEGER NOT NULL DEFAULT 0,  -- the node row half committed
    artifact_written INTEGER NOT NULL DEFAULT 0,  -- the artifact directory half
    tree_appended    INTEGER,           -- whether the tree write appended (idempotency)
    created_at       TEXT NOT NULL      -- when the row was first written (ISO)
);
"""


# -- The agreement check ---------------------------------------------------------


def _reference(cost_model: object) -> str:
    """A record's cost model, as the ``venue/version`` reference every record
    stamps — the axis the agreement check compares on.

    Every record steps 7–9 produced carries a cost model, and two fee schedules
    net different post-cost edges out of the same gross returns, so the whole
    record set must be priced under one — the same agreement
    :mod:`evaluator._capacity_store`._check_pair_agreement enforces on a pair,
    extended to the whole set. The reference is the canonical spelling
    :func:`cost_model_ref` folds any of the records' cost models to, so a
    ``CostModelRef`` and the shared cost library's resolved config compare equal.
    """
    return cost_model_ref(cost_model).reference


def _check_agreement(
    *,
    node_id: str,
    cost_model: object,
    records: Mapping[str, object],
) -> None:
    """Refuse a record set that does not name one node and one fee schedule.

    The whole set — returns, metrics, profile, capacity, attribution, marginal —
    must name the node the persistence names and be priced under the cost model
    the persistence names. A record filed under the wrong node, or priced under
    a different fee schedule, is an artifact no single evaluation produced, and
    the write is the last place that can be caught: once the files land, a reader
    has no way to tell a spliced set from a computed one. Refused *before any
    write*, so a mismatched record never reaches a seam.
    """
    for name, record in records.items():
        record_node = getattr(record, "node_id", _MISSING)
        if record_node is _MISSING:
            raise EvaluatorArtifactError(
                f"the record {name!r} carries no node_id — the whole set must "
                "name the node the persistence names, and a record without one "
                "cannot be checked against it"
            )
        if record_node != node_id:
            raise EvaluatorArtifactError(
                f"the record {name!r} names node {record_node!r} but the "
                f"persistence names node {node_id!r}; the artifact is one "
                "node's content, and a set spliced across two nodes is an "
                "artifact no evaluation produced"
            )
    canonical = _reference(cost_model)
    for name, record in records.items():
        record_ref = _reference(getattr(record, "cost_model", _MISSING))
        if record_ref != canonical:
            raise EvaluatorArtifactError(
                f"the record {name!r} was priced under {record_ref!r} but the "
                f"persistence names {canonical}; one evaluation prices one fee "
                "schedule, and a set priced across two is an artifact no "
                "evaluation produced"
            )


# -- The node row ----------------------------------------------------------------


def _cost_adjusted_ir(returns: PostCostReturns, metrics: NodeMetrics) -> float:
    """The mean post-cost edge of the equal-weight book — the cost-adjusted axis.

    Over the horizon the four scalars were measured over (:attr:`NodeMetrics.horizon`,
    the shortest the panel covers), for each rebalance date take the equal-weight
    mean post-cost return across the symbols that date held, then take the mean
    of those per-date means. That is "the mean post-cost edge of the equal-weight
    book" — the same panel ``ir_standalone`` is measured over, reduced to its mean
    rather than its reward-to-variance, so ``cost_adjusted_ir`` and
    ``ir_standalone`` sit on one axis and the former is the cost-adjusted edge the
    latter normalizes. It is carried on the node row as the cost-adjusted IR axis
    §9.1 names, restated from the priced returns rather than recomputed from the
    metrics, because it is a property of the panel, not of the four scalars.
    """
    series = returns.series[metrics.horizon]
    per_date_means = [
        (sum(series.at(day).values()) / len(series.at(day)))
        for day in sorted(series.dates())
        if series.at(day)
    ]
    if not per_date_means:
        raise EvaluatorArtifactError(
            f"the returns carry no post-cost edge at the metrics horizon "
            f"({metrics.horizon}), so there is no cost-adjusted IR to state on "
            "the node row; the node's headline numbers reduce from a priced "
            "panel, and a panel with no measured date has none"
        )
    return sum(per_date_means) / len(per_date_means)


def _assemble_node_row(
    *,
    node_id: str,
    campaign_id: str,
    snapshot_name: str,
    evaluator_hash: str,
    returns: PostCostReturns,
    metrics: NodeMetrics,
    marginal: object,
) -> NodeRow:
    """The ``node`` row's metric columns, assembled from the measured records.

    The evaluator supplies exactly the columns its records measure; the tree
    member supplies the rest. ``ic_mean``, ``ic_tstat``, ``ir_standalone`` and
    ``turnover`` come from the metrics; ``ir_marginal`` from the marginal IR;
    ``cost_adjusted_ir`` from the priced returns; and ``perturb_stability`` is
    carried as ``None`` — step 10's tripwire metric, and step 10 is not this
    step's input, so the honest value is "not measured by this step" rather than
    a zero.
    """
    if not hasattr(marginal, "ir_marginal"):
        raise EvaluatorArtifactError(
            "the marginal IR must carry ir_marginal — feature 83's scalar, the "
            "incremental information ratio the node row carries — got "
            f"{type(marginal).__name__}; the node row's ir_marginal column is "
            "step 9's number, and a record without it has none to write"
        )
    return NodeRow(
        node_id=node_id,
        campaign_id=campaign_id,
        snapshot_name=snapshot_name,
        evaluator_hash=evaluator_hash,
        cost_model=_reference(returns.cost_model),
        ic_mean=metrics.ic_mean,
        ic_tstat=metrics.ic_tstat,
        ir_standalone=metrics.ir_standalone,
        turnover=metrics.turnover,
        ir_marginal=marginal.ir_marginal,
        cost_adjusted_ir=_cost_adjusted_ir(returns, metrics),
        perturb_stability=None,
    )


# -- The store -------------------------------------------------------------------


class NodeArtifactStore:
    """Drives the two seams in one idempotent transaction for one database.

    Bound to a database URL at construction; construction performs no I/O (the
    path is resolved and the schema created on first use), so composing an
    application that carries this store touches no disk — the stance every store
    in this workspace takes. Like the identity, cost, decay, capacity and metrics
    stores and unlike the snapshot member's manifest store, it refuses rather than
    degrading when no store is configured: feature 85's text is "persisting", and
    the orchestration ledger is what a retry and :meth:`load` read back.

    :meth:`persist` reads the evaluator's own stores back to render the artifacts
    from what actually persisted, writes the §9.2 files through the
    :class:`ArtifactWriter`, writes the ``node`` row's metric columns through the
    ``TreeNodeWriter``, and records the orchestration row — one node, one write.
    :meth:`load` reads the orchestration row back and refuses a half.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise EvaluatorArtifactError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None
        self._resolved = False

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Optional[Mapping[str, str]] = None) -> "NodeArtifactStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the way the shared
        fixtures treat an empty ``TEST_DATABASE_URL``.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorArtifactError(
                f"{DATABASE_URL_ENV} is not set, so there is no orchestration "
                "store to record feature 85's write into (app_spec.xml feature "
                f"85); set {DATABASE_URL_ENV} to the system's database"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The write ------------------------------------------------------------

    def persist(
        self,
        *,
        node_id: str,
        campaign_id: str,
        snapshot_name: str,
        evaluator_hash: str,
        returns: PostCostReturns,
        metrics: NodeMetrics,
        profile: DecayProfile,
        estimate: object,
        attribution: object,
        marginal: object,
        artifact_writer: ArtifactWriter,
        tree_writer: TreeNodeWriter,
        code: Optional[str] = None,
        steps_completed: Tuple[int, ...] = (7, 8, 9, 11),
    ) -> NodePersistence:
        """Persist one node's artifact and scalars — pipeline step 12.

        The whole of feature 85 at its seams, in one node-scoped call:

        1. the whole record set is checked to name one node and one fee
           schedule — a spliced set is refused before any write;
        2. the canonical rows are read back from the evaluator's own stores —
           :func:`load_signal_returns`, :func:`load_node_metrics`,
           :func:`load_decay_profile`, :func:`load_capacity`,
           :func:`load_marginal_ir` — and a record the store does not hold is
           refused, so the artifact is rendered from what actually persisted;
        3. each §9.2 file is rendered via :mod:`evaluator._artifact` and written
           through the :class:`ArtifactWriter` (staged);
        4. the ``node`` row's metric columns are assembled and written through
           the ``TreeNodeWriter``;
        5. the artifact directory is committed with the writer's ``flush`` — the
           commit point — and the orchestration row records each half as it
           lands, in one node-scoped write;
        6. a node whose two halves cannot both be accounted for is refused.

        ``code`` is the caller's signal source, written as ``code.py`` when
        present and omitted when absent — the directory is complete without it.
        ``steps_completed`` is the pipeline steps this node reached, carried in
        ``exec_trace.json`` for replay. The write is idempotent by ``node_id``: a
        retry refreshes the files and the row's metric columns, and the returned
        :class:`NodePersistence` carries ``tree_appended`` so the caller sees
        whether this call wrote the row or was answered by the prior one.

        Every failure surfaces as :class:`~evaluator.EvaluatorArtifactError`,
        deliberately not swallowed: an artifact and a node row that were rendered
        and never accounted for are the state feature 85's "persisting" exists to
        rule out. The seams' own failures propagate unwrapped — a writer that
        cannot write is the artifacts' or tree member's to report, the same
        stance the oracle and cost-schedule seams take.
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorArtifactError(
                f"persist_node persists one node — its node_id must be a "
                f"non-empty name, got {node_id!r}"
            )
        if not isinstance(campaign_id, str) or not campaign_id.strip():
            raise EvaluatorArtifactError(
                "persist_node persists one node — its campaign_id must be a "
                f"non-empty name, got {campaign_id!r}"
            )
        if not isinstance(evaluator_hash, str) or not evaluator_hash.strip():
            raise EvaluatorArtifactError(
                "persist_node stamps the node with the evaluator that produced "
                f"it — its evaluator_hash must be a non-empty name, got "
                f"{evaluator_hash!r}"
            )
        if (
            not hasattr(artifact_writer, "write_artifact")
            or not callable(getattr(artifact_writer, "write_artifact"))
            or not hasattr(artifact_writer, "flush")
            or not callable(getattr(artifact_writer, "flush"))
        ):
            raise EvaluatorArtifactError(
                "the artifact writer must expose write_artifact and flush — "
                f"the ArtifactWriter seam the artifacts member speaks — got "
                f"{type(artifact_writer).__name__}; the evaluator imports no "
                "sibling, so the writer is injected and satisfied by duck typing"
            )
        if not hasattr(tree_writer, "write_node") or not callable(
            getattr(tree_writer, "write_node")
        ):
            raise EvaluatorArtifactError(
                "the tree writer must expose write_node — the TreeNodeWriter "
                f"seam the tree member speaks — got {type(tree_writer).__name__}; "
                "the evaluator imports no sibling, so the writer is injected"
            )

        # Resolve this store's own URL before touching anything else — an
        # unsupported scheme is this store's to refuse, and refusing it here
        # keeps the read-back from reaching a sibling store under a URL this
        # store cannot speak.
        self._resolve_path()

        records = {
            "returns": returns,
            "metrics": metrics,
            "profile": profile,
            "estimate": estimate,
            "attribution": attribution,
            "marginal": marginal,
        }
        _check_agreement(
            node_id=node_id, cost_model=returns.cost_model, records=records
        )

        # Read the canonical rows back from the evaluator's own stores, so the
        # artifact is rendered from what actually persisted — a record the store
        # does not hold is refused, not rendered from a value the pipeline held.
        store_returns = self._require(
            "load_signal_returns", node_id, returns.cost_model
        )
        store_metrics = self._require(
            "load_node_metrics", node_id, returns.cost_model
        )
        store_profile = self._require(
            "load_decay_profile", node_id, returns.cost_model
        )
        store_capacity, store_attribution = self._require_pair(
            "load_capacity", node_id, returns.cost_model
        )
        store_marginal = self._require(
            "load_marginal_ir", node_id, returns.cost_model
        )

        # The orchestration row exists before either half lands, so a crash
        # between the two halves leaves a row to inspect rather than none — the
        # half is discoverable, not silent.
        self._ensure_row(
            node_id,
            campaign_id,
            snapshot_name,
            evaluator_hash,
            store_returns.cost_model,
        )

        # Render each §9.2 file and write it through the seam, staged until flush.
        # ``code.py`` is the caller's signal source, written only when supplied —
        # it is not part of the fixed §9.2 set, so it is appended to the write
        # order conditionally rather than rendered unconditionally.
        written: list[str] = []
        artifact_order = _ARTIFACT_ORDER + (("code.py",) if code is not None else ())
        for filename in artifact_order:
            payload = _render_artifact(
                filename=filename,
                node_id=node_id,
                campaign_id=campaign_id,
                snapshot_name=snapshot_name,
                evaluator_hash=evaluator_hash,
                returns=store_returns,
                metrics=store_metrics,
                profile=store_profile,
                attribution=store_attribution,
                charges_budget=store_returns.charges_budget,
                steps_completed=steps_completed,
                code=code,
            )
            artifact_writer.write_artifact(
                node_id, campaign_id, filename, payload
            )
            written.append(filename)

        # Write the node row's metric columns through the tree seam, then commit
        # the artifacts. The tree write precedes flush — the commit point — so a
        # tree failure leaves the artifacts uncommitted (rolled back by the
        # writer) and the orchestration row's two flags disagreeing, which load
        # refuses.
        node_row = _assemble_node_row(
            node_id=node_id,
            campaign_id=campaign_id,
            snapshot_name=snapshot_name,
            evaluator_hash=evaluator_hash,
            returns=store_returns,
            metrics=store_metrics,
            marginal=store_marginal,
        )
        written_node_id, tree_appended = tree_writer.write_node(node_row)
        if written_node_id != node_id:
            raise EvaluatorArtifactError(
                f"the tree seam answered a node-row write for node "
                f"{written_node_id!r} but the persistence names node "
                f"{node_id!r}; a node row for one node cannot be written under "
                "another's identity"
            )
        self._mark_tree_written(node_id, tree_appended)

        # Commit the artifact directory — the write's commit point. A failure
        # here leaves the tree row written but the artifacts uncommitted; the
        # flags then disagree and load refuses the half, and a retry heals it.
        artifact_writer.flush(node_id)
        self._mark_artifact_written(node_id)

        row = self._read_row(node_id)
        if row is None or not (row["tree_written"] and row["artifact_written"]):
            raise EvaluatorArtifactError(
                f"node {node_id!r} was written half: the node row and the "
                "artifact directory must both be accounted for, and a node "
                "whose two halves cannot both be confirmed is refused — the "
                "two halves are one artifact's content, and a reader must "
                "never see one without the other"
            )

        return NodePersistence(
            node_id=node_id,
            campaign_id=campaign_id,
            snapshot_name=snapshot_name,
            evaluator_hash=evaluator_hash,
            cost_model=store_returns.cost_model,
            returns=store_returns,
            metrics=store_metrics,
            profile=store_profile,
            capacity=store_capacity,
            attribution=store_attribution,
            marginal=store_marginal,
            artifact_paths=tuple(written),
            tree_appended=bool(tree_appended),
            artifact_written=True,
        )

    # -- The read-back --------------------------------------------------------

    def load(self, node_id: str) -> Optional[NodePersistence]:
        """Read one node's persisted state back, or ``None`` — refusing a half.

        The read a retry and the live loop resolve against: given the node,
        answer with the :class:`NodePersistence` feature 85 left — or ``None``,
        the honest answer for a node this step never persisted. What comes back is
        *checked*: the orchestration row's two flags must both be set, so a node
        whose artifact directory exists but whose tree row does not (or vice
        versa) is refused rather than served — the two halves are one artifact's
        content, and a reader must never see one without the other (the defence
        :mod:`evaluator._capacity_store` applies to a capacity row without its
        attribution).
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorArtifactError(
                "a node id must be a non-empty string to read its persisted "
                f"state by, got {node_id!r}"
            )
        row = self._read_row(node_id)
        if row is None:
            return None
        if not (row["tree_written"] and row["artifact_written"]):
            raise EvaluatorArtifactError(
                f"node {node_id!r} is half-written: the orchestration ledger "
                f"records tree_written={row['tree_written']} and "
                f"artifact_written={row['artifact_written']}, and a node whose "
                "two halves cannot both be accounted for is refused — the "
                "artifact directory and the node row are one artifact's content"
            )
        # Re-read the records from the evaluator's own stores, so load returns
        # what actually persisted — the same read-back persist renders from.
        store_returns = self._require(
            "load_signal_returns", node_id, _row_cost_model(row)
        )
        store_metrics = self._require(
            "load_node_metrics", node_id, _row_cost_model(row)
        )
        store_profile = self._require(
            "load_decay_profile", node_id, _row_cost_model(row)
        )
        store_capacity, store_attribution = self._require_pair(
            "load_capacity", node_id, _row_cost_model(row)
        )
        store_marginal = self._require(
            "load_marginal_ir", node_id, _row_cost_model(row)
        )
        return NodePersistence(
            node_id=node_id,
            campaign_id=row["campaign_id"],
            snapshot_name=row["snapshot_name"],
            evaluator_hash=row["evaluator_hash"],
            cost_model=store_returns.cost_model,
            returns=store_returns,
            metrics=store_metrics,
            profile=store_profile,
            capacity=store_capacity,
            attribution=store_attribution,
            marginal=store_marginal,
            artifact_paths=(),
            tree_appended=bool(row["tree_appended"]),
            artifact_written=True,
        )

    # -- Connection ---------------------------------------------------------

    def _resolve_path(self) -> Optional[Path]:
        """Resolve the sqlite path once, refusing schemes this store cannot read.

        Deferred out of ``__init__`` so construction performs no I/O. An
        in-memory URL resolves to ``None``, which :meth:`_connect` reads as "use
        ``:memory:``" — per-connection, which is why the schema is created on
        every connect rather than cached.
        """
        if self._resolved:
            return self._path
        parsed = urlparse(self._database_url)
        if parsed.scheme != "sqlite":
            raise EvaluatorArtifactError(
                f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
                "store speaks sqlite:/// (the spec's single-machine allowance); "
                f"point {DATABASE_URL_ENV} at a sqlite database"
            )
        if parsed.netloc not in ("", "localhost"):
            raise EvaluatorArtifactError(
                f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
                f"{parsed.netloc!r}"
            )
        path = unquote(parsed.path).removeprefix("/")
        self._path = None if path in ("", ":memory:") else Path(path)
        self._resolved = True
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store and ensure its schema exists.

        Idempotent on every connect, so a fresh database and an existing one take
        the same path and no migration step is needed for this member. The caller
        owns the connection.
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

    # -- The orchestration row ------------------------------------------------

    def _ensure_row(
        self,
        node_id: str,
        campaign_id: str,
        snapshot_name: str,
        evaluator_hash: str,
        cost_model: object,
    ) -> None:
        """Create the node's orchestration row if it does not yet exist.

        Inserted with both flags at zero and the identity filled in, so a crash
        between the two halves leaves a row whose flags disagree — a discoverable
        half — rather than no row at all. An idempotent insert: a retry over an
        existing row is a no-op on the identity, and the flags are refreshed by
        the two ``_mark_*`` steps.
        """
        ref = _reference(cost_model)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {NODE_PERSIST_TABLE} (
                        node_id, campaign_id, snapshot_name, evaluator_hash,
                        cost_venue, cost_version,
                        tree_written, artifact_written, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        campaign_id   = excluded.campaign_id,
                        snapshot_name = excluded.snapshot_name
                    """,
                    (
                        node_id,
                        campaign_id,
                        snapshot_name,
                        evaluator_hash,
                        ref.split("/", 1)[0],
                        ref.split("/", 1)[1],
                        dt.datetime.now(dt.UTC).isoformat(),
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorArtifactError(
                f"could not record the orchestration row for node "
                f"{node_id!r}: {exc}"
            ) from exc

    def _mark_tree_written(self, node_id: str, tree_appended: bool) -> None:
        """Record that the node row half committed, with its idempotency signal."""
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"UPDATE {NODE_PERSIST_TABLE} SET tree_written = 1, "
                    f"tree_appended = ? WHERE node_id = ?",
                    (1 if tree_appended else 0, node_id),
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorArtifactError(
                f"could not record the tree half for node {node_id!r}: {exc}"
            ) from exc

    def _mark_artifact_written(self, node_id: str) -> None:
        """Record that the artifact directory half committed."""
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"UPDATE {NODE_PERSIST_TABLE} SET artifact_written = 1 "
                    f"WHERE node_id = ?",
                    (node_id,),
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorArtifactError(
                f"could not record the artifact half for node {node_id!r}: "
                f"{exc}"
            ) from exc

    def _read_row(self, node_id: str) -> Optional[dict[str, Any]]:
        """The node's orchestration row, or ``None``."""
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT node_id, campaign_id, snapshot_name, evaluator_hash,
                           cost_venue, cost_version, artifact_dir,
                           tree_written, artifact_written, tree_appended
                    FROM {NODE_PERSIST_TABLE}
                    WHERE node_id = ?
                    """,
                    (node_id,),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorArtifactError(
                f"could not read the orchestration row for node {node_id!r}: "
                f"{exc}"
            ) from exc
        if row is None:
            return None
        return {
            "node_id": row[0],
            "campaign_id": row[1],
            "snapshot_name": row[2],
            "evaluator_hash": row[3],
            "cost_venue": row[4],
            "cost_version": row[5],
            "artifact_dir": row[6],
            "tree_written": bool(row[7]),
            "artifact_written": bool(row[8]),
            "tree_appended": row[9],
        }

    # -- The read-back helpers ------------------------------------------------

    def _require(self, loader: str, node_id: str, cost_model: object) -> object:
        """Read one record back from the evaluator's store, refusing its absence.

        The artifact is rendered from what actually persisted, so a record the
        store does not hold is refused rather than rendered from a value the
        pipeline happened to hold — the precedent every store module states. The
        ``(venue, version)`` is part of the lookup key, so a record priced under a
        different fee schedule is not a partial answer.
        """
        from ._cost_store import load_signal_returns
        from ._capacity_store import load_capacity
        from ._decay_store import load_decay_profile
        from ._marginal_store import load_marginal_ir
        from ._metrics_store import load_node_metrics

        loaders = {
            "load_signal_returns": load_signal_returns,
            "load_node_metrics": load_node_metrics,
            "load_decay_profile": load_decay_profile,
            "load_capacity": load_capacity,
            "load_marginal_ir": load_marginal_ir,
        }
        reader = loaders[loader]
        result = reader(node_id, cost_model, database_url=self._database_url)
        if result is None:
            raise EvaluatorArtifactError(
                f"the store holds no {loader} row for node {node_id!r}; the "
                "artifact is rendered from what actually persisted, and a "
                "record the evaluator's own store does not hold is refused "
                "rather than rendered from a value the pipeline held"
            )
        return result

    def _require_pair(
        self, loader: str, node_id: str, cost_model: object
    ) -> Tuple[object, object]:
        """Read the capacity-and-attribution pair back, refusing either half alone.

        Feature 82's two values persist together as one artifact's content, so
        :func:`load_capacity` answers the pair or refuses a half; this step
        carries that refusal through, because a capacity without its attribution
        (or the reverse) is not the node's artifact.
        """
        from ._capacity_store import load_capacity

        result = load_capacity(node_id, cost_model, database_url=self._database_url)
        if result is None:
            raise EvaluatorArtifactError(
                f"the store holds no capacity-and-attribution pair for node "
                f"{node_id!r}; the two persist together as one artifact's "
                "content, and a record the evaluator's own store does not hold "
                "is refused rather than rendered from a value the pipeline held"
            )
        return result


def _row_cost_model(row: dict[str, Any]) -> CostModelRef:
    """The fee schedule the orchestration row names — the ``(venue, version)``
    every record the node persisted was priced under.

    The row stores the venue and version as columns; :func:`cost_model_ref`
    folds them back to the pair the records carry, so ``load`` reads the records
    back under the same fee schedule ``persist`` wrote them under.
    """
    return cost_model_ref({"venue": row["cost_venue"], "version": row["cost_version"]})


# -- The renderers' caller -------------------------------------------------------


def _render_artifact(
    *,
    filename: str,
    node_id: str,
    campaign_id: str,
    snapshot_name: str,
    evaluator_hash: str,
    returns: PostCostReturns,
    metrics: NodeMetrics,
    profile: DecayProfile,
    attribution: object,
    charges_budget: bool,
    steps_completed: Tuple[int, ...],
    code: Optional[str],
) -> object:
    """One §9.2 file's payload, rendered from the read-back records.

    Each file is one the artifacts member owns the encoding of; this member owns
    the content. The parquet files carry their record as the writer's source; the
    json files carry their rendered structure as text; and ``code.py`` carries the
    caller's signal source when present.
    """
    from ._artifact import ArtifactPayload

    if filename == "signal_returns.parquet":
        return ArtifactPayload(filename=filename, kind="parquet", source=returns)
    if filename == "ic_series.parquet":
        return ArtifactPayload(filename=filename, kind="parquet", source=metrics)
    if filename == "turnover_series.parquet":
        return ArtifactPayload(
            filename=filename, kind="parquet", source=(returns, metrics)
        )
    if filename == "decay_profile.json":
        return ArtifactPayload(
            filename=filename,
            kind="json",
            json_text=json.dumps(render_decay_profile(profile)),
        )
    if filename == "regime_attribution.json":
        return ArtifactPayload(
            filename=filename,
            kind="json",
            json_text=json.dumps(render_regime_attribution(attribution)),
        )
    if filename == "exec_trace.json":
        return ArtifactPayload(
            filename=filename,
            kind="json",
            json_text=json.dumps(
                render_exec_trace(
                    node_id=node_id,
                    campaign_id=campaign_id,
                    snapshot_name=snapshot_name,
                    evaluator_hash=evaluator_hash,
                    cost_model=returns.cost_model,
                    horizons=HORIZONS,
                    charges_budget=charges_budget,
                    steps_completed=steps_completed,
                )
            ),
        )
    if filename == "code.py":
        if code is None:
            raise EvaluatorArtifactError(
                "code.py is only written when the caller supplies the signal "
                "source; the render asked for it with none"
            )
        return ArtifactPayload(filename=filename, kind="code", code_text=code)
    raise EvaluatorArtifactError(
        f"{filename!r} is not one of §9.2's artifact files; the artifact set "
        "is closed, and a file outside it is not this step's to write"
    )


# -- The module-level spelling the pipeline calls -----------------------------


def persist_node(
    *,
    node_id: str,
    campaign_id: str,
    snapshot_name: str,
    evaluator_hash: str,
    returns: PostCostReturns,
    metrics: NodeMetrics,
    profile: DecayProfile,
    estimate: object,
    attribution: object,
    marginal: object,
    artifact_writer: ArtifactWriter,
    tree_writer: TreeNodeWriter,
    code: Optional[str] = None,
    steps_completed: Tuple[int, ...] = (7, 8, 9, 11),
    database_url: Optional[str] = None,
) -> NodePersistence:
    """Persist one node's artifact and scalars — the pipeline's step-12 spelling.

    Feature 85's two verbs, joined: the records steps 7–9 produced are gathered,
    each rendered into its §9.2 artifact file, and the scalar metrics copied onto
    the §9.1 ``node`` row, under one node-scoped, idempotent, half-refusing
    contract. ``database_url`` falls back to ``DATABASE_URL``, and a missing store
    is refused by name rather than silently skipped — feature 85 says
    "persisting", so a write that never landed in the orchestration ledger is the
    gap it exists to close.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorArtifactError(
            f"{DATABASE_URL_ENV} is not set, so there is no orchestration store "
            "to record feature 85's write into (app_spec.xml feature 85); set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one explicitly"
        )
    return NodeArtifactStore(url.strip()).persist(
        node_id=node_id,
        campaign_id=campaign_id,
        snapshot_name=snapshot_name,
        evaluator_hash=evaluator_hash,
        returns=returns,
        metrics=metrics,
        profile=profile,
        estimate=estimate,
        attribution=attribution,
        marginal=marginal,
        artifact_writer=artifact_writer,
        tree_writer=tree_writer,
        code=code,
        steps_completed=steps_completed,
    )
