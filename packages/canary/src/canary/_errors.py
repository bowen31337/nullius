"""The canary plugin's error taxonomy.

One base class (:class:`CanaryError`) so a caller — the nightly runner, an
operator's health check, the determinism suite §19 files under
``tests/determinism`` — can catch every failure of the determinism
canary's assertions with a single ``except``. The subclasses split by
*which contract* was violated, not by which line of code failed:

* :class:`CanaryImageError` — the container-pinning contract (app_spec.xml
  feature 135, the plugin's root feature). Architecture §12's determinism
  table opens with "Pinned evaluator | Container digest in
  ``evaluator_hash``; refuse cross-hash comparison", and §16's runtime row
  is "Docker, digest-pinned, because ``evaluator_hash`` requires digest
  pinning, not tags". A tag is a mutable pointer — the same tag resolves
  to different bytes next week — so a tag-only reference is refused here
  rather than swept past, and the refusal is raised once for the whole
  declaration, naming every offender, because a sweep that reported only
  the first would be re-run N times to learn what one run should have
  said. The same error covers the declaration that names no containers at
  all (a sweep over an empty set passes vacuously, and vacuous green is
  the one reading the nightly canary must never allow) and an environment
  variable that names no reference (an evaluation container nobody named
  is an evaluation container nobody pinned).

Later features in this category add the rest of §12's table — the
lockfile, the thread caps, ``PYTHONHASHSEED``, the import allowlist, the
GPU refusal — and each will bring its own subclass rather than folding
into this one: a caller halting dreaming (§15's "Replay non-determinism"
recovery) needs to know *which* line of the contract broke, because the
recovery differs (bisect the image diff is not reinstall-from-lockfile).
"""

from __future__ import annotations

__all__ = [
    "CanaryError",
    "CanaryImageError",
]


class CanaryError(Exception):
    """Base class for every failure of the determinism canary's assertions."""


class CanaryImageError(CanaryError):
    """An evaluation container is not pinned by image digest.

    Raised for a tag-only or bare reference (never a digest), for a digest
    that is not ``sha256:<64 lowercase hex>``, for a declaration naming no
    containers at all, and for an environment that names no reference for
    a declared container. The refusal names the role — and the environment
    variable, when the declaration came from one — for every offender at
    once, because the feature's word is *every*.
    """
