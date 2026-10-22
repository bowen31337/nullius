"""The campaign close-out CLI -- ``python -m orchestrator.closeout``.

additions_spec_operator_surfaces.xml, "Campaign Close-out" category,
feature 13: *System closes out a finished campaign from* ``python -m
orchestrator.closeout --campaign-id ID``. *It saves the campaign's
calibration figures to the stores the dashboard and API read, and displays
them as one JSON line, so FDR_deploy is measured for real campaigns and not
only for the demo seeder.*

This module *is* the scorer process prd §4.2 grants the sidecar key to: it
resolves :class:`scoring.NullPickScorer` and :class:`nulloracle.NullSidecar`
from ``NULL_SIDECAR_PATH``/``NULL_SIDECAR_KEY_REF``, reads the campaign's
evaluated node rows, splits their in-sample scores into the null and real
samples :class:`nulloracle.KsGuard` compares, and hands the campaign's
planted roots and its discoveries (each mapped to its root) to the scorer's
own ``calibration_figures`` verb -- never reading or printing a node id
beside its null status (PRD §4.2), and never deriving a label anywhere but
inside this one process.

**The sidecar seals one assignment per root, and every evaluated node is
asked through it.**  §7.3 makes a campaign homogeneous in null type, and a
Type-R subtree inherits its root's sealed assignment by construction (the
same rule :class:`orchestrator._oracle.SubtreeOracle` applies during
evaluation).  So this module never asks the sidecar about an evaluated
node's own id: every node -- root or child -- is first walked to its root
(:func:`_resolve_root`, reusing :meth:`SubtreeOracle._root_of` rather than
restating the ``parent_id`` walk), and it is the *root's* entry the sidecar
answers for.  The KS split puts every evaluated node's ``ic_mean`` on the
side its root's label chose; the population :meth:`scoring.NullPickScorer.
calibration_figures` measures over is the campaign's planted roots (the
only nodes the sidecar ever holds an entry for), and a discovery is mapped
to its root before it is handed over as a pick -- so two discoveries under
one root are one pick, exactly as that verb's own docstring states for a
repeated node.  A node whose walk cannot reach a root, or reaches one this
campaign did not plant, or reaches a root the sidecar holds no entry for,
is refused by this module rather than read as unlabelled.

**Gate A and Gate B (bug_spec_ks_null_calibration_gate.xml): the verdict
tests whether the nulls still look like nulls, never whether a real root
carries edge.**  PRD §4.3 states the guard's whole premise: *"the nulls are
detectable, the agent may be learning to identify them"* -- a statement
about whether the null branches' own construction (the block permutation
and its length) leaks, not about whether a real root carries genuine edge.
Every design this module carried before this fix -- feeding the guard every
evaluated node's ``ic_mean`` (the original shape), then root-only and
non-significance-truncated samples (bug_spec_ks_guard_root_level.xml,
bug_spec_closeout_type_d_ks_branch.xml) -- was still a **comparison of null
scores against real ones**, and a two-sample comparison rejects exactly
when the two sides differ, for *any* reason: a window where real signals
have power makes the real side a mixture of edge and noise while the null
side stays noise alone, so the test rejected "real roots have edge" and
reported it as "the nulls are detectable".  Ten synthetic archC campaigns
with a planted, genuine, weak real edge (every real root's own ``ic_tstat``
below the discovery bar, so none would be flagged a discovery on its own)
voided 6 of 10 while the nulls were, by construction, perfectly calibrated;
twenty-five archM campaigns with *weaker* real edge voided 0 of 25 --
rewarding weaker research with a cleaner bill of calibration health, the
exact inversion §7.4's guard exists to prevent.  No non-significance
truncation closes this gap, because the real side's own non-significant
members still carry the window's genuine (if individually sub-threshold)
edge; the comparison itself is the defect.

So this module no longer compares null scores against real ones to decide
``calibration_status`` at all.  Two gates, each a test the nulls alone (or
the campaign's own choices alone) can fail, replace it:

* **Gate A, null calibration.**  Every null's own ``ic_tstat`` -- one per
  root for a Type-R campaign (PRD §4.1.2's *"null status inherited by the
  whole subtree"* makes a child's reading the same label's, so the gate
  loses nothing reading one per root and nothing by never reading a child);
  one per branch for a Type-D campaign, its **shallowest** null node
  (:class:`nulloracle.TypeDOracle`'s own depth resolution, the same one the
  Type-B step below reads -- every Type-D root is real, PRD §4.1.2, so a
  root-only reading would find no null to test at all, which is
  bug_spec_closeout_type_d_ks_branch.xml's own bug; shallowest rather than
  every past-flip node for the same pseudo-replication reason Type-R excludes
  a child -- a branch refined several times past its flip would otherwise
  count correlated descendants as independent samples) -- is tested with a
  **one-sample, two-sided Kolmogorov-Smirnov test against N(0,1)**
  (:func:`_one_sample_ks_against_standard_normal`; nulloracle's own ``ks``
  module carries no one-sample estimator to call, so this module restates
  the asymptotic Kolmogorov series it already documents, with the Stephens
  (1970) small-sample correction).  This is the test PRD §4.3's own sentence
  actually describes: *do the nulls look like the no-edge distribution their
  construction promises*, asked of the nulls alone, with no real-root value
  anywhere in the sample a genuine edge could move.  VOID at
  ``pvalue < nulloracle.VOID_THRESHOLD`` (the same 0.05 the previous, removed
  gate used -- what changed is the comparison, not the level); fewer than
  :data:`GATE_A_MIN_NULL_COUNT` null values leaves the gate
  :data:`CALIBRATION_STATUS_INSUFFICIENT`, neither VOID nor ok, the same
  "untested, too little evidence" reading :data:`CALIBRATION_STATUS_
  INSUFFICIENT` has always named.  ``gate_a_p`` (and its persisted alias
  ``ks_pvalue``) is this figure; ``null_tstat_mean``/``null_tstat_sd`` are
  the sample's own two aggregate numbers, reported because an operator
  investigating a VOID needs to see which way the nulls drifted without PRD
  §4.2 ever handing back a single root's own label.

* **Gate B, agent behaviour.**  A campaign's nulls can also be calibrated
  while the *exploration policy itself* leaks -- learning, in effect, to
  avoid expanding a null root even though it cannot read ``is_null``, by
  whatever surface correlates with it.  This gate asks exactly that: of
  every planted root the sidecar holds an entry for, was it ever **selected
  for expansion** -- does its subtree carry any node beside itself at all
  (:func:`_read_campaign_node_parents`; a node counts whether or not its own
  evaluation succeeded, because an attempt the sandbox or a tripwire failed
  still used the policy's own pick) -- and does that bit depend on the
  root's null status?  A **two-sided Fisher exact test**
  (:func:`_fisher_exact_two_sided`, exact over the hypergeometric
  distribution the 2x2 table's margins imply) over (null, real) x (expanded,
  never expanded).  VOID at ``pvalue < GATE_B_VOID_THRESHOLD`` -- 0.01,
  stricter than Gate A's 0.05 because it is a *second* gate on the same
  campaign, and running two tests at one level would compound their
  combined false-positive rate past what either is calibrated for.
  :data:`CALIBRATION_STATUS_INSUFFICIENT` when either label class is empty
  or no root was ever expanded at all -- the spec's own "insufficient when
  no root was expanded".  ``gate_b_p`` is this figure.

**calibration_status** is VOID if either gate rejects (sticky: once a prior
run or this one has voided the campaign, :func:`_force_void` never clears
it, the same one-way rule :class:`nulloracle.CampaignVerdict` itself states
for its own write); ok unless Gate A is itself
:data:`CALIBRATION_STATUS_INSUFFICIENT`.  Gate B's own insufficiency does
not, by itself, downgrade an otherwise-clean Gate A reading to
``insufficient``: a campaign that never expanded a single root (a short
run, a tiny synthetic one) has no agent-behaviour evidence either way, which
is not itself a finding, unlike Gate A's own floor -- PRD §4.1.1's own
floor keeps a live campaign's planted null count at two or more, so Gate
A's insufficiency is a genuine, rare structural state, while Gate B's is the
common shape of a campaign nothing has been asked to explore yet.

**The previous comparison survives, demoted to a diagnostic, never
gating.**  :attr:`CloseoutResult.ks_pvalue_root_nonsig` is exactly
bug_spec_ks_guard_root_level.xml's and bug_spec_closeout_type_d_ks_branch.
xml's own sample and test -- one ``ic_mean`` per root (Type-R) or per
branch (Type-D), truncated to values whose own ``|ic_tstat|`` has not
cleared :data:`DISCOVERY_TSTAT`, null side against real side -- computed and
persisted exactly as before (:class:`nulloracle.KsGuard` still writes
``campaign.ks_pvalue`` and ``campaign_ks_guard`` with it, the one column
``ops.instrument_status``'s KS lamp and this store's own read-back
invariant both depend on), but no longer read by
:class:`nulloracle.CampaignVerdict` to decide anything: that call is
removed from this module entirely, because it is precisely the comparison
this bug fix found guilty.  :attr:`CloseoutResult.ks_root_counts` is that
diagnostic sample's ``(n_null, n_real)``, unchanged.
:attr:`CloseoutResult.ks_pvalue_all_nodes` is the older, pre-root-level
diagnostic (every evaluated node's own ``ic_mean``), also unchanged and also
never gating.  :attr:`CloseoutResult.ks_variant` now names the one rule this
module gates on, :data:`KS_VARIANT_NULL_CALIBRATION`, for both campaign
types -- which unit Gate A's own sample used (root or branch) is no longer a
fact about the verdict, only about where its sample came from.

**Why this module reads ``node`` with raw SQL rather than a shared
reader.**  No member in this workspace exposes "every evaluated node of a
campaign" as a public call: :mod:`orchestrator._live_tree` and
:mod:`orchestrator._oracle` each restate the columns they need in their own
module, because the ``node`` table is the tree's -- owned by the migrations
(``0118``, ``0114``) and by :mod:`discovery.persist`'s attempt log, which
adds ``fail_class`` by its own ``ALTER TABLE`` probe rather than a
migration.  This module follows the same convention: it restates the four
columns it reads (``id``, ``fail_class``, ``ic_mean``, ``ic_tstat``) rather
than inventing a reader another member would have to agree with, and it
probes for ``fail_class`` the way every lazily-added column in this
workspace is probed for, reading its absence as "nothing has failed yet"
rather than refusing a tree no attempt has ever touched.

**The five stores, in the sentence's own order.**  1) :class:`nulloracle.
KsGuard` writes the campaign's *diagnostic* p-value (the demoted, null-vs-
real comparison above) -- 2) :class:`nulloracle.CampaignVerdict` is no
longer called from this module: Gate A and Gate B (above) decide and write
``calibration_status`` directly, themselves and via :func:`_force_void`;
3) :meth:`scoring.NullPickScorer.calibration_figures` answers sensitivity and
specificity over the campaign's planted population and its discoveries;
4) :class:`scoring.FdrDeployStore` reweights that pair to ``FDR_deploy`` and
persists it; 5) :class:`ops.NullCalibrations` persists the pair itself. For
a Type-D campaign only, :func:`scoring.account_errors` answers the Type-B
depth-past-flip count, persisted by :class:`ops.TypeBDepths`. Last,
:class:`ops.DiscoveryRates` persists the discovery rate over the trial
ledger's own budget-charging and total counts for the campaign. Every store
is idempotent on the campaign's id, so running this command twice saves no
duplicate row and prints the same line.

**Exit codes.** 0 once the campaign is calibrated; 3 when the verdict is
``VOID`` -- the figures are saved either way, and the exit code is what lets
an ``OnFailure`` alert hook fire; 2 for a missing ``DATABASE_URL`` or an
unconfigured sidecar, naming the variable; 1 when a collaborator refuses (an
unknown campaign, a one-sided plant with no real or no null node, an
evaluated node the sidecar holds no entry for, a campaign whose ``node``
table carries no evaluation metrics, or any other unreadable ``node`` table),
printing its message with no traceback.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import os
import sqlite3
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import ledger
import nulloracle
import ops
import policy_runtime
import replay
import scoring
from artifacts import ArtifactStore

from ._context import EvaluationContext, load_evaluation_context
from ._evaluate import evaluate_on_dates
from ._oracle import OracleTargetError, SubtreeOracle
from ._targets import snapshot_forward_returns

__all__ = [
    "CALIBRATION_STATUS_INSUFFICIENT",
    "CLOSEOUT_CODE",
    "CLOSEOUT_TRIAGE_TABLE",
    "CLOSEOUT_UNEVALUATED_CODE",
    "DATABASE_URL_ENV",
    "DISCOVERY_TSTAT",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_VOID",
    "GATE_A_MIN_NULL_COUNT",
    "GATE_B_VOID_THRESHOLD",
    "KS_VARIANT_NULL_CALIBRATION",
    "M2_FIXED_BETA",
    "M2_FIXED_POLICY_VERSION",
    "SELECTION_RULE_IC_FALLBACK",
    "SELECTION_RULE_POST_COST_IR",
    "TRIAGE_MIN_SIDE",
    "CloseoutError",
    "CloseoutResult",
    "close_out",
    "main",
]

#: The greppable word every refusal this module itself pronounces opens
#: with -- never a collaborator's own message, which already opens with its
#: own code word.
CLOSEOUT_CODE = "closeout"

#: The code word a campaign whose ``node`` rows carry no metric columns is
#: refused with -- distinct from :data:`CLOSEOUT_CODE` so a reader can tell
#: "no evaluation has ever run against this store" from "something else went
#: wrong reading it" without parsing the sentence that follows.
CLOSEOUT_UNEVALUATED_CODE = "closeout_unevaluated"

#: The environment variable naming the research database -- the one
#: spelling every store in this workspace already uses.
DATABASE_URL_ENV = "DATABASE_URL"

#: The in-sample bar a committed evaluation's ``ic_tstat`` must clear to
#: count as a discovery -- the two-sided ``p < 0.05`` threshold restated as
#: a t-statistic (prd's own "roughly p < 0.05" reading of the bar).  A
#: module constant, documented here, rather than a number repeated at each
#: call site.
DISCOVERY_TSTAT = 2.0

#: The discovery, commit and ranking rule a node carrying ``ir_tstat`` is
#: read by (additions_spec_cost_aware_selection.xml, "Cost-Aware Selection",
#: feature 2): discovery is ``ir_tstat >= DISCOVERY_TSTAT and ic_tstat > 0``,
#: and the commit ranks eligible nodes by ``ir_tstat``.  Named here so
#: :attr:`CloseoutResult.selection_rule` can report which rule a close-out
#: actually ran without a reader re-deriving it from the source.  The commit
#: leg skips a node whose root the sidecar labels null even when it cleared
#: the bar (see :func:`_commit_top_node`) -- the rule the discovery count and
#: the commit share is the bar, and the label is the commit's own addition.
SELECTION_RULE_POST_COST_IR = "post-cost-ir"

#: The rule a node whose ``ir_tstat`` was never written falls back to -- the
#: in-sample IC bar feature 2 replaces, kept alive for a tree evaluated by an
#: orchestrator that predates feature 1 (the column is added by the tree
#: writer's own probe-then-``ALTER``, never backfilled onto a row a past
#: evaluation already wrote).  ``ic_tstat >= DISCOVERY_TSTAT`` already implies
#: a positive value at this bar, so the fallback needs no separate sign test.
SELECTION_RULE_IC_FALLBACK = "ic-fallback"

#: Close-out's own third calibration reading, alongside nulloracle's ``'ok'``
#: and ``'VOID'``: Gate A had fewer than :data:`GATE_A_MIN_NULL_COUNT` null
#: values to test at all (PRD §4.3; bug_spec_ks_null_calibration_gate.xml).
#: Never written to the campaign row -- :mod:`nulloracle`'s own
#: ``calibration_status`` column carries only the two values its own verdict
#: pronounces -- but reported here so a reader of the printed line can tell
#: "untested, too little evidence" from "tested and cleared".  Gate B's own
#: insufficiency (no root ever expanded, or an empty label class) never by
#: itself produces this combined reading -- see "Gate A and Gate B" in the
#: module docstring for why.
CALIBRATION_STATUS_INSUFFICIENT = "insufficient"

#: The gate variant this module computes (bug_spec_ks_null_calibration_
#: gate.xml): a campaign's calibration no longer turns on any comparison of
#: null scores against real ones -- see "Gate A and Gate B" in the module
#: docstring for the rule and the evidence that replaced the previous
#: null-vs-real design (:data:`DISCOVERY_TSTAT`-truncated two-sample KS,
#: kept below only as a diagnostic).  One name, for both campaign types: the
#: unit Gate A samples still follows the type (one value per root for
#: Type-R, one per branch for Type-D), but that distinction is no longer a
#: fact about the *verdict*, only about where its sample came from, so it is
#: no longer named on :attr:`CloseoutResult.ks_variant`.
KS_VARIANT_NULL_CALIBRATION = "null-calibration"

#: Gate A's floor: fewer than this many null values (one per root for
#: Type-R, one per branch's shallowest null node for Type-D) leaves a
#: one-sample test with nothing to resolve a shape from -- the same
#: structural reasoning :data:`nulloracle.KS_MIN_SAMPLE` states for a
#: two-sample comparison, specialised to the single sample Gate A reads.
#: Below it, Gate A is :data:`CALIBRATION_STATUS_INSUFFICIENT`, never VOID
#: or ok.
GATE_A_MIN_NULL_COUNT = 3

#: Gate B's void level -- stricter than Gate A's :data:`nulloracle.
#: VOID_THRESHOLD` because Gate B is a *second* gate: a campaign already has
#: one chance to be voided on Gate A's 0.05, and a second test run at the
#: same level would raise the whole procedure's false-positive rate above
#: what either gate alone is calibrated for.
GATE_B_VOID_THRESHOLD = 0.01

#: The policy version every close-out world score is persisted under — a
#: single, fixed baseline (additions_spec_m2_baseline_financial_worlds.xml,
#: feature 2) rather than a revision's own version, so dreaming's own
#: "m2-fixed" arm (feature 3, out of this module's scope) always has one
#: name to compare a candidate's "{version}#financial" rows against,
#: whichever campaign the world came from.
M2_FIXED_POLICY_VERSION = "m2-fixed"

#: The beta the fixed baseline is scored at. Close-out commits the single
#: top in-sample node and never explores, so "m2-fixed" is not a function
#: of beta the way a swept revision's own rounds are -- but
#: ``replay_score.beta`` is ``NOT NULL`` (migration 0109) and
#: :func:`replay.persist_replay_score` requires a finite number. ``0.5`` is
#: the workspace's own default explore/exploit scalar
#: (:func:`orchestrator.dream.main`'s own ``--beta`` default), reused here
#: as the one fixed point every "m2-fixed" row is filed under.
M2_FIXED_BETA = 0.5

#: Calibrated: the campaign closed out and its verdict is not VOID.
EXIT_OK = 0
#: A collaborator refused: an unknown campaign, a one-sided plant, or an
#: evaluated node the sidecar holds no entry for.
EXIT_REFUSED = 1
#: Missing configuration: no DATABASE_URL, or no sidecar.
EXIT_CONFIG = 2
#: The verdict is VOID. The figures are still saved; this code is what lets
#: an alert hook fire.
EXIT_VOID = 3

#: The tree store's node table -- feature 97's, read here and created
#: nowhere: a database this command is pointed at must already hold the
#: finished campaign's tree.
NODE_TABLE = "node"

_logger = logging.getLogger(__name__)

#: The M1 triage figure's own table -- created here (``CREATE TABLE IF NOT
#: EXISTS``, the contract every store in this workspace states), unlike
#: ``node``: this one is close-out's own research row, not a tree table a
#: live evaluation already owns. One row per campaign, refreshed on rerun.
CLOSEOUT_TRIAGE_TABLE = "closeout_triage"

#: The fewest nodes either side (planted-null or planted-real) must carry for
#: the perturbation-stability AUC to mean anything -- a Mann-Whitney U needs
#: at least two values a side to rank against the other side at all. Below
#: this, ``triage_auc`` is ``None`` rather than the uninformative ``0.5`` a
#: naive formula would divide its way to.
TRIAGE_MIN_SIDE = 2


class CloseoutError(Exception):
    """A refusal this module itself pronounces, by name.

    An unknown campaign, or an evaluated node the sidecar holds no entry
    for: both are facts about the close-out's own ask rather than a
    collaborator's internal law, so they are named here rather than
    borrowing another member's vocabulary for a question that member was
    never asked.
    """


@dataclass(frozen=True)
class CloseoutResult:
    """What one close-out run saved and printed -- the JSON line's content.

    ``type_b`` is ``None`` for a Type-R campaign (the figure is Type-D's
    own, prd §4.1.2) and the measured count -- possibly ``0`` -- for a
    Type-D one.

    ``ks_pvalue`` (and its alias ``gate_a_p``) is Gate A's one-sample p-value
    -- the figure :attr:`calibration_status` is actually voided on, alongside
    ``gate_b_p`` -- ``None`` when Gate A itself is
    :data:`CALIBRATION_STATUS_INSUFFICIENT` (fewer than
    :data:`GATE_A_MIN_NULL_COUNT` null values).  See "Gate A and Gate B" in
    the module docstring for the rule.  ``null_tstat_mean``/``null_tstat_sd``
    are Gate A's own sample, reported as the two aggregate numbers prd §4.2
    allows past the barrier -- never the per-root values themselves --
    ``None`` when Gate A has no null value to summarise at all.

    ``ks_pvalue_all_nodes`` and ``ks_pvalue_root_nonsig`` are diagnostics,
    never gating: the former is every evaluated node's own ``ic_mean``, root
    and child alike, the sample this module gated on before
    bug_spec_ks_guard_root_level.xml, always present; the latter is that
    fix's own root/branch-level, :data:`DISCOVERY_TSTAT`-truncated two-sample
    comparison of null roots against real ones, the sample
    :mod:`nulloracle.ksguard`'s store still persists (``None`` when its own
    sample is too thin to compute at all) -- the comparison this bug fix
    removed from the verdict because a real root's genuine edge moved it, not
    because the nulls themselves looked any different from their own known
    distribution.  ``ks_root_counts`` is that diagnostic sample's
    ``(n_null, n_real)``, unchanged from before this fix.

    ``discoveries`` is additions_spec_cost_aware_selection.xml feature 2's
    cost-aware count -- ``ir_tstat >= DISCOVERY_TSTAT and ic_tstat > 0``,
    falling back per node to the plain ``ic_tstat >= DISCOVERY_TSTAT`` rule
    where a node carries no ``ir_tstat`` -- the count :meth:`scoring.
    NullPickScorer.calibration_figures` and :class:`scoring.FdrDeployStore`
    are both measured against. ``discoveries_ic`` is the previous rule's own
    count over every evaluated node, kept as a diagnostic and never fed to
    either store. ``selection_rule`` names which rule this close-out actually
    ran: :data:`SELECTION_RULE_POST_COST_IR` when at least one evaluated node
    carried ``ir_tstat``, :data:`SELECTION_RULE_IC_FALLBACK` when none did (a
    tree evaluated before that feature landed).

    ``null_discoveries`` counts the discoveries of that count whose root the
    sidecar labels null -- bar-clearing null branches the commit skipped
    (see :func:`_commit_top_node`).  It is ``0`` for a campaign with no
    null branch past the bar, and a campaign whose only bar-clearing nodes
    are null abstains (``committed_pick`` ``None``) exactly as a campaign
    with no discovery does.  A count, never a node id: the payload reports
    how many null branches were skipped, not which ones (PRD §4.2).

    ``dedup_skipped`` and ``dedup_against`` are additions_spec_dedup_
    committed_constructs.xml's pair: the number of bar-clearing real nodes
    the commit skipped because their in-sample fingerprint equals one an
    earlier campaign under the same ``evaluation_config_sha256`` already
    committed, and the number of earlier picks they were checked against.
    Both are ``0`` for every campaign whose evaluation config omitted the
    key or set it ``false`` -- which is every campaign written before the
    key existed -- and for one whose config set it ``true`` but whose store
    holds no earlier commit under the same hash.  Counts, not identities,
    the same §4.2 stance ``null_discoveries`` takes.
    """

    campaign_id: str
    ks_pvalue: float | None
    ks_pvalue_all_nodes: float
    ks_pvalue_root_nonsig: float | None
    ks_variant: str
    ks_root_counts: tuple[int, int]
    gate_a_p: float | None
    gate_b_p: float | None
    null_tstat_mean: float | None
    null_tstat_sd: float | None
    calibration_status: str
    sensitivity: float
    specificity: float
    fdr_deploy: float | None
    type_b: int | None
    discoveries: int
    discoveries_ic: int
    null_discoveries: int
    dedup_skipped: int
    dedup_against: int
    selection_rule: str
    budget_charging_trials: int
    ledger_trials: int
    triage_auc: float | None
    triage_null_count: int
    triage_real_count: int
    committed_pick: str | None
    oos_ir: float | None
    oos_ic_tstat: float | None
    world_persisted: bool

    @property
    def is_void(self) -> bool:
        """Whether the campaign's verdict is VOID."""
        return self.calibration_status == nulloracle.CALIBRATION_STATUS_VOID

    def to_payload(self) -> dict[str, Any]:
        """The result as the one JSON line this command prints.

        Never a node id beside a null label (PRD §4.2): every field here is
        a campaign-level aggregate -- a p-value, a status, two fractions, a
        count -- and none of them is a node's own identity. The same holds
        for the M1 triage figure: ``triage_auc`` and the two side counts are
        the whole of it, never a node id or its label.

        ``committed_pick`` is the one node id this payload *does* print --
        the node close-out committed to, or ``null`` for a miss.  The
        pick's own identity is not what PRD §4.2 protects; only its null
        status is, and that status is read only for calibration above and
        never joins this payload (feature 2).  ``null_discoveries`` is the
        same stance applied to the commit's own skip: a count of bar-clearing
        null branches passed over, never which ones.  ``dedup_skipped`` and
        ``dedup_against`` are that stance a second time -- how many
        bar-clearing nodes the dedup rule excluded and how many earlier
        picks they were checked against -- and neither is ever a node id.
        """
        return {
            "campaign_id": self.campaign_id,
            "ks_pvalue": self.ks_pvalue,
            "ks_pvalue_all_nodes": self.ks_pvalue_all_nodes,
            "ks_pvalue_root_nonsig": self.ks_pvalue_root_nonsig,
            "ks_variant": self.ks_variant,
            "ks_root_counts": list(self.ks_root_counts),
            "gate_a_p": self.gate_a_p,
            "gate_b_p": self.gate_b_p,
            "null_tstat_mean": self.null_tstat_mean,
            "null_tstat_sd": self.null_tstat_sd,
            "calibration_status": self.calibration_status,
            "sensitivity": self.sensitivity,
            "specificity": self.specificity,
            "fdr_deploy": self.fdr_deploy,
            "type_b": self.type_b,
            "selection_rule": self.selection_rule,
            "discoveries_ic": self.discoveries_ic,
            "discoveries": self.discoveries,
            "null_discoveries": self.null_discoveries,
            "dedup_skipped": self.dedup_skipped,
            "dedup_against": self.dedup_against,
            "budget_charging_trials": self.budget_charging_trials,
            "ledger_trials": self.ledger_trials,
            "triage_auc": self.triage_auc,
            "triage_null_count": self.triage_null_count,
            "triage_real_count": self.triage_real_count,
            "committed_pick": self.committed_pick,
            "oos_ir": self.oos_ir,
            "oos_ic_tstat": self.oos_ic_tstat,
            "world_persisted": self.world_persisted,
        }


@dataclass(frozen=True)
class _EvaluatedNode:
    """One evaluated node's in-sample reading -- the bit this module reads
    the sidecar for, and the score the KS guard and the discovery bar read.

    ``perturb_stability`` is the lookback-jitter tripwire's own figure
    (:mod:`orchestrator._tripwire_step`), written onto the node row by that
    step and read here as ``None`` when that one probe never measured --
    "not measured" is excluded from the triage AUC's sample, never treated
    as a reading of zero stability.

    ``ir_tstat`` is the post-cost IR t-statistic :mod:`orchestrator._evaluate`
    writes beside ``ic_tstat`` (additions_spec_cost_aware_selection.xml
    feature 1) -- ``None`` for a node a pre-feature-1 tree writer evaluated,
    read here as the signal to fall back to :data:`SELECTION_RULE_IC_
    FALLBACK` for that node (:func:`_is_discovery`, :func:`_selection_value`).

    ``turnover`` is feature 101's seventh metric column, read here for
    additions_spec_dedup_committed_constructs.xml's fingerprint
    (:func:`_construct_fingerprint`, :func:`_earlier_committed_fingerprints`)
    -- ``None`` when the column is absent or NULL, which the fingerprint
    reads as "never matches" rather than as a zero-turnover construct.  It
    rides on this record rather than a second read so one campaign's own
    fingerprint costs no extra query.
    """

    node_id: str
    ic_mean: float
    ic_tstat: float
    perturb_stability: float | None
    ir_tstat: float | None
    #: The node's stored turnover, or ``None`` when the column is missing or
    #: NULL.  Defaulted, unlike the five above, only so a caller that
    #: constructs one of these to drive :func:`_commit_top_node` (the
    #: incumbent-equivalence ground truth, a test) need not name a field it
    #: does not use.
    turnover: float | None = None


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The same translation every store in this workspace restates rather
    than imports, so this module states its own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CloseoutError(
            f"{CLOSEOUT_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: closeout speaks sqlite:/// (the spec's "
            "single-machine allowance)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise CloseoutError(
            f"{CLOSEOUT_CODE}: {DATABASE_URL_ENV} carries no database path"
        )
    return Path(path)


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        row[1] == column
        for row in connection.execute(f"PRAGMA table_info({table})")
    )


def _read_campaign_root_ids(database_url: str, campaign_id: str) -> tuple[str, ...]:
    """Every root id the tree holds under this campaign -- its planted whole.

    A root is the row whose ``parent_id`` is ``NULL`` (feature 97's own
    definition, the one :mod:`orchestrator._oracle` walks to) -- the only
    nodes the sidecar ever seals an assignment for.  This is the population
    :meth:`scoring.NullPickScorer.calibration_figures` is measured over:
    every root the campaign's planting fixed a null or real status for,
    whether or not it -- or any node of its subtree -- was ever evaluated.
    A child is never in this set; its label is its root's, found at the
    call site through :func:`_resolve_root`.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        try:
            rows = connection.execute(
                f"SELECT id FROM {NODE_TABLE} WHERE campaign_id = ? "
                "AND parent_id IS NULL",
                (campaign_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise CloseoutError(
                f"{CLOSEOUT_CODE}: could not read campaign {campaign_id!r}'s "
                f"planted roots from {database_url!r}: {exc}"
            ) from exc
    return tuple(row[0] for row in rows)


class _NoPostEndpoint:
    """Satisfies :class:`SubtreeOracle`'s endpoint contract without ever
    being posted to.

    Close-out reuses :meth:`SubtreeOracle._root_of` -- the exact
    ``parent_id`` walk the live evaluator's oracle takes from a node to its
    root -- and never calls :class:`SubtreeOracle` itself, which would post
    a target request to the null oracle's route.  This stand-in exists only
    so :class:`SubtreeOracle`'s constructor, which requires a callable
    ``post``, can be satisfied without composing a real endpoint.
    """

    def post(self, request: Any) -> Any:  # pragma: no cover - never reached
        raise AssertionError(
            f"{CLOSEOUT_CODE}: the root-resolution endpoint stand-in was "
            "posted to; close-out only walks node.parent_id to a root and "
            "never asks the null oracle's route"
        )


def _resolve_root(
    oracle: SubtreeOracle, node_id: str, *, campaign: str, roots: frozenset[str]
) -> str:
    """One evaluated node's root, found via ``oracle``'s own walk and
    checked against the campaign's own planted roots.

    Reuses :meth:`SubtreeOracle._root_of` -- the same ``parent_id`` walk
    evaluation applies -- rather than restating it.  Refuses with
    :class:`CloseoutError`, naming the node, in two cases this module adds
    on top of the oracle's own: the walk reaches a root this campaign did
    not plant (it has, in effect, left the campaign -- a corrupted
    ``parent_id`` spine being the only way there), or the oracle's own walk
    itself cannot reach a root at all (an absent row or a parent-chain
    cycle, its own :class:`~orchestrator._oracle.OracleTargetError`,
    translated into this module's vocabulary).
    """
    try:
        root_id = oracle._root_of(node_id)
    except OracleTargetError as exc:
        raise CloseoutError(
            f"{CLOSEOUT_CODE}: node {node_id!r} of campaign {campaign!r} "
            f"could not be walked to a root: {exc}"
        ) from exc
    if root_id not in roots:
        raise CloseoutError(
            f"{CLOSEOUT_CODE}: node {node_id!r} of campaign {campaign!r} "
            f"walks to root {root_id!r}, which this campaign does not "
            "plant; a node's root must be one of the campaign's own, and "
            "a walk that leaves the campaign names no root the sidecar "
            "could ever hold an assignment for"
        )
    return root_id


def _read_evaluated_nodes(
    database_url: str, campaign_id: str
) -> tuple[_EvaluatedNode, ...]:
    """The campaign's evaluated node rows -- ``fail_class`` ``ok``, metrics present.

    ``fail_class`` is added to ``node`` lazily, by :mod:`discovery.persist`'s
    own attempt log rather than a migration; a database it has never
    reached carries no such column at all, read here the same as every row
    being ``'ok'`` -- a tree with no recorded failure is one where nothing
    has failed.  A row whose metrics are not yet written (``ic_mean`` or
    ``ic_tstat`` ``NULL``) is not evaluated and is excluded, the same
    absence-is-not-a-measurement reading every store in this workspace
    takes of an unset column.

    ``ic_mean`` and ``ic_tstat`` themselves are added by a sibling migration
    (0114) rather than the one that creates the table (0118), so a store
    this process is pointed at before any evaluator has ever run against it
    -- :mod:`nullius_api.demo`'s own seed is one -- carries no such columns
    at all.  That is not "zero evaluated nodes" (an empty, readable result)
    but "nothing has been evaluated here, ever", and it is refused by name
    with :data:`CLOSEOUT_UNEVALUATED_CODE` before the column is ever named
    in a query, rather than let as a raw ``sqlite3.OperationalError`` reach
    the CLI's generic refusal printer.

    ``ir_tstat`` and ``turnover`` are probed for the same way: a tree no
    evaluation has touched since additions_spec_cost_aware_selection.xml
    feature 1 landed carries no ``ir_tstat`` column, read here as ``NULL`` on
    every row rather than refused -- the column's whole absence is feature 2's
    own documented fallback trigger, not an unevaluated tree.  ``turnover``
    is feature 101's and arrives with ``0114``; either of the two being
    absent reads ``NULL`` on every row, which is the answer
    additions_spec_dedup_committed_constructs.xml's fingerprint needs (a
    ``NULL`` field never matches).
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        if not (
            _has_column(connection, NODE_TABLE, "ic_mean")
            and _has_column(connection, NODE_TABLE, "ic_tstat")
        ):
            raise CloseoutError(
                f"{CLOSEOUT_UNEVALUATED_CODE}: campaign {campaign_id!r} has "
                f"not been evaluated -- its {NODE_TABLE} table carries no "
                "ic_mean/ic_tstat columns, so no evaluation has written "
                "metrics for it, and there is nothing to calibrate"
            )
        fail_class_column = (
            "fail_class" if _has_column(connection, NODE_TABLE, "fail_class") else "'ok'"
        )
        ir_tstat_column = (
            "ir_tstat" if _has_column(connection, NODE_TABLE, "ir_tstat") else "NULL"
        )
        turnover_column = (
            "turnover" if _has_column(connection, NODE_TABLE, "turnover") else "NULL"
        )
        query = (
            f"SELECT id, {fail_class_column}, ic_mean, ic_tstat, "
            f"perturb_stability, {ir_tstat_column}, {turnover_column} "
            f"FROM {NODE_TABLE} WHERE campaign_id = ?"
        )
        try:
            rows = connection.execute(query, (campaign_id,)).fetchall()
        except sqlite3.Error as exc:
            raise CloseoutError(
                f"{CLOSEOUT_CODE}: could not read campaign {campaign_id!r}'s "
                f"evaluated nodes from {database_url!r}: {exc}"
            ) from exc
    evaluated: list[_EvaluatedNode] = []
    for (
        node_id,
        fail_class,
        ic_mean,
        ic_tstat,
        perturb_stability,
        ir_tstat,
        turnover,
    ) in rows:
        # A NULL fail_class on a row with metrics is an evaluated node: the
        # root evaluation path writes metrics but no fail_class, and a row
        # with no recorded failure is one where nothing has failed. Dropping
        # it left campaign 90d95c6d's ten scored roots out of the KS split.
        if fail_class not in (None, "ok") or ic_mean is None or ic_tstat is None:
            continue
        evaluated.append(
            _EvaluatedNode(
                node_id=node_id,
                ic_mean=ic_mean,
                ic_tstat=ic_tstat,
                perturb_stability=perturb_stability,
                ir_tstat=ir_tstat,
                turnover=turnover,
            )
        )
    return tuple(evaluated)


def _triage_auc(
    null_stabilities: Sequence[float], real_stabilities: Sequence[float]
) -> float | None:
    """The M1 triage figure: the perturbation-stability AUC that separates
    ``real_stabilities`` from ``null_stabilities``, real as the positive
    class and a *lower* figure read as more real.

    ``node.perturb_stability`` is the lookback-jitter figure,
    ``|rerun Sharpe - reference Sharpe| / threshold``
    (:func:`tripwires.lookback.lookback_figure`). It is 0 when the jittered
    window changed nothing and grows as the node gets less stable, so it is
    an instability magnitude. The first real campaigns' AUCs (0.20 and 0.33)
    came out inverted under the original "higher reads as more real"
    orientation.

    A Mann-Whitney U over the two samples, normalized to ``[0, 1]`` by
    ``n_real * n_null`` -- the rank-sum form, so a tie between a null and a
    real reading contributes half a win to each side rather than breaking
    toward either (``ties give 0.5``, both for one tied pair and for a
    sample that is nothing but ties). ``None`` when either side holds fewer
    than :data:`TRIAGE_MIN_SIDE` nodes: with one reading on a side there is
    nothing to rank it against, and the uninformative ``0.5`` a smaller
    formula would divide its way to is not a measurement.
    """
    n_null = len(null_stabilities)
    n_real = len(real_stabilities)
    if n_null < TRIAGE_MIN_SIDE or n_real < TRIAGE_MIN_SIDE:
        return None
    # Ranked on the negated figure, so the most stable node ranks highest.
    labelled = sorted(
        [(-value, False) for value in null_stabilities]
        + [(-value, True) for value in real_stabilities]
    )
    total = len(labelled)
    rank_sum_real = 0.0
    index = 0
    while index < total:
        end = index + 1
        while end < total and labelled[end][0] == labelled[index][0]:
            end += 1
        # Ranks are 1-indexed; a tied run of [index, end) shares the average
        # of those ranks (the standard tie-handling for a rank-sum test).
        average_rank = (index + 1 + end) / 2
        for _value, is_real in labelled[index:end]:
            if is_real:
                rank_sum_real += average_rank
        index = end
    u_real = rank_sum_real - n_real * (n_real + 1) / 2
    return u_real / (n_real * n_null)


def _persist_triage(
    database_url: str,
    campaign_id: str,
    *,
    auc: float | None,
    null_count: int,
    real_count: int,
) -> None:
    """Land the M1 triage figure as one row of :data:`CLOSEOUT_TRIAGE_TABLE`,
    created if absent and refreshed (never duplicated) on a rerun.

    Only the three figures a close-out computed -- never a node id, never a
    label -- land here, the same stance :meth:`CloseoutResult.to_payload`
    takes for the printed line.
    """
    path = _sqlite_path(database_url)
    try:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {CLOSEOUT_TRIAGE_TABLE} ("
                "campaign_id TEXT PRIMARY KEY, "
                "auc REAL, "
                "null_count INTEGER NOT NULL, "
                "real_count INTEGER NOT NULL, "
                "computed_at TEXT NOT NULL"
                ")"
            )
            connection.execute(
                f"INSERT INTO {CLOSEOUT_TRIAGE_TABLE} "
                "(campaign_id, auc, null_count, real_count, computed_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(campaign_id) DO UPDATE SET "
                "auc = excluded.auc, "
                "null_count = excluded.null_count, "
                "real_count = excluded.real_count, "
                "computed_at = excluded.computed_at",
                (
                    campaign_id,
                    auc,
                    null_count,
                    real_count,
                    dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                ),
            )
    except sqlite3.Error as exc:
        raise CloseoutError(
            f"{CLOSEOUT_CODE}: could not persist campaign {campaign_id!r}'s "
            f"triage figure into {database_url!r}: {exc}"
        ) from exc


# -- Gate A: does the campaign's own null sample still look like N(0,1)? -----
#
# nulloracle's ks module carries no one-sample test (its own two-sample
# ``ks_two_sample`` is the only estimator it offers -- see the module
# docstring's "Gate A and Gate B" section for why this bug fix does not add
# one there), so the statistic and its asymptotic p-value are restated here,
# mirroring the shape nulloracle.ks itself already documents for its own
# two-sample series rather than inventing a different numerical recipe.

#: sqrt(2), used once per CDF evaluation; named rather than recomputed so the
#: one spelling is unmistakably the same constant everywhere it appears.
_SQRT_TWO = math.sqrt(2.0)


def _standard_normal_cdf(x: float) -> float:
    """Phi(x) -- the standard normal CDF, forward only, never inverted.

    ``math.erf`` is the one libm call Gate A needs; nulloracle's own
    asymptotic two-sample branch already accepts the same platform-dependent
    -but-documented trade for ``math.exp``, and there is no exact,
    libm-free estimator available here the way there is for two empirical
    samples (nulloracle.ks's lattice count has no one-sample counterpart).
    """
    return 0.5 * (1.0 + math.erf(x / _SQRT_TWO))


def _one_sample_ks_statistic(ordered: Sequence[float]) -> float:
    """The one-sample two-sided KS statistic ``D`` of ``ordered`` against
    N(0,1).  ``ordered`` must already be sorted ascending.

    The textbook definition, mirroring the two-sided, tie-stepped shape
    nulloracle.ks states for its own two-sample statistic: ``D+`` is the
    largest amount the empirical CDF leads Phi by, ``D-`` the largest amount
    it trails, and ``D`` is the larger of the two.
    """
    n = len(ordered)
    d_plus = max(i / n - _standard_normal_cdf(x) for i, x in enumerate(ordered, start=1))
    d_minus = max(_standard_normal_cdf(x) - (i - 1) / n for i, x in enumerate(ordered, start=1))
    return max(d_plus, d_minus)


def _kolmogorov_q(lam: float) -> float:
    """``Q(lambda)``, the Kolmogorov distribution.

    Restated term for term from the same published series (Numerical
    Recipes' ``probks``) nulloracle.ks's own, private ``_kolmogorov_series``
    mirrors for its two-sample asymptotic branch -- that function is not
    exported (nulloracle's two-sample test has no one-sample counterpart to
    call it from), so this is this module's own copy, kept in step with the
    published algorithm rather than a "cleaner" rearrangement, for the same
    reason nulloracle.ks gives: a stored p-value's last digits should not
    drift with how the series is written.
    """
    if lam <= 0.0:
        return 1.0
    a2 = -2.0 * lam * lam
    factor = 2.0
    total = 0.0
    previous = 0.0
    for j in range(1, KS_SERIES_TERMS + 1):
        term = factor * math.exp(a2 * j * j)
        total += term
        if abs(term) <= _KS_SERIES_EPS1 * previous or abs(term) <= _KS_SERIES_EPS2 * total:
            return min(1.0, max(0.0, total))
        factor = -factor
        previous = abs(term)
    return 1.0


#: Numerical Recipes' own cap on the Kolmogorov series' term count -- the
#: same figure nulloracle.ks pins for its own copy of this series.
KS_SERIES_TERMS = 100

#: The series' two convergence tolerances -- nulloracle.ks's own ``EPS1``
#: and ``EPS2``, restated so this copy converges on the same term nulloracle's
#: two-sample asymptotic branch would.
_KS_SERIES_EPS1 = 1e-6
_KS_SERIES_EPS2 = 1e-16


def _one_sample_ks_against_standard_normal(values: Sequence[float]) -> tuple[float, float]:
    """Gate A's test: the ``(statistic, pvalue)`` of a one-sample two-sided
    KS test of ``values`` against N(0,1).

    The asymptotic Kolmogorov approximation, with the small-sample
    correction Stephens (1970) publishes for the one-sample case --
    ``lambda = (sqrt(n) + 0.12 + 0.11/sqrt(n)) * D`` in place of the raw
    ``sqrt(n)*D`` the large-``n`` limit alone would use -- because Gate A's
    own floor (:data:`GATE_A_MIN_NULL_COUNT`) admits samples far smaller than
    an uncorrected asymptotic series is accurate for.
    """
    ordered = sorted(values)
    n = len(ordered)
    d = _one_sample_ks_statistic(ordered)
    lam = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
    return d, _kolmogorov_q(lam)


def _gate_a(null_values: Sequence[float]) -> tuple[str, float | None, float | None]:
    """Gate A: one-sample KS test of ``null_values`` (one ``ic_tstat`` per
    null root for Type-R, per branch's shallowest null node for Type-D)
    against N(0,1) -- see "Gate A and Gate B" in the module docstring.

    Returns ``(status, pvalue, statistic)``.  ``status`` is
    :data:`CALIBRATION_STATUS_INSUFFICIENT` below :data:`GATE_A_MIN_NULL_
    COUNT`, :data:`nulloracle.CALIBRATION_STATUS_VOID` at
    ``pvalue < nulloracle.VOID_THRESHOLD`` and :data:`nulloracle.
    CALIBRATION_STATUS_OK` otherwise -- Gate A's own level is deliberately
    the same 0.05 the previous, removed gate voided on (PRD §7.4's own
    figure), because what changed is the *comparison*, not the bar a
    detectable null must clear.
    """
    if len(null_values) < GATE_A_MIN_NULL_COUNT:
        return CALIBRATION_STATUS_INSUFFICIENT, None, None
    statistic, pvalue = _one_sample_ks_against_standard_normal(null_values)
    status = (
        nulloracle.CALIBRATION_STATUS_VOID
        if pvalue < nulloracle.VOID_THRESHOLD
        else nulloracle.CALIBRATION_STATUS_OK
    )
    return status, pvalue, statistic


# -- Gate B: does the agent's own behaviour predict a root's null status? ----


def _fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """The two-sided Fisher exact p-value of the 2x2 table ``[[a, b], [c, d]]``.

    Exact over the hypergeometric distribution the table's fixed margins
    imply: sums the probability of every table at least as extreme as the
    observed one -- the standard definition of a two-sided exact test --
    using ``math.comb`` the same way nulloracle.ks's own exact two-sample
    branch uses arbitrary-precision integers, so the only floating-point
    operations are the final ratios.
    """
    n_null = a + b
    n_real = c + d
    total = n_null + n_real
    k = a + c
    total_ways = math.comb(total, k)

    def _probability(x: int) -> float:
        return (math.comb(n_null, x) * math.comb(n_real, k - x)) / total_ways

    low = max(0, k - n_real)
    high = min(n_null, k)
    probabilities = {x: _probability(x) for x in range(low, high + 1)}
    observed = probabilities[a]
    # A relative tolerance keeps the observed table counted as "at least as
    # extreme as itself" despite floating-point rounding of the ratio.
    cutoff = observed * (1 + 1e-9)
    return min(1.0, sum(p for p in probabilities.values() if p <= cutoff))


def _gate_b(
    root_labels: Mapping[str, bool], expanded_roots: frozenset[str]
) -> tuple[str, float | None]:
    """Gate B: whether a root's sidecar label predicts whether the policy
    ever selected it for expansion -- a two-sided Fisher exact test over the
    2x2 table of (null, real) x (expanded at least once, never expanded).

    ``root_labels`` maps every planted root this campaign's sidecar holds an
    entry for to its ``is_null`` bit (not only an evaluated root's -- a root
    nobody ever expanded still answers "never expanded", which is exactly
    the fact this gate reads).  ``expanded_roots`` is the set of roots whose
    subtree carries at least one other node (see
    :func:`_read_campaign_node_parents`).

    Returns ``(status, pvalue)``.  ``status`` is :data:`CALIBRATION_STATUS_
    INSUFFICIENT` when either label class is empty or no root was ever
    expanded -- the spec's own "insufficient when no root was expanded",
    widened to the symmetric case of no null (or no real) root to compare at
    all -- :data:`nulloracle.CALIBRATION_STATUS_VOID` at
    ``pvalue < GATE_B_VOID_THRESHOLD`` and :data:`nulloracle.
    CALIBRATION_STATUS_OK` otherwise.
    """
    expanded_null = not_expanded_null = expanded_real = not_expanded_real = 0
    for root_id, is_null in root_labels.items():
        expanded = root_id in expanded_roots
        if is_null:
            if expanded:
                expanded_null += 1
            else:
                not_expanded_null += 1
        elif expanded:
            expanded_real += 1
        else:
            not_expanded_real += 1
    n_null = expanded_null + not_expanded_null
    n_real = expanded_real + not_expanded_real
    if n_null == 0 or n_real == 0 or (expanded_null + expanded_real) == 0:
        return CALIBRATION_STATUS_INSUFFICIENT, None
    pvalue = _fisher_exact_two_sided(
        expanded_null, not_expanded_null, expanded_real, not_expanded_real
    )
    status = (
        nulloracle.CALIBRATION_STATUS_VOID
        if pvalue < GATE_B_VOID_THRESHOLD
        else nulloracle.CALIBRATION_STATUS_OK
    )
    return status, pvalue


def _read_campaign_node_parents(
    database_url: str, campaign_id: str
) -> tuple[tuple[str, str | None], ...]:
    """Every node id and its ``parent_id`` for the campaign -- root and
    child alike, evaluated or not.

    Gate B's "was a root ever selected for expansion" reads every attempted
    expansion that left a row, not only a scored one: a sandbox failure or a
    tripwire halt still persists its child
    (:class:`discovery.persist.AttemptLog`'s own law -- see the module
    docstring's note on why this module reads ``node`` by raw SQL), and
    excluding those rows would undercount a root the policy genuinely
    selected but whose attempt never finished.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        try:
            rows = connection.execute(
                f"SELECT id, parent_id FROM {NODE_TABLE} WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise CloseoutError(
                f"{CLOSEOUT_CODE}: could not read campaign {campaign_id!r}'s "
                f"node parentage from {database_url!r}: {exc}"
            ) from exc
    return tuple((row[0], row[1]) for row in rows)


def _force_void(database_url: str, campaign_id: str) -> None:
    """Set ``calibration_status`` to VOID directly, idempotently, and
    stickily -- never clearing an existing VOID.

    Gate B's own voiding path: :class:`nulloracle.CampaignVerdict` only ever
    compares ``campaign.ks_pvalue`` (the diagnostic this bug fix demotes,
    :attr:`CloseoutResult.ks_pvalue_root_nonsig`) against its own 0.05, so a
    campaign Gate B alone rejects -- at a different threshold, over a
    different statistic -- cannot be voided through that seam.  This is the
    same ``UPDATE ... WHERE calibration_status != 'VOID'`` sticky shape
    :mod:`nulloracle.verdict` itself states for the same reason: once
    measured detectable, a campaign only ever moves toward VOID, never away
    from it.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            f"UPDATE {nulloracle.CAMPAIGN_TABLE} SET calibration_status = ? "
            "WHERE id = ? AND calibration_status != ?",
            (
                nulloracle.CALIBRATION_STATUS_VOID,
                campaign_id,
                nulloracle.CALIBRATION_STATUS_VOID,
            ),
        )


# -- The dedup: a construct an earlier campaign already committed --


#: How close two fingerprint fields must be to name one construct --
#: additions_spec_dedup_committed_constructs.xml's own ``1e-9``.  Absolute,
#: so it means the same thing whatever magnitude the figure it compares
#: carries.
DEDUP_FINGERPRINT_TOL = 1e-9


def _construct_fingerprint(
    ic_mean: float | None,
    ic_tstat: float | None,
    ir_tstat: float | None,
    turnover: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """A construct's in-sample fingerprint -- the four stored figures a
    committed pick is identified by (additions_spec_dedup_committed_
    constructs.xml).

    The four columns are the ones the RESULT's own finding is stated in:
    ``docs/preregistration/2026-10-21-m2-short-h5.RESULT.md`` records
    campaigns 4 and 8 committing roots with *"bit-identical statistics (IC t
    2.0558, IR t 3.5953, out-of-sample -12.93 bp) under different code
    hashes: two agents wrote the same function in different source text"* --
    so a *code* hash cannot see the duplicate and a statistics tuple can.
    ``turnover`` joins them because it is the figure that separates two
    constructions agreeing on their ranking metric but trading different
    names -- the fingerprint is the construct, not the metric alone.

    The tuple is a value, never compared here: :func:`_fingerprints_match`
    owns the comparison, including the tolerance, so one call site could not
    drift from another on what "the same construct" means.  A ``None`` field
    is carried through rather than refused: it is the honest reading of a
    column the tree never wrote (a pre-feature-1 ``ir_tstat``, a node
    migrated before ``0114``), and :func:`_fingerprints_match` turns any such
    field into "never matches", which is the rule the spec states.
    """
    return (ic_mean, ic_tstat, ir_tstat, turnover)


def _fingerprints_match(
    left: Sequence[float | None],
    right: Sequence[float | None],
    *,
    tol: float = DEDUP_FINGERPRINT_TOL,
) -> bool:
    """Whether two fingerprints name the same construct.

    ``False`` when *any* field of either side is ``None``: a fingerprint
    missing a term identifies no construct this campaign could be a repeat
    of, and reading a missing ``ir_tstat`` as agreement would merge every
    pre-feature-1 pick with every other.  Otherwise every field must agree
    within ``tol`` — additions_spec_dedup_committed_constructs.xml's own
    ``1e-9``, loose enough to absorb the last-bit drift two runs of the same
    arithmetic can show on one platform (the four-decimal agreement the
    RESULT quotes is 1e-4), tight enough that the next distinct construct
    the search finds — which differs in the third decimal at worst — is never
    swallowed by it.
    """
    for a, b in zip(left, right, strict=False):
        if a is None or b is None:
            return False
        if not math.isclose(a, b, rel_tol=0.0, abs_tol=tol):
            return False
    return len(left) == len(right)


def _earlier_committed_fingerprints(
    database_url: str, campaign_id: str
) -> list[tuple[float | None, ...]]:
    """Every construct an *earlier* campaign under this campaign's own
    evaluation config hash already committed as its ``m2-fixed`` row.

    The read walks the store the way the feature's sentence does, in three
    steps:

    1. **This campaign's own grid identity.**  ``campaign.evaluation_config_
       sha256`` and ``campaign.created_at`` are read off this campaign's row.
       A row with no sha256 (every campaign written before
       ``0120_campaign_evaluation_grid.py``, and any the backfill could not
       place) answers an empty list: *same evaluation config hash* names no
       set, so there is nothing this campaign could be a duplicate of.  The
       same absence-as-not-applicable reading :func:`_read_evaluated_nodes`
       takes of an absent column.
    2. **The peer campaigns.**  Every other campaign row carrying the same
       sha256 and a **strictly earlier** ``created_at``.  Strictly, so a
       campaign can never be its own peer — a rerun of one close-out refreshes
       its own row rather than tripping over it, and two campaigns created in
       the same second do not silently dedup against each other.  The
       comparison is on the stored text, which is ISO-8601 UTC in both
       dialects (``0111``'s own note) and therefore orders correctly as
       text.
    3. **Their committed picks.**  Every ``replay_score`` row under
       :data:`M2_FIXED_POLICY_VERSION` whose ``world_id`` is one of those
       campaigns and whose ``committed_pick`` is not NULL — a miss committed
       nothing, so it fingerprints nothing — with the pick's four figures
       read off the ``node`` table.

    ``ir_tstat`` and ``turnover`` are read through the same
    :func:`_has_column` probe :func:`_read_evaluated_nodes` uses, so a
    database whose chain has not reached them answers ``None`` for every
    row rather than raising ``no such column``: a pick with an absent field
    never matches (:func:`_fingerprints_match`), which is the feature's own
    rule for a NULL.

    Read-only and idempotent: a campaign whose config did not set
    :data:`orchestrator._context.DEDUP_COMMITTED_KEY` never calls this at
    all, and a call writes nothing.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        try:
            own = connection.execute(
                f"SELECT {discovery.EVALUATION_CONFIG_SHA256_COLUMN}, "
                f"{discovery.CREATED_AT_COLUMN} FROM "
                f"{discovery.CAMPAIGN_TABLE} WHERE {discovery.ID_COLUMN} = ?",
                (campaign_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            # A chain that has not reached 0120 carries no such column, and
            # a database the campaign table itself is missing has no peers
            # to compare at all -- both are "no grid identity recorded",
            # never a broken store this read should refuse on.
            return []
        if own is None or own[0] is None or own[1] is None:
            return []
        config_sha256, created_at = own[0], own[1]

        try:
            peers = connection.execute(
                f"SELECT {discovery.ID_COLUMN} FROM "
                f"{discovery.CAMPAIGN_TABLE} WHERE "
                f"{discovery.EVALUATION_CONFIG_SHA256_COLUMN} = ? "
                f"AND {discovery.CREATED_AT_COLUMN} < ? "
                f"AND {discovery.ID_COLUMN} != ?",
                (config_sha256, created_at, campaign_id),
            ).fetchall()
        except sqlite3.Error as exc:
            raise CloseoutError(
                f"{CLOSEOUT_CODE}: could not read the campaigns sharing "
                f"campaign {campaign_id!r}'s evaluation config hash from "
                f"{database_url!r}: {exc}"
            ) from exc
        if not peers:
            return []

        # The picks those campaigns committed.  A store with no
        # replay_score table yet holds no earlier commit, the same
        # absence-is-nothing reading :func:`_m2_fixed_is_holdout` takes.
        picks: list[str] = []
        for (peer_id,) in peers:
            try:
                rows = connection.execute(
                    f"SELECT committed_pick FROM {replay.REPLAY_SCORE_TABLE} "
                    "WHERE policy_version = ? AND world_id = ? "
                    "AND committed_pick IS NOT NULL",
                    (M2_FIXED_POLICY_VERSION, peer_id),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            picks.extend(row[0] for row in rows)
        if not picks:
            return []

        ir_tstat_column = (
            "ir_tstat" if _has_column(connection, NODE_TABLE, "ir_tstat") else "NULL"
        )
        turnover_column = (
            "turnover" if _has_column(connection, NODE_TABLE, "turnover") else "NULL"
        )
        fingerprints: list[tuple[float | None, ...]] = []
        for node_id in picks:
            row = connection.execute(
                f"SELECT ic_mean, ic_tstat, {ir_tstat_column}, "
                f"{turnover_column} FROM {NODE_TABLE} WHERE id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                # A pick whose node row is gone names no construct to
                # compare against; skipped rather than refused, because the
                # only way there is a store something else has edited.
                continue
            fingerprints.append(_construct_fingerprint(*row))
    return fingerprints


# -- The commit: policy-runtime's EpisodeCommit, over this module's own tree --


def _is_discovery(node: _EvaluatedNode) -> bool:
    """additions_spec_cost_aware_selection.xml feature 2's discovery rule.

    ``ir_tstat >= DISCOVERY_TSTAT and ic_tstat > 0`` for a node that carries
    ``ir_tstat``; :data:`SELECTION_RULE_IC_FALLBACK`'s plain ``ic_tstat >=
    DISCOVERY_TSTAT`` for one that does not (a tree a pre-feature-1
    evaluator wrote).  ``DISCOVERY_TSTAT`` is positive, so the fallback
    needs no separate sign test to match the primary rule's ``> 0`` leg.
    """
    if node.ir_tstat is not None:
        return node.ir_tstat >= DISCOVERY_TSTAT and node.ic_tstat > 0
    return node.ic_tstat >= DISCOVERY_TSTAT


def _selection_value(node: _EvaluatedNode) -> float:
    """The figure the commit ranks an eligible node by -- ``ir_tstat`` where
    the node carries one, ``ic_tstat`` under the fallback rule."""
    return node.ir_tstat if node.ir_tstat is not None else node.ic_tstat


def _dedup_excluded_nodes(
    evaluated: Sequence[_EvaluatedNode],
    earlier: Sequence[Sequence[float | None]],
    *,
    null_nodes: frozenset[str],
) -> frozenset[str]:
    """The evaluated nodes the dedup rule excludes from the commit --
    additions_spec_dedup_committed_constructs.xml.

    A node is excluded when it **clears the discovery bar** (the same
    :func:`_is_discovery` the commit's own eligible set reads -- a node that
    would never have been committed cannot be a duplicate of one that was),
    is **not a null branch** (that exclusion is the null rule's,
    :func:`_commit_top_node`'s ``null_nodes``, and counting a node twice
    would overstate ``dedup_skipped``), and its **stored fingerprint matches
    one an earlier campaign already committed** (:func:`_fingerprints_match`,
    over :func:`_construct_fingerprint` of its own four stored figures --
    stored, never recomputed, so a node the tree measured with an older
    evaluator is compared on the figures the commit ranked it by).

    Empty when ``earlier`` is empty, so a campaign with no peers reads
    nothing further and its exclusion set is exactly the null one.
    """
    if not earlier:
        return frozenset()
    excluded: set[str] = set()
    for node in evaluated:
        if node.node_id in null_nodes or not _is_discovery(node):
            continue
        fingerprint = _construct_fingerprint(
            node.ic_mean, node.ic_tstat, node.ir_tstat, node.turnover
        )
        if any(_fingerprints_match(fingerprint, seen) for seen in earlier):
            excluded.add(node.node_id)
    return frozenset(excluded)


class _ClosingTree:
    """The address seam :class:`policy_runtime.EpisodeCommit` needs -- the
    campaign's evaluated node ids, and nothing posted.

    Close-out already knows every node id it may commit to (the ``evaluated``
    rows its own read produced); this is the minimal carrier that lets
    :func:`policy_runtime.episode_commit` validate the one commit through the
    same seam a live episode's question does, rather than restating the
    cardinality and one-way-door checks :mod:`policy_runtime.commit` already
    owns.  The same stand-in-over-a-known-set shape as :class:`_NoPostEndpoint`
    above, for the sibling reason: nothing here is ever posted to.
    """

    def __init__(self, node_ids: frozenset[str]) -> None:
        self._node_ids = node_ids

    def node(self, node_id: str) -> str:
        if node_id not in self._node_ids:
            raise policy_runtime.PolicyAddressError(
                f"{CLOSEOUT_CODE}: close-out tried to commit to node "
                f"{node_id!r}, which is not one of this campaign's evaluated "
                "nodes"
            )
        return node_id


class _ClosingQuestion:
    """Fronts :class:`_ClosingTree` as the ``question`` :class:`policy_runtime.
    EpisodeCommit` requires -- a public ``tree`` carrying a callable
    ``node()``, the whole of that record's address-seam demand."""

    def __init__(self, node_ids: frozenset[str]) -> None:
        self.tree = _ClosingTree(node_ids)


def _commit_top_node(
    evaluated: Sequence[_EvaluatedNode],
    *,
    null_nodes: frozenset[str] = frozenset(),
) -> policy_runtime.Termination:
    """Commit to the eligible evaluated node with the highest ``ir_tstat``
    (additions_spec_cost_aware_selection.xml feature 2's commit rule --
    ``ic_tstat`` under :data:`SELECTION_RULE_IC_FALLBACK` for a node with no
    ``ir_tstat``, :func:`_is_discovery` and :func:`_selection_value`), run
    through :func:`policy_runtime.episode_commit` so the one-way-door and
    one-node cardinality it already enforces are not restated here.

    ``null_nodes`` names the evaluated nodes whose root the sidecar labels
    null -- the per-node labels :func:`close_out`'s own KS-split loop already
    resolved in the same run -- and the commit skips them even when they
    cleared the discovery bar: a null branch's score was read on the
    permuted branch, so committing one writes the campaign's m2-fixed
    replay row on a branch constructed to carry no edge (campaigns 46db5446
    and 6717ee2b committed exactly such nodes).  A campaign whose only
    bar-clearing nodes are null abstains exactly as a campaign with no
    bar-clearing node does.  Only the eligible set shrinks -- the
    :class:`_ClosingQuestion` seam still carries every evaluated node id,
    so :func:`policy_runtime.episode_commit` validates the commit over the
    same addresses it always did.  The default (no labels handed over)
    skips nothing and ranks every bar-clearing node, the rule as it stood
    before this fix -- the shape a caller with no sidecar labels of its own
    (the incumbent-equivalence ground truth) still asks for.

    ``null_nodes`` also carries the *dedup* exclusion when the evaluation
    config set :data:`orchestrator._context.DEDUP_COMMITTED_KEY`
    (additions_spec_dedup_committed_constructs.xml, and
    :func:`_dedup_excluded_nodes`, which computes that half): the two
    exclusions ride in through one parameter because they are one thing to
    this function -- evaluations the commit must not spend its one pick on --
    and keeping the signature and the ranking untouched is what lets the
    pre-flag behaviour stay provably identical.  The dedup half exists
    because ``docs/preregistration/2026-10-21-m2-short-h5.RESULT.md`` records
    ten campaigns under one evaluation config committing the same
    persistent-high-funding construct: mean pairwise correlation 0.91, N_eff
    1.09, and campaigns 4 and 8 committing roots with bit-identical
    statistics (IC t 2.0558, IR t 3.5953) under different code hashes, because
    two agents wrote the same function in different source text.  A series of
    ten campaigns therefore sampled one book ten times; with the flag set,
    the later campaigns skip a construct an earlier one already committed and
    the series' verdict measures a space rather than a point.  This function
    never reads the store itself: the caller resolves the earlier
    fingerprints and hands the excluded ids over, so the commit stays a pure
    ranking over records.

    Ties are broken by node id, ascending: a deterministic total order over
    ``(-_selection_value(node), node_id)`` picks the same winner on every
    call over the same rows, which a direct ``max()`` without a tie-break key
    would not guarantee.  With no eligible node (every node below its own
    rule's bar, every bar-clearing node a skipped null branch, or no
    evaluated node at all), nothing is committed and the returned
    :class:`~policy_runtime.Termination` carries no pick -- the campaign is
    a miss, scored :data:`policy_runtime.NON_COMMITTING_SCORE` by the caller
    that reads it, never refused.
    """
    record = policy_runtime.episode_commit(
        _ClosingQuestion(frozenset(node.node_id for node in evaluated))
    )
    eligible = [
        node
        for node in evaluated
        if _is_discovery(node) and node.node_id not in null_nodes
    ]
    if eligible:
        winner = min(eligible, key=lambda node: (-_selection_value(node), node.node_id))
        record.commit(winner.node_id)
    return record.terminate()


# -- The out-of-sample read: the committed node's stored code, over oos_dates --


def _oos_target_endpoint(sidecar: Any, context: EvaluationContext) -> Any:
    """A real :class:`nulloracle.TargetEndpoint` over ``sidecar``, serving
    forward returns narrowed to ``context.oos_dates`` -- the OOS grid's own
    echo of :func:`orchestrator._sidecar_backed_endpoint`'s production
    wiring (which narrows to ``context.evaluation_dates`` instead).

    The same reconciliation that production endpoint makes: the snapshot's
    own close-to-close forward returns (:func:`orchestrator._targets.
    snapshot_forward_returns`), narrowed to the one grid this read is over
    (feature 1's own note on why an unnarrowed supply fails a sparse grid's
    gate -- ``orchestrator._targets.grid_forward_returns``'s docstring), and
    nulloracle's own per-symbol block permutation
    (:func:`nulloracle.blockpermute.block_permute_cross_section`) for the
    null branch, read from the sidecar's own sealed seed and block length.
    Built fresh per call -- cheap, and it holds no state of its own, the
    same stance :class:`nulloracle.TargetEndpoint` itself takes.
    """
    from nulloracle.blockpermute import block_permute_cross_section

    grid = frozenset(context.oos_dates)
    base = snapshot_forward_returns(context)

    def _targets(request: Any) -> dict[Any, dict[str, float]]:
        return {day: row for day, row in base(request).items() if day in grid}

    def _permute(series: Any, *, seed: Any, block_days: Any) -> dict[Any, Any]:
        return block_permute_cross_section(series, seed=seed, block_days=block_days)

    return nulloracle.TargetEndpoint(sidecar, targets=_targets, permute=_permute)


def _oos_reading(
    node_id: str,
    *,
    campaign_id: str,
    database_url: str,
    sidecar: Any,
    context: EvaluationContext,
) -> tuple[float, float]:
    """The committed node's OOS cost-adjusted IR and OOS ``ic_tstat``.

    Reads the node's stored ``code.py`` artifact back
    (:meth:`artifacts.ArtifactStore.read`, the same file
    :mod:`orchestrator._evaluate`'s in-sample write produced) and runs it
    through :func:`orchestrator._evaluate.evaluate_on_dates` over
    ``context.oos_dates``, gated through a real oracle over this campaign's
    own sealed sidecar -- so a planted-null commit is measured on its
    permuted branch out of sample exactly as it was in sample.  Every
    failure the read or the chain raises (an artifact the node never wrote,
    a sandbox failure, a gate refusal) propagates unchanged: this function
    charges nothing and persists nothing, so there is no failure path of
    its own to translate.
    """
    code = ArtifactStore(context.artifact_dir).read(campaign_id, node_id, "code.py")
    oracle = SubtreeOracle(
        _oos_target_endpoint(sidecar, context), database_url=database_url
    )
    metrics, cost_adjusted_ir = evaluate_on_dates(
        node_id,
        code.decode("utf-8"),
        context=context,
        oracle=oracle,
        dates=context.oos_dates,
    )
    return cost_adjusted_ir, metrics.ic_tstat


# -- The world: one m2-fixed replay_score row per campaign, refreshed on rerun --


def _m2_fixed_is_holdout(database_url: str, world_id: str) -> bool:
    """The campaign's rotation, if one exists -- ``True`` otherwise.

    "The campaign's rotation" is whatever ``is_holdout`` this world's own
    most recent ``m2-fixed`` row already carried -- close-out's own prior
    write, or (additions_spec_m2_baseline_financial_worlds.xml feature 3,
    out of this module's scope) a dreaming cycle's baseline sweep scoring
    this same financial world under the same policy version.  Read before
    that row is refreshed, so a rerun does not quietly flip a world between
    train and holdout on every close-out. ``True`` when no such row exists
    yet: an unrotated financial world defaults to held out, the same
    conservative reading an un-dreamt bootstrap world gets before its first
    rotation.

    A database that has never persisted a replay score at all (``replay_
    score`` does not exist yet) answers ``True`` the same way -- there is no
    prior rotation to read, not a broken store.
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        try:
            row = connection.execute(
                f"SELECT is_holdout FROM {replay.REPLAY_SCORE_TABLE} "
                "WHERE policy_version = ? AND world_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (M2_FIXED_POLICY_VERSION, world_id),
            ).fetchone()
        except sqlite3.OperationalError:
            return True
    return True if row is None else bool(row[0])


def _clear_m2_fixed_rows(database_url: str, world_id: str) -> None:
    """Delete every existing ``m2-fixed`` row for ``world_id``, so the fresh
    row :func:`replay.persist_replay_score` is about to write is the only
    one -- the "rerunning close-out refreshes that row and never duplicates
    it" rule, enforced here because :func:`replay.persist_replay_score`'s
    own law is one fresh row per call, never an upsert (feature 255's own
    docstring: "each run is its own row").
    """
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        try:
            connection.execute(
                f"DELETE FROM {replay.REPLAY_SCORE_TABLE} "
                "WHERE policy_version = ? AND world_id = ?",
                (M2_FIXED_POLICY_VERSION, world_id),
            )
        except sqlite3.OperationalError:
            pass


def close_out(
    campaign_id: str,
    *,
    database_url: str,
    scorer: scoring.NullPickScorer,
    sidecar: Any,
    context: EvaluationContext | None = None,
) -> CloseoutResult:
    """Close out one campaign -- feature 13's whole sentence, one call.

    ``scorer`` is the resolved :class:`scoring.NullPickScorer` (feature
    265's process); ``sidecar`` is the resolved :class:`nulloracle.
    NullSidecar` the same deployment names -- held separately because the
    scorer's own law lets no label or sidecar accessor out, and the split
    this function runs for the KS guard is this process's own read, not
    the scorer's verb.

    ``context`` is the resolved :class:`~orchestrator._context.
    EvaluationContext` (:func:`~orchestrator._context.load_evaluation_context`'s
    answer, or ``None`` when unconfigured) -- additions_spec_m2_baseline_
    financial_worlds.xml, "Out-of-Sample Evaluation", feature 2's own input:
    when it is not ``None`` and its ``oos_dates`` is not empty, the node
    this call commits to is scored out of sample through it; otherwise the
    OOS reading is unavailable (``None``) and the world is still persisted,
    scored by the miss rule.

    ``context.dedup_committed_constructs`` is additions_spec_dedup_
    committed_constructs.xml's switch: when it is set, the node step 9
    commits to is chosen after excluding every bar-clearing real node whose
    stored in-sample fingerprint an earlier campaign under the same
    ``evaluation_config_sha256`` already committed, and the two counts are
    reported as ``dedup_skipped`` and ``dedup_against``.  With the flag unset
    -- and for every caller that hands no context at all -- the commit ranks
    exactly the nodes it always did and both counts are ``0``.

    Refuses with :class:`CloseoutError` for an unknown campaign or an
    evaluated node whose root cannot be resolved -- its walk leaves the
    campaign, cycles, or ends at a root the sidecar holds no entry for;
    propagates every collaborator's own refusal unwrapped (an unreadable
    sidecar, a one-sided plant with no real or no null node, a broken
    store) -- each already opens with its own greppable code word.
    """
    record = discovery.CampaignRecords(database_url).get(campaign_id)
    if record is None:
        raise CloseoutError(
            f"{CLOSEOUT_CODE}: campaign {campaign_id!r} is not recorded; "
            "close-out reads a campaign its planner already created, and "
            "an unknown id names no campaign to close out"
        )
    campaign = record.campaign_id
    is_type_d = record.campaign_type == discovery.TYPE_D_CAMPAIGN_TYPE

    root_ids = _read_campaign_root_ids(database_url, campaign)
    roots = frozenset(root_ids)
    evaluated = _read_evaluated_nodes(database_url, campaign)
    root_oracle = SubtreeOracle(_NoPostEndpoint(), database_url=database_url)

    # Type-D only: every evaluated node's own depth-based resolution,
    # answered once through the same oracle the Type-B step (step 6 below)
    # already reads -- the gate's branch sample built in the loop below and
    # the Type-B accounting both read this one resolution per node rather
    # than asking the oracle twice.
    node_resolutions: dict[str, nulloracle.TypeDResolution] = {}
    if is_type_d:
        type_d_oracle = nulloracle.TypeDOracle(database_url)
        for node in evaluated:
            node_resolutions[node.node_id] = type_d_oracle.resolve_request(
                node.node_id, (0.0,), permute=lambda series: series
            )

    null_scores: list[float] = []
    real_scores: list[float] = []
    discoveries: list[str] = []
    discovery_roots: list[str] = []
    discoveries_ic = 0
    # The evaluated nodes whose root the sidecar labels null -- the same
    # per-node labels this loop resolves for the KS split, handed on to the
    # commit (step 9) so it can skip them.  Nothing new is read and no label
    # is persisted: the set is this run's own memory of entries it already
    # held.  ``null_discoveries`` counts the ones that cleared the discovery
    # bar -- discoveries the calibration figures below still count, but
    # nodes the campaign must never commit to.
    null_branch_nodes: set[str] = set()
    null_discoveries = 0
    triage_null: list[float] = []
    triage_real: list[float] = []
    # root_id -> (ic_mean, ic_tstat, is_null) of the root's *own* evaluation
    # -- the Type-R gate's population (bug_spec_ks_guard_root_level.xml).
    # Set only when the root itself was evaluated (node.node_id == root_id);
    # a child never adds or overwrites an entry here.
    root_level: dict[str, tuple[float, float, bool]] = {}
    # root_id -> (depth, ic_mean, ic_tstat) of the branch's shallowest null
    # node and deepest real node -- the Type-D gate's population
    # (bug_spec_closeout_type_d_ks_branch.xml).  "Branch" and "root" are the
    # same key here: a Type-D flip is drawn on a branch's root, so grouping
    # by _resolve_root's answer groups by branch.
    branch_null: dict[str, tuple[int, float, float]] = {}
    branch_real: dict[str, tuple[int, float, float]] = {}
    for node in evaluated:
        root_id = _resolve_root(
            root_oracle, node.node_id, campaign=campaign, roots=roots
        )
        entry = sidecar.assignment(root_id)
        if entry is None:
            raise CloseoutError(
                f"{CLOSEOUT_CODE}: the sidecar holds no entry for node "
                f"{node.node_id!r}'s root {root_id!r} of campaign "
                f"{campaign!r}: its null status is unknown, and the split "
                "the KS guard compares cannot count a node on either side "
                "without one"
            )
        (null_scores if entry.is_null else real_scores).append(node.ic_mean)
        if entry.is_null:
            null_branch_nodes.add(node.node_id)
        if node.node_id == root_id:
            root_level[root_id] = (node.ic_mean, node.ic_tstat, entry.is_null)
        if is_type_d:
            resolution = node_resolutions[node.node_id]
            if resolution.real:
                deepest = branch_real.get(root_id)
                if deepest is None or resolution.depth > deepest[0]:
                    branch_real[root_id] = (
                        resolution.depth, node.ic_mean, node.ic_tstat,
                    )
            else:
                shallowest = branch_null.get(root_id)
                if shallowest is None or resolution.depth < shallowest[0]:
                    branch_null[root_id] = (
                        resolution.depth, node.ic_mean, node.ic_tstat,
                    )
        if node.ic_tstat >= DISCOVERY_TSTAT:
            discoveries_ic += 1
        if _is_discovery(node):
            discoveries.append(node.node_id)
            discovery_roots.append(root_id)
            if entry.is_null:
                null_discoveries += 1
        # The M1 triage sample -- every evaluated node whose lookback-jitter
        # tripwire actually measured, labelled by the same root-mapped
        # sidecar entry the KS split above just resolved (a child inherits
        # its root's label here too).  A node the tripwire step could not
        # measure (`perturb_stability` NULL) contributes nothing: "not
        # measured" is not a stability reading of zero.
        if node.perturb_stability is not None:
            (triage_null if entry.is_null else triage_real).append(
                node.perturb_stability
            )

    # Which rule produced the discoveries, discovery_roots and (below) the
    # commit: post-cost-ir once any evaluated node carries ir_tstat, the
    # ic-fallback only when the whole tree predates feature 1 and none do.
    selection_rule = (
        SELECTION_RULE_POST_COST_IR
        if any(node.ir_tstat is not None for node in evaluated)
        else SELECTION_RULE_IC_FALLBACK
    )

    # The diagnostic: §7.4's test over every evaluated node's realised
    # ic_mean, root and child alike -- the sample this module gated on
    # before bug_spec_ks_guard_root_level.xml.  Computed and reported, never
    # persisted through the guard's own store: that store's one row per
    # campaign is the gate's (step 1 below), and a second write would be a
    # second answer to "what is this campaign's ks_pvalue".  Refuses exactly
    # as the gate below would for a campaign too small to measure at all
    # (nulloracle.KS_MIN_SAMPLE on a side) -- the same refusal this call
    # replaces, so a one-sided plant still refuses close-out outright rather
    # than reporting a diagnostic no test produced.
    diagnostic = nulloracle.ks_two_sample(null_scores, real_scores)
    ks_pvalue_all_nodes = diagnostic.pvalue

    # The diagnostic's own sample, its unit following the campaign type: one
    # ic_mean per root for Type-R (never a child's), one per branch for
    # Type-D (its shallowest null and deepest real, never a pseudo-
    # replicated descendant in between) -- truncated, either way, to values
    # whose own |ic_tstat| has not already cleared DISCOVERY_TSTAT on either
    # side.  This is bug_spec_ks_guard_root_level.xml's fix, kept exactly as
    # it was computed, but demoted to a diagnostic by this bug fix: it is a
    # comparison of null roots against *real* ones, and "no edge vs no edge"
    # on both labels is still a comparison genuine real edge can fail on its
    # own (the defect this fix removes from the verdict -- see "Gate A and
    # Gate B" in the module docstring).  Also collects each null's own
    # ic_tstat, untruncated: Gate A below reads every one of them, including
    # an individually "significant" one, because a leaking null is exactly
    # what an outlier in the null population would look like.
    if is_type_d:
        null_gate_scores = [
            ic_mean
            for _depth, ic_mean, ic_tstat in branch_null.values()
            if abs(ic_tstat) < DISCOVERY_TSTAT
        ]
        real_gate_scores = [
            ic_mean
            for _depth, ic_mean, ic_tstat in branch_real.values()
            if abs(ic_tstat) < DISCOVERY_TSTAT
        ]
        gate_a_null_tstats = [
            ic_tstat for _depth, _ic_mean, ic_tstat in branch_null.values()
        ]
    else:
        null_gate_scores = [
            ic_mean
            for ic_mean, ic_tstat, is_null in root_level.values()
            if is_null and abs(ic_tstat) < DISCOVERY_TSTAT
        ]
        real_gate_scores = [
            ic_mean
            for ic_mean, ic_tstat, is_null in root_level.values()
            if not is_null and abs(ic_tstat) < DISCOVERY_TSTAT
        ]
        gate_a_null_tstats = [
            ic_tstat for ic_mean, ic_tstat, is_null in root_level.values() if is_null
        ]
    ks_root_counts = (len(null_gate_scores), len(real_gate_scores))
    if (
        len(null_gate_scores) < nulloracle.KS_MIN_SAMPLE
        or len(real_gate_scores) < nulloracle.KS_MIN_SAMPLE
    ):
        # Too few non-significant values on one side for the diagnostic
        # itself to be computed at all -- reported as None, never raised:
        # unlike before this fix, nothing downstream is gated on it.
        ks_pvalue_root_nonsig: float | None = None
    else:
        # nulloracle.KsGuard is still the writer of campaign.ks_pvalue and
        # campaign_ks_guard -- ops.instrument_status's KS lamp and this
        # store's own read-back invariant both depend on that column holding
        # whatever this call persists, and this diagnostic is what it has
        # always persisted.  What changed is that calibration_status is no
        # longer read off this write (see Gate A below, and the module
        # docstring).
        ks_record = nulloracle.KsGuard(database_url).guard(
            campaign, null_gate_scores, real_gate_scores
        )
        ks_pvalue_root_nonsig = ks_record.pvalue

    if gate_a_null_tstats:
        null_tstat_mean: float | None = statistics.fmean(gate_a_null_tstats)
        null_tstat_sd: float | None = (
            statistics.stdev(gate_a_null_tstats)
            if len(gate_a_null_tstats) >= 2
            else None
        )
    else:
        null_tstat_mean = None
        null_tstat_sd = None

    # Gate A: does the campaign's own null sample still look like N(0,1)?
    # The one-sample test this bug fix adds -- see the module docstring.
    gate_a_status, gate_a_p, _gate_a_statistic = _gate_a(gate_a_null_tstats)

    # Gate B: does the agent's own behaviour -- which roots it chose to
    # expand -- predict a root's null status?  Every planted root the
    # sidecar holds an entry for (not only an evaluated one: a root nobody
    # ever expanded still answers "never expanded"), labelled by the
    # sidecar and by whether its subtree carries any node beside itself.
    root_labels: dict[str, bool] = {}
    for a_root_id in root_ids:
        root_entry = sidecar.assignment(a_root_id)
        if root_entry is not None:
            root_labels[a_root_id] = root_entry.is_null
    expanded_roots: set[str] = set()
    for node_id, parent_id in _read_campaign_node_parents(database_url, campaign):
        if parent_id is None:
            continue
        expanded_roots.add(
            _resolve_root(root_oracle, node_id, campaign=campaign, roots=roots)
        )
    gate_b_status, gate_b_p = _gate_b(root_labels, frozenset(expanded_roots))

    # calibration_status: VOID if either gate rejects; otherwise ok unless
    # Gate A itself has nothing to test (fewer than GATE_A_MIN_NULL_COUNT
    # null values) -- Gate B's own "insufficient" (no root ever expanded, or
    # no root of one label) is common in a short or synthetic campaign and
    # is not itself evidence of a problem, so it never alone downgrades an
    # otherwise-clean Gate A reading.  VOID is sticky: once a prior run (or
    # this one) has voided the campaign, it never clears.
    already_void = record.calibration_status == nulloracle.CALIBRATION_STATUS_VOID
    if (
        already_void
        or gate_a_status == nulloracle.CALIBRATION_STATUS_VOID
        or gate_b_status == nulloracle.CALIBRATION_STATUS_VOID
    ):
        calibration_status = nulloracle.CALIBRATION_STATUS_VOID
        _force_void(database_url, campaign)
    elif gate_a_status == CALIBRATION_STATUS_INSUFFICIENT:
        calibration_status = CALIBRATION_STATUS_INSUFFICIENT
    else:
        calibration_status = nulloracle.CALIBRATION_STATUS_OK

    ks_pvalue = gate_a_p
    ks_variant = KS_VARIANT_NULL_CALIBRATION

    # 3. The calibration figures, over the planted roots and the
    #    campaign's discoveries, each mapped to its root -- the scorer's
    #    own verb collapses a subtree's repeated discoveries into one pick.
    figures = scorer.calibration_figures(population=root_ids, picks=discovery_roots)
    # 4. FDR_deploy, reweighted and persisted from that pair. A campaign
    #    that declared no discovery sits at the (sensitivity 0, specificity
    #    1) corner, where FDR_deploy is 0/0 and the store refuses it. That is
    #    an undefined figure, not a failed close-out: it is reported as None
    #    and every later step (calibration pair, discovery rate, triage) still
    #    runs (campaign 1ffef8b3 lost all three to this refusal).
    if discoveries:
        fdr_value: float | None = scoring.FdrDeployStore(database_url).persist(
            campaign, figures
        )
    else:
        fdr_value = None
        _logger.info(
            "campaign %s declared no discovery; FDR_deploy is undefined (0/0) "
            "and is not persisted",
            campaign,
        )
    # 5. The pair itself, persisted for the dashboard's trend.
    ops.NullCalibrations(database_url).record(
        campaign, sensitivity=figures.sensitivity, specificity=figures.specificity
    )

    type_b: int | None = None
    if is_type_d:
        # 6. Type-B depth past the flip, Type-D campaigns only -- each
        #    evaluated node's depth and its branch's flip, joined by the
        #    same resolution the gate's branch sample above already read
        #    (resolved by the node's own id, never the root: a Type-D
        #    node's branch -- and the flip it may sit past -- is a fact of
        #    depths the oracle reads straight off the tree, not of the
        #    sidecar, so it is not refused for a child the way the
        #    sidecar's own per-root entries would be).
        explored = [node_resolutions[node.node_id] for node in evaluated]
        # commitment_error_rate is discarded below (Type-A is not this
        # campaign's figure to report here) -- picks are handed as the
        # same root-mapped discoveries calibration_figures took, so the
        # rate the scorer computes along the way never asks the sidecar
        # about a child's own id either.
        accounting = scoring.account_errors(
            discovery_roots, explored=explored, scorer=scorer
        )
        type_b = accounting.depth_past_flip_errors
        ops.TypeBDepths(database_url).record(campaign, depth_past_flip_errors=type_b)

    # 7. The discovery rate, over the ledger's own budget-charging and
    #    total trial counts for this campaign.
    trial_ledger = ledger.TrialLedger(database_url)
    campaign_trials = [
        row for row in trial_ledger.rows() if row.campaign_id == campaign
    ]
    ledger_trials = len(campaign_trials)
    budget_charging_trials = sum(1 for row in campaign_trials if row.charges_budget)
    ops.DiscoveryRates(database_url).record(
        campaign,
        discoveries=len(discoveries),
        budget_charging_trials=budget_charging_trials,
        ledger_trials=ledger_trials,
    )

    # 8. The M1 triage figure -- the perturbation-stability AUC over the
    #    sample collected above, persisted to its own table and refreshed on
    #    a rerun.  Only the three figures land (never a node id or a label).
    triage_auc = _triage_auc(triage_null, triage_real)
    triage_null_count = len(triage_null)
    triage_real_count = len(triage_real)
    _persist_triage(
        database_url,
        campaign,
        auc=triage_auc,
        null_count=triage_null_count,
        real_count=triage_real_count,
    )

    # 9. The M2 commit -- one pick per campaign, scored out of sample, and
    #    persisted as the campaign's financial replay-world score
    #    (additions_spec_m2_baseline_financial_worlds.xml, "Out-of-Sample
    #    Evaluation", feature 2).  Runs after every calibration step above:
    #    the commit reads the same in-sample ic_tstat those steps already
    #    measured, and the world is admitted or refused by the campaign's
    #    calibration_status as that machinery just left it.  The null labels
    #    the KS-split loop above already resolved ride along, so a planted
    #    null branch that cleared the discovery bar is skipped, never
    #    committed -- the calibration figures above still counted it, and
    #    null_discoveries reports how many were skipped here.
    #
    #    The dedup variant (additions_spec_dedup_committed_constructs.xml)
    #    rides in through the same exclusion set when the evaluation config
    #    set dedup_committed_constructs: every bar-clearing real node whose
    #    stored in-sample fingerprint equals one an earlier campaign under
    #    the same evaluation_config_sha256 already committed is excluded too,
    #    so a series of campaigns samples distinct constructs rather than the
    #    same one repeatedly (the short-h5 RESULT's ten campaigns, mean
    #    pairwise correlation 0.91).  With the flag false nothing is read and
    #    both counts stay 0.
    dedup_skipped = 0
    dedup_against = 0
    dedup_nodes: frozenset[str] = frozenset()
    if context is not None and context.dedup_committed_constructs:
        earlier = _earlier_committed_fingerprints(database_url, campaign)
        dedup_against = len(earlier)
        dedup_nodes = _dedup_excluded_nodes(
            evaluated, earlier, null_nodes=frozenset(null_branch_nodes)
        )
        dedup_skipped = len(dedup_nodes)
        _logger.info(
            "campaign %s: dedup_committed_constructs is set — %d bar-clearing "
            "node(s) skipped as already committed, checked against %d earlier "
            "pick(s) under this evaluation config",
            campaign,
            dedup_skipped,
            dedup_against,
        )
    termination = _commit_top_node(
        evaluated,
        null_nodes=frozenset(null_branch_nodes) | dedup_nodes,
    )
    committed_pick = termination.pick.node_id if termination.committed else None

    oos_ir: float | None = None
    oos_ic_tstat: float | None = None
    if termination.committed and context is not None and context.oos_dates:
        oos_ir, oos_ic_tstat = _oos_reading(
            termination.pick.node_id,
            campaign_id=campaign,
            database_url=database_url,
            sidecar=sidecar,
            context=context,
        )

    # The world is this campaign itself: a financial world's identity is
    # its own campaign id (additions_spec_m2_baseline_financial_worlds.xml
    # feature 3's score_on_financial_world(policy, campaign_id, ...) reads
    # the replay pool's financial worlds by that same id), never a
    # synthesized backfill id -- a live campaign's world *is* the regime it
    # ran in, and needs no second identity to name it by.
    world_id = campaign
    manifest = discovery.finish_campaign(campaign, database_url=database_url)
    try:
        discovery.admit_completed_campaigns([manifest])
    except discovery.VoidCampaignError:
        # §7.4's own gate: a VOID campaign is excluded from the replay pool,
        # so this campaign is not persisted as a world at all -- the figures
        # above are already saved, and the VOID verdict (if any) is already
        # the printed calibration_status.
        world_persisted = False
    else:
        world_persisted = True
        score = (
            oos_ir
            if termination.committed and oos_ir is not None
            else replay.NON_COMMITTING_SCORE
        )
        is_holdout = _m2_fixed_is_holdout(database_url, world_id)
        _clear_m2_fixed_rows(database_url, world_id)
        replay.persist_replay_score(
            replay.TerminalPick(pick=termination.pick, score=score),
            M2_FIXED_POLICY_VERSION,
            world_id,
            M2_FIXED_BETA,
            is_holdout=is_holdout,
            database_url=database_url,
        )

    return CloseoutResult(
        campaign_id=campaign,
        ks_pvalue=ks_pvalue,
        ks_pvalue_all_nodes=ks_pvalue_all_nodes,
        ks_pvalue_root_nonsig=ks_pvalue_root_nonsig,
        ks_variant=ks_variant,
        ks_root_counts=ks_root_counts,
        gate_a_p=gate_a_p,
        gate_b_p=gate_b_p,
        null_tstat_mean=null_tstat_mean,
        null_tstat_sd=null_tstat_sd,
        calibration_status=calibration_status,
        sensitivity=figures.sensitivity,
        specificity=figures.specificity,
        fdr_deploy=fdr_value,
        type_b=type_b,
        discoveries=len(discoveries),
        discoveries_ic=discoveries_ic,
        null_discoveries=null_discoveries,
        dedup_skipped=dedup_skipped,
        dedup_against=dedup_against,
        selection_rule=selection_rule,
        budget_charging_trials=budget_charging_trials,
        ledger_trials=ledger_trials,
        triage_auc=triage_auc,
        triage_null_count=triage_null_count,
        triage_real_count=triage_real_count,
        committed_pick=committed_pick,
        oos_ir=oos_ir,
        oos_ic_tstat=oos_ic_tstat,
        world_persisted=world_persisted,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.closeout",
        description=(
            "Close out a finished campaign: run the KS guard and the "
            "verdict, persist its calibration figures to the stores the "
            "dashboard and API read, and print them as one JSON line."
        ),
    )
    parser.add_argument(
        "--campaign-id",
        dest="campaign_id",
        required=True,
        metavar="ID",
        help="the finished campaign to close out",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m orchestrator.closeout --campaign-id ID``.

    Checks, in order, before anything is read: ``DATABASE_URL``, then the
    sidecar's two variables (``NULL_SIDECAR_PATH``, ``NULL_SIDECAR_KEY_REF``)
    -- each absence exits :data:`EXIT_CONFIG`, naming the missing variable.
    Then runs :func:`close_out` and prints its one JSON line. A refusal
    :func:`close_out` or a collaborator raises is printed to stderr verbatim
    (every one of them already opens with its own code word) and answered
    :data:`EXIT_REFUSED`; a VOID verdict still prints the line and answers
    :data:`EXIT_VOID`.

    ``env`` and ``emit`` are this command's seams, read and written exactly
    as the other operator CLIs in this workspace take them: ``env`` is
    where every variable above is read from (the process environment when
    ``None``), and ``emit`` is what the one JSON line is printed with.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{CLOSEOUT_CODE}: {DATABASE_URL_ENV} must name the research "
            "database closeout reads and writes to",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    if not source.get(nulloracle.SIDECAR_PATH_ENV, "").strip():
        print(
            f"{CLOSEOUT_CODE}: {nulloracle.SIDECAR_PATH_ENV} must name the "
            "sealed null sidecar closeout reads as the scorer process "
            "(prd §4.2)",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    if not source.get(nulloracle.KEY_REF_ENV, "").strip():
        print(
            f"{CLOSEOUT_CODE}: {nulloracle.KEY_REF_ENV} must name the "
            "sidecar's key",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    scorer = scoring.NullPickScorer.resolve(source)
    sidecar = nulloracle.NullSidecar.resolve(source)
    if scorer is None or sidecar is None:
        print(
            f"{CLOSEOUT_CODE}: no null sidecar is configured under "
            f"{nulloracle.SIDECAR_PATH_ENV}/{nulloracle.KEY_REF_ENV}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        # Loaded inside the same refusal path as close_out's own collaborators:
        # an unset NULLIUS_EVALUATION_CONFIG is the unconfigured state
        # (None, no OOS reading -- feature 2's own documented "no oos_dates"
        # case), but a configured-and-broken one is refused the same way any
        # other collaborator's refusal is here, naming the key or variable at
        # fault (EvaluationConfigError's own words).
        context = load_evaluation_context(env=source)
        result = close_out(
            arguments.campaign_id,
            database_url=database_url,
            scorer=scorer,
            sidecar=sidecar,
            context=context,
        )
    except Exception as exc:  # noqa: BLE001 - every collaborator's own
        # refusal is caught here: nulloracle, scoring, ops, ledger and
        # discovery each raise from their own, unrelated base class, with
        # no common ancestor across the five members to catch by type.
        # Every one of those refusals already opens its own message with a
        # greppable code word, which is what reaches stderr unchanged.
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(result.to_payload()))
    return EXIT_VOID if result.is_void else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
