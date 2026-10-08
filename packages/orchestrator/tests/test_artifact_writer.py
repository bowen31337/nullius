"""Feature 4, the artifact writer — the evaluator's step-12 seam over the
artifacts member's store.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 4:
*System saves to the artifacts member's store every evaluation artifact
of a node, with orchestrator._artifact_writer.ArtifactStoreWriter(store),
an implementation of the evaluator's ArtifactWriter protocol.*  The
member is the adapter the workspace contract requires — neither Z0
member may import the other, so the artifacts member's own seam suite
proves the store *could* be driven to the protocol and leaves the
driving to whoever injects the writer — and every test here runs the
*real* seam end to end: an :class:`artifacts.ArtifactStore` over a
``tmp_path`` directory (the spec's own sentence), the evaluator's real
:class:`~evaluator.ArtifactPayload` values, and the parquet sources
built by the evaluator's real steps 4 through 8, because a payload
whose source no evaluation produced would be a file no evaluation
wrote.

One test per claim the feature sentence makes:

* **every evaluation artifact** — the whole §9.2 set (three Parquet
  files, three JSON files and ``code.py``) staged through
  ``write_artifact`` and published by one ``flush`` lands as the node's
  one directory at the store's own address, the text files byte-exact
  and the Parquet files decoding back, through the artifacts member's
  own readers, to the records the evaluator measured.

* **the Parquet bytes are the member's own codecs'** — the published
  ``ic_series.parquet``, ``turnover_series.parquet`` and
  ``signal_returns.parquet`` are byte-identical to what
  :func:`artifacts.encode_series` and
  :func:`artifacts.encode_signal_returns` answer for the same records:
  the writer *calls* the member's encoders, it does not grow a second
  Parquet spelling beside features 170-173.

* **staging touches nothing** — a staged write leaves no directory at
  the node's address, nothing in the store's staging plumbing and no
  campaign in the store's listing: the writer holds the staging, and
  the store is reached only by the flush.

* **flushing with nothing staged is a no-op** — a node this writer
  never staged for flushes silently, publishing nothing, and does not
  disturb a node that was flushed.

* **flushing twice rewrites nothing** — the second flush makes no store
  call at all, held by the published files' own inodes and modification
  times: no bytes staged, no directory refreshed.

* **the staged set is a mapping** — re-staging a filename keeps the
  last bytes, the same shape the store's own staging holds, so a retry
  that re-rendered a file replaces it rather than duplicating it.

* **one flush, one node** — flushing a node publishes that node alone;
  a sibling staged in the same writer stays staged and flushes later.

* **a refresh publishes exactly the newly staged set** — a second
  write-and-flush of the §9.2 set without ``code.py`` leaves the
  directory holding exactly the six files, the store's wholesale
  refresh with no splice of the first run's leftovers.

* **a failed flush rolls back and is retryable** — a store that
  refuses mid-flush leaves nothing staged in the store's plumbing and
  the staged set in the writer, so ``flush`` again publishes the whole
  set.

* **the seam's own drift is refused, named, before anything stages** —
  one node staged under two campaigns; a Parquet payload carrying the
  wrong record for its filename, a record naming another node, or a
  filename outside §9.2's three; a payload that is not the evaluator's;
  a ``filename`` that disagrees with the payload's own.

* **the protocol, structurally** — the two callables the evaluator
  duck-checks for, with the protocol's own parameter names, so a rename
  on either side of the seam fails here rather than deep inside a
  pipeline step.

* **the seam's only production caller, run for real** — the
  evaluator's own ``persist_node`` drives this writer end to end over
  the real store: its steps' records persisted to a throwaway SQLite
  database, read back, rendered and handed over as payloads, six files
  published, and the Parquet ones decoding back to the metrics the
  evaluator measured.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
from pathlib import Path

import contract
import pytest
from artifacts import (
    IC_SERIES_FILENAME,
    SIGNAL_RETURNS_FILENAME,
    TURNOVER_SERIES_FILENAME,
    ArtifactNotFoundError,
    ArtifactStore,
    ReturnRow,
    SignalReturns,
    decode_series,
    decode_signal_returns,
    encode_series,
    encode_signal_returns,
)
from evaluator import (
    ArtifactPayload,
    ArtifactWriter,
    CostModelRef,
    CostQuote,
    OracleRequest,
    OracleResponse,
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
    persist_node,
    persist_node_metrics,
    persist_signal_returns,
    render_turnover_series,
)
from orchestrator._artifact_writer import (
    ARTIFACT_WRITER_CODE,
    ArtifactStoreWriter,
    ArtifactWriterError,
)

#: The evaluated node and a sibling, in the UUID spelling the tree
#: store's rows carry, plus the two campaigns keying their directories.
NODE = "11111111-2222-4333-8444-555555555555"
OTHER_NODE = "99999999-8888-4777-8666-555555555555"
CAMPAIGN = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_CAMPAIGN = "77777777-6666-4555-8444-333333333333"

#: Feature 59's cost model identity — the venue/version pair the priced
#: panel is stamped with and the Parquet grid's metadata carries.
VENUE = "binance_spot"
VERSION = "2026.09.1"
REF = CostModelRef(venue=VENUE, version=VERSION)

_START = dt.date(2026, 9, 1)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    """The real artifacts member's store, over a per-test directory.

    The spec's own sentence — *tests use an ArtifactStore over a
    tmp_path directory* — taken literally: the member's store, bound to
    a fresh root under the pytest temporary directory, so no test ever
    writes into a configured artifact root.
    """
    return ArtifactStore(tmp_path / "artifacts")


# -- The records: the evaluator's real steps 4 through 8 -------------------------


def _days(count: int) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid."""
    return tuple(_START + dt.timedelta(days=i) for i in range(count))


# A 12-bar grid with three rebalance dates at its head: horizons 1, 2, 5
# and 10 cover all three, horizon 20 covers none.  AAA trends (a growing
# compound curve), BBB is flat — so the alternating ranking below gives
# the per-date IC a mean and a standard error to reduce over.
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_CLOSES = {
    "AAA": dict(zip(_GRID, _COMPOUND)),
    "BBB": dict(zip(_GRID, [50.0] * 12)),
}

# The regime labels over the rebalance grid and the venues' volumes —
# what the integration test's capacity estimate and regime attribution
# need, one stratum per rebalance date and a thin leg that sizes the
# book.
_TREND, _CHOP, _CRASH = "trend", "chop", "crash"
_LABELS = {
    _REBALANCE[0]: _TREND,
    _REBALANCE[1]: _CHOP,
    _REBALANCE[2]: _CRASH,
}
_THIN, _THICK = 1e6, 5e6
_VOLUMES = {
    "AAA": {day: _THICK for day in _GRID},
    "BBB": {day: _THIN for day in _GRID},
}


def _execution(dates) -> SignalExecution:
    """A hand-built execution — feature 73's output — for step 4."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=("AAA", "BBB"),
            seed=7,
            contract_version=contract.CONTRACT_VERSION,
            problems=[],
        )
        for day in dates
    }
    return SignalExecution(
        snapshot_name="snap_abc123", code_hash="ab" * 32, seed=7, vectors=vectors
    )


def _oracle(alignment):
    """A stub oracle whose real branch is the identity — §7.2's ask seam."""

    def ask(request: OracleRequest) -> OracleResponse:
        aligned = alignment.targets(request.horizon)
        return OracleResponse(
            target_series={
                day: dict(aligned.at(day)) for day in aligned.dates()
            },
            charges_budget=False,
        )

    return ask


def _flat_schedule(bps: float = 10.0):
    """A stub fee schedule: a flat ``bps`` charge on every symbol and bar."""
    rate = bps / 10_000.0

    def schedule(request) -> CostQuote:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: {symbol: rate for symbol in request.symbols}
                for day in request.gross_returns
            },
        )

    return schedule


def _scores(rebalance_dates) -> dict[dt.date, dict[str, float]]:
    """The normalized scores — step 3's output — over the rebalance dates.

    The ranking alternates across the dates (AAA above BBB, then
    reversed) so the per-date IC varies: a constant ranking would give a
    zero standard error and an undefined ``ic_tstat``.
    """
    return {
        day: (
            {"AAA": 1.0, "BBB": -1.0}
            if index % 2 == 0
            else {"AAA": -1.0, "BBB": 1.0}
        )
        for index, day in enumerate(rebalance_dates)
    }


def _priced(node_id: str = NODE):
    """Step 7's own result, over the real steps 4 through 7."""
    aligned = align_targets(_execution(_REBALANCE), _CLOSES)
    gated = gate_targets(
        aligned,
        _oracle(aligned),
        node_id=node_id,
        campaign_id=CAMPAIGN,
        depth=2,
    )
    return apply_costs(gated, _flat_schedule(), node_id=node_id, cost_model=REF)


def _metrics(priced):
    """Step 8's four scalars and their own ic_series, over the same panel."""
    return compute_node_metrics(priced, _scores(priced.rebalance_dates))


def _records():
    """The parquet sources the evaluator's persist step would hand over."""
    priced = _priced()
    return priced, _metrics(priced)


# -- The payloads: §9.2's set as the persist step renders it ---------------------


def _full_set(priced, metrics, *, code=None, decay=None):
    """The §9.2 payloads in the evaluator's own write order.

    The Parquet sources are the real records; the JSON texts are
    literals because the writer's claim about them is bytes, not
    rendering — the evaluator's renderers own that half, and any text
    stands for the text they serialized.
    """
    payloads = [
        (
            SIGNAL_RETURNS_FILENAME,
            ArtifactPayload(
                filename=SIGNAL_RETURNS_FILENAME, kind="parquet", source=priced
            ),
        ),
        (
            IC_SERIES_FILENAME,
            ArtifactPayload(
                filename=IC_SERIES_FILENAME, kind="parquet", source=metrics
            ),
        ),
        (
            TURNOVER_SERIES_FILENAME,
            ArtifactPayload(
                filename=TURNOVER_SERIES_FILENAME,
                kind="parquet",
                source=(priced, metrics),
            ),
        ),
        (
            "decay_profile.json",
            ArtifactPayload(
                filename="decay_profile.json",
                kind="json",
                json_text=decay if decay is not None else "[0.05, 0.04, null, null, null]",
            ),
        ),
        (
            "regime_attribution.json",
            ArtifactPayload(
                filename="regime_attribution.json",
                kind="json",
                json_text='{"trend": {}, "unattributed_dates": 0}',
            ),
        ),
        (
            "exec_trace.json",
            ArtifactPayload(
                filename="exec_trace.json",
                kind="json",
                json_text=json.dumps(
                    {
                        "node_id": priced.node_id,
                        "campaign_id": CAMPAIGN,
                        "charges_budget": False,
                        "steps_completed": [7, 8, 9, 11],
                    }
                ),
            ),
        ),
    ]
    if code is not None:
        payloads.append(
            (
                "code.py",
                ArtifactPayload(filename="code.py", kind="code", code_text=code),
            )
        )
    return payloads


def _stage(writer: ArtifactStoreWriter, payloads, *, node_id=NODE) -> None:
    """Stage a payload set through the seam, as persist_node would."""
    for filename, payload in payloads:
        writer.write_artifact(node_id, CAMPAIGN, filename, payload)


def _flat_panel(priced) -> SignalReturns:
    """The grid the writer builds, stated here independently of it.

    The same flatten the evaluator's own store persists as rows — one
    ``(date, horizon, symbol)`` cell per priced return, the charge and
    the net it carries — so the byte-equality test compares the writer's
    panel against a second construction, not against itself.
    """
    rows = []
    for horizon, series in sorted(priced.series.items()):
        for day in series.dates():
            for symbol, net in sorted(series.at(day).items()):
                rows.append(
                    ReturnRow(
                        rebalance_date=day,
                        horizon=horizon,
                        symbol=symbol,
                        charge=series.charge_at(day)[symbol],
                        post_cost_return=net,
                    )
                )
    return SignalReturns(
        node_id=priced.node_id,
        snapshot_name=priced.snapshot_name,
        venue=priced.cost_model.venue,
        version=priced.cost_model.version,
        rows=rows,
    )


# -- Every evaluation artifact, saved to the store --------------------------------


def test_write_then_flush_publishes_every_evaluation_artifact(
    store: ArtifactStore,
) -> None:
    # The feature sentence's whole claim: the seven §9.2 files of one
    # evaluated node — three Parquet, three JSON, and the caller's
    # code.py — staged through write_artifact and published by one
    # flush land as the node's one directory at the store's own address,
    # keyed campaign then node.  The text files are byte-exact; the
    # Parquet files decode back, through the artifacts member's own
    # readers, to the records the evaluator measured.
    priced, metrics = _records()
    code = "def signal():\n    return {}\n"
    writer = ArtifactStoreWriter(store)
    _stage(writer, _full_set(priced, metrics, code=code))

    assert writer.flush(NODE) is None

    assert store.files(CAMPAIGN, NODE) == (
        "code.py",
        "decay_profile.json",
        "exec_trace.json",
        "ic_series.parquet",
        "regime_attribution.json",
        "signal_returns.parquet",
        "turnover_series.parquet",
    )
    assert store.read(CAMPAIGN, NODE, "code.py") == code.encode("utf-8")
    assert (
        store.read(CAMPAIGN, NODE, "decay_profile.json")
        == b"[0.05, 0.04, null, null, null]"
    )
    trace = json.loads(store.read(CAMPAIGN, NODE, "exec_trace.json"))
    assert trace["node_id"] == NODE
    assert trace["charges_budget"] is False

    ic = decode_series(
        store.read(CAMPAIGN, NODE, IC_SERIES_FILENAME),
        filename=IC_SERIES_FILENAME,
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    assert ic == dict(metrics.ic_series)
    turnover = decode_series(
        store.read(CAMPAIGN, NODE, TURNOVER_SERIES_FILENAME),
        filename=TURNOVER_SERIES_FILENAME,
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    rendered = render_turnover_series(priced, metrics)
    assert turnover == {
        dt.date.fromisoformat(day): value for day, value in rendered.items()
    }

    panel = decode_signal_returns(
        store.read(CAMPAIGN, NODE, SIGNAL_RETURNS_FILENAME),
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    assert panel.node_id == NODE
    assert panel.snapshot_name == priced.snapshot_name
    assert panel.venue == VENUE
    assert panel.version == VERSION
    answered = {
        (row.rebalance_date, row.horizon, row.symbol): (
            row.charge,
            row.post_cost_return,
        )
        for row in panel.rows
    }
    expected = {}
    for horizon, series in priced.series.items():
        for day in series.dates():
            for symbol, net in series.at(day).items():
                expected[(day, horizon, symbol)] = (
                    series.charge_at(day)[symbol],
                    net,
                )
    assert answered == expected


def test_parquet_bytes_are_the_artifacts_member_s_own_codecs(
    store: ArtifactStore,
) -> None:
    # The writer calls the member's encoders, it does not re-implement
    # them: each published Parquet file is byte-identical to what
    # artifacts.encode_series / encode_signal_returns answer for the
    # same records — the panel built here by a second construction of
    # the flatten, so the equality is writer-vs-member, not tautology.
    priced, metrics = _records()
    writer = ArtifactStoreWriter(store)
    _stage(writer, _full_set(priced, metrics))
    writer.flush(NODE)

    assert store.read(CAMPAIGN, NODE, IC_SERIES_FILENAME) == encode_series(
        metrics.ic_series,
        filename=IC_SERIES_FILENAME,
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    assert store.read(
        CAMPAIGN, NODE, TURNOVER_SERIES_FILENAME
    ) == encode_series(
        render_turnover_series(priced, metrics),
        filename=TURNOVER_SERIES_FILENAME,
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    assert store.read(
        CAMPAIGN, NODE, SIGNAL_RETURNS_FILENAME
    ) == encode_signal_returns(_flat_panel(priced))


def test_staging_touches_nothing_until_the_flush(
    store: ArtifactStore,
) -> None:
    # write_artifact stages in the writer, not the store: before any
    # flush the node holds no directory, the store's staging plumbing
    # holds nothing for it, and no campaign exists in the listing — a
    # reader of the store sees a node exactly when a flush published it.
    writer = ArtifactStoreWriter(store)
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(filename="code.py", kind="code", code_text="pass\n"),
    )

    assert not store.has_node(CAMPAIGN, NODE)
    assert store.staged(CAMPAIGN, NODE) == ()
    assert store.campaign_ids() == ()
    with pytest.raises(ArtifactNotFoundError):
        store.files(CAMPAIGN, NODE)


def test_flush_with_nothing_staged_is_a_no_op(store: ArtifactStore) -> None:
    # A node this writer never staged flushes silently: no error (the
    # store refuses an empty commit, and rightly — but a writer that
    # staged nothing is a flush with nothing to do, not a failure to
    # name), nothing published, nothing staged.  And the no-op spares a
    # node that *was* flushed: only the sibling holds a directory.
    writer = ArtifactStoreWriter(store)

    assert writer.flush(NODE) is None
    assert not store.has_node(CAMPAIGN, NODE)
    assert store.campaign_ids() == ()

    writer.write_artifact(
        OTHER_NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(filename="code.py", kind="code", code_text="pass\n"),
    )
    writer.flush(OTHER_NODE)
    assert writer.flush(NODE) is None

    assert store.node_ids(CAMPAIGN) == (OTHER_NODE,)
    assert not store.has_node(CAMPAIGN, NODE)


def test_flushing_twice_rewrites_nothing(store: ArtifactStore) -> None:
    # The first flush consumes the staging once the publication
    # succeeded, so the second finds no entry and returns before the
    # store is touched — held by the published files' own inodes and
    # modification times, which any re-stage and re-commit would have
    # replaced (the commit publishes by renaming a fresh directory in).
    priced, metrics = _records()
    writer = ArtifactStoreWriter(store)
    _stage(writer, _full_set(priced, metrics, code="pass\n"))
    writer.flush(NODE)

    published = store.node_directory(CAMPAIGN, NODE)
    before = {
        entry.name: (entry.stat().st_ino, entry.stat().st_mtime_ns)
        for entry in published.iterdir()
    }
    assert len(before) == 7

    assert writer.flush(NODE) is None

    after = {
        entry.name: (entry.stat().st_ino, entry.stat().st_mtime_ns)
        for entry in published.iterdir()
    }
    assert after == before
    assert store.staged(CAMPAIGN, NODE) == ()


def test_re_staging_a_filename_keeps_the_last_bytes(
    store: ArtifactStore,
) -> None:
    # The staged set is a mapping, one entry per filename — the same
    # shape the store's own staging holds — so a retry that re-rendered
    # a file replaces it rather than publishing both.
    writer = ArtifactStoreWriter(store)
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(
            filename="code.py", kind="code", code_text="def first():\n    pass\n"
        ),
    )
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(
            filename="code.py", kind="code", code_text="def second():\n    pass\n"
        ),
    )
    writer.flush(NODE)

    assert store.files(CAMPAIGN, NODE) == ("code.py",)
    assert store.read(CAMPAIGN, NODE, "code.py") == b"def second():\n    pass\n"


def test_flush_publishes_only_the_flushed_node(store: ArtifactStore) -> None:
    # flush is per node: one node's publish is never another's.  The
    # sibling staged in the same writer stays staged — untouched by the
    # first node's flush, invisible to the store — and flushes later to
    # its own directory.
    writer = ArtifactStoreWriter(store)
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(filename="code.py", kind="code", code_text="first\n"),
    )
    writer.write_artifact(
        OTHER_NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(filename="code.py", kind="code", code_text="second\n"),
    )

    writer.flush(NODE)

    assert store.has_node(CAMPAIGN, NODE)
    assert not store.has_node(CAMPAIGN, OTHER_NODE)
    assert store.staged(CAMPAIGN, OTHER_NODE) == ()

    writer.flush(OTHER_NODE)

    assert store.read(CAMPAIGN, NODE, "code.py") == b"first\n"
    assert store.read(CAMPAIGN, OTHER_NODE, "code.py") == b"second\n"


def test_a_refreshed_flush_publishes_exactly_the_newly_staged_set(
    store: ArtifactStore,
) -> None:
    # The evaluator's idempotent re-persist, answered: a second
    # write-and-flush of the §9.2 set — a retry whose caller supplied
    # no code.py, and one JSON file re-rendered — leaves the directory
    # holding exactly the newly staged set.  The store commits
    # wholesale, and the flush's opening discard guarantees the
    # published set is this writer's staging, never a splice with the
    # first run's code.py.
    priced, metrics = _records()
    writer = ArtifactStoreWriter(store)
    _stage(writer, _full_set(priced, metrics, code="pass\n"))
    writer.flush(NODE)
    assert "code.py" in store.files(CAMPAIGN, NODE)

    _stage(
        writer,
        _full_set(priced, metrics, decay="[0.2, null, null, null, null]"),
    )
    writer.flush(NODE)

    assert store.files(CAMPAIGN, NODE) == (
        "decay_profile.json",
        "exec_trace.json",
        "ic_series.parquet",
        "regime_attribution.json",
        "signal_returns.parquet",
        "turnover_series.parquet",
    )
    assert (
        store.read(CAMPAIGN, NODE, "decay_profile.json")
        == b"[0.2, null, null, null, null]"
    )


class _FailingWrites:
    """A store that delegates to the real one but refuses one write.

    The writer takes its store structurally, so a seam that counts the
    ``write`` calls and raises on a chosen one drives the failure path
    over the real filesystem beneath — the refusal lands mid-flush,
    with earlier files already staged in the store's plumbing.
    """

    def __init__(self, real: ArtifactStore, refuse_at: int) -> None:
        self._real = real
        self._refuse_at = refuse_at
        self.writes = 0

    def write(self, *args: object) -> object:
        self.writes += 1
        if self.writes == self._refuse_at:
            raise RuntimeError("the store could not stage the file")
        return self._real.write(*args)

    def commit(self, *args: object) -> object:
        return self._real.commit(*args)

    def discard(self, *args: object) -> object:
        return self._real.discard(*args)


def test_a_failed_flush_rolls_the_store_back_and_is_retryable(
    store: ArtifactStore,
) -> None:
    # The flush is a transaction over the store's staged set: a write
    # that fails mid-flush leaves nothing in the store's plumbing (the
    # file that did stage is rolled back) and no directory published,
    # and the staged set stays in the writer — so the retry is flush
    # again, and it publishes the whole set, not the remainder.
    writer = ArtifactStoreWriter(_FailingWrites(store, refuse_at=2))
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "decay_profile.json",
        ArtifactPayload(
            filename="decay_profile.json", kind="json", json_text="[0.05]"
        ),
    )
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "exec_trace.json",
        ArtifactPayload(
            filename="exec_trace.json", kind="json", json_text="{}"
        ),
    )
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "regime_attribution.json",
        ArtifactPayload(
            filename="regime_attribution.json", kind="json", json_text="{}"
        ),
    )

    with pytest.raises(RuntimeError, match="could not stage"):
        writer.flush(NODE)

    assert store.staged(CAMPAIGN, NODE) == ()
    assert not store.has_node(CAMPAIGN, NODE)

    writer.flush(NODE)

    assert store.files(CAMPAIGN, NODE) == (
        "decay_profile.json",
        "exec_trace.json",
        "regime_attribution.json",
    )
    assert store.read(CAMPAIGN, NODE, "decay_profile.json") == b"[0.05]"
    assert writer.flush(NODE) is None  # consumed: a third flush rewrites nothing
    assert store.staged(CAMPAIGN, NODE) == ()


def test_a_node_staged_under_two_campaigns_is_refused(
    store: ArtifactStore,
) -> None:
    # §9.2 keys a node's one directory by campaign then node, so a set
    # spliced across two campaigns would publish half of itself under
    # each — refused before anything stages, with the store untouched
    # and the original staging still flushable under its own campaign.
    writer = ArtifactStoreWriter(store)
    writer.write_artifact(
        NODE,
        CAMPAIGN,
        "code.py",
        ArtifactPayload(filename="code.py", kind="code", code_text="pass\n"),
    )

    with pytest.raises(ArtifactWriterError, match=ARTIFACT_WRITER_CODE) as refused:
        writer.write_artifact(
            NODE,
            OTHER_CAMPAIGN,
            "exec_trace.json",
            ArtifactPayload(filename="exec_trace.json", kind="json", json_text="{}"),
        )
    assert CAMPAIGN in str(refused.value)
    assert OTHER_CAMPAIGN in str(refused.value)

    assert store.campaign_ids() == ()
    writer.flush(NODE)
    assert store.has_node(CAMPAIGN, NODE)
    assert not store.has_node(OTHER_CAMPAIGN, NODE)


def test_a_parquet_payload_with_the_wrong_source_is_refused(
    store: ArtifactStore,
) -> None:
    # Each §9.2 Parquet file is encoded from the record the evaluator's
    # own render hands it: the priced panel for the grid, the metrics
    # for the IC series, the pair for the turnover.  A payload carrying
    # any other source — or naming a Parquet file outside §9.2's three,
    # or a record belonging to another node — is refused by name, and
    # nothing reaches the store.
    priced, metrics = _records()
    other = _priced(node_id=OTHER_NODE)
    writer = ArtifactStoreWriter(store)

    with pytest.raises(ArtifactWriterError, match="NodeMetrics"):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            IC_SERIES_FILENAME,
            ArtifactPayload(
                filename=IC_SERIES_FILENAME, kind="parquet", source=priced
            ),
        )
    with pytest.raises(ArtifactWriterError, match="PostCostReturns"):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            SIGNAL_RETURNS_FILENAME,
            ArtifactPayload(
                filename=SIGNAL_RETURNS_FILENAME, kind="parquet", source=metrics
            ),
        )
    with pytest.raises(ArtifactWriterError, match="returns, metrics"):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            TURNOVER_SERIES_FILENAME,
            ArtifactPayload(
                filename=TURNOVER_SERIES_FILENAME, kind="parquet", source=priced
            ),
        )
    with pytest.raises(ArtifactWriterError, match="returns, metrics"):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            TURNOVER_SERIES_FILENAME,
            ArtifactPayload(
                filename=TURNOVER_SERIES_FILENAME,
                kind="parquet",
                source=(priced, priced),
            ),
        )
    with pytest.raises(ArtifactWriterError, match=OTHER_NODE):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            SIGNAL_RETURNS_FILENAME,
            ArtifactPayload(
                filename=SIGNAL_RETURNS_FILENAME, kind="parquet", source=other
            ),
        )
    with pytest.raises(ArtifactWriterError, match="closed"):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            "other.parquet",
            ArtifactPayload(
                filename="other.parquet", kind="parquet", source=metrics
            ),
        )

    assert store.staged(CAMPAIGN, NODE) == ()
    assert not store.has_node(CAMPAIGN, NODE)
    assert store.campaign_ids() == ()


def test_a_foreign_payload_and_a_filename_mismatch_are_refused(
    store: ArtifactStore,
) -> None:
    # The seam carries the evaluator's own payload — the kind names the
    # medium, and a value without one is a file no renderer vouched
    # for — and the filename asked for must be the payload's own, so
    # content can never land under a name its renderer never chose.
    writer = ArtifactStoreWriter(store)

    with pytest.raises(ArtifactWriterError, match="ArtifactPayload"):
        writer.write_artifact(NODE, CAMPAIGN, "code.py", object())

    with pytest.raises(ArtifactWriterError, match="payload's own"):
        writer.write_artifact(
            NODE,
            CAMPAIGN,
            "exec_trace.json",
            ArtifactPayload(
                filename="decay_profile.json", kind="json", json_text="{}"
            ),
        )

    assert store.staged(CAMPAIGN, NODE) == ()
    assert store.campaign_ids() == ()


def test_the_writer_satisfies_the_evaluator_s_protocol(
    store: ArtifactStore,
) -> None:
    # The protocol is structural and never imported by the artifacts
    # member; what can be pinned is that the writer exposes exactly the
    # two callables the evaluator's own duck-check asks for, with the
    # parameter names the protocol declares — node first — so a rename
    # on either side of the seam fails here rather than deep inside a
    # pipeline step.
    writer = ArtifactStoreWriter(store)

    assert callable(writer.write_artifact)
    assert callable(writer.flush)

    write_parameters = list(
        inspect.signature(writer.write_artifact).parameters  # type: ignore[attr-defined]
    )
    flush_parameters = list(
        inspect.signature(writer.flush).parameters  # type: ignore[attr-defined]
    )
    # The protocol's own declarations are the source of truth, read off
    # the class (where the parameter list still carries ``self``).
    assert write_parameters == [
        name
        for name in inspect.signature(ArtifactWriter.write_artifact).parameters
        if name != "self"
    ]
    assert flush_parameters == [
        name
        for name in inspect.signature(ArtifactWriter.flush).parameters
        if name != "self"
    ]
    assert write_parameters == ["node_id", "campaign_id", "filename", "payload"]
    assert flush_parameters == ["node_id"]


class _FakeTreeNodeWriter:
    """An in-memory ``TreeNodeWriter`` — answers ``(node_id, appended)``.

    The tree seam is feature 3's, not this one's, so the integration
    test fakes it the way the evaluator's own persist suite does: a
    dict keyed by node, a first write appending and a refresh not, so
    step 12's orchestration proceeds to the flush this feature owns.
    """

    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def write_node(self, node_row: object) -> tuple[str, bool]:
        appended = node_row.node_id not in self.rows  # type: ignore[attr-defined]
        self.rows[node_row.node_id] = node_row  # type: ignore[attr-defined]
        return node_row.node_id, appended  # type: ignore[attr-defined]


def test_the_evaluator_s_persist_step_drives_the_writer_end_to_end(
    store: ArtifactStore, tmp_path: Path
) -> None:
    # The seam's only production caller, run for real.  The evaluator's
    # own steps 4 through 9 produce and persist the records over a
    # throwaway SQLite database; persist_node reads them back, renders
    # each §9.2 file and hands it to this writer — the payload
    # vocabulary exactly as the evaluator speaks it, no test-built
    # stand-ins — and the artifacts member's store answers the whole
    # directory back: six files for six renders, no code.py because no
    # signal source was supplied, and the Parquet files decoding, through
    # the member's own readers, to the metrics the evaluator measured.
    url = f"sqlite:///{tmp_path / 'persist-test.db'}"
    priced = _priced()
    scores = _scores(priced.rebalance_dates)
    metrics = compute_node_metrics(priced, scores)
    profile = compute_decay_profile(priced, scores)
    estimate = estimate_capacity(priced, _VOLUMES)
    attribution = attribute_regimes(priced, _LABELS)
    # A resident book whose per-date return varies — a constant book has
    # no reward-to-variance ratio to increment, so compute_marginal_ir
    # refuses it.
    book = {
        "resident_signal": dict(
            zip(priced.rebalance_dates, [0.01, -0.02, 0.015])
        )
    }
    marginal = compute_marginal_ir(priced, book)
    persist_signal_returns(priced, url)
    persist_node_metrics(metrics, url)
    persist_decay_profile(profile, url)
    persist_capacity(estimate, attribution, url)
    persist_marginal_ir(marginal, url)

    persistence = persist_node(
        node_id=NODE,
        campaign_id=CAMPAIGN,
        snapshot_name=priced.snapshot_name,
        evaluator_hash="sha256:" + "ab" * 32,
        returns=priced,
        metrics=metrics,
        profile=profile,
        estimate=estimate,
        attribution=attribution,
        marginal=marginal,
        artifact_writer=ArtifactStoreWriter(store),
        tree_writer=_FakeTreeNodeWriter(),
        database_url=url,
    )

    assert persistence.node_id == NODE
    assert persistence.artifact_written is True
    assert persistence.tree_appended is True
    assert store.files(CAMPAIGN, NODE) == (
        "decay_profile.json",
        "exec_trace.json",
        "ic_series.parquet",
        "regime_attribution.json",
        "signal_returns.parquet",
        "turnover_series.parquet",
    )
    trace = json.loads(store.read(CAMPAIGN, NODE, "exec_trace.json"))
    assert trace["node_id"] == NODE
    assert trace["campaign_id"] == CAMPAIGN
    assert trace["evaluator_hash"] == "sha256:" + "ab" * 32
    ic = decode_series(
        store.read(CAMPAIGN, NODE, IC_SERIES_FILENAME),
        filename=IC_SERIES_FILENAME,
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    assert ic == dict(metrics.ic_series)
    panel = decode_signal_returns(
        store.read(CAMPAIGN, NODE, SIGNAL_RETURNS_FILENAME),
        campaign_id=CAMPAIGN,
        node_id=NODE,
    )
    assert panel.node_id == NODE
    assert panel.venue == VENUE
    assert panel.version == VERSION


def test_the_module_exports_exactly_its_two_names() -> None:
    # The private module's surface is the feature's spelling and its
    # own refusal — the name feature 8 re-exports from the package and
    # the error a caller catches — and nothing else.
    from orchestrator import _artifact_writer

    assert set(_artifact_writer.__all__) == {
        "ArtifactStoreWriter",
        "ArtifactWriterError",
    }
    assert callable(_artifact_writer.ArtifactStoreWriter)
    assert issubclass(_artifact_writer.ArtifactWriterError, Exception)
