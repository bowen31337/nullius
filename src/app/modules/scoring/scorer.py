"""The scorer process's seat in the ``app`` package namespace — feature 265.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 265: *System
computes null pick rate inside a scorer process holding the sidecar key,
which returns the rate while labels stay in.*  docs/nullius-tech-
architecture.md §10.3 states the barrier in one line (507): *"``null_pick_rate``
is computed by a scorer process holding the sidecar key.  The number flows
out; the labels do not."*  The process itself lives in
:mod:`scoring._scorer` in the scoring workspace member; this module is how
the app package reaches the composed process without importing the member
at module scope.

Feature 256's seat (:mod:`app.modules.scoring`) answers *what is the
composed per-world objective?*; this one answers the same shape of
question for the member's second component: *what is the composed scorer
process?*  The growth is the one ``app.modules.bootstrap`` took for its
pool (feature 188's ``bootstrap-pool`` beside feature 181's ``bootstrap``)
— a seat per component rather than one accessor learning a second key —
and for the same reason: the two components are different things on
different lifecycles, and a caller that wants the objective never pays
for the scorer's deployment state or vice versa.

**A second seat, and why the two ``None``s are not one ``None``.**  The
objective seat's ``None`` means *no component was registered* — a
statement about composition (the member was not scanned, the workspace is
empty), and nothing else, because that member's builder cannot fail and
reads no environment.  This seat's ``None`` means something else: the
member was scanned, its builder ran, and *nothing named a sidecar* — a
statement about the deployment, exactly the pool seat's split from the
world seat's.  Those are different facts that fail differently, and the
docstring of each seat must not be read through the other's.  A caller
holding the objective seat's ``None`` cannot score a world at all; a
caller holding this seat's ``None`` has no process to read a null pick
rate from and must refuse to proceed rather than invent one — prd §7.1
line 327 calls β₂ *"the term that does not exist in the paper and without
which none of this works"*, and a loop that charged that term on a
quietly-defaulted ``0.0`` would be a calibration that never ran.  The
honest move is the loud one, at the caller: the process is absent, say
so, stop.

**Composition stays the factory's job.**  This module asks the factory
for the component and answers ``None`` — not an exception — when there
is none, mirroring the factory's own "degrade, don't break" stance
toward absent components.  It deliberately does **not** re-export the
process class, the sidecar seam, or the rate verb: a caller who has the
process calls ``null_pick_rate(picks)`` on it — the one public verb the
process carries, the feature's own sentence made structural — and a
second spelling of it here would be a second thing to keep in sync and a
second surface the barrier would have to hold.  The one question this
module answers is *what is the composed scorer process?*

**Asking touches no sidecar.**  The composed process holds its carrier
and reads the sealed file per ask, so asking for the component is always
safe — the same promise the objective seat makes for the arithmetic and
the pool seat makes for its database — and the labels are read only when
a caller demands a rate, which is the whole point of the barrier: compose
freely, read never without meaning to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from scoring import NullPickScorer

__all__ = ["COMPONENT_NAME", "null_pick_scorer_component"]

#: The component name the scoring member registers its scorer process
#: under.  Kept here as well as in the member — the objective seat spells
#: its own name for the same reason, and the member's suite asserts the
#: spellings agree — so the seat, the member and the spec cannot drift
#: apart silently.
COMPONENT_NAME = "scoring-null-pick-rate"


def null_pick_scorer_component(
    app: Application | None = None,
) -> NullPickScorer | Any:
    """Return the composed scorer process (feature 265's process).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``scoring-null-pick-rate``
    component is registered.

    That ``None`` is a statement about the deployment rather than about
    the member: nothing named a sidecar — no ``NULL_SIDECAR_PATH`` (or
    lake) with a ``NULL_SIDECAR_KEY_REF`` to open it — so there are no
    labels for a scorer process to hold, and the builder honestly
    contributed no process rather than a broken one.  It is deliberately
    **not** the same fact as the objective seat's ``None**, which means
    no component was registered at all — and it is not a rate of zero
    either: ``0.0`` is a *measurement* (picks were committed, none were
    null) where this ``None`` is an absence (no rate was, or could be,
    computed).  A caller that needs β₂ — every caller that charges it,
    feature 258's seam — must treat it as a refusal to proceed rather
    than as a clean campaign.

    The returned object is the process itself — call
    ``null_pick_rate(picks)`` on it, handing the committed picks — and it
    composes to the same process for the same environment, reading the
    sealed file per ask and never caching a label.  Asking is always
    safe; the labels are touched at the rate, not the composition.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
