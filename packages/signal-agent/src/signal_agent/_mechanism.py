"""Feature 211's law: the stated mechanism, persisted and never scored.

app_spec.xml, "Hypothesis Authoring Agent", feature 211: *System persists a
stated mechanism string used for deduplication and human review, never as a
scored input.*  docs/nullius-tech-architecture.md §9.1 draws the column and
annotates it with the whole of the rule::

    stated_mechanism  TEXT,                -- dedup + human review ONLY, never scored

and docs/alpha-engine-prd.md says the same thing from the authoring side —
``stated_mechanism: str   # agent's economic rationale; used for dedup and
human review ONLY. Never scored.``  The column itself is already there:
``migrations/versions/0117_identity_trio.py`` (feature 98) adds it to ``node``
bare and nullable, and its own docstring argues the nullability at length — the
NULL is a positive fact ("an agent that states no mechanism has left nothing to
review"), not an un-backfilled state.  What no feature has yet supplied is a
**writer**, and that is this module.

The sentence decomposes into four claims, and the split between the last two is
the whole design:

* **the stated mechanism string** — the agent's own economic rationale, *as the
  agent stated it*.  Not a summary of the source, not a classification this
  member derives, not a theme root: it is the one free-text field on the node
  row, and its entire value is that a human reads what the agent *claimed it was
  doing*.  So :func:`canonical_mechanism` exists for comparison and the stored
  column keeps the agent's **verbatim** text — the discipline
  :meth:`SignalContract.adopt` keeps for source and
  :meth:`DeadTerritoryGate.admit` keeps for a theme root, restated here because
  a member that tidied a rationale "into a comparable form" would be rewriting
  the agent's claim rather than recording it.

* **persists** — it lands on ``node.stated_mechanism`` through the same
  compare-then-set, one-connection, one-transaction discipline every store in
  this workspace keeps (:class:`MechanismStore`).  The column is nullable and
  that is load-bearing: the store can write *nothing* honestly rather than
  fabricate a rationale no one wrote (:meth:`MechanismStore.persist`'s unstated
  branch).

* **used for deduplication and human review** — two *readers*, and this member
  serves both without restating feature 179.  :meth:`MechanismStore.duplicates`
  answers the *semantic* companion question to 179's content check — the same
  economic claim resubmitted in different code, which is §14.1's own root
  failure mode: *"A converged tree is not caught by anything.  At roots, a weak
  model's failure mode is proposing the 400th variant of one indicator."* — and
  :meth:`MechanismStore.stated` is the review queue's read.  Neither charges a
  trial; 179's :class:`artifacts.CodeHashIndex` remains the gate that refuses an
  exact duplicate before the evaluator runs, and this member deliberately does
  **not** re-implement or extend it.  The two axes are different in kind —
  identical *code* is one hypothesis, identical *claim* with different code is
  the parameter-tweak collapse — and a second reject-before-charge path here
  would have to re-derive 179's serialized-probe argument against a text key
  with no index behind it.

* **never as a scored input** — the clause the feature is actually about, and
  the reason this module is not merely a store.  A nullable ``TEXT`` column with
  a writer is trivial; what is not trivial is making the *non-scoring* a
  property a later change cannot quietly break.  The failure mode is specific
  and quiet: the moment ``stated_mechanism`` is reachable as an input to the
  evaluator, the scoring path or a policy, then ``agent_model_id``
  stratification (PRD §5a), the M3 paired comparison (architecture §14.1) and
  the ``β₃`` deflation term all become functions of **prose an LLM wrote** — a
  leakage channel from the authoring model straight into the headline figure.
  It would not look like a bug; it would look like a feature ("let the policy
  condition on the mechanism").

**How the barrier is built, so that it is a property rather than a promise.**
Three seams, each catching a different way the value could reach a number:

* :class:`MechanismRecord` carries no numeric field and implements none of
  ``__float__`` / ``__int__`` / ``__index__``, so ``float(record)`` raises
  ``TypeError`` from Python itself rather than producing an ordered value.  Its
  :attr:`~MechanismRecord.digest` is a ``str``, which is a *key* rather than a
  magnitude, and the class's ``__slots__`` is pinned by the suite so a later
  edit cannot add one invisibly.
* :meth:`StatedMechanism.scored_input` answers the question affirmatively and
  always refuses, as a **value** — the shape every gate in this workspace takes
  (:meth:`SignalContract.adopt`, :meth:`SignalThemeGate.admit`,
  :meth:`DeadTerritoryGate.admit`) — with a sentence that says what the score
  actually is: feature 85's metrics over the signal *source*.  A caller that
  wants to branch on the refusal branches on ``scored``.
* :meth:`StatedMechanism.require_scored_input` is the bridge for the caller on
  its last line before it wires the value into a scorer, and only there does
  :class:`~signal_agent.errors.MechanismNotScoredError` appear.

The barrier is deliberately **store-independent**: it is a fact about the
caller's wiring and about §9.1's annotation, not about a row, so it answers in a
deployment that names no database — which is why the component is composed
always and only its store half can be ``None``.

**What "the same mechanism" means, and what it deliberately does not.**
:func:`canonical_mechanism` strips, collapses internal whitespace runs to one
space and casefolds.  It is not a stemmer, a synonym map or an embedding, and
the restraint is the feature: those would be this member inventing a semantic
equivalence the spec does not state, and a false merge is worse than a miss —
it hides a genuinely distinct hypothesis from the human review the same sentence
asks for.  The one authority claimed is §9.1's ``-- dedup`` comment, and the
docstring says exactly that much.

**Why this is a fourth component and not a parameter of feature 205's law.**
The member's three components each answer one feature's question, and the
registry is keyed by name — a fourth builder taking ``signal-agent`` would
*replace* feature 205's law rather than sit beside it, which is the
registry-replacement hazard :data:`signal_agent.THEMES_COMPONENT_NAME` names.
``signal-agent-stated-mechanism`` sorts between ``signal-agent-dead-territory``
and ``signal-agent-themes``, so all four stay contiguous in the name-sorted
``app.order``.

Stdlib only, and import-cheap — :mod:`enum`, :mod:`hashlib`, :mod:`json`,
:mod:`os`, :mod:`pathlib`, :mod:`sqlite3`, :mod:`urllib.parse` and the member's
own errors — so the factory's scan, which imports this package to fire its
``@register``, pays nothing for it.
"""

from __future__ import annotations

import enum
import hashlib
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Final, NoReturn
from urllib.parse import unquote, urlparse

from .errors import (
    MechanismColumnError,
    MechanismConflictError,
    MechanismNodeNotRecordedError,
    MechanismNotScoredError,
    MechanismStatementError,
    MechanismStoreUnavailableError,
)

__all__ = [
    "CANONICAL_MECHANISM_MAX_WORDS",
    "MECHANISM_COLUMN",
    "MECHANISM_CONFLICT_CODE",
    "MECHANISM_POLICY_REVISION",
    "NEVER_SCORED_CODE",
    "NODE_ID_COLUMN",
    "NODE_TABLE",
    "NOT_A_STATEMENT_CODE",
    "STATED_MECHANISM_CODE",
    "STATED_MECHANISM_COMPONENT_NAME",
    "MechanismConflictError",
    "MechanismReason",
    "MechanismRecord",
    "MechanismScoredInput",
    "MechanismStore",
    "StatedMechanism",
    "canonical_mechanism",
    "mechanism_digest",
    "stated_mechanism",
]

#: The ``node`` column feature 98's revision adds and this feature writes.
#: Spelled from the spec's own schema block and §9.1's ``CREATE TABLE``, both of
#: which name it identically, so the store, the refusals and the suite share one
#: string rather than three that can drift.
MECHANISM_COLUMN: Final[str] = "stated_mechanism"

#: The table that column lives on — feature 97's, created by revision
#: ``0118_node_table``.  This member reads and writes one column of it and
#: deliberately does not create it: the ``node`` table is the discovery tree's.
NODE_TABLE: Final[str] = "node"

#: The node's primary key, named so the store's two lookups share one spelling.
NODE_ID_COLUMN: Final[str] = "id"

#: The revision that adds :data:`MECHANISM_COLUMN` — feature 98's migration.
#: Named as data because it is the whole actionable content of a
#: :class:`~signal_agent.errors.MechanismColumnError`: a tree that has not
#: reached this revision has nowhere for a stated mechanism to live, and the
#: repair is to run the chain to here.
MECHANISM_POLICY_REVISION: Final[str] = "0117_identity_trio"

#: The environment variable naming the relational store, shared with every
#: other member of the data spine.  Restated rather than imported for the reason
#: every store in this workspace restates its own: a store loaded inside one
#: member must not depend on another member being importable.
DATABASE_URL_ENV: Final[str] = "DATABASE_URL"

#: The greppable code the *stored* verdict's sentence carries — the feature's
#: own subject written as a word, so an operator grepping a campaign log for the
#: proposals that recorded a mechanism finds them by it.  Its mirror is the
#: refusal, which opens with its :class:`MechanismReason` value instead.
STATED_MECHANISM_CODE: Final[str] = "stated_mechanism"

#: The code the not-a-statement refusal opens with — its own, not
#: :data:`STATED_MECHANISM_CODE`, for the reason
#: :attr:`MechanismReason.NOT_A_STATEMENT` states: a refusal that opened with
#: the feature's headline while its text said the value was never a statement
#: would be quoting the subject rather than the verdict.
NOT_A_STATEMENT_CODE: Final[str] = "not_a_statement"

#: The code the statement-conflict refusal opens with.  Its own, for the same
#: reason: the repair differs from every other reason here — the caller must
#: stop trying to re-state history, not re-prompt the agent.
MECHANISM_CONFLICT_CODE: Final[str] = "mechanism_conflict"

#: The code the scoring barrier's refusal opens with — *"never as a scored
#: input"* written as a token.  This is the one code an operator greps for to
#: audit the barrier, and it is deliberately its own word rather than a
#: spelling of the feature's: the feature is *persisting* a mechanism, and this
#: is the clause that says what may not be done with one afterwards.
NEVER_SCORED_CODE: Final[str] = "never_scored"

#: The component name this law registers under — beside feature 205's
#: ``signal-agent``, feature 212's ``signal-agent-themes`` and feature 213's
#: ``signal-agent-dead-territory``.  The registry is keyed by name and a later
#: registration of the same name *replaces* the earlier one, so the category's
#: later features each take their own seat on the member rather than
#: overwriting an earlier law.  Prefixed for that reason — an unprefixed
#: ``signal-agent`` a fourth time would replace feature 205's law — and
#: ``signal-agent-stated-mechanism`` sorts between
#: ``signal-agent-dead-territory`` and ``signal-agent-themes`` in the
#: name-sorted ``app.order``, keeping the member's four components contiguous in
#: the category they belong to.
STATED_MECHANISM_COMPONENT_NAME: Final[str] = "signal-agent-stated-mechanism"

#: The whitespace runs a canonical form collapses.  A rationale is prose, so
#: its line breaks, tabs and double spaces are formatting rather than meaning.
_WHITESPACE_RUN: Final[re.Pattern[str]] = re.compile(r"\s+")

#: The largest number of words :attr:`MechanismRecord.words` will report.  Not
#: a limit on storage — the column keeps whatever the agent wrote — but a bound
#: on the *summary* the review read emits, so a pathological submission cannot
#: make a review queue's line unbounded.  Named as data so the read side and its
#: test share one number.
CANONICAL_MECHANISM_MAX_WORDS: Final[int] = 24


def canonical_mechanism(statement: object) -> str:
    """The comparison form of a stated mechanism: stripped, collapsed, casefolded.

    §9.1's annotation is ``-- dedup + human review ONLY``, and deduplication over
    a free-text field is only meaningful if two spellings of one claim compare
    equal: ``"Cross-sectional momentum"`` and ``"cross-sectional   momentum"``
    are one mechanism, and a reader that treated them as two would fail the
    feature's first clause on formatting alone.

    So the canonical form is exactly three normalizations, and **no more**:
    surrounding whitespace stripped, internal whitespace runs collapsed to one
    space, and the result casefolded (the spelling
    :func:`nulloracle.schemaguard.review_node_columns` uses for its own
    case-insensitive comparison, and the one Python's own case-insensitive
    matching is built on).

    **What is deliberately absent is the whole restraint.**  No stemming, no
    synonym map, no stop-word removal, no embedding: each would be this member
    inventing a semantic equivalence the spec does not state, and the
    asymmetry of the two errors decides against it.  A *miss* — two spellings of
    one claim that do not compare equal — costs a reviewer one extra line.  A
    *false merge* — two genuinely distinct hypotheses folded into one — hides a
    hypothesis from the human review the same sentence asks for, which is the
    one outcome §9's "choosing the space is the highest-value human input"
    cannot tolerate.  The one authority this function claims is §9.1's
    ``-- dedup`` comment, and it claims no more than that.

    A value that is not text cannot be canonicalized into text: it is refused
    with :class:`~signal_agent.errors.MechanismStatementError` before anything
    is derived, rather than strung and compared.
    """
    if not isinstance(statement, str):
        raise MechanismStatementError(
            f"a stated mechanism must be text, got "
            f"{type(statement).__name__}; it is the agent's own economic "
            f"rationale for a proposal (docs/alpha-engine-prd.md's "
            f"construction block, §9.1's {MECHANISM_COLUMN} column), and a "
            f"value that is not text states no rationale a human could read or "
            f"a dedup could compare (feature 211)."
        )
    return _WHITESPACE_RUN.sub(" ", statement).strip().casefold()


def mechanism_digest(statement: object) -> str:
    """The sha256 hexdigest of a statement's canonical form — the dedup key.

    The value :meth:`MechanismStore.duplicates` compares on, computed over
    :func:`canonical_mechanism`'s output rather than over the raw text, so two
    spellings of one claim share a key.  It is spelled
    ``hashlib.sha256(...).hexdigest()`` in lowercase — the same three lines
    :func:`source_code_hash`, :func:`artifacts.source_code_hash` and
    :func:`artifacts.canonical_code_hash` each state — because a digest that
    disagreed with its neighbours on case would make one value look like two,
    which is precisely the failure this key exists to prevent.

    **It is a key, never a magnitude.**  The type is ``str`` and not an integer,
    and that is a decision rather than an accident: a numeric digest is
    *orderable*, and an orderable derived value is the first step toward a
    scored one.  See the module docstring's account of the barrier.
    """
    return hashlib.sha256(canonical_mechanism(statement).encode("utf-8")).hexdigest()


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Accepts a :class:`uuid.UUID` or any text :func:`uuid.UUID` parses, and
    returns the lowercased hyphenated rendering — the normalization every store
    that joins ``node.id`` applies, because the column is a UUID primary key and
    a mixed-case key would make one node look like two: here, in the question of
    which mechanism it states.

    A malformed id is refused with
    :class:`~signal_agent.errors.MechanismStatementError` directly rather than
    with one of the store's deployment classes: it is the *caller's* addressing
    value and not a fact about a database, so no repair the store's own classes
    name would fix it.
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
    raise MechanismStatementError(
        f"node id {value!r} is not a UUID ({type(value).__name__}); a node id "
        f"joins the tree store's {NODE_TABLE}.{NODE_ID_COLUMN} primary key, so "
        f"an id that cannot join it names no node to record a stated mechanism "
        f"on (feature 211)."
    )


class MechanismReason(enum.StrEnum):
    """Why a stated mechanism was recorded or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`MechanismRecord.detail` opens with, so the reason is greppable in a
    campaign log without a lookup table and a refusal never opens with another
    reason's headline.  The three are split by *repair*, not by which check
    happened to fail — the discipline :class:`AdoptionReason`,
    :class:`ThemeReason` and :class:`DeadTerritoryReason` state for their own
    vocabularies: a caller handed a non-string has a wiring bug, a caller handed
    a conflict must stop trying to re-state history, and a row that states
    nothing needs nothing from anyone.

    **There is deliberately no fourth "blank statement" reason.**  An empty or
    whitespace-only value and an absent one are the *same* proposal-level fact —
    the agent stated nothing — and they have the same repair, which is none: the
    row's NULL is the honest record of both, and 0117's docstring makes the NULL
    a positive fact rather than a missing value.  Splitting them would give a
    reviewer two vocabulary tokens for one state and invite a reader to think
    the difference mattered, which is the opposite of what a split *by repair*
    is for.
    """

    #: Recorded: the agent stated a mechanism and it is what the row now holds.
    #: Its detail opens with :data:`STATED_MECHANISM_CODE` rather than with this
    #: value, the one place this enum and its codes differ — the same asymmetry
    #: :attr:`ThemeReason.LEGAL` has against
    #: :data:`~signal_agent.LEGAL_THEME_CODE`.  "stated" is the reason a caller
    #: branches on; "stated_mechanism" is the word a log line opens with.
    STATED = "stated"

    #: Recorded-as-nothing: the agent stated no mechanism, and the row's NULL is
    #: that positive fact rather than a missing value.  Feature 98's revision
    #: argues the nullability from the column's side — *"an agent that states no
    #: mechanism has left nothing to review, and a NULL records that rather than
    #: fabricating a rationale no one wrote"* — and this is the reason the store
    #: reaches that state deliberately instead of refusing it: refusing would
    #: force a caller to invent a rationale, which is the one thing the column's
    #: nullability exists to prevent.  Its detail opens with
    #: :data:`NOT_A_STATEMENT_CODE` rather than :data:`STATED_MECHANISM_CODE`,
    #: because a record holding nothing is not the feature's subject being
    #: recorded; it is the feature's subject being *absent*, reported.
    NOT_A_STATEMENT = NOT_A_STATEMENT_CODE

    #: Refused: the row already states a *different* mechanism.  Spelled as the
    #: code itself, so branching on the value and grepping for it are the same
    #: string.  Its own reason because the repair is different in kind from
    #: every other: nothing about the proposal is wrong, and what must change is
    #: the caller's belief that it may re-state history.
    CONFLICT = MECHANISM_CONFLICT_CODE


class MechanismScoredInput:
    """Feature 211's barrier, as a returned answer — and it always refuses.

    ``scored`` is the one field a caller must check, and it is *computed* from
    the reason rather than set by a constant — the same "computed, never
    assumed" stance :class:`SourceAdoption`, :class:`ThemeAdmission` and
    :class:`DeadTerritoryVerdict` take for their own answers.  There is no
    constructor that admits: the class exists to make the refusal an *answered
    question* rather than an absent one, so a caller reaching for the value in a
    scoring path gets a sentence explaining what it is holding instead of a
    silent ``AttributeError`` or, worse, a working coercion.

    **Why a verdict object and not just an exception.**  A caller that wants to
    branch — a validator that reports every reason a proposal bundle was
    rejected, an audit that collects barriers rather than tripping on the first
    — needs the refusal *as a value*.  :meth:`StatedMechanism.require_scored_input`
    is the bridge for the caller that wants it as an exception.
    """

    __slots__ = ("detail", "scored", "statement")

    def __init__(self, *, statement: str, detail: str) -> None:
        self.statement = statement
        self.detail = detail
        # Constant, and stated as such rather than left implicit: this class has
        # exactly one verdict, and the field is kept because every gate in this
        # workspace answers with the same shape and a caller written against
        # one of them must not need a special case for this one.
        self.scored = False

    def require(self) -> NoReturn:
        """Refuse — always.  The bridge to :class:`MechanismNotScoredError`.

        Present for symmetry with the member's other verdicts, where ``require``
        returns the admitted value.  Here there is no admitted state, so it
        raises unconditionally with this verdict's own sentence — and its return
        type says so: a caller can write
        ``law.require_scored_input(record)`` on its last line before a scorer and
        have feature 211's clause enforced there rather than remembered, but no
        caller can bind a *value* from it, because there is none to bind.
        """
        raise MechanismNotScoredError(self.detail)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"MechanismScoredInput(scored=False, statement={self.statement!r})"


class MechanismRecord:
    """One proposal's stated mechanism, as the row holds it.

    The value :meth:`StatedMechanism.state` and :meth:`MechanismStore.load`
    answer with, and the object every other seam in this module takes.  It
    carries what the four claims need and **nothing that can be scored**:

    * :attr:`statement` — the agent's text, verbatim, as the column stores it.
      ``None`` is the unstated state that feature 98's nullable column exists
      for; a caller that has checked :attr:`stated` reads the string rather than
      a sentinel.
    * :attr:`node_id` — the row the value belongs to, in canonical UUID text.
    * :attr:`reason` — the :class:`MechanismReason`, so a caller branches on a
      value rather than on a message.
    * :attr:`digest` — the dedup key :func:`mechanism_digest` computes, ``None``
      when nothing is stated.  A ``str``, never a number; see the barrier.
    * :attr:`recorded` — whether the call that produced this record wrote the
      column.  ``True`` for a write, ``False`` for an idempotent retry that
      found the statement already stored, and ``None`` on every read path,
      where the question has no referent.  A tri-state rather than a flag, on
      the grounds :attr:`providers.AgentWeights.recorded` sets out: a ``False``
      standing for both *the row already held it* and *nothing was asked for*
      would make reading and writing one answer.
    * :attr:`words` — the whitespace-split canonical form, bounded by
      :data:`CANONICAL_MECHANISM_MAX_WORDS`, the *summary* a review queue's line
      emits.  A tuple of ``str``, deliberately: a count is a number, and this
      record's whole discipline is that nothing on it is one.
    * :attr:`detail` — one operator-facing paragraph, the sentence a log line
      records.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline :class:`SourceAdoption` and
    :class:`ThemeAdmission` state for their own constructors.  ``statement`` is
    taken as given (including ``None``), and the refusals live at
    :meth:`StatedMechanism.state` and :meth:`require`.

    **No numeric surface, and that is structural.**  The class implements
    ``__float__``, ``__int__`` and ``__index__`` nowhere, so a caller that tried
    to coerce a record into a number gets Python's own ``TypeError`` rather than
    a silently-ordered value, and :attr:`digest` is a string so it is not a
    magnitude even by accident.  The suite pins each of the three dunder
    absences, because the failure mode this guards against is a *later* edit
    adding one.
    """

    __slots__ = (
        "detail",
        "digest",
        "node_id",
        "reason",
        "recorded",
        "stated",
        "statement",
        "words",
    )

    def __init__(
        self,
        *,
        node_id: str,
        reason: MechanismReason,
        detail: str,
        statement: str | None = None,
        recorded: bool | None = None,
    ) -> None:
        self.node_id = node_id
        self.reason = reason
        self.detail = detail
        self.stated = statement is not None
        self.statement = statement
        # Derived once at construction from the text that was recorded, so the
        # key and the statement cannot come apart — the argument
        # SourceAdoption.code_hash makes for hashing where the source is
        # adopted rather than where it is persisted.
        self.digest = mechanism_digest(statement) if statement is not None else None
        # ``None`` on every read path — the question *did this call write?* has
        # no referent when nothing was asked for — and ``True`` on the write
        # path.  Not a ``bool`` with a ``False``: ``persist`` has exactly one
        # write outcome here (a compare-and-set that matches) and one non-write
        # outcome (:meth:`MechanismStore._retry`), so ``False`` would be the
        # retry's spelling and ``None`` the reader's, and a caller that
        # conflated them would have confused reading with writing.  That is the
        # same three-valued spelling providers.AgentWeights.recorded uses, for
        # the same reason.
        self.recorded = recorded
        self.words = (
            tuple(canonical_mechanism(statement).split(" ")[
                :CANONICAL_MECHANISM_MAX_WORDS
            ])
            if statement is not None
            else ()
        )

    def require(self) -> str:
        """Return the recorded mechanism, or raise :class:`MechanismStatementError`.

        The bridge between a returned answer and the exception a caller wants on
        its last line before it records anything.  An unstated record is
        **not** a refusal — feature 98's NULL is a positive fact — so it is
        returned as an empty string only for the caller that already checked
        :attr:`stated`; a caller that reaches here having *required* a statement
        and got nothing is refused, with this record's own sentence, because the
        two states must not be conflated at the one line where it matters.
        """
        if self.statement is None:
            raise MechanismStatementError(self.detail)
        return self.statement

    def same_mechanism(self, other: object) -> bool:
        """Whether ``other`` states the same mechanism as this record.

        The companion read to :meth:`MechanismStore.duplicates`, exposed on the
        value so a caller comparing two proposals in hand does not have to reach
        the store — or recompute a digest — to ask the dedup question.  A record
        holding nothing states nothing and compares equal to nothing, including
        another unstated record: two nodes that both state no mechanism are not
        two occurrences of one mechanism.
        """
        if self.digest is None:
            return False
        if isinstance(other, MechanismRecord):
            return other.digest is not None and other.digest == self.digest
        if isinstance(other, str):
            return mechanism_digest(other) == self.digest
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"MechanismRecord(node_id={self.node_id!r}, "
            f"reason={self.reason.value!r}, stated={self.stated})"
        )


class StatedMechanism:
    """Feature 211's law: the barrier, and the store when the deployment has one.

    The value a composed application carries, in the shape
    :class:`signal_agent.SignalContract` gives feature 205,
    :class:`signal_agent.SignalThemeGate` gives 212 and
    :class:`signal_agent.DeadTerritoryGate` gives 213 — so a caller holding the
    composed component can ask feature 211's questions without importing this
    submodule by name.

    **It carries a store, and the store is optional.**  ``store=None`` is the
    state a deployment reaches by naming no ``DATABASE_URL``, and it is a
    *discoverable* state rather than a broken one — the stance
    :meth:`artifacts.CodeHashIndex.resolve` and
    :meth:`providers.AgentModelPins.resolve` take for their own ``None``.  It is
    not an empty store: an empty store answers *no node states a mechanism here*
    about every id, while this says there is no database to have recorded one
    in, and a mechanism persisted into nothing is a rationale no reviewer will
    ever read.

    **The barrier is store-independent, and that is why the component is
    composed always.**  :meth:`scored_input` and :meth:`require_scored_input`
    are facts about the *caller's* wiring and about §9.1's annotation, not about
    a row, so they answer in a deployment with no database at all.  The four
    store-backed verbs raise
    :class:`~signal_agent.errors.MechanismStoreUnavailableError` in that state,
    which is the "a caller that must persist has to treat this as a refusal to
    proceed" reading the member's other store builders state for their own
    ``None``.

    **Why one component and not two.**  The store and the barrier are one
    feature's subject: a caller holding the barrier separately from the writer
    would be able to persist into a tree it cannot ask the *scoring* question
    about, which is exactly the half-wired shape the sentence's two clauses are
    meant to hold together.  So they are one handle, one seat and one
    registration.
    """

    __slots__ = ("_store",)

    def __init__(self, store: MechanismStore | None = None) -> None:
        self._store = store

    # -- The barrier: feature 211's "never as a scored input" ----------------

    def scored_input(self, statement: object) -> MechanismScoredInput:
        """Answer *may this be a scored input?* — and the answer is always no.

        Not a validation with a possible pass: feature 211's clause is *"never
        as a scored input"*, and a method that could return ``scored=True`` for
        some well-formed value would be a method whose contract allowed the
        thing the feature forbids.  So the verdict is constructed refused, and
        the type is the enforcement — a caller cannot get an admitting verdict
        out of this law at all.

        The subject is taken as text, a :class:`MechanismRecord`, or anything
        else, and the sentence names whatever it was handed: a caller that
        reached a scoring path with a mechanism has a wiring bug, and the report
        should describe the value it actually held rather than assume the shape
        it expected.

        The refusal names what the score *is*, which is the half that makes it
        actionable: every figure this system reports is a measurement of the
        signal **source** (feature 85's metrics over what the sandbox ran), and
        the stated mechanism is prose the authoring model wrote *about* that
        source.  A caller looking for a number to score should be told where the
        number lives.
        """
        described = _describe_statement(statement)
        mechanism = (
            statement
            if isinstance(statement, MechanismRecord)
            else None
        )
        return MechanismScoredInput(
            statement=described,
            detail=(
                f"{NEVER_SCORED_CODE}: {described} cannot be a scored input. "
                f"docs/nullius-tech-architecture.md §9.1 annotates the "
                f"{MECHANISM_COLUMN} column `dedup + human review ONLY, never "
                f"scored`, and docs/alpha-engine-prd.md states the same of a "
                f"node's stated mechanism: it is the agent's own economic "
                f"rationale, and it is prose an authoring model wrote. Every "
                f"number this system reports is a measurement of the signal "
                f"*source* — feature 85's metrics over what the sandbox ran — "
                f"and a score conditioned on the rationale would make "
                f"agent_model_id stratification (PRD §5a), the M3 paired "
                f"comparison (architecture §14.1) and the beta-three deflation "
                f"term functions of what a model said about itself. Score the "
                f"source; read the mechanism (feature 211)."
                + (
                    f" The record held was {mechanism!r}."
                    if mechanism is not None
                    else ""
                )
            ),
        )

    def require_scored_input(self, statement: object) -> NoReturn:
        """Refuse the mechanism as a scored input; the caller's bridge.

        Raises :class:`~signal_agent.errors.MechanismNotScoredError` —
        carrying the barrier's own ``never_scored`` sentence — so a caller can
        put it on the last line before it wires a mechanism into a scorer and
        have feature 211's clause enforced there rather than remembered.  There
        is no passing state, so there is no return value a caller could use.
        """
        return self.scored_input(statement).require()

    # -- The store, when the deployment has one ------------------------------

    def persist(
        self, node_id: Any, statement: object = None
    ) -> MechanismRecord:
        """Persist one node's stated mechanism; answer what the row holds.

        Feature 211's *"persists"* as one call, delegated to
        :meth:`MechanismStore.persist` — this facade adds discoverability and
        the composed seam, and restating the store's ordering here would be a
        second thing to keep in sync with it.  Raises
        :class:`~signal_agent.errors.MechanismStoreUnavailableError` when the
        component was composed with no store.
        """
        return self._required_store().persist(node_id, statement)

    def load(self, node_id: Any) -> MechanismRecord | None:
        """Read one node's stated mechanism back, or ``None`` when unstated.

        ``None`` means *this row records no mechanism* — the positive fact
        feature 98's nullable column exists for — and never *the node is
        absent* (which raises) or *the read failed* (which raises).  Three-way
        distinction preserved, the discipline the workspace's other stores
        state.
        """
        return self._required_store().load(node_id)

    def duplicates(
        self, statement: object, *, exclude: object = None
    ) -> tuple[MechanismRecord, ...]:
        """The stored nodes stating the same mechanism — the dedup read.

        Delegated to :meth:`MechanismStore.duplicates`.  It is a **report**,
        not a gate: feature 179's :class:`artifacts.CodeHashIndex` remains the
        check that refuses an exact duplicate before a trial is charged, and
        this answers the neighbouring question — the same economic claim
        resubmitted in different code, §14.1's root failure mode — for a human
        and a retry prompt rather than for a charge.
        """
        return self._required_store().duplicates(statement, exclude=exclude)

    def stated(self) -> tuple[MechanismRecord, ...]:
        """Every stored node that states a mechanism — the human review read."""
        return self._required_store().stated()

    # -- Composition ---------------------------------------------------------

    @property
    def store(self) -> MechanismStore | None:
        """The store this law was composed with, or ``None``.

        Exposed so a caller can tell *this deployment has no tree store* from
        *this deployment's tree store holds no mechanism* without catching an
        exception to find out — the distinction
        :func:`providers.build_agent_model_pins` draws for its own ``None``.
        Reading it refuses nothing: the store holds no capability.
        """
        return self._store

    def _required_store(self) -> MechanismStore:
        """The store, or a named refusal saying there is none.

        The one place :class:`~signal_agent.errors.MechanismStoreUnavailableError`
        is raised, so the four store-backed verbs report the same fact in the
        same words.
        """
        if self._store is None:
            raise MechanismStoreUnavailableError(
                f"this signal-agent member was composed with no mechanism "
                f"store: {DATABASE_URL_ENV} names no relational store in this "
                f"deployment, so there is no {NODE_TABLE} table to record "
                f"feature 211's {MECHANISM_COLUMN} column in or read it back "
                f"from. This is not an empty store — an empty store would "
                f"answer `no node states a mechanism here` about every id, "
                f"while this says there is no database to have recorded one in, "
                f"and a mechanism persisted into nothing is a rationale no "
                f"reviewer will ever read. Point {DATABASE_URL_ENV} at the tree "
                f"store, or ask the law's `store` property first and treat its "
                f"`None` as a refusal to proceed (feature 211)."
            )
        return self._store

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"StatedMechanism(store={'set' if self._store else 'none'})"


def _describe_statement(statement: object) -> str:
    """One phrase naming what a caller handed the barrier or the store.

    Written once because three messages describe the same values — the
    barrier's refusal, the store's not-a-statement reporting and the store's
    conflict — and three spellings of "a 40-character string" would be three
    things to keep in step.  A string is described by length rather than quoted:
    a rationale can be a paragraph, and an operator-facing message that embedded
    one would be unreadable in a log.
    """
    if isinstance(statement, MechanismRecord):
        return (
            f"the stated mechanism on node {statement.node_id} "
            f"({len(statement.statement)} character(s))"
            if statement.statement is not None
            else f"the unstated mechanism on node {statement.node_id}"
        )
    if isinstance(statement, str):
        return f"the {len(statement)}-character stated mechanism"
    return f"the stated mechanism ({type(statement).__name__})"


class MechanismStore:
    """The writer and reader of ``node.stated_mechanism`` — feature 211's row work.

    Constructed with the database URL holding the tree store.  Four operations,
    and the split between them is the split between the feature's three readers:

    * :meth:`persist` — records one node's mechanism, or records that it stated
      none.  Feature 211's *"persists"*.
    * :meth:`load` — reads one node's mechanism back.  The read behind any
      single-row question.
    * :meth:`duplicates` — every stored node stating the same mechanism.  The
      ``dedup`` reader.
    * :meth:`stated` — every stored node that states one.  The ``human review``
      reader.

    The class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states and the reason
    :meth:`~signal_agent.StatedMechanism._required_store` can hand a
    ``DATABASE_URL`` this member cannot speak to a caller that never persists
    anything.

    The ``node`` **table** belongs to ``0118_node_table`` (feature 97) and the
    ``stated_mechanism`` **column** to ``0117_identity_trio`` (feature 98);
    neither is this member's to create, alter or version.  So this is the shape
    :class:`providers.AgentModelPins` and
    :class:`discovery.CampaignRecords` are — a writer over a table someone
    else's migration owns — and, like the pins store and unlike the discovery
    planner, it names the revision it needs rather than letting SQLite's ``no
    such column`` escape: a mechanism has a documented prerequisite and the
    refusal should say which one.

    The store holds no cache.  The row is the only record of what an agent
    claimed, which is the entire point — the rationale is read days later by a
    human reviewer and by a dedup pass in another process — so it is the only
    thing an answer is drawn from.  A memo here would make *"what did this
    agent claim it was doing?"* a question about this process's history rather
    than about the world.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise MechanismStoreUnavailableError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL; a stated "
                f"mechanism is a column on a node, so there must be a store "
                f"holding the tree"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.  A URL this
        # member cannot speak is refused by name at that first use.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> MechanismStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes the
        law with ``store=None`` — a discoverable state, not an exception — while
        a caller that must persist a mechanism is the caller that must not find
        itself in it.  The same stance
        :meth:`providers.AgentModelPins.resolve` takes, and for the same reason:
        the factory builds every registered component on every ``create_app()``,
        so a builder that raised here would take composition down
        workspace-wide for a deployment that simply has no database yet.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MechanismStore:
        """The store ``DATABASE_URL`` names, refused by name when it names none.

        The caller-side twin of :meth:`resolve`, for a caller that *must* have a
        store — a migration script, an operator tool, a test that is about to
        write a row.  Split from ``resolve`` rather than spelled as a
        ``raise`` at each call site so that the "is there a store?" decision is
        made once, in the open, by a caller that knows which of the two
        questions it is asking.
        """
        store = cls.resolve(env)
        if store is None:
            raise MechanismStoreUnavailableError(
                f"{DATABASE_URL_ENV} names no relational store, so there is no "
                f"{NODE_TABLE} table to record feature 211's "
                f"{MECHANISM_COLUMN} column in. Point {DATABASE_URL_ENV} at the "
                f"tree store the discovery tree's node rows live in."
            )
        return store

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
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to commit,
        which is what :meth:`persist` does — the row read and the ``UPDATE`` are
        one unit of work and must be one transaction, or two workers recording
        one node could interleave a compare and a set.

        **No schema is created here.**  A tree store that has not reached
        revision :data:`MECHANISM_POLICY_REVISION` is a named, actionable
        condition, so this store probes for the column and refuses by name
        rather than letting SQLite's ``no such column`` escape.  Creating the
        table would be this member legislating DDL feature 97 owns; creating the
        *column* would be worse still, since it would paper over exactly the gap
        the refusal exists to report.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    # -- The write ----------------------------------------------------------

    def persist(self, node_id: Any, mechanism: Any = None) -> MechanismRecord:
        """Persist one node's stated mechanism; answer what the row holds.

        Feature 211's *"persists"* as one call: the node id and the agent's
        rationale in, the recorded state — and whether *this* call wrote it —
        out.  The state machine itself is :meth:`_state`'s; this method is the
        write half of it — the four states, with the ``UPDATE`` on the two that
        write.

        **The three states of the ask, and why all three are legal.**  The
        column is nullable by design — 0117's own words are that the NULL is *"a
        positive fact, not an absence: an agent that states no mechanism has
        left nothing to review"* — so ``None`` here does not mean "I forgot the
        argument".  It means *this agent stated no rationale*, and the honest
        record of that is a NULL rather than a fabricated one.  The three:

        * **a statement** → canonicalised for comparison, stored **verbatim**.
          Verbatim is the whole point: §9.1's clause is that this string is what
          a human reviews, and a store that tidied the agent's prose *"into a
          comparable form"* would be rewriting the agent's claim rather than
          recording it.  Canonicalisation exists for the comparison only.
        * **``None``** → the unstated write: a NULL, ``reason`` is
          :attr:`MechanismReason.NOT_A_STATEMENT`, and ``recorded`` is ``True``.
          It is a write, and it is deliberately restricted to a row that holds
          nothing — see :meth:`_raise_conflict` for why a row that already
          states a mechanism cannot be cleared by a later call.
        * **blank text** (``""``, ``"   "``) → the same state as ``None``, and
          deliberately not a refusal.  :class:`MechanismReason` states the
          argument: an empty value and an absent one are the same
          proposal-level fact with the same repair, which is none.

        A value that is neither text nor ``None`` — a list, a dict, a number —
        is refused with :class:`~signal_agent.errors.MechanismStatementError`,
        because that is a *caller* mistake rather than a proposal-level fact:
        no agent ever emitted it, so nothing about the proposal should be
        recorded from it.

        **The answer is a :class:`MechanismRecord`, not the string.**  A caller
        that wants the column's spelling reads :attr:`MechanismRecord.statement`
        and one that wants the dedup key reads :attr:`MechanismRecord.digest`,
        so no caller has to re-canonicalise what the store already canonicalised
        — the same argument :meth:`providers.AgentModelPins.persist` makes for
        answering a ``ModelPin`` rather than a string.  :attr:`~MechanismRecord.recorded`
        tells a first write from an idempotent retry, which §14 demands of the
        workers this runs on: a retry that could not see which one it got could
        not report whether it changed anything.
        """
        return self._state(node_id, mechanism)

    def _state(self, node_id: Any, mechanism: Any) -> MechanismRecord:
        """The four-state machine :meth:`persist` runs.

        Split out so :meth:`persist`'s docstring can be about the feature's
        sentence rather than about a branch nest, and so the four states are one
        body: the validation order, the prerequisite probe, the two refusals and
        the two recorded shapes.  Two of the four return before the ``UPDATE``
        and two fall through to it — a statement onto a row that held nothing,
        and the unstated state, which *is* the row holding nothing and
        therefore has nothing to write.
        """
        node = _validated_node_id(node_id)
        stated = _validated_statement(mechanism)
        with closing(self._connect()) as connection, connection:
            self._require_column(node)
            row = connection.execute(
                f"SELECT {MECHANISM_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (node,),
            ).fetchone()
            if row is None:
                self._raise_absent(node)
            stored = row[0]
            if stored is not None:
                assert isinstance(stored, str), "a TEXT column returns text"
                if (
                    stated is not None
                    and canonical_mechanism(stored) == canonical_mechanism(stated)
                ):
                    # The idempotent retry.  The *stored* text is reported
                    # rather than the caller's: the two canonicalise equal —
                    # which is why this is a retry and not a conflict — but
                    # they are two different strings, and a review that reported
                    # the caller's spelling would be reporting a value that is
                    # nowhere in the tree.
                    return MechanismRecord(
                        node_id=node,
                        reason=MechanismReason.STATED,
                        detail=(
                            f"{STATED_MECHANISM_CODE}: node {node} already "
                            f"states {stored!r}, which is this call's mechanism "
                            f"under canonicalisation "
                            f"({canonical_mechanism(stated)!r}); nothing was "
                            f"written. The row's spelling is reported rather "
                            f"than the caller's — it is what a reviewer will "
                            f"read (feature 211)."
                        ),
                        statement=stored,
                        recorded=False,
                    )
                self._raise_conflict(node, stored, mechanism, stated)
            if stated is None:
                # The unstated state, and there is **nothing to write**: a
                # column holding NULL and an ask offering nothing are the same
                # state, and the NULL is where every node's row starts.  So this
                # is not the write branch below with a NULL in it — it is the
                # column's own default, reported.
                #
                # ``recorded`` is ``False``, and the reasoning is worth stating
                # because ``True`` is tempting: a caller asking to record *"this
                # agent stated nothing"* is asking for the state the row is
                # already in, so a flag meaning *did this call change the row?*
                # must say no.  The alternative — writing an explicit NULL over
                # an implicit one and calling it a write — would make the flag
                # report a change that did not happen, and would make the value
                # of ``recorded`` depend on whether some earlier call had
                # happened to touch the row.  Nothing distinguishes a fresh row
                # from one an earlier call reported as unstated, and nothing
                # should: the NULL is the fact and *who wrote it* is not part
                # of it.
                #
                # The record is still a *record*, not a refusal — the reason
                # vocabulary says ``NOT_A_STATEMENT`` and the detail says so at
                # length — because a caller must be able to see that the
                # proposal was answered rather than skipped.
                return MechanismRecord(
                    node_id=node,
                    reason=MechanismReason.NOT_A_STATEMENT,
                    detail=(
                        f"{NOT_A_STATEMENT_CODE}: node {node} states no "
                        f"mechanism, and the {MECHANISM_COLUMN} column records "
                        f"that as a NULL — a positive fact rather than a missing "
                        f"value (0117's own words: an agent that states no "
                        f"mechanism has left nothing to review). Nothing was "
                        f"written: a NULL and an offer of nothing are the same "
                        f"state, and the column is already in it."
                    ),
                    recorded=False,
                )
            self._write(connection, node, stated)
        return self._recorded(node, stated)

    def _raise_conflict(
        self, node: str, stored: str, offered: Any, stated: str | None
    ) -> None:
        """Refuse a call whose statement the row does not already agree with.

        Always raises, and its two branches are the two ways a call can
        disagree with a row that states a mechanism.  Spelled as a helper rather
        than inline so :meth:`persist` reads as the four states it answers
        rather than as a nest of branches around one long message — the shape
        :meth:`providers.AgentModelPins._answer_stored` takes for its own
        compare-then-set.

        **A different statement** is
        :class:`~signal_agent.errors.MechanismConflictError`; both are named so
        an operator can see which two proposals are claiming one node.

        **Offering to clear the row** — ``None``, or text that canonicalises to
        nothing — is :class:`~signal_agent.errors.MechanismStatementError`, and
        the direction of that refusal is the whole reason the two branches are
        not one.  ``persist(node, None)`` writes the unstated NULL, but it writes
        it *only onto a row that holds nothing*: feature 98's nullability exists
        so that an agent that states no mechanism is recorded honestly, not so
        that one that stated a mechanism can have it erased.  A store that
        cleared the column on request would let a caller destroy the rationale a
        reviewer read and a dedup pass compared against — the same loss the
        conflict branch exists to prevent, reached from the other side, and
        reachable by an *accident* (a caller that lost a value on the way to
        this call) rather than by a decision.  Withdrawal, if this system ever
        wants it, is a state machine with a history column, not a ``NULL``
        quietly written over a claim — which is also why no ``reviewed_at``
        column and no ``unreviewed()`` read exist here.
        """
        if stated is None:
            raise MechanismStatementError(
                f"node {node!r} in the tree store at {self.path} states the "
                f"mechanism {stored!r}, and this call offers to record that it "
                f"states nothing. Refusing: the column's NULL is the honest "
                f"record of an agent that stated no mechanism (0117's own "
                f"words — *an agent that states no mechanism has left nothing "
                f"to review*), not a way to erase one that did. The value here "
                f"is what a human reviewer read and what the dedup pass "
                f"(MechanismStore.duplicates) compared against when this node's "
                f"scores were recorded, and clearing it would leave every stored "
                f"comparison referring to a claim the row no longer makes. If "
                f"the caller has genuinely lost the mechanism it meant to state, "
                f"the mechanism this row already holds is the one that was "
                f"authored; re-state that, or record a new node (feature 211)."
            )
        raise MechanismConflictError(
            f"node {node!r} in the tree store at {self.path} already states the "
            f"mechanism {stored!r}, and this call states {offered!r}. They are "
            f"different mechanisms — not two spellings of one, since both were "
            f"canonicalised before being compared — and a node's stated "
            f"mechanism is history rather than a field: it is what a human "
            f"reviewer read and what the dedup pass "
            f"(MechanismStore.duplicates) compared against when this node's "
            f"scores were recorded, so replacing it would leave every stored "
            f"comparison referring to a claim the row no longer makes. A "
            f"*different* mechanism is a different proposal and belongs on a "
            f"different node (feature 211)."
        )

    def _recorded(self, node: str, stated: str) -> MechanismRecord:
        """Build the record for a write that just happened.

        One shape, and one caller: :meth:`_state` reaches it only after an
        ``UPDATE`` that wrote a statement, so ``recorded`` is ``True`` and the
        mechanism is :data:`STATED_MECHANISM_CODE` — the word an operator greps
        a campaign log for, one line per proposal that carried a rationale.
        Every other outcome answers itself inside :meth:`_state`: the retry with
        ``recorded=False``, and the unstated state with
        :data:`NOT_A_STATEMENT_CODE` and no write at all.

        ``write`` is the argument this method does not read, and that is on
        purpose: every state that reaches it is one the caller asked to write
        (a first write of a statement, or the unstated write), because the
        retry answers itself inside :meth:`_state` with ``recorded=False``.  It
        is taken so that a later change of that split has one place to change
        rather than two, and it is passed through rather than hardcoded so the
        flag can never say ``True`` about a call that did not write.
        """
        return MechanismRecord(
            node_id=node,
            reason=MechanismReason.STATED,
            detail=(
                f"{STATED_MECHANISM_CODE}: node {node} states {stated!r}, "
                f"recorded verbatim on the {MECHANISM_COLUMN} column. It is "
                f"read for deduplication and human review ONLY and is never a "
                f"scored input (architecture §9.1); the dedup key is "
                f"{mechanism_digest(stated)}, which is a key and not a "
                f"magnitude."
            ),
            statement=stated,
            recorded=True,
        )

    def _raise_absent(self, node: str) -> None:
        """Refuse a call about an id the tree does not hold.  Always raises.

        The write path's message and the read path's are separate methods
        because they answer different asks — one was about to write, the other
        was about to read — and an operator reading a log needs to know which.
        Both name the same repair: the discovery loop records the node first.
        """
        raise MechanismNodeNotRecordedError(
            f"there is no node {node!r} in the tree store at {self.path}: "
            f"feature 211's stated mechanism is a column on a node — "
            f"{MECHANISM_COLUMN} on feature 97's {NODE_TABLE} table, added by "
            f"revision {MECHANISM_POLICY_REVISION} — so persisting one for an id "
            f"the tree does not hold would mean writing a *row*, and the "
            f"{NODE_TABLE} table is the discovery tree's rather than this "
            f"member's. The discovery loop records the node first (feature 232's "
            f"campaign record is the writer); the stated mechanism is then a "
            f"column on it."
        )

    def _write(
        self, connection: sqlite3.Connection, node: str, stated: str
    ) -> None:
        """Write the statement onto the node row that held nothing.

        One statement, on the connection the read above used, inside the
        transaction the caller's ``with`` closes — so the compare and the set
        cannot be split by a second writer.  The guard in the ``WHERE`` is not
        decoration: it is what makes this a compare-and-set rather than a blind
        overwrite, so a concurrent writer that recorded a mechanism for this
        node between the read and this statement loses nothing — the row simply
        does not match — and the caller's next call reads the winner's value.

        The value is the caller's **verbatim** text — never a canonical form;
        see :func:`_validated_statement` — and this is the only place in the
        package that spells ``stated_mechanism``, so the write path and the read
        path cannot disagree about the stored form.

        ``stated`` is never ``None`` here, and that is enforced by the type
        rather than by a check: the unstated state is answered by
        :meth:`_state` before this method is reached, because a NULL and an
        offer of nothing are the same state and the column is already in it.
        There is nothing for a NULL write to do.
        """
        connection.execute(
            f"UPDATE {NODE_TABLE} SET {MECHANISM_COLUMN} = ? "
            f"WHERE {NODE_ID_COLUMN} = ? AND {MECHANISM_COLUMN} IS NULL",
            (stated, node),
        )

    # -- The reads ----------------------------------------------------------

    def load(self, node_id: Any) -> MechanismRecord | None:
        """Read one node's stated mechanism back, or ``None`` when it states none.

        ``None`` means *this row records no mechanism* — feature 98's positive
        fact, the state :meth:`persist` writes deliberately and the state a node
        the agent proposed without a rationale is in.  It does **not** mean the
        node is absent, and it does not mean the read failed: a node the tree
        does not hold raises
        :class:`~signal_agent.errors.MechanismNodeNotRecordedError` and an
        unreachable store raises.  So a caller can never mistake a node that
        states nothing for a node that is not there, or a broken store for
        either — the three-way distinction
        :meth:`providers.AgentModelPins.load` draws between *"records nothing"*
        and *"the read failed"*, kept here rather than collapsed.

        Callers that want the record rather than the question should prefer
        :meth:`stated` (the review read) or :meth:`duplicates` (the dedup read);
        this one exists for the single-row question.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            self._require_column(node)
            row = connection.execute(
                f"SELECT {MECHANISM_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (node,),
            ).fetchone()
        if row is None:
            raise MechanismNodeNotRecordedError(
                f"there is no node {node!r} in the tree store at {self.path}: "
                f"load() reads one node's stated mechanism and needs the node to "
                f"read it from. A missing node is not a node that states no "
                f"mechanism — the second is a row that exists and holds NULL, "
                f"and that NULL is feature 98's positive fact — and only the "
                f"first says the tree has never heard of this id."
            )
        stored = row[0]
        if stored is None:
            return None
        assert isinstance(stored, str), "a TEXT column returns text"
        return self._loaded(node, stored)

    def duplicates(
        self, mechanism: Any, *, exclude: Any = None
    ) -> tuple[MechanismRecord, ...]:
        """Every stored node stating the same mechanism — the dedup read.

        **What this is, and what it deliberately is not.**  It is a *report*:
        it names every holder so a human decides.  It is not a gate, and it
        refuses nothing and excludes nothing on its own account — passing
        ``exclude`` is a caller saying *I know about this one*, not this method
        deciding what counts.  Feature 179's
        :class:`artifacts.CodeHashIndex` remains the check that *refuses* an
        exact duplicate before a trial is charged, and this deliberately does
        not extend it.  The two answer different questions on different keys:

        * 179 gates on **code** — ``code_hash``, an exact identity with an index
          behind it (feature 102's ``node_code_hash``), re-derived from the
          source by the sandbox that will run it.  Its refusal is a
          *conservation* decision: do not spend a trial on a node the tree
          already holds.
        * this reports on **claim** — the agent's stated mechanism, free text
          with no index and no exactness.  Its report is an *attention*
          decision: these nodes say they are doing the same thing, which is
          architecture §14.1's root failure mode ("the agent reformulates the
          same hypothesis in different code") and which a code hash is
          structurally blind to.

        A node can be a 179 duplicate and not a 211 duplicate — the same idea
        re-derived with a different literal — and a 211 duplicate and not a 179
        one, which is the case this read exists for.  Collapsing them would mean
        giving free text the authority of an exact identity: a false merge here
        would refuse a genuinely distinct hypothesis, and the asymmetry that
        makes the merge worth reporting is exactly the asymmetry that makes it
        unfit to refuse on.

        The match is on :func:`mechanism_digest`, so two spellings of one claim
        are one mechanism — the ``dedup`` clause §9.1's annotation names, and
        nothing beyond it.  A statement that canonicalises to nothing is refused
        by :func:`canonical_mechanism` rather than matching every other empty
        one, which is what keeps this read from answering "all of them" about a
        proposal that stated nothing.

        The result is ordered by ``node_id``, so two runs against one tree
        report the same sequence — a review queue that reshuffled between reads
        would be one a reviewer could not work through.  ``exclude`` is
        validated like any node id, so a typo'd id is refused rather than
        silently matching nothing.
        """
        # Refused before the digest is taken, and the refusal is the *write
        # path's own* for a statement that names nothing: :func:`mechanism_digest`
        # would happily hash the empty canonical form, and every blank would then
        # share one key — a read that matched every other blank, which answers
        # "all of them" about a proposal that stated nothing.  So the two seams
        # treat a blank differently on purpose: :meth:`persist` folds it to the
        # unstated state, because a NULL is the honest record of an agent that
        # stated nothing, while a *query* for one has no such state to report
        # and is refused.
        if mechanism is None or not canonical_mechanism(mechanism):
            raise MechanismStatementError(
                f"duplicates() was asked which nodes state {mechanism!r}, and a "
                f"blank names no mechanism to match: every node that states "
                f"nothing would share its digest, so the answer would be *every "
                f"unstated node* rather than an empty set. Pass a mechanism — a "
                f"node that states none has nothing to deduplicate (feature "
                f"211)."
            )
        wanted = mechanism_digest(mechanism)
        exclude_node = (
            _validated_node_id(exclude) if exclude is not None else None
        )
        with closing(self._connect()) as connection:
            self._require_column("a duplicate query")
            rows = connection.execute(
                f"SELECT {NODE_ID_COLUMN}, {MECHANISM_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {MECHANISM_COLUMN} IS NOT NULL "
                f"ORDER BY {NODE_ID_COLUMN}",
                (),
            ).fetchall()
        found = []
        for node_id, stored in rows:
            assert isinstance(stored, str), "a TEXT column returns text"
            node = str(node_id)
            if node == exclude_node:
                continue
            if mechanism_digest(stored) != wanted:
                continue
            found.append(self._loaded(node, stored))
        return tuple(found)

    def stated(self) -> tuple[MechanismRecord, ...]:
        """Every stored node that states a mechanism — the human review read.

        §9.1's annotation says the column is *"used for deduplication and human
        review"*, and the second reader needs something the first cannot give
        it: **the whole set, not a match**.  :meth:`duplicates` requires a
        mechanism in hand, which means a caller that already knows what it is
        looking for; this requires nothing, which is what a review queue is.

        It is deliberately **not** called ``unreviewed()``.  This member owns no
        review workflow — there is no ``reviewed_at`` column on ``node``, no
        reviewer identity and no queue state, and none of the three is in
        feature 211's sentence or in either spec document's schema.  Naming this
        ``unreviewed`` would claim a state machine that does not exist and would
        make a later feature's ``reviewed_at`` look like a migration of this
        method rather than an addition of its own.  It answers *what has been
        claimed* — which is the honest description of what the column holds —
        and the rows whose ``stated_mechanism`` is NULL are not in it, because a
        NULL is the positive fact that there is nothing to review.

        Ordered by ``node_id`` so a reviewer's pass is reproducible between
        reads, for the reason :meth:`duplicates` gives.
        """
        with closing(self._connect()) as connection:
            self._require_column("a review read")
            rows = connection.execute(
                f"SELECT {NODE_ID_COLUMN}, {MECHANISM_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {MECHANISM_COLUMN} IS NOT NULL "
                f"ORDER BY {NODE_ID_COLUMN}",
                (),
            ).fetchall()
        return tuple(
            self._loaded(str(node_id), stored)
            for node_id, stored in rows
            if isinstance(stored, str)
        )

    def _loaded(self, node: str, stored: str) -> MechanismRecord:
        """Build the record for a statement read out of a row.

        One helper for the three read paths, so a record loaded by
        :meth:`load`, one reported by :meth:`duplicates` and one emitted by
        :meth:`stated` are the same shape with the same ``detail`` — a caller
        that switched from one read to another should not discover that the
        values it holds are only *nearly* alike.

        ``reason`` is :attr:`MechanismReason.STATED` throughout: a row that
        holds text states a mechanism, and the reason vocabulary is about what
        the row *is*, not about which call read it.  ``recorded`` is ``None``
        for the same reason — a read writes nothing, so *did this call write?*
        has no referent, and the honest answer is neither of the two a write
        can give.
        """
        return MechanismRecord(
            node_id=node,
            reason=MechanismReason.STATED,
            detail=(
                f"{STATED_MECHANISM_CODE}: node {node} states {stored!r}, read "
                f"from the {MECHANISM_COLUMN} column. It is read for "
                f"deduplication and human review ONLY and is never a scored "
                f"input (architecture §9.1); the dedup key is "
                f"{mechanism_digest(stored)}, which is a key and not a "
                f"magnitude."
            ),
            statement=stored,
        )

    # -- The prerequisite ---------------------------------------------------

    def _require_column(self, node: str) -> set[str]:
        """Refuse a tree store whose ``node`` table lacks the stated-mechanism column.

        The prerequisite check, and the reason it is a probe rather than a
        caught exception: SQLite answers *"no such column: stated_mechanism"*
        only once a statement mentions the column, so a store that reached the
        ``UPDATE`` first would report the gap at a point where the message is
        about a statement rather than about the deployment.  ``PRAGMA
        table_info`` asks the table instead, which is the move
        :meth:`providers.AgentModelPins._require_columns` and
        ``nulloracle.TreeStoreGuard.audit`` each make for their own column.

        Both depths are one refusal.  A missing ``node`` table and a ``node``
        table missing the column are the same fact — this database has not
        reached revision :data:`MECHANISM_POLICY_REVISION` — seen at two depths,
        and both repairs are the same chain of migrations.  The ``node``
        argument is the caller's addressing value, used only to name the row in
        the message; the two read-set methods pass a parenthesised description
        instead, since they are not about one node.
        """
        connection = self._connect()
        try:
            rows = connection.execute(f"PRAGMA table_info({NODE_TABLE})").fetchall()
        except sqlite3.Error as exc:  # pragma: no cover - driver-level failure
            connection.close()
            raise MechanismColumnError(
                f"the tree store at {self.path} could not be asked for its "
                f"{NODE_TABLE} table's columns: {exc}"
            ) from exc
        columns = {str(row[1]) for row in rows}
        connection.close()
        if MECHANISM_COLUMN in columns:
            return columns
        if not columns:
            raise MechanismColumnError(
                f"the tree store at {self.path} has no {NODE_TABLE} table: "
                f"{node} cannot record a stated mechanism because there is no "
                f"node table to record it in. Feature 97's table is revision "
                f"0118 and the identity triple that adds {MECHANISM_COLUMN} is "
                f"revision {MECHANISM_POLICY_REVISION} (feature 98); run the "
                f"migration chain to there."
            )
        raise MechanismColumnError(
            f"the tree store at {self.path} holds a {NODE_TABLE} table with no "
            f"{MECHANISM_COLUMN} column, so {node} cannot record a stated "
            f"mechanism: the column belongs to revision "
            f"{MECHANISM_POLICY_REVISION} (feature 98), and a deployment that "
            f"has not reached it has nowhere for an agent's economic rationale "
            f"to live — there is no NULL to record *stated nothing* in either, "
            f"so the agent's claim would simply be lost. Run the migration "
            f"chain to {MECHANISM_POLICY_REVISION}."
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"MechanismStore({self._database_url!r})"


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract —
    the spelling :mod:`providers._pin_store`, the ledger's and the discovery
    planner's each state for the same reason, which is that a store loaded
    inside one member must not depend on another member being importable.

    A non-SQLite scheme is refused loudly, and so is a pathless (in-memory)
    URL: an in-memory database dies with the connection that opened it, and a
    node's stated mechanism must outlive the authoring call that recorded it —
    the human reviewer reads it in another process entirely, days later, and the
    dedup pass runs in a third.  Both refusals are
    :class:`~signal_agent.errors.MechanismStoreUnavailableError` rather than
    :class:`MechanismStatementError`: neither is a fact about a proposal or a
    node, and the class an operator needs is the one that says *this deployment
    has nowhere to persist anything* — the same class
    :meth:`StatedMechanism._required_store` raises for the ``None`` case, the
    two being one fact read from opposite sides.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise MechanismStoreUnavailableError(
            f"{DATABASE_URL_ENV} must be a non-empty database URL; a stated "
            f"mechanism is a column on a node, so there must be a store holding "
            f"the tree"
        )
    parsed = urlparse(database_url.strip())
    if parsed.scheme != "sqlite":
        raise MechanismStoreUnavailableError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            f"store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the tree store's "
            f"{NODE_TABLE} table already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise MechanismStoreUnavailableError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise MechanismStoreUnavailableError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            f"database would die with the connection that opened it, and a "
            f"node's stated mechanism must outlive the authoring call that "
            f"recorded it — the human reviewer and the dedup pass both read "
            f"this column from other processes"
        )
    return Path(path)


def _validated_statement(value: Any) -> str | None:
    """Read a caller's ``mechanism`` as a statement, or as the unstated null.

    Returns the caller's text **verbatim** — never the canonical form — because
    the value it returns is what gets written.  :func:`canonical_mechanism`
    exists so that two spellings of one claim *compare* equal; §9.1's clause is
    that the column is what a human reviews, and a store that tidied the agent's
    prose on the way in would be rewriting the agent's claim rather than
    recording it.  The comparison is the caller's business, and
    :meth:`MechanismStore._state` makes it explicitly at the one place it
    decides *retry* from *conflict*, so the two uses cannot be confused — which
    is the bug this function's docstring exists to prevent a second of.

    Three inputs, three answers:

    * ``None`` → ``None``.  The agent stated no mechanism; feature 98's NULL is
      the honest record of that.
    * text whose canonical form is **empty** → also ``None``, and deliberately
      not a refusal.  ``""``, ``"   "`` and ``"\\n"`` all state nothing, which
      is the same proposal-level fact as ``None`` with the same repair, and
      :class:`MechanismReason` already argues why there is no vocabulary token
      for the difference.
    * anything else → :class:`~signal_agent.errors.MechanismStatementError`.
      A list, a number, a dict: no agent emitted one, so the defect is in the
      caller's wiring and nothing about the proposal should be recorded from it.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise MechanismStatementError(
            f"a stated mechanism must be text or None, got "
            f"{type(value).__name__}; ``None`` is the legal spelling of *this "
            f"agent stated no mechanism* (feature 98's nullable column), but a "
            f"{type(value).__name__} is not a rationale any agent wrote, so the "
            f"defect is in the caller's wiring rather than in the proposal "
            f"(feature 211)."
        )
    if not canonical_mechanism(value):
        return None
    return value


def stated_mechanism(
    env: Mapping[str, str] | None = None,
) -> StatedMechanism:
    """The stated-mechanism law, composed from the environment.

    The module-level convenience every feature in this member ships beside its
    component: a caller — an operator script, a suite, the campaign driver —
    that wants feature 211's answers without standing up an application.  The
    component is what the factory builds and what a composed caller should use;
    this is the same law, composed from ``DATABASE_URL`` in one call.

    It **never** returns ``None``, and it never raises for a missing database.
    The barrier clause is answerable with no store at all — that is the whole
    reason :class:`StatedMechanism` composes ``store=None`` rather than
    refusing to exist — so a deployment with no ``DATABASE_URL`` still gets a
    law that enforces *never a scored input*, and the four store-backed verbs
    raise :class:`~signal_agent.errors.MechanismStoreUnavailableError` when
    they are called.  Returning ``None`` here would make the barrier
    unavailable in exactly the deployment that has the least other protection,
    which is backwards.
    """
    return StatedMechanism(MechanismStore.resolve(env))
