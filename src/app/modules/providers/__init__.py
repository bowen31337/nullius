"""The providers module — app-level entrypoint for the providers workspace member.

The implementation lives in the ``providers`` workspace member
(``packages/providers``, import name ``providers``), which self-registers with
the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its ``@register``
decorator fires, and ``create_app()`` composes feature 203's
:class:`~providers.AgentModelPins` store, bound to the ``DATABASE_URL`` the
tree store lives at.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/providers/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for the
component, and a module that cannot reach it (member not scanned, workspace
empty) returns ``None`` rather than failing import, mirroring the factory's own
"degrade, don't break" stance toward absent components.

The seat answers exactly one question — *what is the composed authoring-model
pin store?* — and deliberately does not re-export the triple, the answer
record, the error vocabulary or the parse.  The distinction is worth stating
plainly here, because this member registers **two** components and the seat
exposes the one that is a service: feature 192's provider interface
(``providers``) is a contract and a set of records whose builder contributes
``None``, so there is nothing composed to hand back and a caller holding the
interface imports it from the member directly.  A seat that re-exported
:class:`~providers.ModelPin` or :class:`~providers.Provider` would be a second
spelling of the member's surface that has to be kept in sync with the first,
and it would invite a caller to reach the *interface* by way of the
application, where the only thing the application actually holds is the store.

Like the ``cost-model``, ``feature-store`` and ``signal-agent`` seats, this
directory's name is also a valid dotted import path, so it is reached either as
``importlib.import_module("app.modules.providers")`` (the shape the factory uses
for every seat) or as a plain ``from app.modules.providers import
agent_model_pins_component`` — the way ``app.modules.contract`` and
``app.modules.bootstrap`` are reached.  Both spellings name this module and
nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from providers import AgentModelPins

__all__ = ["COMPONENT_NAME", "agent_model_pins_component"]

#: The component name the providers member registers its pin store under.
#: Kept here so anything asking the composed application for feature 203's
#: store — by way of the app package, not the member — shares one spelling.
#: The two are pinned against each other by the member's own suite rather than
#: by a shared constant, because a constant the seat imports from the member
#: would be the import this seat exists to avoid.
COMPONENT_NAME = "agent-model-pins"


def agent_model_pins_component(app: Application | None = None) -> AgentModelPins | Any:
    """Return the composed authoring-model pin store (feature 203's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``agent-model-pins`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.

    A composed application carries this component as ``None`` whenever nothing
    names a relational store, and **that ``None`` is not the same fact as this
    function's**.  The component's ``None`` says *a store was built and there
    was no ``DATABASE_URL`` to point it at*; this function's says *no
    ``agent-model-pins`` component was registered at all*.  Both are refusals to
    persist — a caller that must record feature 203's triple has to treat either
    as one — but they name different repairs (configure the store, or scan the
    member), so a caller that needs them apart reads the application's
    components rather than this one call.  What this function must never be read
    as is *"this node has no authoring model"*: that is a question about a node,
    and the store answers it.

    Construction touches no file and no database: asking for the component is
    always safe, and the path is resolved at the first ``persist`` or ``load``.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
