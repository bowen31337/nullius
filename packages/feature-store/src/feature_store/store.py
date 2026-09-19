"""Feature storage addressed exclusively by the five-component key.

app_spec.xml, "Point-in-Time Feature Store", feature 48: *System keys
every stored feature with feature_name, feature_version, snapshot_hash,
symbol and frequency.*  :class:`FeatureStore` is the read/write surface
of that sentence: a record enters only already carrying a complete,
validated :class:`~feature_store.keys.FeatureKey`, and the only way back
out is under the identical key.

Feature 48 deliberately fixes the *identity* contract and nothing else.
The payload is opaque ``bytes`` — the Parquet representation is feature
49's materialisation contract, and the keying layer must not leak
assumptions about row schema into identity — and the backing store is a
dictionary.  Features 49/50 (lazy Parquet materialisation and caching)
extend this class with a lake-rooted backing and a ``cache_hit`` counter;
the put/get/keys seam below is what they extend, not replace.  Row-level
point-in-time stamping (``computed_as_of``, features 51/52) likewise
lives in the payload layer those features add.

Stdlib-only, like ``keys.py``: import-safe everywhere, replay included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .keys import FeatureKey

__all__ = [
    "DuplicateFeatureKeyError",
    "FeatureRecord",
    "FeatureStore",
]


class DuplicateFeatureKeyError(ValueError):
    """A feature was stored twice under one identical key.

    An exact-key collision almost always means two writers believe they
    computed the same feature independently — the class of bug this
    store exists to surface, not absorb.  Replacing is an explicit
    decision (``put(..., replace=True)``), never a silent default.
    """


@dataclass(frozen=True, slots=True)
class FeatureRecord:
    """One stored feature: its full identity plus an opaque payload.

    ``key`` is the complete five-component identity (feature 48); there is
    no field here that could override or extend it — the key is the
    record's address, full stop.  ``payload`` is uninterpreted bytes:
    empty is allowed (a feature with no rows), interpretation is not
    attempted, and feature 49's Parquet materialisation owns the format.
    """

    key: FeatureKey
    payload: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.key, FeatureKey):
            raise TypeError(
                f"FeatureRecord.key must be a FeatureKey; got {type(self.key).__name__}"
            )
        if not isinstance(self.payload, bytes):
            raise TypeError(
                "FeatureRecord.payload must be bytes (the Parquet "
                f"materialisation contract, feature 49, owns the format); "
                f"got {type(self.payload).__name__}"
            )


class FeatureStore:
    """A feature store whose every entry is keyed by a complete key.

    The invariants, both enforced by construction:

    * **Completeness** — there is no ``put`` overload taking scattered
      name/version/snapshot arguments, and ``get``/``__contains__`` accept
      only a :class:`FeatureKey`.  A feature cannot be stored or fetched
      under a partial identity because no such address exists.
    * **Distinctness** — the mapping key is the whole
      :class:`FeatureKey`, so two features differing in any single
      component are two entries, and writing the *identical* key twice is
      an error (:class:`DuplicateFeatureKeyError`) rather than a
      replacement.

    :meth:`keys` and iteration are sorted by the canonical component
    order, so traversals are deterministic and bit-reproducible — the
    same discipline the universe plugin applies to symbol ordering
    (feature 46).
    """

    def __init__(self) -> None:
        self._records: dict[FeatureKey, FeatureRecord] = {}

    def put(self, record: FeatureRecord, *, replace: bool = False) -> FeatureKey:
        """Store ``record`` under its key and return that key.

        Raises :class:`DuplicateFeatureKeyError` when the exact key is
        already present, unless ``replace=True`` makes the overwrite an
        explicit decision.  A new ``feature_version`` therefore never
        clobbers prior-version rows — it lands under a different key
        entirely (feature 53).
        """
        if not isinstance(record, FeatureRecord):
            raise TypeError(
                f"put expects a FeatureRecord; got {type(record).__name__}"
            )
        existing = self._records.get(record.key)
        if existing is not None and not replace:
            raise DuplicateFeatureKeyError(
                f"a feature is already stored under {record.key}; pass "
                "replace=True to overwrite deliberately"
            )
        self._records[record.key] = record
        return record.key

    def get(self, key: FeatureKey) -> FeatureRecord | None:
        """Return the record stored under exactly ``key``, else ``None``.

        ``key`` must be a :class:`FeatureKey` — partial addressing (by
        name only, say) is not a store operation; it is a query feature
        the category adds later, on top of :meth:`keys`.
        """
        self._require_key(key)
        return self._records.get(key)

    def keys(self) -> tuple[FeatureKey, ...]:
        """Every stored key, sorted in canonical component order."""
        return tuple(sorted(self._records, key=FeatureKey.to_tuple))

    def __contains__(self, key: object) -> bool:
        # Containment stays boolean: a non-key simply is not in the store.
        return isinstance(key, FeatureKey) and key in self._records

    def __iter__(self) -> Iterator[FeatureKey]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"FeatureStore(features={len(self._records)})"

    @staticmethod
    def _require_key(key: object) -> None:
        if not isinstance(key, FeatureKey):
            raise TypeError(
                "features are addressed by FeatureKey only — there is no "
                f"partial addressing; got {type(key).__name__}"
            )
