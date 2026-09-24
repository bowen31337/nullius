"""The persisted rebalance record — feature 309: each target weight set written
down with the promoted signals it originated from.

app_spec.xml, "Portfolio Book Construction", feature 309: *System persists each
rebalance target weight set with its originating promoted signal identifiers.*

§C8's chain ends at feature 305's publication — *"final target weights as the
only output consumed by the order layer"* — and docs/nullius-tech-architecture.md
§13.2 opens the order path immediately downstream on
``client_order_id = hash(book_id, rebalance_ts, symbol)``.  This feature is the
sentence that says where the chain's output is **written down**, and what must be
written down **beside** it: the identifiers of the promoted signals the set came
from.

**The provenance is not on any value the chain hands out, and that is why this is
a feature.**  Feature 301's :class:`book.CompositeBook` holds
``information_ratios`` and ``weights`` keyed by ``signal_id`` — the composite *is*
the record of which signals weighted the book — but feature 303's
:class:`book.TargetWeights` and feature 305's
:class:`book.FinalTargetWeights` are keyed by **symbol** only.  That is feature
305's own decision, stated in its docstring: the construction's *working* stays
where it was computed, because the sentence's *only* is what keeps it out of the
order layer's instruction.  So the provenance is deliberately absent from
everything downstream of feature 301 — and persisting it is the only way the
chain's output can ever be audited back to the views that produced it.

**This feature adds no arithmetic.**  No re-weighting, no re-normalization, no
re-bounding, no re-publication: the set that is written down is the set the
construction built, read off the value the caller already holds.  It re-opens
nothing features 301-308 settled, and it reaches into no order-path machinery —
no ``client_order_id`` (that hash is the router's own feature 316), no rounding to
a venue's step or tick, no sizing, no venue choice.

**The identity is the rebalance's, and it is read from §13.2 rather than
invented.**  §13.2 keys the order path on the triple
``(book_id, rebalance_ts, symbol)``; two of those three are the rebalance's.  So
:data:`book._rebalance.REBALANCE_TARGET_WEIGHTS_TABLE` is keyed by exactly that
pair — one row per rebalance per book — and a surrogate key would be a *second*
identity standing beside the one the order path hashes, free to disagree with it.
``book_id`` is the deployment's (the system runs more than one book, §C9), and
``rebalance_ts`` is the rebalance's instant rather than the write's: a default of
*now* would make the row's identity the moment somebody happened to call, so a
retry would land under a different identity — which is the one property
idempotence rests on.  Both are therefore **required keywords with no default**,
the stance feature 303's target, feature 304's two limits and feature 308's
figures take.

**The set is one JSON object, so it lands whole or not at all.**  The alternative
— one row per ``(book, rebalance_ts, symbol)`` — would make the set's *coverage* a
property of how many rows happened to be written: a write that failed halfway
would read back as a smaller book, which is exactly the *absence-versus-zero* trap
this member refuses everywhere.  A partially written set is not a small book; it
is the absence of one.  So :data:`WEIGHTS_COLUMN` holds the whole set as a JSON
object and :data:`SIGNAL_IDS_COLUMN` the identifiers as a JSON array, and both are
**rebuilt on read** rather than summarised into derived columns — the discipline
:mod:`cost_model.latency_store` states for its ``samples`` and
:mod:`evaluator._metrics_store` for its ``ic_series``.

**The provenance is read off the promoted signals, never retyped.**  ``record``'s
``originating_signals`` argument is the promoted signals the set originated from,
and this module reads each one's ``signal_id`` — the same attribute feature 301's
combiner reads off the same values, duck-typed, no ``isinstance``, because the
loader imports every member under a synthetic name and a value composed in this
process may be a second class object.  A bare list of identifiers would be a
*claim*: nothing could check that those signals are the ones that weighted the
book, and provenance nothing checks is the one thing an audit table exists to
avoid.  Reading ``signal_id`` off each signal means a caller cannot pass bare
strings, so what is recorded is always the identifiers of values that call
themselves promoted signals.

The identifiers are stored sorted and distinct — a provenance is a *set*, and one
spelling of it makes two records of it compare equal, which is what the idempotent
re-issue below rests on.  A duplicate is refused with feature 301's own
``duplicate_signal`` word, read one step further along the chain: the book was
weighted by one signal, and a provenance naming it twice is a malformed set of
identifiers rather than a second weighting.

**Persisted once: an identical re-issue is a retry, a differing one is a
rewrite.**  The sentence says *each*, so there is one recorded set per rebalance:

* an **absent row** takes the insert, and the answer is read back from the
  database inside the same transaction, so the record's stamp is the table's own;
* a **standing row equal to the offered set** — weights and identifiers both —
  answers the standing row **untouched**, ``recorded_at`` included: a re-issue is
  the same call arriving twice (a reclaimed spot instance, a loop that re-ran its
  rebalance step), and the set did not change, so the instant it was recorded did
  not either;
* a **standing row different** from the offered set is refused with
  :data:`REBALANCE_RECORDED_CODE` (``rebalance_already_recorded``).

The refusal is the sentence's own judgment, in the shape feature 305's
``annexed_record`` takes one layer up: two target weight sets for one rebalance
instant leave every reader of this table **choosing between them**, and here there
is no bound to re-run and no act to re-apply — the row *is* the record, so a silent
overwrite would be a rebalance nobody decided, recorded as though somebody had.
The repair is the caller's: record the set under the instant it was actually
computed for.  This module reconciles nothing and overwrites nothing.

**Absence is not zero, read on the provenance.**  Refused: a value carrying no
``weights`` (with feature 305's own :data:`book.NO_BOOK_CODE`, imported rather than
respelt — the same fact about the same surface, read one step further along the
chain), a set covering no symbols, a non-finite weight, a blank symbol name, an
absent or non-iterable provenance, a signal carrying no ``signal_id``, a duplicate
identifier, a blank ``book_id`` and a naive or non-datetime instant.  **Answered**:
a book held flat — every weight ``0.0``, feature 303's zero-target answer, admitted
by feature 304 at every limit of zero or more.  *Hold nothing* is a decision a
rebalance is entitled to record, and the provenance of that decision is real: three
signals placed a book at zero.

**Three faces, and the third is this member's first.**  Every feature 303-308
mints a pair — the ask's own facts and the one judgment its sentence mints —
because none of them touches a database.  A store has a third face the member has
never had to name: **the write that did not land**, and the address that made it
impossible.  Every store-bearing feature in this workspace names it in its own
class (``PromotionStoreError``, ``RouterStoreError``, ``CoverageError``), for the
reason :mod:`promotion.errors` argues at length: a malformed ask and an unreachable
database must not arrive in the same class, because the caller's position differs —
*fix what you handed me* against *your store is unreachable*.  So this feature
adds :class:`~book.errors.RebalanceRequestError` (the ask),
:class:`~book.errors.RebalanceRewriteError` (the judgment) and
:class:`~book.errors.RebalanceStoreError` (the store), all siblings under
:class:`~book.errors.BookConstructionError`.

**No new component, no seat edit, no migration.**  The member registers exactly one
component — the combiner — and the member's suite pins that six times, precisely so
a later edit cannot quietly add a second.  A builder runs with no arguments and
must not fail composition, and this store's address is a deployment's
``DATABASE_URL``; the combiner's whole configuration is the arithmetic, as its own
docstring and the component suite both say.  So the store is reached the way
:meth:`regime.coverage.RegimeCoverage.resolve` is: a class beside the combiner,
with a ``resolve`` classmethod that answers ``None`` for a deployment that named no
database.  No ``@register``, no endpoint, no entry in the shared migration chain —
the member-owned table is created idempotently by the only module that writes it —
and no seat edit.

**The honest change to the member's layering story: this package is no longer
environment-free.**  Every other module in this member reads a value the caller
holds and touches nothing; this one opens the deployment's relational store.  It
reads ``DATABASE_URL`` at the **call** and never at composition, so the factory's
scan still pays only the imports it already paid — :mod:`json`, :mod:`os`,
:mod:`sqlite3`, :mod:`urllib.parse` and :mod:`pathlib` are stdlib — and it takes no
clock, imports no other member and performs no arithmetic.  The member's package
docstring says so plainly rather than claiming otherwise.

Storage is the workspace's relational store, addressed by ``DATABASE_URL`` exactly
as every other store in this workspace is, and the schema is created idempotently
on connect, so no migration step is needed.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlparse

from ._publish import NO_BOOK_CODE
from .errors import (
    RebalanceRequestError,
    RebalanceRewriteError,
    RebalanceStoreError,
)

__all__ = [
    "DATABASE_URL_ENV",
    "NO_ORIGINATING_SIGNALS_CODE",
    "REBALANCE_RECORDED_CODE",
    "REBALANCE_TARGET_WEIGHTS_TABLE",
    "RebalanceTargetWeights",
    "RebalanceTargetWeightsStore",
]

#: The workspace-wide environment variable naming the relational store.
DATABASE_URL_ENV = "DATABASE_URL"

#: One row per rebalance per book — the table this member owns and the only
#: writer of it is :meth:`RebalanceTargetWeightsStore.record`.  Named
#: ``book_``-prefixed for the reason every member-owned table in this workspace
#: is: the store is shared, the table is not.
REBALANCE_TARGET_WEIGHTS_TABLE = "book_rebalance_target_weights"

#: The column holding the set's symbols, one row of the table's own spelling.
#: Named once so the read path and the write path cannot drift apart about the
#: order they use, and so a future migration that appends a column cannot
#: silently shift the fields.
BOOK_ID_COLUMN = "book_id"

#: The column holding the rebalance's instant, as the one canonical ISO 8601 UTC
#: spelling :func:`_isoformat_utc` writes — which is what makes the pair with
#: :data:`BOOK_ID_COLUMN` a primary key rather than a pair of spellings.
REBALANCE_TS_COLUMN = "rebalance_ts"

#: The whole target weight set as one JSON object (``{symbol: weight}``).  One
#: column rather than one row per symbol, because a set's coverage must not be a
#: property of how many rows landed — see the module docstring.
WEIGHTS_COLUMN = "weights"

#: The originating promoted signal identifiers as one JSON array, sorted and
#: distinct.  The provenance the sentence pairs with the set.
SIGNAL_IDS_COLUMN = "signal_ids"

#: The column holding the database's own stamp of when the row was written.
#: ``DEFAULT (datetime('now'))``, with the outer parentheses SQLite's ``DEFAULT``
#: grammar demands of a function call — without them the whole ``CREATE TABLE``
#: is a syntax error, the trap :mod:`regime.coverage` and migration ``0107``
#: both document for this exact expression.
RECORDED_AT_COLUMN = "recorded_at"

#: The code an ask refusal opens with when the provenance the caller handed over
#: names no promoted signals at all — an absent, empty or non-iterable argument.
#: Greppable by the word that names what is missing rather than what is wrong
#: with it, the convention :data:`book.NO_BOOK_CODE` states.  Feature 309's
#: sentence mandates no token (it names its subject in prose), so the code is
#: this module's own, and it is a *separate* word from ``no_book`` because the
#: repairs differ: *hand the book to record* against *hand the signals it came
#: from*.
NO_ORIGINATING_SIGNALS_CODE = "no_originating_signals"

#: The code the one judgment opens with — the rebalance already carries a
#: different recorded set.  This is the sentence's own word made greppable: the
#: system persists *each* rebalance's set with its provenance, so one row per
#: rebalance is the shape, and an operator greps this word to find out *which
#: rebalance was recorded twice, differently*.
REBALANCE_RECORDED_CODE = "rebalance_already_recorded"

#: Sentinel for "attribute not present", so a value that carries no ``weights``
#: is distinguished from one that carries ``weights=None``.  The member's own
#: ``_MISSING`` discipline, read on this feature's value.
_MISSING = object()

#: The DDL, created idempotently by the only module that writes this table.
#: The primary key is the rebalance's identity — §13.2's own pair, one row per
#: rebalance per book — and there is deliberately no ``AUTOINCREMENT`` and no
#: surrogate key beside it: a second identity here would be free to disagree
#: with the one the order path hashes into its ``client_order_id``.
#:
#: No index is declared beside the primary key.  Every read this store performs
#: is either the key itself (:meth:`RebalanceTargetWeightsStore.get`) or the
#: key's leading column (:meth:`RebalanceTargetWeightsStore.history`), and the
#: primary key's index already serves both — a second index would cost a write
#: per rebalance to save a scan over rows the key has already bounded.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {REBALANCE_TARGET_WEIGHTS_TABLE} (
    {BOOK_ID_COLUMN}      TEXT NOT NULL,
    {REBALANCE_TS_COLUMN} TEXT NOT NULL,  -- ISO 8601 UTC, one spelling
    {WEIGHTS_COLUMN}      TEXT NOT NULL,  -- JSON: {{symbol: weight}}, whole
    {SIGNAL_IDS_COLUMN}   TEXT NOT NULL,  -- JSON: [signal_id, ...], sorted
    {RECORDED_AT_COLUMN}  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY ({BOOK_ID_COLUMN}, {REBALANCE_TS_COLUMN})
)
"""

#: The write.  ``recorded_at`` is left to the table's own default — one clock,
#: the database's — so the row's stamp is the store's rather than a caller's
#: process's, the writer contract every table in this workspace states.
_INSERT_SQL = (
    f"INSERT INTO {REBALANCE_TARGET_WEIGHTS_TABLE} "
    f"({BOOK_ID_COLUMN}, {REBALANCE_TS_COLUMN}, {WEIGHTS_COLUMN}, "
    f"{SIGNAL_IDS_COLUMN}) VALUES (?, ?, ?, ?)"
)

#: One rebalance's row, column by column rather than ``SELECT *``: the order
#: :meth:`RebalanceTargetWeightsStore._from_row` reads must be the order this
#: names, and a future migration that appends a column must not silently shift
#: the fields.
_READ_COLUMNS = (
    f"{BOOK_ID_COLUMN}, {REBALANCE_TS_COLUMN}, {WEIGHTS_COLUMN}, "
    f"{SIGNAL_IDS_COLUMN}, {RECORDED_AT_COLUMN}"
)

_READ_ONE_SQL = (
    f"SELECT {_READ_COLUMNS} FROM {REBALANCE_TARGET_WEIGHTS_TABLE} "
    f"WHERE {BOOK_ID_COLUMN} = ? AND {REBALANCE_TS_COLUMN} = ?"
)

#: One book's rebalances, oldest first.  Ordered by the stored instant, which is
#: correct exactly because every row this store writes goes through
#: :func:`_isoformat_utc` — one UTC offset, one format, one width.  A row another
#: tool wrote in another spelling may therefore sort outside where it "should"
#: fall, and that is the safe direction: it is read back through
#: :meth:`RebalanceTargetWeightsStore._from_row`, which refuses a spelling this
#: store cannot order rebalances by.
_READ_BOOK_SQL = (
    f"SELECT {_READ_COLUMNS} FROM {REBALANCE_TARGET_WEIGHTS_TABLE} "
    f"WHERE {BOOK_ID_COLUMN} = ? ORDER BY {REBALANCE_TS_COLUMN}"
)


# -- Validation -------------------------------------------------------------------


def _validated_book_id(value: Any) -> str:
    """Return ``value`` as a book identity, or refuse what cannot be one.

    Non-empty text, stripped — the near-miss a trailing newline or an indented
    copy would otherwise persist as a *second* book against a table whose whole
    identity is one row per book per rebalance, the discipline
    :func:`regime.coverage._validated_stratum` states for its own key.  Nothing
    else is normalised: a book's identity is its deployment's configuration, and
    a store that case-folded or re-spelled one would be silently renaming the
    book the order path hashes into its ``client_order_id``.
    """
    if not isinstance(value, str) or not value.strip():
        raise RebalanceRequestError(
            f"a book must be named by non-empty text — got {value!r} "
            f"({type(value).__name__}); the rebalance record's identity is one "
            "row per book per rebalance, and a name that states nothing names "
            "no book for which a target weight set could be recorded "
            "(feature 309)"
        )
    return value.strip()


def _validated_instant(value: Any) -> datetime:
    """Return ``value`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* a rebalance happened, and
    a record keyed by one would file two books' rebalances in one order or none
    — the same discipline :func:`router.submission_health._require_aware` holds
    its caller to, and the reason it is checked here rather than assumed.
    """
    if not isinstance(value, datetime):
        raise RebalanceRequestError(
            "the rebalance's instant must be a datetime, not "
            f"{type(value).__name__}; the record is keyed by the rebalance's "
            "own instant — the one the order path is about to submit under — "
            "and it must say unambiguously when the rebalance was for "
            "(feature 309)"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise RebalanceRequestError(
            f"the rebalance's instant must be timezone-aware — got {value!r}; a "
            "naive timestamp cannot say when a rebalance was for, and two books' "
            "rebalances would be filed in one order or none (feature 309)"
        )
    return value


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    The reads compare these strings lexicographically and the primary key
    compares them for equality, which is correct exactly because every row this
    store writes goes through here: one UTC offset, one format, one width.  It
    is what makes the rebalance's identity a pair rather than a pair of
    spellings — ``12:00+02:00`` and ``10:00+00:00`` are one instant and must be
    one row.
    """
    return moment.astimezone(UTC).isoformat()


def _validated_weights(weights: Any) -> dict[str, float]:
    """Read a symbol-to-weight mapping as the set to persist, or refuse it.

    The surface feature 303's :class:`book.TargetWeights` and feature 305's
    :class:`book.FinalTargetWeights` carry — one weight per symbol — and the
    reader is restated here rather than imported from :mod:`book._publish` for
    the reason every store in this workspace restates its URL translation: a
    module never reaches into a sibling's private reader, so a later change to
    one module's value handling cannot silently move another's, and a caller's
    ``except RebalanceRequestError`` must not be defeated by a refusal raised
    out of feature 305's own class.

    Every scalar check is the shape this member's other readers state: a
    ``bool`` is a flag where a magnitude belongs, and a ``nan`` / ``inf`` weight
    is not a size any venue could hold.  A set whose weights are all zero is
    **not** refused: *hold nothing* is a decision a rebalance is entitled to
    record (feature 303 answers exactly that set for a zero configured target,
    and feature 304 admits it at every limit of zero or more), and refusing it
    would report a risk appetite's own consequence as a malformed ask.
    """
    if not isinstance(weights, Mapping):
        raise RebalanceRequestError(
            "a rebalance target weight set is a mapping of symbol to weight — "
            f"got {type(weights).__name__} ({NO_BOOK_CODE}); the record holds a "
            "book one symbol at a time, and a value that is not a mapping names "
            "no set to persist"
        )
    if not weights:
        raise RebalanceRequestError(
            "a rebalance target weight set covers at least one symbol — got "
            f"none ({NO_BOOK_CODE}); a recorded set covering no symbols is the "
            "absence of a book rather than a book held flat — a flat book is "
            "every symbol weighted 0.0, and that one is recorded"
        )
    validated: dict[str, float] = {}
    for symbol, weight in weights.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise RebalanceRequestError(
                "a rebalance target weight set must be keyed by non-empty "
                f"symbol names — got {symbol!r}; the order path routes an "
                "instruction to a symbol, and a position cannot be attributed "
                "to a name the recorded set does not carry"
            )
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise RebalanceRequestError(
                f"the target weight for symbol {symbol!r} must be a finite real "
                f"— got {weight!r} ({type(weight).__name__}); a weight that is "
                "not a number is not a size any venue could hold, and the order "
                "layer would have to invent one"
            )
        number = float(weight)
        if not math.isfinite(number):
            raise RebalanceRequestError(
                f"the target weight for symbol {symbol!r} is not finite "
                f"({weight!r}); a NaN or ±inf would reach the venue dressed as a "
                "position, and no rounding to a venue's step size could make one "
                "of it"
            )
        validated[symbol] = number
    return validated


def _settled_signal_ids(identifiers: Iterable[str]) -> tuple[str, ...]:
    """Settle a sequence of promoted signal identifiers — sorted, distinct, real.

    The one reading both paths take — the caller's signals, whose ``signal_id``
    is read off each value first, and a stored row's JSON array — so the ask's
    own facts and the row's are checked by the same law and cannot disagree
    about whether a provenance is well formed.

    Sorted and distinct because a provenance is a **set**: sorting makes one
    spelling of it, which is what lets two records of one provenance compare
    equal for the idempotent re-issue, and it is the same argument feature 305
    makes for emitting its weights sorted.  A duplicate is refused rather than
    folded with feature 301's own ``duplicate_signal`` word: the book was
    weighted by one signal, and a provenance naming it twice is a malformed set
    of identifiers rather than a second weighting.  An identifier that states
    nothing is refused for the reason a stratum name or a process identity is —
    a near-miss like a trailing newline would be a second identifier against a
    record whose whole value is that the provenance can be matched back to the
    signals.
    """
    settled: list[str] = []
    for identifier in identifiers:
        if not isinstance(identifier, str) or not identifier.strip():
            raise RebalanceRequestError(
                "every originating promoted signal must be identified by "
                f"non-empty text — got {identifier!r} "
                f"({type(identifier).__name__}); the recorded provenance is only "
                "worth writing down if each identifier names the signal the set "
                "came from (feature 309)"
            )
        settled.append(identifier.strip())
    if not settled:
        raise RebalanceRequestError(
            "a recorded target weight set must name at least one originating "
            f"promoted signal — got none ({NO_ORIGINATING_SIGNALS_CODE}); the "
            "sentence pairs the set with the signals it originated from, and a "
            "set recorded with no provenance is the absence of one rather than a "
            "provenance that happens to be empty — hand the promoted signals the "
            "set was combined from, and this act reads their ``signal_id``"
        )
    ordered = tuple(sorted(settled))
    for previous, following in itertools.pairwise(ordered):
        if previous == following:
            raise RebalanceRequestError(
                f"duplicate_signal: the originating promoted signals name "
                f"{previous!r} twice; a provenance is the set of signals that "
                "weighted the book, and the book was weighted by one signal — "
                "hand each promoted signal once (feature 309)"
            )
    return ordered


def _originating_signal_ids(signals: Any) -> tuple[str, ...]:
    """Read the provenance off the promoted signals the set originated from.

    ``signals`` is the caller's own promoted signals — :class:`book.PromotedSignal`
    values, or any values exposing the same ``signal_id`` surface, because a
    member never isinstance-gates the value a composition seam hands out: the
    loader imports every member under a synthetic name, so a signal this process
    composed may be a second class object.  This is the same duck-typed read
    feature 301's :func:`book.combine` performs on the same values, which is the
    point: the provenance is read off the signals that weighted the book rather
    than retyped beside it, so nothing can be recorded that no value claims.

    A ``str`` (or ``bytes``) is refused up front rather than iterated: a
    provenance of *names* is exactly the shape this read exists to make
    impossible — "momentum" is one signal's name, not three signals named
    ``m``, ``o`` and ``m`` — and the refusal says so rather than reporting a
    character with no ``signal_id``.
    """
    if isinstance(signals, (str, bytes)):
        raise RebalanceRequestError(
            "the originating promoted signals are the signals themselves, not "
            f"their names — got {signals!r}; a name is a claim that nothing can "
            "check against the book, while a signal carries the ``signal_id`` "
            "this record reads, so hand the promoted signals feature 301 "
            "combined (feature 309)"
        )
    try:
        iterator = iter(signals)
    except TypeError:
        raise RebalanceRequestError(
            "the originating promoted signals must be an iterable of promoted "
            f"signals — got {signals!r} ({type(signals).__name__}), which is "
            f"not iterable ({NO_ORIGINATING_SIGNALS_CODE}); the sentence pairs "
            "the set with the signals it originated from, and this act reads "
            "each one's ``signal_id``"
        ) from None
    identifiers: list[Any] = []
    for signal in iterator:
        identifier = getattr(signal, "signal_id", _MISSING)
        if identifier is _MISSING:
            raise RebalanceRequestError(
                "every originating promoted signal carries a ``signal_id`` to "
                f"attribute the set to — got {signal!r} "
                f"({type(signal).__name__}), which carries none; the provenance "
                "of a rebalance is the identifiers of the signals that weighted "
                "it, and a value that cannot be named cannot be recorded as one "
                "(feature 309)"
            )
        identifiers.append(identifier)
    return _settled_signal_ids(identifiers)


def _weights_to_json(weights: Mapping[str, float]) -> str:
    """The set as one JSON object — the one byte spelling of it.

    ``sort_keys`` and the compact separators so two writes of the same set
    produce identical bytes, which is what makes the row's content comparable
    rather than merely equal.  Floats serialise as their ``repr``, which
    round-trips exactly, so a read-back is an exact comparison rather than a
    tolerant one.
    """
    return json.dumps(dict(weights), sort_keys=True, separators=(",", ":"))


def _signal_ids_to_json(signal_ids: Iterable[str]) -> str:
    """The provenance as one JSON array — sorted, distinct, one spelling."""
    return json.dumps(list(signal_ids), separators=(",", ":"))


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation every store in this workspace restates — the reason
    :func:`regime.coverage._sqlite_path` gives for restating it is this module's
    too: a store reaches into no sibling's private helper, so a later change to
    one table's address handling cannot silently move another's.
    ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is absolute, and a
    non-SQLite scheme, a URL carrying a host and a pathless URL are refused by
    name.  An in-memory database is refused as well, and for this feature's own
    reason: a rebalance record must outlive the call that wrote it — the order
    path reads it back on a retry, and an audit reads it long afterwards, both
    from another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RebalanceStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the rebalance "
            "records live in (feature 309)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RebalanceStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 309)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RebalanceStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "record would die with the connection that opened it, and a rebalance "
            "target weight set must outlive the call that recorded it — the order "
            "path reads it back on a retry and an audit reads it afterwards, both "
            "from another process (feature 309)"
        )
    return Path(path)


# -- The record -------------------------------------------------------------------


@dataclass(frozen=True)
class RebalanceTargetWeights:
    """One rebalance's recorded target weight set, with its provenance.

    The five fields are the table's five columns: the book, the rebalance's
    instant, the set, the identifiers of the promoted signals it originated
    from, and the database's own stamp of when the row was written.  Frozen, so
    a record that has been read back cannot be edited into a different set by a
    caller who kept a reference — the discipline
    :class:`regime.coverage.CoverageCount` and
    :class:`discovery.campaign.CampaignRecord` state, and for the same reason:
    this value *is* the record of what the book was aimed at, and a mutable one
    would let a caller retype a rebalance in memory while the row said
    otherwise.  On this record the guarantee carries the sentence's own subject,
    because the row is the only record there is: nothing downstream re-derives
    it, and no bound re-runs.

    Validated in :meth:`__post_init__` rather than only through the store,
    because ``dataclasses.replace`` and unpickling both rebuild instances past a
    factory's nose — and because the *read* path needs the same check the write
    path does, since SQLite's columns are dynamically typed and a corrupt row is
    reachable here.  The store re-raises a validation refusal naming the book and
    the instant the row came from (see
    :meth:`RebalanceTargetWeightsStore._from_row`).
    """

    #: The book the rebalance was for — the deployment's identity for it.
    book_id: str
    #: The rebalance's instant, timezone-aware and held in UTC.
    rebalance_ts: datetime
    #: The target weight set — the book the construction built, keyed by symbol
    #: in sorted order so two readings of one row answer identical values.
    weights: Mapping[str, float]
    #: The identifiers of the promoted signals the set originated from, sorted
    #: and distinct.  A ``tuple`` rather than a list so the record is hashable
    #: and the set cannot be appended to after it was read.
    signal_ids: tuple[str, ...]
    #: When the row was written — the database's own stamp, read back.  Not
    #: parsed on this side: the honest check is only that the ``NOT NULL``
    #: column carried *something*, and a NULL stamp is a row this store could
    #: not have written.
    recorded_at: Any

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the strip and
        # the UTC normalization below are normalization rather than mutation of
        # the caller's values, and they are the only writes this object ever
        # takes.  The instant is held in UTC on the record as well as in the row
        # so that what a caller holds and what the primary key says are the same
        # instant, whatever offset the caller's value carried.
        object.__setattr__(self, "book_id", _validated_book_id(self.book_id))
        object.__setattr__(
            self, "rebalance_ts", _validated_instant(self.rebalance_ts).astimezone(UTC)
        )
        object.__setattr__(self, "weights", MappingProxyType(_validated_weights(self.weights)))
        object.__setattr__(self, "signal_ids", _settled_signal_ids(self.signal_ids))
        if self.recorded_at is None:
            raise RebalanceStoreError(
                f"the rebalance record for book {self.book_id!r} at "
                f"{_isoformat_utc(self.rebalance_ts)} carries no "
                f"{RECORDED_AT_COLUMN}; the table declares the column NOT NULL "
                "because a record without the moment it was written is not "
                "evidence, so a record without one is not a row this store can "
                "have written (feature 309)"
            )

    def weight(self, symbol: str) -> float:
        """The recorded target weight for one symbol — the set's figure for it.

        Refuses with :class:`~book.errors.RebalanceRequestError` a symbol the set
        does not cover, rather than answering a fabricated zero: a symbol the set
        carries no weight for is not a symbol this rebalance aimed at, and a zero
        would read as *hold none of it* — a position decision the construction
        never made.  The message opens with the same ``uncovered_symbol`` word
        feature 301's ``CompositeBook.target_score``, feature 303's
        :meth:`book.TargetWeights.weight` and feature 305's
        :meth:`book.FinalTargetWeights.weight` answer with, because it is the same
        fact about the same surface read all the way to the record of it.
        """
        try:
            return self.weights[symbol]
        except KeyError:
            raise RebalanceRequestError(
                f"uncovered_symbol: the recorded target weight set for book "
                f"{self.book_id!r} holds no weight for symbol {symbol!r}; the "
                f"set covers {sorted(self.weights)}"
            ) from None

    @property
    def symbols(self) -> tuple[str, ...]:
        """The symbols the recorded set is held at, sorted.

        Derived from :attr:`weights` rather than stored, so it can never disagree
        with the set it summarises — the discipline
        :attr:`book.FinalTargetWeights.symbols` states for its own derived
        figure.
        """
        return tuple(sorted(self.weights))

    @property
    def gross_exposure(self) -> float:
        """The recorded set's gross exposure, ``Σ_s |w_s|`` — the recorded size.

        Derived, like :attr:`symbols`, and for the same reason.  A flat set's
        gross exposure is ``0.0``, which is the honest reading of *hold nothing*
        rather than a missing measurement: the weights exist and they sum to
        nothing.
        """
        return math.fsum(abs(weight) for weight in self.weights.values())

    def originated_from(self, signal_id: str) -> bool:
        """Whether this set's provenance names one promoted signal.

        The sentence's own pairing, made answerable off the record: an auditor
        asking *"did the momentum signal weight this rebalance?"* reads it here
        rather than re-reading the JSON column.  A plain membership test over the
        sorted identifiers — the record already refused a malformed provenance at
        construction, so there is nothing to validate and nothing to settle: the
        answer is a fact about the record.
        """
        return signal_id in self.signal_ids

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`regime.coverage.CoverageCount.row` states: a rendered mapping
        names the same things the same way the row does.  The two JSON columns
        are rendered as their stored text, so what a caller sees here is what an
        operator at a sqlite3 prompt would see.
        """
        return {
            BOOK_ID_COLUMN: self.book_id,
            REBALANCE_TS_COLUMN: _isoformat_utc(self.rebalance_ts),
            WEIGHTS_COLUMN: _weights_to_json(self.weights),
            SIGNAL_IDS_COLUMN: _signal_ids_to_json(self.signal_ids),
            RECORDED_AT_COLUMN: self.recorded_at,
        }


# -- The store --------------------------------------------------------------------


class RebalanceTargetWeightsStore:
    """Reads and appends this member's rebalance record: one row per rebalance.

    Constructed with the database URL the records live in;
    :meth:`record` persists one rebalance's set with its provenance, :meth:`get`
    reads one rebalance's record back, and :meth:`history` reads one book's
    rebalances in the order they were for.  Construction performs no I/O, so
    composing an application never touches the database and a store costs nothing
    until a rebalance is recorded — the contract every store in this workspace
    states.

    The store holds no cache of the rows it wrote: the row is the only record of
    what the book was aimed at, so it is the only thing an answer is drawn from —
    the stance :class:`regime.coverage.RegimeCoverage` states for its own reads,
    and for the same reason.  A memo of persisted sets would make *"what did we
    target at that rebalance?"* a question about this process's history rather
    than about the record, and the order path that reads it back on a retry runs
    in another process entirely.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the records live in.

        The URL is validated here, before any call, because it is a fact about
        the *store* rather than about any one rebalance: a URL that is not a
        non-empty string names no store, and a store that accepted one would fail
        identically on every persist — the wrong place for a deployment to
        discover a wiring fault.  The URL's *scheme* is not checked here, though:
        that is :func:`_sqlite_path`'s job on first use, so constructing a store
        touches no disk and refuses nothing a later call would not.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise RebalanceStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL; the "
                "rebalance record is a table in the database the deployment "
                "names, and a store pointed at nothing has nowhere to persist a "
                "target weight set (feature 309)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RebalanceTargetWeightsStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which records no
        rebalance — a discoverable state, not an exception, the stance every
        store in this workspace takes — while a caller that *must* record a
        rebalance before the order path reads it back is the caller that must not
        find itself in it.

        This is how the member reaches the store, beside the combiner the way
        :meth:`regime.coverage.RegimeCoverage.resolve` sits beside its member's
        own acts: there is no second component and no seat accessor, because a
        builder runs with no arguments and must not fail composition, and the
        combiner's whole configuration is its arithmetic.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and writes."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the records' database, ensuring the table exists.

        ``CREATE TABLE IF NOT EXISTS``, created idempotently by the only module
        that writes this table, so a fresh database and one that has been
        written to before take the same path and no migration step is needed.
        The caller owns the connection; use it as a context manager to commit,
        which is what every write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Feature 309: the persist --------------------------------------------

    def record(
        self,
        *,
        book_id: Any,
        rebalance_ts: Any,
        target_weights: Any,
        originating_signals: Any,
    ) -> RebalanceTargetWeights:
        """Persist one rebalance's target weight set with its provenance — 309's act.

        Feature 309's verb: *System persists each rebalance target weight set
        with its originating promoted signal identifiers.*  ``target_weights`` is
        the set the construction built — a :class:`book.FinalTargetWeights`, a
        :class:`book.TargetWeights`, or any value exposing the same ``weights``
        mapping of symbol to weight, read duck-typed; ``originating_signals`` is
        the promoted signals it was combined from, whose ``signal_id`` this act
        reads.  ``book_id`` and ``rebalance_ts`` are the rebalance's identity —
        §13.2's own pair, read at its head — and both are **required** keywords
        with no default: a book id would be a deployment's identity invented by
        this member, and a default instant of *now* would make the row's identity
        the moment somebody called rather than the rebalance it was for, so a
        retry would land under a different identity.

        The steps, in the order they must happen, each refusal leaving the
        database untouched:

        (1) settle the ask — the book id, the instant, the set and the provenance
        — **before** anything is opened, so a malformed persist is refused
        without touching a database, the ordering every verdict and act in this
        workspace states;
        (2) read the rebalance's standing row.  The table is keyed by the
        rebalance, so that row is the whole of what the store knows about it;
        (3) **insert** when the rebalance has no row, and read the row back
        inside the same transaction so the answer's stamp is the table's own;
        (4) **answer the standing row untouched** when it holds the same set and
        the same provenance.  A re-issue is the same call arriving twice — a
        reclaimed spot instance, a loop that re-ran its rebalance step — and the
        set did not change, so the instant it was recorded did not either.  The
        idempotence is a *content* test, both halves: a set re-issued with a
        different provenance is a different record of the same rebalance, and the
        provenance is what this feature exists to keep;
        (5) **refuse** with :class:`~book.errors.RebalanceRewriteError` and
        :data:`REBALANCE_RECORDED_CODE` when the standing row holds anything
        else.  Two target weight sets for one rebalance instant leave every
        reader of this table choosing between them, and the row is the only
        record there is — no bound re-runs and no act re-applies — so a silent
        overwrite would be a rebalance nobody decided, recorded as though
        somebody had.  The repair is the caller's: record the set under the
        instant it was actually computed for.  This method reconciles nothing and
        overwrites nothing.

        Returns the record that stands in the table — the value that landed, or
        the value that was already there — so a caller logging the rebalance
        holds the row rather than a re-derivation of it.  Fails with
        :class:`~book.errors.RebalanceStoreError` when the configured store could
        not take the row: a rebalance the system computed and could not write down
        is exactly the gap this feature closes.
        """
        # The ask is settled whole — and in this order, the identity first —
        # before a connection is opened: a malformed persist is refused without
        # touching a database, with no row left behind and no half-written set.
        wanted = _validated_book_id(book_id)
        instant = _validated_instant(rebalance_ts)
        weights = _weight_set_of(target_weights)
        signal_ids = _originating_signal_ids(originating_signals)
        standing = self._read_one(wanted, instant)
        if standing is None:
            return self._insert(wanted, instant, weights, signal_ids)
        if _same_set(standing, weights, signal_ids):
            return standing
        raise RebalanceRewriteError(
            f"{REBALANCE_RECORDED_CODE}: the rebalance for book {wanted!r} at "
            f"{_isoformat_utc(instant)} is already recorded with a different "
            f"target weight set — the standing record (weights "
            f"{dict(standing.weights)!r}, originating signals "
            f"{list(standing.signal_ids)!r}) was written at "
            f"{standing.recorded_at!r}, and what this call offers is (weights "
            f"{weights!r}, originating signals {list(signal_ids)!r}). Feature 309 "
            "persists *each* rebalance's set with its originating promoted signal "
            "identifiers, so one rebalance has one row: two sets for one instant "
            "leave every reader of this record choosing between them, and nothing "
            "downstream re-derives it. This store overwrites nothing — record the "
            "set under the instant it was actually computed for"
        )

    def _insert(
        self,
        book_id: str,
        instant: datetime,
        weights: Mapping[str, float],
        signal_ids: tuple[str, ...],
    ) -> RebalanceTargetWeights:
        """Write one absent rebalance's row and answer the table's own version.

        The read-back is inside the same transaction as the write, so the stamp
        in the answer is the database's clock rather than anything this process
        holds — the discipline :meth:`regime.coverage.RegimeCoverage.record`
        states for its own vintage, and the reason ``recorded_at`` is left to the
        column's default and never passed to the insert.  The record is built
        *from the row* rather than from the caller's values, so the answer is what
        the table holds rather than what this process meant.
        """
        key = (book_id, _isoformat_utc(instant))
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _INSERT_SQL,
                    (
                        book_id,
                        _isoformat_utc(instant),
                        _weights_to_json(weights),
                        _signal_ids_to_json(signal_ids),
                    ),
                )
                row = connection.execute(_READ_ONE_SQL, key).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RebalanceStoreError(
                f"could not persist the rebalance target weight set for book "
                f"{book_id!r} at {_isoformat_utc(instant)}: {exc}"
            ) from exc
        if row is None:
            raise RebalanceStoreError(
                f"the rebalance target weight set for book {book_id!r} at "
                f"{_isoformat_utc(instant)} was written and could not be read "
                "back in the transaction that wrote it; the record is the only "
                "evidence this feature produces, so a write that cannot be read "
                "is not one this store can report (feature 309)"
            )
        return self._from_row(row)

    def _read_one(self, book_id: str, instant: datetime) -> RebalanceTargetWeights | None:
        """One rebalance's row, or ``None`` when the rebalance has none.

        ``None`` rather than a raised miss: a rebalance that has not been recorded
        is a fact this act is *asking about* — it is how :meth:`record` decides
        between the insert and the rewrite refusal — and it is also what
        :meth:`get` answers.  The row is addressed by the canonical spelling the
        write path uses, so the read cannot miss a row the write landed.
        """
        key = (book_id, _isoformat_utc(instant))
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_READ_ONE_SQL, key).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RebalanceStoreError(
                f"could not read the rebalance record for book {book_id!r} at "
                f"{_isoformat_utc(instant)}: {exc}"
            ) from exc
        if row is None:
            return None
        return self._from_row(row)

    def get(self, *, book_id: Any, rebalance_ts: Any) -> RebalanceTargetWeights | None:
        """One rebalance's recorded set and provenance, or ``None``.

        The read a caller takes when it wants to know *what did we target at that
        rebalance, and which signals put it there?*  ``None`` is the honest answer
        for a rebalance that was never recorded — deliberately not a default or a
        zeroed set, since a rebalance nobody wrote down is a different fact from
        one recorded flat, and the whole point of this feature is that the second
        is evidence and the first is a gap.

        Both keywords are validated here rather than only inside the record
        builder, because a malformed ask must be refused as the ask's own fact
        whether or not a row exists to read.
        """
        return self._read_one(
            _validated_book_id(book_id), _validated_instant(rebalance_ts)
        )

    def history(self, book_id: Any) -> tuple[RebalanceTargetWeights, ...]:
        """One book's recorded rebalances, oldest first.

        The reading the sentence's *each* is checked against: every rebalance the
        book has been through that the system wrote down, in the order they were
        for.  Ordered by the stored instant rather than by insertion, because the
        rebalance's instant *is* the order the book was aimed in — a backfill that
        recorded an older rebalance after a newer one answers in the right place.

        An empty tuple for a book with no records at all: the honest answer for a
        book that has never rebalanced, and not an error — unlike the *ask*, which
        is refused by name when the book id states nothing.
        """
        wanted = _validated_book_id(book_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(_READ_BOOK_SQL, (wanted,)).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RebalanceStoreError(
                f"could not read the rebalance history of book {wanted!r}: {exc}"
            ) from exc
        return tuple(self._from_row(row) for row in rows)

    def _from_row(self, row: tuple) -> RebalanceTargetWeights:
        """Rebuild one stored row, refusing a value no record can be.

        The refusal is the point: this table is written by this store, but SQLite
        will accept anything another tool inserts, and a row whose ``weights`` or
        ``signal_ids`` does not decode would otherwise be read as a *smaller* book
        or an *empty* provenance — the direction that erases the very pairing this
        feature exists to record.  A decode that fails, a JSON value of the wrong
        shape, and a value-level refusal are all re-raised as
        :class:`~book.errors.RebalanceStoreError` naming the book and the instant
        the row came from, so an operator can find the offending row without a
        second query.

        The class is the *store's* rather than the ask's on purpose: the
        validators below refuse a malformed *ask*, and a row this table holds is
        not an ask — the caller did not hand it over, the store's own table did,
        and the repair is *repair the row* rather than *fix what you passed*.  The
        same place :func:`regime.coverage._validated_world_count`'s refusal is
        re-raised naming the stratum.
        """
        (
            book_id,
            rebalance_ts_raw,
            weights_raw,
            signal_ids_raw,
            recorded_at,
        ) = row
        what = f"book {book_id!r} at {rebalance_ts_raw!r}"
        try:
            moment = datetime.fromisoformat(rebalance_ts_raw)
        except (TypeError, ValueError) as exc:
            raise RebalanceStoreError(
                f"the rebalance row for {what} carries {rebalance_ts_raw!r}, "
                "which is not an ISO 8601 moment this store can order rebalances "
                "by (feature 309)"
            ) from exc
        try:
            return RebalanceTargetWeights(
                book_id=book_id,
                rebalance_ts=moment,
                weights=_weights_from_json(weights_raw, what=what),
                signal_ids=_signal_ids_from_json(signal_ids_raw, what=what),
                recorded_at=recorded_at,
            )
        except RebalanceRequestError as refusal:
            # The value layer validates the row, and this re-raise is what makes
            # the refusal *findable*: the record sees one row and cannot know
            # which one, while a reader holding the history can name the book and
            # the instant — so an operator gets the row to repair rather than a
            # complaint about a value with no address.
            raise RebalanceStoreError(
                f"{refusal} — the row this came from is the rebalance for {what} "
                "(feature 309)"
            ) from refusal


# -- The row's two JSON columns, read back ----------------------------------------


def _weights_from_json(raw: Any, *, what: str) -> dict[str, float]:
    """One stored ``weights`` column, back as the set it was written from.

    The columns are rebuilt rather than summarised — there is no derived total,
    no symbol count and no hash beside them to disagree with the set — so this
    decode *is* the value, and a row that will not decode is refused rather than
    read as a smaller book.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RebalanceStoreError(
            f"the rebalance row for {what} carries a {WEIGHTS_COLUMN} column that "
            f"is not JSON ({raw!r}); the set is stored whole so that a partially "
            "written book cannot read back as a smaller one, which means a column "
            "that will not decode is a row no reader can report (feature 309)"
        ) from exc
    if not isinstance(parsed, dict):
        raise RebalanceStoreError(
            f"the rebalance row for {what} carries a {WEIGHTS_COLUMN} column that "
            f"is not a JSON object ({raw!r}); a target weight set is one weight "
            "per symbol, and no other shape is a book (feature 309)"
        )
    return _validated_weights(parsed)


def _signal_ids_from_json(raw: Any, *, what: str) -> tuple[str, ...]:
    """One stored ``signal_ids`` column, back as the provenance it records.

    A JSON array of strings and nothing else — the shape this store writes — and
    an empty array is refused by the same settled reading that refuses an empty
    ask, because a row carrying no provenance is a corrupted record rather than a
    rebalance that originated from nothing.
    """
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RebalanceStoreError(
            f"the rebalance row for {what} carries a {SIGNAL_IDS_COLUMN} column "
            f"that is not JSON ({raw!r}); the provenance is what this record "
            "exists to pair with the set, so a column that will not decode is a "
            "row no reader can report (feature 309)"
        ) from exc
    if not isinstance(parsed, list):
        raise RebalanceStoreError(
            f"the rebalance row for {what} carries a {SIGNAL_IDS_COLUMN} column "
            f"that is not a JSON array ({raw!r}); the provenance is the set of "
            "promoted signal identifiers the set originated from, and no other "
            "shape is one (feature 309)"
        )
    return _settled_signal_ids(parsed)


# -- The one record builder, shared by the write path and the read path -----------


def _weight_set_of(target_weights: Any) -> dict[str, float]:
    """Read a value's ``weights`` as the set to persist, or refuse it.

    The surface feature 305's :class:`book.FinalTargetWeights` carries — the very
    value the order layer consumes — read duck-typed, so any value exposing
    ``weights`` is a set here whatever composed it.  The sentinel keeps *this is
    not a book* apart from *this book covers no symbols*: different repairs, so
    different reports, and both carry feature 305's own
    :data:`book.NO_BOOK_CODE` because each means the same thing to the caller —
    what it meant to write down is not a book.
    """
    weights = getattr(target_weights, "weights", _MISSING)
    if weights is _MISSING:
        raise RebalanceRequestError(
            "a rebalance target weight set is the construction's book — got "
            f"{target_weights!r} ({type(target_weights).__name__}), which "
            f"carries no ``weights`` ({NO_BOOK_CODE}); record the published book "
            "the order layer consumes (feature 305's final_target_weights "
            "answer), or any value exposing the same ``weights`` mapping of "
            "symbol to weight, and this act writes it down with the signals it "
            "came from"
        )
    return _validated_weights(weights)


def _same_set(
    standing: RebalanceTargetWeights,
    weights: Mapping[str, float],
    signal_ids: tuple[str, ...],
) -> bool:
    """Whether a standing row already records exactly what this call offers.

    The idempotence test, and it is deliberately a *content* test on both halves:
    equal weights (compared as the ``float`` values both sides were rebuilt to,
    which is exact because the stored spelling round-trips) **and** an equal
    provenance.  A re-issue that changed the provenance is a different record of
    the same rebalance, and the provenance is half of what this feature exists to
    write down — so it is refused as a rewrite rather than waved through as a
    retry.  The book and the instant are equal by construction: the standing row
    was addressed by the key this call offered.
    """
    return dict(standing.weights) == dict(weights) and standing.signal_ids == tuple(
        signal_ids
    )
