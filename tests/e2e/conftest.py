"""Path setup for the end-to-end suite.

The e2e journeys run against the *assembled* system: the workspace members
the production module loader discovers, reached through the ``app``
namespace and through the members' own public seams, in the processes the
deployment actually runs them in — several of these journeys spawn real
second and third interpreters (the risk supervisor, the strategy process)
over a shared store, because the sentence a journey verifies names
processes, and a process is not a thread wearing a taller story.

The repository-level ``tests/`` tree is not on a bare interpreter's
``sys.path``, and the harness is not assumed to invoke the suite through
``uv run``.  This conftest makes the application factory and every
declared member importable either way, exactly as
``tests/invariants/conftest.py`` and ``tests/contract/conftest.py`` do for
their suites.

It resolves the workspace from the root ``pyproject.toml``'s own
``[tool.uv.workspace]`` declaration via ``workspace_scan_roots()`` rather
than hard-coding a package path, so it follows the persisted layout — the
same declaration the production module loader reads, and therefore the
same one that decides whether a component is discovered at all.  A
hard-coded path here could quietly disagree with it and let a journey
exercise an import that production composition would never resolve.

The root ``tests/conftest.py`` still applies to every test here: each gets
an isolated ``LAKE_ROOT`` and ``DATABASE_URL``.  A journey whose
choreography is database-engine-specific (SQLite's write lock is the one
thing a hung strategy process can wedge, and wedging it is how the risk
journey stages "unresponsive") builds its own throwaway SQLite URL under
pytest's temporary directory instead, for the same reason the risk
member's own cross-process tests do: the wedge belongs to one database's
locking story, and no scratch CI database should be asked to play a part
its lock manager never wrote.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ensure_on_path(directory: Path) -> None:
    entry = str(directory)
    if directory.is_dir() and entry not in sys.path:
        sys.path.insert(0, entry)


# The factory first: workspace_scan_roots() below is imported from it.
_ensure_on_path(REPO_ROOT / "src")

from app.module_loader import workspace_scan_roots

# Then every declared member's scan root, which is what makes each member
# importable as a normal package rather than only under the loader's
# synthetic scan name — the same import surface a spawned interpreter gets
# when a journey hands it a PYTHONPATH built from the same declaration.
for _root in workspace_scan_roots():
    _ensure_on_path(_root)
