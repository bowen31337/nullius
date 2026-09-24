"""The promotion plugin: pre-registered criteria, hashed before the decision.

Implements app_spec.xml, "Promotion & Epoch Governance", feature 291 —
*"System exposes POST /promotion/pre-register, which returns a criteria hash
recorded before the deciding evaluation runs"* — against
docs/alpha-engine-prd.md §13 item 7, *"Promotion criteria are pre-registered
and hashed before the evaluation that decides them"*, and against the
``promotion_registry`` table feature 108's migration
(``migrations/versions/0108_forward_and_universe_tables.py``) already
declares.

The member's surface is ten modules.  :mod:`promotion.criteria` is *what* a
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
migrations'* own ``statements("sqlite")`` for the tables this member's
statements need — feature 291's three (``node``, ``epoch_ledger`` and
``promotion_registry``), feature 298's two (``node`` and ``campaign``),
feature 293's one (``promotion_registry`` alone) and feature 294's one
(``epoch_ledger`` alone), one set per act — so this
member authors no DDL and cannot drift from the schema's owners.  :mod:`promotion.blocking` is feature 299's *reason*:
:class:`~promotion.blocking.PromotionBlocks`, the store that records why a
promotion was blocked on §C7's regime coverage, with
:class:`~promotion.blocking.PromotionBlock` as the row and
:func:`~promotion.blocking.blocking_reason` rendering the one canonical sentence
that row explains itself with.  :mod:`promotion.calibration` is feature 298's
*refusal*: :class:`~promotion.calibration.PromotionCalibrations`, the gate that
follows a promoted node to the campaign that spawned it and refuses the
promotion when that campaign's §7.4 verdict is ``VOID``, with
:func:`~promotion.calibration.rejects_void_calibration` as the comparison and
:func:`~promotion.calibration.rejects_void_promotion` as the act.  The two are
the category's two merit refusals and are deliberately **not** one thing: they
read different tables, they answer different questions, and their repairs differ
— grow the pool's coverage (§C7) versus re-plan a campaign whose control is gone
(§7.4).  :mod:`promotion.decision` is feature 293's *stamp*:
:class:`~promotion.decision.PromotionDecisions`, the store that persists each
promotion decision by closing the row the pre-registration opened — one
``UPDATE`` whose ``SET`` clause names ``decided_at`` and nothing else, so the
criteria hash the decision is checked against is a column the closing write
cannot touch — with :func:`~promotion.decision.record_decision` as the act and
:func:`~promotion.decision.promotion_decision` as the read.  It judges
nothing: the verdict is the deciding evaluation's and the mismatch refusal is
292's; what it persists is the decision's timestamp beside the standing hash,
the two facts §13 item 4's epoch count and feature 360's invariant read off
the row.  :mod:`promotion.epoch` is feature 294's *charge*:
:class:`~promotion.epoch.EpochCharges`, the store that persists the running
promotion decision count against the serving epoch in the ``epoch_ledger``
— one ``UPDATE`` whose ``SET`` clause names ``promotion_decisions_served``
and nothing else, re-supplying the figure derived from the closed rows
feature 293's listing holds against the epoch the node's row booked rather
than incrementing it, so the count stays a function of the registry and a
retried charge recomputes the same number — with
:class:`~promotion.epoch.ServingEpoch` as the row as the charge reads it,
:func:`~promotion.epoch.decisions_served` as the derivation on its own,
and :func:`~promotion.epoch.charge_epoch` /
:func:`~promotion.epoch.epoch_charge` as the write and the read.  It
judges nothing and it takes no ``epoch_id``: the epoch billed is read off
the row the pre-registration booked, the mirror of the decision's own
refusal, and the threshold the count feeds is features 295-297's.
:mod:`promotion.selection` is feature 295's *gate*:
:class:`~promotion.selection.EpochSelections`, the reader that refuses
further selection of a sequestered epoch once it has served §13 item 4's
three promotion decisions — reading the row through
:meth:`~promotion.epoch.EpochCharges.epoch`, feature 294's own seam, so
the gate holds no connection, authors no DDL and spells no statement —
with :data:`~promotion.selection.SEQUESTERED_EPOCH_BUDGET` as the PRD's
own number spelled once and
:func:`~promotion.selection.rejects_further_selection` as the comparison
on its own, :func:`~promotion.selection.select_epoch` as the act at module
level.  It judges the count and only the count — the ``retired`` flag is
feature 296's and the depleting remainder feature 297's — and it writes
nothing: the refusal is the act.  :mod:`promotion.forward` is feature 300's *window*:
:class:`~promotion.forward.PromotionWindow`, the derived forward measurement
window a promotion opened — the feature's sentence, *"timestamps every promoted
signal at promotion, which creates its forward measurement window"*, answered as
the half-open interval running from feature 293's stamp for the horizon the
caller registered — with
:class:`~promotion.forward.PromotionWindows` as the store that reads it through
:mod:`promotion.decision`'s own seam rather than a second ``SELECT``,
:func:`~promotion.forward.promotion_window` and
:func:`~promotion.forward.promotion_windows` as the acts, and
:func:`~promotion.forward.window_closes_at` as the arithmetic on its own.  It is
a **read**: it writes nothing, spells no DDL, and leaves the ``forward`` plugin's
``forward_record`` (feature 332's writer) entirely alone — what it answers is the
interval that record is opened against.  :mod:`promotion.errors` is the member's error
vocabulary: :class:`~promotion.errors.PromotionError` (the *ask* face: a
malformed body, a criterion that is not a number, a re-registration with
different criteria), :class:`~promotion.errors.PromotionStoreError` (the
*address, parent and write* face, every message opening
:data:`~promotion.errors.PROMOTION_REGISTRY_ERROR_CODE`), feature 299's
:class:`~promotion.errors.PromotionBlockError` (the *§C7 coverage* merit face —
a promotion refused on the pool's coverage rather than on form), feature
298's :class:`~promotion.errors.VoidCalibrationError` (the *§7.4 calibration*
merit face, opening :data:`~promotion.errors.VOID_CALIBRATION_ERROR_CODE`, the
literal it shares with feature 243's own gate in the discovery member), and
feature 293's :class:`~promotion.errors.PromotionDecisionError` (the
*recording* face, opening
:data:`~promotion.errors.PROMOTION_DECISION_ERROR_CODE` — a decision that
happened and was not recorded, gathered across its ask, address, absence,
ordering and write faces because a gate's one failure mode is silence),
feature 294's :class:`~promotion.errors.EpochChargeError` (the *counting*
face, opening :data:`~promotion.errors.EPOCH_CHARGE_ERROR_CODE` — an
epoch's running decision count that did not land in the ledger, gathered
across the same gate's faces for the same caller-position reason, and
spelled beside the decision's word but not in its letter because the two
are two writes to two tables one decision apart), feature
295's :class:`~promotion.errors.EpochSelectionError` (the *budgeting*
face, opening :data:`~promotion.errors.EPOCH_SELECTION_ERROR_CODE` —
further selection of a sequestered epoch refused because the count §13
item 4 budgets it by has been served, gathered across the same gate's
faces for the same caller-position reason, and spelled beside the charge's
word but not in its letter because the two are the write and the refusal
over one column), and
feature 300's :class:`~promotion.errors.PromotionWindowError` (the *reading*
face, opening
:data:`~promotion.errors.PROMOTION_WINDOW_ERROR_CODE` — a window that could not
be opened, gathered across the same ask, address, absence and row faces for the
same caller-position reason, and spelled beside the decision's word but not in
its letter because the two are two *acts* over one row: an operator greps one for
*a stamp did not land* and the other for *a window could not be opened*, and
landing on the wrong one sends them debugging a write that never happened), split
by the repair rather than by the code path except where a gate's caller
position overrides the split — the argument that module states.  This module re-exports
all of it and registers the one component; it carries no logic of its own, which
is the same shape every member in this workspace takes.

**The two-timestamp law is created here and enforced elsewhere.**  ``0108``
declares ``pre_registered_at TIMESTAMPTZ NOT NULL`` and ``decided_at
TIMESTAMPTZ`` nullable, and its own comment says why: *"``decided_at`` is
nullable because the row is written while the decision is still open, which
is the only ordering under which pre-registration means anything."*  The
member writes the first timestamp in a statement that cannot write the second,
and the second in a statement that cannot write the first: the insert's column
list has four columns and ``decided_at`` is not among them, so a
pre-registration row is born open by the *shape* of the statement rather than
by a check the writer remembers to make — and :mod:`promotion.decision`'s
update names ``decided_at`` in its ``SET`` clause and nothing else, so the
closing write cannot touch the hash, the epoch or the first stamp either.
Each half of §13 item 7's ordering is enforced by the *other* statement's
shape, and neither by a check the writer remembers to make.  Feature 292
judges a promotion against the recorded hash; feature 360 is the CI invariant
that refuses a merge when criteria were recorded after the deciding
evaluation, and the decision store refuses that finding's write-side face — a
stamp that would precede the criteria it was judged against.  This member's
job is to make the ordering *possible* to enforce, which means making it true
in the table rather than in a docstring.

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
campaign row (and is constructed from a URL by the caller that has one, like
299's block store beside it), and 300's forward window is a pair of figures
*derived* from the stamp 293's write placed — a read through that store rather
than a second thing to persist.
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
from .calibration import (
    CALIBRATION_STATUS_COLUMN,
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    CAMPAIGN_ID_COLUMN,
    CAMPAIGN_TABLE,
    PromotionCalibrations,
    campaign_calibration,
    rejects_void_calibration,
    rejects_void_promotion,
)
from .criteria import CRITERIA_FIELDS, PromotionCriteria, criteria_hash
from .decision import PromotionDecisions, promotion_decision, record_decision
from .epoch import (
    PROMOTION_DECISIONS_SERVED_COLUMN,
    RETIRED_COLUMN,
    SEALED_AT_COLUMN,
    EpochCharges,
    ServingEpoch,
    charge_epoch,
    decisions_served,
    epoch_charge,
)
from .errors import (
    EPOCH_CHARGE_ERROR_CODE,
    EPOCH_SELECTION_ERROR_CODE,
    NO_CLEAN_EPOCH_REMAINS_CODE,
    PROMOTION_BLOCK_ERROR_CODE,
    PROMOTION_DECISION_ERROR_CODE,
    PROMOTION_REGISTRY_ERROR_CODE,
    PROMOTION_WINDOW_ERROR_CODE,
    VOID_CALIBRATION_ERROR_CODE,
    EpochChargeError,
    EpochSelectionError,
    PromotionBlockedError,
    PromotionBlockError,
    PromotionDecisionError,
    PromotionError,
    PromotionStoreError,
    PromotionWindowError,
    VoidCalibrationError,
)
from .forward import (
    CLOSES_AT_COLUMN,
    FORWARD_WINDOW_TABLE,
    OPENS_AT_COLUMN,
    PROMOTED_AT_COLUMN,
    WINDOW_DAYS_COLUMN,
    PromotionWindow,
    PromotionWindows,
    promotion_window,
    promotion_windows,
    window_closes_at,
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
    CALIBRATION_MIGRATION_ORDER,
    CHARGE_MIGRATION_ORDER,
    DECISION_MIGRATION_ORDER,
    EPOCH_LEDGER_TABLE,
    MIGRATION_ORDER,
    PROMOTION_REGISTRY_TABLE,
    bootstrap_calibration_schema,
    bootstrap_charge_schema,
    bootstrap_decision_schema,
    bootstrap_schema,
    migrations_dir,
)
from .selection import (
    SEQUESTERED_EPOCH_BUDGET,
    EpochSelectionError,
    EpochSelections,
    rejects_further_selection,
    select_epoch,
)
from .terminal import (
    TerminalStates,
    block_when_no_clean_epoch_remains,
    blocks_when_no_clean_epoch_remains,
)

__all__ = [
    "BLOCKED_AT_COLUMN",
    "CALIBRATION_MIGRATION_ORDER",
    "CALIBRATION_STATUS_COLUMN",
    "CALIBRATION_STATUS_OK",
    "CALIBRATION_STATUS_VOID",
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "CHARGE_MIGRATION_ORDER",
    "CLOSES_AT_COLUMN",
    "COMPONENT_NAME",
    "COVERAGE_THRESHOLD_COLUMN",
    "CRITERIA_FIELDS",
    "CRITERIA_HASH_COLUMN",
    "DATABASE_URL_ENV",
    "DECIDED_AT_COLUMN",
    "DECISION_MIGRATION_ORDER",
    "EPOCH_CHARGE_ERROR_CODE",
    "EPOCH_ID_COLUMN",
    "EPOCH_LEDGER_TABLE",
    "EPOCH_SELECTION_ERROR_CODE",
    "FORWARD_WINDOW_TABLE",
    "MIGRATION_ORDER",
    "NODE_ID_COLUMN",
    "OPENS_AT_COLUMN",
    "PRE_REGISTERED_AT_COLUMN",
    "PRE_REGISTER_ROUTE",
    "PROMOTED_AT_COLUMN",
    "PROMOTION_BLOCK_ERROR_CODE",
    "PROMOTION_BLOCK_TABLE",
    "PROMOTION_DECISIONS_SERVED_COLUMN",
    "PROMOTION_DECISION_ERROR_CODE",
    "PROMOTION_REGISTRY_ERROR_CODE",
    "PROMOTION_REGISTRY_TABLE",
    "PROMOTION_WINDOW_ERROR_CODE",
    "REGIME_COLUMN",
    "RETIRED_COLUMN",
    "SEALED_AT_COLUMN",
    "SEQUESTERED_EPOCH_BUDGET",
    "VOID_CALIBRATION_ERROR_CODE",
    "WINDOW_DAYS_COLUMN",
    "WORLD_COUNT_COLUMN",
    "EpochChargeError",
    "EpochCharges",
    "EpochSelectionError",
    "EpochSelections",
    "NO_CLEAN_EPOCH_REMAINS_CODE",
    "PreRegisterEndpoint",
    "PreRegistrationRequest",
    "PreRegistrationResponse",
    "PreRegistrations",
    "PromotionBlock",
    "PromotionBlockedError",
    "PromotionBlockError",
    "PromotionBlocks",
    "PromotionCalibrations",
    "PromotionCriteria",
    "PromotionDecisionError",
    "PromotionDecisions",
    "PromotionError",
    "PromotionRecord",
    "PromotionStoreError",
    "PromotionWindow",
    "PromotionWindowError",
    "PromotionWindows",
    "ServingEpoch",
    "TerminalStates",
    "VoidCalibrationError",
    "block_when_no_clean_epoch_remains",
    "blocked_promotion",
    "blocking_reason",
    "blocks_when_no_clean_epoch_remains",
    "bootstrap_calibration_schema",
    "bootstrap_charge_schema",
    "bootstrap_decision_schema",
    "bootstrap_schema",
    "build_promotion_registry",
    "campaign_calibration",
    "charge_epoch",
    "criteria_hash",
    "decisions_served",
    "epoch_charge",
    "migrations_dir",
    "promotion_decision",
    "promotion_window",
    "promotion_windows",
    "record_decision",
    "rejects_further_selection",
    "rejects_void_calibration",
    "rejects_void_promotion",
    "select_epoch",
    "utc_now",
    "window_closes_at",
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
