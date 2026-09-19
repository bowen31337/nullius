"""The contract module — app-level entrypoint for the contract workspace member.

The implementation lives in the ``contract`` workspace member
(``packages/contract``, import name ``contract``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` composes the component: the ABI version constant plus the
``module:attribute`` name of :class:`contract.MarketWindow`, the Z0 window
every LLM-authored signal is evaluated against.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/contract/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

Like the window it exposes, this seat answers exactly one question — *what
is the composed contract component?* It does not re-export
:class:`~contract.MarketWindow` itself: the component advertises the ABI by
name (see :data:`contract.MARKET_WINDOW_ABI` for why — a scanned package is
imported under a synthetic module name, so a class object handed across the
scan seam is not the class a normal import yields). A caller who wants the
class imports it; a caller who wants the composed system asks here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from contract import CONTRACT_VERSION, MARKET_WINDOW_ABI

__all__ = ["COMPONENT_NAME", "contract_component"]

#: The component name the contract member registers under. Kept here so
#: anything asking the composed application for the market-window contract —
#: by way of the app package, not the member — shares one spelling.
COMPONENT_NAME = "contract"


def contract_component(app: Application | None = None) -> dict | Any:
    """Return the composed contract component (the market-window ABI record).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``contract`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
