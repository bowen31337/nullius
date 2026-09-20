"""Feature 147: the mount — every write refused, every read served.

The sentence's posture, at the seam untrusted code actually meets: *System
mounts the immutable zone read-only for every service, which rejects a write
attempt with a permission error message.*  A write is hostile input by
definition — it comes from agent-authored code — so the mount refuses it
structurally, with a permission error *message*, before any syscall; and a
read is served, because a read-only mount is not a read-nothing one.  What
the tests below assert is the register: the refusal is a ``PermissionError``
that says why, and the read returns the sealed bytes.

The last group proves the derivation is real: the refusal is over real
sealed bytes (the ``0444``/``0555`` modes stop the write at the filesystem
too), and a path derived from the mount inherits the mount's refusals.
"""

from __future__ import annotations

import errno

import pytest

from infra.security.tests.zone_mount.helpers import (
    ZONE_RELATIVE_CONTRACT,
)
from infra.security.zone_mount import (
    MOUNT_POINT,
    ZoneMountError,
    ZoneWriteRefused,
)


class TestWritesAreRefusedWithAPermissionErrorMessage:
    """The headline: a write attempt is rejected with a permission error."""

    def test_write_bytes_is_refused(self, mount) -> None:
        """The mount's own ``write_bytes`` refuses, with a permission error."""
        with pytest.raises(ZoneWriteRefused) as raised:
            mount.write_bytes(b"tampered", "z0/trial-ledger/trials.db")
        assert raised.value.errno == errno.EACCES

    def test_the_refusal_is_a_permission_error(self, mount) -> None:
        """The refusal is a ``PermissionError`` — ``except PermissionError``
        and ``except OSError`` catch it exactly as a write to a read-only
        medium would."""
        with pytest.raises(PermissionError):
            mount.write_bytes(b"x", "z0/trial-ledger/trials.db")
        with pytest.raises(OSError):
            mount.write_bytes(b"x", "z0/trial-ledger/trials.db")

    def test_the_message_names_the_operation_path_and_zone(self, mount) -> None:
        """The message states the operation, the sealed path, and the zone —
        the three facts an operator needs to tell a sealed refusal from an
        ordinary permissions accident."""
        with pytest.raises(ZoneWriteRefused) as raised:
            mount.write_bytes(b"x", "z0/trial-ledger/trials.db")
        message = str(raised.value)
        assert "write" in message
        assert "trials.db" in message
        assert "z0-immutable" in message
        assert "read-only" in message

    @pytest.mark.parametrize("method", [
        "write_text",
        "mkdir",
        "unlink",
        "rmdir",
        "chmod",
    ])
    def test_every_mutating_verb_is_refused(self, mount, method: str) -> None:
        """'Any write attempt' is every mutating verb: the mount refuses on
        all of them, in the same permission-error register."""
        verb = getattr(mount, method)
        args = ("x",) if method in ("write_text",) else (
            ("x", "y") if method == "rename" else ("z0/trial-ledger/trials.db",)
        )
        with pytest.raises(ZoneWriteRefused):
            verb(*args)

    def test_a_path_derived_from_the_root_inherits_the_refusal(self, mount) -> None:
        """A ``ReadOnlyZonePath`` derived from the mount's root carries the
        same refusals: the mount is the only handle, and every path from it
        refuses writes structurally, before any syscall."""
        path = mount.root_path / "z0/trial-ledger/trials.db"
        with pytest.raises(ZoneWriteRefused):
            path.write_bytes(b"x")

    def test_open_for_write_is_refused_before_the_syscall(self, mount) -> None:
        """Opening a sealed file for writing is refused by the mount, not the
        kernel — the refusal names the operation (``write``/``append``)."""
        path = mount.root_path / "z0/trial-ledger/trials.db"
        with pytest.raises(ZoneWriteRefused):
            path.open("w")
        with pytest.raises(ZoneWriteRefused):
            path.open("a")

    def test_open_for_write_mode_plus_is_refused(self, mount) -> None:
        """The read-write ``+`` mode is the write it is — refused."""
        path = mount.root_path / "z0/trial-ledger/trials.db"
        with pytest.raises(ZoneWriteRefused):
            path.open("r+")


class TestReadsAreServed:
    """A read-only mount is not a read-nothing one — §2's Z0 is readable."""

    def test_read_bytes_by_relative_path(self, mount) -> None:
        """The mount reads a sealed file's bytes by zone-relative path."""
        assert mount.read_bytes("z0/trial-ledger/trials.db") == b"sealed-ledger"

    def test_read_text_by_relative_path(self, mount) -> None:
        """...and as text."""
        assert mount.read_text("z0/contract/contract.py") == "sealed-contract"

    def test_a_derived_path_reads(self, mount) -> None:
        """A ``ReadOnlyZonePath`` derived from the root reads the sealed
        bytes — reading a sealed path is always allowed."""
        path = mount.root_path / "z0/snapshots/2026/w42.parquet"
        assert path.read_bytes() == b"sealed-bars"

    def test_the_root_lists_its_members(self, mount) -> None:
        """The mount lists the zone's top-level directories — a read a
        read-only mount must serve."""
        names = {entry.name for entry in mount.root_path.children()}
        assert "z0" in names

    def test_a_member_lists_its_files(self, mount) -> None:
        """Listing a member directory returns its sealed files as read-only
        paths, each carrying the mount's refusals.  A member is reached from
        the mount root by a zone-relative join (an absolute join is an
        escape the mount refuses)."""
        entries = (mount.root_path / "z0/trial-ledger").children()
        assert [entry.name for entry in entries] == ["trials.db"]
        with pytest.raises(ZoneWriteRefused):
            entries[0].write_bytes(b"x")

    def test_open_for_read_succeeds(self, mount) -> None:
        """Opening a sealed file for reading returns a real handle."""
        path = mount.root_path / "z0/contract/contract.py"
        with path.open("rb") as handle:
            assert handle.read() == b"sealed-contract"

    def test_files_reports_the_content_identity(self, mount) -> None:
        """The mount's content identity is the ``{path: sha256}`` mapping —
        re-walked, so a reader can compare against the seal."""
        files = mount.files()
        assert "z0/trial-ledger/trials.db" in files
        assert files["z0/trial-ledger/trials.db"]

    def test_file_count_and_bytes(self, mount) -> None:
        """Observability: how many sealed files, and their total size."""
        files = mount.files()
        # The sealed tree holds the six zone members plus the staging file;
        # the mount serves them all.  What matters is that the zone's files
        # are present with a digest each.
        assert "z0/trial-ledger/trials.db" in files
        assert "z0/contract/contract.py" in files
        assert mount.file_count() >= 6
        assert mount.total_bytes() > 0


class TestSymlinksAreRefused:
    """A link planted inside the zone would put staging onto the mount path."""

    def test_a_symlink_is_refused_on_read(self, mount, tmp_path) -> None:
        """A symlink planted inside a member is refused on read, not
        followed — following it would put whatever it points at onto the
        zone path."""
        import os

        member = mount.root / "z0" / "contract"
        target = tmp_path / "secret"
        target.write_bytes(b"outside")
        link = member / "escape"
        # The member is sealed 0555, so it must be widened briefly to plant
        # the link, then re-sealed so the mount serves the tree.
        os.chmod(member, 0o755)
        os.symlink(target, link)
        os.chmod(member, 0o555)
        path = mount.root_path / "z0/contract/escape"
        with pytest.raises(ZoneMountError):
            path.read_bytes()


class TestTheRefusalIsDerivedNotHardcoded:
    """The refusal is over real sealed bytes, and inherited by derived paths."""

    def test_the_underlying_bytes_are_read_only_too(self, mount) -> None:
        """Defence in depth: the raw sealed file resists a write at the
        filesystem, so the mount's structural refusal is over real bytes,
        not a substitute for them."""
        raw = mount.root / "z0" / "trial-ledger" / "trials.db"
        with pytest.raises(PermissionError):
            raw.write_bytes(b"x")

    def test_a_mount_built_on_a_non_directory_is_refused(self, tmp_path) -> None:
        """A mount that is not a directory is not a mount — refused, fail
        closed, the same whether built by the service or by hand."""
        from infra.security.zone_mount import ReadonlyZoneMount

        a_file = tmp_path / "file"
        a_file.write_bytes(b"x")
        with pytest.raises(ZoneMountError):
            ReadonlyZoneMount.for_directory(a_file)

    def test_modes_are_reasserted_on_mount(self) -> None:
        """A tree whose bits were loosened is tightened back on mount — the
        re-assertion counts the correction, so drift is observable, and the
        loosened file ends at the sealed contract.  The whole tree is sealed
        first, so the only correction is the one drifted file."""
        import os
        import tempfile

        from infra.security.zone_mount import (
            materialize_read_only,
        )

        root = tempfile.mkdtemp(prefix="zone-drift-")
        drifted = os.path.join(root, "z0", "trial-ledger")
        os.makedirs(drifted)
        drifted_file = os.path.join(drifted, "trials.db")
        with open(drifted_file, "w") as handle:
            handle.write("x")
        # Seal the whole tree, then loosen exactly one file.
        materialize_read_only(root)
        os.chmod(drifted_file, 0o644)  # drifted: writable by owner
        corrections = materialize_read_only(root)
        assert corrections == 1
        assert os.stat(drifted_file).st_mode & 0o777 == 0o444

    def test_materialize_read_only_only_tightens(self) -> None:
        """The re-assertion clears write bits and never grants one: a file
        sealed stricter than the contract (``0400``) is left exactly as it
        was — never widened back to ``0444`` — and a drifted file is
        tightened to the contract."""
        import os
        import tempfile

        from infra.security.zone_mount import materialize_read_only

        root = tempfile.mkdtemp(prefix="zone-tighten-")
        strict = os.path.join(root, "strict")
        drifted = os.path.join(root, "drifted")
        with open(strict, "w") as handle:
            handle.write("x")
        with open(drifted, "w") as handle:
            handle.write("x")
        os.chmod(strict, 0o400)   # stricter than the contract
        os.chmod(drifted, 0o644)  # looser than the contract
        materialize_read_only(root)
        # The stricter file is left exactly as it was — never widened.
        assert os.stat(strict).st_mode & 0o777 == 0o400
        # The looser file is tightened to the contract.
        assert os.stat(drifted).st_mode & 0o777 == 0o444

    def test_materialize_read_only_counts_a_drifted_file(self) -> None:
        """With ``fix=False`` the sweep changes nothing and only counts
        drift — a drifted file is counted, a sealed one is not, and nothing
        is fixed."""
        import os
        import tempfile

        from infra.security.zone_mount import materialize_read_only

        root = tempfile.mkdtemp(prefix="zone-sweep-")
        sealed = os.path.join(root, "sealed")
        drifted = os.path.join(root, "drifted")
        with open(sealed, "w") as handle:
            handle.write("x")
        with open(drifted, "w") as handle:
            handle.write("x")
        # Seal the whole tree first, so the only drifted entry is the one we
        # loosen next — the swept root itself starts at the contract.
        materialize_read_only(root)
        os.chmod(drifted, 0o644)  # drift: writable by owner
        # Count drift without fixing: only the loosened file is counted.
        assert materialize_read_only(root, fix=False) == 1
        # Nothing was fixed — the drifted file is still drifted.
        assert os.stat(drifted).st_mode & 0o777 == 0o644
        assert os.stat(sealed).st_mode & 0o777 == 0o444

    def test_the_mount_point_prefix_is_served(self, mount) -> None:
        """The mount serves paths under the mount point: a zone-relative path
        from the root maps to the on-disk tree."""
        path = mount.root_path / ZONE_RELATIVE_CONTRACT
        assert path.read_bytes() == b"sealed-contract"
        assert path.posix == f"{MOUNT_POINT}/z0/contract/contract.py"
