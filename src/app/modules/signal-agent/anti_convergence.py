"""The anti-convergence gate's seat in the ``app`` namespace — feature 210.

app_spec.xml, "Hypothesis Authoring Agent", feature 210: *Agent applies an
explicit anti-convergence clause, so a tree never collapses into 400 parameter
tweaks of one indicator.*  The law lives in
:mod:`signal_agent._anti_convergence`; this module is how the app package
reaches the composed gate without importing the member at module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring law?*;
feature 212's seat (:mod:`app.modules.signal-agent.themes`) answers it for the
legal theme gate, feature 213's (:mod:`app.modules.signal-agent.dead_territory`)
for the dead-territory gate and feature 211's
(:mod:`app.modules.signal-agent.mechanism`) for the stated-mechanism law.  This
module answers the same shape of question for the member's fifth component:
*what is the composed anti-convergence gate?*  A seat per component rather than
one accessor learning a fifth key, the convention
:mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the five
components answer different questions on different lifecycles — the authoring
law resolves the contract member's ABI lazily, the theme gate carries a
compiled allowlist, the dead-territory gate a compiled denylist, the mechanism
law a store resolved from ``DATABASE_URL``, and this one a compiled *clause* —
and a caller that wants the anti-convergence gate should not have to hold the
other four to get it.

**This seat's ``None`` is a statement about composition.**  It means *no
``signal-agent-anti-convergence`` component was registered* — the member was not
scanned, or the workspace is empty.  It is **not** the gate's own answer about a
proposal or a prompt, and the distinction is load-bearing twice over here:

* a *present* gate whose clause artifact drifted fails **closed** on the prompt
  half — :meth:`~signal_agent.AntiConvergenceGate.carries` certifies no prompt
  while its own clause is unreadable — so "the campaign's prompt does not carry
  the clause" is an answer this seat's ``None`` must not be read as.  Reading it
  that way would collapse a deployment problem into a research finding, which is
  the collapse feature 212's seat already refuses;
* a *present* gate with an empty comparison set admits every proposal, because a
  campaign with no proposals yet has nowhere to have converged to.  An operator
  who read this ``None`` as "the tree converged" would be reading the absence of
  a component as feature 210's headline finding.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the clause, the verdict
value, the reasons or the compiler: a caller who has the gate reaches
``gate.admit(source, held)`` for feature 210's verdict, ``gate.text()`` for
PRD §C3's clause and ``gate.carries(prompt)`` for the read side, and a second
spelling of those here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed anti-convergence gate?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import AntiConvergenceGate

__all__ = ["COMPONENT_NAME", "anti_convergence_component"]

#: The component name the signal-agent member registers its anti-convergence
#: gate under.  Kept here as well as in the member — every seat in this
#: workspace spells its own name twice for the same reason — so the two cannot
#: drift apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-anti-convergence"


def anti_convergence_component(
    app: Application | None = None,
) -> AntiConvergenceGate | Any:
    """Return the composed anti-convergence gate (feature 210's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-anti-convergence`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    Construction touches nothing an operator has to configure: PRD §C3's clause
    ships inside the member's package, so unlike the database-backed stores in
    this workspace there is no unconfigured state for ``None`` to describe
    beyond the member not having been scanned at all.  Holding the handle
    computes nothing, and the first ``admit`` or ``carries`` is where a
    proposal's structure or a campaign's prompt is judged.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
