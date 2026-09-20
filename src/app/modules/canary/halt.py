"""The dream-halt store's seat in the ``app`` package namespace — feature 143.

Feature 135's seat (:mod:`app.modules.canary`) answers *what is the composed
canary service?* — the pin sweep — and feature 141's seat
(:mod:`app.modules.canary.reference_store`) answers the same shape of question
for the frozen reference pair.  This one answers it for feature 143's half:
*what is the composed store a determinism break is halted to?*

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 143: *System
halts dreaming when the canary score differs from the recorded constant by
more than 1e-12, which emits a determinism_broken alert.*  The decision and
the alert live in :mod:`canary._halt`; both arrive through the workspace
member's ``@register`` decorator, and this module is how the app package
reaches the composed halt store without importing the member at module scope.

**A third seat, beside the other two.**  ``src/app/modules/canary/`` held a
single ``__init__.py`` while the member contributed one component, and a
second module when it contributed two.  It now contributes three — the pin
sweep, the reference store and the halt store — and the third is as different
from the second as the second was from the first: the reference store holds
the frozen pair the nightly canary replays, while this one holds the halt a
broken replay writes, and a deployment can hold a frozen pair while dreaming
runs un-halted.  So the halt store gets its own module beside the older seats
rather than a third accessor crowded into either, and both older promises are
untouched: ``app.modules.canary`` still exports exactly :data:`COMPONENT_NAME`
and :func:`canary_component`, and ``app.modules.canary.reference_store`` still
exports exactly its own two.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the store class, the
record, the alert vocabulary or the module-level spellings: a caller who has
the store reaches ``halt(...)``, ``halted()`` and
``require_dreaming_allowed()`` on it, and the emission itself
(:func:`canary.halt_dreaming`) is the member's, not the seat's — a second
spelling here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed halt store?*

Where the composed store is ``None``, that is a statement about the
deployment, not an error: nothing named ``DATABASE_URL``, so there is no
relational store to compose — the same answer the reference store's seat
gives, for the same deployment fact.  A caller that needs one must not treat
``None`` as "the canary ran and did not break" — those are different facts,
and the member's refusal in :func:`canary.halt_dreaming` exists to keep them
apart.

**Construction touches no database.**  The store resolves its path on first
use, so asking for the component is always safe and the first ``halt()`` or
``halted()`` is where the file is actually opened — the same promise the
member's builder makes, and the reason composing an application never has the
side effect of creating a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from canary import CanaryHaltStore

__all__ = ["COMPONENT_NAME", "halt_store_component"]

#: The component name the canary member registers its halt store under.  Kept
#: here as well as in the member — the member's seat spells its own
#: :data:`COMPONENT_NAME` twice for the same reason, and the store's
#: :data:`canary.HALT_STORE_COMPONENT_NAME` for a third — so the three cannot
#: drift apart silently, and ``test_app_module.py`` asserts they agree.
COMPONENT_NAME = "canary-dream-halt"


def halt_store_component(
    app: Application | None = None,
) -> CanaryHaltStore | Any:
    """Return the composed canary halt store (feature 143's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``canary-dream-halt`` component is registered — an absent component is a
    discoverable state, not an exception, exactly as an unset ``DATABASE_URL``
    is for the member's own builder.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
