"""The poison store's seat in the ``app`` package namespace — feature 131.

app_spec.xml, "Leakage Tripwires", feature 131: *System persists a tripwire
failure as poisoning the node together with its entire subtree.*  The
implementation lives in :mod:`tripwires.poison`; this module is how the app
package reaches the composed store without importing the member at module
scope.

Feature 125's seat (:mod:`app.modules.tripwires`) answers *what is the composed
tripwire component?*; this one answers the same shape of question for the
member's second component: *what is the composed store a tripwire failure is
persisted to?*

**A second seat, beside the first.**  ``src/app/modules/tripwires/`` was a
single ``__init__.py`` while the member contributed one component — feature
125's stateless probe.  It now contributes two, and they are different things
on different lifecycles: the probe resolves nothing and is ready the instant it
is built, while the store resolves ``DATABASE_URL`` and may legitimately not
exist.  So the store gets its own module beside the older seat rather than a
second accessor crowded into it.  The older seat's promise is untouched:
``app.modules.tripwires`` still exports exactly :data:`COMPONENT_NAME` and
:func:`tripwires_component`, and a caller that only wants the probe never
imports this file.

**The two ``None``\\ s are different, and that is the whole reason this module
exists rather than a second function in the first one.**  Feature 125's seat
documents its ``None`` as meaning exactly one thing — no tripwires component was
registered — precisely because a stateless probe has no second unconfigured
state to be confused with.  This seat's ``None`` means *nothing named a
relational store*, which is a statement about the deployment and not about the
member: there is no store to persist anything to here.  A caller that needs one
must not treat ``None`` as "the failure was recorded and there was nothing to
record" — those are different facts, and this feature's refusals are built
around keeping them apart.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the store class, the table
name, the error or the entry points: a caller who has the store reaches
``poison(...)``, ``poisoned(...)`` and ``subtree_of(...)`` on it, and a second
spelling here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed poison store?*

**Construction touches no database.**  The store resolves its path on first
use, so asking for the component is always safe and the first ``poison()`` or
``poisoned()`` is where the file is actually opened — the same promise the
member's builder makes, and the reason composing an application never has the
side effect of creating a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from tripwires import PoisonStore

__all__ = ["COMPONENT_NAME", "poison_store_component"]

#: The component name the tripwires member registers its poison store under.
#: Kept here as well as in the member — the nulloracle member's three seats
#: each spell their own name twice for the same reason, and
#: ``test_component.py`` asserts the two agree — so the two cannot drift apart
#: silently.
COMPONENT_NAME = "tripwires-poison"


def poison_store_component(app: Application | None = None) -> PoisonStore | Any:
    """Return the composed poison store (feature 131's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``tripwires-poison`` component is registered.

    That ``None`` is a statement about the deployment rather than about the
    member: nothing named ``DATABASE_URL``, so there is no relational store for
    a poisoning to be written to.  It is deliberately **not** the same fact as
    feature 125's seat's ``None``, which means no component was registered at
    all — and it is certainly not "the failure was recorded and there was
    nothing to record", which is a claim this store's own refusals exist to
    make impossible.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
