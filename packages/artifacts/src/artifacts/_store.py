"""The artifact store — one persisted directory per node, keyed campaign then node.

app_spec.xml feature 169: *"System persists one artifact directory per
node keyed by campaign_id then node_id."*  docs/nullius-tech-
architecture.md §9.2 draws what that sentence persists:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet
      turnover_series.parquet
      decay_profile.json
      regime_attribution.json
      exec_trace.json
      code.py

This module is the store that owns the **directory** half: the address
(:mod:`artifacts._keys` — the key is the layout), the persistence
(below), and the listing a reader — the replay engine §1 grants read
access to this store and nothing else, feature 174's campaign load, an
operator's reconciliation sweep — walks.  The *content* of the files is
not this feature's: features 170-173 layer the Parquet and JSON files
onto this store's API, and the evaluator's step-12 orchestration
(feature 85) already renders content and hands it across a seam.  What
feature 169 pins is the thing every one of those depends on — that a
node's artifact lives in **one** directory at **one** address, derived
from the two identities the rest of the system joins on.

**One directory per node, exactly.**  A node's directory is created on
demand — :meth:`ArtifactStore.node_directory` persists it — and the
creation is idempotent: the same ``(campaign_id, node_id)`` resolves to
the same directory every time, forever, because the address is a pure
function of the two keys.  There is no second spelling: no seal-time
name, no content prefix, no per-write directory.  Two nodes therefore
never share a directory (different second segments address different
directories), a node never gets two (one key pair, one address), and
two campaigns never collide on a node (the first segment separates
them — §9.1 makes ``campaign_id`` part of a node's identity in the
tree store, and the artifact store keys the same way, or a node could
be addressed by only half its identity).  The campaign parent exists
exactly when one of its nodes does; a campaign with no nodes holds no
artifact and gets no directory.

**Writes are staged; a commit publishes the directory as one unit.**
:meth:`ArtifactStore.write` stages a file under the store's hidden
``.staging`` plumbing — invisible to every read — and
:meth:`ArtifactStore.commit` is the commit point that publishes the
staged set as the node's directory by renaming it into place.
:func:`os.rename` of a directory is atomic on POSIX, so a reader never
observes a half-written node directory under its key: before the
commit there is no new directory at all, after it there is the whole
one.  This is the snapshot member's publication discipline (``.sealing``
working directory, then the rename), applied per node: a failure before
the commit leaves the previous directory (if any) untouched and nothing
new visible.  :meth:`ArtifactStore.discard` is the rollback half: staged
writes vanish without a trace, idempotently, so an interrupted pipeline
retries cleanly rather than resuming half a node.

**The evaluator's step-12 seam adapts to this store; it is not this
store.**  Feature 85's ``ArtifactWriter`` (``evaluator._artifact``)
names its two operations ``write_artifact(node_id, campaign_id,
filename, payload)`` and ``flush(node_id)`` — node first, and a payload
object rather than raw bytes — where this store spells the same two
operations :meth:`ArtifactStore.write(campaign_id, node_id, filename,
data) <write>` and :meth:`ArtifactStore.commit(campaign_id, node_id)
<commit>`, campaign first.  The *contract* is the same one this module
documents above — writes stage, one commit point publishes, nothing is
half-written — which is what the seam's docstring means when it says the
writer is "satisfied structurally"; the *signatures* are not, so
satisfying that seam takes an adapter that maps one spelling onto the
other (swapping the key order and encoding a payload's ``kind`` into
bytes).  The workspace contract keeps the evaluator from importing this
member and this member from importing the evaluator, so that adapter
lives with whoever injects the writer, not here.  What this feature
owes the seam is the discipline, not the method names.

**Commit refreshes wholesale.**  A commit of a node that already holds
a directory replaces it as a unit: the prior version steps aside and
the newly staged set takes the address, so a re-persisted node carries
exactly the files the retry wrote — never a splice of two runs.  POSIX
cannot swap two directories in one atomic step, so the refresh briefly
holds the address empty between the two renames; the invariant that
holds throughout is the one the feature states — one directory per
node, never two, never partial.  A commit with nothing staged refuses
(:class:`~artifacts._errors.ArtifactStoreError`): an empty replace
would silently delete a node's artifact, and "the writer wrote
nothing" is a failure to name, not a publication to make.

**The root is configured, not guessed at.**  :meth:`ArtifactStore.from_env`
reads :data:`ARTIFACT_ROOT` (an empty or whitespace-only value counts as
unset, mirroring the shared fixtures' treatment of an empty
``TEST_DATABASE_URL``), and defaults to ``artifacts/`` beside the
workspace root — located through the factory's workspace discovery, the
same way the snapshot member defaults its lake — so a composed
application always carries a store for the tree the process is pointed
at.  With neither available the store refuses to guess: raising a clear
error beats persisting into ``/``.  Construction performs no I/O — the
service is safe to build at composition time in any environment, and
directories appear only when an operation needs them.

Stdlib-only by design: the directory half of §9.2 is pure filesystem
work, and an import-safe member with no dependencies cannot break
another member's resolution.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

from app.module_loader import find_workspace_root

from ._errors import (
    ArtifactNotFoundError,
    ArtifactStoreError,
)
from ._keys import (
    campaign_directory,
    is_plumbing,
    validate_campaign_id,
    validate_filename,
    validate_node_id,
)
from ._keys import (
    node_directory as node_path,
)

__all__ = [
    "ARTIFACT_ROOT_ENV",
    "DEFAULT_ROOT_NAME",
    "STAGING_ROOT_NAME",
    "ArtifactStore",
    "artifact_uri",
]

#: Environment variable naming the artifact store's root — the one
#: spelling of "where the artifacts live" (§9.2's ``/artifacts``).  The
#: shared test fixtures set it per test; a deployment points it at the
#: store's volume.
ARTIFACT_ROOT_ENV = "ARTIFACT_ROOT"

#: The name of the store's hidden plumbing root under ``root`` — the
#: staging area every write lands in before its commit publishes it,
#: and the parent of the aside-directories a refresh moves a replaced
#: version through.  Dot-prefixed, so no campaign can be keyed into it
#: (:mod:`artifacts._keys` refuses the namespace) and no listing ever
#: shows it (:func:`artifacts._keys.is_plumbing` hides it).
STAGING_ROOT_NAME = ".staging"

#: The default directory name beside the workspace root, mirroring the
#: snapshot member's ``lake/`` default: §9.2 draws ``/artifacts`` as the
#: store's own root, and a workspace that configured nothing gets its
#: artifacts beside its lake rather than scattered into the cwd.
DEFAULT_ROOT_NAME = "artifacts"


class ArtifactStore:
    """Persists and reads the §9.2 tree: one directory per node.

    Bound to a root at construction (see :meth:`from_env`).  All paths
    the store touches live under that root: ``<campaign_id>/<node_id>``
    for the published directories, ``.staging`` for the write path's
    plumbing.  Construction performs no I/O; directories are created on
    demand by the operations that need them.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if isinstance(root, str) and not root.strip():
            # Path("") would silently become "." — persisting into the
            # current directory is never what a caller meant.
            raise ArtifactStoreError(
                "the artifact root must be a non-empty path — got an "
                "empty string; §9.2's store is rooted somewhere, and a "
                "root of '.' would scatter node directories into "
                "whatever directory the process happened to start in"
            )
        try:
            self._root = Path(root).expanduser()
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreError(
                f"the artifact root must be a usable path — got "
                f"{root!r}: {exc}"
            ) from exc
        self._staging = self._root / STAGING_ROOT_NAME

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> ArtifactStore:
        """Resolve the artifact root the way the rest of the system states it.

        ``ARTIFACT_ROOT`` wins when set (an empty or whitespace-only
        value counts as unset, mirroring the shared fixtures' treatment
        of an empty ``TEST_DATABASE_URL``).  Otherwise the root defaults
        to ``artifacts/`` beside the workspace root — located via the
        factory's workspace discovery rather than a hard-coded guess,
        so the default can never silently point somewhere the
        declaration does not cover.  With neither available the store
        refuses to guess: raising a clear error beats persisting into
        ``/``, because a node directory written to a wrong root is one
        the tree store's ``artifact_uri`` cannot find again.
        """
        source = os.environ if env is None else env
        raw = source.get(ARTIFACT_ROOT_ENV, "").strip()
        if raw:
            return cls(Path(raw))
        workspace_root = find_workspace_root()
        if workspace_root is not None:
            return cls(workspace_root / DEFAULT_ROOT_NAME)
        raise ArtifactStoreError(
            f"{ARTIFACT_ROOT_ENV} is not set and no uv workspace root "
            "was found above this package; set ARTIFACT_ROOT to the "
            "artifact store's root (§9.2)"
        )

    # -- Paths --------------------------------------------------------------

    @property
    def root(self) -> Path:
        """The store's root — §9.2's ``/artifacts``, wherever it is mounted."""
        return self._root

    @property
    def staging_root(self) -> Path:
        """The hidden plumbing root: staged writes, and nothing readable.

        Exposed for operators and tests that need to see (or clean) the
        write path's working area; no read surface of this store ever
        lists it, and no key can address into it.
        """
        return self._staging

    def campaign_root(self, campaign_id: str) -> Path:
        """The campaign's subtree root — ``<root>/<campaign_id>``, purely.

        Resolves the first segment of the key and creates nothing: a
        campaign exists in the store exactly when one of its nodes does,
        so this directory is created (as a node directory's parent) by
        the write path, never on its own.
        """
        return campaign_directory(self._root, campaign_id)

    def node_directory(self, campaign_id: str, node_id: str) -> Path:
        """Persist and return the node's one directory, keyed by both ids.

        The feature's sentence as an operation: the directory at
        ``<root>/<campaign_id>/<node_id>`` comes to exist — created with
        its campaign parent when absent — and the node's key now
        addresses a real directory.  Idempotent by construction: the
        address is a pure function of the two keys, so asking again
        returns the same directory and creates nothing new.  An empty
        directory is a legitimate persisted state here — a node whose
        files have not been staged yet, or whose writer failed before
        committing anything; the read side reports it honestly as a
        node with no files rather than papering over it.
        """
        target = node_path(self._root, campaign_id, node_id)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactStoreError(
                f"could not persist the artifact directory for node "
                f"{node_id!r} of campaign {campaign_id!r} at {target}: "
                f"{exc}"
            ) from exc
        return target

    # -- The staged write path ----------------------------------------------

    def write(
        self,
        campaign_id: str,
        node_id: str,
        filename: str,
        data: bytes | bytearray | memoryview | str,
    ) -> Path:
        """Stage one file of the node's artifact; return the staged path.

        The staged write half of the publication path: the bytes land
        under ``<root>/.staging/<campaign_id>/<node_id>/<filename>``,
        invisible to every read, until :meth:`commit` publishes the
        staged set as the node's directory.  Staging the same filename
        twice keeps the last bytes — the staged set is a mapping, one
        entry per filename, exactly like the node's published directory
        will be.  ``data`` may be :class:`bytes`-like or :class:`str`
        (encoded UTF-8); anything else is refused, because a file that
        cannot be written as bytes is a payload the encoding features
        (170-173), not the directory store, are responsible for
        rendering.
        """
        staged_file = self._staged_directory(campaign_id, node_id) / str(
            filename
        )
        validate_filename(filename)
        if isinstance(data, str):
            payload = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray, memoryview)):
            payload = bytes(data)
        else:
            raise ArtifactStoreError(
                f"an artifact file holds bytes — got {type(data).__name__} "
                f"for {filename!r} of node {node_id!r}; render the value "
                "to bytes (or UTF-8 text) before handing it to the store"
            )
        try:
            staged_file.parent.mkdir(parents=True, exist_ok=True)
            staged_file.write_bytes(payload)
        except OSError as exc:
            raise ArtifactStoreError(
                f"could not stage {filename!r} for node {node_id!r} of "
                f"campaign {campaign_id!r} at {staged_file}: {exc}"
            ) from exc
        return staged_file

    def staged(self, campaign_id: str, node_id: str) -> tuple[str, ...]:
        """The filenames staged for the node so far, sorted.

        The transaction's visibility: what a :meth:`commit` would
        publish for this node right now.  Empty when nothing is staged.
        """
        directory = self._staged_directory(campaign_id, node_id)
        if not directory.is_dir():
            return ()
        return tuple(sorted(entry.name for entry in directory.iterdir()))

    def commit(self, campaign_id: str, node_id: str) -> Path:
        """Publish the staged set as the node's directory; return it.

        The commit point.  The staged directory is renamed onto
        ``<root>/<campaign_id>/<node_id>`` — atomic on POSIX, so no
        reader observes a partial directory — replacing any prior
        version of the node's artifact wholesale: after a refresh the
        node carries exactly the files the staging area held, never a
        splice of two runs (a file the retry did not stage is gone,
        which is what "refresh" means for a directory that is one
        unit).  Refreshing moves the prior version aside and removes it
        once the new one holds the address; POSIX cannot swap
        directories in one step, so the address is briefly empty
        between the two renames — never two directories, never a
        partial one.

        Refuses, leaving everything as it was, when nothing is staged
        (an empty replace would silently delete a node's artifact) or
        when something other than a directory already occupies the
        node's address.  Key failures
        (:class:`~artifacts._errors.ArtifactKeyError`) refuse before
        the filesystem is touched at all.
        """
        target = node_path(self._root, campaign_id, node_id)
        staged_dir = self._staged_directory(campaign_id, node_id)
        if not staged_dir.is_dir() or not any(staged_dir.iterdir()):
            raise ArtifactStoreError(
                f"nothing is staged for node {node_id!r} of campaign "
                f"{campaign_id!r}, so there is no artifact directory to "
                "commit; stage files with write() first — an empty "
                "commit would replace the node's artifact with nothing"
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not target.is_dir():
                raise ArtifactStoreError(
                    f"the address of node {node_id!r} of campaign "
                    f"{campaign_id!r} — {target} — is occupied by "
                    "something that is not a directory; the node's "
                    "artifact needs its directory, and the store will "
                    "not remove a foreign object to make room"
                )
            if target.is_dir():
                aside = (
                    self._staging
                    / str(campaign_id)
                    / f".replaced-{node_id}-{uuid.uuid4().hex[:12]}"
                )
                aside.parent.mkdir(parents=True, exist_ok=True)
                target.rename(aside)
                try:
                    staged_dir.rename(target)
                except OSError:
                    # Put the prior version back before refusing: the
                    # refresh failed, and the node's current artifact is
                    # not the failure's to delete.
                    aside.rename(target)
                    raise
                shutil.rmtree(aside, ignore_errors=True)
            else:
                staged_dir.rename(target)
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError(
                f"could not publish the artifact directory of node "
                f"{node_id!r} of campaign {campaign_id!r} at {target}: "
                f"{exc}"
            ) from exc
        self._prune_empty_parents(staged_dir)
        return target

    def discard(self, campaign_id: str, node_id: str) -> None:
        """Roll the node's staged writes back — nothing published, nothing kept.

        The rollback half of the staged path: whatever :meth:`write`
        staged for the node vanishes, and any published directory the
        node already holds is untouched.  Idempotent, because a rollback
        a caller cannot repeat safely is a rollback a retrying pipeline
        will skip — and skipping it is how a half-node lingers.
        """
        staged_dir = self._staged_directory(campaign_id, node_id)
        if staged_dir.is_dir():
            try:
                shutil.rmtree(staged_dir)
            except OSError as exc:
                raise ArtifactStoreError(
                    f"could not roll back the staged writes of node "
                    f"{node_id!r} of campaign {campaign_id!r} at "
                    f"{staged_dir}: {exc}"
                ) from exc
        self._prune_empty_parents(staged_dir)

    # -- The read side --------------------------------------------------------

    def has_node(self, campaign_id: str, node_id: str) -> bool:
        """Whether the node's artifact directory is persisted.

        ``True`` for an empty node directory too: "persisted" is a fact
        about the directory existing, not about the files inside it —
        an empty directory is the honest state of a node whose writer
        has not committed anything, and a caller that needs the files
        asks :meth:`files`.
        """
        return node_path(self._root, campaign_id, node_id).is_dir()

    def campaign_ids(self) -> tuple[str, ...]:
        """Every campaign holding at least one entry, sorted.

        The first key level, read back: the non-hidden directories
        directly under the root.  The store's plumbing (``.staging``,
        refresh asides) never appears — a campaign cannot be keyed into
        that namespace and the listing refuses to show it even if some
        other hand put it there.  An empty store answers ``()``.
        """
        if not self._root.is_dir():
            return ()
        return tuple(
            sorted(
                entry.name
                for entry in self._root.iterdir()
                if entry.is_dir() and not is_plumbing(entry.name)
            )
        )

    def node_ids(self, campaign_id: str) -> tuple[str, ...]:
        """Every node the campaign holds a directory for, sorted.

        The second key level, read back.  A campaign nothing was
        persisted under answers ``()`` — an unknown campaign and a
        campaign with no nodes are the same fact to a store keyed by
        nodes, and a listing is not a lookup (:meth:`has_node` answers
        the lookup).
        """
        campaign = campaign_directory(self._root, campaign_id)
        if not campaign.is_dir():
            return ()
        return tuple(
            sorted(
                entry.name
                for entry in campaign.iterdir()
                if entry.is_dir() and not is_plumbing(entry.name)
            )
        )

    def files(self, campaign_id: str, node_id: str) -> tuple[str, ...]:
        """The node's artifact files, sorted — the §9.2 names it holds.

        The flat files this store persisted directly inside the node's
        one directory.  Refuses with
        :class:`~artifacts._errors.ArtifactNotFoundError` when the node
        holds no directory: "the node has no files" and "the node has
        no artifact" are different facts, and conflating them would let
        an empty directory pass for a missing one (or worse, a missing
        node pass for an empty artifact).
        """
        target = node_path(self._root, campaign_id, node_id)
        if not target.is_dir():
            raise ArtifactNotFoundError(
                f"no artifact directory is persisted for node {node_id!r} "
                f"of campaign {campaign_id!r} (looked for {target}); the "
                "node was never persisted, or its write was discarded "
                "before committing"
            )
        return tuple(
            sorted(
                entry.name
                for entry in target.iterdir()
                if entry.is_file()
            )
        )

    def read(self, campaign_id: str, node_id: str, filename: str) -> bytes:
        """Read one file of the node's artifact back, as bytes.

        The read side replay stands on: the same store that persisted
        the directory answers for its contents, keying by the node's
        two ids and the flat filename.  Refuses with
        :class:`~artifacts._errors.ArtifactNotFoundError` when the node
        holds no directory or the directory holds no such file — the
        two refusals name which half is missing, so a reconciliation
        sweep can tell a node that never persisted from one whose
        artifact is short one file.
        """
        validate_filename(filename)
        target = node_path(self._root, campaign_id, node_id)
        if not target.is_dir():
            raise ArtifactNotFoundError(
                f"no artifact directory is persisted for node {node_id!r} "
                f"of campaign {campaign_id!r} (looked for {target}), so "
                f"there is no {filename!r} to read"
            )
        file = target / str(filename)
        if not file.is_file():
            raise ArtifactNotFoundError(
                f"the artifact directory of node {node_id!r} of campaign "
                f"{campaign_id!r} holds no {filename!r}; it holds "
                f"{', '.join(self.files(campaign_id, node_id)) or 'no files'}"
            )
        try:
            return file.read_bytes()
        except OSError as exc:
            raise ArtifactStoreError(
                f"could not read {filename!r} of node {node_id!r} of "
                f"campaign {campaign_id!r} at {file}: {exc}"
            ) from exc

    # -- Plumbing -------------------------------------------------------------

    def _staged_directory(self, campaign_id: str, node_id: str) -> Path:
        """The node's staging directory — hidden, and addressed by nobody.

        Deterministic per node (not per write), so the files of one
        node's staged set accumulate together and a commit publishes
        them as the one directory they were always going to be.  Also
        the staging path's key gate: both segments are validated here,
        so every public operation that reaches for staging (``write``,
        ``staged``, ``commit``, ``discard``) refuses a malformed key
        before the filesystem is touched.
        """
        validate_campaign_id(campaign_id)
        validate_node_id(node_id)
        return self._staging / campaign_id / node_id

    def _prune_empty_parents(self, consumed: Path) -> None:
        """Remove now-empty staging parents, best-effort.

        A commit consumes the staged directory and a rollback removes
        it; the ``.staging/<campaign_id>`` parent (and ``.staging``
        itself) may then be empty, and an empty plumbing directory is
        litter — the next write recreates whatever it needs.  Best-effort
        by design: a prune that failed would be noise on the path of an
        operation that already succeeded.
        """
        for parent in (consumed.parent, self._staging):
            try:
                parent.rmdir()
            except OSError:
                break


def artifact_uri(store: ArtifactStore, campaign_id: str, node_id: str) -> str:
    """The node directory's address as the tree store's ``artifact_uri``.

    §9.1's ``node`` table carries ``artifact_uri TEXT NOT NULL`` — the
    one string a row holds that names where the node's artifact bytes
    live.  This is the spelling this store answers to: a ``file:`` URI
    of the node's directory, percent-encoded so any key the layout
    accepts round-trips.  Pure — it resolves the address without
    requiring the directory to exist yet, because the row that carries
    the URI and the directory it names are written by the two halves of
    one step (feature 85's tree write and artifact commit), and neither
    half is first.
    """
    target = node_path(store.root, campaign_id, node_id)
    return "file://" + quote(str(target))
