"""The null-aware oracle — a node's root answers for its whole subtree.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 2:
*System creates a null-aware OracleResponse for any node of a campaign with
orchestrator._oracle.SubtreeOracle(endpoint, *, database_url).  This is a
callable evaluator Oracle, OracleRequest -> OracleResponse.*  The evaluator
declares the seam — :data:`evaluator.Oracle`, a callable taking an
``OracleRequest`` and returning an ``OracleResponse`` — and injects it into
pipeline step 5's ``gate_targets``; the nulloracle member owns the route
behind it (:class:`~nulloracle.target.TargetEndpoint`, ``POST /target``,
§7.2); and this module is the one object that joins them, exactly as
:mod:`orchestrator._tree_writer` joins the evaluator's writer protocol to
the tree's ``node`` table.

**A subtree is served from its root, because the null type is a campaign
property.**  §7.3 makes a campaign *homogeneous in null type*, and the
sidecar seals **one assignment per node** — but the discovery tree beneath a
campaign's root inherits the root's Type-R assignment by construction
(Type-R *inheritance*: the root's sealed branch covers everything refined
from it).  So an evaluation of a *child* node must be answered by the
assignment the **root** sealed, not by an assignment the child never had.
This object is the translation: it walks ``node.parent_id`` in the
``DATABASE_URL`` store from the requested node up to the row whose
``parent_id`` is ``NULL`` — the root — and posts that root's ``node_id`` to
the endpoint.  A child and its parent and its root therefore all ask the one
sealed assignment, which is the property a re-evaluation of a subtree needs
to be coherent.

**The depth stays the node's own, and that is what keeps the flip honest.**
The request is rebuilt as ``TargetRequest(node_id=<root id>, campaign_id,
depth=<the requested node's own depth>, horizon, symbols, date_range)``.  The
identity moves to the root — the ask must name a node the sidecar holds — but
the **depth does not**: the endpoint's Type-D rule decides the branch by
*the depth of the node being evaluated* (below ``flip_depth`` real, at or
beyond it permuted), so carrying the request's own depth is what makes a
child below the flip answer real while its root, at or above it, answers
permuted.  Substituting the root's depth here would silently move the flip
boundary and hand every deep refinement a real series — the one corruption
§7.3's flip-depth design exists to prevent.

**No node's null bit is read, and no sidecar key is imported.**  This module
holds no ``import nulloracle``: ``endpoint`` is duck-typed — it must have a
``post`` the oracle calls — precisely so the module states no dependency on
the member that owns the bit.  The only thing read from the store is
``parent_id``; the only thing carried back is the endpoint's own
``target_series`` and ``charges_budget``.  Null-ness reaches the evaluation
only as the series and the directive the route answers, never as a label
this module could inspect — the same barrier §7.2's response keeps.

**One refusal: :class:`OracleTargetError`, code word ``oracle_target``.**  A
non-OK status is the world saying *no assignment covers this node*, and it is
raised carrying the status and the endpoint's detail so a caller reads which
answer it got and why.  A node the tree does not hold, and a parent chain
longer than :data:`MAX_PARENT_CHAIN` links (a cycle or a corrupted spine), are
the same class: each is *this node cannot be resolved to a root*, which is the
only thing that stops the ask being made.  A wiring fault — a ``database_url``
this module cannot speak — is the base :class:`SubtreeOracleError`, separated
because it is a fact about how the object was built rather than about any one
node's place in the tree.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

__all__ = [
    "MAX_PARENT_CHAIN",
    "ORACLE_TARGET_CODE",
    "OracleTargetError",
    "SubtreeOracle",
    "SubtreeOracleError",
]

#: The environment variable naming the relational store — the one spelling the
#: workspace's stores share, restated here so this module states its own
#: contract rather than importing another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the tree lives in — migration ``0118``'s ``node`` table, the same
#: one :mod:`orchestrator._tree_writer` updates.
NODE_TABLE = "node"

#: The node's key column — ``0118``'s ``id``, the value ``parent_id`` points at.
NODE_ID_COLUMN = "id"

#: The self-referencing edge this module walks: ``0118``'s ``parent_id``, ``NULL``
#: exactly at a root.  It is the *only* column read from the store — the null
#: bit is not here to read, by the schema's own design.
PARENT_ID_COLUMN = "parent_id"

#: The greppable word that opens every :class:`OracleTargetError` message — the
#: spec's own spelling, so an operator greps one word for *the null oracle
#: could not answer for this node* and reaches every face of it (a non-OK
#: status, an absent row, a chain that never ends).
ORACLE_TARGET_CODE = "oracle_target"

#: The longest parent chain this walk will follow before refusing.  A tree of
#: realistic depth is dozens of links; ten thousand is far past any legitimate
#: spine and comfortably bounds the walk, so a `parent_id` cycle (or a store
#: whose edges were corrupted into one) is refused by name rather than looping
#: forever.  The limit is on *links walked*, not nodes visited: a root is zero
#: links, its child is one, and a chain of exactly this many links is still
#: resolved.
MAX_PARENT_CHAIN = 10000

#: The status a known node answers with, restated from §7.2 (`nulloracle.OK`)
#: rather than imported: this module speaks the route's *shape*, not the
#: member, so it holds no `import nulloracle` and states the one integer it
#: compares against.
_OK = 200

#: The migration that owns the ``node`` table, named in the refusal a database
#: the chain has not reached produces — because SQLite's own ``no such table:
#: node`` names the table but not the feature that creates it.
_NODE_MIGRATION = "migrations/versions/0118_node_table.py"


class SubtreeOracleError(Exception):
    """Base class for a wiring fault of the subtree oracle.

    A ``database_url`` this module cannot speak (a non-SQLite scheme, a host, a
    pathless in-memory URL), or an ``endpoint`` with no ``post`` to call.  These
    are facts about *how the oracle was built*, separated from
    :class:`OracleTargetError` — a fact about *one node's place in the tree* —
    so a caller divides "the wiring is wrong" from "no assignment covers this
    node" by class alone.
    """


class OracleTargetError(SubtreeOracleError):
    """The null oracle could not answer for the node — code word ``oracle_target``.

    Three faces, one repair — the ask cannot be made against a sealed
    assignment — and one code word (:data:`ORACLE_TARGET_CODE`):

    * **a non-OK status.**  The endpoint answered, and its status says no
      assignment covers the root this node resolves to.  ``status`` and
      ``detail`` carry the endpoint's own answer, so a caller reads the figure
      and the reason off the exception rather than parsing a message.

    * **an absent row.**  The walk reached a node id the tree does not hold —
      the requested node, or a ``parent_id`` pointing at a row that is gone.
      Either way there is no root to name, and a live evaluation never creates
      nodes (:mod:`orchestrator._tree_writer` makes the same argument), so a
      missing row is a refusal and not a row to invent.

    * **a chain longer than :data:`MAX_PARENT_CHAIN` links.**  The walk never
      reached a ``parent_id`` of ``NULL`` — a cycle, or a spine corrupted into
      one.  Bounded so the walk terminates and named so an operator sees the
      store is the fault, not the node.

    For the two tree faces ``status`` is ``None`` and ``detail`` is the same
    human-readable reason carried in the message; a caller that only handles
    the endpoint's answer can read ``status`` and treat ``None`` as *the tree,
    not the route, refused this one*.
    """

    def __init__(self, message: str, *, status: int | None = None,
                 detail: str | None = None) -> None:
        super().__init__(message)
        #: The endpoint's status when a non-OK answer raised this; ``None`` when
        #: the refusal came from the tree (an absent row or a runaway chain).
        self.status = status
        #: The endpoint's ``detail`` for a non-OK answer, or the same reason the
        #: message carries for a tree refusal.
        self.detail = detail


class SubtreeOracle:
    """The evaluator's ``Oracle`` over a subtree's root — ``OracleRequest`` in, ``OracleResponse`` out.

    Constructed with the endpoint it asks (duck-typed: anything with a
    ``post``) and the ``database_url`` of the tree it walks.  Construction
    performs no I/O — the path is resolved on first call — so composing an
    application that carries this oracle touches no disk.  Calling it is the
    whole contract: :meth:`__call__` walks the request's node to its root,
    posts the root's id with the node's own depth, and maps the endpoint's
    answer to the evaluator's response record.
    """

    def __init__(self, endpoint: Any, *, database_url: str) -> None:
        if endpoint is None or not callable(getattr(endpoint, "post", None)):
            raise SubtreeOracleError(
                "SubtreeOracle needs an endpoint with a callable post() — the "
                "null oracle's §7.2 route (nulloracle.TargetEndpoint) — got "
                f"{endpoint!r}; an oracle with no route names nothing to ask "
                "(additions_spec_live_evaluation.xml, feature 2)"
            )
        if not isinstance(database_url, str) or not database_url.strip():
            raise SubtreeOracleError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL naming "
                "the tree whose node rows this oracle walks to a root, got "
                f"{database_url!r}; an oracle with no tree cannot resolve any "
                "node's root (additions_spec_live_evaluation.xml, feature 2)"
            )
        self._endpoint = endpoint
        self._database_url = database_url.strip()
        self._path: Path | None = None
        self._resolved = False

    @property
    def database_url(self) -> str:
        """The URL this oracle was bound to."""
        return self._database_url

    @property
    def endpoint(self) -> Any:
        """The endpoint this oracle posts its root-target requests to."""
        return self._endpoint

    # -- Construction -------------------------------------------------------

    def _resolve_path(self) -> Path:
        """Resolve the ``sqlite:///`` path once, refusing schemes it cannot read.

        Deferred out of ``__init__`` so construction performs no I/O.  The
        grammar is the one every store in this workspace restates: a non-SQLite
        scheme is refused by name, a host is refused, and a pathless URL —
        SQLite's in-memory spelling — is refused because a tree must outlive the
        connection that walks it and a campaign's nodes are read across
        processes.
        """
        if self._resolved:
            assert self._path is not None
            return self._path
        parsed = urlparse(self._database_url)
        if parsed.scheme != "sqlite":
            raise SubtreeOracleError(
                f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
                "subtree oracle speaks sqlite:/// (the spec's single-machine "
                f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
                "the node table lives in (feature 2)"
            )
        if parsed.netloc not in ("", "localhost"):
            raise SubtreeOracleError(
                f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
                f"{parsed.netloc!r} (feature 2)"
            )
        path = unquote(parsed.path).removeprefix("/")
        if not path or path == ":memory:":
            raise SubtreeOracleError(
                f"sqlite {DATABASE_URL_ENV} carries no database path: an "
                "in-memory tree would die with the connection that opened it, "
                "and a node's root must outlive the evaluation that asked "
                "(feature 2)"
            )
        self._path = Path(path)
        self._resolved = True
        return self._path

    # -- The call -----------------------------------------------------------

    def __call__(self, request: Any) -> Any:
        """Answer one ``OracleRequest`` by asking the endpoint for the node's root.

        Walks ``request.node_id`` up ``node.parent_id`` to the row whose parent
        is ``NULL``, then posts a ``TargetRequest`` naming that root with
        ``request``'s own ``depth`` (and campaign, horizon, symbols and date
        range).  An ``OK`` answer maps to an ``OracleResponse`` carrying the
        endpoint's ``target_series`` and ``charges_budget``; anything else
        raises :class:`OracleTargetError` with the status and detail.

        An absent row and a chain longer than :data:`MAX_PARENT_CHAIN` raise
        :class:`OracleTargetError` before the endpoint is called, because there
        is no root id to post.  A ``database_url`` this module cannot speak is
        refused with :class:`SubtreeOracleError`, before the database is
        touched.
        """
        node_id = _requested_node_id(request)
        campaign_id = _requested_campaign_id(request)
        root_id = self._root_of(node_id)
        body = _target_request(request, root_id=root_id, campaign_id=campaign_id)
        response = self._endpoint.post(body)
        status = getattr(response, "status", None)
        if status != _OK:
            detail = getattr(response, "detail", None)
            raise OracleTargetError(
                f"{ORACLE_TARGET_CODE}: the null oracle answered status "
                f"{status!r} for root {root_id!r} (requested node {node_id!r}); "
                f"no sealed assignment covers this subtree — {detail or 'no detail given'}",
                status=status,
                detail=detail,
            )
        return _oracle_response(response)

    # -- Resolving the root -------------------------------------------------

    def _root_of(self, node_id: str) -> str:
        """Walk ``node.parent_id`` from ``node_id`` to the root, in one connection.

        The root is the row whose ``parent_id`` is ``NULL``; a root node is its
        own root (zero links).  Only ``parent_id`` is selected — never the null
        bit, which lives nowhere this table could hold it anyway.  A row the
        tree does not hold, and a chain exceeding :data:`MAX_PARENT_CHAIN`
        links, both raise :class:`OracleTargetError`.
        """
        path = self._resolve_path()
        hops = 0
        current = node_id
        with closing(sqlite3.connect(path)) as connection:
            while True:
                parent = _parent_of(connection, current)
                if parent is None:
                    # Either a root (parent_id NULL) or an absent row — the
                    # helper distinguishes them by raising on absence.
                    return current
                hops += 1
                if hops > MAX_PARENT_CHAIN:
                    raise OracleTargetError(
                        f"{ORACLE_TARGET_CODE}: node {node_id!r} has a parent "
                        f"chain longer than {MAX_PARENT_CHAIN} links and never "
                        "reaches a root (parent_id NULL); a cycle or a "
                        "corrupted spine in the tree at "
                        f"{self._database_url!r} is the fault, not the node "
                        "(feature 2)"
                    )
                current = parent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(endpoint={self._endpoint!r}, "
            f"database_url={self._database_url!r})"
        )


# -- Reading the request, structurally -----------------------------------------


def _requested_node_id(request: Any) -> str:
    """The node the request names, canonicalised; refused by name when absent."""
    value = getattr(request, "node_id", None)
    if not isinstance(value, str) or not value.strip():
        raise OracleTargetError(
            f"{ORACLE_TARGET_CODE}: the request must name the node it is for, "
            f"got node_id {value!r} on {type(request).__name__}; a request that "
            "names no node names no subtree to resolve (feature 2)"
        )
    return _canonical_node_id(value.strip())


def _requested_campaign_id(request: Any) -> str:
    """The campaign the request names, refused by name when absent."""
    value = getattr(request, "campaign_id", None)
    if not isinstance(value, str) or not value.strip():
        raise OracleTargetError(
            f"{ORACLE_TARGET_CODE}: the request must name the campaign it "
            f"belongs to, got campaign_id {value!r} on "
            f"{type(request).__name__}; the campaign is what the root's sealed "
            "assignment is scoped to (feature 2)"
        )
    return value.strip()


def _canonical_node_id(value: str) -> str:
    """Canonicalise a node id to the lowercase UUID text the tree stores.

    A UUID is answered as canonical lowercase text — because the value is
    compared against ``node.id`` and a mixed-case key would make one node look
    like two — and anything else is carried through stripped, to be refused as
    *no such row* by the walk rather than here: this module's one business is
    resolving a node to a root, and an id that names no node is exactly the
    absent-row refusal.
    """
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return value


def _target_request(request: Any, *, root_id: str, campaign_id: str) -> Any:
    """§7.2's ``TargetRequest`` for the root, at the requested node's own depth.

    Imports ``TargetRequest`` lazily, from the member that owns the route:
    this module holds no module-level ``import nulloracle`` so the composition
    scan pays nothing for an oracle that was never called, and the class is
    resolved only on the call path that genuinely needs to build the body.
    Every field but ``node_id`` is the request's own — the identity moves to
    the root, the *depth does not*, which is what keeps the endpoint's Type-D
    flip resolving on the node actually being evaluated.
    """
    from nulloracle.target import TargetRequest

    return TargetRequest(
        node_id=root_id,
        campaign_id=campaign_id,
        depth=request.depth,
        horizon=request.horizon,
        symbols=request.symbols,
        date_range=request.date_range,
    )


def _oracle_response(response: Any) -> Any:
    """The endpoint's OK answer as the evaluator's ``OracleResponse``.

    The series and the opaque directive are carried through untouched — this
    module interprets neither — and the record that holds them is imported
    lazily for the same reason ``TargetRequest`` is.
    """
    from evaluator import OracleResponse

    return OracleResponse(
        target_series=response.target_series,
        charges_budget=response.charges_budget,
    )


def _parent_of(connection: sqlite3.Connection, node_id: str) -> str | None:
    """One ``parent_id`` hop, or a raise when the store holds no such node.

    ``None`` is returned only for a *root* — a row that exists whose
    ``parent_id`` is ``NULL``.  An absent row is refused here rather than
    returned as ``None`` so the caller never mistakes "no row" for "root": the
    two are different facts and only one of them names a node to post.
    """
    try:
        row = connection.execute(
            f"SELECT {PARENT_ID_COLUMN} FROM {NODE_TABLE} "
            f"WHERE {NODE_ID_COLUMN} = ?",
            (node_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # `no such table: node` — the migration has not reached this database.
        # From the caller's view that is the same fact as an absent row: there
        # is no place in a tree for this node, so no root to name.
        if "no such table" not in str(exc).lower():
            raise OracleTargetError(
                f"{ORACLE_TARGET_CODE}: could not read node {node_id!r} from "
                f"the tree at {NODE_TABLE}: {exc} (feature 2)"
            ) from exc
        raise OracleTargetError(
            f"{ORACLE_TARGET_CODE}: the tree at this {DATABASE_URL_ENV} holds "
            f"no node {node_id!r} to resolve to a root — {_NODE_MIGRATION} "
            "must have created the node table, and a live evaluation never "
            "creates nodes (feature 2)"
        ) from exc
    except sqlite3.Error as exc:
        raise OracleTargetError(
            f"{ORACLE_TARGET_CODE}: could not read node {node_id!r} from the "
            f"tree at {NODE_TABLE}: {exc} (feature 2)"
        ) from exc
    if row is None:
        raise OracleTargetError(
            f"{ORACLE_TARGET_CODE}: the tree holds no node {node_id!r} to "
            "resolve to a root; a node's root is found by walking "
            "node.parent_id, and an id the tree does not hold names no row — "
            "and no row is not a root (feature 2)"
        )
    parent = row[0]
    if parent is None:
        return None
    return _canonical_node_id(parent if isinstance(parent, str) else str(parent))
