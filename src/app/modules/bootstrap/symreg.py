"""The symbolic regression world's seat in the ``app`` namespace — feature 183.

app_spec.xml, "Bootstrap Worlds", feature 183: *System exposes a symbolic
regression world, which returns a ground-truth score against known target
expressions.*  The implementation lives in :mod:`bootstrap._symreg`; this
module is how the app package reaches the composed world without
importing the member at module scope.

The directory's growth now reads as a pattern.  Feature 181's seat
(:mod:`app.modules.bootstrap`) answers *what is the composed bootstrap
world?*; feature 188's pool seat (:mod:`app.modules.bootstrap.pool`)
answers *what is the composed bootstrap pool?*; this module answers the
same shape of question for the member's third component: *what is the
composed symbolic regression world?*  A seat per component rather than
one accessor learning a second key, the convention :mod:`tripwires`
states for its own seats, and for the same reason: the three components
are different things on different lifecycles — both worlds are ready the
instant they are built and never degrade, while the pool is a deployment
state that may legitimately be ``None`` — and a caller that wants a
world never pays for the pool's deployment state.

**This seat's ``None`` is the world seat's ``None``, not the pool's.**
It means *no ``bootstrap-symreg`` component was registered* — a
statement about composition (the member was not scanned, the workspace
is empty), never about the deployment: unlike the pool, this component
has no ``DATABASE_URL`` to be absent, so the two ``None``s of this
directory must not be read through each other.  A caller holding this
seat's ``None`` cannot label a symbolic node at all, exactly as a caller
holding the world seat's ``None`` cannot label a hyperparameter node —
and for the same reason must not mistake it for "no symreg worlds in the
pool", which is a statement about what has been authored (§10.6's
*"Report the two pools separately"*, the rule feature 186's census
keeps).

**Composition stays the factory's job.**  This module asks the factory
for the component and answers ``None`` — not an exception — when there
is none, mirroring the factory's own "degrade, don't break" stance
toward absent components.  It deliberately does **not** re-export the
target, the lattice, the codec or the question: a caller who has the
world reaches ``world.label(node_id)`` for the feature's ground-truth
score, ``world.target`` for the known expression it is scored against,
and ``bootstrap.symreg_question_for(world)`` for the policy-facing
question — and a second spelling of those here would be a second thing
to keep in sync.  The one question this module answers is *what is the
composed symbolic regression world?*

**Construction touches nothing.**  The world's whole configuration is
its seed; the builder allocates one object and the dataset is generated
on the first ``label()`` and not before — the same laziness the world
seat documents for the hyperparameter world, for the same reason:
holding the handle computes nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from bootstrap import SymbolicRegressionWorld

__all__ = ["COMPONENT_NAME", "symreg_world_component"]

#: The component name the bootstrap member registers its symbolic
#: regression world under.  Kept here as well as in the member — the
#: sibling seats spell their own names twice for the same reason, and
#: this directory's tests assert the two agree — so the two cannot drift
#: apart silently.
COMPONENT_NAME = "bootstrap-symreg"


def symreg_world_component(
    app: Application | None = None,
) -> SymbolicRegressionWorld | Any:
    """Return the composed symbolic regression world (feature 183's world).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``bootstrap-symreg`` component
    is registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    Construction touches nothing: asking for the component is always
    safe, the world's known target is drawn the moment the builder runs
    (one hash read, published whole), and the dataset is generated on
    the first ``label()`` and not before.  That laziness is the reason a
    composed application can carry this component in a process that
    never labels a node — holding the handle computes nothing.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
