"""Resolving a Type-D request: real targets below the flip, permuted at or beyond — feature 121.

app_spec.xml, "Null Oracle & Planted Nulls", feature 121: *System resolves a
Type-D request by which returns real targets below the flip depth and permuted
targets at or beyond it.*  docs/nullius-tech-architecture.md §7.2 spells the
whole rule in one line — *"For Type-D campaigns the oracle resolves the flip
using ``depth``: below ``flip_depth`` the real targets are returned, at or
beyond it the permuted ones"* — and this module is that rule with a store
behind it: the request names a node, the node's depth and its branch's stored
flip depth are read back, and the branch the request lands on decides which
targets are served.

**The boundary, and why one comparison is the whole feature.**  The load-bearing
words in feature 121's sentence are **below** and **at or beyond**: the real
branch is *strictly* below the flip and the permuted branch is everything from
the flip down, so the entire resolution is the comparison
:func:`past_the_flip` spells — ``depth >= flip_depth`` means past the flip.  A
resolution that treated "at the flip" as real would serve real targets at the
one depth §7.3 says the branch turned null, and a resolution that treated
"beyond" as real would serve them everywhere; either would hand the caller real
signal inside a world that was planted to have none, and every calibration
number the campaign produced would be computed over a design that was never
applied.  The boundary errs nowhere: the node at exactly the flip depth is
null, because §7.3 draws the depth the branch flips *at*, not the depth it
flips *after*.

**The depth the resolution reads is the tree's, not the request's claim.**
§7.2's request carries a ``depth`` field beside ``node_id``, and the oracle
resolves on the depth the tree store holds for the node — feature 97's
``node.depth``, fixed when the discovery loop placed the node — rather than on
what the caller claims.  A request whose claimed depth disagrees with the row's
is refused by name: a caller asking for a node at a depth the tree does not
record is a request the oracle cannot serve coherently, and silently preferring
either value would let a request move itself across the flip.  The claim is
checked, not trusted and not ignored — the same read-back-rather-than-trust
discipline :mod:`nulloracle.verdict` applies to the p-value it voids on.

**The flip the resolution reads is the one feature 119 drew, inherited down.**
§7.3 draws ``flip_depth`` once per branch and the flip is *"silent and
irreversible: every descendant past ``flip_depth`` is null"*, so the resolution
walks the node's ancestor chain — ``parent_id`` by ``parent_id``, the node
itself included — and the branch's flip is the **shallowest** stored depth on
that chain.  Shallowest, because a flip past which the branch is already null
marks no transition: where one chain somehow carries several drawn depths (a
root's draw and an interior re-draw), the branch went null at the shallowest
one and the deeper draws are boundaries the walk never reaches.  The ordinary
world has exactly one — the draw on the branch's root, whose subtree is the
branch — and the shallowest of one is the one.  A chain that carries no drawn
flip at all is an **undrawn branch**, and it is refused rather than guessed:
serving the real targets would read as "no flip" while the campaign loop
believed it had drawn one, which is the exact quiet failure feature 119's
refusals exist to rule out.  The walk refuses a cycle and a dangling
``parent_id`` by name for the same reason — a branch whose chain cannot be
walked to its flip is a branch whose flip cannot be found, not a branch with
no flip.

**The campaign must be the type that has flips.**  §7.3: *"Campaigns are
homogeneous in null type"*, and the two regimes keep their null-ness in
different places — a Type-R node's null status lives in §7.1's sidecar,
inherited from its root; a Type-D node's lives in the depth rule this module
resolves.  So the store confirms the node's campaign exists and is a
``'Type-D'`` campaign before it resolves, and a campaign of any other type is
refused with the type named: resolving a Type-R node through the depth rule
would serve real targets to a subtree the sidecar holds null, the same
heterogeneous-world confusion feature 122 rejects at the planning gate.  The
read-side check is not that gate's substitute; it is this module declining to
answer a question of the wrong regime.

**The permutation is a seam, and the real series is never its own stand-in.**
§7.2's internal rule is *"if ``is_null``, return ``block_permute(
forward_returns, seed=perm_seed, block=20d)``; else return the real forward
returns"*, and the two halves of that ``if`` belong to two features: the
*which branch* is feature 121's (this module), the *block permutation* is
feature 115's, reproduced from the seed §7.1's sidecar stores.  So the
resolution takes the permutation as a callable — ``permute(targets)``, the
caller composing it from the sidecar's ``perm_seed`` and ``block_days`` — and
this module owns only the decision of which branch the request lands on.  What
it will not do is serve the permuted branch without one: a request past the
flip with no permutation supplied is refused by name, because serving the real
series there would be a real world wearing a null's name — the one failure
whose whole danger is that nothing downstream would look wrong.  The callable's
return is validated as a series of the **same length**: §7.2 promises *"the
caller cannot distinguish the two branches from the response"*, and a permuted
series of a different length would mark the branch as plainly as an
``is_null`` column would.

**What crosses the barrier, one more time.**  The value this module returns is
the oracle's own record — the series served, the depth and flip it was served
on, and which branch it was.  None of it is the sidecar's secret: ``depth`` and
``flip_depth`` are tree-store columns and the branch is derivable from them,
which is the Type-D regime's own design (the flip is *silent* to the agent
because the response does not carry it, not because the column is encrypted).
The response §7.2's endpoint builds from this value — features 112-113's
``{target_series, charges_budget}`` — carries the series and never the branch;
this module states that boundary so the endpoint does not have to re-derive it.

**Stdlib only, and import-cheap.**  ``sqlite3`` and ``urllib.parse``; no
third-party import at module scope, so the factory's scan — which imports this
package to fire its ``@register`` — pays nothing for this module, the same
discipline feature 117's, feature 119's and feature 124's stores state and for
the same reason: the member already defers ``cryptography`` to first use, and a
store that pulled a driver in at import would undo that.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import KsGuardError

__all__ = [
    "CAMPAIGN_TABLE",
    "DATABASE_URL_ENV",
    "FLIP_DEPTH_COLUMN",
    "NODE_TABLE",
    "TYPE_D_CAMPAIGN_TYPE",
    "TypeDOracle",
    "TypeDResolution",
    "past_the_flip",
    "resolve_type_d",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the fraction's, the flip depth's, the repository-level
#: conftest's), restated here so each store states its own contract and none
#: imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The tree store's node table — feature 97's, the table that carries every
#: node of the discovery tree with the ``depth`` and ``parent_id`` columns this
#: resolution walks.  Spelled once here, beside the walk that reads it, so the
#: resolution and the migration cannot drift apart on what the node table is
#: called.  The same spelling :mod:`nulloracle.flipdepth` states for the same
#: reason — both modules join the same rows.
NODE_TABLE = "node"

#: The campaign table — named so the store can confirm the node's campaign
#: exists and is a Type-D campaign before resolving.  Spelled once here, and
#: once in :mod:`nulloracle.phi`, :mod:`nulloracle.ksguard`,
#: :mod:`nulloracle.verdict` and :mod:`nulloracle.flipdepth`, so the six
#: writers and readers of the campaign row cannot drift apart on what the
#: campaign table is called.
CAMPAIGN_TABLE = "campaign"

#: The node column feature 119's draw landed on — the depth at which a branch's
#: subtree flips null.  The resolution reads it back rather than re-deriving
#: it, the same read-not-re-derive discipline every store in this member
#: applies to a fact a earlier feature fixed.
FLIP_DEPTH_COLUMN = "flip_depth"

#: The campaign type this resolution is for — §7.3's stopping-test regime, the
#: one whose null-ness is a depth rather than a root inheritance.  The value
#: ``migrations/versions/0111_campaign_table.py`` documents and the campaign's
#: planner writes; spelled once here so the gate and the refusal share one
#: spelling of the regime they require.
TYPE_D_CAMPAIGN_TYPE = "Type-D"


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``* — but re-raises its refusal as
    :class:`~nulloracle.errors.KsGuardError`, exactly as the flip-depth store
    does.  The distinction is the taxonomy's: a malformed id handed to the
    *resolution* is a store-contract failure, not a sidecar-schema one, and a
    caller reading ``SidecarError`` out of a Type-D request would look in the
    wrong module for the cause.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(
            f"node_id {value!r} is not a UUID: {exc}"
        ) from exc


def _validated_depth(value: Any, node: str) -> int:
    """Refuse a depth that is not a genuine non-negative integer.

    A node's depth is fixed when the discovery loop places it (§9.1: zero at a
    root, incrementing down each branch), and the resolution compares it
    against the flip — so a ``True``, a ``"3"`` or a ``-1`` in the column is a
    row no comparison could trust, refused with the node named rather than
    coerced into a depth nobody placed the node at.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KsGuardError(
            f"node {node!r} carries depth {value!r} "
            f"({type(value).__name__}); a node's depth is a non-negative "
            "integer fixed when the discovery loop placed it (§9.1), and a "
            "depth that is not one is a row the flip cannot be resolved "
            "against"
        )
    return value


def _validated_flip_depth(value: Any, node: str) -> int:
    """Refuse a stored flip depth that is not a genuine positive integer.

    Feature 119's draw is a geometric on the trial count, whose support is
    ``{1, 2, 3, …}`` precisely so that a root (depth 0) can never be the flip.
    A stored ``0`` or a truthy-looking ``True`` would break that invariant from
    the read side — turning a root null and retyping the campaign Type-R by
    corruption — so the resolution refuses it with the node named, the same
    refusal the flip-depth store states for the same value at the write.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KsGuardError(
            f"node {node!r} carries {FLIP_DEPTH_COLUMN} {value!r} "
            f"({type(value).__name__}); the Type-D flip depth is drawn from a "
            "geometric whose support is {1, 2, 3, …}, and a flip depth below 1 "
            "would turn a root null — retyping the campaign §7.3 holds all "
            "roots real in"
        )
    return value


def _validated_targets(value: Any) -> tuple[float, ...]:
    """Refuse a target series that is not a non-empty sequence of finite reals.

    §7.2's response serves ``target_series`` — the forward returns the request
    asked for — and the resolution's whole output is which series to serve, so
    a series that is not one serves no world: a bare string, a scalar, an
    empty request (no target days at all), or a ``None``/``nan`` that survived
    a caller's mean would be served as a resolution that reads as resolved.
    Refused with the type named, in the same discipline the KS test applies to
    its scores.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KsGuardError(
            f"targets must be a sequence of finite reals, got "
            f"{type(value).__name__} ({value!r}); §7.2's response serves "
            "target_series, and a value that is not a series is a request "
            "with nothing to resolve"
        )
    if len(value) == 0:
        raise KsGuardError(
            "targets is empty; a request that carries no target days serves "
            "no world, and an empty resolution would read as a resolved one"
        )
    for element in value:
        if isinstance(element, bool) or not isinstance(element, (int, float)):
            raise KsGuardError(
                f"targets must be finite reals, found {element!r} "
                f"({type(element).__name__}); a forward return is a real, and "
                "a value that is not one would be served to the caller as a "
                "target nobody measured"
            )
        number = float(element)
        if not math.isfinite(number):
            raise KsGuardError(
                f"targets must be finite reals, found {element!r}; a "
                "non-finite forward return would be served to the caller as a "
                "target nobody measured"
            )
    return tuple(float(element) for element in value)


def past_the_flip(depth: Any, flip_depth: Any) -> bool:
    """§7.2's Type-D boundary: whether ``depth`` sits at or beyond the flip.

    The whole of the resolution's decision in one comparison: ``depth <
    flip_depth`` is the real branch — *"below ``flip_depth`` the real targets
    are returned"* — and ``depth >= flip_depth`` is the permuted one — *"at or
    beyond it the permuted ones"*.  The comparison is inclusive of the flip
    because §7.3 draws the depth the branch flips **at**: the node at exactly
    ``flip_depth`` is the first null node of the branch, not the last real one.

    Because the flip's support starts at 1 (feature 119's geometric on the
    trial count), a root — depth 0 — is never past a drawn flip, which is
    *"every root stays real"* seen from the resolution side: the invariant is
    structural in the draw and re-checked in the read, so a corrupted ``0`` in
    the column cannot quietly retype a root.

    Refuses, and names what it refuses:

    * a ``depth`` that is not a genuine non-negative integer — the depth is
      the tree's own fact about the node, and a comparison against a value
      nobody placed the node at would resolve nothing;
    * a ``flip_depth`` that is not a genuine integer ``>= 1`` — the flip is
      the geometric's draw, whose support cannot produce anything else, and a
      flip below 1 would turn a root null.
    """
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise KsGuardError(
            f"depth must be a non-negative integer, got {type(depth).__name__} "
            f"({depth!r}); the Type-D flip is resolved against the depth the "
            "tree holds for the node (§7.2), and a depth that is not one is a "
            "depth nobody placed the node at"
        )
    if (
        isinstance(flip_depth, bool)
        or not isinstance(flip_depth, int)
        or flip_depth < 1
    ):
        raise KsGuardError(
            f"flip_depth must be an integer >= 1, got "
            f"{type(flip_depth).__name__} ({flip_depth!r}); the Type-D flip "
            "depth is drawn from a geometric whose support is {1, 2, 3, …} "
            "(§7.3), and a flip depth below 1 would turn a root null, which "
            "§7.3 forbids outright"
        )
    return depth >= flip_depth


class TypeDResolution:
    """The outcome of resolving one Type-D request — what was served, and why.

    Five fields, and together they are the whole record: ``node_id`` (the node
    the request named), ``depth`` (the depth the tree holds for it),
    ``flip_depth`` (the branch's effective flip the request was resolved
    against), ``real`` (genuine bool — which branch the request landed on) and
    ``targets`` (the series served: the caller's real series below the flip,
    the permutation's return at or beyond it).

    Frozen and validated in :meth:`__init__`, through ``object.__setattr__``
    with every other assignment refused, for the same reason
    :class:`~nulloracle.verdict.Verdict` is frozen: the resolution is the
    value the §7.2 endpoint builds its response from and a caller may log, and
    a resolution that could be edited into a different branch after the fact
    would be a mutable handle to a decision already served.  The one coherence
    check beyond field types mirrors the verdict's status/``voided`` check:
    ``real`` must agree with ``depth < flip_depth``, because a resolution that
    claims the real branch while sitting at or beyond the flip is a resolution
    that cannot explain itself.

    This value is the *oracle's* record, not the §7.2 response.  The endpoint
    that serves the agent carries ``target_series`` (and feature 113's
    ``charges_budget``) and never the branch — see the module docstring on
    which side of §4.2's barrier each field lives on.
    """

    __slots__ = ("_depth", "_flip_depth", "_node_id", "_real", "_targets")

    def __init__(
        self,
        *,
        node_id: Any,
        depth: Any,
        flip_depth: Any,
        real: Any,
        targets: Any,
    ) -> None:
        object.__setattr__(self, "_node_id", _validated_node_id(node_id))
        # The depth and the flip are validated with the node in hand so the
        # refusal can name the row they were read from.
        object.__setattr__(self, "_depth", _validated_depth(depth, node_id))
        object.__setattr__(
            self, "_flip_depth", _validated_flip_depth(flip_depth, node_id)
        )
        if not isinstance(real, bool):
            raise KsGuardError(
                f"real must be a genuine bool, got {type(real).__name__} "
                f"({real!r}); which branch a request landed on is one bit, "
                "and a truthy-looking non-bool is exactly the value that "
                "would silently serve the wrong world"
            )
        if real != (self._depth < self._flip_depth):
            raise KsGuardError(
                f"depth {self._depth!r}, flip_depth {self._flip_depth!r} and "
                f"real={real!r} disagree; below the flip the targets are real "
                "and at or beyond it permuted (§7.2), and a resolution that "
                "cannot explain itself is not one"
            )
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_targets", _validated_targets(targets))

    @property
    def node_id(self) -> str:
        """The node the request named, canonical UUID text."""
        return self._node_id

    @property
    def depth(self) -> int:
        """The depth the tree holds for the node — the depth resolved on."""
        return self._depth

    @property
    def flip_depth(self) -> int:
        """The branch's effective flip the request was resolved against."""
        return self._flip_depth

    @property
    def real(self) -> bool:
        """Whether the request landed below the flip — the real branch.

        ``True`` means the served targets are the caller's real series
        unchanged; ``False`` means the request sits at or beyond the flip and
        the served targets are the permutation's return.  Derivable from
        ``depth`` and ``flip_depth`` — stated as a field so a log line or a
        caller reads the branch without re-deriving the rule.
        """
        return self._real

    @property
    def targets(self) -> tuple[float, ...]:
        """The target series served: the real series below the flip, the permuted one at or beyond it."""
        return self._targets

    def to_payload(self) -> dict[str, Any]:
        """The resolution as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, the same discipline
        :meth:`nulloracle.assignment.NullAssignment.to_payload` states: a
        rendered mapping and a structured log record name the same things the
        same way.  This is the oracle-side record; the agent-facing §7.2
        response is built from it and carries the series, never the branch.
        """
        return {
            "node_id": self._node_id,
            "depth": self._depth,
            "flip_depth": self._flip_depth,
            "real": self._real,
            "targets": list(self._targets),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TypeDResolution):
            return NotImplemented
        return (
            self._node_id == other._node_id
            and self._depth == other._depth
            and self._flip_depth == other._flip_depth
            and self._real == other._real
            and self._targets == other._targets
        )

    def __repr__(self) -> str:
        branch = "real" if self._real else "permuted"
        return (
            f"{type(self).__name__}(node_id={self._node_id!r}, "
            f"depth={self._depth!r}, flip_depth={self._flip_depth!r}, "
            f"{branch}, {len(self._targets)} targets)"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        # Frozen: the resolution is what was served, and a handle that could
        # be edited into a different branch after the fact would be a mutable
        # handle to a decision already made.  The slots hold only the five
        # fields, all set in ``__init__`` via ``object.__setattr__``.
        raise AttributeError(
            f"{type(self).__name__} is frozen; a served resolution cannot be "
            "edited into a different branch"
        )


class TypeDOracle:
    """§7.2's Type-D resolution: the flip each branch carries, resolved per request.

    Constructed with the database URL it reads from; :meth:`resolve_request`
    reads the node's stored depth and its branch's stored flip depth (feature
    119's), and serves the real targets below the flip and the permuted ones
    at or beyond it.  The class resolves its path lazily, so constructing one
    performs no I/O — composition-time work must not touch the disk, the
    contract every store in this workspace states and the one feature 117's,
    feature 119's and feature 124's state for the same tables.

    The oracle holds no labels and no series of its own: it reads two integers
    off the tree the discovery loop built, compares them, and picks which of
    the caller's two series to serve.  The sidecar's ``is_null`` is never
    opened here — a Type-D node's branch is a fact of depths, not of the
    sidecar — so a process that is not the one service account can resolve
    Type-D requests, which is the design §7.2 describes: the flip is silent
    to the *agent*, not encrypted against the *oracle*.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # oracle is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> TypeDOracle | None:
        """The Type-D oracle ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no resolution component — a discoverable state, not an exception —
        while the endpoint that must serve §7.2's Type-D requests is the
        caller that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this oracle reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this oracle, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the node and campaign tables exist, idempotently.

        The same ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` dance
        :mod:`nulloracle.flipdepth` states, restated here rather than imported
        so each store owns its own contract: the node table is created with
        feature 97's five structural columns, the campaign table with feature
        104's own, and feature 119's ``flip_depth`` column is added by
        ``ALTER TABLE`` only when absent — so a fresh database, a
        migration-created one and a store-created one all end up the same
        schema and re-opening changes nothing.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    parent_id          UUID,
                    campaign_id        UUID NOT NULL,
                    theme_root         TEXT NOT NULL,
                    depth              INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {CAMPAIGN_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    campaign_type      TEXT NOT NULL,
                    workspace_count    INT NOT NULL,
                    null_fraction      REAL NOT NULL,
                    calibration_status TEXT NOT NULL DEFAULT 'ok',
                    ks_pvalue          REAL,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                """
            )
            has_column = any(
                row[1] == FLIP_DEPTH_COLUMN
                for row in connection.execute(f"PRAGMA table_info({NODE_TABLE})")
            )
            if not has_column:
                connection.execute(
                    f"ALTER TABLE {NODE_TABLE} ADD COLUMN {FLIP_DEPTH_COLUMN} INT"
                )
        return connection

    # -- Feature 121: the resolution ---------------------------------------

    def resolve_request(
        self,
        node_id: Any,
        targets: Any,
        *,
        permute: Callable[[Sequence[float]], Sequence[float]] | None = None,
        depth: Any = None,
    ) -> TypeDResolution:
        """Resolve one Type-D request: real targets below the flip, permuted at or beyond it.

        The whole of feature 121 in one call: the node is confirmed to exist
        and to belong to a ``'Type-D'`` campaign, the depth the tree holds for
        it is read back (and the request's own claimed ``depth`` — §7.2's
        request field — is checked against it when supplied), the branch's
        flip is found by walking the ancestor chain to the shallowest stored
        draw, and the branch the node lands on decides what is served: the
        caller's ``targets`` unchanged below the flip, or ``permute(targets)``
        at or beyond it.

        ``permute`` is §7.2's ``block_permute(forward_returns,
        seed=perm_seed, block=20d)`` — feature 115's mechanism, composed by
        the caller from the seed §7.1's sidecar stores — supplied as a seam
        because the *which branch* decision is this feature's and the
        *permutation* is not.  It is required exactly when the request lands
        at or beyond the flip, and its return is validated as a series of the
        same length: a different length would mark the branch as plainly as an
        ``is_null`` column would.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``node_id``, or a ``targets`` that is not a non-empty
           sequence of finite reals (:class:`~nulloracle.errors.KsGuardError`)
           — refused before the store is opened, so a refused request cannot
           leave a half behind;
        2. a node the table does not hold, or a campaign the campaign table
           does not hold, or a campaign whose type is not ``'Type-D'``
           (:class:`~nulloracle.errors.KsGuardError`) — the resolution is a
           fact about a node in a Type-D campaign, and resolving anything
           else would serve real targets to a branch whose null-ness lives
           elsewhere;
        3. a request whose claimed ``depth`` disagrees with the depth the tree
           holds (:class:`~nulloracle.errors.KsGuardError`) — §7.2's request
           carries the node's depth, and a disagreeing claim is a request the
           oracle cannot serve coherently;
        4. a branch no node of whose chain carries a drawn flip
           (:class:`~nulloracle.errors.KsGuardError`) — an undrawn branch
           cannot be resolved, and serving the real targets would read as "no
           flip" while the campaign loop believed it had drawn one;
        5. a request at or beyond the flip with no callable ``permute``
           supplied (:class:`~nulloracle.errors.KsGuardError`) — serving the
           real series there would be a real world wearing a null's name;
        6. a permutation whose return is not a series of finite reals of the
           same length (:class:`~nulloracle.errors.KsGuardError`).
        """
        node = _validated_node_id(node_id)
        series = _validated_targets(targets)
        with closing(self._connect()) as connection:
            row = self._read_node(connection, node)
            campaign_id, stored_depth, own_flip, parent_id = row
            self._require_type_d_campaign(connection, node, campaign_id)
            depth_value = _validated_depth(stored_depth, node)
            if depth is not None:
                claimed = _validated_request_depth(depth)
                if claimed != depth_value:
                    raise KsGuardError(
                        f"the request claims depth {claimed!r} for node "
                        f"{node!r} but the tree holds {depth_value!r}; §7.2's "
                        "request carries the node's depth, and a claim that "
                        "disagrees with the tree is a request the oracle "
                        "cannot serve coherently — it would let a request move "
                        "itself across the flip"
                    )
            flips = self._branch_flips(connection, node, own_flip, parent_id)
            if not flips:
                raise KsGuardError(
                    f"no {FLIP_DEPTH_COLUMN} is drawn anywhere on node "
                    f"{node!r}'s branch; §7.3's flip is drawn once per branch "
                    "before the branch is walked, and a request against an "
                    "undrawn branch cannot be resolved — serving the real "
                    "targets would read as 'no flip' while the campaign loop "
                    "believed it had drawn one"
                )
            # The branch's effective flip is the shallowest draw on the chain:
            # past a flip is past, irreversibly, so a deeper draw on a chain
            # that already flipped marks no transition.
            effective = min(flips)
            real = depth_value < effective
            if real:
                served = series
            else:
                if permute is None:
                    raise KsGuardError(
                        f"node {node!r} sits at depth {depth_value!r}, at or "
                        f"beyond its branch's flip depth {effective!r}, and no "
                        "permute was supplied; §7.2 serves the permuted branch "
                        "through block_permute(forward_returns, "
                        "seed=perm_seed, block=20d), and serving the real "
                        "series there would hand the caller real signal inside "
                        "a world planted to have none — the exact failure the "
                        "null oracle exists to prevent"
                    )
                if not callable(permute):
                    raise KsGuardError(
                        f"permute must be callable, got "
                        f"{type(permute).__name__} ({permute!r}); §7.2 serves "
                        "the permuted branch through block_permute, and a "
                        "value the oracle cannot call serves no permuted "
                        "series"
                    )
                served = _validated_targets(permute(series))
                if len(served) != len(series):
                    raise KsGuardError(
                        f"the permutation returned {len(served)} targets for "
                        f"{len(series)} real ones; §7.2 promises the caller "
                        "cannot distinguish the two branches from the "
                        "response, and a permuted series of a different "
                        "length would mark the branch as plainly as an "
                        "is_null column would"
                    )
        return TypeDResolution(
            node_id=node,
            depth=depth_value,
            flip_depth=effective,
            real=real,
            targets=served,
        )

    def _read_node(
        self, connection: sqlite3.Connection, node: str
    ) -> tuple[Any, Any, Any, Any]:
        """The node row's campaign, depth, own flip and parent, read once.

        The four facts the resolution needs from the node itself: which
        campaign it belongs to (the Type-D gate reads it), the depth it sits
        at (the boundary reads it), its own stored flip (the root's draw lives
        on the node itself, so the chain walk starts with it) and its parent
        (the walk's next step).  A node the table does not hold is refused
        with the same spelling the flip-depth store uses, because it is the
        same fact: the row is created by the discovery loop, before any
        request could name it.
        """
        cursor = connection.execute(
            f"SELECT campaign_id, depth, {FLIP_DEPTH_COLUMN}, parent_id "
            f"FROM {NODE_TABLE} WHERE id = ?",
            (node,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"the node table holds no row for {node!r}; §7.2's Type-D "
                "resolution answers for a node the discovery loop placed, and "
                "a request that cannot be joined to its node row is refused "
                "rather than resolved against a node this store would have to "
                "invent"
            )
        return row

    def _require_type_d_campaign(
        self, connection: sqlite3.Connection, node: str, campaign_id: Any
    ) -> None:
        """Refuse a node whose campaign is missing or not a Type-D campaign, by name.

        §7.3: campaigns are homogeneous in null type, and the two regimes keep
        their null-ness in different places — a Type-R node's in §7.1's
        sidecar, a Type-D node's in the depth rule this module resolves.  A
        resolution that ran the depth rule over a Type-R node would serve real
        targets to a subtree the sidecar holds null, so the campaign is
        confirmed to exist and to be ``'Type-D'`` before anything is served.
        The check is a read, not a create: the campaign is created by its
        planner, before any node is expanded.
        """
        if campaign_id is None:
            raise KsGuardError(
                f"node {node!r} names no campaign; §7.2's Type-D resolution "
                "is a fact about a node in a campaign, and a request whose "
                "node belongs to no campaign is a request that hangs off "
                "nothing"
            )
        campaign = _validated_node_id(campaign_id)
        cursor = connection.execute(
            f"SELECT campaign_type FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}, the "
                f"campaign node {node!r} belongs to; §7.2's Type-D resolution "
                "is a fact about a node in a campaign, and a request that "
                "cannot be joined to the campaign its node belongs to is "
                "refused rather than resolved against a campaign this store "
                "would have to invent"
            )
        found = row[0]
        if found != TYPE_D_CAMPAIGN_TYPE:
            raise KsGuardError(
                f"campaign {campaign!r} is a {found!r} campaign; §7.2's flip "
                f"resolution is the {TYPE_D_CAMPAIGN_TYPE!r} regime (§7.3: "
                "campaigns are homogeneous in null type), and resolving a "
                f"{found!r} node by depth would serve real targets to a "
                "branch whose null-ness lives in the sidecar, not in a flip"
            )

    def _branch_flips(
        self,
        connection: sqlite3.Connection,
        node: str,
        own_flip: Any,
        parent_id: Any,
    ) -> list[int]:
        """Every drawn flip depth on the node's ancestor-or-self chain.

        Walks ``parent_id`` upward from the node itself — the branch's flip is
        drawn on one of its nodes (§7.3 draws it on the branch's root) and
        inherited by every descendant past it, so the chain, not the node
        alone, is where the flip is found.  Each stored flip is validated as a
        genuine positive integer on the way past, so a corrupted ``0`` cannot
        quietly retype a root; the caller takes ``min`` of the result, because
        the branch's effective flip is the shallowest draw — past a flip is
        past, irreversibly.

        Two corruptions of the chain itself are refused by name rather than
        walked into: a parent edge that revisits a node (a cycle — a branch
        whose flip can never be found by walking), and a parent the table does
        not hold (a missing link in the same walk).
        """
        flips: list[int] = []
        if own_flip is not None:
            flips.append(_validated_flip_depth(own_flip, node))
        seen = {node}
        current = _validated_parent_id(parent_id, node) if parent_id is not None else None
        while current is not None:
            if current in seen:
                raise KsGuardError(
                    f"node {node!r}'s ancestor chain revisits {current!r}; a "
                    "tree whose parent edges form a cycle is a branch whose "
                    "flip cannot be found by walking, and the walk refuses "
                    "rather than loop"
                )
            seen.add(current)
            cursor = connection.execute(
                f"SELECT {FLIP_DEPTH_COLUMN}, parent_id FROM {NODE_TABLE} "
                "WHERE id = ?",
                (current,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None:
                raise KsGuardError(
                    f"node {node!r}'s ancestor {current!r} is not held by the "
                    "node table; a branch with a missing link cannot be "
                    "walked to its flip, and a flip that cannot be found is "
                    "not a flip that was drawn"
                )
            flip_raw, parent_raw = row
            if flip_raw is not None:
                flips.append(_validated_flip_depth(flip_raw, current))
            current = (
                _validated_parent_id(parent_raw, current)
                if parent_raw is not None
                else None
            )
        return flips


def _validated_request_depth(value: Any) -> int:
    """Validate the §7.2 request's claimed ``depth`` field.

    The same kind of value the tree stores — a non-negative integer, refused
    rather than coerced — with its own spelling because the refusal is about
    the *request*, not the row: a claimed depth that is not a genuine depth
    is a malformed request whatever the row holds.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KsGuardError(
            f"depth must be a non-negative integer, got {type(value).__name__} "
            f"({value!r}); §7.2's request carries the node's depth, and a "
            "claim that is not a genuine depth is a request the oracle cannot "
            "check against the tree"
        )
    return value


def _validated_parent_id(value: Any, child: str) -> str:
    """Validate a parent edge, returning it in canonical UUID text.

    A ``parent_id`` that is not a UUID is a corrupt edge, not a walkable one,
    and the refusal names the child whose edge it is — the row that read it —
    so the operator reading it knows which insert went wrong.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(
            f"node {child!r} carries parent_id {value!r}, which is not a "
            f"UUID: {exc}; the ancestor walk follows parent edges to the "
            "branch's flip, and an edge that cannot be followed is a branch "
            "whose flip cannot be found"
        ) from exc


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.  A
    non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a request
    resolved against one would be a resolution no replay could reproduce.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a Type-D resolution read from one would be a resolution "
            "no replay could reproduce"
        )
    return Path(path)


def resolve_type_d(
    node_id: Any,
    targets: Any,
    *,
    permute: Callable[[Sequence[float]], Sequence[float]] | None = None,
    depth: Any = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> TypeDResolution | None:
    """Resolve one Type-D request, opening its own store — a single spelling.

    Feature 121's sentence as one call: the store is resolved from
    ``database_url``, else from ``DATABASE_URL``, and the request is resolved
    against it.  A deployment that names neither answers ``None`` — the same
    "no store, no resolution" answer :meth:`TypeDOracle.resolve` gives for an
    unconfigured deployment, kept distinct because a caller that mistook an
    unconfigured deployment for an unresolved request would serve nothing
    while believing it had resolved a world.

    A :class:`~nulloracle.errors.KsGuardError` from the store is left to
    propagate unwrapped; see the taxonomy for why "the request could not be
    resolved" is a store-contract failure and shares the flip-depth store's
    error.
    """
    if database_url is None:
        source = os.environ if env is None else env
        database_url = source.get(DATABASE_URL_ENV, "").strip()
        if not database_url:
            return None
    return TypeDOracle(database_url).resolve_request(
        node_id, targets, permute=permute, depth=depth
    )
