"""The scoring plugin: the per-world objective and the aggregation over
worlds.

Implements app_spec.xml, "Objective Scoring & CVaR Aggregation" — feature
256, *"System computes the per-world objective starting from out-of-sample
information ratio of the committed pick, which returns a scalar world
score"* — on the formula docs/alpha-engine-prd.md §7.1 states (line 318)
and docs/nullius-tech-architecture.md §10.3 restates (line 495):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # statistical budget consumed
            − β₂ · null_pick_rate               # … five more terms, §7.1

app_spec.xml's M3 phase note names what the category as a whole is for:
*"Build deterministic replay, the full objective with regime-stratified
aggregation"*.  This member is the objective's half of that sentence, and
feature 256 is its head: the leading term and the scalar it starts.  The
six β-adjustments (features 257 through 262), the cross-world CVaR
aggregation (263-264), the scorer-process calibration figures (265-269)
are this member's later features — each arriving as its own law over the
:class:`~scoring.WorldScore` this one answers, through the
:meth:`~scoring.WorldScore.adjusted` seam, never by rewriting the
measurement underneath.

This package is a workspace member discovered by convention.  The module
loader (``app.module_loader``) scans the members the root
``pyproject.toml`` declares, imports each package, and composes whatever
the package's ``@register`` builder contributes — so the registration at
the foot of this module is the entire wiring story.  Nothing edits a
registry, router or factory to make the scoring plugin exist; importing
this module *is* joining the application.  All intra-package imports are
relative so the package imports identically under its own name and under
the loader's scan-time name.

**What composes, and why the objective is a component at all.**  The
builder contributes :func:`~scoring.world_objective` itself — the
callable — under the plugin name the spec's features carry
(``plugin="scoring"``).  A pure function is an unusual component in a
workspace whose members mostly contribute deployment state, and the
choice is deliberate on both of its sides:

* the objective never degrades.  Every store-bound builder in this
  workspace must answer ``None`` for a deployment that names nothing
  (``DATABASE_URL`` absent, ``ARTIFACT_ROOT`` unset), because its
  contribution *is* deployment state; the objective's whole
  configuration is the arithmetic, so its builder cannot fail, needs no
  environment, and composes to the same callable in every process — the
  property :func:`bootstrap.hyperparameter_world` makes for a generated
  world, held here for a formula;
* the cross-member seam is composition.  A workspace member never
  imports another workspace member and reaches shared shapes through
  ``app.*`` — and the member that will need this one is easy to name:
  the replay engine's scoring step (docs §10.1's
  ``score(pick, book, epoch, revealed, rounds)`` and §478's
  ``score = ...`` beside it) routes every world's leading term through
  this objective, and feature 222's
  :meth:`~policy_runtime.Termination.score` hands a scorer per
  termination.  The composed callable under ``"scoring"`` is how those
  callers reach the law without importing the member — the same reason
  the contract member contributes its ABI and not a service.

**The member's own surfaces.**  Feature 256's law is
:mod:`scoring._objective` — :func:`~scoring.world_objective` (the verb),
:class:`~scoring.WorldScore` (the value), :data:`~scoring.IR_DATES_MINIMUM`
(the floor beneath the ratio), and the one error
:class:`~scoring.WorldObjectiveError` from :mod:`scoring.errors`.  The
information ratio's spelling (mean over population standard deviation,
feature 80's) is restated there rather than imported from the evaluator
member — a member never imports a member — so a world score's leading
term and the node metrics a policy read in-sample are one axis by
construction, which is prd §7.1's Change A whole: scored on a sequestered
epoch, on the same ruler the diagnostics spoke.

**No persistence here, by the same law that keeps the arithmetic pure.**
The ``replay_score`` row is the replay plugin's (feature 255); this
member answers the value it is written from, exactly as migration 0109
shapes it.  The features of this category that *do* own state — feature
265's scorer process holding the sidecar key, feature 267's per-campaign
``FDR_deploy`` — will take their own components beside this one when
they land, the growth pattern ``app.modules.bootstrap`` took for its
pool: a second component name, a sibling seat, this module's surface
untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.module_loader import register

from ._objective import IR_DATES_MINIMUM, WorldScore, world_objective
from .errors import ScoringError, WorldObjectiveError

if TYPE_CHECKING:  # pragma: no cover - typing only; the annotation is lazy
    from collections.abc import Callable

__all__ = [
    "COMPONENT_NAME",
    "IR_DATES_MINIMUM",
    "ScoringError",
    "WorldObjectiveError",
    "WorldScore",
    "world_objective",
]

__version__ = "0.1.0"

#: The component name this member registers under — the plugin name the
#: spec's features carry (``plugin="scoring"``), so the component key, this
#: member's seat (:mod:`app.modules.scoring`) and the spec cannot drift
#: apart.  A later feature of this category that owns its own deployment
#: state (265's scorer process, 267's FDR store) registers its own name
#: beside this one rather than widening this one, the way
#: ``bootstrap-pool`` sits beside ``bootstrap``.
COMPONENT_NAME = "scoring"


@register(COMPONENT_NAME)
def build_world_objective() -> Callable[..., WorldScore]:
    """Component builder: the per-world objective itself (feature 256).

    Takes no arguments — that is the factory's registration protocol — and
    contributes :func:`~scoring.world_objective` unchanged, so a composed
    application carries the one callable every world's leading term is
    computed through (prd §7.1, docs §10.3) and the members that need it
    reach it through the app package rather than importing this member.

    Never raises and reads no environment — there is nothing to read.  The
    objective's whole configuration is the arithmetic; a deployment cannot
    misconfigure it, an empty workspace cannot degrade it, and the factory
    building this component on every ``create_app()`` call costs one
    attribute lookup.  That is not a boast about this feature but the
    property the objective must have to be the ranking's floor: a score
    that could fail to compose would be a ranking that silently drops the
    worlds it was asked to compare.

    A second spelling of the builder — the sibling members' "ordinary
    function a script calls directly" — is deliberately *not* shipped
    here, because the builder's contribution already is one: the callable
    a direct caller wants is :func:`~scoring.world_objective` itself,
    reached from this member's own namespace.
    """
    return world_objective
