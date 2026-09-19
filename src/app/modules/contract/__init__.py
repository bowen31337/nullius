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

This seat answers two questions, both about the market-window contract.  It
does not re-export :class:`~contract.MarketWindow` itself: the component
advertises the ABI by name (see :data:`contract.MARKET_WINDOW_ABI` for why —
a scanned package is imported under a synthetic module name, so a class
object handed across the scan seam is not the class a normal import yields).
A caller who wants the class imports it; a caller who wants the composed
system, or the window's accessor surface, asks here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from contract import (
        CONTRACT_VERSION,
        MARKET_WINDOW_ABI,
        inspect_accessors,
    )

__all__ = ["COMPONENT_NAME", "contract_component", "window_accessor_names"]

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


def window_accessor_names() -> tuple[str, ...]:
    """Return the MarketWindow's accessor names, asserting none takes a time.

    The app-namespace seat for feature 10: it calls
    :func:`contract.inspect_accessors`, which enumerates the window's public
    accessors and *raises* the moment one accepts a timestamp argument.  This
    returns the accessor names on success, so a caller learns both that the
    window's surface is free of a widening accessor and what that surface is.

    Unlike :func:`contract_component`, this does not degrade to ``None``: the
    window class is the boundary every signal is evaluated against, so an
    accessor that could widen it is a hard failure, not a discoverable absent
    state.  The member is imported lazily, exactly as the component seat
    already does, so importing this app module never pulls the member in.
    """
    from contract import inspect_accessors

    return inspect_accessors()
