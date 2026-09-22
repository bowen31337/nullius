"""The mechanism diagnosis's seat in the ``app`` namespace — feature 209.

app_spec.xml, "Hypothesis Authoring Agent", feature 209: *Agent distinguishes a
flawed core mechanism from a sound idea undermined by a located bug, which
returns a retry decision for only the second case.*  The law lives in
:mod:`signal_agent._diagnosis`; this module is how the app package reaches the
composed law without importing the member at module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring law?*;
feature 212's seat (:mod:`app.modules.signal-agent.themes`) answers it for the
legal theme gate, feature 213's (:mod:`app.modules.signal-agent.dead_territory`)
for the dead-territory gate, feature 211's
(:mod:`app.modules.signal-agent.mechanism`) for the stated-mechanism law and
feature 210's (:mod:`app.modules.signal-agent.anti_convergence`) for the
anti-convergence gate.  This module answers the same shape of question for the
member's sixth component: *what is the composed mechanism diagnosis?*  A seat
per component rather than one accessor learning a sixth key, the convention
:mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the six
components answer different questions on different lifecycles — the authoring
law resolves the contract member's ABI lazily, the theme and dead-territory and
anti-convergence gates each carry a compiled committed document, the mechanism
law carries a store resolved from ``DATABASE_URL``, and this one carries
nothing at all — and a caller that wants the diagnosis should not have to hold
the other five to get it.

**This seat's ``None`` is a statement about composition.**  It means *no
``signal-agent-diagnosis`` component was registered* — the member was not
scanned, or the workspace is empty.  It is **not** the law's own answer about a
branch, and here that distinction is the whole feature.  The law's two answers
are *retry* and *do not retry*, and an operator that read this seat's ``None``
as "the mechanism is flawed" would close a branch nobody diagnosed — while one
that read it as "retry" would spend a trial charge on the strength of a
component that is not there at all.  Both are the collapse
:mod:`app.modules.signal-agent.dead_territory` and
:mod:`app.modules.signal-agent.anti_convergence` each refuse for their own
answer, restated for a decision rather than a verdict: the decision is the
law's own returned value — ``diagnosis.retry(source, complaints)`` — and never
this ``None``.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the verdict value, the
located defect, the reasons or the resolution rule: a caller who has the law
reaches ``diagnosis.diagnose(source, complaints)`` for feature 209's verdict,
``diagnosis.require(...)`` for the exception and the :class:`LocatedDefect`
whose ``source_line`` is the proposal verbatim, and
``diagnosis.locate(source, line)`` for the read side, and a second spelling of
those here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed mechanism diagnosis?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import MechanismDiagnosis

__all__ = ["COMPONENT_NAME", "mechanism_diagnosis_component"]

#: The component name the signal-agent member registers feature 209's law
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-diagnosis"


def mechanism_diagnosis_component(
    app: Application | None = None,
) -> MechanismDiagnosis | Any:
    """Return the composed mechanism diagnosis (feature 209's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-diagnosis`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    Construction touches nothing an operator has to configure and reads no
    artifact: feature 209's law compiles no committed document and consults no
    environment — what counts as a located bug is a fact about the proposal
    handed in — so unlike the database-backed stores and the three
    artifact-backed gates in this workspace there is no unconfigured or
    degraded state for ``None`` to describe beyond the member not having been
    scanned at all.  Holding the handle computes nothing, and the first
    ``diagnose`` is where a branch is judged.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
