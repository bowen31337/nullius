"""Feature 58's persistence: market-regime labels as versioned records.

app_spec.xml, "Point-in-Time Feature Store", feature 58: *System labels
market regimes using a rolling-window fit only, which rejects any labeler
configured to fit over full history.*  The labelling lives in
:mod:`feature_store.regime_labeler`; this module is the *persisting* half — it
turns the per-date labels into feature-store records, stamping each with its
``feature_version``, and reads them back.

**The version stamp is the point of this module, so it is stated once and
used everywhere.**  ``feature_version`` is a component of feature 48's
five-component key, which makes it part of a stored feature's *identity*:
the stamp is not a field inside the payload, it is a segment of the address.
Two records carrying the same labels under different versions are therefore
two distinct stored features, and — this is what the stamp buys — a changed
definition lands *beside* the old rows rather than on top of them (feature
53's contract).  Version 1 is the definition computed here: the k-means over
the four feature-55 features (multi-horizon rolling realized volatility plus
rolling vol-of-vol), the causal within-window standardization, the trailing
fit window and the three-regime default.  Change any of those and the version
must move with it; changing the version without changing them would file
identical labels under a second identity, which the payload's definition block
makes checkable rather than a matter of trust.

The record is market-wide — a single label per date describes the *market's*
regime, not one instrument's — so it is keyed with the market-wide sentinel
symbol at the daily frequency (feature 48 admits no four-component keys).  The
snapshot hash pins which sealed snapshot's bars the labels were computed over,
so a replay that opens different bytes reads different records, never these.

The payload is opaque ``bytes`` (feature 48's contract: interpretation is the
payload layer's, identity is the key's).  Here it is a small self-describing
JSON envelope written by stdlib ``json`` with sorted keys and no incidental
whitespace, so the same value always encodes to byte-identical payload — the
replay path compares payloads.  The labels travel as a list aligned to the
return-axis dates, with ``null`` where no label was produced (un-computable
features, or not yet a full window of history), so the decoder reconstructs
the exact alignment.

:mod:`feature_store.regime_labeler` owns *what regime each date was in*;
feature 40 owns *which symbols were tradable*; this module owns *storing what
was computed, under which version*.  It never builds a panel, ranks a universe
or fits a model.
"""

from __future__ import annotations

import datetime as dt
import json

from .keys import MARKET_WIDE_SYMBOL, FeatureKey, Frequency
from .regime_labeler import RegimeLabels
from .store import FeatureRecord, FeatureStore

__all__ = [
    "FEATURE_NAME_LABELS",
    "FEATURE_VERSION",
    "LABELS_DEFINITION",
    "RegimeLabelerFeatureStore",
    "decode_labels",
    "definition_parameters",
    "encode_labels",
    "feature_version",
]


#: feature_name of the market-regime-labels record.
FEATURE_NAME_LABELS = "market_regime_labels"

#: feature_version of the record — the definition as first stated.  A changed
#: definition bumps this and lands under a new key, leaving these rows intact
#: (feature 53); it is never edited in place.
FEATURE_VERSION = "1"

#: The definition the version names, kept beside the version so the stamp is
#: checkable rather than a bare number.  Changing the definition means editing
#: this *and* bumping :data:`FEATURE_VERSION` together.
LABELS_DEFINITION = (
    "k-means over rolling realized-volatility and vol-of-vol features, fit on "
    "a trailing window only"
)


def feature_version() -> str:
    """The version stamped on feature 58's record.

    A function rather than only the constant so a caller assembling a key by
    hand and a caller reading the stamp off a record share one spelling.  It
    takes no arguments by design: which version is current is a property of
    the definition that is deployed, not of the call.
    """
    return FEATURE_VERSION


class IncompleteLabelerMetricsError(KeyError):
    """The labels record for a snapshot was stored with a mismatched shape.

    A stored labels payload that does not decode to the same number of labels
    as dates means the persist wrote a malformed envelope — a state no reader
    should have to paper over, so it is raised rather than returned as a
    misaligned :class:`RegimeLabels`.
    """


def _feature_key(snapshot_hash: str) -> FeatureKey:
    """The market-wide, daily key of the labels record at ``snapshot_hash``.

    The stamp is the ``feature_version`` component — the same string the
    payload carries, so the address and the envelope cannot disagree about
    which definition produced the row.
    """
    return FeatureKey(
        feature_name=FEATURE_NAME_LABELS,
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


def encode_labels(labels: RegimeLabels, *, top_n: int) -> bytes:
    """Encode a labels result to its opaque payload, version stamped.

    The envelope names the feature, the ``feature_version`` the record is
    stored under, the universe size it was computed over (``top_n``), the
    definition in words, and the fit parameters (``k``, ``window``) with the
    labels themselves — ``null`` where no label was produced — aligned to the
    return-axis dates.  A reader with only the payload — the key not shown —
    can therefore tell which definition it is looking at and how each date was
    labelled.
    """
    return _envelope(
        {
            "definition": LABELS_DEFINITION,
            "feature": FEATURE_NAME_LABELS,
            "version": FEATURE_VERSION,
            "top_n": top_n,
            "k": labels.k,
            "window": labels.window,
            "dates": [date.isoformat() for date in labels.dates],
            "labels": labels.labels,
            "n_labeled": labels.n_labeled,
        }
    )


def decode_labels(payload: bytes) -> RegimeLabels:
    """Reconstruct the labels result :func:`encode_labels` wrote."""
    import datetime as dt

    envelope = json.loads(payload)
    _require_feature(envelope)
    dates = [dt.date.fromisoformat(value) for value in envelope["dates"]]
    labels = tuple(
        None if value is None else int(value) for value in envelope["labels"]
    )
    if len(labels) != len(dates):
        raise IncompleteLabelerMetricsError(
            f"{FEATURE_NAME_LABELS} payload carries {len(labels)} labels but "
            f"{len(dates)} dates; the pair must be aligned"
        )
    return RegimeLabels(
        dates=tuple(dates),
        labels=labels,
        k=int(envelope["k"]),
        window=int(envelope["window"]),
        n_labeled=int(envelope["n_labeled"]),
    )


def _require_feature(envelope: dict) -> None:
    """Refuse a payload that names a different feature or a later version."""
    if envelope.get("feature") != FEATURE_NAME_LABELS:
        raise ValueError(
            f"{FEATURE_NAME_LABELS} payload must name "
            f"{FEATURE_NAME_LABELS!r}; got {envelope.get('feature')!r}"
        )
    stamped = envelope.get("version")
    if stamped != FEATURE_VERSION:
        raise ValueError(
            f"{FEATURE_NAME_LABELS} payload is stamped version {stamped!r}, but "
            f"this reader decodes version {FEATURE_VERSION!r}; a version bump "
            "is a different stored feature, not a payload this decoder "
            "reinterprets"
        )


# ---------------------------------------------------------------------------
# The persistence surface
# ---------------------------------------------------------------------------


class RegimeLabelerFeatureStore:
    """Persists and reads feature 58's labels through a feature store.

    A thin wrapper over a :class:`FeatureStore`: it supplies the market-wide,
    daily key at the current ``feature_version``, encodes the labels to their
    opaque payload, and hands the put/get to the underlying store, which
    enforces feature 48's identity contract.  It owns no store of its own —
    the store is composed once (feature 48) and this borrows it — so there is
    exactly one surface on which the labels are written or read.
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
                "RegimeLabelerFeatureStore wraps a feature store exposing "
                f"put()/get(); got {type(store).__name__}"
            )
        self._store = store

    # -- Keys ---------------------------------------------------------------

    @staticmethod
    def labels_key(snapshot_hash: str) -> FeatureKey:
        """The feature-store key of the labels record at ``snapshot_hash``."""
        return _feature_key(snapshot_hash)

    # -- Writing ------------------------------------------------------------

    def persist(
        self,
        snapshot_hash: str,
        labels: RegimeLabels,
        *,
        top_n: int,
        replace: bool = False,
    ) -> FeatureKey:
        """Store the labels for ``snapshot_hash``; return their key.

        Writes the one market-wide labels record at the current
        ``feature_version``.  The key carries the stamp, so a later definition
        writes beside these rows rather than over them.

        ``replace`` defaults to ``False``: re-persisting an identical key is an
        error (:class:`~feature_store.store.DuplicateFeatureKeyError`) rather
        than a silent clobber, because an exact-key collision almost always
        means two writers believe they computed the same thing.  A caller that
        deliberately recomputes passes ``replace=True``.
        """
        labels_key = self.labels_key(snapshot_hash)
        self._store.put(
            FeatureRecord(
                key=labels_key,
                payload=encode_labels(labels, top_n=top_n),
            ),
            replace=replace,
        )
        return labels_key

    # -- Reading ------------------------------------------------------------

    def load(self, snapshot_hash: str) -> RegimeLabels | None:
        """The stored labels for ``snapshot_hash``, or ``None`` if absent.

        A normal point-in-time miss — an unpersisted snapshot — returns
        ``None``; the labels are a single record, so there is no exactly-one-of
        -a-pair case to raise on.
        """
        record = self._store.get(self.labels_key(snapshot_hash))
        return None if record is None else decode_labels(record.payload)


def definition_parameters() -> dict[str, object]:
    """The defaults the version-1 definition is stated in.

    Exposed so a caller can record, assert or log *what* version 1 means
    without importing the computation module — the stamp and the definition it
    names stay one lookup apart.
    """
    from .regime_labeler import DEFAULT_K, DEFAULT_WINDOW

    return {
        "feature_version": FEATURE_VERSION,
        "labels": LABELS_DEFINITION,
        "k": DEFAULT_K,
        "window": DEFAULT_WINDOW,
    }
