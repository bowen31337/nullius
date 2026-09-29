"""Feature 215 — ``tree_diversity``: distinct mechanism clusters per campaign.

*"System computes tree_diversity as the count of distinct mechanism clusters
per campaign, which returns the figure per authoring model."*

docs/nullius-tech-architecture.md §14.1 states the figure inside its
"Measuring model adequacy on this task" block, beside the correlation feature
214 owns::

    mechanism_discrimination = corr( IS_gain, OOS_gain | real branches )
    tree_diversity           = distinct mechanism clusters per campaign

and the paragraph under it says what the pair is *for* — §14.1's M2
instrument, run *"at M2, before the M3 gate"*, two campaigns per candidate
model, roughly $60 — together with the sentence that makes diversity a
*requirement* rather than a delight::

    Avoid distilling a small model on a frontier model's successful proposals
    after M3: it narrows toward one family's distribution, and diversity is
    precisely what roots need.

**This module is the first reader of feature 207's store that is not the
authoring loop.** :mod:`signal_agent._proposal` writes one row per node into
the member-owned ``node_proposal`` table — a proposal document plus the score
snapshot taken when the round read it — and this module counts over those
rows. ``additions_spec_207.xml`` names the reader from the writer's side:
*"depended on by features 214 and 215 (mechanism discrimination and tree
diversity, which read the persisted score records across a campaign's real
branches)"*.

Three decisions carry the feature, and each is argued where it bites below:
what a **cluster** is (:data:`_CLUSTERS_SQL`), which column may **not** be
clustered on (:class:`StatedMechanism`'s barrier, cited and not
re-implemented), and what the **per-authoring-model** half is a statement
about (:data:`MODEL_COLUMN`, joined).

Parse nothing, import nothing outside the standard library, write nothing.

**What this module is not.**  It is not feature 214's correlation — that is a
different statistic over a different pair of columns (the metric pair, keyed
on the real/null discriminant), and nothing here reads a metric.  It is not
feature 210's anti-convergence gate, which answers a yes-or-no about **one**
proposal against a campaign's history and whose own module docstring
pre-empts this one: *"nothing here prices a proposal or measures how converged
a tree is — that figure is feature 215's, and it is a count of distinct
mechanism clusters rather than anything this module computes."*  This feature
measures **the whole tree** and its consumer is a report, not a gate.  It is
not feature 211's read — see "which column may not be clustered on".  And it
persists nothing: §14.1's sentence for 214 is *"persists mechanism_
discrimination per campaign"* while 215's is *"computes ... which returns the
figure"*, so the figure is a returned value with no row behind it.

**Why no component, and why no seat.**  The count resolves no configuration of
its own: the table to read, the columns to join and the figure's shape are all
facts about state two existing component builders already expose (207's store
and the tree it lives in).  So it is a free function beside them, reached as
``from signal_agent import tree_diversity``, exactly as feature 186's
:func:`bootstrap.world_census` sits beside the bootstrap pool, feature 229's
``plan_grid`` and features 230/231's ``screen_policy`` sit in their own member,
and feature 222's ``episode_commit``, 223's ``prefix_view``, 226's
``read_beta`` and 227/228's threshold laws sit in theirs.  A tenth
``signal-agent-*`` registration would put a name in the registry for a
question that composes nothing, and this feature has no *composed component*
to read.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .errors import (
    DiversityCohortError,
    ProposalHistoryStoreUnavailableError,
    ProposalNodeNotRecordedError,
)

__all__ = [
    "MODEL_COLUMN",
    "NODE_PROPOSAL_CODE_HASH_COLUMN",
    "NODE_PROPOSAL_NODE_COLUMN",
    "NODE_PROPOSAL_TABLE",
    "TreeDiversity",
    "tree_diversity",
]

#: The table the count reads — feature 207's member-owned
#: ``node_proposal``, created lazily by :meth:`ProposalStore._connect` and
#: declared nowhere in the shared migration chain.  Spelled here as a literal
#: rather than imported from :mod:`signal_agent._proposal` for the reason
#: every store in this workspace restates its own: a private constant of a
#: sibling module is not a promise, and a module that reads one column and one
#: table does not need that module importable to say which.  The name is
#: ``signal_agent.NODE_PROPOSAL_TABLE``'s, and the member's own suite asserts
#: the two spellings agree rather than leaving them to drift.
NODE_PROPOSAL_TABLE: Final[str] = "node_proposal"

#: 0118's table — the discovery tree's, created by feature 97 and owned by it.
#: This module joins it read-only to reach the authoring model and creates
#: nothing.
NODE_TABLE: Final[str] = "node"

#: 0118's primary key, and the tree-side half of the join.
NODE_ID_COLUMN: Final[str] = "id"

#: Feature 207's key on its own table — *deliberately a second constant*, even
#: though it currently spells the same four characters as :data:`NODE_ID_COLUMN`.
#:
#: The two are keys of two different tables owned by two different features, and
#: the join is ``node.id = node_proposal.node_id``.  One constant spelled in both
#: places would read as *the id column*, which is how a join comes to be written
#: ``n.id = p.id`` — a statement SQLite answers with ``no such column: p.id``
#: (measured, in this feature's own suite: the first draft of the tests ran
#: against exactly that), and which on a schema that *did* hold both names would
#: join on the wrong pair and count a silent wrong figure.  Feature 207's
#: ``_SCHEMA`` names its column ``node_id`` and this module reads that name.
NODE_PROPOSAL_NODE_COLUMN: Final[str] = "node_id"

#: **The column the "per authoring model" half of the sentence turns on.**
#: 0115's ``agent_model_id`` — feature 100's column, written by feature 203's
#: :class:`providers.AgentModelPins` as a provider/model/version *triple* rather
#: than a rolling alias, "pinned, not a rolling alias" being the whole of
#: feature 203's sentence and PRD §5a's *"the only real guarantee"*.  It is
#: ``NOT NULL`` in the migration, because *"every node is authored by exactly
#: one model"* — and it is the one column a stratification may group on.
#:
#: **It is joined, not copied.**  Feature 207's ``_SCHEMA`` note explains why
#: ``agent_model_id`` is deliberately absent from its own table: it *"is 0115's
#: column on ``node`` (features 203/204), indexed for the M3 stratification,
#: and a copy here would be a second spelling of it that can drift from the
#: stratum the paired comparison actually groups by ... A reader that wants it
#: joins."*  This module is that reader, and this constant is that join.
MODEL_COLUMN: Final[str] = "agent_model_id"

#: The proposal document's identity on 207's row: §9.1's ``code_hash``, taken
#: over the stored document's exact bytes by
#: :func:`signal_agent._proposal._document_digest`.  It is the column a cluster
#: is counted by — see :data:`_CLUSTERS_SQL` for why this and not a skeleton.
NODE_PROPOSAL_CODE_HASH_COLUMN: Final[str] = "code_hash"

#: The campaign scope on 207's row, taken from the ``node`` row at the moment
#: of the write and stored, so the count is §9's *"one campaign = one discovery
#: tree"* without trusting a caller's pairing of node to campaign.
CAMPAIGN_ID_COLUMN: Final[str] = "campaign_id"

#: The revision that adds :data:`MODEL_COLUMN` — feature 100's migration, the
#: whole actionable content of a :class:`~signal_agent.DiversityCohortError`
#: raised for a tree that has not reached it.
MODEL_POLICY_REVISION: Final[str] = "0115_agent_model_trio"

#: The revision that creates :data:`NODE_TABLE` — feature 97's, named for the
#: reason ``0117``'s sibling refusals name it: a tree with no ``node`` table
#: has not reached the chain's node feature, and the repair is an operation.
NODE_POLICY_REVISION: Final[str] = "0118_node_table"


# ── What a cluster is ────────────────────────────────────────────────────────
#
# "Distinct mechanism clusters" needs a definition, and this member owns three
# candidate identities, each built for a different question.  The choice, and
# the two rejections, are the feature — a reader who guessed wrong here would
# get a number that looks like a measurement and is not one.
#
# * ``mechanism_digest(node.stated_mechanism)`` — the agent's *stated claim*,
#   feature 211's key.  **Refused**, and the refusal is the load-bearing one:
#   see the barrier note on :data:`_CLUSTERS_SQL`.
#
# * ``skeleton_digest(source)`` — the source's *structure with every numeric
#   literal erased*, feature 210's key.  **Refused**, for the two reasons
#   argued below.  It is the tempting choice, because "the mechanism's shape"
#   *sounds* like what "mechanism cluster" means, so the argument is written
#   out rather than implied:
#
#   1. It is another feature's unit, and that feature has already assigned it.
#      §14.1's own words, quoted by 210's module docstring, draw the line —
#      210's verdict is *"a yes-or-no about one structure against one
#      campaign's history"* and the diversity figure is *"a count of distinct
#      mechanism clusters rather than anything this module computes"*.  A
#      derived key has one owner in this member — the rule that makes
#      :func:`mechanism_digest` and :func:`skeleton_digest` each spell their
#      sha256 in the same three lines — and borrowing 210's here would make
#      this module a second, silent definition of "the same structure".
#      If a cluster is ever to be skeleton-based that is a change to what a
#      cluster *is*, argued once and in one place.
#
#   2. Erasing constants makes the count blind to what §14.1 says depth
#      actually does.  210's gate stops the 400th tweak from being *written*;
#      what a diversity figure has to describe is what *was* written.  A weak
#      model that emits forty structurally distinct variants of one indicator
#      — each a different accessor, each curve-fitting the same noise — is the
#      failure §14.1 is measuring, and a skeleton-erased count reports it as
#      forty clusters.  ``code_hash`` reports forty distinct proposals, which
#      is the honest description of the tree in front of it.  Neither count is
#      "the convergence measure" — 210's gate is — and this one is the count
#      the sentence asks for.
#
#      The same argument costs the third candidate nothing extra: counting
#      skeletons would also mean parsing every stored document, and
#      :func:`proposal_skeleton` *raises* on text that does not parse (its
#      docstring says so — the conformance screen runs first).  A reporting
#      function that can be taken down by one malformed old row is a reporting
#      function that stops reporting, and this one reads bytes it never
#      interprets.
#
# * ``code_hash`` — *this exact proposal*, feature 207's stored identity.
#   **This one.**  It asserts no semantic equivalence at all: two rows are one
#   cluster exactly when they are the same document, so the count is the number
#   of distinct proposals the campaign recorded, per model.  That is a figure
#   the system can vouch for rather than one it inferred, it is computable in
#   one SQL statement, it needs no parse, and it is stable across a replay
#   because ``code_hash`` is the tree's own identity for a node's source (§9.1,
#   recomputed by feature 206's identity check on every read).

#: The count, grouped by authoring model — the feature's whole arithmetic.
#:
#: * ``COUNT(DISTINCT p.code_hash)`` — one row is one node's proposal, and two
#:   nodes carrying the *same* document are **one** mechanism cluster while
#:   being two proposals.  This is the clause that makes the figure diversity
#:   rather than activity: a plan that grew by re-proposing what it already
#:   held shows a count that does not move, which is exactly the reading §14.1
#:   wants — *"diversity is precisely what roots need"*.
#:
#: * ``JOIN node`` — the model stratum.  An inner join rather than a left one
#:   on purpose: an orphan row (a ``node_proposal`` row whose node is gone) has
#:   no model to be counted under, and the inner join would drop it silently,
#:   which is the one direction a count must never move by accident.  The
#:   orphans are therefore looked for *first* (:data:`_ORPHANS_SQL`) and refused
#:   by name before this statement runs, so the join guarded by that refusal can
#:   never be the thing that lost a row.
#:
#: * ``GROUP BY`` and ``ORDER BY`` on the model — the answer is a mapping, and
#:   the order is fixed here rather than left to SQLite's row layout so two
#:   reads of one unchanged cohort produce the same report line, which is what
#:   §14.1's reporting rules assume when they compare tables across models.
#:
#: **No metric column appears, and no ``stated_mechanism``.**  The score
#: snapshot 207 stores beside each document is evidence about the *round that
#: read it* — what feature 214 correlates — and diversity is a statement about
#: what was written, so this feature reads neither the metrics nor the score
#: document.  And the rationale is refused outright; see below.
#:
#: **Why ``stated_mechanism`` is not the clustering key — the barrier.**  The
#: column exists, :func:`mechanism_digest` is right there, and using them would
#: be a subtle bug rather than an obvious one: the figure would look like a
#: measurement and would in fact be a function of what models claim about
#: themselves.  Three authorities already in this member's vocabulary agree:
#:
#: * docs/nullius-tech-architecture.md §9.1 annotates the column
#:   ``-- dedup + human review ONLY``, and docs/alpha-engine-prd.md states the
#:   same of a node's stated mechanism;
#: * feature 211's :meth:`StatedMechanism.scored_input` refusal names *this*
#:   reader in as many words: *"a score conditioned on the rationale would make
#:   ``agent_model_id`` stratification (PRD §5a), the M3 paired comparison
#:   (architecture §14.1) and the beta-three deflation term functions of what a
#:   model said about itself."*  This feature's sentence **is** the
#:   ``agent_model_id`` stratification — *"returns the figure per authoring
#:   model"* — so it is precisely the reader that sentence forbids;
#: * feature 210's docstring records the mechanical reason it fails anyway:
#:   *"a weak model asked for the 400th variant states it confidently in fresh
#:   prose, so the claim differs while the structure repeats."*  A count over
#:   claims therefore counts prose variation as diversity — the flattering
#:   direction, which §14.1's own reporting rules warn about (*"the direction
#:   of the error is always flattering"*).
#:
#: So the barrier is enforced **structurally** rather than by a check: this
#: module does not import :mod:`signal_agent._mechanism`, never names
#: ``MECHANISM_COLUMN``, and its SQL selects two columns.  A column that is not
#: selected cannot reach the figure, and there is no guard here to get wrong or
#: to be refactored away.  That is also why :func:`tree_diversity` takes a
#: *proposal-history* handle and not a :class:`StatedMechanism` one: a
#: signature that accepted the rationale's law would make the wrong read
#: reachable from the feature that must not make it.
_CLUSTERS_SQL: Final[str] = f"""
SELECT n.{MODEL_COLUMN} AS model,
       COUNT(DISTINCT p.{NODE_PROPOSAL_CODE_HASH_COLUMN}) AS clusters
FROM {NODE_PROPOSAL_TABLE} AS p
JOIN {NODE_TABLE} AS n ON n.{NODE_ID_COLUMN} = p.{NODE_PROPOSAL_NODE_COLUMN}
WHERE p.{CAMPAIGN_ID_COLUMN} = ?
GROUP BY n.{MODEL_COLUMN}
ORDER BY n.{MODEL_COLUMN} ASC
"""

#: The cohort's size: how many proposals this campaign recorded, which is
#: §14.1's denominator and the number a bare count cannot be read without.
#: *"3 clusters"* is uninterpretable; *"3 clusters over 40 proposals"* is the
#: figure the M2 comparison reasons about, and §14.1's rule 2 — *"both trivial
#: baselines appear in every table"* — is the same argument from the other end:
#: a figure reported without the thing it is a figure *about* is a figure
#: nobody can check.
_COHORT_SQL: Final[str] = (
    f"SELECT COUNT(*) FROM {NODE_PROPOSAL_TABLE} "
    f"WHERE {CAMPAIGN_ID_COLUMN} = ?"
)

#: The orphan sweep — the row the inner join would have dropped.
#:
#: ``NOT EXISTS`` rather than ``NOT IN``, for the reason feature 186's census
#: spells for its own exclusion: ``NOT IN`` over a subquery holding one ``NULL``
#: is *unknown* for every row and so answers empty, which here would mean
#: reporting no orphans about a table full of them.  Feature 207 refuses this
#: state at write time (:class:`ProposalNodeNotRecordedError` — a proposal is
#: recorded against a node the tree holds), so a row found here is a database
#: that has *lost* a node: an FK-less table, a hand edit, a restored backup.
#: Refused rather than dropped, because a diversity figure that quietly shrank
#: would flatter exactly the model whose nodes went missing.
_ORPHANS_SQL: Final[str] = f"""
SELECT p.{NODE_PROPOSAL_NODE_COLUMN} FROM {NODE_PROPOSAL_TABLE} AS p
WHERE p.{CAMPAIGN_ID_COLUMN} = ?
  AND NOT EXISTS (
      SELECT 1 FROM {NODE_TABLE} AS n
      WHERE n.{NODE_ID_COLUMN} = p.{NODE_PROPOSAL_NODE_COLUMN}
  )
ORDER BY p.{NODE_PROPOSAL_NODE_COLUMN} ASC
"""

#: The rows that cannot be stratified: a node whose ``agent_model_id`` is NULL
#: or blank, so the count has no stratum to put it in.
#:
#: 0115 declares the column ``NOT NULL`` — *"every node is authored by exactly
#: one model"* — so this is a brought-forward or hand-edited database rather
#: than the shape the chain builds.  It is refused rather than bucketed under a
#: ``None``/``""`` key, because a stratum labelled "unknown" is a value a report
#: would print beside the real models as though it were one of them, and §14.1's
#: whole point is a *per-model* comparison: a bucket that is not a model makes
#: the table it appears in uninterpretable rather than incomplete.  Feature 186
#: makes the same call about a nullable world id in its own count.
#:
#: ``TRIM`` is spelled explicitly because a whitespace-only value is the
#: realistic half of this failure — a writer that supplied ``"  "`` would pass
#: a bare ``IS NULL`` test and land in a stratum no model answers to.  It is not
#: a *normalisation* of the value: 203's :func:`providers.require_agent_model_id`
#: owns what a model id may be, and this module only refuses the ones that name
#: no model at all rather than reshaping one that does.
_UNMODELLED_SQL: Final[str] = f"""
SELECT p.{NODE_PROPOSAL_NODE_COLUMN} FROM {NODE_PROPOSAL_TABLE} AS p
JOIN {NODE_TABLE} AS n ON n.{NODE_ID_COLUMN} = p.{NODE_PROPOSAL_NODE_COLUMN}
WHERE p.{CAMPAIGN_ID_COLUMN} = ?
  AND (n.{MODEL_COLUMN} IS NULL OR TRIM(n.{MODEL_COLUMN}) = '')
ORDER BY p.{NODE_PROPOSAL_NODE_COLUMN} ASC
"""

#: The ``sqlite_master`` probe that answers *does this database hold a recorded
#: history at all?* — read-only, and asked before the count rather than assumed,
#: the idiom feature 207's own ``_NODE_TABLE_EXISTS_SQL``, feature 232's
#: ordering law and feature 239's workspace read each restate for the same
#: reason: a private constant of a sibling module is not a promise.
_HISTORY_EXISTS_SQL: Final[str] = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)

#: The read that answers *which columns does the tree actually have?* — the
#: ``PRAGMA`` probe :meth:`MechanismStore._require_column` and
#: :meth:`providers.AgentModelPins._require_columns` each make for their own
#: column, and for the reason they give: SQLite answers *"no such column"* only
#: once a statement mentions it, which reports the gap as a fact about a
#: statement rather than about the deployment.
_TREE_COLUMNS_SQL: Final[str] = f"PRAGMA table_info({NODE_TABLE})"


class TreeDiversity:
    """One campaign's distinct mechanism clusters, per authoring model.

    The value :func:`tree_diversity` answers with, and feature 215's whole
    output.  It carries three things, and each is one of §14.1's reporting
    rules made structural:

    * :attr:`by_model` — the figure **per authoring model**.  This is the
      feature's sentence taken literally: *"returns the figure per authoring
      model"*, so the answer is a mapping and never a scalar.  A caller that
      wants the pooled number sums the values, and the sum is deliberately not
      offered as a method — a flat figure is a *different* question (the same
      restraint feature 186's :class:`WorldCensus` applies to its own pair),
      and one that invited a single number would invite a table where the
      per-model comparison §14.1 asks for had been quietly collapsed.
    * :attr:`campaign_id` — the scope, canonical UUID text.  §9 makes the
      campaign the unit of search and feature 210 states what that means for a
      comparison set (*"two campaigns exploring one structure from different
      angles are two campaigns, not one collapse"*), so a figure that did not
      name its scope could be read into another campaign's table.
    * :attr:`proposals` — the cohort's size, which is §14.1's rule 2 read as a
      structural requirement rather than a formatting one: *"both trivial
      baselines appear in every table"*, and the baseline for a diversity count
      is the **floor** of one cluster, an entire tree that is one mechanism.
      One is not a field — it is a constant dressed as a measurement — so what
      the object must not do is hide the *denominator*: *"3 clusters"* is
      uninterpretable and *"3 clusters over 40 proposals"* is the figure §14.1
      actually compares across models.  It is a field and not a derived sum,
      because the number of proposals is not the sum of the clusters.

    **Immutable, and immutable in fact rather than by convention.**  The
    mapping is a :class:`~types.MappingProxyType` over a private copy taken at
    construction, so a caller scribbling on what :attr:`by_model` handed it
    moves a proxy that refuses writes rather than the figure — the guarantee
    feature 223's ``observed()`` makes by returning a fresh dict, made here by
    returning a read-only view of a copy.  The counts are plain integers and
    deliberately not a wrapper type: feature 221 wraps its scalar because a
    policy compares it in authored code and the denomination is the feature,
    while this one's consumer is a report whose denomination is the attribute
    name, and a wrapper would put an unwrap between the value and the JSON
    §14.1's cohort table is written into.

    **Validated at construction, not trusted.**  A hand-built value is a test's
    prerogative, and every field here reaches a report that compares models
    against each other, so a value no read could produce is refused rather than
    printed.  The checks are feature 186's three — a key that is not a
    non-empty string, a count that is not a non-negative whole number (with
    ``bool`` refused first, because ``True`` is ``1`` in Python and a flag
    where a count belongs would report a model that produced one cluster), and
    a negative cohort — plus the one this feature needs and 186 has no analogue
    for: **no model's count may exceed the cohort it was counted from**, since
    that is the single arithmetic that would mean the join fanned out.
    """

    __slots__ = ("_by_model", "_campaign_id", "_proposals")

    def __init__(
        self,
        *,
        campaign_id: str,
        by_model: Mapping[str, int],
        proposals: int,
    ) -> None:
        campaign = _validated_campaign_id(campaign_id)
        if not isinstance(by_model, Mapping):
            raise DiversityCohortError(
                f"tree_diversity is a mapping of authoring model to cluster "
                f"count, got {by_model!r} ({type(by_model).__name__}): feature "
                f"215's sentence is *which returns the figure per authoring "
                f"model*, so the answer is one figure per model rather than a "
                f"single number (feature 215)."
            )
        counted = _validated_cohort_size(proposals)
        copied: dict[str, int] = {}
        for model, clusters in by_model.items():
            key = _validated_model(model)
            count = _validated_cluster_count(key, clusters)
            if count > counted:
                raise DiversityCohortError(
                    f"model {key!r} is reported with {count} distinct clusters "
                    f"over a cohort of {counted} proposal(s): a campaign's "
                    f"models each wrote a share of its proposals, so a stratum "
                    f"cannot hold more clusters than the campaign holds "
                    f"documents. A count larger than its denominator is the one "
                    f"arithmetic a fanned-out join produces, and reporting it "
                    f"would put a diversity figure from no tree into §14.1's "
                    f"M2 comparison (feature 215)."
                )
            copied[key] = count
        self._campaign_id = campaign
        self._by_model = MappingProxyType(copied)
        self._proposals = counted

    @property
    def campaign_id(self) -> str:
        """The campaign this figure is scoped to, in canonical UUID text."""
        return self._campaign_id

    @property
    def by_model(self) -> Mapping[str, int]:
        """Distinct mechanism clusters per authoring model — the feature's answer.

        A read-only view over a private copy: two reads of one value answer the
        same mapping by value, and neither can be written through.  The keys are
        the ``agent_model_id`` triples feature 203 pins — provider, model and
        version, *"a pinned snapshot ... the only real guarantee"* — spelled
        exactly as the column holds them, because the stratum this figure is
        grouped by has to be the stratum the M3 paired comparison groups by
        (207's own reason for joining rather than copying the column).
        """
        return self._by_model

    @property
    def proposals(self) -> int:
        """How many proposals the campaign recorded — the denominator.

        Not the sum of :attr:`by_model` and not derivable from it: two nodes
        carrying one document are two proposals and one cluster, and that gap
        is precisely what the figure beside the counts is for.
        """
        return self._proposals

    def row(self) -> dict[str, Any]:
        """The figure as a report-shaped mapping — a fresh dict per call.

        The shape feature 186's :meth:`WorldCensus.row` and feature 223's
        ``observed()`` return: a new mapping each time, so a report tool that
        writes into what it read moves its own copy.  ``by_model`` is nested
        rather than spread in beside the other two keys, and that is deliberate:
        the model keys are values from the database, and a spread row would let
        a model literally named ``proposals`` shadow the denominator — a
        collision a nested mapping cannot have.
        """
        return {
            "campaign_id": self._campaign_id,
            "proposals": self._proposals,
            "by_model": dict(self._by_model),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TreeDiversity):
            return NotImplemented
        return (
            self._campaign_id == other._campaign_id
            and self._proposals == other._proposals
            and dict(self._by_model) == dict(other._by_model)
        )

    def __hash__(self) -> int:
        # The mapping is ordered here so two equal values hash alike whatever
        # order their strata arrived in: a ``dict`` field has no hash of its
        # own, and a value object that were unhashable could not be a dict key
        # or a set member in the report machinery this figure is built for.
        return hash(
            (
                self._campaign_id,
                self._proposals,
                tuple(sorted(self._by_model.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TreeDiversity(campaign_id={self._campaign_id!r}, "
            f"proposals={self._proposals!r}, by_model={dict(self._by_model)!r})"
        )


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    The same normalisation :func:`signal_agent._proposal._validated_campaign_id`
    applies to the column this read is scoped by, restated rather than imported
    for the reason this module restates the table and column names: the count
    joins ``node_proposal.campaign_id``, a TEXT column holding UUID text, and a
    mixed-case id would make one campaign look like two — here, in the question
    of which proposals are counted together.  The two spellings are asserted to
    agree rather than left to drift.
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
    raise DiversityCohortError(
        f"campaign_id {value!r} is not a UUID: feature 215's figure is *per "
        f"campaign* and §9 makes the campaign the unit of search, so the count "
        f"is scoped by the value {CAMPAIGN_ID_COLUMN} holds — and an id that "
        f"cannot join it would silently count another campaign's proposals as "
        f"this one's (feature 215)."
    )


def _validated_model(value: Any) -> str:
    """Validate one stratum key: the model id a bucket is labelled with."""
    if isinstance(value, str) and value.strip():
        return value
    raise DiversityCohortError(
        f"a diversity stratum is keyed by a node's {MODEL_COLUMN} — got "
        f"{value!r} ({type(value).__name__}); 0115 declares that column NOT "
        f"NULL because every node is authored by exactly one model, so a "
        f"bucket that is not a model id is a stratum no model answers to, and "
        f"printing it beside the real ones would make §14.1's per-model table "
        f"uninterpretable rather than incomplete (feature 215)."
    )


def _validated_cluster_count(model: str, value: Any) -> int:
    """Validate one stratum's count: a non-negative whole number, not a flag."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiversityCohortError(
            f"the cluster count for model {model!r} — got {value!r} "
            f"({type(value).__name__}); a cluster count is how many distinct "
            f"mechanisms that model wrote, and a value that is not a whole "
            f"number is a figure no count could produce. ``bool`` is refused "
            f"explicitly because ``True`` is ``1`` in Python, and a flag where "
            f"a count belongs would report a model that wrote one mechanism "
            f"(feature 215)."
        )
    if value < 0:
        raise DiversityCohortError(
            f"the cluster count for model {model!r} cannot be negative — got "
            f"{value!r}; a model wrote zero distinct mechanisms or more, and a "
            f"negative figure would reach §14.1's M2 comparison as a diversity "
            f"no tree can hold (feature 215)."
        )
    return value


def _validated_cohort_size(value: Any) -> int:
    """Validate the denominator: a non-negative whole number, not a flag."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiversityCohortError(
            f"a campaign's proposal count — got {value!r} "
            f"({type(value).__name__}); it is how many proposals the campaign "
            f"recorded, which is the denominator every cluster count is read "
            f"against, and a value that is not a whole number is a cohort size "
            f"no table could report (feature 215)."
        )
    if value < 0:
        raise DiversityCohortError(
            f"a campaign's proposal count cannot be negative — got {value!r}; "
            f"a campaign recorded zero proposals or more, and a negative "
            f"denominator would make every cluster count read as impossible "
            f"(feature 215)."
        )
    return value


def _proposal_history(history: Any) -> Path:
    """Check that ``history`` is feature 207's handle, and return its database.

    Duck-typed rather than ``isinstance``, for the reason feature 186's
    :func:`_counting_pool` and feature 184's question seam state: the module
    loader imports the member under a synthetic name and re-executes it, so the
    composed store ``create_app()`` hands out is a *second* ``ProposalStore``
    class object and an ``isinstance`` gate here would refuse the very store the
    composition seam serves.

    Two names are asked for, and each for its own reason:

    * ``path`` — where the rows are.  Resolved *lazily* by the store (207's own
      decision: construction is composition-time work and must not touch the
      disk), so reading it here is the first thing that resolves it, which is
      why the shape is checked before this function returns rather than after;
    * ``history`` — the verb that makes the object a *proposal history* rather
      than anything else holding a path.  It is not called: this module reads
      the table directly, because the clustering half needs the join to ``node``
      and :meth:`ProposalStore.history` deliberately hands back
      :class:`~signal_agent.PriorProposal` values — feature 206's three-field
      type, with no model on them — so a count built on it would need a second
      query for the strata and a join in Python over a table SQLite groups in
      one statement.  But requiring the verb is what stops a caller handing over
      an arbitrary object that merely has a filesystem path, and that refusal
      is worth more than the call it does not make.

    The attributes are **checked here and used by :func:`tree_diversity`**, so
    an object refused for its shape is refused before the count has opened
    anything — feature 186's reasoning: a refusal that arrived after a
    connection had been made is a validation that ran too late to be one.
    """
    resolver = getattr(history, "history", None)
    if not callable(resolver):
        raise DiversityCohortError(
            f"tree_diversity counts feature 207's recorded proposals — got "
            f"{history!r} ({type(history).__name__}), which has no callable "
            f"``history``; the figure is a count over a campaign's proposal "
            f"documents, so an object that is not the proposal-history law "
            f"holds none for it to count (feature 215)."
        )
    path = getattr(history, "path", None)
    if path is None or not isinstance(path, Path):
        raise DiversityCohortError(
            f"tree_diversity reads a campaign's recorded proposals from the "
            f"store they live in — got {history!r} ({type(history).__name__}), "
            f"which names no ``path``; the count joins "
            f"{NODE_PROPOSAL_TABLE} to {NODE_TABLE} in one database, and where "
            f"the proposals live is where the tree lives (features 207/215)."
        )
    return path


def _has_history(connection: sqlite3.Connection) -> bool:
    """Whether the database holds a ``node_proposal`` table yet.

    ``sqlite_master`` is read and never the rows, which makes it a safe
    question to ask before the count — the probe feature 207 makes for the
    ``node`` table beside it.  It is asked rather than assumed because the two
    states it tells apart are different facts: a migrated deployment whose
    campaign has not proposed anything genuinely holds zero clusters, while a
    database this member's own DDL has never run in has no history at all — and
    the second must be refused rather than answered with the first's zero.
    """
    row = connection.execute(
        _HISTORY_EXISTS_SQL, (NODE_PROPOSAL_TABLE,)
    ).fetchone()
    return row is not None


def _tree_columns(connection: sqlite3.Connection) -> frozenset[str]:
    """The live ``node`` table's columns, the missing table refused by name.

    The stratification needs one column of the tree, so the tree has to be
    there and has to have reached the revision that adds it.  Both depths are
    one refusal each, and they are kept apart because the repairs differ: no
    ``node`` table is feature 97's revision, and a table without
    :data:`MODEL_COLUMN` is feature 100's.  Naming the losing revision is the
    whole actionable content — the discipline
    :class:`~signal_agent.MechanismColumnError` follows for its own column.
    """
    rows = connection.execute(_TREE_COLUMNS_SQL).fetchall()
    columns = frozenset(str(row[1]) for row in rows)
    if not columns:
        raise ProposalNodeNotRecordedError(
            f"the store at this path has no {NODE_TABLE} table, so there is no "
            f"tree to count a campaign's clusters in: feature 215's figure "
            f"groups {NODE_PROPOSAL_TABLE}'s proposals by the authoring model "
            f"{MODEL_COLUMN} records on each node, and a node is feature 97's "
            f"row, revision {NODE_POLICY_REVISION}. Run the migration chain to "
            f"there, then record the campaign (feature 215)."
        )
    if MODEL_COLUMN not in columns:
        raise DiversityCohortError(
            f"the {NODE_TABLE} table holds no {MODEL_COLUMN} column, so a "
            f"campaign's proposals cannot be counted *per authoring model*: the "
            f"column belongs to revision {MODEL_POLICY_REVISION} (feature 100), "
            f"and feature 215's sentence is *returns the figure per authoring "
            f"model* — a tree that has not reached it can answer no per-model "
            f"figure at all, and reporting one flat number in its place would "
            f"be a stratum this member invented. Run the migration chain to "
            f"{MODEL_POLICY_REVISION} (feature 215)."
        )
    return columns


def _named(rows: list[tuple[Any, ...]]) -> str:
    """Render a non-empty id list for a refusal, bounded like the member's own.

    The first few ids, so an operator reading a log sees *which* rows are the
    problem, with a count of the rest rather than a wall of UUIDs — the shape
    :data:`~signal_agent.MAX_LISTED_OFFENDERS` bounds for feature 206.
    """
    listed = ", ".join(str(row[0]) for row in rows[:5])
    if len(rows) > 5:
        listed += f" (and {len(rows) - 5} more)"
    return listed


def tree_diversity(history: Any, campaign_id: Any) -> TreeDiversity:
    """Count one campaign's distinct mechanism clusters, per authoring model.

    The one factory for feature 215's figure, the way
    :func:`bootstrap.world_census` is the one factory for its census: a
    proposal-history handle in, a :class:`TreeDiversity` out.  It answers the
    sentence whole — *"computes tree_diversity as the count of distinct
    mechanism clusters per campaign, which returns the figure per authoring
    model"* — by reading the clustering key and the stratum from one database
    in one connection, so the figure cannot describe a cohort other than the
    one the table holds.

    **A cluster is a distinct proposal document** (:data:`_CLUSTERS_SQL`, argued
    at the constant, with the two competing identities this member already owns
    and why neither is this one).  **The model is joined, never read from the
    rationale**, and the column that would tempt a caller —
    ``node.stated_mechanism`` — is not selected at all.

    Refuses, in this order, each naming what it is about:

    1. an object that is not feature 207's law or store — no callable
       ``history`` or no ``path`` — refused before anything touches the disk;
    2. a ``campaign_id`` that is not a UUID, and a database holding no
       ``node_proposal`` table (no history has ever been recorded in it, so
       there is nothing to count and a zero would be invented);
    3. a tree with no ``node`` table (feature 97's revision) or a ``node`` table
       without ``agent_model_id`` (feature 100's) — the per-model half of the
       sentence cannot be answered at all, so no flat number is offered in its
       place;
    4. a recorded proposal whose node the tree does not hold — the row the inner
       join would have dropped silently, looked for *before* the join runs so a
       lost node can never read as a smaller figure;
    5. a recorded proposal whose node carries no authoring model — a stratum no
       model answers to, refused rather than bucketed under an empty key.

    **A campaign with no recorded proposals answers zero**, and that is not the
    same state as (2): :class:`TreeDiversity` is returned with an empty
    :attr:`~TreeDiversity.by_model` and a zero denominator.  It is the honest
    state of a campaign that has not proposed yet — feature 207's *"a campaign
    that has not proposed anything yet"* — and refusing it would make the first
    call of every campaign an error.  The distinction is the one feature 186
    draws for its absent table, and it is drawn here in the opposite direction
    because zero is *not* a blocking figure for this metric: what it must never
    be is a figure this member invented about a database that has no history in
    it, which is why (2) refuses.

    Reads only.  The count writes no row to ``node_proposal``, none to ``node``
    and nothing to any file: taking a diversity reading can never change the
    figure the next reading reports, which is what makes it a measurement rather
    than an event in the campaign.
    """
    path = _proposal_history(history)
    campaign = _validated_campaign_id(campaign_id)
    with closing(sqlite3.connect(path)) as connection:
        if not _has_history(connection):
            raise ProposalHistoryStoreUnavailableError(
                f"the store at {path} holds no {NODE_PROPOSAL_TABLE} table, so "
                f"there is no recorded history to count a campaign's clusters "
                f"in — feature 215 counts the proposal documents feature 207 "
                f"persists, and a deployment whose store has never run that "
                f"member's own DDL has none. Answering zero here would be a "
                f"diversity figure this member invented rather than measured, "
                f"and zero is indistinguishable from the flattering reading "
                f"*this model wrote one mechanism* (feature 215)."
            )
        _tree_columns(connection)
        # The order of the next three reads is the feature's most load-bearing
        # ordering decision, so it is stated rather than left to the reader:
        # the orphan sweep runs FIRST, because the grouped read below is an
        # inner join and an orphan is exactly the row it would drop. Counting
        # first and reconciling afterwards would mean the figure had already
        # been computed from an incomplete cohort — and a reconciliation that
        # only ever runs after the fact is a check a caller can forget to make.
        orphans = connection.execute(_ORPHANS_SQL, (campaign,)).fetchall()
        if orphans:
            raise ProposalNodeNotRecordedError(
                f"{len(orphans)} recorded proposal(s) in this campaign name a "
                f"node the tree does not hold ({_named(orphans)}): feature 215 "
                f"groups each proposal by the authoring model its node records, "
                f"so a proposal whose node is gone has no stratum to be counted "
                f"under. Feature 207 refuses this state at write time — a "
                f"proposal is recorded against a node the tree holds — so these "
                f"rows are a database that has lost nodes, and dropping them "
                f"would understate the figure for exactly the model whose nodes "
                f"went missing (feature 215)."
            )
        unmodelled = connection.execute(_UNMODELLED_SQL, (campaign,)).fetchall()
        if unmodelled:
            raise DiversityCohortError(
                f"{len(unmodelled)} recorded proposal(s) in this campaign have "
                f"a node with no {MODEL_COLUMN} ({_named(unmodelled)}): "
                f"revision {MODEL_POLICY_REVISION} declares that column NOT "
                f"NULL because every node is authored by exactly one model, so "
                f"a node without one is either a tree the chain has not reached "
                f"or a row a hand has been to. Feature 215's figure is returned "
                f"*per authoring model*, and a bucket that is not a model would "
                f"print beside the real strata as though it were one of them "
                f"(feature 215)."
            )
        (cohort,) = connection.execute(_COHORT_SQL, (campaign,)).fetchone()
        groups = connection.execute(_CLUSTERS_SQL, (campaign,)).fetchall()
    return TreeDiversity(
        campaign_id=campaign,
        by_model={str(model): int(clusters) for model, clusters in groups},
        proposals=int(cohort),
    )
