"""The verdict's seat in the ``app`` package namespace — feature 124.

app_spec.xml, "Null Oracle & Planted Nulls", feature 124: *System persists a
campaign calibration_status of VOID when the KS p-value falls below 0.05,
which halts dreaming and excludes the campaign from the pool.*  The verdict —
§7.4's ``p < 0.05`` comparison and the ``VOID`` it sets — lives in
:mod:`nulloracle.verdict`, and this module is how the app package reaches the
composed verdict store without importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?* and feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*; this one answers the same shape of question for the member's third
component: *what is the composed verdict store?*

**A third seat, beside the other two.**  ``src/app/modules/nulloracle/`` was a
single ``__init__.py`` while the member contributed one component.  It now
contributes three — the sidecar, the guard journal and the verdict — and the
three are different things on different lifecycles (§7.1's sealed file,
feature 123's relational store, and feature 124's verdict store), so the
verdict gets its own module beside the other two rather than a third accessor
crowded into either.  The older seats' promises are untouched:
``app.modules.nulloracle`` still exports exactly :data:`COMPONENT_NAME` and
:func:`null_sidecar_component`, and ``app.modules.nulloracle.ksguard`` still
exports exactly its ``COMPONENT_NAME`` and :func:`ks_guard_component`; a caller
that only wants the sidecar or the guard never imports this file.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the store class, the
threshold or the verdict: a caller who has the store reaches
``verdict.void_if_detectable(...)`` and ``verdict.load(...)`` on it, and a
second spelling here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed verdict store?*

Where the composed store is ``None``, that is a statement about the
deployment, not an error: nothing named ``DATABASE_URL``, so there is no
relational store to compose.  A caller that needs one must not treat ``None``
as "the campaign was judged and left calibrated" — those are different facts,
and the member's error taxonomy is built around keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import CampaignVerdict

__all__ = ["COMPONENT_NAME", "verdict_component"]

#: The component name the nulloracle member registers its verdict store under.
#: Kept here as well as in the member — the member's seat spells its own
#: :data:`COMPONENT_NAME` twice for the same reason — so the two cannot drift
#: apart silently, and ``test_app_module.py`` asserts they agree.
COMPONENT_NAME = "nulloracle-ks-verdict"


def verdict_component(app: Application | None = None) -> CampaignVerdict | Any:
    """Return the composed verdict store (feature 124's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-ks-verdict`` component is registered — an absent component is
    a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` is for the member's own builder.

    Construction touches no database: the store resolves its path on first
    use, so asking for the component is always safe and the first
    ``void_if_detectable()`` or ``load()`` is where the file is actually
    opened.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
