"""The canary module — app-level entrypoint for the canary workspace member.

The implementation lives in the ``canary`` workspace member
(``packages/canary``, import name ``canary``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME`
— scanning the workspace imports it, its ``@register`` decorator fires,
and ``create_app()`` builds a :class:`~canary.CanaryService` that
resolves the evaluation containers :data:`canary.IMAGE_ENV_VARS` names
from the environment the composition runs in.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/canary/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import
time. Composition stays the factory's job — this module only asks the
factory for the component, and a module that cannot reach it (member
not scanned, workspace empty) returns ``None`` rather than failing
import, mirroring the factory's own "degrade, don't break" stance
toward absent components.

One thing to be careful about, because this seat differs from its
siblings: the composed canary service is *lazily* swept. The factory
builds every registered component on every ``create_app()``, so a
builder that insisted on a pinned environment would take composition
down for every unrelated feature in a bare test process — which is why
:func:`~canary.build_canary_service` constructs a service that runs
the pin sweep on first use. The consequence for this seat is that a
non-``None`` component is not by itself proof the deployment is pinned:
``service.containers`` raises :class:`~canary.CanaryImageError` when
any declared container is unset, blank or tag-only, and that refusal
is the feature rather than a defect — a tag-only reference must never
be accepted (app_spec.xml feature 135, the plugin's root feature). A
caller that wants the check at startup instead builds strictly:
``CanaryService.from_env(strict=True)``.

This seat answers exactly one question — *what is the composed canary
component?* — and does not re-export the sweep's vocabulary: a caller
who has the service can reach ``service.containers`` for the pinned
set, and the role table (:data:`canary.IMAGE_ENV_VARS`) is imported
from the member, which is where the declaration lives. A second
spelling of either here would be a second thing to keep in sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from canary import CanaryService

__all__ = ["COMPONENT_NAME", "canary_component"]

#: The component name the canary member registers under. Kept here so
#: anything asking the composed application for the canary component —
#: by way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "canary"


def canary_component(app: Application | None = None) -> CanaryService | Any:
    """Return the composed canary component (the pin-sweep service).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace). Returns ``None`` when no ``canary`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory. A
    returned service may still be guarding an unpinned deployment: see
    the module docstring on why the refusal is deferred to first use
    rather than raised here.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
