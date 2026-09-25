"""The forward plugin: one record per promoted signal, carrying its instant.

Implements app_spec.xml, "Forward-Test Tracking", feature 332 — *"System
exposes POST /forward/promote, which creates a forward_record carrying the
promotion timestamp"* — against docs/alpha-engine-prd.md §5 Loop 3, *"Every
promoted signal is timestamped and its live forward IC tracked from the
promotion date forward.  After 90 days, that signal has a track record on data
that did not exist when the hypothesis was formed"*, and against the
``forward_record`` table feature 108's migration
(``migrations/versions/0108_forward_and_universe_tables.py``) already declares.

The member's surface is seven modules, and each answers one question.

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

:mod:`forward.observation` is **the tracking** — feature 333, the second
clause of §5's sentence.  :class:`~forward.observation.ForwardObservations`
appends the rows that carry the live information coefficient, one per
observation date, each stating its own day and reading its ``promoted_at``
off the record's standing rows rather than off the registry.  The store is
built over the composed one
(:meth:`~forward.observation.ForwardObservations.over`) — the same table in
the same database — and holds the one-row-per-date law in the write path,
where ``0108`` declined to hold it in a constraint: a retry is answered by
the standing row, a different coefficient for a standing day is refused, and
no day on or before the boundary is observed at all.

:mod:`forward.reconciliation` is **the cost half** — feature 340, the loop
§13.4 closes: *"Those outcomes become the labels that recalibrate ``β₄``
and the decay priors in the outer loop."*  A rebalance's fills are one of
those outcomes.
:class:`~forward.reconciliation.ForwardCostReconciliations` persists one row
per rebalance — the ``(book_id, rebalance_ts)`` pair feature 309 persists
and feature 316 hashes — carrying the realized fill cost against the
modeled cost, both in basis points, and the difference the store computes
between them: §6.2's *"divergence between these two is exactly the
quantity ``β₄`` penalizes"*, §16's live metric, and the fact §15's repair
(*reconcile the cost model*) starts from.  The table is the module's own
(see the paragraph on the three NULL columns below for why it is not a
column on the record), the difference is computed and never stated, and a
second reconciliation naming different figures for one rebalance is
refused — the one-row law the record holds, one grain over.

:mod:`forward.retention` is **the criterion** — feature 337, prd §11's
*"Forward-test IC retention: live IC ÷ backtest IC at 90 days | > 0.5"* and
§C10's *"if live IC falls below 40% of backtest IC over a statistically
meaningful window, demote automatically."*
:class:`~forward.retention.ForwardIcRetentions` lands the backtest
coefficient on the record's opening row — the column ``0108`` drew for this
feature and which neither writer before it may name — and divides the
record's own live coefficients by it, answering
:class:`~forward.retention.IcRetention`.  Both operands are **read**: the
live IC is the mean of feature 333's observed rows with the day count beside
it as the evidence §11's *"at 90 days"* counts, and the backtest IC is the
figure the caller landed once and the row kept — this member never reads the
evaluation member's tables, so prd §6.1's ``metrics.ic_mean`` arrives from
the caller rather than being fetched.  A zero backtest is refused at the
division rather than answered with an infinity or a zero, and the ratio
carries **no bound**: over-delivery above one and inversion below zero are
both facts §11 and §C10 read, which is why the scoring member declines to
charge on this ratio at all.

:mod:`forward.priors` is **the outer loop's other recalibration** — feature
339, §13.4's third clause: *"Those outcomes become labels. They recalibrate
``β₄`` (sim-reality divergence), the decay priors, and which signal families
the objective should reward."*  A signal's forward half-life is the day its
prefix retention — feature 337's own statistic, computed on prefixes —
first falls to §11's half line, and :class:`~forward.priors.ForwardDecayPriors`
folds every observed half-life into the 90-day prior the prd itself states
(§5's *"After 90 days"*), at the pseudo-count strength feature 228
established.  The answer :class:`~forward.priors.DecayPriorRevision` is the
revised input the risk register's mitigation names — *"feed half-life into
``plan_grid``"* — carried with its evidence (the half-lives, the censored
bounds, the absences) and **persisted nowhere**: the revision is a pure
function of rows features 332, 333 and 337 already hold, and where a
campaign's planned-with figures live is the planning side's own question.
A signal that has not fallen to half is *censored*, not dead — its bound is
counted, never averaged in — and the aggregate counts what it cannot
measure (young, unbacktested, edgeless signals) where the per-signal ask
refuses the same states, each naming its one-call repair.

:mod:`forward.errors` is **what can go wrong**, split by the repair the caller
must make: a malformed row, a store that is misrouted or broken, a promotion
with no instant to open at, a reconciliation whose book, instant or figures
state nothing measurable, a division whose operands do not support it, a
revision whose half-lives cannot be dated or whose evidence does not blend,
and a request that disagrees with a row an identity already holds — a second
promotion instant, a day the boundary excludes, a second coefficient claiming
a measured day, or a second reconciliation claiming a rebalance that already
holds one.

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
Feature 333 fills ``live_ic``, feature 337 lands ``backtest_ic`` on the
opening row and divides the one by the other;
``realized_cost_bps`` stays NULL for the signal-day aggregate the column was
drawn for, because feature 340's sentence prices a different grain — *per
rebalance*, the ``(book_id, rebalance_ts)`` pair no column of this table
names — and lands its differences in its own table
(:data:`~forward.reconciliation.FORWARD_COST_RECONCILIATION_TABLE`) rather
than allocating one book-level figure across signal-days, an allocation no
spec states and no honest default exists for.  A writer here that guessed
would be answering for features that have not run — the same boundary the
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
database through the component this builder registers — feature 340's table
lands in it beside the record, authored by the one module that writes it — or
through :func:`~forward.record.forward_record`,
:func:`~forward.observation.forward_observation` and
:func:`~forward.reconciliation.reconcile_fill_costs` when they hold a URL and
no app.

**The three sibling spellings, and which to reach for.**  A caller with a
composed application asks the seat (``app.modules.forward``) for the store.  A
caller holding a store calls :meth:`~forward.record.ForwardRecords.open_record`
and gets ``(record, created)``.  A caller holding only a URL calls
:func:`~forward.record.forward_record` and gets the record.  Every one of them
reads the promotion instant through :func:`~forward.window.
read_promotion_window`, so there is one read of feature 293's stamp in this
package and every path to a record goes through it.  The observing act mirrors
the same ladder one feature later — :meth:`~forward.observation.
ForwardObservations.over` off the composed store,
:meth:`~forward.observation.ForwardObservations.append_observation` on a held
one, :func:`~forward.observation.forward_observation` from a bare URL.  It
never re-reads the promotion registry — the instant its rows carry is the
record's own, read once at the open — but feature 335 measures the window's
far edge against that same instant, reaching the promotion member's
``window_closes_at`` arithmetic through :func:`~forward.window.
read_window_close` rather than re-reading feature 293's stamp, so the lower
bound (feature 333) and the upper bound (feature 335) are measured against the
one instant the record carries.  The reconciling act is the same ladder one grain
over — :meth:`~forward.reconciliation.ForwardCostReconciliations.over` off
the composed store,
:meth:`~forward.reconciliation.ForwardCostReconciliations.reconcile` on a
held one, :func:`~forward.reconciliation.reconcile_fill_costs` from a bare
URL — and reads neither a promotion nor a record: the rebalance it prices
is named by the pair the order path already hashed, and the figures arrive
from the paths that measured them.  The retaining act climbs the same ladder
one feature later — :meth:`~forward.retention.ForwardIcRetentions.over` off
the composed store,
:meth:`~forward.retention.ForwardIcRetentions.record_backtest_ic` or
:meth:`~forward.retention.ForwardIcRetentions.retention` on a held one,
:func:`~forward.retention.forward_ic_retention` from a bare URL — and is the
one act in this member with two, because it both lands a figure and computes
one: the writer refuses an unconfigured deployment while the reader's
``resolve`` answers ``None``, the way :func:`~forward.reconciliation.
reconciled_fill_costs` answers nothing rather than refusing it.  The
revising act climbs the same ladder one feature later again —
:meth:`~forward.priors.ForwardDecayPriors.over` off the composed store,
:meth:`~forward.priors.ForwardDecayPriors.half_life` or
:meth:`~forward.priors.ForwardDecayPriors.revise` on a held one,
:func:`~forward.priors.forward_half_life` and
:func:`~forward.priors.revised_decay_prior` from a bare URL — and lands
nothing anywhere: it is the member's one act that only reads, because every
figure it answers is derived from rows the other acts already hold.
"""

from __future__ import annotations

from app.module_loader import register

from .errors import (
    FORWARD_DECAY_PRIOR_ERROR_CODE,
    FORWARD_IDENTITY_ERROR_CODE,
    FORWARD_PROMOTION_ERROR_CODE,
    FORWARD_RECONCILIATION_ERROR_CODE,
    FORWARD_RECORD_ERROR_CODE,
    FORWARD_RETENTION_ERROR_CODE,
    ForwardDecayPriorError,
    ForwardError,
    ForwardIdentityError,
    ForwardPromotionError,
    ForwardReconciliationError,
    ForwardRecordError,
    ForwardRetentionError,
    ForwardStoreError,
)
from .observation import (
    FORWARD_OBSERVATION_SEAM,
    ForwardObservations,
    forward_observation,
)
from .priors import (
    FORWARD_PRIOR_SEAM,
    PRIOR_HALF_LIFE_DAYS,
    PRIOR_WEIGHT,
    RETENTION_LINE,
    REVISED_HALF_LIFE_KEY,
    DecayPriorRevision,
    ForwardDecayPriors,
    ForwardHalfLife,
    forward_half_life,
    revised_decay_prior,
)
from .reconciliation import (
    FORWARD_COST_RECONCILIATION_TABLE,
    FORWARD_RECONCILIATION_SEAM,
    CostReconciliation,
    ForwardCostReconciliations,
    reconcile_fill_costs,
    reconciled_fill_costs,
)
from .record import (
    DATABASE_URL_ENV,
    FORWARD_PROMOTE_ROUTE,
    LIVE_IC_BOUND,
    LIVE_IC_COLUMN,
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
from .retention import (
    BACKTEST_IC_COLUMN,
    FORWARD_RETENTION_SEAM,
    RETENTION_RATIO_KEY,
    ForwardIcRetentions,
    IcRetention,
    forward_ic_retention,
)
from .schema import FORWARD_RECORD_TABLE, MIGRATION_ORDER, bootstrap_schema
from .window import PROMOTION_MEMBER, PROMOTION_WINDOW_VERB, read_promotion_window

__all__ = [
    "BACKTEST_IC_COLUMN",
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "FORWARD_COST_RECONCILIATION_TABLE",
    "FORWARD_DECAY_PRIOR_ERROR_CODE",
    "FORWARD_IDENTITY_ERROR_CODE",
    "FORWARD_OBSERVATION_SEAM",
    "FORWARD_PRIOR_SEAM",
    "FORWARD_PROMOTE_ROUTE",
    "FORWARD_PROMOTION_ERROR_CODE",
    "FORWARD_RECONCILIATION_ERROR_CODE",
    "FORWARD_RECONCILIATION_SEAM",
    "FORWARD_RECORD_ERROR_CODE",
    "FORWARD_RECORD_TABLE",
    "FORWARD_RETENTION_ERROR_CODE",
    "FORWARD_RETENTION_SEAM",
    "LIVE_IC_BOUND",
    "LIVE_IC_COLUMN",
    "MIGRATION_ORDER",
    "NODE_ID_COLUMN",
    "OBSERVED_ON_COLUMN",
    "PRIOR_HALF_LIFE_DAYS",
    "PRIOR_WEIGHT",
    "PROMOTED_AT_COLUMN",
    "PROMOTION_MEMBER",
    "PROMOTION_WINDOW_VERB",
    "RETENTION_LINE",
    "RETENTION_RATIO_KEY",
    "REVISED_HALF_LIFE_KEY",
    "CostReconciliation",
    "DecayPriorRevision",
    "ForwardCostReconciliations",
    "ForwardDecayPriorError",
    "ForwardDecayPriors",
    "ForwardError",
    "ForwardHalfLife",
    "ForwardIcRetentions",
    "ForwardIdentityError",
    "ForwardObservations",
    "ForwardPromotionError",
    "ForwardReconciliationError",
    "ForwardRecord",
    "ForwardRecordError",
    "ForwardRecordRequest",
    "ForwardRecordResponse",
    "ForwardRecords",
    "ForwardRetentionError",
    "ForwardStoreError",
    "IcRetention",
    "PromoteEndpoint",
    "bootstrap_schema",
    "build_forward_records",
    "forward_half_life",
    "forward_ic_retention",
    "forward_observation",
    "forward_record",
    "read_promotion_window",
    "reconcile_fill_costs",
    "reconciled_fill_costs",
    "revised_decay_prior",
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
