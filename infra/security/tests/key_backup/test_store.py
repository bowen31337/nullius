"""Feature 155's stores: a sealed backup written, read and deleted.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 155: *System
persists a sidecar key backup to two independent stores, because key loss
makes all recorded calibration uninterpretable.*  This suite is the store
half: :class:`infra.security.key_backup.InMemoryBackupStore` and
:class:`infra.security.key_backup.FileBackupStore` — the durability sinks
the two-store rule quantifies over.  A store holds the *sealed* envelope,
never sees the seal secret, and returns on recall exactly what it was
written; the seal, the count and the reconciliation are
:class:`infra.security.key_backup.KeyBackup`'s, in ``test_backup.py``.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

from infra.security.key_backup import (
    FileBackupStore,
    InMemoryBackupStore,
    SealedKeyBackup,
    StoreReadError,
    StoreWriteError,
)


def _store_parametrize():
    """Every store this suite exercises, so the store contract is tested once."""

    def make_in_memory(name, tmp_path):
        return InMemoryBackupStore(name)

    def make_file(name, tmp_path):
        return FileBackupStore(name, tmp_path / f"{name}.bak")

    return make_in_memory, make_file


@pytest.mark.parametrize("make", _store_parametrize())
def test_write_then_read_roundtrip(make, tmp_path, backup: SealedKeyBackup, seal_secret: bytes) -> None:
    """A store returns exactly what it was written."""
    store = make("store", tmp_path)
    store.write(backup)
    assert store.read() is not None
    assert store.read().envelope == backup.envelope
    assert store.read().material(seal_secret) == backup.material(seal_secret)


@pytest.mark.parametrize("make", _store_parametrize())
def test_read_before_write_is_none(make, tmp_path) -> None:
    """An unwritten store reads as a miss (``None``), not a failure."""
    store = make("store", tmp_path)
    assert store.read() is None


@pytest.mark.parametrize("make", _store_parametrize())
def test_delete_removes_the_backup(make, tmp_path, backup: SealedKeyBackup) -> None:
    """After delete, the store reads as a miss."""
    store = make("store", tmp_path)
    store.write(backup)
    store.delete()
    assert store.read() is None


@pytest.mark.parametrize("make", _store_parametrize())
def test_store_id_is_unique_per_location(make, tmp_path) -> None:
    """A store's ``store_id`` names its durability domain — distinct per store."""
    first = make("a", tmp_path)
    second = make("b", tmp_path)
    assert first.store_id != second.store_id


def test_file_store_id_resolves_the_path(tmp_path) -> None:
    """A file store's ``store_id`` keys on the resolved path, so one file is one store."""
    path = tmp_path / "nested" / "sidecar-key.bak"
    store = FileBackupStore("kms", path)
    assert str(path.resolve()) in store.store_id


def test_file_store_write_is_0600(tmp_path, backup: SealedKeyBackup) -> None:
    """A file store's backup file is owner-only — a second lock on a sealed object."""
    path = tmp_path / "sidecar-key.bak"
    FileBackupStore("kms", path).write(backup)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_file_store_directory_is_0700(tmp_path, backup: SealedKeyBackup) -> None:
    """A file store creates its directory owner-only."""
    path = tmp_path / "nested" / "sidecar-key.bak"
    FileBackupStore("kms", path).write(backup)
    mode = stat.S_IMODE(os.stat(path.parent).st_mode)
    assert mode == 0o700


def test_file_store_write_is_atomic(tmp_path, backup: SealedKeyBackup) -> None:
    """A file store's write leaves no stray temp and a whole file."""
    path = tmp_path / "sidecar-key.bak"
    FileBackupStore("kms", path).write(backup)
    FileBackupStore("kms", path).write(backup)
    assert path.is_file()
    assert not any(tmp_path.glob(".sidecar-key.bak.*.tmp"))
    assert FileBackupStore("kms", path).read().envelope == backup.envelope


def test_file_store_read_missing_is_none(tmp_path) -> None:
    """A file store with no file reads as a miss, not a failure."""
    assert FileBackupStore("kms", tmp_path / "absent.bak").read() is None


def test_file_store_read_unreadable_raises(tmp_path, backup: SealedKeyBackup) -> None:
    """A file store whose path is a directory cannot be read — refused, not crashed."""
    directory = tmp_path / "a-directory"
    directory.mkdir()
    with pytest.raises(StoreReadError):
        FileBackupStore("kms", directory).read()


def test_file_store_write_unwritable_dir_raises(backup: SealedKeyBackup) -> None:
    """A file store whose directory cannot be made refuses the write."""
    # A path whose parent is a regular file cannot be created as a directory.
    with tempfile.NamedTemporaryFile() as handle:
        store = FileBackupStore("kms", Path(handle.name) / "sidecar-key.bak")
        with pytest.raises(StoreWriteError):
            store.write(backup)


def test_in_memory_store_is_process_local(backup: SealedKeyBackup) -> None:
    """An in-memory store holds only for the process — the ephemeral deployment."""
    store = InMemoryBackupStore("store")
    store.write(backup)
    assert store.read() is not None
    store.delete()
    assert store.read() is None
