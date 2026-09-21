"""The bootstrap trials' budget bit — feature 185's zero-cost persistence.

app_spec.xml, "Bootstrap Worlds", feature 185: *System charges no
statistical budget for a bootstrap world, persisting charges_budget as
false on those trials.*  docs/nullius-tech-architecture.md §10.6 states
the fact the sentence persists — the third of the three things a
bootstrap world gives the pool:

    Each exposes the **same** ``question.*`` API as a financial campaign,
    so a policy is portable without modification. They give perfect
    labels, zero statistical-budget cost, and no dependence on market
    time.

—and §10.6's own arithmetic is why the *persistence* half matters: a
bootstrap pool converts the §10.3.1 pool-size precondition into a compute
problem by making worlds cheap to *have*, and this feature makes them
cheap to *probe*, which is only true if the probing leaves the accounting
exactly where it found it.

**The sentence has two clauses, and the second is the feature.**  The
first — *charges no statistical budget* — is a fact the question already
states (:meth:`bootstrap.BootstrapQuestion.budget_remaining` answers the
whole budget, always; a counter it decremented would be a budget, and the
budget is not the world's to keep).  The second — *persisting
``charges_budget`` as ``false`` on those trials* — is a fact about what
the **trial** records, and it is the load-bearing half because of what
the column is downstream: §8 fixes it (``charges_budget BOOLEAN NOT
NULL``), feature 90 makes it the null oracle's one opaque directive, and
feature 93 makes ``K_effective`` a count of the rows where it is *true*
— *"so null nodes never inflate the trial count"*.  A bootstrap trial
that reached the accounting stamped ``true`` would inflate ``K`` the
same way a null node would, and for no reason anyone wrote down: §10.6
*publishes* that a bootstrap world's probes are free.  This module is
that publication, persisted.

**Why the row lives in a table this member owns.**  ``trial_ledger`` is
the ledger member's (feature 86) and speaks a UUID vocabulary — §8
declares ``node_id UUID NOT NULL``, and the store's write seams hold
every row to the canonical UUID spelling — while a bootstrap node is a
lattice address (``d+1.i+1.s+0.a+3``): a row this member wrote there
could not even name its node.  One writer per table is the seam
discipline the whole workspace states, so the bootstrap half of the
trial record lives where the bootstrap half of everything else lives:
``bootstrap_trial``, a table this member owns and creates lazily, in the
one database ``DATABASE_URL`` names — the same choice feature 188 made
when it seated ``bootstrap_world`` beside ``replay_score``, so that
*"persists into the replay pool"* meant the pool the dreaming loop
reads.  Here it means the database the accounting reads: the ledger
member's ``K_effective`` and this member's trials share one store, which
is what makes *"those trials"* a statement about the trials the system
actually counts over rather than about a side file.

**The bit is written by the store, never stated by the caller.**
:meth:`BootstrapTrialLedger.record_trials` has no ``charges_budget``
parameter — there is nothing to spell wrong.  The contrast with feature
90 is the point.  There the directive must be *opaque* and
caller-supplied, because the evaluator must not learn ``is_null``; the
oracle knows the reason and the ledger must not.  A bootstrap world's
budget-freeness is the opposite of a secret — §10.6 states it in the
document — so there is nothing to keep and no caller to trust, and the
write spells the literal ``0``.  And the table's own
``CHECK (charges_budget = 0)`` makes the sentence a fact about the
*store* rather than a convention of this module's writers: a hand that
reached past the writer — the hazard every append-only table here names
— cannot seat a charging trial even by accident.  The refusal meets a
hand-built record too (:class:`TrialRecord` refuses a ``charges_budget``
that says ``True``), because a record of a trial that charged describes
no row the table can hold.

**The seam is the question's, because the trial is a probe.**  Feature
185 depends on feature 184, and the dependency is the whole shape: the
one act a policy performs on a bootstrap world is a probe through the
identical ``question.*`` interface, so *those trials* are the question's
reveals.  The recorder therefore takes the question and the batch,
reveals through the question's own
:meth:`~bootstrap.BootstrapQuestion.probe_batch`, and writes one row per
*newly* revealed cell — the reveal and the record cannot drift apart,
because the row is built from the very observations the probe returned,
and the row's world is read from the observation's own payload
(:attr:`~bootstrap.BootstrapQuestion.Observation.world_id`) rather than
restated by the caller, which is the attribution discipline the
observation carries for §10.6's *"report the two pools separately"*.  A
re-probe records nothing new (the question is idempotent on its revealed
set, and the trial already has its row); two replays' probes of one cell
each record (each policy's evaluation is its own trial — and both are
free).  The question is duck-typed rather than ``isinstance``-checked
for the reason every seam in this member is: the module loader imports
the member under a synthetic name and re-executes it, so the composed
question ``create_app()`` serves is a second class object, and the
authored world, the ported world (feature 190's
:func:`~bootstrap.ported_question_for`) and the composed world record
through one code path.

**Append-only, in the store's own spelling.**  ``seq`` is
``INTEGER PRIMARY KEY AUTOINCREMENT`` — a spent number never reusable,
SQLite's high-water-mark restatement of the wall feature 92 builds
around ``trial_ledger`` (no ``UPDATE`` or ``DELETE`` is written here
either; the log is a record of past trials, and facts are superseded by
new rows, never edited).  ``ts`` is the second-truncated ISO-8601 UTC
stamp every store in this workspace writes, validated aware the same way
the pool validates an authoring instant, and ``recorded_at`` is a
parameter for the same reason the pool's is: a re-statement that must
name an instant names it exactly.  The reads
(:meth:`~bootstrap.BootstrapTrialLedger.trials`,
:meth:`~bootstrap.BootstrapTrialLedger.trial_count`) are ordered by
``seq`` — the log's own order, the one §12's determinism rule wants a
report to reproduce — and validate every row back through the record's
constructor, which is how a hand-edited row is refused rather than
served.

**No component, and why.**  The trial ledger resolves the same
``DATABASE_URL`` the pool resolves, the same way the pool resolves it
(:meth:`BootstrapTrialLedger.resolve`, with the same degrade-to-``None``
stance toward a deployment that names no database), and it deliberately
adds no registry name.  The pool's component is the member's one
*deployment seat* — it answers *what is the composed bootstrap pool?*
for the one database the process is pointed at — and a second store over
the same URL would be two names for one deployment fact, free to drift
until a caller held a pool in one database and its trials in another.
One deployment seat, two tables, both owned here: the census
(:mod:`bootstrap._census`) set the precedent — register no name for a
question another component already answers — and the member's registry
contribution is pinned at two names by its own suite, which is the
convention speaking.

**What this module deliberately does not ship.**  It computes no
``K_effective`` — feature 93's arithmetic is the ledger member's, and
this member's contribution is that its rows can never be counted by it
(every row the table can hold answers ``0`` to the only question the
count asks).  It decrements nothing — the budget is reported whole by
the question and never counted down anywhere, because a counter would be
a budget.  It carries no ``charge_units`` — §8's unit prices *compute*
("1.0 default; CV folds may cost more"), §10.6's zero cost is
*statistical*, and the spec keeps the two facts apart on the very row
that names them; a column for units would be a compute accounting no
feature of this category asked for.  And it books no epoch, no evaluator
hash and no cost model — those are §8's statements about a *financial*
evaluation's provenance, and a bootstrap trial's provenance is total in
one column pair: the world it was probed on and the cell that was
probed, both of which the row already carries.

Stdlib only, and import-cheap: ``sqlite3``, ``datetime``, ``os`` and
``pathlib``; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for the ledger (the discipline :mod:`bootstrap._pool` states for
its own import).
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from ._pool import DATABASE_URL_ENV, _sqlite_path, _stamp, parsed_instant
from .errors import BootstrapPoolError

__all__ = [
    "TRIAL_CHARGES_BUDGET",
    "TRIAL_TABLE",
    "BootstrapTrialLedger",
    "TrialRecord",
]

#: The table the bootstrap trials persist into — this member's own, created
#: lazily and never migrated, for the same reason :data:`~bootstrap.POOL_TABLE`
#: gives: the table has one writer, this ledger, and the shape is a fact
#: about the feature rather than about the database's history.  Named beside
#: ``bootstrap_world`` the way ``trial_ledger`` names itself: one row per
#: trial, and the row *is* the trial's record against the accounting.
TRIAL_TABLE = "bootstrap_trial"

#: The directive every bootstrap trial records — §10.6's *"zero
#: statistical-budget cost"* as the one bit §8's column carries.  Published
#: the way :data:`~bootstrap.DISCOVERY_BAR` publishes the evidential bar: the
#: number is a fact about every bootstrap world this member can build, so a
#: caller or a test reads it rather than restating it.  ``False`` is not a
#: default here — it is the only value the table's CHECK admits.
TRIAL_CHARGES_BUDGET = False

#: The row's column names, in declaration order — the one spelling of what a
#: trial row is made of, shared by the DDL, the insert and the read-back so
#: the three cannot disagree on a column order (the failure a positional
#: ``SELECT *`` invites, and the one :data:`~bootstrap.POOL_TABLE`'s own
#: ``_ROW_COLUMNS`` constant exists to prevent).
_TRIAL_COLUMNS = ("seq", "ts", "world_id", "node_id", "charges_budget")

#: The store's whole schema: one append-only table, created lazily and
#: idempotently.  The comment carries the argument because a schema is where
#: a store states its contract; every clause below is load-bearing.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TRIAL_TABLE} (
    -- The trial's order in the log, assigned by the table.  AUTOINCREMENT
    -- makes a spent number never reusable (SQLite keeps a high-water mark
    -- that deletes do not lower), which is the append-only wall's own
    -- spelling: nothing here writes an UPDATE or a DELETE, and the row's
    -- identity is the order it was appended in -- the order every read
    -- returns and every report reproduces.
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    -- When the trial ran: ISO-8601 UTC, second-truncated, Z-suffixed --
    -- the same stamp the pool's authoring rows carry, written by the
    -- caller-stamped store rather than an engine DEFAULT (which is why
    -- there is no dialect split here: a caller-stamped column never meets
    -- SQLite's parenthesised-DEFAULT grammar).
    ts             TEXT NOT NULL,
    -- The world the trial probed, the observation's own attribution --
    -- the bootstrap half of "report the two pools separately", carried on
    -- the row so a report over the log can split the pools without
    -- joining anything.
    world_id       TEXT NOT NULL,
    -- The cell the trial evaluated -- a lattice address
    -- ("d+1.i+1.s+0.a+3"), which is the plain reason this row lives in a
    -- table this member owns rather than in trial_ledger: §8 declares
    -- that table's node a UUID, and a bootstrap node is not one.
    node_id        TEXT NOT NULL,
    -- Whether the trial consumed statistical budget (§8's column, feature
    -- 90's directive, feature 93's filter): FALSE for every bootstrap
    -- trial, because §10.6 publishes that a bootstrap world's probes are
    -- free -- and FALSE by the table's own voice, not by convention of
    -- this module's writers.  The CHECK is the feature's sentence as a
    -- constraint: a hand that reached past the writer cannot seat a
    -- charging trial even by accident, and K_effective (feature 93)
    -- counts only rows this table can never hold.  Stored as the 0 of a
    -- SQLite BOOLEAN, written as the literal 0 of the INSERT -- there is
    -- no parameter to spell wrong.
    charges_budget BOOLEAN NOT NULL CHECK (charges_budget = 0)
)
"""

#: The one write this store performs.  The ``charges_budget`` value is the
#: literal ``0`` — not a bound parameter — so the writer cannot charge
#: budget even by argument: the sentence's second clause is a fact about the
#: statement, and the statement has one spelling.  The assigned ``seq`` is
#: read back per row (``lastrowid``), which is the number the returned
#: record carries.
_INSERT_TRIAL = f"""
INSERT INTO {TRIAL_TABLE} (ts, world_id, node_id, charges_budget)
VALUES (?, ?, ?, 0)
"""

#: The read path's column list, in the table's declaration order — one
#: string shared by every SELECT so the reader and the record cannot drift
#: apart in column order, the way the ledger store's own ``_COLUMNS``
#: constant holds its reads.
_SELECT_TRIALS = f"SELECT {', '.join(_TRIAL_COLUMNS)} FROM {TRIAL_TABLE}"


def _validated_charges_budget(value: Any) -> bool:
    """Validate the trial's budget bit, which a bootstrap trial never charges.

    The read path's coercion: SQLite hands a ``BOOLEAN`` column back as the
    ``int`` ``0``, and a stored value that is neither ``0`` nor ``1`` is a
    hand that reached past the append — refused rather than served, the
    same check the ledger's own ``validated_charges_budget`` applies to its
    rows.  ``True`` — in either of its spellings, the bool or the stored
    ``1`` — is refused *here* before the table ever sees it, because this
    member's table cannot hold it and a record that said a bootstrap trial
    charged budget would describe no row this store can write — the
    CHECK's twin at the value layer, where a hand-built record is refused
    by name instead of by constraint.
    """
    if isinstance(value, bool) or (isinstance(value, int) and value in (0, 1)):
        if value:
            raise BootstrapPoolError(
                "a bootstrap trial charges no statistical budget "
                "(docs/nullius-tech-architecture.md §10.6: perfect labels, "
                "zero statistical-budget cost), so no record of one can say "
                "it did — a trial row that charged budget is a row this "
                "member's table refuses by its own CHECK, and a hand-built "
                "record of it is refused here, before the store is touched"
            )
        return False
    raise BootstrapPoolError(
        f"a trial's charges_budget is the bit §8's column carries, stored "
        f"as 0 or 1 — got {value!r} ({type(value).__name__}); a value that "
        "is not one of the two spellings is a hand that reached past the "
        "append, and a row that cannot say whether it charged budget is a "
        "row no audit could classify"
    )


class TrialRecord:
    """One persisted bootstrap trial, as the log reads it back — feature 185's row.

    The whole of what a bootstrap trial records against the accounting: the
    order it was appended in (``seq``), the instant it ran (``ts``), the
    world it probed and the cell it evaluated (``world_id``, ``node_id`` —
    both read from the observation's own payload, so the row is attributed
    by the trial rather than restated by the caller), and the directive
    (``charges_budget`` — :data:`TRIAL_CHARGES_BUDGET`, ``False``, the only
    value the table's CHECK admits).  Held as an immutable value for the
    reason :class:`~bootstrap.WorldRecord` holds a world's identity: it is
    what every report over the log is made of, and a record of a past trial
    is a fact — superseded by new rows, never edited.

    Construction validates and canonicalises, so an instance is trustworthy
    by construction: the store's write builds its return value through this
    constructor, and the read path rebuilds rows through it, which is how a
    malformed or hand-edited row is refused rather than served.  The one
    value the constructor refuses outright is the one the feature's sentence
    exists to keep out of the accounting — a ``charges_budget`` of ``True``
    (see :func:`_validated_charges_budget`).
    """

    __slots__ = ("charges_budget", "node_id", "seq", "ts", "world_id")

    def __init__(
        self,
        *,
        seq: int,
        ts: dt.datetime,
        world_id: str,
        node_id: str,
        charges_budget: Any = TRIAL_CHARGES_BUDGET,
    ) -> None:
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise BootstrapPoolError(
                f"a trial's seq is an integer assigned by the log's append "
                f"— got {seq!r} ({type(seq).__name__}); the sequence is the "
                "row's order in an append-only log, and a value that is not "
                "one names no order the log can reproduce"
            )
        if seq < 1:
            raise BootstrapPoolError(
                f"a trial's seq is 1 or greater (the log counts from 1) — "
                f"got {seq!r}; the first append is the log's first row, and "
                "a seq below it names a row no append ever wrote"
            )
        if not isinstance(ts, dt.datetime) or ts.tzinfo is None or ts.utcoffset() is None:
            raise BootstrapPoolError(
                f"a trial's ts is a timezone-aware datetime — got {ts!r}; "
                "the stamp records when the trial ran, and a naive one "
                "would place it hours away from the process that ran it, "
                "in whatever zone the host happens to keep"
            )
        for field, value in (("world_id", world_id), ("node_id", node_id)):
            if not isinstance(value, str) or not value.strip():
                raise BootstrapPoolError(
                    f"a trial's {field} is a non-empty string — got "
                    f"{value!r} ({type(value).__name__}); the row is "
                    "attributed by the two names it carries, and a trial "
                    "that cannot name its world and its cell records "
                    "nothing a report over the log could attribute"
                )
        self.seq = seq
        self.ts = ts
        self.world_id = world_id
        self.node_id = node_id
        self.charges_budget = _validated_charges_budget(charges_budget)

    @classmethod
    def from_row(cls, row: tuple) -> TrialRecord:
        """Unpack one trial row into the record it holds, in column order.

        The inverse of :meth:`row`, and the only place a stored row becomes
        a value — so the read path and the write path cannot disagree on
        what a trial's record is.  The stored ``0`` of the budget bit is
        coerced to its :class:`bool` here (never with ``bool()`` — SQLite
        answers an ``int``, and the affinity trap is to coerce what was
        never checked); the stamp is parsed back through the pool's own
        strict reader, so a row whose ``ts`` cannot be reconstructed is
        refused rather than served.
        """
        seq, ts, world_id, node_id, charges_budget = row
        return cls(
            seq=seq,
            ts=parsed_instant(ts),
            world_id=world_id,
            node_id=node_id,
            charges_budget=charges_budget,
        )

    def row(self) -> dict[str, object]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The payload a report writes down, in the table's own spellings:
        ``ts`` as the ISO-8601 UTC text the column holds, and
        ``charges_budget`` as the ``0``/``1`` a SQLite ``BOOLEAN`` column
        stores — which is ``0``, always, because that is the only value the
        record can hold.
        """
        return {
            "seq": self.seq,
            "ts": _stamp(self.ts),
            "world_id": self.world_id,
            "node_id": self.node_id,
            "charges_budget": 1 if self.charges_budget else 0,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TrialRecord):
            return NotImplemented
        return (self.seq, self.ts, self.world_id, self.node_id) == (
            other.seq,
            other.ts,
            other.world_id,
            other.node_id,
        )

    def __hash__(self) -> int:
        return hash((self.seq, self.ts, self.world_id, self.node_id))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TrialRecord(seq={self.seq!r}, world_id={self.world_id!r}, "
            f"node_id={self.node_id!r}, charges_budget={self.charges_budget!r})"
        )


def _probing_question(question: Any) -> Any:
    """Check that ``question`` fronts the probe surface, and return it.

    Duck-typed rather than ``isinstance``, for the reason every seam in
    this member is: the module loader imports the member under a synthetic
    name and re-executes it, so the composed question ``create_app()``
    serves is a second ``BootstrapQuestion`` class object, and an
    ``isinstance`` gate here would refuse the very question the
    composition seam exists to serve.  What is checked is the one method
    the recorder calls through — ``probe_batch``, feature 184's reveal —
    so a string, a bare object or a world handed in by mistake is refused
    naming what was missing, *before* the recorder has touched the disk:
    a validation that ran after the schema work would be a validation
    that ran too late to be one.
    """
    probe = getattr(question, "probe_batch", None)
    if not callable(probe):
        raise BootstrapPoolError(
            f"trials are recorded through the question interface a policy "
            f"is handed — got {question!r} ({type(question).__name__}), "
            "which has no callable ``probe_batch``; a trial on a bootstrap "
            "world is a probe of it (feature 184's seam), and an object "
            "that cannot probe names no trial this ledger could record"
        )
    return probe


def _attributed(observation: Any, node_id: str) -> tuple[str, str]:
    """Read the (world, node) an observation attributes its label to.

    The row is built from the payload the probe returned rather than from
    values the caller restated — the attribution discipline the
    observation carries for §10.6's *"report the two pools separately"*:
    the observation knows which world it was earned on, and a recorder
    that let the caller re-say it could seat a trial on a world that
    never ran it.  Both names are validated for the shape a row needs,
    naming the observation that could not give them.
    """
    world_id = getattr(observation, "world_id", None)
    if not isinstance(world_id, str) or not world_id.strip():
        raise BootstrapPoolError(
            f"the observation a probe returns carries the world it was "
            f"earned on — the observation for {node_id!r} answered "
            f"{world_id!r} ({type(world_id).__name__}); a trial row is "
            "attributed by its payload, and an observation that cannot "
            "name its world records nothing a report could split the two "
            "pools by"
        )
    observed_node = getattr(observation, "node_id", None)
    if not isinstance(observed_node, str) or not observed_node.strip():
        raise BootstrapPoolError(
            f"the observation a probe returns carries the node it labels "
            f"— the observation keyed {node_id!r} answered "
            f"{observed_node!r} ({type(observed_node).__name__}); the row "
            "is the trial's own record, and an observation that cannot "
            "name its cell records nothing the log could attribute"
        )
    return world_id, observed_node


class BootstrapTrialLedger:
    """The bootstrap half of the trial record — feature 185's store.

    Constructed with the database URL it persists into — the same
    ``DATABASE_URL`` the pool resolves, and deliberately not a second
    registered component for it (see the module docstring's *"No
    component"* argument: one deployment seat, two tables).  The one
    write is :meth:`record_trials`, which reveals a batch through a
    question's own ``probe_batch`` and persists one row per newly
    revealed cell, ``charges_budget`` written as the literal ``0`` of the
    INSERT — there is no parameter for it, no directive to trust, and no
    way to charge budget for a bootstrap world even by mistake.  The
    reads are :meth:`trials` (the log, ascending by ``seq``) and
    :meth:`trial_count` (a number, not every record built to count it).

    The class resolves its path lazily, so constructing one performs no
    I/O — composition-time work must not touch the disk, the contract
    every store in this workspace states — and recording happens only
    when a caller asks for it, on demand, the terms the pool's authoring
    takes.  Nothing is decremented anywhere: the budget the question
    reports stays whole before and after every row this store writes,
    because the trial's ``charges_budget`` is a *statement* the row
    makes, not a booking the store performs.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise BootstrapPoolError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction, for the pool's
        # own reason: building the ledger is composition-time work and must
        # not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> BootstrapTrialLedger | None:
        """The trial ledger ``DATABASE_URL`` names, or ``None`` when it names none.

        The pool's own contract, spelled for this store: an empty or
        whitespace-only value counts as unset, absent is not an error — it
        is a deployment without a relational store, a discoverable state —
        and the caller who means to record trials is the caller that must
        not find itself silently recording nothing.  The same variable the
        pool reads, read the same way, so the worlds and the trials of a
        deployment can never come to live in two different databases.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this ledger persists into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this ledger, resolved on first use.

        Translated by the pool's own URL-to-path spelling (one translation
        of ``sqlite:///`` in this member, refused in this member's
        vocabulary), so a URL the pool cannot speak is a URL this store
        cannot speak either — two stores over one deployment fact, one
        grammar.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The store's shape ----------------------------------------------------

    def ensure_schema(self) -> None:
        """Bring the database to the shape this ledger reads and writes, idempotently.

        Public for the pool's own reason: it is a real operation — an
        operator pointing this member at a fresh database runs it once, and
        a test seeds a log into exactly the schema the store will read.  One
        ``CREATE TABLE IF NOT EXISTS``, so a fresh database and one this
        ledger already prepared take the same path and leave the same
        schema.  Opens its own connection and commits it (the shape the
        pool's own ``ensure_schema`` takes), so a caller that wants only
        the schema does not open a connection it will not use.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this ledger's shape first.

        The caller owns the connection; use it as a context manager to
        commit.  The schema work is delegated to :meth:`ensure_schema`
        rather than inlined, mirroring the pool's own split.
        """
        self.ensure_schema()
        return sqlite3.connect(self.path)

    # -- The write ---------------------------------------------------------------

    def record_trials(
        self,
        question: Any,
        cells: Iterable[str],
        *,
        recorded_at: dt.datetime | None = None,
    ) -> tuple[TrialRecord, ...]:
        """Reveal ``cells`` through ``question`` and record the trials — the feature's whole call.

        Probes the batch through the question's own
        :meth:`~bootstrap.BootstrapQuestion.probe_batch` — feature 184's
        seam, so the reveal and the record are one act and cannot drift
        apart — and writes one row per **newly** revealed cell: the
        observation's own ``world_id`` and ``node_id`` attribute the row,
        the stamp is ``recorded_at`` (defaulting to the current UTC
        instant, second-truncated), and ``charges_budget`` is the literal
        ``0`` of the INSERT statement — the method has no parameter for
        it, because §10.6 publishes that a bootstrap world's probes are
        free and there is no directive to trust.  Returns the records the
        call seated, in probe order (ascending node id within the batch,
        appended order across batches).

        A batch that names a cell the world does not hold is refused by
        the question before anything is written — the probe validates up
        front and raises
        :class:`~bootstrap.BootstrapWorldError`, which propagates
        untranslated (it is the question's refusal, in the caller's
        vocabulary already), and the write runs only after the probe
        answered, so a refused batch records nothing.  A re-probe of cells
        the question already holds records nothing new and returns
        ``()``: the trial already has its row, and the log is
        append-only, not re-appendable.  Two questions over one world
        each record their own trials for the same cell — each replay's
        evaluation is its own trial, and both are free.

        Refuses, in this order, each naming what it is about:

        1. an object that is not a question (no callable ``probe_batch``)
           — refused before anything touches the disk;
        2. a probe whose payload cannot attribute a row (an observation
           with no usable ``world_id`` or ``node_id``) — refused before
           the transaction opens, so a half-shaped payload records
           nothing;
        3. a ``recorded_at`` that is not a timezone-aware datetime — the
           stamp is part of the log's history, refused by the pool's own
           instant validation;
        4. a database this store cannot speak (the URL is the store's
           contract, refused in this member's vocabulary at path
           resolution).
        """
        probe = _probing_question(question)
        # The probe first: its refusals are the question's own (a cell
        # outside the lattice never reaches this store), and its payload
        # is what the rows are built from.  Validated in full before the
        # transaction opens, so a payload that cannot attribute a row
        # records nothing rather than half a batch.
        observations = probe(cells)
        if not hasattr(observations, "items"):
            raise BootstrapPoolError(
                f"a probe answers the observations it revealed, keyed by "
                f"node id — got {observations!r} ({type(observations).__name__}), "
                "which is not a mapping; the trial rows are built from the "
                "payload the question returned, and a probe that cannot be "
                "read by node records nothing this ledger could attribute"
            )
        attributed: list[tuple[str, str]] = []
        for node_id, observation in observations.items():
            attributed.append(_attributed(observation, node_id))
        stamp = _stamp(
            recorded_at if recorded_at is not None else dt.datetime.now(dt.UTC)
        )
        records: list[TrialRecord] = []
        with closing(self._connect()) as connection, connection:
            for world_id, node_id in attributed:
                cursor = connection.execute(
                    _INSERT_TRIAL, (stamp, world_id, node_id)
                )
                records.append(
                    TrialRecord(
                        seq=int(cursor.lastrowid),
                        ts=parsed_instant(stamp),
                        world_id=world_id,
                        node_id=node_id,
                        charges_budget=TRIAL_CHARGES_BUDGET,
                    )
                )
        return tuple(records)

    # -- The reads ------------------------------------------------------------

    def trials(self, world_id: str | None = None) -> tuple[TrialRecord, ...]:
        """Every trial the log holds, ascending by ``seq`` — the log's own order.

        The whole log, or — with ``world_id`` — one world's trials, which
        is §10.6's *"report the two pools separately"* restated for the
        trial record: the row carries its world, so the split is a filter
        the caller asks for by name rather than an arithmetic over
        attributed scores.  Explicitly ordered by ``seq`` under §12's
        determinism rule, so two reads of one log return the same
        sequence whatever the storage engine's accident, and a report
        rendered from the tuple is reproducible.  Empty when nothing has
        been recorded — an empty log is a statement about what has been
        probed, not about the deployment.
        """
        if world_id is not None and (not isinstance(world_id, str) or not world_id.strip()):
            raise BootstrapPoolError(
                f"a world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how the log is "
                "filtered to one world's trials, and an id that is not one "
                "addresses no trials this ledger holds"
            )
        with closing(self._connect()) as connection:
            if world_id is None:
                rows = connection.execute(
                    f"{_SELECT_TRIALS} ORDER BY seq"
                ).fetchall()
            else:
                rows = connection.execute(
                    f"{_SELECT_TRIALS} WHERE world_id = ? ORDER BY seq",
                    (world_id,),
                ).fetchall()
        return tuple(TrialRecord.from_row(row) for row in rows)

    def trial_count(self, world_id: str | None = None) -> int:
        """How many trials the log holds — a number, not every record built to count it.

        The whole log, or one world's, for the same reason
        :meth:`~bootstrap.BootstrapPool.world_count` counts rows rather
        than building every record to len() them: the question a dreaming
        loop asks of a log is a number, and a number that built every
        record of the log to answer would pay for the whole history to
        return one integer.  Every row it counts holds ``charges_budget``
        ``0`` — the table's CHECK admits nothing else — so the count is
        exactly the number of trials that can never inflate
        ``K_effective`` (feature 93's filter, answered from the far side).
        """
        if world_id is not None and (not isinstance(world_id, str) or not world_id.strip()):
            raise BootstrapPoolError(
                f"a world id is a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the id is how the log's "
                "count is filtered to one world's trials, and an id that "
                "is not one addresses no trials this ledger holds"
            )
        with closing(self._connect()) as connection:
            if world_id is None:
                (held,) = connection.execute(
                    f"SELECT COUNT(*) FROM {TRIAL_TABLE}"
                ).fetchone()
            else:
                (held,) = connection.execute(
                    f"SELECT COUNT(*) FROM {TRIAL_TABLE} WHERE world_id = ?",
                    (world_id,),
                ).fetchone()
        return int(held)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"BootstrapTrialLedger(database_url={self._database_url!r})"
