"""Import wiring for the feature-store suite.

Workspace members are not installed into the root environment — only the
root project and its dev group are — and the application factory imports
member packages by file path during its scan.  A suite that wants to
import ``feature_store`` directly therefore puts the member's ``src/``
tree, and the factory's ``src/`` tree for ``app.module_loader``, on
``sys.path`` itself.

This keeps the suite identical under ``uv run pytest`` (where the venv
also provides ``app``) and a bare ``pytest``: either way the worktree's
own sources win, and no installation step is implied.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMBER_SRC = REPO_ROOT / "packages" / "feature-store" / "src"
FACTORY_SRC = REPO_ROOT / "src"

for _entry in (str(MEMBER_SRC), str(FACTORY_SRC)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
