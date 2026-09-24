"""The promotion plugin: pre-registered criteria, hashed before the decision.

Implements app_spec.xml, "Promotion & Epoch Governance", feature 291 —
*"System exposes POST /promotion/pre-register, which returns a criteria hash
recorded before the deciding evaluation runs"* — against
docs/alpha-engine-prd.md §13 item 7, *"Promotion criteria are pre-registered
and hashed before the evaluation that decides them"*, and against the
``promotion_registry`` table feature 108's migration
(``migrations/versions/0108_forward_and_universe_tables.py``) already
declares.

The member's surface is five modules.  :mod:`promotion.criteria` is *what* a
promotion is judged against and *how it is hashed*:
:class:`~promotion.criteria.PromotionCriteria`, the six terms §13.7's
"criteria" enumerates — the paired ΔIR advantage, the significance level, the
deployment FDR ceiling and the three quantities of evidence a promotion must
be measured over — with :meth:`~promotion.criteria.PromotionCriteria.
canonical` as the one spelling of the document the digest is taken over and
:func:`~promotion.criteria.criteria_hash` as the digest itself, sha256 hex,
the spelling the ``CHAR(64)`` column holds.
:mod:`promotion.pre_register` is *the recording*:
:class:`~promotion.pre_register.PreRegistrations`, the store that writes one
open row per node into ``promotion_registry``;
:class:`~promotion.pre_register.PreRegistrationRequest` and
:class:`~promotion.pre_register.PreRegistrationResponse`, the body and the
answer; :class:`~promotion.pre_register.PreRegisterEndpoint`, the route
itself with :data:`~promotion.pre_register.PRE_REGISTER_ROUTE` pinned on it;
and :class:`~promotion.pre_register.PromotionRecord`, the row as the table
holds it.  :mod:`promotion.schema` is the DDL adapter: it runs the *owning
migrations'* own ``statements("sqlite")`` for the three tables this one
``INSERT`` needs — ``node``, ``epoch_ledger`` and ``promotion_registry`` — so
this member authors no DDL and cannot drift from the schema's owners.
:mod:`promotion.blocking` is feature 299's *reason*:
:class:`~promotion.blocking.PromotionBlocks`, the store that records why a
promotion was blocked on §C7's regime coverage, with
:class:`~promotion.blocking.PromotionBlock` as the row and
:func:`~promotion.blocking.blocking_reason` rendering the one canonical sentence
that row explains itself with.  :mod:`promotion.errors` is the member's error
vocabulary: :class:`~promotion.errors.PromotionError` (the *ask* face: a
malformed body, a criterion that is not a number, a re-registration with
different criteria), :class:`~promotion.errors.PromotionStoreError` (the
*address, parent and write* face, every message opening
:data:`~promotion.errors.PROMOTION_REGISTRY_ERROR_CODE`), and feature 299's
:class:`~promotion.errors.PromotionBlockError` (the *merit* face — a promotion
refused on coverage rather than on form), split by the repair rather than by
the code path except where a gate's caller position overrides the split — the
argument that module states.  This module re-exports all of it and registers
the one component; it carries no logic of its own, which is the same shape every
member in this workspace takes.

**The two-timestamp law is created here and enforced elsewhere.**  ``0108``
declares ``pre_registered_at TIMESTAMPTZ NOT NULL`` and ``decided_at
TIMESTAMPTZ`` nullable, and its own comment says why: *"``decided_at`` is
nullable because the row is written while the decision is still open, which
is the only ordering under which pre-registration means anything."*  This
member writes the first timestamp and never the second — the insert's column
list has four columns and ``decided_at`` is not among them, so a
pre-registration row is born open by the *shape* of the statement rather than
by a check the writer remembers to make.  Feature 293's decision closes it;
feature 292 judges a promotion against the recorded hash; feature 360 is the
CI invariant that refuses a merge when criteria were recorded after the
deciding evaluation.  This member's job is to make the ordering *possible* to
enforce, which means making it true in the table rather than in a docstring.

**Registration is the entire wiring story.**  The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml``
declares, imports each package, and composes whatever each package's
``@register`` builder contributes — so the decorator at the foot of this
module is all that makes the plugin exist.  Nothing edits a registry, router
table, entry-points list or app factory to wire this package in, and nothing
here reaches back and mutates the factory: the factory is the composition
root and the sole author of the object it returns.

**The registration lives here and not in a submodule.**  ``@register`` fires
at import time, and importing a *submodule* of this package is not the same
act as importing the package: a submodule's registration would fire only on
the first ``create_app()`` of a process, and only if that process happened to
load it.  Keeping the decorator in ``__init__.py`` — spelled against names
imported from ``.pre_register`` rather than beside it — is what makes the
component present from the moment the workspace scan touches this package.

**One component, and it may be ``None``.**  ``"promotion"`` is the member's
first component, registered unprefixed, following the ``ledger`` /
``artifacts`` / ``canary`` / ``discovery`` / ``regime`` precedent for a
member's first and only component: the prefix families (``nulloracle-*``,
``tripwires-*``) exist to disambiguate many components inside one member, and
this member has one.  ``promotion`` sorts between ``policy-runtime`` and
``providers`` — the two names immediately around it are also the two names
nearest it that *begin* differently, so the key is unambiguous at a glance —
and every existing adjacency assertion over the name-sorted ``app.order``
is untouched.  The name is the *store*, not the endpoint: the
endpoint is a thin seam that holds no state of its own and can be built from
the store at any time (:meth:`PreRegisterEndpoint.from_env`), so the thing a
deployment actually holds — a table in the database ``DATABASE_URL`` names,
written by one process and read by another — is what is composed.  The
builder returns ``None`` when nothing names a relational store, on the
degrade-don't-break stance every store in this workspace takes toward an
absent ``DATABASE_URL``: an unconfigured registry is a discoverable state,
and the caller that must pre-register criteria before the evaluation that
decides them is the caller that must not find itself in it.  It never raises,
including for a URL whose scheme this member cannot speak: the factory builds
every registered component on every ``create_app()`` call, so a raising
builder would take composition down for every unrelated feature in the
workspace.

**Why only one component, and why the category's later features add none.**
The factory's registration protocol is for *state a deployment holds*, and
the registry is exactly that.  Everything the category's later features add
is an act *over* these rows rather than a second thing to persist — 292's
mismatch verdict is a comparison against a hash a caller read through this
store, 293's decision closes a row this store opened, 294's count advances a
column in ``epoch_ledger``, 295's threshold reads that column, 296's terminal
state is what remains when every epoch is retired, 297's depleting count is a
read of the same table, 298's ``VOID`` refusal is a judgement over the
campaign row, and 300's promotion timestamp is a fact placed by 293's write.
A builder takes no arguments and is built on every ``create_app()`` call,
while each of those acts is a function of evidence the factory does not hold —
a decision, a count, a calibration status — so registering one would be a
component pointed at state no composition can supply.  The sibling seams will
reach this store the only way the spec allows: by asking the composed
``promotion`` component, or by constructing a store from a URL.

**Feature 299's block, and the design question it settled.**  This paragraph
used to add *"299's blocking reason is one more column's worth of state on a
decision"* to the list above, and feature 299 did not take that reading.
:mod:`promotion.blocking` is a store of its own — ``promotion_block``, one row
per node, keyed by ``node_id`` and foreign-keyed to ``node`` — and the reasons
are three, each stated in full in that module's docstring: the spec's schema
block declares ``promotion_registry``'s six columns and **no** seventh, and the
migration tree that owns that DDL stops at ``0108``, which this member may not
edit, so a column could only arrive as a runtime ``ALTER TABLE`` — a second,
dialect-dependent spelling of a shared table's shape added by a member that does
not own it; a blocked promotion is a different noun from a pre-registered one,
with a different writer, lifetime and reader; and the block store's read must
answer *is this node blocked, and why* for a node that may hold no registry row,
which is a probe over the *decision* and awkward bolted onto a row with an
identity of its own.  What that paragraph got right is kept: the block is state
about one decision, written once, never revised, read back by node.  It is
still not a second component — it is never registered and is constructed from a
URL by the caller that has one, so the member's one ``build_*`` name stands.
"""

from __future__ import annotations

from app.module_loader import register

from .blocking import (
    BLOCKED_AT_COLUMN,
    COVERAGE_THRESHOLD_COLUMN,
    PROMOTION_BLOCK_TABLE,
    REGIME_COLUMN,
    WORLD_COUNT_COLUMN,
    PromotionBlock,
    PromotionBlocks,
    blocked_promotion,
    blocking_reason,
)
from .criteria import CRITERIA_FIELDS, PromotionCriteria, criteria_hash
from .errors import (
    PROMOTION_BLOCK_ERROR_CODE,
    PROMOTION_REGISTRY_ERROR_CODE,
    PromotionBlockError,
    PromotionError,
    PromotionStoreError,
)
from .pre_register import (
    CRITERIA_HASH_COLUMN,
    DATABASE_URL_ENV,
    DECIDED_AT_COLUMN,
    EPOCH_ID_COLUMN,
    NODE_ID_COLUMN,
    PRE_REGISTER_ROUTE,
    PRE_REGISTERED_AT_COLUMN,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PreRegistrationResponse,
    PreRegistrations,
    PromotionRecord,
    utc_now,
)
from .schema import (
    MIGRATION_ORDER,
    PROMOTION_REGISTRY_TABLE,
    bootstrap_schema,
    migrations_dir,
)

__all__ = [
    "BLOCKED_AT_COLUMN",
    "COMPONENT_NAME",
    "COVERAGE_THRESHOLD_COLUMN",
    "CRITERIA_FIELDS",
    "CRITERIA_HASH_COLUMN",
    "DATABASE_URL_ENV",
    "DECIDED_AT_COLUMN",
    "EPOCH_ID_COLUMN",
    "MIGRATION_ORDER",
    "NODE_ID_COLUMN",
    "PRE_REGISTERED_AT_COLUMN",
    "PRE_REGISTER_ROUTE",
    "PROMOTION_BLOCK_ERROR_CODE",
    "PROMOTION_BLOCK_TABLE",
    "PROMOTION_REGISTRY_ERROR_CODE",
    "PROMOTION_REGISTRY_TABLE",
    "REGIME_COLUMN",
    "WORLD_COUNT_COLUMN",
    "PreRegisterEndpoint",
    "PreRegistrationRequest",
    "PreRegistrationResponse",
    "PreRegistrations",
    "PromotionBlock",
    "PromotionBlockError",
    "PromotionBlocks",
    "PromotionCriteria",
    "PromotionError",
    "PromotionRecord",
    "PromotionStoreError",
    "blocked_promotion",
    "blocking_reason",
    "bootstrap_schema",
    "build_promotion_registry",
    "criteria_hash",
    "migrations_dir",
    "utc_now",
]

#: The name the promotion member registers its registry under.  Unprefixed,
#: following the ``ledger`` / ``artifacts`` / ``canary`` / ``discovery`` /
#: ``regime`` precedent for a member's first and only component, and spelled
#: here once so the seat (``src/app/modules/promotion``) and the composed
#: application agree on the key — the seat repeats the literal and its suite
#: asserts the two match, so the pair cannot drift apart silently.
#: ``promotion`` sorts between ``policy-runtime`` and ``providers``, clear of
#: both.
COMPONENT_NAME = "promotion"


@register(COMPONENT_NAME)
def build_promotion_registry() -> PreRegistrations | None:
    """Component builder: the pre-registration registry this deployment writes into.

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the registry for the deployment the process is actually running in.  The
    endpoint that serves the route is built from this store
    (:meth:`PreRegisterEndpoint.from_env`), so the composed component and the
    route always point at the same database.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately not an empty registry: an empty registry answers *this node
    holds no pre-registration* about every identity it is asked for, while
    this ``None`` says there is no database a criteria hash could have been
    recorded in — the distinction ``0108`` draws between a row written while
    the decision is open and an absent one, at the level of the whole table.
    A caller that must pre-register criteria has to treat the ``None`` as a
    refusal to proceed rather than as a registry that happened to find
    nothing, because §13 item 7 leaves nothing to fall back on: criteria
    recorded nowhere are criteria the deciding evaluation is not measured
    against.

    Never raises — including for a URL whose scheme the store cannot speak,
    which is refused by name the first time an operation needs the path
    rather than here.  Construction performs no I/O: the path is resolved on
    first use, and the schema is brought up on the first
    :meth:`~promotion.pre_register.PreRegistrations.pre_register`, so
    composing the application neither opens a database nor creates a table.
    """
    return PreRegistrations.resolve()
