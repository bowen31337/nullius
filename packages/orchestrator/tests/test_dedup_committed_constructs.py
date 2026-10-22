"""The dedup commit variant -- additions_spec_dedup_committed_constructs.xml.

``docs/preregistration/2026-10-21-m2-short-h5.RESULT.md`` records ten
campaigns under one evaluation config that each committed the same
persistent-high-funding construct: mean pairwise correlation of the ten
out-of-sample book series 0.91 and N_eff 1.09, and campaigns 4 and 8
committing roots with bit-identical statistics (IC t 2.0558, IR t 3.5953,
turnover 0.22) under different code hashes, because two agents wrote the same
function in different source text.  A series of ten campaigns therefore
sampled one book ten times.

The feature under test gives the evaluation config one optional boolean key,
``dedup_committed_constructs`` (default ``false``).  When it is ``true``, the
close-out's M2 commit (step 9 of :func:`orchestrator.closeout.close_out`)
excludes every bar-clearing real node whose stored in-sample fingerprint
(``ic_mean``, ``ic_tstat``, ``ir_tstat``, ``turnover``, each within ``1e-9``)
equals that of a pick an earlier campaign under the same
``evaluation_config_sha256`` already committed as its ``m2-fixed`` row, and
the printed JSON line gains ``dedup_skipped`` and ``dedup_against``.  With the
key absent or false every number, row and field is identical to today.

The sqlite store is the throwaway, fully migrated database the sibling
closeout suites build (``test_closeout_commit_skips_nulls.py``,
``test_closeout_cost_aware.py``), plus ``0120_campaign_evaluation_grid`` for
the ``evaluation_config_sha256`` column this feature reads; the sidecar is
sealed the way :mod:`nullius_api.demo` seals one.  Node rows are planted
directly, the state a finished campaign's live evaluator would have written.

One test per claim the spec's own test list makes: the loader's new key (a),
the pure comparison (b), the two-campaign dedup through the real close-out
(c), a different config hash counting nothing (d), the abstention (e), a NULL
fingerprint field never matching (f), and the unchanged payload (g, which
lives in ``test_closeout_commit_skips_nulls.py``'s own fixture).

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory, and none holds state at module scope,
so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import ledger
import nulloracle
import pytest
import replay
import scoring
from orchestrator._context import (
    DEDUP_COMMITTED_KEY,
    EvaluationConfigError,
    load_evaluation_context,
)
from orchestrator.closeout import (
    M2_FIXED_BETA,
    M2_FIXED_POLICY_VERSION,
    _construct_fingerprint,
    _earlier_committed_fingerprints,
    _fingerprints_match,
    close_out,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the same resolution every sibling
# closeout suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")
#: The grid columns this feature joins on.  Applied here so a campaign row can
#: carry an ``evaluation_config_sha256`` at all; the "no hash recorded" case is
#: exercised by planting a row with a NULL one, which is the same read a chain
#: that never reached this revision produces.
GRID_MIGRATION = "0120_campaign_evaluation_grid"

EVALUATOR_HASH = hashlib.sha256(b"dedup-committed-constructs-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"dedup-committed-constructs-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"dedup-committed-constructs-cost-model").hexdigest()

CODE_WORD = "evaluation_config"

#: One evaluation config hash -- the ten-campaign series' own, in miniature.
CONFIG_SHA = hashlib.sha256(b"evaluation-config-short-h5").hexdigest()
#: A second, different one -- a different snapshot, a different book.
OTHER_CONFIG_SHA = hashlib.sha256(b"evaluation-config-wide-h5").hexdigest()

#: The duplicate construct's fingerprint F.  ``ic_tstat`` 2.0558 and
#: ``turnover`` 0.22 are the RESULT's own campaigns 4 and 8 (it quotes the
#: pair to four decimals); ``ir_tstat`` 3.5 and ``ic_mean`` 0.0351 complete the
#: tuple, the former the spec's own test fixture's figure for the duplicate
#: contender.  The four figures *are* the fingerprint -- stored, never
#: recomputed -- so the earlier pick's node and the duplicate carry all four
#: identically, and the duplicate clears the bar on the ``ir_tstat`` the
#: earlier pick was committed on.
DUPLICATE_IC_MEAN = 0.0351
DUPLICATE_IC_TSTAT = 2.0558
DUPLICATE_IR_TSTAT = 3.5
DUPLICATE_TURNOVER = 0.22

#: The distinct construct the later campaign must commit instead.
DISTINCT_IC_MEAN = 0.0412
DISTINCT_IC_TSTAT = 2.31
DISTINCT_IR_TSTAT = 2.5
DISTINCT_TURNOVER = 0.31


# -- The store ---------------------------------------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_dedup_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'dedup-committed-constructs-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    _load_migration(GRID_MIGRATION).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _plant_campaign(
    database_url: str,
    *,
    campaign_id: str,
    config_sha256: str | None,
    created_at: str,
) -> str:
    """Create one campaign row directly, with the grid hash this feature reads
    and an explicit ``created_at``, so the earlier/later ordering is a fact of
    the fixture rather than of the clock."""
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE,
        4,
        campaign_id=campaign_id,
        database_url=database_url,
        evaluation_config_sha256=config_sha256,
    )
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            f"UPDATE {discovery.CAMPAIGN_TABLE} SET "
            f"{discovery.CREATED_AT_COLUMN} = ? WHERE {discovery.ID_COLUMN} = ?",
            (created_at, campaign_id),
        )
    return campaign_id


def _plant_node(
    database_url: str,
    campaign_id: str,
    *,
    node_id: str,
    ic_mean: float,
    ic_tstat: float,
    ir_tstat: float | None,
    turnover: float | None,
) -> str:
    """Insert one evaluated root node row directly, ``ir_tstat`` written by the
    same probe-then-``ALTER`` :mod:`orchestrator._tree_writer` runs.
    ``ir_tstat=None`` plants the column's NULL, the shape test (f) needs."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        has_column = any(
            row[1] == "ir_tstat" for row in connection.execute("PRAGMA table_info(node)")
        )
        if not has_column:
            connection.execute("ALTER TABLE node ADD COLUMN ir_tstat REAL")
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat, ir_tstat, turnover) VALUES (?, NULL, ?, ?, 0, ?, ?, ?, ?)",
            (node_id, campaign_id, "macro", ic_mean, ic_tstat, ir_tstat, turnover),
        )
    return node_id


def _charge_ledger(
    database_url: str, node_id: str, campaign_id: str, *, epoch_id: str
) -> None:
    ledger.TrialLedger(database_url).debit(
        node_id,
        campaign_id,
        outcome="ok",
        charges_budget=True,
        charge_units=1.0,
        epoch_id=epoch_id,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        ts=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )


def _seal_sidecar(
    tmp_path: Path, assignments: list[nulloracle.NullAssignment]
) -> dict[str, str]:
    material = os.urandom(nulloracle.SIDECAR_KEY_BYTES)
    path = tmp_path / "null" / "sidecar.enc"
    nulloracle.NullSidecar(path, material).write(assignments)
    return {
        nulloracle.SIDECAR_PATH_ENV: str(path),
        nulloracle.KEY_REF_ENV: f"hex:{material.hex()}",
    }


def _assignment(
    campaign_id: str, node_id: str, *, is_null: bool
) -> nulloracle.NullAssignment:
    return nulloracle.NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=nulloracle.perm_seed_for(campaign_id, node_id),
    )


def _resolved_scorer_and_sidecar(env: dict[str, str]) -> tuple[Any, Any]:
    sidecar = nulloracle.NullSidecar.resolve(env)
    scorer = scoring.NullPickScorer.resolve(env)
    assert sidecar is not None and scorer is not None
    return scorer, sidecar


def _replay_score_rows(database_url: str, *, world_id: str) -> list[tuple]:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        return connection.execute(
            f"SELECT policy_version, world_id, beta, score, committed_pick "
            f"FROM {replay.REPLAY_SCORE_TABLE} WHERE world_id = ? "
            "ORDER BY created_at",
            (world_id,),
        ).fetchall()


class _Pick:
    """The one attribute :func:`replay.persist_replay_score` reads off a
    committed pick -- ``node_id`` -- so this suite can write an earlier
    campaign's row without composing a policy-runtime record."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


def _record_earlier_commit(
    database_url: str, *, campaign_id: str, node_id: str
) -> None:
    """Write the ``m2-fixed`` replay_score row an earlier campaign's own
    close-out would have written, committing ``node_id``."""
    replay.persist_replay_score(
        replay.TerminalPick(pick=_Pick(node_id), score=0.25),
        M2_FIXED_POLICY_VERSION,
        campaign_id,
        M2_FIXED_BETA,
        database_url=database_url,
    )


def _stub_context(*, dedup: bool) -> Any:
    """A duck-typed stand-in for :class:`orchestrator._context.
    EvaluationContext`, carrying only what :func:`orchestrator.closeout.
    close_out` reads off a context here: the dedup switch.  ``oos_dates`` is
    empty, so no out-of-sample read is attempted -- the same shape a
    deployment with no ``oos_dates`` key has, which is also what keeps these
    tests off the network and off the snapshot."""
    return SimpleNamespace(
        dedup_committed_constructs=dedup,
        oos_dates=(),
        artifact_dir=Path("."),
        database_url="",
    )


# -- (a) The loader's new key ------------------------------------------------


LOAD_SYMBOLS = ("SYM00", "SYM01", "SYM02")
LOAD_FIRST_DAY = dt.date(2026, 9, 1)
LOAD_BAR_DAYS = tuple(
    LOAD_FIRST_DAY + dt.timedelta(days=offset) for offset in range(14)
)
LOAD_EVALUATION_DAYS = tuple(
    day.isoformat() for day in (LOAD_BAR_DAYS[3], LOAD_BAR_DAYS[4], LOAD_BAR_DAYS[5])
)
LOAD_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32


@pytest.fixture
def load_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, str]]:
    """A minimal, fully configured document and environment for the loader --
    ``test_metrics_horizon_config.py``'s own ``load_world``, kept at arm's
    length from every key this suite does not ask about."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import pyarrow as pa
    import pyarrow.parquet as pq
    from snapshot import SnapshotService

    lake_root = tmp_path / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(LOAD_SYMBOLS):
        for offset, day in enumerate(LOAD_BAR_DAYS):
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [str(round(100.0 + 10.0 * index + 0.25 * offset, 2))],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        "cost_model:\n"
        '  version: "2026.10.20"\n'
        "  venue: testnet_spot_dedup_committed\n"
        "  fees:\n"
        "    taker_bps: 12.5\n"
        "    maker_bps: 8.0\n",
        encoding="utf-8",
    )

    document: dict[str, Any] = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(LOAD_EVALUATION_DAYS),
        "horizon": 5,
        "seed": 20261022,
        "epoch_id": "epoch-2026-10-22-dedup-committed",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }

    bwrap_dir = tmp_path / "bwrap-path"
    bwrap_dir.mkdir()
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    environment = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'dedup-load-test.db'}",
        "NULLIUS_EVALUATOR_IMAGE": LOAD_IMAGE,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bwrap_dir),
    }
    return document, environment


def _loaded(
    tmp_path: Path,
    load_world: tuple[dict[str, Any], dict[str, str]],
    **extra: Any,
) -> Any:
    document, environment = load_world
    document = dict(document, **extra)
    config_path = tmp_path / f"evaluation-{abs(id(document))}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    environment = dict(environment, NULLIUS_EVALUATION_CONFIG=str(config_path))
    return load_evaluation_context(environment)


def test_the_key_absent_loads_false(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    context = _loaded(tmp_path, load_world)
    assert DEDUP_COMMITTED_KEY not in load_world[0]
    assert context is not None
    assert context.dedup_committed_constructs is False


def test_the_key_true_loads_true(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    context = _loaded(tmp_path, load_world, **{DEDUP_COMMITTED_KEY: True})
    assert context is not None
    assert context.dedup_committed_constructs is True


def test_the_key_false_loads_false(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    context = _loaded(tmp_path, load_world, **{DEDUP_COMMITTED_KEY: False})
    assert context is not None
    assert context.dedup_committed_constructs is False


def test_a_string_value_is_refused_naming_the_key_and_the_type(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    with pytest.raises(EvaluationConfigError) as record:
        _loaded(tmp_path, load_world, **{DEDUP_COMMITTED_KEY: "true"})

    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert DEDUP_COMMITTED_KEY in message
    # The type found, not only the value: the repair is "write a JSON
    # boolean", and the message has to say what arrived instead.
    assert "str" in message


def test_a_number_value_is_refused_too(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    # A truthy 1 is exactly the guess the refusal exists to not make.
    with pytest.raises(EvaluationConfigError) as record:
        _loaded(tmp_path, load_world, **{DEDUP_COMMITTED_KEY: 1})
    assert DEDUP_COMMITTED_KEY in str(record.value)


def test_an_unknown_keys_refusal_names_the_new_key(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    with pytest.raises(EvaluationConfigError) as record:
        _loaded(tmp_path, load_world, not_a_key=1)

    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert "not_a_key" in message
    assert DEDUP_COMMITTED_KEY in message


# -- (b) The pure comparison -------------------------------------------------


def test_equal_fingerprints_match() -> None:
    left = _construct_fingerprint(0.1, 2.0, 3.0, 0.25)
    right = _construct_fingerprint(0.1, 2.0, 3.0, 0.25)
    assert _fingerprints_match(left, right)


def test_a_one_e_minus_ten_difference_matches() -> None:
    left = _construct_fingerprint(0.1, 2.0, 3.0, 0.25)
    right = _construct_fingerprint(0.1, 2.0 + 1e-10, 3.0, 0.25)
    assert _fingerprints_match(left, right)


def test_a_one_e_minus_six_difference_does_not_match() -> None:
    left = _construct_fingerprint(0.1, 2.0, 3.0, 0.25)
    right = _construct_fingerprint(0.1, 2.0 + 1e-6, 3.0, 0.25)
    assert not _fingerprints_match(left, right)


@pytest.mark.parametrize("missing_index", (0, 1, 2, 3))
def test_any_none_on_either_side_never_matches(missing_index: int) -> None:
    complete = _construct_fingerprint(0.1, 2.0, 3.0, 0.25)
    incomplete = list(complete)
    incomplete[missing_index] = None
    assert not _fingerprints_match(tuple(incomplete), complete)
    assert not _fingerprints_match(complete, tuple(incomplete))


def test_two_none_fields_still_never_match() -> None:
    # The dangerous shape: two pre-feature-1 picks whose ir_tstat is NULL on
    # both sides would otherwise compare equal field-for-field.
    left = _construct_fingerprint(0.1, 2.0, None, 0.25)
    right = _construct_fingerprint(0.1, 2.0, None, 0.25)
    assert not _fingerprints_match(left, right)


# -- (c)-(f) The dedup through the real close-out -----------------------------

#: The quiet roots keep Gate A's and the KS diagnostic's samples on both sides
#: of their floors, so each campaign below closes out calibrated and the
#: commit's own choice is observable on a world that *is* persisted.
QUIET_NULLS = (
    (-0.05, -1.2, -0.9),
    (0.02, -0.5, -0.4),
    (-0.12, 0.3, 0.2),
    (0.07, 1.0, 0.8),
)
QUIET_REALS = ((-0.08, -0.8, -0.6), (0.03, 0.5, 0.3))


def _build_campaign(
    database_url: str,
    tmp_path: Path,
    *,
    config_sha256: str | None = CONFIG_SHA,
    created_at: str,
    contenders: tuple[tuple[str, float, float, float | None, float | None], ...],
) -> tuple[str, dict[str, str]]:
    """A campaign whose bar-clearing contenders the caller names explicitly.

    ``contenders`` is ``(node_id, ic_mean, ic_tstat, ir_tstat, turnover)`` per
    real contender.  Four quiet null roots and two quiet real roots keep both
    KS samples at or above :data:`nulloracle.KS_MIN_SAMPLE`, the fixture the
    sibling commit suites use.
    """
    campaign = str(uuid.uuid4())
    _plant_campaign(
        database_url,
        campaign_id=campaign,
        config_sha256=config_sha256,
        created_at=created_at,
    )
    null_ids = [
        _plant_node(
            database_url,
            campaign,
            node_id=str(uuid.uuid4()),
            ic_mean=ic_mean,
            ic_tstat=ic_tstat,
            ir_tstat=ir_tstat,
            turnover=0.2,
        )
        for ic_mean, ic_tstat, ir_tstat in QUIET_NULLS
    ]
    real_ids = [
        _plant_node(
            database_url,
            campaign,
            node_id=node_id,
            ic_mean=ic_mean,
            ic_tstat=ic_tstat,
            ir_tstat=ir_tstat,
            turnover=turnover,
        )
        for node_id, ic_mean, ic_tstat, ir_tstat, turnover in contenders
    ]
    real_ids += [
        _plant_node(
            database_url,
            campaign,
            node_id=str(uuid.uuid4()),
            ic_mean=ic_mean,
            ic_tstat=ic_tstat,
            ir_tstat=ir_tstat,
            turnover=0.2,
        )
        for ic_mean, ic_tstat, ir_tstat in QUIET_REALS
    ]
    for index, node_id in enumerate([*null_ids, *real_ids]):
        _charge_ledger(database_url, node_id, campaign, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    return campaign, env


def _duplicate_contender() -> tuple[str, float, float, float, float]:
    """Node ``B``: the same construct as the earlier campaign's pick -- all
    four stored figures identical, so its fingerprint *is* that pick's -- and
    ranked *above* the distinct contender, so a commit that did not dedup
    would pick it."""
    return (
        str(uuid.uuid4()),
        DUPLICATE_IC_MEAN,
        DUPLICATE_IC_TSTAT,
        DUPLICATE_IR_TSTAT,
        DUPLICATE_TURNOVER,
    )


def _distinct_contender() -> tuple[str, float, float, float, float]:
    """Node ``C``: a different construct, ``ir_tstat`` 2.5 -- above the bar and
    below the duplicate's, so the dedup is what makes it the pick."""
    return (
        str(uuid.uuid4()),
        DISTINCT_IC_MEAN,
        DISTINCT_IC_TSTAT,
        DISTINCT_IR_TSTAT,
        DISTINCT_TURNOVER,
    )


def _plant_earlier_pick(
    database_url: str,
    *,
    config_sha256: str,
    ir_tstat: float | None = DUPLICATE_IR_TSTAT,
) -> tuple[str, str]:
    """An earlier campaign under ``config_sha256`` that committed a node
    carrying the duplicate construct.  Answers ``(campaign_id, node_id)``.

    ``ir_tstat=None`` plants the pick's node row with the column NULL -- the
    shape a pre-feature-1 writer left, and test (f)'s own case."""
    earlier_id = str(uuid.uuid4())
    _plant_campaign(
        database_url,
        campaign_id=earlier_id,
        config_sha256=config_sha256,
        created_at="2026-10-21T03:38:34Z",
    )
    node_a = _plant_node(
        database_url,
        earlier_id,
        node_id=str(uuid.uuid4()),
        ic_mean=DUPLICATE_IC_MEAN,
        ic_tstat=DUPLICATE_IC_TSTAT,
        ir_tstat=ir_tstat,
        turnover=DUPLICATE_TURNOVER,
    )
    _record_earlier_commit(database_url, campaign_id=earlier_id, node_id=node_a)
    return earlier_id, node_a


def test_the_earlier_commit_is_read_back_as_its_nodes_fingerprint(
    database_url: str,
) -> None:
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    later = _plant_campaign(
        database_url,
        campaign_id=str(uuid.uuid4()),
        config_sha256=CONFIG_SHA,
        created_at="2026-10-21T09:16:00Z",
    )

    assert _earlier_committed_fingerprints(database_url, later) == [
        _construct_fingerprint(
            DUPLICATE_IC_MEAN,
            DUPLICATE_IC_TSTAT,
            DUPLICATE_IR_TSTAT,
            DUPLICATE_TURNOVER,
        )
    ]


def test_a_campaign_with_no_config_hash_is_never_a_duplicate(
    database_url: str,
) -> None:
    # "Same evaluation config hash" names no set for a campaign whose row
    # carries none, so there is nothing it could be a repeat of.
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    unrecorded = _plant_campaign(
        database_url,
        campaign_id=str(uuid.uuid4()),
        config_sha256=None,
        created_at="2026-10-21T09:16:00Z",
    )

    assert _earlier_committed_fingerprints(database_url, unrecorded) == []


def test_a_same_second_peer_is_not_earlier(database_url: str) -> None:
    # Strictly earlier, not "not later": two campaigns created in the same
    # second must not dedup against each other, or a series' first two
    # campaigns could each skip the other's construct.
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    same_second = _plant_campaign(
        database_url,
        campaign_id=str(uuid.uuid4()),
        config_sha256=CONFIG_SHA,
        created_at="2026-10-21T03:38:34Z",
    )

    assert _earlier_committed_fingerprints(database_url, same_second) == []


def test_the_flag_true_commits_the_distinct_construct(
    database_url: str, tmp_path: Path
) -> None:
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    duplicate = _duplicate_contender()
    distinct = _distinct_contender()
    campaign, env = _build_campaign(
        database_url,
        tmp_path,
        created_at="2026-10-21T09:16:00Z",
        contenders=(duplicate, distinct),
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign,
        database_url=database_url,
        scorer=scorer,
        sidecar=sidecar,
        context=_stub_context(dedup=True),
    )

    assert result.committed_pick == distinct[0]
    assert result.committed_pick != duplicate[0]
    assert result.dedup_skipped == 1
    assert result.dedup_against == 1
    payload = result.to_payload()
    assert payload["dedup_skipped"] == 1
    assert payload["dedup_against"] == 1
    # The duplicate is still a *discovery*: the dedup is the commit's rule,
    # never the calibration figures'.
    assert result.discoveries == 2

    rows = _replay_score_rows(database_url, world_id=campaign)
    assert len(rows) == 1
    policy_version, world_id, beta, score, committed_pick = rows[0]
    assert policy_version == M2_FIXED_POLICY_VERSION
    assert world_id == campaign
    assert beta == M2_FIXED_BETA
    assert committed_pick == distinct[0]
    # No OOS grid was configured, so the row carries the miss score.
    assert math.isinf(score) and score < 0


def test_the_flag_false_commits_the_duplicate_as_today(
    database_url: str, tmp_path: Path
) -> None:
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    duplicate = _duplicate_contender()
    distinct = _distinct_contender()
    campaign, env = _build_campaign(
        database_url,
        tmp_path,
        created_at="2026-10-21T09:16:00Z",
        contenders=(duplicate, distinct),
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign,
        database_url=database_url,
        scorer=scorer,
        sidecar=sidecar,
        context=_stub_context(dedup=False),
    )

    # The duplicate outranks the distinct contender, so today's rule picks it
    # -- and nothing was read, nothing skipped.
    assert result.committed_pick == duplicate[0]
    assert result.dedup_skipped == 0
    assert result.dedup_against == 0

    rows = _replay_score_rows(database_url, world_id=campaign)
    assert rows[0][4] == duplicate[0]


def test_no_context_at_all_behaves_as_the_flag_false(
    database_url: str, tmp_path: Path
) -> None:
    # The step-9 read is guarded on a context *being there*; every caller that
    # hands none (the incumbent-equivalence ground truth, a deployment with no
    # sidecar config) must keep today's pick and both counts at 0.
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    duplicate = _duplicate_contender()
    distinct = _distinct_contender()
    campaign, env = _build_campaign(
        database_url,
        tmp_path,
        created_at="2026-10-21T09:16:00Z",
        contenders=(duplicate, distinct),
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign, database_url=database_url, scorer=scorer, sidecar=sidecar
    )

    assert result.committed_pick == duplicate[0]
    assert result.dedup_skipped == 0
    assert result.dedup_against == 0


def test_a_different_config_hash_counts_nothing(
    database_url: str, tmp_path: Path
) -> None:
    # The same fingerprint, but committed under a *different* evaluation config
    # hash: a different snapshot and a different book, so the construct is not
    # the one this campaign is a repeat of.
    _plant_earlier_pick(database_url, config_sha256=OTHER_CONFIG_SHA)
    duplicate = _duplicate_contender()
    distinct = _distinct_contender()
    campaign, env = _build_campaign(
        database_url,
        tmp_path,
        created_at="2026-10-21T09:16:00Z",
        contenders=(duplicate, distinct),
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign,
        database_url=database_url,
        scorer=scorer,
        sidecar=sidecar,
        context=_stub_context(dedup=True),
    )

    assert result.dedup_against == 0
    assert result.dedup_skipped == 0
    assert result.committed_pick == duplicate[0]


def test_a_duplicate_only_campaign_abstains(
    database_url: str, tmp_path: Path
) -> None:
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA)
    duplicate = _duplicate_contender()
    campaign, env = _build_campaign(
        database_url,
        tmp_path,
        created_at="2026-10-21T09:16:00Z",
        contenders=(duplicate,),
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign,
        database_url=database_url,
        scorer=scorer,
        sidecar=sidecar,
        context=_stub_context(dedup=True),
    )

    assert result.committed_pick is None
    assert result.dedup_skipped == 1
    assert result.dedup_against == 1
    # The abstention is not a VOID: the world is still persisted, under the
    # miss rule every abstention takes.
    assert not result.is_void
    assert result.world_persisted is True

    rows = _replay_score_rows(database_url, world_id=campaign)
    assert len(rows) == 1
    _policy_version, _world_id, _beta, score, committed_pick = rows[0]
    assert committed_pick is None
    assert score == replay.NON_COMMITTING_SCORE
    assert math.isinf(score) and score < 0


def test_an_earlier_pick_with_a_null_fingerprint_field_never_matches(
    database_url: str, tmp_path: Path
) -> None:
    # An earlier campaign whose committed node has no stored ir_tstat -- a tree
    # a pre-feature-1 writer evaluated -- fingerprints no construct: the later
    # campaign's otherwise-identical node is *not* a duplicate, and the commit
    # takes the highest ir_tstat as it always did.
    _plant_earlier_pick(database_url, config_sha256=CONFIG_SHA, ir_tstat=None)
    duplicate = _duplicate_contender()
    distinct = _distinct_contender()
    campaign, env = _build_campaign(
        database_url,
        tmp_path,
        created_at="2026-10-21T09:16:00Z",
        contenders=(duplicate, distinct),
    )
    scorer, sidecar = _resolved_scorer_and_sidecar(env)

    result = close_out(
        campaign,
        database_url=database_url,
        scorer=scorer,
        sidecar=sidecar,
        context=_stub_context(dedup=True),
    )

    # The earlier pick *was* read -- dedup_against counts the pick, not the
    # match -- but its NULL ir_tstat names no construct to compare against.
    assert result.dedup_against == 1
    assert result.dedup_skipped == 0
    assert result.committed_pick == duplicate[0]
