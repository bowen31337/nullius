"""The canary reference store's seat in the ``app`` package namespace — feature 141.

Feature 135's seat (:mod:`app.modules.canary`) answers *what is the composed
canary service?* — the pin sweep.  This one answers the same shape of question
for feature 141's other half: *what is the composed frozen reference-pair
store?*

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*  The frozen pair lives in :mod:`canary._reference`
and the store in :mod:`canary._reference_store`; both arrive through the
workspace member's ``@register`` decorator, and this module is how the app
package reaches the composed store without importing the member at module
scope.

**A submodule, unlike feature 135's seat.**  ``src/app/modules/canary/`` was a
single ``__init__.py`` while the member contributed one component.  It now
contributes two — the pin sweep and the reference store — and the two are
different things on different lifecycles (the sweep asserts the deployment's
pins; feature 141's store persists the frozen pair), so the store gets its own
module beside the seat rather than a second accessor crowded into it.  The old
seat's promise is untouched: ``app.modules.canary`` still exports exactly
:data:`COMPONENT_NAME` and :func:`canary_component`, and a caller that only
wants the pin sweep never imports this file.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the value types, the store
class or the module-level spellings: a caller who has the store reaches
``store.freeze(...)`` and ``store.load(...)`` on it, and a second spelling here
would be a second thing to keep in sync.  The one question this module answers
is *what is the composed reference store?*

Where the composed store is ``None``, that is a statement about the deployment,
not an error: nothing named ``DATABASE_URL``, so there is no relational store to
compose.  A caller that needs one must not treat ``None`` as "the store ran and
found nothing" — those are different facts, and the member's error taxonomy is
built around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from canary import CanaryReferenceStore

__all__ = ["COMPONENT_NAME", "reference_store_component"]

#: The component name the canary member registers its reference store under.
#: Kept here as well as in the member — the member's seat spells its own
#: :data:`COMPONENT_NAME` twice for the same reason, and the store's
#: :data:`canary.REFERENCE_STORE_COMPONENT_NAME` for a third — so the three
#: cannot drift apart silently, and ``test_app_module.py`` asserts they agree.
COMPONENT_NAME = "canary-reference-store"


def reference_store_component(
    app: Application | None = None,
) -> CanaryReferenceStore | Any:
    """Return the composed canary reference store (feature 141's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``canary-reference-store`` component is registered — an absent component is
    a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the store resolves its path on first
    use, so asking for the component is always safe and the first ``freeze()``
    or ``load()`` is where the file is actually opened.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
