"""The replay module — app-level entrypoint for the replay workspace member.

The implementation lives in the ``replay`` workspace member
(``packages/replay``, import name ``replay``), which self-registers with the
application factory under the component name :data:`COMPONENT_NAME` — scanning
the workspace imports it, its ``@register`` decorator fires, and
``create_app()`` composes the replay path's facade (app_spec.xml, "Replay
Engine", feature 245: *System rejects any attempt to generate a new child
during replay, because a stored tree reveals only recorded children*).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/replay/``): it exposes the composed component without making
the ``app`` package depend on any workspace member at import time.  Composition
stays the factory's job — this module only asks the factory for the component,
and a module that cannot reach it (member not scanned, workspace empty) returns
``None`` rather than failing import, mirroring the factory's own "degrade,
don't break" stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing more.
It does not re-export the transition, its verbs, the root set, the child lookup
or the tree resolution: a caller who has the engine calls
``engine.transition(tree)`` to open a walk, ``engine.over()`` to open one over
the deployment's own campaign, ``engine.tree()`` to resolve that campaign, and
the member's free functions (``replay_transition``, ``replay_roots``,
``recorded_child``) when it holds a tree already — and a second spelling of
those APIs here would be a second thing to keep in sync.  This module answers
exactly one question — *what is the composed replay component?* — so the
features in this category that need the replay path (246's and 247's dependency
refusals, 248's round loop, 251's resident-array reads, 252–255's latency and
score persistence) can ask it without importing the member directly.

**The seat is the app-namespace spelling of a name that carries a hyphen.**
The component name is ``replay`` and the spec's plugin is ``replay``, so the
seat's own module path is ``app.modules.replay`` — no hyphen to work around
here, unlike the ``app.modules.policy-runtime`` seat this member resolves a
campaign through.  Anything asking the composed application for the replay
component goes through this module rather than naming the member package, which
is what keeps the app package free of a workspace-member dependency.

Nothing here decides anything about a replay.  Feature 245's law — a stored
tree reveals only recorded children, and a replay that was handed a generator
is refused — is enforced by the member, at the seam the generator would arrive
through, and the composed component is a stateless facade over it.  A seat that
also validated a walk would be a second place for the law to hold, and the
first place it would stop being true.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from replay import ReplayEngine

__all__ = ["COMPONENT_NAME", "replay_component"]

#: The component name the replay member registers under.  Kept here so anything
#: asking the composed application for the replay path — by way of the app
#: package, not the member — shares one spelling.
COMPONENT_NAME = "replay"


def replay_component(app: Application | None = None) -> ReplayEngine | Any:
    """Return the composed replay component (feature 245's stateless facade).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``replay`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.

    Construction touches nothing: the member's builder returns a stateless
    facade and resolves no store, no tree and no file, so composing an
    application that carries this component costs composition nothing and the
    deployment's campaign is read only when a caller asks for it through
    ``component.tree()``.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
