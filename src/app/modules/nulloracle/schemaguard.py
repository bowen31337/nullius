"""The tree-store guard's seat in the ``app`` package namespace — feature 110.

app_spec.xml, "Null Oracle & Planted Nulls", feature 110: *System keeps
is_null absent from the tree store entirely, which rejects any proposed node
column named is_null.*  The refusal, the extractor and the standing audit
live in :mod:`nulloracle.schemaguard`, and this module is how the app
package reaches the composed guard without importing the member at module
scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*, feature 124's seat (:mod:`app.modules.nulloracle.verdict`) answers
*what is the composed verdict?*, feature 117's seat
(:mod:`app.modules.nulloracle.phi`) answers *what is the composed fraction
store?*, feature 119's seat (:mod:`app.modules.nulloracle.flipdepth`) answers
*what is the composed flip-depth store?*, feature 121's seat
(:mod:`app.modules.nulloracle.resolution`) answers *what is the composed Type-D
oracle?* and feature 118's seat (:mod:`app.modules.nulloracle.selection`)
answers *what is the composed Type-R selection store?*; this one answers the
same shape of question for the member's twelfth component: *what is the
composed tree-store guard?*

**A twelfth seat, beside the other eleven.**  ``src/app/modules/nulloracle/``
was a single ``__init__.py`` while the member contributed one component.  It
now contributes twelve — the sidecar, the guard journal, the verdict, the
fraction, the flip depth, the Type-D oracle, the true-IR flip probability,
the Type-R selection, the planning gate, the target route, the key alert and
this guard — and the twelve are different things on different lifecycles,
so the guard gets its own module beside the other eleven rather than a
twelfth accessor crowded into any of them.  The older seats' promises are
untouched: a caller that only wants the sidecar, the journal, the verdict,
the fraction, the flip depth, the resolution, the selection, the gate, the
route or the alert never imports this file.

**The one seat whose component reads and never writes.**  Every other seat
answers for a component that resolves from a source and then *holds*
something — a sealed file, a journal, a store of drawn parameters.  This
one's component holds nothing at all: it is the standing audit over a
*schema*, and its one read opens the store read-only (SQLite's ``mode=ro``),
because a check must not mutate what it checks — a guard whose audit
created the ``node`` table would be blessing a schema it just made.  A
composed application therefore carries this component at no risk to the
store it names, and the audit can be run hourly, nightly or before every
campaign without changing a byte.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the reviews, the
extractor or the audit record: a caller who wants them reaches
``nulloracle.schemaguard.review_node_columns`` and ``review_ddl`` — the two
halves of the feature that need no store at all and are imported directly —
while a caller who has the guard reaches ``guard.audit()`` on it, and a
second spelling here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed tree-store guard?*

Where the composed guard is ``None``, that is a statement about the
deployment, not an error and not a verdict: nothing named ``DATABASE_URL``,
so there is no store to audit.  A caller must not treat ``None`` as *"the
barrier holds"* — those are different facts, and the difference is the
whole of this feature: an unaudited store and a clean one look identical
until somebody looks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import TreeStoreGuard

__all__ = ["COMPONENT_NAME", "tree_store_guard_component"]

#: The component name the nulloracle member registers its tree-store guard
#: under.  Kept here as well as in the member — the member's seat spells its
#: own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and ``test_app_module.py``-style suites assert they
#: agree.  The ``tree-`` prefix is chosen for ``app.order``, which is
#: name-sorted: ``nulloracle-tree-store-guard`` lands after
#: ``nulloracle-target-route`` and before ``nulloracle-true-ir-flip-depth``,
#: so feature 123's ``guard``-immediately-after-``sidecar`` adjacency — a
#: rule this member has held since the ``sidecar-`` name was chosen — stays
#: intact.
COMPONENT_NAME = "nulloracle-tree-store-guard"


def tree_store_guard_component(app: Application | None = None) -> TreeStoreGuard | Any:
    """Return the composed tree-store guard (feature 110's standing audit).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-tree-store-guard`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the guard resolves its path on first
    use, so asking for the component is always safe — and the audit it is
    held for opens the store read-only, so the first ``audit()`` is as safe
    as the asking.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
