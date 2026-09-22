"""The proposal history store's seat in the ``app`` namespace — feature 207.

app_spec.xml, "Hypothesis Authoring Agent", feature 207: *System persists one
proposal document plus a score record per node, which together form the
replayable history.*  The law lives in :mod:`signal_agent._proposal`; this
module is how the app package reaches the composed law without importing the
member at module scope.

The directory's growth is the pattern by now.  Feature 205's seat
(:mod:`app.modules.signal-agent`) answers *what is the composed authoring law?*;
feature 212's seat (:mod:`app.modules.signal-agent.themes`) answers it for the
legal theme gate, feature 213's (:mod:`app.modules.signal-agent.dead_territory`)
for the dead-territory gate, feature 211's
(:mod:`app.modules.signal-agent.mechanism`) for the stated-mechanism law,
feature 210's (:mod:`app.modules.signal-agent.anti_convergence`) for the
anti-convergence gate, feature 209's
(:mod:`app.modules.signal-agent.diagnosis`) for the mechanism diagnosis,
feature 206's (:mod:`app.modules.signal-agent.history`) for the proposal
history law and feature 208's
(:mod:`app.modules.signal-agent.guidance`) for the prompt-guidance gate.  This
module answers the same shape of question for the member's ninth component:
*what is the composed proposal history store?*  A seat per component rather
than one accessor learning a ninth key, the convention
:mod:`app.modules.bootstrap` states for its four and
:mod:`app.modules.feature-store` for its five, and for the same reason: the
nine components answer different questions on different lifecycles — the
authoring law resolves the contract member's ABI lazily, three gates carry a
compiled committed document, two more carry nothing at all, one carries a store
resolved from ``DATABASE_URL``, and this one carries a store of its own — and a
caller that wants feature 207's history should not have to hold the other eight
to get it.

**This seat's ``None`` is a statement about composition, and it is the second
seat in the directory where that is a narrower statement than it looks.**  It
means *no ``signal-agent-proposal-history`` component was registered* — the
member was not scanned, or the workspace is empty.  It is **not** the law's own
answer about its store: the law is composed in every deployment, and a
deployment that names no ``DATABASE_URL`` yields a *present* component whose
:attr:`~signal_agent.ProposalHistoryStore.store` is ``None``.  So there are two
``None``\\ s in this area and they are not the same one — exactly the split
:mod:`app.modules.signal-agent.mechanism` draws for feature 211's law:

* ``proposal_history_component() is None`` — nothing was registered.  A
  deployment fact about the scan.
* ``proposal_history_component().store is None`` — the law is here and has
  nowhere to persist.  Also a deployment fact, and a different one: a caller
  that must persist gets a named
  :class:`~signal_agent.errors.ProposalHistoryStoreUnavailableError`.

Collapsing them would make *"the member is not scanned"* indistinguishable from
*"this deployment has no tree store"*, and the two have different repairs.

**It is a *second* seat beside feature 206's, and not a replacement for it.**
:mod:`app.modules.signal-agent.history` answers *is this history whole?* — the
reader's judgment, which never touches a database.  This one answers *where is
the history?* — the writer's store, which always does.  Feature 206's module
docstring names its subject as *the caller's own tree query* and compiles
nothing; this module is the seat of the store behind that query, and the two
are deliberately separate because the reader's verdict is answerable in a
deployment with no database at all while this handle is the one that says there
is nowhere to keep one.  The seam between them is
:meth:`~signal_agent.ProposalHistoryStore.history`, which returns feature 206's
own ``PriorProposal`` values — so a caller holding this seat hands its answer
to the other seat's law and the two cannot disagree about what a history is
made of.

**Composition stays the factory's job.**  This module asks the factory for the
component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the record, the score
record, the stored instants or the refusals: a caller who has the law reaches
``law.persist(...)`` for the write, ``law.history(...)`` for the read feature
206 consumes, ``law.load(...)`` for the single-node read and
``law.counted(...)`` for the completeness figure, and a second spelling of
those here would be a second thing to keep in sync.  The one question this
module answers is *what is the composed proposal history store?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from signal_agent import ProposalHistoryStore

__all__ = ["COMPONENT_NAME", "proposal_history_component"]

#: The component name the signal-agent member registers feature 207's law
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
COMPONENT_NAME = "signal-agent-proposal-history"


def proposal_history_component(
    app: Application | None = None,
) -> ProposalHistoryStore | Any:
    """Return the composed proposal history store (feature 207's law).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``signal-agent-proposal-history`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory.

    **A returned law may carry no store**, and that is not this function's
    ``None``: see the module docstring.  Holding the handle computes nothing
    and touches no disk — the store resolves its URL on first use, and the
    table it owns is created on the first operation rather than here — so the
    one thing that can be true here and nowhere else is that the member was not
    scanned.  The first :meth:`~signal_agent.ProposalHistoryStore.persist` is
    where a round's proposal enters the history, and where a deployment with no
    database is told so by name.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
