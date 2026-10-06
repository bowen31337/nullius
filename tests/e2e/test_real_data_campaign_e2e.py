"""The shipped path, offline, end to end: market data to a scored campaign.

additions_spec_real_campaign_path.xml, "Operator Wiring and Proof" category,
feature 8: *System passes an end-to-end test that runs the shipped path
offline and shows that a campaign scores real forward returns.* Four real
commands, in the operator's own order (README.md's "Running" section):

1. ``python -m nullius_ingest.bars_backfill`` over a recorded Binance fetch,
   into a tmp lake.
2. ``python -m snapshot.seal``, sealing that lake's staging area.
3. ``python -m app.migrate``, applying the whole migration chain.
4. ``python -m orchestrator.campaign``'s own ``main()``, composed through a
   real ``app.module_loader.create_app()`` — not a hand-built stand-in — so
   the live-evaluator and the Type-R selection components are exactly what a
   real deployment's environment variables would build.

**No network, no credential, anywhere.** Step 1's fetch is a recorded,
in-memory callable over hand-built Binance kline arrays (the same discipline
``packages/ingest/tests/test_lake_backfill.py`` uses). Step 4's signal author
is composed for real and then has its one moving part — the provider a pinned
model resolves to — replaced with a genuine ``providers.RecordedProvider``
fixture (feature 193's recorded-fixture backend): a scripted exchange is
captured once against a fake provider, filed through
``providers.FixtureStore``, and replayed with no transport at all. The
live-evaluator and the Type-R selection are left as the real ``create_app()``
composed them from the environment this test sets.

**Why ``discovery.create_campaign`` is patched to a fixed id.**
``signal_agent.build_authoring_prompt`` reads ``campaign_id``, ``theme_root``
and ``depth`` off the workspace it is building a prompt for (see
``tests/e2e/test_live_campaign_end_to_end.py``'s own module docstring), so
the exact prompt text — and therefore the fixture's ``prompt_hash`` — depends
on the campaign id a real run mints. Capturing a root's exchange and
replaying it under a *different* campaign id would be two different prompts,
and the recorded fixture would answer neither. This module's capture calls
and the real run both use the same fixed id for exactly that reason; a root's
own id never enters the prompt at all, so no id-patching is needed for that.

**Why five workspaces, not two.** ``nulloracle.null_fraction(W)`` is
``clip(max(2/W, 0.15), 0.15, 0.35)``, and the planted count is
``round(φ·W)`` — a deterministic count, not a per-root coin flip. Close-out's
KS guard refuses a sample of fewer than two scores on either side (the null
side, the real side, or both), so a two-root campaign (one drawn null, one
left real) cannot be closed out at all. At ``W = 5``, ``φ = 0.35`` and
``round(1.75) = 2``: exactly two of the five roots are drawn null and the
other three stay real, every time, regardless of seed — the smallest
campaign both sides of the guard can read. The campaign driver evaluates
every planted root before the round loop ever runs, so ``--rounds 0`` is
enough: no signal author call is needed below
depth 0.

The close-out line's sensitivity and specificity, and every ``node_id``-bearing
stdout line, are read back off the real JSON this command prints — nothing
here recomputes them.

**Why the closes carry a per-symbol drift rather than a plain autocorrelated
random walk.** ``evaluator._metrics.compute_node_metrics`` measures
``ic_mean`` as the mean of a *per-date* Spearman rank correlation, and
refuses outright — :class:`~evaluator.EvaluatorMetricsError`, never a
defaulted ``0.0`` — when that per-date series has zero variance: a
`fabricated infinity`` is worse than a refusal, in that module's own words.
A pure random walk's cross-sectional momentum is usually too faint over six
symbols and five dates to clear the discovery bar (``ic_tstat >= 2.0``,
needed so close-out's ``FdrDeployStore`` has at least one committed node to
reweight — a campaign that declared nothing is 0/0, feature 267's own
refusal), while a *noiseless* deterministic drift clears it by clearing
*everything*, every date identically, and trips the zero-variance refusal
instead. :data:`_DRIFTS` fixes each symbol's own constant daily drift, wide
enough apart that the momentum ranking survives most days' noise, and
:data:`_DRIFT_NOISE_STD` adds just enough of that noise to keep the five
per-date coefficients honestly different from one another — calibrated
offline against this module's own momentum code before being pinned here,
not tuned against the live evaluator's output.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import secrets
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import discovery
import providers
import pytest
import signal_agent
from app.migrate import main as migrate_main
from app.module_loader import create_app
from nullius_ingest.bars_backfill import HttpResponse
from nullius_ingest.bars_backfill import main as bars_backfill_main
from orchestrator import campaign as campaign_cli
from snapshot.seal import main as seal_main

UTC = dt.UTC

# -- The world: symbols, days, and the horizon the forward returns measure ----

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT")
FIRST_DAY = dt.date(2026, 9, 1)
LOOKBACK = 3
EVALUATION_SPAN = 5
HORIZON = 1
BAR_DAYS = tuple(
    FIRST_DAY + dt.timedelta(days=offset) for offset in range(LOOKBACK + EVALUATION_SPAN + 1)
)
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + EVALUATION_SPAN]
WORLD_SEED = 20260901

#: Each symbol's own constant daily drift, spaced wide enough that the
#: momentum code's cross-sectional ranking survives most days' noise (see
#: the module docstring's calibration note).
_DRIFT_STEP = 0.012
_DRIFTS = {symbol: -0.03 + _DRIFT_STEP * index for index, symbol in enumerate(SYMBOLS)}
#: The daily noise added on top of each symbol's own drift — large enough
#: that the five evaluation dates' per-date information coefficients are
#: not identical (which the evaluator refuses outright), small enough that
#: the ranking the momentum signal reads still mostly agrees with it.
_DRIFT_NOISE_STD = 0.01

EPOCH_ID = "epoch-2026-10-07-real-data-campaign-e2e"
EVALUATOR_IMAGE = "localhost/nullius-evaluator@sha256:" + "ab" * 32

#: Fixed so the capture pass and the real run build byte-identical authoring
#: prompts for the same root (see the module docstring).
FIXED_CAMPAIGN_ID = "a5f00000-0000-4000-8000-000000000e2e"

#: Five root workspaces: the smallest ``W`` at which ``nulloracle.
#: null_root_count(null_fraction(W), workspace_count=W)`` draws *at least
#: two* null roots and leaves *at least two* real ones (``round(0.35*5) =
#: 2``, ``5 - 2 = 3``) — the close-out KS guard refuses a sample of fewer
#: than two points per side, so two of each is the floor, not a convenience.
WORKSPACES = 5

_LEGAL_THEMES = discovery.legal_themes_from_env()
#: One legal theme per planted root, in the same canonical order and the
#: same wraparound ``orchestrator._campaign._themes_for`` applies — read here
#: once so the capture pass below authors exactly the themes the real run
#: will ask for, and the real run only reaches the themes this tuple spans.
ROOT_THEMES = tuple(
    _LEGAL_THEMES.themes[i % len(_LEGAL_THEMES.themes)] for i in range(WORKSPACES)
)


# -- Step 1: recorded Binance klines, no network ------------------------------


def _binance_row(day: dt.date, close: str, *, trades: int = 25) -> list:
    """One Binance kline array, positional, at Binance's own field order."""
    open_ms = int(dt.datetime.combine(day, dt.time(0), tzinfo=UTC).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    return [
        open_ms,
        "100.00000000",
        "110.00000000",
        "90.00000000",
        close,
        "1000.50000000",
        close_ms,
        "87654.321",
        trades,
        "400.00000000",
        "40000.00",
        "0",
    ]


def _recorded_fetch(klines_by_symbol: Mapping[str, list]) -> Callable[[str, Mapping[str, str]], HttpResponse]:
    def fetch(path: str, params: Mapping[str, str]) -> HttpResponse:
        assert path == "/klines", f"unexpected path {path!r}: this test never asks --top"
        rows = klines_by_symbol.get(params["symbol"], [])
        return HttpResponse(200, {}, json.dumps(rows).encode("utf-8"))

    return fetch


def _no_sleep(_seconds: float) -> None:
    return None


def _generate_closes() -> dict[str, dict[dt.date, str]]:
    """A positive random walk per symbol, each around its own constant drift."""
    generator = random.Random(WORLD_SEED)
    closes: dict[str, dict[dt.date, str]] = {}
    for symbol in SYMBOLS:
        price = 100.0
        path: dict[dt.date, str] = {}
        for day in BAR_DAYS:
            shock = generator.gauss(0.0, _DRIFT_NOISE_STD)
            return_ = _DRIFTS[symbol] + shock
            price = max(1.0, price * (1.0 + return_))
            path[day] = f"{price:.2f}"
        closes[symbol] = path
    return closes


def _backfill_lake(lake: Path, events: list[str]) -> None:
    closes = _generate_closes()
    klines_by_symbol = {
        symbol: [_binance_row(day, closes[symbol][day]) for day in BAR_DAYS]
        for symbol in SYMBOLS
    }
    exit_code = bars_backfill_main(
        [
            "--lake", str(lake),
            "--first", BAR_DAYS[0].isoformat(),
            "--last", BAR_DAYS[-1].isoformat(),
            "--symbols", ",".join(SYMBOLS),
        ],
        emit=events.append,
        fetch=_recorded_fetch(klines_by_symbol),
        sleep=_no_sleep,
    )
    assert exit_code == 0, events


# -- Step 4: the recorded-fixture signal author -------------------------------

ROOT_SIGNAL_CODE = f"""\
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    momentum = {{}}
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")
        if len(series) < {LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[0]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


def _answer(theme_root: str) -> str:
    return (
        f"Momentum off the sealed daily bars, theme {theme_root!r}.\n\n"
        f"```python\n{ROOT_SIGNAL_CODE}```\n\n"
        "Mechanism: Short-horizon close-to-close drift over the lookback "
        "window persists for a few sessions before mean-reverting, so the "
        "cross-sectional momentum score is the edge.\n"
    )


ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
DEPTH_PIN = providers.ModelPin("anthropic", "claude-haiku-4-5", "20260401")
POLICY_PIN = providers.ModelPin("self-hosted", "llama-3", "local")

AUTHORING_CONFIG = providers.AuthoringConfig(
    root_tier=(ROOT_PIN,),
    depth=DEPTH_PIN,
    policy=POLICY_PIN,
    temperature=0.2,
    max_tokens=1024,
    max_input_tokens=200_000,
    max_output_tokens=200_000,
)


class _ScriptedProvider(providers.Provider):
    """Answers every root-authoring call with the momentum signal, for its
    own ``theme_root`` — a real :class:`providers.Provider` subclass with no
    transport anywhere in it, used only to capture the root exchanges this
    test replays.

    Every planted root is authored before any proposal is persisted
    (``run_campaign`` plants all its roots, then evaluates them — see the
    module docstring), so every call this provider ever answers is depth 0
    with an empty history; both are asserted rather than assumed.
    """

    def _complete(self, request: providers.Request) -> providers.Completion:
        system = request.messages[0].content
        assert system.startswith("## Task\n"), system
        task_text, _, _ = system[len("## Task\n") :].partition(
            "\n\n## Anti-convergence clause\n"
        )
        task = json.loads(task_text)
        assert task["depth"] == 0, task
        assert "No prior proposals exist yet" in request.messages[1].content
        usage = providers.Usage(input_tokens=500, output_tokens=120, cache_read_tokens=0)
        return providers.Completion(
            content=_answer(task["theme_root"]), model=request.model, usage=usage
        )


def _build_author(
    resolve: Callable[[providers.ModelPin], providers.Provider], history_store: Any
) -> signal_agent.LLMSignalAuthor:
    session = providers.AuthoringSession(AUTHORING_CONFIG, resolve)
    return signal_agent.LLMSignalAuthor(
        session,
        history_store=history_store,
        contract=signal_agent.signal_contract(),
        anti_convergence=signal_agent.anti_convergence_gate(),
        guidance=signal_agent.prompt_guidance_gate(),
        config=AUTHORING_CONFIG,
    )


def _capture_fixture_responses(database_url: str, tmp_path: Path) -> tuple[Any, ...]:
    """Capture every root's exchange against a scripted provider, once.

    ``author_root`` persists nothing (persistence is ``run_campaign``'s own,
    after evaluation), so calling it here directly, outside any campaign,
    leaves no row behind for the real run to trip over.
    """
    history_store = signal_agent.ProposalHistoryStore(signal_agent.ProposalStore(database_url))
    scripted = _ScriptedProvider()
    recorder = providers.RecordingProvider(scripted)
    author = _build_author(lambda pin: recorder, history_store)

    for index, theme_root in enumerate(ROOT_THEMES):
        root_id = f"11111111-0000-4000-8000-{index:012d}"
        author.author_root(FIXED_CAMPAIGN_ID, theme_root, root_id=root_id)

    store = providers.FixtureStore(tmp_path / "fixtures")
    store.record_all(recorder.exchanges())
    return store.responses()


def _patch_fixed_campaign_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ``discovery.create_campaign`` call in this process plant
    under :data:`FIXED_CAMPAIGN_ID` — the real function, called with the id
    explicit rather than left to the table's own mint, so the real run's
    authoring prompts match what :func:`_capture_fixture_responses` captured.
    """
    original = discovery.create_campaign

    def fixed(
        campaign_type: Any,
        workspace_count: Any,
        *,
        campaign_id: Any = None,
        database_url: str | None = None,
        env: Any = None,
    ) -> Any:
        return original(
            campaign_type, workspace_count,
            campaign_id=FIXED_CAMPAIGN_ID, database_url=database_url, env=env,
        )

    monkeypatch.setattr(discovery, "create_campaign", fixed)


# -- Reading the campaign's own node rows -------------------------------------


def _root_ic_means(database_url: str, campaign_id: str) -> list[float | None]:
    path = database_url.removeprefix("sqlite:///")
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT ic_mean FROM node WHERE campaign_id = ? AND depth = 0",
            (campaign_id,),
        ).fetchall()
    finally:
        connection.close()
    return [row[0] for row in rows]


# -- stdout discipline: no node id ever sits beside a null-status key --------


def _keys_mentioning_null(value: Any) -> list[str]:
    found: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, inner in node.items():
                if "null" in key.lower():
                    found.append(key)
                _walk(inner)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(value)
    return found


# -- The test ------------------------------------------------------------------


def test_real_data_campaign_scores_real_forward_returns(
    lake_root: Path,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("bwrap") is None:
        pytest.skip("bwrap is not on PATH; the unisolated sandbox has no fallback")

    events: list[str] = []

    # 1. bars_backfill with recorded Binance JSON into a tmp lake.
    _backfill_lake(lake_root, events)

    # 2. snapshot.seal.
    seal_exit = seal_main(["--lake", str(lake_root)], emit=events.append)
    assert seal_exit == 0, events
    seal_payload = json.loads(events[-1])
    snapshot_mount = seal_payload["path"]

    # 3. app.migrate.
    migrate_exit = migrate_main(emit=events.append)
    assert migrate_exit == 0, events

    # 4. One Type-R campaign through python -m orchestrator.campaign's main().
    evaluation_document = {
        "snapshot_mount": snapshot_mount,
        "evaluation_dates": [day.isoformat() for day in EVALUATION_DATES],
        "horizon": HORIZON,
        "seed": WORLD_SEED,
        "epoch_id": EPOCH_ID,
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    evaluation_config_path = tmp_path / "evaluation-config.json"
    evaluation_config_path.write_text(json.dumps(evaluation_document), encoding="utf-8")

    sidecar_key_hex = secrets.token_hex(32)
    monkeypatch.setenv("NULLIUS_EVALUATION_CONFIG", str(evaluation_config_path))
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", EVALUATOR_IMAGE)
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(tmp_path / "null" / "sidecar.enc"))
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", f"hex:{sidecar_key_hex}")

    _patch_fixed_campaign_id(monkeypatch)

    responses = _capture_fixture_responses(test_database_url, tmp_path)
    fixture_author = _build_author(
        lambda pin: providers.RecordedProvider(responses),
        signal_agent.ProposalHistoryStore(signal_agent.ProposalStore(test_database_url)),
    )

    app = create_app()
    assert app.get("live-evaluator") is not None, (
        "the real create_app() composed no live-evaluator; check "
        "NULLIUS_EVALUATION_CONFIG, DATABASE_URL and NULLIUS_EVALUATOR_IMAGE"
    )
    assert app.get("nulloracle-type-r-selection") is not None, (
        "the real create_app() composed no Type-R selection; check "
        "DATABASE_URL, NULL_SIDECAR_PATH and NULL_SIDECAR_KEY_REF"
    )
    app.components[signal_agent.SIGNAL_AUTHOR_COMPONENT_NAME] = fixture_author

    exit_code = campaign_cli.main(
        ["--type", "Type-R", "--workspaces", str(WORKSPACES), "--rounds", "0"],
        app=app,
        emit=events.append,
    )
    assert exit_code == 0, events

    lines = [json.loads(line) for line in events if line.strip().startswith("{")]

    root_planted = [line for line in lines if line.get("event") == "root_planted"]
    assert len(root_planted) == WORKSPACES, lines

    ic_means = _root_ic_means(test_database_url, FIXED_CAMPAIGN_ID)
    assert len(ic_means) == WORKSPACES, ic_means
    assert any(value is not None for value in ic_means), (
        "no root carries a non-null ic_mean computed from the snapshot's "
        f"forward returns: {ic_means}"
    )

    closeout_lines = [line for line in lines if "sensitivity" in line and "specificity" in line]
    assert len(closeout_lines) == 1, lines
    closeout = closeout_lines[0]
    assert isinstance(closeout["sensitivity"], (int, float))
    assert isinstance(closeout["specificity"], (int, float))

    for line in lines:
        if "node_id" in line:
            offenders = _keys_mentioning_null(line)
            assert not offenders, f"{line} pairs a node id with {offenders}"
