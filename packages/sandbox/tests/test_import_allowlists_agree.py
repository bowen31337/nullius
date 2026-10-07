"""The host screen and the sandbox child submit against one ceiling.

Bug: the host-side admission screen (this member's committed
``imports_allowlist.json``, compiled by :func:`sandbox.committed_imports_allowlist`)
admitted ``numpy`` after ``orchestrator._sandbox_child.AGENT_IMPORTS_ALLOWLIST``
dropped it — the evaluation runtime a signal actually executes under has no
numpy installed, so a numpy signal passed the static screen, was charged a
trial, and only then died inside the sandbox with a ``ModuleNotFoundError``,
instead of being refused deterministically, for free, before anything ran.

The two allowlists are restated by value rather than shared by import (the
child bootstrap cannot import :mod:`sandbox` — see its own module docstring
— and this member carries no third-party dependency, so it cannot import
``orchestrator`` either, which would pull in ``polars``/``pyarrow``/
``contract``).  One restated ceiling with no test pinning it equal is a
ceiling that drifts silently, which is exactly what happened here.  So this
suite reads both committed sources fresh at test time — the JSON document
through this member's own compiled allowlist, the child's set by parsing
``orchestrator/_sandbox_child.py``'s source rather than importing it — and
asserts they name the same top-level modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sandbox import (
    DISALLOWED_IMPORT_CODE,
    ModuleReason,
    committed_imports_allowlist,
    sandbox_imports,
)

_CHILD_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "orchestrator"
    / "src"
    / "orchestrator"
    / "_sandbox_child.py"
)


def _read_child_allowlist() -> frozenset[str]:
    """Parse ``AGENT_IMPORTS_ALLOWLIST`` out of the child's own source.

    A static parse, not an import: this member owns no third-party
    dependency, and importing ``orchestrator._sandbox_child`` would pull in
    ``polars``, ``pyarrow`` and ``contract`` just to read one literal.
    """
    tree = ast.parse(_CHILD_SOURCE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "AGENT_IMPORTS_ALLOWLIST"
            and isinstance(node.value, ast.Call)
            and node.value.args
        ):
            return frozenset(ast.literal_eval(node.value.args[0]))
    raise AssertionError(
        f"AGENT_IMPORTS_ALLOWLIST assignment not found in {_CHILD_SOURCE_PATH}"
    )


def test_host_and_child_allowlists_name_the_same_top_level_modules() -> None:
    host_terms = {term.split(".")[0] for term in committed_imports_allowlist().terms()}
    child_terms = _read_child_allowlist()

    assert host_terms == child_terms


def test_numpy_is_refused_by_the_host_screen_before_any_run() -> None:
    decision = sandbox_imports().screen("import numpy as np\n")

    assert decision.admitted is False
    assert decision.reason is ModuleReason.OUTSIDE_ALLOWLIST
    assert decision.detail.startswith(DISALLOWED_IMPORT_CODE)
    assert "numpy" in decision.detail
