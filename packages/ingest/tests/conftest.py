"""Path setup for the ingest member's suite.

Two imports this suite needs are not on ``sys.path`` by default:

* ``app.module_loader`` — the application factory.  Under ``uv run`` the
  root project ships it into the environment; under a bare ``pytest``
  invocation nothing installs it, so the repository's ``src/`` tree goes
  on the path here.
* ``nullius_ingest`` — this member.  Nothing in the workspace depends on
  it (by design: the module loader finds members by scanning, not by
  installation), so the member's own ``src/`` tree goes on the path the
  same way, under ``uv run`` and bare ``pytest`` alike.
* ``snapshot`` — the sealing-service peer member.  The backfill tests put
  a real :class:`~snapshot.SnapshotService` behind the seal gate, and the
  gate imports ``snapshot`` lazily at call time; nothing depends on it at
  import, so its ``src/`` tree goes on the path here too.

The lake-root and database-isolation fixtures from ``tests/conftest.py``
do not apply at this path (they live beside the repository-level suites);
this suite needs neither — the isolation framework has no I/O of its own
to redirect.
"""

from __future__ import annotations

import sys
from pathlib import Path

# tests/conftest.py -> packages/ingest/tests -> packages/ingest -> packages -> repo root
MEMBER_ROOT = Path(__file__).resolve().parents[1]
MEMBER_SRC = MEMBER_ROOT / "src"
REPO_SRC = Path(__file__).resolve().parents[3] / "src"
SNAPSHOT_SRC = Path(__file__).resolve().parents[2] / "snapshot" / "src"

for _entry in (MEMBER_SRC, REPO_SRC, SNAPSHOT_SRC):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))
