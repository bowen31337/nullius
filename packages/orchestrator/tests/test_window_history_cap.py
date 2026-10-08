"""bug_spec_evaluation_throughput.xml, bug 1 — a window's depth is bounded.

``orchestrator._evaluate._materialize_from_context`` used to read every bars
partition at or before the decision date, for every PIT-universe symbol —
on the 2019-2026 archive, a 2026 date serialized about 150k rows into the
sandbox, and the cost grew linearly with the snapshot's own history rather
than with what a signal can use. The fix is an optional configuration key,
``max_history_days`` (:data:`orchestrator._context.MAX_HISTORY_DAYS_KEY`,
default :data:`orchestrator._context.DEFAULT_MAX_HISTORY_DAYS`): the
materializer now reads only partitions dated in
``(decision_date - max_history_days, decision_date]``, applied *after* the
point-in-time universe rule (feature 72), never in place of it, and
identically for a real node and a planted null alike (neither materializer
nor the truncation it now carries reads any null status).

One test per claim the fix makes:

* **a late date carries only the last N days** — once a decision date has
  more than ``max_history_days`` of history behind it, the materialized
  window's bars are exactly the trailing ``N`` calendar days.
* **an early date carries everything available** — a decision date whose
  own history is shorter than ``N`` is not truncated further; it still
  carries every bar it has.
* **the default applies when the key is absent** — a configuration document
  with no ``max_history_days`` key loads a context whose
  ``max_history_days`` is :data:`orchestrator._context.DEFAULT_MAX_HISTORY_DAYS`.
* **a non-positive value is refused at config load** — zero or negative
  raises :class:`orchestrator._context.EvaluationConfigError`, naming the key.
* **the declaration names the depth** — :func:`signal_agent.signal_contract`'s
  ``declaration(max_history_days=N)`` states ``N`` in the bars accessor's own
  ``returns_notes``, and leaves that sentence out when the caller configures
  no depth (every existing call site, unaffected).

No test opens a network connection or writes outside a pytest temporary
directory, and no test carries state across another, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from contract.bars import bars_frame_name
from evaluator import resolve_window
from orchestrator._context import (
    DEFAULT_MAX_HISTORY_DAYS,
    EvaluationConfigError,
    load_evaluation_context,
)
from orchestrator._evaluate import _materialize_from_context
from signal_agent import signal_contract
from snapshot import SnapshotService

#: One symbol, thirty consecutive daily bars — long enough that a small
#: ``max_history_days`` genuinely truncates a late decision date while
#: leaving an early one untouched.
SYMBOL = "SYM00"
FIRST_DAY = dt.date(2026, 1, 1)
ALL_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(30))

#: Small on purpose: the claim under test is the boundary arithmetic, not
#: the shipped default (covered separately, by its own absence).
MAX_HISTORY_DAYS = 5

#: A pinned, distinct evaluator image — this suite never resolves the
#: evaluator's own identity beyond "does it parse".
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "90" * 32


def _stage_and_seal(
    lake_root: Path, symbol: str, days: Sequence[dt.date]
) -> tuple[SnapshotService, Any]:
    """Stage one symbol's daily bars and seal them — the shared recipe every
    orchestrator context test in this package restates locally rather than
    imports, so this file stays a self-contained regression test.
    """
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, day in enumerate(days):
        partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
        partition.mkdir(parents=True)
        pq.write_table(
            pa.table(
                {
                    "symbol": [symbol],
                    "open_time": [
                        dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                    ],
                    "close": [f"{100.0 + index:.2f}"],
                    "volume": ["1.0"],
                }
            ),
            partition / "part-0.parquet",
        )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service, sealed


def _distinct_bar_dates(window: Any) -> set[dt.date]:
    """The calendar dates a materialized window's own bars frame carries."""
    frame = window.frames[bars_frame_name("1d")]
    values = frame.column("open_time").to_pylist()
    return {value.date() if isinstance(value, dt.datetime) else value for value in values}


# -- The truncation itself: late carries N, early carries everything -----------


@pytest.fixture(scope="module")
def mount(tmp_path_factory: pytest.TempPathFactory) -> Any:
    workdir = tmp_path_factory.mktemp("window-history-cap-world")
    service, sealed = _stage_and_seal(workdir / "lake", SYMBOL, ALL_DAYS)
    return service.mount(sealed.name)


def _materialized_window(mount: Any, decision_day: dt.date) -> Any:
    decision_time = dt.datetime.combine(decision_day, dt.time(23, 59, tzinfo=dt.UTC))
    resolution = resolve_window(mount, decision_time)
    materialize = _materialize_from_context(
        SimpleNamespace(snapshot=mount, max_history_days=MAX_HISTORY_DAYS)
    )
    return materialize(resolution, decision_time)


def test_a_late_date_carries_only_the_last_n_trailing_days(mount: Any) -> None:
    # Twenty-five days of history stand behind this date — far more than
    # MAX_HISTORY_DAYS (5) — so the window must carry exactly the trailing
    # five calendar days, never the whole twenty-six-day history at or
    # before it.
    decision_day = ALL_DAYS[25]
    window = _materialized_window(mount, decision_day)
    dates = _distinct_bar_dates(window)
    expected = set(ALL_DAYS[25 - MAX_HISTORY_DAYS + 1 : 26])
    assert len(expected) == MAX_HISTORY_DAYS, "fixture sanity"
    assert dates == expected


def test_an_early_date_carries_everything_available(mount: Any) -> None:
    # Only three days of history (indices 0, 1, 2) stand behind this date —
    # fewer than MAX_HISTORY_DAYS (5) — so the cap must not remove anything
    # that is genuinely there: every available bar is still carried.
    decision_day = ALL_DAYS[2]
    window = _materialized_window(mount, decision_day)
    dates = _distinct_bar_dates(window)
    expected = set(ALL_DAYS[:3])
    assert len(expected) < MAX_HISTORY_DAYS, "fixture sanity"
    assert dates == expected


# -- Config loading: the default, and the refusal ------------------------------


def _document(snapshot_path: Path, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "snapshot_mount": str(snapshot_path),
        "evaluation_dates": [ALL_DAYS[1].isoformat()],
        "horizon": 1,
        "seed": 7,
        "epoch_id": "epoch-window-history-cap",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    document.update(overrides)
    return document


def _environment(tmp_path: Path, document: Mapping[str, Any]) -> dict[str, str]:
    config_path = tmp_path / f"evaluation-{abs(id(document))}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    bwrap_dir = tmp_path / "bwrap-path"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    if not bwrap.exists():
        bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
        bwrap.chmod(0o755)
    return {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'window-history-cap.db'}",
        "NULLIUS_EVALUATOR_IMAGE": IMAGE,
        "PATH": str(bwrap_dir),
    }


def test_the_default_applies_when_the_key_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _service, sealed = _stage_and_seal(tmp_path / "lake", SYMBOL, ALL_DAYS[:2])
    document = _document(sealed.path, tmp_path)
    assert "max_history_days" not in document, "fixture sanity"

    context = load_evaluation_context(_environment(tmp_path, document))

    assert context is not None
    assert context.max_history_days == DEFAULT_MAX_HISTORY_DAYS


@pytest.mark.parametrize("value", [0, -1, -400])
def test_a_non_positive_value_is_refused_at_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: int
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _service, sealed = _stage_and_seal(tmp_path / "lake", SYMBOL, ALL_DAYS[:2])
    document = _document(sealed.path, tmp_path, max_history_days=value)

    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(_environment(tmp_path, document))

    message = str(record.value)
    assert message.startswith("evaluation_config:")
    assert "max_history_days" in message


# -- The authoring declaration: the depth is named, or absent ------------------


def test_the_declaration_names_the_configured_depth() -> None:
    n = 123
    declared = signal_contract().declaration(max_history_days=n)
    bars_notes = declared["accessors_detail"]["bars"]["returns_notes"]
    assert str(n) in bars_notes
    assert "trailing daily candles" in bars_notes


def test_the_depth_note_is_absent_when_no_depth_is_configured() -> None:
    # Every existing call site hands in no max_history_days (the absence an
    # unconfigured evaluation context is), and must see no note at all —
    # not a note naming "None".
    declared = signal_contract().declaration()
    bars_notes = declared["accessors_detail"]["bars"]["returns_notes"]
    assert "trailing daily candles" not in bars_notes
