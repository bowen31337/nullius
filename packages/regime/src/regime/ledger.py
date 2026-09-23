"""The coverage ledger's reader — feature 284.

app_spec.xml, "Regime Coverage Strata", feature 284: *System returns the
current coverage ledger showing stored world counts for every named
stratum.*  Feature 283's store (:mod:`regime.coverage`) is the ledger's
*writer* — one :meth:`~regime.coverage.RegimeCoverage.record` per stratum,
idempotent by name, with the vintage the table itself mints.  This module
is the other half of that one table: the read that answers with the
ledger **as a whole**.  docs/alpha-engine-prd.md §C7 draws the ledger as
one object — *"Maintain an explicit ledger: ``{high-vol trend: 2,
low-vol chop: 14, crash: 0, …}``"* — and the counting half is only
useful if the whole count is readable at a glance: *"run six months in
low-vol chop and your entire pool is low-vol chop"* is a statement about
the distribution, and a distribution is not visible one stratum at a
time.

**Why this is a second verb and not feature 283's ``get`` in a loop.**
:meth:`~regime.coverage.RegimeCoverage.get` answers *what does this
stratum hold?* for a caller that already holds a name — the promotion
gate asking after its deployment regime (feature 285).  Feature 284's
sentence asks the opposite question: *what does the ledger hold?* for a
caller that holds no name at all.  Looping ``get`` over a vocabulary
would answer it wrongly, and the way it fails is the point of the whole
category.  A loop over :data:`~regime.coverage.DEFAULT_STRATA` reports
only the three names somebody wrote down; a deployment whose labeler
carves five strata has five rows, and the fourth and fifth would be
invisible to every reader that asked the default three — the *exact*
blindness §C7's ledger exists to cure, reintroduced by the read that was
supposed to cure it.  Worse, the two states ``0107`` is built to keep
apart would collapse: a stratum the loop asked after and the table
answered ``None`` for (nobody named it) is indistinguishable, in the
loop's output, from a stratum the loop never asked about.  So this module
reads the **table**, not a vocabulary: one ``SELECT`` over every row the
ledger holds, in name order, and the vocabulary appears only where it
honestly belongs — in :meth:`CoverageLedger.holes`, which is a caller
*asking a question of* a ledger it can now see whole.

**The ledger is a value, and the answer is the ledger.**  The read
answers with a :class:`CoverageLedger` — the rows the table holds, sorted
by stratum, plus the three derived views the category's later features
are written against, and no cached state of its own.  The shape every
store in this workspace states is that the row is the record; the shape
here is its whole-table spelling.  Nothing in this module remembers a
ledger between calls, because a memo would make *"what does the pool hold
now?"* a question about this process's history: the census (feature 290)
and the backfill (287) write new counts from other callers, §C6's
tripwires excise worlds between reads, and the endpoint that publishes
this ledger (feature 343) and the promotion gate that blocks on it (285)
run in other processes entirely.  A ledger read is a question about the
*table*, and the only honest answer is the one the table just gave.

**The named-empty row and the absent one, kept apart on this side too.**
``0107`` detail 1 is the load-bearing distinction under this read: a
stratum named and holding no worlds is a row with ``world_count = 0``
(§C7's own example writes ``crash: 0``), while a stratum nobody named has
no row at all.  A whole-ledger read is exactly where those two would
collapse — *"the stratum is not in the ledger"* is a tempting way to
write "zero" — so this module refuses to let them.  A named-empty stratum
comes back as a :class:`~regime.coverage.CoverageCount` you can hold, and
:attr:`CoverageLedger.empty` is the tuple of them; an unnamed stratum is
**absence from** :attr:`CoverageLedger.rows`, and
:meth:`CoverageLedger.holes` is the only thing that turns that absence
into something nameable, by taking the vocabulary as an argument and
answering with the names it did not find.  That is why
:class:`CoverageHole` is a distinct type rather than a ``CoverageCount``
with a zero in it: *named and empty* and *never named* are different
facts, feature 286's ``empty_stratum`` warning fires on the first and
must not fire on the second, and a single type carrying both would make
that mistake available to every caller that reached for the obvious
attribute.

**The vocabulary is the caller's, and it stays open.**  Feature 283
states the law from the writer's side — ``0107`` stores whatever names
the plugin writes and does not enumerate them, because the day the
stratum set changes is a configuration change in the labeler — and this
read does not close it.  Nothing here enumerates a stratum set, refuses a
name outside
:data:`~regime.coverage.DEFAULT_STRATA`, or requires the ledger to be any
size.  A three-stratum ledger, a five-stratum ledger and a ledger holding
one name a deployment invented are all ledgers, and all read the same
way.  The default three appear here for one purpose only:
:meth:`CoverageLedger.holes` defaults its *vocabulary argument* to them,
so the common call is one word — and even then the argument is a
parameter, because a deployment with five strata asks that question with
its own five.

**Report, never refuse — except about the ask.**  A read has almost
nothing to refuse: an empty ledger is a ledger (a database where no
census has run yet is a discoverable state, not an error), a stratum
holding zero worlds is a fact, and a ledger holding fewer strata than the
vocabulary names is precisely the finding feature 286 and feature 289 are
built to act on.  The refusals that do remain are about the *ask* — a
``DATABASE_URL`` this member cannot speak, a vocabulary that is not a
sequence of distinct names — and about the *data*: SQLite's columns are
dynamically typed, so a raw ``INSERT`` from another tool can land
anything in ``world_count``, and a read that swallowed it would report a
count nobody wrote.  Those refusals are feature 283's own
:class:`~regime.errors.CoverageError`, deliberately: the class already
carries the *row* face and the *address* face for this exact table, and a
second class for reading the rows the first class writes would split one
table's faults across two ``except`` clauses for no gain.

**Stdlib only, and it adds no state to the workspace.**  This module
registers no component.  Feature 283's store is the composed thing — the
table in the database ``DATABASE_URL`` names — and a reader is a *verb on
it* rather than a second seat:
:meth:`~regime.coverage.RegimeCoverage.ledger` is the store's own read,
and :func:`read_ledger` is the module-level spelling for the caller that
holds a URL rather than a store, exactly as
:func:`~regime.coverage.persist_coverage` is the writer's.  The member's
registered surface is still the one store, and the endpoint that will
publish this ledger reads it through the composed component the way the
member's ``__init__`` documents.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from .coverage import (
    COVERAGE_TABLE,
    DATABASE_URL_ENV,
    DEFAULT_STRATA,
    STRATUM_COLUMN,
    UPDATED_AT_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageCount,
    RegimeCoverage,
    _validated_stratum,
    _validated_world_count,
)
from .errors import CoverageError

__all__ = [
    "CoverageHole",
    "CoverageLedger",
    "read_ledger",
]

#: Every row the ledger holds, in name order — the whole-table read
#: feature 284's sentence asks for.
#:
#: ``ORDER BY stratum`` rather than the table's insertion order, for two
#: reasons.  A rowid table's default order is the order rows happened to
#: be written, which is the order the census walked its worlds in and has
#: no claim on being the order a reader wants; and a read whose answer
#: depends on write order would make the ledger's *display* change every
#: time a count crossed zero between censuses, so an operator diffing two
#: readings would see churn where nothing about the pool changed.  The
#: name is the table's primary key and the only stable identity a row
#: has, so it is the order.  :meth:`CoverageLedger.__post_init__` sorts
#: again by the same key, so a hand-built ledger is canonical too and the
#: two orderings cannot disagree — the SQL clause is what keeps the
#: *database's* answer stable, the Python sort is what keeps the *value's*
#: answer stable, and both must hold.
#:
#: The columns are named one by one rather than spelled ``SELECT *``, the
#: discipline :mod:`regime.coverage` states for its own single-row read:
#: the order :meth:`RegimeCoverage._count_from_row` unpacks must be the
#: order this names, and a future migration that appends a column must
#: not silently shift the fields.
_READ_LEDGER_SQL = (
    f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}, {UPDATED_AT_COLUMN} "
    f"FROM {COVERAGE_TABLE} ORDER BY {STRATUM_COLUMN}"
)


# -- The value --------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageHole:
    """A stratum a vocabulary names, which the ledger holds no row for.

    The *never named* fact — and the reason it needs a type of its own is
    the whole of ``0107`` detail 1.  A stratum holding no stored worlds is
    a row with a zero in it, and :attr:`CoverageLedger.empty` answers with
    those rows; a stratum with no row at all is a different fact, and a
    caller that conflated the two would have feature 286's
    ``empty_stratum`` warning firing on a stratum nobody ever configured,
    or — worse, and the commoner mistake — a coverage hole going
    unreported because the ledger it was missing from was read as "no
    worlds" rather than "no such stratum".

    So this is deliberately **not** a
    :class:`~regime.coverage.CoverageCount`: it has no ``world_count``,
    because there is no count it could honestly carry.  Zero would be a
    lie (it says the pool holds none, when the truth is that nobody has
    counted), and ``None`` would put the distinction behind an attribute
    test at every use site.  The type *is* the distinction, and a caller
    holding a :class:`CoverageHole` cannot get it wrong by accident.

    It carries the name and the vintage is nothing, so a caller that
    wants to seat the stratum writes it through
    :meth:`~regime.coverage.RegimeCoverage.name_stratum` — the act that
    lands the named-empty row without asserting a count — and a caller
    that wants a count writes one through ``record``.
    """

    #: The stratum the vocabulary named and the ledger did not.
    stratum: str

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the strip
        # is normalization, not mutation of the caller's value, and it is
        # the only write this object ever takes.  The refusal is feature
        # 283's own, so a vocabulary carrying a name that cannot be one is
        # refused in the vocabulary's terms rather than silently reported
        # as a hole — an empty name is not a stratum the ledger failed to
        # hold, it is not a stratum at all.
        object.__setattr__(self, "stratum", _validated_stratum(self.stratum))

    def row(self) -> dict[str, Any]:
        """The hole as a store-shaped mapping — a fresh dict per call.

        One key, deliberately: the column names are the table's own, the
        discipline every record in this workspace states, and a hole has
        no value for the other two because no row exists to have carried
        one.  A caller that needs the ledger's own shape for a hole has to
        name the stratum first, which is the honest repair.
        """
        return {STRATUM_COLUMN: self.stratum}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(stratum={self.stratum!r})"


def _ledger_rows(rows: Any) -> tuple[CoverageCount, ...]:
    """Return ``rows`` as the ledger's content, or refuse what is not.

    The constructor's one gate, so a hand-built ledger and a read one are
    validated the same way.  Three things are checked, each because a
    ledger that did not check it would misreport:

    * **the shape** — the argument is an iterable of rows carrying a
      ``stratum``, a ``world_count`` and an ``updated_at``.  Duck-typed
      rather than ``isinstance`` against
      :class:`~regime.coverage.CoverageCount`, for the reason the
      component suite documents: the module loader imports each member
      under a synthetic name, so the rows a composed store hands back are
      *structurally* identical to a direct import's but are not the same
      class objects.  A ledger read through the composed component must be
      the same ledger, so the check is on what a row *is*, not on which
      copy of the class built it.
    * **the values** — the name and the count go through feature 283's own
      two validators, restated here by import rather than re-written, so
      the reader cannot drift from the writer on what a stratum or a count
      is.  A stored ``world_count`` that is not a genuine non-negative
      integer is refused naming the stratum, because SQLite's columns are
      dynamically typed and a ledger read that swallowed a corrupt row
      would report a count nobody wrote.  A missing vintage is refused
      for the same reason ``CoverageCount`` refuses one: the table
      declares ``updated_at`` NOT NULL because a coverage number without
      an instant is not evidence.
    * **the identity** — no name twice.  ``stratum`` is the table's whole
      primary key, so the table cannot produce a duplicate; a hand-built
      ledger can, and it would be a ledger whose ``len``,
      :attr:`~CoverageLedger.counts` and
      :attr:`~CoverageLedger.empty` disagree about how many strata it
      holds.  Refused rather than deduplicated: quietly dropping one of
      two rows for one stratum would be this module choosing which count
      to believe, and the caller that assembled both is the one that
      knows which was meant.
    """
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Iterable):
        raise CoverageError(
            f"a ledger's rows must be an iterable of coverage rows — got "
            f"{rows!r} ({type(rows).__name__}); the ledger is the set of "
            "rows the table holds, and something that is not a collection "
            "of them names no ledger (feature 284)"
        )
    ordered: list[CoverageCount] = []
    seen: set[str] = set()
    for row in rows:
        name = _validated_stratum(getattr(row, "stratum", None))
        try:
            # The result is discarded deliberately: this is the *check*,
            # not a value being harvested — the row's own ``world_count``
            # is what the ledger reports, and re-typing it here would be
            # this function assembling a row it was asked to validate.
            _validated_world_count(getattr(row, "world_count", None))
        except CoverageError as exc:
            raise CoverageError(
                f"the ledger row for {name!r} could not be read as a count: {exc}"
            ) from exc
        if getattr(row, "updated_at", None) is None:
            raise CoverageError(
                f"stratum {name!r} carries no {UPDATED_AT_COLUMN}; the "
                "migration declares the column NOT NULL because a coverage "
                "number without a timestamp is not evidence, so a ledger "
                "holding a row without one is not a ledger this module can "
                "report (feature 284)"
            )
        if name in seen:
            raise CoverageError(
                f"the ledger names stratum {name!r} twice; the table's "
                "primary key is the stratum, so the ledger's identity is "
                "one row per name, and a ledger holding two rows for one "
                "stratum answers a different coverage depending on which "
                "row a reader happened to reach (feature 284)"
            )
        seen.add(name)
        ordered.append(row)
    ordered.sort(key=lambda row: _validated_stratum(row.stratum))
    return tuple(ordered)


@dataclass(frozen=True)
class CoverageLedger:
    """§C7's ledger as a whole: every named stratum, with its count.

    The answer to *what does the ledger hold?* — feature 284's sentence —
    as one value.  :attr:`rows` is the content and everything else here is
    a view derived from it on demand, never stored: the member's stores
    hold no cache of what the table says, and a value that memoised a
    derived figure would be the same mistake one level down.

    Validated in :meth:`__post_init__` rather than only at the read, the
    discipline :class:`~regime.coverage.CoverageCount` states for itself
    and for the same reason: unpickling and a direct construction both
    bypass the store, and a ledger is a value a caller may reasonably
    assemble — a test, a rendering, a comparison against a reading taken
    earlier.  What it may not do is assemble one the table could never
    have produced, which is what :func:`_ledger_rows` refuses.

    The lookup protocol is a convenience and is **not** a licence to
    forget the whole-ledger read: :meth:`__getitem__` answers one
    stratum's row for a caller that already holds a name, and the reason
    this module exists is the caller that does not.  A ledger holding no
    rows is a legitimate ledger — a database where no census has run — and
    every answer below is then the empty one rather than an error.
    """

    #: The rows the ledger holds, sorted by stratum — its whole content,
    #: and the only state this value has.
    rows: tuple[CoverageCount, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", _ledger_rows(self.rows))
        # A plain attribute rather than a field: it is a lookup index over
        # ``rows``, not part of the ledger, so it stays out of ``__eq__``,
        # ``__repr__`` and the hash — two ledgers agreeing on their rows
        # are the same ledger however they were built.  Written through
        # ``object.__setattr__`` because the dataclass is frozen.
        object.__setattr__(self, "_by_stratum", {row.stratum: row for row in self.rows})

    # -- The content --------------------------------------------------------

    @property
    def counts(self) -> dict[str, int]:
        """The ledger in §C7's own shape — ``{name: world_count}``.

        A fresh dict per call, so a caller cannot mutate this value's
        answer, and the shape the spec's API summary writes the endpoint
        in (*"Return stored world counts per regime stratum"*, feature
        343).  It is a view over :attr:`rows` rather than a second copy of
        the content: the stratum names and counts are the rows', and a
        ledger that stored both would be two records of one fact.
        """
        return {row.stratum: row.world_count for row in self.rows}

    def __getitem__(self, stratum: str) -> CoverageCount:
        """One named stratum's row.

        Raises :class:`KeyError` when the ledger holds no row for the
        name — the ``Mapping`` protocol's own answer, and deliberately not
        a :class:`~regime.errors.CoverageError`: a name the ledger does
        not hold is not a fault of the ledger or the ask, it is the
        *never named* fact, and the caller that needs it spelled as
        something it can hold is the caller that wants
        :meth:`holes` or :meth:`~regime.coverage.RegimeCoverage.get`.
        A name that cannot be a stratum at all is refused rather than
        answered with a ``KeyError``, because no ledger could ever hold
        one.
        """
        return self._by_stratum[_validated_stratum(stratum)]

    def get(self, stratum: Any, default: Any = None) -> Any:
        """One stratum's row, or ``default`` when the ledger holds none.

        :meth:`~regime.coverage.RegimeCoverage.get`'s answer narrowed to
        what the ledger in hand holds — ``None`` means *this ledger has no
        row for that name*, which is a different statement from the
        store's (that one asks the table, which something else may have
        written to since).  The two are spelled the same way on purpose,
        and the distinction is the ledger's whole point: a value is a
        reading, and reading it does not re-read the table.
        """
        try:
            return self._by_stratum[_validated_stratum(stratum)]
        except (KeyError, CoverageError):
            return default

    def __contains__(self, stratum: object) -> bool:
        """Whether the ledger holds a row for ``stratum``.

        Total, unlike :meth:`__getitem__`: a name that cannot be a stratum
        is simply not in the ledger, because ``in`` is a question and a
        question about a non-stratum has the answer *no* rather than a
        refusal.  The refusal belongs on the paths that would otherwise
        *act* on the value.
        """
        if not isinstance(stratum, str) or not stratum.strip():
            return False
        return stratum.strip() in self._by_stratum

    def __iter__(self) -> Iterator[str]:
        """The ledger's names, in stratum order."""
        return iter(self._by_stratum)

    def __len__(self) -> int:
        """How many strata the ledger names — rows, not worlds.

        The count §C7's ledger has when it is drawn as a set of keys, and
        deliberately not a sum: a ledger naming three strata is three
        names whether they hold two worlds between them or two million,
        and the two questions are answered by ``len(ledger)`` and
        :attr:`counts` respectively.
        """
        return len(self.rows)

    # -- The derived views --------------------------------------------------

    @property
    def empty(self) -> tuple[CoverageCount, ...]:
        """The strata that are named and hold no stored worlds.

        §C7's ``crash: 0`` — the state feature 286's ``empty_stratum``
        warning fires on, and a fact about rows this ledger already holds
        rather than a judgement over them: this property implements the
        *state*, and the warning that acts on it is feature 286's.  Empty
        when every named stratum holds worlds, and also empty when the
        ledger names nothing at all — a database where no census has run
        has no stratum that is *named* and empty, which is why the two
        cases are the same answer here and different answers in
        :meth:`holes`.
        """
        return tuple(row for row in self.rows if row.empty)

    @property
    def covered(self) -> tuple[CoverageCount, ...]:
        """The strata that hold at least one stored world.

        The complement of :attr:`empty`, and stated as its own view
        because it is the figure feature 289's diversity claim is refused
        against — *"rejects a regime-diverse claim while fewer than three
        strata hold stored worlds"* — and because reading it off ``len``
        and a comprehension at every call site would put the same
        definition in every caller.  A stratum is covered when its count
        is above zero; a stratum named and holding none is not, and a
        stratum nobody named is not in the ledger to be either.
        """
        return tuple(row for row in self.rows if not row.empty)

    def holes(
        self, vocabulary: Sequence[str] = DEFAULT_STRATA
    ) -> tuple[CoverageHole, ...]:
        """The vocabulary names the ledger holds no row for, in its order.

        The *nameless* question asked of a ledger that can now be seen
        whole: given a set of strata a deployment expects to count
        coverage across, which of them has the system never binned a
        world into — not *holds zero worlds*, which is a named-empty row
        and §C7's ``crash: 0``, but *has no row at all*.  The distinction
        is the reason this returns :class:`CoverageHole` values rather
        than zeroes, and the reason the vocabulary is a parameter.

        The default is :data:`~regime.coverage.DEFAULT_STRATA` — the three
        names the feature's own sentence spells — so the common call is
        one word.  It is a default and not a law: the stratum set is the
        labeler's configuration (``0107``'s words, and feature 283's
        argument for keeping it open), a deployment carving five strata
        passes its own five, and nothing here refuses a vocabulary that
        shares no name with the default three.  The **order is the
        vocabulary's**, not the ledger's, because the caller that asked
        the question asked it in an order — a worklist of strata still to
        be covered reads in the order the caller listed them, and sorting
        it here would reorder a caller's own list behind its back.

        An empty vocabulary names nothing, so it has no holes and the
        answer is empty: this answers *which of these* the ledger lacks,
        and a question about no strata has no missing ones.  (The other
        direction — the ledger's names a vocabulary does not mention — is
        not a hole and is not reported: a ledger holding five strata
        against a three-name vocabulary is over-covered, not deficient,
        and read off :attr:`rows` by anyone who wants it.)

        A vocabulary that is not a sequence of distinct non-empty names is
        refused in feature 283's vocabulary rather than answered: a
        duplicate would report one missing stratum twice, and a blank name
        is not a stratum that is missing but a malformed ask.
        """
        names = _validated_vocabulary(vocabulary)
        return tuple(
            CoverageHole(stratum=name) for name in names if name not in self._by_stratum
        )

    # -- The words ----------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(rows={self.rows!r})"


def _validated_vocabulary(vocabulary: Any) -> tuple[str, ...]:
    """Return ``vocabulary`` as a tuple of distinct stratum names.

    A sequence of names rather than a set, for the reason
    :meth:`CoverageLedger.holes` gives: the caller's order is part of what
    it asked, and a set would discard it.  Each name goes through feature
    283's own validator — imported rather than re-written, so the reader
    and the writer cannot drift on what a name is — and a duplicate is
    refused rather than deduplicated, because a vocabulary naming one
    stratum twice is a malformed ask and silently repairing it would hide
    the caller's bug behind a clean-looking answer.
    """
    if isinstance(vocabulary, (str, bytes)) or not isinstance(vocabulary, Iterable):
        raise CoverageError(
            f"a stratum vocabulary must be a sequence of names — got "
            f"{vocabulary!r} ({type(vocabulary).__name__}); a single string "
            "is a sequence of its characters, which is not a set of strata, "
            "and something that is not a collection names no vocabulary at "
            "all (feature 284)"
        )
    names: list[str] = []
    seen: set[str] = set()
    for name in vocabulary:
        validated = _validated_stratum(name)
        if validated in seen:
            raise CoverageError(
                f"the stratum vocabulary names {validated!r} twice; a "
                "vocabulary is the set of strata a deployment counts "
                "coverage across, and a duplicate would report one missing "
                "stratum twice (feature 284)"
            )
        seen.add(validated)
        names.append(validated)
    return tuple(names)


# -- The store's read -------------------------------------------------------------


def _read_ledger(store: RegimeCoverage) -> CoverageLedger:
    """Read every row the ledger holds through the store's own connection.

    The body of :meth:`~regime.coverage.RegimeCoverage.ledger`, which
    lives here rather than in :mod:`regime.coverage` so that the write
    module stays about writing: this function holds the only
    whole-table ``SELECT`` in the member, and the writer's module imports
    this one lazily rather than at scope, so neither module needs the
    other to be imported first.

    It reaches the store's own ``_connect`` and ``_count_from_row``
    rather than re-implementing either.  ``_connect`` is the creator —
    the idempotent ``CREATE TABLE IF NOT EXISTS`` that makes a fresh
    database, a migrated one and a downgraded one take the same path — so
    a reader that opened its own connection would either fail on a
    database the writer has not touched yet or, worse, be a *second*
    creator free to drift from ``0107``'s spelling.  ``_count_from_row``
    is documented as the read path's one constructor precisely so that
    every read-back in the store builds its value the same way, and a
    ledger read that built its rows differently would be the exception
    that document forbids.  A corrupt row is refused by that constructor
    naming the stratum it came off, which is what an operator needs from
    a whole-ledger read: *which row of the ledger is unreadable* rather
    than *some row somewhere is*.
    """
    with closing(store._connect()) as connection:
        rows = connection.execute(_READ_LEDGER_SQL).fetchall()
    return CoverageLedger(rows=tuple(store._count_from_row(row) for row in rows))


# -- The module-level spelling ----------------------------------------------------


def read_ledger(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CoverageLedger:
    """Read the coverage ledger — feature 284's sentence as one call.

    The module-level spelling of the read, for the caller that holds a URL
    rather than a store: a script, an operator checking §C7's ledger
    before a promotion, the endpoint that publishes it.  The store is
    resolved from ``database_url``, else from ``DATABASE_URL``, exactly as
    :func:`~regime.coverage.persist_coverage` resolves its own — the two
    are the same seam from the two sides of the table, and a caller that
    persists through one and reads through the other is reading the rows
    it wrote.

    A deployment that names neither is refused *by name* rather than
    answered with an empty ledger, and the difference is the whole
    difference between the two states this category keeps apart.  An
    empty :class:`CoverageLedger` is a real answer about a real database:
    no census has run yet, so nothing is named.  A deployment with no
    database at all has no ledger to be empty — answering ``()`` would
    report *coverage is zero everywhere* about a system whose coverage
    was never counted, and that answer lands on the promotion gate
    (feature 285) and the diversity refusal (feature 289) as a finding
    about the pool rather than as a wiring fault.  §C7's ledger exists to
    make the pool's skew visible; a read that invented an empty one would
    make a missing store look like a missing pool.

    A :class:`~regime.errors.CoverageError` from the store or the
    constructor propagates unwrapped, the stance
    :func:`~regime.coverage.persist_coverage` takes: the refusal already
    names the stratum or the address, and re-wrapping it would put a
    second message in front of the one an operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise CoverageError(
            "read_ledger returns the current coverage ledger and nothing "
            f"names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so there is no ledger to read. An "
            "empty ledger would be a finding about the replay pool — no "
            "census has run, no stratum is named — and this is not that "
            "finding, it is a deployment with nowhere a count could have "
            "been persisted. §C7's ledger is the one remedy for a "
            "regime-monotone pool, and a read that invented an empty one "
            "would leave the skew invisible until the regime break pays "
            "for it (feature 284)"
        )
    return RegimeCoverage(url).ledger()
