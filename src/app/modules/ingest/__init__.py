"""The ingest module — app-level entrypoint for the ingest workspace member.

The implementation lives in the ``ingest`` workspace member
(``packages/ingest``, import name ``nullius_ingest``), which
self-registers with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its
``@register`` decorator fires, and ``create_app()`` builds an
:class:`~nullius_ingest.supervisor.IngestSupervisor` with one worker per
registered stream class.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/ingest/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the
factory for the component, and a module that cannot reach it (member
not scanned, workspace empty) returns ``None`` rather than failing
import, mirroring the factory's own "degrade, don't break" stance
toward absent components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nullius_ingest import IngestSupervisor

__all__ = ["COMPONENT_NAME", "ingest_component"]

#: The component name the ingest member registers under.  Kept here so
#: anything asking the composed application for the ingest component —
#: by way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "ingest"


def ingest_component(app: Application | None = None) -> IngestSupervisor | Any:
    """Return the composed ingest component (the supervisor).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``ingest`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
