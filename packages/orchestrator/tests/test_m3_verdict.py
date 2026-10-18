"""additions_spec_dreaming_m3.xml, "Dreaming Loop M3 Gate", feature 4.

*System computes the pre-registered M3 verdict for one dreaming iteration
from* ``./run.sh m3-verdict --iteration-id ID`` *and records exactly one
PASS or FAIL row.*

This suite drives :mod:`orchestrator.m3_verdict` at two levels: the module's
own helper functions (:func:`orchestrator.m3_verdict._verify_prereg_hash`,
``_verify_bootstrap_pool``, ``_verify_financial_pool``,
``_verify_no_prior_verdict``, ``_criterion1``, ``_criterion2``,
``_criterion3``), each exercised directly over a throwaway SQLite database so
one test states one claim about one criterion or one refusal; and
:func:`orchestrator.m3_verdict.run_verdict`/``main``, exercised end to end
for a full PASS, a full FAIL (exit 3) and the duplicate-verdict refusal.

No test opens a network connection or writes outside a pytest temporary
directory, and none holds state at module scope, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import bootstrap as bootstrap_module
import discovery
import dreaming
import pytest
import scoring
from orchestrator import dream as dream_module
from orchestrator import m3_verdict
from replay import NON_COMMITTING_SCORE

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up -- the resolution every sibling
# closeout/dream suite in this member uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
INCUMBENT_SOURCE = (REPO_ROOT / "deploy" / "dreaming" / "incumbent.m2.py").read_text(
    encoding="utf-8"
)
PREREG_PATH = REPO_ROOT / "docs" / "preregistration" / "2026-10-17-m3-dreaming.md"


def _database_url(tmp_path: Path, name: str = "m3.db") -> str:
    return f"sqlite:///{tmp_path / name}"


def _sqlite_path(database_url: str) -> Path:
    return Path(database_url.removeprefix("sqlite:///"))


def _create_replay_score_table(database_url: str) -> None:
    # dreaming.pool_bootstrap_schema() is the member's own stand-in DDL for
    # both pool tables (replay_score and bootstrap_world) -- bootstrap.
    # world_census() reads both from one database, so a fixture that wants
    # replay_score needs bootstrap_world to exist too, even when this
    # suite's own stub pool never writes to it.
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.executescript(dreaming.pool_bootstrap_schema())


def _insert_score(
    database_url: str,
    *,
    policy_version: str,
    world_id: str,
    score: float,
    committed_pick: str | None = None,
    beta: float = 0.5,
    created_at: str = "2026-01-01T00:00:00.000000Z",
) -> None:
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO replay_score (id, policy_version, world_id, beta, "
            "score, committed_pick, is_holdout, created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, 1, ?)",
            (
                str(uuid.uuid4()),
                policy_version,
                world_id,
                beta,
                score,
                committed_pick,
                created_at,
            ),
        )


# -- Addendum 1's pinned evaluation configuration -----------------------------
#
# docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md pins criterion 1 (and
# every financial-world score a dreaming cycle writes for M3) to one evaluation
# configuration, and has the verdict record that file's sha256 and refuse a file
# that hashes differently.  The verdict only ever hashes these bytes -- the
# loaded context that scores against them is this suite's own duck-typed stub --
# so the document below need not be a loadable evaluation config, only a stable
# blob a test can point the pin at.
EVALUATION_CONFIG_DOCUMENT = b"""{
  "snapshot_mount": "/srv/nullius/snapshots/2026-10-12T03:50:56Z_75d0a1",
  "evaluation_dates": ["2022-01-03", "2022-01-17"],
  "horizon": 10,
  "seed": 20261006,
  "epoch_id": "archive-perp-bn",
  "artifact_dir": "/srv/nullius/artifacts",
  "sandbox_runtime": "gvisor",
  "oos_dates": ["2025-08-04", "2025-08-18"],
  "instrument": "perp"
}
"""


def _pinned_config(tmp_path: Path) -> tuple[Path, str]:
    """A fixture evaluation config and the sha256 the verdict must record."""
    path = tmp_path / "evaluation-config-archive-perp-bn.json"
    path.write_bytes(EVALUATION_CONFIG_DOCUMENT)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _pin(monkeypatch: pytest.MonkeyPatch, digest: str) -> None:
    """Point both of the module's pins at fixture values.

    The real config pin is a fixed 64-hex constant -- no fixture can be made
    to hash to it -- so the happy path moves the pin rather than the file,
    exactly as a deployment moves the file to the pin.  Addendum 2's
    cost-model pin is moved with it and for the same reason: a criterion test
    seeds its rows through :func:`_winner_version`/:func:`_baseline_version`,
    which file their rows under this fixture hash, so pointing the pin
    anywhere else would have the verdict look for rows nobody wrote.
    """
    monkeypatch.setattr(m3_verdict, "M3_EVALUATION_CONFIG_SHA256", digest)
    _pin_cost_model(monkeypatch)


#: A fixture cost-model hash -- deliberately not the real one, and not the
#: pinned :data:`m3_verdict.M3_COST_MODEL_HASH` either: a criterion test's
#: rows must be filed under the pin, so the pin itself is monkeypatched onto
#: this value the same way ``M3_EVALUATION_CONFIG_SHA256`` is pointed at a
#: fixture file's digest.  Nothing in the version helper validates a hash's
#: shape, and no test here reads a real cost-model file or ``~/.config``.
FIXTURE_COST_MODEL_HASH = "fixture-cost-model-hash"


def _pin_cost_model(monkeypatch: pytest.MonkeyPatch, value: str = FIXTURE_COST_MODEL_HASH) -> str:
    """Point the module's cost-model pin at a fixture value."""
    monkeypatch.setattr(m3_verdict, "M3_COST_MODEL_HASH", value)
    return value


def _baseline_version(
    config_sha256: str, cost_model_hash: str = FIXTURE_COST_MODEL_HASH
) -> str:
    return dream_module.financial_policy_version(
        m3_verdict.M2_INCUMBENT_POLICY_VERSION, config_sha256, cost_model_hash
    )


def _winner_version(
    module_id: str,
    config_sha256: str,
    cost_model_hash: str = FIXTURE_COST_MODEL_HASH,
) -> str:
    return dream_module.financial_policy_version(
        module_id, config_sha256, cost_model_hash
    )


def test_evaluation_config_mismatch_is_refused(tmp_path: Path) -> None:
    """The pin is the real 64-hex constant here, so the fixture refuses."""
    config_path, _digest = _pinned_config(tmp_path)
    with pytest.raises(m3_verdict.M3VerdictError, match="hashes to"):
        m3_verdict._verify_evaluation_config(config_path)


def test_evaluation_config_at_the_pin_is_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    assert m3_verdict._verify_evaluation_config(config_path) == digest


def _create_node_table(database_url: str) -> None:
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS node (id TEXT PRIMARY KEY, "
            "parent_id TEXT, campaign_id TEXT)"
        )


def _plant_root(database_url: str, *, campaign_id: str, node_id: str) -> None:
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id) VALUES (?, NULL, ?)",
            (node_id, campaign_id),
        )


class _StubAssignment:
    def __init__(self, is_null: bool) -> None:
        self.is_null = is_null


class _StubSidecar:
    """A duck-typed sidecar: ``assignment(node_id)`` over a fixed label map."""

    def __init__(self, labels: dict[str, bool]) -> None:
        self._labels = labels

    def assignment(self, node_id: str) -> Any:
        is_null = self._labels.get(node_id)
        return None if is_null is None else _StubAssignment(is_null)


class _StubWorldRecord:
    def __init__(self, world_id: str, domain: str) -> None:
        self.world_id = world_id
        self.domain = domain


class _StubPool:
    """A duck-typed bootstrap pool -- the surface ``world_census`` and
    ``m3_verdict._criterion3`` both call through."""

    def __init__(self, database_url: str, records: tuple[_StubWorldRecord, ...]) -> None:
        self.path = _sqlite_path(database_url)
        self._records = records

    def world_count(self) -> int:
        return len(self._records)

    def world_count_by_domain(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self._records:
            counts[record.domain] = counts.get(record.domain, 0) + 1
        return counts

    def worlds(self) -> tuple[_StubWorldRecord, ...]:
        return self._records

    def world(self, world_id: str) -> str:
        # The evaluator stub is keyed on candidate source and world id alone,
        # so the "world" handed back need only carry its own identity.
        return world_id


def _make_pool(database_url: str, *, per_domain: int) -> _StubPool:
    # world_census() reads the financial figure from the same database the
    # bootstrap figure comes from, so a replay_score table must exist even
    # for a test that only cares about the bootstrap side.
    _create_replay_score_table(database_url)
    records = []
    for domain in m3_verdict.BOOTSTRAP_DOMAINS:
        for index in range(per_domain):
            records.append(_StubWorldRecord(f"{domain}-world-{index}", domain))
    return _StubPool(database_url, tuple(records))


def _widened(iteration_id: str, revision_cap: int) -> tuple[Any, ...]:
    candidates = dreaming.revise_policy(INCUMBENT_SOURCE, revision_cap, seed=iteration_id)
    return dreaming.include_incumbent(
        candidates, INCUMBENT_SOURCE, version=f"incumbent-{iteration_id}"
    )


# -- The four pre-computation refusals ---------------------------------------


def test_prereg_hash_matches_the_real_sidecar_file() -> None:
    digest = m3_verdict._verify_prereg_hash(PREREG_PATH)
    assert digest == hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def test_prereg_hash_mismatch_is_refused(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("original text\n", encoding="utf-8")
    sidecar = tmp_path / "doc.md.sha256"
    sidecar.write_text("0" * 64 + "  doc.md\n", encoding="utf-8")
    with pytest.raises(m3_verdict.M3VerdictError, match="hashes to"):
        m3_verdict._verify_prereg_hash(doc)


def test_bootstrap_pool_below_floor_is_refused(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    pool = _make_pool(database_url, per_domain=5)  # 15 total, below 50
    with pytest.raises(m3_verdict.M3VerdictError, match="bootstrap pool holds"):
        m3_verdict._verify_bootstrap_pool(pool)


def test_bootstrap_pool_below_per_domain_floor_is_refused(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    records = [
        _StubWorldRecord(f"hpo-{i}", "hpo") for i in range(40)
    ] + [
        _StubWorldRecord(f"featsel-{i}", "featsel") for i in range(5)
    ] + [
        _StubWorldRecord(f"symreg-{i}", "symreg") for i in range(10)
    ]
    pool = _StubPool(database_url, tuple(records))  # 55 total, featsel below 10
    with pytest.raises(m3_verdict.M3VerdictError, match="domain 'featsel' holds"):
        m3_verdict._verify_bootstrap_pool(pool)


def test_bootstrap_pool_at_floor_is_admitted(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    pool = _make_pool(database_url, per_domain=17)  # 51 total, 17 per domain
    census = m3_verdict._verify_bootstrap_pool(pool)
    assert census.n_bootstrap == 51


def test_financial_pool_below_floor_is_refused(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    with pytest.raises(m3_verdict.M3VerdictError, match="financial world"):
        m3_verdict._verify_financial_pool(database_url)


def test_duplicate_verdict_is_refused(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    path = _sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(m3_verdict._VERDICT_SCHEMA)
        connection.execute(
            "INSERT INTO m3_verdict (iteration_id, prereg_sha256, "
            "evaluation_config_sha256, cost_model_hash, verdict, "
            "criterion1_pass, criterion1_mean_difference, criterion1_one_sided_p, "
            "criterion1_bar, criterion1_paired_worlds, criterion2_pass, "
            "criterion2_winner_fdr_deploy, criterion2_baseline_fdr_deploy, "
            "criterion3_pass, criterion3_mean_transfer, "
            "criterion3_domain_transfers, winner_commit_rate, "
            "baseline_commit_rate, n_bootstrap, n_bootstrap_by_domain, "
            "n_financial, campaign_ids, winner_module_id, created_at) VALUES "
            "('prior-iteration', 'deadbeef', 'cafe', 'f00d', 'PASS', 1, 0.5, 0.01, 0.1, 20, "
            "1, 0.0, 1.0, 1, 0.1, '{}', 1.0, 0.0, 50, '{}', 20, '[]', "
            "'cand-x', '2026-01-01T00:00:00Z')"
        )
        with pytest.raises(m3_verdict.M3VerdictError, match="already exists"):
            m3_verdict._verify_no_prior_verdict(connection, "deadbeef")
        # A different pre-registration's sha256 is unaffected.
        m3_verdict._verify_no_prior_verdict(connection, "some-other-hash")


def test_verdict_table_written_before_addendum_2_is_upgraded_in_place(
    tmp_path: Path,
) -> None:
    """A ``m3_verdict`` table written under Addendum 1's schema is brought
    forward by ``ALTER TABLE``, and its recorded row is left exactly as filed.

    ``CREATE TABLE IF NOT EXISTS`` cannot evolve a table that already exists,
    so without this probe-then-``ALTER`` the next write would fail with "no
    column named cost_model_hash".  The column is added *nullable*: the one
    true statement a pre-Addendum-2 row can make is that no cost model was
    recorded, and inventing one would name a fee schedule nobody measured.
    """
    database_url = _database_url(tmp_path)
    heredoc = m3_verdict._VERDICT_SCHEMA.replace(
        "    cost_model_hash                 TEXT NOT NULL,\n", ""
    )
    assert "cost_model_hash" not in heredoc
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.executescript(heredoc)
        connection.execute(
            "INSERT INTO m3_verdict (iteration_id, prereg_sha256, "
            "evaluation_config_sha256, verdict, "
            "criterion1_pass, criterion1_mean_difference, criterion1_one_sided_p, "
            "criterion1_bar, criterion1_paired_worlds, criterion2_pass, "
            "criterion2_winner_fdr_deploy, criterion2_baseline_fdr_deploy, "
            "criterion3_pass, criterion3_mean_transfer, "
            "criterion3_domain_transfers, winner_commit_rate, "
            "baseline_commit_rate, n_bootstrap, n_bootstrap_by_domain, "
            "n_financial, campaign_ids, winner_module_id, created_at) VALUES "
            "('legacy-iteration', 'deadbeef', 'cafe', 'PASS', 1, 0.5, 0.01, 0.1, 20, "
            "1, 0.0, 1.0, 1, 0.1, '{}', 1.0, 0.0, 50, '{}', 20, '[]', "
            "'cand-x', '2026-01-01T00:00:00Z')"
        )
        m3_verdict._upgrade_verdict_table(connection)
        # Idempotent: a second call is a no-op.
        m3_verdict._upgrade_verdict_table(connection)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(m3_verdict)")
        }
        assert "cost_model_hash" in columns
        legacy = connection.execute(
            "SELECT iteration_id, verdict, cost_model_hash FROM m3_verdict "
            "WHERE iteration_id = 'legacy-iteration'"
        ).fetchone()
    # The recorded verdict is untouched, and its new column is NULL -- no
    # cost model was recorded for it.
    assert legacy == ("legacy-iteration", "PASS", None)


# -- Criterion 1: paired delta IR --------------------------------------------


def _seed_criterion1_pool(
    database_url: str, *, config_path: Path, winner_version: str, diffs: list[float],
    baseline_scores: list[float] | None = None,
) -> None:
    """A criterion-1 fixture: the winner's and the re-scored baseline's rows.

    Both arms are filed under the pinned config's digest, exactly as a dreaming
    cycle writes them (docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md's
    *"Rows carry their config"*) -- never under the bare ``"m2-fixed"`` version,
    which this criterion no longer reads at all.
    """
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    financial_version = _winner_version(winner_version, config_sha256)
    baseline_version = _baseline_version(config_sha256)
    for index, diff in enumerate(diffs):
        world_id = f"campaign-{index}"
        _insert_score(
            database_url, policy_version=financial_version, world_id=world_id, score=diff
        )
        baseline_score = 0.0 if baseline_scores is None else baseline_scores[index]
        _insert_score(
            database_url, policy_version=baseline_version, world_id=world_id, score=baseline_score
        )


def test_criterion1_passes_on_a_clear_winning_margin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    diffs = [0.65, 0.70, 0.75] * 7  # 21 worlds, mean 0.70, small spread
    _seed_criterion1_pool(
        database_url, config_path=config_path, winner_version=winner_version, diffs=diffs
    )
    difference, one_sided_p, bar, passed = m3_verdict._criterion1(
        database_url=database_url,
        winner_version=winner_version,
        revision_cap=40,
        evaluation_config_path=config_path,
    )
    assert passed is True
    assert difference.mean_difference > m3_verdict.CRITERION1_DELTA
    assert one_sided_p < m3_verdict.CRITERION1_LEVEL
    assert difference.mean_difference > bar


def test_criterion1_fails_on_a_small_margin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    diffs = [0.08, 0.10, 0.12] * 7
    _seed_criterion1_pool(
        database_url, config_path=config_path, winner_version=winner_version, diffs=diffs
    )
    _, _, _, passed = m3_verdict._criterion1(
        database_url=database_url,
        winner_version=winner_version,
        revision_cap=40,
        evaluation_config_path=config_path,
    )
    assert passed is False


def test_criterion1_fails_when_the_bar_does_not_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real, significant margin can still fail a wide-enough meta-level bar
    -- few paired worlds and a wide spread, at a realistic M."""
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    diffs = [0.3, 0.7]  # mean 0.5, n=2: the widest possible spread/n ratio
    _seed_criterion1_pool(
        database_url, config_path=config_path, winner_version=winner_version, diffs=diffs
    )
    difference, _, bar, passed = m3_verdict._criterion1(
        database_url=database_url,
        winner_version=winner_version,
        revision_cap=40,
        evaluation_config_path=config_path,
    )
    assert difference.mean_difference > m3_verdict.CRITERION1_DELTA
    assert difference.mean_difference <= bar
    assert passed is False


def test_criterion1_non_committing_worlds_score_flat_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The document's flat abstention rule: a miss reads as 0.0, not refused."""
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    diffs = [NON_COMMITTING_SCORE] * 21
    baseline_scores = [-0.3, -0.4, -0.5] * 7  # varied, so the pool carries spread
    _seed_criterion1_pool(
        database_url,
        config_path=config_path,
        winner_version=winner_version,
        diffs=diffs,
        baseline_scores=baseline_scores,
    )
    difference, _, _, _passed = m3_verdict._criterion1(
        database_url=database_url,
        winner_version=winner_version,
        revision_cap=10,
        evaluation_config_path=config_path,
    )
    # winner reads 0.0 on every world (a miss), baseline reads ~-0.4: the
    # paired difference averages +0.4, which proves the sentinel never reaches
    # the statistic as -inf.
    assert difference.mean_difference == pytest.approx(0.4)


def test_criterion1_ignores_stored_m2_fixed_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect, pinned: stored ``m2-fixed`` rows are never paired against.

    This is the regression test for the reported bug.  A store holds a stored
    ``m2-fixed`` row for every world -- written by close-out under some *other*
    campaign's evaluation config -- and *no* re-scored baseline arm at all.
    Before the fix, criterion 1 paired the winner's fresh rows against those
    stored ones and reported a comparison; after it, the stored rows carry no
    digest, so they name no arm under the pinned config and the comparison is
    refused rather than taken over evidence from a different configuration.
    """
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    for index, diff in enumerate([0.65, 0.70, 0.75] * 7):
        world_id = f"campaign-{index}"
        _insert_score(
            database_url,
            policy_version=_winner_version(winner_version, config_sha256),
            world_id=world_id,
            score=diff,
        )
        # The stored row a different config's close-out wrote -- bare
        # "m2-fixed", carrying no digest at all.
        _insert_score(
            database_url, policy_version="m2-fixed", world_id=world_id, score=0.0
        )
    with pytest.raises(dreaming.PairedComparisonError):
        m3_verdict._criterion1(
            database_url=database_url,
            winner_version=winner_version,
            revision_cap=40,
            evaluation_config_path=config_path,
        )


def test_criterion1_refuses_an_arm_filed_under_another_cost_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Addendum 2's defect, pinned at the reader: rows filed under the right
    *config* but another *cost model* are never read.

    Both arms hold a full set of rows, so a verdict that named its arms by the
    config's sha256 alone would pair them and report a comparison.  Addendum 2
    -- *"A financial-world row's policy version names the config's sha256 **and
    the cost-model hash** it was scored under.  The verdict pairs only rows
    filed under both pinned values, and refuses, as Addendum 1 already requires
    for a missing row, when either arm lacks them"* -- means those rows name no
    arm under the pin, so the comparison finds nothing to pair and the existing
    missing-row refusal fires, naming the version it looked for.
    """
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    for index, diff in enumerate([0.65, 0.70, 0.75] * 7):
        world_id = f"campaign-{index}"
        # The right config, a *different* cost model: spot-priced rows for a
        # perp-priced pin.
        _insert_score(
            database_url,
            policy_version=_winner_version(winner_version, config_sha256, "522d691dspot"),
            world_id=world_id,
            score=diff,
        )
        _insert_score(
            database_url,
            policy_version=_baseline_version(config_sha256, "522d691dspot"),
            world_id=world_id,
            score=0.0,
        )
    # The version the criterion looks for is the pinned pair's own -- and it
    # is exactly the version the mis-filed rows are *not* under, which is why
    # the pairing finds nothing.
    expected = _winner_version(winner_version, config_sha256)
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection:
        pinned_rows = connection.execute(
            "SELECT COUNT(*) FROM replay_score WHERE policy_version = ?",
            (expected,),
        ).fetchone()[0]
    assert pinned_rows == 0

    baseline_version = _baseline_version(config_sha256)
    # The existing missing-row refusal fires -- Addendum 1's own, produced by
    # the paired statistic when an arm carries no rows (the same one a store
    # with no baseline arm at all gets), never a comparison over the
    # differently-priced rows -- and it names the versions the arms were
    # looked for under, which is the repair a caller whose rows exist under
    # another pair of identities needs.
    with pytest.raises(dreaming.PairedComparisonError, match="paired comparison") as refusal:
        m3_verdict._criterion1(
            database_url=database_url,
            winner_version=winner_version,
            revision_cap=40,
            evaluation_config_path=config_path,
        )
    assert expected in str(refusal.value)
    assert baseline_version in str(refusal.value)


def test_criterion1_reads_only_the_rows_filed_under_both_pinned_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Addendum 2: the pinned pair's rows are read, and a decoy set filed
    under the right config and another cost model is not.

    The decoys read *better* than the pinned rows on purpose -- if the
    criterion read them, ``mean_difference`` would be the decoy figure.
    """
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    pinned_diffs = [0.65, 0.70, 0.75] * 7
    for index, diff in enumerate(pinned_diffs):
        world_id = f"campaign-{index}"
        # The pinned pair -- both values as the pin fixes them.
        _insert_score(
            database_url,
            policy_version=_winner_version(winner_version, config_sha256),
            world_id=world_id,
            score=diff,
        )
        _insert_score(
            database_url,
            policy_version=_baseline_version(config_sha256),
            world_id=world_id,
            score=0.0,
        )
        # A decoy under the same config and another cost model, reading far
        # better than the pinned rows.
        _insert_score(
            database_url,
            policy_version=_winner_version(winner_version, config_sha256, "decoy-model"),
            world_id=world_id,
            score=diff + 10.0,
        )
        _insert_score(
            database_url,
            policy_version=_baseline_version(config_sha256, "decoy-model"),
            world_id=world_id,
            score=0.0,
        )

    difference, _p, _bar, passed = m3_verdict._criterion1(
        database_url=database_url,
        winner_version=winner_version,
        revision_cap=40,
        evaluation_config_path=config_path,
    )
    assert difference.paired_worlds == len(pinned_diffs)
    # The pinned rows' own mean difference, never the decoys' +10.0.
    assert difference.mean_difference == pytest.approx(
        statistics.fmean(pinned_diffs)
    )
    assert passed is True


def test_criterion2_ignores_a_commit_filed_under_another_cost_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 2 reads ``committed_pick`` from the *pinned pair's* rows.

    The fixture runs the winner *twice* over the same worlds: once under the
    pinned pair of identities, committing every planted **null**, and once
    under the right config with another cost model, committing every planted
    **real**.  Only the pinned pair is read, so the winner's figures are the
    null-chasing ones -- FDR_deploy ``1.0`` -- and the mis-filed commits,
    which would read ``0.0``, are never joined to a label.
    """
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    _create_node_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    campaigns = tuple(f"campaign-{i}" for i in range(20))
    labels: dict[str, bool] = {}
    for i, campaign_id in enumerate(campaigns):
        root_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"root-{i}"))
        is_null = i >= 10
        labels[root_id] = is_null
        _plant_root(database_url, campaign_id=campaign_id, node_id=root_id)
        # The winner's mis-filed commits: right config, another cost model --
        # and on the *real* roots, which is the figure this test must not read.
        if not is_null:
            _insert_score(
                database_url,
                policy_version=_winner_version(winner_version, config_sha256, "spot"),
                world_id=campaign_id,
                score=0.0,
                committed_pick=root_id,
            )
        # The winner's pinned commits: both values as the pin fixes them, on
        # the *null* roots.
        if is_null:
            _insert_score(
                database_url,
                policy_version=_winner_version(winner_version, config_sha256),
                world_id=campaign_id,
                score=0.0,
                committed_pick=root_id,
            )
        # The baseline's commits, correctly filed under both pinned values, on
        # the reals: a low FDR_deploy the winner must not beat.
        if not is_null:
            _insert_score(
                database_url,
                policy_version=_baseline_version(config_sha256),
                world_id=campaign_id,
                score=0.0,
                committed_pick=root_id,
            )
    scorer = scoring.NullPickScorer(_StubSidecar(labels))
    winner_fdr, baseline_fdr, passed = m3_verdict._criterion2(
        database_url=database_url,
        winner_version=winner_version,
        campaigns=campaigns,
        scorer=scorer,
        config_sha256=digest,
    )
    # Every pinned winner commitment landed on a null: FDR_deploy 1.0.  Had
    # the mis-filed spot rows been read, the winner would have read 0.0.
    assert winner_fdr == pytest.approx(1.0)
    assert baseline_fdr == pytest.approx(0.0)
    assert passed is False


# -- Criterion 2: FDR_deploy --------------------------------------------------


def _seed_criterion2(
    database_url: str, *, config_path: Path, winner_version: str,
    winner_commits_reals: bool,
) -> tuple[tuple[str, ...], Any]:
    """A criterion-2 fixture: 20 campaigns, both arms under the pinned digest."""
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    financial_version = _winner_version(winner_version, config_sha256)
    baseline_version = _baseline_version(config_sha256)
    campaigns = tuple(f"campaign-{i}" for i in range(20))
    labels: dict[str, bool] = {}
    for i, campaign_id in enumerate(campaigns):
        root_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"root-{i}"))
        is_null = i >= 10
        labels[root_id] = is_null
        _plant_root(database_url, campaign_id=campaign_id, node_id=root_id)
        winner_commits_here = (not is_null) if winner_commits_reals else is_null
        if winner_commits_here:
            _insert_score(
                database_url, policy_version=financial_version, world_id=campaign_id,
                score=0.0, committed_pick=root_id,
            )
            _insert_score(
                database_url, policy_version=baseline_version, world_id=campaign_id, score=0.0
            )
        else:
            _insert_score(
                database_url, policy_version=financial_version, world_id=campaign_id, score=0.0
            )
            _insert_score(
                database_url, policy_version=baseline_version, world_id=campaign_id,
                score=0.0, committed_pick=root_id,
            )
    return campaigns, scoring.NullPickScorer(_StubSidecar(labels))


def test_criterion2_passes_when_the_winner_avoids_nulls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    _create_node_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    campaigns, scorer = _seed_criterion2(
        database_url,
        config_path=config_path,
        winner_version=winner_version,
        winner_commits_reals=True,
    )
    winner_fdr, baseline_fdr, passed = m3_verdict._criterion2(
        database_url=database_url,
        winner_version=winner_version,
        campaigns=campaigns,
        scorer=scorer,
        config_sha256=digest,
    )
    assert winner_fdr == pytest.approx(0.0)
    assert baseline_fdr == pytest.approx(1.0)
    assert passed is True


def test_criterion2_fails_when_the_winner_chases_nulls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    _create_node_table(database_url)
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    winner_version = "cand-winner"
    campaigns, scorer = _seed_criterion2(
        database_url,
        config_path=config_path,
        winner_version=winner_version,
        winner_commits_reals=False,
    )
    winner_fdr, baseline_fdr, passed = m3_verdict._criterion2(
        database_url=database_url,
        winner_version=winner_version,
        campaigns=campaigns,
        scorer=scorer,
        config_sha256=digest,
    )
    assert winner_fdr == pytest.approx(1.0)
    assert baseline_fdr == pytest.approx(0.0)
    assert passed is False


# -- Criterion 3: leave-one-family-out transfer ------------------------------


def test_criterion3_passes_when_the_retaken_argmax_beats_the_incumbent(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    iteration_id = "it-criterion3-pass"
    pool = _make_pool(database_url, per_domain=12)
    widened = _widened(iteration_id, revision_cap=4)
    incumbent_entry = next(c for c in widened if c.module_id == f"incumbent-{iteration_id}")

    def evaluator(source: str, world: str, *, round_cap: int) -> Any:
        class _Pick:
            pass

        pick = _Pick()
        pick.score = 1.0 if source == incumbent_entry.source else 2.0
        return pick

    mean_transfer, domain_transfers, passed = m3_verdict._criterion3(
        iteration_id,
        database_url=database_url,
        pool=pool,
        widened=widened,
        incumbent_entry=incumbent_entry,
        evaluator=evaluator,
        round_cap=5,
    )
    assert passed is True
    assert mean_transfer == pytest.approx(1.0)
    for domain in m3_verdict.BOOTSTRAP_DOMAINS:
        assert domain_transfers[domain] == pytest.approx(1.0)


def test_criterion3_fails_when_the_incumbent_beats_the_retaken_argmax(tmp_path: Path) -> None:
    """Every revision underperforms the incumbent everywhere, so the
    retaken argmax is the incumbent itself on every domain (feature 273's
    own guarantee, V^m* >= V^0) -- the transfer is trivially zero, which is
    not a positive transfer."""
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    iteration_id = "it-criterion3-fail"
    pool = _make_pool(database_url, per_domain=12)
    widened = _widened(iteration_id, revision_cap=4)
    incumbent_entry = next(c for c in widened if c.module_id == f"incumbent-{iteration_id}")

    def evaluator(source: str, world: str, *, round_cap: int) -> Any:
        class _Pick:
            pass

        pick = _Pick()
        pick.score = 1.0 if source == incumbent_entry.source else 0.0
        return pick

    mean_transfer, domain_transfers, passed = m3_verdict._criterion3(
        iteration_id,
        database_url=database_url,
        pool=pool,
        widened=widened,
        incumbent_entry=incumbent_entry,
        evaluator=evaluator,
        round_cap=5,
    )
    for domain in m3_verdict.BOOTSTRAP_DOMAINS:
        assert domain_transfers[domain] == pytest.approx(0.0)
    assert mean_transfer == pytest.approx(0.0)
    assert passed is False


def test_criterion3_sweeps_missing_pairs_through_the_evaluator(tmp_path: Path) -> None:
    """No bootstrap-world replay_score rows exist at all -- every (candidate,
    world) pair criterion 3 needs is swept fresh through the evaluator."""
    database_url = _database_url(tmp_path)
    _create_replay_score_table(database_url)
    iteration_id = "it-criterion3-sweep"
    pool = _make_pool(database_url, per_domain=12)
    widened = _widened(iteration_id, revision_cap=3)
    incumbent_entry = next(c for c in widened if c.module_id == f"incumbent-{iteration_id}")

    calls: list[tuple[str, str]] = []

    def evaluator(source: str, world: str, *, round_cap: int) -> Any:
        calls.append((source, world))

        class _Pick:
            pass

        pick = _Pick()
        pick.score = 0.0 if source == incumbent_entry.source else 1.0
        return pick

    m3_verdict._criterion3(
        iteration_id,
        database_url=database_url,
        pool=pool,
        widened=widened,
        incumbent_entry=incumbent_entry,
        evaluator=evaluator,
        round_cap=5,
    )
    assert calls  # nothing was known in advance, so the evaluator carried it all


# -- End to end: run_verdict / main -------------------------------------------


def _plant_cycle(
    tmp_path: Path,
    *,
    iteration_id: str,
    per_domain: int,
    n_campaigns: int,
    winner_commits_reals: bool,
    financial_diffs: list[float],
    config_path: Path,
) -> dict[str, Any]:
    """Build a full, consistent fixture store for one dreaming cycle.

    Returns the pieces an end-to-end test needs: the database URL, the
    stub pool, the winner candidate, a scorer over the planted labels, and
    the admitted campaign ids.
    """
    database_url = _database_url(tmp_path, name=f"{iteration_id}.db")
    _create_replay_score_table(database_url)
    _create_node_table(database_url)

    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    pool = _make_pool(database_url, per_domain=per_domain)
    total_worlds = per_domain * len(m3_verdict.BOOTSTRAP_DOMAINS)
    cap_record = dreaming.record_cycle_cap(iteration_id, total_worlds, database_url=database_url)
    widened = _widened(iteration_id, cap_record.revision_cap)
    winner = widened[1]  # widened[0] is the incumbent (include_incumbent's own contract)
    financial_version = _winner_version(winner.module_id, config_sha256)
    baseline_version = _baseline_version(config_sha256)

    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS policy_revision (id TEXT PRIMARY KEY, "
            "policy_version TEXT NOT NULL UNIQUE, parent_version TEXT, "
            "code_hash TEXT NOT NULL, aggregate_score REAL, "
            "selected BOOLEAN NOT NULL DEFAULT 0)"
        )
        connection.execute(
            "INSERT INTO policy_revision (id, policy_version, parent_version, "
            "code_hash, selected) VALUES (?, ?, ?, ?, 1)",
            (str(uuid.uuid4()), winner.module_id, f"incumbent-{iteration_id}", winner.code_hash),
        )

    # discovery.admit_completed_campaigns reads a manifest's own canonical
    # campaign_id (a UUID, discovery.CampaignManifest's own law) back as the
    # financial world's id -- so the node row and the replay_score rows
    # below are filed under that same canonical id from the start.
    canonical_campaigns = tuple(
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{iteration_id}-campaign-{i}"))
        for i in range(n_campaigns)
    )
    labels: dict[str, bool] = {}
    manifests = discovery.CampaignManifests(database_url)
    for i, canonical_id in enumerate(canonical_campaigns):
        manifests.record(
            discovery.CampaignManifest(
                campaign_id=canonical_id,
                calibration_status="ok",
                branch_count=1,
                refine_count=0,
                leaf_count=1,
                node_count=1,
                depth_max=0,
                theme_roots=1,
            )
        )

    for i, (canonical_id, diff) in enumerate(zip(canonical_campaigns, financial_diffs, strict=True)):
        root_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{iteration_id}-root-{i}"))
        is_null = i >= n_campaigns // 2
        labels[root_id] = is_null
        _plant_root(database_url, campaign_id=canonical_id, node_id=root_id)
        winner_commits_here = (not is_null) if winner_commits_reals else is_null
        if winner_commits_here:
            _insert_score(
                database_url, policy_version=financial_version, world_id=canonical_id,
                score=diff, committed_pick=root_id,
            )
            _insert_score(
                database_url, policy_version=baseline_version, world_id=canonical_id, score=0.0
            )
        else:
            _insert_score(database_url, policy_version=financial_version, world_id=canonical_id, score=diff)
            _insert_score(
                database_url, policy_version=baseline_version, world_id=canonical_id,
                score=0.0, committed_pick=root_id,
            )

    scorer = scoring.NullPickScorer(_StubSidecar(labels))
    return {
        "database_url": database_url,
        "pool": pool,
        "winner": winner,
        "scorer": scorer,
        "campaigns": canonical_campaigns,
        "iteration_id": iteration_id,
        "config_path": config_path,
        "config_sha256": config_sha256,
    }


def _pass_evaluator(incumbent_source: str):
    def evaluator(source: str, world: str, *, round_cap: int) -> Any:
        class _Pick:
            pass

        pick = _Pick()
        pick.score = 1.0 if source == incumbent_source else 2.0
        return pick

    return evaluator


def test_run_verdict_passes_and_persists_one_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    iteration_id = "it-end-to-end-pass"
    diffs = ([0.65, 0.70, 0.75] * 7)[:20]
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    fixture = _plant_cycle(
        tmp_path,
        iteration_id=iteration_id,
        per_domain=17,
        n_campaigns=20,
        winner_commits_reals=True,
        financial_diffs=diffs,
        config_path=config_path,
    )
    result = m3_verdict.run_verdict(
        iteration_id,
        database_url=fixture["database_url"],
        scorer=fixture["scorer"],
        pool=fixture["pool"],
        evaluation_config_path=config_path,
        evaluator=_pass_evaluator(INCUMBENT_SOURCE),
    )
    assert result.verdict == "PASS"
    assert result.criterion1_pass is True
    assert result.criterion2_pass is True
    assert result.criterion3_pass is True
    assert result.prereg_sha256 == hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()
    assert result.evaluation_config_sha256 == digest
    # Addendum 2: the row records the cost model the criteria were judged
    # under, so a recorded verdict says what it read without a reader having
    # to reconstruct a version string.
    assert result.cost_model_hash == FIXTURE_COST_MODEL_HASH

    with closing(sqlite3.connect(_sqlite_path(fixture["database_url"]))) as connection:
        rows = connection.execute(
            "SELECT verdict, prereg_sha256, evaluation_config_sha256, "
            "cost_model_hash FROM m3_verdict WHERE iteration_id = ?",
            (iteration_id,),
        ).fetchall()
    assert rows == [
        ("PASS", result.prereg_sha256, digest, FIXTURE_COST_MODEL_HASH)
    ]


def test_run_verdict_fails_and_persists_the_fail_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    iteration_id = "it-end-to-end-fail"
    diffs = ([0.05, 0.10, 0.15] * 7)[:20]  # a small margin: criterion 1 fails
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    fixture = _plant_cycle(
        tmp_path,
        iteration_id=iteration_id,
        per_domain=17,
        n_campaigns=20,
        winner_commits_reals=True,
        financial_diffs=diffs,
        config_path=config_path,
    )
    result = m3_verdict.run_verdict(
        iteration_id,
        database_url=fixture["database_url"],
        scorer=fixture["scorer"],
        pool=fixture["pool"],
        evaluation_config_path=config_path,
        evaluator=_pass_evaluator(INCUMBENT_SOURCE),
    )
    assert result.verdict == "FAIL"
    assert result.criterion1_pass is False

    with closing(sqlite3.connect(_sqlite_path(fixture["database_url"]))) as connection:
        row = connection.execute(
            "SELECT verdict FROM m3_verdict WHERE iteration_id = ?", (iteration_id,)
        ).fetchone()
    assert row == ("FAIL",)


def test_run_verdict_refuses_a_config_that_hashes_differently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADDENDUM 1: *"the verdict records the config's sha256, and refuses if
    the file it is given hashes differently."*"""
    iteration_id = "it-end-to-end-config-drift"
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    config_path.write_bytes(EVALUATION_CONFIG_DOCUMENT + b"\n")
    diffs = ([0.65, 0.70, 0.75] * 7)[:20]
    fixture = _plant_cycle(
        tmp_path,
        iteration_id=iteration_id,
        per_domain=17,
        n_campaigns=20,
        winner_commits_reals=True,
        financial_diffs=diffs,
        config_path=config_path,
    )
    with pytest.raises(m3_verdict.M3VerdictError, match="hashes to"):
        m3_verdict.run_verdict(
            iteration_id,
            database_url=fixture["database_url"],
            scorer=fixture["scorer"],
            pool=fixture["pool"],
            evaluation_config_path=config_path,
            evaluator=_pass_evaluator(INCUMBENT_SOURCE),
        )


def test_main_exits_3_on_a_fail_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    iteration_id = "it-cli-fail"
    diffs = ([0.05, 0.10, 0.15] * 7)[:20]
    config_path, digest = _pinned_config(tmp_path)
    _pin(monkeypatch, digest)
    fixture = _plant_cycle(
        tmp_path,
        iteration_id=iteration_id,
        per_domain=17,
        n_campaigns=20,
        winner_commits_reals=True,
        financial_diffs=diffs,
        config_path=config_path,
    )

    class _FixedApp:
        def get(self, name: str) -> Any:
            return None

    monkeypatch.setattr(m3_verdict, "bootstrap", _StubBootstrapModule(fixture["pool"]))
    monkeypatch.setattr(m3_verdict.scoring.NullPickScorer, "resolve", staticmethod(lambda env: fixture["scorer"]))
    monkeypatch.setattr(m3_verdict.nulloracle.NullSidecar, "resolve", staticmethod(lambda env: object()))
    monkeypatch.setattr(m3_verdict, "score_on_world", _pass_evaluator(INCUMBENT_SOURCE))

    emitted: list[str] = []
    exit_code = m3_verdict.main(
        [
            "--iteration-id",
            iteration_id,
            "--evaluation-config",
            str(config_path),
        ],
        env={
            "DATABASE_URL": fixture["database_url"],
            "NULL_SIDECAR_PATH": str(tmp_path / "sidecar.json"),
            "NULL_SIDECAR_KEY_REF": "op://vault/item/key",
        },
        emit=emitted.append,
    )
    assert exit_code == m3_verdict.EXIT_FAIL
    assert json.loads(emitted[0])["verdict"] == "FAIL"


class _StubBootstrapModule:
    """Stands in for the ``bootstrap`` module name ``main()`` reaches through
    (``bootstrap.BootstrapPool(database_url)``, ``bootstrap.world_census``)
    -- the two call sites this CLI test exercises, answering the pre-built
    pool fixture; ``world_census`` delegates to the real implementation,
    which is duck-typed over the stub pool's own surface."""

    BootstrapError = bootstrap_module.BootstrapError

    def __init__(self, pool: _StubPool) -> None:
        self._pool = pool

    def BootstrapPool(self, database_url: str) -> _StubPool:
        return self._pool

    def world_census(self, pool: _StubPool) -> Any:
        return bootstrap_module.world_census(pool)


def test_main_refuses_a_missing_database_url() -> None:
    exit_code = m3_verdict.main(["--iteration-id", "it-x"], env={})
    assert exit_code == m3_verdict.EXIT_CONFIG


def test_main_refuses_missing_sidecar_config() -> None:
    exit_code = m3_verdict.main(
        ["--iteration-id", "it-x"], env={"DATABASE_URL": "sqlite:///x.db"}
    )
    assert exit_code == m3_verdict.EXIT_CONFIG
