"""The five-component identity of every stored feature.

app_spec.xml, "Point-in-Time Feature Store", feature 48: *System keys
every stored feature with feature_name, feature_version, snapshot_hash,
symbol and frequency.*  docs/nullius-tech-architecture.md §4.4 fixes the
same tuple — ``(feature_name, feature_version, snapshot_hash, symbol,
freq)`` — and the reasoning behind it: base features are expensive and
shared across thousands of signal nodes, so a stored feature's identity
must pin exactly which definition computed it (``feature_name`` +
``feature_version``), which immutable bytes it was computed over
(``snapshot_hash``, feature 32's sha256 over a sealed snapshot), which
instrument it describes (``symbol``) and at which bar grid
(``frequency``).  Change any one component and you have a different
stored feature — never a silent reuse of the old one.

Everything in this module exists to make that sentence enforceable: a
:class:`FeatureKey` always carries all five components, always in the
canonical order, always validated and normalised.  There is no way to
address the feature store with a partial key, because there is no way to
construct one that skips a component or slips an unnormalised value past
validation.  The rest of this category layers on top of that identity —
lazy Parquet materialisation (49), caching (50), point-in-time row
stamping and filtering (51/52, in :mod:`feature_store.rows`), versioned
definitions (53) — none of it replaces it.

This module is stdlib-only by design, mirroring ``app.module_loader``:
the identity contract must stay import-safe in any environment,
including the deterministic replay path.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

__all__ = [
    "FREQUENCIES",
    "MARKET_WIDE_SYMBOL",
    "FeatureKey",
    "FeatureKeyError",
    "Frequency",
]


class FeatureKeyError(ValueError):
    """A feature key component was missing, malformed or unnormalised.

    Subclasses :class:`ValueError` because an invalid key is a caller bug,
    never a runtime condition to retry or catch-and-continue.
    """


class Frequency(enum.StrEnum):
    """The bar grid a feature is computed on.

    The three values are exactly the ``Literal["1m", "1h", "1d"]`` of the
    ``MarketWindow`` contract (docs/nullius-tech-architecture.md §5.1).
    Widening this set is a contract change that must move in lockstep with
    that Literal, not a configuration tweak — a frequency the window
    cannot serve is a key the evaluator can never read back.
    """

    M1 = "1m"
    H1 = "1h"
    D1 = "1d"


#: Every bar grid the feature store keys on, in declaration order.
FREQUENCIES: tuple[str, ...] = tuple(member.value for member in Frequency)

#: The ``symbol`` component for features computed over the market as a
#: whole — cross-sectional dispersion, pairwise correlation, breadth
#: (app_spec.xml features 56/57) — rather than over one instrument.  Such
#: features are still keyed *with* a symbol, because feature 48's contract
#: admits no four-component keys; they carry this sentinel instead.
MARKET_WIDE_SYMBOL = "__market__"

# A snapshot hash is a sha256 rendered as canonical lowercase hex, exactly
# as hexdigest() emits it.  Feature 32 computes it; feature 48 only has to
# recognise it.
_SNAPSHOT_HASH = re.compile(r"\A[0-9a-f]{64}\Z")

# Path separators and NUL are refused in every key component because a key
# doubles as a relative POSIX path (:meth:`FeatureKey.to_path`): a
# component containing "/" would escape its segment, letting two distinct
# keys spell the same storage path — the exact silent collision the key
# exists to prevent.
_FORBIDDEN_CHARS = frozenset("/\\\0")


def _validated_component(field: str, value: object) -> str:
    """Validate one free-form string component of a key."""
    if not isinstance(value, str):
        raise FeatureKeyError(f"{field} must be a string; got {type(value).__name__}")
    if not value or value != value.strip():
        raise FeatureKeyError(f"{field} must be non-empty and unpadded; got {value!r}")
    if value in (".", ".."):
        raise FeatureKeyError(f"{field} must not be a path metacharacter; got {value!r}")
    for char in value:
        if char in _FORBIDDEN_CHARS or ord(char) < 32 or ord(char) == 127:
            raise FeatureKeyError(
                f"{field} must not contain path separators or control "
                f"characters; got {value!r}"
            )
    return value


def _validated_snapshot_hash(value: object) -> str:
    """Validate the snapshot hash, returning its canonical lowercase form.

    Case is normalised rather than rejected: the hash is content
    addressing (feature 32), and two spellings of the same digest must
    address the same stored feature, never two.
    """
    if not isinstance(value, str):
        raise FeatureKeyError(
            f"snapshot_hash must be a string; got {type(value).__name__}"
        )
    canonical = value.strip().lower()
    if not _SNAPSHOT_HASH.fullmatch(canonical):
        raise FeatureKeyError(
            "snapshot_hash must be a 64-character lowercase-hex sha256 "
            f"digest; got {value!r}"
        )
    return canonical


def _validated_frequency(value: object) -> Frequency:
    """Coerce a frequency value to its canonical enum member."""
    try:
        return Frequency(value)
    except (TypeError, ValueError):
        raise FeatureKeyError(
            f"frequency must be one of {', '.join(FREQUENCIES)}; got {value!r}"
        ) from None


@dataclass(frozen=True, slots=True)
class FeatureKey:
    """The immutable identity of one stored feature.

    Construction validates and canonicalises every component, so an
    instance is trustworthy by construction: equal keys are the same
    stored feature, and keys differing in exactly one component are
    different stored features.  Instances are hashable and totally
    orderable via :meth:`to_tuple`, so they serve directly as dictionary
    keys, database primary keys and — through :meth:`to_path` — on-disk
    path segments.

    Component notes:

    * ``feature_version`` is an opaque string ("1", "v2", …).  What
      triggers a bump is feature 53's contract (a changed definition gets
      a new version and never overwrites); the key only guarantees that
      the version is part of the identity.
    * ``symbol`` is preserved verbatim — canonical symbol casing is the
      universe plugin's contract (feature 46), not the key's.  Market-wide
      features carry :data:`MARKET_WIDE_SYMBOL`.
    """

    feature_name: str
    feature_version: str
    snapshot_hash: str
    symbol: str
    frequency: Frequency

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction.  After
        # this the instance is sealed.
        object.__setattr__(
            self,
            "feature_name",
            _validated_component("feature_name", self.feature_name),
        )
        object.__setattr__(
            self,
            "feature_version",
            _validated_component("feature_version", self.feature_version),
        )
        object.__setattr__(
            self, "snapshot_hash", _validated_snapshot_hash(self.snapshot_hash)
        )
        object.__setattr__(
            self, "symbol", _validated_component("symbol", self.symbol)
        )
        object.__setattr__(
            self, "frequency", _validated_frequency(self.frequency)
        )

    def to_tuple(self) -> tuple[str, str, str, str, str]:
        """The five components as plain strings, in canonical order.

        The order is the one the spec text and §4.4 both state — name,
        version, snapshot, symbol, frequency — and it is also the segment
        order of :meth:`to_path`, so tuple order, path order and
        ``str()`` can never drift apart.
        """
        return (
            self.feature_name,
            self.feature_version,
            self.snapshot_hash,
            self.symbol,
            str(self.frequency),
        )

    def to_path(self) -> PurePosixPath:
        """The key as a relative POSIX path of exactly five segments.

        This is the on-disk addressing the Parquet materialisation
        (feature 49) mounts under the lake; keeping it on the key means
        *what* is stored and *where* it is stored can never disagree.
        POSIX deliberately, independent of host OS: the lake layout is
        part of the replay contract, not a machine's convention.  Every
        component is validated path-safe by construction, so the join
        below cannot escape its segment.
        """
        return PurePosixPath(*self.to_tuple())

    @classmethod
    def from_path(cls, path: "str | PurePosixPath") -> "FeatureKey":
        """Rebuild a key from a five-segment relative path.

        The inverse of :meth:`to_path`.  Every component revalidates, so a
        path that wandered in from outside the store still cannot smuggle
        an unvalidated key inside.
        """
        parts = PurePosixPath(path).parts
        if len(parts) != 5:
            raise FeatureKeyError(
                "a feature key path is exactly five relative segments "
                "(feature_name, feature_version, snapshot_hash, symbol, "
                f"frequency); got {len(parts)} in {str(path)!r}"
            )
        return cls(*parts)

    def __str__(self) -> str:
        # The canonical single-line form is the path itself: one textual
        # identity, round-trippable through from_path().
        return str(self.to_path())
