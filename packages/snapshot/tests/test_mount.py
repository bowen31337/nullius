"""The read-only mount: writes fail, and say why.

app_spec.xml feature 34 — *"System mounts a sealed snapshot read-only,
which rejects any write attempt against a sealed path with a permission
error message"* — has three claims in it, and this suite tests all three
separately, because a mount that satisfied any two of them would be a
different and worse feature:

* **mounted read-only** — the handle reads, lists and queries a sealed
  snapshot, and every path it hands out is a read-only path;
* **rejects any write attempt** — not just ``write_bytes``, but the whole
  mutating vocabulary, including writes aimed at a sealed snapshot through
  the mount, through a derived path, and through the standard file-object
  modes;
* **with a permission error message** — the refusal is a ``PermissionError``
  *carrying a message that states the contract*: which operation, which
  sealed path, and why. An ``EACCES`` with no explanation would satisfy the
  letter of the feature and none of its intent.

The enforcement is layered, and the layering is tested too. Below this
suite's feet, sealing already persists ``0444``/``0555``, so an ordinary
write through a raw ``Path`` fails at the kernel — that is feature 30's
guarantee (``test_seal.py`` pins it). Here the property is that the mount
refuses *first*, structurally, and that mounting re-asserts the modes of a
snapshot whose bits have drifted.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    ReadOnlyPath,
    SnapshotContentError,
    SnapshotError,
    SnapshotMount,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotReadOnlyError,
    SnapshotService,
    SnapshotStagingRequestError,
    materialize_read_only,
    mount_snapshot,
)

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
HASH = "a3f91c" + "0" * 58
NAME = "2026-09-01T00:00:00Z_a3f91c"

BTC_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_1 = b"BTCUSDT-2026-09-01-part-1"


@pytest.fixture
def sealed_path(service: SnapshotService, lake_root: Path) -> Path:
    """A sealed snapshot with the §4.2 partition shape."""
    staging = lake_root / "staging"
    bars = staging / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
    bars.mkdir(parents=True)
    (bars / "part-0.parquet").write_bytes(BTC_0)
    (bars / "part-1.parquet").write_bytes(BTC_1)
    other = staging / "bars" / "symbol=ETHUSDT" / "date=2026-09-01"
    other.mkdir(parents=True)
    (other / "part-0.parquet").write_bytes(b"ETHUSDT-2026-09-01-part-0")
    (staging / "borrow").mkdir()
    (staging / "borrow" / "rates.parquet").write_bytes(b"borrow-rates")
    return service.seal(staging, sealed_at=AT, snapshot_hash=HASH).path


@pytest.fixture
def mount(service: SnapshotService, sealed_path: Path) -> SnapshotMount:
    """The sealed snapshot above, mounted read-only."""
    return service.mount(NAME)


class TestMountingASealedSnapshot:
    def test_mount_names_the_snapshot_it_covers(
        self, mount: SnapshotMount, sealed_path: Path
    ) -> None:
        assert mount.name == NAME
        assert mount.path == sealed_path
        assert mount.sealed_at == AT
        assert mount.hash_prefix == "a3f91c"
        assert "read_only=True" in repr(mount)

    def test_mount_root_is_a_read_only_path(self, mount: SnapshotMount) -> None:
        assert isinstance(mount.root, ReadOnlyPath)
        assert mount.root.relative == ""
        assert Path(os.fspath(mount.root)) == mount.path

    def test_unknown_name_is_a_miss_and_names_nothing(
        self, service: SnapshotService
    ) -> None:
        with pytest.raises(SnapshotNotFoundError, match="no sealed snapshot"):
            service.mount("2026-09-01T00:00:00Z_000000")

    @pytest.mark.parametrize(
        "request_",
        [
            "../staging",          # traversal: contains "staging" but points elsewhere
            "/lake/staging",       # absolute: not a name at all
            "2026-09-01T00:00:00Z_a3f91c/bars",
            "2026-09-01T00:00:00Z_A3F91C",
            "",
            "not-a-name",
        ],
    )
    def test_only_canonical_names_mount(
        self, service: SnapshotService, request_: str
    ) -> None:
        # The strict parser is the boundary: no name that is not
        # `<sealed_at>_<hash prefix>` ever becomes a path. A request that
        # merely *contains* "staging" but resolves elsewhere — a ``..`` walk
        # off the lake, an absolute path — is refused here as a malformed
        # name, before any path exists to reject. (A request that resolves
        # *onto* the staging area is refused more sharply, as a staging
        # request — feature 35, tested in test_staging_request.py.)
        with pytest.raises(SnapshotNameError) as caught:
            service.mount(request_)
        # A malformed name is refused as a *name*, not resolved and then
        # missed: the refusal quotes the offending value and never reports a
        # filesystem location, because no location was ever constructed.
        assert "no sealed snapshot" not in str(caught.value)
        assert not hasattr(caught.value, "filename")

    @pytest.mark.parametrize(
        "request_",
        [
            "staging",
            "2026-09-01T00:00:00Z_a3f91c/../staging",  # resolves onto staging via ..
        ],
    )
    def test_a_request_resolving_onto_staging_is_a_staging_request(
        self, service: SnapshotService, request_: str
    ) -> None:
        # Feature 35: a request that resolves onto the staging area is refused
        # explicitly as a staging request, not incidentally as a malformed
        # name — the evaluator is told staging is never on its mount path.
        with pytest.raises(SnapshotStagingRequestError):
            service.mount(request_)

    def test_mounting_a_directory_that_is_not_a_snapshot_is_refused(
        self, lake_root: Path
    ) -> None:
        # The by-directory constructor has no lake to check a name against,
        # so it checks the name itself: every path a mount hands out must
        # name a real snapshot.
        stray = lake_root / "snapshots" / "not-a-snapshot"
        stray.mkdir()
        with pytest.raises(SnapshotNameError, match="not <sealed_at>"):
            SnapshotMount.for_directory(stray)

    def test_mounting_a_missing_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SnapshotContentError, match="not a directory"):
            SnapshotMount.for_directory(tmp_path / "absent" / NAME)

    def test_a_mount_cannot_be_built_over_a_file(
        self, mount: SnapshotMount
    ) -> None:
        file_inside = mount.path / "borrow" / "rates.parquet"
        with pytest.raises(SnapshotContentError):
            SnapshotMount.for_directory(file_inside)

    def test_every_sealed_snapshot_can_be_mounted(
        self, service: SnapshotService, sealed_path: Path
    ) -> None:
        (service.staging_root / "extra.parquet").write_bytes(b"extra")
        second = service.seal(
            sealed_root := service.staging_root,
            sealed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        del sealed_root
        mounts = service.mounted()
        assert [m.name for m in mounts] == sorted([NAME, second.name])
        assert all(isinstance(m, SnapshotMount) for m in mounts)

    def test_one_shot_mount_helper(self, service: SnapshotService, sealed_path: Path) -> None:
        helper = mount_snapshot(NAME)
        assert helper.name == NAME
        assert helper.path == sealed_path

    def test_the_mount_is_read_only_by_construction(self, mount: SnapshotMount) -> None:
        # The refusal verbs are on the mount itself as well as on its paths:
        # there is no handle here that writes.
        for operation in ("write_bytes", "write_text", "mkdir", "unlink", "rmdir",
                          "rename", "chmod", "copy_into"):
            assert callable(getattr(mount, operation)), operation


class TestWriteAttemptsAreRejected:
    """Every mutating verb, each refused with a permission error message."""

    def _assert_read_only_refusal(
        self, caught: pytest.ExceptionInfo, expected: str, mount_name: str = NAME
    ) -> None:
        error = caught.value
        message = str(error)
        assert isinstance(error, SnapshotReadOnlyError)
        assert isinstance(error, PermissionError)  # the filesystem vocabulary
        assert isinstance(error, OSError)  # ... and its type hierarchy
        assert expected in message  # the operation is named
        assert mount_name in message  # the snapshot that covers the path is named
        assert "read-only" in message  # ... and so is the contract
        assert "Permission denied" in message  # ... in permission-error words
        assert error.errno == errno.EACCES
        assert error.strerror is not None and "read-only" in error.strerror

    def test_write_bytes_through_a_sealed_path(
        self, mount: SnapshotMount
    ) -> None:
        target = mount.root / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        with pytest.raises(SnapshotReadOnlyError) as caught:
            target.write_bytes(b"tampered")
        self._assert_read_only_refusal(caught, "write")
        assert target.read_bytes() == BTC_0  # the sealed bytes survive

    def test_write_text_at_the_snapshot_root(self, mount: SnapshotMount) -> None:
        with pytest.raises(SnapshotReadOnlyError) as caught:
            (mount.root / "MANIFEST.json").write_text("{}")
        self._assert_read_only_refusal(caught, "write")

    def test_open_for_writing_is_refused_before_the_filesystem(
        self, mount: SnapshotMount, sealed_path: Path
    ) -> None:
        target = mount.root / "borrow" / "rates.parquet"
        for mode in ("w", "wb", "a", "ab", "x", "xb", "r+", "rb+", "w+b"):
            with pytest.raises(SnapshotReadOnlyError) as caught:
                target.open(mode)
            self._assert_read_only_refusal(caught, "write" if "a" not in mode else "append")
        # The refusal is the mount's, not the kernel's: the file's mode is
        # still exactly what sealing persisted.
        assert stat.S_IMODE((sealed_path / "borrow" / "rates.parquet").stat().st_mode) == 0o444

    def test_append_is_named_as_an_append(self, mount: SnapshotMount) -> None:
        with pytest.raises(SnapshotReadOnlyError) as caught:
            (mount.root / "borrow" / "rates.parquet").open("a")
        self._assert_read_only_refusal(caught, "append")

    def test_mount_level_write_verbs(self, mount: SnapshotMount) -> None:
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.write_bytes(b"x", "bars/new.parquet")
        self._assert_read_only_refusal(caught, "write")
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.mkdir("bars/symbol=BTCUSDT/date=2026-09-02")
        self._assert_read_only_refusal(caught, "mkdir")
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.unlink("borrow/rates.parquet")
        self._assert_read_only_refusal(caught, "unlink")
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.rename("borrow/rates.parquet", "borrow/moved.parquet")
        self._assert_read_only_refusal(caught, "rename")
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.chmod(0o777, "borrow/rates.parquet")
        self._assert_read_only_refusal(caught, "chmod")

    def test_deleting_and_renaming_through_read_only_paths(
        self, mount: SnapshotMount
    ) -> None:
        sealed_file = mount.root / "borrow" / "rates.parquet"
        for operation in ("unlink", "rmdir"):
            with pytest.raises(SnapshotReadOnlyError) as caught:
                getattr(sealed_file, operation)()
            self._assert_read_only_refusal(caught, operation)
        for operation in ("rename", "replace"):
            with pytest.raises(SnapshotReadOnlyError) as caught:
                getattr(sealed_file, operation)("elsewhere.parquet")
            self._assert_read_only_refusal(caught, "rename")
        with pytest.raises(SnapshotReadOnlyError):
            (mount.root / "newdir").mkdir()
        with pytest.raises(SnapshotReadOnlyError):
            sealed_file.touch()
        with pytest.raises(SnapshotReadOnlyError):
            sealed_file.symlink_to("/etc/passwd")
        with pytest.raises(SnapshotReadOnlyError):
            sealed_file.chmod(0o666)

    def test_writing_through_a_file_opened_via_the_root_descriptor(
        self, mount: SnapshotMount
    ) -> None:
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.open_at("borrow/rates.parquet", "wb")
        self._assert_read_only_refusal(caught, "write")

    def test_copying_bytes_into_the_snapshot(self, mount: SnapshotMount, tmp_path: Path) -> None:
        outside = tmp_path / "incoming.parquet"
        outside.write_bytes(b"outside bytes")
        with pytest.raises(SnapshotReadOnlyError) as caught:
            mount.copy_into(outside, "bars/symbol=BTCUSDT/date=2026-09-01/part-9.parquet")
        self._assert_read_only_refusal(caught, "copy-into")

    def test_escaping_the_mount_is_refused(self, mount: SnapshotMount) -> None:
        # `..` and absolute paths have no meaning inside a mount; the refusal
        # is a read-only refusal, so the traversal never reaches a Path.
        for escape in ("../staging", "../../staging", "/etc/passwd", "bars/../../staging"):
            with pytest.raises(SnapshotReadOnlyError) as caught:
                mount.root / escape
            assert "escape" in str(caught.value)

    def test_nothing_under_the_snapshot_changed(
        self, mount: SnapshotMount, sealed_path: Path
    ) -> None:
        # The strongest statement the suite can make: after every refusal
        # above, the sealed tree hashes exactly as it did when sealed.
        before = mount.files()
        with pytest.raises(SnapshotReadOnlyError):
            (mount.root / "borrow" / "rates.parquet").write_bytes(b"tampered")
        assert mount.files() == before
        assert (sealed_path / "borrow" / "rates.parquet").read_bytes() == b"borrow-rates"


class TestSymlinksAreNeverFollowed:
    """A planted symlink must not put staging on the mount path.

    Sealing refuses symlinks outright (``_content.walk_content``), so a
    sealed tree contains none *by construction* — which is exactly why this
    needs testing from the other direction. The mount is what an evaluator
    opens, and §4.2's guarantee is that *"staging is not on its mount path at
    all"*. A link planted inside a snapshot after sealing is the way to
    falsify that guarantee, and layer 1 does not prevent planting one: the
    owner can ``chmod`` the root writable and ``symlink(2)`` into it (the
    documented crack). So the mount must refuse to *follow* what it did not
    create, and these tests plant links through exactly that crack.

    Two shapes matter, and they fail differently: a link as the *final*
    component (caught by ``is_symlink``), and a link as an *intermediate*
    component (invisible to ``is_symlink`` on the full path — caught only by
    resolving and testing containment).
    """

    @pytest.fixture
    def planted(
        self, service: SnapshotService, lake_root: Path, sealed_path: Path
    ) -> tuple[SnapshotMount, Path]:
        """The sealed snapshot, with links planted into it post-seal."""
        staging_secret = lake_root / "staging" / "borrow" / "rates.parquet"
        os.chmod(sealed_path, 0o755)  # the documented crack, used as an attacker would
        os.symlink(staging_secret, sealed_path / "escape")
        os.symlink(lake_root / "staging" / "bars", sealed_path / "linked")
        os.chmod(sealed_path, 0o555)
        # A tree this tampered is corrupt — verification on open (feature
        # 36, test_verification.py) refuses it at the default door — so the
        # mount is taken through the skip seam: what is under test here is
        # the mount's own refusal to *follow* what it did not create, the
        # layer that still stands for a caller that bypassed or skipped the
        # check.
        return service.mount(NAME, verify=False), staging_secret

    def test_a_final_component_link_is_refused_on_every_read(
        self, planted: tuple[SnapshotMount, Path]
    ) -> None:
        mount, secret = planted
        link = mount.root / "escape"
        # Each of these is a distinct route to the same bytes; all must refuse.
        for read in (
            lambda: link.read_bytes(),
            lambda: link.read_text(),
            lambda: link.open("rb").read(),
            lambda: link.sha256(),
            lambda: link.stat(),
            lambda: mount.read_bytes("escape"),
            lambda: mount.open_at("escape", "rb").read(),
        ):
            with pytest.raises(SnapshotContentError, match="symlink"):
                read()
        # And the staging file the link pointed at is untouched and unread.
        assert secret.read_bytes() == b"borrow-rates"

    def test_a_file_link_reports_itself_absent(
        self, planted: tuple[SnapshotMount, Path]
    ) -> None:
        # `exists()` must not promise a node every read then refuses.
        link = planted[0].root / "escape"
        assert link.exists() is False
        assert link.is_file() is False

    def test_an_intermediate_component_link_is_refused(
        self, planted: tuple[SnapshotMount, Path]
    ) -> None:
        # The harder case: `linked/part-0.parquet` has no `..` in it and its
        # final component is a regular file, so only containment catches it.
        mount, _ = planted
        with pytest.raises(SnapshotContentError, match="symlink"):
            (mount.root / "linked" / "part-0.parquet").read_bytes()
        with pytest.raises(SnapshotContentError, match="symlink"):
            (mount.root / "linked" / "deeper" / "still").read_bytes()

    def test_glob_does_not_report_matches_through_a_link(
        self, planted: tuple[SnapshotMount, Path]
    ) -> None:
        mount, _ = planted
        assert mount.root.glob("linked/*") == ()
        # The real tree is unaffected.
        assert [p.relative for p in mount.root.glob("bars/*/*/*.parquet")] != []

    def test_listing_still_shows_the_planted_entries(
        self, planted: tuple[SnapshotMount, Path]
    ) -> None:
        # Hiding them would make the mount's view of the tree a lie; listing
        # is all a caller can do with one, since every read is refused.
        names = [entry.relative for entry in planted[0].root.children()]
        assert "escape" in names and "linked" in names

    def test_writes_through_a_link_still_report_a_permission_error(
        self, planted: tuple[SnapshotMount, Path]
    ) -> None:
        # Feature 34's wording is a *permission* error, and the symlink guard
        # must not preempt it: a write refusal is a write refusal whatever the
        # path's shape.
        mount, secret = planted
        with pytest.raises(SnapshotReadOnlyError, match="read-only"):
            (mount.root / "escape").write_bytes(b"tampered")
        with pytest.raises(SnapshotReadOnlyError, match="read-only"):
            (mount.root / "linked" / "part-0.parquet").write_bytes(b"tampered")
        assert secret.read_bytes() == b"borrow-rates"

    def test_the_containment_root_is_derived_correctly_when_nested(
        self, mount: SnapshotMount
    ) -> None:
        # The regression this suite was written to catch: `relative` must
        # accumulate across joins. A truncated `relative` makes `root()` climb
        # too far up, so the containment check compares against the wrong
        # directory and an intermediate link slips through.
        nested = mount.root / "bars" / "symbol=BTCUSDT" / "date=2026-09-01"
        assert nested.relative == "bars/symbol=BTCUSDT/date=2026-09-01"
        assert (nested / "part-0.parquet").relative == (
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"
        )
        # And the check is comparing against the snapshot root, not a parent.
        assert nested.root() == mount.path
        assert mount.root.root() == mount.path


class TestTheKernelAgrees:
    """The layer beneath: even without the mount, sealed bytes refuse writes.

    Feature 34's claim is about the *mount*, and :class:`TestWriteAttemptsAreRejected`
    pins it there. But the mount is defence in depth over a filesystem
    property, so this class pins the property too — against **raw paths that
    bypass the mount entirely** — and, just as importantly, pins exactly
    where the property stops. An unqualified "sealed snapshots are read-only"
    would be a claim this platform cannot support; the three documented
    exceptions below are asserted to be the *only* ones, so if a future
    platform or filesystem changes that, this suite says so.
    """

    def _raw(self, mount: SnapshotMount) -> Path:
        return Path(os.fspath(mount.root)) / "borrow" / "rates.parquet"

    @pytest.mark.parametrize(
        "destroy",
        [
            lambda path, outside: path.write_bytes(b"tampered"),
            lambda path, outside: path.write_text("tampered"),
            lambda path, outside: path.open("wb").close(),
            lambda path, outside: path.open("ab").close(),
            lambda path, outside: os.unlink(path),
            lambda path, outside: shutil.copyfile(outside, path),  # overwrite in place
            lambda path, outside: path.replace(outside),  # move the sealed file away
            lambda path, outside: (path.parent / "injected.parquet").write_bytes(b"injected"),
            lambda path, outside: shutil.copytree(path.parent, path.parent.parent / "clone"),
        ],
        ids=[
            "write_bytes",
            "write_text",
            "open_wb",
            "open_ab",
            "unlink",
            "copyfile_over",
            "replace_away",
            "create_new",
            "copytree_in",
        ],
    )
    def test_content_changing_writes_are_refused_by_the_modes(
        self, mount: SnapshotMount, tmp_path: Path, destroy
    ) -> None:
        raw = self._raw(mount)
        outside = tmp_path / "incoming.parquet"
        outside.write_bytes(b"outside bytes")
        with pytest.raises(PermissionError):
            destroy(raw, outside)
        # The bytes survived whatever was attempted, and nothing new appeared.
        assert raw.read_bytes() == b"borrow-rates"
        assert not (raw.parent / "injected.parquet").exists()
        assert not (raw.parent.parent / "clone").exists()

    def test_the_owner_can_widen_the_modes_and_the_next_mount_repairs_it(
        self, service: SnapshotService, mount: SnapshotMount
    ) -> None:
        # The one real crack in layer 1, pinned rather than glossed over:
        # modes are ownership-governed, so the sealing user can chmod them
        # away and then write. Layer 3 is what answers this — the drift is
        # detected and undone on the next mount, and counted while it lasts.
        raw = self._raw(mount)
        os.chmod(raw, 0o666)
        raw.write_bytes(b"written while loose")
        assert raw.read_bytes() == b"written while loose"

        # The written bytes are corruption, and the default door now says
        # so (feature 36, test_verification.py pins the alert). This test
        # is about the mode repair, so it remounts through the skip seam —
        # layer 3's behaviour in isolation, exactly as it was before the
        # verification door sat in front of it.
        remounted = service.mount(mount.name, verify=False)
        assert remounted.modes_corrected >= 1
        assert stat.S_IMODE(raw.stat().st_mode) == 0o444
        with pytest.raises(PermissionError):
            raw.write_bytes(b"tampered again")

    def test_timestamp_only_touches_are_metadata_not_content(
        self, mount: SnapshotMount
    ) -> None:
        # Documented exception 2: utime needs no write bit, but it cannot
        # change a byte, so the sealed content is unaffected.
        raw = self._raw(mount)
        before = mount.read_bytes("borrow/rates.parquet")
        os.utime(raw)
        assert mount.read_bytes("borrow/rates.parquet") == before

    def test_renaming_the_snapshot_directory_is_out_of_this_layer(
        self, lake_root: Path, mount: SnapshotMount
    ) -> None:
        # Documented exception 3: removing or renaming the *directories*
        # needs write on snapshots/, which must stay writable because that
        # is where seals are published. Availability, not integrity: the
        # sealed bytes are never rewritten in place by this.
        sealed_parent = mount.path.parent
        assert os.access(sealed_parent, os.W_OK)
        renamed = sealed_parent / "renamed-by-operator"
        os.rename(mount.path, renamed)
        assert (renamed / "borrow" / "rates.parquet").read_bytes() == b"borrow-rates"
        os.rename(renamed, mount.path)  # restore for the fixture's sake

    def test_the_mount_refuses_all_three_whatever_the_kernel_allows(
        self, mount: SnapshotMount
    ) -> None:
        # The feature's actual claim, stated as the contrast it is: the
        # kernel permits chmod and utime, and the mount permits neither.
        raw = self._raw(mount)
        with pytest.raises(SnapshotReadOnlyError):
            (mount.root / "borrow" / "rates.parquet").chmod(0o666)
        with pytest.raises(SnapshotReadOnlyError):
            (mount.root / "borrow" / "rates.parquet").touch()
        with pytest.raises(SnapshotReadOnlyError):
            mount.root.rename("elsewhere")
        assert stat.S_IMODE(raw.stat().st_mode) == 0o444  # nothing happened



class TestModeReassertion:
    """Mounting tightens a drifted snapshot back to the sealed contract."""

    def test_a_drifted_snapshot_is_put_back_under_the_contract(
        self, service: SnapshotService, sealed_path: Path
    ) -> None:
        # Simulate the real failure mode: a copy or restore that dropped the
        # modes, leaving a sealed tree writable by its owner.
        loosened = sealed_path / "borrow" / "rates.parquet"
        os.chmod(loosened, 0o644)
        os.chmod(sealed_path / "borrow", 0o755)
        with loosened.open("wb") as handle:  # the drift is real
            handle.write(b"overwritten while loose")

        # The overwrite is corruption the default door refuses (feature 36,
        # test_verification.py); the mode repair is this test's subject, so
        # it mounts through the skip seam.
        mount = service.mount(NAME, verify=False)

        assert mount.modes_reasserted is True
        assert mount.modes_corrected >= 2
        assert stat.S_IMODE(loosened.stat().st_mode) == 0o444
        assert stat.S_IMODE((sealed_path / "borrow").stat().st_mode) == 0o555
        with pytest.raises(PermissionError):
            loosened.write_bytes(b"tampered again")

    def test_a_fully_permissive_tree_is_repaired_and_then_refuses(
        self, service: SnapshotService, sealed_path: Path
    ) -> None:
        # The worst realistic drift: an archive extracted with a permissive
        # umask leaves the whole tree 0777. Nothing about that is sealed, so
        # mounting must repair it — and the repaired snapshot must still read
        # (a mount that broke reads to enforce writes would be useless).
        for entry in (sealed_path, *sealed_path.rglob("*")):
            os.chmod(entry, 0o777)
        mount = service.mount(NAME)
        assert mount.modes_corrected >= 1
        leaf = mount.root / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        assert leaf.read_bytes() == BTC_0
        with pytest.raises(SnapshotReadOnlyError):
            leaf.write_bytes(b"tampered")
        # And the repair is idempotent: the next mount has nothing to do.
        assert service.mount(NAME).modes_corrected == 0

    def test_reassertion_never_loosens_a_permission(self, sealed_path: Path) -> None:
        # A snapshot sealed *stricter* than the contract is left alone. The
        # tightening-only policy is the mask, so this is the direction that
        # would break first if the walk ever tried to "restore" 0444.
        sealed_file = sealed_path / "borrow" / "rates.parquet"
        os.chmod(sealed_file, 0o400)  # stricter than 0444, by operator choice
        corrections = materialize_read_only(sealed_path)
        assert stat.S_IMODE(sealed_file.stat().st_mode) == 0o400
        assert corrections == 0  # nothing to tighten, so nothing is reported
        # The directory granting entry to a stricter-than-contract file: its
        # execute bit is likewise never stripped to match some ideal mode.
        os.chmod(sealed_path / "borrow", 0o500)
        materialize_read_only(sealed_path)
        assert stat.S_IMODE((sealed_path / "borrow").stat().st_mode) == 0o500

    def test_a_perfectly_sealed_snapshot_needs_no_correction(
        self, sealed_path: Path
    ) -> None:
        assert materialize_read_only(sealed_path) == 0

    def test_dry_run_counts_drift_without_changing_it(self, sealed_path: Path) -> None:
        os.chmod(sealed_path / "borrow" / "rates.parquet", 0o644)
        corrections = materialize_read_only(sealed_path, fix=False)
        assert corrections >= 1
        assert stat.S_IMODE((sealed_path / "borrow" / "rates.parquet").stat().st_mode) == 0o644

    def test_a_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        assert materialize_read_only(tmp_path / "absent") == 0

    def test_reassertion_can_be_skipped(self, service: SnapshotService, sealed_path: Path) -> None:
        mount = service.mount(NAME, reassert_modes=False)
        assert mount.modes_reasserted is False
        assert mount.modes_corrected == 0


class TestReadingThroughTheMount:
    """A read-only mount is still a mount: reads, listing and queries work."""

    def test_reads_a_sealed_file(self, mount: SnapshotMount) -> None:
        assert mount.read_bytes("borrow/rates.parquet") == b"borrow-rates"
        part = mount.root / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-1.parquet"
        assert part.read_bytes() == BTC_1

    def test_read_only_paths_offer_path_like_reads(self, mount: SnapshotMount) -> None:
        part = mount.root / "borrow" / "rates.parquet"
        assert part.exists()
        assert part.is_file()
        assert not part.is_dir()
        assert part.name == "rates.parquet"
        assert part.suffix == ".parquet"
        assert stat.S_IMODE(part.stat().st_mode) == 0o444
        assert part.read_text().startswith("borrow")
        with part.open("rb") as handle:
            assert handle.read() == b"borrow-rates"
        assert str(part).endswith("borrow/rates.parquet")

    def test_the_mount_lists_the_sealed_tree(self, mount: SnapshotMount) -> None:
        # The listing is filesystem truth, so the manifest the seal
        # published is right there beside the content it describes; the
        # *content* mapping (files(), below) is where it is excluded.
        assert [entry.name for entry in mount.root.children()] == [
            "MANIFEST.json",
            "bars",
            "borrow",
        ]
        assert [entry.relative for entry in mount.root.iterdir()] == [
            "MANIFEST.json",
            "bars",
            "borrow",
        ]

    def test_file_mapping_matches_what_was_sealed(self, mount: SnapshotMount) -> None:
        files = mount.files()
        assert set(files) == {
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet",
            "bars/symbol=BTCUSDT/date=2026-09-01/part-1.parquet",
            "bars/symbol=ETHUSDT/date=2026-09-01/part-0.parquet",
            "borrow/rates.parquet",
        }
        assert mount.file_count() == 4
        assert mount.total_bytes() == len(BTC_0) + len(BTC_1) + len(b"ETHUSDT-2026-09-01-part-0") + len(b"borrow-rates")

    def test_hashes_are_comparable_to_the_sealed_record(
        self, mount: SnapshotMount, service: SnapshotService
    ) -> None:
        # The digest the mount computes is the digest the seal recorded —
        # which is what makes feature 36's corruption check a comparison.
        record = service.seal(
            service.staging_root, sealed_at=AT, snapshot_hash=HASH
        )
        assert record.path == mount.path
        for relative, recorded in record.files.items():
            assert (mount.root / relative).sha256() == recorded

    def test_partition_queries_prune_to_one_date(self, mount: SnapshotMount) -> None:
        assert mount.partitions("bars") == ("BTCUSDT", "ETHUSDT")
        assert mount.dates("bars", "BTCUSDT") == ("2026-09-01",)
        assert mount.partitions("borrow") == ()
        assert mount.dates("bars", "SOLUSDT") == ()  # a symbol not in this snapshot
        parts = mount.select("bars", "BTCUSDT", "2026-09-01")
        assert [part.name for part in parts] == ["part-0.parquet", "part-1.parquet"]
        assert all(isinstance(part, ReadOnlyPath) for part in parts)
        # No ETHUSDT bytes cross the boundary for a BTCUSDT query.
        assert b"ETHUSDT" not in b"".join(part.read_bytes() for part in parts)

    def test_select_matches_the_glob_it_replaced(self, mount: SnapshotMount) -> None:
        # select builds the partition path instead of globbing (each glob
        # scanned the symbol's whole history: 79% of an archive campaign).
        # It must answer exactly what the glob answered.
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for date in ("2026-09-01", "2026-09-02"):
                built = mount.select("bars", symbol, date)
                globbed = mount.root.glob(f"bars/symbol={symbol}/date={date}/*.parquet")
                assert [p.relative for p in built] == [p.relative for p in globbed]
        assert mount.select("borrow", "BTCUSDT", "2026-09-01") == ()
        assert mount.select("nonesuch", "BTCUSDT", "2026-09-01") == ()

    def test_glob_returns_read_only_paths(self, mount: SnapshotMount) -> None:
        matches = mount.root.glob("bars/symbol=*/date=*/*.parquet")
        assert len(matches) == 3
        assert all(isinstance(match, ReadOnlyPath) for match in matches)
        with pytest.raises(SnapshotReadOnlyError):
            matches[0].write_bytes(b"tampered")

    def test_reading_through_the_root_descriptor(self, mount: SnapshotMount) -> None:
        with mount.open_at("borrow/rates.parquet", "rb") as handle:
            assert handle.read() == b"borrow-rates"

    def test_a_root_descriptor_handle_cannot_be_written_to(
        self, mount: SnapshotMount
    ) -> None:
        # The descriptor is O_RDONLY, so even a caller who skips the mount's
        # own guards and calls os.write directly is refused by the kernel.
        with mount.open_at("borrow/rates.parquet", "rb") as handle:
            with pytest.raises(OSError) as caught:
                os.write(handle.fileno(), b"tampered")
            assert caught.value.errno == errno.EBADF
        assert mount.read_bytes("borrow/rates.parquet") == b"borrow-rates"

    def test_open_at_refuses_an_escape(self, mount: SnapshotMount) -> None:
        for escape in ("../staging", "/etc/passwd"):
            with pytest.raises(SnapshotReadOnlyError, match="escape"):
                mount.open_at(escape, "rb")


class TestTheRefusedErrorIsAPermissionError:
    """The message is the deliverable, so it is pinned exactly."""

    def test_message_states_operation_path_and_contract(self, mount: SnapshotMount) -> None:
        target = mount.root / "borrow" / "rates.parquet"
        with pytest.raises(SnapshotReadOnlyError) as caught:
            target.write_bytes(b"x")
        message = str(caught.value)
        assert "Permission denied" in message
        assert "write to" in message
        assert str(target) in message
        assert NAME in message
        assert "read-only" in message
        assert "staging is the writable area" in message
        assert caught.value.filename == str(target)
        assert caught.value.errno == errno.EACCES

    def test_message_is_also_catchable_as_a_plain_permission_error(
        self, mount: SnapshotMount
    ) -> None:
        # A caller written against filesystem vocabulary — the natural way to
        # write around a read-only medium — catches the refusal without
        # knowing this package exists.
        with pytest.raises(PermissionError, match="read-only"):
            mount.write_bytes(b"x", "borrow/rates.parquet")

    def test_message_is_catchable_as_a_snapshot_error(self, mount: SnapshotMount) -> None:
        with pytest.raises(SnapshotError, match="read-only"):
            mount.unlink("borrow/rates.parquet")

    def test_the_mount_reports_the_sealing_it_covers(self, mount: SnapshotMount) -> None:
        with pytest.raises(SnapshotReadOnlyError) as caught:
            (mount.root / "x.parquet").write_bytes(b"x")
        assert f"snapshot {NAME}" in str(caught.value)
