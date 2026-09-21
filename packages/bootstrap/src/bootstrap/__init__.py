"""The bootstrap plugin: non-financial ground-truth worlds.

Implements app_spec.xml, "Bootstrap Worlds" — feature 181, *"System
exposes a hyperparameter search world over a fixed model and dataset,
which returns a ground-truth score per node"*; feature 184, the identical
``question.*`` interface every bootstrap world fronts; feature 185,
*"System charges no statistical budget for a bootstrap world, persisting
charges_budget as false on those trials"*; feature 188, *"System
persists 40 to 50 generated bootstrap worlds into the replay pool on
demand"*; feature 189, *"System labels every bootstrap node with ground
truth, which returns perfect sensitivity and specificity references for
calibration"*; feature 190, the ported-world adapter; and feature 191,
*"System persists source commit and dataset manifest hash for every
ported world, which rejects a world whose recorded values no longer
match its upstream"*; and feature 186, *"System tracks financial world
count independently from bootstrap world count, which returns both figures
separately"* — on the phase
docs/nullius-tech-architecture.md §10.6 opens:

    Build the non-financial ground-truth worlds so pool size becomes a
    compute problem rather than a calendar problem.

This package is a workspace member discovered by convention.  The module
loader (``app.module_loader``) scans the members the root
``pyproject.toml`` declares, imports each package, and composes whatever
the package's ``@register`` builder contributes — so the registration at
the foot of this module is the entire wiring story.  Nothing edits a
registry, router or factory to make the bootstrap plugin exist;
importing this module *is* joining the application.  All intra-package
imports are relative so the package imports identically under its own
name and under the loader's scan-time name.

**What this category is for.**  §10.6 states the problem before it states
the answer: *"A replay world need not be a crypto campaign"*, and the
paper's own result is evidence *"that the exploration policy is learning
problem **structure** rather than market specifics."*  §10.3.1's
meta-selection discipline then puts a hard precondition in the way — a
paired comparison on financial worlds needs on the order of 53 of them —
and a pool that can only grow by waiting for markets to close is a pool
that grows on a calendar.  Bootstrap worlds are the escape: they *"give
perfect labels, zero statistical-budget cost, and no dependence on market
time"*, and §10.6's instruction is that they are therefore *built*, 40-50
at a time, rather than awaited.

**What this member ships.**  Feature 181's world, feature 188's pool,
and the pieces the world is made of, all importable directly for the
sibling features of this category:

* **The world** (:mod:`bootstrap._world`).  A
  :class:`~bootstrap.HyperparameterWorld` is a *fixed model* — an
  expression over six features, published in full because a bootstrap
  world's answer is *supposed* to be known — plus a *fixed dataset*
  generated from the world's seed, plus the lattice of hyperparameters a
  node may propose.  :meth:`~bootstrap.HyperparameterWorld.label` answers
  a node's ground-truth score: the held-out coefficient of determination
  of the model fitted with that node's hyperparameters, beside the
  training score and the fitted coefficients.  The label is a pure
  function of ``(world, node)``, so a replay may reveal cells in whatever
  order a policy chooses and every label is still the same number.

* **The lattice** (:mod:`bootstrap._world`).  A node *is* a point of a
  rooted lattice over four axes — polynomial degree, whether the design
  carries pairwise interactions, whether its columns are standardised, and
  the ridge strength.  A legal move is one axis by one position, so the
  space is connected from its declared default: a policy that only ever
  moves along edges can reach every cell, which is what makes the world
  addressable by the structural vocabulary §10.6.1's ``CellMeta`` speaks.

* **The honest label** (:mod:`bootstrap._fit`).  The fit is an ordinary
  ridge regression solved through a Cholesky factorisation, in
  :func:`math.fsum` throughout, so the answer is exactly rounded and
  independent of the platform's BLAS and of the order the rows arrived in
  — §12's determinism contract met by construction rather than by
  tolerance.  A design the world's own sample does not span raises
  :class:`~bootstrap.BootstrapScoringError` rather than being jittered
  into a plausible number, because a stand-in score in a pool whose whole
  value is *honest labels* is worse than no score at all.

* **The policy question interface** (:mod:`bootstrap._question`).  Feature
  184 wraps the world in the one object a policy is handed — a
  :class:`~bootstrap.BootstrapQuestion`, built by :func:`~bootstrap.
  question_for` — that exposes the identical ``question.*`` API
  docs/nullius-tech-architecture.md §11 names: :meth:`~bootstrap.
  BootstrapQuestion.observed` (the revealed cells and their honest
  observations), :meth:`~bootstrap.BootstrapQuestion.legal_actions` and
  :meth:`~bootstrap.BootstrapQuestion.legal_roots` (the walk's moves and
  its start), :meth:`~bootstrap.BootstrapQuestion.meta` (the structural
  :class:`~bootstrap.CellMeta` — branch, depth, parent, theme_root),
  :meth:`~bootstrap.BootstrapQuestion.probe_batch`,
  :meth:`~bootstrap.BootstrapQuestion.budget_remaining` (the whole budget,
  always — §10.6's zero statistical-budget cost) and
  :meth:`~bootstrap.BootstrapQuestion.commit`.  The question is bound to
  the world it wraps and adds only the reveal bookkeeping a replay needs
  and a world must not hold, so one policy runs unmodified against a
  bootstrap world and returns scores comparable with the financial pool —
  the identical interface every bootstrap world exposes.

* **The trials' budget bit** (:mod:`bootstrap._trial`).  Feature 185's
  persistence half: §10.6 gives a bootstrap world *"perfect labels, zero
  statistical-budget cost, and no dependence on market time"*, and the
  zero-cost clause reaches the accounting through §8's
  ``charges_budget`` column — the one bit ``K_effective`` (feature 93)
  filters on.  A :class:`~bootstrap.BootstrapTrialLedger` records *those
  trials* — the probes a policy makes through the question interface,
  revealed by the question's own ``probe_batch`` so the record and the
  reveal cannot drift apart — into ``bootstrap_trial``, a table this
  member owns in the database ``DATABASE_URL`` names (the same one the
  worlds and ``replay_score`` live in), one row per newly revealed cell,
  attributed from the observation's own payload.  Every row writes
  ``charges_budget`` as the literal ``0`` of the INSERT — the write has
  no parameter for the bit, because §10.6 publishes that a bootstrap
  world's probes are free — and the table's own
  ``CHECK (charges_budget = 0)`` makes the sentence a fact about the
  store rather than a convention of its writers: no bootstrap trial, and
  no hand that reached past the writer, can ever inflate the count
  feature 93 takes.

* **The seeded stream** (:mod:`bootstrap._stream`).  Every number a world
  contains is a pure integer-hash draw on a *cell*, not a step of a
  generator: this is the property that makes a label independent of the
  path a policy took to the node, and the reason a world's identity can
  simply *be* its seed (§10.6.1's provenance rule — *"An upstream that
  changes is a different world, not an updated one"* — has nothing to
  check when the world has no upstream).

* **The pool** (:mod:`bootstrap._pool`).  A
  :class:`~bootstrap.BootstrapPool` is the replay pool's bootstrap half:
  ``persist_worlds`` draws 40-50 seeds from a pool seed (the SplitMix
  stream — the one place a generator-shaped use of the hash is idiomatic,
  because a pool is authored as a batch where a world's cells are
  content-addressed), names each world, and upserts one identity row per
  world into ``bootstrap_world`` — the database ``replay_score`` lives
  in, so *"persists into the replay pool"* is a statement about the pool
  the dreaming loop reads.  A re-run is a refresh (``created_at`` keeps
  the world's first authoring instant), a size outside 40-50 is refused
  rather than clamped, and a second pool over a *different* seed adds
  worlds it can name rather than mutating rows it cannot.

* **The ported world and its seat** (:mod:`bootstrap._ported`,
  :mod:`bootstrap._pool`).  Feature 190's
  :class:`~bootstrap.PortedWorld` fronts an external ground-truth
  environment through the identical interface — its labels are the
  environment's own, carried unchanged — and its identity is not a seed
  but the :class:`~bootstrap.Provenance` that pinned them: the source
  commit of the upstream code and the dataset manifest of the
  label-bearing data.  Feature 191 gives that identity its persistence:
  ``persist_ported_world`` seats the two digests into the same
  ``bootstrap_world`` table the authored draw writes, under the
  ``ported`` domain, with no seed and no draw, and
  ``verify_ported_world`` is the check the category's provenance rule
  turns on — the digests the row *recorded* against the digests the
  upstream *now shows*, and a world whose two no longer match is
  refused, not re-hashed (§10.6.1: *"an upstream that changes is a
  different world, not an updated one"*).

* **The ground truth of every node** (:mod:`bootstrap._truth`).
  Feature 189's reference: :func:`~bootstrap.ground_truth` labels every
  cell of a world's lattice with its class — a **discovery** when the
  node's honest held-out ``R²`` clears the published evidential bar
  :data:`~bootstrap.DISCOVERY_BAR`, a **null** when it does not — read
  off the same answer surface the question interface calls through, so
  the authored world, the ported world and the composed world are
  labelled through one duck-typed code path.  The counts those labels
  make are integers and the rates are single divisions, so the
  sensitivity and specificity a declaration scores
  (:meth:`~bootstrap.GroundTruth.calibrate`) are exact — *perfect
  references* in the feature's own sense — and the declaration naming
  exactly the discoveries (:meth:`~bootstrap.GroundTruth.perfect`)
  scores ``1.0`` / ``1.0`` outright: the answer key a financial pool's
  estimated rates are calibrated against, published.

* **The two pools' sizes, counted apart** (:mod:`bootstrap._census`).
  Feature 186's answer to §10.6's *"Report the two pools separately"*:
  :func:`~bootstrap.world_census` takes a bootstrap pool and returns a
  :class:`~bootstrap.WorldCensus` holding ``n_financial`` and
  ``n_bootstrap`` as two figures.  Both are *read from the one database*
  the pool resolves — the bootstrap figure through
  :meth:`~bootstrap.BootstrapPool.world_count` (authored and ported alike,
  §10.6's *"both qualify"*), the financial figure as the distinct
  ``replay_score.world_id`` values ``bootstrap_world`` does not hold, so a
  bootstrap world can raise ``n`` but never ``n_financial`` (§10.6.1's
  *"pads ``n``, never ``n_financial``"*).  A single count is deliberately
  absent: §12.1's ladder reads the total, so
  :attr:`~bootstrap.WorldCensus.total` exists and is documented as the
  ladder's reading, while :meth:`~bootstrap.WorldCensus.row` hands a
  report the two figures and nothing else.

* **The headline refusal** (:mod:`bootstrap._claim`).  Feature 187's
  verdict over feature 186's two figures: :func:`~bootstrap.
  rejects_dreaming_claim` takes a :class:`~bootstrap.DreamingClaim` — the
  basis a dreaming cycle asserts, :data:`~bootstrap.FINANCIAL_BASIS` when
  it rests on the gate's financial world count or :data:`~bootstrap.
  TOTAL_BASIS` when it rests on the ladder's bootstrap-padded sum — and
  the census, and answers whether the claim rests on bootstrap worlds
  alone.  A claim is refused when the financial figure the M3 gate reads
  (:data:`~bootstrap.M3_GATE_WORLDS` by default, §10.3.1's ``n > 53``)
  falls short of the gate yet the claim would proceed — either because it
  names the total as its basis or because the bootstrap half is what
  carries it over the gate.  When ``n_financial`` meets the gate the claim
  stands on the pool the gate was meant to see and is admitted.  It is a
  free function beside :func:`~bootstrap.world_census`, the way
  :func:`~bootstrap.ground_truth` is: the census reports the two figures
  and this module judges what a claim may be claimed to support, and the
  two figures are the seam between them.

**What this member deliberately does not ship.**  The things this member
does not ship are the ones that are statements about *callers* of its
labels rather than about the labels.  Feature 185 ships the trial's own
record — the ``charges_budget`` row (:mod:`bootstrap._trial`) — and
ships *only* that: the question keeps reporting the whole budget and
nothing here indexes, decrements or reports a budget of its own, because
a counter would be a budget and the budget is not the world's to keep.
Feature 187's verdict is shipped as a judgment the *caller* renders over
feature 186's two figures (:func:`~bootstrap.rejects_dreaming_claim`),
and no verdict lives inside the census or the pool themselves.  And
§10.3's ``FDR_deploy`` reweighting is the scorer's arithmetic over rates
this member makes exact, not a rate itself.  The world itself stays
reveal-history-free by design — a world that owned a reveal history
would be a world whose answers depended on it, which is why the
bookkeeping lives in the question (:mod:`bootstrap._question`) and not
in the world — and the pool, for its part, records identities and
refuses to record datasets, for the drift a cached dataset would invite
(§10.6.1's rule, the same one the ported half's digests exist to check).

**Two components, two questions.**  The world registers under
``"bootstrap"`` (:data:`COMPONENT_NAME`) and answers *what is the
composed bootstrap world?* — the one world a bare ``create_app()``
carries.  The pool registers under ``"bootstrap-pool"``
(:data:`POOL_COMPONENT_NAME`) and answers *what is the composed bootstrap
pool?* — the store a deployment's ``DATABASE_URL`` names, or ``None``
when nothing does.  Two names rather than one component with two faces,
the convention :mod:`tripwires` states for its own seats: the world is
ready the instant it is built and never degrades, while the pool is a
deployment state that may legitimately be absent, and a caller holding
``None`` from one wants a *refusal to author*, not a label — two facts
that different should not share one component key.

The tests that hold this package to §10.6 and to §10.3.1's reproducibility
live in ``packages/bootstrap/tests``, inside this member's own file claim,
rather than under the repository-level ``tests/`` tree — the placement the
artifacts, sandbox and canary members take for the same reason.
"""

from __future__ import annotations

from app.module_loader import register

from ._census import (
    REPLAY_SCORE_TABLE,
    REPLAY_SCORE_WORLD_COLUMN,
    WorldCensus,
    world_census,
)
from ._claim import (
    FINANCIAL_BASIS,
    M3_GATE_WORLDS,
    TOTAL_BASIS,
    DreamingClaim,
    claim_basis,
    rejects_dreaming_claim,
)
from ._fit import FitResult, fit_and_score, solve_cholesky
from ._pool import (
    DATABASE_URL_ENV,
    DEFAULT_POOL_SIZE,
    MAX_POOL_SIZE,
    MIN_POOL_SIZE,
    POOL_COMPONENT_NAME,
    POOL_DOMAIN,
    POOL_SEED,
    POOL_TABLE,
    PORTED_DOMAIN,
    BootstrapPool,
    PersistedPool,
    PortedWorldRecord,
    WorldRecord,
    draw_world_seed,
    world_id_for,
)
from ._ported import (
    DEFAULT_PORTED_WORLD_ID,
    PortedWorld,
    Provenance,
    ported_question_for,
    ported_world,
)
from ._question import (
    BOOTSTRAP_THEME_ROOT,
    BootstrapQuestion,
    CellMeta,
    Observation,
    question_for,
)
from ._stream import GOLDEN_GAMMA, MASK64, mix64, normal, uniform
from ._trial import (
    TRIAL_CHARGES_BUDGET,
    TRIAL_TABLE,
    BootstrapTrialLedger,
    TrialRecord,
)
from ._truth import (
    DISCOVERY_BAR,
    ConfusionMatrix,
    GroundTruth,
    NodeTruth,
    ground_truth,
)
from ._world import (
    AXIS_ORDER,
    DEFAULT_ALPHA,
    DEFAULT_DEGREE,
    DEFAULT_INTERACTIONS,
    DEFAULT_RIDGE,
    DEFAULT_STANDARDIZE,
    FEATURE_COUNT,
    FEATURE_SCALES,
    HOLDOUT_STRIDE,
    HYPERPARAMETER_AXES,
    INTERACTION_COEFFICIENTS,
    INTERCEPT,
    LINEAR_COEFFICIENTS,
    NOISE_SCALE,
    PRICED_ROWS,
    PRICED_SEED,
    SQUARE_COEFFICIENTS,
    Dataset,
    HyperparameterAxis,
    HyperparameterSetting,
    HyperparameterWorld,
    canonical_node_id,
    column_statistics,
    decode_node_id,
    design_columns,
    encode_node_id,
    generate_dataset,
    node_steps,
    setting_dimensions,
    setting_from_steps,
    split_indices,
)
from .errors import (
    BootstrapError,
    BootstrapPoolError,
    BootstrapScoringError,
    BootstrapWorldError,
)

__all__ = [
    "AXIS_ORDER",
    "BOOTSTRAP_THEME_ROOT",
    "DATABASE_URL_ENV",
    "DEFAULT_ALPHA",
    "DEFAULT_DEGREE",
    "DEFAULT_INTERACTIONS",
    "DEFAULT_POOL_SIZE",
    "DEFAULT_PORTED_WORLD_ID",
    "DEFAULT_RIDGE",
    "DEFAULT_STANDARDIZE",
    "DEFAULT_WORLD_ID",
    "DISCOVERY_BAR",
    "FEATURE_COUNT",
    "FEATURE_SCALES",
    "FINANCIAL_BASIS",
    "GOLDEN_GAMMA",
    "HOLDOUT_STRIDE",
    "HYPERPARAMETER_AXES",
    "HYPERPARAMETER_WORLD_ID",
    "INTERACTION_COEFFICIENTS",
    "INTERCEPT",
    "LINEAR_COEFFICIENTS",
    "M3_GATE_WORLDS",
    "MASK64",
    "MAX_POOL_SIZE",
    "MIN_POOL_SIZE",
    "NOISE_SCALE",
    "POOL_COMPONENT_NAME",
    "POOL_DOMAIN",
    "POOL_SEED",
    "POOL_TABLE",
    "PORTED_DOMAIN",
    "PRICED_ROWS",
    "PRICED_SEED",
    "REPLAY_SCORE_TABLE",
    "REPLAY_SCORE_WORLD_COLUMN",
    "SQUARE_COEFFICIENTS",
    "TOTAL_BASIS",
    "TRIAL_CHARGES_BUDGET",
    "TRIAL_TABLE",
    "BootstrapError",
    "BootstrapPool",
    "BootstrapPoolError",
    "BootstrapQuestion",
    "BootstrapScoringError",
    "BootstrapTrialLedger",
    "BootstrapWorldError",
    "CellMeta",
    "ConfusionMatrix",
    "Dataset",
    "DreamingClaim",
    "FitResult",
    "GroundTruth",
    "HyperparameterAxis",
    "HyperparameterSetting",
    "HyperparameterWorld",
    "NodeTruth",
    "Observation",
    "PersistedPool",
    "PortedWorld",
    "PortedWorldRecord",
    "Provenance",
    "TrialRecord",
    "WorldCensus",
    "WorldRecord",
    "build_bootstrap_pool",
    "build_hyperparameter_world",
    "canonical_node_id",
    "claim_basis",
    "column_statistics",
    "decode_node_id",
    "design_columns",
    "draw_world_seed",
    "encode_node_id",
    "fit_and_score",
    "generate_dataset",
    "ground_truth",
    "hyperparameter_world",
    "mix64",
    "node_steps",
    "normal",
    "ported_question_for",
    "ported_world",
    "question_for",
    "rejects_dreaming_claim",
    "setting_dimensions",
    "setting_from_steps",
    "solve_cholesky",
    "split_indices",
    "uniform",
    "world_census",
    "world_id_for",
]

#: The component name this member registers under — the plugin name the
#: spec's features carry (``plugin="bootstrap"``), so the component key, the
#: app-namespace seat (``src/app/modules/bootstrap``) and the spec cannot
#: drift apart.  Deliberately *not* ``bootstrap-hpo``: features 182
#: (feature selection) and 183 (symbolic regression) are siblings in this
#: category that share this member and this pool, and the pool is one
#: thing, so the member registers the *pool's* seat once rather than a
#: component per domain.
COMPONENT_NAME = "bootstrap"

#: The world id the composed application carries.  A stable, human-readable
#: id rather than a generated UUID: §10.6's pool is *reported per pool*, and
#: an operator reading a replay score or a coverage ledger wants to see
#: which world it came from.  Feature 188's pool builder draws further ids
#: and further seeds; this is the one world a bare ``create_app()``
#: carries, so composing the application is enough to have a world to
#: label against.
HYPERPARAMETER_WORLD_ID = "bootstrap-hpo-20260921"

#: A shorter alias for the same id, for callers that read the world id as
#: the *domain's* name rather than as one instance of it.
DEFAULT_WORLD_ID = HYPERPARAMETER_WORLD_ID


@register(COMPONENT_NAME)
def hyperparameter_world() -> HyperparameterWorld:
    """Component builder: the hyperparameter world the application carries.

    Takes no arguments — that is the factory's registration protocol — and
    builds a world bound to :data:`HYPERPARAMETER_WORLD_ID` and
    :data:`~bootstrap.PRICED_SEED`.  Construction performs no arithmetic:
    the dataset is generated on the first :meth:`~bootstrap.
    HyperparameterWorld.label` and not before, so composing an application
    that carries this world costs one object allocation — the stance
    feature 169's store and the null sidecar both take, and the reason a
    pool builder can hold 40-50 of these without paying for datasets it
    may never label against.

    The builder never raises and needs no configuration.  Every other
    path-configured component in this workspace has a deployment state it
    degrades to (``ARTIFACT_ROOT`` unset, ``DATABASE_URL`` absent); a
    generated world has none, because its whole configuration *is* its
    seed.  That is a property of §10.6 rather than an accident: the pool
    exists so that the precondition *"is a compute problem"* rather than a
    deployment problem, and a world that could fail to compose would put
    the precondition back where it started.
    """
    return HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)


#: A second spelling of the builder, for a caller that wants the world
#: without reaching for the composed application.  Not a component and not
#: registered — registering it would put two components of the same name in
#: the registry and the later import would silently win, the hazard
#: ``app.module_loader.Registration.add`` documents — so this is an
#: ordinary function a script or a sibling suite calls directly.
build_hyperparameter_world = hyperparameter_world


@register(POOL_COMPONENT_NAME)
def build_bootstrap_pool() -> BootstrapPool | None:
    """Component builder: the replay pool the worlds persist into (feature 188).

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application
    carries the pool for the deployment the process is actually running
    in.  It is this member's second component and, unlike the first, one
    that may legitimately be ``None``: the world's whole configuration is
    its seed, while the pool's is a deployment's database.

    Returns ``None`` when nothing names a relational store — the
    degrade-don't-break stance every store in this workspace takes toward
    an absent ``DATABASE_URL``, and the same one
    :func:`tripwires.build_poison_store` takes for the poison store.  An
    unconfigured pool is a discoverable state, and the operator who means
    to author §10.6's 40-50 worlds is the caller that must not find
    itself in it — which is why a pool that *must* exist is resolved
    explicitly (:meth:`bootstrap.BootstrapPool.resolve`) or refused
    against, never silently defaulted.

    Never raises — including for a URL whose scheme the store cannot
    speak.  The factory builds every registered component on every
    :func:`~app.module_loader.create_app` call, so a builder that raised
    would take composition down for every unrelated feature in the
    workspace; a process that *requires* a pool passes a URL to
    :class:`~bootstrap.BootstrapPool` directly, where a named
    :class:`~bootstrap.BootstrapPoolError` is the right answer.
    Construction performs no I/O — the path is resolved on first use —
    so composing the application never opens a database, and the worlds
    are authored only when a caller demands them
    (:meth:`~bootstrap.BootstrapPool.persist_worlds`): the "on demand" of
    the feature's own sentence, kept true at the composition seam.
    """
    return BootstrapPool.resolve()
