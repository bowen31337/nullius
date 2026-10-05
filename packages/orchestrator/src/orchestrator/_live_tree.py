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

**The payload is the four fields the feature names, and nothing it does
not.**  An evaluated node's payload is ``{ic_insample: ic_mean, r2_insample:
ic_mean ** 2, n_periods: evaluation_periods, n_features: 1}`` — exactly the
four keys :meth:`~policy_runtime.PolicyObservation.from_node` reads by name,
so a policy's :meth:`~policy_runtime.PolicyQuestion.observed` renders this
node's honest in-sample reading.  ``r2_insample`` is derived rather than read
a second time: the live evaluator (spec A) measures information coefficient,
not a second R², and ``ic_mean ** 2`` is the live run's own stand-in for it —
this module states that substitution once rather than leaving every caller to
reinvent it.  ``n_features`` is the constant ``1``: spec A's live evaluator
scores one authored signal per node, never a feature set, so every node this
tree can hold names exactly one.

**A node with no metrics freezes an empty payload, and is never revealed.**
``ic_mean IS NULL`` means the node failed or has not reached evaluation yet —
the same fact :mod:`orchestrator._tree_writer` reads off the row, since the
six core metrics land in one transaction or not at all.  Such a node's payload
is ``{}``, not the bare JSON ``null`` the feature sentence's prose might
suggest: a :class:`~policy_runtime.CampaignNode` demands a payload that is
canonical JSON, and ``{}`` is what keeps every *other* read this tree answers
for an unmeasured node honest — :func:`~policy_runtime.cell_meta` reads
``theme_root`` off *every* node's payload, revealed or not (docs §11.1 is
explicit that structure is not the thing the barrier withholds), and a bare
``null`` there would turn a policy's ``meta()`` call into a crash rather than
the honest "this cell states no family" an absent key already answers.  The
*effect* the feature's sentence names is produced instead where it has to be:
this module never calls :meth:`~policy_runtime.PolicyQuestion.reveal` or
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

**The module reads four columns and nothing else.**  ``id``, ``parent_id``
and ``depth`` are the tree's own structural skeleton (migration ``0118``,
feature 97); ``ic_mean`` (migration ``0114``, feature 101) is read because it
is both this payload's ``ic_insample`` and, by the tree writer's own
all-or-nothing contract, a reliable witness that the row's other five core
metrics landed too — a second column would read a fact this one already
carries.  Nothing else on the row is read: not ``theme_root`` (the database
column; this payload carries no ``theme_root`` key, so a policy that reaches
for one through :func:`~policy_runtime.cell_meta` reads ``None`` for every
cell this tree freezes), not the identity, provenance or authoring-model
columns, and never the null sidecar or an ``is_null`` bit — the standing
constraint this spec repeats at every seam that touches a node
(:mod:`orchestrator._oracle`, :mod:`orchestrator._charge`): the sidecar is
``nulloracle.TypeRSelection``'s alone to read.

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

#: The one metric column this module reads — migration ``0114``'s
#: ``ic_mean``.  It is both the payload's ``ic_insample`` and, because the
#: tree writer lands its six core metrics in one transaction or none, the
#: reliable witness that a row has been evaluated at all; see the module
#: docstring for why a second metric column would read a fact this one
#: already carries.
METRIC_COLUMN = "ic_mean"

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
    ``depth`` and ``ic_mean`` — and freezes them into a
    :class:`~policy_runtime.CampaignTree`.  A node whose ``ic_mean`` is
    ``NULL`` (not yet evaluated, or failed before landing one) freezes an
    empty payload and is left out of the reveal; every other node's payload
    is ``{ic_insample: ic_mean, r2_insample: ic_mean ** 2, n_periods:
    evaluation_periods, n_features: 1}`` and is revealed, in one
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
    for node_id, parent_id, depth, ic_mean in rows:
        if ic_mean is None:
            node_specs[node_id] = (parent_id, depth, {})
            continue
        node_specs[node_id] = (
            parent_id,
            depth,
            {
                "ic_insample": ic_mean,
                "r2_insample": ic_mean**2,
                "n_periods": periods,
                "n_features": N_FEATURES,
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
) -> list[tuple[str, str | None, int, float | None]]:
    """The campaign's node rows — ``(id, parent_id, depth, ic_mean)``, ascending by id.

    Reads exactly these four columns and nothing else on the row — see the
    module docstring for why ``ic_mean`` alone stands in for "this node has
    been evaluated".  A database the ``node`` migration has not reached
    answers :class:`LiveTreeError` naming the migration; any other store
    fault is the same class, naming the error SQLite gave.
    """
    try:
        with closing(sqlite3.connect(path)) as connection:
            cursor = connection.execute(
                f"SELECT {NODE_ID_COLUMN}, {PARENT_ID_COLUMN}, {DEPTH_COLUMN}, "
                f"{METRIC_COLUMN} FROM {NODE_TABLE} WHERE "
                f"{CAMPAIGN_ID_COLUMN} = ? ORDER BY {NODE_ID_COLUMN}",
                (campaign_id,),
            )
            rows = cursor.fetchall()
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
            str(node_id),
            (str(parent_id) if parent_id is not None else None),
            int(depth),
            (float(ic_mean) if ic_mean is not None else None),
        )
        for node_id, parent_id, depth, ic_mean in rows
    ]
