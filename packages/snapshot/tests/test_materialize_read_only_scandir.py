"""``materialize_read_only`` walks with ``scandir``, and means the same thing.

The policy in :func:`snapshot.materialize_read_only` never needed the sorted
path list it used to build: it reads one fact per entry — the mode — and
corrects each entry independently, so the order entries are visited in has
never mattered. Building ``sorted(target.rglob("*"))`` and then calling
``os.stat`` on every one of its results cost 2.3M rglob visits, 4.6M stats
and 242s inside ``sorted`` on the 1.15M-file wide snapshot, which every
``load_evaluation_context`` paid before reading a byte.

The fix is a recursive ``os.scandir`` walk that takes ``st_mode`` and
``is_dir`` from the ``DirEntry`` the directory read already returned. These
tests pin the *behaviour* the rewrite must not move: the same corrections
count, the same resulting modes, the same counting-only mode, the same
return-zero for a missing root — plus the two properties that make the
walk's shape load-bearing (a symlink is not followed; 20,000 files are
walked in well under five seconds).

Every expected value here is written out explicitly rather than recomputed
from the tree, so a walk that (say) started counting directories it had
already counted, or that quietly widened a ``0400`` file back to ``0444``,
fails rather than agreeing with itself.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest
from snapshot import materialize_read_only

#: The sealed contract the policy re-asserts, quoted here rather than
#: imported so a change to either constant shows up as a test failure in
#: both directions instead of silently moving with the implementation.
FILE_MODE = 0o444
DIRECTORY_MODE = 0o555


def mode_of(path: Path) -> int:
    """The permission bits of ``path``, never of what a link points at."""
    return stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A tree whose modes span the three cases the policy distinguishes.

    ``files/`` and ``stricter/`` are sealed-clean (``0444``/``0555``);
    ``loose/`` carries the real drift — files at ``0644`` and ``0444``, and
    the directory itself at ``0755`` — over a root deliberately left
    writable so the walk's treatment of the root is exercised too.
    """
    root = tmp_path / "snapshot"
    (root / "clean").mkdir(parents=True)
    (root / "clean" / "sealed.parquet").write_bytes(b"sealed")
    (root / "clean" / "read-only.parquet").write_bytes(b"read-only")
    (root / "stricter").mkdir()
    (root / "stricter" / "operator.parquet").write_bytes(b"operator")
    (root / "loose").mkdir()
    (root / "loose" / "writable.parquet").write_bytes(b"writable")
    (root / "loose" / "sealed.parquet").write_bytes(b"sealed")
    (root / "loose" / "deeper").mkdir()
    (root / "loose" / "deeper" / "writable.parquet").write_bytes(b"deeper")

    os.chmod(root / "clean", DIRECTORY_MODE)
    os.chmod(root / "clean" / "sealed.parquet", FILE_MODE)
    os.chmod(root / "clean" / "read-only.parquet", 0o444)
    os.chmod(root / "stricter", DIRECTORY_MODE)
    os.chmod(root / "stricter" / "operator.parquet", 0o400)  # stricter, by choice
    os.chmod(root / "loose", 0o755)
    os.chmod(root / "loose" / "writable.parquet", 0o644)
    os.chmod(root / "loose" / "sealed.parquet", FILE_MODE)
    os.chmod(root / "loose" / "deeper", DIRECTORY_MODE)
    os.chmod(root / "loose" / "deeper" / "writable.parquet", 0o664)
    os.chmod(root, 0o755)  # the root itself has drifted
    return root


class TestThePolicyIsUnchanged:
    """Same corrections count and same resulting modes as the rglob walk."""

    def test_corrections_count_is_unchanged(self, tree: Path) -> None:
        # Drifted entries, counted one apiece: the root, `loose/`, its two
        # writable files (0644 and 0664), and `clean/read-only.parquet` is
        # *not* drifted (0444 carries no write bit). `deeper/` and everything
        # under `clean/`/`stricter/` are already at or stricter than the
        # contract, so they contribute nothing.
        assert materialize_read_only(tree) == 4

    def test_resulting_modes_are_exactly_the_contract(self, tree: Path) -> None:
        materialize_read_only(tree)

        assert mode_of(tree) == 0o555
        assert mode_of(tree / "loose") == 0o555
        assert mode_of(tree / "loose" / "writable.parquet") == FILE_MODE
        assert mode_of(tree / "loose" / "deeper") == DIRECTORY_MODE
        assert mode_of(tree / "loose" / "deeper" / "writable.parquet") == FILE_MODE
        assert mode_of(tree / "loose" / "sealed.parquet") == FILE_MODE

    def test_a_stricter_entry_is_never_widened(self, tree: Path) -> None:
        # 0400 carries no write bit, so the walk reports nothing and touches
        # nothing — it never "restores" 0444. This is the direction that
        # breaks first if the new walk starts guessing at the contract.
        materialize_read_only(tree)

        assert mode_of(tree / "stricter" / "operator.parquet") == 0o400
        assert mode_of(tree / "stricter") == DIRECTORY_MODE
        assert mode_of(tree / "clean" / "sealed.parquet") == FILE_MODE

    def test_a_second_pass_is_a_no_op(self, tree: Path) -> None:
        first = materialize_read_only(tree)
        assert first == 4
        assert materialize_read_only(tree) == 0


class TestCountingOnlyMode:
    """``fix=False`` reports drift without changing a single bit."""

    def test_counts_drift_and_changes_nothing(self, tree: Path) -> None:
        before = {p: mode_of(p) for p in (tree, *sorted(tree.rglob("*")))}

        assert materialize_read_only(tree, fix=False) == 4

        after = {p: mode_of(p) for p in (tree, *sorted(tree.rglob("*")))}
        assert after == before
        assert mode_of(tree) == 0o755
        assert mode_of(tree / "loose" / "writable.parquet") == 0o644


class TestMissingRoot:

    def test_a_missing_directory_returns_zero(self, tmp_path: Path) -> None:
        assert materialize_read_only(tmp_path / "absent") == 0

    def test_a_file_instead_of_a_directory_returns_zero(self, tmp_path: Path) -> None:
        # A path that is not a directory holds no tree to tighten, so the
        # answer is the same as for one that does not exist.
        stray = tmp_path / "not-a-tree.parquet"
        stray.write_bytes(b"x")
        os.chmod(stray, 0o666)
        assert materialize_read_only(stray) == 0
        assert mode_of(stray) == 0o666  # and it is left alone


class TestSymlinksAreNotFollowed:

    def test_a_symlinked_file_outside_the_tree_is_not_chmodded(self, tmp_path: Path) -> None:
        # A link planted inside the snapshot must not put anything else on
        # the mount path — here, a writable bystander the walk would loosen
        # to 0444 if it followed the link.
        root = tmp_path / "snapshot"
        root.mkdir()
        outside = tmp_path / "outside.parquet"
        outside.write_bytes(b"bystander")
        os.chmod(outside, 0o666)
        os.symlink(outside, root / "escape.parquet")
        os.chmod(root, DIRECTORY_MODE)

        materialize_read_only(root)

        assert mode_of(outside) == 0o666
        assert (root / "escape.parquet").is_symlink()

    def test_a_symlinked_directory_outside_the_tree_is_not_walked(self, tmp_path: Path) -> None:
        # The link's *target* must not be traversed either: following it
        # would walk a directory the snapshot does not own.
        root = tmp_path / "snapshot"
        root.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "writable.parquet").write_bytes(b"outside")
        os.chmod(elsewhere / "writable.parquet", 0o644)
        os.chmod(elsewhere, 0o755)
        os.symlink(elsewhere, root / "linked")
        os.chmod(root, DIRECTORY_MODE)

        materialize_read_only(root)

        assert mode_of(elsewhere) == 0o755
        assert mode_of(elsewhere / "writable.parquet") == 0o644

    def test_a_symlink_inside_the_tree_does_not_stop_the_walk(self, tmp_path: Path) -> None:
        # A broken link is not an error: the walk corrects what it can and
        # says how much it corrected.
        root = tmp_path / "snapshot"
        (root / "loose").mkdir(parents=True)
        (root / "loose" / "writable.parquet").write_bytes(b"x")
        os.chmod(root / "loose" / "writable.parquet", 0o644)
        os.symlink(root / "nowhere", root / "broken")
        os.chmod(root / "loose", 0o755)
        os.chmod(root, 0o755)

        assert materialize_read_only(root) == 3


class TestTheWalkDoesNotRestatPaths:
    """The mode comes from the ``DirEntry``, not from a fresh ``os.stat``.

    This is the mechanical half of the defect: the old walk rebuilt a path
    for every entry (``sorted(target.rglob("*"))``) and then ``os.stat``-ed
    each one, so the cost per entry was a path object allocation plus a
    second look-up by name — the 4.6M stats. Counting the calls pins the
    part of the fix a wall-clock assertion cannot check cheaply.
    """

    def test_the_stat_count_does_not_grow_with_the_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ten times the entries must not mean ten times the ``os.stat`` calls.

        A count that stays flat as the tree grows is the property the old
        walk lacked: there, one ``os.stat`` per entry meant the count *was*
        the entry count (4.6M on the wide snapshot). The absolute figure is
        small either way — the root, and whatever ``pathlib`` looks up to
        answer ``is_dir`` — so it is the invariance under scale that is
        asserted, not a magic number.
        """
        real_stat = os.stat

        def count_stats(root: Path) -> int:
            calls = 0

            def counting_stat(*args: object, **kwargs: object):
                nonlocal calls
                calls += 1
                return real_stat(*args, **kwargs)

            monkeypatch.setattr(os, "stat", counting_stat)
            try:
                materialize_read_only(root, fix=False)
            finally:
                monkeypatch.setattr(os, "stat", real_stat)
            return calls

        def build(root: Path, width: int) -> Path:
            (root / "loose").mkdir(parents=True)
            for index in range(width):
                (root / "loose" / f"part-{index}.parquet").write_bytes(b"x")
            os.chmod(root / "loose", 0o755)
            os.chmod(root, 0o755)
            return root

        small = build(tmp_path / "small", 3)
        large = build(tmp_path / "large", 300)
        # A hundredfold tree, so "flat" and "linear" cannot be confused.
        assert sum(1 for _ in large.rglob("*")) >= 50 * sum(1 for _ in small.rglob("*"))

        calls_small = count_stats(small)
        calls_large = count_stats(large)

        assert calls_large == calls_small, (
            f"{calls_large} os.stat calls for 301 entries vs {calls_small} for "
            "4 — the walk is stat-ing entries one by one again"
        )

    def test_the_walk_does_not_build_a_sorted_path_list(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*args: object, **kwargs: object):
            raise AssertionError("materialize_read_only must walk with os.scandir")

        monkeypatch.setattr(Path, "rglob", forbidden)
        monkeypatch.setattr(Path, "glob", forbidden)
        assert materialize_read_only(tree, fix=False) == 4


def test_twenty_thousand_files_finish_in_under_five_seconds(tmp_path: Path) -> None:
    """The walk is linear in entries, in the shape a wide snapshot has.

    Not a benchmark of this machine: a tree built this way took ~1.0s under
    the old walk and ~0.05s under scandir, so the five-second ceiling is a
    guard against the walk regressing back to a per-entry path rebuild and
    ``os.stat`` (the 343s form would fail this by two orders of magnitude).
    """
    root = tmp_path / "snapshot"
    per_symbol = 100
    symbols = 200
    for symbol in range(symbols):
        for date in range(per_symbol):
            part = root / f"symbol=S{symbol:04d}" / f"date={date:03d}" / "part-0.parquet"
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(b"x")

    started = time.monotonic()
    corrections = materialize_read_only(root)
    elapsed = time.monotonic() - started

    # Every file (20,000) and every date directory (20,000) is writable when
    # created, and so is the root — 40,001 corrections, and none of the
    # symbol directories, which are one level higher and count once each.
    assert corrections == 40_001 + symbols
    assert elapsed < 5.0, f"walk took {elapsed:.2f}s for {symbols * per_symbol} files"
    assert mode_of(root) == DIRECTORY_MODE
    probe = root / "symbol=S0000" / "date=000" / "part-0.parquet"
    assert mode_of(probe) == FILE_MODE
