"""The legal theme gate's seat in the ``app`` namespace — feature 212.

app_spec.xml, "Hypothesis Authoring Agent", feature 212: *System rejects a
proposal whose theme root falls outside the configured legal set, which
returns an illegal_theme error message.*  The law lives in
:mod:`signal_agent._themes`; this module is how the app package reaches the
composed gate without importing the member at module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring
law?*; this module answers the same shape of question for the member's second
component: *what is the composed legal theme gate?*  A seat per component
rather than one accessor learning a second key, the convention
:mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the
two components answer different questions on different lifecycles — the
authoring law resolves the contract member's ABI lazily and needs no
configuration, while this one carries a compiled set read from a committed
artifact at build time — and a caller that wants the theme gate should not
have to hold the authoring law to get it.

**This seat's ``None`` is a statement about composition.**  It means *no
``signal-agent-themes`` component was registered* — the member was not
scanned, or the workspace is empty.  It is **not** the gate's own answer about
a theme: a composed gate that admits nothing is a *present* component that
refuses every proposal, and reading this ``None`` as "the agent opened in an
illegal theme" would collapse a deployment problem into a research result.
The two are distinguishable exactly the way feature 205's seat keeps them
apart, and it matters more here: an operator who cannot tell "the set is
empty" from "the theme is illegal" cannot tell whether to widen the document
or re-prompt the agent.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the set, the admission
value, the reasons or the compiler: a caller who has the gate reaches
``gate.admit(root)`` for feature 212's verdict, ``gate.legal()`` for PRD §9.3's
slugs and ``gate.covers(root)`` for the read side, and a second spelling of
those here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed legal theme gate?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import SignalThemeGate

__all__ = ["COMPONENT_NAME", "theme_gate_component"]

#: The component name the signal-agent member registers its legal theme gate
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-themes"


def theme_gate_component(app: Application | None = None) -> SignalThemeGate | Any:
    """Return the composed legal theme gate (feature 212's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-themes`` component is registered —
    an absent component is a discoverable state, not an exception, exactly as
    an empty workspace is for the factory.

    Construction touches nothing an operator has to configure: the committed
    legal theme set ships inside the member's package, so unlike the
    database-backed stores in this workspace there is no unconfigured state
    for ``None`` to describe beyond the member not having been scanned at all.
    Holding the handle computes nothing, and the first ``admit`` is where a
    proposal's theme is judged.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
