"""The bootstrap plugin: non-financial ground-truth worlds.

Implements app_spec.xml, "Bootstrap Worlds" — feature 181, *"System
exposes a hyperparameter search world over a fixed model and dataset,
which returns a ground-truth score per node"* — on the phase
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

**What this member ships.**  Feature 181's world, and the pieces it is
made of, all importable directly for the sibling features of this
category:

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

* **The seeded stream** (:mod:`bootstrap._stream`).  Every number a world
  contains is a pure integer-hash draw on a *cell*, not a step of a
  generator: this is the property that makes a label independent of the
  path a policy took to the node, and the reason a world's identity can
  simply *be* its seed (§10.6.1's provenance rule — *"An upstream that
  changes is a different world, not an updated one"* — has nothing to
  check when the world has no upstream).

**What this member deliberately does not ship.**  The policy-facing
runtime — the ``question.*`` object a policy is handed, the reveal
bookkeeping, the commit — belongs to features 184 (identical interface
across all bootstrap worlds), 189 (ground-truth labels as sensitivity and
specificity references) and 190-191 (the ported-world adapter and its
provenance check), all later features of this category; this member
answers *labels*, and a world that owned a reveal history would be a world
whose answers depended on it.  The pool builder that authors 40-50 worlds
is feature 188's.  The budget rule — *"System charges no statistical
budget for a bootstrap world"* — is feature 185's, and it is a statement
about what the *trial* records rather than about what the world computes,
so nothing here indexes, decrements or reports a budget.

The tests that hold this package to §10.6 and to §10.3.1's reproducibility
live in ``packages/bootstrap/tests``, inside this member's own file claim,
rather than under the repository-level ``tests/`` tree — the placement the
artifacts, sandbox and canary members take for the same reason.
"""

from __future__ import annotations

from app.module_loader import register

from ._fit import FitResult, fit_and_score, solve_cholesky
from ._stream import GOLDEN_GAMMA, MASK64, mix64, normal, uniform
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
from .errors import BootstrapError, BootstrapScoringError, BootstrapWorldError

__all__ = [
    "AXIS_ORDER",
    "DEFAULT_ALPHA",
    "DEFAULT_DEGREE",
    "DEFAULT_INTERACTIONS",
    "DEFAULT_RIDGE",
    "DEFAULT_STANDARDIZE",
    "DEFAULT_WORLD_ID",
    "FEATURE_COUNT",
    "FEATURE_SCALES",
    "GOLDEN_GAMMA",
    "HOLDOUT_STRIDE",
    "HYPERPARAMETER_AXES",
    "HYPERPARAMETER_WORLD_ID",
    "INTERACTION_COEFFICIENTS",
    "INTERCEPT",
    "LINEAR_COEFFICIENTS",
    "MASK64",
    "NOISE_SCALE",
    "PRICED_ROWS",
    "PRICED_SEED",
    "SQUARE_COEFFICIENTS",
    "BootstrapError",
    "BootstrapScoringError",
    "BootstrapWorldError",
    "Dataset",
    "FitResult",
    "HyperparameterAxis",
    "HyperparameterSetting",
    "HyperparameterWorld",
    "build_hyperparameter_world",
    "canonical_node_id",
    "column_statistics",
    "decode_node_id",
    "design_columns",
    "encode_node_id",
    "fit_and_score",
    "generate_dataset",
    "hyperparameter_world",
    "mix64",
    "node_steps",
    "normal",
    "setting_dimensions",
    "setting_from_steps",
    "solve_cholesky",
    "split_indices",
    "uniform",
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
