"""The cost-model member's registration and its composition in the app.

Placement is the risky part of a plugin-shaped feature: a component that is
never scanned passes its own suite and contributes nothing.  These tests
assert the wiring rather than trusting it — that the root pyproject.toml's
declared workspace resolves to this package, that ``create_app`` composes
the service, and that the default composition reaches it — going through
the factory's public discovery functions rather than importing the package
directly, because importing it would bypass the very mechanism under test.

One trap is pinned here specifically, because it fails silently:

* **the double composition.**  ``app.module_loader._import_package``
  re-executes a package's ``__init__.py`` on every ``create_app()`` call,
  but a submodule already cached in ``sys.modules`` under the loader's
  synthetic name is not re-executed — so a ``@register`` that drifted into
  a submodule would fire on the first composition of a process and drop out
  of every later one.  A single-composition assertion passes vacuously once
  that happens; the test below composes twice and asserts on the *second*
  application.

Neither the builder's no-I/O promise nor its zero-argument signature is
decoration: the factory calls every builder during composition, so a
builder that read a file or demanded a parameter would break composition
for every other member.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import cost_model

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_members,
    workspace_scan_roots,
)

MEMBER_SRC = Path(cost_model.__file__).resolve().parent.parent
MEMBER_ROOT = MEMBER_SRC.parent


class TestTheMemberIsDiscovered:
    def test_the_member_is_declared_in_the_scanned_workspace(self) -> None:
        # The member's own pyproject.toml is what makes it a workspace
        # member and therefore scannable — the registration chain starts
        # here.  The loader treats a member's src/ as a *package-parent*:
        # its immediate children are the importable packages, which is why
        # the package lives at src/cost_model/ and not src/nullius/cost_model/.
        assert (MEMBER_ROOT / "pyproject.toml").is_file()
        assert MEMBER_SRC in workspace_scan_roots()
        assert (MEMBER_SRC / "cost_model" / "__init__.py").is_file()

    def test_the_declared_workspace_names_this_member(self) -> None:
        assert "cost-model" in {member.name for member in workspace_members()}

    def test_scanning_the_package_registers_exactly_one_component(self) -> None:
        # A fresh registry, not the process default: any earlier test that
        # called a bare create_app() has already imported every workspace
        # member into the current registry, so reading it back here would
        # assert accumulated process state, not this member's contribution.
        components = scan_components(str(MEMBER_SRC), registry=Registration())
        assert [component.name for component in components] == ["cost-model"]

    def test_the_registered_builder_takes_no_arguments(self) -> None:
        registry = Registration()
        (component,) = scan_components(str(MEMBER_SRC), registry=registry)
        signature = inspect.signature(component.builder)
        assert all(
            parameter.default is not inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )


class TestComposition:
    def test_create_app_composes_the_service(self, test_database_url: str) -> None:
        app = create_app(str(MEMBER_SRC), registry=Registration())
        assert isinstance(app, Application)
        service = app.get("cost-model")
        # The loader imports scanned packages under its own mangled module
        # name, so the composed service is the scanned copy's class — assert
        # on the observable contract, not on cross-copy isinstance.
        assert type(service).__qualname__ == "CostModelService"
        assert service.database_url == test_database_url

    def test_composition_touches_no_document_and_no_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The factory calls every builder during composition, so a builder
        # that read its document would fail composition for the whole
        # application in any deployment where the document is not yet
        # mounted — and would make an unreadable artifact an import error
        # rather than a use-site one.
        monkeypatch.setenv("NULLIUS_COST_MODEL_PATH", "/nonexistent/nope.yaml")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = create_app(str(MEMBER_SRC), registry=Registration())
        assert app.get("cost-model") is not None

    def test_the_builder_is_importable_by_name(self) -> None:
        # The registered builder and the importable symbol are one thing, so
        # a test or a tool can exercise the builder without the registry.
        assert callable(cost_model.build_cost_model_service)
        assert cost_model.build_cost_model() is not None

    def test_the_component_survives_a_second_composition(
        self, test_database_url: str
    ) -> None:
        # The registration lives in the package __init__ and not in a
        # submodule; the second composition is the one that catches it if it
        # ever drifts (see the module docstring).
        first = create_app(str(MEMBER_SRC), registry=Registration())
        assert first.get("cost-model") is not None
        second = create_app(str(MEMBER_SRC), registry=Registration())
        assert second.get("cost-model") is not None
        assert "cost-model" in second.order

    def test_the_default_roots_follow_the_declared_workspace(self) -> None:
        # No explicit roots: the factory scans what the root pyproject
        # declares, which is how this member is discovered in production.
        app = create_app(registry=Registration())
        assert "cost-model" in app.order


class TestTheEnvironmentBinding:
    def test_from_env_applies_the_shipped_default(self, test_database_url: str) -> None:
        # No NULLIUS_COST_MODEL_PATH: the service defers to the packaged
        # §6.2 document, so an unconfigured deployment still resolves one.
        service = cost_model.CostModelService.from_env()
        assert service.config_path is None
        assert service.database_url == test_database_url
        assert service.config.version == "2026.09.1"

    def test_from_env_honors_a_configured_document(
        self, document, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = document(
            'cost_model:\n  version: "2027.01.1"\n  venue: kraken_spot\n'
        )
        monkeypatch.setenv(cost_model.COST_MODEL_PATH_ENV, str(path))
        service = cost_model.CostModelService.from_env()
        assert service.config_path == str(path)
        assert service.config.reference == "kraken_spot/2027.01.1"

    def test_an_empty_path_variable_counts_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty variable is how a shell exports "nothing"; treating it as
        # a path would turn an unset override into a missing-file error.
        monkeypatch.setenv(cost_model.COST_MODEL_PATH_ENV, "")
        assert cost_model.CostModelService.from_env().config_path is None


class TestTheComposedApplication:
    def test_the_default_composition_answers_the_component(self) -> None:
        # With no explicit roots the factory scans the declared workspace —
        # the production path.
        assert create_app().get("cost-model") is not None

    def test_an_absent_component_answers_none(self) -> None:
        # An absent component is a discoverable state, not an exception.
        assert Application(components={}).get("cost-model") is None
