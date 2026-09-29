"""The contract package is discovered by the application factory.

Placement is the risky part of a plugin-shaped feature: a component that is
never scanned passes its own suite and contributes nothing.  These tests assert
the wiring rather than trusting it — that the root pyproject.toml's declared
workspace resolves to this package, and that ``create_app`` actually composes
it.

They deliberately go through the factory's public discovery functions
(``workspace_members``, ``scan_components``, ``create_app``) rather than
importing the package directly, because importing it would bypass the very
mechanism under test.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from app.module_loader import (
    Registration,
    create_app,
    scan_components,
    workspace_members,
    workspace_scan_roots,
)

# Anchored to this file, never to the process's working directory: the suite
# must give the same answer whether pytest is invoked from the repo root, from
# tests/, or from inside the member itself.
REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SRC = REPO_ROOT / "packages" / "contract" / "src"


def test_contract_is_a_declared_workspace_member():
    # The root pyproject.toml declares `members = ["packages/*"]`; this member
    # must satisfy uv's rule that a member directory carries a pyproject.toml.
    members = {member.name for member in workspace_members()}
    assert "contract" in members


def test_contract_member_uses_a_scan_root_that_resolves_to_the_package():
    # The loader treats a member's src/ as a *package-parent*: its immediate
    # children are the importable packages.  `contract` must be one of them,
    # which is why the package lives at src/contract/ and not src/nullius/contract/.
    assert CONTRACT_SRC in workspace_scan_roots()
    assert (CONTRACT_SRC / "contract" / "__init__.py").is_file()


def test_factory_scans_and_composes_the_contract_component():
    app = create_app(CONTRACT_SRC)
    assert "contract" in app
    component = app.get("contract")
    assert component["contract_version"] == "0.1.0"
    assert component["market_window"] == "contract:MarketWindow"


def test_advertised_abi_name_resolves_to_the_class():
    # The component names the ABI instead of handing back a class object,
    # because a scanned package is imported under a synthetic module name —
    # the class the loader would return is not the class a normal
    # `from contract import MarketWindow` yields, and isinstance across that
    # seam silently fails.  Prove the name resolves to the real thing.
    from contract import MARKET_WINDOW_ABI, MarketWindow

    module_name, _, attribute = MARKET_WINDOW_ABI.partition(":")
    assert importlib.import_module(module_name).__dict__[attribute] is MarketWindow


def test_scanning_the_package_registers_exactly_one_component():
    # A fresh registry, not the process default: any earlier test that called
    # a bare ``create_app()`` has already imported every workspace member
    # into the current registry, so reading it back here would assert
    # accumulated process state, not this package's contribution.
    # The question under test is exactly "what does *this* member register?".
    components = scan_components(CONTRACT_SRC, registry=Registration())
    assert [component.name for component in components] == ["contract"]
