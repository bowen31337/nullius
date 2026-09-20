"""The null-oracle plugin's error taxonomy.

One base class (:class:`NullOracleError`) so a caller — the scorer process
holding the sidecar key, a campaign driver, an operator script, a later
feature in this category — can catch every failure of the null-oracle path
with a single ``except``.  The subclasses split by *which contract* was
violated, not by which line of code failed:

* :class:`SidecarError` — the sidecar contract (app_spec.xml feature 109).
  An assignment's identity is malformed (a ``node_id`` that is not a UUID),
  its status is not a genuine bool, its permutation seed is not a
  non-negative integer, or its block length is not a positive integer.  The
  sidecar is the one place in the entire system where a node's null status
  is written down (docs/nullius-tech-architecture.md §7.1: *"There is no
  ``is_null`` column anywhere in the tree store"*), so an assignment that
  cannot state its own status coherently is refused at the write rather than
  sealed into the file as a value no reader could interpret.

* :class:`SidecarKeyError` — the key contract.  The key reference
  ``NULL_SIDECAR_KEY_REF`` names is absent, blank, or not a form this
  member can resolve (a KMS ARN, a ``sops:`` reference, or inline hex).  The
  refusal here is *before* any crypto is attempted, because a key that
  cannot be named is a configuration problem an operator can fix, not a
  decryption failure to escalate.

* :class:`SidecarDecryptionError` — the refusal to serve a sidecar that
  cannot be authenticated.  AES-GCM's tag failed, the file was truncated,
  the nonce was wrong, or the key simply is not the one the file was sealed
  under.  §7's failure table names this the *unrecoverable* one — *"Null
  sidecar key lost → Decrypt failure → Unrecoverable. All FDR history
  becomes uninterpretable"* — so this error is deliberately loud and
  deliberately not caught by anything that would degrade quietly.  A
  sidecar that will not open is never served as "no nulls assigned": an
  empty assignment map and an unreadable one mean opposite things about
  every score the system has ever recorded.

* :class:`SidecarAccessError` — the one-service-account contract.  A read
  of the sidecar was attempted by a process that is not the single service
  account the key is granted to (§7.1: *"readable by ONE service
  account"*; §2's trust table: *"separate IAM role"*).  The check is a
  filesystem-permission gate plus an explicit identity assertion, so the
  refusal meets a caller that reaches for the file directly rather than
  only the ones that go through this package's API.

* :class:`SidecarStoreError` — the store contract.  The sidecar's location
  is misrouted or the write failed.  A store that is *absent* — no
  ``NULL_SIDECAR_PATH`` configured and no lake root found — is not this
  error: it is a supported, discoverable state in which no sidecar
  component composes (see :meth:`nulloracle.sidecar.NullSidecar.resolve`),
  because the factory's stance toward an unconfigured component is to
  degrade, not to break.

* :class:`KsTestError` — the detectability test's contract (app_spec.xml
  feature 123).  A sample handed to §7.4's two-sample Kolmogorov–Smirnov
  test is empty, too small to decide anything, or not made of finite
  scores.  Refused rather than computed, because the p-value this test
  returns is what voids a campaign: a number produced from four nodes, or
  from a sample that silently dropped a ``None``, would enter §7.4's
  ``p < 0.05`` comparison wearing a real statistic's authority.

* :class:`KsGuardError` — the guard's store contract (feature 123's other
  half).  The campaign the p-value belongs to is unknown, the relational
  store cannot be reached or speaks another scheme, or the write of the
  two halves could not be completed.  Distinct from
  :class:`KsTestError` for the same reason :class:`SidecarStoreError` is
  distinct from :class:`SidecarError`: *the measurement was refused* and
  *the measurement could not be recorded* are different facts, and only
  the first is about the numbers.

Every message names the offending value and the contract it broke, in the
same discipline as the ledger member's taxonomy: these errors are
operational signals for a system whose whole FDR claim rests on the labels
this file holds, so a failure of the sidecar path must be *speakable*, not
merely loggable.
"""

from __future__ import annotations

__all__ = [
    "KsGuardError",
    "KsTestError",
    "NullOracleError",
    "SidecarAccessError",
    "SidecarDecryptionError",
    "SidecarError",
    "SidecarKeyError",
    "SidecarStoreError",
]


class NullOracleError(Exception):
    """Base class for every failure of the null-oracle path."""


class SidecarError(NullOracleError):
    """A null assignment's identity, status or perm parameters are malformed.

    Raised at the write, where the cause can still be named: a ``node_id``
    that is not a UUID cannot be joined to the tree store later, so it is
    refused before it is sealed into the sidecar; an ``is_null`` that is
    not a genuine bool (a string ``"false"``, an int ``0``, ``None``) is
    refused rather than coerced, because the whole transfer to a null world
    hangs on this one bit and a truthy-looking non-bool is exactly the
    value that would silently plant the wrong world; a ``perm_seed`` that
    is not a non-negative integer or a ``block_days`` that is not a
    positive integer is refused for the same reason — feature 115's block
    permutation is only reproducible from a stored seed and block length
    that mean one thing.
    """


class SidecarKeyError(NullOracleError):
    """The sidecar key reference is absent, blank, or unresolvable.

    Raised when ``NULL_SIDECAR_KEY_REF`` names nothing, names an empty or
    whitespace-only value, or names a form this member cannot resolve.  A
    key that cannot be named is a *configuration* failure, refused before
    any ciphertext is touched — the same distinction the cost-model member
    draws between a missing parser and a malformed document.  Feature 111
    is the feature that answers *where the key comes from*; this error is
    the refusal that feature resolves *from*.
    """


class SidecarDecryptionError(NullOracleError):
    """The sidecar could not be authenticated and was therefore not served.

    AES-GCM's authentication tag failed: the file was tampered with, it was
    truncated, it was sealed under a different key, or its nonce is not the
    one the file carries.  All four are one refusal here, deliberately,
    because distinguishing them for a caller would be an oracle of its own —
    and because §7's failure table treats every one of them the same way:
    *unrecoverable*, all recorded calibration becomes uninterpretable.

    Never swallowed on the read path.  A sidecar that will not open must
    not read as "no node is null", because that reading would hand the
    caller a world where every planted null looks real, and the system
    would report an FDR computed over nothing.
    """


class SidecarAccessError(NullOracleError):
    """The sidecar was read by a process that is not the granted account.

    §7.1 seals the sidecar *"readable by ONE service account"* and §2 gives
    the key *"separate IAM role"*.  The check behind this error is
    deliberately two-layered: the file is written with owner-only mode bits
    so the operating system refuses a foreign read, and the read path
    asserts the process's own service-account identity against the one the
    sidecar records, so the refusal holds even where the mode bits have
    been loosened (a copied file, a permissive mount, a root-owned
    backup).  Filesystem permissions are the enforcement; this error is
    what the caller sees when they hold.
    """


class SidecarStoreError(NullOracleError):
    """The sidecar's location is misrouted, or its write failed.

    A configured path this member cannot use (a directory where a file
    belongs), or a seal whose bytes could not be written.  Raised rather
    than swallowed because a sidecar that silently failed to persist is
    exactly the state feature 109 exists to prevent: a campaign would then
    run against a world whose null assignments nobody recorded, and the
    resulting FDR would be computed over a design that was never applied.
    """


class KsTestError(NullOracleError):
    """A sample handed to §7.4's two-sample KS test cannot support a verdict.

    app_spec.xml feature 123 is the test; §7.4 is what it decides with:

    .. code-block:: text

        if ks_pvalue < 0.05:
            campaign.calibration_status = VOID

    So a p-value from this path is not a diagnostic — it is the number that
    voids a campaign, halts dreaming and removes the campaign from the
    replay pool (feature 124).  A sample that cannot support such a verdict
    must therefore be *refused*, never quietly computed over: an empty
    sample (a campaign where nothing was scored on one side), a sample of
    one (a KS statistic that is degenerate by construction), a score that
    is not a finite real (a ``None`` that a caller's ``if score:`` dropped,
    or a ``nan`` that survived a mean), or a distribution that is not a
    mapping of node to score at all.

    Refusing is the same discipline :class:`SidecarDecryptionError` states
    for the labels: the failure mode this taxonomy exists to prevent is a
    *plausible-looking number* standing in for a fact nobody measured, and
    the campaign that would be voided on it would be voided for the wrong
    reason.
    """


class KsGuardError(NullOracleError):
    """The KS guard's p-value could not be recorded against its campaign.

    Feature 123's store half: the campaign is unknown, the relational store
    is unreachable or speaks a scheme this member cannot read, or the
    two halves of the write — §7.4's ``ks_pvalue`` and the campaign row it
    joins to — could not both be completed.

    Kept distinct from :class:`KsTestError` deliberately.  "The measured
    distributions cannot support a test" is a statement about a campaign's
    data; "the number could not be written down" is a statement about the
    deployment, and a caller that conflated them would investigate the
    wrong one.  The distinction is the same one :class:`SidecarStoreError`
    draws beside :class:`SidecarError`, and the one
    :class:`~nulloracle.errors.SidecarKeyError` draws beside
    :class:`SidecarDecryptionError`.
    """
