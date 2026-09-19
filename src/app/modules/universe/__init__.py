"""The universe module — app-level entrypoint for the universe workspace member.

The implementation lives in the ``universe`` workspace member
(``packages/universe``, import name ``universe``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` builds a :class:`~universe.service.UniverseService` bound
to ``DATABASE_URL`` and the ``NULLIUS_UNIVERSE_*`` configuration.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/universe/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import
time. Composition stays the factory's job — this module only asks the
factory for the component, and a module that cannot reach it (member not
scanned, workspace empty) returns ``None`` rather than failing import,
mirroring the factory's own "degrade, don't break" stance toward absent
components.

The seat is where the survivorship audit report (feature 44) is read out of
the composed system: the caller asks for the component and the component
already knows how to emit the report — one line per historical window
carrying the window bounds and the delisted-symbol count
(``service.render_survivorship_report()``). The survivorship gate
(feature 45) rides the same composed service without a seat API of its
own: a build whose window is known to contain delistings yet counts
``delisted=0`` is refused by ``service.persist()`` itself, so composing
the component is enough to be protected. Like the snapshot seat, this
module answers exactly one question — *what is the composed universe
component?* — and does not re-export the audit, its rendering, the gate
or the point-in-time resolution: a caller who has the service can reach
``service.resolve(when)`` for the symbols tradable as of a decision time
— *then*, never now; the resolution feature 42 owns —
``service.survivorship_audit()`` for the counted, listed names, the
rendering for the report lines, and ``service.survivorship_gaps()`` for
the windows the gate would refuse, and a second spelling of those APIs
here would be a second thing to keep in sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from universe import UniverseService

__all__ = ["COMPONENT_NAME", "universe_component"]

#: The component name the universe member registers under. Kept here so
#: anything asking the composed application for the universe component — by
#: way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "universe"


def universe_component(app: Application | None = None) -> UniverseService | Any:
    """Return the composed universe component (the universe service).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``universe`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
