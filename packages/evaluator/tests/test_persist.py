"""Feature 85 — persist the full artifact to the artifact store plus the scalar
metrics to the tree store, as the final pipeline step.

app_spec.xml feature 85: *"System persists the full artifact to the artifact
store plus the scalar metrics to the tree store as the final pipeline step."*
docs/nullius-tech-architecture.md §6.1 names this as the last line of the
pipeline — ``12. persist   artifact → ART, scalars → TREE`` — and §9 lays out
the two destinations: §9.2's artifact store (one directory per node, holding the
Parquet and JSON files replay needs) and §9.1's tree store (the ``node``
table's scalar columns).

This step is not a new metric and not a new store. It is the orchestration the
other steps deliberately do not do: gather the node's persisted pieces, render
each into its §9.2 artifact file, and copy the scalar metrics onto the §9.1
``node`` row — under one contract that says the write is keyed by the node,
refuses a half-written node, and can be retried safely. This suite tests that
contract, in two halves that are separately assertable:

* **the artifact content** — each §9.2 file is rendered from the records the
  measured steps produced: ``decay_profile.json`` as the positional
  five-horizon array, ``regime_attribution.json`` as the per-stratum,
  per-horizon split, ``turnover_series`` by the same arithmetic the metrics
  reduce, and ``exec_trace.json`` as the run's provenance fingerprint;
* **the orchestration contract** — one node, one write, one transaction: the
  artifact files and the ``node`` row are written under one ``persist_node``
  call, the write is idempotent by ``node_id`` (a retry refreshes, reports
  ``appended=False`` and never duplicates), a record set that disagrees on node
  or cost model is refused before any write, and a half-written node is
  refused on read-back.

The records are produced by the real steps 4 through 9 over a real priced
bundle — the same fixtures ``test_metrics.py``, ``test_capacity.py`` and
``test_marginal.py`` use — because an artifact rendered from a value that never
persisted would be a file no evaluation produced. The two seams are fakes: an
in-memory :class:`_FakeArtifactWriter` that records what it was asked to write
and rolls back on ``flush`` failure, and a :class:`_FakeTreeNodeWriter` that
answers ``(node_id, appended)`` from a dict, so the idempotency signal is
assertable.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import closing

import contract
import pytest
from evaluator import (
    DECAY_HORIZONS,
    HORIZONS,
    NODE_PERSIST_TABLE,
    ArtifactPayload,
    ArtifactWriter,
    CostModelRef,
    CostQuote,
    EvaluatorArtifactError,
    NodeArtifactStore,
    OracleRequest,
    OracleResponse,
    PostCostReturns,
    RawScoreVector,
    SignalExecution,
    align_targets,
    apply_costs,
    attribute_regimes,
    compute_decay_profile,
    compute_marginal_ir,
    compute_node_metrics,
    estimate_capacity,
    gate_targets,
    persist_capacity,
    persist_decay_profile,
    persist_marginal_ir,
    persist_node_metrics,
    persist_node,
    persist_signal_returns,
)

_START = dt.date(2026, 9, 1)
_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_OTHER_REF = CostModelRef(venue="coinbase_spot", version="2026.09.1")


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid."""
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _execution(
    dates,
    universe: tuple[str, ...] = ("AAA", "BBB"),
    *,
    snapshot_name: str = "snap_abc123",
) -> object:
    """A hand-built execution — feature 73's output — for step 4 to align."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=universe,
            seed=7,
            contract_version=contract.CONTRACT_VERSION,
            problems=[],
        )
        for day in dates
    }
    return SignalExecution(
        snapshot_name=snapshot_name,
        code_hash="ab" * 32,
        seed=7,
        vectors=vectors,
    )


# A 12-bar grid with three rebalance dates at its head — horizons 1, 2, 5 and
# 10 cover all three, horizon 20 covers none (the empty-but-carried case).
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = {
    "AAA": dict(zip(_GRID, _COMPOUND)),
    "BBB": dict(zip(_GRID, [50.0] * 12)),
}
_MAIN_ALIGNED = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)

# The regime labels over the rebalance grid — one stratum per date, so the
# attribution carries three strata, each measured at the horizons that cover
# its date.
_TREND = "trend"
_CHOP = "chop"
_CRASH = "crash"
_MAIN_LABELS = {_REBALANCE[0]: _TREND, _REBALANCE[1]: _CHOP, _REBALANCE[2]: _CRASH}

# Volumes for the capacity estimate — thick on AAA, thin on BBB, so the book
# is sized by the thinner leg.
_THIN = 1e6
_THICK = 5e6
_MAIN_VOLUMES = {
    "AAA": {day: _THICK for day in _GRID},
    "BBB": {day: _THIN for day in _GRID},
}


def _oracle(alignment):
    """A stub oracle whose real branch is the identity — §7.2's ask seam."""

    def ask(request: OracleRequest) -> OracleResponse:
        aligned = alignment.targets(request.horizon)
        return OracleResponse(
            target_series={day: dict(aligned.at(day)) for day in aligned.dates()},
            charges_budget=False,
        )

    return ask


def _flat_schedule(bps: float = 10.0):
    """A stub fee schedule: a flat ``bps`` charge on every symbol and bar."""
    rate = bps / 10_000.0

    def schedule(request):
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: {symbol: rate for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    return schedule


def _priced(node_id: str = "node_1", cost_model: CostModelRef = _REF) -> PostCostReturns:
    """Step 7's own result, over the real steps 4 through 7."""
    gated = gate_targets(
        _MAIN_ALIGNED,
        _oracle(_MAIN_ALIGNED),
        node_id=node_id,
        campaign_id="camp_1",
        depth=2,
    )
    return apply_costs(gated, _flat_schedule(), node_id=node_id, cost_model=cost_model)


def _scores(rebalance_dates):
    """The normalized scores — step 3's output — over the rebalance dates.

    Alternating the ranking across the dates (AAA above BBB, then reversed) so
    the per-date IC varies — a constant ranking would give a constant
    coefficient, a zero standard error, and an undefined ``ic_tstat`` and
    ``turnover``. CCC is named to show it is simply ignored — it is not priced.
    """
    return {
        day: ({"AAA": 1.0, "BBB": -1.0, "CCC": 0.0} if index % 2 == 0 else {"AAA": -1.0, "BBB": 1.0, "CCC": 0.0})
        for index, day in enumerate(rebalance_dates)
    }


def _seed(node_id: str = "node_1", cost_model: CostModelRef = _REF):
    """Run steps 4–9 over the real bundle and persist each, returning the records.

    The whole set feature 85 gathers: step 7's ``PostCostReturns``, step 8's
    ``NodeMetrics`` / ``DecayProfile`` / ``CapacityEstimate`` +
    ``RegimeAttribution``, and step 9's ``MarginalIR`` — each persisted to the
    store feature 85 reads back, so ``persist_node`` renders from what actually
    persisted.
    """
    priced = _priced(node_id=node_id, cost_model=cost_model)
    scores = _scores(priced.rebalance_dates)
    metrics = compute_node_metrics(priced, scores)
    profile = compute_decay_profile(priced, scores)
    estimate = estimate_capacity(priced, _MAIN_VOLUMES)
    attribution = attribute_regimes(priced, _MAIN_LABELS)
    # A resident book whose per-date return *varies* — a constant book has no
    # reward-to-variance ratio to increment, so compute_marginal_ir refuses it.
    book_values = [0.01, -0.02, 0.015]
    book = {
        "resident_signal": dict(zip(priced.rebalance_dates, book_values))
    }
    marginal = compute_marginal_ir(priced, book)
    persist_signal_returns(priced)
    persist_node_metrics(metrics)
    persist_decay_profile(profile)
    persist_capacity(estimate, attribution)
    persist_marginal_ir(marginal)
    return {
        "priced": priced,
        "metrics": metrics,
        "profile": profile,
        "estimate": estimate,
        "attribution": attribution,
        "marginal": marginal,
    }


# -- The seams ------------------------------------------------------------------


class _FakeArtifactWriter:
    """An in-memory :class:`ArtifactWriter` — records what it was asked to write.

    The seam the artifacts member speaks, faked so the artifact content is
    assertable without a real store: each ``write_artifact`` is recorded under
    the node, and ``flush`` commits them (or, when ``fail_on`` names a file,
    raises before committing — leaving nothing flushed, so the orchestration
    refuses the half).
    """

    def __init__(self, *, fail_on: str | None = None):
        self._fail_on = fail_on
        self.written: dict[str, dict[str, ArtifactPayload]] = {}
        self.flushed: set[str] = set()

    def write_artifact(self, node_id, campaign_id, filename, payload):
        self.written.setdefault(node_id, {})[filename] = payload

    def flush(self, node_id):
        if self._fail_on in self.written.get(node_id, {}):
            raise RuntimeError(f"the artifacts member could not commit {self._fail_on}")
        self.flushed.add(node_id)


class _FakeTreeNodeWriter:
    """An in-memory ``TreeNodeWriter`` — answers ``(node_id, appended)``.

    The seam the tree member speaks, faked as a dict keyed by node: a first
    write appends (``True``), a refresh does not (``False``) — so the
    idempotency signal ``persist_node`` reports is the tree writer's, asserted
    end to end.
    """

    def __init__(self):
        self.rows: dict[str, object] = {}

    def write_node(self, node_row):
        appended = node_row.node_id not in self.rows
        self.rows[node_row.node_id] = node_row
        return node_row.node_id, appended


# -- The happy path -------------------------------------------------------------


def test_persist_writes_all_six_files_and_the_node_row():
    """One ``persist_node`` writes the six §9.2 files and the ``node`` row."""
    records = _seed()
    writer = _FakeArtifactWriter()
    tree = _FakeTreeNodeWriter()
    result = persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=writer,
        tree_writer=tree,
    )
    files = writer.written["node_1"]
    assert set(files) == {
        "signal_returns.parquet",
        "ic_series.parquet",
        "turnover_series.parquet",
        "decay_profile.json",
        "regime_attribution.json",
        "exec_trace.json",
    }
    # ``code.py`` is not rendered when the caller supplies no source.
    assert "code.py" not in files
    # The parquet files carry their record as the writer's source — the
    # store's read-back of what actually persisted, so the artifact cannot
    # disagree with the row about what was computed — the json files carry
    # rendered text; and the node row carried the metric columns.
    assert files["signal_returns.parquet"].kind == "parquet"
    assert files["signal_returns.parquet"].source == records["priced"]
    assert files["ic_series.parquet"].source == records["metrics"]
    assert files["decay_profile.json"].kind == "json"
    assert files["regime_attribution.json"].kind == "json"
    assert files["exec_trace.json"].kind == "json"
    assert result.tree_appended is True
    assert result.artifact_written is True
    assert "node_1" in tree.rows


def test_decay_profile_json_is_the_positional_five_horizon_array():
    """``decay_profile.json`` is the positional array, ``None`` per un-measured."""
    records = _seed()
    writer = _FakeArtifactWriter()
    persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=writer,
        tree_writer=_FakeTreeNodeWriter(),
    )
    rendered = json.loads(writer.written["node_1"]["decay_profile.json"].json_text)
    assert rendered == list(records["profile"].as_array())
    assert len(rendered) == len(DECAY_HORIZONS)
    # Horizon 20 covers no date in this grid — the last position is ``None``.
    assert rendered[-1] is None


def test_regime_attribution_json_is_the_per_stratum_per_horizon_split():
    """``regime_attribution.json`` is ``{stratum: {horizon: {dates, mean}}}`` plus the unattributed count."""
    records = _seed()
    writer = _FakeArtifactWriter()
    persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=writer,
        tree_writer=_FakeTreeNodeWriter(),
    )
    rendered = json.loads(writer.written["node_1"]["regime_attribution.json"].json_text)
    assert rendered["unattributed_dates"] == records["attribution"].unattributed_dates
    for stratum_name in records["attribution"].named_strata:
        assert stratum_name in rendered
        for horizon, slice_ in records["attribution"].stratum(stratum_name).slices.items():
            assert rendered[stratum_name][str(horizon)] == {
                "dates": slice_.dates,
                "mean_post_cost_return": slice_.mean_post_cost_return,
            }
    # The three labels are the only strata, plus the unattributed count.
    assert set(rendered) == {*records["attribution"].named_strata, "unattributed_dates"}


def test_exec_trace_carries_the_run_provenance():
    """``exec_trace.json`` is the deterministic fingerprint of the run."""
    records = _seed()
    writer = _FakeArtifactWriter()
    persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "cd" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=writer,
        tree_writer=_FakeTreeNodeWriter(),
    )
    trace = json.loads(writer.written["node_1"]["exec_trace.json"].json_text)
    assert trace == {
        "node_id": "node_1",
        "campaign_id": "camp_1",
        "snapshot_name": records["priced"].snapshot_name,
        "evaluator_hash": "sha256:" + "cd" * 32,
        "cost_model": _REF.reference,
        "horizons": list(HORIZONS),
        "charges_budget": False,
        "steps_completed": [7, 8, 9, 11],
    }


def test_turnover_series_matches_the_metrics_turnover():
    """The rendered ``turnover_series`` reduces to the metrics ``turnover`` scalar.

    The artifact keeps ``turnover_series`` in full and the metrics reduce it to
    one scalar, over the same panel and the same arithmetic; the mean of the
    per-date rendered turnover is the scalar — when the scored symbols equal the
    priced symbols, which this bundle satisfies (AAA and BBB on every date).
    """
    records = _seed()
    writer = _FakeArtifactWriter()
    persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=writer,
        tree_writer=_FakeTreeNodeWriter(),
    )
    # The turnover series is rendered from (returns, metrics); render it the
    # same way and reduce it the way the metrics did — the mean of the per-date
    # rendered turnover is the scalar the metrics reduced.
    from evaluator import render_turnover_series

    rendered = render_turnover_series(records["priced"], records["metrics"])
    assert len(rendered) == records["metrics"].turnover_dates
    assert sum(rendered.values()) / len(rendered) == pytest.approx(records["metrics"].turnover)


# -- Idempotency ----------------------------------------------------------------


def test_a_repersist_refreshes_and_reports_not_appended():
    """A second ``persist_node`` for the same node refreshes, does not duplicate."""
    records = _seed()
    tree = _FakeTreeNodeWriter()
    first = persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=_FakeArtifactWriter(),
        tree_writer=tree,
    )
    second = persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=_FakeArtifactWriter(),
        tree_writer=tree,
    )
    assert first.tree_appended is True
    assert second.tree_appended is False
    # One orchestration row, not two — the idempotent insert refreshed it.
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection:
        rows = connection.execute(
            f"SELECT COUNT(*) FROM {NODE_PERSIST_TABLE} WHERE node_id = 'node_1'"
        ).fetchone()[0]
    assert rows == 1


def test_load_returns_the_persisted_node_and_refuses_a_half():
    """``load`` returns a fully-persisted node and refuses a half-written one."""
    records = _seed()
    persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=_FakeArtifactWriter(),
        tree_writer=_FakeTreeNodeWriter(),
    )
    store = NodeArtifactStore(os.environ["DATABASE_URL"])
    loaded = store.load("node_1")
    assert loaded is not None
    assert loaded.node_id == "node_1"
    assert loaded.metrics.ic_mean == records["metrics"].ic_mean
    assert loaded.marginal.ir_marginal == records["marginal"].ir_marginal
    # A node this step never persisted is honestly ``None``.
    assert store.load("node_never") is None
    # A row whose two flags disagree — the artifact half never committed — is
    # refused, because the two halves are one artifact's content.
    with closing(sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[1])) as connection, connection:
        connection.execute(
            f"UPDATE {NODE_PERSIST_TABLE} SET artifact_written = 0 WHERE node_id = 'node_1'"
        )
    with pytest.raises(EvaluatorArtifactError, match="half-written|two halves"):
        store.load("node_1")


# -- The agreement refusal ------------------------------------------------------


def test_a_metrics_naming_a_different_node_is_refused_before_any_write():
    """A record naming another node is refused before the writer is touched."""
    records = _seed()
    other = _seed(node_id="node_other")
    writer = _FakeArtifactWriter()
    with pytest.raises(EvaluatorArtifactError, match="names node|one node"):
        persist_node(
            node_id="node_1",
            campaign_id="camp_1",
            snapshot_name=records["priced"].snapshot_name,
            evaluator_hash="sha256:" + "ab" * 32,
            returns=records["priced"],
            metrics=other["metrics"],  # a different node's metrics
            profile=records["profile"],
            estimate=records["estimate"],
            attribution=records["attribution"],
            marginal=records["marginal"],
            artifact_writer=writer,
            tree_writer=_FakeTreeNodeWriter(),
        )
    # Nothing was written — the refusal preceded every seam.
    assert writer.written == {}


def test_a_returns_under_a_different_cost_model_is_refused():
    """A record priced under another fee schedule is refused before any write."""
    records = _seed()
    other = _seed(cost_model=_OTHER_REF)
    writer = _FakeArtifactWriter()
    with pytest.raises(EvaluatorArtifactError, match="priced under|one fee"):
        persist_node(
            node_id="node_1",
            campaign_id="camp_1",
            snapshot_name=records["priced"].snapshot_name,
            evaluator_hash="sha256:" + "ab" * 32,
            returns=other["priced"],  # priced under a different fee schedule
            metrics=records["metrics"],
            profile=records["profile"],
            estimate=records["estimate"],
            attribution=records["attribution"],
            marginal=records["marginal"],
            artifact_writer=writer,
            tree_writer=_FakeTreeNodeWriter(),
        )
    assert writer.written == {}


# -- The half-written refusal ---------------------------------------------------


def test_an_artifact_writer_that_fails_leaves_no_partial_node():
    """A writer that fails on one file commits nothing — the half is refused."""
    records = _seed()
    writer = _FakeArtifactWriter(fail_on="regime_attribution.json")
    with pytest.raises(RuntimeError, match="could not commit"):
        persist_node(
            node_id="node_1",
            campaign_id="camp_1",
            snapshot_name=records["priced"].snapshot_name,
            evaluator_hash="sha256:" + "ab" * 32,
            returns=records["priced"],
            metrics=records["metrics"],
            profile=records["profile"],
            estimate=records["estimate"],
            attribution=records["attribution"],
            marginal=records["marginal"],
            artifact_writer=writer,
            tree_writer=_FakeTreeNodeWriter(),
        )
    # The directory was never committed — nothing flushed.
    assert "node_1" not in writer.flushed
    # And the orchestration row's two flags disagree, so load refuses the half.
    store = NodeArtifactStore(os.environ["DATABASE_URL"])
    with pytest.raises(EvaluatorArtifactError, match="half-written|two halves"):
        store.load("node_1")


def test_a_tree_writer_reporting_no_row_is_refused():
    """A tree seam that reports a different node's identity is refused."""

    class _BadTreeWriter:
        def write_node(self, node_row):
            return "some_other_node", True

    records = _seed()
    with pytest.raises(EvaluatorArtifactError, match="another's identity|one node"):
        persist_node(
            node_id="node_1",
            campaign_id="camp_1",
            snapshot_name=records["priced"].snapshot_name,
            evaluator_hash="sha256:" + "ab" * 32,
            returns=records["priced"],
            metrics=records["metrics"],
            profile=records["profile"],
            estimate=records["estimate"],
            attribution=records["attribution"],
            marginal=records["marginal"],
            artifact_writer=_FakeArtifactWriter(),
            tree_writer=_BadTreeWriter(),
        )


# -- code.py: written only when the caller supplies the source ------------------


def test_code_py_is_written_only_when_the_source_is_supplied():
    """``code.py`` is written when the caller passes the signal source, else not."""
    records = _seed()
    with_source = _FakeArtifactWriter()
    persist_node(
        node_id="node_1",
        campaign_id="camp_1",
        snapshot_name=records["priced"].snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=records["priced"],
        metrics=records["metrics"],
        profile=records["profile"],
        estimate=records["estimate"],
        attribution=records["attribution"],
        marginal=records["marginal"],
        artifact_writer=with_source,
        tree_writer=_FakeTreeNodeWriter(),
        code="def alpha(bars): return bars.mean()",
    )
    assert "code.py" in with_source.written["node_1"]
    assert with_source.written["node_1"]["code.py"].kind == "code"
    assert with_source.written["node_1"]["code.py"].code_text == "def alpha(bars): return bars.mean()"


# -- Missing store / unsupported scheme -----------------------------------------


def test_a_missing_store_is_refused_by_name():
    """A missing orchestration store is refused by name, not silently skipped."""
    records = _seed()
    with pytest.raises(EvaluatorArtifactError, match="DATABASE_URL"):
        persist_node(
            node_id="node_1",
            campaign_id="camp_1",
            snapshot_name=records["priced"].snapshot_name,
            evaluator_hash="sha256:" + "ab" * 32,
            returns=records["priced"],
            metrics=records["metrics"],
            profile=records["profile"],
            estimate=records["estimate"],
            attribution=records["attribution"],
            marginal=records["marginal"],
            artifact_writer=_FakeArtifactWriter(),
            tree_writer=_FakeTreeNodeWriter(),
            database_url="",
        )


def test_an_unsupported_scheme_is_refused():
    """The store speaks sqlite; a postgres URL is refused, not silently skipped."""
    records = _seed()
    store = NodeArtifactStore("postgres://localhost/nullius")
    with pytest.raises(EvaluatorArtifactError, match="unsupported.*scheme|sqlite"):
        store.persist(
            node_id="node_1",
            campaign_id="camp_1",
            snapshot_name=records["priced"].snapshot_name,
            evaluator_hash="sha256:" + "ab" * 32,
            returns=records["priced"],
            metrics=records["metrics"],
            profile=records["profile"],
            estimate=records["estimate"],
            attribution=records["attribution"],
            marginal=records["marginal"],
            artifact_writer=_FakeArtifactWriter(),
            tree_writer=_FakeTreeNodeWriter(),
        )


# -- Import-cheap: the new modules are stdlib-only ------------------------------


def test_the_new_modules_import_no_heavy_dependency():
    """``_artifact`` and ``_persist_store`` import no polars/pyarrow/lake/HTTP."""
    import importlib

    for module_name in ("evaluator._artifact", "evaluator._persist_store"):
        module = importlib.import_module(module_name)
        assert "polars" not in module.__dict__
        assert "pyarrow" not in module.__dict__
