"""bug_spec_hardened_nproc_race.xml (NPROC-1): the hardened sandbox's
process-tree budget must never be a UID-wide ``RLIMIT_NPROC`` derived from an
ambient ``/proc`` snapshot — that accounting is per *real UID*, host-wide, so
any thread or process the same user spawns elsewhere during a run (another
pytest worker's own sandbox, an editor, a browser) races the snapshot and can
starve a perfectly healthy child.

The deterministic half of this suite does not depend on actually winning that
race on whatever host runs it (racy by nature, and this harness's own nested
sandboxing was observed, while writing this fix, to scope ``RLIMIT_NPROC``
enforcement differently from what ``/proc`` enumeration shows — so a thread-
churn reproduction that reliably starves the child on a bare host may pass
even on unfixed code here). Instead, :func:`test_apply_rlimits_never_sets_rlimit_nproc`
asserts the root-cause line is gone directly: it is a plain monkeypatch of
``resource.setrlimit`` (never applied to a real process), and it was
confirmed RED against the pre-fix module (every ``_apply_rlimits`` call
included ``RLIMIT_NPROC``) and GREEN against this one, while writing this
fix.

The remaining tests exercise the real behaviour end to end, against real
``bwrap`` subprocesses, the same discipline ``test_hostile_signals.py`` and
``test_hardened_sandbox.py`` already apply: a helper thread churns 60-thread
bursts throughout several real evaluations (the bug's own reproduction
recipe), every evaluation still succeeds, a fork bomb is still refused, and
the cgroup v2 probe/leaf-cgroup machinery is checked in isolation against a
fake delegated cgroup built from plain files — so the suite proves the fix's
two halves (the UID-wide limit is gone; the per-tree cgroup limit, where one
is available, is wired correctly) independently of whether this particular
host happens to have a writable delegated cgroup at all.
"""

from __future__ import annotations

import datetime as dt
import os
import resource
import shutil
import threading
import time
from pathlib import Path

import pyarrow as pa
import pytest
from contract.window import MarketWindow
from orchestrator import _hardened_sandbox as hs
from orchestrator._hardened_sandbox import HardenedLimits, HardenedSubprocessSandbox

#: SEC-1: HardenedSubprocessSandbox has no bare-subprocess fallback, so a
#: host without bwrap skips this whole module rather than failing every test
#: here — the same discipline test_hardened_sandbox.py and
#: test_hostile_signals.py already apply to their own bwrap dependency.
pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is not on PATH")

_UNIVERSE = ("AAA", "BBB")

_BENIGN = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([float(len(sym)) for sym in ctx.universe])
"""


def _window() -> MarketWindow:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({sym: [1.0] for sym in _UNIVERSE})}
    return MarketWindow(t, universe=_UNIVERSE, frames=frames)


def _fast_limits(**overrides: object) -> HardenedLimits:
    base: dict[str, object] = {"cpu_s": 10.0, "runner_mem_mb": 4096, "pids": 32, "wall_s": 10.0}
    base.update(overrides)
    return HardenedLimits(**base)


# -- the root cause: no RLIMIT_NPROC is ever set from an ambient snapshot ----


def test_apply_rlimits_never_sets_rlimit_nproc(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(resource, "setrlimit", lambda res, lims: calls.append(int(res)))

    hs._apply_rlimits(_fast_limits())

    assert resource.RLIMIT_NPROC not in calls
    # The three limits this fix leaves untouched are still applied — the
    # bug's own constraint that RLIMIT_AS and the wall-clock watchdog keep
    # their current behaviour.
    assert resource.RLIMIT_CPU in calls
    assert resource.RLIMIT_AS in calls
    assert resource.RLIMIT_FSIZE in calls


# -- a helper churns thread bursts throughout several real evaluations ------


def _churn_thread_bursts(stop: threading.Event, burst: int = 60, sleep_s: float = 0.4) -> None:
    """Mirror the bug's own reproduction: 60 short-lived threads, repeatedly."""
    while not stop.is_set():
        workers = [threading.Thread(target=time.sleep, args=(sleep_s,)) for _ in range(burst)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()


def test_evaluations_under_heavy_thread_churn_all_succeed() -> None:
    stop = threading.Event()
    churner = threading.Thread(target=_churn_thread_bursts, args=(stop,), daemon=True)
    churner.start()
    try:
        sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
        results = [sandbox_instance.run(_BENIGN, _window(), seed=i) for i in range(6)]
    finally:
        stop.set()
        churner.join(timeout=5)

    for result in results:
        assert result.fail_class is None, result.detail
        assert result.scores.to_list() == [3.0, 3.0]


# -- a fork bomb is still refused --------------------------------------------


def test_fork_bomb_signal_is_still_refused() -> None:
    # `os` is outside the committed allowlist, so this never reaches a real
    # fork: refused by the import guard before any process is spawned,
    # exactly as test_hostile_signals.py's own fork-bomb case — unaffected
    # by this fix, which only changes how the process-tree budget is
    # enforced for admitted code.
    sandbox_instance = HardenedSubprocessSandbox(limits=_fast_limits())
    code = "import os\ndef signal(ctx, seed):\n    for _ in range(50):\n        os.fork()\n    return None\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail


# -- the cgroup v2 probe and leaf-cgroup lifecycle, against fake files -------


def test_probe_detects_a_fake_delegated_cgroup_as_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "cgroup.subtree_control").write_text("cpu memory pids\n", encoding="utf-8")
    monkeypatch.setattr(hs, "_CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(hs, "_own_unified_cgroup_path", lambda: "")

    mechanism = hs._probe_pids_mechanism()

    assert mechanism.available
    assert mechanism.cgroup_base == tmp_path


def test_probe_refuses_a_cgroup_with_no_delegated_pids_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "cgroup.subtree_control").write_text("cpu memory\n", encoding="utf-8")
    monkeypatch.setattr(hs, "_CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(hs, "_own_unified_cgroup_path", lambda: "")

    mechanism = hs._probe_pids_mechanism()

    assert not mechanism.available
    assert mechanism.cgroup_base is None


def test_probe_refuses_when_no_unified_hierarchy_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hs, "_own_unified_cgroup_path", lambda: None)

    mechanism = hs._probe_pids_mechanism()

    assert not mechanism.available


def test_leaf_cgroup_create_writes_pids_max_and_join_writes_cgroup_procs(tmp_path: Path) -> None:
    leaf = hs._create_leaf_cgroup(tmp_path, 7)

    assert leaf is not None
    assert leaf.is_dir()
    assert (leaf / "pids.max").read_text(encoding="ascii") == "7"

    hs._join_cgroup(leaf)
    assert (leaf / "cgroup.procs").read_text(encoding="ascii") == str(os.getpid())

    # A real cgroup's ``rmdir`` does not require its pseudo control files to
    # be unlinked first (the kernel does not count them against
    # "directory must be empty"); a plain filesystem's does, so the fake
    # cgroup's own files are cleared here to exercise the same empty-leaf
    # case :func:`_remove_cgroup` sees against a real one.
    (leaf / "pids.max").unlink()
    (leaf / "cgroup.procs").unlink()
    hs._remove_cgroup(leaf)
    assert not leaf.exists()


def test_create_leaf_cgroup_returns_none_under_a_nonexistent_base(tmp_path: Path) -> None:
    assert hs._create_leaf_cgroup(tmp_path / "does-not-exist", 7) is None


def test_remove_cgroup_is_a_no_op_for_an_already_gone_directory(tmp_path: Path) -> None:
    missing = tmp_path / "already-gone"
    hs._remove_cgroup(missing)  # must not raise


def test_remove_cgroup_gives_up_silently_on_a_directory_that_never_empties(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(hs, "_CGROUP_CLEANUP_ATTEMPTS", 2)
    monkeypatch.setattr(hs, "_CGROUP_CLEANUP_DELAY_S", 0.01)
    stuck = tmp_path / "stuck-cgroup"
    stuck.mkdir()
    (stuck / "pids.max").write_text("7", encoding="ascii")

    hs._remove_cgroup(stuck)  # must not raise, even though it never empties

    assert stuck.exists()
