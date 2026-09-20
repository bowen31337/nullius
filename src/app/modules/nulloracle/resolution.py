"""The Type-D resolution's seat in the ``app`` package namespace — feature 121.

app_spec.xml, "Null Oracle & Planted Nulls", feature 121: *System resolves a
Type-D request by which returns real targets below the flip depth and
permuted targets at or beyond it.*  The boundary and the oracle that applies
it live in :mod:`nulloracle.resolution`, and this module is how the app
package reaches the composed Type-D oracle without importing the member at
module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*, feature 124's seat (:mod:`app.modules.nulloracle.verdict`) answers
*what is the composed verdict?*, feature 117's seat
(:mod:`app.modules.nulloracle.phi`) answers *what is the composed fraction
store?*, and feature 119's seat (:mod:`app.modules.nulloracle.flipdepth`)
answers *what is the composed flip-depth store?*; this one answers the same
shape of question for the member's sixth component: *what is the composed
Type-D oracle?* — the component the ``POST /target`` resolution of features
112-113 asks for when the campaign it is serving is the Type-D regime.

**A sixth seat, beside the other five.**  ``src/app/modules/nulloracle/`` was
a single ``__init__.py`` while the member contributed one component.  It now
contributes six — the sidecar, the guard journal, the verdict, the fraction,
the flip depth and the Type-D resolution — and the six are different things
on different lifecycles (§7.1's sealed file, feature 123's relational store,
feature 124's verdict store, feature 117's fraction store, feature 119's
flip-depth store and feature 121's read-side oracle), so the resolution gets
its own module beside the other five rather than a sixth accessor crowded
into any of them.  The older seats' promises are untouched: a caller that
only wants the sidecar, the guard, the verdict, the fraction or the flip
depth never imports this file.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the boundary, the oracle
class or the module-level spellings: a caller who has the oracle reaches
``resolve_request`` on it, and a second spelling here would be a second thing
to keep in sync.  The one question this module answers is *what is the
composed Type-D oracle?*

Where the composed oracle is ``None``, that is a statement about the
deployment, not an error: nothing named ``DATABASE_URL``, so there is no
relational store to compose.  A caller that needs one must not treat ``None``
as "the request resolved real" — an unconfigured deployment and an unresolved
request are different facts, and the member's error taxonomy is built around
keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import TypeDOracle

__all__ = ["COMPONENT_NAME", "type_d_resolution_component"]

#: The component name the nulloracle member registers its Type-D oracle
#: under.  Kept here as well as in the member — each seat spells its own
#: :data:`COMPONENT_NAME` twice for the same reason — so the two cannot drift
#: apart silently, and ``test_resolution_component.py`` asserts they agree.
#: The ``type-d-`` prefix sorts after both the ``ks-*`` and the ``null-*``
#: families in the name-sorted ``app.order``, so feature 123's
#: guard-immediately-after-sidecar adjacency is untouched (the same ordering
#: fact feature 119's seat states for its ``null-`` prefix).
COMPONENT_NAME = "nulloracle-type-d-resolution"


def type_d_resolution_component(app: Application | None = None) -> TypeDOracle | Any:
    """Return the composed Type-D oracle (feature 121's resolution).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-type-d-resolution`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the oracle resolves its path on first
    use, so asking for the component is always safe and the first
    ``resolve_request`` is where the file is actually opened.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
