"""The coverage ledger's writer — one count per named stratum — feature 283.

app_spec.xml, "Regime Coverage Strata", feature 283: *System persists a
regime_coverage count per stratum such as high-volatility trend,
low-volatility chop and crash.*  docs/alpha-engine-prd.md §C7 — "Regime
coverage ledger" — is the doctrine this feature serves.  The replay pool
grows monotonically with calendar time, and that is its danger: a pool
built during six months of low-volatility chop *is* six months of
low-volatility chop, the meta-policy selected over it learns a
chop-optimal search policy, and the first thing finding that out costs is
the regime break.  §C7's remedy is an explicit ledger — *"Maintain an
explicit ledger: ``{high-vol trend: 2, low-vol chop: 14, crash: 0, …}``"*
— and §C5's dreaming engine, §7.2's stratified aggregation and the risk
table's *"Replay pool is regime-monotone | High | §C7 coverage ledger with
promotion block"* all read the rows this module writes.  The architecture
doc counts the ledger among the campaign's research metrics
(docs/nullius-tech-architecture.md §909: *"regime coverage ledger"*), and
the endpoint that will publish it (feature 284, ``GET
/metrics/regime-coverage``) reads the table this module fills.

**What the count is a count of, and why this module counts nothing.**  A
stratum's ``world_count`` is the number of *stored worlds* the replay pool
carries in that stratum — but the worlds are files in the pool, not rows
in this database, and ``0107`` states what that makes the table: *"the row
is a materialised aggregate over facts that live outside the database —
that is what a ledger **is** — and the honest spelling of that is no
``REFERENCES`` clause pretending otherwise."*  So the count arrives as the
caller's, and this module's act is the *persisting*: it never opens the
pool, never reads a price panel, and never runs a labeler.  The features
that make the number are the category's later ones — feature 290 assigns
each stored world to a stratum with the causal rolling-window labeler,
and feature 287 backfills coverage by replaying stored trees against
historical epochs — and every one of them writes what it learned through
this store.  That division is not modesty but the seam the spec draws:
the labeler is :mod:`feature_store.regime_labeler`'s and the ledger is
this member's, and no member imports another, so the count crosses
between them as a value the caller carries.

**The three names, and a set that is open.**  :data:`DEFAULT_STRATA` is
the feature's own sentence, verbatim — ``"high-volatility trend"``,
``"low-volatility chop"``, ``"crash"`` — and :data:`feature_store.
regime_labeler.DEFAULT_K` is 3 because those three are *"the regimes that
promotion counts coverage across"* (its own comment cites this feature).
The set is open, and the sentence's *"such as"* is the openness stated in
the spec's own words; §C7's example closes with an ellipsis.  Nothing
here refuses a stratum outside the default three, and that is a decision
worth stating against the nearest precedent: feature 241's legal theme
set is closed and refuses near-misses because *"choosing the space is the
highest-value human input"* and an illegal theme is a configured-space
refusal with its own error.  A stratum name is not that.  ``0107`` says
so from the schema's side — *"the migration stores whatever names the
plugin writes; it does not enumerate them, because the day the stratum
set changes is a configuration change in the labeler, not a schema change
here"* — so the honest writer is one that persists the name it is given
and refuses only what cannot be a name (blank or non-text).  A deployment
with five strata writes five rows; a stratum set nobody configured still
has the three.

**The named-empty row is a fact, and it is not the same fact as an absent
one.**  §C7's example ledger *writes the zero* — ``crash: 0`` — and
``0107`` makes the point load-bearing: ``world_count INT NOT NULL DEFAULT
0`` exists so that *"a stratum that is named and empty must be a row with
a 0, because feature 286's ``empty_stratum`` warning fires on exactly
that state; an absent row means a stratum nobody named, which is a
different fact and must stay distinguishable."*  So the store offers two
acts where one might do.  :meth:`RegimeCoverage.record` persists a count
— and recording ``0`` is naming, because §C7's example is written as a
count.  :meth:`RegimeCoverage.name_stratum` names a stratum *without
asserting anything about its count*: the one-column ``INSERT`` ``0107``
describes (``INSERT INTO regime_coverage (stratum) VALUES (?)``, the
default supplying the 0), and on a stratum already named it returns the
standing row **untouched** — naming is idempotent, and a name that
arrived twice must not zero a count the pool already holds.

**Idempotent by stratum, and the vintage is part of the law.**  The
table's identity is one row per named stratum (``stratum`` is the primary
key), so a re-issued ``record`` with the *same* count returns the stored
row byte for byte, ``updated_at`` included: a retry is the same
persisting call arriving twice (a reclaimed spot instance, a loop that
re-ran its census step), and *"a coverage number is only evidence while
you know when it was last true"* (``0107``, detail 3) — the count did not
change, so the instant it was last true did not either.  A *changed*
count is an ``UPDATE`` that re-stamps ``updated_at`` explicitly, because
a SQLite/Postgres default fires at insert and not on update — ``0107``
names this as *"a writer contract the regime plugin owns; stated here so
the column's meaning is readable from the DDL alone"*, and this module is
the party to that contract.  A *lower* count is persisted, not refused:
§C6's tripwires excise a poisoned node and its entire subtree from the
replay pool, so the pool is not monotone in worlds either — the ledger
records what is true now, and a store that refused a decrease would be
legislating a monotonicity the system does not have.

**One clock, and it is the database's.**  The insert path leaves
``updated_at`` to the table's own default and the update path writes
``datetime('now')`` explicitly — the same expression the default spells —
so a row's vintage always comes from one clock, at second resolution.
That is the convention the shipped stores already write
(``0107``'s dialect section: *"``ledger.record.utc_now`` drops
microseconds for the stated reason that sub-second precision buys nothing
a reader of these tables needs"*), and it is why this module never
computes a timestamp in Python: a writer-minted vintage beside a
default-minted one would be two clocks, and two clocks can disagree
about which count was true first.

**The table has two creators, and they converge on purpose.**
``migrations/versions/0107_regime_coverage.py`` (feature 107) is the
schema's owner — the spec's three columns with two argued corrections
(``NOT NULL`` on ``stratum``, the dialect-split ``NOW()`` default) — and
this store creates the same table idempotently on first use, column for
column, so that *"whichever ran first is the winner and the statements
agree, because both take the spec's columns and both are idempotent"*
(``0107``'s own convergence clause).  The contrast with the campaign
store is deliberate and worth one sentence, because the two members take
opposite stances toward the same situation:
:class:`discovery.campaign.CampaignRecords` **refuses** to create its
table, on the ground that ``0111`` is the authority and a writer that
invented it would be improvising a schema it does not own.  ``0107``
delegates where ``0111`` forbids — its downgrade docstring says a
downgraded database *"is refilled by the regime plugin's next persist,
which creates the table idempotently"* — so the plugin that declines to
create would be failing the one contract its own migration states.  A
database the migration never reached takes the same write path as one it
did, and running the migration over a database this store created
changes nothing.

**The answer is read back, and the read path validates.**  Every write
answers with the row the table holds — the count, and the vintage the
database minted — never a value assembled from the arguments, for the
reason every store in this workspace states: the row is the record, and
features 284-289 will read these rows through their own seams.  And
because SQLite's columns are dynamically typed, a raw ``INSERT`` from
another tool can land anything in ``world_count``; a read that swallowed
it would report a count nobody wrote, so :class:`CoverageCount` refuses
a stored value that is not a genuine non-negative integer, naming the
stratum it came off.

**Stdlib only, and import-cheap.**  ``sqlite3`` and ``urllib.parse``; no
third-party import at module scope, so the factory's scan — which imports
this package to fire its ``@register`` — pays nothing for the ledger, and
a composed application that never persists a count never opens a
database.  The store's registration lives in this member's
``__init__.py``, with the argument for why the ledger's writer is this
member's one component; this module holds no registration of its own.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import CoverageError

__all__ = [
    "COVERAGE_TABLE",
    "DATABASE_URL_ENV",
    "DEFAULT_STRATA",
    "STRATUM_COLUMN",
    "UPDATED_AT_COLUMN",
    "WORLD_COUNT_COLUMN",
    "CoverageCount",
    "RegimeCoverage",
    "persist_coverage",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the campaign
#: planner's, the seven null-oracle readers'), restated here so this store
#: states its own contract and imports nobody else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The ledger's table — feature 107's, created by
#: ``migrations/versions/0107_regime_coverage.py`` and restated here, on the
#: convergence that migration's own docstring sets up: whichever creator ran
#: first is the winner and the statements agree.  Spelled once so the writer
#: and the migration cannot drift apart on what the table is called.
COVERAGE_TABLE = "regime_coverage"

#: The ledger's identity — one row per named stratum.  ``0107`` declares it
#: ``TEXT NOT NULL PRIMARY KEY``: the explicit ``NOT NULL`` is that
#: migration's argued correction of the spec's bare key, because SQLite does
#: not make a rowid table's primary key NOT NULL and NULLs compare distinct,
#: so the bare spelling would admit any number of nameless rows against a
#: ledger whose whole identity is one row per name.
STRATUM_COLUMN = "stratum"

#: The stratum's stored-world count — the number the feature's sentence
#: persists.  ``NOT NULL DEFAULT 0`` because §C7's own example ledger writes
#: ``crash: 0``: a named stratum with no worlds is a coverage hole the row
#: *is*, not an absence.
WORLD_COUNT_COLUMN = "world_count"

#: The count's vintage.  ``NOT NULL`` because a coverage number without a
#: timestamp is not evidence, and defaulted so the one-column insert of a
#: named-empty stratum is stamped by the table itself.  An ``UPDATE``
#: re-stamps explicitly — the writer contract this module owns.
UPDATED_AT_COLUMN = "updated_at"

#: The three strata the feature's own sentence names, verbatim —
#: *"high-volatility trend, low-volatility chop and crash"* — and the
#: default vocabulary, not a gate.  :data:`feature_store.regime_labeler.
#: DEFAULT_K` is 3 because these are the regimes its clusters carve; the
#: set stays open (§C7's example ledger closes with an ellipsis, and the
#: sentence's *"such as"* is that openness in the spec's own words), so a
#: deployment with more strata persists more names and nothing refuses
#: one.  The labeler's comment cites this feature by number;
#: ``packages/regime/tests/test_cross_member.py`` pins the count the two
#: agree on, since no member may import another.
DEFAULT_STRATA: tuple[str, ...] = (
    "high-volatility trend",
    "low-volatility chop",
    "crash",
)

#: The ledger's DDL, in the SQLite spelling this store speaks — the same
#: statement ``0107`` returns for its sqlite dialect, token for token, so
#: the two creators converge as that migration's docstring promises.  The
#: default keeps the outer parentheses SQLite's ``DEFAULT`` grammar demands
#: of a function call: without them the whole ``CREATE TABLE`` is a syntax
#: error, the trap ``0107`` documents for this exact expression.
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {COVERAGE_TABLE} (
    {STRATUM_COLUMN}     TEXT NOT NULL PRIMARY KEY,
    {WORLD_COUNT_COLUMN} INT NOT NULL DEFAULT 0,
    {UPDATED_AT_COLUMN}  TIMESTAMPTZ NOT NULL DEFAULT (datetime('now'))
)
"""

#: One stratum's row, column by column rather than ``SELECT *``: the order
#: :meth:`RegimeCoverage._count_from_row` reads must be the order this
#: names, and a future migration that appends a column must not silently
#: shift the fields.
_READ_ROW_SQL = (
    f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}, {UPDATED_AT_COLUMN} "
    f"FROM {COVERAGE_TABLE} WHERE {STRATUM_COLUMN} = ?"
)

#: The persist itself, on a stratum the ledger does not hold.  The vintage
#: is left to the table's default — one clock, the database's — and the
#: count is written beside the name because §C7's ledger is drawn in
#: counts, zeros included.
_INSERT_COUNT_SQL = (
    f"INSERT INTO {COVERAGE_TABLE} ({STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}) "
    "VALUES (?, ?)"
)

#: The naming act — ``0107`` detail 1's one-column insert, verbatim in
#: shape.  The count comes from the column's ``DEFAULT 0`` and the vintage
#: from the table's own default, which is the whole point of both defaults:
#: naming a stratum asserts nothing about its count, and the row the insert
#: lands is the named-empty one feature 286's warning reads.
_INSERT_NAMED_SQL = f"INSERT INTO {COVERAGE_TABLE} ({STRATUM_COLUMN}) VALUES (?)"

#: A changed count, with the vintage re-stamped by the same expression the
#: insert default spells — ``0107`` detail 3's writer contract, stated as
#: the plugin's to own.  A default does not fire on ``UPDATE``, so a writer
#: that left the column alone would freeze every stratum's vintage at the
#: moment it was first named, and the ledger would stop being evidence.
_UPDATE_COUNT_SQL = (
    f"UPDATE {COVERAGE_TABLE} SET {WORLD_COUNT_COLUMN} = ?, "
    f"{UPDATED_AT_COLUMN} = datetime('now') WHERE {STRATUM_COLUMN} = ?"
)


# -- Validation -------------------------------------------------------------------


def _validated_stratum(value: Any) -> str:
    """Return ``value`` as a stratum name, or refuse what cannot be one.

    Non-empty text, stripped — the near-miss a trailing newline or an
    indented copy would otherwise persist as a *second* row for one
    stratum, against a primary key whose whole identity is one row per
    name.  Nothing else is normalised, and that is deliberate: the stratum
    vocabulary is the labeler's configuration (``0107``'s own words), and a
    store that case-folded or re-spelled names would be silently renaming a
    stratum a deployment configured — ``"Crash"`` and ``"crash"`` persist
    as two rows, and the caller that wrote both is the one that must
    reconcile them, in the configuration the names came from.
    """
    if not isinstance(value, str) or not value.strip():
        raise CoverageError(
            f"a stratum must be non-empty text — got {value!r} "
            f"({type(value).__name__}); the ledger's identity is one row per "
            f"named stratum, and a name that states nothing names no stratum "
            "a count could be persisted for (feature 283)"
        )
    return value.strip()


def _validated_world_count(value: Any) -> str:
    """Return ``value`` as a stored-world count, or refuse what is not one.

    A genuine non-negative integer.  ``bool`` is refused explicitly —
    ``True`` is an ``int`` in Python, and a truthy ``1`` accepted here
    would let a flag land where a count belongs; a negative number is
    refused because a count of stored worlds cannot be negative (§C6's
    excision empties a stratum, it never owes worlds); a non-``int``
    because a fractional world is not a world.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CoverageError(
            f"a stratum's {WORLD_COUNT_COLUMN} must be a non-negative "
            f"integer — got {value!r} ({type(value).__name__}); the count is "
            "of stored worlds in the replay pool, and a number of worlds is "
            "a count, not a truthy flag or a fraction (feature 283)"
        )
    if value < 0:
        raise CoverageError(
            f"a stratum's {WORLD_COUNT_COLUMN} must be at least 0, got "
            f"{value!r}; §C6's tripwires excise worlds from the pool but "
            "never create a stratum that owes them, and a negative count is "
            "not a number of stored worlds (feature 283)"
        )
    return value


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same convention every store in this workspace restates —
    :func:`discovery.campaign._sqlite_path`'s translation with this
    member's own refusal vocabulary, because a caller's ``except
    CoverageError`` must not be defeated by a planning refusal raised from
    the ledger's path.  A non-SQLite scheme and a pathless URL are refused
    by name; an in-memory database is refused because the ledger must
    outlive the call that wrote it — the promotion gate reads these rows
    under time pressure (``0107``'s opening line), from another process
    entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CoverageError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the coverage "
            "ledger lives in (feature 283)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CoverageError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 283)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CoverageError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory ledger would die with the connection that opened it, "
            "and a coverage count must outlive the call that persisted it — "
            "the coverage endpoint, the promotion block and the diversity "
            "gate all read these rows from another process (feature 283)"
        )
    return Path(path)


# -- The record -------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageCount:
    """One stratum's row in the ledger, as the table holds it.

    The three fields are the table's three columns: the name, the count and
    the vintage.  Frozen, so a count that has been read back cannot be
    edited into a different coverage number by a caller who kept a
    reference — the discipline :class:`discovery.campaign.CampaignRecord`
    and :class:`bootstrap.WorldRecord` state, and for the same reason: this
    value is the record of what the pool holds, and a mutable one would
    let a caller retype coverage in memory while the row said otherwise.

    Validated in :meth:`__post_init__` rather than only through the store,
    because ``dataclasses.replace`` and unpickling both rebuild instances
    past a factory's nose — and because the *read* path needs the same
    check the write path does: SQLite's columns are dynamically typed, so
    a corrupt row is reachable here, and a ledger read that swallowed it
    would report a count nobody wrote.  A validation refusal on a stored
    row is the store's to re-raise naming the stratum (see
    :meth:`RegimeCoverage._count_from_row`).
    """

    #: The stratum's name — the ledger's identity, one row per name.
    stratum: str
    #: How many stored worlds the replay pool carries in this stratum.
    world_count: int
    #: When the count was last true — the database's own stamp, read back.
    updated_at: Any

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the strip
        # below is normalization, not mutation of the caller's values, and
        # it is the only write this object ever takes.
        object.__setattr__(self, "stratum", _validated_stratum(self.stratum))
        object.__setattr__(
            self, "world_count", _validated_world_count(self.world_count)
        )
        # The vintage is read back rather than parsed: ``0107`` stamps it
        # with ``datetime('now')`` (SQLite text, second resolution) and the
        # honest check on this side is only that the NOT NULL column
        # carried *something* — a NULL vintage is a row this member could
        # not have written, whatever wrote it.
        if self.updated_at is None:
            raise CoverageError(
                f"stratum {self.stratum!r} carries no {UPDATED_AT_COLUMN}; "
                f"the migration declares the column NOT NULL because a "
                "coverage number without a timestamp is not evidence, so a "
                "row without one is not a count this store can report "
                "(feature 283)"
            )

    @property
    def empty(self) -> bool:
        """True when the stratum is named and holds no stored worlds.

        The named-empty state — §C7's ``crash: 0`` — and a *fact about the
        row* rather than a judgement over it: the ``empty_stratum``
        warning that fires on exactly this state is feature 286's, and
        this property deliberately implements the state, not the warning.
        """
        return self.world_count == 0

    def row(self) -> dict[str, Any]:
        """The count as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`discovery.campaign.CampaignRecord.row` states: a rendered
        mapping names the same things the same way the row does.
        """
        return {
            STRATUM_COLUMN: self.stratum,
            WORLD_COUNT_COLUMN: self.world_count,
            UPDATED_AT_COLUMN: self.updated_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(stratum={self.stratum!r}, "
            f"world_count={self.world_count!r}, "
            f"updated_at={self.updated_at!r})"
        )


# -- The store --------------------------------------------------------------------


class RegimeCoverage:
    """The store that persists the ledger: one count per named stratum.

    Constructed with the database URL the ledger lives in;
    :meth:`record` persists one stratum's count, :meth:`name_stratum`
    names a stratum without asserting a count, and :meth:`get` reads one
    stratum's row back.  The class resolves its path lazily, so
    constructing one performs no I/O: composition-time work must not touch
    the disk, the contract every store in this workspace states.

    The store holds no cache of the rows it wrote: the row is the only
    record of what the pool holds, so it is the only thing an answer is
    drawn from — the stance :class:`discovery.campaign.CampaignRecords`
    states for its own idempotence, and for the same reason.  A memo of
    persisted counts would make *"when was this count last true?"* a
    question about this process's history rather than about the ledger,
    and the endpoint and the gates that read these rows run in other
    processes entirely.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the ledger lives in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one count: a URL that is
        not a non-empty string names no ledger, and a store that accepted
        one would fail identically on every persist — the wrong place for
        a deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise CoverageError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL; the "
                "coverage ledger is a table in the database the deployment "
                "names, and a store pointed at nothing has nowhere to "
                "persist a count (feature 283)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RegimeCoverage | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not
        an error: it is a deployment without a relational store, which
        composes no coverage component — a discoverable state, not an
        exception — while the caller that must persist a count before
        anything reads it is the caller that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the ledger, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the ledger's database, ensuring the table exists.

        ``CREATE TABLE IF NOT EXISTS`` on the coverage table, in the
        spelling ``0107`` itself returns for this dialect — the convergence
        that migration's docstring sets up (*"whichever ran first is the
        winner and the statements agree"*), and the contract its downgrade
        path delegates to this plugin (*"refilled by the regime plugin's
        next persist, which creates the table idempotently"*).  A fresh
        database, a migrated one and a downgraded one all take the same
        write path, and running the migration over a table this store
        created changes nothing.  The caller owns the connection; use it
        as a context manager to commit, which is what every write here
        does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executescript(_CREATE_TABLE_SQL)
        return connection

    # -- Feature 283: the persist -------------------------------------------

    def record(self, stratum: Any, world_count: Any) -> CoverageCount:
        """Persist one stratum's stored-world count — feature 283's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the name as non-empty text, the count as
           a genuine non-negative integer — before anything is opened, so
           a malformed persist is refused without touching a database.
        2. **Read the stratum's row.**  The ledger is keyed by name, so
           the row is the whole of what the store knows about the count.
        3. **Insert, update, or neither.**  An absent row takes the
           insert (the vintage from the table's default).  A standing row
           with a *different* count takes the update, which re-stamps the
           vintage explicitly — ``0107`` detail 3's writer contract.  A
           standing row with the *same* count takes neither: the persist
           is idempotent, and the vintage records when the count was last
           true, which a retry did not move.  A lower count is persisted,
           not refused — §C6's excision removes worlds, and the ledger
           records current truth rather than legislating monotonicity.
        4. **Read back and answer with the row**, inside the same
           transaction as the write, so the count and the vintage in the
           answer are the table's own.

        Refuses, in this order, each naming what it is about: a malformed
        name or count (:class:`~regime.errors.CoverageError`); a
        ``DATABASE_URL`` this member cannot speak (the same class, by
        name); and a stored row too corrupt to be a count (the same
        class, naming the stratum it came off).
        """
        name = _validated_stratum(stratum)
        count = _validated_world_count(world_count)
        with closing(self._connect()) as connection, connection:
            row = _read_row(connection, name)
            if row is None:
                connection.execute(_INSERT_COUNT_SQL, (name, count))
            else:
                stored = self._count_from_row(row)
                if stored.world_count == count:
                    # The re-issued persist: the count was already true, so
                    # the instant it was last true did not change, and
                    # re-stamping it would claim a freshness the retry does
                    # not have.  Return the standing row untouched.
                    return stored
                connection.execute(_UPDATE_COUNT_SQL, (count, name))
            row = _read_row(connection, name)
        if row is None:
            raise CoverageError(
                f"stratum {name!r} could not be read back after the persist; "
                "a coverage count must be accounted for, and a row that "
                "cannot be re-read is a count this store cannot vouch for "
                "(feature 283)"
            )
        return self._count_from_row(row)

    def name_stratum(self, stratum: Any) -> CoverageCount:
        """Name one stratum, asserting nothing about its count.

        The named-empty state's own act: ``0107`` detail 1's one-column
        insert, landing a row whose ``world_count`` comes from the column's
        ``DEFAULT 0`` and whose vintage the table stamps itself.  §C7's
        example ledger *writes the zero* — ``crash: 0`` — because feature
        286's ``empty_stratum`` warning fires on exactly that state, and
        an absent row (a stratum nobody named) is a different fact that
        must stay distinguishable from it.

        Idempotent in the stronger of the two directions: a stratum the
        ledger already holds is returned **untouched** — its count stands,
        its vintage stands — because naming is a statement about the
        vocabulary, not about the pool, and a name arriving twice must not
        zero a count the pool already holds.  (Recording ``0`` through
        :meth:`record` lands the same row on a fresh stratum; the two acts
        differ only in what they say about a stratum that is already
        named.)
        """
        name = _validated_stratum(stratum)
        with closing(self._connect()) as connection, connection:
            row = _read_row(connection, name)
            if row is None:
                connection.execute(_INSERT_NAMED_SQL, (name,))
                row = _read_row(connection, name)
        if row is None:
            raise CoverageError(
                f"stratum {name!r} could not be read back after naming it; "
                "a named stratum must be a row the ledger holds, and one "
                "that cannot be re-read is a name this store cannot vouch "
                "for (feature 283)"
            )
        return self._count_from_row(row)

    def get(self, stratum: Any) -> CoverageCount | None:
        """One stratum's row, or ``None`` when the ledger holds none.

        ``None`` means *nobody has named this stratum* — which is the
        honest answer for a name the table does not hold, and the fact
        ``0107`` keeps distinguishable from a named stratum holding zero
        worlds.  It does **not** mean the read failed: an unreachable
        database raises, so a caller can never mistake a broken store for
        an unnamed stratum.  Reading validates what it reads — a stored
        ``world_count`` that is not a non-negative integer is refused
        naming the stratum, because a ledger read that swallowed a corrupt
        row would report a count nobody wrote.

        Deliberately a *one-stratum* read.  The coverage ledger as a whole
        — every named stratum's count at a glance — is
        :meth:`ledger`, feature 284's verb, and this store's read exists
        for the write's read-back and for the caller that holds one
        stratum's name (a promotion gate asking after its deployment
        regime, feature 285).
        """
        name = _validated_stratum(stratum)
        with closing(self._connect()) as connection:
            row = _read_row(connection, name)
        if row is None:
            return None
        return self._count_from_row(row)

    def ledger(self) -> Any:
        """The current coverage ledger — every named stratum, feature 284.

        app_spec.xml, "Regime Coverage Strata", feature 284: *System
        returns the current coverage ledger showing stored world counts
        for every named stratum.*  Where :meth:`get` answers one name the
        caller already holds, this answers the *table* — one ``SELECT``
        over every row, in stratum order — and the difference is the
        point of the feature rather than a convenience:
        :data:`DEFAULT_STRATA` is a default vocabulary, not an
        enumeration of what the ledger may hold, so a reader that walked
        the three names would report nothing about a deployment whose
        labeler carves five.  §C7's ledger is the *distribution* of the
        pool across regimes, and a distribution is not readable one
        stratum at a time.

        Returns a :class:`~regime.ledger.CoverageLedger`: the rows, each
        a :class:`CoverageCount` read back from the table, sorted by
        stratum, with the counts, the named-empty set, the covered set
        and the vocabulary holes as views derived on demand.  The rows are
        the record — this store holds no cache of them, and a ledger read
        is a question about the *table*, so a memo would turn *what does
        the pool hold now?* into a question about this process's history.
        The census (feature 290) and the backfill (287) write counts from
        other callers, §C6's excision removes worlds between reads, and
        the endpoint that publishes this ledger (feature 343) and the
        promotion gate that blocks on it (285) run in other processes
        entirely.

        An empty ledger is a legitimate answer, not an error: a database
        where no census has run yet names no stratum, and ``len(ledger)
        == 0`` is the honest report of that state.  It is deliberately
        *not* the same fact as a ledger naming a stratum and holding zero
        worlds — ``0107`` detail 1's distinction, kept apart on this side
        as on that one: the second is a row in :meth:`ledger`'s answer and
        a member of :attr:`~regime.ledger.CoverageLedger.empty`, the
        first is absence from it.

        Refuses what :meth:`get` refuses, in the same class: a
        ``DATABASE_URL`` this member cannot speak, and a stored row too
        corrupt to be a count — the latter naming the stratum it came
        off, because a whole-ledger read's most useful failure is *which
        row is unreadable*.

        The body lives in :mod:`regime.ledger`, imported here **lazily**:
        that module imports this one for the value types and the column
        names, so a scope-level import in either direction would be a
        cycle, and the deferred import is the plain answer — the write
        module stays about writing, the read module owns the only
        whole-table ``SELECT`` in the member, and the two are one call
        apart rather than one import apart.
        """
        from .ledger import _read_ledger

        return _read_ledger(self)

    # -- The words ----------------------------------------------------------

    def _count_from_row(self, row: tuple[Any, ...]) -> CoverageCount:
        """Build a :class:`CoverageCount` from a row, with the stratum named.

        The read path's one constructor, so every read-back in the store
        builds the value the same way.  A validation refusal raised from
        the row names the stratum it came off — the difference between an
        operator learning *this stratum's count is corrupt* and learning
        only that some number somewhere is not a count.
        """
        stratum = row[0]
        try:
            return CoverageCount(
                stratum=stratum,
                world_count=row[1],
                updated_at=row[2],
            )
        except CoverageError as exc:
            raise CoverageError(
                f"the coverage row for {stratum!r} could not be read as a "
                f"count: {exc}"
            ) from exc

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _read_row(
    connection: sqlite3.Connection, stratum: str
) -> tuple[Any, ...] | None:
    """One stratum's row as the table holds it, or ``None`` when absent."""
    cursor = connection.execute(_READ_ROW_SQL, (stratum,))
    try:
        return cursor.fetchone()
    finally:
        cursor.close()


# -- The module-level spelling -----------------------------------------------------


def persist_coverage(
    stratum: Any,
    world_count: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CoverageCount:
    """Persist one stratum's count — the module-level spelling.

    Feature 283's sentence as one call, for the caller that wants the act
    without holding a store: the stratum and its count in, the stored
    coverage row out.  The store is resolved from ``database_url``, else
    from ``DATABASE_URL``; a deployment that names neither is refused *by
    name* rather than silently doing nothing, because a persist that
    quietly skipped its write would leave the ledger silent about exactly
    the strata the pool holds — the skew §C7's ledger exists to make
    countable, discovered instead at the promotion gate that reads it.

    A :class:`~regime.errors.CoverageError` from the store propagates
    unwrapped: the refusal already names the stratum and the fact, and
    re-wrapping it here would put a second message in front of the one an
    operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise CoverageError(
            "persist_coverage persists a stratum's count and nothing names "
            f"a store: {DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the count could not be recorded. The ledger is "
            "the one remedy §C7 names for a regime-monotone replay pool, "
            "and a persist that skipped its write would leave the pool's "
            "skew invisible until the regime break pays for it (feature 283)"
        )
    return RegimeCoverage(url).record(stratum, world_count)
