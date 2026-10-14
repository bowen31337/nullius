"""Pool workers outlive the thread that spawned them.

``ProcessPoolExecutor`` spawns its workers lazily, from whichever thread first
calls ``submit``. In a campaign, that is a thread of the root-evaluation
thread pool, and it ends with the root phase. POOL-1 first asked the kernel
for ``PR_SET_PDEATHSIG``, which fires when the parent *thread* exits. So
every worker was SIGTERMed after the roots, and each round-loop child raised
``BrokenProcessPool`` (archP01 and archP02 evaluated roots only).
"""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

from orchestrator._process_pool import _start_parent_watchdog


def test_workers_survive_the_exit_of_the_thread_that_spawned_them() -> None:
    pool = ProcessPoolExecutor(
        max_workers=2,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_start_parent_watchdog,
    )
    try:
        first: list[int] = []
        spawner = threading.Thread(
            target=lambda: first.append(pool.submit(os.getpid).result(timeout=60))
        )
        spawner.start()
        spawner.join()
        assert first, "the spawning thread's submit did not complete"
        time.sleep(3.0)  # past one watchdog interval, after the spawner ended
        assert pool.submit(os.getpid).result(timeout=60) > 0
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
