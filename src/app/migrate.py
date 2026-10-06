"""``python -m app.migrate`` -- apply every migrations/versions/0*.py file in
chain order, with no Alembic dependency (the workspace has none installed).

Each file in ``migrations/versions/`` is a plain module exposing ``REVISION``,
``DOWN_REVISION`` and ``apply(database_url)`` (see any file in that directory
for the convention). This module is the runner they never had: it discovers
the chain by following ``DOWN_REVISION`` links -- never filename sort alone,
because a filename is a convention, not the chain's own structure -- imports
each file by path, and calls ``apply()`` in order.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType

__all__ = [
    "DATABASE_URL_ENV",
    "EXIT_CONFIG",
    "EXIT_MIGRATION_FAILED",
    "EXIT_OK",
    "VERSIONS_DIR",
    "MigrationApplyError",
    "MigrationError",
    "discover_chain",
    "main",
    "run_migrations",
]

#: The environment variable naming the relational store, the one spelling
#: every runner in this workspace uses.
DATABASE_URL_ENV = "DATABASE_URL"

#: The migration tree, resolved from this file's own location so it is
#: correct regardless of the caller's working directory.
VERSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations" / "versions"

EXIT_OK = 0
EXIT_MIGRATION_FAILED = 1
EXIT_CONFIG = 2


class MigrationError(Exception):
    """The tree itself does not chain into one line: no root, two files
    chaining after the same revision, or a revision unreachable from the
    root."""


class MigrationApplyError(Exception):
    """One migration's ``apply()`` raised. ``str()`` is the one line
    ``main`` prints: the revision, then the cause -- no traceback."""

    def __init__(self, revision: str, cause: BaseException) -> None:
        super().__init__(f"{revision}: {cause}")
        self.revision = revision
        self.cause = cause


def _load_migration(path: Path) -> ModuleType:
    """Import one migrations/versions/*.py file by path, under a synthetic
    module name so it never collides with an installed package of the same
    name."""
    module_name = f"_nullius_migration_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"{path}: not an importable module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    for attribute in ("REVISION", "DOWN_REVISION", "apply"):
        if not hasattr(module, attribute):
            raise MigrationError(f"{path}: carries no {attribute!r}")
    return module


def discover_chain(versions_dir: Path) -> list[ModuleType]:
    """Every ``0*.py`` file under ``versions_dir``, loaded and ordered by its
    own ``REVISION``/``DOWN_REVISION`` chain -- from the one file whose
    ``DOWN_REVISION`` names no file in the tree, to the head.

    Never filename sort: the chain is the files' own claim about their
    order, and a filename is only a convention this tree happens to follow.
    """
    paths = sorted(versions_dir.glob("0*.py"))
    modules = [_load_migration(path) for path in paths]
    if not modules:
        return []

    by_revision: dict[str, ModuleType] = {}
    for module in modules:
        if module.REVISION in by_revision:
            raise MigrationError(
                f"two migration files both claim REVISION {module.REVISION!r}"
            )
        by_revision[module.REVISION] = module
    revisions = set(by_revision)

    roots = [m for m in modules if m.DOWN_REVISION not in revisions]
    if not roots:
        raise MigrationError(
            "no root migration found: every file's DOWN_REVISION names "
            "another file in the tree"
        )
    if len(roots) > 1:
        names = ", ".join(sorted(m.REVISION for m in roots))
        raise MigrationError(
            f"ambiguous migration tree: {len(roots)} files chain after a "
            f"revision outside the tree ({names})"
        )

    by_down_revision: dict[str | None, ModuleType] = {}
    for module in modules:
        if module.DOWN_REVISION in by_down_revision:
            other = by_down_revision[module.DOWN_REVISION]
            raise MigrationError(
                f"both {other.REVISION!r} and {module.REVISION!r} chain "
                f"after {module.DOWN_REVISION!r}"
            )
        by_down_revision[module.DOWN_REVISION] = module

    chain = [roots[0]]
    seen = {roots[0].REVISION}
    current = roots[0]
    while current.REVISION in by_down_revision:
        current = by_down_revision[current.REVISION]
        if current.REVISION in seen:
            raise MigrationError(f"migration cycle detected at {current.REVISION!r}")
        chain.append(current)
        seen.add(current.REVISION)

    if len(chain) != len(modules):
        missing = sorted(revisions - seen)
        raise MigrationError(
            f"{len(missing)} migration(s) not reachable from root "
            f"{roots[0].REVISION!r}: {', '.join(missing)}"
        )
    return chain


def run_migrations(
    database_url: str,
    *,
    versions_dir: Path | None = None,
    emit: Callable[[str], object] = print,
) -> tuple[str, ...]:
    """Apply every migration in chain order against ``database_url``.

    Prints one JSON line per file (``{"revision": ..., "statements": N}``),
    then one ``{"head": ...}`` line, and returns the applied revisions in
    order. A file whose ``apply()`` raises stops the run and is reported as
    :class:`MigrationApplyError`, naming the revision -- migrations already
    applied before it stay applied, since each is its own committed unit.
    """
    chain = discover_chain(versions_dir if versions_dir is not None else VERSIONS_DIR)
    applied: list[str] = []
    for module in chain:
        try:
            statements = module.apply(database_url)
        except Exception as exc:
            raise MigrationApplyError(module.REVISION, exc) from exc
        applied.append(module.REVISION)
        emit(json.dumps({"revision": module.REVISION, "statements": len(statements)}))
    emit(json.dumps({"head": applied[-1] if applied else None}))
    return tuple(applied)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
    versions_dir: Path | None = None,
) -> int:
    """``python -m app.migrate`` -- no flags, no secret, needs ``DATABASE_URL``.

    ``env`` and ``emit`` are this command's seams, read and written exactly
    as the other operator CLIs in this workspace take them; ``versions_dir``
    is this module's own, so a test can point it at a tmp copy of the tree
    without touching the real one.
    """
    del argv  # no CLI flags are defined; accepted for interface symmetry
    source = os.environ if env is None else env
    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{DATABASE_URL_ENV} must name the database to migrate",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        run_migrations(database_url, versions_dir=versions_dir, emit=emit)
    except (MigrationApplyError, MigrationError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_MIGRATION_FAILED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
