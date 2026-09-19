"""Feature 54 as a persisted ledger: a feature_version bump flags the dependent
scores the old version held, emitting the same recomputation signal a snapshot
change (feature 39) produces.

app_spec.xml, "Point-in-Time Feature Store", feature 54: *System treats a
feature_version bump as invalidating dependent scores, which emits the same
recomputation signal an evaluator change produces.*  This module is the
feature-store half of that sentence, the exact counterpart to feature 39's
:class:`~snapshot.RecomputationRegistry` on the snapshot side.

The architecture's model is feature 39's, transposed from snapshot to version
(docs/nullius-tech-architecture.md §4.4, the failure-mode table row *"Feature
definition changed → new ``feature_version`` … Rows survive; dependents do
not"*):

* Feature 39's invalidation trigger is a *new ``snapshot_hash``* — the lake was
  extended, so every score anchored to the old hash is a content-addressed miss
  and must be recomputed.  This module's trigger is a *new ``feature_version``*
  for a ``feature_name`` — feature 53's mechanism, a changed definition written
  *beside* the old rows, never on top of them — so every dependent score
  anchored to the old version is stale and must be recomputed.
* Feature 39 anchors a score by ``(score_id, snapshot_hash)``; this module
  anchors a *dependent score* by ``(score_id, feature_name, feature_version)``.
  A dependent score is any value the derived zone computed from a feature at a
  particular version — a signal node that read version 1's rows, a regime label
  fit on version 1's metrics — and whose value therefore cannot survive a
  version bump untouched.  The version is the dependent's provenance: the only
  thing that lets a later bump find it.
* Feature 39's ``record_snapshot_change(old, new)`` flips each score under
  ``old`` to ``recompute=True`` carrying ``superseded_by=new`` and appends a
  supersession to an append-only audit, leaving the discovery tree's nodes and
  edges intact.  This module's ``record_version_change(name, old, new)`` does
  the identical thing over the dependent scores under ``(name, old)``, carrying
  ``superseded_by=new`` — and touches nothing else.  The version-1 rows feature
  53 leaves beside the new definition are not rewritten; only the dependents'
  flags move.  The rows survive; the dependents under them do not.

So the signal this module emits is *the same shape* feature 39 emits — a
per-score ``recompute`` flag, a ``superseded_by`` reason, an append-only audit of
the changes, and a ``needs_recomputation(score_id)`` query the derived zone
polls — only the anchor changed from snapshot to version.  A dependent score
that was flagged and then recomputed against the new version is re-registered,
which clears its flag, mirroring feature 39's re-registration semantics: the
derived zone re-registered the score after recomputing it.

**The registry is persisted to the lake, not held in memory.**  It lives at
``<lake>/feature_version_recomputation.json`` beside feature 39's
``recomputation.json`` (§4.2's layout), so a version bump flagged by one process
is read back by another, and the flag outlives the process that set it.
Persistence is the whole point of "System *treats* a version bump as
invalidating": an in-memory flag is not treated, and a flag that vanishes on
restart is a flag that silently re-uses a stale dependent — exactly the reuse
the feature guards against.  The file is written atomically (a temp file plus
``os.replace``), so a crash mid-write leaves the previous, valid registry rather
than a half-written one.

**The registry is a version-change ledger, not a feature store.**  It records
*which* dependent scores are flagged and *why* (the version-change audit), not
what any feature or score computed to.  That keeps it honest about its boundary:
it is the invalidation signal, and the derived zone owns the recomputation the
signal points at.  It knows only the dependent scores it was told about — a
version change against a version the registry holds no dependents for is
refused, because there is nothing to flag and recording a change with no effect
would be a signal anchored to a version nothing depends on.

Stdlib-only, like ``keys.py`` and ``store.py``: import-safe everywhere, replay
included.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

from .keys import FeatureKeyError, _validated_component
from ._errors import VersionRecomputationError

__all__ = [
    "DEPENDENT_RECOMPUTATION_NAME",
    "DependentScore",
    "VersionChange",
    "VersionRecomputationRegistry",
]

#: The registry's file name inside the lake root (§4.2 layout), beside feature
#: 39's ``recomputation.json``.  A lake-level record, not a per-snapshot or
#: per-feature one: a version change relates one version to the next for a
#: feature, so the ledger that carries it must span versions.
DEPENDENT_RECOMPUTATION_NAME = "feature_version_recomputation.json"

#: The version of the registry format this package writes and reads.  Bumped
#: only deliberately — every consumer reads the same file.
_REGISTRY_VERSION = 1

_UTC = timezone.utc


def _now() -> datetime:
    """The current instant, timezone-aware UTC, for audit timestamps."""
    return datetime.now(_UTC).replace(microsecond=0)


# -- The records -------------------------------------------------------------


@dataclass(frozen=True)
class DependentScore:
    """A dependent score anchored to a feature and the version it was read from.

    The three coordinates a dependent score needs to be found by a later version
    bump: *which* score (``score_id``), *which feature* (``feature_name``), and
    *which version* it was computed from (``feature_version``).  The version is
    the dependent's provenance (feature 48): the only thing that lets a later
    bump find it.  The fourth coordinate — the flag — is derived: ``recompute``
    starts ``False`` and a version change over ``(feature_name,
    feature_version)`` turns it ``True``.  A fifth field, ``superseded_by``,
    names the version that superseded the one this score was read from, so a
    flagged dependent carries its own reason without a separate lookup.
    """

    #: The score's id within the derived zone — opaque here.
    score_id: str
    #: The feature_name the score depends on (feature 48's key component).
    feature_name: str
    #: The feature_version the score was computed from (§4.4 provenance).
    feature_version: str
    #: Whether a version bump has flagged this score for recomputation.
    recompute: bool = False
    #: The version that superseded ``feature_version``, set when flagged.
    superseded_by: Optional[str] = None

    def __post_init__(self) -> None:
        # feature_name/feature_version are key components: validate them exactly
        # as FeatureKey construction does, so the registry can never hold a
        # dependent anchored to an address that could never be a real key.
        object.__setattr__(
            self,
            "feature_name",
            _validated_component("feature_name", self.feature_name),
        )
        object.__setattr__(
            self,
            "feature_version",
            _validated_component("feature_version", self.feature_version),
        )
        if not isinstance(self.score_id, str) or not self.score_id:
            raise VersionRecomputationError(
                "score_id must be a non-empty string"
            )

    def to_dict(self) -> dict:
        """The serialisable form — exactly the fields, no extras."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DependentScore":
        """Rebuild a dependent score from its serialisable form, refusing drift."""
        try:
            return cls(
                score_id=data["score_id"],
                feature_name=data["feature_name"],
                feature_version=data["feature_version"],
                recompute=data["recompute"],
                superseded_by=data["superseded_by"],
            )
        except (KeyError, TypeError) as exc:
            raise VersionRecomputationError(
                f"corrupt dependent score record (missing or malformed "
                f"field: {exc})"
            ) from exc


@dataclass(frozen=True)
class VersionChange:
    """One version bump in the audit: feature, old version, new version, when,
    how many.

    The counterpart to feature 39's ``SupersessionRecord``: it records the
    feature whose definition moved, the version it moved from and to, when the
    change was recorded, and how many dependent scores it flagged.  The audit
    counts the effect, so a reader sees how widely each version bump reached.
    """

    #: The feature whose definition changed.
    feature_name: str
    #: The version the superseded dependents were computed from.
    old_version: str
    #: The version that superseded it — the changed definition's new version.
    new_version: str
    #: When the change was recorded, timezone-aware UTC.
    recorded_at: datetime
    #: How many dependent scores the change flagged.
    flagged_scores: int

    def to_dict(self) -> dict:
        return {
            "feature_name": self.feature_name,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "recorded_at": self.recorded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "flagged_scores": self.flagged_scores,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "VersionChange":
        try:
            return cls(
                feature_name=data["feature_name"],
                old_version=data["old_version"],
                new_version=data["new_version"],
                recorded_at=datetime.strptime(
                    data["recorded_at"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=_UTC),
                flagged_scores=data["flagged_scores"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VersionRecomputationError(
                f"corrupt version change record ({exc})"
            ) from exc


# -- The registry ------------------------------------------------------------


class VersionRecomputationRegistry:
    """Persists the recomputation flag on dependent scores, and the audit of the
    version bumps that set it.

    The store behind feature 54.  It holds two things, each through the record
    types above: the dependent scores (with their ``recompute`` flags) and the
    append-only version-change audit that records every bump.  Everything is
    persisted to ``<lake>/feature_version_recomputation.json`` and re-read on
    construction, so the flag a version bump sets is the flag the next process
    reads.

    The registry never touches a dependent score's value or a feature's rows —
    it holds only the addressing (which score, which feature, which version) and
    the flag.  It is the invalidation signal, and the derived zone owns the
    recomputation the signal points at.
    """

    def __init__(self, lake_root: Union[str, os.PathLike[str]]) -> None:
        self._path = Path(lake_root).expanduser() / DEPENDENT_RECOMPUTATION_NAME
        self._scores: dict[str, DependentScore] = {}
        self._changes: list[VersionChange] = []
        self._load()

    # -- Construction --------------------------------------------------------

    def _load(self) -> None:
        """Read the persisted registry, or start empty if none exists yet.

        A missing file is a fresh lake — an empty registry, not an error.  A
        present-but-unreadable file is refused loudly: a corrupt registry is
        worse than none, because it would silently drop every flag it held.
        """
        if not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text("utf-8"))
        except ValueError as exc:
            raise VersionRecomputationError(
                f"{DEPENDENT_RECOMPUTATION_NAME} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise VersionRecomputationError(
                f"{DEPENDENT_RECOMPUTATION_NAME} must be a JSON object, got "
                f"{type(payload).__name__}"
            )
        version = payload.get("version")
        if version != _REGISTRY_VERSION:
            raise VersionRecomputationError(
                f"{DEPENDENT_RECOMPUTATION_NAME} declares version {version!r}; "
                f"this package reads version {_REGISTRY_VERSION}"
            )
        self._scores = {
            key: DependentScore.from_dict(value)
            for key, value in payload.get("scores", {}).items()
        }
        self._changes = [
            VersionChange.from_dict(value)
            for value in payload.get("changes", [])
        ]

    def _flush(self) -> None:
        """Write the registry atomically: temp file plus ``os.replace``.

        A crash mid-write leaves the previous file in place — ``os.replace`` is
        atomic on POSIX, so a reader never observes a half-written registry.
        The lake root is created on demand; the first write brings the file into
        being.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _REGISTRY_VERSION,
            "scores": {
                key: value.to_dict() for key, value in self._scores.items()
            },
            "changes": [value.to_dict() for value in self._changes],
        }
        directory = self._path.parent
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=".feature-version-recomputation-"
        )
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
        """Where this registry persists — ``<lake>/feature_version_recomputation.json``."""
        return self._path

    # -- Dependent scores ----------------------------------------------------

    def register_dependent_score(
        self,
        score_id: str,
        feature_name: str,
        feature_version: str,
    ) -> DependentScore:
        """Anchor a dependent score to the feature and version it was read from.

        Idempotent by score id: re-registering the same score restates its
        coordinates and clears any flag a prior registration set, so a fresh
        computation of a previously-flagged score returns it to
        ``recompute=False`` — the derived zone re-registered the score after
        recomputing it against the new version.  A dependent registered under a
        *new* version after a bump simply replaces this id's record; each version
        keeps its own flag through the scores still anchored to it.

        ``feature_name`` and ``feature_version`` are validated as key components
        (exactly as :class:`~feature_store.keys.FeatureKey` construction does), so
        a dependent anchored to an address that could never be a real key is a
        caller bug, raised as :class:`VersionRecomputationError` rather than the
        key layer's :class:`~feature_store.keys.FeatureKeyError`.
        """
        try:
            record = DependentScore(
                score_id=score_id,
                feature_name=feature_name,
                feature_version=feature_version,
            )
        except FeatureKeyError as exc:
            raise VersionRecomputationError(str(exc)) from exc
        self._scores[score_id] = record
        self._flush()
        return record

    def score(self, score_id: str) -> Optional[DependentScore]:
        """The record for one dependent score, or ``None`` if it was never registered."""
        return self._scores.get(score_id)

    def scores_for(
        self, feature_name: str, feature_version: str
    ) -> list[DependentScore]:
        """Every dependent score anchored to ``(feature_name, feature_version)``.

        What a version bump reads to decide which dependents to flag: the
        dependent scores whose provenance is exactly ``(feature_name,
        feature_version)``.  Empty when no dependent was computed from that
        version — the case :meth:`record_version_change` refuses on, because a
        bump against a version nothing depends on flags nothing.

        ``feature_name`` and ``feature_version`` are validated as key components
        before use: a value that could never be part of a key (empty, padded,
        path-unsafe) is a caller bug, raised rather than silently returning an
        empty answer.
        """
        name = _validated_component("feature_name", feature_name)
        version = _validated_component("feature_version", feature_version)
        return [
            record
            for record in self._scores.values()
            if record.feature_name == name and record.feature_version == version
        ]

    def flagged_scores(self) -> list[DependentScore]:
        """Every dependent score currently flagged for recomputation, sorted by id."""
        return sorted(
            (record for record in self._scores.values() if record.recompute),
            key=lambda record: record.score_id,
        )

    def needs_recomputation(self, score_id: str) -> bool:
        """Whether one dependent score has been flagged — the derived zone's query.

        A score the registry does not know is reported as not needing
        recomputation: an unknown score was never anchored to a version, so no
        bump can have flagged it, and treating the unknown as flagged would flag
        scores that do not exist.
        """
        record = self._scores.get(score_id)
        return record is not None and record.recompute

    # -- Version changes -----------------------------------------------------

    def record_version_change(
        self,
        feature_name: str,
        old_version: str,
        new_version: str,
        *,
        recorded_at: Optional[datetime] = None,
    ) -> VersionChange:
        """Flag every dependent score under ``(feature_name, old_version)`` as
        superseded by ``new_version``.

        The event feature 54 is about, transposed from feature 39's snapshot
        change to a version change.  It reads the dependent scores the registry
        holds under ``(feature_name, old_version)`` (``scores_for``), flips each
        to ``recompute=True`` carrying ``superseded_by=new_version``, appends one
        record to the version-change audit, and writes the registry once.  It
        touches nothing else: the version-1 rows feature 53 leaves beside the new
        definition are not rewritten, and dependents under any other version keep
        their flags.  The rows survive; the dependents under them do not.

        The change is refused in two cases, leaving the registry untouched:
        ``old_version`` and ``new_version`` name the same version — a version
        does not supersede itself — and ``old_version`` anchors no dependent
        score — a bump against a version nothing depends on would be a signal
        anchored to a version nothing depends on, exactly the dishonesty the
        feature guards against.

        Returns the :class:`VersionChange` — the audit entry carrying the
        feature, the old and new versions, when the change was recorded, and how
        many dependents it flagged.
        """
        name = _validated_component("feature_name", feature_name)
        old = _validated_component("feature_version", old_version)
        new = _validated_component("feature_version", new_version)
        if old == new:
            raise VersionRecomputationError(
                "a version change must name two different versions; old_version "
                f"and new_version are both {old!r} — a version does not "
                "supersede itself"
            )
        affected = self.scores_for(name, old)
        if not affected:
            raise VersionRecomputationError(
                f"no dependent scores are anchored to feature_name {name!r} at "
                f"feature_version {old!r}; a version bump flags the dependents a "
                "version holds, and this one holds none — register the dependent "
                "scores before recording the change"
            )
        for record in affected:
            self._scores[record.score_id] = DependentScore(
                score_id=record.score_id,
                feature_name=name,
                feature_version=old,
                recompute=True,
                superseded_by=new,
            )
        change = VersionChange(
            feature_name=name,
            old_version=old,
            new_version=new,
            recorded_at=(recorded_at or _now()).replace(microsecond=0),
            flagged_scores=len(affected),
        )
        self._changes.append(change)
        self._flush()
        return change

    def version_changes(self) -> list[VersionChange]:
        """The append-only audit of version bumps, oldest first."""
        return list(self._changes)
