"""bug_spec_orphaned_pool_workers.xml (POOL-1): a killed campaign driver
must not leave its ``ProcessEvaluator`` workers running.

``ProcessEvaluator``'s own shutdown (``atexit``, a ``SIGTERM`` handler —
see ``_process_pool.py``'s module docstring) is cooperative: neither fires
when the driver is ``SIGKILL``ed, and neither runs inside a worker at all.
Before this fix, a spawn worker had no link whatsoever to its parent's
lifetime, so it kept answering queued evaluations — each one starting a
sandbox subprocess — long after the driver that submitted them was gone.

This suite drives the exact mechanism that closes that gap
(``orchestrator._process_pool._start_parent_watchdog``) with a real driver
subprocess and real worker processes, but with a stub task: no
``EvaluationContext``, no composed application, no sandbox and no sealed
snapshot, because the watchdog's own job — noticing its parent is gone and
exiting — has nothing to do with what a worker is asked to evaluate.

* ``test_killed_driver_orphans_no_worker``: the reproduction. A driver
  subprocess starts a small pool, each worker records its own pid and then
  sleeps for far longer than this test's own timeout; once every pid is on
  disk, the driver is ``SIGKILL``ed while its workers are still mid-task,
  and every worker pid must be gone within 10 seconds.
* ``test_live_parent_never_stops_its_workers``: the control. The same
  driver, left alive, with a stub task short enough that every worker
  finishes it and goes idle before the hold starts; the workers must
  still be running 5 seconds later, proving the watchdog never fires on
  its own against an idle worker with a live parent.

Both tests write their own driver script into ``tmp_path`` (the same
real-subprocess-harness technique ``test_hostile_signals.py`` already uses
for this member) rather than adding a third committed file, and poll only
``os.kill(pid, 0)`` and pid files under ``tmp_path`` — no network, no
credential, nothing outside the pytest temporary directory — so the suite
is safe under pytest-xdist.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

#: Comfortably above the 2-second watchdog interval
#: (``_PARENT_WATCHDOG_INTERVAL_SECONDS``) plus reparenting and process
#: teardown, comfortably below "a hung test" — the spec's own figure.
ORPHAN_DETECTION_TIMEOUT_SECONDS = 10.0

#: The spec's own figure for the control: long enough to span at least two
#: watchdog wake-ups with a live parent throughout.
LIVE_PARENT_HOLD_SECONDS = 5.0

#: The reproduction's own stub task duration: far longer than
#: ORPHAN_DETECTION_TIMEOUT_SECONDS, so the SIGKILL always lands while
#: every worker is still mid-task.
STUB_TASK_SECONDS = 120.0

#: The control's own stub task duration: short enough that every worker
#: has finished it and gone idle (sitting on the pool's call queue with
#: nothing to do) well before LIVE_PARENT_HOLD_SECONDS elapses — so that
#: test actually checks idle workers, not busy ones.
IDLE_STUB_TASK_SECONDS = 0.5

WORKER_COUNT = 2

_DRIVER_SCRIPT = textwrap.dedent(
    """
    # Driver subprocess for test_process_pool_orphan_exit.py: a bare
    # ProcessPoolExecutor using orchestrator._process_pool's own
    # parent-watchdog initializer and a stub task, nothing else.
    import os
    import sys
    import time
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context


    def _stub_task(pid_dir, index, seconds):
        pid = os.getpid()
        path = os.path.join(pid_dir, "worker-%d.pid" % index)
        with open(path, "w") as handle:
            handle.write(str(pid))
        time.sleep(seconds)
        return pid


    def main():
        pid_dir = sys.argv[1]
        worker_count = int(sys.argv[2])
        task_seconds = float(sys.argv[3])

        from orchestrator._process_pool import _start_parent_watchdog

        pool = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=get_context("spawn"),
            initializer=_start_parent_watchdog,
        )
        for index in range(worker_count):
            pool.submit(_stub_task, pid_dir, index, task_seconds)
        print("ready", flush=True)
        time.sleep(10_000)


    if __name__ == "__main__":
        main()
    """
)


def _write_driver(tmp_path: Path) -> Path:
    path = tmp_path / "driver.py"
    path.write_text(_DRIVER_SCRIPT, encoding="utf-8")
    return path


def _start_driver(tmp_path: Path, *, worker_count: int, task_seconds: float) -> subprocess.Popen[bytes]:
    driver_path = _write_driver(tmp_path)
    process = subprocess.Popen(
        [sys.executable, str(driver_path), str(tmp_path), str(worker_count), str(task_seconds)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(os.environ),
    )
    return process


def _wait_for_worker_pids(
    tmp_path: Path, *, worker_count: int, timeout: float, driver: subprocess.Popen[bytes]
) -> list[int]:
    deadline = time.monotonic() + timeout
    pid_paths = [tmp_path / f"worker-{index}.pid" for index in range(worker_count)]
    while time.monotonic() < deadline:
        if driver.poll() is not None:
            raise AssertionError(
                f"driver subprocess exited early (code={driver.returncode}); "
                f"stderr={driver.stderr.read().decode('utf-8', 'replace') if driver.stderr else ''}"
            )
        if all(path.exists() for path in pid_paths):
            return [int(path.read_text().strip()) for path in pid_paths]
        time.sleep(0.05)
    raise AssertionError(f"worker pid files never appeared under {tmp_path} within {timeout}s")


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _reap_driver(driver: subprocess.Popen[bytes]) -> None:
    _kill_quietly(driver.pid)
    try:
        driver.wait(timeout=ORPHAN_DETECTION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


# -- the reproduction: SIGKILL the driver; every worker pid vanishes ----------


def test_killed_driver_orphans_no_worker(tmp_path: Path) -> None:
    driver = _start_driver(tmp_path, worker_count=WORKER_COUNT, task_seconds=STUB_TASK_SECONDS)
    try:
        worker_pids = _wait_for_worker_pids(
            tmp_path,
            worker_count=WORKER_COUNT,
            timeout=ORPHAN_DETECTION_TIMEOUT_SECONDS,
            driver=driver,
        )
        assert len(set(worker_pids)) == WORKER_COUNT
        for pid in worker_pids:
            assert _pid_is_alive(pid), f"worker {pid} is not even alive yet"

        # The reproduction: SIGKILL the driver while its workers are still
        # mid-task (each sleeps STUB_TASK_SECONDS, far longer than the
        # detection timeout below).
        os.kill(driver.pid, signal.SIGKILL)
        driver.wait(timeout=ORPHAN_DETECTION_TIMEOUT_SECONDS)

        deadline = time.monotonic() + ORPHAN_DETECTION_TIMEOUT_SECONDS
        remaining = set(worker_pids)
        while remaining and time.monotonic() < deadline:
            remaining = {pid for pid in remaining if _pid_is_alive(pid)}
            if remaining:
                time.sleep(0.1)

        assert not remaining, (
            f"worker pid(s) {remaining} outlived their SIGKILLed driver "
            f"past {ORPHAN_DETECTION_TIMEOUT_SECONDS}s"
        )
    finally:
        _reap_driver(driver)
        for pid in locals().get("worker_pids", []) or []:
            _kill_quietly(pid)


# -- the control: a live parent never stops its own workers -------------------


def test_live_parent_never_stops_its_workers(tmp_path: Path) -> None:
    driver = _start_driver(tmp_path, worker_count=WORKER_COUNT, task_seconds=IDLE_STUB_TASK_SECONDS)
    try:
        worker_pids = _wait_for_worker_pids(
            tmp_path,
            worker_count=WORKER_COUNT,
            timeout=ORPHAN_DETECTION_TIMEOUT_SECONDS,
            driver=driver,
        )

        # Let every worker's own short stub task finish, so the hold below
        # actually watches idle workers (sitting on the pool's call queue
        # with nothing to do), not busy ones — the SIGKILL test above
        # already covers mid-task.
        time.sleep(IDLE_STUB_TASK_SECONDS * 2)

        deadline = time.monotonic() + LIVE_PARENT_HOLD_SECONDS
        while time.monotonic() < deadline:
            assert driver.poll() is None, "driver subprocess exited unexpectedly"
            for pid in worker_pids:
                assert _pid_is_alive(pid), f"worker {pid} exited despite a live, idle parent"
            time.sleep(0.2)

        for pid in worker_pids:
            assert _pid_is_alive(pid)
    finally:
        _reap_driver(driver)
        for pid in locals().get("worker_pids", []) or []:
            _kill_quietly(pid)
