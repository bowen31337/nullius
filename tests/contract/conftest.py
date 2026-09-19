"""Path setup for the contract suite.

These tests import two things that are not on a bare interpreter's ``sys.path``:

* ``app.module_loader`` — the shared application factory, shipped by the root
  project from ``src/app``.  It is importable under ``uv run`` (which installs
  the root project into the venv) but not under a bare ``pytest``.
* ``contract`` — this feature's package, which lives at
  ``packages/contract/src/contract``.

Rather than assume the harness invokes the suite through ``uv run``, this
conftest makes both importable either way.  It resolves the workspace from the
root pyproject.toml's own ``[tool.uv.workspace]`` declaration via
``workspace_scan_roots()`` instead of hard-coding a package path, so it follows
the persisted layout — the same declaration the production module loader reads,
and therefore the same one that decides whether this component is discovered at
all.  A hard-coded path here could quietly disagree with it.
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

from app.module_loader import workspace_scan_roots  # noqa: E402

# Then every declared member's scan root, which is what makes `contract`
# importable as a normal package (rather than only under the loader's
# synthetic `_nullius_scanned_*` name).
for _root in workspace_scan_roots(REPO_ROOT / "src" / "app" / "module_loader.py"):
    _ensure_on_path(_root)
