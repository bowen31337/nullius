"""The stability store's seat in the ``app`` package namespace — feature 129.

app_spec.xml, "Leakage Tripwires", feature 129: *System re-runs a candidate
against a 20 percent universe subsample, persisting the subsample stability
figure.*  The implementation lives in :mod:`tripwires.subsample` (the figure)
and :mod:`tripwires.stability` (its persistence); this module is how the app
package reaches the composed store without importing the member at module
scope.

The member's earlier seats answer *what is the composed tripwire component?*
(:mod:`app.modules.tripwires`), *what is the composed poison store?*
(:mod:`app.modules.tripwires.poison`) and *what is the composed replay pool?*
(:mod:`app.modules.tripwires.excise`).  This one answers the same shape of
question for the member's fifth component: *what is the composed store a
perturbation-stability figure is persisted to?*

**A fourth seat rather than a second accessor on the poison store's.**  Both
resolve ``DATABASE_URL``, and that resemblance is exactly why they must not be
reached through one module.  Feature 131's store writes the record of a
*failure*, upserts on ``(node_id, axis)`` in ``tripwire_poison``, and refuses a
verdict that passed — there is nothing to poison, and a mark on a branch that
passed would excise scores nothing condemned.  This store writes a
*measurement* that is taken whether or not anything failed, into
``tripwire_stability``, and refuses only a verdict that disagrees with itself.
A caller asking for one and handed the other would get an object whose every
method means the other feature's thing, and the mistake would not surface until
a passing figure was refused or a poisoning was reported as a stability.

**The ``None`` is the deployment's, not the member's.**  As with the poison
seat: ``None`` means *nothing named a relational store here*, which is a
statement about the deployment rather than about the member, and it is not the
same fact as "the figure was small and there was nothing to record".  That
second sentence is the one feature 129's refusals exist to make impossible —
:func:`~tripwires.stability.record_stability` refuses by name when it resolves
no store rather than no-opping, and :meth:`~tripwires.stability.StabilityStore.stability_of`
refuses when a node has no figure on an axis — which is why this seat stays
silent and hands the refusal to the caller who actually needs to write.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance.  It deliberately
does **not** re-export the store class, the table name, the error or the entry
points: a caller who has the store calls ``record(...)``, ``figures(...)``,
``stability_of(...)`` and ``axes(...)`` on it, and a second spelling here would
be a second thing to keep in sync.

**Construction touches no database.**  The store resolves its path on first
use, so asking for the component is always safe and the first ``record()`` is
where the file is actually opened — the same promise the member's builder
makes, and the reason composing an application never has the side effect of
creating a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from tripwires import StabilityStore

__all__ = ["COMPONENT_NAME", "stability_store_component"]

#: The component name the tripwires member registers its stability store under.
#: Kept here as well as in the member — the member's other seats each spell
#: their own name twice for the same reason, and ``test_component.py`` asserts
#: the two agree — so the two cannot drift apart silently.
COMPONENT_NAME = "tripwires-stability"


def stability_store_component(app: Application | None = None) -> StabilityStore | Any:
    """Return the composed stability store (feature 129's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``tripwires-stability`` component is registered.

    That ``None`` is a statement about the deployment rather than about the
    member: nothing named ``DATABASE_URL``, so there is no relational store for
    a stability figure to be written to.  It is deliberately **not** the same
    fact as this member's first seat's ``None``, which means no component was
    registered at all, and not feature 131's seat's ``None`` either, which is
    the same deployment fact about a different table and a different refusal.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
