"""Feature 56's persistence: dispersion and autocorrelation as versioned records.

app_spec.xml, "Point-in-Time Feature Store", feature 56: *System computes
cross-sectional return dispersion plus return autocorrelation at several
lags, persisting them with feature_version stamps.*  The computation lives in
:mod:`feature_store.dispersion`; this module is the *persisting* half — it
turns the two computed values into feature-store records, stamping each with
its ``feature_version``, and reads them back.

**The version stamp is the point of this module, so it is stated once and
used everywhere.**  ``feature_version`` is a component of feature 48's
five-component key, which makes it part of a stored feature's *identity*: the
stamp is not a field inside the payload, it is a segment of the address.  Two
records carrying the same numbers under different versions are therefore two
distinct stored features, and — this is what the stamp buys — a changed
definition lands *beside* the old rows rather than on top of them (feature
53's contract, which this feature's "persisting them with feature_version
stamps" clause leans on).  Version 1 is the definition computed here: the
population-standard-deviation dispersion, the equal-weighted market return,
the pairwise-complete Pearson coefficient, the default lag set.  Change any of
those and the version must move with it; changing the version without changing
them would file identical numbers under a second identity, which the payload's
``parameters`` block makes checkable rather than a matter of trust.

Both metrics are market-wide — a cross-section's width and the market's memory
describe the market, not one instrument — so both are keyed with the
market-wide sentinel symbol at the daily frequency (feature 48 admits no
four-component keys).  The snapshot hash pins which sealed snapshot's bars
they were computed over, so a replay that opens different bytes reads
different records, never these.

The payload is opaque ``bytes`` (feature 48's contract: interpretation is the
payload layer's, identity is the key's).  Here it is a small self-describing
JSON envelope written by stdlib ``json`` with sorted keys and no incidental
whitespace, so the same value always encodes to byte-identical payload — the
replay path compares payloads.

:mod:`feature_store.dispersion` owns *what the market did*; feature 40 owns
*which symbols were tradable*; this module owns *storing what was computed,
under which version*.  It never builds a panel or ranks a universe.
"""

from __future__ import annotations

import json

from .dispersion import (
    DEFAULT_LAGS,
    DEFAULT_MIN_OBSERVATIONS,
    DEFAULT_MIN_SYMBOLS,
    AutocorrelationResult,
    DispersionMetrics,
    DispersionResult,
)
from .keys import MARKET_WIDE_SYMBOL, FeatureKey, Frequency
from .store import FeatureRecord, FeatureStore

__all__ = [
    "AUTOCORRELATION_DEFINITION",
    "DISPERSION_DEFINITION",
    "FEATURE_NAME_AUTOCORRELATION",
    "FEATURE_NAME_DISPERSION",
    "FEATURE_VERSION",
    "DispersionFeatureStore",
    "IncompleteDispersionMetricsError",
    "decode_autocorrelation",
    "decode_dispersion",
    "encode_autocorrelation",
    "encode_dispersion",
    "feature_version",
]


#: feature_name of the cross-sectional return dispersion record.
FEATURE_NAME_DISPERSION = "cross_sectional_dispersion"
#: feature_name of the several-lag return autocorrelation record.
FEATURE_NAME_AUTOCORRELATION = "return_autocorrelation"

#: feature_version of both records — the definition as first stated.  A changed
#: definition bumps this and lands under a new key, leaving these rows intact
#: (feature 53); it is never edited in place.
FEATURE_VERSION = "1"

#: The definition each version names, kept beside the version so the stamp is
#: checkable rather than a bare number.  Changing the definition means editing
#: one of these *and* bumping :data:`FEATURE_VERSION` together.
DISPERSION_DEFINITION = "population-stddev of latest log returns"
AUTOCORRELATION_DEFINITION = "pairwise-complete Pearson of equal-weighted market returns"


def feature_version() -> str:
    """The version stamped on feature 56's records.

    A function rather than only the constant so a caller assembling a key by
    hand and a caller reading the stamp off a record share one spelling.  It
    takes no arguments by design: which version is current is a property of
    the definition that is deployed, not of the call.
    """
    return FEATURE_VERSION


class IncompleteDispersionMetricsError(KeyError):
    """Exactly one of feature 56's two metrics was stored for a snapshot.

    The two are persisted as a pair for a snapshot; finding only one under a
    snapshot hash means a persist was interrupted between the two writes — a
    state no reader should have to paper over, so it is raised rather than
    returned as half a :class:`DispersionMetrics`.
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


def _envelope(feature: str, body: dict) -> bytes:
    """Serialize an envelope deterministically: sorted keys, no whitespace."""
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encode_dispersion(result: DispersionResult, *, top_n: int) -> bytes:
    """Encode a dispersion result to its opaque payload, version stamped.

    The envelope names the feature, the ``feature_version`` the record is
    stored under, the universe size it was computed over (``top_n``), the
    definition in words, and the number with the cross-section that produced
    it (``n``, ``mean_return``).  A reader with only the payload — the key not
    shown — can therefore tell which definition it is looking at.
    """
    return _envelope(
        FEATURE_NAME_DISPERSION,
        {
            "definition": DISPERSION_DEFINITION,
            "feature": FEATURE_NAME_DISPERSION,
            "version": FEATURE_VERSION,
            "top_n": top_n,
            "n": result.n,
            "mean_return": result.mean_return,
            "dispersion": result.dispersion,
        },
    )


def decode_dispersion(payload: bytes) -> DispersionResult:
    """Reconstruct the dispersion result :func:`encode_dispersion` wrote."""
    envelope = json.loads(payload)
    _require_feature(envelope, FEATURE_NAME_DISPERSION)
    return DispersionResult(
        dispersion=float(envelope["dispersion"]),
        mean_return=float(envelope["mean_return"]),
        n=int(envelope["n"]),
    )


def encode_autocorrelation(
    result: AutocorrelationResult, *, top_n: int
) -> bytes:
    """Encode an autocorrelation result to its opaque payload, version stamped.

    Same deterministic envelope discipline as :func:`encode_dispersion`.  The
    lags and their coefficients travel as parallel lists, so the payload is
    self-describing about *which* lags were computed — a reader never has to
    assume the default set.
    """
    return _envelope(
        FEATURE_NAME_AUTOCORRELATION,
        {
            "definition": AUTOCORRELATION_DEFINITION,
            "feature": FEATURE_NAME_AUTOCORRELATION,
            "version": FEATURE_VERSION,
            "top_n": top_n,
            "lags": list(result.lags),
            "coefficients": list(result.coefficients),
            "observations": list(result.observations),
            "min_observations": result.min_observations,
        },
    )


def decode_autocorrelation(payload: bytes) -> AutocorrelationResult:
    """Reconstruct the autocorrelation result :func:`encode_autocorrelation` wrote."""
    envelope = json.loads(payload)
    _require_feature(envelope, FEATURE_NAME_AUTOCORRELATION)
    return AutocorrelationResult(
        lags=tuple(int(lag) for lag in envelope["lags"]),
        coefficients=tuple(float(value) for value in envelope["coefficients"]),
        observations=tuple(int(value) for value in envelope["observations"]),
        min_observations=int(envelope["min_observations"]),
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


class DispersionFeatureStore:
    """Persists and reads feature 56's two metrics through a feature store.

    A thin wrapper over a :class:`FeatureStore`: it supplies the two
    market-wide, daily keys at the current ``feature_version``, encodes each
    metric to its opaque payload, and hands the put/get to the underlying
    store, which enforces feature 48's identity contract.  It owns no store of
    its own — the store is composed once (feature 48) and this borrows it — so
    there is exactly one surface on which a dispersion metric is written or
    read.
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
                "DispersionFeatureStore wraps a feature store exposing "
                f"put()/get(); got {type(store).__name__}"
            )
        self._store = store

    # -- Keys ---------------------------------------------------------------

    @staticmethod
    def dispersion_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the dispersion record at ``snapshot_hash``."""
        return _feature_key(FEATURE_NAME_DISPERSION, snapshot_hash)

    @staticmethod
    def autocorrelation_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the autocorrelation record at ``snapshot_hash``."""
        return _feature_key(FEATURE_NAME_AUTOCORRELATION, snapshot_hash)

    # -- Writing ------------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        metrics: DispersionMetrics,
        *,
        top_n: int,
        replace: bool = False,
    ) -> tuple[FeatureKey, FeatureKey]:
        """Store both metrics for ``snapshot_hash``; return their two keys.

        Writes the dispersion then the autocorrelation, each under its own
        market-wide daily key at the current ``feature_version``.  Both keys
        carry the stamp, so a later definition writes beside these rows rather
        than over them.

        ``replace`` defaults to ``False``: re-persisting an identical key is an
        error (:class:`~feature_store.store.DuplicateFeatureKeyError`) rather
        than a silent clobber, because an exact-key collision almost always
        means two writers believe they computed the same thing.  A caller that
        deliberately recomputes passes ``replace=True``.
        """
        dispersion_key = self.dispersion_key(snapshot_hash)
        autocorrelation_key = self.autocorrelation_key(snapshot_hash)
        self._store.put(
            FeatureRecord(
                key=dispersion_key,
                payload=encode_dispersion(metrics.dispersion, top_n=top_n),
            ),
            replace=replace,
        )
        self._store.put(
            FeatureRecord(
                key=autocorrelation_key,
                payload=encode_autocorrelation(
                    metrics.autocorrelation, top_n=top_n
                ),
            ),
            replace=replace,
        )
        return dispersion_key, autocorrelation_key

    # -- Reading ------------------------------------------------------------

    def load_dispersion(self, snapshot_hash: str) -> DispersionResult | None:
        """The stored dispersion for ``snapshot_hash``, or ``None`` if absent."""
        record = self._store.get(self.dispersion_key(snapshot_hash))
        return None if record is None else decode_dispersion(record.payload)

    def load_autocorrelation(
        self, snapshot_hash: str
    ) -> AutocorrelationResult | None:
        """The stored autocorrelation for ``snapshot_hash``, or ``None``."""
        record = self._store.get(self.autocorrelation_key(snapshot_hash))
        return None if record is None else decode_autocorrelation(record.payload)

    def load(self, snapshot_hash: str) -> DispersionMetrics | None:
        """Both metrics for ``snapshot_hash``, or ``None`` if neither is stored.

        Reads the two records independently: both present returns the bundled
        :class:`DispersionMetrics`; neither present returns ``None`` (an
        unpersisted snapshot, a normal point-in-time miss); exactly one
        present raises :class:`IncompleteDispersionMetricsError`, because half
        a pair is a persist that was interrupted, not a value to hand back.
        """
        dispersion = self.load_dispersion(snapshot_hash)
        autocorrelation = self.load_autocorrelation(snapshot_hash)
        if dispersion is None and autocorrelation is None:
            return None
        if dispersion is None or autocorrelation is None:
            raise IncompleteDispersionMetricsError(
                f"only one of feature 56's two metrics is stored under "
                f"{snapshot_hash}; the pair must be persisted together"
            )
        return DispersionMetrics(
            dispersion=dispersion, autocorrelation=autocorrelation
        )


def definition_parameters() -> dict[str, object]:
    """The defaults the version-1 definition is stated in.

    Exposed so a caller can record, assert or log *what* version 1 means
    without importing the computation module — the stamp and the definition it
    names stay one lookup apart.
    """
    return {
        "feature_version": FEATURE_VERSION,
        "dispersion": DISPERSION_DEFINITION,
        "autocorrelation": AUTOCORRELATION_DEFINITION,
        "min_symbols": DEFAULT_MIN_SYMBOLS,
        "lags": list(DEFAULT_LAGS),
        "min_observations": DEFAULT_MIN_OBSERVATIONS,
    }
