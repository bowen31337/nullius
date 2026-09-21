"""The dead-territory gate's seat in the ``app`` namespace — feature 213.

app_spec.xml, "Hypothesis Authoring Agent", feature 213: *System rejects any
root opening in structurally dead territory such as sub-30-minute
liquidity-taking strategies.*  The law lives in
:mod:`signal_agent._dead_territory`; this module is how the app package reaches
the composed gate without importing the member at module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring
law?*; feature 212's seat (:mod:`app.modules.signal-agent.themes`) answers it
for the legal theme gate; this module answers the same shape of question for
the member's third component: *what is the composed dead-territory gate?*  A
seat per component rather than one accessor learning a third key, the
convention :mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the
three components answer different questions on different lifecycles — the
authoring law resolves the contract member's ABI lazily, the theme gate carries
a compiled allowlist read from a committed artifact, and this one carries a
compiled denylist read from a different committed artifact — and a caller that
wants the dead-territory gate should not have to hold the other two to get it.

**This seat's ``None`` is a statement about composition.**  It means *no
``signal-agent-dead-territory`` component was registered* — the member was not
scanned, or the workspace is empty.  It is **not** the gate's own answer about
a theme: a composed gate that refuses every proposal (an empty denylist, which
fails open) is a *present* component admitting every proposal, and reading this
``None`` as "the agent opened in dead territory" would collapse a deployment
problem into a research result.  The two are distinguishable exactly the way
feature 212's seat keeps them apart, and it matters here too: an operator who
cannot tell "the denylist is empty" from "the mechanism is live" cannot tell
whether to widen the document or re-prompt the agent.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the list, the verdict
value, the reasons or the compiler: a caller who has the gate reaches
``gate.admit(root)`` for feature 213's verdict, ``gate.dead()`` for PRD §9.4's
mechanisms and ``gate.covers(root)`` for the read side, and a second spelling
of those here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed dead-territory gate?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import DeadTerritoryGate

__all__ = ["COMPONENT_NAME", "dead_territory_component"]

#: The component name the signal-agent member registers its dead-territory gate
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-dead-territory"


def dead_territory_component(
    app: Application | None = None,
) -> DeadTerritoryGate | Any:
    """Return the composed dead-territory gate (feature 213's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-dead-territory`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    Construction touches nothing an operator has to configure: the committed
    dead-territory list ships inside the member's package, so unlike the
    database-backed stores in this workspace there is no unconfigured state
    for ``None`` to describe beyond the member not having been scanned at all.
    Holding the handle computes nothing, and the first ``admit`` is where a
    proposal's mechanism is judged.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
