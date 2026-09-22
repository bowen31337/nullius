"""The stated-mechanism law's seat in the ``app`` namespace — feature 211.

app_spec.xml, "Hypothesis Authoring Agent", feature 211: *System persists a
stated mechanism string used for deduplication and human review, never as a
scored input.*  The law lives in :mod:`signal_agent._mechanism`; this module is
how the app package reaches the composed law without importing the member at
module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring law?*;
feature 212's seat (:mod:`app.modules.signal-agent.themes`) answers it for the
legal theme gate; feature 213's (:mod:`app.modules.signal-agent.dead_territory`)
for the dead-territory gate; this module answers the same shape of question for
the member's fourth component: *what is the composed stated-mechanism law?*  A
seat per component rather than one accessor learning a fourth key, the
convention :mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the
four components answer different questions on different lifecycles — the
authoring law resolves the contract member's ABI lazily, the two gates carry
compiled committed artifacts, and this one carries a **store composed from the
environment** — and a caller that wants feature 211's law should not have to
hold the other three to get it.

**This seat's ``None`` is a statement about composition, and it is the one seat
in the directory where that is a narrower statement than it looks.**  It means
*no ``signal-agent-stated-mechanism`` component was registered* — the member
was not scanned, or the workspace is empty.  It is **not** the law's own answer
about its store: the law is composed in every deployment, and a deployment that
names no ``DATABASE_URL`` yields a *present* component whose
:attr:`~signal_agent.StatedMechanism.store` is ``None``.  So there are two
``None``\\ s in this area and they are not the same one:

* ``stated_mechanism_component() is None`` — nothing was registered.  A
  deployment fact about the scan.
* ``stated_mechanism_component().store is None`` — the law is here and has
  nowhere to persist.  Also a deployment fact, and a different one: the barrier
  clause still answers, and a caller that must persist gets a named
  :class:`~signal_agent.errors.MechanismStoreUnavailableError`.

Collapsing them would make *"the member is not scanned"* indistinguishable from
*"this deployment has no tree store"*, and the two have different repairs.  The
separation is the one :mod:`app.modules.signal-agent.dead_territory` draws
between its own ``None`` and the gate's answer about a theme, applied to a
deployment rather than to a proposal.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the record, the reasons, the
barrier verdict or the store: a caller who has the law reaches
``law.scored_input(record)`` for the barrier's verdict,
``law.require_scored_input(record)`` for the exception, ``law.persist(...)`` for
the write and ``law.duplicates(...)``/``law.stated()`` for the two reads, and a
second spelling of those here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed stated-mechanism law?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import StatedMechanism

__all__ = ["COMPONENT_NAME", "stated_mechanism_component"]

#: The component name the signal-agent member registers feature 211's law
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-stated-mechanism"


def stated_mechanism_component(
    app: Application | None = None,
) -> StatedMechanism | Any:
    """Return the composed stated-mechanism law (feature 211's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-stated-mechanism`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    **A returned law may carry no store**, and that is not this function's
    ``None``: see the module docstring.  Holding the handle computes nothing
    and touches no disk — the store resolves its URL on first use — so the one
    thing that can be true here and nowhere else is that the member was not
    scanned.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
