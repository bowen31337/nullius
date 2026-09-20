"""The POST /target route's seat in the ``app`` package namespace — feature 112.

app_spec.xml, "Null Oracle & Planted Nulls", feature 112: *System exposes
POST /target accepting node_id, campaign_id, depth, horizon, symbols and a
date range, which returns 200 for a known node.*  The route lives in
:mod:`nulloracle.target`, and this module is how the app package reaches
the composed endpoint without importing the member at module scope.

Feature 109's seat (:mod:`app.modules.nulloracle`) answers *what is the
composed null sidecar?*, feature 123's seat
(:mod:`app.modules.nulloracle.ksguard`) answers *what is the composed guard
journal?*, feature 124's seat (:mod:`app.modules.nulloracle.verdict`)
answers *what is the composed verdict?*, feature 117's seat
(:mod:`app.modules.nulloracle.phi`) answers *what is the composed fraction
store?*, feature 119's seat (:mod:`app.modules.nulloracle.flipdepth`)
answers *what is the composed flip-depth store?*, and feature 121's seat
(:mod:`app.modules.nulloracle.resolution`) answers *what is the composed
Type-D oracle?*; this one answers the same shape of question for the
member's seventh component: *what is the composed POST /target route?* —
the endpoint §6.1's null_gate step asks when it needs the target series a
node's world serves.

**A seventh seat, beside the other six.**  ``src/app/modules/nulloracle/``
was a single ``__init__.py`` while the member contributed one component.
It now contributes seven — the sidecar, the guard journal, the verdict,
the fraction, the flip depth, the Type-D resolution and the route — and
the seven are different things on different lifecycles (§7.1's sealed
file, feature 123's relational store, feature 124's verdict store, feature
117's fraction store, feature 119's flip-depth store, feature 121's
read-side oracle and feature 112's server over the sidecar), so the route
gets its own module beside the other six rather than a seventh accessor
crowded into any of them.  The older seats' promises are untouched: a
caller that only wants the sidecar, the guard, the verdict, the fraction,
the flip depth or the resolution never imports this file.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is
none, mirroring the factory's own "degrade, don't break" stance toward
absent components.  It deliberately does **not** re-export the request and
response records or the route constant: a caller who has the endpoint
reaches ``post`` on it, and a second spelling here would be a second thing
to keep in sync.  The one question this module answers is *what is the
composed POST /target route?*

Where the composed route is ``None``, that is a statement about the
deployment, not an error: nothing named ``NULL_SIDECAR_PATH``, ``LAKE_ROOT``
or a workspace root to locate the file, or no key reference to open it
with, so there is no sidecar to answer from.  A caller that needs the
route must not treat ``None`` as "every node is unknown" — those are
different facts, and the member's own error taxonomy is built around
keeping them apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from nulloracle import TargetEndpoint

__all__ = ["COMPONENT_NAME", "target_route_component"]

#: The component name the nulloracle member registers its POST /target
#: route under.  Kept here as well as in the member — each seat spells its
#: own :data:`COMPONENT_NAME` twice for the same reason — so the two cannot
#: drift apart silently, and ``test_target_component.py`` asserts they
#: agree.  The ``target-`` prefix sorts after the ``ks-*``, ``null-*`` and
#: ``plan-*`` families and before the ``true-ir-*`` and ``type-*`` families
#: in the name-sorted ``app.order``, so feature 123's
#: guard-immediately-after-sidecar adjacency is untouched (the same
#: ordering fact the resolution's and the flip depth's seats state for
#: their prefixes).
COMPONENT_NAME = "nulloracle-target-route"


def target_route_component(app: Application | None = None) -> TargetEndpoint | Any:
    """Return the composed POST /target route (feature 112's endpoint).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app`.  Returns ``None`` when no
    ``nulloracle-target-route`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an
    unset ``NULL_SIDECAR_PATH`` is for the member's own builder.

    Construction touches no file: asking for the component is always safe,
    and the sidecar it answers from is opened at the first ``post``.  That
    laziness is the reason a composed application can carry this route in
    a process that is not the one service account — holding the endpoint
    opens nothing, and the read that would open it is where §7.1's
    permission rule bites.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
