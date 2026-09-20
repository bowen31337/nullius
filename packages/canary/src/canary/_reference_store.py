"""Persisting §12's frozen determinism reference pair — feature 141's store half.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*  :mod:`canary._reference` is the *frozen pair* —
the value types, the canonical bytes, the hashes; this module writes it down.
The split is the one this workspace already uses twice — :mod:`nulloracle.ks`
states the test and :mod:`nulloracle.ksguard` writes its answer,
:mod:`nulloracle.assignment` states the schema and :mod:`nulloracle.sidecar`
writes the file — and for the same reason: the value types can be tested with
no database in the way, and the store can be tested with a hand-built pair
rather than a hand-built freeze.

**The two tables, and which half each carries.**  ``migrations/versions/
0119_canary_reference_pair.py`` creates two tables and this module writes both,
one row per frozen pair, keyed by a shared ``reference_id``:

* ``canary_reference_policy`` carries the policy half — its ``version``
  (UNIQUE), its canonical ``source`` bytes and its ``code_hash``, the identity
  the nightly replay checks the replayed policy against.  The ``version`` is
  UNIQUE for the same reason ``policy_revision.policy_version`` is: a version is
  a name for one policy, and two policies sharing one version would make the
  store's own key unreadable.
* ``canary_reference_tree`` carries the tree half — its ``tree_hash``, the
  identity the nightly replay checks the replayed tree against, and the count of
  nodes.  The per-node rows live in ``canary_reference_tree_node`` — one row per
  node, keyed by ``(reference_id, node_id)``, carrying the parent, the depth and
  the canonical payload.  The tree hash is on the tree row, not the nodes: the
  hash is the identity of the whole tree, and a per-node column would repeat it
  on every row and could drift from it.

The ``reference_id`` that joins the two halves is a minted UUID, the same kind
of value the rest of the spine mints for a row's identity.  A reference pair is
the grain: re-freezing the same version refreshes the policy row rather than
appending a second one, exactly as re-running the KS guard refreshes its row —
the two stores take the same stance because both are keyed by the thing they
measure, and a version frozen twice to different bytes is the one the latest
freeze wins, the row saying what was written.

**The store resolves its path lazily, and creates nothing at construction.**
The factory builds every registered component on every ``create_app()`` — in a
bare test process, in a factory scan, on paths with no reference pair to
freeze — so the component builder must construct this store without a complete
environment: an eager resolution that refused an unset ``DATABASE_URL`` would
take down composition for every unrelated feature in the workspace, which is
precisely the coupling the one-way factory dependency exists to prevent.  The
store resolves its path on first use, where the refusal is informative — a
nightly runner's entrypoint, a health check, the moment before a freeze is
allowed to continue.

**The store creates its tables idempotently, and refuses a policy it does not
hold.**  ``CREATE TABLE IF NOT EXISTS`` is the contract every store in this
workspace states, and the one the migration describes for its orchestrator: a
fresh database and an existing one take the same path, so no migration step is
needed here and running the migration over a database this store created changes
nothing.  But the *row* is never created here: the policy and the tree are facts
about a reference pair, and a store that wrote them onto a row it invented would
be inventing the pair the bytes belong to.  A freeze names the pair; the store
writes it.

**The recorded score is not written here.**  §12's "matches a recorded constant
to ``1e-12``" is feature 142's verb — the nightly replay computes the score and
compares it — and feature 143's ``1e-12`` tolerance and ``determinism_broken``
alert are the next feature's.  So ``recorded_score`` is left ``Nullable`` on
purpose, and a freshly frozen pair has not been replayed, so it has no constant
yet: the store fills it when the replay writes it, and a store that also decided
the comparison would be a threshold nobody could audit without changing what a
freeze means.  This feature *freezes*, the next one *replays and decides*, and a
store that also replayed would be a canary nobody could trust.

**The pair is never stored as rendered bytes, and the samples are never
logged.**  The tree carries canonical payloads, not the raw walk; the store row
carries the canonical bytes and the hash, and not one node id is logged.  See
:mod:`canary._reference` — the same rule stated where the bytes are frozen.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime``, ``json`` and
``urllib.parse``; no third-party import at module scope, so the factory's scan —
which imports this package to fire its ``@register`` — pays nothing for this
module.  That matters here more than usual: the member already defers nothing to
first use on the pin sweep, and a store that pulled a driver in at import would
undo the import-cheap contract the whole category holds.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ._reference import (
    CanaryPolicy,
    CanaryReferencePair,
    CanaryTree,
    CanaryTreeNode,
    canonical_json,
    content_hash,
)
from ._errors import CanaryError

__all__ = [
    "DATABASE_URL_ENV",
    "POLICY_TABLE",
    "REFERENCE_TABLE",
    "TREE_NODE_TABLE",
    "TREE_TABLE",
    "REFERENCE_STORE_COMPONENT_NAME",
    "CanaryReferenceStore",
    "CanaryReferenceStoreRecord",
    "build_reference_store",
    "freeze_reference_pair",
    "load_reference_pair",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the evaluator's
#: five, the repository-level conftest's), restated here so each store states
#: its own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the policy half lives in — the frozen ``π_canary``.
POLICY_TABLE = "canary_reference_policy"

#: The table the tree half's identity lives in — the frozen ``T_canary``.
TREE_TABLE = "canary_reference_tree"

#: The per-node rows — one row per node of the frozen tree.
TREE_NODE_TABLE = "canary_reference_tree_node"

#: The table that joins the two halves — one row per frozen reference pair.
REFERENCE_TABLE = "canary_reference"

#: ``canary_reference_policy``'s DDL as
#: ``migrations/versions/0119_canary_reference_pair.py`` spells it for SQLite,
#: restated rather than imported: a migration is loaded by path by its runner
#: and must not depend on a workspace package being importable in order to run,
#: and this store must not depend on the migration file being on ``sys.path`` in
#: order to open a database.  The two spellings are held together by the columns
#: they name, which is the thing they have to agree on — and
#: ``test_reference_store.py`` asserts the agreement against the migration's own
#: ``statements("sqlite")``.  Every declared *type* is spelled the migration's
#: way — SQLite applies its own affinity, so ``UUID``, ``TIMESTAMPTZ`` and
#: ``JSONB`` are as usable here as ``TEXT`` would be — so a database this store
#: creates is the database the migration would have created.
_POLICY_SCHEMA = f"""
-- Feature 141: the frozen canary policy half. `version` is the policy's name
-- (UNIQUE — two policies may not share one, or the store's own key would be
-- unreadable); `source` is the canonical JSON bytes the policy froze to;
-- `code_hash` is the sha256 over those bytes, the identity the nightly replay
-- checks the replayed policy against.  `created_at` orders freezes.
CREATE TABLE IF NOT EXISTS {POLICY_TABLE} (
    reference_id TEXT NOT NULL PRIMARY KEY,   -- the pair this policy half belongs to
    version      TEXT NOT NULL UNIQUE,
    source       TEXT NOT NULL,      -- canonical JSON bytes the policy froze to
    code_hash    CHAR(64) NOT NULL,  -- sha256 over source — the policy identity
    created_at   TEXT NOT NULL       -- the freeze instant (ISO-8601 UTC)
);
"""

#: ``canary_reference_tree``'s DDL.
_TREE_SCHEMA = f"""
-- Feature 141: the frozen canary tree half. `tree_hash` is the identity the
-- nightly replay checks the replayed tree against — sha256 over the sorted
-- nodes, so a tree and the same tree walked in another order are one hash.
-- `node_count` is a convenience a human reads; the hash is the thing a replay
-- keys on.  `created_at` orders freezes.
CREATE TABLE IF NOT EXISTS {TREE_TABLE} (
    reference_id TEXT NOT NULL PRIMARY KEY,   -- the pair this tree half belongs to
    tree_hash    CHAR(64) NOT NULL,  -- sha256 over the sorted nodes — the tree identity
    node_count   INT  NOT NULL,      -- how many nodes the frozen tree holds
    created_at   TEXT NOT NULL       -- the freeze instant (ISO-8601 UTC)
);
"""

#: ``canary_reference_tree_node``'s DDL.
_TREE_NODE_SCHEMA = f"""
-- Feature 141: the frozen tree's nodes, one row per node. `node_id` names the
-- node; `parent_id` its parent (NULL for a root); `depth` its level; `payload`
-- the canonical JSON bytes the node froze to.  Keyed by (reference_id, node_id)
-- so a re-freeze refreshes rather than appends, exactly as the tree row does.
CREATE TABLE IF NOT EXISTS {TREE_NODE_TABLE} (
    reference_id TEXT NOT NULL,      -- the pair this node belongs to
    node_id      TEXT NOT NULL,      -- the node's id within the tree
    parent_id    TEXT,               -- the parent node's id, or NULL for a root
    depth        INT  NOT NULL,      -- the node's level, zero at a root
    payload      TEXT NOT NULL,      -- canonical JSON bytes the node froze to
    PRIMARY KEY (reference_id, node_id)
);
"""

#: ``canary_reference``'s DDL — the join.
_REFERENCE_SCHEMA = f"""
-- Feature 141: the join between the policy half and the tree half. One row per
-- frozen reference pair: `recorded_score` is the constant the nightly replay
-- (feature 142) compares its score against, Nullable so a freshly frozen pair —
-- not yet replayed — stays distinguishable from a replayed one; `is_active`
-- marks the one pair the nightly canary replays.
CREATE TABLE IF NOT EXISTS {REFERENCE_TABLE} (
    reference_id   TEXT NOT NULL PRIMARY KEY,  -- the frozen pair's identity
    recorded_score REAL,             -- the constant the nightly replay compares against
    is_active      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TEXT NOT NULL     -- the freeze instant (ISO-8601 UTC)
);
"""

_POLICY_COLUMNS = "reference_id, version, source, code_hash, created_at"
_TREE_COLUMNS = "reference_id, tree_hash, node_count, created_at"
_TREE_NODE_COLUMNS = "reference_id, node_id, parent_id, depth, payload"
_REFERENCE_COLUMNS = "reference_id, recorded_score, is_active, created_at"


def _validated_reference_id(value: Any) -> str:
    """Validate a reference id, returning it in canonical UUID text.

    The same normalisation :func:`nulloracle.assignment.normalize_node_id` and
    :func:`ledger.record._validated_uuid` apply to an id that joins the tree
    store's ``node.id`` — and ``reference_id`` is the same kind of value, the
    identity of a row.  A malformed id is refused with :class:`~canary.CanaryError`
    rather than stored: an id that cannot be a row's key is a store-contract
    failure, and a caller reading ``CanaryImageError`` out of a reference store
    would look in the wrong module for the cause.
    """
    import uuid as _uuid

    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(_uuid.UUID(text))
            except ValueError:
                pass
    raise CanaryError(
        f"reference_id {value!r} is not a UUID: a reference pair is keyed by a "
        "row identity, and an id that cannot be a key names no pair this store "
        "could hold"
    )


def _utc_now() -> datetime:
    """The current instant, timezone-aware UTC — the freeze instant.

    Second resolution with microseconds dropped rather than rounded, the same
    spelling :func:`ledger.record.utc_now` and :mod:`nulloracle.ksguard` use: the
    stamp orders freezes against one another, and dropping — not rounding — keeps
    it never *after* the instant observed.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass(frozen=True)
class CanaryReferenceStoreRecord:
    """One frozen reference pair, as the store holds it.

    The pair (:class:`~canary.CanaryReferencePair`) plus the store's own metadata
    — the ``reference_id`` that joins the halves and the instant the store wrote.
    Frozen, and validated in :meth:`__post_init__` rather than only where it is
    built, because the read path reconstructs one from stored rows: a record whose
    pair does not reconstruct, or whose id is not a UUID, fails to reconstruct
    rather than loading as a plausible-looking reference.
    """

    #: The frozen pair — the policy and the tree together.
    pair: CanaryReferencePair
    #: The row identity that joins the policy half and the tree half.
    reference_id: str
    #: When the store wrote the pair.
    stored_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_id", _validated_reference_id(self.reference_id))
        if not isinstance(self.stored_at, datetime) or self.stored_at.tzinfo is None:
            raise CanaryError(
                "a reference store record must carry a timezone-aware stored_at: the "
                "stamp orders freezes against one another, and a naive one would raise "
                "far from the write that set it"
            )

    def to_payload(self) -> dict[str, Any]:
        """The record as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, so a stored row, a rendered mapping
        and a structured log record name the same things the same way — and the
        instant renders as the ISO-8601 text the table stores, so a round trip
        through this mapping and back is the same instant.
        """
        return {
            "reference_id": self.reference_id,
            "policy_version": self.pair.policy.version,
            "code_hash": self.pair.policy.code_hash,
            "tree_hash": self.pair.tree.tree_hash,
            "recorded_score": self.pair.recorded_score,
            "is_active": self.pair.is_active,
            "stored_at": self.stored_at.isoformat(),
        }


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.
    A non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a reference
    pair that vanished would leave the nightly canary replaying against nothing.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CanaryError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this store "
            "speaks sqlite:/// (the spec's single-machine allowance); point "
            f"{DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CanaryError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CanaryError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a frozen "
            "reference pair must outlive the freeze that produced it"
        )
    return Path(path)


class CanaryReferenceStore:
    """§12's frozen reference pair journal: the policy and tree written down.

    Constructed with the database URL it appends to; :meth:`freeze` writes a pair
    and its two halves, :meth:`load` reads one pair back.  The class resolves its
    path lazily, so constructing one performs no I/O — composition-time work must
    not touch the disk, the contract every store in this workspace states.

    The store holds no walk and no rendered bytes: it takes a frozen pair, writes
    the canonical bytes and the hashes, and lets the caller's mappings go out of
    scope with the call.  There is no field here that could drift from the frozen
    bytes, deliberately — see the module docstring and §12.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise CanaryError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["CanaryReferenceStore"]:
        """The reference store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        reference-store component — a discoverable state, not an exception —
        while the nightly runner that must freeze the pair is the caller that
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
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure all four tables exist, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` on every table, the contract every store
        in this workspace states and the one
        ``migrations/versions/0119_canary_reference_pair.py`` describes for its
        orchestrator: a fresh database and an existing one take the same path, so
        no migration step is needed here and running the migration over a database
        this store created changes nothing.  The caller owns the connection; use
        it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_REFERENCE_SCHEMA)
            connection.executescript(_POLICY_SCHEMA)
            connection.executescript(_TREE_SCHEMA)
            connection.executescript(_TREE_NODE_SCHEMA)
        return connection

    # -- Feature 141: the freeze --------------------------------------------

    def freeze(
        self,
        pair: CanaryReferencePair,
        *,
        reference_id: Optional[Any] = None,
        stored_at: Optional[datetime] = None,
    ) -> CanaryReferenceStoreRecord:
        """Persist a frozen reference pair and its two halves.

        The whole of feature 141 in one call: the policy half is written to
        ``canary_reference_policy``, the tree half to ``canary_reference_tree`` and
        its nodes to ``canary_reference_tree_node``, and the join row to
        ``canary_reference`` — all four in one transaction, keyed by one
        ``reference_id``.

        The write is idempotent by reference pair: re-freezing the same version
        refreshes the policy row rather than appending a second one — a version
        frozen twice is the latest freeze that wins, exactly as re-running the KS
        guard refreshes its row — and what the tables should hold is the latest
        pair and nothing else.

        Refuses, in this order, and each refusal names what it is about:

        1. a pair that is not a :class:`~canary.CanaryReferencePair`
           (:class:`~canary.CanaryError`) — the pair is the policy and the tree
           together, and a pair missing either froze only half of the reference;
        2. a write that could not be completed, in any of the four halves.

        ``recorded_score`` is **not** decided here.  §12's "matches a recorded
        constant to ``1e-12``" is feature 142's verb — the nightly replay computes
        the score and compares it — and this store writes only the ``recorded_score``
        the pair already carries, leaving it ``None`` for a pair not yet replayed.
        A store that also decided the comparison would be a threshold nobody could
        audit.

        ``stored_at`` defaults to the current UTC instant at second resolution; a
        caller replaying a recorded freeze supplies its own, so a restored pair
        stamps the instant the original froze.
        """
        if not isinstance(pair, CanaryReferencePair):
            raise CanaryError(
                "freeze takes a CanaryReferencePair — a policy and a tree together — "
                f"got {pair!r}; a reference pair is the two halves, and freezing one "
                "without the other froze only half of the reference"
            )
        identifier = (
            str(reference_id)
            if reference_id is not None
            else str(uuid.uuid4())
        )
        identifier = _validated_reference_id(identifier)
        instant = _utc_now() if stored_at is None else stored_at
        record = CanaryReferenceStoreRecord(
            pair=pair, reference_id=identifier, stored_at=instant
        )
        with closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    f"INSERT INTO {REFERENCE_TABLE} ({_REFERENCE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(reference_id) DO UPDATE SET "
                    "recorded_score = excluded.recorded_score, "
                    "is_active = excluded.is_active, created_at = excluded.created_at",
                    (
                        record.reference_id,
                        pair.recorded_score,
                        pair.is_active,
                        pair.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    f"INSERT INTO {POLICY_TABLE} ({_POLICY_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(reference_id) DO UPDATE SET "
                    "version = excluded.version, source = excluded.source, "
                    "code_hash = excluded.code_hash, created_at = excluded.created_at",
                    (
                        record.reference_id,
                        pair.policy.version,
                        pair.policy.source,
                        pair.policy.code_hash,
                        pair.policy.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    f"INSERT INTO {TREE_TABLE} ({_TREE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(reference_id) DO UPDATE SET "
                    "tree_hash = excluded.tree_hash, node_count = excluded.node_count, "
                    "created_at = excluded.created_at",
                    (
                        record.reference_id,
                        pair.tree.tree_hash,
                        len(pair.tree.nodes),
                        pair.created_at.isoformat(),
                    ),
                )
                connection.executemany(
                    f"INSERT OR REPLACE INTO {TREE_NODE_TABLE} ({_TREE_NODE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        (
                            record.reference_id,
                            node.node_id,
                            node.parent_id,
                            node.depth,
                            node.payload,
                        )
                        for node in pair.tree.nodes
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # A UNIQUE violation here is a policy whose version is already
                # frozen under a different pair: two policies may not share one
                # version, exactly as ``policy_revision.policy_version`` may not,
                # and a freeze that would create a second is refused rather than
                # left to a raw database error.
                raise CanaryError(
                    f"reference pair {record.reference_id!r} could not be frozen: "
                    f"{exc}; a frozen policy version is a name for one policy, and "
                    "two policies sharing one version would make the store's own "
                    "key unreadable"
                ) from exc
            stored = self._read_pair(connection, record.reference_id)
            if stored is None or not stored.has_same_content_as(pair):
                raise CanaryError(
                    f"reference pair {record.reference_id!r} was written half: the "
                    f"stored fingerprint {stored.content_fingerprint if stored else None!r} "
                    f"does not match the frozen {pair.content_fingerprint!r}; the pair "
                    "lives across four tables and a freeze whose halves disagree is "
                    "not a freeze"
                )
        return record

    # -- Feature 141: the read-back -----------------------------------------

    def load(self, reference_id: Any) -> CanaryReferenceStoreRecord:
        """Read one frozen reference pair back from the store.

        Reads the join row, the policy half and the tree half — and reconstructs
        the tree from its per-node rows — into one :class:`CanaryReferencePair`.
        The stored bytes re-derive their hashes through the value types' own
        validation, so a row edited outside this package fails to reconstruct
        instead of loading as a plausible-looking reference — the defence
        :func:`content_hash` states for a stored p-value, and the same reason it
        exists: the stored pair is what the nightly replay replays, and a store
        that could hand back bytes disagreeing with their own hash would launder a
        tamper.

        A reference id the store does not hold is refused by name: the pair is a
        fact about a reference, and a store that invented one would be inventing
        the pair the bytes belong to.
        """
        identifier = _validated_reference_id(reference_id)
        with closing(self._connect()) as connection, connection:
            pair = self._read_pair(connection, identifier)
            if pair is None:
                raise CanaryError(
                    f"reference pair {identifier!r} is not in the store: a reference "
                    "pair is a fact about a freeze, and reading one the store never "
                    "froze would invent the pair the bytes belong to"
                )
            return CanaryReferenceStoreRecord(
                pair=pair,
                reference_id=identifier,
                stored_at=datetime.fromisoformat(
                    self._read_stored_at(connection, identifier)
                ),
            )

    def _read_pair(
        self, connection: sqlite3.Connection, reference_id: str
    ) -> Optional[CanaryReferencePair]:
        """Reconstruct the pair for ``reference_id`` from the four tables.

        Returns ``None`` when the reference id names no join row — the caller
        decides whether that is a refusal or an absent state.  The policy and tree
        are rebuilt from their stored bytes through the value types' own
        constructors, so a row edited outside this package fails to reconstruct
        rather than loading as a plausible-looking reference.
        """
        ref_row = connection.execute(
            f"SELECT reference_id, recorded_score, is_active, created_at "
            f"FROM {REFERENCE_TABLE} WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()
        if ref_row is None:
            return None
        policy_row = connection.execute(
            f"SELECT version, source, code_hash, created_at FROM {POLICY_TABLE} "
            f"WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()
        tree_row = connection.execute(
            f"SELECT tree_hash, node_count, created_at FROM {TREE_TABLE} "
            f"WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()
        if policy_row is None or tree_row is None:
            raise CanaryError(
                f"reference pair {reference_id!r} is written half: the policy and "
                "tree halves must both be present, and a pair with only one is a "
                "freeze that froze only half of the reference"
            )
        policy = CanaryPolicy(
            version=policy_row[0],
            source=policy_row[1],
            code_hash=policy_row[2],
            created_at=datetime.fromisoformat(policy_row[3]),
        )
        node_rows = connection.execute(
            f"SELECT node_id, parent_id, depth, payload FROM {TREE_NODE_TABLE} "
            f"WHERE reference_id = ? ORDER BY node_id",
            (reference_id,),
        ).fetchall()
        tree = CanaryTree(
            nodes=tuple(
                CanaryTreeNode(
                    node_id=row[0],
                    parent_id=row[1],
                    depth=row[2],
                    payload=row[3],
                )
                for row in node_rows
            )
        )
        return CanaryReferencePair(
            policy=policy,
            tree=tree,
            recorded_score=ref_row[1],
            is_active=bool(ref_row[2]),
            id=ref_row[0],
            created_at=datetime.fromisoformat(ref_row[3]),
        )

    def _read_stored_at(
        self, connection: sqlite3.Connection, reference_id: str
    ) -> str:
        """The join row's ``created_at`` — the store's write instant."""
        row = connection.execute(
            f"SELECT created_at FROM {REFERENCE_TABLE} WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()
        if row is None:
            raise CanaryError(
                f"reference pair {reference_id!r} is not in the store"
            )
        return row[0]


def freeze_reference_pair(
    database_url: str, pair: CanaryReferencePair, **kwargs: Any
) -> CanaryReferenceStoreRecord:
    """The one-shot convenience: open the store and freeze a pair.

    Kept beside the class so a test and the factory freeze a pair the same way.
    A caller that wants the store resolved lazily uses
    :meth:`CanaryReferenceStore.resolve` — this function is the composition
    spelling, not the operator's.  A refused pair is not papered over either way:
    :class:`~canary.CanaryError` is the only failure this member has, and it
    propagates to the caller that asked for the freeze.
    """
    return CanaryReferenceStore(database_url).freeze(pair, **kwargs)


def load_reference_pair(database_url: str, reference_id: Any) -> CanaryReferenceStoreRecord:
    """The one-shot convenience: open the store and read a pair back.

    The read-side twin of :func:`freeze_reference_pair`, kept beside the class for
    the same reason.  A reference id the store does not hold is refused by name.
    """
    return CanaryReferenceStore(database_url).load(reference_id)


#: The component name the reference store registers under — the key a deployment
#: names when it asks the composed application for the frozen reference pair.
#: Deliberately a second name rather than a second component under
#: :data:`canary.CANARY_COMPONENT_NAME` (which the pin sweep registers): the pin
#: sweep and the reference store are different things on different lifecycles —
#: one asserts the deployment's pins, the other persists the frozen pair — and a
#: deployment configured for the pin but not the store composes one and not the
#: other.  Kept here as well as in the app module seat for the same reason the
#: member's seat spells its own :data:`COMPONENT_NAME` twice — so the two cannot
#: drift apart silently.
REFERENCE_STORE_COMPONENT_NAME = "canary-reference-store"


def build_reference_store(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[CanaryReferenceStore]:
    """Build the reference store the composed application carries.

    The one-shot convenience the component builder uses, kept beside the class so
    a test and the factory construct it the same way.  Deliberately resolves
    rather than strict: the factory builds this component on every
    ``create_app()``, so it must succeed without a ``DATABASE_URL`` and compose
    ``None`` where the deployment has no relational store — a discoverable state,
    not an exception — rather than taking composition down for every unrelated
    feature in the workspace.  A caller that wants the store pointed at a URL uses
    :class:`CanaryReferenceStore` — this function is the composition spelling, not
    the operator's.
    """
    return CanaryReferenceStore.resolve(env)
