"""The live tree — a running campaign's node rows, as a policy's question.

additions_spec_campaign_driver.xml, "Exploration Policy" category, feature 3:
*System creates a live policy question over a running campaign with
orchestrator._live_tree.live_question(campaign_id, *, database_url,
evaluation_periods, budget=None).  It answers a policy_runtime.PolicyQuestion
over a CampaignTree frozen from the campaign's node rows.*  policy_runtime
owns the question's whole vocabulary (feature 217's ``PolicyQuestion``,
feature 184's prefix-only law, feature 221's budget) and the ``node`` table
is the tree member's own (migrations ``0118``, ``0114``); this module is the
one object that joins them, the same shape :mod:`orchestrator._tree_writer`
and :mod:`orchestrator._oracle` already give the table's other two seams. It
is deliberately the smallest thing that can: one query, one freeze, one
reveal, one function.

**Every call rebuilds the tree, and that is the whole freshness story.**
:func:`live_question` opens no persistent handle and remembers nothing
between calls — it reads the campaign's rows, freezes a fresh
:class:`~policy_runtime.CampaignTree` over them and hands back a fresh
:class:`~policy_runtime.PolicyQuestion`.  A round of the campaign loop (spec
B, feature 6) calls this once per round, so a child a worker planted in round
``N`` is a row this query finds in round ``N + 1`` without this module having
to notice it was written — the tree is a read, not a subscription.

**The payload is the four fields the feature names, plus the one key a
cell's family is read from — and nothing else.**  An evaluated node's payload
is ``{ic_insample: value, r2_insample: ic_mean ** 2, n_periods:
evaluation_periods, n_features: 1, theme_root: theme}`` — the four keys
:meth:`~policy_runtime.PolicyObservation.from_node` reads by name, so a
policy's :meth:`~policy_runtime.PolicyQuestion.observed` renders this node's
honest in-sample reading, plus ``theme_root``, the one key
:func:`~policy_runtime.cell_meta` reads (its own
``policy_runtime.meta.THEME_ROOT_KEY``, spelled exactly as the node table's
column is), so a policy conditioning on family
(:mod:`policy_runtime.families`, feature 228) sees in a financial tree the
theme bootstrap worlds state as ``BOOTSTRAP_THEME_ROOT``.  ``r2_insample`` is
derived rather than read a second time: the live evaluator (spec A) measures
information coefficient, not a second R², and ``ic_mean ** 2`` is the live
run's own stand-in for it — this module states that substitution once rather
than leaving every caller to reinvent it.  ``n_features`` is the constant
``1``: spec A's live evaluator scores one authored signal per node, never a
feature set, so every node this tree can hold names exactly one.
``theme_root`` is the row's own column carried verbatim — ``None`` when the
column is absent or the row's value is ``NULL``, never normalised — because
which themes may exist is feature 241's committed config, not this module's
to restate.

**``ic_insample`` carries the post-cost value when the row has one
(additions_spec_cost_aware_selection.xml, "Cost-Aware Selection", feature
3), and close-out's own fallback otherwise (bug_spec fix: the m2 incumbent
equivalence).**  ``value`` above is ``ir_tstat`` when the row's ``ir_tstat``
is not ``NULL`` and either ``ic_tstat`` is unknown or positive — the sign
leg :mod:`orchestrator.closeout`'s own ``_is_discovery`` checks before
trusting ``ir_tstat`` — ``ic_tstat`` when that row carries one, and
``ic_mean`` only when neither reading is available (a row a test plants
with no ``ic_tstat`` at all).  This restates
:func:`orchestrator.closeout._selection_value`'s own fallback, which reads
``ic_tstat``, not ``ic_mean``, for a node with no ``ir_tstat`` — the
distinction :mod:`deploy.dreaming.incumbent.m2` depends on to reproduce
close-out's commit, since ``ic_mean`` and ``ic_tstat`` are different
readings of the same node and need not agree.
:class:`~policy_runtime.PolicyObservation` carries exactly one numeric field
a ranking policy reads (``ic_insample``; :mod:`orchestrator._policy`'s
``BaselinePolicy`` sorts by nothing else), so giving the policy post-cost
evidence without a second field — one :mod:`policy_runtime` does not carry
and this spec does not add — means reusing the one field the view already
has.  This is the "one place" the feature's own sentence names: the rename
happens here, in this payload, and nowhere downstream.  ``r2_insample`` is
unaffected — it stays ``ic_mean``'s own square, the live evaluator's
in-sample R² stand-in, never ``ir_tstat``'s or ``ic_tstat``'s.

**A node with no metrics freezes a metric-free payload — its theme and
nothing else — and is never revealed.**  ``ic_mean IS NULL`` means the node
failed or has not reached evaluation yet — the same fact
:mod:`orchestrator._tree_writer` reads off the row, since the six core
metrics land in one transaction or not at all.  Such a node's payload is
``{theme_root: theme}`` (``{theme_root: None}`` when the row states no
theme), not the bare JSON ``null`` the feature sentence's prose might
suggest: a :class:`~policy_runtime.CampaignNode` demands a payload that is
canonical JSON, and a mapping is what keeps every *other* read this tree
answers for an unmeasured node honest — :func:`~policy_runtime.cell_meta`
reads ``theme_root`` off *every* node's payload, revealed or not (docs §11.1
is explicit that structure is not the thing the barrier withholds), and a
bare ``null`` there would turn a policy's ``meta()`` call into a crash rather
than the honest "this cell states no family" a ``None`` value answers as
cleanly as an absent key.  The *effect* the feature's sentence names is
produced instead where it has to be: this module never calls
:meth:`~policy_runtime.PolicyQuestion.reveal` or
:meth:`~policy_runtime.PolicyQuestion.reveal_many` for a node whose
``ic_mean`` is ``NULL``, so :meth:`~policy_runtime.PolicyQuestion.observed`
never names it and a policy never sees it — "not revealed" is a fact about
the reveal set this module builds, not about what the frozen node's bytes
say.

**Every evaluated node is revealed, once, through one batch call.**  The
rows are partitioned once into the tree's full node set and the subset whose
``ic_mean`` is not ``NULL``; the full set freezes the tree (so an unmeasured
node is still a legal frontier move — :func:`~policy_runtime.legal_actions`
is a pure function of the tree and must see it) and the evaluated subset is
handed to :meth:`~policy_runtime.PolicyQuestion.reveal_many` in one call, so
the batch is validated against the tree it was just built from and reveals in
one ascending pass rather than one :meth:`reveal` per row.

**The module reads five columns and nothing else, plus the two optional
columns.**  ``id``, ``parent_id`` and ``depth`` are the tree's
own structural skeleton (migration ``0118``, feature 97); ``ic_mean``
(migration ``0114``, feature 101) is read because it is the reveal witness
(by the tree writer's own all-or-nothing contract, a non-``NULL`` ``ic_mean``
means the row's other five core metrics landed too — a second column would
read a fact this one already carries) and the source of ``r2_insample``;
``ic_tstat``, added by the same migration and read unconditionally beside
it (never probed — a tree old enough to carry ``ic_mean`` carries this
sibling column too), is ``ic_insample``'s fallback whenever the row carries
no usable ``ir_tstat``, matching :func:`orchestrator.closeout.
_selection_value`'s own fallback rather than restating ``ic_mean`` under a
different name.  ``ir_tstat`` (additions_spec_cost_aware_selection.xml,
feature 1) is read in the same query, *probed* rather than demanded: feature
1 adds the column by probe-then-``ALTER`` in the tree writer rather than a
migration, so a tree a live evaluation has not yet written through still
carries ``0114``'s seven columns and no eighth, and :func:`_load_rows` reads
``PRAGMA table_info`` first and selects ``ir_tstat`` only when the probe
finds it — never a bare ``SELECT`` that would raise ``no such column`` on
every tree feature 1 has not touched yet.  ``theme_root`` is read the same
way — probed, then selected when the probe finds it — and carried onto every
cell's payload under the one key :func:`~policy_runtime.cell_meta` reads,
so a policy that reaches for a cell's family through ``meta()`` reads the
theme its branch was planted in (what bootstrap worlds state as
``BOOTSTRAP_THEME_ROOT``) instead of ``None`` for every cell this tree
freezes; unlike ``ir_tstat`` the column is migration-guaranteed
(migration ``0113``'s skeleton has carried ``theme_root`` since the table
was first created), so the probe is symmetry with the one beside it rather
than a state the chain can produce, and a table without the column — or a
row whose value is ``NULL`` — answers ``None`` per cell rather than
refusing.  Nothing else on the row is read:
not the identity, provenance or authoring-model columns, and never
the null sidecar or an ``is_null`` bit — the standing constraint this spec
repeats at every seam that touches a node (:mod:`orchestrator._oracle`,
:mod:`orchestrator._charge`): the sidecar is ``nulloracle.TypeRSelection``'s
alone to read.

**One error, for the wiring; the question's own for everything else.**  A
``database_url`` this module cannot speak, a campaign with no node rows yet,
or a database the ``node`` migration has not reached, are facts about how
this call was made and are refused with :class:`LiveTreeError`, naming what
was wrong.  A malformed tree the rows themselves would produce — a dangling
``parent_id``, a cycle — is :class:`~policy_runtime.PolicyTreeError`, and a
``budget`` that does not answer ``remaining`` honestly is
:class:`~policy_runtime.PolicyBudgetError`: both are refusals
``policy_runtime`` already owns the vocabulary for, propagated unchanged
rather than re-spelled here (the stance :mod:`orchestrator._charge` takes at
the evaluator's seam, for the same reason).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from policy_runtime import CampaignTree, PolicyQuestion

__all__ = [
    "LIVE_TREE_CODE",
    "LiveTreeError",
    "live_question",
]

#: The environment variable naming the relational store — the one spelling
#: the workspace's stores share, restated here so this module states its own
#: contract rather than importing another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table every column below is read from — migration ``0118``'s ``node``
#: table, the same one :mod:`orchestrator._tree_writer` updates and
#: :mod:`orchestrator._oracle` walks.
NODE_TABLE = "node"

#: The node's key column — ``0118``'s ``id``, the value this module freezes
#: as a :class:`~policy_runtime.CampaignNode`'s ``node_id``.
NODE_ID_COLUMN = "id"

#: The self-referencing edge — ``0118``'s ``parent_id`` — frozen unchanged as
#: each node's ``parent_id``.
PARENT_ID_COLUMN = "parent_id"

#: The node's own depth — ``0118``'s ``depth`` — frozen unchanged.
DEPTH_COLUMN = "depth"

#: The column every node row is scoped by.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The metric column that decides whether a row has been evaluated at all —
#: migration ``0114``'s ``ic_mean``.  Because the tree writer lands its six
#: core metrics in one transaction or none, a non-``NULL`` reading here is a
#: reliable witness that the row's other five core metrics landed too; see
#: the module docstring for why a second metric column would read a fact
#: this one already carries.  It is also ``ic_insample``'s last-resort
#: fallback — read only when neither :data:`IR_TSTAT_COLUMN` nor
#: :data:`IC_TSTAT_COLUMN` has a usable reading on the row (a row a test
#: plants with no ``ic_tstat`` at all; a real evaluation always writes both).
METRIC_COLUMN = "ic_mean"

#: The column migration ``0114`` adds beside :data:`METRIC_COLUMN` — read
#: unconditionally in the same query, never probed, because the two land in
#: the same ``ALTER TABLE`` chain.  Preferred over :data:`METRIC_COLUMN` for
#: ``ic_insample`` whenever the row carries one: this is
#: :func:`orchestrator.closeout._selection_value`'s own fallback for a node
#: with no ``ir_tstat``, and matching it (rather than ``ic_mean``, a
#: different reading of the same node) is what lets
#: :mod:`deploy.dreaming.incumbent.m2` reproduce close-out's commit.
IC_TSTAT_COLUMN = "ic_tstat"

#: The post-cost column feature 3 adds to ``ic_insample``
#: (additions_spec_cost_aware_selection.xml, "Cost-Aware Selection", feature
#: 3) — feature 1's ``ir_tstat``, added to the ``node`` table by
#: probe-then-``ALTER`` in the tree writer rather than a migration, so it is
#: read only when :func:`_load_rows`'s own probe finds it on the row's table.
#: Preferred over :data:`IC_TSTAT_COLUMN` for ``ic_insample`` whenever the
#: row carries a non-``NULL`` value and the row's own ``ic_tstat`` is either
#: unknown or positive — the sign leg :mod:`orchestrator.closeout`'s
#: ``_is_discovery`` checks before trusting ``ir_tstat``, per the module
#: docstring.
IR_TSTAT_COLUMN = "ir_tstat"

#: The column every cell's family is read from — migration ``0113``'s own
#: ``theme_root``, the research theme the node's root was planted in (§9.1's
#: ``theme_root TEXT NOT NULL``, written at plant time by
#: :mod:`orchestrator._roots`, never by evaluation).  Carried verbatim onto
#: every cell's payload — evaluated or not — under the column's own name,
#: which is the one key :func:`policy_runtime.cell_meta` reads
#: (``policy_runtime.meta.THEME_ROOT_KEY``), so family conditioning
#: (:mod:`policy_runtime.families`, feature 228) sees in a financial tree
#: what bootstrap worlds state as ``BOOTSTRAP_THEME_ROOT``.  Probed rather
#: than demanded — selected only when :func:`_load_rows`'s own probe finds
#: it on the row's table, the same probe-then-select
#: :data:`IR_TSTAT_COLUMN` is read through — so a table without the column
#: answers ``None`` per cell rather than raising; a ``NULL`` value reads
#: the same.  The value is never normalised: which themes may exist is
#: feature 241's committed config, not this module's to restate.
THEME_ROOT_COLUMN = "theme_root"

#: The constant every evaluated node's payload carries for ``n_features``:
#: spec A's live evaluator scores one authored signal per node, never a
#: feature set, so every node this tree can hold names exactly one.
N_FEATURES = 1

#: The greppable word that opens every :class:`LiveTreeError` message — a
#: caller greps one word for *this call to live_question was wired wrong* and
#: reaches every face of it (a bad URL, an unmigrated database, a campaign
#: with no rows yet).
LIVE_TREE_CODE = "live_tree"

#: The migration that owns the ``node`` table, named in the refusal a
#: database the chain has not reached produces — because SQLite's own "no
#: such table: node" names the table but not the feature that creates it.
_NODE_MIGRATION = "migrations/versions/0118_node_table.py"


class LiveTreeError(Exception):
    """A wiring fault of :func:`live_question` — never a fact about one node.

    Everything this class carries is a fact about *how the call was made*
    rather than about any one row the tree holds: a ``database_url`` this
    module cannot speak (a non-SQLite scheme, a host, a pathless in-memory
    URL), a ``campaign_id`` or ``evaluation_periods`` that names nothing, a
    database the ``node`` migration has not reached, or a campaign whose tree
    holds no node at all.  A malformed *tree* the rows themselves would
    produce — a dangling parent reference, a parent cycle — is
    :class:`~policy_runtime.PolicyTreeError`, raised by
    :class:`~policy_runtime.CampaignTree` itself and left unwrapped, because
    that refusal already names the node and the defect and a second class
    here would only separate one caller's ``except`` from the fact that
    refused it.
    """


def live_question(
    campaign_id: str,
    *,
    database_url: str,
    evaluation_periods: int,
    budget: Any = None,
) -> PolicyQuestion:
    """Build a fresh :class:`~policy_runtime.PolicyQuestion` over one campaign's rows.

    Reads every node the campaign has planted — ``id``, ``parent_id``,
    ``depth``, ``ic_mean``, ``ic_tstat``, ``theme_root`` and, when the row's
    table carries it, ``ir_tstat`` — and freezes them into a
    :class:`~policy_runtime.CampaignTree`.  A node whose ``ic_mean`` is
    ``NULL`` (not yet evaluated, or failed before landing one) freezes a
    payload of ``theme_root`` alone and is left out of the reveal; every
    other node's payload is ``{ic_insample: value, r2_insample:
    ic_mean ** 2, n_periods: evaluation_periods, n_features: 1, theme_root:
    theme}``, where ``value`` is the node's
    ``ir_tstat`` when it is not ``NULL`` and the row's own ``ic_tstat`` is
    either unknown or positive (additions_spec_cost_aware_selection.xml,
    "Cost-Aware Selection", feature 3, folded with
    :func:`orchestrator.closeout._is_discovery`'s sign check), the row's
    ``ic_tstat`` when that is known, and ``ic_mean`` only when neither is —
    the fallback :func:`orchestrator.closeout._selection_value` itself takes
    for a node with no ``ir_tstat``, which is what lets
    :mod:`deploy.dreaming.incumbent.m2` reproduce close-out's own commit over
    this payload.  ``theme_root`` is the row's own column carried verbatim
    on every cell — ``None`` when the column is absent or the value is
    ``NULL`` — under the one key :func:`~policy_runtime.cell_meta` reads.
    The payload is revealed, in one
    :meth:`~policy_runtime.PolicyQuestion.reveal_many` call, before this
    function returns — so the question a caller receives already answers
    :meth:`~policy_runtime.PolicyQuestion.observed` for every evaluated node
    without a second call.

    ``budget``, when given, is forwarded to
    :class:`~policy_runtime.PolicyQuestion` untouched — build one with
    :func:`policy_runtime.budget_account`, or pass ``None`` for a deployment
    that states no statistical ceiling; a value that does not answer
    ``remaining`` honestly raises
    :class:`~policy_runtime.PolicyBudgetError`, the question's own refusal.

    Refuses with :class:`LiveTreeError` a ``campaign_id`` or
    ``evaluation_periods`` that names nothing, a ``database_url`` this module
    cannot speak, a database the ``node`` migration has not reached, or a
    campaign whose tree holds no node row at all — a running campaign always
    plants its roots before a policy is ever asked (spec B, feature 6), so an
    empty tree here means the campaign was never planted or the id is wrong,
    and a vacuous question is not one a policy could be handed.
    """
    campaign = _campaign_id(campaign_id)
    periods = _evaluation_periods(evaluation_periods)
    path = _resolve_path(database_url)
    rows = _load_rows(path, campaign, database_url=database_url)
    if not rows:
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: the tree at {database_url!r} holds no node "
            f"for campaign {campaign!r}; a live question fronts the nodes a "
            "campaign has already planted, and a campaign with none yet has "
            "no tree a policy could be asked over (feature 3)"
        )
    node_specs: dict[str, tuple[str | None, int, dict[str, Any]]] = {}
    evaluated: list[str] = []
    for node_id, parent_id, depth, ic_mean, ic_tstat, ir_tstat, theme_root in rows:
        if ic_mean is None:
            node_specs[node_id] = (parent_id, depth, {"theme_root": theme_root})
            continue
        if ir_tstat is not None and (ic_tstat is None or ic_tstat > 0):
            value = ir_tstat
        elif ic_tstat is not None:
            value = ic_tstat
        else:
            value = ic_mean
        node_specs[node_id] = (
            parent_id,
            depth,
            {
                "ic_insample": value,
                "r2_insample": ic_mean**2,
                "n_periods": periods,
                "n_features": N_FEATURES,
                "theme_root": theme_root,
            },
        )
        evaluated.append(node_id)
    tree = CampaignTree.freeze(node_specs)
    question = PolicyQuestion(tree, budget)
    if evaluated:
        question.reveal_many(evaluated)
    return question


# -- Validating the call's own terms -------------------------------------------


def _campaign_id(campaign_id: Any) -> str:
    """The campaign id, stripped — refused by name when it names nothing."""
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: live_question needs a non-empty campaign_id "
            f"naming the campaign whose tree is being asked, got "
            f"{campaign_id!r} (feature 3)"
        )
    return campaign_id.strip()


def _evaluation_periods(evaluation_periods: Any) -> int:
    """``evaluation_periods``, as the positive int every payload's ``n_periods`` needs."""
    if (
        isinstance(evaluation_periods, bool)
        or not isinstance(evaluation_periods, int)
        or evaluation_periods <= 0
    ):
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: evaluation_periods must be a positive integer "
            "— the number of periods the live evaluator measured over, "
            f"carried onto every evaluated node's payload as n_periods — got "
            f"{evaluation_periods!r} ({type(evaluation_periods).__name__}) "
            "(feature 3)"
        )
    return evaluation_periods


# -- Reading the rows, as the table holds them ---------------------------------


def _resolve_path(database_url: Any) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The grammar every store in this workspace restates: a non-SQLite scheme
    is refused by name (this module speaks one dialect), a host is refused,
    and a pathless URL — SQLite's in-memory spelling — is refused because a
    live campaign's tree must outlive the connection that reads it and is
    written by a process other than this one.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: {DATABASE_URL_ENV} must be a non-empty "
            f"database URL naming the tree a live question is built over, "
            f"got {database_url!r} (feature 3)"
        )
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: live_question speaks sqlite:/// (the spec's "
            f"single-machine allowance); point {DATABASE_URL_ENV} at the "
            "sqlite database the node table lives in (feature 3)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: sqlite {DATABASE_URL_ENV} must not carry a "
            f"host, got {parsed.netloc!r} (feature 3)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: sqlite {DATABASE_URL_ENV} carries no database "
            "path: an in-memory tree would die with the connection that read "
            "it, and a live question must read the rows a running campaign "
            "actually wrote (feature 3)"
        )
    return Path(path)


def _load_rows(
    path: Path, campaign_id: str, *, database_url: str
) -> list[
    tuple[str, str | None, int, float | None, float | None, float | None, str | None]
]:
    """The campaign's node rows — ``(id, parent_id, depth, ic_mean, ic_tstat,
    ir_tstat, theme_root)``, ascending by id.

    Reads exactly these five columns, plus two more each probed rather than
    demanded — see the module docstring for why ``ic_mean`` alone stands in
    for "this node has been evaluated", why ``ic_tstat`` is read
    unconditionally beside it (the same migration adds both), and why
    ``ir_tstat`` and ``theme_root`` are read only when
    :func:`_node_table_columns` finds them on the row's own table.  A table
    that lacks a column answers it as ``None`` for every row, the same
    reading a ``NULL`` value there would give — a tree feature 1 has not
    written through yet carries no post-cost evidence, and a table with no
    ``theme_root`` column states no family per cell, which are exactly the
    fallback cases. A database the ``node`` migration has not reached
    answers :class:`LiveTreeError` naming the migration; any other store
    fault is the same class, naming the error SQLite gave.
    """
    try:
        with closing(sqlite3.connect(path)) as connection:
            columns = _node_table_columns(connection)
            select_columns = [
                NODE_ID_COLUMN,
                PARENT_ID_COLUMN,
                DEPTH_COLUMN,
                METRIC_COLUMN,
                IC_TSTAT_COLUMN,
            ]
            if IR_TSTAT_COLUMN in columns:
                select_columns.append(IR_TSTAT_COLUMN)
            if THEME_ROOT_COLUMN in columns:
                select_columns.append(THEME_ROOT_COLUMN)
            cursor = connection.execute(
                f"SELECT {', '.join(select_columns)} FROM {NODE_TABLE} WHERE "
                f"{CAMPAIGN_ID_COLUMN} = ? ORDER BY {NODE_ID_COLUMN}",
                (campaign_id,),
            )
            fetched = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise LiveTreeError(
                f"{LIVE_TREE_CODE}: could not read the node table at "
                f"{database_url!r}: {exc} (feature 3)"
            ) from exc
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: the tree at {database_url!r} holds no node "
            f"table yet — {_NODE_MIGRATION} must have created it before a "
            "live question can be built over it (feature 3)"
        ) from exc
    except sqlite3.Error as exc:
        raise LiveTreeError(
            f"{LIVE_TREE_CODE}: could not read the node table at "
            f"{database_url!r}: {exc} (feature 3)"
        ) from exc
    return [
        (
            str(values[NODE_ID_COLUMN]),
            (str(values[PARENT_ID_COLUMN]) if values[PARENT_ID_COLUMN] is not None else None),
            int(values[DEPTH_COLUMN]),
            (float(values[METRIC_COLUMN]) if values[METRIC_COLUMN] is not None else None),
            (float(values[IC_TSTAT_COLUMN]) if values[IC_TSTAT_COLUMN] is not None else None),
            (float(values[IR_TSTAT_COLUMN]) if values.get(IR_TSTAT_COLUMN) is not None else None),
            values.get(THEME_ROOT_COLUMN),
        )
        for values in (dict(zip(select_columns, row)) for row in fetched)
    ]


def _node_table_columns(connection: sqlite3.Connection) -> set[str]:
    """The ``node`` table's own column names — the probe behind both optional
    reads.

    ``PRAGMA table_info`` on a table that does not exist yet answers no rows
    at all rather than raising, so a database the ``node`` migration has not
    reached reads as holding neither :data:`IR_TSTAT_COLUMN` nor
    :data:`THEME_ROOT_COLUMN` here and then fails on the ``SELECT`` moments
    later with its own ``no such table`` — :meth:`_load_rows`'s existing
    refusal, not a new one this probe would have to race.  The probe itself
    never raises.
    """
    return {
        row[1] for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})").fetchall()
    }
