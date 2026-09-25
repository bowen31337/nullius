"""The forward plugin: one record per promoted signal, carrying its instant.

Implements app_spec.xml, "Forward-Test Tracking", feature 332 — *"System
exposes POST /forward/promote, which creates a forward_record carrying the
promotion timestamp"* — against docs/alpha-engine-prd.md §5 Loop 3, *"Every
promoted signal is timestamped and its live forward IC tracked from the
promotion date forward.  After 90 days, that signal has a track record on data
that did not exist when the hypothesis was formed"*, and against the
``forward_record`` table feature 108's migration
(``migrations/versions/0108_forward_and_universe_tables.py``) already declares.

The member's surface is four modules, and each answers one question.

:mod:`forward.window` is **where the instant comes from**.  The promotion
timestamp is not this member's to compute: it is feature 293's
``decided_at`` on the registry row, carried out by feature 300's
``promotion_window``.  That seam is reached through
``importlib.import_module("promotion")`` at call time — a member never imports
another member — and every refusal it raises arrives here as
:class:`~forward.errors.ForwardPromotionError`.

:mod:`forward.schema` is **who owns the DDL**: it loads ``0118_node_table`` and
``0108_forward_and_universe_tables`` by file path and runs their own
``statements("sqlite")``, because SQLite resolves a foreign key's parent when a
row is *written* through the child table, so a records-only database refuses
every insert naming a node table this member does not own.  Not one
``CREATE TABLE`` is spelled in this package.

:mod:`forward.record` is **the act**: :class:`~forward.record.ForwardRecords`
opens one row per promoted signal and answers a retry with the standing one;
:class:`~forward.record.ForwardRecordRequest` and
:class:`~forward.record.ForwardRecordResponse` are the body and the answer;
:class:`~forward.record.PromoteEndpoint` is the route itself with
:data:`~forward.record.FORWARD_PROMOTE_ROUTE` pinned on it; and
:class:`~forward.record.ForwardRecord` is the row as the table holds it.

:mod:`forward.errors` is **what can go wrong**, split by the repair the caller
must make: a malformed row, a store that is misrouted or broken, a promotion
with no instant to open at, and a signal that already holds a record for a
different promotion.

**The one-signal law, and why this feature is not a plain append.**  §13.4
makes the ``promoted_at`` / ``observed_on`` pair the vintage a forward record
carries, and docs/nullius-tech-architecture.md's Loop 3 makes the promotion
instant the boundary between backtest and out-of-sample.  A signal has exactly
one such boundary, so ``POST /forward/promote`` is idempotent on the node: a
retry returns the standing row untouched, and a request that *disagrees* with
it is refused rather than resolved — the argument
:class:`~forward.errors.ForwardIdentityError` states.  Feature 333, which
appends the *observation* rows, is a different act with a different key; this
one opens the record and nothing else.

**Three columns are left NULL, and that is the migration's decision.**  ``0108``
declares ``live_ic``, ``backtest_ic`` and ``realized_cost_bps`` nullable with
its reason in the comment beside them: *"a freshly promoted signal has no
observation yet — a NOT NULL here would force a fabricated zero on the day of
promotion, which would read as 'measured, and it was zero'."*  Feature 332
measures nothing, so its ``INSERT`` names three columns and stamps no zero.
Features 333, 337 and 340 fill those columns; a writer here that guessed would
be answering for three features that have not run — the same boundary the
promotion member's own suite pins from the other side, where
``packages/promotion/src/promotion/forward.py`` refuses even to *name* this
table because its rows are this plugin's to write.

**Registration is the entire wiring story.**  The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml`` declares,
imports each package, and composes whatever each package's ``@register``
builder contributes — so the decorator at the foot of this module is all that
makes the plugin exist.  Nothing edits a registry, router table, entry-points
list or app factory to wire this package in, and nothing here reaches back and
mutates the factory: the factory is the composition root and the sole author of
the object it returns.

**The registration lives here and not in a submodule.**  ``@register`` fires at
import time, and importing a *submodule* of this package is not the same act as
importing the package: a submodule's registration would fire only on the first
``create_app()`` of a process, and only if that process happened to load it.
Keeping the decorator in ``__init__.py`` — spelled against names imported from
``.record`` rather than beside it — is what makes the component present from
the moment the workspace scan touches this package.

**One component, and it may be ``None``.**  ``"forward"`` is the member's first
component, registered unprefixed, following the ``ledger`` / ``artifacts`` /
``canary`` / ``discovery`` / ``regime`` / ``promotion`` precedent for a member's
first and only component: the prefix families (``nulloracle-*``,
``tripwires-*``, ``sandbox-*``) exist to disambiguate many components inside one
member, and this member has one.  ``forward`` sorts between ``fixture-store``
and ``ingest`` — the two names it lands between in the composed application's
name-sorted ``app.order``, verified against the composed order rather than
guessed at — so every existing adjacency assertion there is untouched.  The
name is the *store*, not the endpoint: the endpoint is a thin seam that holds
no state of its own and can be built from the store at any time
(:meth:`~forward.record.PromoteEndpoint.from_env`), so the thing a deployment
actually holds — a table in the database ``DATABASE_URL`` names, written by the
promotion pipeline and read by feature 334's endpoint — is what is composed.

**Why this member registers where its sibling's later features do not.**  The
promotion member's post-291 features add no component, and its docstring gives
the reason: a builder takes no arguments and is built on every ``create_app()``
call, while those acts are functions of evidence the factory does not hold.  The
distinction is not *statefulness* but *what the factory can supply*.  A forward
record's act is a function of a **promotion instant**, and that instant lives in
a database the deployment names — the same fact ``DATABASE_URL`` states.  So the
store the deployment holds is one table pointer, and it composes exactly as the
promotion member's registry does.  Features 333-340 read and extend that same
table through the component this builder registers, or through
:func:`~forward.record.forward_record` when they hold a URL and no app.

**The three sibling spellings, and which to reach for.**  A caller with a
composed application asks the seat (``app.modules.forward``) for the store.  A
caller holding a store calls :meth:`~forward.record.ForwardRecords.open_record`
and gets ``(record, created)``.  A caller holding only a URL calls
:func:`~forward.record.forward_record` and gets the record.  Every one of them
reads the promotion instant through :func:`~forward.window.
read_promotion_window`, so there is one read of feature 293's stamp in this
package and every path to a record goes through it.
"""

from __future__ import annotations

from app.module_loader import register

from .errors import (
    FORWARD_IDENTITY_ERROR_CODE,
    FORWARD_PROMOTION_ERROR_CODE,
    FORWARD_RECORD_ERROR_CODE,
    ForwardError,
    ForwardIdentityError,
    ForwardPromotionError,
    ForwardRecordError,
    ForwardStoreError,
)
from .record import (
    DATABASE_URL_ENV,
    FORWARD_PROMOTE_ROUTE,
    NODE_ID_COLUMN,
    OBSERVED_ON_COLUMN,
    PROMOTED_AT_COLUMN,
    ForwardRecord,
    ForwardRecordRequest,
    ForwardRecordResponse,
    ForwardRecords,
    PromoteEndpoint,
    forward_record,
    utc_now,
)
from .schema import FORWARD_RECORD_TABLE, MIGRATION_ORDER, bootstrap_schema
from .window import PROMOTION_MEMBER, PROMOTION_WINDOW_VERB, read_promotion_window

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "FORWARD_IDENTITY_ERROR_CODE",
    "FORWARD_PROMOTE_ROUTE",
    "FORWARD_PROMOTION_ERROR_CODE",
    "FORWARD_RECORD_ERROR_CODE",
    "FORWARD_RECORD_TABLE",
    "MIGRATION_ORDER",
    "NODE_ID_COLUMN",
    "OBSERVED_ON_COLUMN",
    "PROMOTED_AT_COLUMN",
    "PROMOTION_MEMBER",
    "PROMOTION_WINDOW_VERB",
    "ForwardError",
    "ForwardIdentityError",
    "ForwardPromotionError",
    "ForwardRecord",
    "ForwardRecordError",
    "ForwardRecordRequest",
    "ForwardRecordResponse",
    "ForwardRecords",
    "ForwardStoreError",
    "PromoteEndpoint",
    "bootstrap_schema",
    "build_forward_records",
    "forward_record",
    "read_promotion_window",
    "utc_now",
]

#: The name this member registers its forward-record store under.  Unprefixed,
#: following the precedent for a member's first and only component, and spelled
#: here once so the seat (``src/app/modules/forward``) and the composed
#: application agree on the key — the seat repeats the literal and its suite
#: asserts the two match, so the pair cannot drift apart silently.
#: ``forward`` sorts between ``fixture-store`` and ``ingest``, clear of both.
COMPONENT_NAME = "forward"


@register(COMPONENT_NAME)
def build_forward_records() -> ForwardRecords | None:
    """Component builder: the forward-record store this deployment writes into.

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the store for the deployment the process is actually running in.  The
    endpoint that serves the route is built from it
    (:meth:`PromoteEndpoint.from_env`), so the composed component and the route
    always point at the same database.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately not an empty store: a store over a fresh database answers
    *this signal holds no forward record* about every identity it is asked for,
    while this ``None`` says there is no database a record could have been
    written into at all — the distinction the promotion member draws between an
    empty registry and an unconfigured one, at the level of the whole table.  A
    caller whose pipeline has just promoted a signal has to treat the ``None``
    as a refusal to proceed rather than as a store that happened to find
    nothing, because §5's loop leaves nothing to fall back on: a promotion
    whose record never opened is a signal whose out-of-sample life began
    unrecorded, and no later reader can recover the instant it should have
    carried.

    Never raises — including for a URL whose scheme the store cannot speak,
    which is refused by name the first time an operation needs the path rather
    than here.  Construction performs no I/O: the path is resolved on first use
    and the schema is brought up on the first
    :meth:`~forward.record.ForwardRecords.open_record`, so composing the
    application neither opens a database nor creates a table.  It reads no
    promotion either: the promotion member is reached for the first time when a
    record is actually being opened.
    """
    return ForwardRecords.resolve()
