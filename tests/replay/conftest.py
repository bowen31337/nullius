"""Import wiring for the repository-level replay suite.

This suite lives under the repository-level ``tests/`` tree — alongside the
feature-store and nulloracle integration suites — because its subject is the
*assembled* system: the replay component reached through the app namespace over
a deployment composed by the factory, and the walk the runtime actually takes
over the campaign tree the policy-runtime member holds.

Workspace members are not installed into the root environment — only the root
project and its dev group are — and the application factory imports member
packages by file path during its scan.  So this conftest puts the two members'
``src/`` trees on ``sys.path`` itself, the way ``tests/nulloracle/conftest.py``
and ``tests/feature-store/conftest.py`` do, and the root conftest's lake and
database isolation applies as it does to every suite here.

**What this suite is for, and what it deliberately is not.**  The member's own
suite (``packages/replay/tests``) pins feature 245's law — the refusal, the
recorded child, the cardinality, the refusals each in this member's vocabulary
— against a duck-typed tree, because a member never imports another member.
What *cannot* be pinned there is the wiring: that the member is scanned, that
``create_app()`` composes the component under the spec's plugin name, and that
the duck-typed seam matches the real ``CampaignTree`` the deployment holds.
Those are the questions here, and each one is asked the way a deployment asks
it — through the factory's public discovery functions and the app seat, never
by importing the member directly (an import would bypass the mechanism under
test).

The path bootstrap is spelled once, at import, and there is nothing else to
isolate: a replay is pure arithmetic over bytes that were already computed and
stored (docs/nullius-tech-architecture.md §10.1), so no test here writes a
file, opens a database or consults a clock beyond what the root conftest
already redirects.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_SRC = REPO_ROOT / "src"
REPLAY_SRC = REPO_ROOT / "packages" / "replay" / "src"
POLICY_RUNTIME_SRC = REPO_ROOT / "packages" / "policy-runtime" / "src"

for _entry in (str(REPLAY_SRC), str(POLICY_RUNTIME_SRC), str(FACTORY_SRC)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
