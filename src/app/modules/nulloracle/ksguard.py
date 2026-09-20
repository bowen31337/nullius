"""The KS guard's seat in the ``app`` package namespace — feature 123.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*; this one answers the same shape of question for
the other half of §7.4: *what is the composed guard journal?*

app_spec.xml, "Null Oracle & Planted Nulls", feature 123: *System persists
the p-value of a two-sample Kolmogorov-Smirnov test comparing in-sample
scores of null nodes against real nodes per campaign.*  The test lives in
:mod:`nulloracle.ks` and the store in :mod:`nulloracle.ksguard`; both arrive
through the workspace member's ``@register`` decorator, and this module is
how the app package reaches the composed store without importing the member
at module scope.

**A submodule, unlike feature 109's seat.**  ``src/app/modules/nulloracle/``
was a single ``__init__.py`` while the member contributed one component.  It
now contributes two — the sidecar and the guard journal — and the two are
different things on different lifecycles (§7.1's sealed file and feature
123's relational store), so the guard gets its own module beside the seat
rather than a second accessor crowded into it.  The old seat's promise is
untouched: ``app.modules.nulloracle`` still exports exactly
:data:`COMPONENT_NAME` and :func:`null_sidecar_component`, and a caller that
only wants the sidecar never imports this file.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the test, the store
class or the module-level spellings: a caller who has the journal reaches
``journal.guard(...)`` and ``journal.load(...)`` on it, and a second
spelling here would be a second thing to keep in sync.  The one question
this module answers is *what is the composed KS guard?*

Where the composed journal is ``None``, that is a statement about the
deployment, not an error: nothing named ``DATABASE_URL``, so there is no
relational store to compose.  A caller that needs one must not treat
``None`` as "the guard ran and found nothing" — those are different facts,
and the member's error taxonomy is built around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import KsGuard

__all__ = ["COMPONENT_NAME", "ks_guard_component"]

#: The component name the nulloracle member registers its guard journal
#: under.  Kept here as well as in the member — the member's seat spells its
#: own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and ``test_app_module.py`` asserts they agree.
COMPONENT_NAME = "nulloracle-ks-guard"


def ks_guard_component(app: Application | None = None) -> KsGuard | Any:
    """Return the composed KS guard journal (feature 123's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-ks-guard`` component is registered — an absent component is
    a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the store resolves its path on first
    use, so asking for the component is always safe and the first
    ``guard()`` or ``load()`` is where the file is actually opened.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
