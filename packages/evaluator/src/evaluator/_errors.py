"""The evaluator plugin's error taxonomy.

One base class (:class:`EvaluatorError`) so a caller — the orchestrator, the
trial-ledger writer, a comparison that has to refuse a mismatched provenance
— can catch every failure of the identity path with a single ``except``.
The subclasses split by *which contract* was violated, not by which line of
code failed:

* :class:`EvaluatorImageError` — the pinning contract. The evaluator is
  immutable, and the only thing that makes it so is that its image is named
  by digest: architecture §12 pins "Container digest in ``evaluator_hash``",
  and the supported runtime (architecture §16, ``containers``) is
  "Docker, digest-pinned, because ``evaluator_hash`` requires digests not
  tags". A tag is a mutable pointer — the same tag resolves to different
  bytes next week — so a tag-only reference is refused here rather than
  folded into an identity that would silently mean two different evaluators.
  This error also covers "no image configured at all": an identity over an
  image nobody named is not an identity.
* :class:`EvaluatorConfigError` — the resolution contract. The resolved
  configuration is the second term of the identity, so a configuration that
  cannot be resolved (not a JSON object, a non-string key, a value JSON
  cannot carry, an override blob that is not JSON) is refused before any
  hash is computed over it. A hash over under-specified bytes is a hash over
  nothing, which is the same argument the snapshot member's ``_identity``
  makes for its own three terms.
* :class:`EvaluatorIdentityError` — the identity's own shape: a 64-hex
  value that is not, a hash that contradicts the digest and configuration it
  claims to be over. A malformed term of the identity rather than a
  malformed input to it, mirroring ``SnapshotNameError``'s split from
  ``SnapshotManifestError``.
* :class:`EvaluatorStoreError` — the persistence contract (app_spec.xml
  feature 70). "System persists ``evaluator_hash``" is the feature's whole
  text, so a configured store whose write fails is an error rather than a
  shrug, and — unlike the snapshot member, where the sealed directory is a
  complete record on its own and a missing row leaves a verifiable artifact
  behind — the persisted row *is* the artifact here, so a service with no
  store configured refuses to persist rather than degrading to a no-op that
  a caller could mistake for success. The same error covers a stored row
  that cannot be believed: a row read back whose terms do not fold to the
  hash it is filed under is a tamper, and it surfaces here rather than
  loading as a plausible-looking lie (see ``_store``).
* :class:`EvaluatorWindowError` — the window contract (app_spec.xml feature
  72). The evaluation window is resolved host-side by slicing a *sealed*
  snapshot to the decision time, so the failures here are all failures of
  that slicing: something that is not a sealed mount at all (a path, a
  service, a name), a decision time the sealed coverage cannot speak for
  (before the first partition, after the last), a snapshot with no bars
  partitions to resolve a universe from, and a partition value that does
  not parse as the ISO date the §4.2 layout promises. Each is refused
  rather than defaulted, because the window is the thing every downstream
  number is computed over — a silently widened or fabricated window is
  look-ahead bias with a return value (see ``_window``).
* :class:`EvaluatorSandboxError` — the sandbox runner contract (app_spec.xml
  feature 73). The signal runs inside a resource-limited child process, so
  the failures here are failures of *driving* that process rather than of
  the signal it ran: the interpreter is missing, the child cannot be
  spawned, the platform has no POSIX resource limits to enforce. A signal
  that times out, runs out of memory or crashes is **not** here — those are
  recorded outcomes (:class:`~evaluator._sandbox.SandboxResult.fail_class`),
  because a failed run is a value the pipeline persists, not an exception
  that aborts it (see ``_sandbox``).
* :class:`EvaluatorSignalError` — the execution-orchestration contract
  (app_spec.xml feature 73). Step 2 of §6.1's pipeline ties a resolved
  window to raw scores per rebalance date, so the failures here are failures
  of that tying: no rebalance grid to score at (a resolution with no
  surviving bars and no explicit dates), or a materialize callable that
  returns something that is not a materialized window. A signal that returns
  a contract-violating vector is **not** here — that is a
  ``contract_violation`` the caller decides on (feature 12), carried on the
  vector's ``problems`` rather than raised (see ``_execute``).
* :class:`EvaluatorStoreError` — the persistence contract (app_spec.xml
  feature 70). "System persists ``evaluator_hash``" is the feature's whole
  text, so a configured store whose write fails is an error rather than a
  shrug, and — unlike the snapshot member, where the sealed directory is a
  complete record on its own and a missing row leaves a verifiable artifact
  behind — the persisted row *is* the artifact here, so a service with no
  store configured refuses to persist rather than degrading to a no-op that
  a caller could mistake for success. The same error covers a stored row
  that cannot be believed: a row read back whose terms do not fold to the
  hash it is filed under is a tamper, and it surfaces here rather than
  loading as a plausible-looking lie (see ``_store``).
"""

from __future__ import annotations

__all__ = [
    "EvaluatorConfigError",
    "EvaluatorError",
    "EvaluatorIdentityError",
    "EvaluatorImageError",
    "EvaluatorNormalizeError",
    "EvaluatorSandboxError",
    "EvaluatorSignalError",
    "EvaluatorStoreError",
    "EvaluatorWindowError",
]


class EvaluatorError(Exception):
    """Base class for every failure of the frozen-evaluator identity path."""


class EvaluatorImageError(EvaluatorError):
    """The container image cannot serve as an identity term.

    Raised for a tag-only or bare reference (never a digest), for a digest
    that is not ``sha256:<64 lowercase hex>``, and for a service asked to
    resolve an identity when no image is configured at all.
    """


class EvaluatorConfigError(EvaluatorError):
    """The configuration cannot be resolved into an identity term.

    Raised for a configuration that is not a JSON object, carries keys that
    are not non-empty strings, or holds values JSON cannot round-trip — and
    for a ``NULLIUS_EVALUATOR_CONFIG`` override that does not parse as a
    JSON object.
    """


class EvaluatorIdentityError(EvaluatorError):
    """A value claiming to be an ``evaluator_hash`` is not one.

    Raised by :func:`evaluator.normalize_evaluator_hash` and by a record
    built by hand, so a hash that arrives from outside — a database row, an
    API caller, a report — is canonicalised and checked before anything
    compares or stores it.
    """


class EvaluatorStoreError(EvaluatorError):
    """The persisted ``evaluator_hash`` row could not be written or read.

    Raised when no store is configured (feature 70 is a persistence feature,
    so there is nothing to degrade to), when ``DATABASE_URL`` names a scheme
    this store does not speak, and when an SQLite write fails.
    """


class EvaluatorNormalizeError(EvaluatorError):
    """A raw score vector could not be normalized into a comparable score.

    Raised by :func:`evaluator.normalize_scores` (app_spec.xml feature 74)
    when the rank-then-z-score reduction cannot produce a comparable
    cross-sectional score: the input is not a Polars ``Series`` of finite
    floats, the vector holds a single symbol (one symbol is not a
    cross-section to be relatively preferred within), or every raw score is
    identical so the cross-sectional deviation is zero and dividing by it
    would dress a "no preference" up as a measurement. Each is refused rather
    than defaulted, because a normalized vector is only comparable when there
    was a scale to remove, and these are the cases in which there was not.
    """


class EvaluatorWindowError(EvaluatorError):
    """The evaluation window could not be resolved from a sealed snapshot.

    Raised by :func:`evaluator.resolve_window` (app_spec.xml feature 72) for
    an object that is not a sealed snapshot mount, a decision time outside
    the sealed bars coverage, a snapshot carrying no bars partitions, and a
    partition date that does not parse as ISO — every failure of the slice
    itself, rather than of anything downstream of it.
    """


class EvaluatorSandboxError(EvaluatorError):
    """The signal sandbox could not be driven at all.

    Raised by :class:`evaluator._sandbox.SignalSandbox` when the runner
    itself fails rather than the signal it ran: the interpreter is missing,
    the child cannot be spawned, or the platform has no POSIX resource limits
    to enforce. A signal that times out, runs out of memory or crashes is not
    this error — those are recorded outcomes on the returned
    :class:`~evaluator._sandbox.SandboxResult`, because a failed run is a
    value the pipeline persists, not an exception that aborts it.
    """


class EvaluatorSignalError(EvaluatorError):
    """The signal-execution orchestration failed.

    Raised by :func:`evaluator.execute_signal` (app_spec.xml feature 73) when
    step 2 of the §6.1 pipeline cannot tie a resolved window to raw scores:
    there is no rebalance grid to score at (a resolution with no surviving
    bars and no explicit dates), or the injected ``materialize`` callable
    returned something that is not a materialized window. A signal that
    returns a contract-violating vector is not this error — that is a
    ``contract_violation`` the caller decides on (feature 12), carried on the
    vector's ``problems`` rather than raised.
    """
