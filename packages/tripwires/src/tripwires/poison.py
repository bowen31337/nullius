"""Poisoning a failing node and its subtree — feature 131's persistence half.

app_spec.xml, "Leakage Tripwires", feature 131: *"System persists a tripwire
failure as poisoning the node together with its entire subtree."*
docs/alpha-engine-prd.md §C6 states the same act in the sentence that gives it
its weight — *"Run periodically on any candidate; a failure poisons the node
**and its entire subtree**, which is excised from the replay pool"* — and
docs/nullius-tech-architecture.md §892 reaches for the same construct from the
sandbox's side (*"quarantine the node and its subtree"*).  Feature 125 states
the verdict; :mod:`tripwires.corpus` proves the probe catches planted leaks;
this module is where a stated verdict becomes a fact about the tree.

**The subtree is the transitive closure of ``parent_id``, and that is the whole
of it.**  The discovery tree is feature 97's ``node`` table: a minted-UUID key
and a self-referencing ``parent_id`` foreign key, ``NULL`` at a root.  "The node
together with its entire subtree" therefore has exactly one reading — the
failing node, its children, their children, to the leaves — and the recursion
follows that edge, scoped to the failing node's campaign (§9.1: *"every tree
query in the system is already scoped to one campaign"*).  The scope is not
decoration: without it a ``parent_id`` that ever pointed across a campaign
boundary would drag an unrelated branch into a poisoning it has nothing to do
with, and the failure would be attributed to a campaign that never ran it.

The closure is computed over the campaign's edges
(:meth:`PoisonStore._subtree`) rather than by a recursive CTE, and that is a
deliberate departure from the obvious spelling — the CTE hangs on a cyclic
``parent_id`` instead of refusing it, so the guard that was supposed to catch a
broken tree would never run.  The walk's docstring tells that story; the short
version is that the one input this store cannot trust is exactly the one a
``UNION ALL`` recursion cannot survive.

**Why the subtree and not only the node.**  A rejection at a node is evidence
about the *branch*, not about one row: a leak in a node's mechanism is a leak in
every descendant built by refining that mechanism, because the child differs
from the parent by an accepted revision, not by an independent draw.  Poisoning
the node alone would leave the replay pool holding every score the branch
contributed, and §C5's dreaming loop — which replays *stored trees* against
candidate policies — would go on learning from the very scores the tripwire just
said were leaked.  That is the failure mode the whole category exists to
prevent, and it is why the unit of this feature is the subtree.

**Irreversible, and stated as such.**  There is no ``unpoison``, no ``clear``,
no ``reset`` — in this module or in the store's schema (``poisoned_at`` is
``NULL`` until a poisoning writes it; nothing ever writes it back).  A
poisoning is an irreversible act (§C2 and feature 132 both lean on that), so a
record of *when* it happened is the only defensible state: a node whose mark
could be cleared would make "was this branch replayed after it was poisoned?"
unanswerable, and the audit feature 132 needs — *which* scores the branch
contributed, so they can be rejected — would have nothing to key on.  The
store's one value-write besides the marks is the append of the audit rows, and
a re-run of a poisoning is an idempotent refresh that says ``False``.

**What is written, and where.**  Two things, in one transaction:

* the mark — ``node.poisoned_at`` set to the poisoning instant on the failing
  node and every node in its subtree, in one ``UPDATE`` driven by the same
  recursive CTE the walk uses;
* the record — one row per poisoned node in this member's own
  ``tripwire_poison`` table, carrying the failing node it descends from, the
  tripwire that fired, the verdict's outcome word (§8's ``tripwire_fail``) and
  the verdict's own arithmetic (the surviving Sharpe, the threshold, the seed,
  the level, the horizon, the measured date count).

The record is a row per poisoned node rather than one row per poisoning because
feature 132 excises *every score that branch contributed*, and that question —
"was this node poisoned, and by what?" — is asked a node at a time, in the
replay path, where a whole-tree document would have to be parsed to answer it.
The verdict's numbers travel on every row so a reader can check the arithmetic
from the record alone, which is the same reason feature 125 carries them on the
verdict: a poisoning that rejects a subtree is irreversible and must be
auditable from what was written.

**The verdict is validated before anything is written, and by re-deriving it.**
A caller cannot hand this module a failure it invented.  The verdict's own
invariants are enforced at construction (feature 125's), and this module adds
the two a *persistence* feature must not take on trust: the outcome word must
be the verdict's own translation of its ``rejected`` bit, and ``rejected`` must
be what its statistic and its threshold actually decide.  The second is the one
worth naming — a hand-built verdict claiming ``rejected=True`` beside a
surviving Sharpe that clears no bar would poison a subtree on a failure that
never happened, and re-deriving the comparison here costs one ``abs`` and
closes it.  A verdict that *passed* is refused with the same clarity: there is
nothing to poison, and a store that accepted one would be a store that marks
nodes for failing probes that succeeded.

**A node the tree does not hold is refused, not created.**  The rule the guard
and the verdict store both keep, from the other side: a poisoning is a fact
about a node's *place in a tree*, and a mark written onto a row this module
invented would be poisoning a branch nobody expanded — with ``parent_id``
``NULL`` it would look like a root, and the subtree the verdict rejected would
be silently absent from the record.  So the failing node must be held, and its
campaign is read from the row rather than taken from the caller: the scope of
the recursion is the tree's own fact about the node, not a value the caller can
get wrong.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime``, ``uuid`` and
``urllib.parse``; no third-party import at module scope, so the factory's scan
— which imports this package to fire its ``@register`` — pays nothing for this
module.  That matters the same way it matters for the member's probe: the
tripwires run inside the frozen evaluator image, and a persistence feature that
pulled a driver in at import would give that image a dependency it cannot name.
Like every store in this workspace, construction performs no I/O — the path is
resolved on first use — so composing the application never opens a database.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import TripwirePoisonError
from .layout import (
    DATABASE_URL_ENV,
    NODE_CAMPAIGN_COLUMN,
    NODE_ID_COLUMN,
    NODE_PARENT_COLUMN,
    NODE_POISONED_COLUMN,
    NODE_TABLE,
    dialect_of,
    node_bootstrap_schema,
    parsed_instant,
    sqlite_path,
    validated_instant,
    validated_node_id,
)
from .time_shuffle import TimeShuffleVerdict

__all__ = [
    "COMPONENT_NAME",
    "POISON_TABLE",
    "PoisonRecord",
    "PoisonStore",
    "PoisonedSubtree",
    "poison_node",
    "poisoned_node_ids",
]

#: The component name this member registers its poison store under — a third
#: name rather than a third component under ``"tripwires"``, the convention
#: :mod:`nulloracle` states for its own three: the probe answers *what is the
#: composed tripwire suite?* while this answers *what is the composed store a
#: tripwire failure is persisted to?*, and a caller asking for one must not be
#: handed the other.  The names are not interchangeable and the registry must
#: not pretend they are.
COMPONENT_NAME = "tripwires-poison"

#: This member's own table — one row per poisoned node, the audit trail feature
#: 132 excises from.  It is *not* the ``node`` table and it is not a column on
#: it: the mark belongs on the node (that is what the tree walk and the replay
#: path read) and the record belongs here (that is what the *audit* reads), and
#: a store that folded the two together would have to widen a table three
#: features short of it — 0118's own "why these five, and no more".
POISON_TABLE = "tripwire_poison"

#: The columns of :data:`POISON_TABLE`, in the order the insert statement
#: names them and the order :func:`_record_from_row` unpacks them.  Spelled
#: once so the write and the read cannot drift apart on a column order — the
#: failure a positional ``SELECT *`` invites.
_COLUMNS = (
    "node_id, root_node_id, campaign_id, subtree_depth, tripwire, outcome, "
    "rejected, surviving_sharpe, threshold, seed, level, horizon, "
    "measured_dates, poisoned_at, detected_at"
)

_SCHEMA = f"""
-- Feature 131: a tripwire failure, persisted as a poisoning of one node and
-- every node beneath it.  One row per poisoned node — not one per poisoning —
-- because feature 132 asks "was this node poisoned, and by what?" a node at a
-- time in the replay path, and a whole-tree document would have to be parsed
-- to answer it.
--
-- `node_id` is the row's key: a node is poisoned once, and re-running the
-- poisoning over the same failure refreshes the row rather than appending a
-- second one, so the audit cannot show a branch poisoned twice by one probe.
-- `root_node_id` is the *failing* node — the one the verdict probed — which is
-- what makes a subtree recoverable from the table: every row sharing it is
-- exactly the subtree of that failure.
--
-- The verdict's own arithmetic travels on every row (surviving_sharpe,
-- threshold, seed, level, horizon, measured_dates) so a reader can recompute
-- the decision from the record alone.  That is the same discipline feature
-- 125's verdict states for itself, and it is not redundant here: the verdict
-- is an in-memory value and this row is what survives it.
CREATE TABLE IF NOT EXISTS {POISON_TABLE} (
    node_id          TEXT NOT NULL PRIMARY KEY,  -- the poisoned node, canonical UUID
    root_node_id     TEXT NOT NULL,              -- the failing node the verdict probed
    campaign_id      TEXT NOT NULL,              -- the tree's own campaign scope
    subtree_depth    INTEGER NOT NULL,           -- hops below the failing node (0 = it)
    tripwire         TEXT NOT NULL,              -- which probe fired (time-shuffle)
    outcome          TEXT NOT NULL,              -- §8's word: tripwire_fail
    rejected         INTEGER NOT NULL,           -- the verdict's detection bit
    surviving_sharpe REAL NOT NULL,              -- the statistic judged
    threshold        REAL NOT NULL,              -- the bar it was judged against
    seed             INTEGER NOT NULL,           -- rebuilds the probe's pairing
    level            REAL NOT NULL,              -- rebuilds the threshold
    horizon          INTEGER NOT NULL,           -- the target series probed
    measured_dates   INTEGER NOT NULL,           -- the T behind the threshold
    poisoned_at      TEXT NOT NULL,              -- when the mark was written (ISO UTC)
    detected_at      TEXT NOT NULL               -- the instant the probe stated it
);
"""

#: The index the replay path wants: "which nodes were poisoned in this
#: campaign, and from which failure?" is a lookup by ``root_node_id`` for the
#: subtree walk and by ``campaign_id`` for the pool's refusal (§C7's pool is
#: read per campaign).  Created here beside the table rather than left to a
#: later feature for the reason 0113 states from the other side: this module
#: is the only thing that knows how *it* will be read.
_INDEX = (
    f"CREATE INDEX IF NOT EXISTS {POISON_TABLE}_root_campaign "
    f"ON {POISON_TABLE} (root_node_id, campaign_id)"
)


# -- The value -----------------------------------------------------------------


class PoisonedSubtree:
    """Feature 131's answer: the branch a tripwire failure marked, and what did it.

    A *value* — frozen, self-describing — carrying both halves of the feature's
    sentence: the node the verdict probed, the nodes the poisoning actually
    marked (the failing node first, then its descendants in walk order), and the
    verdict's own terms so the record explains itself.  It is what
    :func:`poison_node` returns, and it is deliberately not a row: the caller
    wants *what happened to the tree*, and the rows are the store's business.

    ``replayed`` answers the question a re-run asks — whether *this* call
    changed anything.  A store that reported the same thing on a first poisoning
    and on a retry would make a double-mark indistinguishable from a first one,
    which is precisely the distinction §8's ``tree_appended`` idiom draws for
    the evaluator's own one-shot write.
    """

    __slots__ = (
        "_campaign_id",
        "_node_ids",
        "_outcome",
        "_poisoned_at",
        "_replayed",
        "_root_node_id",
        "_surviving_sharpe",
        "_threshold",
        "_tripwire",
    )

    def __init__(
        self,
        *,
        root_node_id: Any,
        campaign_id: Any,
        node_ids: Sequence[str],
        tripwire: str,
        outcome: str,
        surviving_sharpe: float,
        threshold: float,
        poisoned_at: Any,
        replayed: bool,
    ) -> None:
        object.__setattr__(self, "_root_node_id", validated_node_id(root_node_id))
        object.__setattr__(self, "_campaign_id", validated_node_id(campaign_id))
        marked = tuple(validated_node_id(node) for node in node_ids)
        if not marked:
            raise TripwirePoisonError(
                "a poisoning marks at least the failing node itself; got an "
                "empty subtree, which would be a failure recorded against no "
                "node at all"
            )
        if marked[0] != object.__getattribute__(self, "_root_node_id"):
            raise TripwirePoisonError(
                f"a poisoned subtree's first node must be the failing node "
                f"{object.__getattribute__(self, '_root_node_id')!r}, got "
                f"{marked[0]!r}; the walk starts at the node the verdict "
                "probed, and a subtree that does not contain it did not come "
                "from this store's recursion"
            )
        if len(set(marked)) != len(marked):
            raise TripwirePoisonError(
                "a poisoned subtree names each node once; a repeated node "
                "means the recursion reached one by two paths, which a tree "
                "with one parent per node cannot do"
            )
        object.__setattr__(self, "_node_ids", marked)
        if not isinstance(tripwire, str) or not tripwire.strip():
            raise TripwirePoisonError(
                f"a poisoning must name the tripwire that fired, got "
                f"{tripwire!r}; the record says *which* probe rejected the "
                "branch, and a blank name is an unattributable deletion"
            )
        object.__setattr__(self, "_tripwire", tripwire)
        if outcome != "tripwire_fail":
            raise TripwirePoisonError(
                f"a poisoning's outcome is §8's 'tripwire_fail', got "
                f"{outcome!r}; only a failed tripwire poisons a subtree, and a "
                "record carrying any other word would make the poisoning "
                "indistinguishable from a timeout or a crash at the ledger"
            )
        object.__setattr__(self, "_outcome", outcome)
        for name, value in (
            ("surviving_sharpe", surviving_sharpe),
            ("threshold", threshold),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePoisonError(
                    f"a poisoning's {name} must be a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePoisonError(
                    f"a poisoning's {name} is not finite ({value!r}); a NaN "
                    "or ±inf would reach the audit trail dressed as the "
                    "arithmetic the decision was made on"
                )
        object.__setattr__(self, "_surviving_sharpe", float(surviving_sharpe))
        object.__setattr__(self, "_threshold", float(threshold))
        stamp = validated_instant(poisoned_at)
        object.__setattr__(self, "_poisoned_at", stamp)
        if not isinstance(replayed, bool):
            raise TripwirePoisonError(
                f"replayed must be a bool, got {replayed!r} "
                f"({type(replayed).__name__}); whether this call changed the "
                "tree is one bit, and a truthy-looking non-bool is the value "
                "that would silently misreport a re-run as a first poisoning"
            )
        object.__setattr__(self, "_replayed", replayed)

    @property
    def root_node_id(self) -> str:
        """The failing node — the one the verdict probed.  Canonical UUID text."""
        return self._root_node_id

    @property
    def campaign_id(self) -> str:
        """The campaign whose tree was marked, read from the tree, not the caller."""
        return self._campaign_id

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Every poisoned node, the failing node first, then its descendants."""
        return self._node_ids

    @property
    def size(self) -> int:
        """How many nodes the poisoning marked — one, for a leaf failure.

        One is the honest and common answer: a failure at a *leaf* — the
        frontier the discovery loop is still expanding — poisons exactly the
        node that failed.  The subtree is what makes the feature more than
        that, not what it always is.
        """
        return len(self._node_ids)

    @property
    def tripwire(self) -> str:
        """Which probe fired — ``time-shuffle`` for feature 125's, and its name."""
        return self._tripwire

    @property
    def outcome(self) -> str:
        """The verdict's §8 word — always ``tripwire_fail`` for a poisoning."""
        return self._outcome

    @property
    def surviving_sharpe(self) -> float:
        """The statistic the verdict judged — carried so the record explains itself."""
        return self._surviving_sharpe

    @property
    def threshold(self) -> float:
        """The bar the statistic cleared — recomputable from the seed and level."""
        return self._threshold

    @property
    def poisoned_at(self) -> dt.datetime:
        """When the mark was written, UTC."""
        return self._poisoned_at

    @property
    def replayed(self) -> bool:
        """Whether this poisoning found the branch *already* marked.

        ``True`` means the store refreshed a poisoning an earlier call made and
        changed nothing: the nodes were poisoned, and this call did not do it.
        A caller retrying after a crash reads this to tell "I marked it" from
        "it was marked", the distinction feature 85's ``tree_appended`` draws.
        """
        return self._replayed

    def to_payload(self) -> dict[str, Any]:
        """The subtree as a plain mapping, for a log line or an operator's report."""
        return {
            "root_node_id": self._root_node_id,
            "campaign_id": self._campaign_id,
            "size": self.size,
            "node_ids": list(self._node_ids),
            "tripwire": self._tripwire,
            "outcome": self._outcome,
            "surviving_sharpe": self._surviving_sharpe,
            "threshold": self._threshold,
            "poisoned_at": self._poisoned_at.isoformat(),
            "replayed": self._replayed,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PoisonedSubtree):
            return NotImplemented
        return (
            self._root_node_id == other._root_node_id
            and self._campaign_id == other._campaign_id
            and self._node_ids == other._node_ids
            and self._tripwire == other._tripwire
            and self._outcome == other._outcome
            and self._surviving_sharpe == other._surviving_sharpe
            and self._threshold == other._threshold
            and self._poisoned_at == other._poisoned_at
            and self._replayed == other._replayed
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._root_node_id,
                self._campaign_id,
                self._node_ids,
                self._tripwire,
                self._outcome,
                self._surviving_sharpe,
                self._threshold,
                self._poisoned_at,
                self._replayed,
            )
        )

    def __repr__(self) -> str:
        return (
            f"PoisonedSubtree(root={self._root_node_id!r}, "
            f"nodes={self.size}, tripwire={self._tripwire!r}, "
            f"outcome={self._outcome!r}, "
            f"{'replayed' if self._replayed else 'marked'})"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        # Frozen: the record of an irreversible act, so once stated it cannot be
        # edited into a different one.
        raise AttributeError(
            f"{type(self).__name__} is frozen; a poisoning that has been "
            "recorded cannot be edited into a different one"
        )


# -- The verdict check -----------------------------------------------------------


#: The fields a poisoning reads off a verdict.  Spelled once so the three
#: checks below and the audit row's columns cannot drift apart on what a
#: verdict is made of — and so the structural check names them in one place.
_VERDICT_FIELDS = (
    "node_id",
    "tripwire",
    "horizon",
    "dates",
    "seed",
    "level",
    "surviving_sharpe",
    "threshold",
    "rejected",
    "outcome",
)


def _validate_failure(verdict: Any) -> TimeShuffleVerdict:
    """Hold a verdict to everything a poisoning must not take on trust.

    Checked *structurally* — by the fields the record is built from — rather
    than by ``isinstance``, and that is not a shortcut.  The factory's scan
    imports this member under a synthetic module name
    (``_nullius_scanned_tripwires``), so a suite that also imported ``tripwires``
    canonically holds two distinct ``TimeShuffleVerdict`` classes for one source
    file and ``isinstance`` cannot hold across them; the member's own component
    suite documents the same seam for the same reason.  Asking for the ten
    fields the record actually reads is the stronger check anyway: a verdict is
    the *terms a decision was made on*, and an object that carries all ten of
    them, with a re-derivable decision among them, **is** a verdict for every
    purpose this store has.

    What the check is for, and what the verdict's own constructor cannot do for
    it.  ``TimeShuffleVerdict`` already enforces its invariants at construction;
    this function adds the three things a *persistence* feature must not
    delegate:

    * the shape — a producer that is not a verdict at all has no terms to
      store, and the refusal names the missing fields rather than an attribute
      error three frames deeper;
    * the outcome word — §8's ``tripwire_fail`` is what a ledger row and a
      poisoned node's record must agree on, and a record whose word was
      unrelated to its bit would classify the failure as something else;
    * the decision itself — ``rejected`` is **re-derived** from the statistic
      and the threshold rather than believed.  A hand-built verdict claiming a
      failure beside a surviving Sharpe that clears no bar would poison a
      subtree on a leak that never happened: an irreversible act performed on
      an invented cause, which is the one class of error this store cannot
      repair by being run again.

    A verdict that *passed* is refused by the same comparison, with a message
    that says so: there is nothing to poison, and a store that accepted one
    would mark nodes for probes that succeeded.
    """
    missing = [field for field in _VERDICT_FIELDS if not hasattr(verdict, field)]
    if missing:
        raise TripwirePoisonError(
            f"a poisoning is stated by a time-shuffle verdict, and "
            f"{type(verdict).__name__} carries none of "
            f"{', '.join(missing)}; the record's arithmetic comes from the "
            "verdict, and a producer whose terms the store cannot read would "
            "leave it storing a decision it cannot check"
        )
    if verdict.outcome != "tripwire_fail":
        raise TripwirePoisonError(
            f"a poisoning is stated by a failed tripwire, got the verdict's "
            f"outcome {verdict.outcome!r} (§8's word for a probe that found no "
            "leakage); there is nothing to poison, and marking a branch for a "
            "probe that passed would excise scores nothing rejected"
        )
    if not verdict.rejected:
        raise TripwirePoisonError(
            f"a poisoning is stated by a rejection, but this verdict's "
            f"rejected is {verdict.rejected!r}; a poisoning has to be a "
            "failure that happened, not one the caller asserted"
        )
    if not abs(verdict.surviving_sharpe) > verdict.threshold:
        raise TripwirePoisonError(
            f"the verdict claims rejected={verdict.rejected!r} but its own "
            f"arithmetic disagrees (|{verdict.surviving_sharpe!r}| vs "
            f"{verdict.threshold!r}); the subtree an irreversible poisoning "
            "marks must be marked on a judgement that survives being "
            "re-derived, and this one does not"
        )
    return verdict


# -- The store -------------------------------------------------------------------


class PoisonStore:
    """Feature 131's persistence: the mark on the tree and the record beside it.

    Constructed with the database URL it writes to; :meth:`poison` marks a
    failing node and its subtree and appends the audit rows; :meth:`poisoned`
    reads one node's mark back; :meth:`subtree_of` reads the branch a past
    failure marked.  The class resolves its path lazily, so constructing one
    performs no I/O — composition-time work must not touch the disk, the
    contract every store in this workspace states.

    The store holds no verdicts and no scores: it writes what a failure *was*
    and reads which nodes it marked.  The replay pool's excision of those
    scores is feature 132's — this store makes the fact true and legible, and
    the pool's own refusal is where the consequence must live so it holds no
    matter what wrote the mark.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise TripwirePoisonError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> PoisonStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        poison component — a discoverable state, not an exception — while the
        evaluation loop that must persist §C6's rejection is the caller that
        must not find itself in it.
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
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = sqlite_path(self._database_url)
        return self._path

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store reads and writes, idempotently.

        Public because it is a real operation and not an implementation detail:
        an operator pointing this member at a database the orchestrator has not
        migrated yet runs it once, and a test seeds a tree into exactly the
        schema the store will read.  Doing the work inside :meth:`_connect`
        instead and leaving this private would force both callers to reach
        through a leading underscore for something they legitimately want, which
        is how a private method quietly becomes the public one.

        What it does, and the middle step is the interesting one.  The bootstrap
        creates ``node`` if the migration has not (see
        :func:`~tripwires.layout.node_bootstrap_schema` for the five columns and
        the one this member adds); the probe then asks whether the table —
        whichever of the two created it — carries ``poisoned_at``, and issues
        the ``ALTER TABLE`` when it does not.  The probe exists because SQLite's
        ``ADD COLUMN`` has no ``IF NOT EXISTS``: there is no single statement
        that both creates and migrates, and a second ``CREATE TABLE`` on a table
        the migration already made would change nothing at all — leaving the
        feature's own column absent, the first poisoning failing on a missing
        column, and the failure surfacing far from its cause.

        Every statement is ``IF NOT EXISTS`` or guarded by a probe, so running
        it against a fresh database, a migrated one and one this store already
        prepared all take the same path and leave the same schema.

        It opens its own connection and commits it, and it does **not** go
        through :meth:`_connect`: that method calls this one, and a public entry
        point that reached back through it would be a pair of methods that
        recurse into each other until the stack ran out.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self._apply_schema(connection)

    def _apply_schema(self, connection: sqlite3.Connection) -> None:
        """The DDL itself, on a connection the caller already holds open.

        Split out so :meth:`ensure_schema` and :meth:`_connect` share one
        spelling of the schema without either calling the other's opener — the
        DDL has exactly one home, and the two openers differ only in whether
        they hand the connection back.
        """
        connection.executescript(node_bootstrap_schema(dialect_of(connection)))
        if not self._has_poisoned_column(connection):
            connection.execute(
                f"ALTER TABLE {NODE_TABLE} "
                f"ADD COLUMN {NODE_POISONED_COLUMN} TIMESTAMPTZ"
            )
        connection.executescript(_SCHEMA)
        connection.execute(_INDEX)

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this store's shape first.

        Foreign keys are enabled, as in every SQLite store in the workspace, so
        a poisoning against a database whose tree has no such node is refused by
        the same constraint production enforces rather than by this store's
        optimism.  The caller owns the connection; use it as a context manager
        to commit.

        The schema work is delegated to :meth:`ensure_schema` rather than
        inlined, so a caller that only wants the schema does not have to open a
        connection it will not use.
        """
        self.ensure_schema()
        path = self.path
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _has_poisoned_column(connection: sqlite3.Connection) -> bool:
        """Whether the ``node`` table already carries ``poisoned_at``.

        ``PRAGMA table_info`` rather than a ``SELECT`` against the column: the
        pragma answers for an empty table and a populated one alike, and a
        probe that had to find a row before it could tell would report "no
        such column" on the very database a first poisoning is about to be
        written to.
        """
        rows = connection.execute(f"PRAGMA table_info({NODE_TABLE})").fetchall()
        return any(row[1] == NODE_POISONED_COLUMN for row in rows)

    # -- Feature 131: the poisoning -------------------------------------------

    def poison(
        self,
        verdict: TimeShuffleVerdict,
        *,
        poisoned_at: dt.datetime | None = None,
    ) -> PoisonedSubtree:
        """Poison the verdict's node and its entire subtree — feature 131.

        The whole of the feature in one call: the verdict is checked to be a
        failure that happened, the failing node is confirmed to be held by the
        tree (and its campaign read from the tree's own row), the subtree is
        walked over ``parent_id`` inside that campaign, and — in one
        transaction — ``node.poisoned_at`` is set on every node of it and one
        audit row per node is appended to :data:`POISON_TABLE`.

        ``poisoned_at`` defaults to the current UTC instant truncated to the
        second, and on a branch that is *already* poisoned it defaults to the
        instant the tree already holds rather than to now (see
        :func:`_stamp_for`).  It is a parameter at all so a replay can stamp the
        instant the failure *happened* rather than the instant the retry ran —
        the same reason feature 124 takes an instant where the ledger takes one,
        and the same reason it is validated: a naive datetime would place a
        poisoning hours away from the trial that caused it and nothing would
        look wrong.

        Re-running it over the same verdict is a refresh and not a second
        poisoning: the marks are set to the same values, the audit rows are
        upserted on their key, the original instant is kept, and the returned
        subtree reports ``replayed`` as ``True``.  The action is irreversible —
        nothing in this store or its schema clears a mark — so a re-run must be
        idempotent, and a crash between the mark and the record must be
        repairable by running it again.

        Refuses, in this order, and each refusal names what it is about:

        1. a verdict that is not a stated rejection, or whose arithmetic does
           not re-derive its own rejection
           (:class:`~tripwires.TripwirePoisonError`) — there is nothing to
           poison;
        2. a failing node the tree does not hold — a poisoning marks a node's
           *place in a tree*, and a row this store invented would be a branch
           nobody expanded, looking like a root, with the subtree the verdict
           rejected silently absent;
        3. a subtree whose recursion came back to where it started — refused
           rather than walked, because a cycle means the edge the whole feature
           stands on no longer describes a tree, and marking a branch on a
           broken walk would poison an unbounded set;
        4. a mark that did not survive being read back, or a write that could
           not be completed.
        """
        checked = _validate_failure(verdict)
        root = validated_node_id(checked.node_id)
        with closing(self._connect()) as connection, connection:
            campaign = self._require_node(connection, root)
            walked = self._subtree(connection, root, campaign)
            nodes = tuple(node for _, node in walked)
            if not nodes or nodes[0] != root:
                raise TripwirePoisonError(
                    f"the subtree walk from {root!r} in campaign {campaign!r} "
                    "did not return the failing node itself first; the walk "
                    "starts at the node the verdict probed and reads the "
                    "node's own campaign, so a walk that omits its own root "
                    "was run against a tree the store's read does not describe"
                )
            held = self._marked_instant(connection, root)
            stamp = _stamp_for(poisoned_at, held)
            self._mark(connection, nodes, stamp)
            self._record(connection, checked, walked, campaign, root, stamp)
            self._confirm(connection, nodes, stamp)
        return PoisonedSubtree(
            root_node_id=root,
            campaign_id=campaign,
            node_ids=nodes,
            tripwire=checked.tripwire,
            outcome=checked.outcome,
            surviving_sharpe=checked.surviving_sharpe,
            threshold=checked.threshold,
            poisoned_at=stamp,
            replayed=held is not None,
        )

    def _require_node(self, connection: sqlite3.Connection, node_id: str) -> str:
        """The campaign of ``node_id``, or a refusal naming the absent node.

        Reads the campaign from the node's own row rather than accepting one
        from the caller: the scope of the subtree recursion is the tree's fact
        about the node, and a caller-supplied scope that disagreed would walk
        another campaign's branch — or, worse, walk nothing and report a
        subtree of one.  A node the tree does not hold is refused by name, the
        rule the guard and the verdict store both keep from the other side.
        """
        cursor = connection.execute(
            f"SELECT {NODE_CAMPAIGN_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node_id,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise TripwirePoisonError(
                f"the tree holds no node {node_id!r}, so there is no branch to "
                "poison; a poisoning marks a node *and the nodes beneath it*, "
                "which is a fact about a node's place in the tree — a row this "
                "store invented would be a branch nobody expanded, and the "
                "subtree the verdict rejected would be silently absent from "
                "the record"
            )
        return validated_node_id(row[0])

    def _subtree(
        self, connection: sqlite3.Connection, root: str, campaign: str
    ) -> tuple[tuple[int, str], ...]:
        """The subtree of ``root``, failing node first — the walk over ``parent_id``.

        Returns ``(depth, node_id)`` pairs in walk order, the failing node
        first, rather than bare ids.  The depth is not a presentational detail:
        :meth:`_record` stores it so :meth:`subtree_of` can reproduce this
        order from the audit table, and a caller that wanted only the ids takes
        them off the pairs (which is exactly what :meth:`poison` does, once,
        for the mark, the record and the returned value).

        ``parent_id`` is the edge and the campaign is the scope; the subtree is
        the transitive closure of the first inside the second.  The walk begins
        at the failing node itself, so a *leaf* failure — the frontier the loop
        is still expanding, and the common case — returns a subtree of exactly
        one node and the feature degenerates to "poison the node", which is what
        the sentence means when there is nothing beneath it.

        **Walked here rather than in a recursive CTE, and the reason is a bug
        this replaced.**  The first version handed the recursion to SQLite:

            WITH RECURSIVE subtree(id, depth) AS (... UNION ALL ...)

        which is the natural spelling and is wrong in one case that matters.
        ``parent_id`` is a foreign key and the tree's *writer* is what makes it
        a tree; this store cannot enforce acyclicity across arbitrary writers,
        and a ``UNION ALL`` recursion over a cycle does not terminate — it walks
        forever, and the duplicate check that was supposed to refuse it never
        ran, because the query it guards never returned.  The failure was not a
        wrong answer but a hang, with a transaction open on the table.  (The
        member's own suite caught it: the cycle test did not fail, it stopped.)

        So the closure is computed over the campaign's edges fetched once, with
        the traversal carrying the ancestry it has travelled, and the one way
        ``parent_id`` can fail to describe a tree is *named* rather than
        silently absorbed — the property a recursive CTE made hard to reach.

        **The one way, and why it is the only one.**  ``parent_id`` is a single
        column, so a row names exactly one parent: a *diamond* — one node
        reachable by two independent paths — cannot be written down, and the
        walk cannot meet one.  The only way to reach a node twice is to come
        back around a cycle, so a node that is its own ancestor is the entire
        failure mode, and it is refused by name.  A branch whose floor is its
        own ceiling is not a subtree: the recursion closes on itself, the set it
        encloses is bounded only by arithmetic that has stopped meaning
        anything, and marking it would be an irreversible act on a branch the
        operator cannot have meant.  It is not repaired by re-running the
        feature either, so it is not guessed at — the refusal says so, and
        nothing is written.

        Each node appears once, and the ordering is deterministic — walk depth
        first, then the id — so two runs over the same failure return the same
        tuple in the same order and a record can be compared across runs.
        """
        children: dict[str, list[str]] = {}
        for node, parent in connection.execute(
            f"SELECT {NODE_ID_COLUMN}, {NODE_PARENT_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_CAMPAIGN_COLUMN} = ?",
            (campaign,),
        ).fetchall():
            if parent is None:
                continue
            children.setdefault(validated_node_id(parent), []).append(
                validated_node_id(node)
            )
        for kids in children.values():
            # Sorted so the walk's shape does not depend on the row order the
            # database happened to return — the tuple is compared across runs.
            kids.sort()

        ordered: list[tuple[int, str]] = []
        # An explicit stack rather than recursion, and each entry carries the
        # path from the root to itself: a deep chain would otherwise be bounded
        # by Python's recursion limit, which is a property of the interpreter
        # and not of the tree.
        stack: list[tuple[str, int, frozenset[str]]] = [(root, 0, frozenset())]
        while stack:
            node, depth, ancestors = stack.pop()
            if node in ancestors:
                raise TripwirePoisonError(
                    f"the walk from {root!r} came back to {node!r} through its "
                    f"own ancestry, so `parent_id` does not describe a tree "
                    f"over campaign {campaign!r}: a node that is its own "
                    "descendant has no subtree — the recursion closes on itself "
                    "— and poisoning the set it encloses would be an "
                    "irreversible act on a branch the operator cannot have "
                    "meant. Repair the tree and re-run; this poisoning wrote "
                    "nothing"
                )
            ordered.append((depth, node))
            here = ancestors | {node}
            for kid in children.get(node, ()):
                stack.append((kid, depth + 1, here))
        ordered.sort()
        return tuple(ordered)

    @staticmethod
    def _marked_instant(
        connection: sqlite3.Connection, root: str
    ) -> dt.datetime | None:
        """When the failing node was already marked, or ``None`` if it was not.

        Read before the write, inside the same transaction, so the answer is
        about the state *this* call found.  Only the failing node's mark is
        consulted, and deliberately: it is the record of the act, and a subtree
        whose root is marked while a descendant is not is the half-written state
        a crash between two statements leaves — a state a re-run repairs, and
        one that a per-descendant check would report as "not poisoned" and go on
        building on.

        The *instant* is returned rather than a bit because a re-run must keep
        the moment the branch was first halted — see :func:`_stamp_for`.
        """
        row = connection.execute(
            f"SELECT {NODE_POISONED_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (root,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return _parse_instant(row[0])

    @staticmethod
    def _mark(
        connection: sqlite3.Connection, nodes: Sequence[str], stamp: dt.datetime
    ) -> None:
        """Set ``node.poisoned_at`` on every node of the subtree, in one statement.

        One ``UPDATE`` over the walk's own node list, not a statement per node:
        the mark is one act about one branch, and a loop of updates would make
        it a sequence of acts a crash could stop half-way — leaving half a
        subtree marked and the other half still replayable, which is exactly the
        state the replay pool must never read.
        """
        placeholders = ", ".join("?" for _ in nodes)
        connection.execute(
            f"UPDATE {NODE_TABLE} SET {NODE_POISONED_COLUMN} = ? "
            f"WHERE {NODE_ID_COLUMN} IN ({placeholders})",
            (stamp.isoformat(), *nodes),
        )

    @staticmethod
    def _record(
        connection: sqlite3.Connection,
        verdict: TimeShuffleVerdict,
        walked: Sequence[tuple[int, str]],
        campaign: str,
        root: str,
        stamp: dt.datetime,
    ) -> None:
        """Append one audit row per poisoned node — the branch's provenance.

        Upserted on ``node_id``, so a re-run refreshes rather than accumulating
        a second row per node: the question feature 132 asks is "was this node
        poisoned, and by what?", and two rows for one node would make that
        question answer "twice" for a failure that happened once.

        The verdict's own terms travel on every row, including on the
        descendants' rows where they are the *root's* terms rather than the
        node's own.  That is the point: the row says which failure marked this
        node, and the failure is the root's — a descendant was not probed, it
        was in the wrong branch.

        ``subtree_depth`` is the walk's own depth for the node — zero at the
        failing node — and it is stored so :meth:`PoisonStore.subtree_of` can
        reproduce the walk's *order* from the audit table alone.  Without it
        the read has only ids to sort by, and a minted UUID sorts wherever it
        likes: the read would return the right *set* in an order that agreed
        with :attr:`PoisonedSubtree.node_ids` until a random id happened to
        fall the other way, which is the worst kind of disagreement — silent,
        and only sometimes.
        """
        detected = _verdict_instant()
        connection.executemany(
            f"""
            INSERT INTO {POISON_TABLE} ({_COLUMNS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                root_node_id     = excluded.root_node_id,
                campaign_id      = excluded.campaign_id,
                subtree_depth    = excluded.subtree_depth,
                tripwire         = excluded.tripwire,
                outcome          = excluded.outcome,
                rejected         = excluded.rejected,
                surviving_sharpe = excluded.surviving_sharpe,
                threshold        = excluded.threshold,
                seed             = excluded.seed,
                level            = excluded.level,
                horizon          = excluded.horizon,
                measured_dates   = excluded.measured_dates,
                poisoned_at      = excluded.poisoned_at,
                detected_at      = excluded.detected_at
            """,
            [
                (
                    node,
                    root,
                    campaign,
                    depth,
                    verdict.tripwire,
                    verdict.outcome,
                    1 if verdict.rejected else 0,
                    verdict.surviving_sharpe,
                    verdict.threshold,
                    verdict.seed,
                    verdict.level,
                    verdict.horizon,
                    verdict.dates,
                    stamp.isoformat(),
                    detected,
                )
                for depth, node in walked
            ],
        )

    @staticmethod
    def _confirm(
        connection: sqlite3.Connection,
        nodes: Sequence[str],
        stamp: dt.datetime,
    ) -> None:
        """Read the marks back and refuse a write that did not land.

        The same discipline feature 124's ``void_if_detectable`` applies to the
        campaign row: the status the store *actually holds* and the act it
        reports must agree, and a disagreement is not a poisoning.  A mark is
        irreversible and feature 132 will excise scores on the strength of it,
        so "the UPDATE returned without raising" is not good enough evidence
        that a branch is poisoned.
        """
        placeholders = ", ".join("?" for _ in nodes)
        rows = connection.execute(
            f"SELECT {NODE_ID_COLUMN}, {NODE_POISONED_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} IN ({placeholders})",
            tuple(nodes),
        ).fetchall()
        marked = {validated_node_id(row[0]) for row in rows if row[1]}
        if marked != set(nodes):
            missing = sorted(set(nodes) - marked)
            raise TripwirePoisonError(
                f"the poisoning wrote {len(marked)} of {len(nodes)} mark(s); "
                f"{', '.join(missing)} came back unmarked. A branch that reads "
                "as poisoned while the replay pool still holds its scores is "
                "the failure this feature exists to prevent, so the store "
                "refuses rather than reporting a subtree it did not mark"
            )
        # The stamp is checked too: a mark written with a different instant is a
        # write this call did not make, and the audit's ordering hangs on it.
        expected = stamp.isoformat()
        wrong = sorted(
            validated_node_id(row[0]) for row in rows if row[1] and row[1] != expected
        )
        if wrong:
            raise TripwirePoisonError(
                f"the poisoning stamped {', '.join(wrong)} with an instant "
                f"other than {expected!r}; the record's ordering against the "
                "trial that caused it rests on this column, and a mark written "
                "by something else is a poisoning this call did not make"
            )

    # -- Reading it back ------------------------------------------------------

    def poisoned(self, node_id: Any) -> dt.datetime | None:
        """When ``node_id`` was poisoned, or ``None`` when it is clean.

        ``None`` means *the node is not poisoned* — the honest answer for a
        node the tree holds with ``poisoned_at`` ``NULL``.  It does **not** mean
        the read failed: an unreachable database or an id that cannot join the
        tree's key raises, so a caller can never mistake a broken store for a
        clean branch and go on replaying scores the tripwire rejected.  That
        distinction is the whole reason this method does not simply answer a
        boolean.

        A node the tree does not hold is answered ``None`` as well, and for a
        reason worth stating: "is this node poisoned?" is asked by the replay
        path about the ids its stored trees carry, and a node the tree has
        forgotten was never marked within it.  The *write* is where an absent
        node is a refusal — there, an invented row would be an act — but a read
        that raised for one would turn a stale id in an old tree into a crash
        in the replay path.
        """
        node = validated_node_id(node_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {NODE_POISONED_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (node,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return _parse_instant(row[0])

    def is_poisoned(self, node_id: Any) -> bool:
        """Whether ``node_id`` is poisoned — the replay path's one-bit question.

        Reads through :meth:`poisoned`, so the store has one answer to *when*
        and this method is only its collapse to a bit.  A caller that needs to
        tell a broken store from a clean branch asks :meth:`poisoned` directly;
        one that only has to decide whether to replay a node asks this.
        """
        return self.poisoned(node_id) is not None

    def subtree_of(self, root_node_id: Any) -> tuple[str, ...]:
        """The nodes a *past* failure marked, failing node first.

        Read from the audit table rather than re-walked over ``parent_id``, and
        that is deliberate: the table is the record of what was actually
        marked, so this answers "which nodes did that poisoning excise?" even
        if the tree has grown children beneath them since — a re-walk would
        quietly include nodes that never belonged to the failure.  Feature 132's
        excision reads this, and it must see the acts, not the tree's current
        shape.

        The order is the *walk's* order, reproduced from the row's own
        ``subtree_depth`` and then the id — the same ``(depth, id)`` ordering
        :meth:`_subtree` sorts by.  Ordering by the id alone was wrong and
        looked right: a minted UUID sorts wherever it likes, so the read would
        agree with :attr:`PoisonedSubtree.node_ids` until one happened to fall
        the other way.  The root is not special-cased because it does not need
        to be: its depth is zero, which is the smallest.

        A root with no rows — a node no poisoning ever named — answers the empty
        tuple, which is the honest reading of "this node poisoned nothing": the
        table records acts, and it holds none for a node that was never the
        origin of a failure.  It is not the same question as
        :meth:`poisoned`, which asks whether a node was *in* a poisoned subtree.
        """
        root = validated_node_id(root_node_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT node_id FROM {POISON_TABLE} WHERE root_node_id = ? "
                "ORDER BY subtree_depth, node_id",
                (root,),
            ).fetchall()
        return tuple(validated_node_id(row[0]) for row in rows)

    def load(self, node_id: Any) -> PoisonRecord | None:
        """The audit row feature 131 wrote for ``node_id``, or ``None``.

        ``None`` means no poisoning recorded this node.  The row carries the
        whole failure — which tripwire fired, the failing node, the statistic
        and the bar, the seed and level that rebuild the pairing and the
        threshold — so a reader auditing an excision (feature 132) can check the
        decision from the record alone, as they can from the verdict itself.
        """
        node = validated_node_id(node_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM {POISON_TABLE} WHERE node_id = ?",
                (node,),
            ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)


class PoisonRecord:
    """One row of :data:`POISON_TABLE` — a node's poisoning, as it was recorded.

    Frozen and validated in :meth:`__init__`, and deliberately *not* the
    verdict: the verdict is the in-memory value feature 125 states, and this is
    what survives it.  The two carry the same terms because the row is the
    verdict's persistence, not a second opinion about it — which is why
    :meth:`as_verdict_terms` hands back exactly the dictionary a reader would
    rebuild the verdict from, rather than a re-derived verdict this class would
    have to re-validate.
    """

    __slots__ = (
        "_campaign_id",
        "_detected_at",
        "_horizon",
        "_level",
        "_measured_dates",
        "_node_id",
        "_outcome",
        "_poisoned_at",
        "_rejected",
        "_root_node_id",
        "_seed",
        "_subtree_depth",
        "_surviving_sharpe",
        "_threshold",
        "_tripwire",
    )

    def __init__(
        self,
        *,
        node_id: Any,
        root_node_id: Any,
        campaign_id: Any,
        subtree_depth: int,
        tripwire: str,
        outcome: str,
        rejected: bool,
        surviving_sharpe: float,
        threshold: float,
        seed: int,
        level: float,
        horizon: int,
        measured_dates: int,
        poisoned_at: dt.datetime,
        detected_at: dt.datetime,
    ) -> None:
        object.__setattr__(self, "_node_id", validated_node_id(node_id))
        object.__setattr__(self, "_root_node_id", validated_node_id(root_node_id))
        object.__setattr__(self, "_campaign_id", validated_node_id(campaign_id))
        object.__setattr__(self, "_subtree_depth", int(subtree_depth))
        object.__setattr__(self, "_tripwire", tripwire)
        object.__setattr__(self, "_outcome", outcome)
        object.__setattr__(self, "_rejected", bool(rejected))
        object.__setattr__(self, "_surviving_sharpe", float(surviving_sharpe))
        object.__setattr__(self, "_threshold", float(threshold))
        object.__setattr__(self, "_seed", int(seed))
        object.__setattr__(self, "_level", float(level))
        object.__setattr__(self, "_horizon", int(horizon))
        object.__setattr__(self, "_measured_dates", int(measured_dates))
        object.__setattr__(self, "_poisoned_at", poisoned_at)
        object.__setattr__(self, "_detected_at", detected_at)

    @property
    def node_id(self) -> str:
        """The poisoned node — the row's key."""
        return self._node_id

    @property
    def root_node_id(self) -> str:
        """The failing node the verdict probed and the walk started from."""
        return self._root_node_id

    @property
    def campaign_id(self) -> str:
        """The campaign whose tree the failure poisoned."""
        return self._campaign_id

    @property
    def subtree_depth(self) -> int:
        """How many hops below the failing node this one sits — zero for the root.

        Read back off the row rather than recomputed, so a reader auditing a
        past excision sees the shape of the branch *as it was poisoned*: a
        node's place in a tree can change (feature 97's loop keeps expanding
        it) and its depth at the moment of the act is the one the record is
        about.
        """
        return self._subtree_depth

    @property
    def tripwire(self) -> str:
        """Which probe fired."""
        return self._tripwire

    @property
    def outcome(self) -> str:
        """§8's word for the failure — ``tripwire_fail``."""
        return self._outcome

    @property
    def rejected(self) -> bool:
        """The verdict's detection bit, as recorded."""
        return self._rejected

    @property
    def surviving_sharpe(self) -> float:
        """The statistic the verdict judged."""
        return self._surviving_sharpe

    @property
    def threshold(self) -> float:
        """The bar it cleared."""
        return self._threshold

    @property
    def seed(self) -> int:
        """The seed the probe's pairing was drawn from — rebuilds the shuffle."""
        return self._seed

    @property
    def level(self) -> float:
        """The two-sided level the threshold was taken at."""
        return self._level

    @property
    def horizon(self) -> int:
        """The target series the probe resolved to."""
        return self._horizon

    @property
    def measured_dates(self) -> int:
        """The ``T`` behind the threshold's ``√T``."""
        return self._measured_dates

    @property
    def poisoned_at(self) -> dt.datetime:
        """When the mark was written, UTC."""
        return self._poisoned_at

    @property
    def detected_at(self) -> dt.datetime:
        """When the probe stated the failure it was written from, UTC."""
        return self._detected_at

    def as_verdict_terms(self) -> dict[str, Any]:
        """The verdict's terms, as the record holds them.

        Exactly the fields a reader needs to rebuild the decision — the node,
        the horizon, the date count, the seed, the level, the statistic, the
        bar and the outcome — named the way
        :class:`~tripwires.time_shuffle.TimeShuffleVerdict` names them, so an
        audit compares like with like and does not translate between two
        vocabularies for one fact.
        """
        return {
            "node_id": self._root_node_id,
            "tripwire": self._tripwire,
            "horizon": self._horizon,
            "dates": self._measured_dates,
            "seed": self._seed,
            "level": self._level,
            "surviving_sharpe": self._surviving_sharpe,
            "threshold": self._threshold,
            "rejected": self._rejected,
            "outcome": self._outcome,
        }

    def to_payload(self) -> dict[str, Any]:
        """The record as a plain mapping, for a log line or an operator's report."""
        payload = self.as_verdict_terms()
        payload.update(
            {
                "node_id": self._node_id,
                "campaign_id": self._campaign_id,
                "subtree_depth": self._subtree_depth,
                "poisoned_at": self._poisoned_at.isoformat(),
                "detected_at": self._detected_at.isoformat(),
            }
        )
        return payload

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PoisonRecord):
            return NotImplemented
        return all(
            getattr(self, slot) == getattr(other, slot) for slot in type(self).__slots__
        )

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, slot) for slot in type(self).__slots__))

    def __repr__(self) -> str:
        return (
            f"PoisonRecord(node={self._node_id!r}, root={self._root_node_id!r}, "
            f"tripwire={self._tripwire!r}, outcome={self._outcome!r}, "
            f"poisoned_at={self._poisoned_at.isoformat()})"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            f"{type(self).__name__} is frozen; a recorded poisoning cannot be "
            "edited into a different one"
        )


def _record_from_row(row: Sequence[Any]) -> PoisonRecord:
    """Build a :class:`PoisonRecord` from the tuple :data:`_COLUMNS` selects.

    Positional, and that is why :data:`_COLUMNS` is spelled once and shared
    between the insert and this read: a ``SELECT *`` and a hand-counted unpack
    are the pair that drifts apart silently, and the drift shows up as a
    poisoning whose statistic is its own level.
    """
    (
        node_id,
        root_node_id,
        campaign_id,
        subtree_depth,
        tripwire,
        outcome,
        rejected,
        surviving_sharpe,
        threshold,
        seed,
        level,
        horizon,
        measured_dates,
        poisoned_at,
        detected_at,
    ) = row
    return PoisonRecord(
        node_id=node_id,
        root_node_id=root_node_id,
        campaign_id=campaign_id,
        subtree_depth=subtree_depth,
        tripwire=tripwire,
        outcome=outcome,
        rejected=bool(rejected),
        surviving_sharpe=surviving_sharpe,
        threshold=threshold,
        seed=seed,
        level=level,
        horizon=horizon,
        measured_dates=measured_dates,
        poisoned_at=_parse_instant(poisoned_at),
        detected_at=_parse_instant(detected_at),
    )


def _utc_now() -> dt.datetime:
    """The current UTC instant, truncated to the second.

    Truncated for the reason feature 123's guard truncates its own stamp: a
    poisoning instant is read back beside instants every other store wrote, and
    a stored microsecond is a precision the ISO spelling carries but no reader
    of the trail compares on.  Truncating at the *write* is what makes a
    re-run's stamp equal the first one's when a caller passes the first one's
    instant back, which is how a replay reproduces a poisoning exactly.
    """
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _stamp_for(
    poisoned_at: dt.datetime | None, held: dt.datetime | None
) -> dt.datetime:
    """The instant a poisoning carries, given what the tree already holds.

    Three cases, and each is a different sentence:

    * the branch is clean — the stamp is the caller's, or now, and this call is
      the act that poisons it;
    * the branch is already marked and the caller named an instant — the
      caller's instant wins, because a replay re-running a failure means to
      record when the failure *happened*, and refusing it would make a poisoned
      branch's history unreproducible from the record;
    * the branch is already marked and the caller named none — the instant
      already on the node is kept.  A retry after a crash is a refresh, not a
      second act, and rewriting the stamp would move the moment a branch was
      halted later with every retry: the audit's ordering against the trial
      that caused the failure would then track the retries rather than the
      failure, and the drift would be invisible because every row would agree.
    """
    if poisoned_at is not None:
        return validated_instant(poisoned_at)
    if held is not None:
        return held
    return _utc_now()


def _parse_instant(value: Any) -> dt.datetime:
    """Parse a stored instant — :func:`~tripwires.layout.parsed_instant`, kept by name.

    The parser moved to :mod:`tripwires.layout` when feature 132 became its
    second caller: the pool's ``replay_score.created_at`` is read back exactly
    as this store's ``poisoned_at`` is, and two spellings of one parser is the
    drift the member's one-provenance rule forbids.  This name stays because
    three call sites in this module read a stored instant and the helper is
    what they read it with; deleting it would make each of them name the layout
    module for a value this module wrote.

    A thin delegation and nothing else, deliberately: the shared function
    already raises :class:`~tripwires.TripwirePoisonError` for an unparseable
    value, which is this module's own error, so unlike
    :func:`~tripwires.excise._pool_instant` there is no translation to do here.
    """
    return parsed_instant(value)


def _verdict_instant() -> str:
    """The instant the failure was *detected and persisted*, as an ISO-8601 UTC string.

    A verdict carries no timestamp of its own — deliberately, because a probe
    is a pure function of its inputs and a clock reading would make two runs of
    the same panel differ, which §12's determinism contract forbids.  So the
    record's ``detected_at`` is stamped at the write and dates the
    *persistence* of the failure, not the failure's arithmetic; the column
    beside it, ``poisoned_at``, dates the mark.  The two are named apart
    because they answer different questions — *when was this branch halted?*
    and *when was the judgement that halted it recorded?* — and a single column
    for both would have to pick one of the two answers to be wrong about.
    """
    return _utc_now().isoformat()


# -- The two module-level entry points -------------------------------------------


def poison_node(
    verdict: TimeShuffleVerdict,
    *,
    database_url: str | None = None,
    store: PoisonStore | None = None,
    poisoned_at: dt.datetime | None = None,
) -> PoisonedSubtree:
    """Persist ``verdict`` as poisoning its node and its subtree — feature 131.

    The module-level spelling of :meth:`PoisonStore.poison`, for a caller that
    has a verdict and wants the feature rather than an object: it composes a
    store from ``DATABASE_URL`` (or the URL handed to it) and runs the
    poisoning.  A ``store`` may be handed in instead, which is what the
    composed component is and what a test passes to pin the database it wrote
    to.

    Refuses a call that names no store — neither a ``store`` nor a
    ``database_url`` nor a ``DATABASE_URL`` — with
    :class:`~tripwires.TripwirePoisonError`, and that is deliberate rather than
    a fall-through.  A deployment with no relational store cannot persist a
    poisoning *at all*, and a version of this function that quietly did
    nothing would let an evaluation loop believe §C6's rejection had been
    recorded while every score the branch contributed went on being replayed.
    """
    resolved = store if store is not None else _store_from(database_url)
    return resolved.poison(verdict, poisoned_at=poisoned_at)


def poisoned_node_ids(
    verdict: TimeShuffleVerdict,
    *,
    database_url: str | None = None,
    store: PoisonStore | None = None,
) -> tuple[str, ...]:
    """Persist ``verdict`` and answer the ids it poisoned — the branch, marked.

    The shape an evaluation loop wants: it holds a verdict, it needs the list
    of nodes whose scores it must stop replaying, and it does not want to hold
    a store to get it.  Returns the same tuple :attr:`PoisonedSubtree.node_ids`
    carries, so a caller that needs the rest of the record asks for the subtree
    instead and is not served by a second code path.
    """
    return poison_node(verdict, database_url=database_url, store=store).node_ids


def _store_from(database_url: str | None) -> PoisonStore:
    """The store a module-level call runs against, or a refusal naming why not.

    An explicit ``database_url`` wins over the environment, so a caller with a
    URL in hand never depends on ambient state — the same precedence the
    evaluator's own entry points give their argument.  Absent both, the refusal
    names the variable, because "nothing was configured" is the one failure a
    caller can fix without reading this module.
    """
    if database_url is not None:
        return PoisonStore(database_url)
    resolved = PoisonStore.resolve()
    if resolved is None:
        raise TripwirePoisonError(
            f"no store to persist a poisoning to: {DATABASE_URL_ENV} names no "
            "relational store and no explicit database_url was passed. "
            "Feature 131 persists a tripwire failure as a fact about the tree, "
            "and a caller that cannot write that fact must not proceed as "
            "though it had — the replay pool would go on holding every score "
            "the poisoned branch contributed"
        )
    return resolved
