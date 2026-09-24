"""The scoring module — app-level entrypoint for the scoring workspace
member.

The implementation lives in the ``scoring`` workspace member
(``packages/scoring``, import name ``scoring``), which self-registers with
the application factory under the component name :data:`COMPONENT_NAME` —
scanning the workspace imports it, its ``@register`` builder fires, and
``create_app()`` composes the per-world objective the deployment scores
under (app_spec.xml feature 256: *System computes the per-world objective
starting from out-of-sample information ratio of the committed pick, which
returns a scalar world score* — the head of prd §7.1's and docs §10.3's
``V_i^m`` formula).

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/scoring/``): it exposes the composed component without
making the ``app`` package depend on any workspace member at import time.
Composition stays the factory's job — this module only asks the factory
for the component, and a module that cannot reach it (member not scanned,
workspace empty) returns ``None`` rather than failing import, mirroring
the factory's own "degrade, don't break" stance toward absent components.

**What the component is, and why the seat is shaped for it.**  The
``scoring`` component is not a store or a service but the objective
itself — :func:`scoring.world_objective`, the callable — because the
objective never degrades: it has no ``DATABASE_URL`` to be absent and no
``ARTIFACT_ROOT`` to be unset, its whole configuration being the
arithmetic (feature 80's one spelling of the information ratio, mean over
population standard deviation, restated rather than imported from the
evaluator member).  A member that needs the law — the replay engine's
scoring step, docs §10.1's ``score(pick, book, epoch, revealed, rounds)``,
routing every world's leading term — reaches it here, through the app
package, because a workspace member never imports another workspace
member.  The callable is the component the way the contract member's ABI
is: the shared shape, contributed once, consumed by whoever composes.

**The one question this seat answers** is *what is the composed per-world
objective?* — and nothing else.  It deliberately does not re-export
:class:`scoring.WorldScore`, :func:`scoring.world_objective`,
:data:`scoring.IR_DATES_MINIMUM` or the error vocabulary: a caller who
holds the callable calls it and gets the value, and a second spelling of
the member's surface here would be a second thing to keep in sync — the
discipline every seat in this workspace states, and the reason the
``__all__`` assertion in the member's suite pins this module to exactly
two names.  A caller that wants the value types (a sibling feature of the
category wiring its own terms onto ``WorldScore.adjusted``) reaches the
member's own namespace, the way the policy-runtime member's free seams —
229's ``plan_grid``, 230's admission gate, 223's prefix view — are reached
from theirs.

Where the composed component is ``None``, that is a statement about
composition, not an error: the member was not scanned, or the workspace is
empty, so there is no objective composed into *this* application.  It is
not a statement about the deployment — unlike the store-bound components
whose ``None`` means "nothing named a database", this member's builder
cannot fail and reads no environment, so a ``None`` here can only mean
the member itself was absent from the scan.  A caller that needs the
objective and finds ``None`` must not proceed to score anything: a
ranking computed over an absent objective is a ranking nothing wrote
down, and the honest move is to refuse loudly at the caller, not to
re-derive the arithmetic beside it.

**Later features of this category and what they will find here.**  The
β-terms (257-262) extend the objective inside the member, each landing
its adjustment through the ``adjusted`` seam on the value this component
answers — no second seat, for the same reason no second spelling of the
arithmetic exists.  Feature 262's β₆ orthogonality bonus has since taken
exactly that path: the formula's last term and its only addition is pure
arithmetic measured against the committed book
(:func:`scoring.orthogonality_bonus`, reached from the member's own
namespace), with no component beside ``scoring`` and no second seat
beside this module.  Feature 261's β₅ switch penalty has taken it since:
one charge per regime crossing of the scored horizon, counted off the
ordered path of regime labels the caller hands over
(:func:`scoring.switch_penalty`, reached from the member's own
namespace), with no component and no second seat either.  Feature 260's
β₄ divergence penalty has taken the same path since: the gap between the
pick's forward and backtest information coefficient, derived off the pair
the caller hands over rather than read from any store
(:func:`scoring.divergence_penalty`, reached from the member's own
namespace), with no component and no second seat either.  Feature
259's β₃ deflation penalty has taken it too: the multiple-testing
haircut prd §7.3's growth law states, computed from the ledger
member's ``K_effective`` derivation handed over as a view rather than
a count — the one β-term whose feature sentence is itself a rejection
(:func:`scoring.deflation_penalty`, reached from the member's own
namespace), with no component and no second seat either.  Feature
258's β₂ null-pick penalty has taken the same path since: the charge
for the planted nulls the policy committed to, computed from the rate
feature 265's scorer process answers rather than from any label — the
term prd §7.1 line 327 makes the one without which the calibration
works (:func:`scoring.null_pick_penalty`, reached from the member's own
namespace), with no component and no second seat either.  Feature 263's aggregation has since taken exactly
that path: the blend of the stratum mean and the stratum minimum is pure
arithmetic like the objective, so it lives as the member's second law
(:func:`scoring.aggregate_objective`, reached from the member's own
namespace) with no component beside ``scoring`` and no second seat
beside this module — the composed callable here stays the per-world
objective the replay's scoring step routes through.  Feature 264's
regime index has taken the same path since: *which* strata the blend is
taken over, and the refusal of a plain mean across them, is pure
arithmetic over labels the census wrote — a join, not a store — so it
lives as the member's third law (:func:`scoring.regime_strata`,
:func:`scoring.regime_aggregate`, reached from the member's own
namespace) with no component and no second seat either.  The first
feature of the category that owns deployment state — feature 265's
scorer process holding the sidecar key, then 267's per-campaign
``FDR_deploy`` store — takes its own component name beside ``scoring``
and its own sibling seat module beside this one, exactly the growth
``app.modules.bootstrap`` took when feature 188's pool arrived: a second
module answering *what is the composed scorer process?*, this one going
on answering *what is the composed objective?*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from collections.abc import Callable

    from scoring import WorldScore

    #: The objective's callable shape, for the annotation only — the
    #: member's own docstring is the authoritative spelling of the seam.
    Objective = Callable[..., WorldScore]

__all__ = ["COMPONENT_NAME", "world_objective_component"]

#: The component name the scoring member registers under.  Kept here so
#: anything asking the composed application for the per-world objective —
#: by way of the app package, not the member — shares one spelling, and so
#: the seat, the member and the spec's ``plugin="scoring"`` cannot drift
#: apart silently; the member's suite asserts the two agree.
COMPONENT_NAME = "scoring"


def world_objective_component(
    app: Application | None = None,
) -> Objective | Any:
    """Return the composed per-world objective (feature 256's callable).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``scoring`` component is
    registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory; see the
    module docstring for why that ``None`` is a statement about
    composition and never about the deployment.

    The returned object is the objective itself — call it as
    ``objective(world_id, pick, sequestered_panel, epoch_id=...)`` — and
    it composes to the same callable in every process, because the
    builder holds no state, reads no environment and cannot fail.  Asking
    is always safe; scoring begins at the call, not the composition.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
