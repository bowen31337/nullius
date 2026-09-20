"""Feature 155's stores: the sidecar key, sealed, in two independent places.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 155: *System
persists a sidecar key backup to two independent stores, because key loss
makes all recorded calibration uninterpretable.*  docs/nullius-tech-
architecture.md §15 names this the one unrecoverable failure — *"Null
sidecar key lost → Decrypt failure → Unrecoverable. All FDR history becomes
uninterpretable. Back up the key to two independent stores"* — and §7's
failure table gives it the same line: the sidecar key is the single secret
whose loss does not surface as an error but as *every calibration number
the system has ever produced going silent*, because the null labels
(feature 109, :mod:`nulloracle.sidecar`) are sealed under it and nothing
else anywhere holds the plaintext.  Feature 111's key resolution knows it
too: the caller that *created* the key is the caller that must back it up,
because a key that already existed needed no backup and one just minted
needs two.

This module is that backup, and it decomposes into three claims, each of
which is a seam rather than a comment:

* **two** — the cardinality is enforced, not hoped for.  A backup over one
  store is refused (:class:`InsufficientStoresError`); a backup over three
  is refused too (:class:`StoresNotIndependentError` names the count).  The
  number is not a minimum ("at least two") because "at least two" lets a
  deployment ship one and call it compliant — the failure the feature
  exists to prevent is exactly *one store that silently held nothing*.
  Two, checked, is the sentence.

* **independent** — the two stores must not share a failure mode.  The
  check is structural, because "independent" asserted in prose is how a
  backup ends up as two writes to the same bucket under different prefixes.
  Two stores are independent here iff they are distinct objects with
  distinct :meth:`BackupStore.name` and distinct :meth:`BackupStore.
  store_id` — the identity that captures the store's durability domain (a
  file store's resolved path, a network store's endpoint).  Two file stores
  in different directories pass (different failure domains); two handles to
  one path do not.  That a deployment's real stores are *genuinely*
  independent — a KMS, a sops/age document, an HSM, a paper vault in a
  different fire zone — is a deployment fact this check cannot see and does
  not pretend to; it refuses only the failures it *can* see, so the ones it
  cannot are at least not the ones that got shipped.

* **persists … because key loss makes calibration uninterpretable** — the
  *why*, and it orders the whole design.  A backup that could not be
  trusted to come back is worse than none: none fails loudly at the first
  read, while a corrupt backup fails years later over a world whose nulls
  can no longer be reconstructed.  So the key is not written raw — it is
  sealed into an authenticated envelope (:class:`SealedKeyBackup`) whose
  integrity tag is checked on every recall, and every recall reconciles the
  two stores against each other before trusting either.  A store whose
  bytes have drifted — bit rot, a truncated write, a tampering hand — is
  caught by :class:`StoreMismatchError` (the two stores disagree) or
  :class:`UnsealedKeyError` (one store's envelope failed its own tag), and
  is never silently served as the key.

**The seal is stdlib-only, and deliberately so.**  :mod:`infra.security`
sits outside the uv workspace by design (policy that guards the zones must
not be importable from inside them), so it owns no ``cryptography`` wheel;
the envelope here is built from :mod:`hashlib` and :mod:`hmac` alone —
HMAC-SHA256 in counter mode as the keystream (a PRF is a stream cipher), a
second HMAC as the tag, encrypt-then-MAC.  That is not an invention of a
new cipher: it is the one AEAD shape that is safe to build without a C
extension, and it is the *backup's* lock, not the sidecar's — the sidecar
keeps its own AES-GCM (:mod:`nulloracle.envelope`).  The seal secret that
locks the backup is a deployment secret managed out of band, like the
sidecar key itself; losing it loses every backup at once, which is why it
is never persisted by this module and never written beside the stores it
protects.

Stdlib-only, like the rest of the zone's tooling.  Nothing here dials a
network; the stores are durability sinks the deployment supplies, and this
module is the seal, the two-store rule and the reconciliation between them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Final

__all__ = [
    "BackupReceipt",
    "BackupStore",
    "FileBackupStore",
    "InMemoryBackupStore",
    "InsufficientStoresError",
    "KeyBackup",
    "KeyBackupError",
    "SealError",
    "SealedKeyBackup",
    "StoreMismatchError",
    "StoreReadError",
    "StoreWriteError",
    "StoresNotIndependentError",
    "UnsealedKeyError",
    "digest_of",
]

#: The sealed backup's first bytes: a fixed marker so a store operator can
#: tell a key backup from anything else that happens to share the sink,
#: before spending an unseal attempt.  Not secret — it is meant to be
#: recognizable, which is why the tag authenticates it.
MAGIC: Final[bytes] = b"NULLIUS-KEYBACKUP\x00"

#: The envelope format's version.  Bumped only by a change to the layout
#: below; authenticated, so a backup cannot be silently re-read under a
#: different format's rules.
FORMAT_VERSION: Final[int] = 1

#: GCM-sized nonce, here drawn fresh per seal.  Random rather than derived:
#: the backup is written a handful of times in a key's life, never a
#: high-volume stream, so the random-nonce birthday bound is never near.
NONCE_BYTES: Final[int] = 12

#: PBKDF2's iteration count for stretching the seal secret into the keystream
#: and tag keys.  A cost, not a security parameter: it slows a brute-force
#: of a weak seal secret, and is fixed so a backup sealed today opens under
#: the same cost years later when the key must be recovered.
_KDF_ITERATIONS: Final[int] = 200_000

#: Lengths of the two keys PBKDF2 derives (keystream key, then tag key) and
#: of the tag itself.  256 bits each: the sidecar key is 256 bits, and a
#: shorter tag would be a deliberate weakening nothing here needs.
_STREAM_KEY_BYTES: Final[int] = 32
_MAC_KEY_BYTES: Final[int] = 32
_TAG_BYTES: Final[int] = 32

#: Four bytes for the ciphertext length.  A sidecar key is 32 bytes; this
#: header spells it out so the layout is self-describing and a truncated
#: envelope is refused by length, not misread.
_LEN_BYTES: Final[int] = 4

_HEADER_BYTES: Final[int] = len(MAGIC) + 1 + NONCE_BYTES


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """A keystream of ``length`` bytes from ``key`` and ``nonce``.

    HMAC-SHA256 keyed by ``key`` over ``nonce || counter``, concatenated.
    HMAC-SHA256 is a pseudorandom function, and a PRF in counter mode is a
    stream cipher: XORing the plaintext with this is the one symmetric
    encryption that needs no C extension.  A fresh ``nonce`` per seal (see
    :func:`_seal`) is what keeps the keystream from ever repeating under the
    same key — the one invariant that makes a stream cipher safe.
    """
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            key, nonce + counter.to_bytes(8, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _derive(seal_secret: bytes, nonce: bytes) -> tuple[bytes, bytes]:
    """The (keystream key, tag key) for ``seal_secret`` under ``nonce``.

    One PBKDF2 stretch yields both keys, so a seal and the recall that opens
    it cannot disagree about how the secret was turned into keys — the same
    reason the null oracle's cost model folds once from one parse.  The
    nonce is the salt: fresh per seal, stored in the envelope, so two
    backups of the same key under the same seal secret still derive
    different keys.
    """
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        seal_secret,
        nonce,
        _KDF_ITERATIONS,
        _STREAM_KEY_BYTES + _MAC_KEY_BYTES,
    )
    return derived[:_STREAM_KEY_BYTES], derived[_STREAM_KEY_BYTES:]


def _seal(material: bytes, seal_secret: bytes) -> bytes:
    """Seal ``material`` into the bytes of a key backup envelope."""
    nonce = os.urandom(NONCE_BYTES)
    stream_key, mac_key = _derive(seal_secret, nonce)
    ciphertext = bytes(
        b ^ k for b, k in zip(material, _keystream(stream_key, nonce, len(material)))
    )
    header = MAGIC + bytes([FORMAT_VERSION]) + nonce
    tag = hmac.new(mac_key, header + ciphertext, hashlib.sha256).digest()
    return header + len(ciphertext).to_bytes(_LEN_BYTES, "big") + ciphertext + tag


def _open(envelope: bytes, seal_secret: bytes) -> bytes:
    """Open a key backup envelope, refusing anything that is not genuine."""
    if len(envelope) < _HEADER_BYTES + _LEN_BYTES + _TAG_BYTES:
        raise UnsealedKeyError(
            f"the key backup is {len(envelope)} bytes, shorter than the "
            f"{_HEADER_BYTES + _LEN_BYTES + _TAG_BYTES}-byte minimum a sealed "
            "backup has; a truncated backup is not an empty one, and reading "
            "it as 'no key' would hand the recovery a world whose nulls can "
            "no longer be reconstructed (feature 155)."
        )
    if not envelope.startswith(MAGIC):
        raise UnsealedKeyError(
            "the key backup does not begin with this module's marker; the "
            "bytes in this store are not a sealed sidecar-key backup, so they "
            "are refused rather than opened under a format they may not have "
            "(feature 155)."
        )
    version = envelope[len(MAGIC)]
    if version != FORMAT_VERSION:
        raise UnsealedKeyError(
            f"the key backup declares container format {version} and this "
            f"build writes {FORMAT_VERSION}; a backup sealed under another "
            "build's rules is read by that build, not guessed at by this one "
            "(feature 155)."
        )
    nonce = envelope[len(MAGIC) + 1 : _HEADER_BYTES]
    offset = _HEADER_BYTES
    clen = int.from_bytes(envelope[offset : offset + _LEN_BYTES], "big")
    offset += _LEN_BYTES
    ciphertext = envelope[offset : offset + clen]
    tag = envelope[offset + clen : offset + clen + _TAG_BYTES]
    stream_key, mac_key = _derive(seal_secret, nonce)
    header = envelope[: _HEADER_BYTES]
    expected = hmac.new(mac_key, header + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise UnsealedKeyError(
            "the key backup failed its integrity check: the seal secret is "
            "not the one it was sealed under, or the store's bytes were "
            "altered after they were written — bit rot, a truncated write, a "
            "tampering hand. docs/nullius-tech-architecture.md §15 names this "
            "the unrecoverable failure, so a backup that will not authenticate "
            "is refused rather than served as a key that may be wrong "
            "(feature 155)."
        )
    return bytes(
        b ^ k for b, k in zip(ciphertext, _keystream(stream_key, nonce, len(ciphertext)))
    )


def digest_of(sealed: bytes) -> str:
    """A sha256 over a sealed backup's bytes, as 64 lowercase hex characters.

    The digest of the *ciphertext*, so two stores can be compared — do they
    hold the same backup? — by an operator or an audit that holds neither
    the seal secret nor the key.  Like the null oracle's
    ``envelope_digest``, it detects a *different* backup and cannot detect a
    *forged* one; only the tag does that, and only the seal secret verifies
    it.  Deliberately hashes the bytes as given: its subject is the stored
    object, and a digest that refused a malformed input could not answer the
    one question it is asked about a store already suspected of drift.
    """
    if not isinstance(sealed, (bytes, bytearray)):
        raise StoreReadError(
            f"a backup digest is taken over bytes, got {type(sealed).__name__}"
        )
    return hashlib.sha256(bytes(sealed)).hexdigest()


class KeyBackupError(Exception):
    """Base of the two-store backup taxonomy.

    One base class so a caller — the key-minting path that must back up a
    freshly created sidecar key (feature 111), an operator's restore or
    audit script, a later feature in this category — can catch every
    failure of the backup path with a single ``except``.  The subclasses
    split by *which contract* was violated, not by which line failed.
    """


class InsufficientStoresError(KeyBackupError):
    """A backup was attempted over fewer than the two stores the feature demands.

    Feature 155's "two independent stores" is a hard count, and a backup
    over one store is not a backup at all — it is the single point of
    failure the feature exists to remove.  Refused rather than accepted,
    because a one-store "backup" that silently succeeded would be discovered
    only when that one store lost the key, which is the exact failure it was
    meant to prevent.
    """


class StoresNotIndependentError(KeyBackupError):
    """The stores named for a backup do not form two independent places.

    Raised when the two stores are the same object, share a
    :meth:`BackupStore.name`, or share a :meth:`BackupStore.store_id` — the
    identity that captures a store's durability domain.  Two handles to one
    path, two names for one bucket, or a count other than two all land here:
    the sentence names *two independent* stores, and a pair that collapses
    to one under a failure is refused before the backup is written, not
    discovered when both halves go down together.
    """


class SealError(KeyBackupError):
    """The key material could not be sealed into a backup envelope.

    The material is the wrong length for the key it claims to be (the
    sidecar key is exactly 32 bytes — AES-256 — and a backup of a key of a
    different length is a key-identity mistake, not a backup), or is not
    bytes at all.  Refused at the seal, because a backup of a mis-shaped key
    would restore into the wrong key years later, over a world whose nulls
    it cannot reconstruct.
    """


class StoreWriteError(KeyBackupError):
    """A store could not be made to hold the sealed backup.

    The store raised on write, or returned something other than what it was
    given.  Refused rather than skipped: a backup that silently failed to
    persist to one of its two stores is exactly the state feature 155 exists
    to prevent — the deployment would then believe it had two stores and
    have one — so the whole backup is refused, not the failed half dropped.
    """


class StoreReadError(KeyBackupError):
    """A store held no backup to recall, or could not be read.

    Distinct from :class:`UnsealedKeyError` for the same reason
    :class:`StoreWriteError` is distinct from :class:`SealError`: *the store
    has nothing* and *the store has a backup that will not open* are
    different facts, and a caller that conflated them would investigate the
    wrong one.  A restore over a store that is merely empty is a recoverable
    miss (the other store still holds the key); a restore over a store whose
    bytes failed their tag is the tamper/rot the tag exists to catch.
    """


class UnsealedKeyError(KeyBackupError):
    """A store's sealed backup failed to open under the seal secret.

    The envelope's integrity tag did not verify: the seal secret is not the
    one the backup was sealed under, or the store's bytes were altered after
    they were written.  §15 calls this the unrecoverable failure — all
    recorded calibration becomes uninterpretable — so a backup that will not
    authenticate is refused rather than degraded to a guessed key.  The
    refusal is the signal; the intact second store is the recovery.
    """


class StoreMismatchError(KeyBackupError):
    """The two stores hold different backups — the reconciliation failed.

    The two stores' sealed bytes do not share a digest, so they cannot both
    be the key's backup.  One store drifted — a rewrite under a new seal, a
    stale object, a copy from a different key — and the other did not, and
    serving either alone would be serving a key the deployment cannot
    vouch for.  Refused: the whole point of two stores is that they agree,
    and a disagreement is the one thing that must never be silently
    resolved by picking one.
    """


class SealedKeyBackup:
    """The sidecar key sealed into an authenticated, store-agnostic envelope.

    Built once by :meth:`KeyBackup.seal` and handed to each store's
    :meth:`BackupStore.write`; the identical sealed object is what two
    independent stores then durably hold.  Holds no key material in the
    clear — :meth:`material` opens it only under the seal secret, and the
    envelope's integrity tag is checked on the way, so a
    :class:`SealedKeyBackup` is safe to persist, copy and compare by digest
    without ever loosening the secret it carries.
    """

    __slots__ = ("_envelope",)

    def __init__(self, envelope: bytes) -> None:
        if not isinstance(envelope, (bytes, bytearray)):
            raise SealError(
                f"a sealed key backup is bytes, got {type(envelope).__name__}"
            )
        self._envelope = bytes(envelope)

    @classmethod
    def seal(cls, material: bytes, seal_secret: bytes) -> SealedKeyBackup:
        """Seal ``material`` under ``seal_secret`` into a backup envelope.

        ``material`` is the key being backed up — the 32-byte sidecar key —
        and is validated here, not assumed: a backup is taken of a key whose
        identity matters years later, so a non-bytes or mis-length material
        is refused at the seal (:class:`SealError`) rather than sealed into
        an envelope that would restore into the wrong key.
        """
        if not isinstance(material, (bytes, bytearray)):
            raise SealError(
                f"the key to back up must be bytes, got {type(material).__name__}"
            )
        material = bytes(material)
        if len(material) != _SIDECAR_KEY_BYTES:
            raise SealError(
                f"the key to back up is {len(material)} bytes; the null "
                f"sidecar key it backs up is exactly {_SIDECAR_KEY_BYTES} "
                "(AES-256-GCM, nulloracle.keyref.SIDECAR_KEY_BYTES), and a "
                "backup of a key of a different length would restore into the "
                "wrong key over a world whose nulls it cannot reconstruct "
                "(feature 155)."
            )
        return cls(_seal(material, seal_secret))

    @property
    def envelope(self) -> bytes:
        """The sealed bytes — safe to persist, copy and digest, never the key."""
        return self._envelope

    def digest(self) -> str:
        """The sha256 of the sealed bytes — compare two stores without the key."""
        return digest_of(self._envelope)

    def material(self, seal_secret: bytes) -> bytes:
        """The key material, opened only under the correct seal secret.

        The one door out of the wrapper, deliberately named so every call
        site that takes the key back into a local is visible in a grep.  An
        unsealed backup is the recovery path's last step, so the integrity
        tag is checked on the way: a backup that fails to open raises
        :class:`UnsealedKeyError` rather than returning bytes that look like
        a key and are not.
        """
        return _open(self._envelope, seal_secret)


class BackupStore:
    """One durable sink for a sealed key backup — one of the two stores.

    The abstraction the two-store rule quantifies over.  A store *holds* a
    sealed :class:`SealedKeyBackup` durably and returns it on recall; it
    never sees the seal secret and never opens the envelope — the seal is
    the backup's lock and the store is only its vault.  Concrete stores
    (an in-memory hold for tests, a ``0o600`` file for a single-machine
    deployment) implement :meth:`write`, :meth:`read` and :meth:`delete`;
    the identity halves (:meth:`name`, :meth:`store_id`) are what
    :class:`KeyBackup` checks for independence.

    Subclass this for a real backend — a KMS blob, a sops/age document, an
    HSM partition — and implement the three I/O methods; the seal, the
    two-store rule and the reconciliation stay here, so a new backend adds
    no new crypto and no new reconciliation logic.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise KeyBackupError(
                f"a backup store must have a non-empty name, got {name!r}. "
                "The name is how the two stores are told apart and how a "
                "receipt and an audit line say which store held the key — a "
                "store that cannot be named cannot be one of two "
                "(feature 155)."
            )
        self._name = name.strip()

    @property
    def name(self) -> str:
        """This store's name — one half of the independence check."""
        return self._name

    @property
    def store_id(self) -> str:
        """This store's durability-domain identity.

        The whole of "is this store independent of that one": two stores
        sharing a ``store_id`` share a failure mode and are refused.  The
        base class keys it on ``(name, type)`` — so two stores with the same
        name, or two bare base stores, are the same domain — and concrete
        stores widen it (a file store adds its resolved path).
        """
        return f"{type(self).__name__}:{self._name}"

    def write(self, backup: SealedKeyBackup) -> None:
        """Persist ``backup`` durably.  Abstract: a concrete store holds it."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement write() (feature 155)."
        )

    def read(self) -> SealedKeyBackup | None:
        """Return the held backup, or ``None`` when this store holds none.

        ``None`` — not an exception — is a deliberate answer: a store that
        was never written, or whose object was lost, is a *miss*, and a miss
        on one of two stores is recoverable (the other still holds the key).
        It is :class:`StoreReadError`'s subject only when the store could not
        be read at all; the distinction lets a restore fall through to the
        intact store instead of failing on the first empty one.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement read() (feature 155)."
        )

    def delete(self) -> None:
        """Remove this store's backup.  Abstract: a concrete store drops it."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement delete() (feature 155)."
        )


class InMemoryBackupStore(BackupStore):
    """A store that holds the sealed backup in process memory.

    The test double and the ephemeral deployment: it keeps the sealed bytes
    in an instance attribute, so a backup written to it can be recalled in
    the same process, and nothing survives the process.  It is a store like
    any other to :class:`KeyBackup` — the two-store rule and the
    reconciliation do not care where the bytes live — which is why the suite
    exercises the real logic through it rather than around it.  Instance
    state, not class state: two in-memory stores are two independent places,
    and a shared class attribute would make them one.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._held: bytes | None = None

    def write(self, backup: SealedKeyBackup) -> None:
        self._held = backup.envelope

    def read(self) -> SealedKeyBackup | None:
        return SealedKeyBackup(self._held) if self._held is not None else None

    def delete(self) -> None:
        self._held = None


class FileBackupStore(BackupStore):
    """A store that persists the sealed backup to a single ``0o600`` file.

    The single-machine and operator-script spelling of "an independent
    store": the sealed bytes are written to a file the way the null
    sidecar is — created ``0o600`` before any byte lands, swapped in with
    :func:`os.replace` so a reader sees the whole old backup or the whole
    new one, never a half-written one, and a crash mid-write leaves a stray
    ``.tmp`` rather than a corrupt backup.  The file holds the *sealed*
    envelope, so its ``0o600`` is a second lock on an already-locked
    object, not the only one.  A distinct path is a distinct ``store_id``,
    so two file stores in two directories are independent and two handles
    to one path are not.
    """

    def __init__(self, name: str, path: str | os.PathLike[str]) -> None:
        super().__init__(name)
        import pathlib

        self._path = pathlib.Path(path)

    @property
    def store_id(self) -> str:
        # A file store's durability domain is its path, not its name: two
        # file stores in different directories survive each other's loss, two
        # handles to one path do not — so the domain is keyed on the resolved
        # path alone.  Resolved, so ``./backup`` and the same file reached by
        # an absolute path are correctly read as one store.
        try:
            resolved = str(self._path.resolve())
        except OSError:
            resolved = str(self._path)
        return f"{type(self).__name__}:{resolved}"

    def write(self, backup: SealedKeyBackup) -> None:
        directory = self._path.parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        except OSError as exc:
            raise StoreWriteError(
                f"the backup store directory {directory} could not be "
                f"prepared: {exc} (feature 155)."
            ) from exc
        temporary = directory / f".{self._path.name}.{os.getpid()}.tmp"
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            try:
                os.write(descriptor, backup.envelope)
            finally:
                os.close(descriptor)
            os.replace(temporary, self._path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:  # pragma: no cover - cleanup only
                pass
            raise StoreWriteError(
                f"the backup store at {self._path} could not be written: "
                f"{exc} (feature 155)."
            ) from exc

    def read(self) -> SealedKeyBackup | None:
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StoreReadError(
                f"the backup store at {self._path} could not be read: {exc} "
                "(feature 155)."
            ) from exc
        return SealedKeyBackup(data)

    def delete(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StoreReadError(
                f"the backup store at {self._path} could not be removed: "
                f"{exc} (feature 155)."
            ) from exc


#: The sidecar key's length, named here rather than imported — the null
#: oracle member is deliberately not on infra/security's import graph, so
#: the constant is restated (and the refusal cites its true home) rather
#: than reached across the workspace boundary.
_SIDECAR_KEY_BYTES: Final[int] = 32


class BackupReceipt:
    """The record of a successful two-store backup — what the minting path keeps.

    Names the two stores that hold the key, the digest they both hold (so a
    later audit can confirm they still agree without opening either), and
    when the backup was made.  It is the proof the backup happened and the
    index a restore starts from; it carries no key material and no seal
    secret, so it is safe to log and to keep beside the campaign records
    that feature 111's ``created`` flag tells the minting path to annotate
    with it.
    """

    __slots__ = ("digest", "store_ids", "timestamp")

    def __init__(self, *, store_ids: tuple[str, ...], digest: str, timestamp: float) -> None:
        self.store_ids = store_ids
        self.digest = digest
        self.timestamp = timestamp

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"BackupReceipt(stores={self.store_ids!r}, digest={self.digest!r})"
        )


class KeyBackup:
    """The two-store rule and the reconciliation between the stores.

    The whole of feature 155 as one object: :meth:`backup` seals the key
    once and writes the identical sealed envelope to exactly two
    independent stores, refusing anything fewer, anything more, or any pair
    that is not independent; :meth:`restore` reads both, refuses a
    mismatch, and opens the key only when the two stores agree; :meth:`
    audit` confirms both stores still hold the same backup without opening
    either.  It holds no state and performs no I/O of its own — the stores
    do the persisting — so it is a pure orchestrator of the seal, the count
    and the reconciliation, which are the three things the feature is about.
    """

    @staticmethod
    def _require_two_independent(
        stores: tuple[BackupStore, ...] | list[BackupStore],
    ) -> tuple[BackupStore, BackupStore]:
        """Return the two stores when they are exactly two and independent.

        The whole enforcement of "two independent stores", in one seam so
        the count rule and the independence rule cannot drift apart.  A
        count other than two is refused outright — one is the single point
        of failure, three is a deployment that misunderstood the sentence —
        and two stores that share an object, a name or a ``store_id`` are
        refused as not independent, because a pair that collapses to one
        domain under a failure is one store wearing two names.
        """
        if len(stores) != 2:
            raise InsufficientStoresError(
                f"a sidecar-key backup needs exactly two independent stores "
                f"(docs/nullius-tech-architecture.md §15), and this backup was "
                f"given {len(stores)}; one store is the single point of "
                f"failure the backup exists to remove, and more than two is a "
                f"deployment that mistook the sentence for a minimum "
                "(feature 155)."
            )
        first, second = stores[0], stores[1]
        if first is second:
            raise StoresNotIndependentError(
                f"the two backup stores are the same object ({first.name!r}); "
                "a backup written twice to one store is a backup with one "
                "failure domain, which is no backup at all — two independent "
                "stores are demanded, not two writes (feature 155)."
            )
        if first.name == second.name:
            raise StoresNotIndependentError(
                f"the two backup stores share the name {first.name!r}; the "
                "name is how the two stores are told apart in a receipt and "
                "an audit line, and two stores that cannot be named apart "
                "cannot be shown to be two — refused (feature 155)."
            )
        if first.store_id == second.store_id:
            raise StoresNotIndependentError(
                f"the two backup stores {first.name!r} and {second.name!r} "
                f"share the durability domain {first.store_id!r}; two stores "
                "that would fail together are one store, and a sidecar key "
                "backed up to one domain is the key-loss failure feature 155 "
                "exists to prevent (feature 155)."
            )
        return first, second

    def backup(
        self,
        material: bytes,
        *,
        seal_secret: bytes,
        stores: tuple[BackupStore, ...] | list[BackupStore],
        timestamp: float | None = None,
    ) -> BackupReceipt:
        """Seal ``material`` and persist it to exactly two independent stores.

        Seals once (:class:`SealedKeyBackup`) and writes the identical sealed
        envelope to both stores — the two stores are independent *storage*
        domains (a KMS, a sops document, an HSM), not two different ciphers,
        so the same sealed object in two places is the redundancy, and a
        deployment that wants each store to seal its own way supplies two
        seal secrets and two :class:`KeyBackup` calls.  Both writes must
        succeed: a backup that failed to persist to one store is refused
        whole (:class:`StoreWriteError`), never silently shipped as a
        one-store backup that would be discovered only when that store lost
        the key.  Returns a :class:`BackupReceipt` naming the two stores and
        the digest they both hold.
        """
        first, second = self._require_two_independent(stores)
        sealed = SealedKeyBackup.seal(material, seal_secret)
        for store in (first, second):
            store.write(sealed)
            held = store.read()
            if held is None or held.envelope != sealed.envelope:
                raise StoreWriteError(
                    f"the backup store {store.name!r} did not return what it "
                    "was written; a store that cannot give back the exact "
                    "bytes it took cannot be trusted to give back the key "
                    "years later, so the backup is refused rather than "
                    "believed (feature 155)."
                )
        return BackupReceipt(
            store_ids=(first.store_id, second.store_id),
            digest=sealed.digest(),
            timestamp=time.time() if timestamp is None else timestamp,
        )

    def restore(
        self,
        *,
        seal_secret: bytes,
        stores: tuple[BackupStore, ...] | list[BackupStore],
    ) -> bytes:
        """Read the key back from two stores, trusting it only when they agree.

        Reads both stores, refuses a mismatch (:class:`StoreMismatchError` —
        the two stores hold different backups, so neither can be vouched
        for), and opens the key from the first store only after the two
        stores' sealed bytes are confirmed identical.  A store that holds
        nothing (:meth:`BackupStore.read` returning ``None``) is a miss, not
        a failure: if the other store holds the backup, the key is recovered
        from it.  Only if *both* stores miss, or the surviving store's
        envelope fails its integrity tag, does the restore fail — and it
        fails loud (:class:`StoreReadError` / :class:`UnsealedKeyError`),
        because a key restored wrongly is the uninterpretable-calibration
        failure the whole feature guards against.
        """
        first, second = self._require_two_independent(stores)
        a = first.read()
        b = second.read()
        if a is None and b is None:
            raise StoreReadError(
                f"neither backup store ({first.name!r}, {second.name!r}) "
                "holds a sidecar-key backup; the key was never backed up, or "
                "both stores lost it — docs/nullius-tech-architecture.md §15's "
                "unrecoverable failure. The seal secret and the stores are "
                "still named; supply a store that holds the backup "
                "(feature 155)."
            )
        if a is None or b is None:
            surviving = b if a is None else a
            source = second if a is None else first
            return self._open_survivor(surviving, source, seal_secret)
        if a.digest() != b.digest():
            raise StoreMismatchError(
                f"the two backup stores disagree: {first.name!r} holds "
                f"{a.digest()[:12]}… and {second.name!r} holds "
                f"{b.digest()[:12]}…. A sidecar key restored from a store the "
                "other cannot confirm is a key the deployment cannot vouch "
                "for, over a world whose nulls it may not reconstruct — so a "
                "mismatch is refused rather than resolved by picking one "
                "(feature 155)."
            )
        try:
            return a.material(seal_secret)
        except UnsealedKeyError as exc:
            raise UnsealedKeyError(
                f"{exc} Both stores hold identical bytes, so the surviving "
                "redundancy could not help: the seal secret is wrong or the "
                "shared backup was altered in both domains (feature 155)."
            ) from exc

    @staticmethod
    def _open_survivor(
        surviving: SealedKeyBackup, source: BackupStore, seal_secret: bytes
    ) -> bytes:
        """Open the one store that still holds the backup, naming the miss.

        The recovery half of restore: one store lost its backup (a miss the
        two-store design is built to survive), so the key comes from the
        store that did not.  The open still checks the integrity tag, so a
        "surviving" store whose bytes were altered is refused, not served.
        """
        try:
            return surviving.material(seal_secret)
        except UnsealedKeyError as exc:
            raise UnsealedKeyError(
                f"the surviving backup store {source.name!r} failed to open: "
                f"{exc} With the other store already empty, there is no "
                "second copy to fall back to — this is the key-loss failure "
                "the second store was meant to prevent, now one store down "
                "(feature 155)."
            ) from exc

    def audit(
        self,
        *,
        stores: tuple[BackupStore, ...] | list[BackupStore],
    ) -> tuple[str, ...]:
        """Confirm both stores still hold the same backup, without opening either.

        Reads each store's sealed bytes and returns their digests — an
        operator or an audit job that holds neither the seal secret nor the
        key can still answer *do the two stores agree?*, the question that
        tells a backup is intact before it is ever needed.  Raises
        :class:`StoreMismatchError` if the two digests differ (one store
        drifted) and :class:`StoreReadError` if a store holds nothing — the
        two early warnings that a restore would later fail, surfaced here
        where they can be acted on instead of discovered over an
        uninterpretable calibration history.
        """
        first, second = self._require_two_independent(stores)
        a = first.read()
        b = second.read()
        if a is None or b is None:
            missing = [
                store.name
                for store, held in ((first, a), (second, b))
                if held is None
            ]
            raise StoreReadError(
                f"backup audit found no backup in {', '.join(missing)}; the "
                "two-store guarantee holds only while both stores hold the "
                "key, and an empty store is the first half of a key-loss "
                "failure — found now, while the other store can still be "
                "rewritten, rather than when it too is gone (feature 155)."
            )
        if a.digest() != b.digest():
            raise StoreMismatchError(
                f"backup audit: {first.name!r} holds {a.digest()[:12]}… and "
                f"{second.name!r} holds {b.digest()[:12]}… — the two stores "
                "disagree, so one drifted. A sidecar key whose two backups "
                "no longer match cannot be restored with confidence, and the "
                "drift must be repaired by rewriting both from a known-good "
                "source before either is trusted (feature 155)."
            )
        return (a.digest(), b.digest())
