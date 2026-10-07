"""bug_spec_authoring_contract.xml, bug 1 — the declaration made usable.

A campaign's authored roots called ``getattr(ctx, "bars")`` and guessed at
it, because :meth:`signal_agent.SignalContract.declaration` named the
accessor surface without a signature, a frame schema, a known stream to read
from, or the import ceiling the sandbox actually enforces — and every root
that guessed returned a constant vector, which the evaluator refused
(``EvaluatorNormalizeError: cannot normalize: every raw score is
identical``). This file asserts the fix is *usable*, not merely present:
the bars signature and its frame columns are the real, introspected ones;
``available_streams`` reflects a real sealed snapshot (bars at 1d, nothing
else) rather than a guess; ``allowed_imports`` is the sandbox child's own
ceiling; and the shipped example signal actually runs against a window
materialized from that same snapshot and produces a score
:func:`evaluator.normalize_scores` accepts.

No network; the snapshot fixture is a few tiny Parquet files under
``tmp_path`` and ``DATABASE_URL`` is explicitly unset, so sealing never
reaches for a relational store (``snapshot.SnapshotService``'s own stance:
a lake with none records nothing beyond its own ``MANIFEST.json``). No
module-level state, so the suite is order- and worker-independent under
pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import json

import polars as pl
import pytest
from signal_agent import SignalContract

#: Two symbols with deliberately divergent five-day trajectories — AAAUSDT
#: rising, BBBUSDT falling — so a momentum computed over them is non-constant
#: by construction, not by chance, and the two scores land in a checkable
#: order (AAAUSDT's score must exceed BBBUSDT's) if the example signal is
#: really reading each row's own symbol rather than mixing them up.
SYMBOLS = ("AAAUSDT", "BBBUSDT")
_DATES = ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05")
_CLOSES = {
    "AAAUSDT": ("100.00", "101.00", "102.00", "103.00", "110.00"),
    "BBBUSDT": ("50.00", "49.00", "48.00", "47.00", "40.00"),
}

#: declaration()'s nine keys before this bug's fix — used only to isolate
#: "the text this fix added" for the character-budget check below.
_PRE_EXISTING_KEYS = frozenset(
    {
        "entrypoint",
        "window_arg",
        "seed_arg",
        "signature",
        "returns",
        "market_window",
        "contract_version",
        "accessors",
        "purity",
    }
)


def _seal_tiny_bars_snapshot(lake_root, monkeypatch: pytest.MonkeyPatch):
    """Seal a real snapshot: one 1d-bars partition per symbol per day.

    The venue-string convention the sealed snapshot actually carries (§4.1):
    ``close``/``volume`` as strings, ``open_time`` a UTC timestamp, plus the
    row-level ``interval`` column every real kline row carries
    (:mod:`nullius_ingest.klines`) — the column :func:`signal_agent._authoring
    ._parquet_interval` reads to answer "which frequency".
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    snapshot = pytest.importorskip("snapshot")

    staging = lake_root / "staging"
    for symbol in SYMBOLS:
        for date, close in zip(_DATES, _CLOSES[symbol], strict=True):
            partition = staging / "bars" / f"symbol={symbol}" / f"date={date}"
            partition.mkdir(parents=True)
            table = pa.table(
                {
                    "symbol": [symbol],
                    "open_time": pa.array(
                        [dt.datetime.fromisoformat(f"{date}T00:00:00+00:00")],
                        type=pa.timestamp("us", tz="UTC"),
                    ),
                    "close": [close],
                    "volume": ["1.0"],
                    "interval": ["1d"],
                }
            )
            pq.write_table(table, partition / "part-0.parquet")

    service = snapshot.SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 1, 6, tzinfo=dt.UTC))
    return service.mount(sealed.path.name)


@pytest.fixture
def sealed_mount(tmp_path, monkeypatch: pytest.MonkeyPatch):
    return _seal_tiny_bars_snapshot(tmp_path / "lake", monkeypatch)


# -- accessors_detail: the bars signature and its frame columns ---------------


def test_bars_signature_and_frame_columns_appear(law: SignalContract) -> None:
    contract = pytest.importorskip("contract")
    bars_detail = law.declaration()["accessors_detail"]["bars"]
    assert bars_detail["signature"] == "bars(freq, lookback=None) -> polars.DataFrame"
    assert bars_detail["freq_values"] == contract.BARS_FREQUENCIES
    assert bars_detail["returns_columns"] == contract.BARS_REQUIRED_COLUMNS
    assert "symbol" in bars_detail["returns_columns"]
    assert "open_time" in bars_detail["returns_columns"]


# -- available_streams: absent by default, derived from a real snapshot ------


def test_available_streams_is_absent_with_no_context_configured(
    law: SignalContract,
) -> None:
    assert "available_streams" not in law.declaration()


def test_available_streams_reflects_a_tmp_sealed_snapshot_of_1d_bars(
    law: SignalContract, sealed_mount
) -> None:
    declaration = law.declaration(snapshot=sealed_mount)
    assert declaration["available_streams"] == {"bars": ("1d",)}


# -- allowed_imports: the sandbox child's own ceiling, not the stale JSON -----


def test_allowed_imports_equals_the_sandbox_childs_allowlist(
    law: SignalContract,
) -> None:
    sandbox_child = pytest.importorskip("orchestrator._sandbox_child")
    allowed = law.declaration()["allowed_imports"]
    assert set(allowed) == set(sandbox_child.AGENT_IMPORTS_ALLOWLIST)
    assert tuple(allowed) == tuple(sorted(allowed))  # stable, deterministic order


# -- example_signal: runs for real, against a window materialized from the ---
# -- same sealed snapshot, and its score is one normalize_scores accepts -----


def test_example_signal_runs_against_the_sealed_snapshot_and_normalizes(
    law: SignalContract, sealed_mount
) -> None:
    pq = pytest.importorskip("pyarrow.parquet")
    pa = pytest.importorskip("pyarrow")
    contract = pytest.importorskip("contract")
    evaluator = pytest.importorskip("evaluator")

    # Materialize a MarketWindow the way the production evaluator does
    # (orchestrator._evaluate._materialize_from_context): read every surviving
    # bars partition's parquet bytes back off the mount and concatenate them
    # into one frame, under the window's own bars:1d frame name.
    tables = []
    for symbol in SYMBOLS:
        for date in sealed_mount.dates("bars", symbol):
            for path in sealed_mount.select("bars", symbol, date):
                tables.append(pq.read_table(str(path)))
    frame = pa.concat_tables(tables)
    window = contract.MarketWindow(
        "2026-01-06T00:00:00Z",
        universe=SYMBOLS,
        frames={contract.bars_frame_name("1d"): frame},
    )

    namespace: dict[str, object] = {}
    exec(law.declaration()["example_signal"], namespace)  # noqa: S102
    result = namespace["signal"](window, 0)

    assert isinstance(result, pl.Series)
    assert result.dtype == pl.Float64
    assert len(result) == len(SYMBOLS)
    assert result.is_finite().all()
    # Positionally aligned: AAAUSDT (rising 100 -> 110) must score above
    # BBBUSDT (falling 50 -> 40), not merely "some two different numbers".
    assert result[0] > result[1]

    # The evaluator's own refusal is exactly what the symptom's momentum root
    # hit ("cannot normalize: every raw score is identical"); accepting here
    # is the proof the vector is genuinely non-constant, not merely asserted so.
    normalized = evaluator.normalize_scores(result)
    assert len(normalized) == len(result)


# -- the prompt budget: additive text stays small enough not to crowd history -


def test_added_declaration_text_stays_under_the_prompt_budget(
    law: SignalContract,
) -> None:
    declaration = law.declaration()
    added = {k: v for k, v in declaration.items() if k not in _PRE_EXISTING_KEYS}
    rendered = json.dumps(added, sort_keys=True, default=str)
    assert len(rendered) < 4000, len(rendered)
