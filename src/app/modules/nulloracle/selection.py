"""The Type-R selection store's seat in the ``app`` package namespace — feature 118.

app_spec.xml, "Null Oracle & Planted Nulls", feature 118: *System persists
Type-R null status drawn without replacement across roots, inherited by the
whole subtree.*  The draw, the store and the inheritance rule live in
:mod:`nulloracle.selection`, and this module is how the app package reaches the
composed store without importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the composed
null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*, feature 124's seat (:mod:`app.modules.nulloracle.verdict`) answers
*what is the composed verdict?*, feature 117's seat
(:mod:`app.modules.nulloracle.phi`) answers *what is the composed fraction
store?*, feature 119's seat (:mod:`app.modules.nulloracle.flipdepth`) answers
*what is the composed flip-depth store?* and feature 121's seat
(:mod:`app.modules.nulloracle.resolution`) answers *what is the composed Type-D
oracle?*; this one answers the same shape of question for the member's eighth
component: *what is the composed Type-R selection store?*

**An eighth seat, beside the other seven.**  ``src/app/modules/nulloracle/`` was
a single ``__init__.py`` while the member contributed one component.  It now
contributes eight — the sidecar, the guard journal, the verdict, the fraction,
the flip depth, the Type-D oracle, the true-IR flip probability and the Type-R
selection — and the eight are different things on different lifecycles (§7.1's
sealed file, feature 123's relational store, feature 124's verdict store,
feature 117's fraction store, feature 119's flip-depth store, feature 121's
resolution, feature 120's true-IR store and feature 118's selection), so the
selection gets its own module beside the other seven rather than an eighth
accessor crowded into any of them.  The older seats' promises are untouched: a
caller that only wants the sidecar, the guard, the verdict, the fraction, the
flip depth, the resolution or the true-IR store never imports this file.

**The one seat that needs two things composed.**  Every other seat answers for a
component that resolves from a single source — a database URL or a sidecar
location.  This one's component needs *both*: the tree and the campaign row (so
the draw can read φ, ``W`` and the wells) and §7.1's sealed sidecar (the one
artifact allowed to hold the null bit, feature 110).  A composed application
carries this component only where both resolve, and this module's ``None`` means
*one of the two is unconfigured* — never *the campaign planted no nulls*, which
is a fact about a world and not about a deployment.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the store class, the draw or
the inheritance rule: a caller who has the store reaches
``selection.persist(campaign_id)``, ``selection.load(campaign_id)`` and
``selection.null_status(node_id)`` on it, and a second spelling here would be a
second thing to keep in sync.  The one question this module answers is *what is
the composed Type-R selection store?*

Where the composed store is ``None``, that is a statement about the deployment,
not an error: nothing named ``DATABASE_URL``, or nothing named a sidecar
location and key, so there is no store to compose.  A caller that needs one must
not treat ``None`` as "the campaign's roots are all real" — those are different
facts, and the member's error taxonomy is built around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import TypeRSelection

__all__ = ["COMPONENT_NAME", "type_r_selection_component"]

#: The component name the nulloracle member registers its Type-R selection
#: store under.  Kept here as well as in the member — the member's seat spells
#: its own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and ``test_app_module.py`` asserts they agree.  The
#: ``type-r-`` prefix is feature 121's convention: the selection is the second
#: of §7.3's two null regimes, and the prefix sorts the whole selection family
#: after the ``ks-*``, ``null-*``, ``type-d-*`` and ``true-ir-*`` families in
#: the name-sorted ``app.order``, so feature 123's
#: ``guard``-immediately-after-``sidecar`` order stays intact.
COMPONENT_NAME = "nulloracle-type-r-selection"


def type_r_selection_component(app: Application | None = None) -> TypeRSelection | Any:
    """Return the composed Type-R selection store (feature 118's store).

    With ``app`` given, the component is read from that application; without it,
    the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-type-r-selection`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` (or an unresolvable sidecar) is for the member's own
    builder.

    Construction touches no database and no file: the store resolves its path on
    first use and the sidecar opens nothing until the first ``write()`` or
    ``open()``, so asking for the component is always safe — which is what lets
    a composed application carry this store in a process that is not the one
    service account.  The read that would open the sidecar is where §7.1's
    permission rule bites.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
