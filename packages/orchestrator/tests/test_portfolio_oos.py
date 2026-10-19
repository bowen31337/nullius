"""Feature 6, additions_spec_engine_edge_recovery.xml, "Portfolio Scoring":
*System scores a set of committed picks as one equal-weight book out of
sample and reports its mean, volatility, t-statistic and effective number of
independent bets beside each pick's own.*

The aggregation math (``score_portfolio``) is driven with ``_score_pick_oos``
monkeypatched -- the sandboxed, expensive act every sibling suite in this
member stubs out the same way (``evaluate_on_dates`` on
``orchestrator._financial_eval`` in ``test_financial_world_admission.py``) --
so these tests prove the book's own arithmetic, never the sandbox.  The
admission half (an excluded pick, "nothing written to the store") drives a
real, migrated SQLite database the way that same suite does, because
admission *is* a store read this module does not stub.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import pytest
from orchestrator import portfolio_oos
from orchestrator.portfolio_oos import (
    PORTFOLIO_OOS_CODE,
    PortfolioOosError,
    PortfolioPick,
    ScoredPick,
    load_picks_file,
    load_picks_policy_version,
    main,
    score_portfolio,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
GRID_MIGRATION = "0120_campaign_evaluation_grid"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")
REPLAY_SCORE_MIGRATION = "0109_replay_score_and_policy_revision"

DATES = (
    dt.date(2026, 6, 1),
    dt.date(2026, 6, 2),
    dt.date(2026, 6, 3),
    dt.date(2026, 6, 4),
)

#: A series with mean 0.5, population variance 1.
_SERIES_A = (1.5, -0.5, 1.5, -0.5)
#: A series with mean 0.5, population variance 1, zero covariance with
#: ``_SERIES_A`` over :data:`DATES` (the classic orthogonal-contrast pair).
_SERIES_B_UNCORRELATED = (1.5, 1.5, -0.5, -0.5)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_portfolio_oos_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sqlite_path(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


class _StubContext:
    """A stand-in for :class:`orchestrator._context.EvaluationContext`
    carrying only what :func:`score_portfolio` itself reads by attribute --
    everything the sandboxed scoring path reads is behind the
    ``_score_pick_oos`` monkeypatch in every test below."""

    def __init__(self, database_url: str, oos_dates: tuple[dt.date, ...] = ()) -> None:
        self.database_url = database_url
        self.oos_dates = oos_dates


def _scored(
    pick: PortfolioPick,
    series: tuple[float, ...],
    *,
    horizon: int = 5,
    theme: str | None = "macro",
    ic_tstat: float = 2.5,
) -> ScoredPick:
    return ScoredPick(
        pick=pick,
        horizon=horizon,
        theme=theme,
        book_returns=dict(zip(DATES, series)),
        ic_series={day: 0.1 for day in DATES},
        ic_tstat=ic_tstat,
    )


def _stub_scorer(fixtures: dict[tuple[str, str], ScoredPick]):
    def _stub(pick: PortfolioPick, *, evaluation_context: Any) -> ScoredPick:
        key = (pick.campaign_id, pick.node_id)
        assert key in fixtures, f"unexpected pick scored: {pick!r}"
        return fixtures[key]

    return _stub


# -- The aggregation math: N_eff, the portfolio t, the mean correlation ------


def test_two_uncorrelated_picks_give_n_eff_two_and_the_known_portfolio_t(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pick_a = PortfolioPick(campaign_id="world-a", node_id="node-a")
    pick_b = PortfolioPick(campaign_id="world-b", node_id="node-b")
    fixtures = {
        ("world-a", "node-a"): _scored(pick_a, _SERIES_A),
        ("world-b", "node-b"): _scored(pick_b, _SERIES_B_UNCORRELATED),
    }
    monkeypatch.setattr(portfolio_oos, "_score_pick_oos", _stub_scorer(fixtures))
    monkeypatch.setattr(
        portfolio_oos,
        "_admit",
        lambda picks, **_: (tuple(picks), ()),
    )

    context = _StubContext("sqlite:///unused.db")
    result = score_portfolio([pick_a, pick_b], evaluation_context=context)

    summary = result.summary
    assert summary["K"] == 2
    assert summary["mean"] == pytest.approx(0.5)
    assert summary["sd"] == pytest.approx(math.sqrt(0.5))
    assert summary["t"] == pytest.approx(math.sqrt(2))
    assert summary["N_eff"] == pytest.approx(2.0)
    assert summary["mean_pairwise_correlation"] == pytest.approx(0.0, abs=1e-12)
    assert summary["oos_dates"] == 4
    assert {row["campaign_id"] for row in summary["picks"]} == {"world-a", "world-b"}
    for row in summary["picks"]:
        assert row["mean"] == pytest.approx(0.5)
        assert row["sd"] == pytest.approx(1.0)
        assert row["t"] == pytest.approx(1.0)
        assert row["oos_ic_t"] == pytest.approx(2.5)
        assert row["horizon"] == 5
    assert summary["excluded"] == []
    assert set(summary["themes"]) == {"macro"}
    theme_row = summary["themes"]["macro"]
    assert theme_row["K"] == 2
    assert theme_row["mean"] == pytest.approx(0.5)
    assert theme_row["sd"] == pytest.approx(math.sqrt(0.5))
    assert theme_row["t"] == pytest.approx(math.sqrt(2))


def test_two_identical_picks_give_n_eff_one(monkeypatch: pytest.MonkeyPatch) -> None:
    pick_a = PortfolioPick(campaign_id="world-a", node_id="node-a")
    pick_b = PortfolioPick(campaign_id="world-b", node_id="node-b")
    fixtures = {
        ("world-a", "node-a"): _scored(pick_a, _SERIES_A),
        ("world-b", "node-b"): _scored(pick_b, _SERIES_A),
    }
    monkeypatch.setattr(portfolio_oos, "_score_pick_oos", _stub_scorer(fixtures))
    monkeypatch.setattr(portfolio_oos, "_admit", lambda picks, **_: (tuple(picks), ()))

    context = _StubContext("sqlite:///unused.db")
    result = score_portfolio([pick_a, pick_b], evaluation_context=context)

    summary = result.summary
    assert summary["N_eff"] == pytest.approx(1.0)
    assert summary["mean_pairwise_correlation"] == pytest.approx(1.0)
    assert summary["mean"] == pytest.approx(0.5)
    assert summary["sd"] == pytest.approx(1.0)
    assert summary["t"] == pytest.approx(1.0)


def test_fewer_than_two_admitted_picks_is_refused_with_its_own_code_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pick_a = PortfolioPick(campaign_id="world-a", node_id="node-a")
    monkeypatch.setattr(portfolio_oos, "_admit", lambda picks, **_: ((pick_a,), ()))

    context = _StubContext("sqlite:///unused.db")
    with pytest.raises(PortfolioOosError) as excinfo:
        score_portfolio([pick_a], evaluation_context=context)
    assert str(excinfo.value).startswith(PORTFOLIO_OOS_CODE)


# -- Admission: an excluded pick is reported, and the store is untouched ----


def _campaign_database(tmp_path: Path, name: str) -> str:
    database_url = f"sqlite:///{tmp_path / name}"
    _load_migration(CAMPAIGN_MIGRATION).apply(database_url)
    _load_migration(GRID_MIGRATION).apply(database_url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)
    return database_url


def _plant_node(
    database_url: str, campaign_id: str, node_id: str, *, theme_root: str = "macro"
) -> None:
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, 0.4, 1.0)",
            (node_id, campaign_id, theme_root),
        )


def _build_campaign(
    database_url: str,
    *,
    grid_first_date: str | None = None,
    grid_last_date: str | None = None,
    theme_root: str = "macro",
) -> tuple[str, str]:
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE,
        4,
        campaign_id=campaign_id,
        database_url=database_url,
        horizon=5,
        grid_first_date=grid_first_date,
        grid_last_date=grid_last_date,
    )
    node_id = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id, theme_root=theme_root)
    discovery.finish_campaign(campaign_id, database_url=database_url)
    return campaign_id, node_id


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_an_excluded_pick_is_reported_and_the_store_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oos_first = dt.date(2026, 6, 1)
    database_url = _campaign_database(tmp_path, "portfolio-admission.db")

    campaign_a, node_a = _build_campaign(
        database_url, grid_first_date="2026-05-01", grid_last_date="2026-05-20"
    )
    campaign_b, node_b = _build_campaign(
        database_url, grid_first_date="2026-05-01", grid_last_date="2026-05-20"
    )
    # No grid_last_date recorded at all -- excluded as unknown, since the
    # context below carries an out-of-sample grid.
    campaign_c, node_c = _build_campaign(database_url)

    pick_a = PortfolioPick(campaign_id=campaign_a, node_id=node_a)
    pick_b = PortfolioPick(campaign_id=campaign_b, node_id=node_b)
    pick_c = PortfolioPick(campaign_id=campaign_c, node_id=node_c)

    fixtures = {
        (campaign_a, node_a): _scored(pick_a, _SERIES_A),
        (campaign_b, node_b): _scored(pick_b, _SERIES_B_UNCORRELATED),
    }
    monkeypatch.setattr(portfolio_oos, "_score_pick_oos", _stub_scorer(fixtures))

    before = _file_digest(_sqlite_path(database_url))
    context = _StubContext(database_url, oos_dates=(oos_first,))
    result = score_portfolio([pick_a, pick_b, pick_c], evaluation_context=context)
    after = _file_digest(_sqlite_path(database_url))

    assert before == after, "portfolio_oos must write nothing to the store"
    assert result.summary["K"] == 2
    excluded = result.summary["excluded"]
    assert len(excluded) == 1
    assert excluded[0]["campaign_id"] == campaign_c
    assert excluded[0]["node_id"] == node_c
    assert "financial_world_admission" in excluded[0]["reason"]
    assert "grid_last_date" in excluded[0]["reason"]


# -- --policy-version: one committed pick per world, the latest row ---------


def _replay_score_database(tmp_path: Path, name: str) -> str:
    database_url = f"sqlite:///{tmp_path / name}"
    _load_migration(REPLAY_SCORE_MIGRATION).apply(database_url)
    return database_url


def _insert_replay_score(
    database_url: str,
    *,
    policy_version: str,
    world_id: str,
    committed_pick: str | None,
    created_at: str,
) -> None:
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO replay_score (id, policy_version, world_id, beta, "
            "score, committed_pick, is_holdout, created_at) VALUES "
            "(?, ?, ?, 0.5, 0.1, ?, 0, ?)",
            (str(uuid.uuid4()), policy_version, world_id, committed_pick, created_at),
        )


def test_policy_version_reads_the_fixture_rows_one_per_world(tmp_path: Path) -> None:
    database_url = _replay_score_database(tmp_path, "replay-score.db")
    # world w1 is re-scored under v1; the later row's pick must win.
    _insert_replay_score(
        database_url,
        policy_version="v1",
        world_id="w1",
        committed_pick="n1-old",
        created_at="2026-06-01T00:00:00+00:00",
    )
    _insert_replay_score(
        database_url,
        policy_version="v1",
        world_id="w1",
        committed_pick="n1-new",
        created_at="2026-06-02T00:00:00+00:00",
    )
    _insert_replay_score(
        database_url,
        policy_version="v1",
        world_id="w2",
        committed_pick="n2",
        created_at="2026-06-01T00:00:00+00:00",
    )
    # A miss under v1 -- no pick, so no row in the answer.
    _insert_replay_score(
        database_url,
        policy_version="v1",
        world_id="w3",
        committed_pick=None,
        created_at="2026-06-01T00:00:00+00:00",
    )
    # A different policy version -- must not leak into v1's answer.
    _insert_replay_score(
        database_url,
        policy_version="other",
        world_id="w4",
        committed_pick="n4",
        created_at="2026-06-01T00:00:00+00:00",
    )

    picks = load_picks_policy_version(database_url, "v1")

    assert set(picks) == {
        PortfolioPick(campaign_id="w1", node_id="n1-new"),
        PortfolioPick(campaign_id="w2", node_id="n2"),
    }


# -- --picks: a JSON file of {"campaign_id", "node_id"} ----------------------


def test_load_picks_file_reads_a_json_list(tmp_path: Path) -> None:
    path = tmp_path / "picks.json"
    path.write_text(
        json.dumps(
            [
                {"campaign_id": "world-a", "node_id": "node-a"},
                {"campaign_id": "world-b", "node_id": "node-b"},
            ]
        ),
        encoding="utf-8",
    )
    picks = load_picks_file(str(path))
    assert picks == (
        PortfolioPick(campaign_id="world-a", node_id="node-a"),
        PortfolioPick(campaign_id="world-b", node_id="node-b"),
    )


def test_load_picks_file_refuses_a_malformed_entry(tmp_path: Path) -> None:
    path = tmp_path / "picks.json"
    path.write_text(json.dumps([{"campaign_id": "world-a"}]), encoding="utf-8")
    with pytest.raises(PortfolioOosError) as excinfo:
        load_picks_file(str(path))
    assert str(excinfo.value).startswith(PORTFOLIO_OOS_CODE)


# -- main(): the JSON line's fields, and --out --------------------------------


def test_main_prints_one_json_line_with_every_required_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pick_a = PortfolioPick(campaign_id="world-a", node_id="node-a")
    pick_b = PortfolioPick(campaign_id="world-b", node_id="node-b")
    fixtures = {
        ("world-a", "node-a"): _scored(pick_a, _SERIES_A),
        ("world-b", "node-b"): _scored(pick_b, _SERIES_B_UNCORRELATED),
    }
    monkeypatch.setattr(portfolio_oos, "_score_pick_oos", _stub_scorer(fixtures))
    monkeypatch.setattr(portfolio_oos, "_admit", lambda picks, **_: (tuple(picks), ()))

    database_url = f"sqlite:///{tmp_path / 'unused.db'}"
    context = _StubContext(database_url)
    monkeypatch.setattr(
        portfolio_oos, "load_evaluation_context", lambda env: context
    )

    picks_path = tmp_path / "picks.json"
    picks_path.write_text(
        json.dumps(
            [
                {"campaign_id": "world-a", "node_id": "node-a"},
                {"campaign_id": "world-b", "node_id": "node-b"},
            ]
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "series.json"

    lines: list[str] = []
    exit_code = main(
        ["--picks", str(picks_path), "--out", str(out_path)],
        env={"NULLIUS_EVALUATION_CONFIG": "irrelevant-with-the-stub-above"},
        emit=lines.append,
    )

    assert exit_code == 0
    assert len(lines) == 1
    summary = json.loads(lines[0])
    for field in (
        "K",
        "mean",
        "sd",
        "t",
        "N_eff",
        "mean_pairwise_correlation",
        "oos_dates",
        "picks",
        "excluded",
        "themes",
    ):
        assert field in summary, field
    assert summary["K"] == 2

    series = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(series["portfolio"].keys()) == {day.isoformat() for day in DATES}
    assert set(series["picks"].keys()) == {"world-a:node-a", "world-b:node-b"}
    for entry in series["picks"].values():
        assert "book_returns" in entry
        assert "ic_series" in entry


def test_main_refuses_fewer_than_two_admitted_picks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pick_a = PortfolioPick(campaign_id="world-a", node_id="node-a")
    monkeypatch.setattr(portfolio_oos, "_admit", lambda picks, **_: ((pick_a,), ()))
    database_url = f"sqlite:///{tmp_path / 'unused.db'}"
    monkeypatch.setattr(
        portfolio_oos, "load_evaluation_context", lambda env: _StubContext(database_url)
    )

    picks_path = tmp_path / "picks.json"
    picks_path.write_text(
        json.dumps([{"campaign_id": "world-a", "node_id": "node-a"}]), encoding="utf-8"
    )

    lines: list[str] = []
    exit_code = main(
        ["--picks", str(picks_path)],
        env={"NULLIUS_EVALUATION_CONFIG": "irrelevant-with-the-stub-above"},
        emit=lines.append,
    )

    assert exit_code == portfolio_oos.EXIT_REFUSED
    assert lines == []


def test_main_requires_an_evaluation_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(portfolio_oos, "load_evaluation_context", lambda env: None)
    picks_path = tmp_path / "picks.json"
    picks_path.write_text(
        json.dumps([{"campaign_id": "world-a", "node_id": "node-a"}]), encoding="utf-8"
    )

    exit_code = main(["--picks", str(picks_path)], env={}, emit=lambda line: None)

    assert exit_code == portfolio_oos.EXIT_CONFIG


def test_main_refuses_to_overwrite_an_existing_out_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pick_a = PortfolioPick(campaign_id="world-a", node_id="node-a")
    pick_b = PortfolioPick(campaign_id="world-b", node_id="node-b")
    fixtures = {
        ("world-a", "node-a"): _scored(pick_a, _SERIES_A),
        ("world-b", "node-b"): _scored(pick_b, _SERIES_B_UNCORRELATED),
    }
    monkeypatch.setattr(portfolio_oos, "_score_pick_oos", _stub_scorer(fixtures))
    monkeypatch.setattr(portfolio_oos, "_admit", lambda picks, **_: (tuple(picks), ()))
    database_url = f"sqlite:///{tmp_path / 'unused.db'}"
    monkeypatch.setattr(
        portfolio_oos, "load_evaluation_context", lambda env: _StubContext(database_url)
    )

    picks_path = tmp_path / "picks.json"
    picks_path.write_text(
        json.dumps(
            [
                {"campaign_id": "world-a", "node_id": "node-a"},
                {"campaign_id": "world-b", "node_id": "node-b"},
            ]
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "series.json"
    out_path.write_text("already here", encoding="utf-8")

    lines: list[str] = []
    exit_code = main(
        ["--picks", str(picks_path), "--out", str(out_path)],
        env={"NULLIUS_EVALUATION_CONFIG": "irrelevant-with-the-stub-above"},
        emit=lines.append,
    )

    assert exit_code == portfolio_oos.EXIT_REFUSED
    assert lines == []
    assert out_path.read_text(encoding="utf-8") == "already here"
