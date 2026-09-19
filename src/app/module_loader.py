"""Application factory with a package-scanning module loader.

The design intent is a strict one-way dependency: *components* know about the
factory's registration protocol, but the factory never knows about any specific
component.  A component opts in by importing :func:`register` and decorating a
zero-argument callable (a "component builder").  The factory, when asked to
build the application, scans the configured workspace packages, collects every
registered builder, and composes their results into a single application object
(:class:`Application`).

Nothing a component does — not its registration, not its builder body — may
reach back and mutate the factory or the object it returns.  The factory is the
composition root and the sole author of the object it returns.

This module has no third-party dependencies and no I/O beyond filesystem scans
and imports, so it is import-safe in any environment (tests, sandboxes, the
deterministic replay path).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

__all__ = [
    "Application",
    "Component",
    "ComponentBuilder",
    "Reducer",
    "Registration",
    "create_app",
    "register",
    "registered_components",
    "scan_components",
]

log = logging.getLogger(__name__)

# A builder takes no arguments and returns the component's contribution to the
# composed application.  Returning ``None`` is allowed and simply contributes
# nothing under the default reducer.
ComponentBuilder = Callable[[], object]

# The default reducer folds a sequence of builder results into the single value
# stored under the component's key.  The signature is ``(accumulator, name,
# result)`` so a reducer can special-case by name if it ever needs to, while
# still never receiving any factory internals.
Reducer = Callable[[object, str, object], object]


class Component:
    """A registered component: the name and builder contributed to the app.

    A component is created only by :func:`register`.  It is immutable after
    creation — the factory reads ``name`` and ``builder`` but nothing edits
    them, and no component may reach in and rebind them.
    """

    __slots__ = ("name", "builder")

    def __init__(self, name: str, builder: ComponentBuilder) -> None:
        if not isinstance(name, str) or not name:
            raise TypeError("component name must be a non-empty string")
        if not callable(builder):
            raise TypeError(f"builder for component {name!r} must be callable")
        # Bind once, into read-only slots.  Deliberately no setter is exposed.
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "builder", builder)

    def __setattr__(self, key: str, value: object) -> None:
        # Components are immutable by contract: nothing — not the factory, not
        # another component, not the builder itself — may rebind a component
        # after registration.  This is the concrete enforcement of "no component
        # edits the factory": the registration record cannot be mutated in place.
        raise AttributeError(f"{type(self).__name__} is immutable; cannot set {key!r}")

    def __delattr__(self, key: str) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable; cannot delete {key!r}")

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Component(name={self.name!r}, builder={self.builder!r})"


class Registration:
    """The registry the factory reads from.

    Components register into a module-level registry.  A single process may host
    several registries (e.g. one per discovered workspace package tree), so the
    registry is a first-class object rather than a hidden global: :func:`register`
    writes to the *current* registry, and :func:`create_app` reads from the
    registry it is handed (defaulting to the current one).
    """

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}

    def add(self, component: Component) -> Component:
        """Record a component, replacing any prior registration of the same name.

        A later import of the same component name wins; this makes the scan
        order deterministic-by-name rather than import-order dependent.
        """
        if not isinstance(component, Component):
            raise TypeError("expected a Component instance")
        self._components[component.name] = component
        return component

    def components(self) -> list[Component]:
        # Sorted by name so composition order is stable regardless of the order
        # in which modules happened to be imported or scanned.
        return [self._components[name] for name in sorted(self._components)]

    def names(self) -> list[str]:
        return [component.name for component in self.components()]

    def __len__(self) -> int:
        return len(self._components)

    def __contains__(self, name: object) -> bool:
        return name in self._components


# The process-wide "current" registry.  Components that use the bare
# ``@register`` decorator (no registry argument) land here.
_current_registry = Registration()


def register(
    name: Optional[str] = None,
    *,
    registry: Optional[Registration] = None,
) -> Callable[[ComponentBuilder], ComponentBuilder]:
    """Register a component builder.

    Use as a decorator::

        from app.module_loader import register

        @register("config")
        def build_config() -> dict:
            return {"debug": False}

    ``name`` defaults to the builder's ``__name__`` when omitted.  ``registry``
    defaults to the process-wide current registry; pass an explicit registry to
    keep a set of components isolated from the default scan.

    The decorator returns the original builder unchanged, so the decorated
    function remains an ordinary callable — registration is a side effect, not
    a wrapper.
    """

    def decorator(builder: ComponentBuilder) -> ComponentBuilder:
        component_name = name if name is not None else getattr(
            builder, "__name__", None
        )
        if not component_name:
            raise TypeError(
                "register requires an explicit name when the builder has no __name__"
            )
        _current_registry_for(registry).add(Component(component_name, builder))
        return builder

    return decorator


def _current_registry_for(registry: Optional[Registration]) -> Registration:
    return registry if registry is not None else _current_registry


def registered_components(
    registry: Optional[Registration] = None,
) -> list[Component]:
    """Return every component currently registered, sorted by name."""
    return list(_current_registry_for(registry).components())


def scan_components(
    *roots: "str | os.PathLike[str]",
    registry: Optional[Registration] = None,
) -> list[Component]:
    """Scan workspace package directories for registered components.

    Each ``root`` is a directory whose immediate subdirectories are Python
    packages (a directory containing ``__init__.py``).  Every such package is
    imported so that its module-level ``@register`` calls fire; the components
    they register are collected from ``registry`` (default: the current one).

    Importing a package runs its top-level code.  Registration is a deliberate
    import side effect — this is how a component "announces" itself to the
    factory without the factory knowing its name in advance.

    Returns the registry's components (sorted by name).  Unimportable packages
    are logged and skipped rather than aborting the whole scan, so one broken
    component cannot take down composition — matching the "per-component
    isolation" principle of the wider system.
    """
    target = _current_registry_for(registry)
    # Make `target` the current registry so that `@register` calls fired during
    # import (which omit an explicit registry) land in the same registry that
    # create_app will read from.  Without this, a scanned component would
    # register into the process default while create_app read from a fresh one.
    global _current_registry
    previous_registry = _current_registry
    if registry is not None:
        _current_registry = registry
    try:
        for root in roots:
            root_path = Path(root)
            if not root_path.is_dir():
                log.warning(
                    "scan root %s does not exist or is not a directory; skipping", root
                )
                continue
            for package_dir in sorted(root_path.iterdir()):
                if not package_dir.is_dir():
                    continue
                if not (package_dir / "__init__.py").exists():
                    # Not a package directory; ignore (e.g. data files, docs).
                    continue
                _import_package(package_dir)
    finally:
        _current_registry = previous_registry
    return list(target.components())


def _import_package(package_dir: Path) -> None:
    """Import a package directory by file path, firing its registrations."""
    parent = package_dir.parent
    package_name = f"_nullius_scanned_{package_dir.name}"
    # Ensure the parent directory is importable, without permanently polluting
    # sys.path more than necessary.
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
        cleanup_path = True
    else:
        cleanup_path = False
    try:
        init_file = package_dir / "__init__.py"
        spec = importlib.util.spec_from_file_location(package_name, init_file)
        if spec is None or spec.loader is None:
            log.warning("could not create import spec for %s; skipping", package_dir)
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
        log.debug("scanned package %s", package_dir)
    except Exception:  # noqa: BLE001 - a bad component must not halt the scan
        log.exception("failed to import component package %s; skipping", package_dir)
    finally:
        if cleanup_path:
            try:
                sys.path.remove(str(parent))
            except ValueError:
                pass


@dataclass
class Application:
    """The object the factory returns.

    ``components`` maps each contributing component name to the value its builder
    returned (already folded by ``reducer``).  ``order`` records the deterministic
    composition order.  The factory owns construction; callers receive a fully
    composed, read-only-by-convention object.
    """

    components: Mapping[str, object] = field(default_factory=dict)
    order: tuple[str, ...] = ()

    def get(self, name: str, default: object = None) -> object:
        return self.components.get(name, default)

    def __contains__(self, name: object) -> bool:
        return name in self.components

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Application(components={list(self.components)!r})"


def create_app(
    *roots: "str | os.PathLike[str]",
    registry: Optional[Registration] = None,
    reducer: Optional[Reducer] = None,
) -> Application:
    """Build and return the composed :class:`Application`.

    This is the application factory.  It:

    1. scans ``roots`` (workspace package directories) so every component's
       ``@register`` decorator runs,
    2. reads the resulting components from ``registry`` (default: current),
    3. calls each component's builder, and
    4. folds the results into a single :class:`Application` via ``reducer``.

    No component receives any reference to the factory, the registry, or the
    :class:`Application` under construction, and none may mutate them.  The
    factory is the sole author of the returned object.

    ``reducer`` defaults to a dict merge: each component's result is stored under
    its name.  A custom reducer can combine results (e.g. merge config dicts,
    attach middleware) but still receives only ``(accumulator, name, result)`` —
    never the factory internals.
    """

    def default_reducer(accumulator: object, name: str, result: object) -> object:
        if accumulator is None:
            accumulator = {}
        if not isinstance(accumulator, dict):
            raise TypeError(
                "default reducer expects a dict accumulator; "
                f"got {type(accumulator).__name__}"
            )
        accumulator[name] = result
        return accumulator

    effective_reducer = reducer if reducer is not None else default_reducer

    # Scan first so that registrations made during the scan are visible.
    scan_components(*roots, registry=registry)
    target = _current_registry_for(registry)

    accumulator: object = None
    order: list[str] = []
    for component in target.components():
        result = component.builder()
        accumulator = effective_reducer(accumulator, component.name, result)
        order.append(component.name)

    if accumulator is None:
        # No components registered at all: return an empty, well-formed app
        # rather than raising, so an empty workspace is not an error state.
        accumulator = {}

    return Application(components=dict(accumulator), order=tuple(order))
