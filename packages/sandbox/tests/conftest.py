"""Suite-local bootstrap for the sandbox package's tests.

This suite lives inside the workspace member (``packages/sandbox/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
Feature 157's law needs none of them: it is a pure function of a policy
document and a run, so there is no lake to isolate, no database to point at
and no environment to clear.  That is a property worth keeping stated rather
than assumed: a sandbox law test that needed a temporary lake would mean the
law had grown a dependency ``packages/sandbox`` is not allowed to have — the
sandbox is the box agent-authored code goes inside, and the evaluator that
runs it is frozen and digest-pinned (§5, §12).

**No environment variables are read anywhere in this member, and that is the
design.**  The other members' conftests here clear the variables their code
reads (``DATABASE_URL``, ``NULLIUS_EVALUATOR_IMAGE``, …) so a developer shell
cannot leak into an assertion.  This one clears nothing, deliberately: the
law's only input beyond the run is the *committed isolation artifact*, which
ships inside the package, so a test that wanted to drift the policy does it by
building a document in memory rather than by setting a variable.  If a later
feature in this category does grow an environment knob, its suite will need
the clearing fixture; this file is where that would go, and the absence is
itself the statement that feature 157 has no such knob.

The path bootstrap below puts two trees on ``sys.path``:

* the member's ``src/``, because the root project does not depend on this
  member and the venv therefore does not install it — the same mechanism the
  module loader uses when it scans members;
* the repository root's ``src/``, because the member's ``__init__`` imports
  ``app.module_loader`` for the registration protocol.

This suite runs with the repository's pytest:
``uv run --all-packages pytest packages/sandbox``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MEMBER_SRC = _HERE.parent / "src"
_FACTORY_SRC = _HERE.parents[2] / "src"
for _path in (_MEMBER_SRC, _FACTORY_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
