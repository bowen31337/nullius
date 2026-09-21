"""The discovery plugin: the campaign record, planned before any node is expanded.

Implements app_spec.xml, "Discovery Orchestrator & Campaigns", feature
232 — *"System creates a campaign record capturing type, workspace count
and null fraction before any node is expanded"* — against §5's discovery
tree and §4.1.1's planted-null fraction.

The member's whole surface is :mod:`discovery.campaign`: the clip that
derives φ from ``W``, §7.3's two regimes as a closed set, the frozen
:class:`~discovery.campaign.CampaignRecord` and the store that creates one
row in the ``campaign`` table the migration already declares.  This module
re-exports it and registers the component; it carries no logic of its own,
which is the same shape every member in this workspace takes.

**Why this member exists at all.**  The ``campaign`` table is feature
104's (``migrations/versions/0111_campaign_table.py``) and eight stores
already read it — the seven null-oracle stores plus the discovery
orchestrator itself — and every one of them *refuses to create its row*.
:mod:`nulloracle.phi` says so in as many words, naming this plugin as the
planner: *"``null_fraction`` is fixed before any node is expanded … which
is the planner's job (feature 232's ``discovery`` plugin), not this
member's."*  A row that nobody writes is a system whose every calibration
number is unreachable, so this member is the writer that closes that loop,
and it is a member of its own rather than a function inside nulloracle
because the workspace contract forbids one member importing another and
because §5's orchestrator is a different concern from §7's null oracle
(the planner decides *what* to plant; the oracle plants it and keeps the
answer secret).

**Registration is the entire wiring story.**  The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml``
declares, imports each package, and composes whatever each package's
``@register`` builder contributes — so the decorator at the foot of this
module is all that makes the plugin exist.  Nothing edits a registry,
router table, entry-points list or app factory to wire this package in,
and nothing here reaches back and mutates the factory: the factory is the
composition root and the sole author of the object it returns.

**The registration lives here and not in a submodule.**  ``@register``
fires at import time, and importing a *submodule* of this package is not
the same act as importing the package: a submodule's registration would
fire only on the first ``create_app()`` of a process, and only if that
process happened to load it.  Keeping the decorator in ``__init__.py`` —
spelled against names imported from ``.campaign`` rather than beside it —
is what makes the component present from the moment the workspace scan
touches this package.

**One component, and it may be ``None``.**  ``"discovery"`` is the
member's first component, registered unprefixed: it is the whole of what
this member contributes, and the null-oracle member's ``nulloracle-*``
names exist to disambiguate *eleven* components inside one member, a
problem this one does not have.  The builder returns ``None`` when
nothing names a relational store, on the degrade-don't-break stance every
store in this workspace takes toward an absent ``DATABASE_URL`` — an
unconfigured campaign store is a discoverable state, and the orchestrator
that must create a campaign before it expands anything is the caller that
must not find itself in it.  It never raises, including for a URL whose
scheme this member cannot speak: the factory builds every registered
component on every ``create_app()`` call, so a raising builder would take
composition down for every unrelated feature in the workspace.
"""

from __future__ import annotations

from app.module_loader import register

from .campaign import (
    CALIBRATION_STATUS_DEFAULT,
    CAMPAIGN_TABLE,
    CAMPAIGN_TYPE_COLUMN,
    CREATED_AT_COLUMN,
    DATABASE_URL_ENV,
    ID_COLUMN,
    NODE_TABLE,
    NULL_FRACTION_COLUMN,
    PHI_CEILING,
    PHI_FLOOR,
    REGIMES,
    TYPE_D_CAMPAIGN_TYPE,
    TYPE_R_CAMPAIGN_TYPE,
    WORKSPACE_COUNT_COLUMN,
    CampaignRecord,
    CampaignRecords,
    create_campaign,
    null_fraction,
)
from .errors import CampaignOrderError, CampaignPlanningError, DiscoveryError

__all__ = [
    "CALIBRATION_STATUS_DEFAULT",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "COMPONENT_NAME",
    "CREATED_AT_COLUMN",
    "DATABASE_URL_ENV",
    "ID_COLUMN",
    "NODE_TABLE",
    "NULL_FRACTION_COLUMN",
    "PHI_CEILING",
    "PHI_FLOOR",
    "REGIMES",
    "TYPE_D_CAMPAIGN_TYPE",
    "TYPE_R_CAMPAIGN_TYPE",
    "WORKSPACE_COUNT_COLUMN",
    "CampaignOrderError",
    "CampaignPlanningError",
    "CampaignRecord",
    "CampaignRecords",
    "DiscoveryError",
    "build_campaign_records",
    "create_campaign",
    "null_fraction",
]

#: The name the discovery member registers its campaign store under.
#: Unprefixed, following the ``ledger`` / ``artifacts`` / ``canary``
#: precedent for a member's first and only component, and spelled here
#: once so the seat (``src/app/modules/discovery``) and the composed
#: application agree on the key — the seat repeats the literal and its
#: suite asserts the two match, so the pair cannot drift apart silently.
COMPONENT_NAME = "discovery"


@register(COMPONENT_NAME)
def build_campaign_records() -> CampaignRecords | None:
    """Component builder: the campaign store this deployment writes into.

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application
    carries the campaign store for the deployment the process is actually
    running in.  Feature 232's record is a row, and the deployment that
    holds the ``campaign`` table is what this component is: the member's
    other spelling of the same act,
    :func:`~discovery.campaign.create_campaign`, resolves the same
    variable when it is called without a URL, so a script and a composed
    application reach the same store.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately not an empty store: an empty store answers *no campaign
    has been planned here* about every id, while this ``None`` says there
    is no database to have planned one in, and a caller that needs to make
    feature 232's record must treat it as a refusal to proceed rather than
    as a store that happened to find nothing.  The distinction is the one
    :func:`bootstrap.build_bootstrap_pool` draws for its own deployment
    state.

    Never raises — including for a URL whose scheme the store cannot
    speak, which is refused by name the first time an operation needs the
    path rather than here.  Construction performs no I/O: the path is
    resolved on first use, so composing the application never opens a
    database, and nothing is written until a caller demands a campaign.
    """
    return CampaignRecords.resolve()
