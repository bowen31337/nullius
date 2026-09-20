"""The null-oracle member: §7.1's encrypted sidecar of null assignments.

app_spec.xml, "Null Oracle & Planted Nulls", lands on this workspace member
(``packages/nulloracle``, import name ``nulloracle``).
docs/nullius-tech-architecture.md §7 opens with the reason the component
exists at all — *"The component that makes the whole method work. It is
deliberately small, deliberately isolated, and deliberately boring."* — and
§1 states what is at stake if the isolation fails: the null labels are the
one secret whose leak *"silently voids every calibration number the system
has ever produced, and you would not notice."*

Feature 109 is the foundation the whole category stands on: *System
persists null assignments in an AES-GCM encrypted sidecar file readable by
exactly one service account.*  The features that follow layer onto this
member rather than beside it — feature 110's absence of ``is_null`` from
the tree store (a rule about a *different* component, resting on this one
being the only place the bit lives), feature 111's KMS/sops key resolution
(:mod:`nulloracle.keyref` is the grammar that resolution runs behind),
feature 112's ``POST /target`` and 115's block permutation (which read the
seeds this member stores), 117's ``φ`` and 118-122's campaign assignment
(the writers of the map this member seals), and 123-124's KS guard (which
needs the labels, not merely their count).

**Feature 123 is where the labels are finally *used*, and it is the one
place they may be.**  §7.4 states the test — *"a job holding the sidecar key
runs a two-sample KS test on in-sample score distributions, null nodes vs.
real nodes"* — and §4.2 states the rule it is the single exception to:
``is_null`` is visible to exactly one component, and the guard is the job
that component runs.  So feature 123 arrives as two modules split the way
the sidecar's three are: :mod:`nulloracle.ks` is the test (the statistic
and its p-value, validated, stdlib-only and carrying no node id) and
:mod:`nulloracle.ksguard` is the store that writes the number against its
campaign.

**Feature 124 is the decision the test does not make.**  §7.4's ``p < 0.05``
comparison and the ``VOID`` it sets are feature 124's, and they arrive as
:mod:`nulloracle.verdict` — the module that reads the p-value feature 123
persisted, compares it to :data:`VOID_THRESHOLD`, and sets
``calibration_status = VOID`` when it falls below.  The split is the same
discipline feature 123 observes: this feature measures, the next one
decides, and the threshold that separates "calibrated" from "void" is a
constant of the verdict module because the verdict module is the one place
the verdict is pronounced.  The verdict is a fact about a campaign, so it is
written to the campaign row the guard already writes to; the alert and the
dreaming-halt and pool-exclusion that §7.4's rule also names are
*consequences* of the status being ``VOID``, enforced where the pool and
promotion read the status (features 876/1056), not here.

**Feature 116 is the sentence feature 115's mechanism exists to satisfy.**
§7.3 states it in one line — *"Block permutation shuffles contiguous 20-day
blocks, preserving return autocorrelation and volatility clustering while
destroying the signal-to-target relationship"* — and
:mod:`nulloracle.preservation` is that sentence made checkable: the block
structure survives *exactly* (the output is the input's runs concatenated in
some order, each run whole and in order, which a pointwise shuffle fails at
every length above two), the two statistics survive *approximately* to within
a bound scaled by how much of each estimate the shuffle actually disturbed,
and the signal-to-target relationship is destroyed to within what a
rearrangement of the series' blocks produces by chance.  The asymmetry is the
whole point: §7.4's guard must not be able to tell a null branch from a real
one, while §4.1's *"expected true OOS edge of a null branch is exactly zero by
construction"* must hold.  :func:`~nulloracle.preservation.check_preservation`
measures all three at the ``block_days`` the assignment sealed and returns a
:class:`~nulloracle.preservation.PreservationReport` carrying every number,
and :meth:`~nulloracle.preservation.PreservationReport.require` is the
serving path's refusal — a null series that broke the sentence is a
computation that went wrong, so it is the guard's error and not the sidecar's.

**Feature 121 is where the flip depth is finally *used*.**  §7.2 states the
rule in one line — *"below ``flip_depth`` the real targets are returned, at or
beyond it the permuted ones"* — and :mod:`nulloracle.resolution` is that rule
with a store behind it: :func:`~nulloracle.resolution.past_the_flip` is the
boundary itself, and :class:`~nulloracle.resolution.TypeDOracle` reads the
node's stored depth and its branch's stored flip (feature 119's, inherited
down the ancestor chain), requires the campaign to be the Type-D regime, and
serves the caller's real targets below the flip and the caller's permutation
at or beyond it.  The permutation arrives as a seam because the *which branch*
decision is feature 121's and the *permutation* is feature 115's —
:mod:`nulloracle.blockpermute` is §7.2's ``block_permute(forward_returns,
seed=perm_seed, block=20d)``: it cuts a series into contiguous ``block_days``
blocks and shuffles those blocks as units, preserving the autocorrelation and
volatility clustering within each block while destroying the signal-to-target
relationship, from the ``perm_seed`` feature 109 stored beside the bit so a
replayed campaign reproduces the same series.  The two are composed at the
call site — the seed and block length are read from §7.1's sidecar and handed
to :func:`~nulloracle.blockpermute.block_permute`, whose return is passed to
the resolution as its ``permute`` — because the *which branch* decision is
feature 121's and the *permutation* is not; what the oracle refuses to do is
serve the permuted branch without one.

**Feature 122 is the gate the two writers answer to.**  §7.3 fixes the rule
in one sentence — *"Campaigns are homogeneous in null type.  Mixed trees make
a bad FDR unattributable between selection failure and stopping failure"* —
and :mod:`nulloracle.plan` is that sentence as a refusal:
:class:`~nulloracle.plan.CampaignPlan` is one campaign's planned null world
(the declared regime, the roots a selection lands on, the branches a flip
lands on) and a plan that mixes the two regimes within one tree refuses to
*exist*, raising :class:`~nulloracle.errors.HeterogeneousWorldError` with the
``heterogeneous_world`` message the spec names.  The writers each decline the
regime they are not on their own row; this is the check above them, and
:class:`~nulloracle.plan.CampaignPlanGate.review` reads the plan they left
behind — flip depths off the tree, root selections off §7.1's sealed file —
so a world that went mixed by any path is caught by the one decision.

**Features 112 and 113 are where the member first answers, rather than
records.**  Every module above this paragraph *writes* a fact — the sealed
file, the flip depths, the selections, the p-value, the verdict — and
:mod:`nulloracle.target` is the one that *serves*: §7.2's ``POST
/target``, the interface the evaluator's step 5 asks, as a Python seam
over the sidecar.  The request is §7.2's six terms validated at
construction (the identities as UUIDs, the horizon inside the closed five,
the cross-section as one sorted spelling, the range first-to-last); the
answer for a known node — one §7.1's sidecar holds an entry for — is the
feature's own ``200`` carrying §7.2's whole payload, an unknown node
answers ``404``, and a sidecar that is missing or will not open propagates
its own named error rather than reading as either.

The payload is feature 113's half, and it is the one place in the member
where the sealed bit is *used*.  §7.2's rule is *"if ``is_null``, return
``block_permute(forward_returns, seed=perm_seed, block=20d)``; else return
the real forward returns"*, so the entry the lookup read selects the
branch — and selects it without disclosing it.  What leaves the route is
the series and one bool: ``charges_budget``, ``False`` exactly for a null
node (§8's own column comment is ``-- FALSE for null nodes``), because a
null node's signal was never compared to real forward returns and so spent
no statistical degrees of freedom — ``K_effective`` counts only the rows
whose directive is true, and a null node must never inflate it.  §7.2's
response comment
(``# is_null NEVER appears``) is a property of the whole answer, and the
corruption table's audit is the reason it is stated twice: *"Null budget
flag leaked as a label → Audit: ``charges_budget`` correlated with
anything in the agent's context → the flag must be opaque."*  The real
series, feature 115's permutation and feature 121's flip rule all arrive
as injected seams — this member holds no forward returns and imports no
other member's store — and a deployment that supplies none composes a
route that answers for the branch it can and refuses the other by name,
with :class:`~nulloracle.errors.TargetPayloadError`, rather than serving a
world it does not hold.

**Feature 114 is §7.2's promise read the way an adversary reads a response.**
The line at the end of §7.2's rule — *"The caller cannot distinguish the two
branches from the response"* — is stated over the payload, and features
112-113 kept it there: one record, one shape, no field that names the branch,
the one crossing bit carried as §8's opaque directive.  Feature 114 reads
"the response" as everything the caller can observe about the call, and a
response arrives with more than its bytes: *how long it took* is part of it
too.  The null branch's series is the real one put through a block
permutation, so a route that permuted only when the bit said so would do
strictly more work for a null node — panel-sized work, spent on one branch
alone — and a caller holding nothing but a stopwatch would read the branch
off the latency.  So :meth:`nulloracle.target.TargetEndpoint.post` computes
**both** branches' series on every request, checks both, and lets the bit do
exactly one thing: select which already-computed value is served.  A real
node's answer now pays for a permutation it discards — deliberate, because
the alternative is a branch the caller can time — and nothing a caller can
read — value, shape, call sequence, or clock — varies with the bit except
the one directive §8 sends across.  The same-work discipline generalises the
one features 112-113 already stated in the small (both supplies named before
the branch is chosen, both payload validators run on both branches) to the
series itself, and it is the route's own — no deployment configures it,
because indistinguishability that a deployment could switch off would not be
§7.2's promise at all.

**The three halves, and why they are three modules.**  A sidecar entry is a
schema (:mod:`nulloracle.assignment`), a cipher (:mod:`nulloracle.envelope`)
and a file (:mod:`nulloracle.sidecar`), and each is separately arguable.
The schema is §7.1's ``{node_id: {is_null, perm_seed, block_days}}`` and can
be reasoned about — and tested — with no key in hand; the cipher is AES-GCM
in a pinned container and can be tested for tampering with no schema in the
way; the file is permissions and atomic replacement, which is neither of the
other two.  Collapsing them would mean the one thing that cannot be
separated is where a bug hides.

**Why the plaintext schema is what it is.**  ``is_null`` is the bit itself.
``perm_seed`` and ``block_days`` are there because feature 115's block
permutation must be *reproducible* — *"using a stored permutation seed with
a 20 day block length"*, and the load-bearing word is **stored** — so the
parameters that make a null node's series what it is are sealed beside the
bit that says the node is null.  A world whose permutation was re-drawn on
each request would not be a world; §12's determinism contract forbids it
outright.

**Why the labels are never cached in memory.**  :class:`NullSidecar` holds
no memo of the map it just read.  The file is sealed and mode-``0600``
precisely so that *reading it* is the controlled operation; a cache would
move that operation to construction and then hold the plaintext labels for
the process's lifetime, which is a strictly worse place for them to be than
the disk they are encrypted on.

**The ``@register`` decorator lives here, in this ``__init__``, and in no
submodule.**  The factory's scan re-executes a package's ``__init__`` on
every :func:`~app.module_loader.create_app` call, but a submodule already
cached in ``sys.modules`` is not re-executed; a ``@register`` in a submodule
would therefore fire on the first composition of a process and silently drop
out of every later one.  Registration lives on the import path the scan
always runs — the same invariant every other member's registration states.

The public API is small on purpose, and each piece is the seam a later
feature composes rather than a second spelling of something the sidecar
already says:

* :class:`~nulloracle.assignment.NullAssignment` with
  :func:`~nulloracle.assignment.canonical_assignments` — §7.1's schema as a
  value and as canonical bytes: one node's ``is_null``/``perm_seed``/
  ``block_days``, validated at construction and renderable reproducibly.
* :class:`~nulloracle.sidecar.NullSidecar` — the file: :meth:`~nulloracle.
  sidecar.NullSidecar.write` seals a whole map atomically at mode ``0600``,
  :meth:`~nulloracle.sidecar.NullSidecar.open` reads it back or refuses, and
  :meth:`~nulloracle.sidecar.NullSidecar.assignment` answers for one node.
* :class:`~nulloracle.target.TargetEndpoint` with
  :class:`~nulloracle.target.TargetRequest` and
  :class:`~nulloracle.target.TargetResponse` — features 112 through 114's
  route: ``POST /target``, answering §7.2's request (node, campaign, depth,
  horizon, symbols, date range) with a ``200`` carrying the target series
  and the opaque ``charges_budget`` directive for a node the sidecar holds,
  and a ``404`` for one it does not — carrying nothing of the branch either
  way, and (feature 114) spending the same work whichever branch supplied
  the series, so neither the answer nor the clock names the branch.
* :class:`~nulloracle.keyref.SidecarKey` with
  :class:`~nulloracle.keyref.KeyReference` and
  :func:`~nulloracle.keyref.ensure_key` — feature 109's seam: the reference
  grammar (``kms:``, ``sops:``, ``hex:``), the account check, and a key
  wrapper that will not leak into a traceback.
* :class:`~nulloracle.backends.KmsBackend` and
  :class:`~nulloracle.backends.SopsBackend` with
  :func:`~nulloracle.backends.resolve_sidecar_key` — feature 111's
  resolution, on the receiving end of the seam above: the two backends turn a
  ``kms:`` or ``sops:`` reference into key material (each taking an injected
  client or runner, so no test needs a cloud SDK or the ``sops`` binary), and
  the entry point resolves and hands the material to ``ensure_key``.
* :class:`~nulloracle.keyalert.UnrecoverableState` with
  :class:`~nulloracle.keyalert.UnrecoverableStateError`,
  :func:`~nulloracle.keyalert.guard_decryption` and
  :class:`~nulloracle.keyalert.KeyAlertJournal` — feature 111's alert, and
  §7's one row that is *not* a repair: a failed decryption emits an
  ``unrecoverable_state`` (the raise is the emission, the record is the
  payload, and the journal is where it is kept), because all FDR history
  becomes uninterpretable and the only answer is a restore from backup.  A
  malformed reference or secret is deliberately *not* this alert — it is a
  configuration mistake with a repair that is not a restore.
* :func:`~nulloracle.envelope.seal` with
  :func:`~nulloracle.envelope.open_envelope` — the AES-GCM container, whose
  layout is pinned in that module so a nonce can never be reused.
* :func:`~nulloracle.assignment.assignments_digest` and
  :func:`~nulloracle.envelope.envelope_digest` — the two key-free
  comparisons: *is this the same sidecar?*, answerable by a process that is
  not allowed to open it.
* :func:`~nulloracle.ks.ks_two_sample` with :mod:`nulloracle.ksguard` —
  feature 123's detectability test and the store that persists its p-value
  against the campaign, and :func:`~nulloracle.verdict.void_if_detectable`
  with :mod:`nulloracle.verdict` — feature 124's verdict, which reads that
  stored p-value, compares it to :data:`VOID_THRESHOLD`, and sets the
  campaign's ``calibration_status`` to ``VOID``.  The test measures, the
  verdict decides, and the verdict pronounces on the number the guard
  persisted rather than on one a caller hands in.
* The error taxonomy of :mod:`nulloracle.errors`, one base class wide —
  and its central distinction is that an unopenable sidecar raises rather
  than reading as an empty one.
"""

from __future__ import annotations

from typing import Any

from app.module_loader import register

from .assignment import (
    DEFAULT_BLOCK_DAYS,
    NullAssignment,
    assignments_digest,
    canonical_assignments,
    decode_assignments,
    encode_assignments,
    normalize_node_id,
)
from .blockpermute import block_indices, block_permute
from .envelope import (
    FORMAT_VERSION,
    MAGIC,
    NONCE_BYTES,
    TAG_BYTES,
    envelope_digest,
    open_envelope,
    require_cryptography,
    seal,
)
from .errors import (
    HeterogeneousWorldError,
    KsGuardError,
    KsTestError,
    NullOracleError,
    SidecarAccessError,
    SidecarDecryptionError,
    SidecarError,
    SidecarKeyError,
    SidecarStoreError,
    TargetPayloadError,
    TargetRouteError,
)
from .flipdepth import (
    FLIP_DEPTH_COLUMN,
    NODE_TABLE,
    P_MAX,
    P_MIN,
    FlipDepth,
    flip_depth,
    node_as_seed,
    persist_flip_depth,
)
from .irprob import (
    CAMPAIGN_SPREAD,
    PROBABILITY_CEILING,
    PROBABILITY_FLOOR,
    TRUE_IR_MIDPOINT,
    TRUE_IR_SCALE,
    FlipDepthDistribution,
    TrueIRFlipDepth,
    campaign_as_seed,
    campaign_offset,
    draw_flip_depth,
    flip_depth_distribution,
    probability_from_true_ir,
)
from .keyref import (
    KEY_REF_ENV,
    SERVICE_ACCOUNT_ENV,
    SIDECAR_KEY_BYTES,
    EnsureKeyResult,
    KeyReference,
    SidecarKey,
    ensure_key,
    resolve_key,
    service_account,
)

# Feature 111's two halves: the backends (:mod:`nulloracle.backends`) that
# actually call KMS and sops, and the alert (:mod:`nulloracle.keyalert`) a
# failed decryption emits.  Imported at module scope like the rest of the
# member's pure-Python halves: both are stdlib-only — the cloud SDK and the
# `sops` binary are deferred to first use — so the factory's scan, which
# imports this package to fire its `@register`, pays nothing for them.
from .backends import (
    KMS_BLOB_ENV,
    KMS_SCHEME,
    SOPS_SCHEME,
    SOPS_TIMEOUT_SECONDS,
    KmsBackend,
    KeyBackend,
    SopsBackend,
    default_backends,
    require_boto3,
    require_sops,
    resolve_material,
    resolve_sidecar_key,
)
from .keyalert import (
    ALERT_KIND,
    KEY_ALERT_TABLE,
    KEY_BACKEND_STAGE,
    SIDECAR_STAGE,
    KeyAlertJournal,
    UnrecoverableState,
    UnrecoverableStateError,
    emit_unrecoverable_state,
    guard_decryption,
    load_key_alerts,
    unrecoverable_state_error,
)

# Feature 123's two halves: the test (:mod:`nulloracle.ks`) and the store
# that writes its answer against the campaign (:mod:`nulloracle.ksguard`).
# Imported at module scope, unlike the `cryptography` the envelope defers:
# both are stdlib-only, so the factory's scan — which imports this package
# to fire its `@register` — pays nothing for them.
from .ks import (
    KS_ASYMPTOTIC,
    KS_ASYMPTOTIC_FLOOR,
    KS_EXACT,
    KS_EXACT_CELLS,
    KS_MIN_SAMPLE,
    KS_SERIES_TERMS,
    KolmogorovSmirnov,
    ks_pvalue,
    ks_two_sample,
    two_sample_statistic,
)
from .ksguard import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    KS_GUARD_TABLE,
    KsGuard,
    KsGuardRecord,
    guard_record_from_row,
    load_ks_guard,
    persist_ks_pvalue,
)
from .phi import (
    NULL_FRACTION_COLUMN,
    PHI_CEILING,
    PHI_FLOOR,
    WORKSPACE_COUNT_COLUMN,
    PlantedNullFraction,
    null_fraction,
    persist_null_fraction,
)
from .plan import (
    HETEROGENEOUS_WORLD,
    REGIMES,
    CampaignPlan,
    CampaignPlanGate,
    review_campaign_plan,
)
from .preservation import (
    DESTRUCTION_HEADROOM,
    PRESERVATION_TOLERANCE,
    PreservationReport,
    autocorrelation,
    block_runs,
    check_preservation,
    destroys_relationship,
    preservation_lags,
    preserves_block_structure,
    preserves_structure,
    signal_to_target_correlation,
    volatility_clustering,
)
from .resolution import (
    TYPE_D_CAMPAIGN_TYPE,
    TypeDOracle,
    TypeDResolution,
    past_the_flip,
    resolve_type_d,
)
from .selection import (
    CAMPAIGN_TYPE_COLUMN,
    TYPE_R_CAMPAIGN_TYPE,
    RootSelection,
    TypeRSelection,
    draw_null_roots,
    null_root_count,
    perm_seed_for,
    persist_type_r_selection,
)
from .sidecar import (
    SIDECAR_DIRECTORY,
    SIDECAR_FILE_MODE,
    SIDECAR_FILENAME,
    SIDECAR_PATH_ENV,
    NullSidecar,
)
from .target import (
    HORIZONS,
    NOT_FOUND,
    OK,
    STATUS_CODES,
    TARGET_ROUTE,
    TargetEndpoint,
    TargetRequest,
    TargetResponse,
)
from .verdict import (
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    VOID_THRESHOLD,
    CampaignVerdict,
    Verdict,
    load_verdict,
    void_if_detectable,
)

__all__ = [
    "CALIBRATION_STATUS_OK",
    "CALIBRATION_STATUS_VOID",
    "CAMPAIGN_SPREAD",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "ALERT_KIND",
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DEFAULT_BLOCK_DAYS",
    "DESTRUCTION_HEADROOM",
    "FLIP_DEPTH_COLUMN",
    "FLIP_DEPTH_COMPONENT_NAME",
    "FORMAT_VERSION",
    "FRACTION_COMPONENT_NAME",
    "HETEROGENEOUS_WORLD",
    "HORIZONS",
    "KEY_ALERT_COMPONENT_NAME",
    "KEY_ALERT_TABLE",
    "KEY_BACKEND_STAGE",
    "KEY_REF_ENV",
    "KMS_BLOB_ENV",
    "KMS_SCHEME",
    "KS_ASYMPTOTIC",
    "KS_ASYMPTOTIC_FLOOR",
    "KS_EXACT",
    "KS_EXACT_CELLS",
    "KS_GUARD_COMPONENT_NAME",
    "KS_GUARD_TABLE",
    "KS_MIN_SAMPLE",
    "KS_SERIES_TERMS",
    "MAGIC",
    "NODE_TABLE",
    "NONCE_BYTES",
    "NOT_FOUND",
    "NULL_FRACTION_COLUMN",
    "OK",
    "PHI_CEILING",
    "PHI_FLOOR",
    "PLAN_COMPONENT_NAME",
    "PRESERVATION_TOLERANCE",
    "PROBABILITY_CEILING",
    "PROBABILITY_FLOOR",
    "P_MAX",
    "P_MIN",
    "REGIMES",
    "RESOLUTION_COMPONENT_NAME",
    "SERVICE_ACCOUNT_ENV",
    "SIDECAR_DIRECTORY",
    "SIDECAR_FILENAME",
    "SIDECAR_FILE_MODE",
    "SIDECAR_KEY_BYTES",
    "SIDECAR_PATH_ENV",
    "SIDECAR_STAGE",
    "SOPS_SCHEME",
    "SOPS_TIMEOUT_SECONDS",
    "STATUS_CODES",
    "TAG_BYTES",
    "TARGET_COMPONENT_NAME",
    "TARGET_ROUTE",
    "TRUE_IR_FLIP_DEPTH_COMPONENT_NAME",
    "TRUE_IR_MIDPOINT",
    "TRUE_IR_SCALE",
    "TYPE_D_CAMPAIGN_TYPE",
    "TYPE_R_CAMPAIGN_TYPE",
    "TYPE_R_COMPONENT_NAME",
    "VERDICT_COMPONENT_NAME",
    "VOID_THRESHOLD",
    "WORKSPACE_COUNT_COLUMN",
    "CampaignPlan",
    "CampaignPlanGate",
    "EnsureKeyResult",
    "FlipDepth",
    "FlipDepthDistribution",
    "HeterogeneousWorldError",
    "KeyAlertJournal",
    "KeyBackend",
    "KeyReference",
    "KmsBackend",
    "KolmogorovSmirnov",
    "KsGuard",
    "KsGuardError",
    "KsGuardRecord",
    "KsTestError",
    "NullAssignment",
    "NullOracleError",
    "NullSidecar",
    "PlantedNullFraction",
    "PreservationReport",
    "RootSelection",
    "SidecarAccessError",
    "SidecarDecryptionError",
    "SidecarError",
    "SidecarKey",
    "SidecarKeyError",
    "SidecarStoreError",
    "SopsBackend",
    "TargetEndpoint",
    "TargetPayloadError",
    "TargetRequest",
    "TargetResponse",
    "TargetRouteError",
    "TrueIRFlipDepth",
    "TypeDOracle",
    "TypeDResolution",
    "TypeRSelection",
    "UnrecoverableState",
    "UnrecoverableStateError",
    "Verdict",
    "assignments_digest",
    "autocorrelation",
    "block_indices",
    "block_permute",
    "block_runs",
    "build_campaign_plan_gate",
    "build_flip_depth",
    "build_key_alert_journal",
    "build_null_sidecar",
    "build_target_route",
    "build_true_ir_flip_depth",
    "build_type_d_resolution",
    "build_verdict",
    "campaign_as_seed",
    "campaign_offset",
    "canonical_assignments",
    "check_preservation",
    "decode_assignments",
    "default_backends",
    "destroys_relationship",
    "draw_flip_depth",
    "draw_null_roots",
    "emit_unrecoverable_state",
    "encode_assignments",
    "ensure_key",
    "envelope_digest",
    "flip_depth",
    "flip_depth_distribution",
    "guard_decryption",
    "guard_record_from_row",
    "ks_pvalue",
    "ks_two_sample",
    "load_key_alerts",
    "load_ks_guard",
    "load_verdict",
    "node_as_seed",
    "normalize_node_id",
    "null_fraction",
    "null_root_count",
    "open_envelope",
    "past_the_flip",
    "perm_seed_for",
    "persist_flip_depth",
    "persist_ks_pvalue",
    "persist_null_fraction",
    "persist_type_r_selection",
    "preservation_lags",
    "preserves_block_structure",
    "preserves_structure",
    "probability_from_true_ir",
    "require_boto3",
    "require_cryptography",
    "require_sops",
    "resolve_key",
    "resolve_material",
    "resolve_sidecar_key",
    "resolve_type_d",
    "review_campaign_plan",
    "seal",
    "service_account",
    "signal_to_target_correlation",
    "two_sample_statistic",
    "unrecoverable_state_error",
    "void_if_detectable",
    "volatility_clustering",
]

__version__ = "0.1.0"

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the sidecar at, and the
#: name the seat in the app namespace (``src/app/modules/nulloracle``) asks
#: for.  Spelled once here so the member, the factory's registry and the
#: seat cannot drift apart.
COMPONENT_NAME = "nulloracle"

#: The component name feature 123's guard journal registers under — the key a
#: composed :class:`~app.module_loader.Application` carries the journal at.
#: A second name rather than a second component under :data:`COMPONENT_NAME`
#: because the two are different things on different lifecycles: the sidecar
#: is §7.1's sealed file, the guard is feature 123's store, and a deployment
#: can legitimately have one without the other.  The ledger member registers
#: three names the same way.
KS_GUARD_COMPONENT_NAME = "nulloracle-ks-guard"

#: The component name feature 124's verdict store registers under — the key a
#: composed :class:`~app.module_loader.Application` carries it at.  A third
#: name rather than a second/third component under :data:`COMPONENT_NAME`
#: because the sidecar, the guard journal and the verdict are three different
#: things on three different lifecycles, and a deployment can legitimately
#: have one without the others.  The ledger member registers three names the
#: same way.
VERDICT_COMPONENT_NAME = "nulloracle-ks-verdict"

#: The component name feature 117's fraction store registers under — the key a
#: composed :class:`~app.module_loader.Application` carries it at.  A fourth
#: name rather than a second component under :data:`COMPONENT_NAME` because
#: the sidecar, the guard journal, the verdict and the fraction are four
#: different things on four different lifecycles, and a deployment can
#: legitimately have one without the others.  The ledger member registers
#: several names the same way.
FRACTION_COMPONENT_NAME = "nulloracle-null-fraction"

#: The component name feature 119's flip-depth store registers under — the key
#: a composed :class:`~app.module_loader.Application` carries it at.  A fifth
#: name rather than a second component under :data:`COMPONENT_NAME` because the
#: sidecar, the guard journal, the verdict, the fraction and the flip depth are
#: five different things on five different lifecycles, and a deployment can
#: legitimately have one without the others.  The ledger member registers
#: several names the same way.
FLIP_DEPTH_COMPONENT_NAME = "nulloracle-null-flip-depth"

#: The component name feature 121's Type-D resolution registers under — the
#: key a composed :class:`~app.module_loader.Application` carries it at.  A
#: sixth name rather than a sixth component under :data:`COMPONENT_NAME`
#: because the sidecar, the guard journal, the verdict, the fraction, the flip
#: depth and the resolution are six different things on six different
#: lifecycles, and a deployment can legitimately have any without the others.
#: The ``type-d-`` prefix sorts after both the ``ks-*`` and the ``null-*``
#: families in the name-sorted ``app.order``, so feature 123's
#: guard-immediately-after-sidecar adjacency is untouched.
RESOLUTION_COMPONENT_NAME = "nulloracle-type-d-resolution"

#: The component name feature 120's true-IR flip-depth store registers under —
#: the key a composed :class:`~app.module_loader.Application` carries it at.  A
#: seventh name rather than a second component under
#: :data:`FLIP_DEPTH_COMPONENT_NAME` because the two hold different things: the
#: flip depth's component is the store that draws a geometric from a probability
#: the caller supplies, and this one is the store that *derives* that probability
#: from a branch's true information ratio and its campaign (feature 120).  A
#: deployment can legitimately carry either without the other — the campaign
#: loop that owns the world's true IRs wants this one, and a re-draw from a
#: probability already decided wants the other.  The ``true-ir-`` prefix sorts
#: after the ``ks-*``, ``null-*`` and ``type-d-*`` families in the name-sorted
#: ``app.order``, so feature 123's guard-immediately-after-sidecar adjacency is
#: untouched.
TRUE_IR_FLIP_DEPTH_COMPONENT_NAME = "nulloracle-true-ir-flip-depth"

#: The component name feature 118's Type-R root selection registers under — the
#: key a composed :class:`~app.module_loader.Application` carries it at.  An
#: eighth name rather than a second component under
#: :data:`RESOLUTION_COMPONENT_NAME` because the two regimes are different
#: things on different lifecycles: the Type-D oracle resolves a *request*
#: against a branch's flip depth, and this store draws and persists a *world*'s
#: root selection into §7.1's sidecar.  A deployment can legitimately carry
#: either without the other, and the spec's own campaign planning draws exactly
#: one of them per campaign (§7.3: campaigns are homogeneous in null type).
#: Registered as a composite: it needs both a relational store (the tree, φ and
#: ``W``) and the sealed sidecar (the one artifact allowed to hold the bit), so
#: it composes only where both resolve.  The ``type-r-`` prefix sorts after the
#: ``ks-*``, ``null-*``, ``type-d-*`` and ``true-ir-*`` families in the
#: name-sorted ``app.order``, so feature 123's guard-immediately-after-sidecar
#: adjacency is untouched.
TYPE_R_COMPONENT_NAME = "nulloracle-type-r-selection"

#: The component name feature 122's planning gate registers under — the key a
#: composed :class:`~app.module_loader.Application` carries the gate at.  A
#: ninth name rather than a ninth component under any of the other eight,
#: because the gate is a different thing on its own lifecycle: it reads the
#: two writers' artifacts (the tree's flip depths and §7.1's sealed file) and
#: refuses the world they would jointly make, so a deployment can carry the
#: writers without the gate and the gate without... nothing, in fact — it
#: composes only where both of the halves it reads resolve, the same pair
#: feature 118's selection composes from.  The ``plan-`` prefix sorts after
#: the ``ks-*`` and ``null-*`` families and before the ``true-ir-*`` and
#: ``type-*`` families in the name-sorted ``app.order``, so feature 123's
#: guard-immediately-after-sidecar adjacency is untouched.
PLAN_COMPONENT_NAME = "nulloracle-plan-gate"

#: The component name feature 112's route registers under — the key a
#: composed :class:`~app.module_loader.Application` carries the endpoint at.
#: A tenth name rather than a tenth component under :data:`COMPONENT_NAME`,
#: because the sidecar and the route over it are different things on
#: different lifecycles: the sidecar is §7.1's sealed file, held wherever
#: the labels must be written, and the route is §7.2's answer, held wherever
#: an evaluation asks — a deployment can legitimately compose the writer
#: without the server and the server without the writer.  The ``target-``
#: prefix sorts after the ``ks-*``, ``null-*`` and ``plan-*`` families and
#: before the ``true-ir-*`` and ``type-*`` families in the name-sorted
#: ``app.order``, so feature 123's guard-immediately-after-sidecar adjacency
#: is untouched.
TARGET_COMPONENT_NAME = "nulloracle-target-route"

#: The component name feature 111's alert journal registers under — the key a
#: composed :class:`~app.module_loader.Application` carries the journal at.
#: An eleventh name rather than a component under :data:`COMPONENT_NAME`,
#: because the sidecar and the journal of its key's failures are different
#: things on different lifecycles: the sidecar is §7.1's sealed file, held
#: wherever the labels must be read, and the journal is §7's *Unrecoverable*
#: row, written wherever one must be able to ask *is this deployment already in
#: that state?* — a deployment can hold either without the other.
#:
#: The ``sidecar-`` prefix is load-bearing, not cosmetic.  ``app.order`` is
#: name-sorted and two tests pin feature 123's guard landing immediately after
#: the sidecar (``nulloracle`` + 1 == ``nulloracle-ks-guard``), so a name
#: sorting into that pair would break a rule this member has held since feature
#: 123.  ``nulloracle-key-…`` would sort *before* ``nulloracle-ks-guard`` and
#: displace it; ``nulloracle-sidecar-key-alert`` sorts after
#: ``nulloracle-plan-gate`` and before ``nulloracle-target-route``, leaving the
#: adjacency untouched.
KEY_ALERT_COMPONENT_NAME = "nulloracle-sidecar-key-alert"


@register(FRACTION_COMPONENT_NAME)
def build_null_fraction() -> PlantedNullFraction | None:
    """Component builder: §4.1.1's fraction store, bound to the environment.

    Feature 117's *store* half as a component, so the campaign planner that
    fixes a campaign's planted-null fraction can ask the composed application
    for the fraction store the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the guard's, the verdict's and the
    ledger's stores expose.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its path from the environment at build time, so a composed
    application carries a fraction store for the deployment the process is
    actually running in.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured fraction is a discoverable state,
    and a deployment whose campaign planner must fix §4.1.1's fraction is the
    caller that must not find itself in it.

    Like :func:`build_null_sidecar`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* a fraction store asks
    :meth:`~nulloracle.phi.PlantedNullFraction.resolve` or calls the store
    directly, where a named :class:`~nulloracle.errors.KsGuardError` is the
    right answer.  Construction performs no I/O — the path is resolved on first
    use — so composing the application never opens a database.
    """
    return PlantedNullFraction.resolve()


@register(FLIP_DEPTH_COMPONENT_NAME)
def build_flip_depth() -> FlipDepth | None:
    """Component builder: §7.3's Type-D flip-depth store, bound to the environment.

    Feature 119's *store* half as a component, so the campaign job that draws a
    Type-D branch's flip depth can ask the composed application for the store
    the deployment configured rather than reading ``DATABASE_URL`` itself — the
    same seam the fraction's, the guard's and the verdict's stores expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured flip depth is a discoverable state,
    and a deployment whose campaign loop must draw §7.3's flip depths is the
    caller that must not find itself in it.

    Like :func:`build_null_fraction`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* a flip-depth store asks
    :meth:`~nulloracle.flipdepth.FlipDepth.resolve` or calls the store directly,
    where a named :class:`~nulloracle.errors.KsGuardError` is the right answer.
    Construction performs no I/O — the path is resolved on first use — so
    composing the application never opens a database.
    """
    return FlipDepth.resolve()


@register(TRUE_IR_FLIP_DEPTH_COMPONENT_NAME)
def build_true_ir_flip_depth() -> TrueIRFlipDepth | None:
    """Component builder: §7.3's true-IR flip probability, bound to the environment.

    Feature 120's *store* half as a component, so the campaign loop that holds a
    branch's true information ratio can ask the composed application for the
    store that turns it into the probability feature 119 draws from — rather
    than reading ``DATABASE_URL`` itself, the same seam the fraction's, the
    flip depth's, the verdict's and the resolution's stores expose.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its path from the environment at build time, so a composed
    application carries a true-IR flip-depth store for the deployment the
    process is actually running in.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured true-IR flip depth is a discoverable
    state, and a deployment whose campaign loop must draw §7.3's Type-D flip
    depths is the caller that must not find itself in it.

    Like :func:`build_flip_depth`, this never raises, including for a URL whose
    scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* this store asks
    :meth:`~nulloracle.irprob.TrueIRFlipDepth.resolve` or calls the store
    directly, where a named :class:`~nulloracle.errors.KsGuardError` is the
    right answer.  Construction performs no I/O — the path is resolved on first
    use — so composing the application never opens a database.

    The store is composed beside feature 119's rather than under it: this one
    *reads* the node's campaign and delegates the write, so a deployment can
    carry the derived-probability seam without carrying anything else.
    """
    return TrueIRFlipDepth.resolve()


@register(RESOLUTION_COMPONENT_NAME)
def build_type_d_resolution() -> TypeDOracle | None:
    """Component builder: §7.2's Type-D flip resolution, bound to the environment.

    Feature 121's resolution half as a component, so the endpoint that serves
    §7.2's ``POST /target`` requests can ask the composed application for the
    Type-D oracle the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the fraction's, the flip depth's,
    the verdict's and the guard's stores expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured resolution is a discoverable
    state, and a deployment whose endpoint must resolve Type-D requests is the
    caller that must not find itself in it.

    Like :func:`build_flip_depth`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* the resolution asks
    :meth:`nulloracle.resolution.TypeDOracle.resolve` or calls the oracle
    directly, where a named :class:`~nulloracle.errors.KsGuardError` is the
    right answer.  Construction performs no I/O — the path is resolved on
    first use — so composing the application never opens a database.
    """
    return TypeDOracle.resolve()


@register(VERDICT_COMPONENT_NAME)
def build_verdict() -> CampaignVerdict | None:
    """Component builder: §7.4's verdict store, bound to the environment.

    Feature 124's *decision* half as a component, so the campaign job that
    judges a completed campaign can ask the composed application for the
    verdict store the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the guard's and the ledger's store
    expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured verdict is a discoverable state,
    and a deployment whose campaign loop must pronounce §7.4's verdict is the
    caller that must not find itself in it.

    Like :func:`build_null_sidecar` and :func:`build_ks_guard`, this never
    raises, including for a URL whose scheme this store cannot speak.  The
    factory builds every registered component on every
    :func:`~app.module_loader.create_app` call, so a builder that raised would
    take composition down for every unrelated feature; a process that *requires*
    a verdict asks :meth:`~nulloracle.verdict.CampaignVerdict.resolve` or calls
    the store directly, where a named :class:`~nulloracle.errors.KsGuardError`
    is the right answer.  Construction performs no I/O — the path is resolved
    on first use — so composing the application never opens a database.
    """
    return CampaignVerdict.resolve()


@register(KS_GUARD_COMPONENT_NAME)
def build_ks_guard() -> KsGuard | None:
    """Component builder: §7.4's guard journal, bound to the environment.

    Feature 123's *store* half as a component, so the campaign job that runs
    the guard over a completed campaign can ask the composed application for
    the journal the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the ledger member's store and
    the evaluator's own expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured guard is a discoverable state,
    and a deployment whose campaign loop must run §7.4's guard is the caller
    that must not find itself in it.

    Like :func:`build_null_sidecar`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every
    registered component on every :func:`~app.module_loader.create_app`
    call, so a builder that raised would take composition down for every
    unrelated feature; a process that *requires* a guard asks
    :meth:`~nulloracle.ksguard.KsGuard.resolve` or calls the store directly,
    where a named :class:`~nulloracle.errors.KsGuardError` is the right
    answer.  Construction performs no I/O — the path is resolved on first
    use — so composing the application never opens a database.
    """
    return KsGuard.resolve()


@register(COMPONENT_NAME)
def build_null_sidecar() -> NullSidecar | None:
    """Component builder: §7.1's sidecar, bound to the environment.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its path and its key from the environment at build time, so a
    composed application carries a sidecar for the deployment the process is
    actually running in (``NULL_SIDECAR_PATH`` or ``LAKE_ROOT`` for the
    location, ``NULL_SIDECAR_KEY_REF`` for the key, and
    ``NULL_SIDECAR_SERVICE_ACCOUNT`` for the one account it is granted to).

    Construction performs no I/O: the directory is created and the file
    written only on a :meth:`~nulloracle.sidecar.NullSidecar.write`, and the
    key is not read from disk or a KMS here beyond what the reference itself
    resolves.  So composing the application never touches the sidecar, which
    is what keeps the factory's scan cheap and unprivileged.

    Returns ``None`` when nothing names a usable location and key — the
    same degrade-don't-break stance the ledger member's store takes toward
    an absent ``DATABASE_URL``: an unconfigured sidecar is a discoverable
    state, and the composed application simply carries no ``"nulloracle"``
    component.  A deployment whose scorer must run §7.4's detectability
    guard is the caller that must not find itself in that state.

    Deliberately never raises, including for a ``kms:`` or ``sops:``
    reference this member does not speak.  The factory builds every
    registered component on every :func:`~app.module_loader.create_app`
    call, so a builder that raised would take composition down for every
    unrelated feature in the workspace; a process that *requires* a sidecar
    asks :func:`~nulloracle.keyref.ensure_key` directly at its own startup,
    where a named :class:`~nulloracle.errors.SidecarKeyError` is the right
    answer.
    """
    return NullSidecar.resolve()


@register(TYPE_R_COMPONENT_NAME)
def build_type_r_selection() -> TypeRSelection | None:
    """Component builder: §7.3's Type-R root selection, bound to the environment.

    Feature 118's *store* half as a component, so the campaign loop that must
    plant a Type-R world can ask the composed application for the store the
    deployment configured rather than resolving ``DATABASE_URL`` and the
    sidecar itself — the same seam the fraction's, the flip depth's, the
    verdict's and the resolution's stores expose.

    Takes no arguments — that is the factory's registration protocol — and
    resolves both halves from the environment at build time.  This one needs
    **both**: a relational store for the tree, φ and ``W``, and §7.1's sidecar
    for the bit itself.  That is the feature's shape rather than a
    convenience — the draw reads the campaign's own row, and the status may
    only be written into the one artifact allowed to hold it (feature 110: no
    ``is_null`` column anywhere in the tree store) — so a deployment carrying
    one without the other composes no selection component rather than a
    half-store that could draw but not persist.

    Returns ``None`` when nothing names a relational store, or when nothing
    names a usable sidecar location and key, the degrade-don't-break stance
    every store in this workspace takes: an unconfigured selection is a
    discoverable state, and a deployment whose campaign loop must plant
    §7.3's Type-R world is the caller that must not find itself in it.

    Like :func:`build_flip_depth`, this never raises, including for a URL
    whose scheme this store cannot speak or a ``kms:`` reference this member
    does not resolve.  The factory builds every registered component on every
    :func:`~app.module_loader.create_app` call, so a builder that raised would
    take composition down for every unrelated feature; a process that
    *requires* the store asks :meth:`~nulloracle.selection.TypeRSelection.
    resolve` or calls the store directly, where a named
    :class:`~nulloracle.errors.KsGuardError` is the right answer.
    Construction performs no I/O — the path is resolved on first use and the
    sidecar opens nothing until the first ``write()`` or ``open()`` — so
    composing the application never opens a database or touches the labels.
    """
    return TypeRSelection.resolve()


@register(PLAN_COMPONENT_NAME)
def build_campaign_plan_gate() -> CampaignPlanGate | None:
    """Component builder: §7.3's planning gate, bound to the environment.

    Feature 122's gate as a component, so the campaign loop that is about to
    plant a world — and the operator auditing one that was already planted —
    can ask the composed application for the gate the deployment configured
    rather than resolving ``DATABASE_URL`` and the sidecar itself, the same
    seam the selection's, the resolution's and the guard's stores expose.

    Takes no arguments — that is the factory's registration protocol — and
    resolves both halves from the environment at build time.  Like feature
    118's selection, this one needs **both**: the relational store the tree
    and its flip depths live in, and §7.1's sidecar the root selections live
    in — the one artifact allowed to hold the bit (feature 110).  A gate
    holding only the database could see flips but not selections, and would
    answer ``homogeneous`` for worlds it never looked at, so a deployment
    carrying one without the other composes no gate at all.

    Returns ``None`` when nothing names a relational store, or when nothing
    names a usable sidecar location and key, the degrade-don't-break stance
    every store in this workspace takes: an unconfigured gate is a
    discoverable state, and a deployment whose campaign loop must review
    §7.3's homogeneity before planting is the caller that must not find
    itself in it.

    Like :func:`build_type_r_selection`, this never raises, including for a
    URL whose scheme this store cannot speak or a ``kms:`` reference this
    member does not resolve.  The factory builds every registered component
    on every :func:`~app.module_loader.create_app` call, so a builder that
    raised would take composition down for every unrelated feature; a process
    that *requires* the gate asks :meth:`nulloracle.plan.CampaignPlanGate.
    resolve` or calls the store directly, where a named
    :class:`~nulloracle.errors.KsGuardError` is the right answer.
    Construction performs no I/O — the path is resolved on first use and the
    sidecar opens nothing until the first ``review`` — so composing the
    application never opens a database or touches the labels.
    """
    return CampaignPlanGate.resolve()


@register(TARGET_COMPONENT_NAME)
def build_target_route() -> TargetEndpoint | None:
    """Component builder: §7.2's POST /target route, bound to the environment.

    Features 112 and 113's route as a component, so the evaluation whose
    §6.1 step 5 must ask the oracle can ask the composed application for the
    endpoint the deployment configured rather than resolving the sidecar
    itself — the same seam the member's other satellites expose.  Resolved
    from the same environment and the same sidecar builder as
    :func:`build_null_sidecar`, so the route and the composed ``nulloracle``
    component always answer from the same file and can never point at two
    worlds.

    **Feature 115's permutation is wired here, and the other two seams are
    not.**  §7.2's null branch is *``block_permute(forward_returns,
    seed=perm_seed, block=20d)``*, and this member owns that mechanism — so
    the builder composes it in, reading the entry's own stored seed and block
    length from the assignment the route hands it.  Nothing left over is
    guessed: the call is the same one :func:`nulloracle.blockpermute.
    block_permute` makes for any caller, made through a closure so the route
    need not import the module that owns it.

    The other two seams are deliberately left unwired, because neither is
    this member's to resolve from an environment variable.  ``targets`` is
    pipeline step 4's aligned series — the evaluator member's, produced from
    a sealed snapshot this member may not open — and ``past_flip`` is feature
    121's store, which a deployment attaches when it composes a route for a
    Type-D world; both arrive on :class:`~nulloracle.target.TargetEndpoint`'s
    constructor by the caller that holds them.  A route built here therefore
    refuses a node by name rather than serving a series it does not have —
    and it refuses *both* branches, not the null one alone, because a refusal
    that fell only on null nodes would itself be the branch oracle §7.2
    forbids.  That is the honest degradation, and the state every deployment
    is in until it wires step 4's supply.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its sidecar at build time.  Construction performs no I/O (the
    sidecar opens nothing until the first ``post``), so composing the
    application never touches the labels.

    Returns ``None`` when nothing names a usable sidecar location and key,
    the degrade-don't-break stance every store in this workspace takes: an
    unconfigured route is a discoverable state, and a deployment whose
    evaluator must gate targets is the caller that must not find itself in
    it.  Like :func:`build_null_sidecar`, this never raises, including for
    a ``kms:`` or ``sops:`` reference this member does not speak — the
    factory builds every registered component on every call, and one
    member's unconfigured environment is not a fault the others pay for.
    """
    sidecar = NullSidecar.resolve()
    if sidecar is None:
        return None
    return TargetEndpoint(sidecar, permute=_stored_permutation)


def _stored_permutation(series: Any, *, seed: Any, block_days: Any) -> dict:
    """Feature 115's permutation, bound to the parameters the entry sealed.

    The closure :func:`build_target_route` hands the route as its ``permute``
    seam.  §7.2 spells the mechanism over ``forward_returns`` — one node's
    series — and the route's payload is a cross-section per date, so this
    closure is where the two grains are reconciled: the blocks feature 115
    moves are runs of ``block_days`` consecutive *dates*, and each date's
    whole row of per-symbol returns travels with it.  That is the reading
    §7.3's preservation claim requires — *"shuffles contiguous 20-day blocks,
    preserving return autocorrelation and volatility clustering while
    destroying the signal-to-target relationship"* — because a permutation at
    ``(date, symbol)`` grain would break each date's cross-section apart,
    destroying structure the null branch is supposed to keep and planting a
    null feature 123's guard could detect.

    The days are gathered through
    :func:`~nulloracle.blockpermute.block_indices`, which is the permutation
    expressed over *positions* and whose docstring names exactly this case:
    *"a caller that wants to permute something other than a float series
    permutes its own positions and gathers."*  The positions here are
    ``range(len(days))`` — the panel's row indices, in the order the mapping
    yielded them.  The index form and the series form share the one seeded
    shuffle, so this closure and a series-grain caller can never disagree
    about what the permutation did.

    **The dates stay where they are; the rows move between them.**  A panel
    is a grid, and the grid is the *axis* rather than a series laid out on
    it, so output slot ``position`` keeps date ``days[position]`` and takes
    the row that input slot ``order[position]`` held.  Writing
    ``{days[i]: series[days[i]] for i in order}`` instead would gather each
    date *with* its own row and rebuild the identical mapping in a different
    insertion order — and since mapping equality is order-insensitive, the
    null branch would serve the real series and nothing downstream could
    tell.  §7.3's whole claim is about rows arriving next to the wrong
    dates; a permutation that keeps them together moves nothing at all.

    The route never calls this with parameters of its own: ``seed`` and
    ``block_days`` are read from the :class:`~nulloracle.assignment.
    NullAssignment` the sidecar returned for this node, which is what makes
    the permutation reproducible from the sealed world alone (§12) rather
    than from anything a process remembers.  A missing or malformed parameter
    is refused by the permutation's own contract — :func:`~nulloracle.
    blockpermute.block_indices` refuses ``None`` by name — so a route that
    reached this closure through a seam that drifted is caught by the
    mechanism rather than by a second validation that could disagree with it.
    """
    # Imported lazily, the way the member defers every other mechanism: the
    # factory's scan imports this package to fire its @register, and the
    # permutation is only ever reached on a null branch's request.
    from .blockpermute import block_indices

    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    # The grid holds; the rows move across it.  ``order[position]`` is the
    # input slot whose row the permuted slot ``position`` receives, so this
    # gather is what puts a block of returns under a *different* block of
    # dates — the displacement §7.3 is about.
    return {days[position]: dict(rows[order[position]]) for position in range(len(days))}


@register(KEY_ALERT_COMPONENT_NAME)
def build_key_alert_journal() -> KeyAlertJournal | None:
    """Component builder: feature 111's alert journal, bound to the environment.

    The journal is where §7's *Unrecoverable* row is kept, so a process that
    comes up against a deployment already in that state can ask
    :meth:`~nulloracle.keyalert.KeyAlertJournal.latest` rather than rediscover
    it by failing to decrypt — the question no other component in this member
    can answer, which is why the journal gets a name of its own.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its path from ``DATABASE_URL`` at build time, the same seam the
    fraction's, the guard's, the verdict's and the ledger's stores expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured journal is a discoverable state,
    and — this is the part worth stating — **the alert does not depend on it**.
    :func:`~nulloracle.keyalert.emit_unrecoverable_state` emits with
    ``journal=None``, because a deployment whose database is the thing that is
    broken still has to hear that its key is gone.  The component exists so the
    state can be *kept*, never so it can be *decided*.

    Like :func:`build_null_sidecar`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* a journal asks
    :meth:`~nulloracle.keyalert.KeyAlertJournal.resolve` or calls the store
    directly, where a named :class:`~nulloracle.errors.KsGuardError` is the
    right answer.  Construction performs no I/O — the path is resolved on first
    use — so composing the application never opens a database.

    Note what this builder deliberately does **not** do: it does not resolve the
    sidecar key, and it does not call a backend.  Feature 111's resolution is
    :func:`~nulloracle.backends.resolve_sidecar_key`, called by a process at its
    own startup where failing loudly is right — a KMS call or a ``sops``
    invocation during composition would put a network round trip inside
    ``create_app()`` and, worse, would raise an ``unrecoverable_state`` alert
    once per composition for every unrelated member to pay for.  The alert
    feature 111 emits is emitted by the caller that asked for the key.
    """
    return KeyAlertJournal.resolve()
