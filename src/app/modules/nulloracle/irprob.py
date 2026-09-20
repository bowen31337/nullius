"""The true-IR flip probability's seat in the ``app`` namespace — feature 120.

app_spec.xml, "Null Oracle & Planted Nulls", feature 120: *System draws the
geometric flip depth with probability decreasing in the parent true information
ratio, which returns a distribution varying across campaigns.*  The map and its
store live in :mod:`nulloracle.irprob`, and this module is how the app package
reaches the composed store without importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the composed
null sidecar?*, feature 123's (:mod:`app.modules.nulloracle.ksguard`) *what is
the composed guard journal?*, feature 124's
(:mod:`app.modules.nulloracle.verdict`) *what is the composed verdict?*, feature
117's (:mod:`app.modules.nulloracle.phi`) *what is the composed fraction store?*
and feature 119's (:mod:`app.modules.nulloracle.flipdepth`) *what is the composed
flip-depth store?*; this one answers the same shape of question for the member's
seventh component: *what is the composed true-IR flip-depth store?*

**A seventh seat, beside the other six.**  ``src/app/modules/nulloracle/`` was a
single ``__init__.py`` while the member contributed one component.  It now
contributes seven — the sidecar, the guard journal, the verdict, the fraction,
the flip depth, the Type-D resolution and this — and they are different things
on different lifecycles (§7.1's sealed file, feature 123's relational store,
feature 124's verdict store, feature 117's fraction store, feature 119's
flip-depth store, feature 121's oracle and feature 120's probability), so the
true-IR flip depth gets its own module beside the others rather than a seventh
accessor crowded into any of them.  The older seats' promises are untouched:
``app.modules.nulloracle`` still exports exactly :data:`COMPONENT_NAME` and
:func:`null_sidecar_component`, and the guard, verdict, fraction, flip depth and
resolution seats still export exactly their own ``COMPONENT_NAME`` and accessor;
a caller that only wants the sidecar, the guard, the verdict, the fraction, the
flip depth or the resolution never imports this file.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the map, the store class, the
distribution value or the module-level spelling: a caller who has the store
reaches ``draw(...)``, ``distribution(...)`` and ``distribution_for_node(...)``
on it, and a second spelling here would be a second thing to keep in sync.  The
one question this module answers is *what is the composed true-IR flip-depth
store?*

Where the composed store is ``None``, that is a statement about the deployment,
not an error: nothing named ``DATABASE_URL``, so there is no relational store to
compose.  A caller that needs one must not treat ``None`` as "the branch's depth
is zero" — those are different facts, and the member's error taxonomy is built
around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import TrueIRFlipDepth

__all__ = ["COMPONENT_NAME", "true_ir_flip_depth_component"]

#: The component name the nulloracle member registers its true-IR flip-depth
#: store under.  Kept here as well as in the member — the member's other seats
#: spell their own :data:`COMPONENT_NAME` twice for the same reason — so the two
#: cannot drift apart silently, and ``test_app_module.py`` asserts they agree.
#: The ``true-ir-`` prefix sorts after the ``ks-*``, ``null-*`` and ``type-d-*``
#: families in the name-sorted ``app.order``, so feature 123's
#: guard-immediately-after-sidecar order stays intact.
COMPONENT_NAME = "nulloracle-true-ir-flip-depth"


def true_ir_flip_depth_component(app: Application | None = None) -> TrueIRFlipDepth | Any:
    """Return the composed true-IR flip-depth store (feature 120's store).

    With ``app`` given, the component is read from that application; without it,
    the application is composed first via :func:`app.module_loader.create_app`.
    Returns ``None`` when no ``nulloracle-true-ir-flip-depth`` component is
    registered — an absent component is a discoverable state, not an exception,
    exactly as an unset ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the store resolves its path on first use,
    so asking for the component is always safe and the first ``draw()`` or
    ``distribution_for_node()`` is where the file is actually opened.  The pure
    ``distribution()`` call never opens it at all — a campaign's shift is a
    function of its id — so a caller reporting *what this campaign draws* can do
    so with no relational store composed.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
