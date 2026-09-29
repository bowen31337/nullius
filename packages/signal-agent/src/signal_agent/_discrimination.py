"""Feature 214 — ``mechanism_discrimination``: IS gain against OOS gain, per campaign.

*"System persists mechanism_discrimination per campaign, computed as the
correlation between in-sample gain and out-of-sample gain across real
branches."*

docs/nullius-tech-architecture.md §14.1 states the figure inside its
"Measuring model adequacy on this task" block, beside the count feature 215
owns::

    mechanism_discrimination = corr( IS_gain, OOS_gain | real branches )
    tree_diversity           = distinct mechanism clusters per campaign

and the paragraph above it is why the pair exists at all (§14.1)::

    Public coding benchmarks measure specified-task completion.  Root
    generation is hypothesis novelty under constraint, which none of them
    measure.  The null-plant machinery already provides a better instrument,
    and in-sample gain is **not** it — a weak model curve-fits noise
    enthusiastically, so null-branch IS gains look healthy.

with the reading the correlation is *of* (§14.1)::

    A strong agent produces refinements whose in-sample improvement
    *predicts* sequestered-epoch improvement.  A weak agent produces
    noise-chasing variations and the correlation collapses even on real
    branches.

and the reporting rule that is this feature's shape constraint (§14.1, rule
3)::

    Calibration beside accuracy.  ``mechanism_discrimination`` is a
    correlation; report its interval, not the point (``design.md`` §9).

**This module is the second reader of feature 207's store and the first that
also writes.**  :mod:`signal_agent._proposal` records one row per node into
the member-owned ``node_proposal`` table — a proposal document plus the score
snapshot taken when the round read it — and feature 215 counts over those rows.
This feature *correlates* them, against the out-of-sample readings the replay
wrote into ``0109``'s ``replay_score``, and persists one row per campaign into
a table this member owns.  ``additions_spec_207.xml`` names the pair of readers
from the writer's side: *"depended on by features 214 and 215 (mechanism
discrimination and tree diversity, which read the persisted score records
across a campaign's real branches)"*.

**What this module is not.**  It is not feature 215: that counts clusters and
returns a figure, this correlates a pair of gains and persists it — and 215's
own suite pins that *its* module has no write path, so the write here is the
half 215 deliberately left unbuilt.  It is not feature 216, the *per candidate
model* stratification: §14.1 budgets *"two campaigns per candidate model"*, so
at M2 the campaign is already the model's unit and this feature's sentence
stays per campaign — what it leaves 216 is
:attr:`MechanismDiscrimination.cohort_digest`.  It is not feature 123's KS
guard, though it borrows that feature's *persistence shape* wholesale (one row
per campaign, primary key = campaign, refresh-not-append, measure before
write): 123 asks whether the planted nulls are *detectable*, and this asks
whether in-sample improvement *predicts* out-of-sample improvement.  And it is
not a null-branch detector; see "the cohort is declared, never derived".

**Why no component, and why no seat.**  The reading resolves no configuration
of its own: the tables to read, the metric pair and the figure's shape are all
facts about state two existing builders already expose (207's store and the
tree it lives in).  So it is a free function beside them, reached as
``from signal_agent import mechanism_discrimination``, exactly as feature 186's
:func:`bootstrap.world_census` sits beside the bootstrap pool and feature 215's
``tree_diversity`` sits beside this one.  A tenth ``signal-agent-*``
registration would put a name in the registry for a question that composes
nothing, and this feature has no *composed component* to read.

**One file, one handle — and that is a decision.**  The figure joins
``node_proposal`` (207's table) to ``replay_score`` (``0109``'s) inside one
statement, so the two must be one database.  Rather than take a store of its
own and refuse a mismatch with the history handle, this module takes **only**
the history handle and writes into *its* database: the mismatch is not refused,
it is **unrepresentable**.  That is the stronger form of feature 185's *"one
deployment fact"* argument, and it costs the feature nothing — a caller that
wants the figure of a campaign is already holding the handle whose database
holds that campaign's proposals.

**A strong agent's reading, and its direction.**  The figure is *higher* for a
better agent: a strong model's in-sample gains predict its sequestered-epoch
gains, so the correlation is large and positive; a weak model's are noise, so
it collapses toward zero.  §14.1 reports the interval rather than the point,
and this module refuses to answer at all when no interval exists — see
:data:`MINIMUM_PAIRS`.

Stdlib only (plus this member's own public ``ScoreRecord``), and import-cheap:
no third-party import at module scope, so the factory's scan — which imports
this member to fire its ``@register`` builders — pays nothing for this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Final

from ._proposal import ScoreRecord
from .errors import (
    DiscriminationCohortError,
    ProposalHistoryStoreUnavailableError,
)

__all__ = [
    "CONFIDENCE_LEVEL",
    "DISCRIMINATION_TABLE",
    "IS_GAIN_METRIC",
    "MINIMUM_PAIRS",
    "MechanismDiscrimination",
    "load_mechanism_discrimination",
    "mechanism_discrimination",
]

#: This member's own table — the row feature 214's sentence persists.  Created
#: lazily by :func:`mechanism_discrimination` and declared nowhere in the shared
#: migration chain, the precedent ``bootstrap_world`` (feature 188),
#: ``depth_run_window`` (feature 202), ``bootstrap_trial`` (feature 185),
#: ``depth_cache_rate`` (feature 200), ``node_proposal`` (feature 207) and
#: ``campaign_ks_guard`` (feature 123) all set: no migration declares this row,
#: and a member that refused to create its own table would be refusing its own
#: feature.
#:
#: **Why not a column on ``campaign``.**  ``0111``'s table carries
#: ``calibration_status`` and ``ks_pvalue`` and no discrimination column, and
#: ``migrations/versions/**`` is a shared, order-sensitive tree this feature
#: must not edit.  So the reading lives in a table this member owns, exactly as
#: feature 123's provenance does beside its own headline column.
#:
#: Named for the *figure* rather than for the campaign, so a reader looking for
#: **what was measured about this campaign, and by which feature** does not
#: have to know which of ``campaign``'s columns are whose — 123's reason for
#: naming its own table for the guard.
DISCRIMINATION_TABLE: Final[str] = "campaign_discrimination"

#: **The in-sample half of the pair, and the choice is forced rather than
#: picked.**  §14.1 correlates *"in-sample **gain**"* against the
#: out-of-sample reading, and of the seven metrics ``0114`` declares (feature
#: 101) exactly one is a gain *by definition*:
#: docs/alpha-engine-prd.md §6.2 states ``ir_marginal(v | book) = IR(book ∪
#: {v}) − IR(book)`` — a difference — and §6.1 step 9 is the step that computes
#: it (*"marginal_ir — orthogonalize vs. current book → ir_marginal"*).
#:
#: The six others are declined, each for its own reason: ``ir_standalone`` is a
#: *level* (the equal-weight book's IR), ``ic_mean`` and ``ic_tstat`` are the
#: correlation and its t-statistic, ``turnover`` and ``cost_adjusted_ir`` are
#: costs, and ``perturb_stability`` is robustness.  §14.1's own sentence is
#: *"refinements whose in-sample improvement predicts sequestered-epoch
#: improvement"* — a difference on both sides — so ``ir_marginal`` is the one
#: metric that pairs with ``IR_oos(pick | book)`` under the same functional
#: form: **the pick's contribution to the book, measured inside the barrier and
#: outside it.**
IS_GAIN_METRIC: Final[str] = "ir_marginal"

#: The floor below which there is **no reading to report**, and §14.1's rule 3
#: is the whole reason it is four rather than two.
#:
#: *"report its interval, not the point"* is not a formatting instruction: the
#: interval is Fisher's z-transform, whose standard error is
#: ``1/sqrt(n − 3)``, so at ``n = 3`` the estimate is a division by zero and
#: below it the root of a negative number.  Four is the smallest cohort for
#: which an interval exists **at all**, and a cohort that cannot be reported
#: under the rule is a cohort this feature refuses rather than one it answers a
#: bare point about — because a point estimate reported alone is, in §14.1's
#: own words via ``design.md`` §9, *"how people convince themselves a noisy
#: result is a finding"*.
#:
#: **It sits above the campaign planner's own floor, deliberately.**  PRD §121
#: plans a campaign with a floor of two real roots; two real branches is a
#: campaign that ran, and one that still cannot be *reported on*.  The floors
#: answer different questions — *may this campaign run* and *may this figure be
#: printed* — and collapsing them would either refuse campaigns the planner
#: admits or print a figure §14.1 forbids.
MINIMUM_PAIRS: Final[int] = 4

#: The two-sided confidence level the interval is reported at: 95%, the level
#: feature 124's ``p < 0.05`` threshold and §14.1's M3 gate both work at, so a
#: reader comparing this interval against a significance verdict is comparing
#: like with like.  Named as data rather than left inside the arithmetic
#: because it is a *claim* about the figure — §14.1 rule 3 asks for the
#: interval, and an interval without its level is as uninterpretable as a point
#: without its cohort.
CONFIDENCE_LEVEL: Final[float] = 0.95

#: The standard normal quantile for :data:`CONFIDENCE_LEVEL` — two-sided, so
#: the 0.975 point — computed rather than written as a literal.  ``1.96`` is
#: the folklore spelling and ``1.9599639845400536`` is what
#: :meth:`statistics.NormalDist.inv_cdf` answers (measured); a magic constant
#: in an interval that §14.1 makes a *reporting requirement* would be a number
#: nobody could check against the level it claims.
_Z_QUANTILE: Final[float] = NormalDist().inv_cdf(
    1.0 - (1.0 - CONFIDENCE_LEVEL) / 2.0
)

#: ``0109``'s table — the replay pool, feature 255's row per run.  Read
#: read-only; the replay member (features 245-255) is its writer and this
#: module creates nothing.
REPLAY_SCORE_TABLE: Final[str] = "replay_score"

#: ``0111``'s table — feature 104's campaign.  Read read-only, for the one
#: check that the campaign this reading is scoped to was actually planned: a
#: reading written under a campaign id no row answers to would be a figure
#: about nothing.
CAMPAIGN_TABLE: Final[str] = "campaign"

#: ``replay_score``'s columns this feature reads: the pick that ties a run to a
#: branch, the revision it was run under, and the score itself.  Spelled as
#: literals rather than imported for the reason this module restates every name
#: it reads — a private constant of a sibling module is not a promise, and a
#: module that reads three columns does not need that module importable to say
#: which.
REPLAY_SCORE_PICK_COLUMN: Final[str] = "committed_pick"
REPLAY_SCORE_POLICY_VERSION_COLUMN: Final[str] = "policy_version"
REPLAY_SCORE_SCORE_COLUMN: Final[str] = "score"

#: Feature 207's campaign scope on its own row, taken from the ``node`` row at
#: the moment of the write.  The cohort's membership is checked against **this**
#: column rather than against the caller's pairing of branch to campaign, which
#: is the fact the store already holds.
CAMPAIGN_ID_COLUMN: Final[str] = "campaign_id"

#: The revision that creates :data:`REPLAY_SCORE_TABLE` and the out-of-sample
#: half with it — the whole actionable content of a refusal raised for a
#: database that has not reached it.
REPLAY_POLICY_REVISION: Final[str] = "0109_replay_score_and_policy_revision"

#: The revision that creates :data:`CAMPAIGN_TABLE`, named for the same reason.
CAMPAIGN_POLICY_REVISION: Final[str] = "0111_campaign_table"

#: The ``sqlite_master`` probe the three shape questions are asked with —
#: read-only, and asked before any measurement rather than assumed, the idiom
#: feature 207's ``_NODE_TABLE_EXISTS_SQL``, feature 215's ``_HISTORY_EXISTS_SQL``
#: and feature 232's ordering law each restate for the same reason.
_TABLE_EXISTS_SQL: Final[str] = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)

#: The in-sample half, read by branch.  ``IN`` over the declared cohort, so one
#: statement answers for every branch and the reconciliation that follows is
#: over values rather than over a second query — and because the placeholders
#: are the *caller's* cohort, an undeclared branch's proposal is never read at
#: all.  That is the ``| real branches`` qualifier with teeth: the filter is not
#: applied to this statement's output, it is built into what the statement can
#: return.
_IS_HALF_SQL: Final[str] = (
    f"SELECT node_id, {CAMPAIGN_ID_COLUMN}, score FROM node_proposal "
    f"WHERE node_id IN ({{placeholders}})"
)

#: The out-of-sample half: every run any declared branch was the committed pick
#: of.  ``committed_pick`` is nullable (``0109``: a candidate scored but never
#: selected has no pick, and *"a decision that was never made must stay
#: distinguishable from one that was"*), and a ``NULL`` pick names no branch —
#: so it can never match a declared one, which is correct rather than a gap:
#: those rows contributed no branch to the cohort.
#:
#: **A non-committing policy's ``−∞`` cannot reach this cohort**, and the reason
#: is the store's own law rather than a guard here: feature 222 writes
#: :data:`policy_runtime.NON_COMMITTING_SCORE` into ``score`` for a policy that
#: terminated without committing, and that row's ``committed_pick`` is absent
#: by the same law — there is no pick to name, so there is no branch for the
#: score to be attributed to.
_OOS_HALF_SQL: Final[str] = (
    f"SELECT {REPLAY_SCORE_PICK_COLUMN}, "
    f"{REPLAY_SCORE_POLICY_VERSION_COLUMN}, {REPLAY_SCORE_SCORE_COLUMN} "
    f"FROM {REPLAY_SCORE_TABLE} "
    f"WHERE {REPLAY_SCORE_PICK_COLUMN} IN ({{placeholders}})"
)

#: The campaign the reading is scoped to, asked as a read.  A *read* and never
#: a create: a store that inserted the missing campaign would be inventing the
#: row the null fraction and the campaign type belong on — feature 123's
#: argument for its own guard row, true here word for word.
_CAMPAIGN_EXISTS_SQL: Final[str] = f"SELECT 1 FROM {CAMPAIGN_TABLE} WHERE id = ?"

#: This feature's row: one per campaign, the figure and its interval, the two
#: denominators, the revision the runs were under, the digest of the frozen
#: cohort, and when the reading was taken.
#:
#: **``campaign_id`` is the primary key**, so the grain is the campaign and a
#: re-reading refreshes rather than appends — feature 123's grain for a
#: campaign-scoped statistic, and the reason is the same: §14.1's instrument is
#: run *"at M2, before the M3 gate"* over a cohort that grows as the campaign
#: proposes, so a campaign is expected to be measured more than once and what
#: the table must hold is the latest reading and nothing else.  ``NOT NULL``
#: beside ``PRIMARY KEY`` for the reason ``0111``'s docstring spells: SQLite
#: accepts NULL — and several — in a bare ``PRIMARY KEY``, so a second
#: NULL-keyed row would split a campaign's reading from its identity while
#: still being accepted as a distinct key.
#:
#: **The interval is two columns and not a derived read.**  §14.1 rule 3 makes
#: the interval the *reported* thing (``design.md`` §9: *"show the interval as
#: the primary mark and the point estimate as a hairline within it"*), so a row
#: holding the point alone would let a report print it unaccompanied — which is
#: the failure the rule exists to prevent.  Storing the bounds makes the
#: unaccompanied reading impossible to produce from this table.
_SCHEMA: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {DISCRIMINATION_TABLE} (
    campaign_id    TEXT     NOT NULL PRIMARY KEY,
    correlation    REAL     NOT NULL,
    interval_lower REAL     NOT NULL,
    interval_upper REAL     NOT NULL,
    pairs          INT      NOT NULL,
    runs           INT      NOT NULL,
    policy_version TEXT     NOT NULL,
    cohort_digest  CHAR(64) NOT NULL,
    seen_at        TEXT     NOT NULL
)
"""

#: The stored row's columns, in the order the schema declares them.  One tuple
#: so the write and the read cannot drift apart on what this feature's row is
#: made of.
_COLUMNS: Final[tuple[str, ...]] = (
    "campaign_id",
    "correlation",
    "interval_lower",
    "interval_upper",
    "pairs",
    "runs",
    "policy_version",
    "cohort_digest",
    "seen_at",
)


# ── The correlation, and why it is this one ──────────────────────────────────
#
# Pearson's product-moment correlation, spelled here rather than taken from
# ``statistics.correlation``, and the reason is the *refusals* rather than the
# arithmetic: what this feature has to decide is whether the cohort can answer
# at all, and a library call that raises its own ``StatisticsError`` on a
# constant series would report that decision in another module's vocabulary.
# The member's error discipline is explicit about this seam
# (the member's error-vocabulary rule): a caller's ``except
# DiscriminationCohortError`` must catch every way this feature can decline,
# and a translation layer between the arithmetic and the refusal would be a
# place for one of them to escape unnamed.
#
# The estimator is the ordinary one and deliberately not a rank correlation.
# §14.1's sentence says *correlation* and its whole reading is about
# *magnitudes* predicting magnitudes — *"in-sample improvement predicts
# sequestered-epoch improvement"* — and a rank statistic would answer a
# different question (does the ordering agree) that stays high under a monotone
# distortion of the gains.  It is also what the interval is stated over:
# Fisher's z is the transform for Pearson's r.


def _pearson(is_gains: list[float], oos_gains: list[float]) -> float:
    """Pearson's r over two equal-length series, both known to vary.

    Takes no decision: every condition that could make it undefined is refused
    by :func:`_require_spread` before this runs, so the division here is a
    division by a genuinely positive number and the result is finite.  Split
    that way rather than returning ``None``, because the *repair* for a
    constant series (the cohort cannot answer) is different from the repair for
    a short one, and each refusal names its own.
    """
    count = len(is_gains)
    mean_is = math.fsum(is_gains) / count
    mean_oos = math.fsum(oos_gains) / count
    deviations_is = [value - mean_is for value in is_gains]
    deviations_oos = [value - mean_oos for value in oos_gains]
    covariance = math.fsum(
        left * right for left, right in zip(deviations_is, deviations_oos)
    )
    spread_is = math.sqrt(math.fsum(value * value for value in deviations_is))
    spread_oos = math.sqrt(math.fsum(value * value for value in deviations_oos))
    return covariance / (spread_is * spread_oos)


def _interval(correlation: float, pairs: int) -> tuple[float, float]:
    """The 95% interval for ``correlation`` over ``pairs`` points — Fisher's z.

    ``z = atanh(r)``, ``se = 1/sqrt(n − 3)``, back through ``tanh``.  The
    transform is the reason :data:`MINIMUM_PAIRS` is four and the reason an
    exactly perfect correlation is refused: ``atanh(±1)`` diverges, so a
    correlation of exactly one has **no** interval under the rule §14.1
    requires — and answering one anyway would be reporting an interval this
    feature invented.

    Total on its domain by construction: :func:`_require_correlation` has
    already clamped into ``[-1, 1]`` and refused the endpoints, and the caller
    has already required ``pairs >= MINIMUM_PAIRS``, so ``pairs − 3 >= 1`` and
    the root is real.  Both facts are asserted here rather than assumed,
    because an interval helper that silently produced a ``nan`` would put a
    ``null`` in a column the schema declares ``NOT NULL``.
    """
    assert pairs >= MINIMUM_PAIRS, "the caller requires the floor before here"
    assert -1.0 < correlation < 1.0, "the endpoints are refused before here"
    centre = math.atanh(correlation)
    standard_error = 1.0 / math.sqrt(pairs - 3)
    return (
        math.tanh(centre - _Z_QUANTILE * standard_error),
        math.tanh(centre + _Z_QUANTILE * standard_error),
    )


def _require_correlation(value: float, pairs: int) -> float:
    """Refuse a correlation with no interval: a clamped, non-degenerate ``r``.

    Two refusals in one function because they are one question — *is this a
    value the interval is defined at* — and both are folds of the arithmetic
    rather than of the data:

    * **``|r|`` at or beyond one.**  A float covariance can overshoot slightly
      and answer ``1.0000000000000002`` for two exactly collinear series, so
      the value is clamped into ``[-1, 1]`` first — the honest reading of a
      slightly-out-of-range float — and the *clamped* value is then refused at
      the endpoints, because ``atanh(±1)`` is a ``ValueError`` and the interval
      it would produce does not exist.  Feature 214's answer to a perfectly
      collinear cohort is a refusal rather than a point at the boundary, and
      the refusal is the same one a constant series gets: a cohort that cannot
      produce an interval cannot be reported under §14.1's rule 3.
    * **A non-finite value.**  ``nan`` reaches here only from a ``nan`` input,
      which :func:`_require_finite` refuses earlier — asserted rather than
      assumed so a later edit to the input guard cannot quietly widen this
      one.
    """
    assert math.isfinite(value), "the gains are required finite before here"
    clamped = max(-1.0, min(1.0, value))
    if abs(clamped) >= 1.0:
        raise DiscriminationCohortError(
            f"the {pairs} real branch(es) this reading covers produce a "
            f"correlation of exactly {value!r}, and an exactly perfect "
            f"correlation has no interval: §14.1's rule 3 is *report its "
            f"interval, not the point* (design.md §9), the interval is "
            f"Fisher's z whose transform diverges at ±1, and a figure with no "
            f"interval is one this feature must refuse rather than print as a "
            f"point. A perfect correlation over a handful of branches is a "
            f"statement about the cohort's size before it is a statement "
            f"about the agent (feature 214)."
        )
    return clamped


def _require_spread(
    values: list[float], *, name: str, pairs: int
) -> float:
    """Refuse a series with no variance, by name; return its *standard deviation*.

    **The spread is measured about the mean, and that is the whole of the check.**
    A sum of squares of the raw values is not a spread — it is positive for any
    non-zero series, including a constant one — so a check written that way
    passes a constant series straight through to the division in
    :func:`_pearson` and surfaces a ``ZeroDivisionError`` from inside the
    arithmetic, which is exactly the unnamed refusal this member's error
    discipline exists to prevent: a shared helper that raised another
    feature's type would defeat the caller's ``except``.  The
    variance is therefore centered here, by the mean of the same series
    :func:`_pearson` will later center: a series that varies is one whose
    deviations from its own mean are not all zero.

    A correlation with no variance on either side is undefined, and ``0.0``
    would be a *claim* — *"this agent's gains carry no discrimination"* — where
    the truth is that the cohort cannot answer the question.  The two cases cut
    in opposite directions and are equally unflattering, which is exactly why
    neither may be answered with a number: a constant in-sample series is a
    cohort of refinements that all gained the same, and a constant
    out-of-sample series is a replay whose runs all scored alike.  Feature
    207's own law is the precedent for the *shape* of this refusal — a ``None``
    metric is an absent measurement and never a zero — applied to a series
    rather than a scalar.
    """
    mean = math.fsum(values) / len(values)
    spread = math.sqrt(math.fsum((value - mean) ** 2 for value in values))
    if spread <= 0.0:
        raise DiscriminationCohortError(
            f"the {name} gains of the {pairs} real branch(es) this reading "
            f"covers do not vary at all, so no correlation exists: a "
            f"correlation is the share of one series' movement the other "
            f"accounts for, and a series that never moves has no movement to "
            f"account for. Answering zero would be a measurement this feature "
            f"invented — *this agent's gains carry no discrimination* — when "
            f"the truth is that this cohort cannot answer, and the constant "
            f"baseline for a correlation is a degenerate predictor's, not a "
            f"figure to report in its place (feature 214, §14.1 rule 3)."
        )
    return spread


def _require_finite(value: Any, *, name: str, branch: str) -> float:
    """Refuse a gain that is not a finite real number, by name.

    Three states collapse into two here, and the collapse is deliberate: a
    non-number and an infinity are both *a measurement that failed*, and neither
    is a large one.  ``nan`` is the third and is refused by the same test, since
    it compares false against everything and would silently poison a mean —
    feature 207's ``to_json`` refuses it at the *writer* for the same reason
    (``allow_nan=False``), so a ``nan`` reaching here is a snapshot a hand or a
    lenient decoder produced.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiscriminationCohortError(
            f"the {name} gain of real branch {branch!r} is {value!r} "
            f"({type(value).__name__}) rather than a number: both halves of "
            f"§14.1's pair are measured quantities, so a value that is not one "
            f"names no measurement to correlate (feature 214)."
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise DiscriminationCohortError(
            f"the {name} gain of real branch {branch!r} is {figure!r}, which "
            f"is not a finite number: an infinite or undefined gain is a "
            f"measurement that failed rather than a large one, and correlating "
            f"it would report a figure about an arithmetic accident (feature "
            f"214)."
        )
    return figure


# ── The cohort ───────────────────────────────────────────────────────────────


def _proposal_history(history: Any) -> Path:
    """Check that ``history`` is feature 207's handle, and return its database.

    Duck-typed rather than ``isinstance``, for the reason every seam in this
    member states: the module loader imports the member under a synthetic name
    and re-executes it, so the composed store ``create_app()`` hands out is a
    *second* ``ProposalStore`` class object and an ``isinstance`` gate here
    would refuse the very store the composition seam serves.

    Two names are asked for, and each for its own reason:

    * ``history`` — the verb that makes the object a *proposal history* rather
      than anything else holding a path.  It is not called: this module reads
      the table directly, because the correlation needs the score snapshot —
      feature 206's :class:`~signal_agent.PriorProposal` carries three fields
      and no score — so a reading built on that verb would need a second query
      per node and a join in Python over a table one statement reads.  But
      requiring the verb is what stops a caller handing over an arbitrary
      object with a filesystem path, and that refusal is worth more than the
      call it does not make;
    * ``path`` — where the rows are.  Resolved *lazily* by the store (207's own
      decision: construction is composition-time work and must not touch the
      disk), so reading it here is the first thing that resolves it.

    The attributes are checked here and used by :func:`mechanism_discrimination`,
    so an object refused for its shape is refused before anything has been
    opened — feature 186's reasoning: a refusal that arrived after a connection
    had been made is a validation that ran too late to be one.
    """
    resolver = getattr(history, "history", None)
    if not callable(resolver):
        raise DiscriminationCohortError(
            f"mechanism_discrimination correlates feature 207's recorded "
            f"proposals — got {history!r} ({type(history).__name__}), which "
            f"has no callable ``history``; the in-sample half of §14.1's pair "
            f"is the score snapshot 207 stores beside each proposal document, "
            f"so an object that is not the proposal-history law holds none for "
            f"it to correlate (feature 214)."
        )
    path = getattr(history, "path", None)
    if path is None or not isinstance(path, Path):
        raise DiscriminationCohortError(
            f"mechanism_discrimination reads a campaign's recorded proposals "
            f"from the store they live in — got {history!r} "
            f"({type(history).__name__}), which names no ``path``; the figure "
            f"joins node_proposal to {REPLAY_SCORE_TABLE} in one database, and "
            f"where the proposals live is where the pool lives (features "
            f"207/214)."
        )
    return path


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    The same normalisation :func:`signal_agent._proposal._validated_campaign_id`
    and :func:`signal_agent._diversity._validated_campaign_id` apply, restated
    for the reason this module restates every name it reads: the row's key is
    UUID text, and a mixed-case id would make one campaign look like two — here,
    in the question of which rows the reading is about.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise DiscriminationCohortError(
        f"campaign_id {value!r} is not a UUID: feature 214's sentence is "
        f"*persists mechanism_discrimination per campaign*, and §9 makes the "
        f"campaign the unit of search, so the reading is scoped by the value "
        f"{CAMPAIGN_ID_COLUMN} holds — and an id that cannot join it would "
        f"silently persist a figure about another campaign (feature 214)."
    )


def _validated_cohort(real_branches: Any) -> tuple[str, ...]:
    """Validate the declared real-branch cohort: a non-empty set of node ids.

    **The cohort is required, and it is the whole of the ``| real branches``
    qualifier.**  §14.1's formula carries it, and the discriminant it turns on
    is not readable from anything this member may open:

    * §7.1: *"There is no ``is_null`` column anywhere in the tree store. Not
      hidden, not nulled out, not ``SELECT``-excluded. **Absent.** The only way
      to learn a node's status is to hold the sidecar key"* — and the sidecar is
      *"readable by ONE service account"*;
    * §4.2: the bit *"is visible to exactly one component: the replay scorer"*;
    * app_spec 447 (feature 110) keeps it absent from the tree store entirely,
      app_spec 456 (feature 113) has the endpoint *"never which returns is_null
      in any form"*, and the merge gate rejects *"any symbol named is_null
      reachable outside the scorer package"*;
    * feature 207's ``node_proposal`` records no such flag — a fact feature 215's
      suite already pins from its own side, concluding that *"there is nothing
      to filter on"*.

    So the cohort is **declared by the caller**, which is the shape §7.4 already
    sanctions for the one other job that needs the partition: *"a job holding
    the sidecar key runs a two-sample KS test on in-sample score distributions,
    null nodes vs. real nodes"*. This module therefore never names the
    discriminant — not in a symbol, not in a constant, not in a string — which
    is what keeps the barrier's invariant true by construction rather than by a
    check that could be refactored away.

    **Why a default is refused rather than supplied.**  A caller that could
    "just correlate everything" would get a number that silently mixes the
    exactly-zero half, and §4.1 says what that half is: *"true out-of-sample
    edge of a null branch is exactly zero by construction"*.  A null branch
    contributes points whose ``y`` is ~0 whatever their ``x``, which attenuates
    the correlation mechanically — so a mixed cohort would flatter a weak agent
    twice over: once by attenuation, and once by giving a null-heavy tree more
    points than the real branches alone would carry.  §14.1's warning is that
    the collapse must remain visible *even after* the null half is removed.

    **What this function can and cannot check.**  It checks that the cohort is a
    non-empty collection of non-blank, non-``bool`` strings, and it de-duplicates
    it — a branch named twice is one branch, and a cohort that counted it twice
    would weight that refinement twice in a correlation over *branches*.  It
    cannot check that the members are *real*; nothing in this member can.  What
    it does instead is make the cohort it was handed auditable, which is
    :attr:`MechanismDiscrimination.cohort_digest` and §14.1's rule 1.
    """
    if isinstance(real_branches, (str, bytes)) or not isinstance(
        real_branches, Iterable
    ):
        raise DiscriminationCohortError(
            f"the real-branch cohort must be an iterable of node ids, got "
            f"{real_branches!r} ({type(real_branches).__name__}): §14.1's "
            f"figure is stated *across real branches*, and the discriminant it "
            f"selects on is not readable from any store this member may open "
            f"(§7.1: the tree store holds no such column; §4.2: the bit is "
            f"visible to exactly one component), so the cohort is declared by "
            f"the caller and a bare string would be a cohort of characters "
            f"(feature 214)."
        )
    cohort: list[str] = []
    seen: set[str] = set()
    for branch in real_branches:
        if isinstance(branch, bool) or not isinstance(branch, str) or not branch.strip():
            raise DiscriminationCohortError(
                f"a real-branch cohort member is {branch!r} "
                f"({type(branch).__name__}) rather than a node id: the cohort "
                f"is the set of branches §14.1's correlation is conditioned "
                f"on, and a member that names no node names no branch "
                f"(feature 214)."
            )
        text = branch.strip()
        if text not in seen:
            seen.add(text)
            cohort.append(text)
    if not cohort:
        raise DiscriminationCohortError(
            "the real-branch cohort is empty, so there is no correlation to "
            "compute: §14.1's figure is stated *across real branches*, and a "
            "cohort with none of them is a question about no branches rather "
            "than a reading of zero. A campaign whose draw left no real branch "
            "is a state the caller must be told about rather than handed a "
            "figure about nothing (feature 214)."
        )
    return tuple(cohort)


# ── The frozen cohort, §14.1's rule 1 ────────────────────────────────────────


def _cohort_digest(
    campaign: str,
    policy_version: str,
    pairs: tuple[tuple[str, float, float], ...],
) -> str:
    """Hash the inputs this figure was computed over — §14.1's rule 1.

    *"Freeze the cohort before any model runs, and hash its inputs."*  The
    digest covers the campaign, the revision the runs were under, the metric the
    in-sample half was read from, and every ``(branch, is_gain, oos_gain)``
    triple in node-id order — so two callers who freeze the same cohort hash
    alike however their iterations happened to be ordered, and a re-computation
    over a *different* cohort is visible as a different digest rather than as a
    quietly different number.

    **Order is imposed here rather than trusted.**  The pairs are sorted by
    branch id before hashing, which is what makes the digest a statement about
    the cohort's *contents* rather than about the caller's iteration order — the
    same reason feature 215's ``TreeDiversity.__hash__`` sorts its mapping's
    items.

    **The floats are rendered with ``repr``**, which round-trips a float exactly
    in Python, so the digest distinguishes two cohorts whose gains differ in the
    last bit — the honest reading of *"hash its inputs"*, since a digest that
    quantised its inputs would report two different measurements as one.

    **What the digest is not.**  It is not a signature and not a proof of
    membership: this module cannot verify that the branches it was handed are
    real (:func:`_validated_cohort`), so it does the one thing it can — it makes
    the inputs behind a published figure *auditable*, which is the honest limit
    of what a feature that cannot see the partition may claim.
    """
    lines = [
        campaign,
        policy_version,
        IS_GAIN_METRIC,
        f"{CONFIDENCE_LEVEL!r}",
    ]
    lines.extend(
        f"{branch}\t{is_gain!r}\t{oos_gain!r}"
        for branch, is_gain, oos_gain in pairs
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    """The current UTC instant, at second resolution.

    Second resolution because the stored stamp is a *reading's* moment rather
    than an ordering key — nothing here is ordered by it — and because a
    sub-second component would make two readings taken in one second differ in a
    column that is not the reading.  The same helper feature 123's guard uses
    for its own row.
    """
    return datetime.now(UTC).replace(microsecond=0)


# ── The value ────────────────────────────────────────────────────────────────


class MechanismDiscrimination:
    """One campaign's ``mechanism_discrimination`` — the figure and its interval.

    The value :func:`mechanism_discrimination` persists and
    :func:`load_mechanism_discrimination` reads back, and §14.1's rule 3 made
    structural: **the interval is a field, not a derived extra.**  A value
    holding ``correlation`` alone could be printed unaccompanied, which is the
    one thing rule 3 forbids; holding the bounds beside the point makes the
    unaccompanied reading impossible to produce from this object without
    deliberately discarding them.

    * :attr:`correlation` — Pearson's r over the cohort's ``(IS_gain,
      OOS_gain)`` pairs.  The point estimate, and deliberately the *hairline*
      of ``design.md`` §9's rendering rather than the primary mark.
    * :attr:`lower` / :attr:`upper` — the 95% interval, Fisher's z.  The
      primary mark.
    * :attr:`pairs` — how many **real branches** the figure is over, which is
      the ``n`` the interval's standard error is computed from.
    * :attr:`runs` — how many ``replay_score`` rows were drawn on.  Carried
      beside :attr:`pairs` because the two are not the same number and the gap
      between them is a fact about the cohort: a branch the policy committed to
      in nine worlds is *one* point, and a figure reported without the number of
      observations behind it is one nobody can check — §14.1's rule 2 read as a
      structural requirement rather than a formatting one.
    * :attr:`policy_version` — the single revision every run was under.  §14.1's
      instrument runs at M2 *"under fixed exploration"* (architecture §994), so
      rows under two revisions would be two policies' commits and a correlation
      across them would attribute one policy's discrimination to a campaign.
    * :attr:`cohort_digest` — §14.1's rule 1, over the frozen inputs.
    * :attr:`seen_at` — when the reading was taken.

    **Immutable, and validated at construction rather than trusted.**  A
    hand-built value is a test's prerogative, and every field here reaches a
    report that a weak agent's verdict is read off, so a value no read could
    produce is refused rather than printed.  The checks are feature 186's three
    as feature 215 applies them — a canonical-UUID campaign, whole numbers that
    are not flags, ``bool`` refused first because ``True`` is ``1`` in Python —
    plus the four this feature needs and 215 has no analogue for: the floor
    (:data:`MINIMUM_PAIRS`), a correlation inside ``[-1, 1]`` that is not the
    boundary, an interval that *is* this correlation's interval, and
    ``runs >= pairs`` (a branch with no run contributes no point, so a cohort
    cannot have been drawn on fewer times than it has members).
    """

    __slots__ = (
        "_campaign_id",
        "_cohort_digest",
        "_correlation",
        "_lower",
        "_pairs",
        "_policy_version",
        "_runs",
        "_seen_at",
        "_upper",
    )

    def __init__(
        self,
        *,
        campaign_id: str,
        correlation: float,
        lower: float,
        upper: float,
        pairs: int,
        runs: int,
        policy_version: str,
        cohort_digest: str,
        seen_at: datetime,
    ) -> None:
        self._campaign_id = _validated_campaign_id(campaign_id)
        counted = _validated_count(pairs, name="pairs")
        drawn = _validated_count(runs, name="runs")
        if counted < MINIMUM_PAIRS:
            raise DiscriminationCohortError(
                f"a mechanism discrimination over {counted} real branch(es) "
                f"cannot be reported: §14.1's rule 3 is *report its interval, "
                f"not the point*, the interval is Fisher's z whose standard "
                f"error is 1/sqrt(n − 3), and below {MINIMUM_PAIRS} pairs there "
                f"is no interval to report — so the honest answer is that the "
                f"cohort cannot answer, not a bare correlation (feature 214)."
            )
        if drawn < counted:
            raise DiscriminationCohortError(
                f"a mechanism discrimination over {counted} real branch(es) "
                f"drawn on {drawn} run(s): every branch in the cohort "
                f"contributes one point at the mean of the runs it earned, so a "
                f"cohort cannot have been drawn on fewer times than it has "
                f"members — a row holding this is a row no measurement produced "
                f"(feature 214)."
            )
        point = _validated_correlation(correlation, counted)
        floor = _validated_bound(lower, name="lower")
        ceiling = _validated_bound(upper, name="upper")
        if not floor <= point <= ceiling:
            raise DiscriminationCohortError(
                f"the correlation {point!r} lies outside its own interval "
                f"[{floor!r}, {ceiling!r}]: §14.1's rule 3 makes the interval "
                f"the reported thing and the point a hairline *within* it "
                f"(design.md §9), so a point outside its bounds is a value two "
                f"different readings have been pasted together from (feature "
                f"214)."
            )
        expected_floor, expected_ceiling = _interval(point, counted)
        if not (
            math.isclose(floor, expected_floor, rel_tol=1e-12, abs_tol=1e-12)
            and math.isclose(
                ceiling, expected_ceiling, rel_tol=1e-12, abs_tol=1e-12
            )
        ):
            raise DiscriminationCohortError(
                f"the interval [{floor!r}, {ceiling!r}] is not the interval of "
                f"the correlation {point!r} over {counted} pair(s), which is "
                f"[{expected_floor!r}, {expected_ceiling!r}]: the bounds are a "
                f"function of the point and the cohort's size and of nothing "
                f"else, so bounds that do not follow from them are a row "
                f"something has edited. Recomputing rather than trusting is "
                f"what replaces the reconciliation feature 123 gets from "
                f"writing its figure onto two rows (feature 214)."
            )
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise DiscriminationCohortError(
                f"the policy version behind a reading is {policy_version!r} "
                f"({type(policy_version).__name__}) rather than a non-empty "
                f"string: every run in the cohort was under exactly one "
                f"revision — §14.1's instrument runs at M2 *under fixed "
                f"exploration* — and a blank would name the revision no policy "
                f"answers to (feature 214)."
            )
        if (
            not isinstance(cohort_digest, str)
            or len(cohort_digest) != 64
            or any(character not in "0123456789abcdef" for character in cohort_digest)
        ):
            raise DiscriminationCohortError(
                f"the cohort digest is {cohort_digest!r} rather than 64 "
                f"lowercase hex characters: §14.1's rule 1 freezes the cohort "
                f"and hashes its inputs, and the digest is what makes a "
                f"figure's inputs auditable — a value that is not a sha256 is "
                f"not a digest of anything (feature 214)."
            )
        if (
            not isinstance(seen_at, datetime)
            or seen_at.tzinfo is None
            or seen_at.utcoffset() is None
        ):
            raise DiscriminationCohortError(
                f"the instant a reading was taken is {seen_at!r}, which names "
                f"no moment: the stamp is stored as ISO-8601 UTC text beside "
                f"the figure, and a naive timestamp would make a reading's "
                f"moment a fact about the machine that recorded it (feature "
                f"214)."
            )
        self._correlation = point
        self._lower = floor
        self._upper = ceiling
        self._pairs = counted
        self._runs = drawn
        self._policy_version = policy_version
        self._cohort_digest = cohort_digest
        self._seen_at = seen_at

    @property
    def campaign_id(self) -> str:
        """The campaign this reading is scoped to, in canonical UUID text."""
        return self._campaign_id

    @property
    def correlation(self) -> float:
        """The point estimate — the hairline inside the interval, not the mark."""
        return self._correlation

    @property
    def lower(self) -> float:
        """The lower bound of the 95% interval."""
        return self._lower

    @property
    def upper(self) -> float:
        """The upper bound of the 95% interval."""
        return self._upper

    @property
    def pairs(self) -> int:
        """How many real branches the figure is over — the interval's ``n``."""
        return self._pairs

    @property
    def runs(self) -> int:
        """How many ``replay_score`` rows were drawn on."""
        return self._runs

    @property
    def policy_version(self) -> str:
        """The single policy revision every run in the cohort was under."""
        return self._policy_version

    @property
    def cohort_digest(self) -> str:
        """The sha256 over the frozen cohort's inputs (§14.1 rule 1)."""
        return self._cohort_digest

    @property
    def seen_at(self) -> datetime:
        """When the reading was taken."""
        return self._seen_at

    @property
    def interval(self) -> tuple[float, float]:
        """The two bounds as one pair — the primary mark, in one value.

        Offered beside :attr:`lower` and :attr:`upper` so a report tool that
        renders *"the interval as the primary mark"* can pass one object to a
        renderer, and the two single-bound properties stay for a caller doing
        arithmetic against one end.  Both are the same two floats; the pair is
        a convenience and not a second spelling of the figure, which is why it
        is a computed tuple rather than a stored field.
        """
        return (self._lower, self._upper)

    def row(self) -> dict[str, Any]:
        """The reading as a report-shaped mapping — a fresh dict per call.

        The shape feature 186's :meth:`WorldCensus.row`, feature 215's
        :meth:`TreeDiversity.row` and feature 123's ``to_payload`` return: a new
        mapping each time, so a report tool that writes into what it read moves
        its own copy.

        **``interval`` is nested, and that is §14.1's rule 3 in the shape of the
        data rather than in a comment.**  ``design.md`` §9: *"show the interval
        as the primary mark and the point estimate as a hairline within it"* —
        a flat row with ``correlation`` beside ``lower`` and ``upper`` invites a
        renderer to pick the first number and print it alone, which is the
        failure the rule exists to prevent.  Nesting makes the point a member
        *of* the interval rather than a sibling of it.  The ``seen_at`` stamp is
        rendered as ISO-8601 text, the form the column holds.
        """
        return {
            "campaign_id": self._campaign_id,
            "interval": {"lower": self._lower, "upper": self._upper},
            "correlation": self._correlation,
            "pairs": self._pairs,
            "runs": self._runs,
            "policy_version": self._policy_version,
            "cohort_digest": self._cohort_digest,
            "seen_at": self._seen_at.isoformat(),
        }

    def payload(self) -> str:
        """The reading as one sorted JSON line — the shape a report stores.

        ``sort_keys`` and compact separators so two readings with equal fields
        are byte-identical, which is what makes a stored reading comparable
        against a re-computation rather than merely equal in Python.  Unlike
        feature 207's ``score.json`` this document holds no metric that could be
        a ``nan`` — every field here has been validated finite — so the
        ``allow_nan`` question does not arise; it is not passed, because a
        default that never fires is a claim this module has not earned.
        """
        return json.dumps(self.row(), sort_keys=True, separators=(",", ":"))

    def __eq__(self, other: object) -> bool:
        """Equal when the parts are equal — never by ``isinstance``.

        The loader imports every member twice, once by file path under a
        synthetic name and once as the importable member, so an ``isinstance``
        check would be false for a value built from the other import of the same
        file.  Equality over the fields is the same statement and survives that,
        the discipline :meth:`signal_agent.TreeDiversity.__eq__` states for its
        own.
        """
        if not isinstance(other, MechanismDiscrimination):
            return NotImplemented
        return (
            self._campaign_id == other._campaign_id
            and self._correlation == other._correlation
            and self._lower == other._lower
            and self._upper == other._upper
            and self._pairs == other._pairs
            and self._runs == other._runs
            and self._policy_version == other._policy_version
            and self._cohort_digest == other._cohort_digest
            and self._seen_at == other._seen_at
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._campaign_id,
                self._correlation,
                self._lower,
                self._upper,
                self._pairs,
                self._runs,
                self._policy_version,
                self._cohort_digest,
                self._seen_at,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"MechanismDiscrimination(campaign_id={self._campaign_id!r}, "
            f"correlation={self._correlation!r}, "
            f"interval=({self._lower!r}, {self._upper!r}), "
            f"pairs={self._pairs!r}, runs={self._runs!r})"
        )


def _validated_count(value: Any, *, name: str) -> int:
    """Validate one denominator: a whole number, not a flag, not negative.

    ``bool`` is refused *first* because ``True`` is ``1`` in Python: a flag
    where a count belongs would report a cohort of one branch, which is the
    trap feature 215's ``_validated_cluster_count`` names for its own count and
    feature 207's ``_metric_from`` names for its metrics.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiscriminationCohortError(
            f"a reading's {name} is {value!r} ({type(value).__name__}) rather "
            f"than a whole number: it is how many {'real branches' if name == 'pairs' else 'runs'} "
            f"the figure is over, and a value that is not a count is a figure "
            f"no measurement could produce. ``bool`` is refused explicitly "
            f"because ``True`` is ``1`` in Python (feature 214)."
        )
    if value < 0:
        raise DiscriminationCohortError(
            f"a reading's {name} cannot be negative — got {value!r}: a cohort "
            f"holds zero branches or more (feature 214)."
        )
    return value


def _validated_correlation(value: Any, pairs: int) -> float:
    """Validate the point estimate: a correlation with an interval."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiscriminationCohortError(
            f"a mechanism discrimination's correlation is {value!r} "
            f"({type(value).__name__}) rather than a number: §14.1's figure is "
            f"``corr(IS_gain, OOS_gain | real branches)``, and a value that is "
            f"not a number is not a correlation (feature 214)."
        )
    figure = float(value)
    if not math.isfinite(figure) or not -1.0 <= figure <= 1.0:
        raise DiscriminationCohortError(
            f"a mechanism discrimination's correlation is {figure!r}, outside "
            f"[-1, 1]: a correlation is the share of one series' movement the "
            f"other accounts for, so a value beyond the unit interval is not "
            f"one — and a stored row holding it is a row no measurement "
            f"produced (feature 214)."
        )
    return _require_correlation(figure, pairs)


def _validated_bound(value: Any, *, name: str) -> float:
    """Validate one interval bound: a finite number inside ``[-1, 1]``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiscriminationCohortError(
            f"the {name} bound of a mechanism discrimination's interval is "
            f"{value!r} ({type(value).__name__}) rather than a number: §14.1's "
            f"rule 3 reports the interval, and a bound that is not a number is "
            f"not an interval (feature 214)."
        )
    figure = float(value)
    if not math.isfinite(figure) or not -1.0 <= figure <= 1.0:
        raise DiscriminationCohortError(
            f"the {name} bound of a mechanism discrimination's interval is "
            f"{figure!r}, outside [-1, 1]: both bounds of a correlation's "
            f"interval are themselves correlations, so a value beyond the unit "
            f"interval is a bound no transform could produce (feature 214)."
        )
    return figure


# ── The reading ──────────────────────────────────────────────────────────────


def mechanism_discrimination(
    history: Any,
    campaign_id: Any,
    real_branches: Any,
    *,
    seen_at: datetime | None = None,
) -> MechanismDiscrimination:
    """Measure one campaign's ``mechanism_discrimination`` and persist it.

    Feature 214's sentence as one call, and the member's *persists* rather than
    215's *computes*: the history handle, the campaign and the declared
    real-branch cohort in; the reading out and written down.  It answers the
    sentence whole — *"persists mechanism_discrimination per campaign, computed
    as the correlation between in-sample gain and out-of-sample gain across real
    branches"* — by reading both halves from one database in one connection, so
    the figure cannot describe a cohort other than the one the tables hold.

    **The two halves, and why they pair.**  The in-sample half is
    :data:`IS_GAIN_METRIC` — ``ir_marginal``, the one of ``0114``'s seven
    metrics that is a *gain* by definition (PRD §6.2: ``IR(book ∪ {v}) −
    IR(book)``) — read from the snapshot feature 207 froze beside each proposal
    rather than from ``node``'s live column, because feature 240 refreshes that
    row in place and a reading that followed the live column would answer *what
    does this node score now* rather than *what did this proposal score when the
    round read it* (207's own argument, and the reason §14.1's history is
    *replayable*).  The out-of-sample half is the mean of the
    ``replay_score.score`` rows whose ``committed_pick`` is the branch —
    ``IR_oos(pick | book)``, the per-world objective feature 256 computes, which
    is the *same functional form* as ``ir_marginal`` measured on the far side of
    the barrier.

    **A branch is one point.**  §14.1's unit is the branch — *"across real
    branches"* — so a refinement committed to in nine worlds is **one**
    observation at the mean of its runs.  The alternative (one observation per
    run) would repeat the same ``x`` for every world the branch was chosen in, so
    a single much-picked node would carry the correlation by frequency rather
    than by contrast, and the figure would stop being a statement about the
    cohort of refinements.

    Refuses, in this order, each naming what it is about, and **measures before
    it writes** so a refused reading leaves no row claiming it happened
    (feature 123's ordering, for its reason):

    1. an object that is not feature 207's law or store, a malformed campaign
       id, or a cohort that is not a non-empty collection of node ids — all
       before anything touches the disk;
    2. a database holding no ``node_proposal`` table (207's DDL has never run),
       no ``replay_score`` table (``0109`` unreached, so there is no
       out-of-sample half at all) or no ``campaign`` table (``0111`` unreached);
    3. a campaign the ``campaign`` table does not hold — a reading is a fact
       about a campaign, and writing it onto a row this feature invented would
       fabricate the campaign the number belongs to;
    4. a declared branch with **no recorded proposal** (a cohort member the
       campaign never proposed), one whose recorded row belongs to **another
       campaign**, or one whose snapshot carries **no in-sample gain** — a
       ``None`` ``ir_marginal`` is an absent measurement and not a zero
       (0114/207's law), so pairing it would report a figure about an
       arithmetic that never happened;
    5. a declared branch with **no committed run**, or whose runs span **more
       than one policy version** — §14.1's instrument runs under fixed
       exploration, and rows under two revisions are two policies' commits;
    6. a cohort the arithmetic cannot answer: fewer than :data:`MINIMUM_PAIRS`,
       a constant in-sample or out-of-sample series, an exactly perfect
       correlation, or a gain that is not finite.

    **Declared is not verified.**  This module cannot check that the branches it
    is handed are real (:func:`_validated_cohort`), so a cohort member that is
    in fact null is the caller's error and reaches the figure as a point whose
    ``y`` is ~0.  What the module does about that is §14.1's rule 1 rather than a
    check: the digest it stores covers the inputs, so a published figure's
    cohort can be audited afterwards.

    **The write is idempotent by campaign**, refreshing rather than appending —
    §14.1's instrument is run at M2 over a cohort that grows as the campaign
    proposes, so a campaign is expected to be measured more than once and the
    table holds the latest reading and nothing else.  ``seen_at`` defaults to
    the current UTC instant at second resolution; a caller replaying a recorded
    run supplies its own, so a replayed reading stamps the instant the original
    did.
    """
    path = _proposal_history(history)
    campaign = _validated_campaign_id(campaign_id)
    cohort = _validated_cohort(real_branches)
    instant = _utc_now() if seen_at is None else seen_at

    # The floor is checked here, before anything is opened.  Every branch in the
    # cohort is required below to carry both halves, so the cohort's size is the
    # figure's `n` whatever the store holds — which means the cheapest and
    # earliest place for this refusal is here, where it costs no connection and
    # cannot be mistaken for a statement about what the store turned out to
    # contain.
    count = len(cohort)
    if count < MINIMUM_PAIRS:
        raise DiscriminationCohortError(
            f"the cohort names {count} real branch(es) of campaign "
            f"{campaign!r}, and §14.1's figure cannot be reported over fewer "
            f"than {MINIMUM_PAIRS}: the arithmetic itself would run — a "
            f"correlation over two points is defined — but rule 3 (*report its "
            f"interval, not the point*) would not, because Fisher's z has no "
            f"standard error below three pairs and no interval at all below "
            f"four. A cohort the rule cannot be applied to is one this feature "
            f"refuses rather than one it answers a bare point about, and the "
            f"answer is to expand the campaign rather than to print a number "
            f"(feature 214)."
        )

    ordered = sorted(cohort)
    with closing(sqlite3.connect(path)) as connection, connection:
        _require_tables(connection, path)
        _require_campaign(connection, campaign)
        is_half = _read_is_half(connection, cohort, campaign)
        oos_half, policy_version, runs = _read_oos_half(connection, cohort)

    # Every value here is already a finite float: both halves were validated at
    # the moment they were read (:func:`_snapshot_gain` for the in-sample side,
    # :func:`_read_oos_half` for the other), so the two list comprehensions are
    # *ordering*, not validation.  That ordering is the point — the finiteness
    # checks ran first, during the read, so a `nan` can never reach
    # :func:`_require_spread` and be reported as a constant series, which would
    # be the right refusal for the wrong reason.
    is_gains = [is_half[branch] for branch in ordered]
    oos_gains = [oos_half[branch] for branch in ordered]
    _require_spread(is_gains, name="in-sample", pairs=count)
    _require_spread(oos_gains, name="out-of-sample", pairs=count)
    point = _require_correlation(_pearson(is_gains, oos_gains), count)
    lower, upper = _interval(point, count)
    pairs = tuple(zip(ordered, is_gains, oos_gains))
    digest = _cohort_digest(campaign, policy_version, pairs)

    reading = MechanismDiscrimination(
        campaign_id=campaign,
        correlation=point,
        lower=lower,
        upper=upper,
        pairs=count,
        runs=runs,
        policy_version=policy_version,
        cohort_digest=digest,
        seen_at=instant,
    )
    _persist(path, reading)
    return reading


def load_mechanism_discrimination(
    history: Any,
    campaign_id: Any,
) -> MechanismDiscrimination | None:
    """Read one campaign's stored reading back, or ``None`` when unread.

    The read half of the module's API, and the seam that makes the write
    checkable: a caller that has just measured a campaign can read the row and
    compare, which is the discipline feature 123's guard applies by reading its
    own half back rather than trusting the transaction.

    **The row is *reconstructed*, not merely parsed.**  Every column is fed
    through :class:`MechanismDiscrimination`'s own validating constructor, so a
    hand-edited row — a correlation outside ``[-1, 1]``, a point outside its own
    interval, bounds that are not this point's interval over this many pairs,
    fewer than :data:`MINIMUM_PAIRS`, ``runs < pairs``, a short digest, a naive
    stamp — fails to load rather than loading as a plausible-looking reading.
    That is the defence feature 123 gets from writing its figure onto two rows
    and reconciling them, taken here by reconstruction instead, because this
    feature may not add a column to a shared table and therefore has no second
    half to reconcile against.

    **``None`` means *this campaign has never been measured***, which is not
    *the store is absent* (the handle is required, and a handle with no database
    behind it is refused by 207's own scheme check) and not *the read failed*
    (which raises).  The three-way distinction :meth:`ProposalStore.load`
    states, kept because a caller that mistook the first for the second would
    re-run a measurement it already has.
    """
    path = _proposal_history(history)
    campaign = _validated_campaign_id(campaign_id)
    with closing(sqlite3.connect(path)) as connection:
        if not _has_table(connection, DISCRIMINATION_TABLE):
            # No table means this member's measurement has never run in this
            # database — 207's own DDL may not have either.  Answering `None`
            # rather than raising is the state feature 207 draws for *"a
            # campaign that has not proposed anything yet"*: a fresh deployment
            # asking what a campaign's discrimination was is asking a question
            # whose honest answer is *nothing is recorded here*.
            return None
        row = connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM {DISCRIMINATION_TABLE} "
            f"WHERE {CAMPAIGN_ID_COLUMN} = ?",
            (campaign,),
        ).fetchone()
    if row is None:
        return None
    return _reading_from_row(row, campaign)


def _reading_from_row(row: Any, campaign: str) -> MechanismDiscrimination:
    """One stored row as a reading, refused by name when it is not one.

    The stamp is parsed back from the ISO-8601 text the column holds, and a
    value that does not parse is refused with :class:`DiscriminationCohortError`
    rather than escaping as a bare ``ValueError`` — the error-vocabulary
    discipline every member seam keeps
    the member's error-vocabulary rule: a caller's handler for this
    feature's refusals must catch every way the read can decline.
    """
    (
        stored_campaign,
        correlation,
        lower,
        upper,
        pairs,
        runs,
        policy_version,
        digest,
        seen_at,
    ) = row
    if str(stored_campaign) != campaign:
        raise DiscriminationCohortError(
            f"the row read for campaign {campaign!r} carries "
            f"{stored_campaign!r}: the read is scoped by the primary key and "
            f"the two disagreeing means the row moved under the query (feature "
            f"214)."
        )
    try:
        instant = datetime.fromisoformat(str(seen_at))
    except ValueError as exc:
        raise DiscriminationCohortError(
            f"the stamp on campaign {campaign!r}'s stored reading is "
            f"{seen_at!r}, which is not an ISO-8601 instant ({exc}): the "
            f"column holds the moment the reading was taken, written by "
            f"``datetime.isoformat``, so a value that does not parse is a row "
            f"this member did not write or one something has since edited — "
            f"either way the reading beside it is not a measurement (feature "
            f"214)."
        ) from exc
    return MechanismDiscrimination(
        campaign_id=campaign,
        correlation=correlation,
        lower=lower,
        upper=upper,
        pairs=pairs,
        runs=runs,
        policy_version=policy_version,
        cohort_digest=digest,
        seen_at=instant,
    )


def _has_table(connection: sqlite3.Connection, table: str) -> bool:
    """Whether the database holds ``table`` yet — a read of ``sqlite_master``."""
    return connection.execute(_TABLE_EXISTS_SQL, (table,)).fetchone() is not None


def _require_tables(connection: sqlite3.Connection, path: Path) -> None:
    """Require the three tables this reading reads, each refused by name.

    Three refusals rather than one, because the repairs differ and naming the
    losing revision is the whole actionable content — the discipline feature
    215's ``_tree_columns`` follows for its own two depths:

    * no ``node_proposal`` → feature 207's DDL has never run in this database,
      and a campaign whose proposals were never recorded has no in-sample half
      at all.  Raised as 207's own class, unchanged, for the reason 215 raises
      it: *"a private constant of a sibling module is not a promise"* but its
      *error* is this member's shared vocabulary, and an absent proposal table
      is one fact with one repair whoever asks;
    * no ``replay_score`` → ``0109`` unreached, so there is no out-of-sample
      half — and this is the refusal that makes the feature's honest claim
      explicit: the figure needs *both* sides of the barrier, and a deployment
      that has only ever run the discovery loop cannot have one;
    * no ``campaign`` → ``0111`` unreached, so there is no campaign row to scope
      the reading to.
    """
    if not _has_table(connection, "node_proposal"):
        raise ProposalHistoryStoreUnavailableError(
            f"the store at {path} holds no node_proposal table, so there is no "
            f"recorded in-sample half to correlate: feature 214 reads the "
            f"score snapshot feature 207 persists beside each proposal "
            f"document, and a deployment whose store has never run that "
            f"member's own DDL has none. Run feature 207's DDL (its store "
            f"creates the table lazily on first use), then record the campaign "
            f"(feature 214)."
        )
    if not _has_table(connection, REPLAY_SCORE_TABLE):
        raise DiscriminationCohortError(
            f"the store at {path} holds no {REPLAY_SCORE_TABLE} table, so "
            f"there is no out-of-sample half to correlate against: §14.1's "
            f"figure is *corr(in-sample gain, out-of-sample gain)*, the "
            f"out-of-sample reading is the per-world objective feature 256 "
            f"computes and feature 255 persists one row of per committed pick, "
            f"and the table is revision {REPLAY_POLICY_REVISION} (feature 1). "
            f"A deployment that has never replayed has measured nothing "
            f"outside the barrier — run the migration chain to there and the "
            f"replays it holds (feature 214)."
        )
    if not _has_table(connection, CAMPAIGN_TABLE):
        raise DiscriminationCohortError(
            f"the store at {path} holds no {CAMPAIGN_TABLE} table, so this "
            f"reading cannot be scoped to a campaign the system planned: the "
            f"campaign row is revision {CAMPAIGN_POLICY_REVISION} (feature "
            f"104), written by the planner *before any node is expanded*, and "
            f"feature 214's sentence is *persists mechanism_discrimination per "
            f"campaign*. Run the migration chain to {CAMPAIGN_POLICY_REVISION} "
            f"(feature 214)."
        )


def _require_campaign(connection: sqlite3.Connection, campaign: str) -> None:
    """Refuse a campaign the table does not hold, by name.

    The reading is *per campaign* and joins the campaign row for its scope, so a
    measurement run against a campaign nobody planned is a caller bug worth
    learning before a figure lands nowhere.  The check is a read, not a create —
    feature 123's argument for its own guard, word for word: a store that
    inserted the missing campaign would be inventing the row the null fraction
    and the campaign type belong on.
    """
    if connection.execute(_CAMPAIGN_EXISTS_SQL, (campaign,)).fetchone() is None:
        raise DiscriminationCohortError(
            f"the {CAMPAIGN_TABLE} table holds no row for {campaign!r}: §14.1's "
            f"instrument persists mechanism_discrimination *per campaign*, so a "
            f"reading that cannot be joined to the campaign it was measured for "
            f"is refused rather than written onto a row this feature would have "
            f"to invent — the campaign is created by its planner, at planning "
            f"time, before any node is expanded (feature 214)."
        )


def _read_is_half(
    connection: sqlite3.Connection,
    cohort: tuple[str, ...],
    campaign: str,
) -> dict[str, float]:
    """Every declared branch's frozen in-sample gain, or a named refusal.

    Reads the ``node_proposal`` rows for exactly the declared branches — the
    ``IN`` clause *is* the ``| real branches`` filter, so an undeclared
    branch's snapshot is never read (see :data:`_IS_HALF_SQL`) — and returns the
    one metric §14.1's formula calls the in-sample gain.

    Three refusals, and each names the branch:

    * **no recorded proposal.**  A cohort member the campaign never proposed
      cannot be paired.  Refused rather than dropped, because rule 1 is explicit
      — *"A cohort assembled after seeing results is a selection, not a
      sample"* — and a figure computed over whatever subset happened to have
      both halves is a cohort assembled after the fact *by availability*, which
      is the same failure one step removed;
    * **a recorded row belonging to another campaign.**  The scope is the
      *stored* ``campaign_id`` (feature 207 took it from the ``node`` row at the
      moment of the write), never the caller's pairing of branch to campaign —
      so a branch from another campaign is refused rather than quietly
      contributing its gain to this campaign's correlation;
    * **a snapshot with no in-sample gain.**  ``ir_marginal`` is nullable in
      ``0114`` because the metrics are *measured* and *"a pre-metric row has no
      honest value to assert"*, so an absence is an absence and not a zero.  An
      attempt that failed before the evaluator reached it has a persisted
      snapshot with every metric ``null`` — an expected state, and one this
      reading must decline rather than treat as a gain of zero.
    """
    placeholders = ", ".join("?" for _ in cohort)
    rows = connection.execute(
        _IS_HALF_SQL.format(placeholders=placeholders), cohort
    ).fetchall()
    recorded = {str(node): (str(scope), score) for node, scope, score in rows}
    gains: dict[str, float] = {}
    for branch in cohort:
        if branch not in recorded:
            raise DiscriminationCohortError(
                f"real branch {branch!r} has no recorded proposal in this "
                f"store, so its in-sample gain cannot be read: §14.1's figure "
                f"pairs each branch's frozen in-sample gain against the "
                f"out-of-sample gain it earned, both halves come from rows "
                f"feature 207 and feature 255 persisted, and a declared branch "
                f"with no snapshot is one the store cannot pair. Refused rather "
                f"than dropped — a cohort reduced after the fact to whatever "
                f"had both halves is a selection, not a sample (feature 214, "
                f"§14.1 rule 1)."
            )
        scope, document = recorded[branch]
        if scope != campaign:
            raise DiscriminationCohortError(
                f"real branch {branch!r} is declared as a member of campaign "
                f"{campaign!r}, but its recorded proposal belongs to campaign "
                f"{scope!r}: the scope on the row is the one feature 207 took "
                f"from the node's own row at the moment of the write, so the "
                f"store's answer is the authority and this branch's gain must "
                f"not be correlated into another campaign's figure (feature "
                f"214)."
            )
        gains[branch] = _snapshot_gain(document, branch)
    return gains


def _snapshot_gain(document: Any, branch: str) -> float:
    """One stored score snapshot's in-sample gain, refused when it carries none.

    Parsed through feature 207's own :meth:`ScoreRecord.from_json`, which is the
    *public* member type rather than a private constant of a sibling module — so
    the reason :mod:`signal_agent._diversity` restates its table and column
    names does not apply here: what this module must not do is re-implement the
    parse, because a second reading of ``score.json`` is a second definition of
    what the document holds.  A row that does not parse, or that is not an
    object, is therefore 207's :class:`ProposalContentError`, raised unchanged —
    the same fact with the same repair whoever asked.

    The gain itself is read by name from the record and then required finite,
    for the reason :func:`_require_finite` gives: a snapshot is JSON text and
    Python's decoder accepts ``Infinity``, so a stored ``inf`` is reachable even
    though feature 207's own writer refuses to render one (``allow_nan=False``).
    """
    record = ScoreRecord.from_json(document, branch)
    gain = getattr(record, IS_GAIN_METRIC)
    if gain is None:
        raise DiscriminationCohortError(
            f"real branch {branch!r} has a recorded proposal whose score "
            f"snapshot carries no {IS_GAIN_METRIC}, so it has no in-sample "
            f"gain to correlate: §14.1's formula pairs *in-sample gain* against "
            f"out-of-sample gain, and 0114 declares every metric nullable "
            f"because a pre-metric row *has no honest value to assert* — an "
            f"attempt that failed before the evaluator reached it is persisted "
            f"with its metrics absent, which is an absence and not a gain of "
            f"zero. Freeze a cohort the store can pair, or measure the campaign "
            f"once the attempt has been re-run (feature 214)."
        )
    return _require_finite(gain, name="in-sample", branch=branch)


def _read_oos_half(
    connection: sqlite3.Connection, cohort: tuple[str, ...]
) -> tuple[dict[str, float], str, int]:
    """Each declared branch's out-of-sample gain, the revision under it, the run count.

    The mean of the ``replay_score.score`` rows whose ``committed_pick`` is the
    branch — §14.1's unit is the *branch*, so a refinement committed to in nine
    worlds is one point (the argument is at
    :func:`mechanism_discrimination`).  The count of those rows comes back
    beside the means because it is a fact about *this* read — the number of
    out-of-sample observations the figure was drawn on — and a count taken in a
    second statement would be a count of whatever the table held when that
    statement ran.  Two refusals, and the second is the one that keeps §14.1's
    instrument honest:

    * **no committed run.**  A declared branch the pool holds no pick for
      contributed no out-of-sample reading, so it has no ``y``.  Refused rather
      than dropped, for rule 1's reason;
    * **more than one policy version.**  A reading whose runs span two revisions
      correlates one policy's in-sample gains against another's commits — and
      §14.1 runs this instrument at M2 *"under fixed exploration"*
      (architecture §994), so rows under two revisions are not a cohort this
      figure is defined over.  Refused rather than scoped to one revision, and
      the alternative is worth stating because it is the tempting one: a
      ``policy_version`` filter would let a caller silently correlate a subset
      of the campaign's runs, which is a cohort assembled after seeing results
      *by hand* — rule 1's failure with a different author.
    """
    placeholders = ", ".join("?" for _ in cohort)
    rows = connection.execute(
        _OOS_HALF_SQL.format(placeholders=placeholders), cohort
    ).fetchall()
    scores: dict[str, list[float]] = {}
    versions: set[str] = set()
    for pick, policy_version, score in rows:
        if policy_version is None or not str(policy_version).strip():
            raise DiscriminationCohortError(
                f"a {REPLAY_SCORE_TABLE} row whose committed pick is one of "
                f"this campaign's real branches names no policy version: "
                f"§14.1's instrument runs at M2 *under fixed exploration*, and "
                f"a run under no named revision cannot be shown to have been "
                f"under the same exploration as the rest of the cohort "
                f"(feature 214)."
            )
        versions.add(str(policy_version))
        branch = str(pick)
        scores.setdefault(branch, []).append(
            _require_finite(score, name="out-of-sample", branch=branch)
        )
    if len(versions) > 1:
        listed = ", ".join(sorted(versions))
        raise DiscriminationCohortError(
            f"the runs behind this reading span {len(versions)} policy "
            f"versions ({listed}): §14.1's figure correlates in-sample gain "
            f"against out-of-sample gain *for one agent under fixed "
            f"exploration* (architecture §994 — the M2 gate is *per-commit OOS "
            f"IR under fixed exploration*), and rows under two revisions are "
            f"two policies' commits, so a correlation across them would "
            f"attribute one policy's discrimination to a campaign. Refused "
            f"rather than filtered to one revision: a filter would let a caller "
            f"correlate a subset of the campaign's runs by hand, which is a "
            f"cohort assembled after seeing results (feature 214, §14.1 rule 1)."
        )
    gains: dict[str, float] = {}
    for branch in cohort:
        if branch not in scores:
            raise DiscriminationCohortError(
                f"real branch {branch!r} has no committed run in the replay "
                f"pool, so its out-of-sample gain cannot be read: §14.1's "
                f"figure pairs each branch's frozen in-sample gain against the "
                f"out-of-sample gain it earned, and "
                f"{REPLAY_SCORE_TABLE}.{REPLAY_SCORE_PICK_COLUMN} (nullable, "
                f"because a candidate scored but never selected has no pick) "
                f"names no row for it. A branch the policy never committed to "
                f"was never scored outside the barrier — declined rather than "
                f"paired against a fabricated zero (feature 214)."
            )
        values = scores[branch]
        gains[branch] = math.fsum(values) / len(values)
    # Unreachable while the cohort is non-empty and every declared branch is
    # required above to have a run — and asserted rather than left implicit,
    # because the fallback matters: the stored column is NOT NULL, so a reading
    # carrying no revision would be a row the schema refuses, while a `None`
    # reaching the value object would be reported as *a malformed policy
    # version* rather than as the internal inconsistency it is.
    assert versions, "a non-empty cohort requires at least one committed run"
    return gains, versions.pop(), sum(len(values) for values in scores.values())


def _persist(path: Path, reading: MechanismDiscrimination) -> None:
    """Write the reading into this member's table, idempotently by campaign.

    Owns the connection because it is the *second* transaction: the halves are
    read and the arithmetic is done first (in :func:`mechanism_discrimination`'s
    connection), so a refused cohort never opens a write at all — feature 123's
    ordering, and the reason its ``guard`` measures before it touches the store.

    ``CREATE TABLE IF NOT EXISTS`` on every call, the contract every store in
    this workspace states: a fresh database and one this build has written to a
    hundred times must both work, and a member-owned table is the one piece of
    DDL this member is entitled to run.  The ``ON CONFLICT`` upsert is feature
    123's, for the same reason — the grain is the campaign, so a re-reading
    refreshes the row rather than appending a second one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(_SCHEMA)
        connection.execute(
            f"INSERT INTO {DISCRIMINATION_TABLE} ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _COLUMNS)}) "
            f"ON CONFLICT({CAMPAIGN_ID_COLUMN}) DO UPDATE SET "
            f"correlation = excluded.correlation, "
            f"interval_lower = excluded.interval_lower, "
            f"interval_upper = excluded.interval_upper, "
            f"pairs = excluded.pairs, runs = excluded.runs, "
            f"policy_version = excluded.policy_version, "
            f"cohort_digest = excluded.cohort_digest, "
            f"seen_at = excluded.seen_at",
            (
                reading.campaign_id,
                reading.correlation,
                reading.lower,
                reading.upper,
                reading.pairs,
                reading.runs,
                reading.policy_version,
                reading.cohort_digest,
                reading.seen_at.isoformat(),
            ),
        )
