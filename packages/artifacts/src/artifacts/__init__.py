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
    ArtifactDeduplicatedError,
    ArtifactKeyError,
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
from ._store import (
    ARTIFACT_ROOT_ENV,
    DEFAULT_ROOT_NAME,
    STAGING_ROOT_NAME,
    ArtifactStore,
    artifact_uri,
)

__all__ = [
    "ARTIFACT_ROOT_ENV",
    "CODE_HASH_COLUMN",
    "CODE_HASH_LENGTH",
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DECAY_PROFILE_FILENAME",
    "DEDUP_COMPONENT_NAME",
    "DEFAULT_ROOT_NAME",
    "DUPLICATE_CODE_HASH",
    "NODE_CODE_HASH_INDEX",
    "NODE_TABLE",
    "REGIME_ATTRIBUTION_FILENAME",
    "SOURCE_FILENAME",
    "STAGING_ROOT_NAME",
    "TRACE_FILENAME",
    "ArtifactDeduplicatedError",
    "ArtifactKeyError",
    "ArtifactNotFoundError",
    "ArtifactProposalError",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactsError",
    "CodeHashIndex",
    "StoredCodeHash",
    "artifact_uri",
    "build_dedup_gate",
    "campaign_directory",
    "canonical_code_hash",
    "decay_profile",
    "decay_profile_is_persisted",
    "executed_source",
    "execution_is_persisted",
    "execution_trace",
    "node_directory",
    "persist_decay_profile",
    "persist_execution",
    "persist_regime_attribution",
    "regime_attribution",
    "regime_attribution_is_persisted",
    "reject_duplicate",
    "source_code_hash",
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
