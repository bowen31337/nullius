"""The §4.2 snapshot hash: one identity over content, universe and schema.

docs/nullius-tech-architecture.md §4.2 states the formula in one line::

    snapshot_hash = sha256(sorted(file_hashes) + universe_definition + schema_version)

and app_spec.xml feature 32 makes it the identity the system persists:
"System persists snapshot_hash computed as a sha256 over sorted file hashes
plus the universe definition plus the schema version". A snapshot's name
abbreviates this hash, its ``MANIFEST.json`` records it in full, and the
snapshot manifest row (feature 33) keys on it — so what the formula covers
is what the whole lake means by "the same snapshot". Each term earns its
place by naming one axis on which otherwise-identical bytes are *not* the
same snapshot:

* **The sorted file hashes** — which bytes. The seal's own walk
  (``_content.walk_content``), the same ``{path: sha256}`` mapping the
  manifest records, folded exactly as ``_content.content_digest`` folds it.
* **The universe definition** — which world the bytes claim to describe.
  The same bars sealed against a different definition of the tradable
  universe are a different snapshot: §4.3 resolves membership as of ``t``
  *by definition*, so the definition a snapshot was sealed under is part
  of what any score computed over it selected. The term is folded by value,
  through the canonical JSON spelling :func:`canonical_universe` produces,
  so two definitions that differ only in key order or spacing are one
  definition — while ``None`` (nothing asserted) and ``{}`` (an asserted
  empty definition) remain the different claims they were in the manifest.
* **The schema version** — what the bytes *mean*. A lake extended with a
  new column or partition kind turns identical bytes into different data;
  :data:`SCHEMA_VERSION` is the lever that says so. Bumping it re-keys
  every seal made afterwards (feature 38's invalidation trigger) without
  touching the directories already immutable under their old hashes.

**The byte-level spelling is the format.** A hash over under-specified
bytes is a hash over nothing, so the preimage is pinned exactly: the three
terms are joined by a single newline, and the result is hashed once, as
UTF-8. Every term is newline-free by construction — hex digits; canonical
JSON (``json.dumps`` escapes control characters, never emits them raw); a
schema version refused if it carries control characters — so the joined
preimage can be split back into exactly the terms that produced it. The
framing is a separability guarantee, not punctuation: without it, a
universe spelling ending where a schema version begins could in principle
be re-split two ways, and two different inputs would share an identity.

The fold is deterministic the way sealing requires: the same file hashes,
universe definition and schema version produce the same hash on any
machine, any day, in any directory order — which is what lets a crashed
schedule's retry recompute the identity it decided, and feature 36's
verification recompute the identity it checks.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Optional

from ._content import sorted_hash_concat
from ._errors import SnapshotManifestError, SnapshotNameError

__all__ = [
    "SCHEMA_VERSION",
    "canonical_universe",
    "snapshot_digest",
    "validate_universe",
]

#: The version of the lake's data schema — §4.2's third hash term.
#:
#: A string (``TEXT``), matching the ``schema_version`` column the snapshot
#: manifest table declares, and deliberately not derived from the code: the
#: version names the *meaning* of the bytes in the lake (the shape of the
#: bars/trades/bookfeat data, the partition layout), not the software that
#: wrote them. It changes only deliberately, when the schema is extended —
#: and the change alone gives every subsequent seal a new ``snapshot_hash``,
#: which is exactly feature 38's "the lake was extended, the old cached
#: scores no longer name the data they claim" lever. Sealed directories
#: keep the hash they were frozen under; immutability outranks recency.
SCHEMA_VERSION = "1"

#: Characters no schema version may carry. ``json.dumps`` escapes controls
#: out of the universe term and hex digits are plain, so this check is what
#: keeps the formula's newline framing unambiguous end to end.
_CONTROLS = frozenset(chr(code) for code in range(0x20)) | {"\x7f"}


# -- The universe definition ------------------------------------------------


def validate_universe(
    universe: Optional[Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    """Accept a universe definition — to record and to fold — or refuse it.

    ``None`` means "not asserted" and passes through — the manifest records
    it as JSON ``null`` and the formula folds it as ``null``, both distinct
    from ``{}`` (an asserted empty definition). Anything else must be a
    JSON *object* (a mapping) whose contents JSON can carry; a dataclass or
    a list is refused with a message that says what to pass instead (the
    mapping form, e.g. ``asdict`` of the universe member's config). The
    accepted value is returned behind a read-only proxy, mirroring the
    record treatment in ``_records``.

    The check runs on a plain ``dict`` copy of the input, and the proxy is
    built over that copy. This matters because validation is *re-entrant*:
    the manifest validates in ``__post_init__`` what the service already
    validated at seal time, so the door has to accept its own output — and
    the proxy it returns is not itself JSON-serializable, so probing the
    proxy would refuse every definition that had passed twice.
    """
    if universe is None:
        return None
    if not isinstance(universe, Mapping):
        raise SnapshotManifestError(
            "universe definition must be a JSON object (a mapping of "
            f"parameter names to values), got {type(universe).__name__}; "
            "pass the mapping form of the definition — for the universe "
            "member's UniverseConfig, dataclasses.asdict(config)"
        )
    copy = dict(universe)
    try:
        json.dumps(copy, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise SnapshotManifestError(
            f"universe definition is not JSON-serializable: {exc}; a "
            "manifest records values the lake can re-read"
        ) from exc
    return MappingProxyType(copy)


def canonical_universe(universe: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The canonical JSON spelling of a universe definition, for the hash.

    ``None`` passes through as ``None`` (the caller folds it as the four
    bytes ``null``); a mapping is validated (see :func:`validate_universe`)
    and spelled as key-sorted, compact JSON — ``separators=(",", ":")`` —
    so key order and whitespace cannot leak into an identity two callers
    mean to be the same. One spelling serves every consumer of "the
    definition, by value": the §4.2 hash term here, and the re-seal
    comparison in ``_service``, so "the same definition" cannot mean one
    thing in the hash and another in an equality check.
    """
    if universe is None:
        return None
    return json.dumps(
        dict(validate_universe(universe)), sort_keys=True, separators=(",", ":")
    )


# -- The formula -------------------------------------------------------------


def snapshot_digest(
    file_hashes: Iterable[str] | Mapping[str, str],
    *,
    universe: Optional[Mapping[str, Any]] = None,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Compute the §4.2 ``snapshot_hash`` over the three terms.

    ``file_hashes`` is the seal's content mapping (``{path: sha256}`` from
    ``walk_content``) or a bare iterable of hashes, folded exactly as
    ``content_digest`` folds it. ``universe`` is the definition the seal
    asserted (``None`` when none was). ``schema_version`` defaults to the
    lake's :data:`SCHEMA_VERSION`; the parameter exists so a reader can
    recompute an identity under the version it holds — a verification pass,
    a test, a future schema bump replaying an old decision — not so a seal
    can quietly pick its own.

    The preimage is the three terms joined by single newlines, UTF-8
    encoded, hashed once with sha256; see the module docstring for why each
    term is provably newline-free and therefore separable. Inputs the
    terms cannot carry (a non-object universe, an empty or control-bearing
    schema version) are refused here, before any identity is computed with
    them.
    """
    universe_term = canonical_universe(universe)
    version = _validate_schema_version(schema_version)
    payload = "\n".join(
        (
            sorted_hash_concat(file_hashes),
            "null" if universe_term is None else universe_term,
            version,
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_schema_version(value: object) -> str:
    """Accept a schema version term, or refuse it as an identity fault.

    The rules are the minimum the formula's framing needs — a non-empty
    string carrying no control characters — plus the honesty rule that an
    empty term would fold silently into every identity alike. A violation
    is a :class:`~snapshot.SnapshotNameError`: the same contract
    ``normalize_snapshot_hash`` serves, a malformed term of the identity
    rather than a malformed name for it.
    """
    if not isinstance(value, str) or not value:
        raise SnapshotNameError(
            f"schema version must be a non-empty string, got {value!r}"
        )
    if _CONTROLS & set(value):
        raise SnapshotNameError(
            f"schema version {value!r} must not contain control characters; "
            "the term has to stay newline-free so the hash preimage splits "
            "back into exactly the terms that produced it"
        )
    return value
