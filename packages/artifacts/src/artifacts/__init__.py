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

The contributed component is an :class:`ArtifactStore` bound to the
root ``ARTIFACT_ROOT`` names (defaulting to ``artifacts/`` beside the
workspace root). Everything else in the public API is importable
directly for scripts, tests and the sibling features of this category,
which build on these seams:

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
"""

from __future__ import annotations

from app.module_loader import register

from ._errors import (
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactsError,
    ArtifactStoreError,
)
from ._keys import (
    campaign_directory,
    node_directory,
    validate_campaign_id,
    validate_filename,
    validate_node_id,
    validate_segment,
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
    "COMPONENT_NAME",
    "DEFAULT_ROOT_NAME",
    "STAGING_ROOT_NAME",
    "ArtifactKeyError",
    "ArtifactNotFoundError",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactsError",
    "artifact_uri",
    "campaign_directory",
    "node_directory",
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
