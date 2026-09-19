"""Error vocabulary for the feature-store's version-recomputation side (feature 54).

Feature 54: *System treats a feature_version bump as invalidating dependent
scores, which emits the same recomputation signal an evaluator change produces.*
The one failure mode this side of the store can raise is a version change that
cannot honestly be recorded — the same class of failure feature 39's
:class:`~snapshot.SnapshotRecomputationError` names on the snapshot side.  A
version change is only honest if it names two different versions and the old
version actually anchors dependent scores to flag — recording a bump against a
version nothing depends on, or a version over itself, would emit a recomputation
signal anchored to nothing.  That refusal is this error.

A subclass of :class:`ValueError`, so it sits in the store's existing vocabulary
of caller-bug errors (:class:`~feature_store.keys.FeatureKeyError` and the
services' ``VersionMismatchError`` are likewise ``ValueError``) — an invalid
version change is a caller bug, never a runtime condition to retry or
catch-and-continue — and so a caller catching the store's single error type
catches it too.
"""

from __future__ import annotations

__all__ = ["VersionRecomputationError"]


class VersionRecomputationError(ValueError):
    """A version change was recorded against a version the registry holds no
    dependent scores for.

    app_spec.xml feature 54: *"System treats a feature_version bump as
    invalidating dependent scores, which emits the same recomputation signal an
    evaluator change produces."* A version change is the event that turns
    feature 53's new ``feature_version`` into a recomputation signal: it flags
    every dependent score the registry anchored to the old version and records
    the supersession in the audit, leaving the prior-version rows feature 53
    left beside the new definition untouched.  The signal is only honest if the
    two versions differ and the old version actually anchors dependent scores to
    flag — a bump naming the same version twice, or a version nothing depends on,
    would emit a recomputation signal anchored to nothing, so it is refused
    rather than recorded.  A subclass of :class:`ValueError`, so callers catching
    the store's single vocabulary of caller-bug errors catch it too.
    """
