"""Path setup for the invariants suite.

The system-invariant CI gates import the workspace members they hold to their
contract — the same packages the production module loader discovers — but the
repository-level ``tests/`` tree is not on a bare interpreter's ``sys.path``,
and the harness is not assumed to invoke the suite through ``uv run``. This
conftest makes both the application factory and every declared member
importable either way, exactly as ``tests/contract/conftest.py`` does for its
suite.

It resolves the workspace from the root ``pyproject.toml``'s own
``[tool.uv.workspace]`` declaration via ``workspace_scan_roots()`` rather than
hard-coding a package path, so it follows the persisted layout — the same
declaration the production module loader reads, and therefore the same one
that decides whether a component is discovered at all. A hard-coded path here
could quietly disagree with it and let a gate test an import that production
composition would never resolve.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The recorded pinned evaluator image and its digest — the identity the pool
#: was scored under (feature 70's row). The digest is the ``sha256:<64 hex>``
#: first term folded into ``evaluator_hash``; the reference is the full
#: ``registry/repo@sha256:…`` spelling, kept only for diagnostics.
PINNED_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
PINNED_DIGEST = "sha256:" + "ab" * 32

#: A different pinned image — the digest a candidate merge would run under when
#: the image has moved. Two different bytes, one image name: the collision the
#: merge gate exists to refuse.
OTHER_PINNED_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "cd" * 32
OTHER_PINNED_DIGEST = "sha256:" + "cd" * 32


def _ensure_on_path(directory: Path) -> None:
    entry = str(directory)
    if directory.is_dir() and entry not in sys.path:
        sys.path.insert(0, entry)


# The factory first: workspace_scan_roots() below is imported from it.
_ensure_on_path(REPO_ROOT / "src")

from app.module_loader import workspace_scan_roots  # noqa: E402

# Then every declared member's scan root, which is what makes ``evaluator``
# (and the other members a gate holds to its contract) importable as a normal
# package rather than only under the loader's synthetic ``_nullius_scanned_*``
# name.
for _root in workspace_scan_roots(REPO_ROOT / "src" / "app" / "module_loader.py"):
    _ensure_on_path(_root)
