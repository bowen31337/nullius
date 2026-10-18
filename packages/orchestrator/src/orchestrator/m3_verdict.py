"""The M3 dreaming-gate verdict -- ``python -m orchestrator.m3_verdict``.

additions_spec_dreaming_m3.xml, "Dreaming Loop M3 Gate", feature 4: *System
computes the pre-registered M3 verdict for one dreaming iteration from*
``python -m orchestrator.m3_verdict --iteration-id ID``. *It records exactly
one PASS or FAIL row, so that the M3 gate is decided by code, once, exactly
as* ``docs/preregistration/2026-10-17-m3-dreaming.md`` *fixes it.*

This module is the pre-registration's "Procedure" step 3 as one call: a
dreaming cycle (``python -m orchestrator.dream --iteration-id ID``) has
already run and persisted its winner (``policy_revision``), its bootstrap
sweep and its financial-world sweep (``replay_score``); this command reads
that evidence back, computes the three pre-registered criteria exactly as
the document fixes them, and writes one ``m3_verdict`` row -- never two,
for one pre-registered attempt (the document's own sha256).

**Addendum 2: the cost model is pinned beside the config.**
``docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md``'s second
addendum fixes the *second* identity a financial-world row carries.  Its
defect: Addendum 1 pinned the evaluation config by sha256, but the cost model
a score is netted through is **not in that file** -- it is read from
``NULLIUS_COST_MODEL_PATH``, and an unset variable means the shipped **spot**
schedule -- so two cycles under one pinned config could price their rows
through different fee and funding schedules and file them under one version
(*"72 of the 84 campaigns were scored with the spot default"*).  Two
consequences here: (a) both criteria name each arm by the config's sha256
**and** :data:`M3_COST_MODEL_HASH`
(:func:`orchestrator.dream.financial_policy_version`), so a row filed under
the pinned config but any other cost model is never read, and an arm with no
row under the pinned pair refuses exactly as Addendum 1 already required for
a missing row; and (b) the verdict records the cost-model hash in its own
column, so what a recorded verdict was judged under is readable from the row
the verdict file rather than inferred from the version strings it read.

**Refusals are checked before any criterion is computed**, in the
pre-registration's own order: the document's sha256 against its sidecar
``.sha256`` file; the pinned evaluation config's sha256 against
:data:`M3_EVALUATION_CONFIG_SHA256`; the bootstrap pool's size (>= 50 worlds,
>= 10 per domain of ``hpo``/``featsel``/``symreg``); the admitted
financial-world count (>= 20); and a prior verdict already filed under this
same document.  Each opens with its own greppable code word and exits 1.

**Addendum 1, and what it changes here.**
``docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md`` fixes the
evaluation config criterion 1 is computed under and where the baseline arm's
scores come from, and it wins wherever it and this module's original reading
of the document differ.  Three consequences, all of them the whole of this
module's own change: (a) the config is pinned by sha256 and the verdict
refuses a file that hashes differently
(:func:`_verify_evaluation_config`); (b) the baseline arm is the
**re-scored** ``deploy/dreaming/incumbent.m2.py`` -- swept by the dreaming
cycle under the pinned config and filed under
:data:`orchestrator.dream.M2_INCUMBENT_POLICY_VERSION`, never the stored
``"m2-fixed"`` rows, which were written by each campaign's own close-out
under that campaign's own setup and are used only for the incumbent's
pick-equivalence check (``test_m2_incumbent_equivalence.py``); and (c) every
financial row a cycle writes for M3 names the config's sha256 in its
``policy_version`` (:func:`orchestrator.dream.financial_policy_version`), so
both criteria pair only rows filed under the pinned digest -- a pair drawn
from two configurations cannot be formed even by accident.

**Criterion 1 (paired ΔIR)** reads the winner's and the re-scored M2
baseline's financial world rows straight from the pool
(:func:`dreaming.paired_pool_difference` under the document's own flat
abstention rule, ``non_committing="flat"``) and judges the one-sided version
of the document's test: ``mean_difference > 0.3``, a one-sided ``p < 0.05``
(computed from the comparison's own ``t_statistic`` --
:func:`dreaming.paired.paired_ir_difference` only carries the two-sided
figure), and the comparison clears :func:`dreaming.bar.selection_bar` at the
cycle's own recorded ``M`` (:func:`dreaming.cycle_caps`, the newest record
naming this iteration).  Both arms are named *by the pinned evaluation
config's sha256* (:func:`orchestrator.dream.financial_policy_version`), per
the pre-registration's first addendum -- see the module's own "Addendum 1"
note below.

**Criterion 2 (FDR_deploy)** reads, for every admitted financial-world
campaign, each arm's ``replay_score.committed_pick`` (the winner's and the
re-scored M2 baseline's own ``#financial@{sha256}`` rows, both written by the
dreaming cycle), maps each committed node to its planted root
(:class:`orchestrator._oracle.SubtreeOracle`, the same walk close-out takes),
and asks :class:`scoring.NullPickScorer` for each arm's
sensitivity/specificity over the pooled population of every admitted
campaign's planted roots -- the one process allowed to join a pick to its
null label (prd §4.2).  :func:`scoring.fdr_deploy` reweights each pair at
its own fixed ``π₀ = 0.9``; the winner must read strictly lower than the
baseline's.

**Criterion 3 (leave-one-family-out transfer)** regenerates the cycle's own
widened candidate set deterministically (:func:`dreaming.revise_policy` at
the recorded ``M`` and a seed equal to the iteration id -- the same
determinism :mod:`orchestrator.dream` relies on for its own reruns) over
the fixed M2 incumbent (``deploy/dreaming/incumbent.m2.py``, the document's
*"first incumbent is the M2 fixed baseline"*).  For each bootstrap domain,
it retakes the argmax among those candidates over the other two domains'
train worlds -- reading every (candidate, world) pair this cycle already
swept into ``replay_score``, and sweeping anything missing through the
evaluator -- and scores that argmax minus the incumbent, averaged over
every world of the held-out domain.  The mean of the three domains' deltas
must be positive.

**Exit codes:** 0 once a PASS verdict is recorded; 3 once a FAIL verdict is
recorded (the row is saved either way); 1 when a refusal fires, naming it;
2 for a missing ``DATABASE_URL`` or an unconfigured null sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bootstrap
import dreaming
import nulloracle
import scoring
from replay import NON_COMMITTING_SCORE

from ._bootstrap_eval import score_on_world
from ._oracle import SubtreeOracle
from .closeout import (
    DATABASE_URL_ENV,
    _NoPostEndpoint,
    _sqlite_path,
)
from .closeout import _read_campaign_root_ids as _campaign_root_ids
from .closeout import _resolve_root as _root_of
from .dream import (
    M2_INCUMBENT_POLICY_VERSION,
    _admitted_financial_campaigns,
    _existing_winner,
    financial_policy_version,
)

__all__ = [
    "BOOTSTRAP_DOMAINS",
    "CRITERION1_DELTA",
    "CRITERION1_LEVEL",
    "DEFAULT_INCUMBENT_PATH",
    "DEFAULT_PREREG_PATH",
    "EXIT_CONFIG",
    "EXIT_FAIL",
    "EXIT_OK",
    "EXIT_REFUSED",
    "M3_CODE",
    "M3_COST_MODEL_HASH",
    "M3_EVALUATION_CONFIG_SHA256",
    "MIN_BOOTSTRAP_PER_DOMAIN",
    "MIN_BOOTSTRAP_WORLDS",
    "MIN_FINANCIAL_WORLDS",
    "VERDICT_TABLE",
    "M3VerdictError",
    "VerdictResult",
    "main",
    "run_verdict",
]

#: The greppable word every refusal this module itself pronounces opens
#: with -- a collaborator's own refusal (dreaming, scoring, closeout,
#: bootstrap) already opens with its own and is never rewrapped.
M3_CODE = "m3_verdict"

#: The table this command owns and creates idempotently on first write --
#: no migration declares it, the same stance :class:`discovery.
#: CampaignManifests` takes for ``campaign_manifest``.
VERDICT_TABLE = "m3_verdict"

#: The pre-registration this command computes, by default -- the document
#: the module docstring quotes throughout.  Overridable with ``--prereg``
#: only so a test can point this command at a fixture document; a real run
#: always computes this one.
DEFAULT_PREREG_PATH = Path("docs/preregistration/2026-10-17-m3-dreaming.md")

#: The fixed M2 incumbent's source file -- additions_spec_dreaming_m3.xml
#: feature 2's own fixed path, the document's *"first incumbent is the M2
#: fixed baseline"*, and the file
#: docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md re-scores as
#: criterion 1's baseline arm.
DEFAULT_INCUMBENT_PATH = Path("deploy/dreaming/incumbent.m2.py")

#: The evaluation configuration criterion 1 -- and every financial-world score
#: a dreaming cycle writes for M3 -- is computed under, as
#: docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md pins it.  The
#: verdict records this digest and *"refuses if the file it is given hashes
#: differently"*.
DEFAULT_EVALUATION_CONFIG_PATH = Path(
    "~/.config/nullius/campaign/evaluation-config-archive-perp-bn.json"
)

#: The pinned configuration's own sha256 -- the digest
#: docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md records for
#: ``evaluation-config-archive-perp-bn.json``.  A file handed to the verdict
#: that hashes to anything else is refused: the pin is the rule, not the path,
#: so a config edited in place is refused exactly as a different file would be.
M3_EVALUATION_CONFIG_SHA256 = (
    "6adc9a93dd4b2b52ac82c4bab91bb8e3bc33af09b010b826dd7de73d12736425"
)

#: The pinned **cost model**'s own hash --
#: docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md, **Addendum 2**:
#: *"Every financial-world score written for M3 is netted through*
#: ``packages/cost-model/src/cost_model/binance_usdm.yaml``, *venue*
#: ``binance_usdm``, *cost-model hash*
#: ``1e946e66e63e308c6d5258fdb8f1a610e7dab18cc2562a90d6084c719c5e958a``. *It
#: is the venue the pinned config's instrument trades, and the schedule the
#: forward shadow already uses."*  It is pinned here rather than read from a
#: file because the cost model a running process resolves is a property of its
#: environment (``NULLIUS_COST_MODEL_PATH``, unset meaning the shipped **spot**
#: schedule), and the verdict's whole job is to judge one pre-registered
#: attempt against values fixed in advance -- so the pin is the rule and the
#: process's own resolution is not consulted at all.
#:
#: Beside :data:`M3_EVALUATION_CONFIG_SHA256` because both criteria must name
#: *both* identities when they build the arms' versions: the cost model is not
#: part of the config file the sha256 covers, so an arm named by the digest
#: alone would pair rows the cycle netted through different fee and funding
#: schedules -- Addendum 2's defect.
M3_COST_MODEL_HASH = "1e946e66e63e308c6d5258fdb8f1a610e7dab18cc2562a90d6084c719c5e958a"

#: The three generated bootstrap domains criterion 3 is taken over --
#: the document's own "hpo, featsel and symreg", and the floor's own three
#: names.
BOOTSTRAP_DOMAINS = ("hpo", "featsel", "symreg")

#: The bootstrap pool's floor -- below it, no verdict is computed at all.
MIN_BOOTSTRAP_WORLDS = 50

#: The floor on each of :data:`BOOTSTRAP_DOMAINS`.
MIN_BOOTSTRAP_PER_DOMAIN = 10

#: The admitted financial-world floor.
MIN_FINANCIAL_WORLDS = 20

#: Criterion 1's mean-difference bar -- the document's "> 0.3".
CRITERION1_DELTA = 0.3

#: Criterion 1's one-sided significance level -- the document's "p < 0.05".
CRITERION1_LEVEL = 0.05

#: The non-committing substitution every comparison in this module reads
#: under -- the document's own flat abstention rule, restated as a literal
#: rather than imported because :mod:`dreaming.paired`'s own spelling is
#: not re-exported from the package's namespace (the same stance
#: :mod:`orchestrator.dream` takes for its own copy of this literal).
_NON_COMMITTING_FLAT = "flat"

#: Done -- a PASS verdict was computed and recorded.
EXIT_OK = 0
#: A refusal fired before any criterion was computed, or a collaborator's
#: own law refused the computation; named on stderr either way.
EXIT_REFUSED = 1
#: Missing configuration: no ``DATABASE_URL``, or no null sidecar.
EXIT_CONFIG = 2
#: A FAIL verdict was computed and recorded -- the row is saved either way.
EXIT_FAIL = 3


class M3VerdictError(Exception):
    """A refusal this module itself pronounces, by name.

    The pre-registration's own four refusals (hash mismatch, a thin
    bootstrap pool, a thin financial pool, a prior verdict already filed)
    and this module's own structural asks (no recorded winner, no recorded
    revision cap).  Every other collaborator's refusal (dreaming, scoring,
    closeout, bootstrap) propagates unwrapped -- each already opens its own
    message with its own greppable code word.
    """


@dataclass(frozen=True)
class VerdictResult:
    """One computed M3 verdict -- the row this command persists and prints."""

    iteration_id: str
    prereg_sha256: str
    evaluation_config_sha256: str
    cost_model_hash: str
    verdict: str
    criterion1_pass: bool
    criterion1_mean_difference: float
    criterion1_one_sided_p: float
    criterion1_bar: float
    criterion1_paired_worlds: int
    criterion2_pass: bool
    criterion2_winner_fdr_deploy: float
    criterion2_baseline_fdr_deploy: float
    criterion3_pass: bool
    criterion3_mean_transfer: float
    criterion3_domain_transfers: Mapping[str, float]
    winner_commit_rate: float | None
    baseline_commit_rate: float | None
    n_bootstrap: int
    n_bootstrap_by_domain: Mapping[str, int]
    n_financial: int
    campaign_ids: Sequence[str]
    winner_module_id: str
    created_at: str

    @property
    def is_pass(self) -> bool:
        return self.verdict == "PASS"

    def to_payload(self) -> dict[str, Any]:
        return {
            "iteration_id": self.iteration_id,
            "prereg_sha256": self.prereg_sha256,
            "evaluation_config_sha256": self.evaluation_config_sha256,
            "cost_model_hash": self.cost_model_hash,
            "verdict": self.verdict,
            "criterion1_pass": self.criterion1_pass,
            "criterion1_mean_difference": self.criterion1_mean_difference,
            "criterion1_one_sided_p": self.criterion1_one_sided_p,
            "criterion1_bar": self.criterion1_bar,
            "criterion1_paired_worlds": self.criterion1_paired_worlds,
            "criterion2_pass": self.criterion2_pass,
            "criterion2_winner_fdr_deploy": self.criterion2_winner_fdr_deploy,
            "criterion2_baseline_fdr_deploy": self.criterion2_baseline_fdr_deploy,
            "criterion3_pass": self.criterion3_pass,
            "criterion3_mean_transfer": self.criterion3_mean_transfer,
            "criterion3_domain_transfers": dict(self.criterion3_domain_transfers),
            "winner_commit_rate": self.winner_commit_rate,
            "baseline_commit_rate": self.baseline_commit_rate,
            "n_bootstrap": self.n_bootstrap,
            "n_bootstrap_by_domain": dict(self.n_bootstrap_by_domain),
            "n_financial": self.n_financial,
            "campaign_ids": list(self.campaign_ids),
            "winner_module_id": self.winner_module_id,
            "created_at": self.created_at,
        }


# -- The four pre-computation refusals, in the document's own order ---------


def _verify_prereg_hash(prereg_path: Path) -> str:
    """The document's sha256, refused if it disagrees with its sidecar file."""
    try:
        content = prereg_path.read_bytes()
    except OSError as exc:
        raise M3VerdictError(
            f"{M3_CODE}: --prereg {str(prereg_path)!r} could not be read: {exc}"
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    sidecar_path = prereg_path.with_name(prereg_path.name + ".sha256")
    try:
        sidecar_text = sidecar_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise M3VerdictError(
            f"{M3_CODE}: the pre-registration's sha256 sidecar "
            f"{str(sidecar_path)!r} could not be read: {exc}"
        ) from exc
    fields = sidecar_text.split()
    recorded = fields[0] if fields else ""
    if recorded != digest:
        raise M3VerdictError(
            f"{M3_CODE}: {str(prereg_path)!r} hashes to {digest!r}, but "
            f"{str(sidecar_path)!r} records {recorded!r}; the pre-registration "
            "must not have drifted since it was filed -- docs/preregistration/"
            "2026-10-17-m3-dreaming.md: \"the verdict row carries this "
            "document's sha256\""
        )
    return digest


def _verify_evaluation_config(config_path: Path) -> str:
    """The pinned evaluation config's sha256, refused if it differs.

    docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md: *"The verdict
    records the config's sha256, and refuses if the file it is given hashes
    differently."*  The pin is :data:`M3_EVALUATION_CONFIG_SHA256` -- the
    digest the addendum states -- rather than whatever file happens to sit at
    a path, so a configuration edited in place after the addendum was filed is
    refused exactly as a different file would be.  A path that cannot be read
    is refused too, and *before* the comparison: a missing file and a drifted
    one are different facts, and the message names which happened.
    """
    try:
        content = config_path.expanduser().read_bytes()
    except OSError as exc:
        raise M3VerdictError(
            f"{M3_CODE}: the pinned evaluation configuration "
            f"{str(config_path)!r} could not be read: {exc}; criterion 1 and "
            "every financial-world score a dreaming cycle writes for M3 is "
            "computed under that one configuration "
            "(docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md)"
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != M3_EVALUATION_CONFIG_SHA256:
        raise M3VerdictError(
            f"{M3_CODE}: the evaluation configuration at {str(config_path)!r} "
            f"hashes to {digest!r}, but the pre-registration's first addendum "
            f"pins {M3_EVALUATION_CONFIG_SHA256!r}; criterion 1 is computed "
            "under that pinned configuration and under no other, so a file "
            "that hashes differently names no config this verdict may compare "
            "over -- docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md: "
            "\"The verdict records the config's sha256, and refuses if the "
            "file it is given hashes differently\""
        )
    return digest


def _verify_bootstrap_pool(pool: Any) -> Any:
    """The bootstrap census, refused below the floor or the per-domain floor."""
    try:
        census = bootstrap.world_census(pool)
    except bootstrap.BootstrapError as exc:
        raise M3VerdictError(f"{M3_CODE}: {exc}") from exc
    if census.n_bootstrap < MIN_BOOTSTRAP_WORLDS:
        raise M3VerdictError(
            f"{M3_CODE}: the bootstrap pool holds {census.n_bootstrap} world(s), "
            f"fewer than the {MIN_BOOTSTRAP_WORLDS} the M3 gate requires before "
            "a verdict may be computed"
        )
    for domain in BOOTSTRAP_DOMAINS:
        count = census.n_bootstrap_by_domain.get(domain, 0)
        if count < MIN_BOOTSTRAP_PER_DOMAIN:
            raise M3VerdictError(
                f"{M3_CODE}: bootstrap domain {domain!r} holds {count} world(s), "
                f"fewer than the {MIN_BOOTSTRAP_PER_DOMAIN} the M3 gate requires "
                "per domain"
            )
    return census


def _verify_financial_pool(database_url: str) -> tuple[str, ...]:
    """The admitted financial campaigns, refused below the floor."""
    campaigns = _admitted_financial_campaigns(database_url)
    if len(campaigns) < MIN_FINANCIAL_WORLDS:
        raise M3VerdictError(
            f"{M3_CODE}: {len(campaigns)} financial world(s) are admitted, "
            f"fewer than the {MIN_FINANCIAL_WORLDS} the M3 gate requires"
        )
    return campaigns


def _verify_no_prior_verdict(connection: sqlite3.Connection, prereg_sha256: str) -> None:
    """Refuse a second verdict under the same pre-registered attempt."""
    row = connection.execute(
        f"SELECT iteration_id FROM {VERDICT_TABLE} WHERE prereg_sha256 = ? LIMIT 1",
        (prereg_sha256,),
    ).fetchone()
    if row is not None:
        raise M3VerdictError(
            f"{M3_CODE}: a verdict already exists for this pre-registration "
            f"(iteration {row[0]!r}); one verdict per pre-registered attempt -- "
            "docs/preregistration/2026-10-17-m3-dreaming.md: \"A second verdict "
            "under the same attempt is refused, whatever its parameters\""
        )


# -- Shared cycle state: the winner, the widened candidates, the cap --------


def _revision_cap(iteration_id: str, *, database_url: str) -> int:
    caps = [
        record
        for record in dreaming.cycle_caps(database_url=database_url)
        if record.iteration_id == iteration_id
    ]
    if not caps:
        raise M3VerdictError(
            f"{M3_CODE}: no recorded revision cap for iteration {iteration_id!r}; "
            f"run ./run.sh dream --iteration-id {iteration_id} first"
        )
    return caps[-1].revision_cap


def _widened_candidates(
    iteration_id: str, incumbent_source: str, revision_cap: int
) -> tuple[Any, ...]:
    candidates = dreaming.revise_policy(incumbent_source, revision_cap, seed=iteration_id)
    incumbent_version = f"incumbent-{iteration_id}"
    return dreaming.include_incumbent(candidates, incumbent_source, version=incumbent_version)


def _winner_candidate(database_url: str, widened: Sequence[Any]) -> Any:
    winner = _existing_winner(database_url, widened)
    if winner is None:
        raise M3VerdictError(
            f"{M3_CODE}: no selected policy_revision row matches this cycle's "
            "own candidates; run ./run.sh dream for this iteration first"
        )
    return winner


# -- Criterion 1: paired delta IR over the financial holdout ----------------


def _criterion1(
    *,
    database_url: str,
    winner_version: str,
    revision_cap: int,
    evaluation_config_path: Path = DEFAULT_EVALUATION_CONFIG_PATH,
) -> tuple[Any, float, float, bool]:
    """The paired ΔIR over the financial holdout, under the pinned config.

    docs/preregistration/2026-10-17-m3-dreaming.md's criterion 1, computed as
    its two addenda fix it: the pinned configuration is verified by digest
    first, and *both* arms are then named by versions carrying **both pinned
    identities** -- the config's :data:`M3_EVALUATION_CONFIG_SHA256` and the
    cost model's :data:`M3_COST_MODEL_HASH` (Addendum 2's *"Rows carry both
    identities"*).  The winner's own fresh ``#financial`` sweep
    (:func:`orchestrator.dream.financial_policy_version`) is paired against the
    **re-scored** M2 baseline arm's
    (:data:`orchestrator.dream.M2_INCUMBENT_POLICY_VERSION`, written by the
    same cycle under the same config *and* the same cost model).  The stored
    ``"m2-fixed"`` rows are not read at all: each was written by a campaign's
    close-out under that campaign's own evaluation setup -- by the nodes'
    recorded provenance, 72 of the 84 under the spot default rather than the
    pinned perp schedule -- so pairing against one would measure the two
    setups' difference rather than dreaming, the defect the addenda fix.
    Because both versions carry both identities, a pair drawn from two
    configurations, or from two cost models under one config, cannot be
    formed even by accident: the versions simply do not match, and
    :func:`dreaming.paired_pool_difference` refuses the pair by naming the
    expected version, exactly as Addendum 1 already required for a missing row
    (*"The verdict pairs only rows filed under both pinned values, and
    refuses, as Addendum 1 already requires for a missing row, when either arm
    lacks them"*).
    """
    config_sha256 = _verify_evaluation_config(evaluation_config_path)
    financial_version = financial_policy_version(
        winner_version, config_sha256, M3_COST_MODEL_HASH
    )
    baseline_version = financial_policy_version(
        M2_INCUMBENT_POLICY_VERSION, config_sha256, M3_COST_MODEL_HASH
    )
    try:
        difference = dreaming.paired_pool_difference(
            financial_version,
            baseline_version,
            database_url=database_url,
            non_committing=_NON_COMMITTING_FLAT,
        )
    except dreaming.PairedComparisonError as refusal:
        # The missing-row refusal is :func:`dreaming.paired_pool_difference`'s
        # own, and it fires *because* both arms are named by the pinned pair --
        # but its message names the two arm *sizes* and not the versions the
        # arms were looked for under, which is the one fact the repair needs
        # when the rows exist under a different pair of identities (a stored
        # config digest, or Addendum 2's spot cost model).  Naming them here
        # rather than minting a second refusal: the exception stays
        # :class:`dreaming.PairedComparisonError`, so every caller and every
        # existing test reads exactly the refusal it read before, with the
        # expected versions added.
        raise dreaming.PairedComparisonError(
            f"{refusal} [expected arms: candidate {financial_version!r}, "
            f"baseline {baseline_version!r} -- file this cycle's financial-world "
            "rows under both pinned identities, the evaluation config's sha256 "
            "and the cost model's hash (docs/preregistration/2026-10-17-m3-"
            "dreaming.ADDENDUM.md, Addenda 1 and 2)]"
        ) from refusal
    one_sided_p = statistics.NormalDist().cdf(-difference.t_statistic)
    bar = dreaming.selection_bar(
        revision_cap, spread=difference.spread, worlds=difference.paired_worlds
    )
    stats_pass = (
        difference.mean_difference > CRITERION1_DELTA and one_sided_p < CRITERION1_LEVEL
    )
    bar_clear = difference.mean_difference > bar
    return difference, one_sided_p, bar, (stats_pass and bar_clear)


# -- Criterion 2: FDR_deploy over the committed picks ------------------------


def _committed_pick(database_url: str, policy_version: str, world_id: str) -> str | None:
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT committed_pick FROM replay_score WHERE policy_version = ? "
            "AND world_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (policy_version, world_id),
        ).fetchone()
    return None if row is None or row[0] is None else row[0]


def _criterion2(
    *,
    database_url: str,
    winner_version: str,
    campaigns: tuple[str, ...],
    scorer: Any,
    config_sha256: str,
) -> tuple[float, float, bool]:
    financial_version = financial_policy_version(
        winner_version, config_sha256, M3_COST_MODEL_HASH
    )
    baseline_version = financial_policy_version(
        M2_INCUMBENT_POLICY_VERSION, config_sha256, M3_COST_MODEL_HASH
    )
    oracle = SubtreeOracle(_NoPostEndpoint(), database_url=database_url)
    population: list[str] = []
    winner_picks: list[str] = []
    baseline_picks: list[str] = []
    for campaign_id in campaigns:
        roots = frozenset(_campaign_root_ids(database_url, campaign_id))
        population.extend(roots)
        winner_node = _committed_pick(database_url, financial_version, campaign_id)
        if winner_node is not None:
            winner_picks.append(
                _root_of(oracle, winner_node, campaign=campaign_id, roots=roots)
            )
        baseline_node = _committed_pick(database_url, baseline_version, campaign_id)
        if baseline_node is not None:
            baseline_picks.append(
                _root_of(oracle, baseline_node, campaign=campaign_id, roots=roots)
            )
    winner_figures = scorer.calibration_figures(population=population, picks=winner_picks)
    baseline_figures = scorer.calibration_figures(population=population, picks=baseline_picks)
    winner_fdr = scoring.fdr_deploy(winner_figures)
    baseline_fdr = scoring.fdr_deploy(baseline_figures)
    return winner_fdr, baseline_fdr, winner_fdr < baseline_fdr


# -- Criterion 3: leave-one-family-out transfer ------------------------------


def _flat(value: float) -> float:
    return 0.0 if value == NON_COMMITTING_SCORE else value


def _known_scores(database_url: str, policy_version: str) -> dict[str, float]:
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT world_id, score FROM replay_score WHERE policy_version = ? "
            "ORDER BY id",
            (policy_version,),
        ).fetchall()
    return {world_id: float(score) for world_id, score in rows}


def _criterion3(
    iteration_id: str,
    *,
    database_url: str,
    pool: Any,
    widened: Sequence[Any],
    incumbent_entry: Any,
    evaluator: Callable[..., Any],
    round_cap: int,
) -> tuple[float, dict[str, float], bool]:
    records = pool.worlds()
    world_by_id = {record.world_id: pool.world(record.world_id) for record in records}
    domain_by_world = {record.world_id: record.domain for record in records}
    split = dreaming.split_pool(tuple(world_by_id), rotation=iteration_id)
    train_worlds = frozenset(split.train)

    known: dict[tuple[str, str], float] = {}
    for candidate in widened:
        for world_id, score in _known_scores(database_url, candidate.module_id).items():
            if world_id in world_by_id:
                known[(candidate.module_id, world_id)] = score

    def scored(candidate: Any, world_id: str) -> float:
        key = (candidate.module_id, world_id)
        if key not in known:
            pick = evaluator(candidate.source, world_by_id[world_id], round_cap=round_cap)
            known[key] = pick.score
        return _flat(known[key])

    domain_transfers: dict[str, float] = {}
    for domain in BOOTSTRAP_DOMAINS:
        other_train = [world_id for world_id in train_worlds if domain_by_world[world_id] != domain]
        if not other_train:
            raise M3VerdictError(
                f"{M3_CODE}: no train world outside domain {domain!r}; criterion "
                "3 needs the other two domains' train worlds to retake the argmax"
            )
        best_candidate: Any = None
        best_mean: float | None = None
        for candidate in widened:
            mean_value = statistics.fmean(scored(candidate, world_id) for world_id in other_train)
            if (
                best_mean is None
                or mean_value > best_mean
                or (mean_value == best_mean and candidate.module_id < best_candidate.module_id)
            ):
                best_mean = mean_value
                best_candidate = candidate
        domain_worlds = [world_id for world_id in world_by_id if domain_by_world[world_id] == domain]
        if not domain_worlds:
            raise M3VerdictError(f"{M3_CODE}: bootstrap domain {domain!r} holds no world")
        domain_transfers[domain] = statistics.fmean(
            scored(best_candidate, world_id) - scored(incumbent_entry, world_id)
            for world_id in domain_worlds
        )

    mean_transfer = statistics.fmean(domain_transfers.values())
    return mean_transfer, domain_transfers, mean_transfer > 0.0


# -- The store ----------------------------------------------------------------

#: The verdict table's DDL -- created idempotently by this command on first
#: write, the same ``CREATE TABLE IF NOT EXISTS`` stance
#: :class:`discovery.CampaignManifests` takes for its own table.
_VERDICT_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {VERDICT_TABLE} (
    iteration_id                    TEXT NOT NULL UNIQUE,
    prereg_sha256                   TEXT NOT NULL,
    evaluation_config_sha256        TEXT NOT NULL,
    cost_model_hash                 TEXT NOT NULL,
    verdict                         TEXT NOT NULL,
    criterion1_pass                 BOOLEAN NOT NULL,
    criterion1_mean_difference      REAL NOT NULL,
    criterion1_one_sided_p          REAL NOT NULL,
    criterion1_bar                  REAL NOT NULL,
    criterion1_paired_worlds        INTEGER NOT NULL,
    criterion2_pass                 BOOLEAN NOT NULL,
    criterion2_winner_fdr_deploy    REAL NOT NULL,
    criterion2_baseline_fdr_deploy  REAL NOT NULL,
    criterion3_pass                 BOOLEAN NOT NULL,
    criterion3_mean_transfer        REAL NOT NULL,
    criterion3_domain_transfers     TEXT NOT NULL,
    winner_commit_rate              REAL,
    baseline_commit_rate            REAL,
    n_bootstrap                     INTEGER NOT NULL,
    n_bootstrap_by_domain           TEXT NOT NULL,
    n_financial                     INTEGER NOT NULL,
    campaign_ids                    TEXT NOT NULL,
    winner_module_id                TEXT NOT NULL,
    created_at                      TEXT NOT NULL
)
"""


def _upgrade_verdict_table(connection: sqlite3.Connection) -> None:
    """Bring a verdict table written before Addendum 2 up to the current schema.

    ``CREATE TABLE IF NOT EXISTS`` cannot evolve a table that already exists,
    so a database whose ``m3_verdict`` row was written under Addendum 1's
    schema would reject every write with "no column named cost_model_hash" --
    the same failure :meth:`cost_model.store` brings its own pre-feature-60
    table forward from, and the same ``PRAGMA table_info`` probe-then-``ALTER``
    the ledger member's store uses for an unstamped ledger.

    The column is added **nullable**, with no default, for the one true
    statement a pre-Addendum-2 row can make: *no cost model was recorded*.  A
    hash invented here would name a fee schedule nobody measured -- and there
    is no safe default to invent, because an unset ``NULLIUS_COST_MODEL_PATH``
    resolves to the **spot** schedule while every M3 row is pinned to
    ``binance_usdm``.  Idempotent by construction: a table that already holds
    the column is left untouched.  No row is rewritten -- an ``ALTER TABLE …
    ADD COLUMN`` is a schema change, so every recorded verdict keeps exactly
    the values it was filed with.
    """
    columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({VERDICT_TABLE})")
    }
    if "cost_model_hash" not in columns:
        connection.execute(
            f"ALTER TABLE {VERDICT_TABLE} ADD COLUMN cost_model_hash TEXT"
        )


def _persist(connection: sqlite3.Connection, result: VerdictResult) -> None:
    connection.execute(
        f"INSERT INTO {VERDICT_TABLE} ("
        "iteration_id, prereg_sha256, evaluation_config_sha256, "
        "cost_model_hash, verdict, "
        "criterion1_pass, criterion1_mean_difference, criterion1_one_sided_p, "
        "criterion1_bar, criterion1_paired_worlds, "
        "criterion2_pass, criterion2_winner_fdr_deploy, criterion2_baseline_fdr_deploy, "
        "criterion3_pass, criterion3_mean_transfer, criterion3_domain_transfers, "
        "winner_commit_rate, baseline_commit_rate, "
        "n_bootstrap, n_bootstrap_by_domain, n_financial, campaign_ids, "
        "winner_module_id, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            result.iteration_id,
            result.prereg_sha256,
            result.evaluation_config_sha256,
            result.cost_model_hash,
            result.verdict,
            result.criterion1_pass,
            result.criterion1_mean_difference,
            result.criterion1_one_sided_p,
            result.criterion1_bar,
            result.criterion1_paired_worlds,
            result.criterion2_pass,
            result.criterion2_winner_fdr_deploy,
            result.criterion2_baseline_fdr_deploy,
            result.criterion3_pass,
            result.criterion3_mean_transfer,
            json.dumps(dict(result.criterion3_domain_transfers)),
            result.winner_commit_rate,
            result.baseline_commit_rate,
            result.n_bootstrap,
            json.dumps(dict(result.n_bootstrap_by_domain)),
            result.n_financial,
            json.dumps(list(result.campaign_ids)),
            result.winner_module_id,
            result.created_at,
        ),
    )


# -- The verdict, as one call --------------------------------------------------


def run_verdict(
    iteration_id: str,
    *,
    database_url: str,
    scorer: Any,
    pool: Any,
    prereg_path: Path = DEFAULT_PREREG_PATH,
    incumbent_path: Path = DEFAULT_INCUMBENT_PATH,
    evaluation_config_path: Path = DEFAULT_EVALUATION_CONFIG_PATH,
    evaluator: Callable[..., Any] | None = None,
    round_cap: int = 30,
) -> VerdictResult:
    """Compute and persist one M3 verdict -- the module's whole act.

    ``scorer`` is the resolved :class:`scoring.NullPickScorer` (the scorer
    process, the only one prd §4.2 lets join a pick to its null label).
    ``pool`` is the :class:`bootstrap.BootstrapPool` the bootstrap census and
    criterion 3 both read.  ``evaluator`` and ``round_cap`` are criterion 3's
    seam onto "the cycle's evaluator" -- :func:`orchestrator._bootstrap_eval.
    score_on_world` (read as this module's own current attribute, resolved
    at call time rather than bound as a default, so a test may replace it by
    name) when ``evaluator`` is not given.
    """
    if evaluator is None:
        evaluator = score_on_world
    if not isinstance(iteration_id, str) or not iteration_id.strip():
        raise M3VerdictError(
            f"{M3_CODE}: --iteration-id must be a non-empty string -- got "
            f"{iteration_id!r}"
        )
    iteration_id = iteration_id.strip()

    prereg_sha256 = _verify_prereg_hash(prereg_path)
    census = _verify_bootstrap_pool(pool)
    campaigns = _verify_financial_pool(database_url)
    config_sha256 = _verify_evaluation_config(evaluation_config_path)

    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(_VERDICT_SCHEMA)
        _upgrade_verdict_table(connection)
        _verify_no_prior_verdict(connection, prereg_sha256)

        revision_cap = _revision_cap(iteration_id, database_url=database_url)
        try:
            incumbent_source = incumbent_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise M3VerdictError(
                f"{M3_CODE}: the incumbent {str(incumbent_path)!r} "
                f"could not be read: {exc}"
            ) from exc
        widened = _widened_candidates(iteration_id, incumbent_source, revision_cap)
        incumbent_entry = next(
            candidate
            for candidate in widened
            if candidate.module_id == f"incumbent-{iteration_id}"
        )
        winner = _winner_candidate(database_url, widened)

        difference, one_sided_p, bar, criterion1_pass = _criterion1(
            database_url=database_url,
            winner_version=winner.module_id,
            revision_cap=revision_cap,
            evaluation_config_path=evaluation_config_path,
        )
        winner_fdr, baseline_fdr, criterion2_pass = _criterion2(
            database_url=database_url,
            winner_version=winner.module_id,
            campaigns=campaigns,
            scorer=scorer,
            config_sha256=config_sha256,
        )
        mean_transfer, domain_transfers, criterion3_pass = _criterion3(
            iteration_id,
            database_url=database_url,
            pool=pool,
            widened=widened,
            incumbent_entry=incumbent_entry,
            evaluator=evaluator,
            round_cap=round_cap,
        )

        verdict = (
            "PASS" if (criterion1_pass and criterion2_pass and criterion3_pass) else "FAIL"
        )
        created_at = connection.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        ).fetchone()[0]
        result = VerdictResult(
            iteration_id=iteration_id,
            prereg_sha256=prereg_sha256,
            evaluation_config_sha256=config_sha256,
            cost_model_hash=M3_COST_MODEL_HASH,
            verdict=verdict,
            criterion1_pass=criterion1_pass,
            criterion1_mean_difference=difference.mean_difference,
            criterion1_one_sided_p=one_sided_p,
            criterion1_bar=bar,
            criterion1_paired_worlds=difference.paired_worlds,
            criterion2_pass=criterion2_pass,
            criterion2_winner_fdr_deploy=winner_fdr,
            criterion2_baseline_fdr_deploy=baseline_fdr,
            criterion3_pass=criterion3_pass,
            criterion3_mean_transfer=mean_transfer,
            criterion3_domain_transfers=domain_transfers,
            winner_commit_rate=difference.candidate_commit_rate,
            baseline_commit_rate=difference.baseline_commit_rate,
            n_bootstrap=census.n_bootstrap,
            n_bootstrap_by_domain=dict(census.n_bootstrap_by_domain),
            n_financial=len(campaigns),
            campaign_ids=campaigns,
            winner_module_id=winner.module_id,
            created_at=created_at,
        )
        _persist(connection, result)
    return result


# -- The CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.m3_verdict",
        description=(
            "Compute the pre-registered M3 dreaming-gate verdict for one "
            "dreaming iteration and record exactly one PASS or FAIL row."
        ),
    )
    parser.add_argument(
        "--iteration-id",
        dest="iteration_id",
        required=True,
        metavar="ID",
        help="the dreaming cycle (python -m orchestrator.dream) to judge",
    )
    parser.add_argument(
        "--prereg",
        dest="prereg_path",
        default=str(DEFAULT_PREREG_PATH),
        metavar="PATH",
        help=f"the pre-registration to compute (default {DEFAULT_PREREG_PATH})",
    )
    parser.add_argument(
        "--incumbent",
        dest="incumbent_path",
        default=str(DEFAULT_INCUMBENT_PATH),
        metavar="PATH",
        help=(
            "the incumbent the judged cycle revised, from which its candidates "
            f"are rebuilt (default {DEFAULT_INCUMBENT_PATH}; Addendum 3 names "
            "deploy/dreaming/incumbent.m3.py)"
        ),
    )
    parser.add_argument(
        "--evaluation-config",
        dest="evaluation_config_path",
        default=str(DEFAULT_EVALUATION_CONFIG_PATH),
        metavar="PATH",
        help=(
            "the evaluation configuration criterion 1 is computed under "
            f"(default {DEFAULT_EVALUATION_CONFIG_PATH}); its sha256 must be "
            "the one docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md "
            "pins, or the verdict refuses"
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m orchestrator.m3_verdict --iteration-id ID [--prereg PATH]``."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{M3_CODE}: {DATABASE_URL_ENV} must name the research database "
            "the M3 verdict reads and writes to",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    if not source.get(nulloracle.SIDECAR_PATH_ENV, "").strip():
        print(
            f"{M3_CODE}: {nulloracle.SIDECAR_PATH_ENV} must name the sealed "
            "null sidecar the M3 verdict reads as the scorer process (prd §4.2)",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    if not source.get(nulloracle.KEY_REF_ENV, "").strip():
        print(
            f"{M3_CODE}: {nulloracle.KEY_REF_ENV} must name the sidecar's key",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    scorer = scoring.NullPickScorer.resolve(source)
    sidecar = nulloracle.NullSidecar.resolve(source)
    if scorer is None or sidecar is None:
        print(
            f"{M3_CODE}: no null sidecar is configured under "
            f"{nulloracle.SIDECAR_PATH_ENV}/{nulloracle.KEY_REF_ENV}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    pool = bootstrap.BootstrapPool(database_url)

    try:
        result = run_verdict(
            arguments.iteration_id,
            database_url=database_url,
            scorer=scorer,
            pool=pool,
            prereg_path=Path(arguments.prereg_path),
            incumbent_path=Path(arguments.incumbent_path),
            evaluation_config_path=Path(arguments.evaluation_config_path),
        )
    except Exception as exc:  # noqa: BLE001 - every collaborator's own
        # refusal (dreaming, scoring, closeout, bootstrap) already opens its
        # own message with a greppable code word, printed unchanged.
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(result.to_payload()))
    return EXIT_OK if result.is_pass else EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
