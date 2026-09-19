"""The recomputation registry — feature 39.

app_spec.xml feature 39: *"System persists a recomputation flag on every
score affected by a snapshot change, while the discovery tree structure
survives intact."* This module is the snapshot side of that sentence, the
counterpart to feature 38's new hash.

The architecture's model (docs/nullius-tech-architecture.md §4.4, §15, the
failure-mode table row *"Snapshot extended → new ``snapshot_hash`` … Tree
*structure* survives; scores do not"*): a snapshot change is the event that
turns feature 38's new identity into a recomputation signal. Scores live in
the derived zone keyed by the ``snapshot_hash`` they were computed over, and
each is anchored to a node in a content-addressed discovery tree. When the
lake is extended the new hash is a cache miss; this registry is what makes
that miss *visible and durable* rather than silent — it flips a persisted
``recompute`` flag on every score the old hash held, records the supersession
in an append-only audit, and **leaves the tree's nodes and edges exactly as
they were**. The tree structure survives; the scores under it do not.

Three nouns, and why each is this module's to hold:

* **A score** — ``register_score`` anchors a score id to the discovery-tree
  node it decorates and to the ``snapshot_hash`` it was computed over. The
  hash is the score's provenance (§4.4): the only thing that lets a later
  snapshot change find it. A score carries an optional ``node_id`` so the
  registry can hold the tree's shape too, but the score's *value* is the
  derived zone's own business and is deliberately never stored here — this
  registry flags, it does not score.
* **A node** — ``register_node`` records the discovery tree's structure: a
  node id, its parents, its type. The edges are what "the tree structure
  survives intact" is a claim about: a snapshot change must not disturb them.
  Registration is idempotent in structure — re-registering a node restates
  its parents, never appends a duplicate edge — so the tree is a set of
  facts, not a log of events.
* **A snapshot change** — ``record_snapshot_change`` is the event. It reads
  every score the lake persisted under ``old_hash``, flips each to
  ``recompute=True`` with the ``new_hash`` that superseded it, appends one
  supersession record to the audit, and touches nothing else. The tree's
  nodes and edges are not rewritten; only the scores' flags move.

**The registry is persisted to the lake, not held in memory.** It lives at
``<lake>/recomputation.json`` beside ``snapshots/`` and ``staging/`` (§4.2's
layout), so a snapshot change flagged by one process is read back by another,
and the flag outlives the process that set it. Persistence is the whole point
of "System *persists* a recomputation flag": an in-memory flag is not
persisted, and a flag that vanishes on restart is a flag that silently
re-uses stale scores. The file is written atomically (a temp file plus
``os.replace``), so a crash mid-write leaves the previous, valid registry
rather than a half-written one.

**The registry is a snapshot-change ledger, not a score store.** It records
*which* scores are flagged and *why* (the supersession audit), not what any
score computed to. That keeps it honest about its boundary: it is the
invalidation signal, and the derived zone owns the recomputation the signal
points at.

**A snapshot change is verified against the lake, not believed on arrival.**
The registry itself is agnostic to which hashes are real — it only knows the
scores it was told about. The service that grounds it (:meth:`SnapshotService
.record_snapshot_change`) checks that both hashes name snapshots this lake
actually seals before the change is applied, because a recomputation flag
anchored to a hash the lake does not hold would flag scores that do not
exist. That check is the service's; the registry raises
:class:`~snapshot.SnapshotRecomputationError` when the service hands it a
change whose old hash holds no scores to flag.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

from ._errors import SnapshotRecomputationError

__all__ = [
    "RECOMPUTATION_NAME",
    "RecomputationRegistry",
    "ScoreRecord",
    "SupersessionRecord",
]

#: The registry's file name inside the lake root (§4.2 layout), beside
#: ``snapshots/`` and ``staging/``. A lake-level record, not a per-snapshot
#: one: a snapshot change relates one snapshot to the next, so the ledger
#: that carries it must span snapshots.
RECOMPUTATION_NAME = "recomputation.json"

#: The version of the registry format this package writes and reads. Bumped
#: only deliberately — every consumer reads the same file.
_REGISTRY_VERSION = 1

_UTC = timezone.utc


def _now() -> datetime:
    """The current instant, timezone-aware UTC, for audit timestamps."""
    return datetime.now(_UTC).replace(microsecond=0)


# -- The records -------------------------------------------------------------


@dataclass(frozen=True)
class ScoreRecord:
    """A score anchored to a discovery-tree node and a snapshot hash.

    The three coordinates a score needs to be found by a later snapshot
    change: *which* score (``score_id``), *where in the tree* it decorates
    (``node_id``), and *which bytes* it was computed over (``snapshot_hash``).
    The fourth coordinate — the flag — is derived: ``recompute`` starts
    ``False`` and a snapshot change over ``snapshot_hash`` turns it ``True``.
    A fifth field, ``superseded_by``, names the hash that superseded the one
    this score was computed over, so a flagged score carries its own reason
    without a separate lookup.
    """

    #: The score's id within the derived zone — opaque here.
    score_id: str
    #: The snapshot hash the score was computed over (§4.4 provenance).
    snapshot_hash: str
    #: The discovery-tree node the score decorates, or ``None`` for a score
    #: the tree does not decorate (a campaign-level aggregate, say).
    node_id: Optional[str]
    #: Whether a snapshot change has flagged this score for recomputation.
    recompute: bool = False
    #: The hash that superseded ``snapshot_hash``, set when flagged.
    superseded_by: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.score_id, str) or not self.score_id:
            raise SnapshotRecomputationError(
                "score_id must be a non-empty string"
            )
        if not isinstance(self.snapshot_hash, str) or not self.snapshot_hash:
            raise SnapshotRecomputationError(
                "snapshot_hash must be a non-empty string"
            )
        if self.node_id is not None and (
            not isinstance(self.node_id, str) or not self.node_id
        ):
            raise SnapshotRecomputationError(
                "node_id must be a non-empty string or null"
            )

    def to_dict(self) -> dict:
        """The serialisable form — exactly the fields, no extras."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ScoreRecord":
        """Rebuild a score from its serialisable form, refusing drift."""
        try:
            return cls(
                score_id=data["score_id"],
                snapshot_hash=data["snapshot_hash"],
                node_id=data["node_id"],
                recompute=data["recompute"],
                superseded_by=data["superseded_by"],
            )
        except (KeyError, TypeError) as exc:
            raise SnapshotRecomputationError(
                f"corrupt score record (missing or malformed field: {exc})"
            ) from exc


@dataclass(frozen=True)
class SupersessionRecord:
    """One snapshot change in the audit: old hash, new hash, when, how many."""

    #: The hash the superseded scores were computed over.
    old_hash: str
    #: The hash that superseded it — the extended lake's new identity.
    new_hash: str
    #: When the change was recorded, timezone-aware UTC.
    recorded_at: datetime
    #: How many scores the change flagged. The audit counts the effect, so a
    #: reader sees how widely each snapshot change reached.
    flagged_scores: int

    def to_dict(self) -> dict:
        return {
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "recorded_at": self.recorded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "flagged_scores": self.flagged_scores,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SupersessionRecord":
        try:
            return cls(
                old_hash=data["old_hash"],
                new_hash=data["new_hash"],
                recorded_at=datetime.strptime(
                    data["recorded_at"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=_UTC),
                flagged_scores=data["flagged_scores"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotRecomputationError(
                f"corrupt supersession record ({exc})"
            ) from exc


@dataclass(frozen=True)
class NodeRecord:
    """A discovery-tree node: its id, its parents, its type.

    The tree's *structure* — the thing feature 39 says survives a snapshot
    change intact. A node names its parents (the edges) and a type drawn from
    the derived zone's own vocabulary (opaque here). Registration is
    idempotent in structure: the parents are stored as a sorted, de-duplicated
    tuple, so re-registering a node restates its edges rather than appending
    them, and the tree is a set of facts, not an event log.
    """

    #: The node's id within the discovery tree — opaque here.
    node_id: str
    #: The parent node ids — the edges into this node.
    parents: tuple[str, ...]
    #: The node type, from the derived zone's vocabulary. Opaque here.
    node_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise SnapshotRecomputationError(
                "node_id must be a non-empty string"
            )
        if not isinstance(self.node_type, str):
            raise SnapshotRecomputationError(
                "node_type must be a string"
            )
        if not isinstance(self.parents, Iterable) or any(
            not isinstance(parent, str) or not parent for parent in self.parents
        ):
            raise SnapshotRecomputationError(
                "parents must be an iterable of non-empty strings"
            )
        # Structural canonicalisation: sorted, de-duplicated, immutable.
        object.__setattr__(
            self, "parents", tuple(sorted(set(self.parents)))
        )

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "parents": list(self.parents),
            "node_type": self.node_type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "NodeRecord":
        try:
            return cls(
                node_id=data["node_id"],
                parents=data["parents"],
                node_type=data["node_type"],
            )
        except (KeyError, TypeError) as exc:
            raise SnapshotRecomputationError(
                f"corrupt node record ({exc})"
            ) from exc


# -- The registry ------------------------------------------------------------


class RecomputationRegistry:
    """Persists the recomputation flag on scores, and the tree that holds them.

    The store behind feature 39. It holds three things, each through the
    record types above: the scores (with their ``recompute`` flags), the
    discovery-tree nodes they decorate, and the append-only supersession
    audit that records every snapshot change. Everything is persisted to
    ``<lake>/recomputation.json`` and re-read on construction, so the flag a
    snapshot change sets is the flag the next process reads.

    The registry never touches a score's value or a tree node's meaning — it
    holds only the addressing (which score, which node, which hash) and the
    flag. It is the invalidation signal, and the derived zone owns the
    recomputation the signal points at.
    """

    def __init__(self, lake_root: Union[str, os.PathLike[str]]) -> None:
        self._path = Path(lake_root).expanduser() / RECOMPUTATION_NAME
        self._scores: dict[str, ScoreRecord] = {}
        self._nodes: dict[str, NodeRecord] = {}
        self._supersessions: list[SupersessionRecord] = []
        self._load()

    # -- Construction --------------------------------------------------------

    def _load(self) -> None:
        """Read the persisted registry, or start empty if none exists yet.

        A missing file is a fresh lake — an empty registry, not an error. A
        present-but-unreadable file is refused loudly: a corrupt registry is
        worse than none, because it would silently drop every flag it held.
        """
        if not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text("utf-8"))
        except ValueError as exc:
            raise SnapshotRecomputationError(
                f"{RECOMPUTATION_NAME} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SnapshotRecomputationError(
                f"{RECOMPUTATION_NAME} must be a JSON object, got "
                f"{type(payload).__name__}"
            )
        version = payload.get("version")
        if version != _REGISTRY_VERSION:
            raise SnapshotRecomputationError(
                f"{RECOMPUTATION_NAME} declares version {version!r}; this "
                f"package reads version {_REGISTRY_VERSION}"
            )
        self._scores = {
            key: ScoreRecord.from_dict(value)
            for key, value in payload.get("scores", {}).items()
        }
        self._nodes = {
            key: NodeRecord.from_dict(value)
            for key, value in payload.get("nodes", {}).items()
        }
        self._supersessions = [
            SupersessionRecord.from_dict(value)
            for value in payload.get("supersessions", [])
        ]

    def _flush(self) -> None:
        """Write the registry atomically: temp file plus ``os.replace``.

        A crash mid-write leaves the previous file in place — ``os.replace``
        is atomic on POSIX, so a reader never observes a half-written
        registry. The lake root is created on demand; the first write brings
        the file into being.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _REGISTRY_VERSION,
            "scores": {
                key: value.to_dict() for key, value in self._scores.items()
            },
            "nodes": {
                key: value.to_dict() for key, value in self._nodes.items()
            },
            "supersessions": [value.to_dict() for value in self._supersessions],
        }
        directory = self._path.parent
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".recomputation-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_name, self._path)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    # -- Paths ---------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Where this registry persists — ``<lake>/recomputation.json``."""
        return self._path

    # -- Scores --------------------------------------------------------------

    def register_score(
        self,
        score_id: str,
        snapshot_hash: str,
        *,
        node_id: Optional[str] = None,
    ) -> ScoreRecord:
        """Anchor a score to a node and the snapshot hash it was computed over.

        Idempotent by score id: re-registering the same score restates its
        coordinates and clears any flag a prior registration set, so a fresh
        computation of a previously-flagged score returns it to
        ``recompute=False`` — the derived zone re-registered the score after
        recomputing it. A score registered under a *new* hash after a change
        simply adds a second record; each hash keeps its own flag.
        """
        record = ScoreRecord(
            score_id=score_id,
            snapshot_hash=snapshot_hash,
            node_id=node_id,
        )
        self._scores[score_id] = record
        self._flush()
        return record

    def score(self, score_id: str) -> Optional[ScoreRecord]:
        """The record for one score, or ``None`` if it was never registered."""
        return self._scores.get(score_id)

    def scores_for_snapshot(self, snapshot_hash: str) -> list[ScoreRecord]:
        """Every score the lake persisted under a given snapshot hash.

        What a snapshot change reads to decide which scores to flag: the
        scores whose provenance hash is ``snapshot_hash``. Empty when no
        score was computed over that hash — the case the service refuses on,
        because a change against a hash the lake holds no scores for flags
        nothing.
        """
        return [
            record
            for record in self._scores.values()
            if record.snapshot_hash == snapshot_hash
        ]

    def flagged_scores(self) -> list[ScoreRecord]:
        """Every score currently flagged for recomputation, sorted by id."""
        return sorted(
            (record for record in self._scores.values() if record.recompute),
            key=lambda record: record.score_id,
        )

    def needs_recomputation(self, score_id: str) -> bool:
        """Whether one score has been flagged — the derived zone's query.

        A score the registry does not know is reported as not needing
        recomputation: an unknown score was never anchored to a snapshot, so
        no change can have flagged it, and treating the unknown as flagged
        would flag scores that do not exist.
        """
        record = self._scores.get(score_id)
        return record is not None and record.recompute

    # -- Tree nodes ----------------------------------------------------------

    def register_node(
        self,
        node_id: str,
        *,
        parents: Iterable[str] = (),
        node_type: str = "",
    ) -> NodeRecord:
        """Record a discovery-tree node and its edges.

        Idempotent in structure: the parents are stored sorted and
        de-duplicated, so re-registering a node restates its edges rather than
        appending them. The tree is a set of facts — a snapshot change does
        not rewrite it.
        """
        record = NodeRecord(
            node_id=node_id, parents=tuple(parents), node_type=node_type
        )
        self._nodes[node_id] = record
        self._flush()
        return record

    def node(self, node_id: str) -> Optional[NodeRecord]:
        """The record for one tree node, or ``None`` if it is unknown."""
        return self._nodes.get(node_id)

    def tree_nodes(self) -> list[NodeRecord]:
        """Every tree node the registry holds, sorted by id."""
        return sorted(self._nodes.values(), key=lambda node: node.node_id)

    def edges(self) -> list[tuple[str, str]]:
        """Every parent→child edge in the tree, sorted.

        The structure that feature 39 says survives a snapshot change intact:
        a snapshot change never adds or removes an edge, so this list is the
        same before and after.
        """
        return sorted(
            (parent, node.node_id)
            for node in self._nodes.values()
            for parent in node.parents
        )

    # -- Snapshot changes ----------------------------------------------------

    def record_snapshot_change(
        self,
        old_hash: str,
        new_hash: str,
        *,
        recorded_at: Optional[datetime] = None,
    ) -> SupersessionRecord:
        """Flag every score under ``old_hash`` as superseded by ``new_hash``.

        The event feature 39 is about. It reads the scores the lake persisted
        under ``old_hash`` (``scores_for_snapshot``), flips each to
        ``recompute=True`` carrying ``superseded_by=new_hash``, appends one
        record to the supersession audit, and writes the registry once. It
        touches nothing else: the tree's nodes and edges are not rewritten,
        and scores under any other hash keep their flags. The tree structure
        survives; the scores under it do not.

        A change against an ``old_hash`` the lake holds no scores for is
        refused: there is nothing to flag, and recording a supersession with
        no effect would be a flag anchored to a hash the lake does not hold —
        exactly the dishonesty the feature guards against.
        """
        if not isinstance(old_hash, str) or not old_hash:
            raise SnapshotRecomputationError(
                "old_hash must be a non-empty string"
            )
        if not isinstance(new_hash, str) or not new_hash:
            raise SnapshotRecomputationError(
                "new_hash must be a non-empty string"
            )
        if old_hash == new_hash:
            raise SnapshotRecomputationError(
                "a snapshot change must name two different hashes; old_hash and "
                "new_hash are both "
                f"{old_hash!r} — a snapshot does not supersede itself"
            )
        affected = self.scores_for_snapshot(old_hash)
        if not affected:
            raise SnapshotRecomputationError(
                f"no scores are anchored to snapshot_hash {old_hash!r}; a "
                "snapshot change flags the scores a snapshot holds, and this "
                "one holds none — record the scores before recording the change"
            )
        for record in affected:
            self._scores[record.score_id] = ScoreRecord(
                score_id=record.score_id,
                snapshot_hash=record.snapshot_hash,
                node_id=record.node_id,
                recompute=True,
                superseded_by=new_hash,
            )
        supersession = SupersessionRecord(
            old_hash=old_hash,
            new_hash=new_hash,
            recorded_at=(recorded_at or _now()).replace(microsecond=0),
            flagged_scores=len(affected),
        )
        self._supersessions.append(supersession)
        self._flush()
        return supersession

    def supersessions(self) -> list[SupersessionRecord]:
        """The append-only audit of snapshot changes, oldest first."""
        return list(self._supersessions)

    # -- Reporting -----------------------------------------------------------

    def tree_structure(self) -> dict[str, list[str]]:
        """The tree's adjacency, node id to sorted parent ids.

        A read-only view of the structure that survives a snapshot change,
        for an operator or an audit that wants to confirm the tree was not
        disturbed.
        """
        return {
            node.node_id: list(node.parents)
            for node in self.tree_nodes()
        }
