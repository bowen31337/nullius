"""The snapshot module — app-level entrypoint for the snapshot workspace member.

The implementation lives in the ``snapshot`` workspace member
(``packages/snapshot``, import name ``snapshot``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` builds a
:class:`~snapshot.SnapshotService` bound to the lake ``LAKE_ROOT`` names.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/snapshot/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing more.
It does not re-export sealing or mounting: a caller who has the service can
reach ``service.mount(name)`` for the read-only mount of feature 34 and
``service.seal(...)`` for the seal of feature 30, and a second spelling of
those APIs here would be a second thing to keep in sync. This module answers
exactly one question — *what is the composed snapshot component?* — so the
evaluator-facing features of this category can ask it without importing the
member directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from snapshot import SnapshotService

__all__ = ["COMPONENT_NAME", "snapshot_component"]

#: The component name the snapshot member registers under.  Kept here so
#: anything asking the composed application for the snapshot component — by
#: way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "snapshot"


def snapshot_component(app: Application | None = None) -> SnapshotService | Any:
    """Return the composed snapshot component (the sealing service).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``snapshot`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
