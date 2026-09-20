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

:class:`CanaryReproducibilityError` is the third such subclass, and it
follows that rule rather than extending the second. Feature 145
(app_spec.xml) asserts that "output [is] bit-identical across two runs of
the same seeded signal", which is §12's *last* row, "Float
reproducibility | Fixed reduction order; no ``fastmath``; no GPU in the
eval path" — and it is a strictly wider statement than the pin. A digest
can be perfectly pinned while the bytes a container emits still differ
run to run (a threaded reduction reassociating, a dict-ordered reduction
seeing a different insertion order, a ``fastmath`` contract collapsing a
sum): that is exactly the failure §12 calls out as invisible, because
non-determinism "does not announce itself". So a caller holding both
failures needs to tell them apart — the repair for a moved pin is to
re-pin, the repair for divergent bytes is bisect-the-image-diff — and the
class split is what makes the difference legible at the ``except``.
"""

from __future__ import annotations

__all__ = [
    "CanaryError",
    "CanaryImageError",
    "CanaryReproducibilityError",
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


class CanaryReproducibilityError(CanaryError):
    """Two runs of one seeded signal did not produce the same bytes.

    Raised by :func:`~canary.assert_bit_identical` when the byte-level
    comparison of a seeded signal's two runs comes back unequal — and
    only then. A byte-level comparison that *returns* a result is the
    feature (app_spec.xml feature 145: "which returns a byte-level
    comparison result"), so the verdict is a value the caller can record,
    file against a run, or branch on; this error is the spelling for the
    caller who asked the check to raise instead.

    Deliberately not :class:`CanaryImageError`. A deployment can be
    perfectly pinned — every container at a frozen digest, every library
    in the lockfile — and still emit different bytes twice, which is the
    failure mode §12 names directly: threaded reductions reassociating, a
    ``fastmath`` contraction, a reduction over an unordered container.
    The two failures share a category (both are §12's determinism
    contract breaking) but not a repair: a moved pin is re-pinned,
    divergent bytes are bisected. A caller catching :class:`CanaryError`
    gets both; one catching this class gets exactly the one it can act
    on.

    The message carries the field names, the two digests and the offset
    of the first differing byte — enough for an operator to decide
    whether the divergence is a reassociated reduction (a low byte of one
    float) or a different result set entirely — without carrying the
    bytes themselves, which for a score panel are far too large to paste
    into a log line.
    """
