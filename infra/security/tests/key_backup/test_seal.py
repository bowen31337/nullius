"""Feature 155's seal: the sidecar key sealed into an authenticated envelope.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 155: *System
persists a sidecar key backup to two independent stores, because key loss
makes all recorded calibration uninterpretable.*  This suite is the seal
half (:class:`infra.security.key_backup.SealedKeyBackup`): the key is
sealed into an authenticated envelope that authenticates on recall, opens
only under the right seal secret, and carries no key material in the clear.
The two-store rule and the reconciliation are feature 155's other half, in
``test_backup.py``; the file store is in ``test_store.py``.
"""

from __future__ import annotations

import pytest

from infra.security.key_backup import (
    MAGIC,
    SealedKeyBackup,
    SealError,
    StoreReadError,
    UnsealedKeyError,
    digest_of,
)


def test_seal_roundtrip_returns_the_key(
    backup: SealedKeyBackup, key_material: bytes, seal_secret: bytes
) -> None:
    """A backup sealed under a secret opens to the same key under that secret."""
    assert backup.material(seal_secret) == key_material


def test_seal_is_authenticated_against_tampering(
    backup: SealedKeyBackup, seal_secret: bytes
) -> None:
    """Flipping one sealed byte fails the integrity check, not the key."""
    tampered = bytearray(backup.envelope)
    tampered[-1] ^= 0x01
    with pytest.raises(UnsealedKeyError):
        SealedKeyBackup(bytes(tampered)).material(seal_secret)


def test_seal_refuses_the_wrong_secret(
    backup: SealedKeyBackup, other_secret: bytes
) -> None:
    """A backup opened under the wrong seal secret is refused, not mis-served."""
    with pytest.raises(UnsealedKeyError):
        backup.material(other_secret)


def test_seal_draws_a_fresh_nonce(key_material: bytes, seal_secret: bytes) -> None:
    """Two seals of the same key differ — a fresh nonce per seal."""
    first = SealedKeyBackup.seal(key_material, seal_secret)
    second = SealedKeyBackup.seal(key_material, seal_secret)
    assert first.envelope != second.envelope
    # But both open to the same key: the nonce rides the envelope, not a key.
    assert first.material(seal_secret) == second.material(seal_secret) == key_material


def test_seal_begins_with_the_marker(backup: SealedKeyBackup) -> None:
    """A sealed backup begins with MAGIC — recognizable before an unseal."""
    assert backup.envelope.startswith(MAGIC)


def test_seal_refuses_non_bytes(seal_secret: bytes) -> None:
    """A non-bytes key to back up is refused at the seal."""
    with pytest.raises(SealError):
        SealedKeyBackup.seal("not-bytes", seal_secret)  # type: ignore[arg-type]


def test_seal_refuses_wrong_length(seal_secret: bytes) -> None:
    """A key of the wrong length is refused — it would restore into the wrong key."""
    with pytest.raises(SealError):
        SealedKeyBackup.seal(b"too-short", seal_secret)


def test_seal_refuses_empty_material(seal_secret: bytes) -> None:
    """An empty key is refused, not sealed into a key-shaped envelope."""
    with pytest.raises(SealError):
        SealedKeyBackup.seal(b"", seal_secret)


def test_digest_is_stable_and_key_free(
    backup: SealedKeyBackup, key_material: bytes, seal_secret: bytes
) -> None:
    """A backup's digest is stable and computable without the seal secret."""
    assert backup.digest() == digest_of(backup.envelope)
    assert len(backup.digest()) == 64
    # Two seals of the same key differ (fresh nonce), so their digests differ.
    assert SealedKeyBackup.seal(key_material, seal_secret).digest() != backup.digest()


def test_material_does_not_leak_from_repr(
    backup: SealedKeyBackup, key_material: bytes
) -> None:
    """A sealed backup's repr carries no key material."""
    assert key_material.hex().encode() not in repr(backup).encode()
    assert "SealedKeyBackup" in repr(backup)


def test_sealed_backup_holds_no_plaintext(
    backup: SealedKeyBackup, key_material: bytes
) -> None:
    """The sealed envelope does not contain the key bytes in the clear."""
    assert key_material not in backup.envelope


def test_open_refuses_a_non_bytes_envelope() -> None:
    """Opening a non-bytes envelope is refused, not crashed."""
    with pytest.raises(SealError):
        SealedKeyBackup("nope")  # type: ignore[arg-type]


def test_digest_refuses_non_bytes() -> None:
    """A digest over non-bytes is refused — its subject is the stored object."""
    with pytest.raises(StoreReadError):
        digest_of("nope")  # type: ignore[arg-type]
