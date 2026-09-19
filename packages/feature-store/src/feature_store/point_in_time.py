"""Feature 52's read layer: a query at ``t`` sees only rows computed by ``t``.

app_spec.xml, "Point-in-Time Feature Store", feature 52: *System returns
only rows whose computed_as_of is at or before the query time, so a
point-in-time read cannot see a later computation.*  §4.4 of the
architecture doc states the same contract as a rule — "every row carries
``computed_as_of``, and a query at ``t`` may only return rows with
``computed_as_of <= t``" — and feature 51 (:mod:`feature_store.rows`)
implemented the *writing* half of that sentence: the stamp, fixed at write
time, one instant per batch.  This module is the *reading* half.  It is the
half the category exists for: §4.4 closes by calling the feature store "the
single most common source of subtle leakage in real quant systems", and the
leak is always the same shape — a caller asks *what did we know at ``t``?*
and is handed *what is true now*.  A row stamped after ``t`` is a
computation that had not happened yet at ``t``; returning it answers the
question the caller did not ask.  The filter therefore lives in the read
path itself, not in caller discipline: the only rows any of these functions
can return are rows whose stamps precede the query instant.

**The boundary is inclusive — "at or before", ``<=``.**  A row stamped
exactly at the query instant had been computed by then, so it is visible:
equality is the edge between known and not-yet-known, and the edge belongs
to the known side.  (The universe plugin draws the same edge the same way —
``valid_from`` is inclusive, ``valid_to`` exclusive — because a fact that
begins at an instant is in effect at that instant.)

**The stamp is the only clock a read consults.**  A row's *values* may
describe any time — a forecast, a forward-looking label, a date column far
in the future — and none of that gates visibility.  ``computed_as_of`` says
when the row was computed, and that is the whole of the point-in-time
question.  Nothing here reads a wall clock either: the answer is a pure
function of the rows and the query instant, so the same question asked twice
gets the same answer, replay included.

**Rows come back verbatim.**  The same objects, in the order they were
written (a series is not a set — :func:`feature_store.rows.stamp_rows`'s
ordering discipline, preserved rather than sorted away), each still carrying
the stamp that was written: a read never restamps, because a stamp is a fact
about the past and restating it as the read's instant would be exactly the
quiet rewriting §4.4 exists to prevent.

**The query time is validated exactly like a stamp, and for the same
reason.**  A naive ``as_of`` compared against an aware ``computed_as_of``
raises :class:`TypeError` — deep inside a loop, far from the caller who
could have named the offset — so it is refused here, at the query, as this
layer's own error.  An aware query time in another offset is normalised to
UTC rather than rejected: it names the same instant either way, and
normalisation is what makes ``<=`` well-defined no matter who asks.

**One contract, three altitudes.**  :func:`rows_as_of` filters rows already
in hand; :func:`decode_rows_as_of` filters one record's payload bytes
(feature 48's opaque-``bytes`` seam, decoded through feature 51's envelope
and then filtered); :func:`read_rows_as_of` reads through a store under a
key — get, decode, filter.  Each composes the one below, so the three
surfaces cannot disagree about what ``<=`` means.

**At the store layer, a miss and an empty answer are different facts.**
:func:`read_rows_as_of` returns ``None`` when nothing is stored under the
key — the same normal miss :meth:`feature_store.store.FeatureStore.get`
returns — and ``()`` when a record *is* stored but every row in it was
computed after the query instant.  Collapsing the two would hide the very
state this feature guarantees: the later computation exists, and the
point-in-time read declines to see it.

**The store is duck-typed; the key passes through untouched.**  The
application factory imports each member package under a scan alias
(``_nullius_scanned_feature_store``, see ``app.module_loader``), so the
composed ``feature-store`` component is structurally a
:class:`~feature_store.store.FeatureStore` but never the same module object
a direct import yields — the same rationale
:class:`~feature_store.persistence.RegimeFeatureStore` documents for its
own wrapping.  The key is
not re-validated here at all: identity is feature 48's contract, and the
store's own ``get`` enforces it (raising the store's ``TypeError`` for a
non-key), so duplicating the check would only risk disagreeing with it.
Rows, by contrast, are values a caller hands this module *within* one
import graph — payloads cross graphs as bytes, rows never do — so
:func:`rows_as_of` can honestly insist on real
:class:`~feature_store.rows.FeatureRow` instances and trust their stamps,
which are validated by construction.

**A payload that is not a rows envelope is refused, wrapped as this
layer's error.**  A caller catching a failed point-in-time read should catch
one type, not this layer's plus the row layer's — the same re-raising
discipline :mod:`feature_store.rows` applies to the key module's errors.
That includes empty bytes: feature 48's record layer blesses an empty
payload as "a feature with no rows", but the rows layer's representation of
no rows is :func:`feature_store.rows.encode_rows` of an empty batch — a
valid envelope — and bytes that were never a rows payload cannot be
reinterpreted into one.

What is deliberately *not* here: version selection (feature 53's contract —
a caller reaches the version it wants through the key it passes), Parquet
materialisation (49) and caching (50).  Like :mod:`feature_store.rows`,
this module registers nothing with the application factory: it is a pure
function over rows and payloads, not an orchestration service with composed
state.

Stdlib-only, like ``rows.py`` and ``store.py``: the read contract must stay
import-safe everywhere, replay included.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from .rows import FeatureRow, FeatureRowError, decode_rows
from .store import FeatureKey, FeatureStore

__all__ = [
    "PointInTimeError",
    "decode_rows_as_of",
    "read_rows_as_of",
    "rows_as_of",
]


class PointInTimeError(ValueError):
    """A point-in-time query was malformed, or its payload was not rows.

    Subclasses :class:`ValueError` because a malformed query time is a
    caller bug at the read — never a runtime condition to retry — and a
    payload that is not a rows envelope is a storage bug that must surface
    rather than be papered over with an empty answer: "no rows visible at
    ``t``" and "these bytes were never a feature's rows" are different
    facts, and only the first one is ever returned as data.
    """


def _validated_query_time(as_of: object) -> dt.datetime:
    """Validate the query time, returning it aware-UTC.

    A naive datetime is refused (the ``<=`` comparison against every row's
    aware stamp would raise :class:`TypeError` deep inside the read); an
    aware datetime in another offset is normalised to UTC, since it names
    the same instant either way.  The message deliberately does not point at
    :func:`feature_store.rows.utc_now` the way the *write*-side validator
    does: a query is usually about the past, and the caller names that
    instant directly rather than reading a clock.
    """
    if not isinstance(as_of, dt.datetime):
        raise PointInTimeError(
            f"as_of must be a datetime; got {type(as_of).__name__}"
        )
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise PointInTimeError(
            f"as_of must be timezone-aware; got the naive datetime "
            f"{as_of.isoformat()!r}. A point-in-time read compares as_of "
            "against every row's computed_as_of with '<=', and a naive "
            "instant has no offset to compare against — pass an aware "
            "instant"
        )
    return as_of.astimezone(dt.timezone.utc)


def rows_as_of(
    rows: Iterable[FeatureRow], *, as_of: dt.datetime
) -> tuple[FeatureRow, ...]:
    """The rows whose ``computed_as_of`` is at or before ``as_of``.

    The whole of feature 52 at its seam: takes a batch of stamped rows and
    returns the subset a query at ``as_of`` may see, dropping every row
    stamped after the query instant — the later computations a point-in-time
    read must not see, however correct their values turn out to be.

    The comparison is ``<=`` ("at or before"), so a row stamped exactly at
    ``as_of`` is visible: it had been computed by then.  Visibility gates on
    the stamp alone — a row's values may describe any time — and the rows
    that pass come back as the same objects in the order they were given,
    each still carrying the stamp that was written.

    Every element must be a :class:`~feature_store.rows.FeatureRow`; rows
    are values handed to this function within one import graph (payloads
    cross graphs as bytes, rows never do), so the instance check is honest
    and buys the by-construction guarantee that each stamp is aware UTC.
    A non-row element is refused naming its index, rather than escaping
    later as an :class:`AttributeError` from ``row.computed_as_of``.

    Returns a tuple: immutable, deterministically ordered, and safe to hand
    on without the visible subset growing after the fact.
    """
    instant = _validated_query_time(as_of)
    visible: list[FeatureRow] = []
    for index, row in enumerate(rows):
        if not isinstance(row, FeatureRow):
            raise PointInTimeError(
                f"row {index} of a point-in-time read must be a FeatureRow; "
                f"got {type(row).__name__}. A read filters stamped rows — "
                "stamp the batch first (feature_store.stamp_rows)"
            )
        if row.computed_as_of <= instant:
            visible.append(row)
    return tuple(visible)


def decode_rows_as_of(
    payload: bytes, *, as_of: dt.datetime
) -> tuple[FeatureRow, ...]:
    """The rows in one record's payload whose stamps precede ``as_of``.

    Feature 48's seam is opaque bytes, so the point-in-time read of a stored
    record is decode-then-filter: :func:`feature_store.rows.decode_rows`
    rebuilds the stamped rows (revalidating every stamp through the row's
    own construction), and :func:`rows_as_of` applies feature 52's filter.
    The query time is validated before the payload is touched, so a
    malformed question is reported as such even against a malformed payload.

    A payload that is not a rows envelope — not JSON, a foreign version, a
    row without a stamp, empty bytes — is refused as
    :class:`PointInTimeError`, chained from the row layer's own error:
    one error type for "the point-in-time read failed", never an empty
    answer that would read as "nothing was computed by ``as_of``".
    """
    _validated_query_time(as_of)
    try:
        rows = decode_rows(payload)
    except FeatureRowError as exc:
        raise PointInTimeError(
            f"a point-in-time read cannot filter this payload: {exc}"
        ) from exc
    return rows_as_of(rows, as_of=as_of)


def read_rows_as_of(
    store: FeatureStore, key: FeatureKey, *, as_of: dt.datetime
) -> tuple[FeatureRow, ...] | None:
    """The rows stored under ``key`` whose stamps precede ``as_of``.

    The point-in-time read at the store layer: get the record under the
    key, decode its payload, return the rows visible at ``as_of``.  Returns
    ``None`` when nothing is stored under the key — the same normal miss
    :meth:`~feature_store.store.FeatureStore.get` returns — and ``()`` when
    a record is stored but every row in it was computed after ``as_of``:
    the later computation exists, and this read declines to see it.  The
    two answers are different facts, which is why they stay distinguishable
    here rather than both collapsing to "no rows".

    ``store`` is duck-typed on ``get()`` rather than ``isinstance``-checked:
    the composed ``feature-store`` component is imported by the factory
    under a scan alias, so it is structurally a store but never the same
    module object a direct import yields.  ``key`` passes through to the
    store untouched — identity is feature 48's contract and the store's to
    enforce, so a non-key raises the store's own ``TypeError`` here rather
    than a re-statement of it.
    """
    if not callable(getattr(store, "get", None)):
        raise TypeError(
            "read_rows_as_of reads through a feature store exposing get(); "
            f"got {type(store).__name__}"
        )
    _validated_query_time(as_of)
    record = store.get(key)
    if record is None:
        return None
    return decode_rows_as_of(record.payload, as_of=as_of)
