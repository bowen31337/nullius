"""Persisting a node's authoring model — feature 203's write path.

app_spec.xml feature 203: *System persists ``agent_model_id`` per node as a
provider, model and version triple rather than a rolling alias.*
:mod:`providers._pinning` owns what the triple *is*; this module owns the one
act the sentence names — writing it onto a node — and the four ways that act
can fail to be honest.

What this store does not own, and why that decides its shape
------------------------------------------------------------

The ``agent_model_id`` **column** belongs to the core migration
``0115_agent_model_trio`` (feature 100) and the ``node`` **table** to
``0118_node_table.py`` (feature 97); both are schema the spec files under
"Database Schema & Migrations" and neither is this member's to create, alter
or version.  So this store is the same shape ``discovery.CampaignRecords`` is —
a writer over a table someone else's migration owns — with one difference in
how it fails, and the difference is deliberate.

``CampaignRecords._connect`` deliberately *lets SQLite raise* ``no such table:
campaign``, on the argument that the writer must not invent the schema it
writes into and an operator should read the real error.  This store cannot take
that stance, because its failure has an actionable name and the raw error does
not say it: a database that has run ``0118`` and not ``0115`` has a ``node``
table and **no authoring-model column**, so the honest report is not *"no such
table"* or *"no such column"* but *"this tree store has not reached revision
0115"*.  A pin is an operation with a documented prerequisite, and
:class:`~providers.PinColumnError` names it.  That is the whole divergence.

What is deliberately *not* checked is anything further up or down the chain.
The storage class of the value is SQLite's own affinity business (0114 explains
at length why the types above the column are hints and not constraints), and
this member reads and writes through the DBAPI rather than restating 0115's
typemap — see ``packages/providers/tests/conftest.py`` for the one place in
this tree that test does restate it, and why.

The states, and the answer to each
----------------------------------

A node row exists or it does not, and its ``agent_model_id`` holds one of four
things: a triple equal to the one being persisted, a *different* triple, a
value that is not a triple at all, or nothing.  Every one of the four is a
reachable state in this workspace and each gets its own answer, because
collapsing any two of them would lose a fact an operator needs:

* **No node row** → :class:`~providers.NodeNotRecordedError`.  A pin is a
  column on a node; stamping one without a node would mean writing a tree row,
  which this member does not own.
* **A different triple** → :class:`~providers.ModelPinConflictError`.  A node's
  author is history — it is the axis the M3 paired comparison stratifies on
  (PRD §5a, architecture §14.1 mitigation 3) — so re-stamping it would move
  every score the node carries into another stratum while leaving the scores
  untouched.  Both triples are named in the refusal so an operator can see
  which two runs are claiming one node.
* **The same triple** → answered, not written: :attr:`NodePin.stamped` is
  ``False``.  This is the idempotent retry §14 demands of the workers this
  runs on, and it is the *reason* the write is a compare-then-set rather than a
  blind ``UPDATE`` — a retry that overwrote an equal value would be
  indistinguishable from one that overwrote a different value.
* **Nothing** → written, :attr:`NodePin.stamped` is ``True``.  This is not
  hypothetical: ``0115``'s ``NOT NULL`` is a bare constraint with no default,
  which SQLite and Postgres both *refuse* to add to a populated table —
  *"the repair is a backfill, not a spell"*, in that migration's own words —
  and this branch is that backfill.  A row can also reach the state by an
  explicit ``NULL`` on a tree built by a bootstrap schema that omits the
  column (``tripwires.layout.node_bootstrap_schema`` creates 0118's five
  structural columns and its own, and creates *no* authoring-model trio).
* **A value that is not a triple** → :class:`~providers.RollingAliasError`,
  raised rather than overwritten.  This is the one case where refusing costs
  something real, and it is still the right answer: the stored alias *is* the
  corruption feature 203 exists to end, and a store that quietly replaced it
  would erase the only evidence that a node was authored under a re-routed id.
  The operator sees which node, which value, and what to backfill.

One node, one statement, one transaction
----------------------------------------

The read of the row and the ``UPDATE`` are one unit of work on one connection,
so the compare-then-set cannot interleave with a second writer: two workers
pinning one node serialize, and the second sees the first's value rather than
a stale read.  That serialization is the store's own; it is not a schema
constraint, because no migration declares one on this column and inventing a
constraint here would be this feature legislating DDL it does not own.

Construction performs no I/O
----------------------------

The database path is resolved on first use, so composing the application never
opens a database — the contract every store in this workspace states, and the
one :class:`~providers.AgentModelPins.resolve` exists to honour: a
``DATABASE_URL`` whose scheme this member cannot speak is refused by name the
first time a pin is actually persisted, not when the component is built.

Stdlib-only, like the rest of this package: ``sqlite3`` and ``urllib.parse``
are the whole of the I/O.
"""

from __future__ import annotations

import os
import sqlite3
import uuid as _uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._pin_errors import (
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    PinColumnError,
    RollingAliasError,
)
from ._pinning import (
    AGENT_MODEL_ID_COLUMN,
    MODEL_PIN_REVISION,
    NODE_TABLE,
    ModelPin,
    require_agent_model_id,
)

__all__ = [
    "DATABASE_URL_ENV",
    "NODE_ID_COLUMN",
    "AgentModelPins",
    "NodePin",
]

#: The environment variable naming the relational store, shared with every
#: other member of the data spine (universe, snapshot, feature store, the null
#: oracle's stores, the discovery planner).
DATABASE_URL_ENV = "DATABASE_URL"

#: The column a node is addressed by — feature 97's ``id``, the same key
#: ``node.parent_id`` references and every downstream ``node_id`` resolves to.
NODE_ID_COLUMN = "id"


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract —
    the spelling the evaluator's stores, the ledger's, the null oracle's guard
    and the discovery planner's all state for the same reason, which is that a
    store loaded inside one member must not depend on another member being
    importable.

    A non-SQLite scheme is refused loudly, and so is a pathless (in-memory)
    URL: an in-memory database dies with the connection that opened it, and a
    node's authoring model must outlive the pinning call that recorded it —
    the ablation that stratifies on ``agent_model_id`` (PRD §5a) opens the
    store in another process entirely, days later.  Both refusals are
    :class:`~providers.ModelPinError` rather than a named subclass: neither is
    a fact about a node, a value or the column, and the taxonomy's four
    subclasses each answer a question the caller can act on about *those*.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise ModelPinError(
            f"{DATABASE_URL_ENV} must be a non-empty database URL; a pin is a "
            "column on a node, so there must be a store holding the tree"
        )
    parsed = urlparse(database_url.strip())
    if parsed.scheme != "sqlite":
        raise ModelPinError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the tree store's "
            "node table already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ModelPinError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise ModelPinError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a "
            "node's authoring model must outlive the pinning call that "
            "recorded it — the model-stratum ablation reads this column from "
            "another process"
        )
    return Path(path)


@dataclass(frozen=True)
class NodePin:
    """What pinning one node left behind — the triple, and whether it was written.

    The store's answer, carried instead of a bare ``ModelPin`` so the two
    outcomes a caller must tell apart are distinguishable: a first (or
    backfill) write, and an idempotent retry answered by the row that was
    already there.  §14 demands retry-safe writes of the workers this runs on,
    and a caller that could not see which one it got could not report whether
    it changed anything — the same distinction
    :class:`evaluator.NodePersistence` draws with its ``tree_appended`` flag.

    ``node_id`` is repeated beside the pin rather than left to the caller,
    because the two together are the fact — *this node was authored by this
    model* — and a retry report that named only the triple would not say which
    node it was answered for.
    """

    node_id: str
    pin: ModelPin
    stamped: bool

    @property
    def agent_model_id(self) -> str:
        """The triple as the column stores it — ``pin`` rendered."""
        return str(self.pin)


class AgentModelPins:
    """The store that pins each node's authoring model.

    Constructed with the database URL holding the tree store; :meth:`persist`
    stamps one node's ``agent_model_id`` and :meth:`load` reads one back.  The
    class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states.

    The store holds no cache of the pins it wrote.  The row is the only record
    of which model authored a node — which is the entire point of the feature,
    since the whole failure it defends against is a value that *looks* right in
    one process and re-routes in another — so it is the only thing an answer is
    drawn from.  A memo here would make *"which model wrote this node?"* a
    question about this process's history rather than about the world, and the
    stratification that wants to know runs elsewhere.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ModelPinError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.  A URL
        # the member cannot speak is refused by name at that first use.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> AgentModelPins | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        pin store — a discoverable state, not an exception — while a caller
        that must pin a node is the caller that must not find itself in it.
        The same stance :func:`discovery.CampaignRecords.resolve` takes for the
        campaign table, and for the same reason.
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
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to commit,
        which is what :meth:`persist` does — the row read and the ``UPDATE``
        are one unit of work and must be one transaction, or two workers
        pinning one node could interleave a compare and a set.

        **No schema is created here**, deliberately, and this is the one place
        the store diverges from ``CampaignRecords``: see the module docstring.
        A tree store that has not reached revision
        :data:`~providers._pinning.MODEL_PIN_REVISION` is a named,
        actionable condition, so this store reports it as one rather than
        letting SQLite's ``no such column`` escape.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    # -- Feature 203: the write ---------------------------------------------

    def persist(self, node_id: Any, pin: Any) -> NodePin:
        """Persist one node's authoring model as a triple; answer what it did.

        Feature 203's sentence as one call: the node id and the triple in, the
        stored pin and whether *this* call wrote it out.  The steps, and why
        each is where it is:

        1. **Validate the ask** — the node id as a UUID and the pin as a
           provider/model/version triple — before anything is opened, so a
           rolling alias is refused without touching a database.
        2. **Prove the column exists**, naming revision
           :data:`~providers._pinning.MODEL_PIN_REVISION` when it does not:
           a pin has a documented prerequisite and this is the report that
           says so.
        3. **Read the node's stored value**, and answer it:

           * no row → :class:`~providers.NodeNotRecordedError`;
           * a different triple → :class:`~providers.ModelPinConflictError`,
             naming both;
           * a value that is not a triple →
             :class:`~providers.RollingAliasError`;
           * the same triple → :class:`NodePin(stamped=False)`, no ``UPDATE``;
           * NULL → the ``UPDATE`` below, :class:`NodePin(stamped=True)`.

        4. **Write, when the row held nothing**, and answer the value that was
           written rather than the one that was passed.

        Refuses, in this order, each naming what it is about: a malformed node
        id or a rolling alias (:class:`~providers.RollingAliasError`), a tree
        store without the column (:class:`~providers.PinColumnError`), a node
        that does not exist (:class:`~providers.NodeNotRecordedError`), a
        stored value that is not a triple
        (:class:`~providers.RollingAliasError`) and a stored value that
        disagrees (:class:`~providers.ModelPinConflictError`).

        The answer is the *pin*, not the string: a caller that wants the
        column's spelling reads :attr:`NodePin.agent_model_id`, and one that
        wants the parts reads :attr:`NodePin.pin` — so no caller has to re-parse
        what the store already parsed.
        """
        node = _validated_node_id(node_id)
        triple = require_agent_model_id(pin)
        with closing(self._connect()) as connection, connection:
            self._require_column(connection, node)
            stored = self._read_value(connection, node)
            if stored is None:
                # Either the row is absent or its value is SQL NULL; the two are
                # one read apart, so they are told apart here rather than by a
                # second query.  An absent row is a caller's mistake about the
                # tree; a NULL value is the state 0115's NOT NULL could not
                # cover on a populated table, and writing it is this feature's
                # backfill.
                if not self._node_exists(connection, node):
                    raise NodeNotRecordedError(
                        f"there is no node {node!r} in the tree store at "
                        f"{self.path}: a pin is a column on a node, so "
                        f"persisting one for an id the tree does not hold would "
                        f"mean writing a row this member does not own — the "
                        f"{NODE_TABLE} table is feature 97's and its rows are "
                        f"the discovery tree's. Record the node first, then "
                        f"pin the model that authored it."
                    )
                self._write(connection, node, triple)
                return NodePin(node_id=node, pin=triple, stamped=True)
            return self._answer_stored(node, stored, triple)

    def load(self, node_id: Any) -> ModelPin | None:
        """Read one node's authoring model back, or ``None`` when it holds none.

        ``None`` means *this node's row records no authoring model* — the
        backfill state :meth:`persist` writes out of, and the state a tree
        built by a bootstrap schema that omits the trio is in.  It does **not**
        mean the node is absent, and it does not mean the read failed: a node
        the tree does not hold raises
        :class:`~providers.NodeNotRecordedError` and an unreachable store
        raises — so a caller can never mistake a node with no pin for a node
        that is not there, or a broken store for either.  The same distinction
        :meth:`discovery.CampaignRecords.get` draws between *"never planned"*
        and *"the read failed"*.

        A stored value that is not a triple raises
        :class:`~providers.RollingAliasError` rather than being returned: the
        read side is where §14.1's corruption would otherwise be laundered, and
        a stratum keyed on ``'deepseek-flash'`` is the failure this feature
        exists to end.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            self._require_column(connection, node)
            if not self._node_exists(connection, node):
                raise NodeNotRecordedError(
                    f"there is no node {node!r} in the tree store at "
                    f"{self.path}: load() reads one node's authoring model and "
                    f"needs the node to read it from. A missing node is not a "
                    f"node with no pin — the second is a row that exists and "
                    f"holds nothing, and only the first says the tree has never "
                    f"heard of this id."
                )
            stored = self._read_value(connection, node)
        if stored is None:
            return None
        return _parse_stored(node, stored, str(self.path))

    # -- The words ----------------------------------------------------------

    def _require_column(self, connection: sqlite3.Connection, node: str) -> None:
        """Refuse a tree store whose ``node`` table has no authoring-model column.

        The prerequisite check, and the reason it is a probe rather than a
        caught exception: SQLite answers *"no such column: agent_model_id"*
        only once a statement mentions the column, so a store that reached the
        ``UPDATE`` first would report the gap at a point where the message is
        about a statement rather than about the deployment.  ``PRAGMA
        table_info`` asks the table instead, which is the same move
        ``nulloracle.TreeStoreGuard.audit`` makes for the column it keeps
        absent — *"it asks the table, not the queries"*.

        Both depths are one refusal.  A missing ``node`` table and a ``node``
        table missing the column are the same fact — this database has not
        reached the revision that adds the trio — seen at two depths, and both
        repairs are the same chain of migrations.
        """
        try:
            rows = connection.execute(
                f"PRAGMA table_info({NODE_TABLE})"
            ).fetchall()
        except sqlite3.Error as exc:  # pragma: no cover - driver-level failure
            raise PinColumnError(
                f"the tree store at {self.path} could not be asked for its "
                f"{NODE_TABLE} table's columns: {exc}"
            ) from exc
        columns = {str(row[1]) for row in rows}
        if AGENT_MODEL_ID_COLUMN in columns:
            return
        if not columns:
            raise PinColumnError(
                f"the tree store at {self.path} has no {NODE_TABLE} table: node "
                f"{node!r} cannot be pinned because there is no node table to "
                f"pin it in. Feature 97's table is revision 0118 and the "
                f"authoring-model column is revision {MODEL_PIN_REVISION} "
                f"(feature 100); run the migration chain to there."
            )
        raise PinColumnError(
            f"the tree store at {self.path} holds a {NODE_TABLE} table with no "
            f"{AGENT_MODEL_ID_COLUMN} column, so node {node!r} cannot be "
            f"pinned: the column belongs to revision {MODEL_PIN_REVISION} "
            f"(feature 100), and a deployment that has not reached it has "
            f"nowhere for a provider/model/version triple to live. Run the "
            f"migration chain to {MODEL_PIN_REVISION}."
        )

    def _read_value(self, connection: sqlite3.Connection, node: str) -> Any:
        """The stored ``agent_model_id`` for one node, or ``None``.

        ``None`` is returned for both *no row* and *a SQL NULL value*, and the
        caller tells them apart with :meth:`_node_exists` — the two are one
        question apart and folding the queries keeps the common path (a node
        that exists and is already pinned) to a single read.
        """
        row = connection.execute(
            f"SELECT {AGENT_MODEL_ID_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node,),
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def _node_exists(self, connection: sqlite3.Connection, node: str) -> bool:
        """Whether the tree holds a row for ``node``.

        Asked of the key alone and never of the value, so a node whose
        ``agent_model_id`` is NULL is answered as *present* — which is the
        distinction :meth:`persist` needs to choose between *"record the node
        first"* and *"backfill the column"*.  Two conditions with two repairs
        must never be one query.
        """
        row = connection.execute(
            f"SELECT 1 FROM {NODE_TABLE} WHERE {NODE_ID_COLUMN} = ?", (node,)
        ).fetchone()
        return row is not None

    def _answer_stored(self, node: str, stored: Any, triple: ModelPin) -> NodePin:
        """Answer a node whose row already holds a value.

        The three outcomes, in the order they are distinguishable: a value that
        is not a triple at all is refused before it is compared (there is
        nothing to compare it *as*), and a triple is then either the one being
        persisted — the idempotent retry, answered without a write — or a
        different one, which is the conflict.

        The stored value is parsed rather than compared as text.  Two spellings
        of one model cannot exist (the triple's parts may not carry padding or
        the separator, so the rendering is injective), but parsing first means
        the comparison is between models rather than between strings, and the
        refusal can name the stored *triple* an operator has to reconcile —
        which a string comparison would leave them to decode.
        """
        stored_pin = _parse_stored(node, stored, str(self.path))
        if stored_pin == triple:
            return NodePin(node_id=node, pin=stored_pin, stamped=False)
        raise ModelPinConflictError(
            f"node {node!r} already records agent_model_id "
            f"{str(stored_pin)!r}, and this call pins {str(triple)!r}. A node's "
            f"author is history, not a field: agent_model_id is the axis the "
            f"M3 paired comparison is stratified on (PRD §5a, architecture "
            f"§14.1), so re-stamping this node would move every score it "
            f"carries into another model stratum while leaving the scores "
            f"themselves untouched. Persist the triple the node was actually "
            f"authored under, or record a new node for the new model."
        )

    def _write(
        self, connection: sqlite3.Connection, node: str, triple: ModelPin
    ) -> None:
        """Write the triple onto the node row that holds nothing.

        One statement, on the connection the read above used, inside the
        transaction the caller's ``with`` closes — so the compare and the set
        cannot be split by a second writer.  The guard in the ``WHERE`` is not
        decoration: it is what makes the write a compare-and-set rather than a
        blind overwrite, so a concurrent writer that pinned this node between
        the read and this statement loses nothing — the row simply does not
        match, and the caller's next call reads the winner's value and answers
        it as a conflict or a retry.

        The value written is ``str(triple)`` — the one rendering feature 203
        declares — and this is the only place in this package that spells the
        column's value, so the write path and the read path cannot disagree
        about the stored form.
        """
        connection.execute(
            f"UPDATE {NODE_TABLE} SET {AGENT_MODEL_ID_COLUMN} = ? "
            f"WHERE {NODE_ID_COLUMN} = ? AND {AGENT_MODEL_ID_COLUMN} IS NULL",
            (str(triple), node),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"AgentModelPins({self._database_url!r})"


def _parse_stored(node: str, stored: Any, location: str) -> ModelPin:
    """Parse a value read out of the column, naming the row it came from.

    :func:`~providers.require_agent_model_id` refuses a value that is not a
    triple, and it is the right function to refuse with — but its message can
    only name the *value*, because at a seam handed a bare string that is all
    there is to name.  A value read out of the column is different: the store
    knows which row it came from, and that row is the only thing that makes the
    refusal actionable.  A corrupt ``agent_model_id`` is repaired **per node**
    — by working out which model actually authored *that* node — so a report
    that says which value is wrong but not which row carries it leaves an
    operator to go and grep for it.

    So the store translates rather than letting the parser's message out
    unchanged: the original is kept verbatim on the new exception, and the row's
    address is put in front of it.  This is the error-vocabulary rule the whole
    spine applies — *translate at the seam, don't re-raise across it* — in its
    cheapest form, where the seam and the owner happen to be one member.

    The inner message is embedded with its trailing sentence-period stripped, so
    the composed report reads as one sentence per thought rather than running a
    doubled ``..`` together in the middle of it — the refusal is read by an
    operator, and a message that looks mis-assembled is one they trust less.
    """
    try:
        return require_agent_model_id(stored)
    except RollingAliasError as refusal:
        inner = str(refusal).rstrip().removesuffix(".")
        raise RollingAliasError(
            f"node {node!r} in the tree store at {location} records "
            f"agent_model_id as something that is not a pinned triple, and this "
            f"store will not paper over it: {inner}. The node was authored by "
            f"whichever model the stored value pointed at *at the time*, and "
            f"only the run that recorded it knows which — so this is repaired "
            f"per node, by backfilling the triple that node was actually "
            f"authored under (feature 203; architecture §14.1 mitigation 2)."
        ) from refusal


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Accepts a :class:`uuid.UUID` or any text :func:`uuid.UUID` parses, and
    returns the lowercased hyphenated rendering — the normalization every store
    that joins ``node.id`` applies (``tripwires.layout.validated_node_id``,
    ``nulloracle.assignment.normalize_node_id``, ``ledger.record``), because
    the column is a ``UUID`` primary key and a mixed-case key would make one
    node look like two: here, in the question of which model authored it.

    A malformed id is refused with :class:`~providers.ModelPinError` directly,
    on the same grounds the URL refusals are: no subclass answers a question a
    caller can act on here.  The id is not a *triple* that failed to parse, so
    :class:`~providers.RollingAliasError` would be a lie about what was wrong,
    and minting a fifth class for *"the addressing value was malformed"* would
    give the taxonomy a member whose only call site is this function.
    """
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(_uuid.UUID(text))
            except ValueError:
                pass
    raise ModelPinError(
        f"node id {value!r} is not a UUID ({type(value).__name__}); a node id "
        f"joins the tree store's {NODE_TABLE}.{NODE_ID_COLUMN} primary key, so "
        f"an id that cannot join it names no node to pin an authoring model on"
    )
