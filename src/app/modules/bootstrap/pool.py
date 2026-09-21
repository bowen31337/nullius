"""The bootstrap pool's seat in the ``app`` package namespace — features 188 and 191.

app_spec.xml, "Bootstrap Worlds", feature 188: *System persists 40 to 50
generated bootstrap worlds into the replay pool on demand*; feature 191:
*System persists source commit and dataset manifest hash for every ported
world, which rejects a world whose recorded values no longer match its
upstream.*  Both implementations live in :mod:`bootstrap._pool`; this
module is how the app package reaches the composed pool without
importing the member at module scope.

Feature 181's seat (:mod:`app.modules.bootstrap`) answers *what is the
composed bootstrap world?*; this one answers the same shape of question
for the member's second component: *what is the composed bootstrap
pool?*  The growth is the one the tripwires directory already took for
its own second and third components — a seat per component rather than
one accessor learning a second key — and for the same reason: the two
components are different things on different lifecycles, and a caller
that wants the world never pays for the pool's deployment state or
vice versa.

**A second seat, and why the two ``None``s are not one ``None``.**  The
world seat's ``None`` means *no component was registered* — a statement
about composition (the member was not scanned, the workspace is empty).
The pool seat's ``None`` means something else: the member was scanned,
its builder ran, and *nothing named a database* — a statement about the
deployment.  Those are different facts that fail differently, and the
docstring of each seat must not be read through the other's.  A caller
holding the world seat's ``None`` cannot label a node at all; a caller
holding this seat's ``None`` has no pool to author 40-50 worlds into and
must refuse to proceed rather than silently authoring nothing — §10.6's
*"Target 40–50 bootstrap worlds before the first financial dreaming
cycle"* is a precondition, and a process that quietly skipped meeting it
would run the cycle the precondition exists to gate.

**Composition stays the factory's job.**  This module asks the factory
for the component and answers ``None`` — not an exception — when there
is none, mirroring the factory's own "degrade, don't break" stance
toward absent components.  It deliberately does **not** re-export the
pool class, the size band, the committed pool seed or the authoring
entry points: a caller who has the pool reaches ``persist_worlds()``,
``persist_ported_world()``, ``worlds()``, ``ported_worlds()``,
``verify_ported_world()``, ``world_count()`` and ``world()`` on it —
the authored half's draw and the ported half's provenance seating and
upstream check are both the store's own surface — and a second spelling
of those here would be a second thing to keep in sync.  The one question
this module answers is *what is the composed bootstrap pool?*

**Construction touches no database.**  The pool resolves its path on
first use, so asking for the component is always safe — the same promise
the member's builder makes and the poison store's seat makes for its
component — and the worlds are persisted only when a caller demands
them, which is the "on demand" of feature 188's own sentence: composing
an application never writes a row, and the first ``persist_worlds()`` is
where the authoring happens.  Feature 191's seating is on the same
terms: a ported world's digests are recorded when the caller that holds
the world asks the pool to record them, never at composition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from bootstrap import BootstrapPool

__all__ = ["COMPONENT_NAME", "bootstrap_pool_component"]

#: The component name the bootstrap member registers its pool under.
#: Kept here as well as in the member — the world seat spells its own name
#: twice for the same reason, and ``test_pool_component.py`` asserts the
#: two agree — so the two cannot drift apart silently.
COMPONENT_NAME = "bootstrap-pool"


def bootstrap_pool_component(app: Application | None = None) -> BootstrapPool | Any:
    """Return the composed bootstrap pool (feature 188's pool).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``bootstrap-pool`` component is
    registered.

    That ``None`` is a statement about the deployment rather than about
    the member: nothing named ``DATABASE_URL``, so there is no database
    for the replay pool's bootstrap half to live in.  It is deliberately
    **not** the same fact as the world seat's ``None``, which means no
    component was registered at all — and it is not an empty pool either:
    an empty pool is a statement about what has been *authored* (feature
    186's count reads it), while this ``None`` is a statement about what
    the deployment can hold.  A caller that needs to author §10.6's
    40-50 worlds must treat it as a refusal to proceed rather than as a
    pool of zero.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
