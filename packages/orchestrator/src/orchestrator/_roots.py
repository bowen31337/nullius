"""Root planting — a campaign's opening signal, as the tree's depth-0 row.

additions_spec_campaign_driver.xml, "Roots", feature 2: *System persists a
planted root as a depth-0 node row with orchestrator._roots.plant_root(
campaign_id, theme_root, authored, *, context, artifact_store), and it
answers the root's node id.*  Feature 1 (:meth:`signal_agent.LLMSignalAuthor.
author_root`) authors the signal; this module is the other half — the write
that turns an :class:`~signal_agent.AuthoredSignal` into the first row of a
theme's discovery tree, the row every later expansion's ``parent_id`` will
eventually trace back to.

**The row, column by column.**  ``id`` is ``authored.record.node_id`` —
feature 1's own ``root_id``, never re-derived here — with ``parent_id`` fixed
at ``NULL`` (a root has no parent; §9.1's self-referencing foreign key is
exempt from ``NULL``) and ``depth`` fixed at ``0``, the two facts that make a
row a *root* rather than a derivation of this function's own guessing.
``campaign_id`` and ``theme_root`` are the caller's own two arguments —
unchanged, because they name the tree this root is being planted into, not
anything the authoring call could know about itself.  ``code_hash`` is
:func:`signal_agent.source_code_hash` of ``authored.code`` — the identity
hash every writer in this workspace takes the same way — and
``stated_mechanism`` is ``authored.stated_mechanism`` verbatim, carrying its
own honest ``None`` when the model stated no rationale.  ``artifact_uri`` is
where :func:`artifacts.artifact_uri` resolves the node's directory to be,
under the ``artifact_store`` this call was handed.  The provenance trio
(``evaluator_hash``, ``snapshot_hash``, ``cost_model_hash``) comes off
``context`` — the live run's own identity, stamped onto the root the same way
every later evaluation of it will be — and the authoring trio
(``agent_model_id``, ``agent_sampling``, and ``agent_ckpt_hash`` riding beside
them) comes off ``authored.record.attempt_provenance_terms()``, the mapping
:class:`~providers.AuthoringRecord` is built to splat onto exactly this kind
of row.

**The code lands through the ArtifactStore directly, not through the
evaluator's pair.**  :func:`artifacts.persist_execution` stages ``code.py``
*and* an execution trace as one contract, because that module's feature is
about a run that has already happened.  A root has not been evaluated yet —
there is no trace to pair it with — so this module stages
:data:`artifacts.SOURCE_FILENAME` on its own, through the store's plain
``write``/``commit``, exactly as the feature's own sentence says: *"artifact_uri
is where the code is written through the ArtifactStore."*

**Idempotent by value, and a second plant writes nothing at all.**  The
tree-writer sibling in this package (:mod:`orchestrator._tree_writer`) states
the discipline this module follows: a rewrite that happens to store the same
bytes is still a rewrite, and the honest no-op touches neither the database
nor the artifact store.  So the existing row for ``authored.record.node_id``
is read *before* anything is written, and when every column the caller's
inputs would produce already matches it, :func:`plant_root` answers the same
id and does no I/O of any kind — not a redundant ``INSERT`` that would be
refused as a duplicate key, and not a redundant artifact commit that would
replace a directory with byte-identical content.  A row that exists with
*different* values is the one case this module treats as a defect rather
than a replay: the five static facts and the nine recorded ones are measured
once, at authoring time, and a second, disagreeing answer for the same node
id means two callers planted two different roots under one identity —
refused as :class:`RootPlantError`, naming the node and every column that
disagrees, before either store is touched.

**Why the artifact is staged before the row, not after.**  A tempting
mirror of :mod:`discovery.persist`'s ``AttemptLog`` would write the row
first and the artifact second, on the theory that a row with an unpublished
``artifact_uri`` is the more recoverable half-state. That reasoning holds
*there* because that module always restages and recommits on every call,
healing a half-state on the very next attempt. This module does the
opposite by design — a second, identical plant does **no** I/O, including no
artifact recommit — so a row inserted before its artifact lands would be a
*permanent* half-state: the next call would see the row already matches and
would never retry the commit. Staging the code and committing it first, and
only then inserting the row, means a failure before the row exists leaves
nothing for a retry to recover *from* — the retry simply starts over, as if
this call had never happened.

**Depth is checked before anything else is read.** *"An authored record
whose depth is not 0 raises RootPlantError."* A root is depth 0 by
definition; a record built for an expansion handed to this function is not a
wiring accident worth a second, more specific exception — it is refused by
the same vocabulary, naming the depth it actually carries, before the node
id, the code hash or either store is touched.

Tests run the real seam: a throwaway SQLite database migrated with the
node table's own migrations (``0118`` creates the table; ``0115``-``0117``
add the three trios this module writes), and a real :class:`artifacts.
ArtifactStore` over a ``tmp_path`` directory — the spec's own sentence, taken
literally, the same way the tree-writer and artifact-writer suites beside
this one take it.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote, urlparse

from artifacts import SOURCE_FILENAME, artifact_uri
from signal_agent import source_code_hash

__all__ = ["ROOT_PLANT_CODE", "RootPlantError", "plant_root"]

#: The greppable word every :class:`RootPlantError` message opens with — the
#: feature's own parenthetical, spelled once so the raise sites and an
#: operator's grep agree on one token.
ROOT_PLANT_CODE: Final[str] = "root_plant"

#: The table this module writes one row of, per campaign theme root.
_NODE_TABLE: Final[str] = "node"

#: The migration that creates :data:`_NODE_TABLE` — named in the refusal a
#: database the chain has not reached produces, because SQLite's own "no
#: such table" names the table but not the feature that creates it.
_NODE_MIGRATION: Final[str] = "migrations/versions/0118_node_table.py"

#: The row's columns beyond ``id``, in the order the ``INSERT`` and the
#: comparison ``SELECT`` both use — one spelling so the two cannot drift.
#: ``parent_id`` and ``depth`` are included even though their values are
#: fixed by this module (``NULL`` and ``0``): a stored row with some other
#: value in either is still a disagreement this function must name, not a
#: column it is free to assume.
_OTHER_COLUMNS: Final[tuple[str, ...]] = (
    "parent_id",
    "campaign_id",
    "theme_root",
    "depth",
    "code_hash",
    "stated_mechanism",
    "artifact_uri",
    "evaluator_hash",
    "snapshot_hash",
    "cost_model_hash",
    "agent_model_id",
    "agent_ckpt_hash",
    "agent_sampling",
)

#: The canonical JSON rendering every member of this workspace that writes
#: ``agent_sampling`` uses — sorted keys and compact separators, so two
#: equal samplings render to equal bytes and key order is never part of a
#: node's identity.  Restated rather than imported: ``providers`` keeps this
#: mapping private to its own module, the same trade
#: :func:`signal_agent.source_code_hash` makes for ``code_hash`` rather than
#: reaching into the evaluator for three lines of stdlib.
_JSON_KWARGS: Final[dict[str, Any]] = {
    "sort_keys": True,
    "separators": (",", ":"),
    "allow_nan": False,
}


class RootPlantError(Exception):
    """A root could not be planted as asked.

    Raised by :func:`plant_root`, and only there, for the feature's two named
    refusals: an ``authored`` record whose depth is not ``0`` (a root is
    depth 0 by definition, and a record built for anything else is the wrong
    shape before a single column is computed), and a node id the tree already
    holds under *different* values than this call would write — the node and
    every disagreeing column are named, so the defect is decidable from the
    message. A handful of wiring faults share the class rather than growing
    their own: a blank ``campaign_id`` or ``theme_root``, an authoring record
    with no usable id, a database URL this module cannot speak, and a
    database the node migration has not reached. Every message opens with
    :data:`ROOT_PLANT_CODE`.
    """


def plant_root(
    campaign_id: str,
    theme_root: str,
    authored: Any,
    *,
    context: Any,
    artifact_store: Any,
) -> str:
    """Persist ``authored`` as the campaign's depth-0 root; answer its node id.

    ``authored`` is a :class:`signal_agent.AuthoredSignal` (or anything that
    carries the same four attributes) whose ``record`` is a
    :class:`providers.AuthoringRecord` — both read structurally, never by
    ``isinstance``, because the module loader's double import makes that
    check unreliable for a value built across the seam. ``context`` is read
    for its ``database_url`` (where the row lands) and its provenance trio
    (``evaluator_hash``, ``snapshot_hash``, ``cost_model_hash``); a
    :class:`~orchestrator._context.EvaluationContext` satisfies this by
    construction, and a test's lightweight stand-in need carry only the four
    attributes this function actually reads.

    See the module docstring for the full account of the row, the write
    order, and why a second identical plant performs no I/O at all.
    """
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: campaign_id must be a non-blank string, got "
            f"{campaign_id!r}; the row's campaign_id is this argument "
            "verbatim, and a blank one names no campaign to plant a root in"
        )
    if not isinstance(theme_root, str) or not theme_root.strip():
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: theme_root must be a non-blank string, got "
            f"{theme_root!r}; every node belongs to the theme its root was "
            "planted in, and a blank one names no theme"
        )
    record = authored.record
    depth = getattr(record, "depth", None)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth != 0:
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: authored.record.depth must be 0 — a root is "
            f"depth 0 by definition — got {depth!r}; plant_root persists "
            "opening signals only, and a record built for an expansion is "
            "the wrong shape to plant as one"
        )
    node_id = getattr(record, "node_id", None)
    if not isinstance(node_id, str) or not node_id.strip():
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: authored.record.node_id must be a non-blank "
            f"string, got {node_id!r}; the row is keyed by this id, and a "
            "record with no id names no row to plant"
        )

    code_hash = source_code_hash(authored.code)
    uri = artifact_uri(artifact_store, campaign_id, node_id)
    evaluator_hash = _require_context_hash(context, "evaluator_hash")
    snapshot_hash = _require_context_hash(context, "snapshot_hash")
    cost_model_hash = _require_context_hash(context, "cost_model_hash")
    agent_model_id, agent_ckpt_hash, agent_sampling = _authoring_trio(record)

    computed = {
        "parent_id": None,
        "campaign_id": campaign_id,
        "theme_root": theme_root,
        "depth": 0,
        "code_hash": code_hash,
        "stated_mechanism": authored.stated_mechanism,
        "artifact_uri": uri,
        "evaluator_hash": evaluator_hash,
        "snapshot_hash": snapshot_hash,
        "cost_model_hash": cost_model_hash,
        "agent_model_id": agent_model_id,
        "agent_ckpt_hash": agent_ckpt_hash,
        "agent_sampling": agent_sampling,
    }

    path = _sqlite_path(_require_database_url(context))
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        stored = _read_row(connection, node_id)
        if stored is not None:
            differing = _differences(stored, computed)
            if differing:
                raise RootPlantError(
                    f"{ROOT_PLANT_CODE}: node {node_id!r} is already planted "
                    "with different values; the five static facts and the "
                    "nine recorded ones are measured once, at authoring "
                    "time, so a disagreeing second answer for the same node "
                    "id is two different roots under one identity — "
                    + "; ".join(differing)
                )
            return node_id

        artifact_store.discard(campaign_id, node_id)
        artifact_store.write(campaign_id, node_id, SOURCE_FILENAME, authored.code)
        artifact_store.commit(campaign_id, node_id)
        _insert_row(connection, node_id, computed)
    return node_id


# -- Reading the inputs --------------------------------------------------------


def _require_context_hash(context: Any, name: str) -> str:
    """One member of the provenance trio, off ``context``, non-blank."""
    value = getattr(context, name, None)
    if not isinstance(value, str) or not value.strip():
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: context.{name} must be a non-blank string, "
            f"got {value!r}; the provenance trio is the live run's own "
            "identity, stamped onto the root the same way every later "
            "evaluation of it will be, and a blank hash names nothing to "
            "stamp"
        )
    return value


def _require_database_url(context: Any) -> str:
    """``context.database_url`` — the store the row is planted into."""
    value = getattr(context, "database_url", None)
    if not isinstance(value, str) or not value.strip():
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: context.database_url must be a non-blank "
            f"string, got {value!r}; the root's row has nowhere to land "
            "without it"
        )
    return value


def _authoring_trio(record: Any) -> tuple[str, str | None, str]:
    """``agent_model_id``, ``agent_ckpt_hash`` and ``agent_sampling`` (JSON text).

    Read off ``record.attempt_provenance_terms()`` — the mapping
    :class:`providers.AuthoringRecord` is built to splat onto exactly this
    kind of row — rather than off ``record.pin`` or ``record.sampling``
    directly, so this module reads the one seam the provider member states
    for the purpose rather than re-deriving it a second way.
    """
    terms = record.attempt_provenance_terms()
    model_id = terms.get("agent_model_id") if isinstance(terms, dict) else None
    if not isinstance(model_id, str) or not model_id.strip():
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: authored.record.attempt_provenance_terms() "
            f"must carry a non-blank 'agent_model_id', got {terms!r}; every "
            "node is authored by exactly one model, and a blank or missing "
            "one is a stratum the node cannot be placed in"
        )
    ckpt_hash = terms.get("agent_ckpt_hash")
    if ckpt_hash is not None and not isinstance(ckpt_hash, str):
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: authored.record.attempt_provenance_terms() "
            f"carries 'agent_ckpt_hash' as {ckpt_hash!r}; the column is a "
            "hash string or an honest None, and anything else is neither"
        )
    sampling = terms.get("agent_sampling")
    if not isinstance(sampling, dict):
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: authored.record.attempt_provenance_terms() "
            f"must carry 'agent_sampling' as a mapping, got {sampling!r}; "
            "the four settings are what a replay would re-issue the "
            "authoring call with, and a value that is not a mapping cannot "
            "be rendered as the column's JSON text"
        )
    try:
        sampling_text = json.dumps(sampling, **_JSON_KWARGS)
    except (TypeError, ValueError) as exc:
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: authored.record.attempt_provenance_terms()'s "
            f"'agent_sampling' must be renderable as canonical JSON — {exc}; "
            "the column holds this text and every reader parses it back"
        ) from exc
    return model_id, ckpt_hash, sampling_text


# -- The database ---------------------------------------------------------------


def _sqlite_path(database_url: str) -> Path:
    """Translate ``context.database_url`` into a filesystem path.

    The same ``sqlite:///`` grammar every store in this workspace restates
    (the tree-writer sibling in this package parses it the identical way): a
    non-SQLite scheme, a host, or a pathless (``:memory:``) URL are refused
    by name, because a planted root must outlive the connection that wrote
    it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: unsupported database_url scheme "
            f"{parsed.scheme!r}: plant_root speaks sqlite:/// only (the "
            f"spec's single-machine dev allowance); point context."
            "database_url at the sqlite database the node table lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: sqlite database_url must not carry a host, "
            f"got {parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: sqlite database_url carries no database "
            "path: an in-memory tree would die with the connection that "
            "planted the root, and a node row must outlive it"
        )
    return Path(path)


def _read_row(connection: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    """The stored row's :data:`_OTHER_COLUMNS`, or ``None`` when absent.

    ``None`` covers both "no such node" and "no such table" — the latter
    translated here, naming :data:`_NODE_MIGRATION`, because SQLite's own
    message names the table but not the feature that creates it. Any other
    :class:`sqlite3.Error` is a store fault, not an absent row, and is not
    mistaken for one.
    """
    try:
        row = connection.execute(
            f"SELECT {', '.join(_OTHER_COLUMNS)} FROM {_NODE_TABLE} "
            "WHERE id = ?",
            (node_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise RootPlantError(
                f"{ROOT_PLANT_CODE}: could not read node {node_id!r}: {exc}"
            ) from exc
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: the database holds no {_NODE_TABLE!r} "
            f"table; {_NODE_MIGRATION} must create it before a root can be "
            "planted"
        ) from exc
    except sqlite3.Error as exc:
        raise RootPlantError(
            f"{ROOT_PLANT_CODE}: could not read node {node_id!r}: {exc}"
        ) from exc
    if row is None:
        return None
    return dict(zip(_OTHER_COLUMNS, row))


def _differences(stored: dict[str, Any], computed: dict[str, Any]) -> list[str]:
    """Every column of :data:`_OTHER_COLUMNS` whose stored value disagrees."""
    differing: list[str] = []
    for column in _OTHER_COLUMNS:
        if stored[column] != computed[column]:
            differing.append(
                f"{column} holds {stored[column]!r}, this call offers "
                f"{computed[column]!r}"
            )
    return differing


def _insert_row(
    connection: sqlite3.Connection, node_id: str, computed: dict[str, Any]
) -> None:
    """Insert the root's row — one ``INSERT``, the only write this call makes.

    Issued only once the artifact is already committed (see the module
    docstring's "why the artifact is staged before the row"), so a failure
    reaching this point never leaves a row whose ``artifact_uri`` names an
    unpublished directory.
    """
    columns = ("id",) + _OTHER_COLUMNS
    values = (node_id,) + tuple(computed[column] for column in _OTHER_COLUMNS)
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {_NODE_TABLE} ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        values,
    )
