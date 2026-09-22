"""The expansion of a selected node — one refined signal, resumed from its workspace — feature 239.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 239: *System
expands a selected node by resuming its workspace, which creates exactly
one refined signal for evaluation.*  docs/alpha-engine-prd.md §5's loop 1
states the same act in its own notation — *"``CONTINUE(v)`` = resume node
``v``'s workspace, generate and evaluate one refined signal"* — and the
architecture doc's verb table (§5) carries it as one row: *"``CONTINUE(v)``
| Refine and re-evaluate one signal"*.  This module is that verb, and it
is the collaborator two of this member's existing modules name in
absentia: :mod:`discovery.workers` calls it **the worker of record**
(*"feature 239's expansion, a deployment's evaluator driver"* — the
callable the pool runs once per job, *"which closes over stores and
workspace handles no pickle can carry"*), and
:meth:`discovery.retry.retry_interrupted`'s identity law states the
constraint that shapes its biggest design choice (see *"the identity is
derived"* below).

**What the expansion is, in one paragraph.**  :class:`NodeExpansion` is
constructed with the deployment's agent seam and a database URL; calling
it with **one selected node** — a node id, the element of the batch the
policy selected and feature 238's pool dispatched — performs
``CONTINUE(v)``: it reads that node's workspace from the tree
(:class:`NodeWorkspace`, the five structural facts feature 97's table
owns), hands the workspace to the agent seam, requires **exactly one**
refined signal in the answer, and returns it as a :class:`RefinedSignal`
— the construction (``code``, ``code_hash``, ``stated_mechanism``) plus
the tree facts the child carries (its derived ``node_id``, its
``parent_id``, the campaign, the theme, the depth) — *for evaluation*:
§6's evaluator consumes it, feature 240 persists it, and this module
persists nothing.

**Resuming is reading the tree, and the tree is the only source.**  The
ask is a node id — canonicalized through :class:`uuid.UUID` exactly as a
campaign id is, because the value joins ``node.parent_id`` and every
reader of the tree resolves it — and everything else the expansion knows
about the node it **reads from the ``node`` table**: the id, the
``parent_id``, the ``campaign_id``, the ``theme_root`` and the ``depth``,
the five columns ``0118_node_table.py`` owns (the migration's own
docstring names this feature as the consumer of the ``parent_id`` edge).
The teeth of *"resuming its workspace"* are in what is refused: an ask
that is not a node id, a tree with no ``node`` table, and an id the tree
does not hold each refuse **naming the node**, before the agent is ever
consulted — you cannot resume a workspace the tree does not hold, and a
caller cannot smuggle workspace facts in through a richer ask, because
there is no field for them.  The *artifact-side* of a workspace — the
source text, every prior proposal, the scores, §9.2's per-node directory
— is deliberately not assembled here: C3's read-the-complete-history
prompt is the agent driver's business, and the driver closes over the
stores that hold it (the closure is why 238's slots are threads).  What
this module proves is that the refinement answers *the selected node*:
the agent is handed the tree's own record of it, and the refined signal
carries that record forward — ``parent_id`` is the selected node,
``campaign_id`` and ``theme_root`` are inherited unchanged (a node's
theme is *"the research theme this node's root was planted in"*, 0118's
own words, so refinement never changes families), and ``depth`` is the
parent's plus one.

**The identity is derived, never minted — and that is feature 244's
law made arithmetic.**  The refined signal's ``node_id`` is
``uuid.uuid5(EXPANSION_NAMESPACE, parent_id)``:
:data:`refined_node_id` is the one spelling of the derivation.
``retry.py`` states why in as many words — *"a re-run that minted a
fresh node id would post a charge the ledger dutifully appends"* — and
§14's contract (*"ledger debits are idempotent by ``node_id``"*) only
answers the retry because the retry re-runs ``result.job`` and this
module makes identity a **function of the ask**: the same selected node
expands to the same child id on every run, first attempt or tenth
reclamation, so the debit keys on one ``node_id`` and the ledger's
idempotence has one row to be idempotent over.  The derivation is
pinned inside :class:`RefinedSignal` itself (the
:class:`~discovery.retry.RetriedResult` pattern): a signal whose id is
not its parent's derivation is not a ``CONTINUE(v)`` this module made,
and ``dataclasses.replace`` cannot build one.  What the derivation does
**not** pin is the content — §10.1's *"online transition is stochastic
(the agent may generate a different child from the same workspace)"* —
and the two are deliberately independent: identity is the *attempt
slot* (stable, so retries are the same attempt), content is what the
answered run produced (free, so the agent explores).  Feature 240
records the content that landed; this module guarantees the slot.

**Exactly one, and the sentence's second clause is a refusal
vocabulary.**  The agent seam is one call, ``agent(workspace)``; the
answer is read duck-typed, and the law is **counted, not assumed**:

* an answer that is a **sized collection** of candidates (``list``,
  ``tuple``, ``set``, ``frozenset``) must hold exactly one — an empty
  collection answered no signal, and two or more answered a batch
  ``CONTINUE`` never asked for.  Several refinements of one workspace
  are several dispatches, each its own attempt, each debited its own
  ``node_id`` — a seam that adopted a list would spend one charge on
  several hypotheses, which is the duplicate-debit shape feature 244
  exists to prevent, arrived at from the other side;
* the one candidate must **carry ``code``** — read as an attribute, the
  one read path (:mod:`signal_agent._authoring`'s screen reads its
  decision the same way) — and the code must be non-blank text.  A bare
  string is refused rather than guessed into a code-only construction:
  §6.1's construction block is the *pair* (``code`` beside
  ``stated_mechanism``), and a seam that accepted a bare string would
  manufacture *"the agent stated no mechanism"* — a fact 0117 permits
  only the agent to state, by leaving the field off a value that could
  carry it;
* ``stated_mechanism`` is optional — absent is 0117's honest ``NULL``
  (*"an agent that states no mechanism has left nothing to review"*)
  — and present-but-blank or non-text is refused, because a blank
  rationale is not a rationale and a non-text one is nothing to review.

The adopted code is returned **unmodified** — the
:mod:`signal_agent._authoring` discipline restated: the ``code_hash``
persisted beside the node is the hash of exactly what §5.2's sandbox
executes, and a member that tidied a proposal "into shape" here would
author it.  Conformance to the signal ABI is deliberately **not**
re-checked: feature 205's adoption is the authoring member's law, the
workspace contract keeps this member from importing it, and a second
validator here would be a second thing to keep in step with the ABI
every stored node is stamped against.  This module refuses *shapes and
cardinality*; the signature is 205's, at the seam that owns it.

**The refusals raise** :class:`~discovery.errors.ExpansionError`
(**new**, the sixth class) — and **the agent's own exceptions pass
through untouched**, in both directions, on purpose.  A
:class:`~discovery.errors.WorkerInterrupted` raised by the agent must
arrive at the pool as itself, because
:func:`~discovery.retry.is_interruption` is true of exactly that class:
a re-wrapped interruption would fail the ``isinstance`` check, quietly
stop retrying, and turn §14's *"scheduled event, not an accident"* into
a spent hypothesis.  An agent's evaluation failure must arrive as
itself for the same reason from the other side — §6.1's step 11 charges
the attempt, and the tree logs what actually happened.  So the
expansion's ``try`` never spans the agent call: this module speaks only
for its own two faces (the tree's and the seam's, one class carrying
both, :mod:`discovery.errors`'s own paragraph for why), and wraps
nothing it did not itself refuse.

**No persistence, and that split is the category's own.**  Feature 240's
sentence — *"System persists every attempt into the node table together
with its full artifact, **including failures**"* — is the *next* feature
in this category and a different act: persistence needs the attempt's
outcome (§6.1's pipeline, steps 1–11) and this module's job ends at the
signal evaluation consumes.  :meth:`RefinedSignal.row` is the hand-off —
the seven ``node``-row columns the attempt will land in (the five
structural plus ``code_hash`` and ``stated_mechanism``), with the source
text travelling as :attr:`RefinedSignal.code` because §9.1 stores the
hash and §9.2's artifact directory stores the text, and the pair cannot
drift when the hash is computed at adoption (the fourth spelling of the
same three stdlib lines — the evaluator's step 6, the authoring
member's, the artifact member's, and now the orchestrator's; each
member's docstring states the same trade).

**No component, for the inherited reason with a face of its own.**
Features 241, 238 and 244 add none because their verbs hold no state a
deployment keeps; this one *does* close over state — the database URL
and the agent seam — and adds none anyway, because the agent is not
composable: a builder runs at factory time with no arguments, and the
one thing it cannot obtain is the deployment's evaluator driver (the
very thing 238's docstring says *"closes over stores and workspace
handles no pickle can carry"*).  A builder that registered an expansion
with no agent would be registering a refusal; the caller that dispatches
a batch constructs the worker with the agent it planned to run and the
store its tree lives in.  The member's registered surface stays feature
232's single campaign store, and its component suite is untouched.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``uuid``, ``hashlib``
and a dataclass; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for the verb, and a composed application that never dispatches
a node never opens the tree.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import ExpansionError

__all__ = [
    "EXPANSION_NAMESPACE",
    "NodeExpansion",
    "NodeWorkspace",
    "RefinedSignal",
    "expand_node",
    "refined_node_id",
]

#: The UUID namespace the refined signal's identity is derived in —
#: ``uuid.uuid5(EXPANSION_NAMESPACE, parent_id)``.
#:
#: The value is arbitrary and that is the point: a version-5 UUID is a
#: SHA-1 over the namespace and the name, so *any* fixed namespace gives
#: a stable derivation, and what the constant buys is a *namespaced*
#: one — the same parent id fed to a different member's ``uuid5`` (a
#: different namespace) answers a different id, so this derivation can
#: never collide with an identity another feature mints over node ids
#: for its own purposes.  It is spelled here, once, because the
#: derivation is a contract (feature 244's identity law) and a contract
#: spelled twice is two contracts.
EXPANSION_NAMESPACE = uuid.UUID("8b4f4a52-9c26-4a2e-8f0b-2391d6375a71")

#: The read-only probe that answers *does this database hold a tree at
#: all?* — the same ``sqlite_master`` idiom feature 232's ordering law
#: uses (``discovery.campaign._NODE_TABLE_EXISTS_SQL``), restated here
#: rather than imported because a private constant of a sibling module
#: is not a promise, and parameterised so the table name is a bound
#: value rather than interpolated text.
_NODE_TABLE_EXISTS_SQL = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)

#: The one statement the workspace read runs: the five structural
#: columns feature 97's table owns, selected by name (never ``SELECT *``)
#: in the order :class:`NodeWorkspace` reads them, so a migration that
#: appends a column (0114–0117 all did) cannot silently shift the fields.
#: The columns beyond the five — the identity, provenance and
#: authoring-model triples, the metrics — are deliberately not read:
#: the artifact-side of a workspace is the agent driver's to assemble,
#: and this module proves the *tree* half of the resumption.
_WORKSPACE_SQL = (
    "SELECT id, parent_id, campaign_id, theme_root, depth FROM node "
    "WHERE id = ?"
)


# -- Validation -------------------------------------------------------------------


def _canonical_node_id(value: Any, *, field: str) -> str:
    """Canonicalize one node id, refusing what is not one.

    The same canonicalization a campaign id gets
    (:func:`discovery.campaign._validated_campaign_id`), restated for the
    tree's key: a :class:`uuid.UUID`, or text ``uuid.UUID`` parses, is
    answered as canonical lowercase text — because the value joins
    ``node.parent_id`` (a mixed-case key would make one node look like
    two) — and anything else is refused, naming the field, so a caller
    learns which id of which ask could not name a node.  ``None`` is
    refused rather than passed through: unlike a campaign's *"let the
    table mint it"*, an expansion has no minted-identity path — the
    identity is derived from the parent, and an ask with no parent names
    no workspace to resume.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise ExpansionError(
        f"{field} {value!r} is not a node id; CONTINUE(v) expands one "
        "selected node — the id the policy's batch selection carries and "
        "node.parent_id resolves — so an ask that names no node names no "
        "workspace to resume (feature 239)"
    )


def _validated_theme_root(value: Any, node: str) -> str:
    """Refuse a stored ``theme_root`` that is not a theme.

    ``0118`` declares the column ``TEXT NOT NULL``, and a node's theme is
    inherited unchanged by the refinement, so a blank or non-text value
    is a row this read cannot carry forward: the refined signal would
    plant a theme the family-conditional thresholds (§11.1) could never
    key on.  Checked on the read path, where the value came out of the
    table, and naming the node it came off.
    """
    if not isinstance(value, str) or not value.strip():
        raise ExpansionError(
            f"node {node!r} carries theme_root {value!r} "
            f"({type(value).__name__}); the theme is the root's research "
            "space and a refinement inherits it unchanged, so a row "
            "without one is a workspace whose family cannot be carried "
            "forward (feature 239)"
        )
    return value


def _canonical_campaign_id(value: Any, node: str) -> str:
    """Canonicalize the row's campaign id, refusing what is not one.

    The same canonicalization a node id gets, restated for the one
    structural fact the workspace read cannot carry forward unexamined:
    the value joins ``node.campaign_id``, and §9.1 scopes *every tree
    query* to one campaign, so a non-UUID there is a row whose
    refinement would scope to no campaign at all.  Refused naming the
    node it came off, the discipline the other two row checks keep —
    every refusal this module raises names the node whose workspace it
    is about (:class:`~discovery.errors.ExpansionError`'s own contract).
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise ExpansionError(
        f"node {node!r} carries campaign_id {value!r} "
        f"({type(value).__name__}), which is not a campaign id; the "
        "campaign is the fact every tree query scopes to (§9.1), and a "
        "row whose campaign cannot be named is a workspace whose "
        "refinement would scope to no campaign at all (feature 239)"
    )


def _validated_depth(value: Any, node: str) -> int:
    """Refuse a stored ``depth`` that is not a tree depth.

    ``0118`` declares the column ``INT NOT NULL``, zero at a root and
    increasing down each branch; ``bool`` is refused explicitly because
    ``True`` is an ``int`` in Python, and ``-1`` is refused because a
    node above the root is not a place in the tree.  The refined signal
    sits at ``depth + 1``, so a depth this check cannot trust is a depth
    the child would inherit wrongly.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExpansionError(
            f"node {node!r} carries depth {value!r} "
            f"({type(value).__name__}); a node's depth is its position "
            "down the branch from the root, and a row whose depth is not "
            "a count is a workspace whose child this module cannot place "
            "(feature 239)"
        )
    if value < 0:
        raise ExpansionError(
            f"node {node!r} carries depth {value!r}; depth is zero at a "
            "root and increases down each branch, so a negative depth is "
            "a position above the root no tree holds (feature 239)"
        )
    return value


# -- The derivation ---------------------------------------------------------------


def refined_node_id(parent_id: Any) -> str:
    """The refined signal's node id: ``uuid5(EXPANSION_NAMESPACE, parent)``.

    The identity law as one call.  The parent is canonicalized first —
    the derivation runs over the canonical spelling, so an uppercase ask
    and its lowercase twin derive the *same* child (they name the same
    node, and the same ask must always be the same attempt) — and the
    answer is a version-5 UUID: stable across processes, platforms and
    runs, because it is a SHA-1 over two fixed inputs rather than a
    draw from an entropy source.

    Public because the identity is a contract two later features read:
    the trial ledger's debit keys on it (§14's *"idempotent by
    ``node_id``"*, answered across a 244 retry), and feature 240's
    persistence writes it onto the row.  A caller that re-derived it by
    hand would be a second spelling of the derivation — the very drift
    :data:`EXPANSION_NAMESPACE`'s docstring refuses — so the one
    spelling is exported.
    """
    parent = _canonical_node_id(parent_id, field="parent_id")
    return str(uuid.uuid5(EXPANSION_NAMESPACE, parent))


# -- The workspace ----------------------------------------------------------------


@dataclass(frozen=True)
class NodeWorkspace:
    """The selected node's workspace, as the tree holds it.

    The five structural facts ``0118_node_table.py`` declares — the
    resumed node's own id, its parent (``None`` at a root: a root's
    workspace is resumable the same as any other node's, and the refined
    signal it yields is the root's first child), the campaign both
    belong to, the theme the whole branch inherits, and the depth the
    child will sit one below.  This is what ``CONTINUE(v)`` resumes:
    the value the agent seam is handed, and the whole of what this
    module claims about the node — the artifact-side of a workspace
    (source text, prior proposals, scores, §9.2's directory) is the
    agent driver's to assemble over the stores it closes around, and a
    driver that wants more tree than this walks it with its own
    connection.

    Frozen and validated in ``__post_init__``, the discipline
    :class:`~discovery.campaign.CampaignRecord` states for its own
    reasons: the workspace is the record of a node's place in the tree,
    and a mutable one would let a caller re-place a node in memory
    while the row said otherwise — worst of all by editing
    ``parent_id``, the very edge the resumption is *of*.
    """

    #: The selected node's own id — the ``v`` of ``CONTINUE(v)``,
    #: canonical UUID text.
    node_id: str
    #: The selected node's parent, or ``None`` when it is a root.
    parent_id: str | None
    #: The campaign the node belongs to — inherited by the refined
    #: signal unchanged.
    campaign_id: str
    #: The theme the node's root was planted in — inherited unchanged;
    #: refinement never changes families.
    theme_root: str
    #: The node's depth: zero at a root, one more down each refinement.
    depth: int

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalization below is normalization, not mutation, and it
        # is the only write this object ever takes.
        node = _canonical_node_id(self.node_id, field="node_id")
        object.__setattr__(self, "node_id", node)
        if self.parent_id is not None:
            object.__setattr__(
                self,
                "parent_id",
                _canonical_node_id(self.parent_id, field="parent_id"),
            )
        object.__setattr__(
            self,
            "campaign_id",
            _canonical_campaign_id(self.campaign_id, node),
        )
        object.__setattr__(
            self, "theme_root", _validated_theme_root(self.theme_root, node)
        )
        object.__setattr__(self, "depth", _validated_depth(self.depth, node))

    @property
    def is_root(self) -> bool:
        """True when the selected node is a root (``parent_id`` is ``None``).

        Offered because the two jobs §14.1 tiers apart meet at this
        property: expanding a root is the depth 0–1 role's work and
        expanding anything deeper is the depth ≥ 2 role's, and the
        driver that routes by role reads the branch's shape off this
        one fact rather than re-deriving it from ``parent_id``.
        """
        return self.parent_id is None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"theme_root={self.theme_root!r}, depth={self.depth!r})"
        )


# -- The refined signal -----------------------------------------------------------


@dataclass(frozen=True)
class RefinedSignal:
    """Exactly one refined signal, ready for evaluation.

    The expansion's whole answer.  The construction half — ``code``, the
    adopted source text, unmodified; ``code_hash``, its sha256, computed
    once here so the pair cannot drift; ``stated_mechanism``, the
    agent's own rationale or ``None`` — is what §6's evaluator runs and
    §9.1's tree persists.  The tree half — the derived ``node_id``, the
    ``parent_id`` whose workspace was resumed, the inherited
    ``campaign_id`` and ``theme_root``, and the ``depth`` one below the
    parent — is what the child row will carry when feature 240 writes
    it, and what the ledger's debit keys on before that.

    Frozen and validated in ``__post_init__``, and the validation pins
    the identity law inside the value (the
    :class:`~discovery.retry.RetriedResult` pattern): ``node_id`` must
    be :func:`refined_node_id` of ``parent_id``, ``depth`` must be at
    least one (a refined signal is never a root — the tree's roots are
    planted, not refined), ``code_hash`` must be the sha256 of ``code``,
    and ``code`` must be non-blank text.  A value that fails any of
    these is not a ``CONTINUE(v)`` this module made, and neither
    ``dataclasses.replace`` nor unpickling can build one past the
    check.
    """

    #: The refined signal's identity — derived, never minted.  Must be
    #: :func:`refined_node_id` of ``parent_id``; see the module docstring
    #: for why the derivation is feature 244's law made arithmetic.
    node_id: str
    #: The selected node whose workspace was resumed — the ``v`` of
    #: ``CONTINUE(v)``, and the child row's ``parent_id``.
    parent_id: str
    #: The campaign the parent belongs to, inherited unchanged.
    campaign_id: str
    #: The theme the parent's root was planted in, inherited unchanged.
    theme_root: str
    #: The child's depth: the parent's, plus one.  At least one, because
    #: a refined signal is never a root.
    depth: int
    #: The adopted source text — the exact text §5.2's sandbox executes,
    #: returned unmodified from the agent's answer.
    code: str
    #: ``sha256(code)`` — §9.1's ``code_hash CHAR(64)``, computed at
    #: adoption and carried beside the text so the two cannot drift.
    code_hash: str
    #: The agent's stated economic rationale, or ``None`` when it stated
    #: none — 0117's honest ``NULL``: *"an agent that states no
    #: mechanism has left nothing to review"*.  Dedup and human review
    #: only, never a scored input.
    stated_mechanism: str | None

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalizations below are normalization, not mutation, and
        # they are the only writes this object ever takes.
        parent = _canonical_node_id(self.parent_id, field="parent_id")
        object.__setattr__(self, "parent_id", parent)
        object.__setattr__(
            self, "campaign_id",
            _canonical_campaign_id(self.campaign_id, parent),
        )
        object.__setattr__(
            self, "theme_root",
            _validated_theme_root(self.theme_root, parent),
        )
        # The identity law, pinned: the child's id is the derivation of
        # the parent's — one refined-signal slot per selected node, and
        # the same ask the same attempt on every run.
        derived = refined_node_id(parent)
        if _canonical_node_id(self.node_id, field="node_id") != derived:
            raise ExpansionError(
                f"a refined signal's node_id is derived from the parent it "
                f"resumes: got {self.node_id!r} for parent {parent!r}, "
                f"whose derivation is {derived!r}. The derivation is what "
                "makes a reclamation's re-run the same attempt in identity "
                "(§14: 'ledger debits are idempotent by node_id', feature "
                "244), so an id that is not its parent's derivation is a "
                "signal no CONTINUE(v) produced (feature 239)"
            )
        object.__setattr__(self, "node_id", derived)
        # Depth: one below the parent, never a root.
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise ExpansionError(
                f"a refined signal's depth must be an integer, got "
                f"{self.depth!r} ({type(self.depth).__name__}); it is the "
                "position the child occupies one below the resumed node, "
                "and a row placed at a non-count depth is a node the tree "
                "cannot walk (feature 239)"
            )
        if self.depth < 1:
            raise ExpansionError(
                f"a refined signal's depth must be at least 1, got "
                f"{self.depth!r}; roots are planted with a fresh research "
                "theme (§9) and only their refinements are CONTINUE(v) — "
                "a refined signal at depth 0 would be a root nobody "
                "assigned a theme to (feature 239)"
            )
        # The construction: non-blank source, and the hash of exactly
        # that source — the pair 0117 persists, computed once so the
        # caller cannot drift them apart.
        if not isinstance(self.code, str) or not self.code.strip():
            raise ExpansionError(
                f"the refined signal for {parent!r} carries no source "
                f"({self.code!r}, {type(self.code).__name__}); §5.2's "
                "sandbox compiles what the agent wrote, and a blank or "
                "non-text code is a signal no evaluation could run "
                "(feature 239)"
            )
        expected = hashlib.sha256(self.code.encode("utf-8")).hexdigest()
        if self.code_hash != expected:
            raise ExpansionError(
                f"the refined signal for {parent!r} carries code_hash "
                f"{self.code_hash!r} over code whose sha256 is "
                f"{expected!r}; §9.1 persists the hash beside the node "
                "and the artifact directory holds the text, so a pair "
                "that disagrees identifies source no run could "
                "reproduce (feature 239)"
            )
        # The stated mechanism: absent is the honest NULL; present must
        # be a rationale somebody could review.
        if self.stated_mechanism is not None and (
            not isinstance(self.stated_mechanism, str)
            or not self.stated_mechanism.strip()
        ):
            raise ExpansionError(
                f"the refined signal for {parent!r} carries "
                f"stated_mechanism {self.stated_mechanism!r} "
                f"({type(self.stated_mechanism).__name__}); the field is "
                "the agent's own rationale for dedup and human review, so "
                "the honest absent value is None and a blank or non-text "
                "one states nothing while claiming to (feature 239)"
            )

    def row(self) -> dict[str, Any]:
        """The signal as the ``node`` row it will land in — a fresh dict.

        The seven columns of §9.1's table that a refined attempt carries
        at birth: the five structural ones (feature 97's) plus the two
        of feature 98's identity triple this feature owns the values of
        (``code_hash``, ``stated_mechanism`` — ``artifact_uri`` is
        feature 240's write, and the provenance, authoring-model and
        metrics triples are the evaluator's and the attempt's, not the
        signal's).  The source text travels as :attr:`code` and not as
        a key here, because §9.1 stores the hash and §9.2's artifact
        directory stores the text — the same split
        :meth:`~discovery.campaign.CampaignRecord.row` makes when it
        reports the columns the table holds and nothing it does not.
        """
        return {
            "id": self.node_id,
            "parent_id": self.parent_id,
            "campaign_id": self.campaign_id,
            "theme_root": self.theme_root,
            "depth": self.depth,
            "code_hash": self.code_hash,
            "stated_mechanism": self.stated_mechanism,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"parent_id={self.parent_id!r}, depth={self.depth!r})"
        )


# -- The agent's answer ------------------------------------------------------------


def _one_refinement(answer: Any, node: str) -> Any:
    """Count the agent's answer, refusing everything that is not one signal.

    The *exactly one* of the feature's sentence, as one read.  An answer
    that is a sized collection of candidates is counted — an empty one
    answered nothing, and a plural one answered a batch the ask never
    carried (each refinement is its own dispatch and its own debited
    ``node_id``, so adopting several under one call would spend one
    charge on several hypotheses).  A single candidate passes through
    unjudged: the shape checks (``code``, ``stated_mechanism``) are the
    next function's, so this one owns the cardinality and nothing else.
    """
    if isinstance(answer, (list, tuple, set, frozenset)):
        count = len(answer)
        if count == 0:
            raise ExpansionError(
                f"the agent seam answered no refined signal for node "
                f"{node!r} (an empty collection); CONTINUE(v) creates "
                "exactly one refined signal for evaluation, and an answer "
                "of none is an attempt that produced nothing — the tree "
                "logs it as a failure rather than this module inventing a "
                "signal nobody proposed (feature 239)"
            )
        if count > 1:
            raise ExpansionError(
                f"the agent seam answered {count} refined signals for "
                f"node {node!r}; CONTINUE(v) creates exactly one, and a "
                "batch of candidates is a batch of asks — each refinement "
                "is its own dispatch, its own derived node_id and its own "
                "trial charge, so adopting several under one call would "
                "spend one ledger debit on several hypotheses (the "
                "duplicate-debit shape feature 244 exists to prevent, "
                "arrived at from the other side) (feature 239)"
            )
        return next(iter(answer))
    return answer


def _validated_construction(candidate: Any, node: str) -> tuple[str, str | None]:
    """Read one candidate's construction, refusing what is not one.

    The refinement is a value **carrying** its construction — ``code``
    read as an attribute, the one read path, and ``stated_mechanism``
    optionally beside it.  A bare string is refused rather than read as
    the code: §6.1's construction is the pair, and a seam that accepted
    a bare string would manufacture *"the agent stated no mechanism"* —
    a fact only the agent can state, by leaving the field off a value
    that could carry it.  The code must be non-blank text (a blank
    answer is a truncation or a stream that ended early, and §5.2's box
    has nothing to compile); the mechanism, when present, must be text
    with something in it.
    """
    if isinstance(candidate, (str, bytes)):
        raise ExpansionError(
            f"the agent seam answered {type(candidate).__name__} for node "
            f"{node!r}; a refinement carries its construction — a value "
            "with a `code` attribute (and optionally "
            "`stated_mechanism`) — and a bare string is source with no "
            "value to state a mechanism on. Reading it as the code would "
            "silently record 'the agent stated no mechanism', which is "
            "the agent's fact to state, not the seam's to manufacture "
            "(feature 239)"
        )
    code = getattr(candidate, "code", None)
    if code is None:
        raise ExpansionError(
            f"the agent seam's answer for node {node!r} carries no code "
            f"({candidate!r}, {type(candidate).__name__}); CONTINUE(v) "
            "creates exactly one refined *signal*, and a value with no "
            "source is a candidate with nothing to evaluate — the answer "
            "must be a refinement carrying `code` (feature 239)"
        )
    if not isinstance(code, str) or not code.strip():
        raise ExpansionError(
            f"the agent seam's answer for node {node!r} carries code "
            f"{code!r} ({type(code).__name__}); §5.2's sandbox compiles "
            "what the agent wrote, and blank or non-text source is a "
            "truncated or unseated completion, not a signal for "
            "evaluation (feature 239)"
        )
    mechanism = getattr(candidate, "stated_mechanism", None)
    if mechanism is not None and (
        not isinstance(mechanism, str) or not mechanism.strip()
    ):
        raise ExpansionError(
            f"the agent seam's answer for node {node!r} carries "
            f"stated_mechanism {mechanism!r} "
            f"({type(mechanism).__name__}); the stated mechanism is the "
            "agent's economic rationale for dedup and human review, so "
            "the honest absent value is None and a blank or non-text one "
            "states nothing while claiming to (feature 239)"
        )
    return code, mechanism


# -- The worker of record ----------------------------------------------------------


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same convention every store in this workspace restates —
    :func:`discovery.campaign._sqlite_path`'s translation with this
    module's own refusal vocabulary, because a caller's ``except
    ExpansionError`` must not be defeated by a planning refusal raised
    from the expansion's path.  A non-SQLite scheme and a pathless URL
    are refused by name; an in-memory database is refused because a
    workspace read must see the tree another process planted, and a
    tree in memory dies with the connection that opened it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ExpansionError(
            f"unsupported DATABASE_URL scheme {parsed.scheme!r}: the "
            "expansion reads the tree the sqlite deployment holds (the "
            "spec's single-machine allowance); point the URL at the "
            "sqlite database the node table already lives in (feature 239)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ExpansionError(
            f"sqlite database URL must not carry a host, got "
            f"{parsed.netloc!r} (feature 239)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise ExpansionError(
            "sqlite database URL carries no database path: the workspace "
            "resumed is the tree another process planted, and an "
            "in-memory tree dies with the connection that opened it "
            "(feature 239)"
        )
    return Path(path)


class NodeExpansion:
    """The worker of record: one call, one selected node, one refined signal.

    Constructed with the deployment's agent seam and the database URL
    the tree lives in; called with one selected node — a node id, the
    element of the batch the policy selected — it performs
    ``CONTINUE(v)`` and answers a :class:`RefinedSignal`.  The callable
    shape is feature 238's contract with it (*"the worker is the
    evaluation — one call per job"*): ``run_batch(expansion, batch,
    width=record.workspace_count)`` runs W of these at once, and the
    closure this instance holds over the agent and the store is the
    very thing *"no pickle can carry"* — why 238's slots are threads.

    The tree half is :meth:`workspace`, public because it is the read
    the resumption *is*: the five structural facts of the selected
    node, refused (naming the node) when the tree holds no such row.
    The seam half is the agent, one call, its answer counted and
    shape-checked; its **exceptions pass through untouched** — an
    interruption must reach the pool as
    :class:`~discovery.errors.WorkerInterrupted` for the retry to
    classify it, and an agent failure must reach it as itself for
    §6.1's step 11 to have charged a real attempt.

    Persists nothing: feature 240's *"including failures"* is the next
    act, and this module's answer ends at the signal evaluation
    consumes.  Holds no cache of workspaces — the row is the workspace,
    and a memo would make "what did the agent resume?" a question about
    this process's history rather than about the tree.
    """

    def __init__(self, agent: Callable[[NodeWorkspace], Any], database_url: str) -> None:
        """Wire the worker: the agent seam, and the tree it resumes from.

        Both are validated here, before any call, because both are
        facts about the *worker* rather than about any one ask: an
        agent that cannot be called fails every slot identically (the
        wrong place for an evaluation to fail, 238's own argument), and
        a URL that is not a non-empty string names no tree.  The path
        is resolved lazily — construction performs no I/O, the
        composition-time contract every store in this workspace keeps.
        """
        if not callable(agent):
            raise ExpansionError(
                f"the agent seam must be callable to expand a node, got "
                f"{agent!r} ({type(agent).__name__}); the agent is what "
                "resumes the workspace and proposes the refinement — one "
                "call per selected node — and a worker wired onto "
                "something that cannot be called is a worker no slot "
                "could run (feature 239)"
            )
        if not isinstance(database_url, str) or not database_url.strip():
            raise ExpansionError(
                f"the expansion needs a database URL naming the tree, got "
                f"{database_url!r}; CONTINUE(v) resumes a workspace the "
                "node table holds, and a worker with no tree to read "
                "names no workspace it could resume (feature 239)"
            )
        self._agent = agent
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building
        # the worker is composition-time work and must not touch disk.
        self._path: Path | None = None

    @property
    def database_url(self) -> str:
        """The database URL this worker reads the tree from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the tree, resolved on first use."""
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the tree's database — read-only in intent, never in DDL.

        No schema is created and none is probed into being: the ``node``
        table is feature 97's, and a worker that invented a tree would
        be resuming workspaces nobody planted.  An absent table is
        :meth:`workspace`'s own named refusal, and a database the
        migration has not reached raises SQLite's own ``no such table``
        for any other read an operator makes.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    # -- The resumption ----------------------------------------------------

    def workspace(self, node_id: Any) -> NodeWorkspace:
        """Read one selected node's workspace — the resumption's tree half.

        The ask is canonicalized, the ``node`` table is probed
        (read-only, the ``sqlite_master`` idiom) so a tree-less store is
        a named refusal rather than a surprise, and the row is read
        column-by-column into a :class:`NodeWorkspace`.  An unknown id
        refuses naming the node: the policy's selection is a prefix
        over the tree the store holds, and an id this store has never
        seen is a selection from a different tree — the one fact this
        module cannot resume its way out of.
        """
        node = _canonical_node_id(node_id, field="node_id")
        with closing(self._connect()) as connection:
            if connection.execute(
                _NODE_TABLE_EXISTS_SQL, ("node",)
            ).fetchone() is None:
                raise ExpansionError(
                    "this database holds no node table, so node "
                    f"{node!r} has no workspace to resume: the tree is "
                    "created by migrations/versions/0118_node_table.py "
                    "(feature 97), and CONTINUE(v) resumes a workspace "
                    "the tree holds — a store with no tree has never "
                    "expanded anything (feature 239)"
                )
            cursor = connection.execute(_WORKSPACE_SQL, (node,))
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            raise ExpansionError(
                f"node {node!r} is not in the tree, so it has no "
                "workspace to resume: the batch selection expands nodes "
                "the tree holds, and an id no row carries is a selection "
                "from a tree this store does not hold (feature 239)"
            )
        return NodeWorkspace(
            node_id=row[0],
            parent_id=row[1],
            campaign_id=row[2],
            theme_root=row[3],
            depth=row[4],
        )

    # -- The verb ------------------------------------------------------------

    def __call__(self, node_id: Any) -> RefinedSignal:
        """Expand one selected node — feature 239's verb, one call.

        ``CONTINUE(v)`` in order: validate the ask (an ask that is not
        a node id refuses before the store is opened or the agent is
        consulted), read the workspace (the resumption — refused,
        naming the node, when the tree does not hold it), call the
        agent with the workspace (**its exceptions pass through
        untouched**), count the answer (exactly one), read the
        construction, and answer the refined signal: the adopted code
        and its hash, the stated mechanism or the honest ``None``, and
        the parentage the tree half carries — the derived id, the
        parent, the inherited campaign and theme, the depth one below.

        Raises :class:`~discovery.errors.ExpansionError` — which
        feature 238's pool captures onto the job's result like any
        failure, so a refused expansion is a value feature 240 logs
        with the rest, never the death of the batch.
        """
        node = _canonical_node_id(node_id, field="node_id")
        workspace = self.workspace(node)
        # The agent's exceptions deliberately span no ``try`` of this
        # module's: an interruption must arrive as WorkerInterrupted
        # and a failure as itself (see the class docstring).
        answer = self._agent(workspace)
        candidate = _one_refinement(answer, node)
        code, mechanism = _validated_construction(candidate, node)
        return RefinedSignal(
            node_id=refined_node_id(workspace.node_id),
            parent_id=workspace.node_id,
            campaign_id=workspace.campaign_id,
            theme_root=workspace.theme_root,
            depth=workspace.depth + 1,
            code=code,
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
            stated_mechanism=mechanism,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(agent={self._agent!r}, "
            f"database_url={self._database_url!r})"
        )


# -- The module-level spelling ------------------------------------------------------


def expand_node(
    agent: Callable[[NodeWorkspace], Any],
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RefinedSignal:
    """Expand one selected node — the module-level spelling.

    Feature 239's sentence as one call, for the caller that wants the
    act without holding a worker: the agent seam and the selected node
    in, the refined signal out.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``; a deployment that
    names neither is refused *by name* rather than silently doing
    nothing, because an expansion that quietly skipped its read would
    hand the agent a workspace nobody resumed — the exact act the
    feature's sentence refuses.

    A :class:`~discovery.errors.DiscoveryError` from the worker is left
    to propagate unwrapped: the refusal already names the node and the
    fact, and re-wrapping it here would put a second message in front
    of the one an operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get("DATABASE_URL", "").strip()
    )
    if not url:
        raise ExpansionError(
            "expand_node expands a selected node and nothing names a "
            "store: DATABASE_URL is unset (and no database_url was "
            "supplied), so the workspace could not be resumed. Feature "
            "239's signal resumes a workspace the tree holds — an "
            "expansion that skipped its read would hand the agent a "
            "blank slate and call it a resumption (feature 239)"
        )
    return NodeExpansion(agent, url)(node_id)
