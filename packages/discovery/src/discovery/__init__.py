"""The discovery plugin: the campaign record, planned before any node is expanded.

Implements app_spec.xml, "Discovery Orchestrator & Campaigns", feature
232 — *"System creates a campaign record capturing type, workspace count
and null fraction before any node is expanded"* — against §5's discovery
tree and §4.1.1's planted-null fraction.

The member's surface is five modules.  :mod:`discovery.campaign` is the clip
that derives φ from ``W``, §7.3's two regimes as a closed set, the frozen
:class:`~discovery.campaign.CampaignRecord` and the store that creates one
row in the ``campaign`` table the migration already declares.
:mod:`discovery.themes` is feature 241 — *"System rejects a root theme
outside the configured legal set when assigning a research theme"* — the
deployment's configured research space and the verb that refuses an
assignment outside it.  :mod:`discovery.workers` is feature 238 — *"System
runs W parallel evaluation workers as concurrent slots, which returns
batch results as each worker completes"* — the dispatch seam that runs a
selected batch across the W slots the campaign was planned with and
yields each answer as its slot finishes.  :mod:`discovery.retry` is
feature 244 — *"System retries an interrupted evaluation worker
idempotently, so spot-instance reclamation returns no duplicate ledger
debit"* — the caller-side seam that re-runs the jobs §14's reclamation
took away, on the same asks their interrupted attempts carried, under a
budget the caller states.  :mod:`discovery.expansion` is feature 239 —
*"System expands a selected node by resuming its workspace, which
creates exactly one refined signal for evaluation"* — the worker of
record those two modules name: the callable a slot runs once per
selected node, resuming the tree's record of it and answering one
refined signal whose node id is derived from the parent, so a
reclamation's re-run is the same attempt in identity.  This module
re-exports all five and registers the one component; it carries no
logic of its own, which is the same shape every member in this
workspace takes.

**Feature 241 adds no component, and that is a decision rather than an
omission.**  The factory's registration protocol is for *state a deployment
holds* — a store, a device, a materialised pool.  A legal set resolved from
:data:`~discovery.themes.LEGAL_THEMES_ENV` is not that: it opens nothing,
writes nothing, and holds no state; and a builder for it could never return
``None``, because an unconfigured deployment still has PRD §9.3's space.  A
component whose builder always answers the same value is a function wearing a
component's name, so the member's first component stays the campaign store and
feature 232's component suite — which asserts this member registers exactly
one unprefixed name — is untouched by this feature.

**Feature 238 adds no component either, and it inherits 241's reason rather
than merely borrowing it.**  :func:`discovery.workers.run_batch` is the
orchestrator's evaluation dispatch — W concurrent slots over a selected
batch — and a pool of slots is emphatically *state a deployment holds*
while it is running, but it exists only for the length of one call: the
dispatch creates its slots, the stream's end joins them, and nothing
persists between batches.  The one honest builder for it would have to
bake the width at composition time — a pool whose W was decided by the
process rather than by the campaign record is precisely the
invented-campaign refusal :func:`discovery.workers.run_batch` states for
its missing default — so the verb stays a function and the member's
registered surface stays feature 232's single store.  W reaches the pool
the only way the spec allows: the caller that planned the campaign passes
``width=record.workspace_count``.

**Feature 244 adds no component, and it inherits 238's reason the way
238 inherited 241's.**  :func:`discovery.retry.retry_interrupted` is
the retry of the workers 238's pool answered interrupted — §14's
spot-instance reclamation, *"Failures retry; ledger debits are
idempotent by ``node_id``"* — and it holds even less between calls
than a pool does: no slots, no records, nothing but the outcome stream
for the length of the call.  Its two numbers are per-call facts the
caller states — ``retries``, the budget (§14 gives no number, so a
default would be this module inventing an interruption policy), and
``width``, the campaign's W again — and a builder that baked either
would freeze a policy no campaign stated.  The member's registered
surface stays feature 232's single store, and the campaign loop
reaches the retry the only way the spec allows: by calling it, with
the campaign's own width and its own tolerance for reclamation.

**Feature 239 adds no component either, and its reason is its own face
of the inherited one.**  :class:`discovery.expansion.NodeExpansion`
*does* close over state a deployment holds — the database URL its tree
lives in — and still composes nothing, because the other thing it
closes over is the agent seam, and the agent is the one collaborator
the factory cannot supply: a builder runs with no arguments, and the
deployment's evaluator driver (the very thing 238's docstring says
*"closes over stores and workspace handles no pickle can carry"*) is
wired by the caller that dispatches the batch, not by composition.  A
builder that registered an expansion with no agent would be
registering a refusal.  The caller reaches the worker the only way the
spec allows: by constructing it with the agent it planned to run, and
handing it to the pool as the worker of record.

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
from .errors import (
    BatchDispatchError,
    CampaignOrderError,
    CampaignPlanningError,
    DiscoveryError,
    ExpansionError,
    IllegalThemeError,
    WorkerInterrupted,
)
from .expansion import (
    EXPANSION_NAMESPACE,
    NodeExpansion,
    NodeWorkspace,
    RefinedSignal,
    expand_node,
    refined_node_id,
)
from .retry import (
    RetriedResult,
    is_interruption,
    retry_interrupted,
)
from .themes import (
    DEFAULT_LEGAL_THEMES,
    DEFAULT_THEME_SET,
    ILLEGAL_THEME,
    LEGAL_THEMES_ENV,
    THEME_ROOT_COLUMN,
    ThemeSet,
    assign_theme,
    legal_themes_from_env,
)
from .workers import (
    SLOT_THREAD_PREFIX,
    WorkerResult,
    run_batch,
)

__all__ = [
    "CALIBRATION_STATUS_DEFAULT",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "COMPONENT_NAME",
    "CREATED_AT_COLUMN",
    "DATABASE_URL_ENV",
    "DEFAULT_LEGAL_THEMES",
    "DEFAULT_THEME_SET",
    "EXPANSION_NAMESPACE",
    "ID_COLUMN",
    "ILLEGAL_THEME",
    "LEGAL_THEMES_ENV",
    "NODE_TABLE",
    "NULL_FRACTION_COLUMN",
    "PHI_CEILING",
    "PHI_FLOOR",
    "REGIMES",
    "SLOT_THREAD_PREFIX",
    "THEME_ROOT_COLUMN",
    "TYPE_D_CAMPAIGN_TYPE",
    "TYPE_R_CAMPAIGN_TYPE",
    "WORKSPACE_COUNT_COLUMN",
    "BatchDispatchError",
    "CampaignOrderError",
    "CampaignPlanningError",
    "CampaignRecord",
    "CampaignRecords",
    "DiscoveryError",
    "ExpansionError",
    "IllegalThemeError",
    "NodeExpansion",
    "NodeWorkspace",
    "RefinedSignal",
    "RetriedResult",
    "ThemeSet",
    "WorkerInterrupted",
    "WorkerResult",
    "assign_theme",
    "build_campaign_records",
    "create_campaign",
    "expand_node",
    "is_interruption",
    "legal_themes_from_env",
    "null_fraction",
    "refined_node_id",
    "retry_interrupted",
    "run_batch",
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
