"""The discovery plugin: the campaign record, planned before any node is expanded.

Implements app_spec.xml, "Discovery Orchestrator & Campaigns", feature
232 — *"System creates a campaign record capturing type, workspace count
and null fraction before any node is expanded"* — against §5's discovery
tree and §4.1.1's planted-null fraction.

The member's surface is ten modules.  :mod:`discovery.campaign` is the clip
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
reclamation's re-run is the same attempt in identity.
:mod:`discovery.persist` is feature 240 — *"System persists every
attempt into the node table together with its full artifact, including
failures"* — the act the other five exist to feed: one `node` row and
one §9.2 artifact directory per attempt, a failure written by the same
call as a success, and a retry refreshing the row its derived identity
already names rather than adding a second.  :mod:`discovery.manifest` is
features 242 and 243 — the termination judgment and the campaign manifest
the reader consumes.  :mod:`discovery.planner` is feature 233 — *"System
rejects a plan_grid implementation that inspects the current episode,
because planning may read only prior campaign manifests"* — the boundary
feature 229's law names and declines to check: the orchestrator runs the
hook against the history it read and refuses one that reaches past it.
:mod:`discovery.grid` is feature 235 — *"System returns a grid plan
carrying a branch count plus a refine count derived from prior
manifests"* — the system's own planner: the derivation that runs *inside*
233's aperture, rebalancing the refinement budget the history actually
spent away from the history's own aspect so the next campaign is not the
400th tweak of the last one's indicator.  :mod:`discovery.difficulty` is
feature 236 — *"System computes a per-branch difficulty weight targeting a
success rate near 0.2, which returns a depth allocation favouring the agent
frontier"* — PRD §428's kernel and the proportional apportionment that
skews 235's flat base per branch.  :mod:`discovery.saturation` is feature
237 — *"System reduces allocation for a saturated branch where nearly every
refinement succeeds, which returns a lowered depth budget"* — the one
response 236's *relative* split cannot make: a level, applied to one branch
rather than to a comparison between branches, so a census whose branches are
*all* saturated is lowered rather than split evenly among them.
This module re-exports all of them and registers the one component; it
carries no logic of its own, which is the same shape every member in this
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

**Feature 240 adds no component, and its reason has 239's face plus a
second one.**  :class:`discovery.persist.AttemptLog` *does* close over
state a deployment holds — a database URL and an artifact directory —
and composes nothing.  The first face is 239's: the artifact directory
is a **sibling member's** component, and a builder takes no arguments,
so a registered log would have to invent one — and an invented store is
the tree row and the artifact directory disagreeing about where a node
lives, which is the one thing §9.1's ``artifact_uri TEXT NOT NULL``
cannot tolerate.  The second face is this feature's own and it is the
sharper one: a component is built on **every** ``create_app()`` call,
and a log that resolved its tree at build time would have to answer
*which campaign's attempts does this writer hold?* — a question with no
answer, because the log holds every campaign's, and a builder that
picked one would be a store that silently wrote a campaign's nodes into
another campaign's directory.  The caller reaches the record the only
way the spec allows: by constructing the log with the tree it writes
into and the store it publishes through, and calling it once per
attempt.  :func:`discovery.persist.record_attempts` is the same act
without the intermediate object, for the caller that holds neither.

**Feature 242 adds no component, and its reason has 240's face plus a
sharper one of its own.**  :class:`discovery.manifest.CampaignManifests`
*does* close over state a deployment holds — a database URL — and still
composes nothing.  The first face is 240's: the manifest is a *value the
loop persists and a reader consumes*, not a policy decision the factory
must discover — there is no judgement here for ``create_app()`` to make,
only a row to write and read, and a builder that registered one would be
a function wearing a component's name, the reason feature 241 gives for
the legal set and feature 238 for the pool.  The sharper second face is
this feature's own and it is the one the log states: a component is built
on **every** ``create_app()`` call, and a registered manifest store would
have to answer *which campaign's manifest does this hold?* — a question
with no answer, because the store holds every completed campaign's, and a
builder that picked one would be a reader pointed at a single campaign's
tree.  The member's registered surface stays feature 232's single store,
and the campaign loop reaches termination the only way the spec allows:
by calling :func:`finish_campaign`, with the campaign id it planned.

**Feature 243 adds no component either, and its reason is 242's without even
the store.**  :func:`discovery.manifest.admit_completed_campaigns` is a
judgement over values the caller already holds — a batch of
:class:`~discovery.manifest.CampaignManifest` — and closes over no deployment
state at all: no database URL, no table, nothing that persists between calls.
If a manifest *store* is already a function-wearing-a-component's-name by
feature 242's argument, a gate over a tuple of manifests is that argument's
limit case: there is no builder to write, because there is nothing for the
factory to discover.  The member's registered surface stays feature 232's
single store, and the caller that adds completed campaigns to the replay pool
reaches the gate the only way the spec allows: by calling it, with the
manifests its own store read through
:meth:`~discovery.manifest.CampaignManifests.completed`.

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

**Feature 233 adds no component either, and it is the limit case of the
argument the other seven make.**  :func:`discovery.planner.plan_grid` is a
pure function of a planning hook and the prior manifests the caller already
holds: it closes over no database URL, opens no table, writes no row, and
reads no clock — so the "which campaign does this hold?" question that
disqualifies a registered manifest store cannot even be asked of it.  It is
feature 241's *"a function wearing a component's name"* in its purest form,
and the member's registered surface stays feature 232's single store.  The
planning hook reaches its history the only way the spec allows: the caller
reads the prior manifests through
:meth:`~discovery.manifest.CampaignManifests.completed` — feature 242's one
authority on which campaigns are complete — and hands them to
:func:`~discovery.planner.plan_grid` before it creates the campaign's record.

**Feature 235 adds no component, and its reason is 233's exactly.**  The
distinction worth drawing is that 235, unlike 233, *does* make a decision —
it authors the grid a campaign is opened with, which is the sort of thing
a component exists to contribute.  What disqualifies it is narrower and
still decisive: a component is built by a builder that takes no arguments
and is *discovered* by the factory, while a plan is a function of evidence
the factory does not hold and cannot read.  A registered planner would
have to plan from a history nobody handed it, and the only history a
builder could find on its own is the one it opened a store to read —
which is feature 233's boundary broken by composition rather than by a
hook, and feature 242's *"which campaign does this hold?"* question
arriving at the one object that may not ask it.  The member's registered
surface stays feature 232's single store, and the orchestrator reaches
the derivation the only way the spec allows: by calling
:func:`~discovery.grid.derive_grid_plan` with the
:class:`~discovery.planner.PlanContext` it built from the manifests its
own store read — or by handing it to :func:`~discovery.planner.plan_grid`
as the hook, where it runs inside 233's aperture unchanged.

**Feature 236 adds no component, and its reason is 235's with one turn of the
screw.**  :func:`discovery.difficulty.allocate_depth` *does* make a decision —
it splits the grid's refinement budget across the branches the prefix
measured — and it is reached the same way 235's derivation is: by calling it,
with the :class:`~discovery.grid.GridPlan` the history justified and the
per-branch census the caller's prefix counted.  What disqualifies a
``@register`` here is narrower than 235's even: the derivation at least reads
the history the factory could have opened a store for, while this allocation
additionally reads the *current episode's* revealed refinements — the one thing
feature 233's boundary forbids a planning step from reaching — so a builder
that registered one would be a component pointed at an episode no composition
can supply, and a plan derived from it would be a description of the campaign
rather than a decision taken before it.  The member's registered surface
therefore stays feature 232's single store, unchanged by the whole of §428's
difficulty targeting, and the sibling member's ``_schedule(beta)`` dict that
PRD §434 says the band *"drops into"* stays the policy's own concern.

**Feature 237 adds no component, and its reason is 236's unchanged — which is
worth saying, because it is the one feature in this pair where a component
looks most tempting.**  :func:`discovery.saturation.reduce_saturated` is the
step §434's *"saturated and loses allocation"* asks for at the level 236's
proportional split cannot reach, and a *response* to saturation is exactly the
kind of policy a deployment might want to configure: the threshold and the
retention are both named defaults this member's own comments invite a
deployment to replace.  It still composes nothing, and the reason is that a
component is built by a builder that takes **no arguments** — so a registered
``SATURATION_RETENTION`` would have to be read from the environment by a member
that already has a configured surface for exactly that purpose (feature 241's
legal set) and no business adding a second one — and, more decisively, that a
builder is built on *every* ``create_app()`` call while this verb is a function
of an allocation and a census the factory holds neither of.  The census is
current-episode evidence, which is 236's own disqualification; the knobs are
constants the caller's own tuning replaces, which is 227's and 228's.  So the
member's registered surface stays feature 232's single store, and the tuning
reaches this rule the way every other band in the workspace is tuned: by
replacing the named constant, or by having planned the campaign through a
policy whose ``_schedule(beta)`` dict carries the value.

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
from .difficulty import (
    DIFFICULTY_BAND,
    TARGET_SUCCESS_RATE,
    TARGET_WEIGHT,
    BranchDifficulty,
    DepthAllocation,
    allocate_depth,
    difficulty_weight,
)
from .errors import (
    AttemptLogError,
    BatchDispatchError,
    CampaignOrderError,
    CampaignPlanningError,
    DiscoveryError,
    ExpansionError,
    IllegalThemeError,
    PlanInspectionError,
    VoidCampaignError,
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
from .grid import (
    REFERENCE_BRANCH_COUNT,
    REFERENCE_REFINE_COUNT,
    GridPlan,
    derive_grid_plan,
)
from .manifest import (
    BRANCH_COUNT_COLUMN,
    CALIBRATION_STATUS_COLUMN,
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    CAMPAIGN_ID_COLUMN,
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    DEPTH_MAX_COLUMN,
    LEAF_COUNT_COLUMN,
    MANIFEST_TABLE,
    NODE_COUNT_COLUMN,
    NODE_TABLE,
    PARENT_ID_COLUMN,
    REFINE_COUNT_COLUMN,
    THEME_ROOTS_COLUMN,
    THEME_ROOT_COLUMN,
    VOID_CAMPAIGN_CODE,
    CampaignManifest,
    CampaignManifests,
    TreeSummary,
    admit_completed_campaigns,
    finish_campaign,
)
from .persist import (
    ARTIFACT_URI_COLUMN,
    ATTEMPT_DATABASE_URL_ENV,
    FAIL_CLASS_COLUMN,
    FAIL_CLASSES,
    MEASURED_FILENAMES,
    SOURCE_FILENAME,
    TRACE_FILENAME,
    ArtifactDirectory,
    Attempt,
    AttemptLog,
    AttemptProvenance,
    AttemptRecord,
    attempt_node_id,
    classify_failure,
    record_attempts,
)
from .planner import (
    DEMANDS_EPISODE,
    EPISODE_SURFACE,
    INSPECTS_EPISODE,
    PlanContext,
    plan_grid,
)
from .retry import (
    RetriedResult,
    is_interruption,
    retry_interrupted,
)
from .saturation import (
    SATURATION_RATE,
    SATURATION_RETENTION,
    is_saturated,
    reduce_saturated,
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
    "ARTIFACT_URI_COLUMN",
    "ATTEMPT_DATABASE_URL_ENV",
    "BRANCH_COUNT_COLUMN",
    "CALIBRATION_STATUS_COLUMN",
    "CALIBRATION_STATUS_DEFAULT",
    "CALIBRATION_STATUS_OK",
    "CALIBRATION_STATUS_VOID",
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "COMPONENT_NAME",
    "CREATED_AT_COLUMN",
    "DATABASE_URL_ENV",
    "DEFAULT_LEGAL_THEMES",
    "DEFAULT_THEME_SET",
    "DEMANDS_EPISODE",
    "DEPTH_MAX_COLUMN",
    "DIFFICULTY_BAND",
    "EPISODE_SURFACE",
    "EXPANSION_NAMESPACE",
    "FAIL_CLASSES",
    "FAIL_CLASS_COLUMN",
    "ID_COLUMN",
    "ILLEGAL_THEME",
    "INSPECTS_EPISODE",
    "LEAF_COUNT_COLUMN",
    "LEGAL_THEMES_ENV",
    "MANIFEST_TABLE",
    "MEASURED_FILENAMES",
    "NODE_COUNT_COLUMN",
    "NODE_TABLE",
    "NULL_FRACTION_COLUMN",
    "PARENT_ID_COLUMN",
    "PHI_CEILING",
    "PHI_FLOOR",
    "REFERENCE_BRANCH_COUNT",
    "REFERENCE_REFINE_COUNT",
    "REFINE_COUNT_COLUMN",
    "REGIMES",
    "SATURATION_RATE",
    "SATURATION_RETENTION",
    "SLOT_THREAD_PREFIX",
    "SOURCE_FILENAME",
    "TARGET_SUCCESS_RATE",
    "TARGET_WEIGHT",
    "THEME_ROOTS_COLUMN",
    "THEME_ROOT_COLUMN",
    "TRACE_FILENAME",
    "TYPE_D_CAMPAIGN_TYPE",
    "TYPE_R_CAMPAIGN_TYPE",
    "VOID_CAMPAIGN_CODE",
    "WORKSPACE_COUNT_COLUMN",
    "ArtifactDirectory",
    "Attempt",
    "AttemptLog",
    "AttemptLogError",
    "AttemptProvenance",
    "AttemptRecord",
    "BatchDispatchError",
    "BranchDifficulty",
    "CampaignManifest",
    "CampaignManifests",
    "CampaignOrderError",
    "CampaignPlanningError",
    "CampaignRecord",
    "CampaignRecords",
    "DepthAllocation",
    "DiscoveryError",
    "ExpansionError",
    "GridPlan",
    "IllegalThemeError",
    "NodeExpansion",
    "NodeWorkspace",
    "PlanContext",
    "PlanInspectionError",
    "RefinedSignal",
    "RetriedResult",
    "ThemeSet",
    "TreeSummary",
    "VoidCampaignError",
    "WorkerInterrupted",
    "WorkerResult",
    "admit_completed_campaigns",
    "allocate_depth",
    "assign_theme",
    "attempt_node_id",
    "build_campaign_records",
    "classify_failure",
    "create_campaign",
    "derive_grid_plan",
    "difficulty_weight",
    "expand_node",
    "finish_campaign",
    "is_interruption",
    "is_saturated",
    "legal_themes_from_env",
    "null_fraction",
    "plan_grid",
    "record_attempts",
    "reduce_saturated",
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
