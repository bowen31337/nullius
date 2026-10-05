"""The artifact writer — the evaluator's step-12 seam, carried by the store.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 4:
*System saves to the artifacts member's store every evaluation artifact
of a node, with orchestrator._artifact_writer.ArtifactStoreWriter(store),
an implementation of the evaluator's ArtifactWriter protocol.*  The
spec's addition summary names the hole — *"No implementation exists of
the evaluator's TreeNodeWriter and ArtifactWriter protocols"* — and the
artifacts member's own seam suite states where the filling has to live:
neither Z0 member may import the other, so *"the adapter lives with
whoever injects the writer"* (``packages/artifacts/tests/test_seam.py``).
This module is that adapter, and it is the orchestrator's because the
orchestrator is the member that injects the writer into
:func:`evaluator.persist_node`.

**Two vocabularies, one adapter.**  The protocol
(:class:`evaluator.ArtifactWriter`) spells its two operations
``write_artifact(node_id, campaign_id, filename, payload)`` and
``flush(node_id)`` — node first, and a payload object rather than raw
bytes; the store (:class:`artifacts.ArtifactStore`) spells the same two
operations ``write(campaign_id, node_id, filename, data)`` and
``commit(campaign_id, node_id)`` — campaign first, and bytes.  The
*contract* is the one the store documents: writes stage, one commit
point publishes, nothing is half-written.  This class maps the spellings
— the key order swapped, the payload's ``kind`` encoded to bytes, and
``flush`` carried by the store's commit — and adds nothing the contract
does not already name.

**Staging is the writer's; writing through the store is the flush's.**
:meth:`ArtifactStoreWriter.write_artifact` encodes the payload to bytes
and stages it *in the writer*, keyed by node, and :meth:`ArtifactStoreWriter.flush`
writes the staged files through the ArtifactStore and commits them — the
feature's own sentence, taken literally.  Nothing touches the store
before the flush, so the store's own staging plumbing stays empty for a
node this writer is still assembling, and a reader of the store sees a
node's directory exactly when a flush published it.  Re-staging a
filename keeps the last bytes — the staged set is a mapping, one entry
per filename, the same shape the store's staging holds — so a retry that
re-renders a file replaces it rather than duplicating it.

**Flushing is exactly-once per staged set.**  A node with nothing staged
flushes as a no-op: the writer holds no entry for it, so the store is
never asked to commit a directory it has nothing to publish for (the
store refuses an empty commit, and rightly — but a writer that staged
nothing is not a failure to name, it is a flush with nothing to do).
Flushing twice rewrites nothing: the first flush consumes the staging
once the publication has succeeded, so the second finds no entry and
returns before the store is touched — no bytes staged, no directory
refreshed, the published files' very inodes unchanged.  A flush that
*fails* consumes nothing: the staged set stays in the writer, so the
retry is simply ``flush`` again.

**The flush is a transaction over the store's staged set.**  It opens by
discarding whatever the store's staging holds for the node — the
isolation half — so the set it publishes is exactly what *this writer*
staged and never a splice of an earlier interrupted attempt's leftovers
(a retry whose caller supplied no ``code.py`` must not publish the
``code.py`` a crashed process left staged).  It then stages every file
through :meth:`ArtifactStore.write` and publishes with
:meth:`ArtifactStore.commit`, whose directory rename is atomic on POSIX.
Any failure — at a write or at the commit — rolls the store's staging
back with :meth:`ArtifactStore.discard`, best-effort so the original
error is the one that surfaces, and leaves any previously published
version of the node untouched: after a failed flush the store holds
nothing half-staged, and after a succeeded one it holds the whole node.

**The Parquet bytes are the artifacts member's own.**  A ``"json"`` or
``"code"`` payload is its text as UTF-8 — the renderers the evaluator
owns already serialized it.  A ``"parquet"`` payload names the record
the writer encodes, and the encoder is the artifacts member's
(:func:`artifacts.encode_signal_returns` for the §9.2 grid,
:func:`artifacts.encode_series` for the two metric series) — called,
never re-implemented, because a second Parquet spelling beside features
170–173's would be a file the member's own readers could refuse.  What
the writer does own is the *record conversion at the boundary*: the
evaluator's :class:`~evaluator.PostCostReturns` becomes the member's
:class:`~artifacts.SignalReturns` one :class:`~artifacts.ReturnRow` per
``(date, horizon, symbol)`` — the same flatten the evaluator's own store
persists as rows, venue and version read off the cost model the record
carries — the metrics' own ``ic_series`` is handed to the series codec
whole, and the turnover series is rendered by the evaluator's own
:func:`~evaluator.render_turnover_series` from the pair the payload
carries.  The dispatch is by the payload's ``filename``, because the
filename is part of the payload's identity: a Parquet payload naming a
file outside §9.2's three is refused, not guessed an encoder for.

**No error of the store's is translated, and none of this module's own
is spent on the store's questions.**  A key the store refuses
(:class:`~artifacts.ArtifactKeyError`), a filesystem it cannot reach
(:class:`~artifacts.ArtifactStoreError`), a panel its own encoder
refuses — each surfaces as the artifacts member's error, unwrapped, the
same stance :mod:`orchestrator._charge` takes at the ledger seam.  What
:exc:`ArtifactWriterError` (code word ``artifact_writer``) names is
exclusively the seam's own drift: a payload that is not the evaluator's,
a ``filename`` that disagrees with the payload's own, a Parquet source
of the wrong record for the file it was handed, a record naming a node
other than the one being written, or one node staged under two
campaigns — each refused before anything is staged.

**The module knows nothing about null.**  It never reads a node's null
status, the sidecar key or any ``is_null`` value; null-ness crosses this
seam only as whatever ``exec_trace.json`` text the evaluator rendered
and the ``charges_budget`` it already serialized.  The writer's whole
world is filenames, bytes and two ids.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from artifacts import (
    IC_SERIES_FILENAME,
    SIGNAL_RETURNS_FILENAME,
    TURNOVER_SERIES_FILENAME,
    ReturnRow,
    SignalReturns,
    encode_series,
    encode_signal_returns,
)
from evaluator import (
    ArtifactPayload,
    NodeMetrics,
    PostCostReturns,
    render_turnover_series,
)

__all__ = ["ArtifactStoreWriter", "ArtifactWriterError"]

#: The code word every refusal of this module opens with — greppable, and
#: named for the seam the refusal is about: the artifact *writer*, not the
#: store beneath it (whose refusals stay its own) and not the evaluator
#: above it (whose renderers refused malformed content before a payload
#: was ever built).
ARTIFACT_WRITER_CODE: Final[str] = "artifact_writer"


class ArtifactWriterError(Exception):
    """The writer's own seam drift — a payload or staging it refuses.

    Raised when the evaluator's step-12 seam is spoken to in a shape this
    adapter cannot carry to the store: a payload that is not the
    evaluator's :class:`~evaluator.ArtifactPayload`, a ``filename``
    argument that disagrees with the payload's own, a Parquet payload
    naming a file outside §9.2's three or carrying the wrong record for
    the file it names, a record that names a node other than the one
    being written, or one node staged under two campaigns.  Each is
    refused before anything is staged, so a refused write leaves the
    writer's staging exactly as it was.  Failures of the store itself
    surface as the artifacts member's own errors, untranslated — this
    error is never a wrapper for them.
    """


@dataclass
class _StagedNode:
    """One node's staged set, in the writer, before any store call.

    The campaign every file of the set named — one value for the whole
    set, enforced by :meth:`ArtifactStoreWriter.write_artifact`, because
    the node's directory is keyed by *both* ids and a set spliced across
    two campaigns would publish half of itself under each.  The files,
    one bytes value per filename in the order they were staged: a
    mapping, so re-staging a filename replaces it, exactly as the
    store's own staging behaves.
    """

    campaign_id: str
    files: dict[str, bytes] = field(default_factory=dict)


class ArtifactStoreWriter:
    """The evaluator's :class:`~evaluator.ArtifactWriter` over an
    :class:`artifacts.ArtifactStore`.

    ``store`` is the artifacts member's store, taken structurally: an
    object exposing ``write(campaign_id, node_id, filename, data)``,
    ``commit(campaign_id, node_id)`` and ``discard(campaign_id,
    node_id)`` — the three operations the flush's transaction uses, and
    the shape :class:`artifacts.ArtifactStore` already speaks, satisfied
    with no adapter of its own.  Construction performs no I/O and owns
    no path: the root, the keys and the publication discipline are the
    store's, and this class never reaches around them.
    """

    def __init__(self, store: object) -> None:
        self._store = store
        self._staged: dict[str, _StagedNode] = {}

    def write_artifact(
        self,
        node_id: str,
        campaign_id: str,
        filename: str,
        payload: ArtifactPayload,
    ) -> None:
        """Stage one file of the node's artifact — in the writer, as bytes.

        The staging half of the seam, and the feature's own sentence:
        the payload is encoded now — a refused payload refuses here,
        before anything is staged — and kept under the node until
        :meth:`flush` writes it through the store.  Nothing touches the
        store: the store's staging plumbing holds nothing for a node
        this writer is still assembling, and the node's directory does
        not exist until a flush publishes it.

        The filename must be the payload's own — the payload's identity
        and the file it lands as are one fact, and a mismatch means the
        caller built one file and asked to write another.  Staging a
        second file under a filename already staged keeps the last
        bytes, and staging under a campaign other than the node's
        staged one is refused, because the node's one directory is
        keyed by both ids.
        """
        if not isinstance(payload, ArtifactPayload):
            raise ArtifactWriterError(
                f"{ARTIFACT_WRITER_CODE}: write_artifact carries the "
                f"evaluator's ArtifactPayload — got {type(payload).__name__}; "
                "the payload's kind names the medium its content comes in, "
                "and a value without one is a file the renderer never "
                "vouched for"
            )
        if payload.filename != filename:
            raise ArtifactWriterError(
                f"{ARTIFACT_WRITER_CODE}: the filename asked for "
                f"({filename!r}) is not the payload's own "
                f"({payload.filename!r}); a payload is the content of one "
                "named file, and writing it under another name would file "
                "content the renderer never vouched for under a name it "
                "never chose"
            )
        data = _encode(payload, node_id=node_id, campaign_id=campaign_id)
        staged = self._staged.get(node_id)
        if staged is None:
            staged = _StagedNode(campaign_id=campaign_id)
            self._staged[node_id] = staged
        elif staged.campaign_id != campaign_id:
            raise ArtifactWriterError(
                f"{ARTIFACT_WRITER_CODE}: node {node_id!r} is staged under "
                f"campaign {staged.campaign_id!r} and was asked to stage "
                f"{filename!r} under {campaign_id!r}; §9.2 keys a node's one "
                "artifact directory by campaign then node, and a set spliced "
                "across two campaigns would publish half of itself under "
                "each"
            )
        staged.files[filename] = data

    def flush(self, node_id: str) -> None:
        """Write the node's staged files through the store and commit them.

        The commit point, and the whole of the store's involvement: the
        staged set is written through :meth:`ArtifactStore.write` and
        published by :meth:`ArtifactStore.commit` — whose directory
        rename is atomic on POSIX, so no reader observes a half-written
        node.  A node with nothing staged flushes as a no-op, and a flush
        of a node whose staging a previous flush already published
        rewrites nothing — no store call is made at all, so much as the
        files' inodes are untouched.

        The publication is transactional over the store's staging: it
        opens by discarding whatever the store holds staged for the node
        (isolation — the published set is exactly this writer's staged
        set, never a splice with an interrupted attempt's leftovers),
        and any failure rolls the store's staging back, best-effort,
        leaving any previously published version untouched and the
        staged set in the writer — so the retry is ``flush`` again.  The
        staging is consumed only once the commit has succeeded.
        """
        staged = self._staged.get(node_id)
        if staged is None or not staged.files:
            return
        campaign_id = staged.campaign_id
        try:
            self._store.discard(campaign_id, node_id)
            for filename, data in staged.files.items():
                self._store.write(campaign_id, node_id, filename, data)
            self._store.commit(campaign_id, node_id)
        except BaseException:
            # Roll the store's staging back so nothing half-written
            # lingers for a later flush to splice in.  Best-effort: the
            # error that triggered the rollback is the one to surface,
            # and a janitorial discard failing under it would mask it.
            try:
                self._store.discard(campaign_id, node_id)
            except Exception:  # noqa: BLE001, S110 - never mask the error
                pass
            raise
        self._staged.pop(node_id, None)


# -- The encoding: the payload's kind, and the member's own codecs ----------------


def _encode(
    payload: ArtifactPayload, *, node_id: str, campaign_id: str
) -> bytes:
    """One payload to the bytes its file holds — the adapter's core.

    The text kinds are their text as UTF-8, already serialized by the
    evaluator's renderers.  The Parquet kind reaches for the artifacts
    member's own encoder, chosen by the payload's ``filename`` — the
    identity the payload carries — so the three §9.2 Parquet files are
    written by the same codecs the member's readers read with, never by
    a second spelling this module grew.  A Parquet payload naming any
    other file is refused: §9.2's artifact set is closed, and the
    evaluator's own render refuses a filename outside it the same way.
    """
    if payload.kind == "json":
        return payload.json_text.encode("utf-8")
    if payload.kind == "code":
        return payload.code_text.encode("utf-8")
    if payload.filename == SIGNAL_RETURNS_FILENAME:
        return encode_signal_returns(
            _panel(payload.source, node_id=node_id)
        )
    if payload.filename == IC_SERIES_FILENAME:
        return encode_series(
            _ic_series_of(payload.source, node_id=node_id),
            filename=IC_SERIES_FILENAME,
            campaign_id=campaign_id,
            node_id=node_id,
        )
    if payload.filename == TURNOVER_SERIES_FILENAME:
        return encode_series(
            _turnover_of(payload.source, node_id=node_id),
            filename=TURNOVER_SERIES_FILENAME,
            campaign_id=campaign_id,
            node_id=node_id,
        )
    raise ArtifactWriterError(
        f"{ARTIFACT_WRITER_CODE}: a parquet payload must name one of "
        f"§9.2's three Parquet files ({SIGNAL_RETURNS_FILENAME!r}, "
        f"{IC_SERIES_FILENAME!r} or {TURNOVER_SERIES_FILENAME!r}) — got "
        f"{payload.filename!r}; the artifact set is closed, and a file "
        "outside it has no encoder this writer may reach for"
    )


def _panel(source: object, *, node_id: str) -> SignalReturns:
    """The grid payload's record, as the artifacts member's panel.

    Step 7's :class:`~evaluator.PostCostReturns` flattened to one
    :class:`~artifacts.ReturnRow` per ``(rebalance date, horizon,
    symbol)`` the evaluation priced — the same walk the evaluator's own
    store persists as rows, so the file and the store's table carry the
    same grid — with the fee schedule's venue and version read off the
    cost model the record is stamped with.  The panel's empty refusal
    and its duplicate-cell refusal are the member's own, met at the
    record's construction.
    """
    if not isinstance(source, PostCostReturns):
        raise ArtifactWriterError(
            f"{ARTIFACT_WRITER_CODE}: a {SIGNAL_RETURNS_FILENAME!r} "
            f"payload carries step 7's own result — a PostCostReturns — "
            f"got {type(source).__name__}; the grid is the priced panel, "
            "and only that record says which dates, symbols and horizons "
            "were measured"
        )
    if source.node_id != node_id:
        raise ArtifactWriterError(
            f"{ARTIFACT_WRITER_CODE}: the {SIGNAL_RETURNS_FILENAME!r} "
            f"payload names node {source.node_id!r} but is written for "
            f"node {node_id!r}; a node's artifact directory holds one "
            "node's returns, and a panel filed under another's address is "
            "a misfiling every later reader would trust"
        )
    rows: list[ReturnRow] = []
    for horizon, series in sorted(source.series.items()):
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
        node_id=source.node_id,
        snapshot_name=source.snapshot_name,
        venue=source.cost_model.venue,
        version=source.cost_model.version,
        rows=rows,
    )


def _ic_series_of(
    source: object, *, node_id: str
) -> Mapping[dt.date, float]:
    """The IC-series payload's record, as the mapping the codec takes.

    Step 8's :class:`~evaluator.NodeMetrics` carries its own per-date
    coefficients as ``ic_series`` — the series whose mean the record's
    ``ic_mean`` is checked against — and that mapping is the whole of
    the file, handed to the member's series codec as the record holds
    it, unreduced.
    """
    if not isinstance(source, NodeMetrics):
        raise ArtifactWriterError(
            f"{ARTIFACT_WRITER_CODE}: an {IC_SERIES_FILENAME!r} payload "
            f"carries step 8's own result — a NodeMetrics — got "
            f"{type(source).__name__}; the per-date coefficients are the "
            "metrics record's own series, and only that record carries "
            "them"
        )
    if source.node_id != node_id:
        raise ArtifactWriterError(
            f"{ARTIFACT_WRITER_CODE}: the {IC_SERIES_FILENAME!r} payload "
            f"names node {source.node_id!r} but is written for node "
            f"{node_id!r}; a node's artifact directory holds one node's "
            "series, and a series filed under another's address is a "
            "misfiling every later reader would trust"
        )
    return source.ic_series


def _turnover_of(source: object, *, node_id: str) -> dict[str, float]:
    """The turnover payload's pair, as the evaluator renders it.

    The payload carries the ``(returns, metrics)`` pair the evaluator's
    own renderer takes, and the rendering is that renderer's —
    :func:`evaluator.render_turnover_series`, called rather than
    restated, because the per-date turnover arithmetic (which dates have
    predecessors, which symbols entered or exited the panel) is the
    evaluator's to keep single.  The pair must name the node being
    written; the renderer's own node-agreement check covers the two
    records against each other.
    """
    if (
        not isinstance(source, tuple)
        or len(source) != 2
        or not isinstance(source[0], PostCostReturns)
        or not isinstance(source[1], NodeMetrics)
    ):
        raise ArtifactWriterError(
            f"{ARTIFACT_WRITER_CODE}: a {TURNOVER_SERIES_FILENAME!r} "
            f"payload carries the evaluator's (returns, metrics) pair — "
            f"got {type(source).__name__}; the turnover is rendered from "
            "the priced panel and the horizon its metrics measured over, "
            "and a source holding neither is a series no book turned over"
        )
    returns, metrics = source
    for record, record_of in ((returns, "returns"), (metrics, "metrics")):
        if record.node_id != node_id:
            raise ArtifactWriterError(
                f"{ARTIFACT_WRITER_CODE}: the {TURNOVER_SERIES_FILENAME!r} "
                f"payload's {record_of} name node {record.node_id!r} but "
                f"are written for node {node_id!r}; a node's artifact "
                "directory holds one node's turnover, and a series filed "
                "under another's address is a misfiling every later "
                "reader would trust"
            )
    return render_turnover_series(returns, metrics)
