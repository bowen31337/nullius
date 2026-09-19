"""The member's seat inside the ``app`` package namespace.

``src/app/modules/snapshot/__init__.py`` is where the composed snapshot
component is reachable from the ``app`` package without the app package
importing the member at module scope. The snapshot suite owns this file (it
is inside the feature's declared footprint), so the seat is tested here
rather than in a repository-level suite — the repository-level ``tests/``
conftest does not reach package-local tests, and the member's own conftest
already reproduces the lake isolation this needs.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none. That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from app.module_loader import Application

_FACTORY_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_FACTORY_SRC) not in sys.path:
    sys.path.insert(0, str(_FACTORY_SRC))


def test_the_seat_exposes_the_composed_snapshot_service(lake_root: Path) -> None:
    from app.modules.snapshot import COMPONENT_NAME, snapshot_component

    assert COMPONENT_NAME == "snapshot"
    service = snapshot_component()
    assert type(service).__name__ == "SnapshotService"
    assert service.lake_root == lake_root


def test_the_seat_reads_from_an_application_it_is_handed(lake_root: Path) -> None:
    from app.modules.snapshot import COMPONENT_NAME, snapshot_component

    application = Application(components={COMPONENT_NAME: "sentinel"}, order=(COMPONENT_NAME,))
    assert snapshot_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.snapshot import snapshot_component

    empty = Application(components={}, order=())
    assert snapshot_component(empty) is None


def test_the_seat_can_seal_and_mount(lake_root: Path) -> None:
    # The evaluator-facing path, one level up: composed service, sealed
    # snapshot, read-only mount, refused write — from the app namespace.
    from app.modules.snapshot import snapshot_component

    service = snapshot_component()
    staging = lake_root / "staging"
    (staging / "bars").mkdir()
    (staging / "bars" / "part-0.parquet").write_bytes(b"seated bytes")
    record = service.seal(sealed_at="2026-09-01T00:00:00Z", snapshot_hash="a3f91c" + "0" * 58)

    mount = service.mount(record.name)
    part = mount.root / "bars" / "part-0.parquet"
    assert part.read_bytes() == b"seated bytes"
    with pytest.raises(PermissionError, match="read-only"):
        part.write_bytes(b"tampered")
    assert part.read_bytes() == b"seated bytes"


def test_the_seat_verifies_on_open_and_emits_the_corruption_alert(
    lake_root: Path,
) -> None:
    # Feature 36 from the app namespace: the composed service re-hashes a
    # snapshot when it is opened, so bytes touched after sealing refuse the
    # open with the corruption alert rather than being served read-only.
    # The service comes from the factory's scanned copy of the member
    # (``_nullius_scanned_snapshot``), whose classes are distinct objects
    # from the ``snapshot`` package this suite imports — the same reason
    # the tests above assert by type name — so the alert is asserted by
    # attribute and the digest, not by class identity.
    from app.modules.snapshot import snapshot_component

    service = snapshot_component()
    staging = lake_root / "staging"
    (staging / "bars").mkdir()
    (staging / "bars" / "part-0.parquet").write_bytes(b"seated bytes")
    record = service.seal(sealed_at="2026-09-01T00:00:00Z", snapshot_hash="a3f91c" + "0" * 58)

    sealed_file = record.path / "bars" / "part-0.parquet"
    os.chmod(sealed_file, 0o644)  # the owner-chmod crack _mount documents
    sealed_file.write_bytes(b"tampered after sealing")
    os.chmod(sealed_file, 0o444)

    with pytest.raises(Exception, match="is corrupt") as raised:
        service.mount(record.name)
    assert type(raised.value).__name__ == "SnapshotCorruptionError"
    (finding,) = raised.value.alert.findings
    assert finding.path == "bars/part-0.parquet"
    assert finding.recomputed == hashlib.sha256(b"tampered after sealing").hexdigest()
