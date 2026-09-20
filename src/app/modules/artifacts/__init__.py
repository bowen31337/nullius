"""The artifacts module — app-level entrypoint for the artifacts workspace member.

The implementation lives in the ``artifacts`` workspace member
(``packages/artifacts``, import name ``artifacts``), which
self-registers with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its
``@register`` decorator fires, and ``create_app()`` builds an
:class:`~artifacts.ArtifactStore` bound to the root ``ARTIFACT_ROOT``
names (app_spec.xml feature 169: one artifact directory per node,
keyed by ``campaign_id`` then ``node_id``, per
docs/nullius-tech-architecture.md §9.2).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/artifacts/``): it exposes the composed component
without making the ``app`` package depend on any workspace member at
import time.  Composition stays the factory's job — this module only
asks the factory for the component, and a module that cannot reach it
(member not scanned, workspace empty) returns ``None`` rather than
failing import, mirroring the factory's own "degrade, don't break"
stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing
more.  It does not re-export the write path, the listings or the
validation: a caller who has the store can reach ``store.write`` and
``store.commit`` for the staged persistence, ``store.node_directory``
for a node's one address, and ``store.read``/``store.files`` for the
read side §1 grants the replay engine — and a second spelling of those
APIs here would be a second thing to keep in sync.  This module answers
exactly one question — *what is the composed artifact store?* — so the
features in this category that need the store (the Parquet and JSON
artifacts of 170-173, the campaign loads of 174-180, the replay-path
read access of the dreaming features) can ask it without importing the
member directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from artifacts import ArtifactStore

__all__ = ["COMPONENT_NAME", "artifact_store_component"]

#: The component name the artifacts member registers under.  Kept here
#: so anything asking the composed application for the artifact store —
#: by way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "artifacts"


def artifact_store_component(app: Application | None = None) -> ArtifactStore | Any:
    """Return the composed artifact store (feature 169's directory store).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``artifacts`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
