"""The policy-runtime module — app-level entrypoint for the policy-runtime workspace member.

The implementation lives in the ``policy-runtime`` workspace member
(``packages/policy-runtime``, import name ``policy_runtime``), which
self-registers with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its ``@register``
decorator fires, and ``create_app()`` composes the campaign tree the
deployment's artifact store holds (app_spec.xml feature 217: *System exposes
an observed accessor which returns a mapping of revealed node ids to
observations*, the read side of docs/nullius-tech-architecture.md §11's
identical ``question.*`` interface an exploration policy is handed during
replay).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/policy-runtime/``): it exposes the composed component
without making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the factory
for the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing more.
It does not re-export the tree, the node model, the observation or the
question: a caller who has the tree reaches
``policy_runtime.policy_question(tree)`` for the read-side adapter,
``tree.observed()`` for the revealed cells, and ``tree.reveal(node_id)`` for a
reveal — and a second spelling of those APIs here would be a second thing to
keep in sync.  This module answers exactly one question — *what is the
composed campaign tree?* — so the features in this category that need the
read-side interface (218's frontier, 219's meta, 220's probe, 222's commit)
can ask it without importing the member directly.

Feature 230 lives in the same member but is not reached through this seat: the
admission gate (:func:`policy_runtime.screen_policy`) is a pure static check
over a policy's source, with no store and no deployment state, so it is reached
directly from the member — ``from policy_runtime import screen_policy`` —
exactly the way feature 229's :func:`policy_runtime.plan_grid` is, rather than
through the composed application.  This module does not wrap it, because a
second spelling of a pure gate would be a second thing to keep in sync, and the
gate has no component to compose.

Where the composed tree is ``None``, that is a statement about the deployment,
not an error: the member was not scanned, or the workspace is empty, or the
deployment's artifact store holds no committed campaign, so there is no tree to
front.  A caller that needs one must not treat ``None`` as "this campaign has
no nodes" — those are different facts, and §10.2's prefix-only enforcement is
precisely the rule that keeps them apart: an absent component is a statement
about composition, while an empty campaign is a statement about what has been
authored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from policy_runtime import CampaignTree

__all__ = ["COMPONENT_NAME", "campaign_tree_component"]

#: The component name the policy-runtime member registers under.  Kept here so
#: anything asking the composed application for the campaign tree — by way of
#: the app package, not the member — shares one spelling.
COMPONENT_NAME = "policy-runtime"


def campaign_tree_component(
    app: Application | None = None,
) -> CampaignTree | Any:
    """Return the composed campaign tree (feature 217's read-side surface).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``policy-runtime`` component is registered — an
    absent component is a discoverable state, not an exception, exactly as an
    empty workspace is for the factory.

    Construction touches nothing: asking for the component is always safe, and
    the member's builder resolves the tree lazily from the deployment's
    artifact store, so composing an application that carries this component
    touches no disk and the tree is read only when a caller demands it.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
