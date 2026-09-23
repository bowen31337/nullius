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

**It is not the ladder.**  §12.1's floor — *"below 20 worlds: do not run
dreaming; fixed exploration; accumulate history"* — is a precondition on a run
that has not started, and it is feature 275's sentence with feature 275's own
code (``pool_too_thin``).  This member's subject is a cycle that is *already
going* and must not have its pool moved underneath it, so it carries
``pool_frozen`` and deliberately not the ladder's word.  What this member does
give feature 275 is an honest pool size: the hold records ``world_count`` at
the moment it opened, and a pool that is not there is refused rather than
counted as zero.

**It is not the evaluator, the selector, or the splitter.**  Running ``M``
revisions (features 271-274), rotating the holdout split per cycle (feature
279), the paired statistic and its bar (feature 280) and the argmax persisted
to ``policy_revision`` (features 276-277) are all their own features depending
on this one.  This member holds the pool and hands back the commitment, the
count and the refusal; it never runs a policy and never picks a winner.

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
from .errors import DreamingError, FreezeRequestError, PoolFrozenError
from .layout import (
    POOL_SCHEMA_BY_TABLE,
    REPLAY_SCORE_COLUMNS,
    WORLD_COLUMNS,
    pool_bootstrap_schema,
    pool_tables_present,
)

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "FREEZE_CODE",
    "FREEZE_TABLE",
    "POOL_SCHEMA_BY_TABLE",
    "POOL_TABLES",
    "REPLAY_SCORE_COLUMNS",
    "REPLAY_SCORE_TABLE",
    "UNGUARDED_CODE",
    "WORLD_COLUMNS",
    "WORLD_TABLE",
    "CycleFreeze",
    "DreamingError",
    "FreezeRecord",
    "FreezeRequestError",
    "PoolFrozenError",
    "build_cycle_freeze",
    "cycle_freeze_schema",
    "expected_triggers",
    "missing_guards",
    "open_cycle_freeze",
    "pool_bootstrap_schema",
    "pool_commitment",
    "pool_tables_present",
    "sqlite_path",
]

#: The name this member registers under.  Re-exported from
#: :mod:`dreaming.cycle` rather than respelled, and named ``COMPONENT_NAME``
#: rather than the module-qualified spelling so the seat
#: (``src/app/modules/dreaming``) can import it under the one name every seat
#: in this workspace exports — the shape the loader's discovery expects.
COMPONENT_NAME = POOL_FREEZE_COMPONENT_NAME


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
