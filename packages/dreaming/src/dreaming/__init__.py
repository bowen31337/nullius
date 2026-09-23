"""The dreaming loop's hold on the replay pool — feature 270.

app_spec.xml, *Dreaming Loop & Meta-Selection*, feature 270:

    System rejects a replay pool mutation during a dreaming iteration, holding
    the pool fixed for the cycle.

docs/alpha-engine-prd.md §C5 states the rule as the *first clause of the loop*
rather than as a caveat on it — *"Per outer iteration: hold the replay pool
fixed, run M code revisions of π, evaluate each on every stored tree, select
the argmax under §7"* — and §12.1 says why the qualifier is load-bearing:

    The dreaming loop **overfits its own replay pool**.  The paper's guarantee
    ``V^{m★} ≥ V^0`` holds on the *fixed history*; selecting the max over ``M``
    revisions scored on a handful of worlds is the same multiple-testing
    problem one level up.

The guarantee is a guarantee about a fixed history, so the history has to
actually be fixed.  This member is the part of the system that does the fixing
and the part that refuses the moving.

What it is
----------

One component, :data:`COMPONENT_NAME`, sitting over the database the replay
pool already lives in.  :meth:`~dreaming.cycle.CycleFreeze.open` writes a hold
row naming the iteration and recording the pool's **commitment** — a digest
over which worlds the tournament is held over — and installing a
``BEFORE INSERT``/``UPDATE``/``DELETE`` guard per pool table per operation;
:meth:`~dreaming.cycle.CycleFreeze.release` closes the hold;
:meth:`~dreaming.cycle.CycleFreeze.verify` re-reads the commitment and answers
whether the pool moved.

**The enforcement is the trigger, not a wrapper.**  A Python guard is a rule
its caller can walk around by opening the database itself, and the pool's
writers are not all this member's callers — the replay member writes scores
(``replay_score``, migration ``0109``), the bootstrap member authors worlds
(``bootstrap_world``, features 188/191), and an operator bisecting a
deployment has a ``sqlite3`` shell.  A rule about a *store* has to live in the
store, so the refusal is a ``RAISE(ABORT, ...)`` in the database and the Python
API is only its translation: a caller that used this member reads a
:class:`~dreaming.errors.PoolFrozenError` naming the holding iteration, and a
caller that bypassed it is refused just the same, by SQLite, with the raw
abort.

**Three members already obey this rule.  This is the one that enforces it.**
:mod:`tripwires.excise` (feature 132) exists to excise a poisoned subtree from
the replay pool and takes the one decision that makes it compatible with
feature 270 — it never deletes a row, because *"feature 270 forbids exactly
that mutation"*; :mod:`canary._void` (feature 144) makes the identical call for
the identical reason, and :mod:`bootstrap._census` (feature 186) reads the
pool's two halves without writing either.  Three members were built to this
rule before this module existed; what was missing was the refusal, and the
account of which cycle is holding what.

What it is not
--------------

**It carries the ladder's floor as a second sentence, not a third face of
feature 270.**  §12.1's floor — *"below 20 worlds: do not run dreaming; fixed
exploration; accumulate history"* — is a precondition on a run that has *not*
started, which is feature 275's sentence.  It lives in this member as its own
code (``pool_too_thin``, :data:`POOL_TOO_THIN_CODE`) and its own class
(:class:`~dreaming.errors.PoolTooThinError`), a sibling of feature 270's
``pool_frozen`` rather than a face of it: feature 270's subject is a cycle that
is *already going* and must not have its pool moved underneath it, and its
repair is *stop writing, or close the iteration*, while the floor's subject is
a run that has not begun and should not begin, and its repair is *grow the
pool, or run fixed exploration*.  The two sentences have different repairs, so
they are two classes under the one :class:`~dreaming.errors.DreamingError`
base, and the floor is a judgment over a count the caller already has —
:func:`dreaming.ladder.rejects_thin_pool` takes the figure, it never counts the
pool — which is the honest division between a verdict and a count.  What this
member gives the floor is the same honest pool size it gives feature 270: the
hold records ``world_count`` at the moment it opened, and a pool that is not
there is refused rather than counted as zero.

**It carries the revision cap's schedule and its per-cycle record as a third
sentence.**  §C5 runs ``M`` code revisions per outer iteration, and §12.1's
ladder caps ``M`` by the pool's size — *"20–50: dreaming with M capped at
8–10"*, *"50+: full dreaming, M = 30–40"* — so feature 277's sentence takes
the top rung: the cap rises to 40 (:data:`FULL_DREAMING_CAP`) once the pool
holds 50 or more worlds (:data:`FULL_DREAMING_WORLDS`).  The schedule
(:func:`dreaming.cap.revision_cap`) is the same shape the floor is — a
judgment over the count the caller already has, delegating the bottom rung to
feature 275's own refusal — and the record
(:func:`dreaming.cap.record_cycle_cap`) writes one row per cycle into this
member's own ``cycle_cap`` table (:data:`CYCLE_CAP_TABLE`), append-only, each
row carrying the pool size its cap was decided over.  The cap is persisted
rather than remembered because Appendix B's selection bar — ``advantage >
√(2 ln M) · σ_V / √n_worlds``, the bar feature 280 applies to the winning
revision — reads ``M`` back, and a bar computed over an ``M`` nobody recorded
is a bar over a number nobody ran.  The record takes the figure rather than
counting the pool (the same verdict-count split the floor states), refuses a
database that holds no pool for the same reason the freeze does — a cap over
a pool that is not there caps nothing — and its refusals are its own pair of
classes (:class:`~dreaming.errors.CapRequestError`,
:class:`~dreaming.errors.CapRecordError`), translated at the seam from the
member's one spellings of the shared rules, never borrowed from feature 270's
vocabulary.

**It carries the middle rung's ceiling as a fourth sentence, and that is the
half of the ladder the schedule cannot state.**  Feature 277 *answers* the cap
the thin band runs under — 10 — while feature 276 *refuses* a cycle that means
to run more than that while the pool sits in the band: *"System rejects a
revision count above 10 while the pool holds between 20 and 50 worlds, so the
selection bar stays low."*  The refusal is
:func:`dreaming.ceiling.rejects_uncapped_sweep`, the same verdict-over-counts
shape the floor is — the revision count the caller means to run and the pool's
size in, a refusal out — and it consumes rather than respells every ladder
figure it judges by: the band's cap is feature 277's
:data:`CAPPED_SWEEP_CAP`, its edges are feature 275's floor and feature 277's
:data:`FULL_DREAMING_WORLDS`.  So the number a cycle is *entitled to* on the
thin rung and the number it is *refused above* are one constant, and the
default judgment admits exactly what the schedule answers at every pool size.
Above the band there is no ceiling — the pool has cleared 50, the raise has
fired, and ``M`` is feature 277's to answer at 40 — and below it the refusal is
feature 275's, delegated, in the floor's own word, because a pool that may not
dream at all needs no cap on its sweep.  The one refusal the sentence itself
mints is :class:`~dreaming.errors.RevisionCeilingError`, its own class and
deliberately without a code word: its repair (*lower ``M`` to the band's cap,
or grow the pool until the raise applies*) is neither the floor's (*grow the
pool before dreaming at all*) nor the cap's (*re-consider the ask*), so a
caller that caught it as either would act on the wrong fact.  The reason the
ceiling exists at all is §12.1's own arithmetic: Appendix B's bar is
``advantage > √(2 ln M) · σ_V / √n_worlds``, ``§12.1`` computes ``n > 53``
worlds at ``M = 40``, and a pool of 20–50 is short of that by construction —
so a wider sweep is *available* only once the pool clears the band, and the
selection bar stays low because it cannot be raised.

**It is not the evaluator, the selector, or the splitter.**  Running ``M``
revisions (features 271-274), rotating the holdout split per cycle (feature
279), the paired statistic and its bar (feature 280) and the argmax persisted
to ``policy_revision`` are all their own features depending on this one.  This
member holds the pool and hands back the commitment, the count and the
refusal; it never runs a policy and never picks a winner.

**It never writes the pool's tables.**  Feature 270's whole subject is not
writing them.  ``pool_freeze`` is this member's own table and the only table it
creates; :mod:`dreaming.layout` restates the pool's two spellings with their
provenance because a trigger needs a table's *name*, and restates them
deliberately **without importing** the members that own them — no member in
this workspace imports another, and a member that did would couple a
database's history to a package's import graph, invisibly, at the one place it
matters: a deployment that installed one and not the other.

The seat
--------

**The registration lives here and not in a submodule.**  ``@register`` fires at
import time, and importing a *submodule* of this package is not the same act as
importing the package: a submodule's registration would fire only on the first
``create_app()`` of a process, and only if that process happened to load it.
Keeping the decorator in ``__init__.py`` — spelled against names imported from
``.cycle`` rather than beside it — is what makes the component present from the
moment the workspace scan touches this package.  Nothing edits a registry,
router table, entry-points list or app factory to wire this package in: the
package joining the uv workspace *is* the wiring, and the loader's scan of the
declared members is the whole of what discovers it.

Composition-time behaviour follows the workspace's one rule: **degrade, don't
break**.  :func:`build_cycle_freeze` returns a
:class:`~dreaming.cycle.CycleFreeze` when ``DATABASE_URL`` names a store, and
``None`` when it names none — a deployment without a relational store composes
no freeze, which is a discoverable state rather than an exception and not the
same fact as a pool that is not currently held.  The builder performs **no
I/O**: it resolves a URL and constructs an object whose path is read lazily, so
composing an application never touches the disk — and it **never holds
anything**, because §C5's hold is *per outer iteration* and an application that
acquired one at composition time would be holding a pool for as long as the
process lived.

**One component, and it may be ``None``.**  ``"dreaming"`` is the member's
first and only component, registered unprefixed, following the ``ledger`` /
``artifacts`` / ``discovery`` precedent for a member whose first component is
the whole of what it contributes.  The name sorts after ``discovery`` and
before ``evaluator``, so every name-sorted ``app.order`` adjacency in the
existing suite is untouched.

The seat is ``src/app/modules/dreaming``, which answers exactly one question —
*what is the composed cycle freeze?* — and re-exports nothing of the member's
API beyond that: a caller who has the freeze reaches ``open()``, ``release()``,
``verify()``, ``guard()`` and ``holds()`` on it, and a second spelling of those
here would be a second thing to keep in sync.  :data:`COMPONENT_NAME` is
spelled once here and repeated literally in the seat, whose suite asserts the
two agree so the pair cannot drift apart silently.
"""

from __future__ import annotations

from app.module_loader import register

from .cap import (
    CAPPED_SWEEP_CAP,
    CYCLE_CAP_TABLE,
    FULL_DREAMING_CAP,
    FULL_DREAMING_WORLDS,
    CapRecord,
    cycle_cap_schema,
    cycle_caps,
    record_cycle_cap,
    revision_cap,
)
from .ceiling import rejects_uncapped_sweep
from .cycle import (
    DATABASE_URL_ENV,
    FREEZE_CODE,
    FREEZE_TABLE,
    POOL_FREEZE_COMPONENT_NAME,
    POOL_TABLES,
    REPLAY_SCORE_TABLE,
    UNGUARDED_CODE,
    WORLD_TABLE,
    CycleFreeze,
    FreezeRecord,
    cycle_freeze_schema,
    expected_triggers,
    missing_guards,
    open_cycle_freeze,
    pool_commitment,
    sqlite_path,
)
from .errors import (
    CapRecordError,
    CapRequestError,
    DreamingError,
    FreezeRequestError,
    PoolFrozenError,
    PoolTooThinError,
    RevisionCeilingError,
)
from .ladder import (
    LADDER_FLOOR_WORLDS,
    POOL_TOO_THIN_CODE,
    rejects_thin_pool,
    validated_floor,
)
from .layout import (
    POOL_SCHEMA_BY_TABLE,
    REPLAY_SCORE_COLUMNS,
    WORLD_COLUMNS,
    pool_bootstrap_schema,
    pool_tables_present,
)

__all__ = [
    "CAPPED_SWEEP_CAP",
    "COMPONENT_NAME",
    "CYCLE_CAP_TABLE",
    "DATABASE_URL_ENV",
    "FREEZE_CODE",
    "FREEZE_TABLE",
    "FULL_DREAMING_CAP",
    "FULL_DREAMING_WORLDS",
    "LADDER_FLOOR_WORLDS",
    "POOL_SCHEMA_BY_TABLE",
    "POOL_TABLES",
    "POOL_TOO_THIN_CODE",
    "REPLAY_SCORE_COLUMNS",
    "REPLAY_SCORE_TABLE",
    "UNGUARDED_CODE",
    "WORLD_COLUMNS",
    "WORLD_TABLE",
    "CapRecord",
    "CapRecordError",
    "CapRequestError",
    "CycleFreeze",
    "DreamingError",
    "FreezeRecord",
    "FreezeRequestError",
    "PoolFrozenError",
    "PoolTooThinError",
    "RevisionCeilingError",
    "build_cycle_freeze",
    "cycle_cap_schema",
    "cycle_caps",
    "cycle_freeze_schema",
    "expected_triggers",
    "ladder_floor",
    "missing_guards",
    "open_cycle_freeze",
    "pool_bootstrap_schema",
    "pool_commitment",
    "pool_tables_present",
    "record_cycle_cap",
    "rejects_thin_pool",
    "rejects_uncapped_sweep",
    "revision_cap",
    "sqlite_path",
    "validated_floor",
]

#: The name this member registers under.  Re-exported from
#: :mod:`dreaming.cycle` rather than respelled, and named ``COMPONENT_NAME``
#: rather than the module-qualified spelling so the seat
#: (``src/app/modules/dreaming``) can import it under the one name every seat
#: in this workspace exports — the shape the loader's discovery expects.
COMPONENT_NAME = POOL_FREEZE_COMPONENT_NAME

#: The ladder floor's world count — §12.1's 20, the floor a dreaming run must
#: meet.  Re-exported from :mod:`dreaming.ladder` under the friendlier name the
#: seat and a caller reach for, the way :data:`POOL_FREEZE_COMPONENT_NAME` is
#: re-exported as :data:`COMPONENT_NAME`; a caller that asks *what is the
#: floor?* gets one spelling, and a second spelling here would be a second
#: thing to keep in sync.
ladder_floor = LADDER_FLOOR_WORLDS


@register(COMPONENT_NAME)
def build_cycle_freeze() -> CycleFreeze | None:
    """Component builder: the cycle freeze this deployment holds the pool with.

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the freeze for the deployment the process is actually running in.  The
    member's other spelling of the same act,
    :func:`~dreaming.cycle.open_cycle_freeze`, resolves the same variable when
    it is called without a URL, so a script and a composed application reach
    the same hold over the same database.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately not a freeze over an empty pool — and not the same fact as a
    pool that is currently unheld, which is :meth:`~dreaming.cycle.CycleFreeze.
    open_hold` answering ``None`` about a database that definitely exists.  An
    unheld pool answers *no cycle is walking this pool right now*; this
    ``None`` says there is no database to walk one in, and a caller that needs
    §C5's first clause must treat it as a refusal to proceed rather than as a
    pool it happened to find free.  The distinction is the one
    :func:`bootstrap.build_bootstrap_pool` draws for its own deployment state.

    Never raises — including for a URL whose scheme this member cannot speak,
    which is refused by name the first time an operation needs the path rather
    than here.  The factory builds every registered component on every
    :func:`~app.module_loader.create_app` call, so a builder that raised would
    take composition down for every unrelated feature in the workspace; a
    process that *requires* a hold passes a URL to :class:`~dreaming.cycle.
    CycleFreeze` directly, where a named
    :class:`~dreaming.errors.FreezeRequestError` is the right answer.

    Construction performs no I/O and acquires no hold: the path is resolved on
    first use, so composing the application never opens a database, and §C5's
    pool is fixed only when a caller's ``open()`` fixes it.  An application
    that held a pool from composition time would hold it for as long as the
    process lived, which would be a dreaming cycle that never ended.
    """
    return CycleFreeze.resolve()
