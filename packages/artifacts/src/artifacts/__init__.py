"""The artifact store: one persisted directory per node.

Implements app_spec.xml feature 169, "System persists one artifact
directory per node keyed by campaign_id then node_id", on the layout of
docs/nullius-tech-architecture.md §9.2:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet
      turnover_series.parquet
      decay_profile.json
      regime_attribution.json
      exec_trace.json
      code.py

This package is a workspace member discovered by convention. The module
loader (``app.module_loader``) scans the members the root
``pyproject.toml`` declares, imports each package, and composes
whatever the package's ``@register`` builder contributes — so the
registration below is the entire wiring story. Nothing edits a
registry, router or factory to make the artifacts plugin exist;
importing this module *is* joining the application. All intra-package
imports are relative so the package imports identically under its own
name and under the loader's scan-time name.

The contributed components are an :class:`ArtifactStore` bound to the
root ``ARTIFACT_ROOT`` names (defaulting to ``artifacts/`` beside the
workspace root) and — feature 179 — a :class:`CodeHashIndex` bound to
the store ``DATABASE_URL`` names, or ``None`` where it names none.
Everything else in the public API is importable directly for scripts,
tests and the sibling features of this category, which build on these
seams:

* **The key is the layout** (:mod:`artifacts._keys`).  A node's
  directory has no name of its own — no seal time, no hash prefix —
  because the feature keys it by the two identities the rest of the
  system joins on: campaign first, then node.  Each key is exactly one
  path segment, enforced at every public boundary, so no key can
  reshape the tree or escape the store root; two campaigns never share
  a node, and a node never gets a second directory, because the
  address is a pure function of the two keys.

* **The write path stages, the commit publishes** (:mod:`artifacts.
  _store`).  :meth:`ArtifactStore.write` stages files under the
  store's hidden ``.staging`` plumbing, and :meth:`ArtifactStore.commit`
  publishes the staged set as the node's directory by renaming it into
  place — atomic on POSIX, so no reader ever observes a half-written
  node directory.  A refresh replaces the prior directory wholesale:
  after a re-persist the node carries exactly the files the retry
  staged, never a splice of two runs.  :meth:`ArtifactStore.discard`
  rolls the staged writes back without a trace.  This is the same
  discipline the evaluator's step-12 ``ArtifactWriter`` seam (feature
  85, :mod:`evaluator._artifact`) is specified over — staged writes, one
  commit point, nothing half-written — so this store is the durability
  the writer side of that seam stands on.  It is not that seam's
  interface: the seam spells its operations ``write_artifact(node_id,
  campaign_id, filename, payload)`` and ``flush(node_id)`` (node first,
  a payload object), this store spells them :meth:`ArtifactStore.write`
  and :meth:`ArtifactStore.commit` (campaign first, raw bytes), and the
  workspace contract forbids either member importing the other — so an
  adapter maps one spelling onto the other where the writer is injected.
  The payload encoders that turn a rendered record into Parquet or JSON
  bytes are the layer features 170-173 add, on this API rather than
  beside it.

* **The read side answers by the same keys.**
  :meth:`ArtifactStore.campaign_ids` and
  :meth:`ArtifactStore.node_ids` walk the two key levels;
  :meth:`ArtifactStore.files` and :meth:`ArtifactStore.read` serve a
  node's bytes.  This is the store §1 grants the replay engine read
  access to (and nothing else), and the one feature 174's dense
  campaign array load will sweep.  A missing node is
  :class:`ArtifactNotFoundError` — a fact about the store's contents,
  kept apart from a malformed key (:class:`ArtifactKeyError`) and from
  a failed write (:class:`ArtifactStoreError`) so a caller can report
  "unknown node" the way §7.2's route reports its 404 while still
  catching every genuine breakage with :class:`ArtifactsError`.

The content of the §9.2 files is deliberately *not* this feature's:
feature 169 pins the directory half — the address, the one-unit
publication, the listing — and the Parquet and JSON files later
features persist land inside the directories this store keys.

* **The dedup gate stands between a proposal and its trial**
  (:mod:`artifacts._dedup`, feature 179).  §9.1's node table carries
  ``code_hash`` as the node's *identity*, and the index over it exists
  ``-- dedup``: :func:`reject_duplicate` compares a proposed node's code
  hash against the stored ones and refuses an exact duplicate, and
  :meth:`CodeHashIndex.probe` holds the tree store's write lock across the
  check and the caller's write, so two proposers holding one code cannot
  both read "not stored" and both charge.  That lock is where migration
  0113's named exposure — *"two writers racing feature 179's check can both
  pass it and both charge a trial"* — is closed, without the ``UNIQUE``
  constraint the spec withheld.  The lookup is over the whole tree, not one
  campaign: the index §9.1 draws for it is keyed on ``code_hash`` alone,
  and 0117's argument that it needs no ``UNIQUE`` rests on the gate
  refusing the pair anywhere.  Nothing here charges: the ledger is feature
  84's, the debit endpoint feature 95's, and this module owns only the
  ordering the feature states.

* **The executed source and its trace persist as one pair**
  (:mod:`artifacts._execution`, feature 173).  §9.2's last two lines —
  ``code.py`` and ``exec_trace.json`` — are the only records of the
  *execution* itself, every other file in the directory being data one
  run derived; §1 grants replay read access to this store and nothing
  else, so the run's bytes and behaviour live in the node's directory
  or nowhere.  :func:`persist_execution` stages both halves through the
  store's write path as one operation (the "plus" is the contract: a
  source without its trace, or a trace without its source, is the half
  pair the feature exists to prevent, and no spelling of this layer
  can stage one), the node's :meth:`~artifacts.ArtifactStore.commit`
  publishes them alongside every stored artifact file, and
  :func:`executed_source`/:func:`execution_trace` answer the pair back
  by the same two keys while :func:`execution_is_persisted` reports the
  invariant for a published node.  The trace's *vocabulary* is the
  evaluator's (feature 85's fingerprint); this layer owns the names,
  the pairing, the canonical JSON bytes and the identity tie —
  :func:`source_code_hash` derives the sha256 §9.1's ``code_hash``
  column carries from the very text staged as ``code.py``, so the row
  and the directory cannot disagree about which code a node ran.

* **The post-cost returns persist as one Parquet grid** (:mod:`artifacts.
  _returns`, feature 170).  §9.2's first line — ``signal_returns.parquet``,
  "per-symbol, per-period, post-cost" — is the artifact the layout calls
  *the key artifact*, and the one whose completeness §9.2 spells out:
  *"Because it is stored in full, marginal contribution against any book
  can be recomputed at replay time, so the same node scores differently
  depending on the path a policy took to reach it, while replay stays fully
  deterministic."*  So nothing is reduced on the way in: a
  :class:`~artifacts.SignalReturns` carries one
  :class:`~artifacts.ReturnRow` per ``(rebalance date, horizon, symbol)``
  the evaluation priced, with the schedule's deduction and the post-cost
  return on every row, and :func:`persist_signal_returns` stages the whole
  grid through feature 169's write path as one file —
  :func:`signal_returns` answers it back by the same two keys and
  :func:`signal_returns_is_persisted` reports the invariant.  The file is
  typed (``date32``/``int32``/``string``/``float64``) because §4.1's
  analytics row reads it in place through DuckDB, the panel's identity —
  the node, the sealed snapshot and feature 59's ``(venue, version)`` pair
  — rides in the Parquet schema's metadata rather than on every row, and
  rows are sorted by date, horizon and symbol so two equal panels stage
  identical bytes.  The gross return is *derived* on the record from the
  charge and the net, so the writer cannot stage a row its own reader — which
  re-checks every stored gross against its own terms — would refuse.

* **One campaign's returns load as one dense resident array**
  (:mod:`artifacts._campaign`, feature 174).  §9.3 opens with the
  bottleneck — *"A replay revealing 100 nodes reads ~20 MB of Parquet;
  200 worlds × 40 policy versions done naively is ~160 GB per dreaming
  cycle"* — and pins the answer this module builds: *"Load each
  campaign's signal returns once as a single dense ``float32`` array of
  shape ``(nodes × T)``."*  :func:`load_campaign_returns` sweeps the
  campaign's nodes through the read side §1 grants replay (and no
  second decoder), reduces each node's grid to the T-vector §9.3 says a
  signal contributes — the equal-weight per-date post-cost return at
  the pinned horizon, both collapses the evaluator's own — and answers
  a :class:`~artifacts.CampaignReturns`: the two sorted axes beside one
  contiguous stdlib ``array.array('f')`` buffer, row-major, one cell
  per ``(node, period)``, NaN where no panel measured (absence, not a
  zero dressed as a measurement) and never an ``inf``.  The horizon is
  a policy — the shortest horizon every swept panel covers, the
  evaluator's ``METRICS_HORIZON`` at campaign scale — with an explicit
  pin for a caller measuring at another axis; the panels' sealed
  snapshot and ``(venue, version)`` cost pair must agree, because the
  load is the seam where a per-file identity becomes a per-campaign
  fact.  The narrowing to float32 is the point and happens once, here:
  the file keeps the double the evaluator computed, the resident array
  keeps the 4 bytes §9.3 sizes its residency by (500 nodes × 2000
  periods × 4 B = 4 MB per campaign).

* **The resident cache holds the series, and declines the marginal IR**
  (:mod:`artifacts._cache`, feature 176).  §9.3's instruction is a
  refusal before it is an instruction — *"So do not cache marginal IR
  against canonical books.  Cache the return series."* — and this
  module speaks both halves.  The decline is a *named verdict*, not a
  silent absence: :func:`decline_marginal_ir` (the data-side
  spelling, needing no store, the way feature 179's
  :func:`reject_duplicate` needs none) and
  :meth:`ReturnSeriesCache.marginal_ir` (the object-side spelling, the
  one a replay holding the cache reaches for) both answer
  :class:`~artifacts.ArtifactMarginalIRDeclinedError` carrying the
  ``declined_marginal_ir`` code, the §9.2 reason a cached value would
  be stale by construction (*"the same node scores differently
  depending on the path a policy took to reach it"* — the book is an
  argument of the metric, not a dimension of the data), and the
  instead this feature's own sentence pins.  The instead is
  :class:`ReturnSeriesCache`: one campaign's
  :class:`~artifacts.CampaignReturns`, loaded once through feature
  174's load (no second decoder — the load's refusals pass through
  unchanged) and answered resident thereafter, keyed by exactly the
  ask ``(campaign, horizon)``.  §9.3's *"no canonical-book cache
  anywhere"* is structural here: the residence is a private mapping of
  campaign keys to return-series values, no public operation accepts
  any other entry kind, and the one ask shaped like one is the
  decline.

* **The two per-date series persist as Parquet** (:mod:`artifacts._series`,
  feature 171).  §9.2's ``ic_series.parquet`` and ``turnover_series.parquet``
  — the two lines between the returns grid and the edge's JSON documents —
  are the node's *date-keyed scalar series*: the information coefficient the
  signal earned on each rebalance date and the fraction of the equal-weight
  book that had to be traded to hold it.  Every other line of the layout has
  a shape of its own — ``signal_returns.parquet`` is a symbol × period grid
  (feature 170), the two documents are an array and a per-stratum split
  (feature 172), the pair is text and a fingerprint (feature 173) — these
  two are one shape twice, which is why they carry one schema
  (``date32``/``float64``) and are written, read and checked by one codec:
  the metric is the filename's to say, the shape is the columns'.
  :func:`persist_ic_series` and :func:`persist_turnover_series` stage each
  file through feature 169's write path (one operation per metric, since
  neither is unreadable without the other), :func:`ic_series` and
  :func:`turnover_series` answer ``{date: value}`` back by the same two keys,
  and :func:`ic_series_is_persisted`/:func:`turnover_series_is_persisted`
  report each invariant separately.  Rows are sorted by date before they are
  written, so two equal series stage identical bytes and key order is never
  part of a stored measurement's identity.  This layer owns the names, the
  schema, the canonical row order and the refusals; the *metric* — what an
  information coefficient and a fractional turnover mean, and how they are
  computed — is the evaluator's (features 80, 85), and is not restated here.

* **The edge's two shapes persist as JSON documents**
  (:mod:`artifacts._profiles`, feature 172).  §9.2's two middle lines —
  ``decay_profile.json`` and ``regime_attribution.json`` — are the
  node's edge described along its two axes: the horizon axis (how much
  information coefficient survives to each of feature 81's horizons, as
  the positional array the live loop reads entry by entry) and the
  regime axis (feature 82's per-stratum, per-horizon split).  Every
  other file in the directory is a date-keyed series (170-171's
  Parquet), the run's record (``exec_trace.json``) or its source
  (``code.py``); these two are the documents a policy reads to ask what
  *shape* an edge has.  :func:`persist_decay_profile` and
  :func:`persist_regime_attribution` stage their file through the same
  write path — one operation per document, because the two are produced
  at two different measurement steps and each is independently readable,
  so unlike feature 173's pair neither insists on the other — with
  :func:`decay_profile`/:func:`regime_attribution` answering them back
  and :func:`decay_profile_is_persisted`/
  :func:`regime_attribution_is_persisted` reporting each invariant
  separately.  This layer owns the names, the two top-level shapes, the
  canonical JSON bytes and the refusals; the axis's horizons and the
  strata's vocabulary are the evaluator's, and are not restated here.
"""

from __future__ import annotations

from app.module_loader import register

from ._cache import (
    DECLINED_MARGINAL_IR,
    IR_MARGINAL,
    RESIDENT_CACHE_POLICY,
    ReturnSeriesCache,
    decline_marginal_ir,
)
from ._campaign import (
    ABSENT,
    CAMPAIGN_LOAD_HORIZON,
    FLOAT32_TYPECODE,
    CampaignReturns,
    load_campaign_returns,
)
from ._daily import (
    DAILY_RETURNS_FILENAME,
    daily_returns,
    daily_returns_is_persisted,
    persist_daily_returns,
)
from ._dedup import (
    CODE_HASH_COLUMN,
    CODE_HASH_LENGTH,
    DATABASE_URL_ENV,
    DUPLICATE_CODE_HASH,
    NODE_CODE_HASH_INDEX,
    NODE_TABLE,
    CodeHashIndex,
    StoredCodeHash,
    canonical_code_hash,
    reject_duplicate,
)
from ._errors import (
    ArtifactCacheError,
    ArtifactDeduplicatedError,
    ArtifactKeyError,
    ArtifactMarginalIRDeclinedError,
    ArtifactNotFoundError,
    ArtifactProposalError,
    ArtifactsError,
    ArtifactStoreError,
)
from ._execution import (
    SOURCE_FILENAME,
    TRACE_FILENAME,
    executed_source,
    execution_is_persisted,
    execution_trace,
    persist_execution,
    source_code_hash,
)
from ._keys import (
    campaign_directory,
    node_directory,
    validate_campaign_id,
    validate_filename,
    validate_node_id,
    validate_segment,
)
from ._profiles import (
    DECAY_PROFILE_FILENAME,
    REGIME_ATTRIBUTION_FILENAME,
    decay_profile,
    decay_profile_is_persisted,
    persist_decay_profile,
    persist_regime_attribution,
    regime_attribution,
    regime_attribution_is_persisted,
)
from ._returns import (
    CHARGE_COLUMN,
    GROSS_COLUMN,
    HORIZON_COLUMN,
    NET_COLUMN,
    SIGNAL_RETURNS_FILENAME,
    SYMBOL_COLUMN,
    ReturnRow,
    SignalReturns,
    decode_signal_returns,
    encode_signal_returns,
    persist_signal_returns,
    signal_returns,
    signal_returns_is_persisted,
)
from ._series import (
    DATE_COLUMN,
    IC_SERIES_FILENAME,
    PARQUET_COMPRESSION,
    TURNOVER_SERIES_FILENAME,
    VALUE_COLUMN,
    decode_series,
    encode_series,
    ic_series,
    ic_series_is_persisted,
    persist_ic_series,
    persist_turnover_series,
    require_arrow,
    turnover_series,
    turnover_series_is_persisted,
)
from ._store import (
    ARTIFACT_ROOT_ENV,
    DEFAULT_ROOT_NAME,
    STAGING_ROOT_NAME,
    ArtifactStore,
    artifact_uri,
)

__all__ = [
    "ABSENT",
    "ARTIFACT_ROOT_ENV",
    "CAMPAIGN_LOAD_HORIZON",
    "CHARGE_COLUMN",
    "CODE_HASH_COLUMN",
    "CODE_HASH_LENGTH",
    "COMPONENT_NAME",
    "DAILY_RETURNS_FILENAME",
    "DATABASE_URL_ENV",
    "DATE_COLUMN",
    "DECAY_PROFILE_FILENAME",
    "DECLINED_MARGINAL_IR",
    "DEDUP_COMPONENT_NAME",
    "DEFAULT_ROOT_NAME",
    "DUPLICATE_CODE_HASH",
    "FLOAT32_TYPECODE",
    "GROSS_COLUMN",
    "HORIZON_COLUMN",
    "IC_SERIES_FILENAME",
    "IR_MARGINAL",
    "NET_COLUMN",
    "NODE_CODE_HASH_INDEX",
    "NODE_TABLE",
    "PARQUET_COMPRESSION",
    "REGIME_ATTRIBUTION_FILENAME",
    "RESIDENT_CACHE_POLICY",
    "SIGNAL_RETURNS_FILENAME",
    "SOURCE_FILENAME",
    "STAGING_ROOT_NAME",
    "SYMBOL_COLUMN",
    "TRACE_FILENAME",
    "TURNOVER_SERIES_FILENAME",
    "VALUE_COLUMN",
    "ArtifactCacheError",
    "ArtifactDeduplicatedError",
    "ArtifactKeyError",
    "ArtifactMarginalIRDeclinedError",
    "ArtifactNotFoundError",
    "ArtifactProposalError",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactsError",
    "CampaignReturns",
    "CodeHashIndex",
    "ReturnRow",
    "ReturnSeriesCache",
    "SignalReturns",
    "StoredCodeHash",
    "artifact_uri",
    "build_dedup_gate",
    "campaign_directory",
    "canonical_code_hash",
    "daily_returns",
    "daily_returns_is_persisted",
    "decay_profile",
    "decay_profile_is_persisted",
    "decline_marginal_ir",
    "decode_series",
    "decode_signal_returns",
    "encode_series",
    "encode_signal_returns",
    "executed_source",
    "execution_is_persisted",
    "execution_trace",
    "ic_series",
    "ic_series_is_persisted",
    "load_campaign_returns",
    "node_directory",
    "persist_daily_returns",
    "persist_decay_profile",
    "persist_execution",
    "persist_ic_series",
    "persist_regime_attribution",
    "persist_signal_returns",
    "persist_turnover_series",
    "regime_attribution",
    "regime_attribution_is_persisted",
    "reject_duplicate",
    "require_arrow",
    "signal_returns",
    "signal_returns_is_persisted",
    "source_code_hash",
    "turnover_series",
    "turnover_series_is_persisted",
    "validate_campaign_id",
    "validate_filename",
    "validate_node_id",
    "validate_segment",
]

#: The component name the artifacts member registers under — the plugin
#: name the spec's features carry (``plugin="artifacts"``), so the
#: component key, the app-namespace seat
#: (``src/app/modules/artifacts``) and the spec cannot drift apart.
COMPONENT_NAME = "artifacts"

#: The component name feature 179's dedup gate registers under.  A second
#: component under its own name rather than a second thing hung on the
#: store: the artifact directory (feature 169) and the dedup gate are two
#: different objects on two different lifecycles — one is bound to a
#: filesystem root, the other to the relational store — and a deployment
#: configured for the tree but not the artifact volume (a reconciliation
#: process, a planner) composes the gate and not the store.  The
#: ``artifacts-`` prefix keeps the member's components adjacent in
#: ``app.order``, which is name-sorted.
DEDUP_COMPONENT_NAME = "artifacts-code-hash-dedup"


@register(COMPONENT_NAME)
def artifact_store() -> ArtifactStore:
    """Component builder: the store bound to the configured root.

    Takes no arguments — that is the factory's registration protocol —
    and resolves its configuration from the environment at build time,
    so a composed application always carries a store for the tree the
    process is actually pointed at (``ARTIFACT_ROOT``, set per test by
    the fixtures in this member's suite and by the deployment's
    environment in production).  Construction performs no I/O: the root
    is resolved and held, and directories appear only when an operation
    needs them — the stance the snapshot service takes, for the same
    reason (composition must be safe in any environment).
    """
    return ArtifactStore.from_env()


@register(DEDUP_COMPONENT_NAME)
def build_dedup_gate() -> CodeHashIndex | None:
    """Component builder: the dedup gate ``DATABASE_URL`` names, or ``None``.

    Feature 179's gate is bound to the *relational* store, not the artifact
    root, so it resolves through :meth:`CodeHashIndex.resolve` — which
    returns ``None`` for a deployment that names no database rather than
    raising, because the factory builds every registered component on every
    ``create_app()`` call and a builder that raised would take composition
    down for every unrelated feature.  ``None`` is a discoverable state, not
    an error: it is a deployment with no tree store to deduplicate against
    — while the proposal path that must not charge a duplicate is the
    caller that must not find itself in it.  Construction performs no I/O:
    the URL is translated on first use, so composing an application that
    carries this gate touches no disk.
    """
    return CodeHashIndex.resolve()
