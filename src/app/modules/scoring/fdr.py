"""The FDR_deploy store's seat in the ``app`` package namespace — feature 267.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 267: *System
persists FDR_deploy per campaign, computed by reweighting sensitivity and
specificity to a deployment base rate of 0.9* — prd §4.1.3's projection
(line 147) of feature 266's pair at π₀ ≈ 0.9, and the figure the PRD makes
the system's primary metric (§11 line 536, target *"< 25% at π₀ = 0.9"*)
and docs §16's first research metric (line 909, *"per campaign:
FDR_deploy at π₀ = 0.9"*).  The store itself lives in
:mod:`scoring._fdr` in the scoring workspace member; this module is how
the app package reaches the composed store without importing the member
at module scope.

Feature 256's seat (:mod:`app.modules.scoring`) answers *what is the
composed per-world objective?*; feature 265's
(:mod:`app.modules.scoring.scorer`) answers *what is the composed scorer
process?*; this one answers the same shape of question for the member's
third component: *what is the composed FDR_deploy store?*  The growth is
the one ``app.modules.bootstrap`` took for its pool — a seat per
component rather than one accessor learning a second key — and for the
same reason: the three components are different things on different
lifecycles, and a caller that wants the objective never pays for the
store's deployment state or vice versa.

**A third seat, and why the three ``None``s are not one ``None``.**  The
objective seat's ``None`` means *no component was registered* — a
statement about composition (the member was not scanned, the workspace
is empty).  The scorer seat's and this seat's ``None`` mean something
else: the member was scanned, its builder ran, and *nothing named a
sidecar* (that one) or *nothing named a database* (this one) —
statements about the deployment, exactly the pool seat's split from the
world seat's.  Those are different facts that fail differently, and the
docstring of each seat must not be read through another's.  A caller
holding the objective seat's ``None`` cannot score a world at all; a
caller holding this seat's ``None`` has no store to persist a
campaign's FDR_deploy into and must refuse to proceed rather than
silently persisting nowhere — the figure is prd §11's primary target,
read across campaigns, and a trend with a hole in it where a campaign's
row should be is exactly the quietly-defaulted number feature 267
exists to rule out.  The honest move is the loud one, at the caller:
the store is absent, say so, stop.

**Composition stays the factory's job.**  This module asks the factory
for the component and answers ``None`` — not an exception — when there
is none, mirroring the factory's own "degrade, don't break" stance
toward absent components.  It deliberately does **not** re-export the
store class, the free verb, the base rate or the table name: a caller
who has the store calls ``persist(campaign, figures)``, ``fdr(campaign)``
and ``history()`` on it — the per-campaign write, the one-campaign read
and the trend read are the store's own surface — and a caller who wants
the pure reweighting without the store reaches
:func:`scoring.fdr_deploy` through the member's own namespace; a second
spelling of any of those here would be a second thing to keep in sync.
The one question this module answers is *what is the composed
FDR_deploy store?*

**Asking touches no database.**  The composed store resolves its path
on first use, so asking for the component is always safe — the same
promise the objective seat makes for the arithmetic and the pool seat
makes for its database — and the rows are written only when a caller
demands them, which is the *persists on demand* shape of feature 267's
own sentence: composing an application never writes a row, and the
first ``persist`` is where the store opens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from scoring import FdrDeployStore

__all__ = ["COMPONENT_NAME", "fdr_store_component"]

#: The component name the scoring member registers its FDR_deploy store
#: under.  Kept here as well as in the member — the objective seat spells
#: its own name for the same reason, and the member's suite asserts the
#: spellings agree — so the seat, the member and the spec cannot drift
#: apart silently.
COMPONENT_NAME = "scoring-fdr-deploy"


def fdr_store_component(
    app: Application | None = None,
) -> FdrDeployStore | Any:
    """Return the composed FDR_deploy store (feature 267's store).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``scoring-fdr-deploy``
    component is registered.

    That ``None`` is a statement about the deployment rather than about
    the member: nothing named ``DATABASE_URL``, so there is no relational
    store for the per-campaign FDR_deploy rows to live in.  It is
    deliberately **not** the same fact as the objective seat's ``None``,
    which means no component was registered at all — and it is not an
    empty trend either: an empty :meth:`~scoring.FdrDeployStore.history`
    is a statement about what has been *closed out* (no campaign has
    persisted a figure yet), while this ``None`` is a statement about
    what the deployment can hold.  A caller that needs to persist a
    campaign's figure must treat it as a refusal to proceed rather than
    as a trend of zero rows.

    The returned object is the store itself — call
    ``persist(campaign, figures)`` on it, handing the campaign's id and
    feature 266's calibration pair, or ``fdr(campaign)`` to read one
    campaign's figure back, or ``history()`` for every campaign's
    oldest-first — and it composes to the same store for the same
    environment, opening the database on first use and never caching a
    figure.  Asking is always safe; the rows are touched at the
    persist, not the composition.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
