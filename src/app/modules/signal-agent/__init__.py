"""The signal-agent module — app-level entrypoint for the signal-agent member.

The implementation lives in the ``signal-agent`` workspace member
(``packages/signal-agent``, import name ``signal_agent``), which
self-registers with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its ``@register``
decorator fires, and ``create_app()`` composes feature 205's law: the
:class:`~signal_agent.SignalContract` that judges whether an agent-authored
proposal is a signal function conforming to the declared contract, and hands
back the exact source the sandbox executes.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/signal-agent/``): it exposes the composed component
without making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the factory
for the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

Like the ``cost-model`` and ``feature-store`` seats, this directory's name
carries a hyphen and so is not a valid dotted import path; it is reached the
way the factory reaches such a package —
``importlib.import_module("app.modules.signal-agent")``.

The seat answers exactly one question — *what is the composed signal-agent
law?* — and does not re-export the adoption value, the reasons, the error
vocabulary or the declaration builder: a caller who has the law calls
``law.adopt(source)`` for feature 205's verdict, ``law.declaration()`` for the
facts an agent is asked to write against and
``law.signature()``/``law.validate(source)`` for the ABI itself, and a second
spelling of those here would be a second thing to keep in sync.  What the seat
adds is the one thing a caller *cannot* get from the member without importing
it: the composed component, reached by way of the application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import SignalContract

__all__ = ["COMPONENT_NAME", "signal_agent_component"]

#: The component name the signal-agent member registers under.  Kept here so
#: anything asking the composed application for the authoring law — by way of
#: the app package, not the member — shares one spelling.
COMPONENT_NAME = "signal-agent"


def signal_agent_component(app: Application | None = None) -> SignalContract | Any:
    """Return the composed signal-agent law (feature 205's contract seam).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.

    Construction touches nothing, so asking for the component is always safe:
    the law is stateless and the declared ABI is read out of the contract
    member on the first question asked of it, not when the builder runs.  The
    one thing this ``None`` must not be read as is "no signal was adopted" —
    it is a statement about *composition* (the member was not scanned, the
    workspace is empty), never about a proposal, and the verdict on a proposal
    is the law's own returned value rather than this function's.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
