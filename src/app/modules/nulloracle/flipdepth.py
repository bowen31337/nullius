"""The flip-depth store's seat in the ``app`` package namespace — feature 119.

app_spec.xml, "Null Oracle & Planted Nulls", feature 119: *System persists a
Type-D flip depth drawn from a geometric distribution while every root stays
real.*  The draw and its store live in :mod:`nulloracle.flipdepth`, and this
module is how the app package reaches the composed flip-depth store without
importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*, feature 124's seat
(:mod:`app.modules.nulloracle.verdict`) answers *what is the composed
verdict?* and feature 117's seat
(:mod:`app.modules.nulloracle.phi`) answers *what is the composed fraction
store?*; this one answers the same shape of question for the member's fifth
component: *what is the composed flip-depth store?*

**A fifth seat, beside the other four.**  ``src/app/modules/nulloracle/`` was a
single ``__init__.py`` while the member contributed one component.  It now
contributes five — the sidecar, the guard journal, the verdict, the fraction
and the flip depth — and the five are different things on different lifecycles
(§7.1's sealed file, feature 123's relational store, feature 124's verdict
store, feature 117's fraction store and feature 119's flip-depth store), so the
flip depth gets its own module beside the other four rather than a fifth
accessor crowded into any of them.  The older seats' promises are untouched:
``app.modules.nulloracle`` still exports exactly :data:`COMPONENT_NAME` and
:func:`null_sidecar_component`, ``app.modules.nulloracle.ksguard`` still exports
exactly its ``COMPONENT_NAME`` and :func:`ks_guard_component`,
``app.modules.nulloracle.verdict`` still exports exactly its ``COMPONENT_NAME``
and :func:`verdict_component`, and ``app.modules.nulloracle.phi`` still exports
exactly its ``COMPONENT_NAME`` and :func:`fraction_component`; a caller that
only wants the sidecar, the guard, the verdict or the fraction never imports
this file.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the draw, the store class or
the module-level spellings: a caller who has the store reaches
``flipdepth.persist(...)`` and ``flipdepth.load(...)`` on it, and a second
spelling here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed flip-depth store?*

Where the composed store is ``None``, that is a statement about the deployment,
not an error: nothing named ``DATABASE_URL``, so there is no relational store to
compose.  A caller that needs one must not treat ``None`` as "the branch was
never drawn" — those are different facts, and the member's error taxonomy is
built around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import FlipDepth

__all__ = ["COMPONENT_NAME", "flip_depth_component"]

#: The component name the nulloracle member registers its flip-depth store
#: under.  Kept here as well as in the member — the member's seat spells its
#: own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and ``test_app_module.py`` asserts they agree.  The
#: ``null-`` prefix is feature 117's convention: the fraction and the flip
#: depth are both null-structure campaign parameters, and the prefix keeps
#: them sorting after the ``ks-*`` pair in the name-sorted ``app.order`` so
#: feature 123's ``guard``-immediately-after-``sidecar`` order stays intact.
COMPONENT_NAME = "nulloracle-null-flip-depth"


def flip_depth_component(app: Application | None = None) -> FlipDepth | Any:
    """Return the composed flip-depth store (feature 119's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-flip-depth`` component is registered — an absent component is
    a discoverable state, not an exception, exactly as an unset ``DATABASE_URL``
    is for the member's own builder.

    Construction touches no database: the store resolves its path on first
    use, so asking for the component is always safe and the first
    ``persist()`` or ``load()`` is where the file is actually opened.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
