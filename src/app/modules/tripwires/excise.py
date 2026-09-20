"""The replay pool's seat in the ``app`` package namespace — feature 132.

app_spec.xml, "Leakage Tripwires", feature 132: *System excises a poisoned
subtree from the replay pool, which rejects every score that branch
contributed.*  The implementation lives in :mod:`tripwires.excise`; this module
is how the app package reaches the composed pool without importing the member at
module scope.

Feature 125's seat (:mod:`app.modules.tripwires`) answers *what is the composed
tripwire component?* and feature 131's (:mod:`app.modules.tripwires.poison`)
answers *what is the composed store a tripwire failure is persisted to?*; this
one answers the same shape of question for the member's fourth component: *what
is the composed replay pool?*

**A third seat, beside the other two.**  ``src/app/modules/tripwires/`` was a
single ``__init__.py`` while the member contributed one component, and grew a
second module when feature 131 added the poison store.  Feature 132 adds a
third, and the three are different things on different lifecycles: the probe
resolves nothing and is ready the instant it is built; the poison store resolves
``DATABASE_URL`` to *write* marks and may legitimately not exist; the pool
resolves ``DATABASE_URL`` to *read* the scores those marks condemn, and may
legitimately not exist either.  The older seats' promises are untouched:
``app.modules.tripwires`` still exports exactly :data:`COMPONENT_NAME` and
:func:`tripwires_component`, and ``app.modules.tripwires.poison`` still exports
exactly its own two names; a caller that only wants the probe or the store never
imports this file.

**The pool's ``None`` is not the poison store's ``None``, and that is why this
is a third module rather than a second accessor on the second one.**  Both mean
*nothing named a relational store*, and for both that is a statement about the
deployment rather than about the member — but a caller holding ``None`` from one
seat goes on to *write* a poisoning, and a caller holding ``None`` from this one
goes on to *refuse scores*.  Those are opposite directions of the same §C6
sentence, and the failure they produce is different in kind: an unconfigured
poison store means a failure that was never recorded, while an unconfigured pool
means a recorded failure whose scores go on being aggregated by §C5's dreaming
loop.  Two facts that different should not be one ``None`` read through one
docstring, which is the argument feature 131's seat already made for itself
against the first seat.

**A caller that wants both has both.**  The composed pool reads its marks
through the member's poison store — it builds one from the same URL when it is
not handed one — so ``pool.marks`` is the store feature 131's seat would hand
back, on one lifecycle, and an audit reading an excision and an audit reading
the mark are reading the same object graph.  This seat therefore does not
re-export the store: a caller who has the pool reaches it at ``marks``, and a
caller who wants the store *without* the pool asks the seat that exists for
exactly that.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the pool class, the score
value, the error or the two entry points: a caller who has the pool reaches
``survivors()``, ``excise(...)`` and ``scores_of(...)`` on it, and a second
spelling here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed replay pool?*

**Construction touches no database.**  The pool resolves its path on first use,
so asking for the component is always safe and the first ``survivors()`` or
``excise()`` is where the file is actually opened — the same promise the member's
builder makes, and the reason composing an application never has the side effect
of creating a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from tripwires import ReplayPool

__all__ = ["COMPONENT_NAME", "replay_pool_component"]

#: The component name the tripwires member registers its replay pool under.
#: Kept here as well as in the member — the member's other two seats each spell
#: their own name twice for the same reason, and ``test_component.py`` asserts
#: the two agree — so the two cannot drift apart silently.
COMPONENT_NAME = "tripwires-excise"


def replay_pool_component(app: Application | None = None) -> ReplayPool | Any:
    """Return the composed replay pool (feature 132's pool).

    With ``app`` given, the component is read from that application; without it,
    the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``tripwires-excise`` component is registered.

    That ``None`` is a statement about the deployment rather than about the
    member: nothing named ``DATABASE_URL``, so there is no relational store to
    read and no pool from which to refuse a poisoned branch's scores.  It is
    deliberately **not** the same fact as feature 125's seat's ``None``, which
    means no component was registered at all — and it is not the same fact as
    feature 131's seat's ``None`` either, which means a *failure* cannot be
    recorded.  This one means a recorded failure cannot be *acted on*, which is
    the state in which §C5's dreaming loop would keep aggregating the very
    evidence a tripwire rejected — so a caller that needs a pool must treat it
    as a refusal to proceed rather than as an empty pool.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
