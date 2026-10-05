"""The tree seam — a node's measured metrics onto its own existing row.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 3:
*System persists a node's evaluated metrics onto its existing node row with
orchestrator._tree_writer.NodeMetricsWriter(database_url), an implementation
of the evaluator's TreeNodeWriter protocol.*  The evaluator owns the write's
*shape* — :class:`evaluator`'s ``NodeRow``, the seven metric values a live
run measured, handed across a seam it declares but never imports — and the
tree owns the ``node`` table (features 97-101, migrations ``0118`` and
``0114``-``0117``); this module is the one object that joins them, and it is
deliberately the smallest one that can: a bound database URL, one method,
one ``UPDATE``, and two answers.

**The write is an ``UPDATE`` and never an ``INSERT``, and that is the whole
contract.**  A live evaluation does not create nodes: the discovery loop
(discovery's ``AttemptLog``, feature 240) or spec B's root planter writes the
row first, and the evaluator's step 12 then copies the measured scalars onto
that row.  So :meth:`NodeMetricsWriter.write_node` addresses a row *by id*
and refuses — loudly, by name — when the tree does not hold it.  An
``INSERT`` here would be worse than a no-op: it would mint a node carrying a
metric and no ``code_hash``, no authoring model and no artifact, a row the
tree walk would find and no evaluation could explain.  ``0118``'s own
docstring states the other side of the same law from inside the table —
*"a node with no ``code_hash`` is not a node at all but an empty attempt"* —
and this writer obeys it by never being the one that puts a row there.

**Idempotent by value, and the second answer is ``False``.**  §14's contract
is that an evaluation retries; a retry re-derives the same metrics from the
same sealed snapshot and charges nothing new.  A second ``write_node`` with
the same seven values is therefore answered ``(node_id, False)`` and touches
no row — no ``UPDATE`` is issued at all, so the write is a no-op the database
never sees rather than a rewrite that happens to store the same bytes.  The
answer mirrors the evaluator's own seam, which reads ``(node_id, appended)``
and carries it onward as ``tree_appended`` on a
:class:`~evaluator.NodePersistence`: the caller can tell a first write from a
retry without re-reading the row.

**A changed value is a conflict, not a refresh.**  The seven metrics are
*measured*, not assigned: two different values for one node mean two
different evaluations of one hypothesis, and the tree keeps one row per node
(§14's identity law, the reason ``node.id`` is a derived ``uuid5`` over the
parent).  So a row that already holds metrics and is handed *different* ones
raises :class:`NodeMetricsConflictError` — the code word
``node_metrics_conflict`` — naming the node and the columns that disagree.
Silently overwriting would let a re-evaluation with a different seed, a
different snapshot or a different cost model bury the number the first
evaluation stood behind, which is exactly the "last write wins" a stored
scalar compared across nodes and cycles must never be.  The conflict is
*decidable from the message*: it names the node and each column's standing
and offered value, so an operator reads which metric moved and by how much.

**Absence is not a measurement, three times over.**  A row this writer has
never served holds ``NULL`` in all seven columns — ``0114``'s docstring
argues at length why a pre-metric row carries no default — and ``NULL`` is
read as "not yet measured", never as zero: the first write lands, and
``written`` is ``True`` because the row genuinely changed.  ``NodeRow``
carries ``perturb_stability`` as ``None`` (feature 85: *"step 10 is not this
step's input, so the honest value is 'not measured by this step'"*), and
this writer takes that at its word — a ``None`` for that one column is *left
untouched*, both in the write and in the conflict comparison, so this step
cannot clobber a stability figure the tripwires member persisted
(:mod:`tripwires.node_metric` writes the same column) and a bare live run
does not conflict with a row a tripwire has already measured.  A number for
it *is* written and *is* compared, because then it is a measurement and falls
under the same changed-value law as the other six.

**The database is the injected ``database_url``, and it is SQLite.**  The
spec's own sentence for the tests — *"a throwaway SQLite database migrated
with the node table migrations"* — is also the deployment this member ships
against: the workspace runs SQLite on one machine (the app spec's dev
allowance) and the tree the live loop writes is that file.  So the URL is
parsed with the same ``sqlite:///`` grammar every store in this workspace
restates, a non-SQLite scheme is refused by name (this writer speaks one
dialect), and an in-memory URL is refused because a node row must outlive the
connection that wrote it.  Construction performs no I/O — the path is
resolved on first use — so composing a run that carries this writer touches
no disk until a node is actually evaluated.

**No schema is created here.**  The ``node`` table and its seven metric
columns belong to the migrations (``0118`` creates the table, ``0114`` adds
the metrics), and a writer that issued ``CREATE TABLE`` or ``ALTER TABLE``
would be inventing a tree the schema owns — the same stance discovery's
``AttemptLog`` takes toward the table it writes into.  A database the chain
has not reached has no table to ``UPDATE``, and that is refused by name
rather than papered over: :meth:`write_node` reports it as a missing node, in
the migration's own terms, because from the caller's view the difference
between "no table" and "no row" is only which side of the same refusal it is
looking at.

**The protocol is structural, so nothing is imported from the evaluator.**
The module holds no ``import evaluator``: ``TreeNodeWriter`` is a ``Protocol``
precisely so this object can satisfy it by having a ``write_node`` method, and
the ``NodeRow`` it is handed is read by attribute — the duck typing the
evaluator's own seam documents (*"satisfied structurally with no adapter"*).
That keeps this module stdlib-only and import-cheap, so the module scan that
composes the application pays nothing for a writer that has not been asked to
write.

**One error.  The vocabulary a caller needs is the conflict, and it is
here.**  A missing row and a changed value are the same *repair* — the tree
and the evaluation disagree about what this node measured, and the caller
must stop rather than overwrite — so they are one class,
:class:`NodeMetricsConflictError`, distinguished by their message and their
code word.  Everything else this writer can be handed — a URL it cannot
speak, a ``node_row`` with no id — is a wiring fault rather than a conflict
with a row, and is refused with the base :class:`NodeMetricsWriterError`;
neither is a runtime condition to catch and continue past.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import unquote, urlparse

__all__ = [
    "NODE_METRICS_CONFLICT_CODE",
    "NodeMetricsConflictError",
    "NodeMetricsWriter",
    "NodeMetricsWriterError",
]

#: The environment variable naming the relational store — the one spelling the
#: workspace's stores share, restated here so this module states its own
#: contract rather than importing another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the node's row lives in — migration ``0118``'s, whose own
#: docstring argues why it is a table and the metrics are columns, and why
#: ``created_at`` (and here, the metrics) are society-owned rather than this
#: writer's to create.
NODE_TABLE = "node"

#: The node's key column — ``0118``'s ``id``, the derived ``uuid5`` identity
#: every ``parent_id`` and every downstream ``node_id`` resolves to.
NODE_ID_COLUMN = "id"

#: The six metric columns this writer always carries — feature 101's seven,
#: less ``perturb_stability``.  These are the columns feature 85's ``NodeRow``
#: names as the node's own measured scalars (four from step 8, ``ir_marginal``
#: from step 9, ``cost_adjusted_ir`` from step 10's cost-adjusted axis), and
#: they travel together on one row in one transaction.
_CORE_COLUMNS: Tuple[str, ...] = (
    "ic_mean",
    "ic_tstat",
    "ir_standalone",
    "ir_marginal",
    "turnover",
    "cost_adjusted_ir",
)

#: The one metric column whose incoming value may be ``None`` — step 10's
#: tripwire figure, which feature 85's ``NodeRow`` carries as ``None`` because
#: it is not that step's input.  A ``None`` here is *not measured by this
#: step*, so the column is left exactly as the tree holds it; a number is a
#: measurement and is written.
_OPTIONAL_COLUMN = "perturb_stability"

#: All seven feature-101 columns, in the order the migration adds them — the
#: ``SET`` list of the ``UPDATE`` and the ``SELECT`` list of the read, one
#: spelling so the two cannot drift.
_TARGET_COLUMNS: Tuple[str, ...] = _CORE_COLUMNS + (_OPTIONAL_COLUMN,)

#: The greppable word that opens every :class:`NodeMetricsConflictError`
#: message — the spec's own spelling, so an operator greps one word for *the
#: tree and the evaluation disagree about this node's metrics* and reaches
#: both faces of it (a row that is absent, a value that changed) without
#: parsing prose.
NODE_METRICS_CONFLICT_CODE = "node_metrics_conflict"

#: The migration that owns the ``node`` table, named in the refusal a database
#: the chain has not reached produces — because SQLite's own ``no such
#: table: node`` names the table but not the feature that creates it.
_NODE_MIGRATION = "migrations/versions/0118_node_table.py"


class NodeMetricsWriterError(Exception):
    """Base class for every failure of the tree-writer seam.

    The wiring refusals: a ``database_url`` this writer cannot speak (a
    non-SQLite scheme, a host, a pathless in-memory URL), or a ``node_row``
    that names no node.  These are facts about *how the writer was built or
    called* rather than about the state of any one row, so they are separated
    from :class:`NodeMetricsConflictError` — a caller divides "the wiring is
    wrong" from "the tree and the evaluation disagree" by class alone, and
    neither is a runtime condition to catch and continue past.
    """


class NodeMetricsConflictError(NodeMetricsWriterError):
    """The tree and the evaluation disagree about one node's metrics.

    Two faces, one repair — stop rather than overwrite — and one code word
    (:data:`NODE_METRICS_CONFLICT_CODE`):

    * **an absent row.**  The write is an ``UPDATE`` keyed by
      ``node_row.node_id``, and the tree does not hold that node.  A live
      evaluation never creates nodes (the discovery loop or the root planter
      does), so an absent row means the evaluation reached step 12 for a node
      the tree was never handed — or reached a database the ``node``
      migration has not created.  The refusal names the node and the
      migration that owns the table; it is never answered by an ``INSERT``,
      which would fabricate a node carrying a metric and no identity.

    * **a changed value.**  The row already holds metrics and the write
      offers *different* ones.  The seven metrics are measured, not assigned,
      and the tree keeps one row per node, so a differing value is a second
      evaluation of one hypothesis whose first result already stands.  The
      refusal names the node and each column that disagrees — the standing
      value and the offered one — so the conflict is decidable from the
      message alone.

    Both faces are the same class because they are the same *caller action*
    (the write must not proceed), and distinguishing them by subclass would
    split one repair in two for no caller's benefit.  The message and the
    code word carry the difference; the class carries the decision.
    """


class NodeMetricsWriter:
    """The evaluator's ``TreeNodeWriter`` over the workspace's ``node`` table.

    Bound to a ``database_url`` at construction, which performs no I/O — the
    path is resolved on first use — so composing an application that carries
    this writer touches no disk.  The one method, :meth:`write_node`, copies a
    node's seven measured metrics onto the row the tree already holds for it,
    keyed by ``node_row.node_id``.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise NodeMetricsWriterError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL naming "
                "the tree whose node rows this writer updates, got "
                f"{database_url!r}; a writer with no tree names no table its "
                "metrics could reach (additions_spec_live_evaluation.xml, "
                "feature 3)"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None
        self._resolved = False

    @property
    def database_url(self) -> str:
        """The URL this writer was bound to."""
        return self._database_url

    # -- Construction -------------------------------------------------------

    def _resolve_path(self) -> Path:
        """Resolve the ``sqlite:///`` path once, refusing schemes it cannot read.

        Deferred out of ``__init__`` so construction performs no I/O.  The
        grammar is the one every store in this workspace restates: a
        non-SQLite scheme is refused by name (this writer speaks one
        dialect), a host is refused, and a pathless URL — SQLite's in-memory
        spelling — is refused because a node row must outlive the connection
        that wrote it and the replay engine reads it from another process.
        """
        if self._resolved:
            assert self._path is not None
            return self._path
        parsed = urlparse(self._database_url)
        if parsed.scheme != "sqlite":
            raise NodeMetricsWriterError(
                f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: "
                "the tree writer speaks sqlite:/// (the spec's single-machine "
                f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
                "the node table already lives in (feature 3)"
            )
        if parsed.netloc not in ("", "localhost"):
            raise NodeMetricsWriterError(
                f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
                f"{parsed.netloc!r} (feature 3)"
            )
        path = unquote(parsed.path).removeprefix("/")
        if not path or path == ":memory:":
            raise NodeMetricsWriterError(
                f"sqlite {DATABASE_URL_ENV} carries no database path: an "
                "in-memory tree would die with the connection that opened it, "
                "and a node row must outlive the evaluation that wrote it "
                "(feature 3)"
            )
        self._path = Path(path)
        self._resolved = True
        return self._path

    # -- The write ----------------------------------------------------------

    def write_node(self, node_row: Any) -> Tuple[str, bool]:
        """Update one node's metric columns; answer ``(node_id, written)``.

        Copies the seven metrics the evaluator measured onto the row the tree
        already holds for ``node_row.node_id``, in one ``UPDATE`` and one
        transaction.  ``written`` is ``True`` when this call changed the row —
        a first write, which is the only call that issues the ``UPDATE`` — and
        ``False`` when the row already held exactly these values, which is the
        retry §14 requires to be a no-op.

        Raises :class:`NodeMetricsConflictError` when the tree does not hold
        the node (the write is never answered by an ``INSERT``) and when the
        row already holds metrics whose values differ from the ones offered —
        see the class for both faces.  ``perturb_stability`` is written and
        compared only when the record states a number; a ``None`` leaves the
        column exactly as the tree holds it, so this step cannot clobber a
        tripwire's figure and does not conflict with one.

        A ``database_url`` this writer cannot speak or a ``node_row`` that
        names no node is refused with :class:`NodeMetricsWriterError`, before
        the database is touched.
        """
        node_id = _node_id_of(node_row)
        incoming = _incoming_values(node_row)
        path = self._resolve_path()
        with closing(sqlite3.connect(path)) as connection, connection:
            stored = _read_row(connection, node_id)
            if stored is None:
                raise NodeMetricsConflictError(
                    f"{NODE_METRICS_CONFLICT_CODE}: the discovery tree at "
                    f"{self._database_url!r} holds no node {node_id!r} to "
                    "write metrics onto. A live evaluation never creates "
                    "nodes — the discovery loop (feature 240) or the root "
                    "planter writes the row first, and step 12 copies the "
                    f"measured scalars onto it — and {_NODE_MIGRATION} must "
                    "have created the table for any row to exist. This writer "
                    "updates an existing row and never INSERTs one, so a node "
                    "the tree does not hold is a refusal and not a new row"
                )
            if _holds_metrics(stored):
                differing = _differences(stored, incoming)
                if not differing:
                    return (node_id, False)
                raise NodeMetricsConflictError(
                    f"{NODE_METRICS_CONFLICT_CODE}: node {node_id!r} already "
                    "holds metrics that differ from the ones offered; the "
                    "seven scalars are measured, not assigned, and the tree "
                    "keeps one row per node, so a differing value is a second "
                    "evaluation of one hypothesis — "
                    + "; ".join(differing)
                )
            _update(connection, node_id, incoming)
        return (node_id, True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- Reading the row, as the table holds it ------------------------------------


def _node_id_of(node_row: Any) -> str:
    """The node the write is keyed by, refused by name when it names none.

    The id is the row's primary key (``0118``'s ``id``), so a row that names
    no node names no row to update — a wiring fault, refused with the base
    error before the database is touched.
    """
    node_id = getattr(node_row, "node_id", None)
    if not isinstance(node_id, str) or not node_id.strip():
        raise NodeMetricsWriterError(
            "a tree write must name the node whose row it updates, got "
            f"node_id {node_id!r} on {type(node_row).__name__}; the metrics "
            "are keyed by the node's id, and a row with no id names no row to "
            "update (feature 3)"
        )
    return node_id.strip()


def _incoming_values(node_row: Any) -> dict[str, Optional[float]]:
    """The seven values the record offers, as numbers or an honest ``None``.

    Read by attribute — the ``NodeRow`` the evaluator hands across its seam is
    duck-typed, not imported.  The six core metrics must each be a finite
    number (a ``None`` there would be a record that measured nothing, and
    ``NULL`` is where *unmeasured* already lives); ``perturb_stability`` may be
    ``None``, which means *not measured by this step* rather than zero.
    """
    values: dict[str, Optional[float]] = {}
    for column in _CORE_COLUMNS:
        value = getattr(node_row, column, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise NodeMetricsWriterError(
                f"the record offers no measured {column!r} for the node "
                f"(got {value!r}); the six core metrics are measured "
                "quantities and NULL is where 'not measured' lives, so a "
                "record that measured nothing has no row to write (feature 3)"
            )
        values[column] = float(value)
    perturb = getattr(node_row, _OPTIONAL_COLUMN, None)
    if perturb is not None:
        if isinstance(perturb, bool) or not isinstance(perturb, (int, float)):
            raise NodeMetricsWriterError(
                f"the record offers {_OPTIONAL_COLUMN!r} as {perturb!r}; it "
                "is a measured figure or an honest None — *not measured by "
                "this step* — and anything else is neither (feature 3)"
            )
        values[_OPTIONAL_COLUMN] = float(perturb)
    else:
        values[_OPTIONAL_COLUMN] = None
    return values


def _read_row(
    connection: sqlite3.Connection, node_id: str
) -> Optional[dict[str, Optional[float]]]:
    """The seven metric columns the tree holds for ``node_id``, or ``None``.

    ``None`` means the tree holds no such node *or* holds no table at all —
    from the caller's view the two are one refusal (nothing to update), and
    :meth:`NodeMetricsWriter.write_node` names the migration that owns the
    table so an operator can tell which from the message.  Only SQLite's own
    "no such table" is read that way; any *other* store error (a locked or
    unwritable database, a malformed query) is a wiring fault and surfaces as
    the base error rather than being mistaken for an absent node.
    """
    try:
        row = connection.execute(
            f"SELECT {', '.join(_TARGET_COLUMNS)} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # `no such table: node` — the migration has not reached this database.
        # The caller sees it as "the tree holds no node", which is the truth,
        # and the migration is named in the refusal above.  Anything else that
        # happens to be an OperationalError is not that fact and is refused as
        # the store fault it is.
        if "no such table" not in str(exc).lower():
            raise NodeMetricsWriterError(
                f"could not read node {node_id!r} from the tree at "
                f"{NODE_TABLE}: {exc} (feature 3)"
            ) from exc
        return None
    except sqlite3.Error as exc:
        raise NodeMetricsWriterError(
            f"could not read node {node_id!r} from the tree at {NODE_TABLE}: "
            f"{exc} (feature 3)"
        ) from exc
    if row is None:
        return None
    return {
        column: (None if value is None else float(value))
        for column, value in zip(_TARGET_COLUMNS, row)
    }


def _holds_metrics(stored: dict[str, Optional[float]]) -> bool:
    """Whether the row already carries a measurement.

    The six *core* columns decide it — they travel together from one write, so
    a row whose six are all non-``NULL`` holds a metrics this writer (or a
    sibling step of the same evaluation) landed, and a changed value is a
    conflict.  ``perturb_stability`` is excluded: the tripwires member writes
    it on its own, so a tree holding only that column has not yet been served
    by this writer and its first write must land rather than conflict.
    """
    return all(stored[column] is not None for column in _CORE_COLUMNS)


def _differences(
    stored: dict[str, Optional[float]], incoming: dict[str, Optional[float]]
) -> list[str]:
    """The columns whose offered value differs from the one the row holds.

    Empty means the write is a no-op and the answer is ``False``.  The six
    core columns are always compared; ``perturb_stability`` only when the
    record offers a number, because a ``None`` there means *this step did not
    measure it* and absence is not a differing measurement.
    """
    differing: list[str] = []
    for column in _CORE_COLUMNS:
        if stored[column] != incoming[column]:
            differing.append(
                f"{column} holds {stored[column]!r}, the record offers "
                f"{incoming[column]!r}"
            )
    if incoming[_OPTIONAL_COLUMN] is not None and (
        stored[_OPTIONAL_COLUMN] != incoming[_OPTIONAL_COLUMN]
    ):
        differing.append(
            f"{_OPTIONAL_COLUMN} holds {stored[_OPTIONAL_COLUMN]!r}, the "
            f"record offers {incoming[_OPTIONAL_COLUMN]!r}"
        )
    return differing


def _update(
    connection: sqlite3.Connection,
    node_id: str,
    incoming: dict[str, Optional[float]],
) -> None:
    """Set the metric columns on the node's row — one ``UPDATE``, one statement.

    The six core columns are always set; ``perturb_stability`` is set only
    when the record offers a number, so a bare live run never clobbers a
    tripwire's figure.  The row was read moments before in this same
    transaction, so a ``rowcount`` other than one means the write did not land
    — and reporting success there would be the "looks done, is not" failure
    the write's whole contract exists to prevent.
    """
    assignments = [f"{column} = ?" for column in _CORE_COLUMNS]
    values: list[Optional[float]] = [incoming[column] for column in _CORE_COLUMNS]
    if incoming[_OPTIONAL_COLUMN] is not None:
        assignments.append(f"{_OPTIONAL_COLUMN} = ?")
        values.append(incoming[_OPTIONAL_COLUMN])
    values.append(node_id)
    cursor = connection.execute(
        f"UPDATE {NODE_TABLE} SET {', '.join(assignments)} "
        f"WHERE {NODE_ID_COLUMN} = ?",
        values,
    )
    if cursor.rowcount != 1:
        raise NodeMetricsWriterError(
            f"the tree write for node {node_id!r} matched {cursor.rowcount} "
            "rows where it must match exactly one; the row was read moments "
            "before in this same transaction, so a mismatch means the write "
            "did not land and reporting success would report a metric no node "
            "carries (feature 3)"
        )
