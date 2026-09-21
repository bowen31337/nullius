"""Fixtures and import wiring for the signal-agent member's own suite.

This suite lives inside the workspace member
(``packages/signal-agent/tests``) rather than under the repository-level
``tests/`` tree, because the member — including its tests — is this feature's
file-claim scope, and the placement is the one the bootstrap, artifacts,
sandbox and canary members take for the same reason: same-basename files
collide under one pytest run, so each member's suite is collected under its
own conftest.

The path bootstrap puts two kinds of tree on ``sys.path``:

* the repository root's ``src/``, because this member's ``__init__`` imports
  ``app.module_loader`` for the registration protocol and the root project
  ships it;
* every declared member's scan root, resolved from the root
  ``pyproject.toml``'s own ``[tool.uv.workspace]`` through
  :func:`app.module_loader.workspace_scan_roots` rather than hard-coded —
  the same convention ``tests/contract/conftest.py`` follows, and for the
  same reason: this member's law is *written against* the ``contract``
  member's signal ABI and *screens against* the ``sandbox`` member's import
  allowlist, so a hard-coded path here could quietly disagree with the
  declaration that decides whether either member is on the path at all.

That gives the suite identical behaviour under
``uv run --all-packages pytest packages/signal-agent`` (where the venv also
provides every member) and under a bare ``pytest``.

**What the fixtures are.**  The vocabulary the tests share: the law itself,
and the sandbox's own admission screen.  The two proposals every claim is
made about live in ``test_authoring.py`` beside the claims rather than here —
they are *text*, and several assertions are about the text itself (it is
returned unmodified; its hash is the tree's ``code_hash``), so a fixture that
rebuilt them per test would make "the same source" a claim about two
constructions rather than about one string.

There is deliberately no environment isolation here.  Feature 205's law reads
no environment variable, opens no database, writes no file and consults no
clock: it is a pure function of a string of source and the contract's own
declaration.  A fixture that cleared the environment would imply a knob this
member does not have — the same statement ``packages/sandbox/tests/conftest``
makes for its own law, and the reason that member's pool-style fixtures (a
database URL, a store) have no counterpart here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# conftest.py -> packages/signal-agent/tests -> packages/signal-agent -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"

if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from app.module_loader import workspace_scan_roots

for _root in workspace_scan_roots():
    _entry = str(_root)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from signal_agent import SignalContract, signal_contract


@pytest.fixture
def law() -> SignalContract:
    """Feature 205's law, built directly rather than reached off a composed app.

    A test of the *law* should not depend on the factory having scanned
    anything; the component tests reach the composed one separately, which is
    the discipline the bootstrap member's suite states for its own worlds.
    """
    return signal_contract()


@pytest.fixture
def box_screen():
    """The sandbox's own admission test — feature 167's screen, as a callable.

    Built from the *sandbox member's* law and its committed allowlist, not
    from a stand-in: the claim under test is that feature 205's adoption can
    be gated by the box that will actually run the source, so the screen used
    here must be the real one.  Imported inside the fixture so the member's
    module-level imports stay the ones every other test needs.
    """
    from sandbox import committed_imports_allowlist, screen_module

    allowlist = committed_imports_allowlist()

    def screen(source: str):
        return screen_module(source, allowlist)

    return screen
