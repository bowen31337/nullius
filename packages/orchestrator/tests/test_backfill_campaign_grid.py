"""The campaign-grid backfill — ``python -m orchestrator.backfill_campaign_grid``.

additions_spec_engine_edge_recovery.xml, "Campaign Grid", feature 4, fourth
step, second half: *"orchestrator (new file): the backfill maps each of the
three fixture grids to the right horizon and dates, leaves an unknown grid
NULL with a report, is a no-op on a second run, and ``--dry-run`` changes
nothing."*

Every test drives :func:`orchestrator.backfill_campaign_grid.main` (or
:func:`~orchestrator.backfill_campaign_grid.backfill` directly) over a
throwaway SQLite database and a throwaway artifact root under pytest's
temporary directory — the injectable seams the module names — never a real
subprocess and never the operator's own store.

The three fixture grids are built **through the artifacts member's own
writer** (:func:`artifacts.persist_ic_series` plus
:meth:`artifacts.ArtifactStore.commit`), not by hand-writing Parquet: a
fixture that rendered its own file would be pinning this command against a
format this test made up, and the whole point of reading the grid off the
artifact is that the artifact's format is the artifacts member's.

Beyond the four claims the spec names, two are pinned because a backfill that
got them wrong would corrupt rather than merely fail: the three columns land
*together* (a row with a horizon and no dates is not a grid), and the two
columns the spec says stay NULL (**``evaluation_config_sha256`` and
``oos_first_date``**) are never written — the difference between a backfilled
row and a driver-written one, which feature 5's admission reads.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest
from artifacts import ArtifactStore, persist_ic_series
from orchestrator.backfill_campaign_grid import (
    BACKFILL_CODE,
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    main,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up — the same resolution
# test_campaign_cli.py and test_campaign.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
GRID_MIGRATION = "0120_campaign_evaluation_grid"

#: The campaign table's columns this command's tests read directly.  Named so
#: a rename is one edit, and so the two the command must *not* write are as
#: visible as the three it must.
CONFIG_SHA_COLUMN = "evaluation_config_sha256"
OOS_FIRST_COLUMN = "oos_first_date"

FIRST_DATE = dt.date(2026, 1, 2)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_backfill_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    return Path(database_url.removeprefix("sqlite:///"))


# -- The fixtures -----------------------------------------------------------------


@pytest.fixture
def grid_database(tmp_path: Path) -> str:
    """A throwaway database at ``0111`` + ``0120`` — the columns exist."""
    url = f"sqlite:///{tmp_path / 'backfill-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    _load_migration(GRID_MIGRATION).apply(url)
    return url


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    """A throwaway artifact root under this test's temporary directory."""
    return ArtifactStore(tmp_path / "artifacts")


def _insert_campaign(
    database_url: str,
    *,
    horizon: int | None = None,
    grid_first: str | None = None,
    grid_last: str | None = None,
    config_sha: str | None = None,
    oos_first: str | None = None,
) -> str:
    """One campaign row, raw SQL — this suite is about the command, not the store.

    Deliberately bypassing :class:`discovery.CampaignRecords`: the backfill
    reads campaign *rows*, and a fixture that routed through the store would
    be exercising the store's own write path instead of producing the state
    under test.  Returns the minted id.
    """
    identifier = str(uuid.uuid4())
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO campaign (id, campaign_type, workspace_count, "
            "null_fraction, horizon, grid_first_date, grid_last_date, "
            "evaluation_config_sha256, oos_first_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                "Type-R",
                12,
                0.1667,
                horizon,
                grid_first,
                grid_last,
                config_sha,
                oos_first,
            ),
        )
    return identifier


def _persist_grid(
    store: ArtifactStore,
    campaign_id: str,
    dates: list[dt.date],
    *,
    node_id: str | None = None,
) -> str:
    """Publish one node whose ``ic_series.parquet`` is keyed by ``dates``."""
    identifier = node_id or str(uuid.uuid4())
    series = {day: float(index) for index, day in enumerate(dates)}
    persist_ic_series(store, campaign_id, identifier, series)
    store.commit(campaign_id, identifier)
    return identifier


def _grid(count: int, spacing: int) -> list[dt.date]:
    return [FIRST_DATE + dt.timedelta(days=spacing * index) for index in range(count)]


def _read_row(database_url: str, campaign_id: str) -> tuple:
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        return connection.execute(
            "SELECT horizon, grid_first_date, grid_last_date, "
            "evaluation_config_sha256, oos_first_date FROM campaign "
            "WHERE id = ?",
            (campaign_id,),
        ).fetchone()


def _run(database_url: str, store: ArtifactStore, *args: str, **kwargs) -> list[dict]:
    lines: list[str] = []
    code = main(
        list(args),
        env={"DATABASE_URL": database_url},
        artifact_store=store,
        emit=lines.append,
        **kwargs,
    )
    assert code == EXIT_OK, lines
    assert lines, "the command always prints at least the summary line"
    return [json.loads(line) for line in lines]


def _campaign_lines(lines: list[dict]) -> list[dict]:
    return [line for line in lines if line["event"] == "campaign"]


def _summary(lines: list[dict]) -> dict:
    return lines[-1]


# -- The three grids --------------------------------------------------------------


class TestTheThreeGrids:
    @pytest.mark.parametrize(
        "count, spacing, horizon",
        [
            (183, 7, 5),
            (235, 7, 5),
            (92, 14, 10),
            (92, 1, 1),
        ],
    )
    def test_each_known_grid_maps_to_its_horizon_and_dates(
        self, grid_database: str, store: ArtifactStore, count, spacing, horizon
    ) -> None:
        campaign = _insert_campaign(grid_database)
        dates = _grid(count, spacing)
        _persist_grid(store, campaign, dates)

        lines = _run(grid_database, store)
        campaign_lines = _campaign_lines(lines)
        assert len(campaign_lines) == 1
        line = campaign_lines[0]
        assert line["status"] == "filled"
        assert line["campaign_id"] == campaign
        assert line["horizon"] == horizon
        assert line["grid_first_date"] == dates[0].isoformat()
        assert line["grid_last_date"] == dates[-1].isoformat()
        assert line["dates"] == count

        assert _read_row(grid_database, campaign)[:3] == (
            horizon,
            dates[0].isoformat(),
            dates[-1].isoformat(),
        )

    def test_the_two_92_date_grids_are_told_apart_by_their_spacing(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # The case a count-alone rule would get wrong: 92 dates at 14-day
        # spacing is the biweekly grid (horizon 10) and 92 at 1-day spacing
        # is the daily one (horizon 1), so this test is what pins that the
        # implementation reads the dates rather than only counting them.
        biweekly = _insert_campaign(grid_database)
        daily = _insert_campaign(grid_database)
        _persist_grid(store, biweekly, _grid(92, 14))
        _persist_grid(store, daily, _grid(92, 1))

        by_id = {line["campaign_id"]: line for line in _campaign_lines(_run(grid_database, store))}
        assert by_id[biweekly]["horizon"] == 10
        assert by_id[daily]["horizon"] == 1

    def test_one_node_is_enough_and_the_walk_skips_a_node_with_no_series(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # A campaign whose first node published nothing (a failed evaluation)
        # still has a grid, readable off the node that did publish.
        campaign = _insert_campaign(grid_database)
        dates = _grid(92, 14)
        _persist_grid(store, campaign, dates, node_id="a" * 32)
        # A second node with a *different* series proves the first readable
        # one is the one used — the grid is the campaign's, not a union.
        _persist_grid(store, campaign, _grid(5, 1), node_id="b" * 32)

        line = _campaign_lines(_run(grid_database, store))[0]
        assert line["horizon"] == 10
        assert line["grid_last_date"] == dates[-1].isoformat()


# -- The unknown grid -------------------------------------------------------------


class TestAnUnknownGrid:
    @pytest.mark.parametrize(
        "count, spacing",
        [
            (50, 3),  # an irregular grid
            (92, 7),  # 92 weekly dates — not one of the three
            (183, 1),  # 183 daily dates
            (1, 0),  # a single date: no spacing to read
        ],
    )
    def test_it_is_reported_with_a_reason_and_left_null(
        self, grid_database: str, store: ArtifactStore, count, spacing
    ) -> None:
        campaign = _insert_campaign(grid_database)
        _persist_grid(store, campaign, _grid(count, spacing))

        lines = _run(grid_database, store)
        line = _campaign_lines(lines)[0]
        assert line["status"] == "left_null"
        assert line["reason"] == "unknown_grid"
        assert line["dates"] == count
        # No horizon is claimed anywhere on the line, and none landed.
        assert "horizon" not in line
        assert _read_row(grid_database, campaign) == (None,) * 5
        assert _summary(lines)["left_null"] == 1

    def test_a_campaign_with_no_artifacts_at_all_is_reported(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        _insert_campaign(grid_database)

        lines = _run(grid_database, store)
        line = _campaign_lines(lines)[0]
        assert line["status"] == "left_null"
        assert line["reason"] == "no_artifact_node"
        assert line["dates"] == 0

    def test_a_node_directory_with_no_series_is_reported_by_its_own_reason(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # Distinguishable from "no artifacts at all": the directory exists
        # and the file does not, which is a different operator action.
        campaign = _insert_campaign(grid_database)
        # ``node_directory`` itself creates the directory (idempotently), so
        # the node is listed with no ``ic_series.parquet`` in it — the state
        # a run that failed before metrics leaves behind.
        store.node_directory(campaign, "c" * 32)

        line = _campaign_lines(_run(grid_database, store))[0]
        assert line["reason"] == "no_ic_series"

    def test_a_series_this_codec_refuses_is_reported_not_raised(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # Bytes the artifacts member did not write: the campaign is reported
        # and the run continues rather than aborting on one bad file.
        campaign = _insert_campaign(grid_database)
        healthy = _insert_campaign(grid_database)
        store.write(campaign, "d" * 32, "ic_series.parquet", b"not parquet")
        store.commit(campaign, "d" * 32)
        _persist_grid(store, healthy, _grid(92, 1))

        lines = _run(grid_database, store)
        by_id = {line["campaign_id"]: line for line in _campaign_lines(lines)}
        assert by_id[campaign]["status"] == "left_null"
        assert by_id[campaign]["reason"] == "unreadable_ic_series"
        assert by_id[healthy]["status"] == "filled"
        assert _summary(lines) == {
            "event": "summary",
            "seen": 2,
            "filled": 1,
            "left_null": 1,
            "dry_run": False,
        }


# -- Idempotence and --dry-run ----------------------------------------------------


class TestIdempotenceAndDryRun:
    def test_a_second_run_is_a_no_op_and_says_so(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        campaign = _insert_campaign(grid_database)
        dates = _grid(183, 7)
        _persist_grid(store, campaign, dates)

        first = _run(grid_database, store)
        after_first = _read_row(grid_database, campaign)
        assert _summary(first)["filled"] == 1

        second = _run(grid_database, store)
        assert _campaign_lines(second) == []
        assert _summary(second) == {
            "event": "summary",
            "seen": 0,
            "filled": 0,
            "left_null": 0,
            "dry_run": False,
        }
        assert _read_row(grid_database, campaign) == after_first

    def test_dry_run_changes_nothing_and_reports_what_it_would_write(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        campaign = _insert_campaign(grid_database)
        dates = _grid(235, 7)
        _persist_grid(store, campaign, dates)

        lines = _run(grid_database, store, "--dry-run")
        line = _campaign_lines(lines)[0]
        assert line["dry_run"] is True
        assert line["status"] == "filled"
        assert line["horizon"] == 5
        assert line["grid_last_date"] == dates[-1].isoformat()
        assert _summary(lines)["dry_run"] is True
        # Nothing landed: every one of the five columns is still NULL.
        assert _read_row(grid_database, campaign) == (None,) * 5

    def test_dry_run_then_a_real_run_fills_exactly_what_was_rehearsed(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        campaign = _insert_campaign(grid_database)
        dates = _grid(92, 14)
        _persist_grid(store, campaign, dates)

        rehearsed = _campaign_lines(_run(grid_database, store, "--dry-run"))[0]
        real = _campaign_lines(_run(grid_database, store))[0]
        # Same shape either way, but for the flag — the property that makes
        # a rehearsal diffable against the run it preceded.
        for field in ("campaign_id", "status", "horizon", "grid_first_date", "grid_last_date"):
            assert rehearsed[field] == real[field], field
        assert rehearsed["dry_run"] is True and real["dry_run"] is False


# -- What the command writes, and what it must not --------------------------------


class TestWhatIsWritten:
    def test_the_two_columns_that_stay_null_are_never_written(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # The spec's own words: "evaluation_config_sha256 and oos_first_date
        # stay NULL for backfilled rows".  Feature 5's admission reads these
        # to tell a backfilled row from a driver-written one, so a value here
        # would be a fabricated fact about a configuration nobody read.
        campaign = _insert_campaign(grid_database)
        _persist_grid(store, campaign, _grid(92, 1))

        _run(grid_database, store)
        row = _read_row(grid_database, campaign)
        assert row[3] is None, CONFIG_SHA_COLUMN
        assert row[4] is None, OOS_FIRST_COLUMN

    def test_an_already_filled_campaign_is_not_selected_never_mind_rewritten(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # A driver-written row carrying a grid the *artifacts* disagree with
        # — the row is authoritative and this command must not touch it.
        digest = hashlib.sha256(b"config").hexdigest()
        campaign = _insert_campaign(
            grid_database,
            horizon=5,
            grid_first="2026-01-02",
            grid_last="2026-09-30",
            config_sha=digest,
            oos_first="2026-10-01",
        )
        _persist_grid(store, campaign, _grid(92, 1))  # would say horizon 1

        lines = _run(grid_database, store)
        assert _campaign_lines(lines) == []
        assert _read_row(grid_database, campaign) == (
            5,
            "2026-01-02",
            "2026-09-30",
            digest,
            "2026-10-01",
        )

    def test_the_three_columns_land_together(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # A row with a horizon and no dates is not a grid, and feature 5's
        # admission compares the two ends — so the three are written in one
        # statement and a reader never sees a partial grid.
        campaign = _insert_campaign(grid_database)
        dates = _grid(183, 7)
        _persist_grid(store, campaign, dates)
        _run(grid_database, store)

        horizon, grid_first, grid_last, _, _ = _read_row(grid_database, campaign)
        assert horizon is not None
        assert grid_first is not None and grid_last is not None
        assert grid_first <= grid_last

    def test_campaigns_are_reported_in_id_order(
        self, grid_database: str, store: ArtifactStore
    ) -> None:
        # Deterministic output is what makes two runs' lines diffable.
        campaigns = sorted(
            _insert_campaign(grid_database) for _ in range(4)
        )
        for campaign in campaigns:
            _persist_grid(store, campaign, _grid(92, 1))

        reported = [line["campaign_id"] for line in _campaign_lines(_run(grid_database, store))]
        assert reported == campaigns


# -- The command's own refusals ---------------------------------------------------


class TestTheCommandRefuses:
    def test_a_missing_database_url_exits_2_naming_it_and_prints_nothing(self) -> None:
        # A backfill with nothing to do and a backfill that could not run
        # must never look alike.
        import io
        from contextlib import redirect_stderr

        stderr = io.StringIO()
        lines: list[str] = []
        with redirect_stderr(stderr):
            code = main([], env={}, emit=lines.append)

        assert code == EXIT_CONFIG
        assert lines == []
        message = stderr.getvalue()
        assert "DATABASE_URL" in message
        assert BACKFILL_CODE in message
        assert "Traceback" not in message
        assert message.count("\n") == 1

    def test_a_database_that_does_not_exist_exits_1(
        self, tmp_path: Path, store: ArtifactStore
    ) -> None:
        import io
        from contextlib import redirect_stderr

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(
                [],
                env={"DATABASE_URL": f"sqlite:///{tmp_path / 'absent.db'}"},
                artifact_store=store,
                emit=lambda _line: None,
            )

        assert code == EXIT_REFUSED
        assert BACKFILL_CODE in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()

    def test_a_database_without_the_campaign_table_exits_1_naming_the_chain(
        self, tmp_path: Path, store: ArtifactStore
    ) -> None:
        import io
        from contextlib import redirect_stderr

        url = f"sqlite:///{tmp_path / 'bare.db'}"
        with closing(sqlite3.connect(_path_of(url))):
            pass  # an empty database file, no tables at all

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(
                [], env={"DATABASE_URL": url}, artifact_store=store, emit=lambda _l: None
            )

        assert code == EXIT_REFUSED
        message = stderr.getvalue()
        assert "0111_campaign_table" in message
        assert "Traceback" not in message

    def test_the_module_runs_as_a_script_door(self, grid_database: str, store) -> None:
        # ``python -m orchestrator.backfill_campaign_grid`` is the spec's own
        # spelling, so the module-level door has to exist and answer 0.
        campaign = _insert_campaign(grid_database)
        _persist_grid(store, campaign, _grid(92, 14))
        lines: list[str] = []

        code = main([], env={"DATABASE_URL": grid_database}, artifact_store=store, emit=lines.append)

        assert code == EXIT_OK
        assert json.loads(lines[0])["horizon"] == 10


# -- The driver's half of the feature ---------------------------------------------


class TestTheDriverBuildsTheGrid:
    """``orchestrator.campaign.evaluation_grid`` — the context's five values.

    The spec's second step: *"the driver (orchestrator/campaign.py) passes
    them from its EvaluationContext"*.  Driven directly here rather than
    through a whole campaign, so the mapping is pinned on its own.
    """

    def test_the_five_values_come_off_the_context(self, tmp_path: Path, monkeypatch) -> None:
        import datetime as dt

        from orchestrator.campaign import evaluation_grid

        config = tmp_path / "evaluation-config.json"
        config.write_bytes(b"{}")
        digest = hashlib.sha256(b"{}").hexdigest()
        monkeypatch.setenv("NULLIUS_EVALUATION_CONFIG", str(config))

        class _Ctx:
            horizon = 5
            evaluation_dates = (
                dt.date(2026, 3, 1),
                dt.date(2026, 1, 2),  # deliberately out of order
                dt.date(2026, 9, 30),
            )
            oos_dates = (dt.date(2026, 10, 5), dt.date(2026, 10, 1))

        grid = evaluation_grid(_Ctx())
        assert grid == {
            "evaluation_config_sha256": digest,
            "horizon": 5,
            "grid_first_date": "2026-01-02",
            "grid_last_date": "2026-09-30",
            "oos_first_date": "2026-10-01",
        }

    def test_a_context_with_no_oos_grid_names_none(self, monkeypatch) -> None:
        import datetime as dt

        from orchestrator.campaign import evaluation_grid

        monkeypatch.delenv("NULLIUS_EVALUATION_CONFIG", raising=False)

        class _Ctx:
            horizon = 10
            evaluation_dates = (dt.date(2026, 1, 2),)
            oos_dates = ()

        grid = evaluation_grid(_Ctx())
        assert grid["oos_first_date"] is None
        assert grid["evaluation_config_sha256"] is None
        assert grid["grid_first_date"] == grid["grid_last_date"] == "2026-01-02"

    def test_a_context_that_carries_none_of_it_writes_nothing_rather_than_raising(
        self, monkeypatch
    ) -> None:
        # The loop passes this mapping straight to ``create_campaign``, and a
        # narrow context (a test double, an older deployment) must produce
        # five NULL columns rather than refusing a whole campaign.
        from orchestrator.campaign import evaluation_grid

        monkeypatch.delenv("NULLIUS_EVALUATION_CONFIG", raising=False)

        class _Narrow:
            pass

        assert evaluation_grid(_Narrow()) == {
            "evaluation_config_sha256": None,
            "horizon": None,
            "grid_first_date": None,
            "grid_last_date": None,
            "oos_first_date": None,
        }

    def test_iso_text_dates_are_accepted_as_well_as_date_objects(self, monkeypatch) -> None:
        # A hand-built context may carry the document's own strings.
        from orchestrator.campaign import evaluation_grid

        monkeypatch.delenv("NULLIUS_EVALUATION_CONFIG", raising=False)

        class _Ctx:
            horizon = 5
            evaluation_dates = ("2026-09-30", "2026-01-02")
            oos_dates = ("2026-10-01",)

        grid = evaluation_grid(_Ctx())
        assert grid["grid_first_date"] == "2026-01-02"
        assert grid["grid_last_date"] == "2026-09-30"
        assert grid["oos_first_date"] == "2026-10-01"

    def test_the_driver_s_mapping_is_what_create_campaign_accepts(
        self, grid_database: str, monkeypatch
    ) -> None:
        # The two halves of the feature compose: the mapping
        # ``evaluation_grid`` builds is exactly the keyword set
        # ``run_campaign`` forwards (``**(grid or {})``) and
        # ``discovery.create_campaign`` accepts.  A drift between the two —
        # a column renamed on one side — would show up here rather than only
        # in a live campaign.
        import discovery
        from orchestrator.campaign import evaluation_grid

        monkeypatch.delenv("NULLIUS_EVALUATION_CONFIG", raising=False)

        class _Ctx:
            horizon = 10
            evaluation_dates = (dt.date(2026, 1, 2), dt.date(2026, 9, 30))
            oos_dates = ()

        grid = evaluation_grid(_Ctx())
        record = discovery.create_campaign(
            "Type-R", 12, database_url=grid_database, **grid
        )
        assert record.horizon == 10
        assert record.grid_first_date == "2026-01-02"
        assert record.grid_last_date == "2026-09-30"
        assert record.oos_first_date is None
        assert _read_row(grid_database, record.campaign_id)[:3] == (
            10,
            "2026-01-02",
            "2026-09-30",
        )
