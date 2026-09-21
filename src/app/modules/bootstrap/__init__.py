"""The bootstrap module — app-level entrypoint for the bootstrap workspace member.

The implementation lives in the ``bootstrap`` workspace member
(``packages/bootstrap``, import name ``bootstrap``), which self-registers
with the application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its
``@register`` decorator fires, and ``create_app()`` builds a
:class:`~bootstrap.HyperparameterWorld` (app_spec.xml feature 181:
*"System exposes a hyperparameter search world over a fixed model and
dataset, which returns a ground-truth score per node"*, the first of
docs/nullius-tech-architecture.md §10.6's three authored domains).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/bootstrap/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory for
the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring the
factory's own "degrade, don't break" stance toward absent components.

The helper below is deliberately the *composition* accessor and nothing
more.  It does not re-export the label, the lattice or the codec: a caller
who has the world reaches ``world.label(node_id)`` for the feature's
ground-truth score, ``world.legal_moves(node_id)`` and
``world.canonical_node()`` for the walk §10.6.1's ``question.*`` API
describes, and ``world.setting(node_id)`` for a node's coordinates — and a
second spelling of those APIs here would be a second thing to keep in sync.
This module answers exactly one question — *what is the composed bootstrap
world?* — so the features in this category that need one (the identical
policy interface of 184, the ground-truth calibration of 189, the
ported-world adapter of 190-191) can ask it without importing the member
directly.

Where the composed world is ``None``, that is a statement about the
deployment, not an error: the member was not scanned, or the workspace is
empty, so there is no world to compose.  A caller that needs one must not
treat ``None`` as "this pool has no bootstrap worlds" — those are different
facts, and §10.6's *"Report the two pools separately"* is precisely the
rule that keeps them apart: an absent component is a statement about
composition, while an empty bootstrap pool is a statement about what has
been authored (feature 188's count, feature 186's independent tally).

**A second seat grew beside this one.**  Feature 188 — *"System persists
40 to 50 generated bootstrap worlds into the replay pool on demand"* —
gave the member a second component, the pool, and this directory grew
the same way ``app.modules.tripwires`` grew for features 131 and 132: a
sibling module (:mod:`app.modules.bootstrap.pool`) holds the pool's own
seat, answering *what is the composed bootstrap pool?* while this module
goes on answering *what is the composed bootstrap world?*.  Two seats
rather than one accessor with two keys, because the two components are
different things on different lifecycles — the world is ready the
instant it is built and never degrades, while the pool is a deployment
state (``DATABASE_URL``) that may legitimately be ``None`` — and a
caller that wants the world never pays for the pool's deployment state.
This module's exports are untouched by the growth: still exactly
:data:`COMPONENT_NAME` and :func:`hyperparameter_world_component`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from bootstrap import HyperparameterWorld

__all__ = ["COMPONENT_NAME", "hyperparameter_world_component"]

#: The component name the bootstrap member registers under.  Kept here so
#: anything asking the composed application for the world — by way of the
#: app package, not the member — shares one spelling.
COMPONENT_NAME = "bootstrap"


def hyperparameter_world_component(
    app: Application | None = None,
) -> HyperparameterWorld | Any:
    """Return the composed hyperparameter world (feature 181's world).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``bootstrap`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    Construction touches nothing: asking for the component is always safe,
    and the world's dataset is generated on the first
    ``label()`` and not before.  That laziness is the reason a composed
    application can carry this component in a process that never labels a
    node — holding the handle computes nothing, and the first label is
    where the world's arithmetic begins.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
