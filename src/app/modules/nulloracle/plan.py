"""The planning gate's seat in the ``app`` package namespace — feature 122.

app_spec.xml, "Null Oracle & Planted Nulls", feature 122: *System rejects a
campaign plan that mixes Type-R and Type-D assignment within one tree, which
emits a heterogeneous_world error message.*  The plan value and the reviewing
store live in :mod:`nulloracle.plan`, and this module is how the app package
reaches the composed gate without importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*, feature 124's seat (:mod:`app.modules.nulloracle.verdict`)
answers *what is the composed verdict?*, feature 117's seat
(:mod:`app.modules.nulloracle.phi`) answers *what is the composed fraction
store?*, feature 119's seat (:mod:`app.modules.nulloracle.flipdepth`)
answers *what is the composed flip-depth store?*, feature 121's seat
(:mod:`app.modules.nulloracle.resolution`) answers *what is the composed
Type-D oracle?*, feature 120's seat (:mod:`app.modules.nulloracle.irprob`)
answers *what is the composed true-IR store?* and feature 118's seat
(:mod:`app.modules.nulloracle.selection`) answers *what is the composed
Type-R selection store?*; this one answers the same shape of question for
the member's ninth component: *what is the composed planning gate?*

**A ninth seat, beside the other eight.**  ``src/app/modules/nulloracle/``
was a single ``__init__.py`` while the member contributed one component.  It
now contributes nine — the sidecar, the guard journal, the verdict, the
fraction, the flip depth, the Type-D oracle, the true-IR flip probability,
the Type-R selection and this gate — and the nine are different things on
different lifecycles, so the gate gets its own module beside the other
eight rather than a ninth accessor crowded into any of them.  The older
seats' promises are untouched: a caller that only wants the sidecar, the
guard, the verdict, the fraction, the flip depth, the resolution, the
true-IR store or the selection never imports this file.

**Like the selection's seat, this one needs two things composed.**  Every
seat that answers for a single-sourced component resolves from one name —
a database URL or a sidecar location.  This seat's component, like feature
118's, needs *both*: the relational store the tree and its flip depths
live in, and §7.1's sealed sidecar the root selections live in (the one
artifact allowed to hold the null bit, feature 110).  A composed
application carries this component only where both resolve, and this
module's ``None`` means *one of the two is unconfigured* — never *the tree
is homogeneous*, which is a fact about a world and not about a deployment.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the plan value, the
gate class or the review: a caller who has the gate reaches
``gate.review(campaign_id)`` on it, and a second spelling here would be a
second thing to keep in sync.  The one question this module answers is
*what is the composed planning gate?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import CampaignPlanGate

__all__ = ["COMPONENT_NAME", "plan_gate_component"]

#: The component name the nulloracle member registers its planning gate
#: under.  Kept here as well as in the member — the member's seat spells its
#: own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and the member's component suite asserts they agree.
#: The ``plan-`` prefix is the family convention the selection's seat states:
#: it sorts after the ``ks-*`` and ``null-*`` families and before the
#: ``true-ir-*`` and ``type-*`` families in the name-sorted ``app.order``, so
#: feature 123's guard-immediately-after-sidecar adjacency stays intact.
COMPONENT_NAME = "nulloracle-plan-gate"


def plan_gate_component(app: Application | None = None) -> CampaignPlanGate | Any:
    """Return the composed planning gate (feature 122's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-plan-gate`` component is registered — an absent component is
    a discoverable state, not an exception, exactly as an unset
    ``DATABASE_URL`` (or an unresolvable sidecar) is for the member's own
    builder.

    Construction touches no database and no file: the gate resolves its path
    on first use and the sidecar opens nothing until the first ``review``,
    so asking for the component is always safe.  The read that would open
    the sidecar is where §7.1's permission rule bites — and where a mixed
    tree's ``heterogeneous_world`` refusal is pronounced.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
