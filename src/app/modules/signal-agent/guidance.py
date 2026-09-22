"""The prompt-guidance gate's seat in the ``app`` namespace — feature 208.

app_spec.xml, "Hypothesis Authoring Agent", feature 208: *System rejects
injecting summarized directional guidance into the prompt, because prose
priors over-constrain the search space.*  The law lives in
:mod:`signal_agent._guidance`; this module is how the app package reaches the
composed law without importing the member at module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring law?*;
feature 212's seat (:mod:`app.modules.signal-agent.themes`) answers it for the
legal theme gate, feature 213's (:mod:`app.modules.signal-agent.dead_territory`)
for the dead-territory gate, feature 211's
(:mod:`app.modules.signal-agent.mechanism`) for the stated-mechanism law,
feature 210's (:mod:`app.modules.signal-agent.anti_convergence`) for the
anti-convergence gate, feature 209's
(:mod:`app.modules.signal-agent.diagnosis`) for the mechanism diagnosis and
feature 206's (:mod:`app.modules.signal-agent.history`) for the proposal
history.  This module answers the same shape of question for the member's
eighth component: *what is the composed prompt-guidance gate?*  A seat per
component rather than one accessor learning an eighth key, the convention
:mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the
eight components answer different questions on different lifecycles — the
authoring law resolves the contract member's ABI lazily, three gates carry a
compiled committed document, the mechanism law carries a store resolved from
``DATABASE_URL``, and the diagnosis, history and guidance laws carry nothing at
all — and a caller that wants the guidance judgment should not have to hold
the other seven to get it.

**This seat's ``None`` is a statement about composition.**  It means *no
``signal-agent-guidance`` component was registered* — the member was not
scanned, or the workspace is empty.  It is **not** the law's own answer about a
round's prompt, and here that distinction is sharp in a particular way: the
law's two answers are *the prompt is unguided* and *it carries injected
guidance*, and a caller that read this seat's ``None`` as "the prompt is
unguided" would ship a prompt nobody screened — which is PRD §C3's *"most
implementations get it backwards"* arriving through the app package's own
seam — while one that read it as "it carries guidance" would block a round on
the strength of a component that is not there at all.  Both are the collapse
:mod:`app.modules.signal-agent.history` refuses for its own verdict,
restated here: the verdict is the law's own returned value —
``guidance.admit(prompt)`` — and never this ``None``.  The ``None`` is not a
third answer either, because the gate's refusal paths are the law's
(:class:`~signal_agent.InjectedGuidanceError` and its sentence), not the
seat's.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the verdict value, the
reasons, the codes or the parts an admitted prompt carries: a caller who has
the law reaches ``guidance.admit(prompt)`` for feature 208's verdict,
``guidance.unguided(prompt)`` for the monitoring read and ``guidance.require``
for the exception, and a second spelling of those here would be a second thing
to keep in sync.  The one question this module answers is *what is the
composed prompt-guidance gate?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import PromptGuidanceGate

__all__ = ["COMPONENT_NAME", "prompt_guidance_component"]

#: The component name the signal-agent member registers feature 208's gate
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-guidance"


def prompt_guidance_component(
    app: Application | None = None,
) -> PromptGuidanceGate | Any:
    """Return the composed prompt-guidance gate (feature 208's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-guidance`` component is registered
    — an absent component is a discoverable state, not an exception, exactly as
    an empty workspace is for the factory.

    Construction touches nothing an operator has to configure and reads no
    artifact: feature 208's gate compiles no committed document and consults no
    environment — what counts as injected guidance is a declaration the
    prompt's own parts carry — so unlike the database-backed stores and the
    three artifact-backed gates in this workspace there is no unconfigured or
    degraded state for ``None`` to describe beyond the member not having been
    scanned at all.  Holding the handle computes nothing, and the first
    ``admit`` is where a round's prompt is judged.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
