"""Feature 338 — the revised beta-four coefficient, persisted per cycle.

app_spec.xml, "Forward-Test Tracking", feature 338: *System persists the
revised beta-four value per cycle, fed back from observed sim-reality
divergence.*  The sentence is prd §5 Loop 3's third clause made operative —
*"Those outcomes become labels.  They recalibrate ``β₄`` (sim-reality
divergence), the decay priors, and which signal families the objective should
reward"* — and docs/nullius-tech-architecture.md §13.4 states it from the
other side (line 729): *"Those outcomes become the labels that recalibrate
``β₄`` and the decay priors in the outer loop."*  The decay priors are
feature 339's; the signal families are a later feature's.  β₄ is this
module's.

**What β₄ is, and why the outer loop owns it.**  β₄ is the coefficient of
prd §7.1's fourth term (line 322) — ``− β₄ · | IC_forward − IC_backtest |``,
whose own comment reads *# sim-reality divergence* — the one charge that
takes away for the gap between what a signal's backtest promised and what
its forward test delivered.  The scoring member's own module
(:mod:`scoring._divergence`, feature 260) sizes its default at a half and
states the expectation plainly: the coefficient is *"the dreaming loop's
offline tuning... expected to set it per cycle"*, and *"the whole outer loop
exists to recalibrate this one number"*.  This module is that recalibration:
it reads the divergence the forward records actually observed, revises the
coefficient from it, and persists the revised value — one row per cycle —
so the dreaming loop's next cycle and every operator auditing it read the
same figure from one place.

**Why this feature persists where its sibling returns.**  The category's
two Loop 3 sentences split on their own verbs: feature 339 (*returns
revised inputs to campaign planning*) authors no table, because the
planning side's manifests (feature 242) are the memory its figure feeds;
feature 338 says *persists*, and its consumer has no memory of its own.
β₄'s reader is the dreaming loop — feature 260's ``beta`` parameter, run
with per cycle and recorded per run in ``replay_score.beta`` (feature 255)
— and a replay row is an *output*: it carries the coefficient a run used,
not the coefficient the next run should use.  Something has to hold the
standing value between cycles, and the table this module authors is that
thing.  The persisted chain is also what makes the feature's own feedback
auditable: each row states the value it revised from, the evidence that
moved it, and the value it landed, so a reader can verify the whole ladder
of cycles from the rows alone.

**The feedback is the chain.**  *"Fed back"* is loop vocabulary, and the
thing fed back is the loop's own output: each cycle's revision blends the
**standing value** — the latest persisted row's ``revised_beta_four`` —
with the divergence the forward records hold as they stand, at the
pseudo-count strength feature 228 established::

    revised = (BETA_FOUR_WEIGHT × prior + Σ observed divergences)
              / (BETA_FOUR_WEIGHT + n)

The head of the chain — the prior a first cycle blends from, and the
figure a deployment with no row yet runs — is :data:`BETA_FOUR_PRIOR`:
``0.5``, feature 260's own ``BETA_FOUR_DEFAULT``, spelled here because a
member never imports a sibling.  The zero-evidence law therefore holds at
**every link**: a cycle over no measurable signal answers the standing
value exactly (``n = 0`` makes the blend the prior), and a database with
no row at all answers the stated default — the same stance feature 228
takes (*zero-evidence == schedule(beta)*) and feature 339 takes toward its
90-day prior.  Each observed divergence moves the coefficient by
``1/(weight + n)`` of the distance between it and the standing value, so
the chain is a tracker: a fleet whose records stop moving converges on the
fleet's own mean observed divergence — the severity the evidence itself
states, which is prd M5's steady state (*"Forward-test queue begins
feeding ``β₄``.  Exit: none."*).

**The evidence is the term's own quantity, per measured signal.**  prd
§7.1 line 322's comment names ``| IC_forward − IC_backtest |`` *sim-reality
divergence*, so that is what a cycle folds: for every signal whose record
holds observations and a landed backtest coefficient, one divergence —
the mean of feature 333's observed ``live_ic`` rows against the opening
row's ``backtest_ic`` (the column feature 337 lands and the only writer of
it), both read through :data:`forward.record._READ_SQL` so the rows this
act charges over and the rows every other act answered with cannot be two
readings of one table.  The fleet read is feature 339's own
classification, one feature earlier in the same loop: a signal whose
backtest has not landed is *unbacktested* — counted, not fatal, because a
young deployment's outer loop must not block on the one figure that has
not arrived; one with a divisor and no observations is *unobserved*; one
whose backtest is exactly zero is *zero-backtest* — the honest figure of
a signal with no measured edge, which made no claim the forward test
could flatter, so it states nothing about how honest backtests are; and a
**negative** backtest refuses the whole revision, because promotion
requires a positive edge and the row contradicts the promotion that
opened it.  A zero divergence is admitted and is the good news: a signal
whose live IC met its backtest is a backtest the forward test vindicated,
and it pulls the coefficient toward nothing to penalize.

**The cost face is read, carried, and deliberately not blended.**  docs
§6.2 (line 259) makes the evaluator and the live engine share one cost
model because *"divergence between these two is exactly the quantity
``β₄`` penalizes"* — the realized-vs-modeled fill cost gap, feature 340's
per-rebalance rows.  §13.4's recalibration therefore sweeps that ledger
too: :meth:`ForwardBetaFourRevisions.revise` reads **every** rebalance's
divergence, oldest first (:meth:`forward.reconciliation.
ForwardCostReconciliations.reconciliations`), and the row persists the
count beside the signed sum in basis points — the sign being prd's *cost
model optimism*, the one direction that quietly flatters every backtest,
and the fact §15's repair (*reconcile the cost model*) starts from.  What
the sweep's figures do **not** do is enter the blend: β₄ multiplies an IC
gap in the objective prd §7.1 states, a basis-point gap is a different
quantity on a different scale, and no document states a conversion
between them — folding one into the other would be exactly the invented
arithmetic this member's insert-naming and re-derivation laws exist to
refuse.  The bps figures are carried as evidence beside the figure they
qualify, the way :class:`forward.reconciliation.CostReconciliation`
carries both sides beside the difference it computes: an operator auditing
a revised β₄ reads both faces of the divergence the documents name, and
the arithmetic stays honest about which one the term charges on.

**One row per cycle, held three ways.**  The law lives in the write path
(a check-and-insert inside one transaction on one connection), in the
schema (``UNIQUE (cycle_id)``, which this member *may* state because this
table is its own), and in the cycle's spelling: an id is text and not
blank, the same rule :func:`dreaming.cycle.validated_iteration_id` holds
its caller to, restated here because a member never imports another — the
cycle this row belongs to is the dreaming iteration the revised value
feeds, and the outer-loop job that runs the recalibration states it.  A
**retry** — the same cycle, the evidence unmoved (the worker died between
the row and the response) — is answered by the standing row with
``created=False``, the semantics :meth:`forward.record.
ForwardRecords.open_record` establishes.  A **disagreement** — the same
cycle re-revised over evidence that has *moved* — is refused
(:class:`~forward.errors.ForwardIdentityError`, the law's per-cycle
face): the dreaming loop may already have run cycle ``k`` with the
standing value (every ``replay_score`` row feature 255 wrote carries the
β it ran with), and silently re-revising that cycle would orphan those
rows from the figure they claim to have used.  The repair is named in the
refusal: the moved evidence belongs to cycle ``k+1`` — revise that.

**The revised value is never a parameter.**  The caller names the cycle;
everything else is read.  The divergences are read off the records, the
prior off the standing row, the cost figures off the ledger, and the
blend is :class:`BetaFourRevision`'s to perform and verify — a caller
cannot hand this store a coefficient it did not compute, exactly as a
caller cannot hand feature 337 a ratio or feature 340 a difference.  The
value layer re-derives the blend in ``__post_init__`` and compares
**exactly**, for the reason every sibling states: both sides are
arithmetic this member performed itself over figures it read, so a
disagreement is not rounding — it is a value that was never the blend of
the evidence stored beside it, and a row carrying one is a hand that
reached past this store.

**The one clock is the row's own.**  ``revised_at`` is the store's fact
(:func:`forward.record.utc_now`), never a parameter — the gap between
cycles is itself readable, and a caller that could set it could forge the
cadence the chain converged at.  Every *figure* in the row is read off
the data: the divergences off days feature 333 observed, the vintage
(``observed_through``) off the latest of them, the prior off the row that
stands.  Nothing in the revision is dated by when the job happened to
run.

**No component, no route, no second registration.**  The member's
registered surface stays feature 332's one store, the stance
:mod:`forward.observation`, :mod:`forward.reconciliation` and
:mod:`forward.priors` take: the composed ``forward`` component is the
deployment's one database pointer, and this store is built over its URL
(:meth:`ForwardBetaFourRevisions.over`) or resolved from
``DATABASE_URL`` (:meth:`ForwardBetaFourRevisions.resolve`).  The spec's
own verb is *persists*, not *exposes* — the reader that makes the rows
visible is the dreaming loop's β and §16's metrics surface, not a
forward endpoint.

**Stdlib only, and import-cheap.**  ``os``, ``math``, ``sqlite3`` and the
typing shapes at module scope; from this member's own modules the error
vocabulary, the record's read spelling and validators, the retention
column, the reconciliation store and the member's one clock — no
third-party import and no import of another workspace member, so the
factory's scan imports this package for the near-nothing it always did
and a revision costs its caller only the store it already held.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Real
from pathlib import Path
from typing import Any

from .errors import (
    FORWARD_BETA_FOUR_ERROR_CODE,
    FORWARD_IDENTITY_ERROR_CODE,
    ForwardBetaFourError,
    ForwardError,
    ForwardIdentityError,
    ForwardStoreError,
)
from .reconciliation import ForwardCostReconciliations
from .record import (
    _READ_SQL,
    DATABASE_URL_ENV,
    FORWARD_RECORD_TABLE,
    NODE_ID_COLUMN,
    OBSERVED_ON_COLUMN,
    ForwardRecord,
    _record_from_row,
    _sqlite_path,
    _validated_date,
    _validated_instant,
    utc_now,
)
from .retention import _validated_backtest_ic
from .schema import bootstrap_schema

__all__ = [
    "BETA_FOUR_PRIOR",
    "BETA_FOUR_WEIGHT",
    "FORWARD_BETA_FOUR_SEAM",
    "FORWARD_BETA_FOUR_TABLE",
    "REVISED_BETA_FOUR_KEY",
    "BetaFourRevision",
    "ForwardBetaFourRevisions",
    "revised_beta_four",
    "standing_beta_four",
]

#: This feature's own table — one row per cycle, the revised β₄ the outer
#: loop feeds back and the dreaming loop's next cycle runs with.  Deliberately
#: not a column on any table the migration tree declares: the versioned tree
#: drew the signal-day grain and is closed (this member runs ``0118``'s and
#: ``0118``'s parents' statements verbatim and never edits them), and a
#: per-cycle coefficient is a grain no revision declares — the same stance
#: :mod:`forward.reconciliation` takes for its per-rebalance ledger and
#: :mod:`risk.halt_events` for its per-event one.
FORWARD_BETA_FOUR_TABLE = "forward_beta_four_revision"

#: The prior a first cycle blends from — and the figure a deployment with no
#: row yet runs.  ``0.5`` is feature 260's own ``BETA_FOUR_DEFAULT``, the
#: value the scoring seam applies when a caller names none, spelled here
#: because a member never imports a sibling: the chain's head must be the
#: value the objective already runs, or the loop's first feedback would move
#: the coefficient away from a figure no backtest ever paid for.  Dyadic, so
#: the fixtures that pin the blend are exact in binary.
BETA_FOUR_PRIOR: float = 0.5

#: How many observed divergences the standing value is worth per cycle — its
#: pseudo-count.  Six, the strength feature 228's family conditioning gives
#: its zero-evidence prior (``w = n/(n+6)``) and feature 339's revision holds
#: its 90-day prior at: the seventh real divergence tips the blend to the
#: evidence's side within a cycle, and until then the standing value stands.
#: Spelled once so the revision's arithmetic and its documentation cannot
#: disagree.
BETA_FOUR_WEIGHT: float = 6.0

#: The key the revised figure travels under in :meth:`BetaFourRevision.
#: summary` — the one the dreaming loop reads before its next cycle.  Not a
#: column name in any *other* table: the column and the key agree here
#: because this feature *is* the persistence, and the spelling is the spec's
#: own three words (*the revised beta-four value*).
REVISED_BETA_FOUR_KEY = "revised_beta_four"

#: The attribute :meth:`ForwardBetaFourRevisions.over` reads off a composed
#: store — deliberately the same string every seam reader in this member
#: reads: every act writes or reads the one database the composed ``forward``
#: component points at, so a second seam spelling would be a second way to
#: name one database.
FORWARD_BETA_FOUR_SEAM = "database_url"

#: The table's DDL, authored here beside the only writer — the member-owned
#: stance :mod:`forward.reconciliation` takes, and deliberately not a
#: migration: the versioned tree drew the signal-day grain, and a per-cycle
#: coefficient is a grain no revision declares.
#:
#: The ``AUTOINCREMENT`` key is the chain's own law: revisions are monotone
#: and never reused, each row's ``prior_beta_four`` is the row before it, and
#: two cycles revised at the same instant keep the order they were revised
#: in.  ``UNIQUE (cycle_id)`` is the one-row-per-cycle law held structurally;
#: the write path still checks first (for the refusal that names the standing
#: row), and the constraint is what makes the law hold against a concurrent
#: writer and a hand that reaches past this store.
_SCHEMA = f"""
-- Feature 338: one row per cycle, the revised beta-four coefficient fed
-- back from observed sim-reality divergence (prd §5 Loop 3, §7.1's fourth
-- term; docs §13.4's recalibration).  `cycle_id` is the dreaming iteration
-- the revised value feeds, stated by the outer-loop job that runs the
-- recalibration.  `prior_beta_four` is the standing value this cycle
-- revised from -- the latest row's `revised_beta_four`, or feature 260's
-- own 0.5 default for a first cycle -- and `prior_weight` is the
-- pseudo-count the blend holds it at (feature 228's strength, enforced by
-- the value layer).  `divergence_sum` is the sum of the per-signal
-- observed |mean live IC - backtest IC| figures the cycle folded,
-- `observed_divergences` their count, and the three tallies state the
-- fleet the sum was *not* taken over.  `cost_reconciliations` and
-- `cost_divergence_bps` carry feature 340's swept ledger -- every
-- rebalance's realized-modeled gap, signed, in basis points -- beside the
-- figure they qualify; they are evidence, not addends: no document states
-- a conversion between a basis-point gap and the IC gap the term charges
-- on.  `observed_through` is the latest day the evidence was measured on,
-- read off the data.  `revised_beta_four` is
-- (prior_weight * prior_beta_four + divergence_sum) /
-- (prior_weight + observed_divergences), computed by the store, checked
-- by the value layer, never stated by a caller.  `revised_at` is when
-- this row was written.  Nothing updates or deletes: a cycle's revision
-- is that cycle's fact, once.
CREATE TABLE IF NOT EXISTS {FORWARD_BETA_FOUR_TABLE} (
    sequence              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id              TEXT NOT NULL,
    prior_beta_four       REAL NOT NULL,
    prior_weight          REAL NOT NULL,
    observed_divergences  INTEGER NOT NULL,
    divergence_sum        REAL NOT NULL,
    unbacktested          INTEGER NOT NULL,
    unobserved            INTEGER NOT NULL,
    zero_backtest         INTEGER NOT NULL,
    cost_reconciliations  INTEGER NOT NULL,
    cost_divergence_bps   REAL NOT NULL,
    observed_through      TEXT,
    revised_beta_four     REAL NOT NULL,
    revised_at            TEXT NOT NULL,
    UNIQUE (cycle_id)
);

-- The chain is read head-first (the standing value the next cycle blends
-- from) and whole (the audit trail: each row's prior is the row before
-- it), so the ledger's own number is the indexed column; both reads ride
-- the same scan.
CREATE INDEX IF NOT EXISTS {FORWARD_BETA_FOUR_TABLE}_sequence
    ON {FORWARD_BETA_FOUR_TABLE} (sequence);
"""

#: The columns of :data:`FORWARD_BETA_FOUR_TABLE` in the order the insert
#: names them and the read unpacks them — spelled once so the write and the
#: read cannot drift apart on a column order, the failure a positional
#: ``SELECT *`` invites.  ``sequence`` is deliberately absent from the write
#: and present in the read: it is the chain's own number, minted by the
#: insert, never supplied by the caller.
_COLUMNS = (
    "cycle_id, prior_beta_four, prior_weight, observed_divergences, "
    "divergence_sum, unbacktested, unobserved, zero_backtest, "
    "cost_reconciliations, cost_divergence_bps, observed_through, "
    "revised_beta_four, revised_at"
)

_INSERT_SQL = (
    f"INSERT INTO {FORWARD_BETA_FOUR_TABLE} ({_COLUMNS}) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

#: One cycle's row, column by column.
_READ_ONE_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_BETA_FOUR_TABLE} "
    "WHERE cycle_id = ?"
)

#: The chain's head — the standing value the next cycle blends from.
_READ_STANDING_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_BETA_FOUR_TABLE} "
    f"ORDER BY sequence DESC LIMIT 1"
)

#: The row a given cycle revised from — the chain strictly before a standing
#: row, so a re-asked cycle recomputes against its own prior rather than
#: against a cycle that post-dates it.
_READ_BEFORE_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_BETA_FOUR_TABLE} "
    f"WHERE sequence < ? ORDER BY sequence DESC LIMIT 1"
)

#: The whole chain, oldest first — the audit trail, and the order each row's
#: ``prior_beta_four`` is the row before it in.
_READ_ALL_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_BETA_FOUR_TABLE} "
    f"ORDER BY sequence"
)

#: Every signal the record table holds, ascending — the revision is taken
#: over the whole fleet, so the read is the whole table rather than one key.
#: The same spelling :mod:`forward.priors` states for its own revision,
#: restated here so each module's read names its own purpose.
_NODES_SQL = (
    f"SELECT DISTINCT {NODE_ID_COLUMN} FROM {FORWARD_RECORD_TABLE} "
    f"ORDER BY {NODE_ID_COLUMN}"
)


# -- Validation -------------------------------------------------------------------


def _validated_cycle(value: Any) -> str:
    """Return ``value`` as a cycle identity, or refuse what cannot be one.

    Non-empty text, stripped — the rule :func:`dreaming.cycle.
    validated_iteration_id` holds its caller to, restated in this member's
    vocabulary because a member never imports another: the cycle this row
    belongs to is the dreaming iteration the revised value feeds, and an id
    that states nothing names no cycle a revision could belong to.  Nothing
    else is normalised — a cycle's identity is the outer loop's own naming,
    and a store that case-folded or re-spelled one would be silently filing
    two revisions for one cycle.
    """
    if not isinstance(value, str) or not value.strip():
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: a cycle is named by non-empty "
            f"text — got {value!r} ({type(value).__name__}); the revision "
            "belongs to the dreaming iteration it will feed (the outer-loop "
            "job states the id, the same rule the dreaming member holds its "
            "own iteration ids to), and a value that cannot name one leaves "
            "a revised beta-four no cycle to be revised for (feature 338)"
        )
    return value.strip()


def _validated_beta(value: Any, field_name: str) -> float:
    """Return ``value`` as a beta-four coefficient, or refuse what cannot be one.

    Three gates, each refused rather than resolved, and the law is the
    scoring member's own (:func:`scoring._divergence._require_beta`,
    feature 260 — the consumer of this figure): a coefficient is a finite
    real, ``bool`` refused first (``True`` is ``1`` and a flag where a
    weight belongs would counterfeit a coefficient nobody tuned), and
    **negative is refused** because the term's verb is *subtracts* — a
    negative β₄ would counterfeit a bonus through the penalty seam,
    teaching the loop to prefer the signal families whose backtests
    flattered them most.  Zero is admitted: an ablation the documents
    leave to the deployment, and the value an honestly-diverging fleet
    pulls the chain toward.  There is deliberately no upper bound, the
    scoring member's own stance — *"every finite non-negative value
    composes identically"* — restated at the persistence layer so a row
    this store refused to blend cannot be read back wearing one.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must be the "
            f"beta-four coefficient as a real number — got {value!r} "
            f"({type(value).__name__}); the coefficient weights prd §7.1's "
            "fourth term (|IC_forward − IC_backtest|), it is what the "
            "dreaming loop runs its next cycle with, and a value that is "
            "not one number is not a weight any term could carry "
            "(feature 338)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must be finite — "
            f"got {narrowed!r}; a NaN would make every score the dreaming "
            "loop computes from this row a NaN its argmax silently drops, "
            "and an infinity is not a coefficient anyone tuned — the chain "
            "blends bounded operands, so a figure that cannot come from "
            "them is a row edited past this store (feature 338)"
        )
    if narrowed < 0.0:
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must not be "
            f"negative — got {narrowed!r}; the spec's verb for the term is "
            "*subtracts* (feature 260), and a negative coefficient would "
            "counterfeit a bonus through the penalty seam, teaching the "
            "loop to prefer the families whose backtests flattered them "
            "most — the inversion of prd §7.1's *\"honest, not merely "
            "high\"*. The evidence this feature folds is non-negative and "
            "the prior is not negative, so a negative figure here is a row "
            "edited past this store (feature 338)"
        )
    return narrowed


def _validated_weight(value: Any) -> float:
    """Return ``value`` as the blend's pseudo-count, or refuse it.

    The weight is not a parameter a caller chooses — it is the strength
    feature 228 established and feature 339 holds its own prior at, so the
    gate is equality with :data:`BETA_FOUR_WEIGHT` rather than a range.
    ``bool`` is refused first and the value must be a finite real, for the
    reason every numeric validator in this workspace refuses both.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: prior_weight must be the "
            f"blend's pseudo-count as a real number — got {value!r} "
            f"({type(value).__name__}); the strength is not a dial (feature "
            "228's ``n/(n+6)`` idiom, the same strength feature 339 holds "
            "its prior at), and a value that is not one number is not a "
            "strength the chain could blend at (feature 338)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: prior_weight must be finite — "
            f"got {narrowed!r}; the blend divides by the weight plus the "
            "observed count, and a value that cannot serve as either is a "
            "row edited past this store (feature 338)"
        )
    if narrowed != BETA_FOUR_WEIGHT:
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: prior_weight must be this "
            f"member's own pseudo-count ({BETA_FOUR_WEIGHT!r}) — got "
            f"{narrowed!r}. The strength the standing value is held at is "
            "not a caller's choice: it is feature 228's idiom, the same "
            "strength feature 339's revision holds its prior at, and a row "
            "blended at any other strength would be a revision nobody "
            "calibrated (feature 338)"
        )
    return narrowed


def _validated_count(value: Any, field_name: str) -> int:
    """Return ``value`` as a whole non-negative count, or refuse it.

    The tallies and the divergence count are counts of things the fleet
    read observed, so whole and at least zero — zero the honest common
    case for every one of them, which is what separates this gate from
    feature 339's day count.  ``bool`` refused first, as everywhere:
    ``True`` is not a census of anything.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must be a whole "
            f"count — got {value!r} ({type(value).__name__}); the figure is "
            "part of the evidence a revised beta-four is audited against, "
            "and a count that is not a whole number hides exactly what the "
            "figure was taken over (feature 338)"
        )
    if value < 0:
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must be at least "
            f"0 — got {value}; a count of signals or rebalances cannot be "
            "negative without measuring more than the tables hold "
            "(feature 338)"
        )
    return value


def _validated_sum(value: Any, field_name: str) -> float:
    """Return ``value`` as a sum of observed divergences, or refuse it.

    A finite real, ``bool`` refused first — the sum of addends each in
    ``[0, 2]`` (two validated coefficients), accumulated by this store in
    the read's own deterministic order.  **Non-negative**, because every
    addend is an absolute value: a negative sum is not a rounding artifact
    but a figure no fleet of divergences could produce, and a NaN would
    make the blend a NaN the dreaming loop's argmax silently drops.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must be a real "
            f"number — got {value!r} ({type(value).__name__}); it is the "
            "sum of the observed divergences the cycle folded, and a value "
            "that is not one number is not a sum of measurements "
            "(feature 338)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must be finite — "
            f"got {narrowed!r}; the blend adds it to a weighted prior and "
            "divides, and a NaN or infinity there is a figure that did not "
            "come from the rows it travels with (feature 338)"
        )
    if narrowed < 0.0:
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: {field_name} must not be "
            f"negative — got {narrowed!r}; every addend is an absolute "
            "divergence (|IC_forward − IC_backtest|), so a negative sum is "
            "a figure no fleet of records could produce and a row edited "
            "past this store (feature 338)"
        )
    return narrowed


def _validated_cost_sum(value: Any) -> float:
    """Return ``value`` as the swept cost divergence, or refuse what is not one.

    A finite real, ``bool`` refused first — the **signed** sum of feature
    340's ``difference_bps`` figures, accumulated in the ledger's own
    order.  The sign is deliberately not bound, and the absence is the
    point: positive is the model understating (prd's *cost model
    optimism*, the direction that flatters every backtest), negative is
    the model overcharging (wastes capacity, lies to nobody), and a bound
    or an absolute value would erase the direction §15's repair decision
    reads.  No magnitude bound, because basis points carry no structural
    limit the way a correlation's ``[−1, 1]`` does — the unit is part of
    the seam's contract, named in the column, and a validator cannot
    check a unit.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: cost_divergence_bps must be "
            f"a real number — got {value!r} ({type(value).__name__}); it is "
            "the sum of the fill-cost divergences the cycle swept, and a "
            "value that is not one number is not evidence any operator "
            "could reconcile the cost model against (feature 338)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: cost_divergence_bps must be "
            f"finite — got {narrowed!r}; the figure qualifies a revised "
            "coefficient that moves live scoring, and a NaN or infinity "
            "would be a measurement that gaps — the exact state feature "
            "340's own gate exists to keep out of this sweep (feature 338)"
        )
    return narrowed


def _require_sequence(value: Any) -> int:
    """Return ``value`` as the chain's own number, or refuse it by name.

    The sequence is the row's ``AUTOINCREMENT`` number — minted by the
    insert, monotone, never reused — so a caller never supplies one and a
    row carrying ``0``, a negative, a bool dressed as an int, or anything
    that is not an ``int`` is a row this store did not write.  The number
    is how an operator cites one revision in an audit of the chain, and a
    value that cannot be one is a row no reader filed.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: a revision's sequence is the "
            f"number the chain minted, an int — got {value!r} "
            f"({type(value).__name__}); the number is how an operator "
            "cites one row in an audit of the feedback chain, and a value "
            "that cannot be one is a row this store did not write "
            "(feature 338)"
        )
    if value < 1:
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: a revision's sequence is "
            f"numbered from 1 upward — got {value!r}; AUTOINCREMENT never "
            "mints 0 or a negative, and a row wearing one is a row this "
            "store did not write (feature 338)"
        )
    return value


# -- The revision -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BetaFourRevision:
    """One ``forward_beta_four_revision`` row, as the table holds it.

    The fourteen fields are the table's fourteen columns: the cycle the
    revision belongs to, the standing value it revised from and the weight
    it held that at, the evidence that moved it (the divergence sum and
    its count, the absence tallies, the swept cost face, the vintage), the
    blend itself, the chain's own number, and the moment the row was
    written.  One type serves the write and the read — :meth:`ForwardBeta.
    FourRevisions.revise` returns what landed, the read methods rebuild
    what stands — so the row an operator audits and the row the table
    holds cannot be two things that disagree.

    **Frozen**, because a caller who could edit ``revised_beta_four`` in
    memory could revise the coefficient the dreaming loop runs with past
    the store that owns it — the in-memory spelling of the silent
    revision the write path refuses.  Frozen also buys equality over the
    stored fields, which is what makes the write path's retry test (*is
    the standing row the one this cycle would revise to?*) a comparison
    of values rather than of columns read by hand.

    Validated in :meth:`__post_init__` rather than only through the store,
    for the reason every sibling record states: ``dataclasses.replace``
    and unpickling both rebuild instances past a factory's nose, and the
    *read* path needs the same check the write path does — SQLite's
    columns are dynamically typed, so a hand-edited row is reachable
    here.  The laws beyond the field validators are the table's own
    arithmetic, three of them:

    * **the blend** — ``revised_beta_four`` must equal ``(prior_weight ×
      prior_beta_four + divergence_sum) / (prior_weight +
      observed_divergences)`` exactly, the re-derivation law that keeps a
      fabricated coefficient away from the dreaming loop;
    * **no evidence, no sum** — a cycle that measured no divergence
      carries a zero sum and no vintage, because a figure over no
      addends is not a measurement;
    * **no sweep, no cost figure** — a cycle that swept no reconciliation
      carries a zero bps figure, the same law one tally over.
    """

    #: The row's own number — the ``AUTOINCREMENT`` key the insert minted.
    #: Monotone, never reused, and the order the chain is read in.
    sequence: int
    #: The cycle this revision belongs to and will feed — the dreaming
    #: iteration's id, stated by the outer-loop job that ran the
    #: recalibration.  One row per cycle, held by the ``UNIQUE`` constraint.
    cycle_id: str
    #: The standing value this cycle revised from — the latest row's
    #: ``revised_beta_four``, or :data:`BETA_FOUR_PRIOR` for a first cycle.
    prior_beta_four: float
    #: The strength the standing value is held at — :data:
    #: `BETA_FOUR_WEIGHT`, enforced equal to the constant.  Not a dial.
    prior_weight: float
    #: How many signals the cycle measured — the blend's ``n``.
    observed_divergences: int
    #: The sum of the measured signals' observed |mean live IC − backtest
    #: IC| figures — the blend's addends, summed.  Non-negative; zero when
    #: the count is zero.
    divergence_sum: float
    #: Signals whose ``backtest_ic`` has not landed — feature 337's writer
    #: is a separate call, and a young deployment's outer loop must not
    #: block on the figures that have not arrived.
    unbacktested: int
    #: Signals with a divisor and no observed days — the observation job
    #: has not reached them.
    unobserved: int
    #: Signals whose backtest is exactly zero — the honest figure of a
    #: signal with no measured edge, which made no claim the forward test
    #: could flatter.
    zero_backtest: int
    #: How many of feature 340's reconciliations the cycle swept — every
    #: rebalance's divergence, oldest first.
    cost_reconciliations: int
    #: The signed sum of the swept ``difference_bps`` figures — positive
    #: is the model understating (prd's *cost model optimism*).  Carried
    #: as evidence beside the blend; deliberately not an addend in it.
    cost_divergence_bps: float
    #: The latest day the folded evidence was measured on — the vintage,
    #: read off the data.  ``None`` when nothing was measured.
    observed_through: Any
    #: The revised coefficient — the blend of the standing value with the
    #: observed divergences.  What the dreaming loop's next cycle runs
    #: with.  Re-derived in ``__post_init__`` and compared exactly.
    revised_beta_four: float
    #: When this row was written — the store's own fact, never a
    #: parameter, and deliberately the row's only clock-read figure.
    revised_at: datetime

    @property
    def observed_mean_divergence(self) -> float | None:
        """The mean observed divergence — the evidence's own severity.

        Derived, never a field, for the reason feature 294's count is
        derived and not incremented: the addends' sum and count are both
        carried, and a mean kept beside them is a second copy of one fact
        that can drift from the first.  ``None`` over no evidence — an
        honest absence, not a zero.
        """
        if not self.observed_divergences:
            return None
        return self.divergence_sum / self.observed_divergences

    @property
    def mean_cost_divergence_bps(self) -> float | None:
        """The swept cost divergence per rebalance — §16's metric face.

        Derived, like :attr:`observed_mean_divergence`: the count and the
        signed sum are what the row holds, and the per-rebalance mean is
        the figure an operator reads off them.  ``None`` over an empty
        ledger.
        """
        if not self.cost_reconciliations:
            return None
        return self.cost_divergence_bps / self.cost_reconciliations

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline every frozen value in this member follows.
        object.__setattr__(self, "sequence", _require_sequence(self.sequence))
        object.__setattr__(self, "cycle_id", _validated_cycle(self.cycle_id))
        prior = _validated_beta(self.prior_beta_four, "prior_beta_four")
        object.__setattr__(self, "prior_beta_four", prior)
        weight = _validated_weight(self.prior_weight)
        object.__setattr__(self, "prior_weight", weight)
        count = _validated_count(self.observed_divergences, "observed_divergences")
        object.__setattr__(self, "observed_divergences", count)
        total = _validated_sum(self.divergence_sum, "divergence_sum")
        object.__setattr__(self, "divergence_sum", total)
        object.__setattr__(
            self, "unbacktested", _validated_count(self.unbacktested, "unbacktested")
        )
        object.__setattr__(
            self, "unobserved", _validated_count(self.unobserved, "unobserved")
        )
        object.__setattr__(
            self, "zero_backtest", _validated_count(self.zero_backtest, "zero_backtest")
        )
        swept = _validated_count(
            self.cost_reconciliations, "cost_reconciliations"
        )
        object.__setattr__(self, "cost_reconciliations", swept)
        costs = _validated_cost_sum(self.cost_divergence_bps)
        object.__setattr__(self, "cost_divergence_bps", costs)
        through = (
            None if self.observed_through is None else _validated_vintage(
                self.observed_through
            )
        )
        object.__setattr__(self, "observed_through", through)
        revised = _validated_beta(self.revised_beta_four, REVISED_BETA_FOUR_KEY)
        object.__setattr__(self, "revised_beta_four", revised)
        object.__setattr__(
            self, "revised_at", _validated_instant(self.revised_at, "revised_at")
        )
        # No evidence, no sum — and no vintage over no evidence.  The three
        # are one law stated where a hand on the table would have to edit
        # all of it: a cycle that measured nothing carries figures that say
        # so, and an absence wearing a sum is a measurement nobody made.
        if count == 0:
            if total != 0.0:
                raise ForwardBetaFourError(
                    f"{FORWARD_BETA_FOUR_ERROR_CODE}: revision {self.sequence} "
                    f"for cycle {self.cycle_id!r} holds no observed "
                    f"divergences but a divergence_sum of {total!r}; the sum "
                    "is the addends the count counts, and a figure over no "
                    "addends is not a measurement — it is a sum wearing an "
                    "absence's clothes, and the blend would move on it "
                    "(feature 338)"
                )
            if through is not None:
                raise ForwardBetaFourError(
                    f"{FORWARD_BETA_FOUR_ERROR_CODE}: revision {self.sequence} "
                    f"for cycle {self.cycle_id!r} holds no observed "
                    f"divergences but a vintage of {through.isoformat()}; the "
                    "vintage is the latest day the folded evidence was "
                    "measured on, and evidence that does not exist was not "
                    "measured on any day (feature 338)"
                )
        elif through is None:
            # And the converse, same law read the other way: a cycle that
            # measured a signal measured it *on days* — feature 333's rows
            # each state one — and the vintage is the latest of them, read
            # off the data and stamped by the write.  A measured fleet with
            # no vintage is the mirror of an unmeasured one wearing a sum:
            # a row this store did not write.
            raise ForwardBetaFourError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: revision {self.sequence} "
                f"for cycle {self.cycle_id!r} holds {count} observed "
                "divergences but no vintage; every divergence was measured "
                "on a day feature 333's rows state, and the vintage is the "
                "latest of them read off the data — an evidence-bearing row "
                "with no day under it is a row this store did not write "
                "(feature 338)"
            )
        if swept == 0 and costs != 0.0:
            raise ForwardBetaFourError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: revision {self.sequence} "
                f"for cycle {self.cycle_id!r} swept no cost reconciliation "
                f"but carries a cost divergence of {costs!r} bps; the figure "
                "is the sum of the rebalances the sweep read, and a sum over "
                "no rebalances is a divergence nobody measured (feature 338)"
            )
        # The blend, checked on the value so no path — write, read, replace,
        # unpickle — can carry a coefficient that is not the arithmetic of
        # the evidence stored beside it.  The comparison is exact on
        # purpose: both sides are arithmetic this member performed itself
        # over figures it read, so anything but exact equality is a hand
        # that edited one of them — and a row that lies about its own blend
        # is refused rather than served.
        blended = (weight * prior + total) / (weight + count)
        if revised != blended:
            raise ForwardBetaFourError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: the revised beta-four "
                f"{revised!r} is not the blend of the standing value "
                f"({prior!r} at weight {weight!r}) with the "
                f"{count} observed divergences summing to {total!r}, which "
                f"is {blended!r}. The revision is not a figure a caller may "
                "state: prd §5's loop recalibrates the coefficient from the "
                "divergence the forward records hold, and a row whose own "
                "evidence does not produce its figure would hand the "
                "dreaming loop's next cycle a coefficient nobody computed. "
                "Nothing is wrong with the store: the repair is to let this "
                "feature take the blend (feature 338)"
            )

    def summary(self) -> dict[str, Any]:
        """The revision as a JSON-shaped mapping — the loop's read.

        The revised figure travels under the spec's own three words, the
        prior and the evidence beside it because a coefficient without its
        evidence is a number the next cycle cannot audit itself against,
        and the instants as ISO strings for the reason every timestamp in
        this member does — :mod:`json` has no ``datetime``.
        """
        return {
            "sequence": self.sequence,
            "cycle_id": self.cycle_id,
            "prior_beta_four": self.prior_beta_four,
            "prior_weight": self.prior_weight,
            REVISED_BETA_FOUR_KEY: self.revised_beta_four,
            "observed_divergences": self.observed_divergences,
            "divergence_sum": self.divergence_sum,
            "observed_mean_divergence": self.observed_mean_divergence,
            "unbacktested_signals": self.unbacktested,
            "unobserved_signals": self.unobserved,
            "zero_backtest_signals": self.zero_backtest,
            "cost_reconciliations": self.cost_reconciliations,
            "cost_divergence_bps": self.cost_divergence_bps,
            "mean_cost_divergence_bps": self.mean_cost_divergence_bps,
            "observed_through": (
                None if self.observed_through is None
                else self.observed_through.isoformat()
            ),
            "revised_at": self.revised_at.isoformat(),
        }

    def row(self) -> dict[str, Any]:
        """The revision as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline every record
        in this workspace follows: a rendered mapping names the same things
        the same way the row does.
        """
        return {
            "sequence": self.sequence,
            "cycle_id": self.cycle_id,
            "prior_beta_four": self.prior_beta_four,
            "prior_weight": self.prior_weight,
            "observed_divergences": self.observed_divergences,
            "divergence_sum": self.divergence_sum,
            "unbacktested": self.unbacktested,
            "unobserved": self.unobserved,
            "zero_backtest": self.zero_backtest,
            "cost_reconciliations": self.cost_reconciliations,
            "cost_divergence_bps": self.cost_divergence_bps,
            "observed_through": (
                None if self.observed_through is None
                else self.observed_through.isoformat()
            ),
            "revised_beta_four": self.revised_beta_four,
            "revised_at": self.revised_at.isoformat(),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(cycle_id={self.cycle_id!r}, "
            f"revised_beta_four={self.revised_beta_four!r})"
        )


def _validated_vintage(value: Any) -> date:
    """Return ``value`` as the evidence's vintage day, or refuse it.

    A :class:`~datetime.date` or its ISO-8601 text — the form the column
    holds — reached through the record's own day validator so a vintage is
    spelled the same way every other day in this member is.  A
    :class:`~datetime.datetime` is refused there by name, which is the
    right refusal here too: a vintage is a day the evidence was measured
    on, and an instant would smuggle in an offset the evidence never
    carried.
    """
    return _validated_date(value, OBSERVED_ON_COLUMN)


# -- The store --------------------------------------------------------------------


class ForwardBetaFourRevisions:
    """Feature 338's store: the revised β₄, persisted per cycle.

    One act over one table and three reads.  :meth:`revise` reads the
    divergence the forward records hold, blends it into the standing value
    and lands one row per cycle; :meth:`standing` answers the chain's head
    — the value the next cycle blends from and the dreaming loop runs
    with; :meth:`get` and :meth:`revisions` answer one cycle and the whole
    audit trail.  The fleet read works through
    :data:`forward.record._READ_SQL` — one reading of ``forward_record``
    across features 332, 333, 337, 340 and this one — and the cost face
    through :class:`forward.reconciliation.ForwardCostReconciliations`,
    the ledger's own reader, so this module spells no column of a table it
    does not own.

    Constructed over a URL, or over a composed store through :meth:`over`,
    the ladder features 333, 337, 340 and 339 all climb: the classmethod
    reads the ``database_url`` off whatever the component is, the store
    methods do the work, and the module-level spellings resolve
    ``DATABASE_URL``.

    **There is no cache, and no clock in the figures.**  Every call reads
    the records, the ledger and the chain as they stand, so two calls over
    unmoved rows answer equal values — the same stance feature 337 takes
    toward its ratio, and for the same reason: the figure moves live
    scoring, and a decision that read a stale copy would be deciding about
    a fleet that had already moved.  The one clock read is ``revised_at``,
    the row's own fact.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the revisions land in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one revision: a URL that
        is not a non-empty string names no table, and a store that
        accepted one would fail identically on every write — the wrong
        place for a deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardStoreError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: {DATABASE_URL_ENV} must be "
                "a non-empty database URL. The revised beta-four is "
                "persisted per cycle into the database the deployment "
                "names, and the divergence it is fed back from is read "
                "from the same database's records — a store pointed at "
                "nothing has nowhere for either to live (feature 338)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> ForwardBetaFourRevisions | None:
        """The revision store ``DATABASE_URL`` names, or ``None``.

        An empty or whitespace-only value counts as unset, the way every
        store in this workspace treats its configuration — and deliberately
        the same spelling every sibling reader in this member answers
        with: a deployment with no relational store holds no revision
        writer, which is a discoverable state rather than an exception,
        while the module-level writer below refuses instead because a
        revision that silently went nowhere would look exactly like one
        that ran.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def over(cls, records: Any) -> ForwardBetaFourRevisions:
        """The revision store over a composed forward-record store.

        The bridge from the seat to this act: a caller holding the
        composed ``forward`` component (``create_app().get("forward")``)
        asks this one question and holds the
        writer for the same database the component points at — one URL,
        the records it reads and the chain it writes in one database.  The
        one thing read is the store's ``database_url``; there is no
        ``isinstance`` to defeat, and no second store constructed beside
        the component to keep consistent, because the URL *is* the
        component's own.
        """
        url = getattr(records, FORWARD_BETA_FOUR_SEAM, None)
        if not isinstance(url, str) or not url.strip():
            raise TypeError(
                "ForwardBetaFourRevisions is built over a forward-record "
                f"store — something exposing a "
                f"{FORWARD_BETA_FOUR_SEAM!r} string (the composed 'forward' "
                "component, or a ForwardRecords); got "
                f"{type(records).__name__}, which names no database. The "
                "divergence the revision folds is read off the forward "
                "records' own rows, so the writer shares one URL with the "
                "record by construction (feature 338)"
            )
        return cls(url)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and writes."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the chain, resolved on first use.

        Nothing is created at construction — the URL is translated the
        first time an operation needs it, by the member's one spelling of
        that translation (:func:`forward.record._sqlite_path`), so a URL
        this member cannot speak is refused in the member's one
        vocabulary whichever store translated it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the chain's database, bringing the tables it names up.

        Two owners, both honoured: :func:`forward.schema.bootstrap_schema`
        runs the owning migrations' own ``statements("sqlite")`` —
        ``0118`` for ``node`` and ``0108`` for ``forward_record`` —
        because the fleet read needs the records; and this module's own
        :data:`_SCHEMA` creates ``forward_beta_four_revision``
        idempotently beside the only writer, the stance
        :mod:`forward.reconciliation` takes.  A fresh database, one the
        record store already brought up, and one this store prepared
        earlier all take the same path, and coexistence is by
        construction.  There is no ``PRAGMA foreign_keys`` to set: this
        table references nothing — the cycle it keys is a dreaming
        iteration, an act in another member's process, not a row in a
        table this member could name, and a foreign key to another
        member's schema would make this bootstrap depend on a table this
        feature does not own.

        The caller owns the connection; use it as a context manager to
        commit, which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            with connection:
                bootstrap_schema(connection)
                connection.executescript(_SCHEMA)
        except ForwardError:
            # A refusal already in this member's vocabulary — re-raised
            # untouched (and the connection closed) rather than re-framed,
            # for the reason :meth:`forward.record.ForwardRecords._connect`
            # states.
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise ForwardStoreError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: the database at {path} "
                "could not be brought to the shape a beta-four revision "
                f"needs: {exc}. {FORWARD_RECORD_TABLE} is created by "
                "migrations/versions/0108_forward_and_universe_tables.py "
                "and its parent by 0118_node_table.py (this store runs "
                "those files' own statements), and "
                f"{FORWARD_BETA_FOUR_TABLE} is created by this member "
                "alone (feature 338's own table — the migration tree "
                "declares the signal-day grain, not the per-cycle one), so "
                "a failure here is a fact about the database rather than "
                "about the row (feature 338)"
            ) from exc
        return connection

    def _rows(
        self, connection: sqlite3.Connection, node: str
    ) -> list[ForwardRecord]:
        """The signal's standing rows, oldest day first — the record itself.

        Feature 332's own read spelling — :data:`forward.record._READ_SQL`
        and :func:`forward.record._record_from_row` — used rather than
        restated, so the rows this act charges divergence over and the
        rows every other act in the member answered with cannot be two
        readings of one table.  A validation refusal off a row is the
        record contract's own (:class:`~forward.errors.
        ForwardRecordError`) and propagates as itself, because it names
        the row it came off and re-framing it would only push a second
        wording in front of the one an operator needs.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [_record_from_row(row, node) for row in rows]

    # -- Feature 338: the revision -------------------------------------------

    def revise(self, cycle_id: Any) -> tuple[BetaFourRevision, bool]:
        """Revise beta-four from the observed divergence — 338's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the cycle as non-empty text — *before*
           anything is opened, so a malformed cycle is refused without
           touching a database and a refused call leaves no row and no
           file behind.
        2. **Sweep the cost ledger** — feature 340's own reader answers
           every reconciliation, oldest rebalance first, and the count and
           the signed bps sum accumulate in that order.  The sweep runs on
           the ledger's own connection before this store's transaction
           opens: the ledger is append-only and its reader is the one its
           module ships, so the read is the same one §16's metric takes.
        3. **Read the fleet.**  Every signal the record table holds, in
           node order, classified exactly as feature 339's revision
           classifies it — one connection, one snapshot, so the revision
           of a database is a pure function of the database.
        4. **Read the chain.**  The standing row for *this* cycle, and the
           row it revised from — the latest row strictly before it, or the
           chain's head when nothing stands.
        5. **Blend**, and answer the retry, or refuse the disagreement,
           or write.  A standing row this call would produce again is the
           same revision arriving twice — answered untouched, with
           ``created=False``.  A standing row this call would *not*
           produce is the evidence having moved under a cycle already
           revised — refused
           (:class:`~forward.errors.ForwardIdentityError`), because the
           dreaming loop may already have run that cycle on the standing
           value.  An absent cycle takes the insert.
        6. **Read back and answer with the row**, inside the same
           transaction as the write, so the minted ``sequence`` and every
           figure in the answer are the table's own.

        **No coefficient is a parameter, and that is the feature.**  The
        prior is read off the chain, the divergences off the records, the
        cost face off the ledger; the blend is :class:`BetaFourRevision`'s
        to perform and verify.  The zero-evidence law holds at every
        link: a cycle over no measurable signal answers the standing
        value exactly, and a first cycle over no measurable signal
        answers :data:`BETA_FOUR_PRIOR`.

        Refuses, in this order, each naming what it is about: a malformed
        cycle (:class:`~forward.errors.ForwardBetaFourError`, the ask
        face); a store this member cannot speak, or a row that could not
        be written or read back
        (:class:`~forward.errors.ForwardStoreError`); a fleet row nobody
        can vouch for — two vintages, a negative backtest
        (:class:`~forward.errors.ForwardBetaFourError`) — and a backtest
        outside ``[−1, 1]``, which arrives in feature 337's own
        vocabulary because that gate is the one spelling of *is this a
        coefficient* this member has; and a cycle that already holds a
        different revision (:class:`~forward.errors.
        ForwardIdentityError`).
        """
        cycle = _validated_cycle(cycle_id)
        costs = self._swept_costs()
        with closing(self._connect()) as connection, connection:
            evidence = self._fleet(connection)
            standing = self._row_at(connection, cycle)
            chain = self._chain_prior(connection, standing)
            prior = BETA_FOUR_PRIOR if chain is None else chain.revised_beta_four
            blended = (
                BETA_FOUR_WEIGHT * prior + evidence.divergence_sum
            ) / (BETA_FOUR_WEIGHT + evidence.observed_divergences)
            if standing is not None:
                return (
                    self._answer_standing(standing, cycle, prior, evidence, costs),
                    False,
                )
            try:
                connection.execute(
                    _INSERT_SQL,
                    (
                        cycle,
                        prior,
                        BETA_FOUR_WEIGHT,
                        evidence.observed_divergences,
                        evidence.divergence_sum,
                        evidence.unbacktested,
                        evidence.unobserved,
                        evidence.zero_backtest,
                        costs[0],
                        costs[1],
                        None
                        if evidence.observed_through is None
                        else evidence.observed_through.isoformat(),
                        blended,
                        utc_now().isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # The UNIQUE fired after this store read no standing row —
                # the constraint doing exactly what it is on the table for.
                # The honest visitor is the concurrent one: a second writer
                # landed this cycle between the read and the insert, and
                # SQLite's write lock means its row is committed — so the
                # answer is the law's, rather than a corruption report:
                # re-read, and answer the retry or refuse the disagreement
                # exactly as the checked path would have.
                #
                # The re-read runs on a fresh *plain* connection rather
                # than this store's own ``_connect()`` on purpose: the
                # bootstrap would take a write lock this failed transaction
                # may still hold, and the only question here is *what
                # stands* — a read, on a connection that starts nothing.
                with closing(sqlite3.connect(self.path)) as other:
                    row = other.execute(_READ_ONE_SQL, (cycle,)).fetchone()
                after = None if row is None else self._from_row(row)
                if after is None:  # pragma: no cover - UNIQUE equality is text equality
                    raise ForwardStoreError(
                        f"{FORWARD_BETA_FOUR_ERROR_CODE}: the revision for "
                        f"cycle {cycle!r} was refused by the table's own "
                        f"UNIQUE (cycle_id) after this store read no "
                        "standing row for it, and no row in this store's "
                        "spelling holds it. The one-row-per-cycle law is "
                        "the table's own, so the standing row cannot be "
                        "answered as a retry and must not be double-written."
                        " The repair is to the table: repair the row's "
                        "cycle_id, then revise (feature 338)"
                    ) from exc
                chain_after = self._chain_prior_of(other, after)
                prior_after = (
                    BETA_FOUR_PRIOR
                    if chain_after is None
                    else chain_after.revised_beta_four
                )
                return (
                    self._answer_standing(
                        after, cycle, prior_after, evidence, costs
                    ),
                    False,
                )
            written = self._row_at(connection, cycle)
        if written is None:
            raise ForwardStoreError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: the revision for cycle "
                f"{cycle!r} could not be read back after the write. The "
                "revised beta-four is what the dreaming loop's next cycle "
                "runs with and what an operator audits the feedback chain "
                "against, and a row that cannot be re-read is a revision "
                "this store cannot vouch for (feature 338)"
            )
        return written, True

    # -- The reads -----------------------------------------------------------

    def standing(self) -> BetaFourRevision | None:
        """The chain's head — the standing value the next cycle blends from.

        The dreaming loop's one question: *what beta-four do I run with?*.
        ``None`` is the honest absent answer — no cycle has been revised
        — and the caller runs :data:`BETA_FOUR_PRIOR`, which is the same
        figure feature 260's seam applies when unnamed: the zero-evidence
        law, stated at the composition level rather than answered here,
        so the table's ``None`` and the deployment's default cannot
        silently disagree.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(_READ_STANDING_SQL).fetchone()
        return None if row is None else self._from_row(row)

    def get(self, cycle_id: Any) -> BetaFourRevision | None:
        """One cycle's standing revision, or ``None``.

        The point read — the answer to *what did cycle k revise to?* for
        an operator auditing the chain.  ``None`` is the honest absent
        answer (the cycle was never revised), not an error, for the same
        reason :meth:`forward.reconciliation.ForwardCostReconciliations.
        get` asserts no uniqueness: presence is the write path's law to
        hold.  Refuses a cycle that states nothing rather than answering
        ``None`` for it, because an unrevised cycle and an unaskable one
        are different facts.
        """
        cycle = _validated_cycle(cycle_id)
        with closing(self._connect()) as connection:
            return self._row_at(connection, cycle)

    def revisions(self) -> tuple[BetaFourRevision, ...]:
        """The whole chain, oldest cycle first — the audit trail.

        Each row's ``prior_beta_four`` is the row before it, so the
        sequence's order *is* the feedback: a reader can verify every
        blend from the rows alone, which is what makes the persisted
        chain auditable rather than merely remembered.

        Fails with :class:`~forward.errors.ForwardStoreError` when the
        chain could not be read, and with
        :class:`~forward.errors.ForwardBetaFourError` when a stored row
        is not a revision this store could have written — the refusal,
        not a skip: a skipped row is a feedback link wearing a shrug, and
        the chain's auditability is what this table exists for.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(_READ_ALL_SQL).fetchall()
        return tuple(self._from_row(row) for row in rows)

    # -- The evidence --------------------------------------------------------

    def _swept_costs(self) -> tuple[int, float]:
        """The cost face: every reconciliation's divergence, oldest first.

        Read through feature 340's own reader — the one §16's metric takes
        — on the ledger's own connection, so this module spells no column
        of a table it does not own and the sweep is the same read every
        other consumer of the ledger performs.  The figures are
        accumulated in the ledger's own order and returned as ``(count,
        signed sum)``; a malformed row refuses here in feature 340's own
        vocabulary (:class:`~forward.errors.
        ForwardReconciliationError`), which is the correct one — it names
        the rebalance the row prices — and propagates untouched.

        The sweep is deliberately **outside** this store's transaction:
        the ledger is append-only and its reader is committed reads only,
        so there is no interleaving to defend against, and holding a
        write lock while reading another table's snapshot would be the
        deadlock 340's own IntegrityError path avoids.  A reconciliation
        landing between the sweep and the write belongs to the *next*
        cycle's evidence — and the disagreement law below refuses the
        re-revision that would silently fold it into this one.
        """
        reconciliations = ForwardCostReconciliations(
            self._database_url
        ).reconciliations()
        total = 0.0
        for reconciliation in reconciliations:
            total += reconciliation.difference_bps
        return len(reconciliations), total

    def _fleet(self, connection: sqlite3.Connection) -> _FleetEvidence:
        """The IC face: every signal's observed sim-reality divergence.

        The classification is feature 339's, stated one feature earlier
        in this loop and restated here in this module's vocabulary — each
        module refuses in its own words, the member's ``_one_vintage``
        precedent.  The divisor is checked before the observations (a
        signal with no divisor cannot be measured however many rows it
        holds); a stored backtest outside ``[−1, 1]`` refuses in feature
        337's own gate, which is the one spelling of *is this a
        coefficient* this member has; zero is counted as edgeless and
        negative refuses the whole revision (promotion requires a
        positive edge, and the halving of a negative coefficient is not a
        divergence anyone defined); and only a signal with a positive
        divisor and no observed days is *unobserved*.

        The divergence itself is prd §7.1 line 322's own expression —
        ``| IC_forward − IC_backtest |`` — over feature 337's operands:
        the mean of the observed ``live_ic`` rows against the opening
        row's landed ``backtest_ic``.  The mean is over the observed rows
        only, exactly as feature 337 takes it, because a row whose
        ``live_ic`` is null is a day the job did not reach — an absence,
        not a measured zero, and averaging nulls in as zeroes would let a
        sparsely observed signal read as one that collapsed.
        """
        divergences: list[float] = []
        unbacktested = 0
        unobserved = 0
        zero_backtest = 0
        through: date | None = None
        cursor = connection.execute(_NODES_SQL)
        try:
            nodes = [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
        for node in nodes:
            standing = self._rows(connection, node)
            opening = _one_vintage(node, standing)
            observed = [row for row in standing if row.live_ic is not None]
            if observed:
                latest = max(row.observed_on for row in observed)
                if through is None or latest > through:
                    through = latest
            stored = opening.backtest_ic
            if stored is None:
                unbacktested += 1
                continue
            backtest = _validated_backtest_ic(stored)
            if backtest == 0.0:
                zero_backtest += 1
                continue
            if backtest < 0.0:
                raise _no_edge(node, backtest)
            if not observed:
                unobserved += 1
                continue
            live = sum(float(row.live_ic) for row in observed) / len(observed)
            divergences.append(abs(live - backtest))
        return _FleetEvidence(
            divergences=tuple(divergences),
            unbacktested=unbacktested,
            unobserved=unobserved,
            zero_backtest=zero_backtest,
            observed_through=through,
        )

    # -- The row plumbing ----------------------------------------------------

    def _row_at(
        self, connection: sqlite3.Connection, cycle: str
    ) -> BetaFourRevision | None:
        """The standing row for one cycle, in this store's spelling.

        Reached through :data:`_READ_ONE_SQL` on the caller's connection
        — inside the write's transaction on the write path, on its own on
        the read path — so there is one reading of a cycle's row in this
        module and the check and the write cannot disagree about what
        stands.
        """
        row = connection.execute(_READ_ONE_SQL, (cycle,)).fetchone()
        return None if row is None else self._from_row(row)

    def _chain_prior(
        self,
        connection: sqlite3.Connection,
        standing: BetaFourRevision | None,
    ) -> BetaFourRevision | None:
        """The row the cycle under revision blends from.

        With no standing row, the chain's plain head — the latest row
        anywhere, which is what a *new* cycle revises from.  With one,
        the row strictly before it: a re-asked cycle recomputes against
        its own prior, not against a cycle that post-dates it, so the
        retry comparison below is the comparison this cycle actually
        made.
        """
        if standing is None:
            row = connection.execute(_READ_STANDING_SQL).fetchone()
        else:
            row = connection.execute(
                _READ_BEFORE_SQL, (standing.sequence,)
            ).fetchone()
        return None if row is None else self._from_row(row)

    def _chain_prior_of(
        self, connection: sqlite3.Connection, standing: BetaFourRevision
    ) -> BetaFourRevision | None:
        """The chain strictly before a standing row, on a bare connection.

        The IntegrityError path's half of :meth:`_chain_prior`: the
        transaction has failed and the bootstrap must not be re-run on
        this connection, so the read goes straight to the statement on a
        connection the caller owns — the table already exists; the
        constraint just fired on it.
        """
        row = connection.execute(_READ_BEFORE_SQL, (standing.sequence,)).fetchone()
        return None if row is None else self._from_row(row)

    def _answer_standing(
        self,
        standing: BetaFourRevision,
        cycle: str,
        prior: float,
        evidence: _FleetEvidence,
        costs: tuple[int, float],
    ) -> BetaFourRevision:
        """Resolve a cycle that already holds a row: retry or refusal.

        The two outcomes are the same cycle read two ways and the
        difference is the evidence.  The *same* revision arriving twice —
        the worker died after the row landed but before the response made
        it back, and the worker that takes over revises again over rows
        that have not moved — is not an error and moves nothing: the
        standing row is returned exactly as it is, sequence and stamps
        included.  A *different* revision is the evidence having moved
        under a cycle already decided, and the store refuses to choose:
        last-wins would re-revise a cycle the dreaming loop may already
        have run — every ``replay_score`` row feature 255 wrote carries
        the β it ran with, and a moved figure would orphan them — and
        first-wins would leave the caller holding a response whose
        figures contradict the records it just read, which is worse than
        a refusal because it looks like success.
        """
        blended = (
            BETA_FOUR_WEIGHT * prior + evidence.divergence_sum
        ) / (BETA_FOUR_WEIGHT + evidence.observed_divergences)
        if (
            standing.prior_beta_four == prior
            and standing.observed_divergences == evidence.observed_divergences
            and standing.divergence_sum == evidence.divergence_sum
            and standing.unbacktested == evidence.unbacktested
            and standing.unobserved == evidence.unobserved
            and standing.zero_backtest == evidence.zero_backtest
            and standing.cost_reconciliations == costs[0]
            and standing.cost_divergence_bps == costs[1]
            and standing.observed_through == evidence.observed_through
            and standing.revised_beta_four == blended
        ):
            return standing
        raise ForwardIdentityError(
            f"{FORWARD_IDENTITY_ERROR_CODE}: cycle {cycle!r} already holds "
            f"a beta-four revision (sequence {standing.sequence}, revised "
            f"at {standing.revised_at.isoformat()}: prior "
            f"{standing.prior_beta_four!r}, {standing.observed_divergences} "
            f"observed divergence(s) summing to {standing.divergence_sum!r}, "
            f"revised to {standing.revised_beta_four!r}), and the records "
            "have moved since: this call would revise the same cycle from "
            f"prior {prior!r} over {evidence.observed_divergences} "
            f"divergence(s) summing to {evidence.divergence_sum!r} to "
            f"{blended!r}. A cycle's revision is that cycle's fact, once: "
            "the dreaming loop may already have run it with the standing "
            "value (every replay_score row feature 255 wrote carries the "
            "β it ran with), and re-revising it would orphan those rows "
            "from the figure they claim to have used. Nothing is wrong "
            "with the store: the repair is to name the moved evidence a "
            "new cycle and revise that (feature 338)"
        )

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> BetaFourRevision:
        """Rebuild one stored row, refusing a value no revision can be.

        The refusal is the point: this table is written by this store,
        but SQLite will accept anything another tool inserts, and a row
        wearing a moment no parser accepts, a sequence the chain never
        minted, or a blend that disagrees with the evidence stored beside
        it — a row lying about its own arithmetic — would otherwise reach
        the dreaming loop as a coefficient nobody computed.  The refusal
        names the row it came from, so an operator gets the row to repair
        rather than a complaint about a value with no address — the
        discipline :meth:`forward.reconciliation.
        ForwardCostReconciliations._from_row` states for its own ledger,
        restated in this member's vocabulary.
        """
        sequence = row[0]
        (
            cycle_id,
            prior,
            weight,
            count,
            total,
            unbacktested,
            unobserved,
            zero_backtest,
            swept,
            costs,
            through_raw,
            revised,
            revised_raw,
        ) = row[1:]
        vintage: date | None
        try:
            vintage = None if through_raw is None else date.fromisoformat(through_raw)
        except (TypeError, ValueError) as exc:
            raise ForwardBetaFourError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: the beta-four revision row "
                f"numbered {sequence!r} carries observed_through "
                f"{through_raw!r}, which is not an ISO 8601 day this store "
                "can date the evidence's vintage by (feature 338)"
            ) from exc
        try:
            moment = datetime.fromisoformat(revised_raw)
        except (TypeError, ValueError) as exc:
            raise ForwardBetaFourError(
                f"{FORWARD_BETA_FOUR_ERROR_CODE}: the beta-four revision row "
                f"numbered {sequence!r} carries revised_at {revised_raw!r}, "
                "which is not an ISO 8601 moment this store can order the "
                "chain's audit by (feature 338)"
            ) from exc
        try:
            return BetaFourRevision(
                sequence=sequence,
                cycle_id=cycle_id,
                prior_beta_four=prior,
                prior_weight=weight,
                observed_divergences=count,
                divergence_sum=total,
                unbacktested=unbacktested,
                unobserved=unobserved,
                zero_backtest=zero_backtest,
                cost_reconciliations=swept,
                cost_divergence_bps=costs,
                observed_through=vintage,
                revised_beta_four=revised,
                revised_at=moment,
            )
        except ForwardBetaFourError as refusal:
            # The value layer validates the row, and this re-raise is what
            # makes the refusal *findable*: the value sees one row and
            # cannot know which one, while a reader holding the chain can
            # name the number and the cycle the bad row came from — so an
            # operator gets the row to repair rather than a complaint about
            # a value with no address.
            raise ForwardBetaFourError(
                f"{refusal} — the row this came from is the beta-four "
                f"revision numbered {sequence!r} for cycle {cycle_id!r}, "
                f"revised at {revised_raw!r} (feature 338)"
            ) from refusal

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The fleet read's evidence ----------------------------------------------------


class _FleetEvidence:
    """What the fleet read measured, counted and refused to measure.

    A private carrier — the evidence exists between the read and the
    blend, and every figure it holds is persisted on the row it moved, so
    it is not part of the member's surface.  The divergences are carried
    whole (in node order, the deterministic order the ``SELECT`` buys) so
    the sum accumulated from them is reproducible bit for bit, and the
    tallies and vintage travel beside them for the same reason feature
    339's revision carries its absences: a coefficient without its
    evidence is a number the next cycle cannot audit itself against.
    """

    __slots__ = (
        "divergences",
        "observed_through",
        "unbacktested",
        "unobserved",
        "zero_backtest",
    )

    def __init__(
        self,
        *,
        divergences: tuple[float, ...],
        unbacktested: int,
        unobserved: int,
        zero_backtest: int,
        observed_through: date | None,
    ) -> None:
        self.divergences = divergences
        self.unbacktested = unbacktested
        self.unobserved = unobserved
        self.zero_backtest = zero_backtest
        self.observed_through = observed_through

    @property
    def observed_divergences(self) -> int:
        """The blend's ``n`` — how many signals were measured."""
        return len(self.divergences)

    @property
    def divergence_sum(self) -> float:
        """The blend's addends, summed in the read's own node order."""
        total = 0.0
        for divergence in self.divergences:
            total += divergence
        return total


# -- The private refusals ---------------------------------------------------------


def _one_vintage(node: str, standing: list[ForwardRecord]) -> ForwardRecord:
    """The record's opening row, after checking the record is one record.

    The one-vintage law read back, in this module's own vocabulary — the
    same check the observation, retention and prior modules make in
    theirs, restated because each module refuses in its own words and a
    divergence measured across two boundaries is a divergence nobody can
    state: the gap between what the backtest promised and what the
    forward test delivered is a gap between two windows, and a record
    whose rows disagree about where one of them begins charges the
    coefficient for a vintage that never existed.  The opening row is
    ``standing[0]`` because :data:`forward.record._READ_SQL` orders by
    ``observed_on``, which is a property of the ordering clause and not
    of any object.
    """
    instants = {row.promoted_at for row in standing}
    if len(instants) > 1:
        raise ForwardBetaFourError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: "
            f"the {FORWARD_RECORD_TABLE} rows for node {node} carry "
            f"{len(instants)} different promoted_at values — "
            + ", ".join(sorted(t.isoformat() for t in instants))
            + ". A forward record is one vintage: feature 332 opens one row "
            "per signal carrying one instant, and every observation carries "
            "that same instant, so rows disagreeing about it are a hand "
            "that reached past this store. A sim-reality divergence "
            "measured over them would charge beta-four for the gap between "
            "a backtest and two different forward windows, and the "
            "recalibration would teach the dreaming loop on a figure "
            "nobody measured — repair the rows, then revise (feature 338)"
        )
    return standing[0]


def _no_edge(node: str, backtest: float) -> ForwardBetaFourError:
    """The contradicted-promotion refusal: a negative backtest IC.

    The fleet read's one hard refusal over an *absence-free* row, and the
    stance feature 339's revision takes one feature later in the same
    loop: promotion requires a positive edge (prd §11's criteria), so a
    negative coefficient on a promoted signal's record is a figure
    wearing the column's name, and the divergence |live − backtest|
    computed against it would be a gap measured from a claim the
    promotion contradicts.  The repair is offline reconciliation of the
    figure, not a convention here — and the refusal names the aggregate's
    stake: one such row stops the whole cycle's revision, because a
    coefficient taught from a fleet it silently filtered is a coefficient
    nobody calibrated.
    """
    return ForwardBetaFourError(
        f"{FORWARD_BETA_FOUR_ERROR_CODE}: "
        f"node {node}'s forward record carries a backtest information "
        f"coefficient of {backtest!r}, and a sim-reality divergence is the "
        "gap between a forward test and a backtest that claimed a "
        "*positive* edge — promotion requires one (prd §11's criteria), so "
        "the row contradicts the promotion that opened it, and no "
        "divergence computed against it is a measurement anyone defined. "
        "A zero is the honest figure of a signal with no measured edge "
        "(feature 337 stores it; this revision counts it and moves on), "
        "but a negative figure is not honest emptiness. Nothing is wrong "
        "with the store: the repair is to reconcile the figure offline, "
        "then revise (feature 338)"
    )


# -- The module-level spellings ---------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardBetaFourRevisions:
    """The store the module-level spellings act through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that
    names neither is refused *by name* rather than silently answering
    nothing — the same seam :func:`forward.reconciliation.
    _resolved_store` resolves for the reconciling act.  The silence
    would be the dangerous failure: a revision that went nowhere would
    leave the dreaming loop running the standing value while the records
    it should have learned from sat unlearned, and the two states —
    *revised* and *never revised* — would read identically to every
    operator downstream.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise ForwardStoreError(
            f"{FORWARD_BETA_FOUR_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so no beta-four revision can be persisted. The "
            "coefficient is fed back from divergence observed on the "
            "forward records' own rows, and a store resolved from nothing "
            "is a refusal rather than a silent answer of the caller's own "
            "choosing (feature 338)"
        )
    return ForwardBetaFourRevisions(url)


def revised_beta_four(
    cycle_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> BetaFourRevision:
    """Revise beta-four from observed divergence — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store — the outer-loop job's recalibration step, an
    operator re-running a cycle whose row never landed, a test.  The
    store is resolved from ``database_url``, else from ``DATABASE_URL``,
    exactly as :func:`forward.reconciliation.reconcile_fill_costs`
    resolves its own, so a caller writing through one spelling and
    reading through :func:`standing_beta_four` is writing and reading
    the same database.

    The answer is the **row the table holds** rather than a
    ``(revision, created)`` pair, for the reason the sibling acts' own
    module-level spellings state: an act asked for as one call has
    nobody to tell about a retry, and the row it returns is the same
    value either way.  A caller that needs to know whether *this* call
    landed the row asks the store
    (:meth:`ForwardBetaFourRevisions.revise`).
    """
    return _resolved_store(database_url, env).revise(cycle_id)[0]


def standing_beta_four(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> BetaFourRevision | None:
    """The standing revised beta-four — the reader's spelling.

    The chain's head: the value the next cycle blends from and the
    dreaming loop runs with (:meth:`ForwardBetaFourRevisions.standing`).
    A deployment that names no store answers ``None``, and so does an
    empty chain — deliberately the same answer, because the caller's
    repair is the same one: run :data:`BETA_FOUR_PRIOR`, which is
    feature 260's own default, the figure the scoring seam already
    applies when a caller names none.  The zero-evidence law, stated at
    the composition level — kept distinct because a caller that mistook
    an unconfigured deployment for an emptied chain would conclude the
    loop had calibrated when nothing ever ran.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return None
    return ForwardBetaFourRevisions(url).standing()
