"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory scans
the workspace members, imports this package, and the ``@register`` builder
lands in the composed application as the ``snapshot`` component, bound to
the lake the environment names. No registry, router or factory was edited
to make that true; this test exists to keep it true.

One property of the loader shapes these tests: it imports each member under
a synthetic module name (``_nullius_scanned_snapshot``), so a package that
this suite also imported canonically as ``snapshot`` exists in the process
twice, with two distinct class objects. ``isinstance`` across the copies
cannot hold, so the composed component is pinned by class name, module
suffix, and — decisively — behaviour.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.module_loader import create_app


def _assert_is_the_snapshot_service(component: object) -> None:
    assert type(component).__name__ == "SnapshotService"
    assert type(component).__module__.endswith("snapshot._service")
    for operation in ("seal", "open", "sealed"):
        assert callable(getattr(component, operation)), operation


def test_composed_application_carries_the_snapshot_component(
    lake_root: Path,
) -> None:
    app = create_app()
    component = app.get("snapshot")
    _assert_is_the_snapshot_service(component)
    assert component.lake_root == lake_root  # type: ignore[attr-defined]
    assert os.environ["LAKE_ROOT"] == str(lake_root)


def test_sealing_through_the_composed_service(lake_root: Path) -> None:
    app = create_app()
    service = app.get("snapshot")
    _assert_is_the_snapshot_service(service)

    staging = lake_root / "staging"
    (staging / "bars").mkdir()
    (staging / "bars" / "part-0.parquet").write_bytes(b"composed bytes")

    record = service.seal(  # type: ignore[attr-defined]
        staging, sealed_at=datetime(2026, 9, 1, tzinfo=timezone.utc)
    )

    expected = lake_root / "snapshots" / f"2026-09-01T00:00:00Z_{record.hash_prefix}"
    assert record.path == expected
    assert record.path.is_dir()
    assert (record.path / "bars" / "part-0.parquet").read_bytes() == b"composed bytes"


def test_builder_rebinds_when_the_environment_moves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # ``from_env`` is evaluated at build time, so a recomposed application
    # follows a moved LAKE_ROOT — the process is always sealing into the
    # lake it is pointed at *now*.
    first = create_app().get("snapshot")
    _assert_is_the_snapshot_service(first)
    assert first.lake_root != tmp_path  # type: ignore[attr-defined]

    moved = tmp_path / "another-lake"
    monkeypatch.setenv("LAKE_ROOT", str(moved))
    second = create_app().get("snapshot")
    _assert_is_the_snapshot_service(second)
    assert second.lake_root == moved  # type: ignore[attr-defined]
