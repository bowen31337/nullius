"""The snapshot directory naming contract.

docs/nullius-tech-architecture.md §4.2 pins the layout::

    snapshots/
      2026-09-01T00:00:00Z_a3f91c/          # <sealed_at>_<snapshot_hash[:6]>

A sealed snapshot's directory name is therefore *not* decoration — it is the
only address the lake persists for that snapshot, and every consumer that
resolves a sealed path parses it back out of the filesystem. That makes the
format a public contract worth enforcing in one place, strictly, in both
directions:

* :func:`snapshot_name` builds ``<sealed_at>_<snapshot_hash[:6]>`` from a
  timezone-aware ``sealed_at`` and a 64-hex-character snapshot hash,
  canonicalising both. ``sealed_at`` is rendered in UTC at second resolution
  (``YYYY-MM-DDTHH:MM:SSZ``); sub-second precision is truncated, because the
  canonical format has no place to carry it. A naive ``sealed_at`` is
  rejected — an unqualified timestamp in a name that must sort and compare
  across machines is exactly the kind of ambiguity that costs a day of
  debugging later.
* :func:`parse_snapshot_name` accepts *only* the canonical form. Anything
  else — a missing underscore, an uppercase prefix, a five-character prefix,
  a directory separator, a ``..`` segment — raises :class:`SnapshotNameError`.
  Strictness here is a security property: a name that arrives from outside
  is turned into a filesystem path, so the parser is the boundary at which
  path traversal dies (:meth:`SnapshotService.open` relies on it).

The hash itself is addressed in full (64 lowercase hex characters); only its
first six characters appear in the name, as a human-checkable shorthand. The
full hash remains the identity of the snapshot — the prefix just makes two
snapshots sealed in the same second distinguishable at a glance.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ._errors import SnapshotNameError

__all__ = [
    "HASH_HEX_LENGTH",
    "PREFIX_LENGTH",
    "format_sealed_at",
    "normalize_snapshot_hash",
    "parse_snapshot_name",
    "resolve_sealed_at",
    "snapshot_name",
]

#: Length of a full sha256 hex digest.
HASH_HEX_LENGTH = 64

#: Characters of the snapshot hash carried in the directory name.
PREFIX_LENGTH = 6

_HEX = frozenset("0123456789abcdef")

# The canonical name shape, anchored at both ends. No path separator, no
# uppercase, no variable-length prefix: anything that does not match this
# exactly is not a snapshot directory name.
_NAME_RE = re.compile(
    r"^(?P<sealed_at>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)_(?P<prefix>[0-9a-f]{6})$"
)

_SEALED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def normalize_snapshot_hash(value: str) -> str:
    """Validate a snapshot hash, returning it in canonical lowercase hex.

    Accepts 64 hexadecimal characters in either case (uppercase is normalised
    away, the same way a caller pasting a digest from `sha256sum` output
    would expect); rejects anything else, including a ``git``-style short
    hash, with a message that states the expected shape.
    """
    if not isinstance(value, str):
        raise SnapshotNameError(
            f"snapshot hash must be a {HASH_HEX_LENGTH}-character hex string, "
            f"got {type(value).__name__}"
        )
    lowered = value.lower()
    if len(lowered) != HASH_HEX_LENGTH or not set(lowered) <= _HEX:
        raise SnapshotNameError(
            "snapshot hash must be exactly "
            f"{HASH_HEX_LENGTH} hexadecimal characters, got {value!r}"
        )
    return lowered


def resolve_sealed_at(value: "datetime | str | None") -> datetime:
    """Canonicalise a ``sealed_at`` to a timezone-aware UTC datetime.

    ``None`` means "now" — the seal-on-schedule flow of §4.1 stamps a
    snapshot when the sealer runs, so that is the useful default. Strings are
    parsed as ISO 8601 (``datetime.fromisoformat`` accepts the trailing
    ``Z`` on Python 3.11+); datetimes pass through. Both paths then share the
    same rules: a value without a UTC offset is rejected rather than guessed,
    everything is converted to UTC, and microseconds are truncated to match
    the second-resolution canonical format.
    """
    if value is None:
        now = datetime.now(timezone.utc)
        return now.replace(microsecond=0)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SnapshotNameError(
                f"sealed_at {value!r} is not an ISO 8601 timestamp: {exc}"
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise SnapshotNameError(
            "sealed_at must be a timezone-aware datetime or ISO 8601 string, "
            f"got {type(value).__name__}"
        )
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise SnapshotNameError(
            f"sealed_at {value!r} has no UTC offset; qualify it (e.g. end it "
            "in '+00:00' or 'Z') so the canonical name is unambiguous"
        )
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def format_sealed_at(value: datetime) -> str:
    """Render a canonicalised ``sealed_at`` as ``YYYY-MM-DDTHH:MM:SSZ``.

    The digits are assembled by hand rather than ``strftime`` so the output
    is byte-identical on every platform (``%Y`` padding for years below 1000
    is not portable, and a directory name is no place for platform drift).
    """
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}Z"
    )


def snapshot_name(sealed_at: "datetime | str | None", snapshot_hash: str) -> str:
    """Build the snapshot directory name ``<sealed_at>_<snapshot_hash[:6]>``.

    Both halves are canonicalised first (see :func:`resolve_sealed_at` and
    :func:`normalize_snapshot_hash`), so every caller that builds a name
    through here produces the same bytes for the same instant and hash.
    """
    canonical_at = resolve_sealed_at(sealed_at)
    canonical_hash = normalize_snapshot_hash(snapshot_hash)
    return f"{format_sealed_at(canonical_at)}_{canonical_hash[:PREFIX_LENGTH]}"


def parse_snapshot_name(name: str) -> tuple[datetime, str]:
    """Parse a canonical snapshot directory name.

    Returns ``(sealed_at, hash_prefix)`` with ``sealed_at`` as a timezone-
    aware UTC datetime. Raises :class:`SnapshotNameError` for anything that
    is not exactly the canonical shape — including calendar-impossible dates
    (``2026-13-01``), which the regex admits but the date parser does not —
    so the strictness boundary is one function, tested as one contract.
    """
    if not isinstance(name, str):
        raise SnapshotNameError(
            f"snapshot name must be a string, got {type(name).__name__}"
        )
    match = _NAME_RE.match(name)
    if match is None:
        raise SnapshotNameError(
            f"snapshot name {name!r} is not <sealed_at>_<hash prefix>; "
            f"expected the form 2026-09-01T00:00:00Z_a3f91c"
        )
    try:
        sealed_at = datetime.strptime(match.group("sealed_at"), _SEALED_AT_FORMAT)
    except ValueError as exc:  # calendar-impossible dates (month 13, day 32, …)
        raise SnapshotNameError(
            f"snapshot name {name!r} carries an impossible sealed_at: {exc}"
        ) from exc
    return sealed_at.replace(tzinfo=timezone.utc), match.group("prefix")
