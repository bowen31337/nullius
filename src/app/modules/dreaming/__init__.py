"""The dreaming module — app-level entrypoint for the dreaming workspace member.

The implementation lives in the ``dreaming`` workspace member
(``packages/dreaming``, import name ``dreaming``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` builds a :class:`~dreaming.cycle.CycleFreeze` (app_spec.xml,
"Dreaming Loop & Meta-Selection", feature 270: *"System rejects a replay pool
mutation during a dreaming iteration, holding the pool fixed for the cycle"*,
which docs/alpha-engine-prd.md §C5 states as the first clause of the outer loop
and §12.1 gives the reason for: *"The paper's guarantee ``V^{m★} ≥ V^0`` holds
on the fixed history"*) — or nothing at all, when the deployment names no
relational store.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/dreaming/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for the
component, and a module that cannot reach it (member not scanned, workspace
empty) returns ``None`` rather than failing import, mirroring the factory's own
"degrade, don't break" stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing more.
It does not re-export the hold record, the schema text, the commitment reader
or the errors: a caller who has the freeze reaches ``open()``, ``release()``,
``verify()``, ``guard()``, ``open_hold()`` and ``holds()`` on it — every one of
them feature 270's own surface, the act of holding the pool and the account of
who held it — and a second spelling of those here would be a second thing to
keep in sync.  This module answers exactly one question — *what is the composed
cycle freeze?* — so features 271-282, which are this member's dependents, can
ask it without importing the member directly.  The one name it repeats beyond
that question is :data:`COMPONENT_NAME`, and its suite asserts the repetition
agrees with the member's.

**Where the composed freeze is ``None``, that is a statement about the
deployment.**  It is not "the pool is not held": a pool that is free is a
database that exists with no open hold, which is
``freeze.open_hold() is None`` against a store this seat *did* hand back.  The
two ``None``s fail differently and a caller must not read one through the
other — a caller holding this seat's ``None`` has no database to hold anything
in and must refuse to proceed rather than run §C5's loop while believing its
history was fixed.  §12.1's *"The dreaming loop overfits its own replay pool"*
is precisely why that refusal matters: a cycle that held nothing would compare
its ``M`` revisions across a pool free to move under them, and nothing in the
result would look wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from dreaming import CycleFreeze

__all__ = ["COMPONENT_NAME", "cycle_freeze_component"]

#: The component name the dreaming member registers under.  Kept here as well
#: as in the member — the sibling seats spell their own name twice for the same
#: reason, and this member's component suite asserts the two agree — so the two
#: cannot drift apart silently.
COMPONENT_NAME = "dreaming"


def cycle_freeze_component(app: Application | None = None) -> CycleFreeze | Any:
    """Return the composed cycle freeze (feature 270's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``dreaming`` component is registered.

    That ``None`` is a statement about the deployment rather than about the
    member: nothing named ``DATABASE_URL``, so there is no database for the
    replay pool to be held in.  It is deliberately **not** the same fact as a
    pool that is currently unheld — that is ``freeze.open_hold() is None``
    against a freeze this seat did hand back, and it means a database exists
    and no cycle is walking its pool.  A caller that needs §C5's first clause
    must treat this ``None`` as a refusal to proceed rather than as a pool it
    happened to find free.

    Construction touches no database and takes no hold: the member resolves its
    path on first use, so asking for the component is always safe — the same
    promise the member's builder makes and the bootstrap pool's seat makes for
    its own component — and the pool is fixed only when a caller's ``open()``
    fixes it, which is the "per outer iteration" of §C5's sentence kept true at
    the composition seam.  A freeze held from composition time would be a cycle
    that never ended.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
