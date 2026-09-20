"""Feature 155's rule: the sidecar key in two independent stores, reconciled.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 155: *System
persists a sidecar key backup to two independent stores, because key loss
makes all recorded calibration uninterpretable.*  This suite is the
orchestration half (:class:`infra.security.key_backup.KeyBackup`): exactly
two independent stores are demanded, a backup writes both, a restore reads
both and trusts the key only when they agree, and an audit confirms they
still agree without opening either.  The seal is in ``test_seal.py``; the
stores are in ``test_store.py``.
"""

from __future__ import annotations

import pytest

from infra.security.key_backup import (
    BackupStore,
    FileBackupStore,
    InMemoryBackupStore,
    InsufficientStoresError,
    KeyBackup,
    SealedKeyBackup,
    StoreMismatchError,
    StoreReadError,
    StoresNotIndependentError,
    StoreWriteError,
    UnsealedKeyError,
)

# -- The "two" -----------------------------------------------------------------


def test_backup_requires_exactly_two(key_material: bytes, seal_secret: bytes) -> None:
    """A backup over one store is refused — the single point of failure."""
    with pytest.raises(InsufficientStoresError):
        KeyBackup().backup(
            key_material,
            seal_secret=seal_secret,
            stores=(InMemoryBackupStore("only"),),
        )


def test_backup_refuses_more_than_two(key_material: bytes, seal_secret: bytes) -> None:
    """A backup over three stores is refused — the sentence names two, not a minimum."""
    with pytest.raises(InsufficientStoresError):
        KeyBackup().backup(
            key_material,
            seal_secret=seal_secret,
            stores=(
                InMemoryBackupStore("a"),
                InMemoryBackupStore("b"),
                InMemoryBackupStore("c"),
            ),
        )


def test_backup_refuses_the_same_object_twice(key_material: bytes, seal_secret: bytes) -> None:
    """Two writes to one store object are refused — one failure domain."""
    store = InMemoryBackupStore("same")
    with pytest.raises(StoresNotIndependentError):
        KeyBackup().backup(
            key_material, seal_secret=seal_secret, stores=(store, store)
        )


def test_backup_refuses_two_stores_with_one_name(key_material: bytes, seal_secret: bytes) -> None:
    """Two stores that cannot be named apart cannot be shown to be two."""
    with pytest.raises(StoresNotIndependentError):
        KeyBackup().backup(
            key_material,
            seal_secret=seal_secret,
            stores=(InMemoryBackupStore("dup"), InMemoryBackupStore("dup")),
        )


def test_backup_refuses_two_handles_to_one_path(tmp_path, key_material: bytes, seal_secret: bytes) -> None:
    """Two file stores to one path share a durability domain — refused."""
    path = tmp_path / "sidecar-key.bak"
    with pytest.raises(StoresNotIndependentError):
        KeyBackup().backup(
            key_material,
            seal_secret=seal_secret,
            stores=(
                FileBackupStore("kms", path),
                FileBackupStore("sops", path),
            ),
        )


def test_backup_allows_two_file_stores_in_two_dirs(tmp_path, key_material: bytes, seal_secret: bytes) -> None:
    """Two file stores in two directories are independent — the real thing."""
    stores = (
        FileBackupStore("kms", tmp_path / "kms" / "sidecar-key.bak"),
        FileBackupStore("sops", tmp_path / "sops" / "sidecar-key.age"),
    )
    receipt = KeyBackup().backup(
        key_material, seal_secret=seal_secret, stores=stores
    )
    assert receipt.store_ids == (stores[0].store_id, stores[1].store_id)


# -- backup --------------------------------------------------------------------


def test_backup_writes_both_stores(two_stores, key_material: bytes, seal_secret: bytes) -> None:
    """A backup writes the identical sealed envelope to both stores."""
    stores, backup = two_stores
    receipt = backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    assert stores[0].read() is not None
    assert stores[1].read() is not None
    # Identical sealed object in both places — that is the redundancy.
    assert stores[0].read().envelope == stores[1].read().envelope
    # Both stores' digest matches the receipt's — the audit vocabulary.
    assert receipt.digest == stores[0].read().digest()
    assert receipt.digest == stores[1].read().digest()
    # And the sealed bytes open back to the key under the seal secret.
    assert stores[0].read().material(seal_secret) == key_material


def test_backup_restores(mem_stores, key_material, seal_secret: bytes) -> None:
    """A backup followed by a restore returns the key."""
    stores, backup = mem_stores
    backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    assert backup.restore(seal_secret=seal_secret, stores=stores) == key_material


def test_backup_refuses_a_store_that_will_not_give_back(tmp_path, key_material: bytes, seal_secret: bytes) -> None:
    """A store that cannot return what it was written is refused — never believed."""

    class _LosingStore(BackupStore):
        """A store that swallows every write — the silent one-store backup."""

        def write(self, backup: SealedKeyBackup) -> None:
            pass

        def read(self) -> SealedKeyBackup | None:
            return None

        def delete(self) -> None:
            pass

    stores = (InMemoryBackupStore("good"), _LosingStore("losing"))
    with pytest.raises(StoreWriteError):
        KeyBackup().backup(
            key_material, seal_secret=seal_secret, stores=stores
        )


def test_backup_receipt_carries_no_key(mem_stores, key_material: bytes, seal_secret: bytes) -> None:
    """A receipt names the stores and the digest, and carries no key material."""
    stores, backup = mem_stores
    receipt = backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    assert key_material not in receipt.store_ids
    assert key_material.hex().encode() not in repr(receipt).encode()
    assert len(receipt.digest) == 64


# -- restore -------------------------------------------------------------------


def test_restore_refuses_a_mismatch(mem_stores, backup, seal_secret: bytes) -> None:
    """Two stores holding different backups are refused — neither can be vouched for."""
    stores, key_backup = mem_stores
    stores[0].write(backup)
    # The second store holds a *different* key's backup.
    stores[1].write(SealedKeyBackup.seal(bytes(range(1, 33)), seal_secret))
    with pytest.raises(StoreMismatchError):
        key_backup.restore(seal_secret=seal_secret, stores=stores)


def test_restore_recovers_when_one_store_is_empty(mem_stores, key_material, seal_secret: bytes) -> None:
    """A backup survives one store losing its bytes — recovered from the other."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    stores[0].delete()  # one store down
    assert key_backup.restore(seal_secret=seal_secret, stores=stores) == key_material


def test_restore_fails_loud_when_both_stores_empty(mem_stores, seal_secret: bytes) -> None:
    """Both stores empty is the unrecoverable failure — refused, not mis-served."""
    stores, key_backup = mem_stores
    with pytest.raises(StoreReadError):
        key_backup.restore(seal_secret=seal_secret, stores=stores)


def test_restore_refuses_a_corrupt_survivor(mem_stores, backup, other_secret, seal_secret: bytes) -> None:
    """A surviving store whose bytes will not open is refused — no second copy left."""
    stores, key_backup = mem_stores
    stores[0].write(backup)
    stores[1].delete()  # the other store is gone
    with pytest.raises(UnsealedKeyError):
        key_backup.restore(seal_secret=other_secret, stores=stores)


def test_restore_rejects_the_wrong_secret(
    mem_stores, key_material: bytes, seal_secret: bytes, other_secret: bytes
) -> None:
    """A restore under the wrong seal secret is refused, not mis-served."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    with pytest.raises(UnsealedKeyError):
        key_backup.restore(seal_secret=other_secret, stores=stores)


def test_restore_agrees_only_when_stores_agree(mem_stores, key_material, seal_secret: bytes) -> None:
    """A restore trusts the key only after the two stores are confirmed identical."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    # The two stores hold the same sealed bytes — restore opens from the first.
    assert stores[0].read().envelope == stores[1].read().envelope
    assert key_backup.restore(seal_secret=seal_secret, stores=stores) == key_material


# -- audit ---------------------------------------------------------------------


def test_audit_confirms_agreement(mem_stores, key_material: bytes, seal_secret: bytes) -> None:
    """An audit confirms both stores hold the same backup, without opening either."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    digests = key_backup.audit(stores=stores)
    assert digests == (stores[0].read().digest(), stores[1].read().digest())


def test_audit_flags_a_drift(mem_stores, backup, key_material: bytes, seal_secret: bytes) -> None:
    """An audit catches a store that drifted — one store's early warning."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    stores[1].write(SealedKeyBackup.seal(bytes(range(1, 33)), seal_secret))
    with pytest.raises(StoreMismatchError):
        key_backup.audit(stores=stores)


def test_audit_flags_an_empty_store(mem_stores, key_material: bytes, seal_secret: bytes) -> None:
    """An audit catches a store that went empty — the first half of a key loss."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    stores[0].delete()
    with pytest.raises(StoreReadError):
        key_backup.audit(stores=stores)


def test_audit_needs_no_secret(mem_stores, key_material: bytes, seal_secret: bytes) -> None:
    """An audit answers without the seal secret or the key — the operator's check."""
    stores, key_backup = mem_stores
    key_backup.backup(key_material, seal_secret=seal_secret, stores=stores)
    # No seal_secret argument: the audit compares sealed bytes only.
    key_backup.audit(stores=stores)


# -- end to end ----------------------------------------------------------------


def test_backup_then_restore_roundtrip_file_stores(tmp_path, key_material, seal_secret: bytes) -> None:
    """The whole path over real file stores: seal, two writes, reconcile, restore."""
    stores = (
        FileBackupStore("kms", tmp_path / "kms" / "sidecar-key.bak"),
        FileBackupStore("sops", tmp_path / "sops" / "sidecar-key.age"),
    )
    receipt = KeyBackup().backup(
        key_material, seal_secret=seal_secret, stores=stores
    )
    assert KeyBackup().audit(stores=stores) == (receipt.digest, receipt.digest)
    assert KeyBackup().restore(seal_secret=seal_secret, stores=stores) == key_material


def test_backup_then_audit_then_restore_with_one_store_down(tmp_path, key_material, seal_secret: bytes) -> None:
    """A file-store backup survives one store's loss: audit flags it, restore recovers."""
    stores = (
        FileBackupStore("kms", tmp_path / "kms" / "sidecar-key.bak"),
        FileBackupStore("sops", tmp_path / "sops" / "sidecar-key.age"),
    )
    KeyBackup().backup(key_material, seal_secret=seal_secret, stores=stores)
    stores[0].delete()
    with pytest.raises(StoreReadError):
        KeyBackup().audit(stores=stores)  # audit flags the empty store
    assert KeyBackup().restore(seal_secret=seal_secret, stores=stores) == key_material
