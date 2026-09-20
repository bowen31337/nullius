"""The void-marker store's seat in the ``app`` package namespace — feature 144.

Feature 135's seat (:mod:`app.modules.canary`) answers *what is the composed
canary service?* — the pin sweep — and features 141 and 143's seats
(:mod:`app.modules.canary.reference_store`, :mod:`app.modules.canary.halt`)
answer the same shape of question for the frozen reference pair and the halt of
dreaming.  This one answers it for feature 144's half: *what is the composed
store that holds which scores a determinism break voided?*

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 144: *System
persists a void marker on every score produced after a detected determinism
break, rather than letting bad data age into good data.*  The window, the
markers and the refusal live in :mod:`canary._void`; all three arrive through
the workspace member's ``@register`` decorator, and this module is how the app
package reaches the composed void-marker store without importing the member at
module scope.

**A fourth seat, beside the other three.**  ``src/app/modules/canary/`` held a
single ``__init__.py`` while the member contributed one component, a second
module when it contributed two, and a third when it contributed three.  It now
contributes four, and the fourth is as different from the third as the third was
from the second: the halt store answers *is dreaming halted?* — one row per
broken pair — while this one answers *may this score still be used?*, one row per
score the break invalidated, and a deployment can hold a halt while no score has
been swept into the void yet (a break detected before the pool is swept is the
normal order of events, not an anomaly).  So the void-marker store gets its own
module beside the older seats rather than a fourth accessor crowded into any of
them, and every older promise is untouched: ``app.modules.canary`` still exports
exactly :data:`COMPONENT_NAME` and :func:`canary_component`,
``app.modules.canary.reference_store`` still exports exactly its own two, and
``app.modules.canary.halt`` still exports exactly its own two.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the store class, the record
values, the window or the module-level spellings: a caller who has the store
reaches ``sweep(...)``, ``markers()`` and ``require_score_usable(...)`` on it,
and the sweep the nightly runner wants
(:func:`canary.void_scores_after_break`) is the member's, not the seat's — a
second spelling here would be a second thing to keep in sync.  The one question
this module answers is *what is the composed void-marker store?*

Where the composed store is ``None``, that is a statement about the deployment,
not an error: nothing named ``DATABASE_URL``, so there is no relational store to
compose — the same answer the other three seats give, for the same deployment
fact.  A caller that needs one must not treat ``None`` as "the canary broke and
nothing was voided" — those are different facts, and the member's refusal in
:func:`canary.void_scores_after_break` exists to keep them apart.

**Construction touches no database.**  The store resolves its path on first use,
so asking for the component is always safe and the first ``sweep()``,
``markers()`` or ``require_score_usable()`` is where the file is actually opened
— the same promise the member's builder makes, and the reason composing an
application never has the side effect of creating a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from canary import CanaryVoidMarkerStore

__all__ = ["COMPONENT_NAME", "void_marker_component"]

#: The component name the canary member registers its void-marker store under.
#: Kept here as well as in the member — the member's seat spells its own
#: :data:`COMPONENT_NAME` twice for the same reason, and the store's
#: :data:`canary.VOID_MARKER_COMPONENT_NAME` for a third — so the three cannot
#: drift apart silently, and ``test_app_module.py`` asserts they agree.
COMPONENT_NAME = "canary-void-marker"


def void_marker_component(
    app: Application | None = None,
) -> CanaryVoidMarkerStore | Any:
    """Return the composed canary void-marker store (feature 144's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``canary-void-marker`` component is registered — an absent component is a
    discoverable state, not an exception, exactly as an unset ``DATABASE_URL``
    is for the member's own builder.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
