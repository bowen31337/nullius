"""Feature 51's row layer: every feature row is stamped with ``computed_as_of``.

app_spec.xml, "Point-in-Time Feature Store", feature 51: *System stamps every
feature row with computed_as_of at write time.*  docs/nullius-tech-architecture.md
§4.4 states the same contract and its reason: the feature store is *point-in-time
correct by construction* — every row carries ``computed_as_of``, and a query at
a time ``t`` may only return rows with ``computed_as_of <= t``.  This module is
the first half of that sentence, the *writing* half: it is the payload layer
that gives a feature's rows a representation at all, and it stamps them as they
are written.

**Why a row layer had to exist before anything could be stamped.**  Feature 48
deliberately made a record's payload opaque ``bytes`` and fixed only the
*identity* contract — the key is the address, interpretation is the payload
layer's, and the keying layer must not leak row-schema assumptions into identity
(see :mod:`feature_store.store`, which says exactly this and points here for
"row-level point-in-time stamping ... features 51/52").  Every persistence
module landed since encodes *one aggregate value per record* — a correlation, a
dispersion, a label series.  None of them has rows.  Feature 51 is therefore not
a stamp added to an existing container; it is the container, and the stamp.

**The stamp is written, then never read from the clock again.**  A
:class:`FeatureRow` is frozen and carries its stamp as a field.  Reading a row
back — out of a store, a payload, a Parquet file once feature 49 materialises
one — returns the stamp that was written, whatever the wall clock says then.
That is the whole point: a row's ``computed_as_of`` records *when the row was
computed*, which is a fact about the past, and a re-read must not quietly
restate it as now.

**One stamp per write, not one per row.**  :func:`stamp_rows` reads the clock
once, at the top of the call, and applies that single instant to every row in
the batch.  Stamping row-by-row would let a batch straddle a clock tick and
carry two different instants, and then a ``<= t`` query — feature 52 — landing
between them would return *part of one write*.  A reader seeing half a batch
cannot tell it from a complete one, which is precisely the silent leakage §4.4
exists to prevent.  One write, one instant.

**The clock is injected, never reached for.**  ``computed_as_of`` may be passed
explicitly by a caller that knows when the computation actually happened (a
backfill, a replay), and otherwise comes from a ``clock`` callable supplied at
the call site, defaulting to ``datetime.now(UTC)``.  Nothing here reads a global
clock, so the deterministic replay path can reproduce a write exactly — the same
discipline :mod:`contract.resolution` argues for at length ("resolution is pure
and clock-free") and the same shape :mod:`universe.store` and
:mod:`snapshot._recomputation` use for their audit timestamps.

**The stamp is timezone-aware UTC, and a naive instant is refused.**  Feature 52
compares the stamp with ``<=``.  Comparing a naive datetime against an aware one
raises :class:`TypeError` — so a naive stamp would detonate deep inside a query,
at read time, far from the write that could have named its offset.  Refusing it
at construction puts the failure on the writer, where the missing offset can
still be explained.  An aware stamp in another offset is normalised to UTC
rather than rejected, because it names an unambiguous instant; only the
*unaware* instant is a caller bug.

**Payload representation.**  :func:`encode_rows` / :func:`decode_rows` bridge
this layer to feature 48's opaque-``bytes`` seam: a deterministic JSON envelope
(sorted keys, no incidental whitespace), the same discipline
:mod:`feature_store.dispersion_persistence` and :mod:`feature_store.persistence`
already follow, because the replay path compares payloads byte-for-byte.  The
stamp serialises as ISO-8601 with an explicit offset, and the decoder rebuilds
an aware-UTC datetime and revalidates through :meth:`FeatureRow.__post_init__`,
so a payload that wandered in from disk cannot smuggle a naive stamp past the
write-time check.

**A value the payload cannot carry is refused at the write.**  The payload is a
JSON envelope, so a ``bytes`` column or a set is a row that cannot be stored at
all; :func:`_require_serialisable` checks each value as it is stamped, so the
failure stays inside this layer's error type rather than surfacing later as a
bare ``TypeError`` from deep inside ``json.dumps``.  ``nan`` is representable
and legal — the member's own metric payloads carry ``NaN`` for an uncomputable
value.

Feature 52's read filter is deliberately *not* here: this module stamps rows and
carries them, and a query at ``t`` that returns only the rows with
``computed_as_of <= t`` is the next feature's contract, built on this seam.

Stdlib-only, like ``keys.py`` and ``store.py``: the row representation must stay
import-safe everywhere, replay included.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .keys import FeatureKeyError, _validated_component

__all__ = [
    "COMPUTED_AS_OF_FIELD",
    "FeatureRow",
    "FeatureRowError",
    "decode_rows",
    "encode_rows",
    "stamp_rows",
    "utc_now",
]


#: The field name the spec gives the stamp (§4.4: "every row carries
#: ``computed_as_of``").  Spelled once here and used everywhere — the key of
#: the stamp in the payload envelope, and the attribute name on a row — so the
#: word in the spec, the word on disk and the word in code cannot drift.
COMPUTED_AS_OF_FIELD = "computed_as_of"

#: The envelope version this module writes and reads.  Bumped only
#: deliberately: every consumer reads the same rows.
_ENVELOPE_VERSION = 1


class FeatureRowError(ValueError):
    """A feature row's stamp or values were malformed at write time.

    Subclasses :class:`ValueError` because a malformed row is a caller bug at
    the write, never a runtime condition to catch and continue past — by the
    time a bad stamp reached a query it would be far from its cause.
    """


def utc_now() -> dt.datetime:
    """The current instant, timezone-aware UTC — the default clock.

    Seconds resolution: ``computed_as_of`` orders writes against one another,
    and sub-second precision in the stamp buys nothing a query needs while
    making two writes that are "the same instant" for every practical purpose
    compare as different.  Microseconds are dropped rather than rounded so the
    result is never *after* the instant observed.
    """
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _validated_instant(value: object, field_name: str) -> dt.datetime:
    """Validate a stamp, returning it aware-UTC.

    A naive datetime is refused (feature 52 compares the stamp with ``<=``, and
    a naive/aware comparison raises); an aware datetime in another offset is
    normalised to UTC, since it names the same instant either way.
    """
    if not isinstance(value, dt.datetime):
        raise FeatureRowError(
            f"{field_name} must be a datetime; got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise FeatureRowError(
            f"{field_name} must be timezone-aware; got the naive datetime "
            f"{value.isoformat()!r}. A point-in-time stamp is compared with "
            "'<=' at read time, and a naive instant has no offset to compare "
            "against — pass an aware UTC instant (see utc_now())"
        )
    return value.astimezone(dt.timezone.utc)


def _validated_values(value: object) -> dict[str, Any]:
    """Validate a row's named values, returning a plain dict copy.

    Keys must be usable, path-safe names — the same rule feature 48 applies to
    a key component — because they double as the payload's JSON object keys and
    as column names once feature 49 materialises rows to Parquet.  Values are
    kept as plain scalars: identity is still the key's (feature 48), so the row
    layer interprets the payload without ever claiming to identify it.

    :data:`COMPUTED_AS_OF_FIELD` is **reserved**: it names the stamp, so it
    cannot also name a column.  Allowing it would let a value collide with the
    stamp's own slot in the serialised row — the payload would carry whichever
    one won, and a row whose stamp is overridden by a column is a row whose
    point-in-time guarantee has been silently replaced by feature data.  A
    caller with such a column renames it; refusing at the write is the only
    place the collision can still be explained.

    Values must be JSON-representable, and that too is checked here rather
    than left to :func:`encode_rows`.  The payload *is* JSON, so a value the
    encoder cannot serialise — ``bytes``, a set, a dataclass — is a row that
    cannot be stored at all; catching it at the stamp keeps the failure in the
    layer whose error type the caller is already catching, instead of surfacing
    later as a bare ``TypeError`` from deep inside ``json.dumps``.  ``nan`` and
    ``inf`` are representable (the member's metric payloads already carry
    ``NaN`` for an uncomputable value), so an unscored cell is legal.
    """
    if not isinstance(value, Mapping):
        # A single row's mapping is a natural misuse ("here are the columns")
        # and would iterate as its *keys*, stamping a batch of column names.
        # Naming the likely intent beats reporting the str it iterated into.
        raise FeatureRowError(
            "values must be a sequence of rows, each a mapping of column name "
            f"to value; got a single {type(value).__name__}. Pass a list — "
            "stamp_rows([{...}]) for one row"
        )
    validated: dict[str, Any] = {}
    for name, item in value.items():
        if not isinstance(name, str):
            raise FeatureRowError(
                f"a feature row's column names must be strings; got "
                f"{type(name).__name__}"
            )
        # The name rule is feature 48's (a column name becomes a JSON key and,
        # once feature 49 materialises, a Parquet column), so it is enforced by
        # the same validator a key component goes through.  Its error is
        # re-raised as this layer's own: a caller catching row problems should
        # not have to know the key module's taxonomy to catch them.
        try:
            name = _validated_component("column name", name)
        except FeatureKeyError as exc:
            raise FeatureRowError(str(exc)) from exc
        if name == COMPUTED_AS_OF_FIELD:
            raise FeatureRowError(
                f"{COMPUTED_AS_OF_FIELD!r} is reserved: it names the row's "
                "write-time stamp (feature 51), so it cannot also name a "
                "column — a value stored under it would collide with the "
                "stamp in the serialised row. Rename the column"
            )
        validated[name] = _require_serialisable(name, item)
    return validated


def _require_serialisable(column: str, value: Any) -> Any:
    """Refuse a column value the payload's JSON encoding cannot carry.

    Probed by encoding the single value, so the check matches exactly what
    :func:`encode_rows` will do to it rather than approximating the rule with
    a list of allowed types — ``nan``, ``inf``, nested lists and nested dicts
    all pass, ``bytes`` and a ``set`` do not.
    """
    try:
        json.dumps({column: value})
    except (TypeError, ValueError) as exc:
        raise FeatureRowError(
            f"column {column!r} holds a value the feature payload cannot "
            f"carry ({type(value).__name__}: {exc}); values must be "
            "JSON-representable, because the payload is a JSON envelope"
        ) from exc
    return value


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One row of a feature's payload, carrying its write-time stamp.

    ``computed_as_of`` is when this row was computed, fixed at write time and
    never restated: it is a fact about the past, and a re-read returns the
    instant that was written rather than the instant of the read (feature 51).
    ``values`` is the row's named values — the columns — opaque to this layer
    beyond being name-addressable and serialisable.  The name
    :data:`COMPUTED_AS_OF_FIELD` is reserved for the stamp and cannot also be a
    column.

    Construction validates and canonicalises, so an instance is trustworthy by
    construction and feature 52 can compare stamps without re-checking them.
    Instances are frozen: a stamped row is a record of a past computation, and
    editing one in place would rewrite history rather than supersede it.

    Rows compare by value (``==``) but are deliberately **unhashable**.  A
    frozen dataclass would otherwise auto-generate ``__hash__``, and since
    ``values`` may legally hold a list or a nested dict, that hash would raise
    ``TypeError: unhashable type: 'dict'`` at the point of use — naming a
    ``dict`` the caller never passed, from an object that advertised itself as
    hashable.  Declaring it unhashable makes the failure honest and immediate,
    naming the row.  Nothing here needs a row as a dict key: rows are ordered
    in a tuple and addressed by their feature's key (feature 48), never by
    identity.
    """

    computed_as_of: dt.datetime
    values: Mapping[str, Any] = field(default_factory=dict)

    # Overrides the __hash__ a frozen dataclass would synthesise; see above.
    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction.  After
        # this the instance is sealed.
        object.__setattr__(
            self,
            COMPUTED_AS_OF_FIELD,
            _validated_instant(self.computed_as_of, COMPUTED_AS_OF_FIELD),
        )
        object.__setattr__(self, "values", _validated_values(self.values))

    def value(self, name: str) -> Any:
        """The value stored under column ``name``, or ``None`` if absent.

        Absent is a normal miss, matching the store's own read discipline: a
        column a feature does not carry is a discoverable state, not an error.
        """
        return self.values.get(name)

    def column_names(self) -> tuple[str, ...]:
        """The row's column names, sorted for deterministic traversal.

        Sorted rather than insertion-ordered, the same discipline
        :meth:`FeatureStore.keys` applies to keys: two rows built from the same
        values in different orders are the same row, and traversing them must
        not depend on how they were built.
        """
        return tuple(sorted(self.values))

    def to_dict(self) -> dict[str, Any]:
        """The row as a plain, JSON-ready dict: the stamp plus every value.

        The stamp is included under :data:`COMPUTED_AS_OF_FIELD` in canonical
        ISO-8601 with an explicit offset, so a row's serialised form says when
        it was computed without a reader having to know to ask.  That name is
        reserved (see :func:`_validated_values`), so the stamp is written last
        and never shadowed by a column.
        """
        body: dict[str, Any] = {
            name: self.values[name] for name in self.column_names()
        }
        body[COMPUTED_AS_OF_FIELD] = _isoformat(self.computed_as_of)
        return body


def _isoformat(instant: dt.datetime) -> str:
    """Render an aware-UTC instant as canonical ISO-8601 with an offset."""
    return instant.astimezone(dt.timezone.utc).isoformat()


def stamp_rows(
    values: Iterable[Mapping[str, Any]],
    *,
    computed_as_of: dt.datetime | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> tuple[FeatureRow, ...]:
    """Stamp every row in ``values`` with one ``computed_as_of``.

    The whole of feature 51 at its seam: takes the rows a computation produced
    and returns them as :class:`FeatureRow`s, each carrying the instant it was
    computed.

    **The instant is read once, before the first row is built.**  Every row in
    the batch receives the identical stamp, so a write is atomic with respect
    to time: a query at any instant either sees the whole batch or none of it,
    never a clock-tick's worth of rows.  Reading the clock per row would make
    that guarantee depend on how long the loop took.

    ``computed_as_of`` is the stamp to apply, for a caller that knows when the
    computation happened — a backfill stamps the historical instant, and a
    replay stamps the instant it is reproducing, so neither records "now" and
    neither depends on when it ran.  When omitted, ``clock()`` supplies the
    instant (defaulting to :func:`utc_now`), so a test or a replay can pin the
    clock without monkeypatching a global.

    Returns a tuple, ordered as ``values`` was: immutable, so the stamped batch
    cannot be appended to after the fact and made to disagree with its one
    stamp.
    """
    # A bare mapping is the one misuse the per-row check cannot catch: an empty
    # dict iterates as nothing, so "one row with no columns" would silently
    # stamp zero rows — a write that reports success and stores no data.  It is
    # tested here, before iteration, because after iteration the evidence is
    # gone.
    if isinstance(values, Mapping):
        raise FeatureRowError(
            "values must be a sequence of rows, each a mapping of column name "
            "to value; got a single mapping. Pass a list — "
            "stamp_rows([{...}]) for one row"
        )
    if computed_as_of is not None:
        instant = _validated_instant(computed_as_of, COMPUTED_AS_OF_FIELD)
    else:
        source = utc_now if clock is None else clock
        if not callable(source):
            raise FeatureRowError(
                f"clock must be callable and return a datetime; got "
                f"{type(source).__name__}"
            )
        instant = _validated_instant(source(), COMPUTED_AS_OF_FIELD)
    return tuple(
        FeatureRow(computed_as_of=instant, values=row) for row in values
    )


# ---------------------------------------------------------------------------
# Payload encode/decode (the opaque-bytes half of feature 48's contract)
# ---------------------------------------------------------------------------


def encode_rows(rows: Iterable[FeatureRow]) -> bytes:
    """Encode stamped rows to an opaque payload for a feature-store record.

    A deterministic JSON envelope — sorted keys, no incidental whitespace —
    exactly as :mod:`feature_store.dispersion_persistence` and
    :mod:`feature_store.persistence` do, because the replay path compares
    payloads: the same rows must always encode to byte-identical bytes.

    Each row travels as its own object, so the stamp is per-row on disk even
    though one write gave the batch a single instant.  The envelope records the
    rows in the order given: a feature's row order is part of what it computed
    (a series is not a set), so it is preserved rather than sorted away.

    A value that is not JSON-representable is refused as a
    :class:`FeatureRowError` rather than escaping as a bare ``TypeError``:
    :meth:`FeatureRow.__post_init__` already rejects one at construction, so
    reaching this here means a hand-built or mutated row — and either way the
    caller should see this layer's error, not ``json``'s.
    """
    body = {
        "version": _ENVELOPE_VERSION,
        "rows": [row.to_dict() for row in rows],
    }
    try:
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FeatureRowError(
            f"the rows cannot be encoded to a feature payload: {exc}"
        ) from exc


def decode_rows(payload: bytes) -> tuple[FeatureRow, ...]:
    """Rebuild the stamped rows :func:`encode_rows` wrote.

    Every row revalidates through :meth:`FeatureRow.__post_init__`, so a
    payload carrying a naive or malformed stamp is refused here rather than
    surfacing later as a ``TypeError`` inside a comparison.  Row order is the
    order the payload recorded.
    """
    try:
        body = json.loads(payload)
    except ValueError as exc:
        raise FeatureRowError(f"not a feature-rows payload: {exc}") from exc
    if not isinstance(body, dict):
        raise FeatureRowError(
            "a feature-rows payload must be a JSON object; got "
            f"{type(body).__name__}"
        )
    version = body.get("version")
    if version != _ENVELOPE_VERSION:
        raise FeatureRowError(
            f"feature-rows payload is version {version!r}, but this reader "
            f"decodes version {_ENVELOPE_VERSION!r}; a changed row "
            "representation is a different stored feature, not a payload this "
            "decoder reinterprets"
        )
    encoded = body.get("rows")
    if not isinstance(encoded, list):
        raise FeatureRowError(
            "a feature-rows payload must carry a list of rows; got "
            f"{type(encoded).__name__}"
        )
    return tuple(_decode_row(item, index) for index, item in enumerate(encoded))


def _decode_row(item: object, index: int) -> FeatureRow:
    """Rebuild one row, refusing a malformed stamp or shape."""
    if not isinstance(item, dict):
        raise FeatureRowError(
            f"row {index} of a feature-rows payload must be a JSON object; "
            f"got {type(item).__name__}"
        )
    if COMPUTED_AS_OF_FIELD not in item:
        raise FeatureRowError(
            f"row {index} of a feature-rows payload carries no "
            f"{COMPUTED_AS_OF_FIELD!r}; every row is stamped at write time "
            "(feature 51)"
        )
    raw = item[COMPUTED_AS_OF_FIELD]
    if not isinstance(raw, str):
        raise FeatureRowError(
            f"row {index} carries a non-string {COMPUTED_AS_OF_FIELD}: "
            f"{type(raw).__name__}"
        )
    try:
        instant = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FeatureRowError(
            f"row {index} carries an unparseable {COMPUTED_AS_OF_FIELD} "
            f"{raw!r}: {exc}"
        ) from exc
    values = {
        name: value for name, value in item.items() if name != COMPUTED_AS_OF_FIELD
    }
    # No try/except: a malformed stamp propagates its own FeatureRowError from
    # __post_init__, naming the field, rather than being rewrapped here.
    return FeatureRow(
        computed_as_of=_validated_instant(instant, COMPUTED_AS_OF_FIELD),
        values=values,
    )
