"""Feature 57's persistence: the two regime metrics as feature-store records.

app_spec.xml, "Point-in-Time Feature Store", feature 57: *System computes
mean pairwise correlation of the top 50 symbols plus breadth above an N-day
moving average, persisting both.*  The computation lives in :mod:`regime`;
this module is the *persisting* half of that sentence — it turns the two
computed numbers into feature-store records and reads them back.

Both metrics are market-wide (they describe the market as a whole, not one
instrument), so both are stored under the market-wide sentinel symbol with
the daily frequency — feature 48's five-component key admits no
four-component keys, and a cross-sectional reduction is still keyed *with* a
symbol, carrying the sentinel instead.  The snapshot hash pins which sealed
snapshot's bars the metrics were computed over (feature 48: which immutable
bytes a stored feature was computed over), so a replay that opens a different
snapshot reads a different pair of records, never this one's.

The payload is opaque ``bytes`` — the feature-store's contract (feature 48):
interpretation is the payload layer's, identity is the key's.  Here the
payload is a small, self-describing JSON envelope (stdlib ``json``, so no
dependency the replay path must resolve); a metric round-trips losslessly
through :func:`encode_correlation`/:func:`decode_correlation` and
:func:`encode_breadth`/:func:`decode_breadth`, provenance (the top-N, the
overlap floor, the breadth window) included.

:mod:`regime` owns *what the market did*; feature 40 owns *which symbols were
tradable*; this module owns *storing what was computed*.  It never builds a
panel or ranks a universe — it takes an already-computed
:class:`~feature_store.regime.RegimeMetrics` and persists it, so the three
boundaries never blur.
"""

from __future__ import annotations

import json
from typing import Optional

from .keys import (
    MARKET_WIDE_SYMBOL,
    FeatureKey,
    Frequency,
)
from .store import FeatureRecord, FeatureStore
from .regime import BreadthResult, CorrelationResult, RegimeMetrics
from .store import FeatureStore

__all__ = [
    "FEATURE_NAME_BREADTH",
    "FEATURE_NAME_CORRELATION",
    "FEATURE_VERSION",
    "IncompleteRegimeMetricsError",
    "RegimeFeatureStore",
    "decode_breadth",
    "decode_correlation",
    "encode_breadth",
    "encode_correlation",
]


# The two feature definitions, as the store addresses them.  The name is the
# definition; the snapshot hash is which sealed bars it was computed over; the
# top-N and the breadth window are definition parameters carried in version 1.
#: feature_name of the mean pairwise correlation record.
FEATURE_NAME_CORRELATION = "mean_pairwise_correlation"
#: feature_name of the breadth-above-moving-average record.
FEATURE_NAME_BREADTH = "breadth_above_moving_average"
#: feature_version of both records — a changed definition bumps this (feature 53).
FEATURE_VERSION = "1"


class IncompleteRegimeMetricsError(KeyError):
    """Exactly one of the two regime metrics was stored for a snapshot.

    The two metrics are persisted as a pair for a snapshot; finding only one
    under a snapshot hash means a persist was interrupted between the two
    writes — a state no reader should have to paper over, so it is raised
    rather than returned as half a :class:`RegimeMetrics`.
    """


def _feature_key(feature_name: str, snapshot_hash: str) -> FeatureKey:
    """The market-wide, daily key for ``feature_name`` at ``snapshot_hash``."""
    return FeatureKey(
        feature_name=feature_name,
        feature_version=FEATURE_VERSION,
        snapshot_hash=snapshot_hash,
        symbol=MARKET_WIDE_SYMBOL,
        frequency=Frequency.D1,
    )


# ---------------------------------------------------------------------------
# Payload encode/decode (the opaque-bytes half of feature 48's contract)
# ---------------------------------------------------------------------------


def encode_correlation(result: CorrelationResult, *, top_n: int) -> bytes:
    """Encode a correlation result to its opaque payload.

    A deterministic JSON envelope: sorted keys, no incidental whitespace, so
    the same result always yields byte-identical payload — the replay path
    compares payloads, and a nondeterministic encoding would flake on it.
    ``top_n`` travels with the number so a reader knows how many universe
    members the average was taken over.
    """
    envelope = {
        "feature": FEATURE_NAME_CORRELATION,
        "version": FEATURE_VERSION,
        "top_n": top_n,
        "min_overlap": result.min_overlap,
        "pairs": result.pairs,
        "mean": result.mean,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_correlation(payload: bytes) -> CorrelationResult:
    """Reconstruct the correlation result :func:`encode_correlation` wrote."""
    envelope = json.loads(payload)
    if envelope.get("feature") != FEATURE_NAME_CORRELATION:
        raise ValueError(
            f"correlation payload must name {FEATURE_NAME_CORRELATION!r}; "
            f"got {envelope.get('feature')!r}"
        )
    return CorrelationResult(
        mean=float(envelope["mean"]),
        pairs=int(envelope["pairs"]),
        min_overlap=int(envelope["min_overlap"]),
    )


def encode_breadth(result: BreadthResult, *, top_n: int) -> bytes:
    """Encode a breadth result to its opaque payload.

    Same deterministic envelope discipline as :func:`encode_correlation`;
    ``window`` records the N-day moving-average lookback the count used.
    """
    envelope = {
        "feature": FEATURE_NAME_BREADTH,
        "version": FEATURE_VERSION,
        "top_n": top_n,
        "window": result.window,
        "count": result.count,
        "above": result.above,
        "total": result.total,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_breadth(payload: bytes) -> BreadthResult:
    """Reconstruct the breadth result :func:`encode_breadth` wrote."""
    envelope = json.loads(payload)
    if envelope.get("feature") != FEATURE_NAME_BREADTH:
        raise ValueError(
            f"breadth payload must name {FEATURE_NAME_BREADTH!r}; "
            f"got {envelope.get('feature')!r}"
        )
    return BreadthResult(
        count=int(envelope["count"]),
        above=int(envelope["above"]),
        total=int(envelope["total"]),
        window=int(envelope["window"]),
    )


# ---------------------------------------------------------------------------
# The persistence surface
# ---------------------------------------------------------------------------


class RegimeFeatureStore:
    """Persists and reads feature 57's two metrics through a feature store.

    A thin wrapper over a :class:`FeatureStore`: it supplies the two
    market-wide, daily keys, encodes each metric to its opaque payload, and
    hands the put/get to the underlying store, which enforces feature 48's
    identity contract.  It owns no store of its own — the store is composed
    once (feature 48) and this borrows it — so there is exactly one surface on
    which a regime metric is written or read.
    """

    def __init__(self, store: FeatureStore) -> None:
        # Duck-typed rather than ``isinstance(store, FeatureStore)`` on purpose:
        # the application factory imports each member package under a scan
        # alias (``_nullius_scanned_feature_store``, see ``app.module_loader``),
        # so the composed ``feature-store`` component is *structurally* a
        # FeatureStore but never the same module object a direct import yields.
        # A strict isinstance here would reject the legitimate case of wrapping
        # the composed component — so this checks for the put/get surface the
        # wrapper actually uses, and fails loudly only on a grossly wrong object.
        if not (
            callable(getattr(store, "put", None))
            and callable(getattr(store, "get", None))
        ):
            raise TypeError(
                "RegimeFeatureStore wraps a feature store exposing put()/get(); "
                f"got {type(store).__name__}"
            )
        self._store = store

    # -- Keys ---------------------------------------------------------------

    @staticmethod
    def correlation_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the correlation record at ``snapshot_hash``."""
        return _feature_key(FEATURE_NAME_CORRELATION, snapshot_hash)

    @staticmethod
    def breadth_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the breadth record at ``snapshot_hash``."""
        return _feature_key(FEATURE_NAME_BREADTH, snapshot_hash)

    # -- Writing ------------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        metrics: RegimeMetrics,
        *,
        top_n: int,
    ) -> tuple[FeatureKey, FeatureKey]:
        """Store both metrics for ``snapshot_hash``; return their two keys.

        Writes the correlation then the breadth, each under its own
        market-wide daily key.  The store raises
        :class:`~feature_store.store.DuplicateFeatureKeyError` if either key
        is already present — re-persisting a snapshot is a deliberate
        ``replace`` on the underlying store, never a silent default — so a
        second computation of the same snapshot surfaces rather than clobbers.
        """
        correlation_key = self.correlation_key(snapshot_hash)
        breadth_key = self.breadth_key(snapshot_hash)
        self._store.put(
            FeatureRecord(
                key=correlation_key,
                payload=encode_correlation(metrics.correlation, top_n=top_n),
            )
        )
        self._store.put(
            FeatureRecord(
                key=breadth_key,
                payload=encode_breadth(metrics.breadth, top_n=top_n),
            )
        )
        return correlation_key, breadth_key

    # -- Reading ------------------------------------------------------------

    def load_correlation(self, snapshot_hash: str) -> Optional[CorrelationResult]:
        """The stored correlation for ``snapshot_hash``, or ``None`` if absent."""
        record = self._store.get(self.correlation_key(snapshot_hash))
        return None if record is None else decode_correlation(record.payload)

    def load_breadth(self, snapshot_hash: str) -> Optional[BreadthResult]:
        """The stored breadth for ``snapshot_hash``, or ``None`` if absent."""
        record = self._store.get(self.breadth_key(snapshot_hash))
        return None if record is None else decode_breadth(record.payload)

    def load(self, snapshot_hash: str) -> Optional[RegimeMetrics]:
        """Both metrics for ``snapshot_hash``, or ``None`` if neither is stored.

        Reads the two records independently: both present returns the bundled
        :class:`RegimeMetrics`; neither present returns ``None`` (an
        unpersisted snapshot, a normal point-in-time miss); exactly one
        present raises :class:`IncompleteRegimeMetricsError`, because half a
        pair is a persist that was interrupted, not a value to hand back.
        """
        correlation = self.load_correlation(snapshot_hash)
        breadth = self.load_breadth(snapshot_hash)
        if correlation is None and breadth is None:
            return None
        if correlation is None or breadth is None:
            raise IncompleteRegimeMetricsError(
                f"only one of the two regime metrics is stored under "
                f"{snapshot_hash}; the pair must be persisted together"
            )
        return RegimeMetrics(correlation=correlation, breadth=breadth)
