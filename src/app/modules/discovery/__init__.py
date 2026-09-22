"""The discovery campaign store's seat in the ``app`` package namespace — feature 232.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 232: *System
creates a campaign record capturing type, workspace count and null fraction
before any node is expanded.*  The record and the store that creates it live
in :mod:`discovery.campaign`; this module is how the app package reaches the
composed store without importing the member at module scope.

Feature 188's pool seat (:mod:`app.modules.bootstrap.pool`) answers *what is
the composed replay pool?*; feature 122's gate seat
(:mod:`app.modules.nulloracle.plan`) answers *what is the composed planning
gate?*; this one answers the same shape of question for the discovery
member's first and only component: *what is the composed campaign store?*

**The seat is not the whole of the member, and this one is deliberately
narrow.**  The member also exposes the planning seam — feature 233's
:func:`discovery.planner.plan_grid`, which runs a policy's planning hook
against the prior campaign manifests and refuses one that reaches for the
current episode — reached directly from :mod:`discovery` exactly as the
policy-runtime member's ``plan_grid`` (229) and ``screen_policy`` (230/231)
are reached from theirs.  It adds no component and so has no seat: a seat
exists to answer *what did composition build for this deployment?*, and this
seam closes over no deployment state at all.  A reader looking for it will
not find it here, which is why this paragraph is here rather than nothing.

**Feature 235's planner is the second such seam, and its absence from this
module is the more interesting one.**  :func:`discovery.grid.derive_grid_plan`
authors the grid a campaign is opened with — a branch count and a refine count
derived from the prior manifests — which is exactly the sort of *decision* a
component is usually the vehicle for, so it is worth being explicit about why
there is no seat for it either.  A builder takes no arguments and is
discovered by the factory; a plan is a function of evidence the factory does
not hold and must not go looking for.  A registered planner would have to read
a history on its own initiative, and the only history it could reach that way
is one it opened a store to read — which is feature 233's prior-manifests-only
boundary broken by composition rather than by a hook.  So the derivation is
reached the way 233's seam is: directly, from :mod:`discovery`, with the
manifests the *caller* read through feature 242's
:meth:`discovery.manifest.CampaignManifests.completed`.  Both seams are
answered by the composed store this module *does* seat — the store is what
makes the history readable at all — and neither is a second thing for
``campaign_records_component`` to return.

**The seat's ``None`` is about the deployment, not about the member.**
``None`` means *nothing named a database* — ``DATABASE_URL`` is unset, so
there is no table for a campaign row to land in.  It does **not** mean the
member was not scanned (that would be a different fact, and it would have
left no component registered at all), and it is emphatically not a store
that happens to hold no campaigns: an empty store answers *this campaign was
never planned* about every id it is asked for, while this ``None`` says
there is nowhere a campaign could have been planned.  Feature 232's record
is a precondition of the whole inner loop — §4.1.1's fraction is *fixed at
planning time, not learned from the run*, and the seven null-oracle stores
refuse to write against a campaign nobody created — so a caller that
requires a campaign must treat this ``None`` as a refusal to proceed rather
than as an empty store, exactly as the pool seat's ``None`` is a refusal to
author §10.6's 40-50 worlds.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is none,
mirroring the factory's own "degrade, don't break" stance toward absent
components.  It deliberately does **not** re-export the record, the clip, §7.3's
regimes or the module-level :func:`discovery.campaign.create_campaign`: a
caller who has the store reaches ``create()`` and ``get()`` on it, and a
second spelling here would be a second thing to keep in sync.  The one
question this module answers is *what is the composed campaign store?*

**Construction touches no database.**  The store resolves its path on first
use and opens nothing until an operation needs it, so asking for the
component is always safe — the same promise the member's own builder makes —
and the first :meth:`~discovery.campaign.CampaignRecords.create` is where a
campaign row is written.  Composing an application never plans a campaign,
and it must not: the record is created when a campaign is planned, and by
the caller that is planning it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from discovery import CampaignRecords

__all__ = ["COMPONENT_NAME", "campaign_records_component"]

#: The component name the discovery member registers its campaign store
#: under.  Kept here as well as in the member — every seat in this workspace
#: spells its own name twice for the same reason — so the two cannot drift
#: apart silently, and the member's component suite asserts they agree.
#: Unprefixed, following the ``ledger`` / ``artifacts`` / ``canary``
#: precedent for a member's first and only component: the prefix families
#: (``nulloracle-*``, ``tripwires-*``) exist to disambiguate many components
#: inside one member, and this member has one.  ``discovery`` sorts after
#: ``cost-model`` and before ``evaluator``, so every existing adjacency
#: assertion over the name-sorted ``app.order`` is untouched.
COMPONENT_NAME = "discovery"


def campaign_records_component(app: Application | None = None) -> CampaignRecords | Any:
    """Return the composed campaign store (feature 232's store).

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``discovery`` component is registered — either
    because the member was not scanned, or because its builder found no
    ``DATABASE_URL`` to resolve.

    That ``None`` is a statement about the deployment, and the caller that
    must create a campaign has to read it as one.  There is deliberately no
    fallback here that opens a default database or fabricates a store: a
    campaign row written into a database nobody named would be invisible to
    the seven null-oracle stores that join it by id, so a *sensible default*
    is precisely the failure this seat's ``None`` exists to make visible.  A
    process that needs a store passes a URL to
    :class:`~discovery.campaign.CampaignRecords` directly (or calls
    :func:`~discovery.campaign.create_campaign`), where a named
    :class:`~discovery.errors.CampaignPlanningError` is the right answer
    rather than a ``None``.

    The store the component returns is only useful once a caller asks it to
    create something: reading the component opens no database, so a
    composed application that never plans a campaign never touches disk.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
