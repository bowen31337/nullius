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
KsGuard` writes the campaign's detectability p-value; 2)
:class:`nulloracle.CampaignVerdict` reads that stored p-value back and
pronounces ``VOID`` or leaves the campaign ``ok``; 3)
:meth:`scoring.NullPickScorer.calibration_figures` answers sensitivity and
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
import json
import os
import sqlite3
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
import scoring

from ._oracle import OracleTargetError, SubtreeOracle

__all__ = [
    "CLOSEOUT_CODE",
    "CLOSEOUT_UNEVALUATED_CODE",
    "DATABASE_URL_ENV",
    "DISCOVERY_TSTAT",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_VOID",
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
    """

    campaign_id: str
    ks_pvalue: float
    calibration_status: str
    sensitivity: float
    specificity: float
    fdr_deploy: float
    type_b: int | None
    discoveries: int
    budget_charging_trials: int
    ledger_trials: int

    @property
    def is_void(self) -> bool:
        """Whether the campaign's verdict is VOID."""
        return self.calibration_status == nulloracle.CALIBRATION_STATUS_VOID

    def to_payload(self) -> dict[str, Any]:
        """The result as the one JSON line this command prints.

        Never a node id beside a null label (PRD §4.2): every field here is
        a campaign-level aggregate -- a p-value, a status, two fractions, a
        count -- and none of them is a node's own identity.
        """
        return {
            "campaign_id": self.campaign_id,
            "ks_pvalue": self.ks_pvalue,
            "calibration_status": self.calibration_status,
            "sensitivity": self.sensitivity,
            "specificity": self.specificity,
            "fdr_deploy": self.fdr_deploy,
            "type_b": self.type_b,
            "discoveries": self.discoveries,
            "budget_charging_trials": self.budget_charging_trials,
            "ledger_trials": self.ledger_trials,
        }


@dataclass(frozen=True)
class _EvaluatedNode:
    """One evaluated node's in-sample reading -- the bit this module reads
    the sidecar for, and the score the KS guard and the discovery bar read."""

    node_id: str
    ic_mean: float
    ic_tstat: float


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
        if _has_column(connection, NODE_TABLE, "fail_class"):
            query = (
                f"SELECT id, fail_class, ic_mean, ic_tstat FROM {NODE_TABLE} "
                "WHERE campaign_id = ?"
            )
        else:
            query = (
                f"SELECT id, 'ok', ic_mean, ic_tstat FROM {NODE_TABLE} "
                "WHERE campaign_id = ?"
            )
        try:
            rows = connection.execute(query, (campaign_id,)).fetchall()
        except sqlite3.Error as exc:
            raise CloseoutError(
                f"{CLOSEOUT_CODE}: could not read campaign {campaign_id!r}'s "
                f"evaluated nodes from {database_url!r}: {exc}"
            ) from exc
    evaluated: list[_EvaluatedNode] = []
    for node_id, fail_class, ic_mean, ic_tstat in rows:
        # A NULL fail_class on a row with metrics is an evaluated node: the
        # root evaluation path writes metrics but no fail_class, and a row
        # with no recorded failure is one where nothing has failed. Dropping
        # it left campaign 90d95c6d's ten scored roots out of the KS split.
        if fail_class not in (None, "ok") or ic_mean is None or ic_tstat is None:
            continue
        evaluated.append(
            _EvaluatedNode(node_id=node_id, ic_mean=ic_mean, ic_tstat=ic_tstat)
        )
    return tuple(evaluated)


def close_out(
    campaign_id: str,
    *,
    database_url: str,
    scorer: scoring.NullPickScorer,
    sidecar: Any,
) -> CloseoutResult:
    """Close out one campaign -- feature 13's whole sentence, one call.

    ``scorer`` is the resolved :class:`scoring.NullPickScorer` (feature
    265's process); ``sidecar`` is the resolved :class:`nulloracle.
    NullSidecar` the same deployment names -- held separately because the
    scorer's own law lets no label or sidecar accessor out, and the split
    this function runs for the KS guard is this process's own read, not
    the scorer's verb.

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

    root_ids = _read_campaign_root_ids(database_url, campaign)
    roots = frozenset(root_ids)
    evaluated = _read_evaluated_nodes(database_url, campaign)
    root_oracle = SubtreeOracle(_NoPostEndpoint(), database_url=database_url)

    null_scores: list[float] = []
    real_scores: list[float] = []
    discoveries: list[str] = []
    discovery_roots: list[str] = []
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
        if node.ic_tstat >= DISCOVERY_TSTAT:
            discoveries.append(node.node_id)
            discovery_roots.append(root_id)

    # 1. The KS guard, over the in-sample scores split above -- only the
    #    two lists reach it, never a node id.
    ks_record = nulloracle.KsGuard(database_url).guard(
        campaign, null_scores, real_scores
    )
    # 2. The verdict, read back off the p-value the guard just persisted.
    verdict = nulloracle.CampaignVerdict(database_url).void_if_detectable(campaign)

    # 3. The calibration figures, over the planted roots and the
    #    campaign's discoveries, each mapped to its root -- the scorer's
    #    own verb collapses a subtree's repeated discoveries into one pick.
    figures = scorer.calibration_figures(population=root_ids, picks=discovery_roots)
    # 4. FDR_deploy, reweighted and persisted from that pair.
    fdr_value = scoring.FdrDeployStore(database_url).persist(campaign, figures)
    # 5. The pair itself, persisted for the dashboard's trend.
    ops.NullCalibrations(database_url).record(
        campaign, sensitivity=figures.sensitivity, specificity=figures.specificity
    )

    type_b: int | None = None
    if record.campaign_type == discovery.TYPE_D_CAMPAIGN_TYPE:
        # 6. Type-B depth past the flip, Type-D campaigns only -- each
        #    evaluated node's depth and its branch's flip, joined by the
        #    oracle's own resolution rather than restated here.  Resolved
        #    by the node's own id (never the root): a Type-D node's
        #    branch -- and the flip it may sit past -- is a fact of depths
        #    the oracle reads straight off the tree, not of the sidecar,
        #    so it is not refused for a child the way the sidecar's own
        #    per-root entries would be.
        oracle = nulloracle.TypeDOracle(database_url)
        explored = [
            oracle.resolve_request(node.node_id, (0.0,), permute=lambda series: series)
            for node in evaluated
        ]
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

    return CloseoutResult(
        campaign_id=campaign,
        ks_pvalue=ks_record.pvalue,
        calibration_status=verdict.status,
        sensitivity=figures.sensitivity,
        specificity=figures.specificity,
        fdr_deploy=fdr_value,
        type_b=type_b,
        discoveries=len(discoveries),
        budget_charging_trials=budget_charging_trials,
        ledger_trials=ledger_trials,
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
        result = close_out(
            arguments.campaign_id,
            database_url=database_url,
            scorer=scorer,
            sidecar=sidecar,
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
