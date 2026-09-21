"""Persisting a node's authoring record — features 203 and 204's write path.

app_spec.xml feature 203: *System persists ``agent_model_id`` per node as a
provider, model and version triple rather than a rolling alias.*
app_spec.xml feature 204: *System persists ``agent_ckpt_hash`` for self-hosted
weights plus ``agent_sampling`` recording temperature, top_p, thinking and
seed.*  :mod:`providers._pinning`, :mod:`providers._ckpt` and
:mod:`providers._sampling` own what each of the three values *is*; this module
owns the act both sentences name — writing them onto a node row — and every way
that act can fail to be honest.

**The three columns are one authoring record, and this is the one store that
writes it.**  ``0115_agent_model_trio`` (feature 100) adds all three to ``node``
in one migration, and the docstring's phrase for them — *"the trio"* — is the
right unit: which model, which weights, which dice, in the order the spec's
schema block lists them.  Features 203 and 204 are two halves of that one
record and their sentences divide it cleanly:

* :meth:`AgentModelPins.persist` — feature 203's act.  One column,
  ``agent_model_id``, refused unless it is a provider/model/version triple.
* :meth:`AgentModelPins.persist_weights` — feature 204's act.  The other two,
  ``agent_ckpt_hash`` and ``agent_sampling``, written together because a single
  call that named the weights and not the dice would leave the row half a
  record.
* :meth:`AgentModelPins.load_provenance` — both halves read back as one.
  :meth:`AgentModelPins.load` stays feature 203's narrower question.

Splitting the write in two is not an accident of the two features landing
separately; it is what the storage states have to be.  ``agent_model_id`` is
``NOT NULL`` with no default (0115), so on a tree the chain built every node row
already carries an author at insert, while ``agent_ckpt_hash`` is nullable and
``agent_sampling`` is ``NOT NULL`` — three columns with three different
reachable-state sets, written at different moments by different parts of a run.
One method taking all three would have to refuse the very states the schema
permits.

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

Feature 204's states, and the three that are refusals
-----------------------------------------------------

``persist_weights`` writes the other two columns of the same row, and its state
space is shaped by the fact that ``agent_ckpt_hash`` is the *only* one of the
three ``0115`` leaves nullable:

* **A row that records no authoring model** →
  :class:`~providers.NodeProvenanceError`.  The row half of feature 338's merge
  refusal, reached from the write side.  Writing weights onto a row with no
  author would produce a node that says which dice were thrown and which weights
  served without saying which model was asked — a node the stratification
  cannot place that nevertheless *looks* placeable, because two of the three
  provenance columns are filled.
* **A recorded checkpoint hash and a call offering a different one** →
  :class:`~providers.CkptHashConflictError`.  A node's weights are history, on
  the same grounds its author is; and the case that makes the refusal
  load-bearing is the **rollback** — a re-recorded node carrying no hash would
  not record less, it would assert that weights previously pinned exactly are a
  provider's to change.
* **A recorded sampling record and a call offering different settings** →
  :class:`~providers.SamplingConflictError`.  ``0115``: *"a replay that
  re-issues the authoring call without these four cannot reproduce the node,
  and determinism under replay is the property §14 demands of every recorded
  decision."*  Re-stamping leaves every stored score reproducible only by
  settings the row no longer holds — a replay guarantee that *looks* recorded.
* **The same weights and the same settings** → answered, not written:
  :attr:`AgentWeights.recorded` is ``False``.  The idempotent retry §14 demands,
  including the hosted-API case re-recorded as hosted-API.
* **NULL columns** → written, :attr:`AgentWeights.recorded` is ``True``.  Not
  hypothetical: ``agent_sampling``'s ``NOT NULL`` is a bare constraint with no
  default, which both dialects refuse to add to a populated table (0115's own
  argument), and a tree built by a bootstrap schema that omits the trio has
  neither column at all.  This branch is the backfill.

The model is checked *before* the weights, and the order is deliberate.
``agent_model_id`` decides whether a checkpoint hash is even meaningful — a node
whose author is a rolling alias cannot have its weights reasoned about, because
the model the weights belonged to is not knowable — so a store that reported a
hash conflict for such a row would be answering the second question about a row
where the first has no answer.  That is the plausible report that hides the real
one, which is the failure mode this whole module is written against.

One node, one statement, one transaction
----------------------------------------

The read of the row and the ``UPDATE`` are one unit of work on one connection,
so the compare-then-set cannot interleave with a second writer: two workers
pinning one node serialize, and the second sees the first's value rather than
a stale read.  That serialization is the store's own; it is not a schema
constraint, because no migration declares one on this column and inventing a
constraint here would be this feature legislating DDL it does not own.

That argument carries over to ``persist_weights`` unchanged, and the two writes
are deliberately *not* merged into one transaction.  They are two calls because
they are two moments in a run — the author is known when the node is proposed,
the weights and dice when the call is made — and a single transaction spanning
both would either force one caller to hold the other's values or make the pair
unresumable after a crash between them.  The two never write the same column, so
there is no lost update to serialize against: each checks-and-sets its own two,
on its own connection, and a retry of either is the idempotent answer it would
be alone.

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

from ._ckpt import (
    AGENT_CKPT_HASH_COLUMN,
    HOSTED_API_CKPT_HASH,
    require_agent_ckpt_hash,
)
from ._pin_errors import (
    AgentSamplingMalformedError,
    CkptHashConflictError,
    CkptHashMalformedError,
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    NodeProvenanceError,
    PinColumnError,
    RollingAliasError,
    SamplingConflictError,
)
from ._pinning import (
    AGENT_MODEL_ID_COLUMN,
    MODEL_PIN_REVISION,
    NODE_TABLE,
    ModelPin,
    require_agent_model_id,
)
from ._sampling import (
    AGENT_SAMPLING_COLUMN,
    AgentSampling,
    require_agent_sampling,
)

__all__ = [
    "DATABASE_URL_ENV",
    "NODE_ID_COLUMN",
    "AgentModelPins",
    "AgentWeights",
    "NodePin",
    "NodeProvenance",
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
    """What pinning one node's authoring model left behind.

    Feature 203's store answer, carried instead of a bare ``ModelPin`` so the
    two outcomes a caller must tell apart are distinguishable: a first (or
    backfill) write, and an idempotent retry answered by the row that was
    already there.  §14 demands retry-safe writes of the workers this runs on,
    and a caller that could not see which one it got could not report whether
    it changed anything — the same distinction
    :class:`evaluator.NodePersistence` draws with its ``tree_appended`` flag.

    ``node_id`` is repeated beside the pin rather than left to the caller,
    because the two together are the fact — *this node was authored by this
    model* — and a retry report that named only the triple would not say which
    node it was answered for.

    ``recorded`` is ``None`` when nothing was written and ``True`` when this
    call wrote it — a *tri-state* rather than a flag, for the reason
    :class:`AgentWeights` sets out at length.  It is feature 204's refinement of
    this record: once a row has three columns and two calls writing them,
    "this call changed nothing" and "the field being reported was already
    there" stop being the same statement, and a ``False`` would make them one.
    :attr:`stamped` keeps the two-valued spelling feature 203's callers and
    suite already use and is ``recorded is True``.
    """

    node_id: str
    pin: ModelPin
    recorded: bool | None = None

    @property
    def stamped(self) -> bool:
        """Whether this call wrote the triple — ``recorded is True``.

        Feature 203's original spelling of the answer, kept because it reads
        correctly at that feature's own seam: :meth:`AgentModelPins.persist`
        writes one column or does not, so *"was it stamped?"* and *"was it
        recorded?"* are the same question there.  It is derived from
        :attr:`recorded` rather than stored beside it, so the two can never
        disagree, and it is ``False`` for the ``None`` case as well — a call
        that wrote nothing did not stamp anything.
        """
        return self.recorded is True

    @property
    def agent_model_id(self) -> str:
        """The triple as the column stores it — ``pin`` rendered."""
        return str(self.pin)


@dataclass(frozen=True)
class AgentWeights:
    """What recording one node's weights and dice left behind — feature 204's answer.

    ``ckpt_hash`` is the checkpoint hash as the column stores it, or ``None``
    for hosted-API weights; ``sampling`` is the four settings; ``recorded`` says
    whether *this* call wrote them.

    The null-hash spelling is :data:`~providers.HOSTED_API_CKPT_HASH`, and a
    caller should read it through ``is None`` rather than by truthiness — the
    empty string is not a state this record has, because
    :func:`~providers.require_agent_ckpt_hash` refuses it, but the habit is what
    keeps a future visitor from reading ``""`` as "hosted".

    **``recorded`` is a tri-state, and the third value is the point.**  A row
    carries two independent facts — which weights served it, which dice were
    thrown — and they are written by one call but not necessarily by the *same*
    call: a re-run of a campaign step may find the weights already recorded (a
    backfill from an earlier run) and the sampling not.  A ``bool`` would force
    this call to answer *"did I write?"* with a single value covering both
    columns, and either answer would be a lie about one of them.  So:

    * ``True`` — this call wrote what the record reports;
    * ``False`` — this call wrote nothing; the row already held it;
    * ``None`` — this call recorded nothing at all, and either because the row
      already held everything or because the caller asked a question that
      cannot be answered with a write.

    ``None`` is also what :class:`NodeProvenance` carries on the read path,
    where the question *"did this call write?"* has no referent, and sharing the
    spelling is deliberate: a caller that conflates the two has confused reading
    with writing, and the ``None`` it meets is the same ``None``.

    Equality is by value, like every record in this package, so a suite can
    assert a store answer against a record it built.
    """

    node_id: str
    ckpt_hash: str | None
    sampling: AgentSampling
    recorded: bool | None = None

    @property
    def self_hosted(self) -> bool:
        """Whether this node's weights are self-hosted — a hash was recorded.

        The predicate §14.1's mitigations are ordered by.  ``True`` means
        mitigation 1 was available for this node and was used: the weights are
        bytes the deployment holds and the hash is an identity rather than a
        promise.  ``False`` means the node was authored through a hosted API, so
        its weights are the one part of its provenance the triple cannot pin —
        which is a fact a stratification wants to be able to select on, and
        which is exactly why the null is recorded rather than left out.

        A property rather than a field: it is a *reading* of ``ckpt_hash``, not
        a second fact, and storing it would give a record that could hold
        ``self_hosted=True`` beside a null hash.
        """
        return self.ckpt_hash is not None

    @property
    def agent_ckpt_hash(self) -> str | None:
        """The checkpoint hash as the column stores it — ``ckpt_hash``."""
        return self.ckpt_hash

    @property
    def agent_sampling(self) -> str:
        """The sampling record as the column stores it — ``sampling`` rendered."""
        return self.sampling.to_json()


@dataclass(frozen=True)
class NodeProvenance:
    """One node's whole authoring record, read back — which model, weights, dice.

    :meth:`AgentModelPins.load_provenance`'s answer, and the read half of both
    features: the ``ModelPin`` feature 203 writes, and the
    :class:`AgentWeights` feature 204 writes, in one record.  A caller asking
    *what produced this node* has one question and should not have to make two
    calls that could interleave with a writer between them.

    **Two of the three fields here are optional and their nulls do not mean the
    same thing**, which is worth stating because it is the one place this record
    cannot be read by a single rule:

    * ``ckpt_hash is None`` — **hosted-API weights**.  A recorded fact, per
      §9.1's ``-- non-null for self-hosted weights``: the weights came from a
      provider and there was no local checkpoint to hash.  This is what
      :attr:`self_hosted` reads.
    * ``sampling is None`` — **the dice are not yet recorded**.  An
      un-backfilled state, and reachable only on a tree whose
      ``agent_sampling`` accepts NULL, since ``0115`` declares it ``NOT NULL``
      and the chain-built tree enforces that.  Its repair is
      :meth:`AgentModelPins.persist_weights` — the same backfill that writes the
      sampling — and a caller that finds it here has met a row that is not
      fully recorded rather than one whose draw was somehow undefined.

    The asymmetry is the schema's and not this record's: one of the two columns
    is nullable because a hosted-API node has no checkpoint, and the other is
    ``NOT NULL`` because *there is no node whose dice are unknown, only
    unrecorded ones* (0115).  So a null in the first is an answer and a null in
    the second is a to-do, and this record reports both as the columns hold
    them rather than picking one reading and forcing it on the other.

    ``model`` is never ``None``: a node whose authoring model is unrecorded is
    the state :meth:`AgentModelPins.load_provenance` answers with ``None``
    outright, because a record that named no model would be a provenance record
    of nothing.

    ``recorded`` is ``None`` throughout — the read path writes nothing, so the
    question *"did this call write?"* has no referent.  It is spelled rather
    than omitted so that a caller holding a :class:`NodeProvenance` and an
    :class:`AgentWeights` reads the same attribute for the same question and
    finds the honest answer in both.
    """

    node_id: str
    model: ModelPin
    ckpt_hash: str | None
    sampling: AgentSampling | None
    recorded: bool | None = None

    @property
    def agent_model_id(self) -> str:
        """The triple as the column stores it — ``model`` rendered."""
        return str(self.model)

    @property
    def agent_ckpt_hash(self) -> str | None:
        """The checkpoint hash as the column stores it, or ``None`` when hosted."""
        return self.ckpt_hash

    @property
    def agent_sampling(self) -> str | None:
        """The sampling record as the column stores it, or ``None`` when unrecorded."""
        return None if self.sampling is None else self.sampling.to_json()

    @property
    def self_hosted(self) -> bool:
        """Whether this node's weights are self-hosted — see :attr:`AgentWeights.self_hosted`."""
        return self.ckpt_hash is not None


class AgentModelPins:
    """The store that writes and reads each node's authoring record.

    Constructed with the database URL holding the tree store.  Four operations,
    and the split between them is the split between 203's column and 204's pair:

    * :meth:`persist` stamps one node's ``agent_model_id`` — feature 203.
    * :meth:`persist_weights` records one node's ``agent_ckpt_hash`` and
      ``agent_sampling`` — feature 204.
    * :meth:`load` reads one node's authoring model back — feature 203.
    * :meth:`load_provenance` reads all three columns back as one record.

    The class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states.

    The class name is feature 203's and is kept.  It is the composed
    ``agent-model-pins`` component and the seat that hands it back, so renaming
    it would rename a thing already wired into the application to say a thing
    the wiring does not need to know; and the wider reading — *the store that
    pins a node's authoring provenance* — is what the class always was, with two
    more columns on the same row.  The docstring, not the name, is where the
    scope is stated.

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

        This method reads and writes ``agent_model_id`` and nothing else.  The
        other two columns of the same row are :meth:`persist_weights`', and
        neither call touches the other's — which is why a caller that needs both
        written makes both calls and a caller that needs only its own does not
        acquire the other's state.
        """
        node = _validated_node_id(node_id)
        triple = require_agent_model_id(pin)
        with closing(self._connect()) as connection, connection:
            self._require_columns((AGENT_MODEL_ID_COLUMN,), node)
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
                self._write_triple(connection, node, triple)
                return NodePin(node_id=node, pin=triple, recorded=True)
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
            self._require_columns((AGENT_MODEL_ID_COLUMN,), node)
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

    def _require_columns(self, wanted: tuple[str, ...], node: str) -> set[str]:
        """Refuse a tree store whose ``node`` table lacks any of ``wanted``.

        The prerequisite check, and the reason it is a probe rather than a
        caught exception: SQLite answers *"no such column: agent_model_id"*
        only once a statement mentions the column, so a store that reached the
        ``UPDATE`` first would report the gap at a point where the message is
        about a statement rather than about the deployment.  ``PRAGMA
        table_info`` asks the table instead, which is the same move
        ``nulloracle.TreeStoreGuard.audit`` makes for the column it keeps
        absent — *"it asks the table, not the queries"*.

        Both depths are one refusal.  A missing ``node`` table and a ``node``
        table missing a column are the same fact — this database has not
        reached the revision that adds the trio — seen at two depths, and both
        repairs are the same chain of migrations.

        **``wanted`` is a tuple, and its order is the order the refusal
        reports.**  Features 203 and 204 ask for different columns of the same
        trio, and a tree has either reached ``0115`` — in which case all three
        are there — or has not, in which case the first name in ``wanted`` that
        is absent is the one reported.  Because 203's own call site passes one
        column, its message is the one it always was, word for word; 204's
        passes ``(AGENT_MODEL_ID_COLUMN, AGENT_SAMPLING_COLUMN,
        AGENT_CKPT_HASH_COLUMN)`` so that on a tree which reached none of them
        the report is still about the *model* column, which is what an operator
        should go and read first.

        Opens its own connection and closes it, so the probe is one short read
        and never holds a transaction open across the caller's work — which is
        also why it returns the column set rather than the connection: a caller
        that needs the connection already has its own, and one that wanted this
        one would be holding a transaction it did not open.  The set is returned
        for the caller's information (none of the four current call sites needs
        it, and each discards it), deliberately *not* as a truthy "it passed"
        signal, which is what a bare return of the set would tempt.
        """
        connection = self._connect()
        try:
            rows = connection.execute(f"PRAGMA table_info({NODE_TABLE})").fetchall()
        except sqlite3.Error as exc:  # pragma: no cover - driver-level failure
            connection.close()
            raise PinColumnError(
                f"the tree store at {self.path} could not be asked for its "
                f"{NODE_TABLE} table's columns: {exc}"
            ) from exc
        columns = {str(row[1]) for row in rows}
        for column in wanted:
            if column in columns:
                continue
            if not columns:
                connection.close()
                raise PinColumnError(
                    f"the tree store at {self.path} has no {NODE_TABLE} table: "
                    f"node {node!r} cannot be pinned because there is no node "
                    f"table to pin it in. Feature 97's table is revision 0118 "
                    f"and the authoring-model trio is revision "
                    f"{MODEL_PIN_REVISION} (feature 100); run the migration "
                    f"chain to there."
                )
            connection.close()
            raise PinColumnError(
                f"the tree store at {self.path} holds a {NODE_TABLE} table with "
                f"no {column} column, so node {node!r} cannot be pinned: the "
                f"authoring-model trio belongs to revision "
                f"{MODEL_PIN_REVISION} (feature 100), and a deployment that has "
                f"not reached it has nowhere for a provider/model/version "
                f"triple, a checkpoint hash and a sampling record to live. Run "
                f"the migration chain to {MODEL_PIN_REVISION}."
            )
        return columns

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
            return NodePin(node_id=node, pin=stored_pin, recorded=False)
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

    def _write_triple(
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
        declares — and this is the only place in this package that spells
        ``agent_model_id``, so the write path and the read path cannot disagree
        about the stored form.  Feature 204's two columns have their own single
        spelling in :meth:`_write_weights` for the same reason; the trio shares
        a row, not a rendering.
        """
        connection.execute(
            f"UPDATE {NODE_TABLE} SET {AGENT_MODEL_ID_COLUMN} = ? "
            f"WHERE {NODE_ID_COLUMN} = ? AND {AGENT_MODEL_ID_COLUMN} IS NULL",
            (str(triple), node),
        )

    # -- Feature 204: the weights and the dice ------------------------------

    def persist_weights(
        self, node_id: Any, ckpt_hash: Any = HOSTED_API_CKPT_HASH, *, sampling: Any
    ) -> AgentWeights:
        """Record one node's checkpoint hash and sampling settings; answer what it did.

        Feature 204's sentence as one call: the node id, the weights and the
        dice in; the recorded pair and whether *this* call wrote it out.  The
        steps mirror :meth:`persist`'s, in the order the two features' questions
        have to be asked:

        1. **Validate the ask** — the node id, the checkpoint hash and the
           sampling record — before anything is opened, so a malformed ask
           costs nothing.  ``ckpt_hash`` is keyword-optional and defaults to
           :data:`~providers.HOSTED_API_CKPT_HASH`, which is the hosted-API
           case; ``sampling`` is keyword-only and has no default, because the
           four settings are what the caller is here to state and a defaulted
           sampling would be this method choosing a draw.
        2. **Prove the trio's columns exist**, naming revision
           :data:`~providers._pinning.MODEL_PIN_REVISION` when they do not.
        3. **Read the row**, and answer it:

           * no row → :class:`~providers.NodeNotRecordedError`;
           * no authoring model → :class:`~providers.NodeProvenanceError`;
           * a stored model that is not a triple →
             :class:`~providers.RollingAliasError`;
           * a recorded hash that disagrees → :class:`~providers.CkptHashConflictError`
             — including the case where the row holds no hash *because* it
             records hosted-API weights and this call offers a digest, which is
             a disagreement the column's NULL cannot express on its own and
             which the row's sampling is read to settle;
           * recorded settings that disagree →
             :class:`~providers.SamplingConflictError`;
           * both already equal → :class:`AgentWeights(recorded=False)`, no
             ``UPDATE``;
           * the row's record unwritten (its sampling NULL) or its hash NULL and
             agreed → the ``UPDATE`` below,
             :class:`AgentWeights(recorded=True)`.

        4. **Write the column the row held nothing in**, and answer the values
           that were written rather than the ones that were passed.

        The model is checked **before** the weights, and that ordering is the
        method's one non-obvious decision — see the module docstring.  A row
        whose author is a rolling alias cannot have its weights reasoned about,
        because the model those weights belonged to is not knowable, so
        reporting a hash conflict for such a row would answer the second
        question where the first has no answer.

        ``recorded=True`` in the answer means *this call's ``UPDATE`` matched*:
        the atomicity argument is :meth:`_write_weights`'s, and the reason the
        flag is ``True`` even when only one of the two columns was NULL is that
        the record :class:`AgentWeights` returns is the pair the caller asked to
        record, and this call did record it.  Which of the two columns was
        previously empty is visible in what was stored and is not a fact this
        answer has to carry: the caller asked to record the pair, and it was
        recorded.
        """
        node = _validated_node_id(node_id)
        stored_hash = _require_ckpt_hash_or_hosted(ckpt_hash, node, str(self.path))
        wanted = require_agent_sampling(sampling)
        with closing(self._connect()) as connection, connection:
            self._require_columns(
                (
                    AGENT_MODEL_ID_COLUMN,
                    AGENT_SAMPLING_COLUMN,
                    AGENT_CKPT_HASH_COLUMN,
                ),
                node,
            )
            author = self._read_value(connection, node)
            if author is None:
                if not self._node_exists(connection, node):
                    raise NodeNotRecordedError(
                        f"there is no node {node!r} in the tree store at "
                        f"{self.path}: agent_ckpt_hash and agent_sampling are "
                        f"columns on a node, so recording them for an id the "
                        f"tree does not hold would mean writing a row this "
                        f"member does not own — the {NODE_TABLE} table is "
                        f"feature 97's and its rows are the discovery tree's. "
                        f"Record the node first, then the weights and dice that "
                        f"authored it."
                    )
                raise NodeProvenanceError(
                    f"node {node!r} in the tree store at {self.path} records no "
                    f"agent_model_id, so its weights and sampling cannot be "
                    f"recorded: a node with no model string is a node the "
                    f"stratification cannot place (0115's own words), and a row "
                    f"holding a checkpoint hash and a sampling record without "
                    f"one would be a node that *looks* placeable — two of its "
                    f"three provenance columns filled — while naming no model "
                    f"at all. This is the state feature 203's backfill exists "
                    f"for: run persist() with the triple this node was "
                    f"actually authored under (architecture §14.1 mitigation "
                    f"2), then record the weights."
                )
            author_pin = _parse_stored(node, author, str(self.path))
            stored_ckpt = self._read_ckpt_hash(connection, node)
            stored_sampling = self._read_sampling(connection, node)
            answer = self._answer_weights(
                node, author_pin, stored_ckpt, stored_sampling, stored_hash, wanted
            )
            if answer is not None:
                return answer
            wrote = self._write_weights(connection, node, stored_hash, wanted)
            return AgentWeights(
                node_id=node,
                ckpt_hash=stored_hash,
                sampling=wanted,
                recorded=True if wrote else None,
            )

    def load_provenance(self, node_id: Any) -> NodeProvenance | None:
        """Read one node's whole authoring record back, or ``None`` when unpinned.

        The three columns read as one answer — which model, which weights, which
        dice — which is the record ``0115``'s trio actually is and the shape a
        stratification wants: a caller asking *what produced this node* should
        not have to make three calls that a writer could interleave between.

        ``None`` means *this node's row records no authoring model* — the
        backfill state :meth:`persist` writes out of, and the state a tree built
        by a bootstrap schema that omits the trio is in.  It does **not** mean
        the node is absent, and it does not mean the read failed: a node the
        tree does not hold raises :class:`~providers.NodeNotRecordedError` and
        an unreachable store raises — the same three-way distinction
        :meth:`load` draws, kept here rather than collapsed.

        **A hosted-API node is not ``None``.**  Its ``ckpt_hash`` is ``None``,
        which is the recorded fact that its weights came from a provider and
        there was no local checkpoint to hash — §9.1: ``-- non-null for
        self-hosted weights``.  So a caller can always tell *"these weights are
        a provider's"* from *"nobody wrote this down"*, and the two are different
        strata in any report that reads them.

        **A node whose sampling is unrecorded is not ``None`` either**, and this
        is the one row shape where the returned record has a null in a field
        that is not the checkpoint hash: its ``sampling`` is ``None``, which on a
        chain-built tree cannot happen (0115 declares the column ``NOT NULL``)
        and off one is the state :meth:`persist_weights` is the repair for.  It
        is reported rather than refused because a reader answering *what is
        recorded here?* has no ask that can disagree with the row, and *"the
        dice are not recorded"* is a thing a caller can report and act on —
        whereas the same null on the write side is a refusal, since a writer has
        to add to a row and cannot add dice to a row someone else already gave
        different ones.  The nulls in ``ckpt_hash`` and in ``sampling`` are
        therefore read the same way — as the column holds them — but they are
        not the same fact: :attr:`NodeProvenance.self_hosted` reads one, and
        *needs backfill* is the other.

        A stored value that is not a triple raises
        :class:`~providers.RollingAliasError` for the reason :meth:`load` gives;
        a stored sampling record that is not four settings raises
        :class:`~providers.AgentSamplingMalformedError`; and a stored checkpoint
        hash that is not a digest raises
        :class:`~providers.CkptHashMalformedError`.  All three are refusals
        rather than values, because the read side is where §14.1's corruption
        would otherwise be laundered into a stratum.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            self._require_columns(
                (
                    AGENT_MODEL_ID_COLUMN,
                    AGENT_SAMPLING_COLUMN,
                    AGENT_CKPT_HASH_COLUMN,
                ),
                node,
            )
            if not self._node_exists(connection, node):
                raise NodeNotRecordedError(
                    f"there is no node {node!r} in the tree store at "
                    f"{self.path}: load_provenance() reads one node's authoring "
                    f"record and needs the node to read it from. A missing node "
                    f"is not a node with no provenance — the second is a row "
                    f"that exists and holds nothing, and only the first says "
                    f"the tree has never heard of this id."
                )
            author = self._read_value(connection, node)
            if author is None:
                # The un-backfilled state.  Reported as None rather than as a
                # refusal, unlike persist_weights', because a *reader* has no
                # ask that can disagree with the row: it answers "what is
                # recorded here?" and "nothing" is the honest answer.  The
                # writer refuses on its own grounds — it must not add two
                # columns to a row with no author.
                return None
            author_pin = _parse_stored(node, author, str(self.path))
            stored_ckpt = self._read_ckpt_hash(connection, node)
            stored_sampling = self._read_sampling(connection, node)
        return NodeProvenance(
            node_id=node,
            model=author_pin,
            ckpt_hash=_parse_stored_ckpt_or_hosted(node, stored_ckpt, str(self.path)),
            sampling=_parse_stored_sampling_or_unrecorded(
                node, stored_sampling, str(self.path)
            ),
        )

    def _read_ckpt_hash(self, connection: sqlite3.Connection, node: str) -> Any:
        """The stored ``agent_ckpt_hash`` for one node, or ``None``.

        ``None`` is both *no row* and *a SQL NULL value* here, and the caller
        has already told those apart with :meth:`_node_exists` — the two are one
        question apart and folding the queries keeps the common path to a single
        read, exactly as :meth:`_read_value` does for the authoring model.
        """
        row = connection.execute(
            f"SELECT {AGENT_CKPT_HASH_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node,),
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def _read_sampling(self, connection: sqlite3.Connection, node: str) -> Any:
        """The stored ``agent_sampling`` text for one node, or ``None``.

        The raw column value, deliberately unparsed: the two callers want
        different things from it — :meth:`persist_weights` compares *settings*
        and :meth:`load_provenance` returns a record — and both go through
        :func:`~providers.require_agent_sampling`, so parsing here would be a
        second parse on one path and none on the other.
        """
        row = connection.execute(
            f"SELECT {AGENT_SAMPLING_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node,),
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def _answer_weights(
        self,
        node: str,
        author: ModelPin,
        stored_ckpt: Any,
        stored_sampling: Any,
        wanted_hash: str | None,
        wanted_sampling: AgentSampling,
    ) -> AgentWeights | None:
        """Answer a row that already records an author; ``None`` when nothing matched.

        ``None`` is the one outcome that means *go and write*, and it is
        returned rather than raised because it is not a refusal.  The two columns
        are answered in the order their questions have to be asked: the
        checkpoint hash first, since a caller offering the wrong weights has the
        wrong node in hand and its sampling agreement is not worth reporting,
        then the sampling.

        **The row's sampling is the witness that the authoring record was
        written at all, and that is what makes the hash's NULL readable.**  A
        NULL in ``agent_ckpt_hash`` has two possible readings on the trees this
        store runs against — *hosted-API weights* (§9.1) on a row whose record
        was written, and *never recorded* on a row whose backfill has not run —
        and the column itself cannot tell them apart, since both are SQL NULL.
        The sampling can: the two columns are written together by
        :meth:`persist_weights`, on chains where ``agent_sampling`` is ``NOT
        NULL`` so a chain-built row always has one, and on the backfill tree the
        sampling's NULL is precisely the un-backfilled state.  So a non-NULL
        sampling means *this row's record is written*, and its hash's NULL is
        then the hosted-API fact rather than an absence.

        That is load-bearing and not a convenience: **without it a hosted-API
        row would accept any digest written over it**, because a NULL on both
        sides would read as a write rather than as a disagreement — which is
        the one direction this refusal exists to stop, and the one its own
        message calls the worst form of the move: it would assert that weights
        previously pinned to a provider are a checkpoint's, moving every score
        on the row into another weight stratum while leaving the scores
        untouched.  A row that records hosted weights and is asked for a digest
        is a :class:`~providers.CkptHashConflictError`, and the mirror ask — a
        digest recorded, hosted offered — is the same refusal on the same
        grounds.

        Every state that reaches :meth:`_write_weights` therefore has a NULL
        sampling — which is what *unwritten* means — and the hash there is
        either NULL too (a wholly unwritten row) or already recorded and equal
        (a row written by a call that recorded the weights without the dice,
        which is the split the two writes allow).  That second shape is why the
        write below is per column and not one statement: the column that needs
        filling is the sampling, and a guard on the hash would match nothing.
        """
        recorded_row = stored_sampling is not None

        def hash_conflict(recorded: str | None) -> CkptHashConflictError:
            """The one wording for both directions of the hash disagreement."""
            return CkptHashConflictError(
                f"node {node!r} in the tree store at {self.path} already "
                f"records "
                f"{_spell_hash(recorded)} and this call records "
                f"{_spell_hash(wanted_hash)}. A node's weights "
                f"are history, on the same grounds its author is: "
                f"agent_ckpt_hash is what more than one M3 campaign reads "
                f"as *these nodes were generated by the same weights and "
                f"may be compared* (PRD §5a, architecture §14.1 mitigation "
                f"1), so re-stamping it would move every score this node "
                f"carries into another weight stratum while leaving the "
                f"scores themselves untouched. Recording hosted-API weights "
                f"over a checkpoint hash is the worst form of it: it "
                f"asserts that weights previously pinned exactly are a "
                f"provider's to change. A deployment that has genuinely "
                f"moved to hosted weights is a *different* node — the "
                f"scores on this row were produced by the checkpoint it "
                f"names."
            )

        if stored_ckpt is not None:
            recorded_hash = _parse_stored_ckpt(node, stored_ckpt, str(self.path))
            if recorded_hash != wanted_hash:
                raise hash_conflict(recorded_hash)
        elif recorded_row and wanted_hash is not None:
            # The row's record is written and its hash is NULL, so the row
            # records hosted-API weights and the ask disagrees.  See the
            # docstring: this branch is the one that stops a digest from being
            # written over the hosted fact, and it is spelled as "the ask is a
            # digest" rather than "the values differ" because on this side
            # there is no stored value to differ from.
            raise hash_conflict(None)

        if recorded_row:
            recorded_sampling = _parse_stored_sampling(
                node, stored_sampling, str(self.path)
            )
            if recorded_sampling != wanted_sampling:
                raise SamplingConflictError(
                    f"node {node!r} in the tree store at {self.path} already "
                    f"records agent_sampling {recorded_sampling.to_json()} and "
                    f"this call records {wanted_sampling.to_json()}. A node's "
                    f"sampling is the draw that produced it, and it is what "
                    f"makes replay a claim rather than a hope — 0115: *a replay "
                    f"that re-issues the authoring call without these four "
                    f"cannot reproduce the node, and determinism under replay "
                    f"is the property §14 demands of every recorded decision*. "
                    f"Re-stamping the row with different settings would leave "
                    f"every stored score reproducible only by settings the row "
                    f"no longer holds. The knobs that move most often are "
                    f"temperature and top_p, so a re-run that reuses a node id "
                    f"across a config change lands here — and the correct answer "
                    f"is a new node, because the score is a fact about one draw."
                )
            return AgentWeights(
                node_id=node,
                ckpt_hash=wanted_hash,
                sampling=wanted_sampling,
                recorded=False,
            )
        return None

    def _write_weights(
        self,
        connection: sqlite3.Connection,
        node: str,
        ckpt_hash: str | None,
        sampling: AgentSampling,
    ) -> bool:
        """Write the weights and dice onto the row whose columns hold nothing.

        **Two statements, one per column, each its own compare-and-set** — and
        the reason is that the two columns have different reachable states, so
        one combined ``UPDATE`` cannot be guarded correctly for both.  Every
        state :meth:`_answer_weights` sends here has a NULL sampling, and the
        hash beside it is either NULL (a wholly unwritten row) or the agreed
        digest (a row whose weights were recorded by an earlier call and whose
        dice were not).  One statement guarded on ``agent_sampling IS NULL``
        would write the sampling in both states but would **silently skip the
        hash in the second** — the hash there is a value, not a NULL — leaving
        the caller told that a record was written when part of it was not.  A
        statement guarded on the hash would write neither column in that state,
        since the hash is *not* NULL and there is nothing for it to fill.  Two
        guarded statements are correct in both, and each is idempotent on its
        own, which is the property §14 asks of every write these workers make.

        Both run on the connection the read above used, inside the transaction
        the caller's ``with`` closes, so neither can be split from the read that
        decided it.  Each is guarded on ``IS NULL`` rather than on the value it
        read, because the guard is what makes it a compare-and-set: a concurrent
        writer that filled the column between the read and this statement simply
        does not match, and the caller's next call reads the winner's value and
        answers it as a retry or a conflict.

        Returns whether **either** statement changed a row, which is what
        :class:`AgentWeights.recorded` reports: the question that flag answers is
        *did this call write?*, and a call whose ``UPDATE`` matched nothing —
        because a concurrent writer had already filled the column — did not.
        The values themselves are still the ones the caller asked to record,
        which is the same distinction :meth:`_answer_weights` draws between a
        write and a retry.

        The two values written are the spellings :mod:`providers._ckpt` and
        :mod:`providers._sampling` declare — the canonical 64-hex digest and the
        canonical JSON text — and this is the only place in this package that
        spells either column.
        """
        wrote = False
        for column, value in (
            (AGENT_CKPT_HASH_COLUMN, ckpt_hash),
            (AGENT_SAMPLING_COLUMN, sampling.to_json()),
        ):
            cursor = connection.execute(
                f"UPDATE {NODE_TABLE} SET {column} = ? "
                f"WHERE {NODE_ID_COLUMN} = ? AND {column} IS NULL",
                (value, node),
            )
            wrote = wrote or cursor.rowcount > 0
        return wrote

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


def _require_ckpt_hash_or_hosted(value: Any, node: str, location: str) -> str | None:
    """Validate a caller's ``ckpt_hash``, allowing the hosted-API null.

    :func:`~providers.require_agent_ckpt_hash` refuses ``None`` — a caller who
    hands it ``None`` has asked it to name a checkpoint and named none — but at
    *this* seam ``None`` is a legal, meaningful ask: it is
    :data:`~providers.HOSTED_API_CKPT_HASH`, the record that this node's weights
    came from a provider and there is no local checkpoint to hash.  So the
    store splits the two cases here rather than weakening the parser: ``None``
    becomes the hosted-API null with no further checks, and anything else goes
    through the parser, which refuses every malformed hash (including the
    ``""`` that a caller might mean as "none" — the empty string is not a state
    this column has, and :mod:`providers._ckpt` says so).

    The translation is at the seam, which is this workspace's rule: a shared
    helper that refused ``None`` outright would make the store's own legal ask
    unreachable, and a store that special-cased it inside the parse would put
    the store's policy in the parser.  The refusal the parser does raise is
    re-raised unchanged — it already names the column, the shape and the repair
    — with only the node's address put in front of it, since the repair for a
    malformed hash is per call and an operator reading it in a log wants to know
    which node's record it was.
    """
    if value is None:
        return HOSTED_API_CKPT_HASH
    try:
        return require_agent_ckpt_hash(value)
    except CkptHashMalformedError as refusal:
        raise CkptHashMalformedError(
            f"node {node!r} in the tree store at {location} was asked to record "
            f"an agent_ckpt_hash it cannot: {refusal}"
        ) from refusal


def _parse_stored_ckpt(node: str, stored: Any, location: str) -> str:
    """Parse a *non-null* value read out of ``agent_ckpt_hash``.

    The read-side counterpart of :func:`_require_ckpt_hash_or_hosted`: a NULL in
    the column is the hosted-API fact and never reaches here, so this function's
    input is always a value the row actually holds and the parse is
    unconditional.  It names the row as well as the value, because a corrupted
    checkpoint hash is repaired per node — the weights that produced a stored
    score are not recoverable in general, so the operator has to know which row
    to go and look at — which is the translation :func:`_parse_stored` performs
    for the triple.
    """
    try:
        return require_agent_ckpt_hash(stored)
    except CkptHashMalformedError as refusal:
        inner = str(refusal).rstrip().removesuffix(".")
        raise CkptHashMalformedError(
            f"node {node!r} in the tree store at {location} records "
            f"agent_ckpt_hash as something that is not a sha256 digest, and this "
            f"store will not paper over it: {inner}. The weights that produced "
            f"this node's stored scores are the ones the value pointed at *at "
            f"the time*, and only the run that recorded it knows which — so this "
            f"is repaired per node, by re-recording the digest of the checkpoint "
            f"that node was actually authored under (feature 204; architecture "
            f"§14.1 mitigation 1)."
        ) from refusal


def _spell_hash(value: str | None) -> str:
    """Spell a checkpoint hash for a message, making the hosted null name itself.

    ``None`` is this column's hosted-API fact and not an absence (see
    :func:`_parse_stored_ckpt_or_hosted`), so a refusal that interpolated the
    value bare would print ``None`` at the one moment a reader most needs to be
    told which of the two things the row holds — the digest it names, or the
    fact that the weights are a provider's.  Both spellings go through this
    function so that a conflict message says what the row records and what the
    call asked for in the same words, whichever side is the null.
    """
    if value is None:
        return f"{HOSTED_API_CKPT_HASH!r} (hosted-API weights)"
    return f"{value!r} (self-hosted weights)"


def _parse_stored_ckpt_or_hosted(node: str, stored: Any, location: str) -> str | None:
    """Read ``agent_ckpt_hash`` as a digest, or ``None`` for hosted-API weights.

    The one place the null is interpreted, and it is the *only* value that maps
    to ``None``: §9.1's comment on the column is ``non-null for self-hosted
    weights``, so a NULL is the recorded fact that the weights came from a
    provider.  Everything else goes through :func:`_parse_stored_ckpt`, which
    refuses what is not a digest — including ``""``, which a lenient reader
    might fold to ``None`` and which would then read as *hosted-API weights*
    about a node whose row says something else entirely.

    Kept as one function rather than a null test at the call site so that
    :meth:`AgentModelPins.load_provenance` reads as the three columns it returns
    instead of as a nest of branches, and so there is one answer to *what does a
    NULL in this column mean* for the whole package.
    """
    if stored is None:
        return HOSTED_API_CKPT_HASH
    return _parse_stored_ckpt(node, stored, location)


def _parse_stored_sampling(node: str, stored: Any, location: str) -> AgentSampling:
    """Parse a value read out of ``agent_sampling``, naming the row it came from.

    :func:`~providers.require_agent_sampling` refuses a document that is not the
    four settings, and it is the right function to refuse with — but at a seam
    handed a bare value that is all it can name.  A value read out of the column
    is different: the store knows which row it came from, and a sampling record
    is repaired **per node**, because the draw that produced *that* node's score
    is a fact only the run that made it holds.  So the store translates, keeping
    the parser's message verbatim on the new exception and putting the row's
    address in front of it — the same seam translation :func:`_parse_stored`
    performs for the triple.

    A NULL does not reach here on the **chain-built** tree, where 0115 declares
    the column ``NOT NULL``.  It does reach :func:`_parse_stored_sampling_or_unrecorded`,
    which is the entry point the read path uses, and which keeps the null out of
    this function so that the parse below stays unconditional — a reader handed
    a NULL should be told *this row's dice are not recorded*, not *what is
    recorded here is not four settings*.
    """
    try:
        return require_agent_sampling(stored)
    except AgentSamplingMalformedError as refusal:
        inner = str(refusal).rstrip().removesuffix(".")
        raise AgentSamplingMalformedError(
            f"node {node!r} in the tree store at {location} records "
            f"agent_sampling as something that is not feature 204's four "
            f"settings, and this store will not paper over it: {inner}. The "
            f"draw that produced this node's stored scores is the one the "
            f"recorded settings describe, and a reader that assumed the missing "
            f"ones would be reading a record of a different draw — so this is "
            f"repaired per node, by re-recording the settings that node was "
            f"actually authored under (feature 204; 0115's NOT NULL comment)."
        ) from refusal


def _parse_stored_sampling_or_unrecorded(
    node: str, stored: Any, location: str
) -> AgentSampling | None:
    """Read ``agent_sampling`` as the four settings, or ``None`` when NULL.

    The counterpart of :func:`_parse_stored_ckpt_or_hosted`, for the other
    nullable column — and deliberately *not* symmetric with it, because the two
    nulls are not the same kind of thing.  A NULL ``agent_ckpt_hash`` is a
    recorded fact (hosted-API weights); a NULL ``agent_sampling`` is an
    unrecorded one, reachable on a tree built outside the migration chain, where
    0115's ``NOT NULL`` has not yet been applied or backfilled.  Mapping both to
    ``None`` here would erase that distinction at exactly the moment a caller
    can act on it — the reader of a half-written row is the one who has to run
    the backfill — so this function's ``None`` means *unrecorded*, and
     :attr:`NodeProvenance.self_hosted` reads the other column for the fact.

    Only the value ``None`` maps to ``None``, for the reason
    :func:`_parse_stored_ckpt_or_hosted` gives about ``""``: a reader that
    folded an empty document to *unrecorded* would report a row as
    waiting-for-backfill when its row says something that is not four settings
    at all, and send an operator to re-record over a record that is already
    wrong in a way re-recording will not fix.
    """
    if stored is None:
        return None
    return _parse_stored_sampling(node, stored, location)


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
