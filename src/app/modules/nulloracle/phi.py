"""The null fraction's seat in the ``app`` package namespace — feature 117.

app_spec.xml, "Null Oracle & Planted Nulls", feature 117: *System persists
the null fraction phi on the campaign, computed as a clip of 2 divided by the
workspace count against a floor of 0.15 and a ceiling of 0.35.*  The store and
its ``clip(2/W, 0.15, 0.35)`` computation live in :mod:`nulloracle.phi`, and
this module is how the app package reaches the composed fraction store without
importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?* and feature 124's seat
(:mod:`app.modules.nulloracle.verdict`) answers *what is the composed
verdict?*; this one answers the same shape of question for the member's fourth
component: *what is the composed fraction store?*

**A fourth seat, beside the other three.**  ``src/app/modules/nulloracle/``
was a single ``__init__.py`` while the member contributed one component.  It
now contributes four — the sidecar, the guard journal, the verdict and the
fraction — and the four are different things on different lifecycles (§7.1's
sealed file, feature 123's relational store, feature 124's verdict store and
feature 117's fraction store), so the fraction gets its own module beside the
other three rather than a fourth accessor crowded into any of them.  The older
seats' promises are untouched: ``app.modules.nulloracle`` still exports
exactly :data:`COMPONENT_NAME` and :func:`null_sidecar_component`,
``app.modules.nulloracle.ksguard`` still exports exactly its ``COMPONENT_NAME``
and :func:`ks_guard_component`, and ``app.modules.nulloracle.verdict`` still
exports exactly its ``COMPONENT_NAME`` and :func:`verdict_component`; a caller
that only wants the sidecar, the guard or the verdict never imports this file.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the store class, the clip
or the fraction: a caller who has the store reaches
``phi.persist(campaign_id, W)`` and ``phi.load(campaign_id)`` on it, and a
second spelling here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed fraction store?*

Where the composed store is ``None``, that is a statement about the
deployment, not an error: nothing named ``DATABASE_URL``, so there is no
relational store to compose.  A caller that needs one must not treat ``None``
as "the campaign's fraction was fixed" — those are different facts, and the
member's error taxonomy is built around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import PlantedNullFraction

__all__ = ["COMPONENT_NAME", "fraction_component"]

#: The component name the nulloracle member registers its fraction store
#: under.  Kept here as well as in the member — the member's seat spells its
#: own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and ``test_app_module.py`` asserts they agree.
COMPONENT_NAME = "nulloracle-null-fraction"


def fraction_component(app: Application | None = None) -> PlantedNullFraction | Any:
    """Return the composed fraction store (feature 117's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-null-fraction`` component is registered — an absent component
    is a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the store resolves its path on first
    use, so asking for the component is always safe and the first
    ``persist()`` or ``load()`` is where the file is actually opened.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
