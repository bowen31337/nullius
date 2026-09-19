"""Verification on open: recomputed hashes against the recorded ones.

app_spec.xml feature 36 — *"System verifies a snapshot on open by
recomputing file hashes, which emits a corruption alert when any recorded
sha256 fails to match"* — has two claims, and this suite tests them as
separately as they can fail:

* **verifies on open** — the door itself recomputes: ``open``, and every
  door built on it (``mount``, ``read_manifest``, the ``mounted`` sweep),
  re-hashes the tree against the manifest's per-file sha256 entries, so a
  snapshot whose bytes were touched after sealing is refused *before* any
  handle exists, not discovered after the tampered bytes were read;
* **emits a corruption alert** — the refusal is not a bare exception: it
  carries :class:`~snapshot.CorruptionAlert`, one
  :class:`~snapshot.CorruptionFinding` per discrepancy with the recorded
  and recomputed digests side by side, rendered into the message and
  returned as data by ``verify``/``verify_all`` for callers that want the
  alert without the refusal.

The tampering model is the one ``_mount`` documents as the crack: the
sealed modes are ownership-governed, so the sealing user (every test here
runs as that user) can ``chmod`` a file writable, write, and put the mode
back. No API layer can prevent that write; verification is what detects
it, so every corruption below is planted through exactly that crack —
and the mode-repair and symlink-refusal layers that act *after* a tree is
known bad are tested in ``test_mount.py`` through the ``verify=False``
seam, which exists so those layers can be exercised in isolation.

Three findings are the alert's whole vocabulary, and each is planted
once: a hash mismatch (bytes changed), a missing file (a recorded path
gone), and an unrecorded node (an injected file or planted symlink the
manifest never covered — the finding that keeps tampered-*in* content
from riding under an honest identity).
"""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    HASH_MISMATCH,
    MANIFEST_VERSION,
    MISSING_FILE,
    UNRECORDED_NODE,
    CorruptionAlert,
    CorruptionFinding,
    SealedSnapshot,
    SnapshotContentError,
    SnapshotCorruptionError,
    SnapshotError,
    SnapshotManifest,
    SnapshotManifestError,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotStagingRequestError,
    verify_snapshot,
    verify_tree,
)

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
AT_LATER = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)
HASH = "a3f91c" + "0" * 58
NAME = "2026-09-01T00:00:00Z_a3f91c"

BTC_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_1 = b"BTCUSDT-2026-09-01-part-1"
PART_0 = "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"
PART_1 = "bars/symbol=BTCUSDT/date=2026-09-01/part-1.parquet"


# -- Planting corruption through the documented crack -------------------------


def _tamper(sealed_file: Path, payload: bytes) -> None:
    """Overwrite a sealed file's bytes through the owner-``chmod`` crack.

    The write itself is the corruption being planted; the mode goes back to
    ``0444`` afterwards so the finding cannot be mistaken for drift the
    mode re-assertion would repair — verification must catch the *bytes*,
    not the permissions.
    """
    os.chmod(sealed_file, 0o644)
    sealed_file.write_bytes(payload)
    os.chmod(sealed_file, 0o444)


def _plant(sealed_dir_parent: Path, name: str, payload: bytes) -> Path:
    """Inject a new file the manifest never recorded."""
    os.chmod(sealed_dir_parent, 0o755)
    planted = sealed_dir_parent / name
    planted.write_bytes(payload)
    os.chmod(sealed_dir_parent, 0o555)
    return planted


def _remove(sealed_file: Path) -> None:
    """Delete a recorded file (unlink needs the parent's write bit, not the
    file's own — the frozen ``0444`` never protected against removal)."""
    os.chmod(sealed_file.parent, 0o755)
    sealed_file.unlink()
    os.chmod(sealed_file.parent, 0o555)


def _plant_link(sealed_dir_parent: Path, name: str, target: Path) -> Path:
    """Plant a symlink inside the sealed tree, pointing outside it."""
    os.chmod(sealed_dir_parent, 0o755)
    link = sealed_dir_parent / name
    os.symlink(target, link)
    os.chmod(sealed_dir_parent, 0o555)
    return link


@pytest.fixture
def sealed(service: SnapshotService, staged: Path) -> SealedSnapshot:
    """A cleanly sealed snapshot over the shared staged tree."""
    return service.seal(staged, sealed_at=AT, snapshot_hash=HASH)


class TestOpeningVerifies:
    """The door recomputes the hashes, and refuses on any mismatch."""

    def test_a_clean_snapshot_opens_and_re_opens(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        # The manifest that describes the content is present in the tree and
        # must not itself become a finding — it is excluded from the walk,
        # exactly as it was excluded from the seal's content identity.
        assert service.open(sealed.name) is not None
        assert service.open(sealed.name).path == sealed.path
        assert service.verify(sealed.name) is None

    def test_tampered_bytes_refuse_the_open(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered bytes")
        with pytest.raises(SnapshotCorruptionError) as raised:
            service.open(sealed.name)
        message = str(raised.value)
        assert "is corrupt" in message
        assert PART_0 in message
        assert hashlib.sha256(BTC_0).hexdigest() in message  # the recorded digest
        assert hashlib.sha256(b"tampered bytes").hexdigest() in message

    def test_the_error_carries_the_alert_as_a_record(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered bytes")
        with pytest.raises(SnapshotCorruptionError) as raised:
            service.open(sealed.name)
        alert = raised.value.alert
        assert isinstance(alert, CorruptionAlert)
        assert alert.snapshot == sealed.name
        assert alert.files_checked == 3
        (finding,) = alert.findings
        assert finding.path == PART_0
        assert finding.kind == HASH_MISMATCH
        assert finding.recorded == hashlib.sha256(BTC_0).hexdigest()
        assert finding.recomputed == hashlib.sha256(b"tampered bytes").hexdigest()

    def test_the_alert_is_catchable_as_a_snapshot_error(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered bytes")
        with pytest.raises(SnapshotError):
            service.open(sealed.name)

    def test_every_door_inherits_the_check(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered bytes")
        with pytest.raises(SnapshotCorruptionError):
            service.mount(sealed.name)
        with pytest.raises(SnapshotCorruptionError):
            service.read_manifest(sealed.name)

    def test_the_owner_chmod_write_is_caught_on_the_next_open(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        # The exact scenario test_mount.py documents as the crack in layer
        # 1: the modes are widened, the write happens, the mode goes back.
        # Mode re-assertion repairs the permissions; verification is what
        # notices the bytes.
        victim = sealed.path / PART_0
        os.chmod(victim, 0o666)
        victim.write_bytes(b"written while loose")
        os.chmod(victim, 0o444)
        with pytest.raises(SnapshotCorruptionError, match="is corrupt") as raised:
            service.mount(sealed.name)
        assert hashlib.sha256(b"written while loose").hexdigest() in str(raised.value)

    def test_corruption_is_reported_not_repaired(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        # Verification reads and never writes: the tampered bytes stay
        # tampered, the manifest stays exactly as sealed, and the frozen
        # modes are neither widened nor re-applied. Dealing with a corrupt
        # snapshot is an operator decision; silently rewriting anything
        # would be a second corruption.
        manifest_bytes = (sealed.path / "MANIFEST.json").read_bytes()
        _tamper(sealed.path / PART_0, b"tampered bytes")
        with pytest.raises(SnapshotCorruptionError):
            service.open(sealed.name)
        assert (sealed.path / PART_0).read_bytes() == b"tampered bytes"
        assert stat.S_IMODE((sealed.path / PART_0).stat().st_mode) == 0o444
        assert (sealed.path / "MANIFEST.json").read_bytes() == manifest_bytes


class TestTheAlertRecord:
    """The alert names every way the tree is not its record."""

    def test_every_mismatch_is_a_finding_sorted_by_path(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_1, b"first tampered")
        _tamper(sealed.path / PART_0, b"second tampered")
        alert = service.verify(sealed.name)
        assert alert is not None
        assert [finding.path for finding in alert.findings] == [PART_0, PART_1]
        assert alert.files_checked == 3
        assert alert.mismatches == alert.findings  # both are mismatch kind

    def test_a_missing_recorded_file_is_a_finding(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _remove(sealed.path / PART_0)
        alert = service.verify(sealed.name)
        assert alert is not None
        (finding,) = alert.findings
        assert finding.path == PART_0
        assert finding.kind == MISSING_FILE
        assert finding.recorded == hashlib.sha256(BTC_0).hexdigest()
        assert finding.recomputed is None  # nothing on disk to hash

    def test_an_injected_file_is_an_unrecorded_finding(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        # The mount serves paths, so a file the manifest does not cover
        # would be read as if it were sealed; the record comparison is the
        # only thing that catches it.
        _plant(sealed.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01", "part-9.parquet", b"injected")
        alert = service.verify(sealed.name)
        assert alert is not None
        (finding,) = alert.findings
        assert finding.path == "bars/symbol=BTCUSDT/date=2026-09-01/part-9.parquet"
        assert finding.kind == UNRECORDED_NODE
        assert finding.recorded is None
        assert finding.recomputed == hashlib.sha256(b"injected").hexdigest()

    def test_a_planted_symlink_is_an_unrecorded_finding(
        self, service: SnapshotService, sealed: SealedSnapshot, lake_root: Path
    ) -> None:
        secret = lake_root / "staging" / "secret.parquet"
        secret.write_bytes(b"staging secret")
        _plant_link(sealed.path, "escape", secret)
        alert = service.verify(sealed.name)
        assert alert is not None
        (finding,) = alert.findings
        assert finding.path == "escape"
        assert finding.kind == UNRECORDED_NODE
        assert finding.recomputed is None  # a link's bytes are somebody else's

    def test_a_symlink_over_a_recorded_file_is_a_mismatch(
        self, service: SnapshotService, sealed: SealedSnapshot, lake_root: Path
    ) -> None:
        # The recorded path now holds a node whose bytes cannot honestly be
        # recomputed at all — the recorded sha256 has failed to match in the
        # strongest possible way.
        secret = lake_root / "staging" / "secret.parquet"
        secret.write_bytes(b"staging secret")
        _remove(sealed.path / PART_0)
        _plant_link(sealed.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01", "part-0.parquet", secret)
        alert = service.verify(sealed.name)
        assert alert is not None
        (finding,) = alert.findings
        assert finding.path == PART_0
        assert finding.kind == HASH_MISMATCH
        assert finding.recorded == hashlib.sha256(BTC_0).hexdigest()
        assert finding.recomputed is None

    def test_all_three_kinds_can_coexist(
        self, service: SnapshotService, sealed: SealedSnapshot, lake_root: Path
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered")
        _remove(sealed.path / PART_1)
        _plant(sealed.path, "injected.parquet", b"injected")
        alert = service.verify(sealed.name)
        assert alert is not None
        assert [finding.kind for finding in alert.findings] == [
            HASH_MISMATCH,
            MISSING_FILE,
            UNRECORDED_NODE,
        ]
        summary = alert.summary()
        for finding in alert.findings:
            assert finding.path in summary

    def test_findings_are_sorted_wherever_they_come_from(self) -> None:
        # An alert replayed from a record (a monitor, a log) renders as
        # deterministically as one the walker built.
        alert = CorruptionAlert(
            snapshot=NAME,
            files_checked=2,
            findings=(
                CorruptionFinding(path="b.parquet", kind=MISSING_FILE, recorded="0" * 64),
                CorruptionFinding(path="a.parquet", kind=HASH_MISMATCH, recorded="0" * 64, recomputed="1" * 64),
            ),
        )
        assert [finding.path for finding in alert.findings] == ["a.parquet", "b.parquet"]
        assert alert.missing[0].path == "b.parquet"
        assert alert.mismatches[0].path == "a.parquet"
        assert alert.unrecorded == ()


class TestVerifyWithoutRaising:
    """The same check, returned as data for callers that report, not stop."""

    def test_verify_returns_none_for_a_clean_snapshot(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        assert service.verify(sealed.name) is None

    def test_verify_returns_the_alert_without_raising(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered bytes")
        alert = service.verify(sealed.name)
        assert isinstance(alert, CorruptionAlert)
        with pytest.raises(SnapshotCorruptionError) as raised:
            service.open(sealed.name)
        assert raised.value.alert == alert  # the same findings, either door

    def test_verify_goes_through_the_door(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        with pytest.raises(SnapshotStagingRequestError):
            service.verify("staging")
        with pytest.raises(SnapshotNameError):
            service.verify("not-a-name")
        with pytest.raises(SnapshotNotFoundError):
            service.verify("2026-09-01T00:00:00Z_000000")

    def test_verify_all_is_empty_on_a_healthy_lake(
        self, service: SnapshotService, staged: Path
    ) -> None:
        service.seal(staged, sealed_at=AT)
        staged.joinpath("bars", "extra.parquet").write_bytes(b"extra")
        service.seal(staged, sealed_at=AT_LATER)
        assert service.verify_all() == ()

    def test_verify_all_reports_every_corrupt_snapshot(
        self, service: SnapshotService, staged: Path
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        staged.joinpath("bars", "extra.parquet").write_bytes(b"extra")
        second = service.seal(staged, sealed_at=AT_LATER)
        _tamper(first.path / PART_0, b"tampered in the first")
        _plant(second.path, "injected.parquet", b"injected in the second")

        alerts = service.verify_all()

        # One alert per corrupt snapshot: a sweep that halted at the first
        # failure would hide the second, which is right for an evaluator
        # and wrong for a monitor.
        assert [alert.snapshot for alert in alerts] == [first.name, second.name]
        assert alerts[0].mismatches[0].path == PART_0
        assert alerts[1].unrecorded[0].path == "injected.parquet"

    def test_the_sweep_stops_at_corruption_when_mounting(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # mounted() is the evaluator host's start-up sweep, and it raises:
        # a host that wants findings as data uses verify_all instead.
        first = service.seal(staged, sealed_at=AT)
        staged.joinpath("bars", "extra.parquet").write_bytes(b"extra")
        service.seal(staged, sealed_at=AT_LATER)
        _tamper(first.path / PART_0, b"tampered in the first")
        with pytest.raises(SnapshotCorruptionError):
            service.mounted()

    def test_verify_tree_verifies_a_directory_the_caller_holds(
        self, sealed: SealedSnapshot
    ) -> None:
        # The path-taking primitive under the door — the same seam
        # SnapshotMount.for_directory offers — for a restore tool or a test
        # that resolved the directory itself.
        assert verify_tree(sealed.path) is None
        _tamper(sealed.path / PART_0, b"tampered bytes")
        alert = verify_tree(sealed.path)
        assert alert is not None
        assert alert.snapshot == sealed.name

    def test_one_shot_verify_snapshot_helper(
        self, sealed: SealedSnapshot, lake_root: Path
    ) -> None:
        assert verify_snapshot(sealed.name, lake_root=lake_root) is None
        _tamper(sealed.path / PART_0, b"tampered bytes")
        assert verify_snapshot(sealed.name, lake_root=lake_root) is not None


class TestThePerformanceSeam:
    """``verify=False``: the caller verified already, and says so."""

    def test_open_skips_the_rehash_when_asked(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        _tamper(sealed.path / PART_0, b"tampered bytes")
        ref = service.open(sealed.name, verify=False)
        assert ref.path == sealed.path  # returned, not refused

    def test_mount_skips_the_rehash_when_asked(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        # The seam's consequence stated plainly: the caller that skips
        # verification reads the tampered bytes. The seam exists so layers
        # that act after a tree is known bad (test_mount.py's mode repair
        # and symlink refusals) and callers that just verified are not made
        # to pay the rehash twice.
        _tamper(sealed.path / PART_0, b"tampered bytes")
        mount = service.mount(sealed.name, verify=False)
        assert (mount.root / PART_0).read_bytes() == b"tampered bytes"

    def test_the_seam_is_independent_of_mode_reassertion(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        mount = service.mount(sealed.name, verify=False, reassert_modes=False)
        assert mount.modes_reasserted is False


class TestHonestBoundaries:
    """What verification does not claim, pinned so it cannot drift."""

    def test_a_snapshot_without_a_manifest_opens_vacuously(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # Sealed before manifests (feature 31), or built by hand: there is
        # no recorded sha256 to fail to match, so verification has nothing
        # to say — while the manifest door still refuses the absence.
        directory = lake_root / "snapshots" / NAME
        (directory / "bars").mkdir(parents=True)
        (directory / "bars" / "part-0.parquet").write_bytes(b"hand sealed")
        assert service.open(NAME).path == directory
        assert service.verify(NAME) is None
        with pytest.raises(SnapshotManifestError, match="carries no"):
            service.read_manifest(NAME)

    def test_an_unparseable_manifest_is_a_manifest_error(
        self, service: SnapshotService, sealed: SealedSnapshot
    ) -> None:
        # It proves nothing either way, so it is refused by the manifest
        # contract — the same error, the same message, the same door that
        # read_manifest raises — never laundered into a hash finding.
        manifest_file = sealed.path / "MANIFEST.json"
        os.chmod(manifest_file, 0o644)
        manifest_file.write_bytes(b"this is not json")
        os.chmod(manifest_file, 0o444)
        with pytest.raises(SnapshotManifestError, match="not valid JSON"):
            service.open(sealed.name)

    def test_a_manifest_that_disagrees_with_its_directory_stays_read_manifest_s(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # The name-binding cross-checks (prefix, sealed_at) belong to the
        # manifest door, and stay there: verification is about bytes, and a
        # manifest that misbinds still has its per-file comparison run.
        manifest = SnapshotManifest(
            manifest_version=MANIFEST_VERSION,
            snapshot_hash="b7d2e4" + "0" * 58,  # not the name's prefix
            sealed_at=AT,
            universe=None,
            files={},
            total_rows=0,
        )
        directory = lake_root / "snapshots" / NAME
        directory.mkdir(parents=True)
        (directory / "MANIFEST.json").write_bytes(manifest.to_json_bytes())
        assert service.open(NAME).path == directory  # bytes check is vacuous
        with pytest.raises(SnapshotManifestError, match="prefix does not match"):
            service.read_manifest(NAME)

    def test_a_tree_that_is_not_a_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(SnapshotContentError, match="not a snapshot directory"):
            verify_tree(tmp_path / "absent")
