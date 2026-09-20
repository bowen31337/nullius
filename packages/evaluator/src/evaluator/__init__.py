"""The frozen evaluator, as a workspace component.

Features (app_spec.xml, "Frozen Evaluator Pipeline", feature 70):
persist ``evaluator_hash`` computed as a sha256 over the container image
digest plus the resolved configuration.
docs/nullius-tech-architecture.md §6 fixes the formula in one line —
``evaluator_hash = sha256(image_digest + config)`` — §12's determinism table
pins what it is for ("Pinned evaluator: container digest in
``evaluator_hash``; refuse cross-hash comparison"), and §16 states the
runtime constraint that makes the first term possible ("Docker,
digest-pinned, because ``evaluator_hash`` requires digests not tags"). The
module docstrings in this package record the mechanics; this one records the
three decisions a reader of the package's surface most needs.

*One identity, two terms, one spelling.* :func:`evaluator_digest` is the
formula; :class:`EvaluatorIdentity` is the formula's result together with
the terms it folded. The terms are carried beside the hash because a hash is
one-way — a row holding only the hash can say *that* two scores came from
different evaluators, never *how*, and feature 71's refusal is only
actionable when it can name the digest or the setting that moved. Both terms
have exactly one canonical spelling (the ``sha256:<64 hex>`` digest; compact,
key-sorted JSON), so two callers who mean the same evaluator compute the same
hash however they happened to write it down.

*The image must be pinned.* A tag-only reference is refused, not resolved:
resolving one would need a registry call at hash time and would fold
different digests on different days with no record that it had. A caller
holding a tag resolves it to a digest out of band, where the resolution can
be recorded. Canary feature 135 states the same refusal as its own feature.

*The row is assigned once.* :class:`EvaluatorIdentityStore` keys on the
hash and never updates a row in place — the hash is a pure function of its
terms, so a rewritten row could keep pointing at one evaluator while
describing another, and every score compared against it afterwards would be
wrong in the direction the system cannot detect. Rows are *read back* rather
than trusted, so a row edited outside this package fails to reconstruct
instead of loading as a plausible-looking lie.

*Nothing is resolved at construction.* The factory builds every registered
component on every ``create_app()`` — in a bare test process, in a factory
scan, and on the replay path, which architecture §1 forbids from reaching
the evaluator at all. So this package's builder must construct its service
without a pinned image, a database, or a parseable ``NULLIUS_EVALUATOR_CONFIG``:
each is resolved on first use, or at construction for a caller that asks for
the check with ``EvaluatorService.from_env(strict=True)``. The refusals are
unchanged — a tag-only image is still rejected, "persists" still needs
somewhere to persist to — they simply happen where the message is
informative instead of taking down composition for every unrelated feature
in the workspace.

Two contract notes for anyone composing or extending this component:

*Registration.* This package opts into the application factory by decorating
a zero-argument builder with :func:`app.module_loader.register` — in this
module, deliberately, not in a submodule: the loader re-executes a package's
``__init__`` on every composition but does not re-execute an already-cached
submodule, so a builder that lived in one would fire on the first
``create_app()`` of a process and silently drop out of every later one. The
factory discovers this package by scanning the declared workspace members —
no central file names it, and none may. All intra-package imports are
relative, so the package imports identically under its own name and under
the loader's scan-time name.

*It resolves the window, and executes the signal.* This member owns the
evaluator's *identity* — the thing §14.1 calls the first third of the
provenance triple — plus the host-side window resolution of feature 72: the
sealed snapshot sliced to the decision time, returning the point-in-time
universe and the partitions at or before it. Both are host-side, resolved
before any sandbox exists, and both are cheap to import — the identity is
what a score is stamped *with*, the window is what it is computed *over*,
and neither touches the environment at import time. Feature 73 adds the
sandboxed execution of step 2: :func:`execute_signal` runs a signal's
``signal`` entrypoint inside a resource-limited child process, over a window
materialized from the resolution and serialized over the payload channel,
returning one raw score vector per rebalance date. It stays import-cheap — the sandbox is a stdlib-only
process runner, and ``polars``/``pyarrow``/``contract`` are reached lazily on
the child path, so composing the application (and the replay path §1 forbids
from reaching the evaluator) pays no numerics cost for importing this member.
Feature 74 adds pipeline step 3: :func:`normalize_scores` turns a raw score
vector into a comparable one by ranking then cross-sectional z-scoring — the
magnitude an author chose is thrown away, and the symbol's rank is rescaled
against its cross-section's own mean and population standard deviation, so two
authors who agree on order but disagree on scale land on the same footing. It
stays import-cheap the same way: ``polars`` is reached only when a vector is
actually normalized, so composing the application pays no numerics cost for
importing this member. Feature 75 adds pipeline step 4: :func:`align_targets`
pairs forward returns with the score grid — one target series per horizon, at
the five horizons :data:`HORIZONS` pins, stepping in bars on the market grid —
and it is the cheapest import in this package so far, stdlib-only with no
lazily-reached numerics at all, because a target series is keyed data, not a
frame. Feature 76 adds pipeline step 5: :func:`gate_targets` asks the null
oracle for the target series — the one substitution the pipeline allows and
the only ask in this package — and :func:`check_targets_gated` certifies
that a bundle held downstream is the gate's own answer over the alignment
it gates, so a target series that arrived by any other door is refused; it
is stdlib-only the same way, because the oracle call is an injected seam —
the gate holds no socket, only records. Feature 79 adds pipeline step 7:
:func:`apply_costs` nets the venue's fee schedule out of the gate's own
answer — ``post_cost = gross − charge``, per symbol, per bar, per horizon —
and :func:`persist_signal_returns` writes the series down, so the artifact
§9.2 calls the key one (``signal_returns.parquet``, "per-symbol, per-period,
post-cost ← enables ir_marginal") exists as soon as the step runs. It is
stdlib-only too, and pointedly so: the fee arithmetic is *not* here. §6.2
requires one shared cost library for research evaluation and live execution,
and feature 69 refuses a second implementation of the fee schedule — so the
charges arrive as an injected seam (:data:`CostSchedule`), the same shape
§7.2's oracle and feature 73's ``materialize`` use, and this member's
contribution is the pairing rather than the prices. The step also *forwards*
§7.2's opaque budget directive untouched, because the steps that consume it
(features 80, 83 and 84) receive step 7's record rather than the gate's, and
feature 84's trial charge has to be written even when an evaluation failed —
so a bit dropped here is one no later step can go back for. Feature 80 adds the first of
step 8's metrics: :func:`compute_node_metrics` reduces step 7's post-cost returns, over the
shortest horizon the priced panel covers and the *same* per-date Spearman coefficient feature
81 measures, into four scalars — ``ic_mean`` (the mean information coefficient), ``ic_tstat``
(the mean over the standard error of the mean of the per-date coefficients), ``ir_standalone``
(the equal-weight book's information ratio) and ``turnover`` (the equal-weight book's mean
per-date fractional turnover) — and :func:`persist_node_metrics` writes them down, one row per
evaluation per cost model, beside the per-date IC series they reduce from, so the tree member's
node row (feature 85) and the live loop read back a scalar that is checked against its own
series. The two stay import-cheap the way the whole step does: stdlib-only, with the returns
and the scores arriving as *values* — the Polars boundary stays at the edge of the package —
so no member is imported and no return is repriced. Feature 82 adds the first two of step 8's
metrics: :func:`estimate_capacity` sizes the largest equal-weight book
whose square-root-law impact drag leaves half of the measured post-cost
edge — the dollar answer to the PRD's "works on $50k but not $50M" — and
:func:`attribute_regimes` splits that same edge across the named strata of
feature 58's causal labels, with :func:`persist_capacity` writing both
halves in one transaction as the durable source the artifacts member's
``regime_attribution.json`` (feature 172) reads back. The two stay
import-cheap the way the whole step does: stdlib-only, with the liquidity
and the labels arriving as *values* — the sealed dollar volumes and the
labeler's answer, the same seam the closes arrive through — so no member
is imported and no fit is restated. Feature 81 adds step 8's decay half:
:func:`compute_decay_profile` measures the information coefficient at each
of the five horizons — the Spearman rank correlation of step 3's normalized
scores against step 7's *post-cost* returns, over the symbols each date's
two sides share — and :func:`persist_decay_profile` writes the result down
as the stored array §9.2 files as ``decay_profile.json``, positional over
the spec's axis with ``None`` for a horizon the window was too short to
measure. The coefficient is the *same* rank transform feature 74 pins for
the scores, so the profile measures the order the evaluator committed to
rather than a second definition of agreement, and it is measured against
priced returns so the entry at horizon ``h`` sits on one axis with the
capacity feature 82 sizes at that horizon. It stays import-cheap the way
the whole step does: stdlib-only, with the scores arriving as a value — the
Polars boundary stays at the edge of the package — so no member is imported
and no normalization is restated. Feature 84 adds step 11:
:func:`debit_trial` charges the trial ledger for the evaluation — one
irreversible row, idempotently keyed by the node, carrying §8's four-way
outcome and the budget directive step 7 forwarded — and it is deliberately
shaped to run on the failure path, because §6.1's note is the feature:
step 11 happens even when the node fails, a failed evaluation still
consumed a hypothesis, and :func:`failure_outcome` is the spelling that
classifies the pipeline's own failures (a sandbox timeout, a crash, a
raised step) into the outcome the charge carries. It stays stdlib-only:
the ledger itself is an injected structural seam (the ledger member's
``TrialLedger`` satisfies it), so this member imports no sibling and owns
no table — the honest ``K`` counter is the ledger's to keep, and this
step's contribution is the charge, the outcome, and the guarantee the
write happens however the evaluation ended. The rest of the pipeline
(the tripwires and the final persist) is the rest of this category's
features, and
each layers on this identity, this window, this execution, this
normalization, this alignment, this gate and this pricing
rather than beside them: a score that cannot name its evaluator cannot be
compared, a score computed over a window that reaches past its decision time
is look-ahead, a raw score that is not validated against the contract cannot
be trusted, a score that has not been normalized to a common scale cannot
be compared across authors, a metric computed against targets that were not
aligned to the grid it scored on measures nothing, a metric computed
against targets that did not come through the gate measures a world nobody
ran, a metric computed against returns whose fee assumptions and
deductions are not on the record cannot be defended to anyone who asks what
it cost to earn them, and an evaluation whose charge was never written is a
hypothesis the honest K counter never counted, however it ended.
Keeping the import this cheap also keeps the replay path importable —
architecture §1 forbids replay from reaching the evaluator at all, so the
less this package does at import time, the less there is to accidentally
invoke.
"""

from app.module_loader import register

from ._config import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    EvaluatorConfig,
    canonical_config,
    resolve_config,
)
from ._errors import (
    EvaluatorAlignmentError,
    EvaluatorArtifactError,
    EvaluatorCapacityError,
    EvaluatorConfigError,
    EvaluatorCostError,
    EvaluatorDecayError,
    EvaluatorDebitError,
    EvaluatorEmbargoError,
    EvaluatorError,
    EvaluatorGateError,
    EvaluatorIdentityError,
    EvaluatorImageError,
    EvaluatorMarginalError,
    EvaluatorMetricsError,
    EvaluatorPurgeError,
    EvaluatorSandboxError,
    EvaluatorSignalError,
    EvaluatorStoreError,
    EvaluatorWindowError,
)
from ._identity import (
    EVALUATOR_HASH_LENGTH,
    EvaluatorIdentity,
    evaluator_digest,
    evaluator_identity,
    normalize_evaluator_hash,
)
from ._image import (
    DIGEST_ALGORITHM,
    DIGEST_HEX_LENGTH,
    ImageRef,
    coerce_image_ref,
    image_digest,
    parse_image_ref,
)
from ._sandbox import (
    DEFAULT_CPU_S,
    DEFAULT_MEM_MB,
    DEFAULT_PIDS,
    DEFAULT_WALL_S,
    SandboxLimits,
    SandboxResult,
    SignalSandbox,
)
from ._execute import (
    RawScoreVector,
    SignalExecution,
    execute_signal,
)
from ._normalize import (
    EvaluatorNormalizeError,
    normalize_scores,
)
from ._align import (
    HORIZONS,
    AlignedTargets,
    TargetSeries,
    align_targets,
)
from ._purge import (
    PurgeCheck,
    check_fold_purged,
)
from ._embargo import (
    EmbargoCheck,
    check_fold_embargoed,
)
from ._gate import (
    NULL_GATE_STEP,
    GateCheck,
    GatedTargets,
    Oracle,
    OracleRequest,
    OracleResponse,
    check_targets_gated,
    gate_targets,
)
from ._costs import (
    COST_STEP,
    CostModelRef,
    CostQuote,
    CostRequest,
    CostSchedule,
    PostCostReturns,
    PostCostSeries,
    apply_costs,
    cost_model_ref,
)
from ._cost_store import (
    SIGNAL_RETURNS_GRID_TABLE,
    SIGNAL_RETURNS_TABLE,
    PostCostStore,
    load_signal_returns,
    persist_signal_returns,
)
from ._capacity import (
    CAPACITY_STEP,
    EDGE_SURVIVAL_FRACTION,
    IMPACT_COEFFICIENT,
    CapacityEstimate,
    HorizonCapacity,
    RegimeAttribution,
    StratumAttribution,
    StratumSlice,
    attribute_regimes,
    estimate_capacity,
)
from ._capacity_store import (
    NODE_CAPACITY_TABLE,
    REGIME_ATTRIBUTION_TABLE,
    CapacityStore,
    load_capacity,
    persist_capacity,
)
from ._decay import (
    DECAY_HORIZONS,
    DECAY_STEP,
    DecayProfile,
    HorizonDecay,
    compute_decay_profile,
)
from ._decay_store import (
    DECAY_PROFILE_TABLE,
    DecayStore,
    load_decay_profile,
    persist_decay_profile,
)
from ._metrics import (
    METRICS_HORIZON,
    METRICS_STEP,
    NodeMetrics,
    compute_node_metrics,
)
from ._metrics_store import (
    NODE_METRICS_TABLE,
    NodeMetricsStore,
    load_node_metrics,
    persist_node_metrics,
)
from ._marginal import (
    MARGINAL_IR_STEP,
    MarginalIR,
    compute_marginal_ir,
)
from ._marginal_store import (
    NODE_MARGINAL_IR_TABLE,
    NodeMarginalIRStore,
    load_marginal_ir,
    persist_marginal_ir,
)
from ._debit import (
    DEBIT_STEP,
    TRIAL_OUTCOMES,
    DebitedTrial,
    TrialCharge,
    charge_failure,
    debit_trial,
    failure_outcome,
)
from ._artifact import (
    PERSIST_STEP,
    ArtifactPayload,
    ArtifactWriter,
    render_decay_profile,
    render_exec_trace,
    render_regime_attribution,
    render_turnover_series,
)
from ._persist_store import (
    NODE_PERSIST_TABLE,
    NodeArtifactStore,
    NodePersistence,
    persist_node,
)
from ._service import ENV_IMAGE, EvaluatorService, build_evaluator_service
from ._window import (
    ROSTER_STREAM,
    SLICED_STREAMS,
    WindowResolution,
    resolve_window,
)
from ._store import (
    DATABASE_URL_ENV,
    IDENTITY_TABLE,
    EvaluatorIdentityStore,
    identity_from_row,
)

__all__ = [
    # Feature 70 — the identity
    "EVALUATOR_HASH_LENGTH",
    "EvaluatorIdentity",
    "evaluator_digest",
    "evaluator_identity",
    "normalize_evaluator_hash",
    # Feature 74 — the normalization
    "EvaluatorNormalizeError",
    "normalize_scores",
    # Feature 75 — the target alignment
    "EvaluatorAlignmentError",
    "HORIZONS",
    "AlignedTargets",
    "TargetSeries",
    "align_targets",
    # Feature 77 — the cross-validation purge
    "EvaluatorPurgeError",
    "PurgeCheck",
    "check_fold_purged",
    # Feature 78 — the cross-validation embargo
    "EvaluatorEmbargoError",
    "EmbargoCheck",
    "check_fold_embargoed",
    # Feature 76 — the null gate
    "NULL_GATE_STEP",
    "GateCheck",
    "GatedTargets",
    "Oracle",
    "OracleRequest",
    "OracleResponse",
    "check_targets_gated",
    "gate_targets",
    # Feature 79 — applying the cost model
    "COST_STEP",
    "CostModelRef",
    "CostQuote",
    "CostRequest",
    "CostSchedule",
    "PostCostReturns",
    "PostCostSeries",
    "EvaluatorCostError",
    "apply_costs",
    "cost_model_ref",
    # Feature 81 — the decay profile
    "DECAY_HORIZONS",
    "DECAY_STEP",
    "DecayProfile",
    "HorizonDecay",
    "compute_decay_profile",
    # Feature 81 — persisting the stored array
    "DECAY_PROFILE_TABLE",
    "DecayStore",
    "load_decay_profile",
    "persist_decay_profile",
    # Feature 80 — the four node metrics
    "METRICS_HORIZON",
    "METRICS_STEP",
    "NodeMetrics",
    "compute_node_metrics",
    # Feature 80 — persisting the four scalars
    "NODE_METRICS_TABLE",
    "NodeMetricsStore",
    "load_node_metrics",
    "persist_node_metrics",
    # Feature 83 — the marginal information ratio
    "MARGINAL_IR_STEP",
    "MarginalIR",
    "compute_marginal_ir",
    # Feature 83 — persisting the incremental information ratio
    "NODE_MARGINAL_IR_TABLE",
    "NodeMarginalIRStore",
    "load_marginal_ir",
    "persist_marginal_ir",
    # Feature 84 — the trial charge
    "DEBIT_STEP",
    "TRIAL_OUTCOMES",
    "DebitedTrial",
    "TrialCharge",
    "charge_failure",
    "debit_trial",
    "failure_outcome",
    # Feature 85 — the final pipeline step: artifact to ART, scalars to TREE
    "PERSIST_STEP",
    "EvaluatorArtifactError",
    "ArtifactPayload",
    "ArtifactWriter",
    "NODE_PERSIST_TABLE",
    "NodeArtifactStore",
    "NodePersistence",
    "persist_node",
    "render_decay_profile",
    "render_exec_trace",
    "render_regime_attribution",
    "render_turnover_series",
    # Feature 79 — persisting the post-cost signal returns
    "SIGNAL_RETURNS_GRID_TABLE",
    "SIGNAL_RETURNS_TABLE",
    "PostCostStore",
    "load_signal_returns",
    "persist_signal_returns",
    # Feature 82 — the capacity estimate and the regime attribution
    "CAPACITY_STEP",
    "EDGE_SURVIVAL_FRACTION",
    "IMPACT_COEFFICIENT",
    "CapacityEstimate",
    "HorizonCapacity",
    "RegimeAttribution",
    "StratumAttribution",
    "StratumSlice",
    "EvaluatorCapacityError",
    "attribute_regimes",
    "estimate_capacity",
    # Feature 82 — persisting both into the node artifact record
    "NODE_CAPACITY_TABLE",
    "REGIME_ATTRIBUTION_TABLE",
    "CapacityStore",
    "load_capacity",
    "persist_capacity",
    # Feature 70 — the first term: the pinned container image
    "DIGEST_ALGORITHM",
    "DIGEST_HEX_LENGTH",
    "ImageRef",
    "coerce_image_ref",
    "image_digest",
    "parse_image_ref",
    # Feature 70 — the second term: the resolved configuration
    "DEFAULT_CONFIG",
    "ENV_CONFIG",
    "EvaluatorConfig",
    "canonical_config",
    "resolve_config",
    # Feature 70 — persistence
    "DATABASE_URL_ENV",
    "IDENTITY_TABLE",
    "EvaluatorIdentityStore",
    "identity_from_row",
    # The composed component
    "ENV_IMAGE",
    "EvaluatorService",
    "build_evaluator_service",
    # Errors
    "EvaluatorConfigError",
    "EvaluatorDecayError",
    "EvaluatorDebitError",
    "EvaluatorError",
    "EvaluatorGateError",
    "EvaluatorIdentityError",
    "EvaluatorImageError",
    "EvaluatorMarginalError",
    "EvaluatorMetricsError",
    "EvaluatorSandboxError",
    "EvaluatorSignalError",
    "EvaluatorStoreError",
    "EvaluatorWindowError",
    # Feature 72 — the host-side window resolution
    "ROSTER_STREAM",
    "SLICED_STREAMS",
    "WindowResolution",
    "resolve_window",
    # Feature 73 — the sandboxed signal execution
    "DEFAULT_CPU_S",
    "DEFAULT_MEM_MB",
    "DEFAULT_PIDS",
    "DEFAULT_WALL_S",
    "SandboxLimits",
    "SandboxResult",
    "SignalSandbox",
    "RawScoreVector",
    "SignalExecution",
    "execute_signal",
]

__version__ = "0.1.0"


@register("evaluator")
def _registered_evaluator_service() -> EvaluatorService:
    """Component builder: the evaluator service, configured from the environment.

    Constructs without touching the environment's *values*: the image, the
    store and the configuration override are all resolved on first use, so
    this builder cannot fail composition (see the module docstring). The
    refusals they carry are unchanged — an unpinned or tag-only image is
    rejected, as is a missing store — they simply land at the first call that
    needs them, where the message names the deployment's own
    misconfiguration. A caller that wants the check at startup uses
    ``EvaluatorService.from_env(strict=True)``.
    """
    return build_evaluator_service()
