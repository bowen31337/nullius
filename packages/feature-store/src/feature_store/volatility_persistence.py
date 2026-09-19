"""Feature 55's persistence: realized volatility and vol-of-vol as versioned records.

app_spec.xml, "Point-in-Time Feature Store", feature 55: *System computes
multi-horizon realized volatility plus volatility-of-volatility, persisting
each as a versioned regime feature.*  The computation lives in
:mod:`feature_store.volatility`; this module is the *persisting* half — it
turns the two computed values into feature-store records, each under its own
``feature_name`` and each stamped with its ``feature_version``, and reads
them back.

**The version stamp is the point of this module, so it is stated once and
used everywhere.**  ``feature_version`` is a component of feature 48's
five-component key, which makes it part of a stored feature's *identity*:
the stamp is not a field inside the payload, it is a segment of the address.
Two records carrying the same numbers under different versions are therefore
two distinct stored features, and — this is what the stamp buys — a changed
definition lands *beside* the old rows rather than on top of them (feature
53's contract, which this feature's "persisting each as a versioned regime
feature" clause leans on).  Version 1 is the definition computed here: the
annualized root-mean-square over each trailing horizon (squared returns, not
demeaned), the strict trailing window, the rolling 21-day base series, and
the population standard deviation over its trailing 60 observations.  Change
any of those and the version must move with it; changing the version without
changing them would file identical numbers under a second identity, which
the payload's definition block makes checkable rather than a matter of
trust.

Both metrics are market-wide — how far the market moved and how unstable
that movement was describe the market, not one instrument — so both are
keyed with the market-wide sentinel symbol at the daily frequency (feature
48 admits no four-component keys).  The snapshot hash pins which sealed
snapshot's bars they were computed over, so a replay that opens different
bytes reads different records, never these.

The payload is opaque ``bytes`` (feature 48's contract: interpretation is
the payload layer's, identity is the key's).  Here it is a small
self-describing JSON envelope written by stdlib ``json`` with sorted keys
and no incidental whitespace, so the same value always encodes to
byte-identical payload — the replay path compares payloads.

:mod:`feature_store.volatility` owns *what the market did*; feature 40 owns
*which symbols were tradable*; this module owns *storing what was computed,
under which version*.  It never builds a panel or ranks a universe.
"""

from __future__ import annotations

import json

from .keys import MARKET_WIDE_SYMBOL, FeatureKey, Frequency
from .store import FeatureRecord, FeatureStore
from .volatility import (
    ANNUALIZATION_PERIODS,
    DEFAULT_BASE_WINDOW,
    DEFAULT_HORIZONS,
    DEFAULT_VOL_WINDOW,
    RealizedVolatilityResult,
    VolOfVolResult,
    VolatilityMetrics,
)

__all__ = [
    "FEATURE_NAME_REALIZED_VOL",
    "FEATURE_NAME_VOL_OF_VOL",
    "FEATURE_VERSION",
    "REALIZED_VOL_DEFINITION",
    "VOL_OF_VOL_DEFINITION",
    "IncompleteVolatilityMetricsError",
    "VolatilityFeatureStore",
    "decode_realized_volatility",
    "decode_vol_of_vol",
    "definition_parameters",
    "encode_realized_volatility",
    "encode_vol_of_vol",
    "feature_version",
]


#: feature_name of the multi-horizon realized volatility record.
FEATURE_NAME_REALIZED_VOL = "realized_volatility"

#: feature_name of the volatility-of-volatility record.
FEATURE_NAME_VOL_OF_VOL = "volatility_of_volatility"

#: feature_version of both records — the definition as first stated.  A changed
#: definition bumps this and lands under a new key, leaving these rows intact
#: (feature 53); it is never edited in place.
FEATURE_VERSION = "1"

#: The definition each version names, kept beside the version so the stamp is
#: checkable rather than a bare number.  Changing the definition means editing
#: one of these *and* bumping :data:`FEATURE_VERSION` together.
REALIZED_VOL_DEFINITION = (
    "annualized root-mean-square of squared returns over each trailing horizon"
)
VOL_OF_VOL_DEFINITION = (
    "population stddev of trailing annualized base-window realized volatility"
)


def feature_version() -> str:
    """The version stamped on feature 55's records.

    A function rather than only the constant so a caller assembling a key by
    hand and a caller reading the stamp off a record share one spelling.  It
    takes no arguments by design: which version is current is a property of
    the definition that is deployed, not of the call.
    """
    return FEATURE_VERSION


class IncompleteVolatilityMetricsError(KeyError):
    """Exactly one of feature 55's two metrics was stored for a snapshot.

    The two are persisted as a pair for a snapshot; finding only one under a
    snapshot hash means a persist was interrupted between the two writes — a
    state no reader should have to paper over, so it is raised rather than
    returned as half a :class:`VolatilityMetrics`.
    """


def _feature_key(feature_name: str, snapshot_hash: str) -> FeatureKey:
    """The market-wide, daily key for ``feature_name`` at ``snapshot_hash``.

    The stamp is the ``feature_version`` component — the same string the
    payload carries, so the address and the envelope cannot disagree about
    which definition produced the row.
    """
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


def _envelope(body: dict) -> bytes:
    """Serialize an envelope deterministically: sorted keys, no whitespace."""
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encode_realized_volatility(
    result: RealizedVolatilityResult, *, top_n: int
) -> bytes:
    """Encode a realized-volatility result to its opaque payload, version stamped.

    The envelope names the feature, the ``feature_version`` the record is
    stored under, the universe size it was computed over (``top_n``), the
    definition in words, and the numbers with the sample behind them.  The
    horizons and their volatilities travel as parallel lists and the
    ``annualization`` records the units, so a reader with only the payload —
    the key not shown — can tell which definition it is looking at and at
    what scale, without assuming the default horizon set.
    """
    return _envelope(
        {
            "definition": REALIZED_VOL_DEFINITION,
            "feature": FEATURE_NAME_REALIZED_VOL,
            "version": FEATURE_VERSION,
            "top_n": top_n,
            "horizons": list(result.horizons),
            "volatilities": list(result.volatilities),
            "observations": list(result.observations),
            "annualization": result.annualization,
        }
    )


def decode_realized_volatility(payload: bytes) -> RealizedVolatilityResult:
    """Reconstruct the result :func:`encode_realized_volatility` wrote."""
    envelope = json.loads(payload)
    _require_feature(envelope, FEATURE_NAME_REALIZED_VOL)
    return RealizedVolatilityResult(
        horizons=tuple(int(horizon) for horizon in envelope["horizons"]),
        volatilities=tuple(
            float(value) for value in envelope["volatilities"]
        ),
        observations=tuple(int(value) for value in envelope["observations"]),
        annualization=float(envelope["annualization"]),
    )


def encode_vol_of_vol(result: VolOfVolResult, *, top_n: int) -> bytes:
    """Encode a vol-of-vol result to its opaque payload, version stamped.

    Same deterministic envelope discipline as
    :func:`encode_realized_volatility`.  The base window and the vol window
    travel with the number, so the instability is self-describing about
    which series of vols it was taken over — a reader never has to assume
    the defaults.
    """
    return _envelope(
        {
            "definition": VOL_OF_VOL_DEFINITION,
            "feature": FEATURE_NAME_VOL_OF_VOL,
            "version": FEATURE_VERSION,
            "top_n": top_n,
            "vol_of_vol": result.vol_of_vol,
            "mean_vol": result.mean_vol,
            "n": result.n,
            "base_window": result.base_window,
            "window": result.window,
            "annualization": result.annualization,
        }
    )


def decode_vol_of_vol(payload: bytes) -> VolOfVolResult:
    """Reconstruct the result :func:`encode_vol_of_vol` wrote."""
    envelope = json.loads(payload)
    _require_feature(envelope, FEATURE_NAME_VOL_OF_VOL)
    return VolOfVolResult(
        vol_of_vol=float(envelope["vol_of_vol"]),
        mean_vol=float(envelope["mean_vol"]),
        n=int(envelope["n"]),
        base_window=int(envelope["base_window"]),
        window=int(envelope["window"]),
        annualization=float(envelope["annualization"]),
    )


def _require_feature(envelope: dict, expected: str) -> None:
    """Refuse a payload that names a different feature or a later version."""
    if envelope.get("feature") != expected:
        raise ValueError(
            f"{expected} payload must name {expected!r}; "
            f"got {envelope.get('feature')!r}"
        )
    stamped = envelope.get("version")
    if stamped != FEATURE_VERSION:
        raise ValueError(
            f"{expected} payload is stamped version {stamped!r}, but this "
            f"reader decodes version {FEATURE_VERSION!r}; a version bump is a "
            "different stored feature, not a payload this decoder reinterprets"
        )


# ---------------------------------------------------------------------------
# The persistence surface
# ---------------------------------------------------------------------------


class VolatilityFeatureStore:
    """Persists and reads feature 55's two metrics through a feature store.

    A thin wrapper over a :class:`FeatureStore`: it supplies the two
    market-wide, daily keys at the current ``feature_version``, encodes each
    metric to its opaque payload, and hands the put/get to the underlying
    store, which enforces feature 48's identity contract.  It owns no store
    of its own — the store is composed once (feature 48) and this borrows it
    — so there is exactly one surface on which a volatility metric is written
    or read.
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
                "VolatilityFeatureStore wraps a feature store exposing "
                f"put()/get(); got {type(store).__name__}"
            )
        self._store = store

    # -- Keys ---------------------------------------------------------------

    @staticmethod
    def realized_vol_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the realized-vol record at ``snapshot_hash``."""
        return _feature_key(FEATURE_NAME_REALIZED_VOL, snapshot_hash)

    @staticmethod
    def vol_of_vol_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the vol-of-vol record at ``snapshot_hash``."""
        return _feature_key(FEATURE_NAME_VOL_OF_VOL, snapshot_hash)

    # -- Writing ------------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        metrics: VolatilityMetrics,
        *,
        top_n: int,
        replace: bool = False,
    ) -> tuple[FeatureKey, FeatureKey]:
        """Store both metrics for ``snapshot_hash``; return their two keys.

        Writes the realized volatility then the vol-of-vol, each under its own
        market-wide daily key at the current ``feature_version`` — "persisting
        each as a versioned regime feature" means two records, two names, one
        stamp.  Both keys carry the stamp, so a later definition writes beside
        these rows rather than over them.

        ``replace`` defaults to ``False``: re-persisting an identical key is an
        error (:class:`~feature_store.store.DuplicateFeatureKeyError`) rather
        than a silent clobber, because an exact-key collision almost always
        means two writers believe they computed the same thing.  A caller that
        deliberately recomputes passes ``replace=True``.
        """
        realized_key = self.realized_vol_key(snapshot_hash)
        vol_of_vol_key = self.vol_of_vol_key(snapshot_hash)
        self._store.put(
            FeatureRecord(
                key=realized_key,
                payload=encode_realized_volatility(
                    metrics.realized, top_n=top_n
                ),
            ),
            replace=replace,
        )
        self._store.put(
            FeatureRecord(
                key=vol_of_vol_key,
                payload=encode_vol_of_vol(
                    metrics.vol_of_vol, top_n=top_n
                ),
            ),
            replace=replace,
        )
        return realized_key, vol_of_vol_key

    # -- Reading ------------------------------------------------------------

    def load_realized_volatility(
        self, snapshot_hash: str
    ) -> RealizedVolatilityResult | None:
        """The stored realized volatility for ``snapshot_hash``, or ``None``."""
        record = self._store.get(self.realized_vol_key(snapshot_hash))
        return None if record is None else decode_realized_volatility(record.payload)

    def load_vol_of_vol(self, snapshot_hash: str) -> VolOfVolResult | None:
        """The stored vol-of-vol for ``snapshot_hash``, or ``None`` if absent."""
        record = self._store.get(self.vol_of_vol_key(snapshot_hash))
        return None if record is None else decode_vol_of_vol(record.payload)

    def load(self, snapshot_hash: str) -> VolatilityMetrics | None:
        """Both metrics for ``snapshot_hash``, or ``None`` if neither is stored.

        Reads the two records independently: both present returns the bundled
        :class:`VolatilityMetrics`; neither present returns ``None`` (an
        unpersisted snapshot, a normal point-in-time miss); exactly one
        present raises :class:`IncompleteVolatilityMetricsError`, because half
        a pair is a persist that was interrupted, not a value to hand back.
        """
        realized = self.load_realized_volatility(snapshot_hash)
        vol_of_vol = self.load_vol_of_vol(snapshot_hash)
        if realized is None and vol_of_vol is None:
            return None
        if realized is None or vol_of_vol is None:
            raise IncompleteVolatilityMetricsError(
                f"only one of feature 55's two metrics is stored under "
                f"{snapshot_hash}; the pair must be persisted together"
            )
        return VolatilityMetrics(realized=realized, vol_of_vol=vol_of_vol)


def definition_parameters() -> dict[str, object]:
    """The defaults the version-1 definition is stated in.

    Exposed so a caller can record, assert or log *what* version 1 means
    without importing the computation module — the stamp and the definition it
    names stay one lookup apart.
    """
    return {
        "feature_version": FEATURE_VERSION,
        "realized_volatility": REALIZED_VOL_DEFINITION,
        "volatility_of_volatility": VOL_OF_VOL_DEFINITION,
        "horizons": list(DEFAULT_HORIZONS),
        "base_window": DEFAULT_BASE_WINDOW,
        "vol_window": DEFAULT_VOL_WINDOW,
        "annualization": ANNUALIZATION_PERIODS,
    }
