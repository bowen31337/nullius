"""Oracles, trees and evolved structures — feature 161's quarantine law.

app_spec.xml, "Untrusted Code Sandbox", feature 161: *System quarantines a node
together with its subtree after a seccomp violation, persisting a
``sandbox_escape`` fail class.*  §15's failure table states the whole feature in
one row — *"Sandbox escape attempt | seccomp violation | Kill, record
``fail_class``, quarantine the node and its subtree"* — and §9.1's ``fail_class``
column is the vocabulary the recorded half is read against.

The sentence decomposes into three claims, and this module is one object per
claim.

**"after a seccomp violation."**  The trigger is feature 160's event and nothing
else.  A :class:`~sandbox.syscalls.SyscallDecision` publishes a
:class:`~sandbox.syscalls.Commitment` on its
:attr:`~sandbox.syscalls.SyscallDecision.violation` when a process inside the box
reached for a syscall the configured ceiling does not admit, and the commitment's
:attr:`~sandbox.syscalls.Commitment.fail_class` is §15's ``sandbox_escape``
restated as data.  That value is the only thing this law quarantines for.  A
timeout, a crash, a tripwire verdict, an ``errno``-action rejection that let the
process carry on, and the ``None`` of a call the gate could not read as a syscall
are all *refused or passed over*, each for the reason its own section below
gives.

**"quarantines a node together with its subtree."**  The subject is a branch of
the discovery tree, not one row.  :class:`NodeTree` reads the caller's
``(id, parent_id, campaign_id)`` rows — feature 97's ``node`` table, whose five
structural columns migration ``0118_node_table`` declares — and
:meth:`NodeTree.subtree` closes over ``parent_id`` from the violating node to
every descendant, scoped to the one campaign the node's own row names.
:class:`Quarantine` is that closure as a value: which nodes are halted, how deep
the branch runs, and the one record that says why.

**"persisting a ``sandbox_escape`` fail class."**  :meth:`Quarantine.mark`
writes the class onto the *failing node's own* fail-class field and the
quarantine instant onto *every* node of the branch, all-or-nothing across the
whole subtree.  ``sandbox_escape`` is deliberately not one of §9.1's four —
``ok | timeout | error | tripwire_fail`` — so the persisted value is the class
§15 names while feature 168's
:data:`~sandbox.failclass.FAIL_CLASS_TABLE` remains the single place that
translates it under ``error``.  Two laws, two writes, no second translation.

The walk is iterative and the cycle is named
--------------------------------------------

:meth:`NodeTree.subtree` walks the closure in Python over the edges it was
handed, with an explicit ancestry set, and refuses a ``parent_id`` chain that
closes on itself.  This is not caution — it is the one choice the shape forces.
A ``UNION ALL`` recursion over a cyclic ``parent_id`` never terminates: the tree
does not *fail* to resolve, it *hangs*, and a guard written above the query never
runs because control never comes back.  So a closure walked in SQL cannot produce
the refusal below, and a law whose whole job is to halt a branch safely cannot be
one that stops responding on a malformed tree.  The closure this member walks is
bounded by the rows the caller hands in, which is why the refusal is a
:class:`~sandbox.errors.QuarantineTreeError` a caller can act on rather than a
timeout nobody can attribute.

What this law does not do
-------------------------

**It opens no database.**  The member's one-provenance rule is that the box
untrusted code is put inside must not depend on anything handed to it, so this
module is stdlib-only, imports no sibling workspace member, and reads no
environment.  The caller fetches the node rows and hands them in as a
:class:`NodeTree`; the caller owns the store, the transaction and the commit.
The same division :mod:`sandbox.seed` and :mod:`sandbox.timeout` draw for the
run they are handed.

**It does not decide that a violation happened.**  Feature 160's gate decides
that, at the filter, and publishes it.  This law reads the class off the
commitment and answers the branch question; a caller that wanted the gate's
answer has :meth:`sandbox.syscalls.SyscallDecision.require`.

**It does not run the sandbox.**  Nothing here spawns, filters or kills.  §15's
row lists a kill before the quarantine, and the kill belongs to the launcher that
armed the filter — by the time this law has a commitment to read, the process is
already gone.

**It answers rather than raises.**  :func:`quarantine_violation` returns a
:class:`QuarantineDecision` naming both the class it found and the class §15
requires, and the raise lives on :meth:`QuarantineDecision.require`.  §6.1 runs
the sandbox unattended over thousands of candidates; a law that killed the run on
its tenth candidate would take the run with it, and halting a branch is the most
consequential thing this member does, so the refusal is available to the caller
rather than forced on it.

See :class:`~sandbox.errors.SandboxQuarantineError` for the contract and
:class:`~sandbox.errors.QuarantineTreeError` for the malformed-tree refusal.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Iterable, Mapping
from typing import Any, Final

from .errors import (
    QuarantineTreeError,
    SandboxEscapeQuarantine,
    SandboxQuarantineError,
)

__all__ = [
    "NODE_QUARANTINED_COLUMN",
    "QUARANTINE_COLUMNS",
    "QUARANTINE_COMPONENT_NAME",
    "QUARANTINE_FAIL_CLASS",
    "QUARANTINE_MISMATCH_CODE",
    "QUARANTINE_REQUIRED_CODE",
    "QUARANTINE_TABLE",
    "QUARANTINE_TREE_CODE",
    "NodeTree",
    "Quarantine",
    "QuarantineDecision",
    "QuarantineReason",
    "QuarantineRecord",
    "SandboxQuarantine",
    "quarantine_violation",
    "quarantines",
    "sandbox_quarantine",
]

QUARANTINE_COMPONENT_NAME: Final[str] = "sandbox-quarantine"
"""This law's component name — what :func:`sandbox.build_sandbox_quarantine` registers.

Distinct from every sibling's, because the module loader's registry is keyed by
name and a later registration of the same name *replaces* the earlier one: two
laws sharing a name would leave one of them silently absent from a composed
application.  The seat :mod:`app.modules.sandbox` reads the same spelling.
"""

QUARANTINE_FAIL_CLASS: Final[str] = "sandbox_escape"
"""§15's class for a seccomp violation — feature 160's ``VIOLATION_CLASS``.

Restated as data rather than imported, the member's one-provenance rule: this
module names the class it persists without reaching into a sibling's namespace
for the spelling.  Deliberately not one of §9.1's four — see
:data:`~sandbox.failclass.FAIL_CLASS_TABLE` for the one place it is translated.
"""

QUARANTINE_REQUIRED_CODE: Final[str] = "quarantine_required"
"""Greppable code for a subject that is not a seccomp violation of the right class."""

QUARANTINE_MISMATCH_CODE: Final[str] = "quarantine_mismatch"
"""Greppable code for a branch the caller could not supply records for."""

QUARANTINE_TREE_CODE: Final[str] = "quarantine_tree_invalid"
"""Greppable code for rows that could not be read as one campaign's tree."""

QUARANTINE_TABLE: Final[str] = "sandbox_quarantine"
"""The store shape this law's records are written as.

Not a migration this member owns — the caller owns the store, and feature 97's
``node`` table is the tree this law reads.  The name is here so an operator and a
query builder spell the quarantine ledger once, the discipline
:data:`sandbox.seed.NODE_SEED_TABLE` and :data:`sandbox.budget.BUDGET_TABLE`
apply to theirs.
"""

QUARANTINE_COLUMNS: Final[tuple[str, ...]] = (
    "node_id",
    "root_node_id",
    "campaign_id",
    "subtree_depth",
    "fail_class",
    "syscall",
    "action",
    "component",
    "quarantined_at",
)
"""The columns of :data:`QUARANTINE_TABLE`, in declaration order — the read side.

``root_node_id`` is the node the violation was attributed to, so a branch of many
rows still names the one node §15's recovery column acts on; ``subtree_depth`` is
that node's distance below the root, so an operator can tell a leaf-level escape
from one at the campaign's entry point without re-walking the tree.
"""

NODE_QUARANTINED_COLUMN: Final[str] = "quarantined_at"
"""The field :meth:`Quarantine.mark` writes on every node of the branch.

One column for the whole branch rather than a flag beside the class: the class
belongs to the node that violated and the mark belongs to every node that was
halted because of it, and a caller reading a node row to ask *is this node still
being evaluated?* should find the answer in one place.
"""


def _require_str(value: object, *, what: str) -> str:
    """Read ``value`` as a non-empty string, or refuse."""
    if not isinstance(value, str) or not value.strip():
        raise QuarantineTreeError(
            f"{QUARANTINE_TREE_CODE}: {what} must be a non-empty string, "
            f"got {value!r} ({type(value).__name__}). The tree this law closes "
            f"over is identified by node and campaign ids, and a node whose id "
            f"this law cannot read is one it cannot mark or refuse by name "
            f"(feature 161)."
        )
    return value.strip()


def _require_mapping(row: object, *, what: str) -> Mapping[str, Any]:
    """Read ``row`` as a mapping, or refuse."""
    if not isinstance(row, Mapping):
        raise QuarantineTreeError(
            f"{QUARANTINE_TREE_CODE}: {what} must be a mapping of node columns, "
            f"got {type(row).__name__}. Rows arrive from a caller's fetch — a "
            f"§9.1 node row, a sqlite3.Row, a dict — and this law reads them by "
            f"name rather than by position so a schema change is a refusal here "
            f"and not a silently wrong branch elsewhere (feature 161)."
        )
    return row


def _row_field(row: Mapping[str, Any], name: str) -> Any:
    """``row[name]`` if present, else ``None`` — a missing column reads absent."""
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def _row_node_id(row: Mapping[str, Any], *, what: str) -> str:
    """The node id of one row, refusing a row that does not carry one."""
    return _require_str(_row_field(row, "id"), what=f"{what}'s id")


def _validated_instant(value: object, *, what: str) -> str:
    """Read ``value`` as one carrier for a quarantine instant, or refuse.

    Accepts a :class:`datetime.datetime`, a date, or the ISO text a store round
    trips, and answers the canonical ISO spelling.  Naive instants are kept
    naive: this law owns no clock policy and converting one would invent an
    offset the caller never wrote.
    """
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            dt.datetime.fromisoformat(text)
        except ValueError as exc:
            raise QuarantineTreeError(
                f"{QUARANTINE_TREE_CODE}: {what} {text!r} is not an ISO-8601 "
                f"instant ({exc}). A quarantine row is a durable halt, and a "
                f"timestamp no reader can parse is one no audit can order "
                f"(feature 161)."
            ) from exc
        return text
    raise QuarantineTreeError(
        f"{QUARANTINE_TREE_CODE}: {what} must be a datetime, a date or an "
        f"ISO-8601 string, got {value!r} ({type(value).__name__}) (feature 161)."
    )


def _now() -> dt.datetime:
    """This process's clock, in UTC — the instant a fresh quarantine is stamped.

    Called once per :func:`quarantine_violation` and never on a replay, so a
    re-run of a quarantine reports the original instant rather than moving the
    halt forward — see :meth:`Quarantine.mark`.
    """
    return dt.datetime.now(dt.UTC)


class NodeTree:
    """One campaign's discovery tree, as the caller fetched it.

    Feature 97's ``node`` table carries five structural columns — ``id``,
    ``parent_id`` (self-referencing, ``NULL`` at a root), ``campaign_id``,
    ``theme_root`` and ``depth`` — and this class reads the three this law
    needs.  It is built from rows rather than from a connection, so a caller owns
    the store, the transaction and the commit, and this member stays stdlib-only
    and opens no database.

    **The campaign scope comes from the node, never from a parameter.**  Every
    walk is confined to the campaign the failing node's *own* row names, so a
    caller cannot halt a branch in a campaign it did not mean to, and a tree that
    happens to hold two campaigns' rows cannot leak one into the other's closure.
    :meth:`subtree` states the consequence: a descendant that is reachable by
    ``parent_id`` but sits in a different campaign is not in the branch.

    **Two rows for one node must agree.**  A caller that hands in the same id
    twice — a join that fanned out, a fetch that overlapped a page — gets a
    refusal if the rows disagree on parent or campaign, and a quiet dedupe if
    they do not.  Reading one of two contradictory edges would make the closure
    depend on row order, which is a branch halted on a fetch accident.
    """

    __slots__ = ("_campaign_of", "_children", "_parent_of", "_rows")

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._parent_of: dict[str, str | None] = {}
        self._campaign_of: dict[str, str] = {}
        self._children: dict[str, list[str]] = {}
        self._rows: dict[str, Mapping[str, Any]] = {}
        for index, raw in enumerate(rows):
            row = _require_mapping(raw, what=f"the node row at position {index}")
            node_id = _row_node_id(row, what=f"the node row at position {index}")
            parent = _row_field(row, "parent_id")
            if parent is not None and not isinstance(parent, str):
                raise QuarantineTreeError(
                    f"{QUARANTINE_TREE_CODE}: node {node_id!r} names a "
                    f"parent_id of {parent!r} ({type(parent).__name__}), which is "
                    f"neither NULL nor a node id. A parent this law cannot read "
                    f"as an id is one it cannot close over, and guessing the "
                    f"branch would halt the wrong nodes (feature 161)."
                )
            parent = None if parent is None or not parent.strip() else parent.strip()
            campaign = _require_str(
                _row_field(row, "campaign_id"), what=f"node {node_id!r}'s campaign_id"
            )
            if node_id in self._parent_of:
                if self._parent_of[node_id] != parent or self._campaign_of[node_id] != campaign:
                    raise QuarantineTreeError(
                        f"{QUARANTINE_TREE_CODE}: node {node_id!r} arrived twice "
                        f"with disagreeing rows — "
                        f"parent_id {self._parent_of[node_id]!r} vs {parent!r}, "
                        f"campaign_id {self._campaign_of[node_id]!r} vs "
                        f"{campaign!r}. Which edge this law read would then "
                        f"depend on the caller's row order, and a branch halted "
                        f"on a fetch accident is worse than one not halted "
                        f"(feature 161)."
                    )
                continue
            self._parent_of[node_id] = parent
            self._campaign_of[node_id] = campaign
            self._rows[node_id] = row
            self._children.setdefault(node_id, [])
            if parent is not None:
                self._children.setdefault(parent, []).append(node_id)
            if parent is not None and parent not in self._parent_of:
                # A child may name a parent the caller did not hand in. The edge
                # is kept so the closure can still refuse to walk past it; see
                # `subtree`.
                self._children.setdefault(parent, [])

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> NodeTree:
        """``NodeTree(rows)`` spelled as a classmethod, for a chained caller."""
        return cls(rows)

    @property
    def size(self) -> int:
        """How many nodes the caller handed in."""
        return len(self._parent_of)

    def node_ids(self) -> tuple[str, ...]:
        """Every node id, in the caller's arrival order.

        Arrival order rather than sorted: the caller fetched these rows, and
        re-ordering them here would hide a fetch that returned two campaigns or
        two pages overlapping.
        """
        return tuple(self._parent_of)

    def campaigns(self) -> tuple[str, ...]:
        """Every campaign id present, deduped, in arrival order — the read side."""
        seen: dict[str, None] = {}
        for campaign in self._campaign_of.values():
            seen.setdefault(campaign, None)
        return tuple(seen)

    def holds(self, node_id: object) -> bool:
        """Whether ``node_id`` is a node the caller handed in.

        The predicate :func:`quarantine_violation` uses to refuse an unknown
        node, exposed so a caller can ask the same question before it builds a
        subject — the reading :meth:`sandbox.budget.BudgetBreach.row`'s callers
        get from the budget law's own accessors.
        """
        return isinstance(node_id, str) and node_id in self._parent_of

    def campaign_of(self, node_id: str) -> str:
        """The campaign ``node_id`` belongs to, or a refusal if it is not here."""
        if node_id not in self._campaign_of:
            raise QuarantineTreeError(
                f"{QUARANTINE_TREE_CODE}: node {node_id!r} is not in the tree this "
                f"caller handed in ({self.size} node(s) from "
                f"{len(self.campaigns())} campaign(s)). The tree is a snapshot of "
                f"what the caller fetched, so a node absent from it is one this "
                f"law cannot scope or mark (feature 161)."
            )
        return self._campaign_of[node_id]

    def parent_of(self, node_id: str) -> str | None:
        """``node_id``'s parent, ``None`` at a root — the one edge this law reads."""
        if node_id not in self._parent_of:
            raise QuarantineTreeError(
                f"{QUARANTINE_TREE_CODE}: node {node_id!r} is not in the tree this "
                f"caller handed in, so it has no parent to read (feature 161)."
            )
        return self._parent_of[node_id]

    def subtree(self, node_id: str) -> tuple[str, ...]:
        """``node_id`` and every descendant of it, within one campaign.

        The closure is walked iteratively with an explicit stack and an ancestry
        set: the root first, then each child, depth-first, stopping at a child
        whose campaign differs from the root's.  The result is in pre-order so an
        operator reads a branch the way it is drawn, and it is a tuple so a
        caller cannot mutate a decision after the fact.

        **A ``parent_id`` chain that closes on itself is refused, and it is
        refused here rather than in SQL for a reason.**  A ``UNION ALL``
        recursion over a cycle never terminates — the query does not fail, it
        hangs — so a closure walked in the database cannot produce this refusal
        at all: the guard never runs, because control never comes back.  Walking
        the edges in Python bounds the work by the rows the caller handed in,
        which is what makes a malformed tree a
        :class:`~sandbox.errors.QuarantineTreeError` an operator can act on.

        A cycle is not only "a node that is its own ancestor".  Two nodes that
        name each other, and a longer ring, are the same fault and are caught by
        the same set: the moment a node is reached that is already on the current
        path from the root, the tree has no well-defined subtree and every
        closure from it is a guess.
        """
        if node_id not in self._parent_of:
            raise QuarantineTreeError(
                f"{QUARANTINE_TREE_CODE}: node {node_id!r} is not in the tree this "
                f"caller handed in ({self.size} node(s) from "
                f"{len(self.campaigns())} campaign(s)), so there is no subtree to "
                f"close over. Quarantining on a node the caller did not fetch "
                f"would halt an unknowable set of rows (feature 161)."
            )
        campaign = self._campaign_of[node_id]
        order: list[str] = []
        on_path: set[str] = set()
        # (node, entering) — entering False means the node's children are done
        # and it comes off the current path. An explicit stack rather than
        # recursion: a deep discovery tree is data, not a stack budget, and a
        # RecursionError is not a refusal an operator can act on.
        stack: list[tuple[str, bool]] = [(node_id, True)]
        while stack:
            current, entering = stack.pop()
            if not entering:
                on_path.discard(current)
                continue
            if current in on_path:
                raise QuarantineTreeError(
                    f"{QUARANTINE_TREE_CODE}: the parent_id chain reached node "
                    f"{current!r} twice while closing over {node_id!r}, so this "
                    f"tree has a cycle and {node_id!r} has no well-defined "
                    f"subtree. A node cannot be its own ancestor, and every "
                    f"closure from a ring is a guess about which rows to halt — "
                    f"refused rather than guessed, because §15 quarantines a "
                    f"branch and a branch that contains itself is not one "
                    f"(feature 161)."
                )
            if self._campaign_of.get(current) != campaign:
                # Reachable by parent_id but not this campaign's: the fetch
                # crossed a boundary, and a branch never crosses one.
                continue
            on_path.add(current)
            order.append(current)
            stack.append((current, False))
            for child in reversed(self._children.get(current, ())):
                stack.append((child, True))
        return tuple(order)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"NodeTree(size={self.size}, "
            f"campaigns={len(self.campaigns())})"
        )


class QuarantineReason(enum.StrEnum):
    """Why a subject was quarantined, or why it was not.

    StrEnum rather than a bare ``str`` so a caller's ``==`` against the member's
    spelling compares by value while a :class:`QuarantineDecision` still prints
    as the word it means — the discipline
    :class:`sandbox.syscalls.SyscallReason` and
    :class:`sandbox.failclass.FailClassReason` follow for their own verdicts.
    """

    QUARANTINED = "quarantined"
    """The subject is a ``sandbox_escape`` violation and its branch is halted."""

    NOTHING_TO_QUARANTINE = "nothing_to_quarantine"
    """There is no violation to act on, so the run continues.

    Feature 160's gate publishes ``None`` on an attempt it could not read as a
    syscall at all, and documents that such an attempt is deliberately *not*
    called an escape attempt: a name no filter could match is a caller's
    mistake, not a process reaching outside its box.  So this reason is not a
    refusal — nothing is raised, nothing is marked, and the branch is untouched.
    """

    FOREIGN_CLASS = "foreign_class"
    """The subject names a class §15's recovery column does not belong to.

    A timeout, an ``error``, a tripwire verdict, or an ``errno``-action rejection
    that let the process keep running.  Each has its own owner — feature 163's
    clock, feature 168's vocabulary, the tripwires' store — and each records
    itself on its own terms.  Quarantining a branch for one of them would halt a
    subtree for a failure no ceiling was ever compared against.
    """

    UNREADABLE_VIOLATION = "unreadable_violation"
    """The subject is not something this law can read as a violation at all."""

    UNKNOWN_NODE = "unknown_node"
    """The violation names a node the caller's tree does not contain."""

    CYCLIC_TREE = "cyclic_tree"
    """The parent_id chain from the node closes on itself, so there is no branch."""


class Quarantine:
    """One halted branch: which nodes, how deep, and the record that says why.

    The value :func:`quarantine_violation` answers with when the trigger is a
    genuine ``sandbox_escape`` violation.  It names the node §15's row acts on
    (:attr:`root`), the campaign that bounds the closure, every node the halt
    covers, and the class that caused it — so *why is this node no longer being
    evaluated?* is answerable from the decision rather than from a log line that
    has since rotated.

    **The class is persisted on the failing node only; the mark lands on
    every node.**  That asymmetry is the feature, not an implementation detail.
    §15 says to *record* a ``fail_class`` and to *quarantine* a subtree; a
    descendant that never called anything did not fail, and writing
    ``sandbox_escape`` onto its fail-class field would make it report a violation
    of its own that it never committed.  What every node of the branch shares is
    the *halt*, which is what :data:`NODE_QUARANTINED_COLUMN` records.
    """

    __slots__ = ("_depth_of", "_nodes", "_root", "_violation")

    def __init__(
        self,
        *,
        root: str,
        nodes: tuple[str, ...],
        depth_of: Mapping[str, int],
        violation: Mapping[str, Any],
    ) -> None:
        self._root = root
        self._nodes = nodes
        self._depth_of = dict(depth_of)
        self._violation = dict(violation)

    @property
    def root(self) -> str:
        """The node the violation was attributed to — §15's "the node"."""
        return self._root

    @property
    def nodes(self) -> tuple[str, ...]:
        """Every node the halt covers, the root first, in pre-order."""
        return self._nodes

    @property
    def size(self) -> int:
        """How many nodes are halted — the branch's width."""
        return len(self._nodes)

    @property
    def descendants(self) -> tuple[str, ...]:
        """The halted nodes *other than* the root — the subtree half of the claim."""
        return self._nodes[1:]

    @property
    def fail_class(self) -> str:
        """§15's class for this halt — ``sandbox_escape``."""
        return QUARANTINE_FAIL_CLASS

    @property
    def campaign_id(self) -> str:
        """The campaign the halt is confined to."""
        return str(self._violation["campaign_id"])

    @property
    def syscall(self) -> str:
        """The syscall the process reached for — feature 160's ``describe()`` half."""
        return str(self._violation.get("syscall", ""))

    @property
    def action(self) -> str:
        """The action the filter reached for it — ``kill`` for §15's row."""
        return str(self._violation.get("action", ""))

    @property
    def component(self) -> str:
        """The component the attempt named, when it named one."""
        return str(self._violation.get("component", ""))

    def depth_of(self, node_id: str) -> int:
        """How far below *this branch's root* ``node_id`` sits; 0 at the root.

        Measured from the violating node rather than from the campaign's tree
        root, because the question an operator asks of a quarantine row is how
        much of the branch the escape retired — a leaf-level violation halts one
        node and an entry-point violation halts the campaign.
        """
        return self._depth_of[node_id]

    def describe(self) -> str:
        """``openat → kill · sandbox_escape · 3 nodes from 1f2e…`` — one line.

        The operator phrase, built from feature 160's own
        :meth:`~sandbox.syscalls.Commitment.describe` for the attempt half so the
        two laws spell one event one way.
        """
        attempt = f"{self.syscall} → {self.action}" if self.syscall else "seccomp violation"
        return (
            f"{attempt} · {self.fail_class} · {self.size} node(s) from "
            f"{self._root} in {self.campaign_id}"
        )

    def rows(self, *, quarantined_at: object) -> tuple[dict[str, Any], ...]:
        """One :data:`QUARANTINE_TABLE` row per halted node, in branch order.

        Every row carries the branch's full identity — root, campaign, class and
        the attempt — so a single row read alone still answers *why*, and
        ``subtree_depth`` distinguishes the root (``0``) from what it took down
        with it.  Fresh dicts per call, never shared ones: the copy-then-hand
        discipline :meth:`sandbox.budget.BudgetBreach.row` and
        :meth:`sandbox.timeout.TimeoutKill.row` apply to their own shapes.
        """
        stamp = _validated_instant(quarantined_at, what="quarantined_at")
        out: list[dict[str, Any]] = []
        for node_id in self._nodes:
            out.append(
                {
                    "node_id": node_id,
                    "root_node_id": self._root,
                    "campaign_id": self.campaign_id,
                    "subtree_depth": self._depth_of[node_id],
                    "fail_class": self.fail_class,
                    "syscall": self.syscall,
                    "action": self.action,
                    "component": self.component,
                    "quarantined_at": stamp,
                }
            )
        return tuple(out)

    def mark(
        self,
        records: Mapping[str, Any],
        *,
        quarantined_at: object = None,
    ) -> tuple[dict[str, Any], ...]:
        """Write the halt into ``records``, all-or-nothing, and answer what was written.

        ``records`` maps a node id to the mapping a caller holds for it — a §9.1
        node row, a record already carrying a ``fail_class`` from feature 168, a
        dict a caller is about to commit.  For **every** node of the branch the
        mark (:data:`NODE_QUARANTINED_COLUMN`) is written; for **only the root**
        the class is written too.

        **All-or-nothing across the branch.**  Every halted node must have a
        record *before* anything is written, so a caller that fetched a partial
        page gets a ``quarantine_mismatch`` refusal with an empty tree rather
        than a half-halted branch.  A subtree whose root is halted and whose
        child is not is a state nothing in this member can produce, and a store
        left in it would read as a child still being evaluated under a parent
        that is not.

        **A re-run keeps the original instant.**  A node already carrying a mark
        is not re-stamped: the returned row reports the instant already there and
        ``replayed`` is ``True``, so replaying a violation on a branch that is
        already halted is an idempotent read rather than a second event.  This is
        the discipline :mod:`sandbox.timeout` applies to a re-recorded timeout —
        an event that happened once keeps the time it happened.

        Returns one written row per node, :data:`QUARANTINE_COLUMNS`-folded, in
        branch order.  The mark never overwrites a *different* quarantined
        instant: two instants on one node means two violations reached it, and
        silently keeping one would lose the earlier halt.
        """
        missing = [node for node in self._nodes if node not in records]
        if missing:
            raise SandboxEscapeQuarantine(
                f"{QUARANTINE_MISMATCH_CODE}: the quarantine covers "
                f"{self.size} node(s) from {self._root!r}, and this caller holds "
                f"no record for {len(missing)} of them: "
                f"{', '.join(repr(node) for node in missing[:4])}"
                f"{'…' if len(missing) > 4 else ''}. The write is all-or-nothing "
                f"because a branch whose root is halted and whose child is not is "
                f"a state that reads as a child still being evaluated under a "
                f"parent that is not — nothing in this member can produce it, so "
                f"refused rather than half-written (feature 161)."
            )
        stamp = _validated_instant(
            _now() if quarantined_at is None else quarantined_at,
            what="quarantined_at",
        )
        written: list[dict[str, Any]] = []
        held = _held_instant(records[self._root])
        effective = held if held is not None else stamp
        for node_id in self._nodes:
            record = _require_mapping(
                records[node_id], what=f"the record this caller holds for {node_id!r}"
            )
            existing = _held_instant(record)
            if existing is not None and existing != effective:
                raise SandboxEscapeQuarantine(
                    f"{QUARANTINE_MISMATCH_CODE}: node {node_id!r} is already "
                    f"quarantined at {existing!r}, and this halt is being "
                    f"recorded at {effective!r}. Two instants on one node mean "
                    f"two violations reached it, and keeping one silently would "
                    f"lose the earlier halt — refused rather than re-stamped "
                    f"(feature 161)."
                )
            node_stamp = existing if existing is not None else stamp
            _write(record, NODE_QUARANTINED_COLUMN, node_stamp)
            if node_id == self._root:
                _write_fail_class(record, self.fail_class)
            written.append(
                {
                    "node_id": node_id,
                    "root_node_id": self._root,
                    "campaign_id": self.campaign_id,
                    "subtree_depth": self._depth_of[node_id],
                    "fail_class": self.fail_class if node_id == self._root else _existing_class(record),
                    "syscall": self.syscall,
                    "action": self.action,
                    "component": self.component,
                    "quarantined_at": node_stamp,
                }
            )
        return tuple(written)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Quarantine(root={self._root!r}, size={self.size}, "
            f"campaign_id={self.campaign_id!r})"
        )


def _held_instant(record: object) -> str | None:
    """The quarantine instant ``record`` already carries, or ``None``."""
    if not isinstance(record, Mapping):
        return None
    value = _row_field(record, NODE_QUARANTINED_COLUMN)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return _validated_instant(value, what=NODE_QUARANTINED_COLUMN)
    except QuarantineTreeError:
        # An unparseable mark is treated as absent rather than as a refusal:
        # this law is being asked to *write* a mark, and a row whose existing
        # text no reader can parse is repaired by writing one, not by refusing.
        return None


def _write(record: Mapping[str, Any], name: str, value: Any) -> None:
    """Write ``record[name] = value``, refusing a record this law cannot write to."""
    try:
        record[name] = value  # type: ignore[index]
    except TypeError as exc:
        raise SandboxEscapeQuarantine(
            f"{QUARANTINE_MISMATCH_CODE}: the record held for this node is a "
            f"{type(record).__name__}, which cannot take the {name!r} mark. This "
            f"law writes into the mappings a caller hands it — a dict a caller is "
            f"about to commit, a mutable row — and a record it cannot write to "
            f"would leave a node halted in this decision and not in the store "
            f"(feature 161)."
        ) from exc


_FAIL_CLASS_FIELDS: Final[tuple[str, ...]] = ("fail_class", "outcome", "terminal_class")
"""Where a node row keeps its class, in the order this law looks.

Feature 163's :mod:`sandbox.timeout` and feature 168's :mod:`sandbox.failclass`
each look for the same three spellings for the reason they give: a caller's row
may carry the class under any of them, and a law that looked under only one would
write a second class field beside the first.
"""


def _existing_class(record: object) -> str:
    """The class ``record`` carries under any of :data:`_FAIL_CLASS_FIELDS`."""
    if not isinstance(record, Mapping):
        return ""
    for name in _FAIL_CLASS_FIELDS:
        value = _row_field(record, name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _write_fail_class(record: Mapping[str, Any], fail_class: str) -> None:
    """Write ``fail_class`` onto the field the record already uses, or ``fail_class``.

    **A different existing class is never overwritten.**  A node whose row already
    names ``timeout`` is one feature 163 recorded, and this law replacing it with
    ``sandbox_escape`` would translate one failure into another — the restraint
    :meth:`sandbox.timeout.SandboxTimeout.timed_out_record` documents for its own
    write.  Only an absent or already-``sandbox_escape`` field is written.
    """
    for name in _FAIL_CLASS_FIELDS:
        value = _row_field(record, name)
        if isinstance(value, str) and value.strip():
            if value.strip() != fail_class:
                return
            _write(record, name, fail_class)
            return
    _write(record, "fail_class", fail_class)


class QuarantineRecord:
    """One ``sandbox_escape`` quarantine, as the row a store keeps.

    Built from a :class:`Quarantine` so a caller that wants the single ledger row
    rather than the per-node spread has one shape to write, and so the fields a
    reader queries by — the node, the campaign, the class, the syscall — are
    named once here rather than spelled at each call site.
    """

    __slots__ = ("action", "campaign_id", "component", "fail_class", "node_id", "quarantined_at", "root_node_id", "subtree_depth", "subtree_size", "syscall")

    def __init__(
        self,
        *,
        node_id: str,
        root_node_id: str,
        campaign_id: str,
        subtree_depth: int,
        subtree_size: int,
        fail_class: str,
        syscall: str,
        action: str,
        component: str,
        quarantined_at: str,
    ) -> None:
        self.node_id = node_id
        self.root_node_id = root_node_id
        self.campaign_id = campaign_id
        self.subtree_depth = subtree_depth
        self.subtree_size = subtree_size
        self.fail_class = fail_class
        self.syscall = syscall
        self.action = action
        self.component = component
        self.quarantined_at = quarantined_at

    @classmethod
    def of(cls, quarantine: Quarantine, *, quarantined_at: object) -> QuarantineRecord:
        """The ledger row for ``quarantine`` — one row for the whole branch.

        :attr:`subtree_size` is carried beside :attr:`subtree_depth` so the row
        answers *how much was retired* as well as *how far below the root*, which
        a per-node spread cannot answer from any one of its rows.
        """
        return cls(
            node_id=quarantine.root,
            root_node_id=quarantine.root,
            campaign_id=quarantine.campaign_id,
            subtree_depth=quarantine.depth_of(quarantine.root),
            subtree_size=quarantine.size,
            fail_class=quarantine.fail_class,
            syscall=quarantine.syscall,
            action=quarantine.action,
            component=quarantine.component,
            quarantined_at=_validated_instant(quarantined_at, what="quarantined_at"),
        )

    def row(self) -> dict[str, Any]:
        """This record as one store-shaped mapping, fresh per call."""
        return {
            "node_id": self.node_id,
            "root_node_id": self.root_node_id,
            "campaign_id": self.campaign_id,
            "subtree_depth": self.subtree_depth,
            "subtree_size": self.subtree_size,
            "fail_class": self.fail_class,
            "syscall": self.syscall,
            "action": self.action,
            "component": self.component,
            "quarantined_at": self.quarantined_at,
        }

    def describe(self) -> str:
        """``1f2e… halted with 2 descendant(s): openat → kill · sandbox_escape``."""
        return (
            f"{self.node_id} halted with {max(self.subtree_size - 1, 0)} "
            f"descendant(s): {self.syscall} → {self.action} · {self.fail_class}"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"QuarantineRecord(node_id={self.node_id!r}, "
            f"fail_class={self.fail_class!r}, size={self.subtree_size})"
        )


class QuarantineDecision:
    """The answer to *is this branch halted?* — with the reason either way.

    The shape :func:`quarantine_violation` returns and the machine-readable half
    of the law: :attr:`quarantined` is ``True`` only for a genuine
    ``sandbox_escape`` violation whose branch closed cleanly, :attr:`reason` names
    the case, and :attr:`quarantine` carries the branch when there is one.  A
    caller that wants the halt to be fatal calls :meth:`require`; a caller running
    the unattended loop §6.1 describes reads the three attributes.
    """

    __slots__ = ("detail", "quarantine", "reason")

    def __init__(
        self,
        *,
        reason: QuarantineReason,
        detail: str = "",
        quarantine: Quarantine | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.quarantine = quarantine

    @property
    def quarantined(self) -> bool:
        """Whether a branch was halted."""
        return self.quarantine is not None

    @property
    def refused(self) -> bool:
        """Whether the subject was refused rather than passed over.

        Distinct from ``not quarantined``: feature 160's unreadable attempt comes
        back as :data:`QuarantineReason.NOTHING_TO_QUARANTINE`, which is the run
        continuing rather than a caller being told it did something wrong.
        """
        return self.reason in (
            QuarantineReason.FOREIGN_CLASS,
            QuarantineReason.UNREADABLE_VIOLATION,
            QuarantineReason.UNKNOWN_NODE,
            QuarantineReason.CYCLIC_TREE,
        )

    def require(self) -> Quarantine:
        """Return the quarantine, or raise — the launcher's verb.

        Raises :class:`~sandbox.errors.SandboxEscapeQuarantine` for every refusal
        **and** for the pass-through, because a caller that called ``require`` has
        said it needs a branch: the two cases where no branch exists are told
        apart by the code the message begins with, not by the class.
        """
        if self.quarantine is not None:
            return self.quarantine
        raise SandboxEscapeQuarantine(
            f"{QUARANTINE_REQUIRED_CODE}: no branch was quarantined — "
            f"{self.reason.value}. {self.detail}".strip()
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        if self.quarantine is not None:
            return f"QuarantineDecision(quarantined, size={self.quarantine.size})"
        return f"QuarantineDecision({self.reason.value})"


_VIOLATION_ATTRIBUTE: Final[str] = "violation"
"""Where feature 160's :class:`~sandbox.syscalls.SyscallDecision` keeps its commitment."""

_VIOLATION_FIELDS: Final[tuple[str, ...]] = ("fail_class", "syscall", "action")
"""The three fields a commitment must carry for this law to call it one."""


def _subject_violation(subject: object) -> object:
    """The violation ``subject`` carries, or ``None`` when it carries none at all.

    Accepts feature 160's decision (by its ``violation`` attribute, which is
    ``None`` for an admitted call and for an attempt the gate could not read), the
    :class:`~sandbox.syscalls.Commitment` itself, and any non-empty mapping — so a
    caller that has already flattened the gate's answer into a row can hand that
    in rather than reconstructing a decision object.

    **A non-empty mapping is returned even when it is incomplete**, so an
    unreadable violation and *no* violation stay distinguishable: the first is a
    refusal a caller acts on, and the second is the run continuing.  Collapsing
    them would make a caller that handed in half a row believe there was nothing
    to see.
    """
    if subject is None:
        return None
    if isinstance(subject, Mapping):
        return subject if subject else None
    carried = getattr(subject, _VIOLATION_ATTRIBUTE, None)
    if carried is not None:
        return carried
    if _readable(subject):
        return subject
    return None


def _readable(subject: object) -> bool:
    """Whether ``subject`` carries all of :data:`_VIOLATION_FIELDS`."""
    return all(_violation_field(subject, name) is not None for name in _VIOLATION_FIELDS)


def _violation_field(violation: object, name: str) -> Any:
    """``violation``'s ``name``, read from an attribute or a mapping key."""
    if isinstance(violation, Mapping):
        return _row_field(violation, name)
    value = getattr(violation, name, None)
    if callable(value):
        # `fail_class` is a property on Commitment but a plain attribute
        # elsewhere; a method would only appear if a caller handed in a type.
        return None
    return value


def quarantine_violation(
    subject: object,
    tree: NodeTree,
    *,
    quarantined_at: dt.datetime | None = None,
) -> QuarantineDecision:
    """Halt ``subject``'s node and its subtree, or answer why not.

    Feature 161's whole sentence, in one call.  ``subject`` is feature 160's
    :class:`~sandbox.syscalls.SyscallDecision` — or its
    :class:`~sandbox.syscalls.Commitment`, or a mapping carrying the same three
    fields.  ``tree`` is the discovery tree the caller fetched, as a
    :class:`NodeTree`.

    The branches, in the order they are checked, each with the section of
    :mod:`sandbox.quarantine`'s docstring that argues for it:

    * ``tree`` is not a :class:`NodeTree` — an ``UNREADABLE_VIOLATION`` refusal,
      because a tree this law cannot walk is one it cannot close a branch over.
    * the subject carries no readable violation — ``NOTHING_TO_QUARANTINE``, the
      run continuing: feature 160 publishes ``None`` for an admitted call and for
      an attempt it could not read as a syscall, and never calls the latter an
      escape attempt.
    * the violation names a class other than ``sandbox_escape`` — a
      ``FOREIGN_CLASS`` refusal.  §15's recovery column is one row, and a timeout
      or an ``error`` belongs to the law that recorded it.
    * the violation names a node the tree does not hold — ``UNKNOWN_NODE``.
    * the ``parent_id`` chain from that node closes on itself — ``CYCLIC_TREE``.

    Otherwise the branch is closed and answered as a :class:`Quarantine`.  **The
    tree is not written to here**: :func:`quarantine_violation` decides *what* is
    halted, and :meth:`Quarantine.mark` is where a caller's records are written,
    so the read-only question and the durable one are separable — the same split
    :func:`sandbox.failclass.classify_run` draws from its own writer.

    ``quarantined_at`` stamps the halt; omitted, this process's UTC clock is read
    once.  It is *not* consulted when the caller's records already carry a mark —
    :meth:`Quarantine.mark` keeps the original instant.
    """
    if not isinstance(tree, NodeTree):
        return QuarantineDecision(
            reason=QuarantineReason.UNREADABLE_VIOLATION,
            detail=(
                f"{QUARANTINE_REQUIRED_CODE}: this law closes a branch over a "
                f"NodeTree built from the caller's node rows, and got "
                f"{type(tree).__name__}. Feature 161 quarantines *a node together "
                f"with its subtree*, so the subtree has to be something this law "
                f"can walk — and the caller owns the store, so the rows are "
                f"fetched there and handed in rather than opened here (feature "
                f"161)."
            ),
        )
    violation = _subject_violation(subject)
    if violation is None:
        return QuarantineDecision(
            reason=QuarantineReason.NOTHING_TO_QUARANTINE,
            detail=(
                "the subject carries no readable seccomp violation, so there is "
                "no branch to halt and the run continues (feature 161)."
            ),
        )
    if not _readable(violation):
        return QuarantineDecision(
            reason=QuarantineReason.UNREADABLE_VIOLATION,
            detail=(
                f"{QUARANTINE_REQUIRED_CODE}: the subject's violation is a "
                f"{type(violation).__name__} carrying no "
                f"{', '.join(_VIOLATION_FIELDS)}, so this law cannot read which "
                f"class it names or which syscall it describes. A violation is a "
                f"record of an event — feature 160's Commitment is one, and a "
                f"mapping with the same three fields is one — and a subject that "
                f"is only *shaped* like one is not evidence a branch should be "
                f"halted on (feature 161)."
            ),
        )
    cls = _violation_field(violation, "fail_class")
    if cls != QUARANTINE_FAIL_CLASS:
        return QuarantineDecision(
            reason=QuarantineReason.FOREIGN_CLASS,
            detail=(
                f"{QUARANTINE_REQUIRED_CODE}: the subject handed to the "
                f"quarantine law names the fail class {cls!r} "
                f"({type(violation).__name__}), and §15's recovery column belongs "
                f"to one row — 'Sandbox escape attempt | seccomp violation | "
                f"Kill, record fail_class, quarantine the node and its subtree'. "
                f"Quarantining a branch for {cls!r} would halt a subtree for a "
                f"failure no ceiling was ever compared against, and the law that "
                f"owns that failure records it on its own terms. Refused rather "
                f"than acted on (feature 161)."
            ),
        )
    node = _violation_field(violation, "node_id")
    if not tree.holds(node):
        return QuarantineDecision(
            reason=QuarantineReason.UNKNOWN_NODE,
            detail=(
                f"{QUARANTINE_REQUIRED_CODE}: the violation names node {node!r}, "
                f"which is not in the tree this caller handed in "
                f"({tree.size} node(s) from {len(tree.campaigns())} "
                f"campaign(s)). §15 quarantines *the node and its subtree*, and a "
                f"node this law cannot find is one whose subtree is unknowable — "
                f"fetch it and hand the tree in again rather than halting an "
                f"empty branch (feature 161)."
            ),
        )
    try:
        nodes = tree.subtree(str(node))
    except QuarantineTreeError as exc:
        return QuarantineDecision(
            reason=QuarantineReason.CYCLIC_TREE,
            detail=(
                f"{QUARANTINE_REQUIRED_CODE}: the branch from {node!r} could not "
                f"be closed — {exc} A node cannot be its own ancestor, and a "
                f"closure from a ring is a guess about which rows to halt; "
                f"refused rather than guessed (feature 161)."
            ),
        )
    # Depth is measured from the branch's root, so the violating node is 0 and
    # each level below it counts up. `subtree` returns pre-order, where a node's
    # index is *not* its depth, so the distance is walked off the parent edges.
    depth_of = {nodes[0]: 0}
    for member in nodes[1:]:
        parent = tree.parent_of(member)
        depth_of[member] = depth_of.get(parent, 0) + 1 if parent in depth_of else 1
    campaign = tree.campaign_of(str(node))
    return QuarantineDecision(
        reason=QuarantineReason.QUARANTINED,
        quarantine=Quarantine(
            root=str(node),
            nodes=nodes,
            depth_of=depth_of,
            violation={
                "fail_class": cls,
                "syscall": _violation_field(violation, "syscall") or "",
                "action": _violation_field(violation, "action") or "",
                "component": _violation_field(violation, "component") or "",
                "campaign_id": campaign,
            },
        ),
    )


def quarantines(subject: object, tree: NodeTree) -> bool:
    """Whether ``subject`` halts ``tree`` — the branch question as a bool.

    Feature 168's :func:`sandbox.failclass.classify_run` answers the same shape of
    question for its own subject; this is the convenience for a caller that only
    needs the predicate and not the reason.  It never raises: a malformed tree or
    an unknown node is ``False`` here, and a caller that needs to tell those apart
    reads the :class:`QuarantineDecision` instead.
    """
    try:
        return quarantine_violation(subject, tree).quarantined
    except SandboxQuarantineError:
        return False


class SandboxQuarantine:
    """Feature 161's law, as the value a composed application carries.

    A stateless facade over this module — the same shape
    :class:`sandbox.SandboxIsolation` gives feature 157,
    :class:`sandbox.SandboxImports` 167, :class:`sandbox.SandboxTransfer` 166,
    :class:`sandbox.SandboxSeed` 165, :class:`sandbox.SandboxThreads` 164,
    :class:`sandbox.SandboxTimeout` 163, :class:`sandbox.SandboxSyscalls` 160 and
    :class:`sandbox.SandboxFailClass` 168 — so a caller holding the composed
    component can ask the feature's question, *is this branch halted?*, without
    importing the member's submodules by name.

    **It carries nothing at all**, and it is the second law in this member that
    can say that: like feature 168's, this law's subject is a *rule* rather than a
    deployment's setting — §15 fixes the trigger and the recovery, §9.1 fixes the
    class vocabulary — so ``__slots__`` is empty, the builder has nothing to
    compile, and there is no committed artifact behind the component.  A
    non-``None`` component at this seat is therefore proof only that the law is
    loaded, the reading features 165's, 166's and 168's seats established.

    **The trigger arrives as an argument, not as state**, which is why this law is
    artifact-less where features 157, 167, 164, 163, 162 and 160 are not: those
    laws compile a policy at build time and answer against it, while this one has
    nothing to answer *against* until a violation and a tree are handed to it.
    The same reason :func:`sandbox.failclass.classify_run` needs a run.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the closure or the class check
    here would be a second thing to keep in sync, and the member's
    one-provenance rule exists so that cannot happen.
    """

    __slots__ = ()

    def check(self, subject: object, tree: NodeTree) -> QuarantineDecision:
        """Answer whether ``subject`` halts ``tree`` — the gate, as a value.

        Nothing is raised for the branch's fate; every refusal comes back as the
        decision's :attr:`~QuarantineDecision.reason`.  This is
        :func:`quarantine_violation` with the law's name on it.
        """
        return quarantine_violation(subject, tree)

    def require(self, subject: object, tree: NodeTree) -> Quarantine:
        """Return the quarantine, or raise — the launcher's verb.

        The caller that puts this on the line after the gate's own
        :meth:`sandbox.syscalls.SyscallDecision.require` has said it needs a
        branch for every violation, so the pass-through raises here too; a caller
        running the unattended loop §6.1 describes reads
        :meth:`check` instead.
        """
        return quarantine_violation(subject, tree).require()

    def quarantines(self, subject: object, tree: NodeTree) -> bool:
        """Whether ``subject`` halts ``tree`` — the predicate, never raising."""
        return quarantines(subject, tree)

    def tree(self, rows: Iterable[Mapping[str, Any]]) -> NodeTree:
        """Build the tree from ``rows`` — the caller's fetch, read once.

        Exposed as a verb so a caller that already holds the component does not
        have to import :class:`NodeTree` by name to hand one in, the discipline
        :meth:`sandbox.SandboxFailClass.classes` applies to §9.1's vocabulary.
        """
        return NodeTree(rows)

    def columns(self) -> tuple[str, ...]:
        """§15's quarantine ledger columns, in declaration order — the read side.

        A deployment building a query, a report or a CI check reads the shape
        here rather than re-spelling it.  Reading it grants nothing: the tuple is
        this module's declaration, and this law holds no capability to widen it.
        """
        return QUARANTINE_COLUMNS

    def fail_class(self) -> str:
        """The class a quarantine persists — ``sandbox_escape`` — spelled once.

        Exposed for the same reason: a caller comparing a stored class against
        §15's row reads the member's own spelling rather than writing the string
        again, and a typo in that string is a branch that never reads as halted.
        """
        return QUARANTINE_FAIL_CLASS

    def mark_column(self) -> str:
        """The field a halt is written to on every node of the branch."""
        return NODE_QUARANTINED_COLUMN

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "SandboxQuarantine()"


def sandbox_quarantine() -> SandboxQuarantine:
    """Feature 161's law, fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs a violation and a tree
    to answer for.  This is the module-level convenience the member's own tests
    and any operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_quarantine` makes minus the composition.
    """
    return SandboxQuarantine()
