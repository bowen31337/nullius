"""Feature 207 — one proposal document plus a score record, per node.

*"System persists one proposal document plus a score record per node, which
together form the replayable history."*

**Where the pair comes from, and why it is the unit.**  Architecture §14.1:769
states the authoring step's requirement in terms of these two artefacts and
nothing else: the C3 prompt reads *"every prior ``proposal.md`` **in full** —
not a sample, not recent cycles"*, and the sizing that sentence is argued from
is *"at ~1k tokens per proposal plus its ``score.json``, a 500-node campaign
carries roughly 500K tokens of history by the late rounds"*.  §14.1:801 repeats
the pair as the unit of the depth role's context (*"~500 nodes at ~1.2k tokens
of ``proposal.md`` + ``score.json`` each"*).  So the *document* and the
*record* are not two features that happen to sit together; they are one
artefact spelled twice, and a store that held only one of them could not answer
the question §14.1 is about.  PRD §C3 states the reading obligation from the
other side — *"Keep history as an interactive replay object, not as prose
advice"* — which is a statement about *what the history is made of*: proposals
and their measured scores, replayed, rather than a narrative about them.

**This module is the writer; feature 206 is the reader.**  :mod:`signal_agent.
_history` refuses a history that is a sample or a truncation, and its
:class:`~signal_agent.PriorProposal` carries exactly ``node_id`` + ``proposal``
+ ``code_hash`` — the three fields §9.1's ``node`` row carries into the
authoring step.  What 206 deliberately does not do is *produce* the entries it
judges: its own module docstring says so in as many words, naming *"the
caller's own tree query for the round"* as the source and compiling no
artefact.  This module is the store behind that query, and it hands back
:class:`~signal_agent.PriorProposal` values rather than a type of its own so
that the writer's output is *literally* the reader's input — see
:meth:`ProposalHistoryStore.history`.

**Why the pair is not written into §9.2's directory, which is where §14.1
names it.**  §9.2 draws one directory per node holding the things replay needs,
and §14.1's ``proposal.md`` and ``score.json`` read as two of its files.  They
cannot be, as the pipeline currently stands, and the reason is a whole-
directory commit rather than a matter of taste.  ``record`` publishes the
node's *whole* directory — ``commit`` replaces it wholesale, and
:data:`discovery.persist.MEASURED_FILENAMES` is what it carries forward across
that replacement: the five files feature 85's step 12 renders.  A
``proposal.md`` staged into that directory is therefore deleted by the next
attempt on the same node, because nothing carries it forward and
:class:`artifacts.ArtifactStore` has no notion that it matters.  A history that
erases itself when its own node is retried is not a history, and the failure is
silent — which is the shape this member refuses everywhere else.  So the pair
lives in a table instead; the storage decision is argued in full at
``_SCHEMA``.

**The score record is captured, not joined.**  The seven metrics 0114 declares
sit on the ``node`` row, and a retry *refreshes that row in place* — feature
240's own module docstring states it (*"a re-record is therefore a refresh —
the row is updated in place"*), and feature 244 exists precisely to re-run
interrupted attempts, so a second score for one node is an expected event
rather than a corruption.  A history read that resolved its scores by joining
``node`` would therefore answer a different question each time it was asked:
*what does this node score now?* rather than *what did this proposal score when
the round read it?*.  §14.1's whole argument is built on the second — the
agent reads *prior* proposals *and their scores* to decide what to try next —
so :meth:`ProposalStore.persist` renders the score once, at the moment the
proposal is recorded, and stores it.  That is what makes the history
*replayable*: replay is a claim about reading the same values again, and a join
cannot make it.  The corollary is stated where it bites, at
:meth:`ProposalStore.load`: a read re-verifies the document's identity but
deliberately does **not** refuse a row whose live metrics have since moved on.

**What this module deliberately does not do.**  It does not write the
document.  Feature 205 owns whether a proposal is a conforming signal and
:func:`~signal_agent.source_code_hash` over it is ``code_hash``; feature 211
owns the agent's stated *rationale*; feature 240 owns the row and the directory.
This module takes the proposal text as given, and its only claim about it is
the one §14.1's reading rule needs: the text stored is the text hashed, so the
identity a later reader checks means something.

**The asymmetry at the errors.**  The four refusals below are siblings of
:class:`~signal_agent.AgentSourceError`, not subclasses — the discipline
:class:`~signal_agent.TruncatedHistoryError` states.  A caller's pre-existing
``except AgentSourceError:`` handler exists to re-prompt the agent, and
re-prompting does not repair a database that cannot hold the history: the
proposal may have been perfectly good and the store unconfigured.  The repairs
are a migration, a `DATABASE_URL` and a corrected identity — none of them an
agent action — so none of them may be reachable through that clause.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote, urlparse

from ._history import PriorProposal
from .errors import (
    ProposalConflictError,
    ProposalContentError,
    ProposalHistoryStoreUnavailableError,
    ProposalNodeNotRecordedError,
)

__all__ = [
    "CODE_HASH_COLUMN",
    "DATABASE_URL_ENV",
    "FAIL_CLASS_COLUMN",
    "METRIC_COLUMNS",
    "NODE_PROPOSAL_COLUMNS",
    "NODE_PROPOSAL_TABLE",
    "PROPOSAL_DOCUMENT_NAME",
    "PROPOSAL_HISTORY_COMPONENT_NAME",
    "PROPOSAL_PERSISTED_CODE",
    "SCORE_COLUMNS",
    "SCORE_RECORD_NAME",
    "ProposalHistoryStore",
    "ProposalRecord",
    "ProposalStore",
    "ScoreRecord",
    "proposal_history_store",
]

#: The name the plugin registers this law's component under.  Hyphenated like
#: its siblings so the member's nine stay contiguous in the loader's
#: name-sorted ``app.order``, and suffixed rather than bare so a later
#: registration cannot replace the plugin's own ``signal-agent`` component by
#: colliding with it.  ``signal-agent-proposal-history`` sorts between
#: ``signal-agent-history`` and ``signal-agent-stated-mechanism``.
PROPOSAL_HISTORY_COMPONENT_NAME: Final[str] = "signal-agent-proposal-history"

#: The member-owned table.  Named for its subject rather than for either half:
#: one row is one node's *pair*, and a name like ``proposal_document`` would
#: invite the reading that the score is somewhere else.
NODE_PROPOSAL_TABLE: Final[str] = "node_proposal"

#: §14.1's own filename for the authoring agent's output — the name the
#: prose in architecture §14.1 uses when it prices the history.  Kept here as
#: data because this module's conversation with an operator is about *the
#: pair §14.1 names*, and a reader who has just come from that paragraph
#: should find the same two words here rather than a synonym.
PROPOSAL_DOCUMENT_NAME: Final[str] = "proposal.md"

#: §14.1's own filename for the score beside it.  The second half of the same
#: sentence, and the reason :class:`ScoreRecord` exists as a value rather
#: than as a handful of columns: the record §14.1 sizes is *a document*.
SCORE_RECORD_NAME: Final[str] = "score.json"

#: The token a *recorded* proposal's sentence opens with — the feature's own
#: subject written as a word, so an operator grepping a campaign log for the
#: nodes whose history is stored finds them by it.  The mirror of
#: :data:`~signal_agent.COMPLETE_HISTORY_CODE` on the reading side, and the
#: same asymmetry: an admission is not a code an operator greps for.
PROPOSAL_PERSISTED_CODE: Final[str] = "proposal_persisted"

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace uses, restated here so this module states its
#: own contract rather than importing a sibling's.
DATABASE_URL_ENV: Final[str] = "DATABASE_URL"

#: The ``node`` table feature 97's ``0118`` creates.  Probed, never created:
#: it is the discovery tree's, and this member is a writer over a table
#: someone else's migration owns — the position
#: :class:`providers.AgentModelPins` and :class:`discovery.CampaignRecords`
#: are in, and for the same reason.
NODE_TABLE: Final[str] = "node"

#: 0114's seven metric columns (feature 101), in the migration's own order.
#: Spelled as data rather than read off the migration because this module must
#: *probe* for them: the store speaks to whatever database ``DATABASE_URL``
#: names, and that database may not have reached 0114 — so the tuple below is
#: what the score record would carry on the fully-assembled tree, and
#: :func:`_scored_columns` intersects it with what the live table actually has.
METRIC_COLUMNS: Final[tuple[str, ...]] = (
    "ic_mean",
    "ic_tstat",
    "ir_standalone",
    "ir_marginal",
    "turnover",
    "cost_adjusted_ir",
    "perturb_stability",
)

#: The column ``discovery.persist`` owns and §6.1 step 11 stamps — *"ok |
#: timeout | error | tripwire_fail"*.  Part of the score record because a
#: failed attempt's metrics are NULL and the *class* is what says whether that
#: NULL means "not measured yet" or "measured as a failure"; §C3's retry
#: decision (feature 209) is about a proposal that already has a class.
FAIL_CLASS_COLUMN: Final[str] = "fail_class"

#: The ``node`` columns this module reads, in the order the score record
#: carries them.  One tuple so the write path and the read path cannot
#: disagree about what a score is made of.
SCORE_COLUMNS: Final[tuple[str, ...]] = (*METRIC_COLUMNS, FAIL_CLASS_COLUMN)

#: 0117's identity column — the digest of the exact source the sandbox
#: executed.  This module re-derives it over the document it stores, which is
#: the load-bearing check :mod:`signal_agent._history` relies on when it reads
#: a history back.
CODE_HASH_COLUMN: Final[str] = "code_hash"

#: 0118's five structural columns this module reads for the campaign id it
#: records, so a history read can be scoped to one campaign without trusting
#: the caller's pairing of ids.
CAMPAIGN_ID_COLUMN: Final[str] = "campaign_id"

#: The node's own key, 0118's.
NODE_ID_COLUMN: Final[str] = "id"

#: The ``node_proposal`` columns.  Named as constants for the reason every
#: store in this workspace names its columns: the write and the read are two
#: statements in two methods, and a literal spelled twice in one module is a
#: literal that can drift once.
NODE_PROPOSAL_COLUMNS: Final[tuple[str, ...]] = (
    "node_id",
    "campaign_id",
    "proposal",
    "code_hash",
    "score",
    "generated_at",
    "recorded_at",
)

#: The read-only probe that answers *does this database hold a tree at all?* —
#: the ``sqlite_master`` idiom feature 232's ordering law and feature 239's
#: workspace read both use, restated rather than imported because a private
#: constant of a sibling module is not a promise.
_NODE_TABLE_EXISTS_SQL: Final[str] = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)

#: The read that answers *which columns does this tree actually have?* — a
#: ``PRAGMA`` over the live table, run once per write.  This is what makes the
#: score record a projection of the deployment's chain rather than of this
#: file's guess at it: ``0118`` creates five columns and ``0113``-``0117`` add
#: indexes and ten more, so a writer that named all seven metrics
#: unconditionally would be an ``OperationalError`` on every database the
#: metric migration has not reached.  Feature 240's ``_table_shape`` states
#: the same rule for the same reason.
_TABLE_COLUMNS_SQL: Final[str] = "PRAGMA table_info(node)"

#: The column that is the node's campaign, taken from 0118's own list.  Named
#: so the probe's answer and the projection agree.
_NODE_LOOKUP_SQL: Final[str] = (
    f"SELECT {CAMPAIGN_ID_COLUMN}, {{columns}} FROM {NODE_TABLE} "
    f"WHERE {NODE_ID_COLUMN} = ?"
)

#: The member-owned table, in one idempotent statement — the contract every
#: store in this workspace states (a fresh database and one this build has
#: written to a hundred times must both work).
#:
#: **Why a table and not §9.2's directory.**  §14.1 names ``proposal.md`` and
#: ``score.json``, and §9.2's one-directory-per-node is where a reader would
#: look for them.  The directory cannot hold them *stably*: feature 240's
#: ``record`` publishes the node's whole directory through a wholesale
#: ``commit``, carrying forward exactly the five names in
#: ``MEASURED_FILENAMES``, so an attempt that follows an evaluation would
#: delete a pair staged alongside them — silently, because the delete is the
#: commit's normal behaviour rather than an error.  This feature's subject is a
#: history that survives being replayed; a store whose contents are erased by
#: the next attempt on the same node cannot be that.  So the pair goes in a
#: table **this member owns and creates lazily**, the precedent
#: ``bootstrap_world`` (feature 188), ``depth_run_window`` (feature 202),
#: ``bootstrap_trial`` (feature 185) and ``depth_cache_rate`` (feature 200)
#: all set: no migration declares this row, and a member that refused to create
#: its own table would be refusing its own feature.  The shared migration chain
#: is not edited, and the ``node`` table beside it is probed read-only.
#:
#: Every column is ``NOT NULL`` — a document plus a score record written whole
#: or not at all, the stance ``depth_cache_rate``'s schema states.  The key
#: carries ``NOT NULL`` explicitly beside ``PRIMARY KEY`` for the reason
#: ``0111``'s docstring spells: SQLite accepts NULL — and several — in a bare
#: ``PRIMARY KEY``, so a second NULL-keyed row would split a document from its
#: node while still being accepted as a distinct key.
#:
#: ``agent_model_id`` is deliberately **absent**.  Which model authored the
#: proposal is 0115's column on ``node`` (features 203/204), indexed for the M3
#: stratification, and a copy here would be a second spelling of it that can
#: drift from the stratum the paired comparison actually groups by — the same
#: restraint :class:`providers.DepthCacheRates` states when it declines to
#: carry a model column on its own row.  A reader that wants it joins.
_SCHEMA: Final[str] = f"""
CREATE TABLE IF NOT EXISTS {NODE_PROPOSAL_TABLE} (
    node_id       TEXT     NOT NULL PRIMARY KEY,
    campaign_id   TEXT     NOT NULL,
    proposal      TEXT     NOT NULL,
    code_hash     CHAR(64) NOT NULL,
    score         TEXT     NOT NULL,
    generated_at  TEXT     NOT NULL,
    recorded_at   TEXT     NOT NULL
)
"""


# ── The score record — §14.1's ``score.json`` ─────────────────────────────────


class ScoreRecord:
    """One node's measured score, as §14.1's ``score.json``.

    The second half of the pair the feature's sentence names, and the half the
    *replay* reading of the history turns on.  §14.1 sizes the depth call's
    context as ``proposal.md`` + ``score.json`` per node, so the record is what
    makes a prior proposal more than prose: an agent reading the history is
    deciding what to try next, and the figure beside each proposal is how it
    knows which directions already worked.

    **It is a snapshot, and that is the feature rather than an implementation
    detail.**  These values are read off the ``node`` row *once*, at the moment
    :meth:`ProposalStore.persist` records the proposal, and stored.  Feature
    240 refreshes that row in place on every retry — its module docstring says
    so — and feature 244 re-runs interrupted attempts, so a second score for
    one node is an expected event.  A history that resolved its scores by
    joining ``node`` would therefore answer a different question each time it
    was asked: *what does this node score now?* rather than *what did this
    proposal score when the round read it?*.  §14.1's entire argument is built
    on the second, and replay is a claim about reading the same values again.

    **A ``None`` metric is an absent measurement, not a zero.**  0114 declares
    all seven metrics nullable with no default, and says why in its own
    docstring: the metrics are measured, so *"a pre-metric row has no honest
    value to assert"*.  An attempt that failed before the evaluator reached it
    has genuinely unmeasured metrics, and the honest record of that is the
    absence.  So the seven are ``float | None`` rather than ``float``, no
    metric is defaulted to ``0.0`` anywhere in this module, and
    :meth:`to_json` writes the absence as JSON ``null`` rather than dropping
    the key — a missing key and a ``null`` are two different documents, and
    only one of them round-trips.

    **It is not a scored input and it does not claim to be one.**  Nothing
    here computes, weights or compares; the figures are the evaluator's, and
    this class's only job is to carry them across a process boundary intact.
    A subclass would be the place a derived figure could quietly appear, so
    there is none.
    """

    __slots__ = (*SCORE_COLUMNS,)

    def __init__(
        self,
        *,
        ic_mean: float | None = None,
        ic_tstat: float | None = None,
        ir_standalone: float | None = None,
        ir_marginal: float | None = None,
        turnover: float | None = None,
        cost_adjusted_ir: float | None = None,
        perturb_stability: float | None = None,
        fail_class: str | None = None,
    ) -> None:
        self.ic_mean = ic_mean
        self.ic_tstat = ic_tstat
        self.ir_standalone = ir_standalone
        self.ir_marginal = ir_marginal
        self.turnover = turnover
        self.cost_adjusted_ir = cost_adjusted_ir
        self.perturb_stability = perturb_stability
        self.fail_class = fail_class

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> ScoreRecord:
        """Build the record from a ``node`` row's columns.

        Reads :data:`SCORE_COLUMNS` by name and nothing else — a column the
        record does not carry is a column that would drift, the discipline
        :mod:`providers._depth` states for its own record.  A mapping is taken
        rather than a sequence because the caller has already had to project
        the live table (see :func:`_scored_columns`), and by the time a
        projection has run, names are the only safe way to read the answer.

        Missing keys become absent measurements rather than raising: the
        projection is this module's own and it is the thing that decides which
        columns exist, so a key absent from the mapping is a fact the caller
        established deliberately.
        """
        metrics = {
            name: _metric_from(row.get(name)) for name in METRIC_COLUMNS
        }
        return cls(**metrics, fail_class=_text_from(row.get(FAIL_CLASS_COLUMN)))

    def to_json(self) -> str:
        """The record as ``score.json`` — one line, sorted, no ``NaN``.

        ``allow_nan=False`` is this renderer's own choice rather than a
        serialiser default, and it is load-bearing: ``NaN`` is not JSON, so a
        ``json.loads`` of a document containing a bare ``NaN`` token succeeds
        only because Python's decoder is lenient about its own extension —
        another reader's would refuse it, and the whole point of storing the
        score as JSON is that a *later, different* process can read it.  A
        metric that is genuinely ``NaN`` is a measurement this system should
        record as an absence; raising here is what makes that a decision
        somebody takes rather than a document that parses in one language.

        ``sort_keys`` so two records with equal fields are byte-identical
        strings: the stored text is what a reader compares against, and a
        rendering whose key order depended on this module's field order would
        make that comparison a claim about two implementations.
        """
        payload = {name: getattr(self, name) for name in SCORE_COLUMNS}
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    @classmethod
    def from_json(cls, text: object, node: str) -> ScoreRecord:
        """Read a stored ``score.json`` back, refusing a document that is not one.

        The mirror of :meth:`to_json`, and the place a corrupted row is caught
        rather than laundered: a stored score that does not parse, does not
        hold an object, or carries a metric that is neither a number nor an
        absence is refused by name, naming the node — the stance
        :meth:`providers.DepthCacheRates.get` takes for a row that contradicts
        its own arithmetic.  A read side that returned whatever it found would
        make the *number* a reader sees a fact about the database's corruption
        rather than about the proposal.
        """
        if not isinstance(text, str):
            raise ProposalContentError(
                f"the stored {SCORE_RECORD_NAME} for node {node!r} is "
                f"{type(text).__name__} rather than text: this column holds a "
                f"JSON document and nothing else can have written a value a "
                f"reader would try to parse (feature 207)."
            )
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise ProposalContentError(
                f"the stored {SCORE_RECORD_NAME} for node {node!r} is not "
                f"JSON ({exc}): the record was rendered by "
                f"ScoreRecord.to_json and stored as a document, so a value "
                f"that does not parse is a row this store did not write or one "
                f"something has since corrupted — either way the figures in it "
                f"are not measurements of anything (feature 207)."
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProposalContentError(
                f"the stored {SCORE_RECORD_NAME} for node {node!r} is a JSON "
                f"{type(payload).__name__} rather than an object: a score "
                f"record is a set of named measurements, and a document with "
                f"no names in it records nothing a later round could read "
                f"(feature 207)."
            )
        return cls(
            **{name: _metric_from(payload.get(name)) for name in METRIC_COLUMNS},
            fail_class=_text_from(payload.get(FAIL_CLASS_COLUMN)),
        )

    def measured(self) -> tuple[str, ...]:
        """The metric names this record actually holds a figure for, sorted.

        The question a campaign driver asks when it wants to know whether a
        proposal was *scored* as opposed to merely *recorded* — a failed
        attempt is persisted with every metric absent, and the difference
        between that and a node that scored badly is the whole reason the
        ``NULL`` is not a zero.
        """
        return tuple(
            sorted(name for name in METRIC_COLUMNS if getattr(self, name) is not None)
        )

    def __eq__(self, other: object) -> bool:
        """Equal when the parts are equal — never by ``isinstance``.

        The loader imports every member twice, once by file path under a
        synthetic name and once as the importable member, so an ``isinstance``
        check against this class would be false for a value built from the
        other import of the same file.  Equality over the fields is the same
        statement and survives that — the discipline
        :meth:`signal_agent.PriorProposal.__eq__` states for its own.
        """
        if not all(hasattr(other, name) for name in SCORE_COLUMNS):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name) for name in SCORE_COLUMNS
        )

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, name) for name in SCORE_COLUMNS))

    def __repr__(self) -> str:
        return (
            f"ScoreRecord(measured={self.measured()}, "
            f"fail_class={self.fail_class!r})"
        )


def _metric_from(value: Any) -> float | None:
    """One metric as a figure or an absence, refusing anything between.

    Three-way, because the three states are three different facts: a number is
    a measurement, ``None`` is *not measured*, and a string or a list is a
    value no evaluator ever produced.  Collapsing the third into the second
    would let a corrupted row read as an honest failure, which is the
    laundering direction this module refuses everywhere else.  A ``bool`` is
    refused explicitly rather than accepted as ``0``/``1``: SQLite returns
    ``0``/``1`` for a ``BOOLEAN`` column and Python's ``bool`` is an ``int``
    subclass, so without this check ``True`` would silently become a metric of
    ``1.0`` — the same trap :mod:`signal_agent._mechanism` names for its own
    column reads.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ProposalContentError(
            f"a score record's metric is {value!r}, which is a boolean rather "
            f"than a measurement: SQLite returns the integers 0 and 1 for a "
            f"BOOLEAN column and Python's bool is an int subclass, so this "
            f"value would otherwise read as a figure of 1.0 or 0.0 and be "
            f"indistinguishable from a real measurement (feature 207)."
        )
    if not isinstance(value, (int, float)):
        raise ProposalContentError(
            f"a score record's metric is {value!r} "
            f"({type(value).__name__}) rather than a number or an absence: "
            f"0114's metric columns are REAL and nullable, so a value that is "
            f"neither is a row the evaluator did not write (feature 207)."
        )
    return float(value)


def _text_from(value: Any) -> str | None:
    """One text field of the score record, or ``None`` when absent.

    ``fail_class`` is §6.1's *"ok | timeout | error | tripwire_fail"* and this
    function judges only that it is text: whether a class is one §9.1 records
    is :func:`discovery.classify_failure`'s question and this module has no
    business answering it a second time.  A blank string is normalised to
    ``None`` — the same fact with the same repair, the stance
    :func:`signal_agent._mechanism._validated_statement` takes — so a row whose
    class was written as whitespace does not read as a *class* while a row
    written as NULL reads as an absence.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProposalContentError(
            f"a score record's fail_class is {value!r} "
            f"({type(value).__name__}) rather than text: §6.1 records the "
            f"class an attempt ended in as one of ok, timeout, error or "
            f"tripwire_fail, and a value that is not text names none of them "
            f"(feature 207)."
        )
    text = value.strip()
    return text or None


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning canonical UUID text.

    The same canonicalisation :func:`signal_agent._mechanism._validated_node_id`
    applies, restated rather than imported because a private helper of a
    sibling module is not a promise.  A mixed-case or braced spelling of one
    node would make one node's history look like two, and the primary key
    would accept both — so the canonical form is what is written and what is
    looked up.  Unlike that function there is no unjudged fallback here: this
    store's key is a node the tree recorded, and 0118 mints those as UUIDs, so
    a value that is not UUID text names no node.
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
    raise ProposalContentError(
        f"node_id {value!r} is not a UUID: feature 207 persists one proposal "
        f"document and one score record *per node*, keyed by the node id "
        f"{NODE_ID_COLUMN} — the value 0118's {NODE_TABLE} table mints and "
        f"every reader joins by — so an id that cannot join it names no node "
        f"whose history could be replayed (feature 207)."
    )


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning canonical UUID text.

    Same three lines as :func:`_validated_node_id` and split from it anyway,
    because the two refusals say different things: a node id that does not
    parse names no node, and a campaign id that does not parse names no *run*
    whose proposals could be listed together.  The history read is scoped to
    one campaign, so this id is the scope and a wrong one silently returns
    another campaign's nodes — which is why it is canonicalised rather than
    taken as given.
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
    raise ProposalContentError(
        f"campaign_id {value!r} is not a UUID: the history is scoped to one "
        f"campaign (§5: one campaign = one discovery tree) and the scope is "
        f"the value {CAMPAIGN_ID_COLUMN} holds, so an id that cannot join it "
        f"would silently list another campaign's proposals as this one's "
        f"(feature 207)."
    )


def _validated_document(value: Any) -> str:
    """The proposal document as it will be stored, refusing non-text.

    Stored **verbatim** — not stripped, not normalised, not re-encoded.  The
    document is the agent's proposal, and the whole reason §14.1 requires the
    history be read *in full* is that the text is the artefact: a store that
    tidied it would be rewriting the proposal rather than recording it.  The
    digest beside it is taken over exactly these bytes, so a normalisation here
    would also silently break every identity check feature 206 makes.

    Empty text is refused rather than accepted as a blank document.  A
    proposal with no content is not a proposal the authoring step produced —
    feature 205 refuses a blank source before it is ever adopted — so an empty
    value here is a caller that lost its text on the way, and recording it
    would put a node in the history whose document can never be read as
    anything.
    """
    if not isinstance(value, str):
        raise ProposalContentError(
            f"a proposal document must be text, got {value!r} "
            f"({type(value).__name__}): §14.1's history is prior proposals "
            f"read *in full*, and a value that is not text is not a document "
            f"a later round could read (feature 207)."
        )
    if not value.strip():
        raise ProposalContentError(
            f"a proposal document must have content, got {len(value)} "
            f"character(s) of whitespace: feature 205 refuses a blank "
            f"proposal before it is ever adopted, so a blank document here is "
            f"a caller that lost its text on the way to this call — and "
            f"recording it would put a node in the history whose document can "
            f"never be read as anything (feature 207)."
        )
    return value


def _document_digest(document: str) -> str:
    """The sha256 hexdigest of one proposal document.

    §9.1's ``code_hash CHAR(64)``, filled the way every writer in this
    workspace fills it — ``sha256(text.encode("utf-8")).hexdigest()`` — and
    the fourth place a source is hashed, after the evaluator's step 6, the
    artifact store's own copy and :func:`signal_agent.source_code_hash` at the
    moment of adoption.  The four must agree to the byte, because feature 206's
    load-bearing check recomputes exactly this function over the text a history
    carries: a row whose stored digest was taken over different bytes is a row
    whose history is refused as truncated.

    Deliberately **not** a call to :func:`signal_agent.source_code_hash` — not
    because the answer would differ, but because that function raises the
    authoring *law's* error for a non-string and this module's refusals are its
    own.  The three lines of stdlib are restated with a pointer, the trade
    :func:`artifacts.source_code_hash` makes for its own copy, and
    :func:`_validated_document` has already established the type.
    """
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def _scored_columns(connection: sqlite3.Connection, node: str) -> tuple[str, ...]:
    """Which of :data:`SCORE_COLUMNS` this tree actually has, in order.

    The projection that makes the write a fact about the deployment's chain
    rather than about this file's guess at it.  ``0118`` creates the ``node``
    table and ``0114`` adds the seven metrics; a database that has run the
    first and not the second is a real state — the chain dispatches the column
    features before the table feature, so a database assembled in the order the
    chain was built to run stops there — and it is the state
    :class:`~signal_agent.errors.ProposalNodeNotRecordedError` is *not* for.
    On such a tree the score record carries ``fail_class`` alone (0117's
    neighbour, not 0114's) and every metric is an absence, which is honest: on
    that deployment nothing has measured them.

    The table's absence is refused by name first, naming ``0118``, rather than
    letting SQLite's ``no such table`` escape — the discipline feature 240's
    ``_table_shape`` states, and the repair for both is an operation rather
    than a value.
    """
    present = _table_columns(connection, node)
    return tuple(name for name in SCORE_COLUMNS if name in present)


def _table_columns(connection: sqlite3.Connection, node: str) -> frozenset[str]:
    """The live ``node`` table's column names, the table itself refused by name.

    One ``PRAGMA``, run per write, and the only place this module asks the
    database what shape it is in.  Splitting it from
    :func:`_scored_columns` keeps *"is there a tree?"* and *"which columns does
    it have?"* as the two separate questions they are: the first has one repair
    (run 0118) and the second has another (run 0114), and a caller reading a
    refusal should be told which.
    """
    exists = connection.execute(_NODE_TABLE_EXISTS_SQL, (NODE_TABLE,)).fetchone()
    if exists is None:
        raise ProposalNodeNotRecordedError(
            f"the database holds no {NODE_TABLE} table, so there is no tree "
            f"for node {node!r}'s proposal to hang off: feature 207's pair is "
            f"keyed by the node id 0118's table mints, and a history is a "
            f"{NODE_TABLE} query's answer — while the {NODE_TABLE} table is "
            f"the discovery tree's and this member's to read rather than to "
            f"create. Bring the deployment's migration chain to at least "
            f"0118 (the tree's table), whose rows feature 232's campaign "
            f"record writes (feature 207)."
        )
    return frozenset(row[1] for row in connection.execute(_TABLE_COLUMNS_SQL))


def _row_for(
    connection: sqlite3.Connection, node: str, columns: Sequence[str]
) -> dict[str, Any]:
    """The node's campaign id and projected score columns, or a named refusal.

    One read, and the node's *absence* is a different refusal from the table's:
    a node the tree does not hold has no id for a proposal to be recorded
    against, and the repair is that the discovery loop records the node first —
    feature 232's campaign record is the writer.  Kept a method-level
    distinction rather than one "unknown id" message, because an operator
    looking at a campaign that persisted nothing needs to know whether the
    schema or the row was missing.

    The columns are projected in the caller's order and read back by position,
    which is safe because the caller decided the order and this function
    returns the names beside the values.
    """
    projection = ", ".join(columns)
    row = connection.execute(
        _NODE_LOOKUP_SQL.format(columns=projection), (node,)
    ).fetchone()
    if row is None:
        raise ProposalNodeNotRecordedError(
            f"there is no node {node!r} in the tree store: feature 207 "
            f"persists one proposal document plus one score record *per "
            f"peer node*, and the score half is read off the node's own row — "
            f"so a node the tree does not hold has no row to take a campaign "
            f"id from and no metrics to snapshot. The discovery loop records "
            f"the node first (feature 232's campaign record is the writer); "
            f"the proposal and its score are then recorded against it "
            f"(feature 207)."
        )
    campaign = row[0]
    return {name: row[index + 1] for index, name in enumerate(columns)} | {
        CAMPAIGN_ID_COLUMN: campaign
    }


def _format_instant(moment: datetime) -> str:
    """One instant as the spine's ISO-8601 UTC text spelling.

    ``%Y-%m-%dT%H:%M:%fZ``, the same three-line rendering
    :func:`providers._cache._format_instant` performs, restated for the same
    reason: the stored form is text the whole workspace reads back with
    :func:`datetime.fromisoformat`, and a second spelling (an offset, a missing
    ``Z``) would make one instant two strings.  Microseconds, because two
    proposals recorded in the same millisecond are a real thing in a batch of
    sibling calls — §14.1's depth role runs ``W`` branches concurrently — and a
    history ordered by a second-resolution stamp would have an order the
    campaign did not have.
    """
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _require_instant(value: object, what: str) -> datetime:
    """Return ``value`` as an aware UTC ``datetime``, refusing the rest.

    A naive datetime names no instant, and stamping a record with one would
    make the stored text depend on the process's local zone — a campaign run on
    a laptop in one zone and a worker in another would order the same history
    two ways.  Aware datetimes of any offset are accepted and converted.
    """
    if not isinstance(value, datetime):
        raise ProposalContentError(
            f"{what} must be a datetime, got {value!r} "
            f"({type(value).__name__}): the recorded-at column is when the "
            f"proposal entered the history, and a value that is not an instant "
            f"names no moment a later round could order itself against "
            f"(feature 207)."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProposalContentError(
            f"{what} must be timezone-aware, got {value!r}: a naive datetime "
            f"names no instant, so two workers in two zones would stamp the "
            f"same moment two ways and the history's order would be a fact "
            f"about the reader's environment (feature 207)."
        )
    return value.astimezone(UTC)


def _parse_instant(text: object, node: str, column: str) -> datetime:
    """Read a stored instant back, refusing text that is not one.

    The read half of :func:`_format_instant`, and the place a corrupted
    timestamp is caught rather than laundered into a plausible-looking value —
    the stance :meth:`providers.DepthCacheRates.get` takes for its own stored
    instant.  Naming the column rather than the node alone, because a row has
    two instants and an operator needs to know which one is unreadable.
    """
    if not isinstance(text, str):
        raise ProposalContentError(
            f"the stored {column} for node {node!r} is "
            f"{type(text).__name__} rather than text: every instant in this "
            f"store is written by _format_instant as ISO-8601 UTC and a value "
            f"that is not text was not written by it (feature 207)."
        )
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise ProposalContentError(
            f"the stored {column} for node {node!r} does not parse as an "
            f"instant ({text!r}): {exc}. The column holds the moment the "
            f"proposal entered the history, rendered by _format_instant, so a "
            f"value that does not parse is a row this store did not write — "
            f"and a history ordered by a guessed timestamp would be an order "
            f"the campaign did not have (feature 207)."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProposalContentError(
            f"the stored {column} for node {node!r} is {text!r}, which names "
            f"no instant: a naive timestamp makes the history's order a fact "
            f"about the machine that reads it rather than about the campaign "
            f"(feature 207)."
        )
    return parsed.astimezone(UTC)


# ── One node's pair — the record a write leaves behind ────────────────────────


class ProposalRecord:
    """One node's proposal document plus its score record — the stored pair.

    What :meth:`ProposalStore.persist` answers and what
    :meth:`ProposalStore.load` hands back: the document text, the identity
    digest taken over it, the score snapshot, and the two instants.  It is the
    value a caller holds when it wants to *show* a proposal — a review tool, an
    operator's listing — and it is deliberately not what the history read
    returns; see :meth:`ProposalHistoryStore.history`.

    **It carries the `node_id` and the `campaign_id`, and neither is restored
    from the document.**  Both are keys: the node's from 0118, the campaign's
    from the ``node`` row at the moment of the write, so a proposal recorded
    against a node whose campaign the caller mis-stated is a fact the record
    makes visible rather than one it hides.  The store refuses the mismatch
    instead of recording it — see :meth:`ProposalStore.persist`.

    **`recorded` is the idempotence signal, and it is 240's ``appended``.**  A
    retry of the same pair reports ``recorded=False`` and carries the *stored*
    instants, not the caller's: a retry is the same proposal arriving twice, and
    the row is that proposal — the retry did not move the moment it was
    written.  §14 demands this of the workers this runs on, and a caller that
    could not see which of the two it got could not report whether it changed
    anything.
    """

    __slots__ = (
        "campaign_id",
        "code_hash",
        "detail",
        "generated_at",
        "node_id",
        "proposal",
        "recorded",
        "recorded_at",
        "score",
    )

    def __init__(
        self,
        *,
        node_id: str,
        campaign_id: str,
        proposal: str,
        code_hash: str,
        score: ScoreRecord,
        generated_at: datetime,
        recorded_at: datetime,
        recorded: bool,
        detail: str = "",
    ) -> None:
        self.node_id = node_id
        self.campaign_id = campaign_id
        self.proposal = proposal
        self.code_hash = code_hash
        self.score = score
        self.generated_at = generated_at
        self.recorded_at = recorded_at
        self.recorded = recorded
        #: The sentence describing this outcome, for a log.  Built by whoever
        #: produced the record rather than composed here, because the two
        #: producers — a first write and an idempotent retry — describe
        #: different events and the difference *is* the sentence; a record read
        #: back from the store carries an empty one, because a read is not an
        #: event that wrote anything.
        self.detail = detail

    @property
    def as_prior(self) -> PriorProposal:
        """This record as feature 206's value — the hand-off to the reader.

        The one-line bridge between the two features, and the reason it is a
        property rather than a second method on the store: a record that is
        already in hand should not need a round trip through the database to be
        handed to the history law.  :class:`~signal_agent.PriorProposal` carries
        exactly the three fields the authoring step reads, and this record holds
        all three — which is what makes the writer's output literally the
        reader's input.
        """
        return PriorProposal(
            node_id=self.node_id,
            proposal=self.proposal,
            code_hash=self.code_hash,
        )

    def __repr__(self) -> str:
        return (
            f"ProposalRecord(node_id={self.node_id!r}, "
            f"chars={len(self.proposal)}, recorded={self.recorded}, "
            f"score={self.score!r})"
        )


# ── The store — the writer and the reader over ``node_proposal`` ──────────────


class ProposalStore:
    """The writer and reader of one node's proposal-plus-score pair.

    Constructed with the database URL holding the tree store.  Four operations,
    and the split between them is the split between the feature's two readers:

    * :meth:`persist` — records one node's pair.  Feature 207's *"persists"*.
    * :meth:`load` — reads one node's pair back.  The single-node question.
    * :meth:`history` — every recorded pair of a campaign, in order, as the
      values feature 206 judges.  The *replayable history* reader.
    * :meth:`counted` — how many nodes of a campaign are recorded.  The
      cheap completeness read a driver uses to decide whether a round has a
      history to hand over at all.

    The class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states and the reason
    :meth:`ProposalHistoryStore._required_store` can hand a ``DATABASE_URL``
    this member cannot speak to a caller that never persists anything.

    **Two tables, one owner each.**  The ``node_proposal`` **table** is this
    member's and is created lazily by :meth:`_connect`.  The ``node`` table
    beside it belongs to ``0118`` (feature 97) and its metric columns to
    ``0114`` (feature 101); none of that is this member's to create, alter or
    version — so the read that builds a score record is a **projection** over
    the live table, and a database that has not reached a column is answered
    honestly rather than refused.  See :func:`_scored_columns`.

    **The store holds no cache.**  The row is the only record of what a round
    read, which is the entire point — a later round replays it days afterwards,
    in another process — so it is the only thing an answer is drawn from.  A
    memo here would make *"what did this proposal score?"* a question about
    this process's history rather than about the campaign.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ProposalHistoryStoreUnavailableError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL; a "
                f"proposal document and its score record are rows beside the "
                f"discovery tree, so there must be a store holding the tree"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.  A URL this
        # member cannot speak is refused by name at that first use.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> ProposalStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        the law with ``store=None`` — a discoverable state, not an exception —
        while a caller that must persist a proposal is the caller that must not
        find itself in it.  The same stance
        :meth:`signal_agent.MechanismStore.resolve` takes, and for the same
        reason: the factory builds every registered component on every
        ``create_app()``, so a builder that raised here would take composition
        down workspace-wide for a deployment that simply has no database yet.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ProposalStore:
        """The store ``DATABASE_URL`` names, refused by name when it names none.

        The caller-side twin of :meth:`resolve`, for a caller that *must* have a
        store — a migration script, an operator tool, a test that is about to
        write a row.  Split from ``resolve`` rather than spelled as a ``raise``
        at each call site so that the "is there a store?" decision is made once,
        in the open, by a caller that knows which of the two questions it is
        asking.
        """
        store = cls.resolve(env)
        if store is None:
            raise ProposalHistoryStoreUnavailableError(
                f"{DATABASE_URL_ENV} names no relational store, so there is no "
                f"database to record feature 207's {PROPOSAL_DOCUMENT_NAME} and "
                f"{SCORE_RECORD_NAME} in. Point {DATABASE_URL_ENV} at the tree "
                f"store the discovery tree's node rows live in."
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
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and bring this member's own table into existence.

        One ``CREATE TABLE IF NOT EXISTS``, the contract every store in this
        workspace states: a fresh database and one this build has written to a
        hundred times must both work, and a member-owned table is the one piece
        of DDL this member is entitled to run.

        **The ``node`` table is not touched here.**  Creating it would be this
        member legislating DDL feature 97 owns, and creating 0114's *columns*
        would be worse still, because it would paper over exactly the gap
        :func:`_scored_columns` exists to report honestly.  The probe runs
        per-operation instead, naming ``0118``.

        The caller owns the connection; use it as a context manager to commit,
        which is what :meth:`persist` does — the row read and the ``INSERT``
        are one unit of work and must be one transaction, or two workers
        recording two nodes of one campaign could interleave a campaign read
        and a write.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(_SCHEMA)
        return connection

    # -- The write ----------------------------------------------------------

    def persist(
        self,
        node_id: Any,
        proposal: Any,
        *,
        score: Any = None,
        generated_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ProposalRecord:
        """Record one node's proposal document plus its score record.

        Feature 207's *"persists"* as one call: the node's id and the agent's
        proposal in, the recorded pair — and whether *this* call wrote it —
        out.  The state machine is :meth:`_state`'s; this method is its
        signature and its docstring.

        **The score defaults to what the node's row currently holds.**  That
        is the documented path: the evaluator has just written the metrics onto
        ``node`` (feature 85's step 12), the round has the proposal text in
        hand, and the two together are the pair §14.1 reads.  A caller may pass
        ``score`` explicitly — a re-recording test, an import of a history from
        before this table existed, a driver that measured something the row
        does not carry — and it is validated the same way either branch is.

        **The campaign is read off the ``node`` row, never taken as an
        argument.**  A caller-supplied campaign id would be a second spelling of
        a fact the tree already holds, and one that could disagree with it: a
        node whose row says campaign *A* recorded under campaign *B* would make
        :meth:`history`'s scope a lie.  So the row is the authority, and the
        scope the history read uses is the tree's own.

        **The three states of the ask, and why all three are legal.**  The same
        four-state machine :meth:`signal_agent.MechanismStore.persist` runs,
        with the document in the place of the rationale:

        * **a first write** → the row is inserted, ``recorded`` is ``True``, and
          the sentence opens with :data:`PROPOSAL_PERSISTED_CODE`.
        * **the identical pair re-issued** → the idempotent retry.  The
          *stored* instants and the *stored* score are reported rather than the
          caller's: a retry is the same proposal arriving twice, so the row is
          the proposal and the retry did not move the moment it was written.
          The score is compared by its rendered document, so two spellings of
          one measurement are one measurement — the canonicalisation argument
          :meth:`signal_agent.MechanismStore.persist` makes for its own text.
        * **a different document, or a different score, for a node that already
          has one** → :class:`~signal_agent.errors.ProposalConflictError`,
          naming both digests.  A different document is a *different proposal*
          and belongs on a *different node*; a different score for the same
          document is a re-measurement, and §14.1's history is a record of what
          a round read rather than a live view of the tree.

        Refuses, in order: an id that is not UUID text
        (:class:`~signal_agent.errors.ProposalContentError`); a document that
        is not non-empty text (the same class); a score that is not a
        :class:`ScoreRecord` and not ``None`` (the same class); a database
        holding no ``node`` table, and a node the tree does not hold (both
        :class:`~signal_agent.errors.ProposalNodeNotRecordedError`); and a
        conflict (:class:`~signal_agent.errors.ProposalConflictError`).
        """
        return self._state(
            node_id, proposal, score=score, generated_at=generated_at, now=now
        )

    def _state(
        self,
        node_id: Any,
        proposal: Any,
        *,
        score: Any,
        generated_at: datetime | None,
        now: datetime | None,
    ) -> ProposalRecord:
        """The state machine :meth:`persist` runs.

        Split out so :meth:`persist`'s docstring can be about the feature's
        sentence rather than about a branch nest, and so the states are one
        body: the validation order, the probe, the conflict, and the two
        recorded shapes.  One of them returns before the ``INSERT`` and one
        falls through to it.
        """
        node = _validated_node_id(node_id)
        document = _validated_document(proposal)
        digest = _document_digest(document)
        recorded_at = (
            _require_instant(datetime.now(UTC), "the recording instant")
            if now is None
            else _require_instant(now, "the recording instant")
        )
        with closing(self._connect()) as connection, connection:
            columns = _scored_columns(connection, node)
            row = _row_for(connection, node, (CAMPAIGN_ID_COLUMN, *columns))
            campaign = _validated_campaign_id(row[CAMPAIGN_ID_COLUMN])
            offered = self._offered_score(score, row, node)
            existing = connection.execute(
                f"SELECT {', '.join(c for c in NODE_PROPOSAL_COLUMNS if c != 'node_id')} "
                f"FROM {NODE_PROPOSAL_TABLE} WHERE node_id = ?",
                (node,),
            ).fetchone()
            if existing is not None:
                return self._answer_stored(
                    node, campaign, document, digest, offered, existing
                )
            generated = (
                recorded_at
                if generated_at is None
                else _require_instant(generated_at, "the proposal's instant")
            )
            connection.execute(
                f"INSERT INTO {NODE_PROPOSAL_TABLE} "
                f"({', '.join(NODE_PROPOSAL_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in NODE_PROPOSAL_COLUMNS)})",
                (
                    node,
                    campaign,
                    document,
                    digest,
                    offered.to_json(),
                    _format_instant(generated),
                    _format_instant(recorded_at),
                ),
            )
        return ProposalRecord(
            node_id=node,
            campaign_id=campaign,
            proposal=document,
            code_hash=digest,
            score=offered,
            generated_at=generated,
            recorded_at=recorded_at,
            recorded=True,
            detail=(
                f"{PROPOSAL_PERSISTED_CODE}: node {node} recorded "
                f"{PROPOSAL_DOCUMENT_NAME} ({len(document)} character(s), "
                f"code_hash {digest}) beside {SCORE_RECORD_NAME} measuring "
                f"{len(offered.measured())} of {len(METRIC_COLUMNS)} metric(s)"
                f"{' under fail_class ' + repr(offered.fail_class) if offered.fail_class else ''}"
                f". The pair is the unit architecture §14.1 reads the history "
                f"in — proposal.md plus its score.json, per node — and it is "
                f"stored as a snapshot rather than joined from the node row, "
                f"because feature 240 refreshes that row in place and a history "
                f"that answered differently each time it was read could not be "
                f"replayed (feature 207)."
            ),
        )

    def _offered_score(
        self, score: Any, row: Mapping[str, Any], node: str
    ) -> ScoreRecord:
        """The score record this call is about to record.

        Two branches and one validation point.  ``score=None`` means *snapshot
        the node's row now*, which is the documented path; anything else must
        already be a :class:`ScoreRecord`, and a caller that handed over a
        mapping gets a named refusal rather than a silent ``.to_json()`` on the
        wrong type.

        A mapping is *deliberately* not accepted.  :meth:`ScoreRecord.from_row`
        exists and is what this branch calls, so the conversion is available —
        but doing it implicitly here would mean a caller's typo in a key became
        an absent measurement, which is the one direction this module refuses
        to launder.  A caller that has a row builds the record explicitly and
        sees the field names it chose.
        """
        if score is None:
            return ScoreRecord.from_row(row)
        if isinstance(score, ScoreRecord):
            return score
        raise ProposalContentError(
            f"the score record for node {node!r} must be a ScoreRecord or "
            f"None, got {score!r} ({type(score).__name__}): None means "
            f"*snapshot the node's own metrics now*, which is the path a round "
            f"takes after feature 85's step 12 has written them — and a caller "
            f"holding something else builds a ScoreRecord explicitly so a "
            f"mistyped field is a visible choice rather than a silent absence "
            f"(feature 207)."
        )

    def _answer_stored(
        self,
        node: str,
        campaign: str,
        document: str,
        digest: str,
        offered: ScoreRecord,
        existing: Sequence[Any],
    ) -> ProposalRecord:
        """Answer a write for a node that already has a recorded pair.

        Always returns, and its two branches are the two states a repeat can
        be in — the idempotent retry and the conflict.  Spelled as a helper
        rather than inline so :meth:`_state` reads as the states it answers
        rather than as a nest of branches around one long message, the shape
        :meth:`signal_agent.MechanismStore._raise_conflict` takes.

        **The comparison is over the rendered documents, not the objects.**  A
        score is equal when its ``score.json`` is equal, because that rendered
        text is what the row holds and what a reader will parse: comparing the
        Python objects instead would make equality depend on this module's
        field order, and would call two records equal that store differently —
        including the one case that matters, a record that differs only by a
        metric the *other* record leaves absent.

        **Both halves must agree, and the document is checked first.**  A
        repeat that matches the document and not the score is a *re-measurement*
        of the same proposal — feature 244 re-runs interrupted attempts, and a
        re-run scores again.  It is refused rather than overwritten, and the
        reason is the feature: §14.1 reads the history to decide what to try
        next, so the figure beside a proposal is evidence about a *round*, and
        a store that updated it in place would make every earlier round's
        reasoning describe a number that no longer exists.  The repair is the
        one the message names — the stored pair is readable with
        :meth:`load`, and a genuinely new measurement belongs to the new
        attempt's node, which the identity law
        (:func:`discovery.expansion.refined_node_id`) already distinguishes.
        """
        stored_campaign, stored_document, stored_hash, stored_score, stored_gen, stored_rec = (
            existing
        )
        assert isinstance(stored_document, str), "a TEXT column returns text"
        assert isinstance(stored_score, str), "a TEXT column returns text"
        stored_digest = _document_digest(stored_document)
        if stored_digest != stored_hash:
            # A row that does not hash to its own identity.  This is the
            # corruption direction feature 206's reader refuses on its input,
            # caught here where the row is written — and it is refused rather
            # than reported, because every later read of this node would
            # otherwise hand the history a document whose digest is a claim
            # about some other text.
            raise ProposalContentError(
                f"node {node!r}'s stored {PROPOSAL_DOCUMENT_NAME} does not "
                f"hash to the code_hash the row carries: the stored document "
                f"is {stored_digest} and the row says {stored_hash}. The "
                f"column holds the digest of the exact source the sandbox "
                f"executed, and feature 206's history law recomputes it over "
                f"the text it reads — so this row would be handed to the "
                f"authoring step as a *truncated* proposal, which is the "
                f"failure that law exists to refuse, arriving from the store "
                f"rather than from the loader. The row was not written by "
                f"this store or has since been corrupted; re-record the node "
                f"(feature 207)."
            )
        same_document = stored_document == document
        same_score = stored_score == offered.to_json()
        if same_document and same_score:
            return ProposalRecord(
                node_id=node,
                campaign_id=stored_campaign,
                proposal=stored_document,
                code_hash=stored_hash,
                score=ScoreRecord.from_json(stored_score, node),
                generated_at=_parse_instant(stored_gen, node, "generated_at"),
                recorded_at=_parse_instant(stored_rec, node, "recorded_at"),
                recorded=False,
                detail=(
                    f"{PROPOSAL_PERSISTED_CODE}: node {node} already records "
                    f"this exact pair ({PROPOSAL_DOCUMENT_NAME} of "
                    f"{len(stored_document)} character(s), code_hash "
                    f"{stored_hash}, and the same {SCORE_RECORD_NAME}) — this "
                    f"call is the idempotent retry of a write that already "
                    f"happened, so nothing was written and the row's own "
                    f"instants are reported rather than this call's. A retry "
                    f"is the same proposal arriving twice, and the row is the "
                    f"proposal: the retry did not move the moment it was "
                    f"recorded (feature 207)."
                ),
            )
        raise ProposalConflictError(
            self._conflict_message(
                node, document, digest, offered, stored_document, stored_hash,
                stored_score, same_document,
            )
        )

    def _conflict_message(
        self,
        node: str,
        document: str,
        digest: str,
        offered: ScoreRecord,
        stored_document: str,
        stored_hash: str,
        stored_score: str,
        same_document: bool,
    ) -> str:
        """The sentence refusing a repeat that disagrees with the stored pair.

        One message with two halves, because the two disagreements are two
        different facts about the campaign and a reader needs to know which one
        it is holding.  Written as a helper rather than inline so the branch
        that *causes* the refusal stays legible in :meth:`_answer_stored`.
        """
        if same_document:
            return (
                f"node {node!r} already records {PROPOSAL_DOCUMENT_NAME} with "
                f"code_hash {stored_hash}, and this call carries the same "
                f"document ({digest}) but a different {SCORE_RECORD_NAME}: the "
                f"stored score is {stored_score} and this call offers "
                f"{offered.to_json()}. Refusing: architecture §14.1 reads the "
                f"history — the proposal *plus its score* — to decide what to "
                f"try next, so the figure beside a proposal is evidence about "
                f"the round that read it. A store that updated it in place "
                f"would leave every earlier round's reasoning describing a "
                f"number that no longer exists. The stored pair is readable "
                f"with load(); if this is a genuinely new measurement of the "
                f"same signal, it belongs to the new attempt's node — feature "
                f"239's derivation already gives that attempt its own id "
                f"(feature 207)."
            )
        return (
            f"node {node!r} already records a different {PROPOSAL_DOCUMENT_NAME}"
            f" — code_hash {stored_hash} against this call's {digest} — and a "
            f"node's proposal is history rather than a field: it is what a "
            f"later round reads *in full* (architecture §14.1) and what "
            f"feature 206's identity check recomputes over, so replacing it "
            f"would leave every stored score referring to a proposal the row "
            f"no longer holds, and would make the history a record of whatever "
            f"was written last. Two documents that differ are two proposals, "
            f"and two proposals are two nodes: the stored pair is readable with "
            f"load(), and the new proposal belongs on the node the expansion "
            f"gives it (feature 207)."
        )

    # -- The reads ----------------------------------------------------------

    def load(self, node_id: Any) -> ProposalRecord | None:
        """Read one node's recorded pair back, or ``None`` when there is none.

        ``None`` means *this node's proposal has never been recorded* — the
        positive fact the missing row is — and never *the node is absent* (which
        raises) or *the read failed* (which raises).  Three-way distinction
        preserved, the discipline :meth:`signal_agent.MechanismStore.load`
        states for its own column: a caller can never mistake a node whose
        proposal is unrecorded for a node that is not there, or a broken store
        for either.

        **A read re-verifies the document's identity and deliberately does not
        refuse a row whose live metrics have moved on.**  The stored digest is
        recomputed over the stored text — that is the check feature 206 depends
        on, and a row that fails it is refused by name.  The *node row's*
        current metrics are not read at all: a retry refreshing an evaluated
        node is legal and expected (feature 240's module docstring says the row
        is updated in place; feature 244 re-runs interrupted attempts), so a
        read that refused a row on that basis would brick the history of every
        retried node.  The whole point of storing the score is that this read
        does not consult the tree for it.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {', '.join(c for c in NODE_PROPOSAL_COLUMNS if c != 'node_id')} "
                f"FROM {NODE_PROPOSAL_TABLE} WHERE node_id = ?",
                (node,),
            ).fetchone()
        if row is None:
            return None
        return self._recorded(node, row, recorded=False, detail="")

    def history(
        self, campaign_id: Any, *, node_ids: Iterable[Any] | None = None
    ) -> tuple[PriorProposal, ...]:
        """A campaign's recorded pairs, as the values feature 206 judges.

        **This is the seam, and it is deliberately a returned value rather than
        a coupling.**  The answer is ``tuple[PriorProposal, ...]`` — feature
        206's own type, imported rather than re-spelled — so the writer's
        output is *literally* the reader's input and
        :meth:`~signal_agent.ProposalHistory.admit` cannot disagree with this
        method about what a history is made of.  A caller's whole history step
        is therefore:

        ``history_law.admit(store.history(campaign), prior_nodes=...)``

        and the round trip that makes the word *replayable* mean something is
        one line rather than a translation layer that could drift.

        **Ordered by the recorded instant, then by node id.**  §14.1's prompt
        reads the history in an order and prices it as an *append-only, stable
        prefix* — the caching argument at §14.1 rests on sibling calls sharing
        an identical prefix — so this read must be deterministic and must be the
        same order the campaign wrote in.  The instant alone is not enough:
        siblings of one batch are recorded in the same microsecond (§14.1's
        depth role runs ``W`` branches concurrently), so the node id is the
        tie-break, and the result is a total order that does not depend on
        SQLite's row layout.  A soft-delete or an update never reorders it: the
        rows are append-only by construction.

        **``node_ids`` scopes and filters, and an unknown id is not an error.**
        A caller that already knows which nodes the round is about — the
        expansion's frontier, a replay's revealed prefix — passes them and gets
        its own order back, empty entries omitted.  It is a *filter*, not a
        fetch: asking for an id with no recorded proposal returns a shorter
        tuple rather than raising, because that is exactly the state feature
        206's ``prior_nodes`` declaration exists to detect — a round that says
        *these nodes are prior* and hands over fewer is refused by the history
        law as a silent drop, with the node named.  Raising here instead would
        move that judgment out of the law and into the store, and would make
        the law's own measurement of dropped proposals impossible.
        """
        campaign = _validated_campaign_id(campaign_id)
        wanted = None
        if node_ids is not None:
            wanted = [_validated_node_id(node) for node in node_ids]
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT node_id, {', '.join(c for c in NODE_PROPOSAL_COLUMNS if c != 'node_id')} "
                f"FROM {NODE_PROPOSAL_TABLE} WHERE campaign_id = ? "
                f"ORDER BY recorded_at ASC, node_id ASC",
                (campaign,),
            ).fetchall()
        records = [self._recorded(row[0], row[1:], recorded=False, detail="") for row in rows]
        if wanted is None:
            return tuple(record.as_prior for record in records)
        by_node = {record.node_id: record for record in records}
        return tuple(
            by_node[node].as_prior for node in wanted if node in by_node
        )

    def counted(self, campaign_id: Any) -> int:
        """How many of a campaign's nodes have a recorded pair.

        The cheap read a driver uses to decide whether a round has a history to
        hand over at all, and the figure a completeness check compares against
        the campaign's node count.  It counts *rows in this table*, not nodes in
        the tree: a campaign whose tree holds 500 nodes and whose table holds
        12 has 488 proposals that were never recorded, and that gap is the
        fact worth surfacing — feature 206 can only refuse a history it was
        handed, so a round that hands over nothing is refused by nothing.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM {NODE_PROPOSAL_TABLE} WHERE campaign_id = ?",
                (campaign,),
            ).fetchone()
        return int(count)

    def recorded_nodes(self, campaign_id: Any) -> tuple[str, ...]:
        """The ids of a campaign's nodes that have a recorded pair, sorted.

        The companion of :meth:`counted`, for a caller that wants to know
        *which* nodes the history covers rather than how many — a driver
        reconciling the table against the tree, or a round deciding which of the
        expansion's nodes it can hand over in full.  Sorted lexically rather
        than by instant, because this is the set question: the order a history
        is *read* in is :meth:`history`'s, and answering the set question with
        the reading order would invite a caller to use one for the other.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT node_id FROM {NODE_PROPOSAL_TABLE} "
                f"WHERE campaign_id = ? ORDER BY node_id ASC",
                (campaign,),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def _recorded(
        self, node: str, row: Sequence[Any], *, recorded: bool, detail: str
    ) -> ProposalRecord:
        """Build the record for one stored row, re-verifying its identity.

        The one place a stored row becomes a :class:`ProposalRecord`, so the
        single-row read, the history read and the retry's answer cannot
        disagree about what a row holds — the discipline
        :meth:`signal_agent.MechanismStore._recorded` states.  ``recorded`` and
        ``detail`` are passed through rather than computed: the retry path
        builds its own sentence and wants ``recorded=False``, and hardcoding
        either here would make a flag that says ``True`` about a call that did
        not write.

        **The identity check lives here.**  Every read of a stored row goes
        through this method, so a row whose document does not hash to its
        ``code_hash`` is refused on *any* path — the single-node read, the
        history read, and the retry — rather than only where somebody thought
        to check.  That matters because the history read is the one that feeds
        feature 206, and the failure mode of a bad digest is a proposal the
        authoring step believes is whole.  Checked on read as well as on write,
        because the write only ever sees the row *it* is about to create.
        """
        campaign, document, code_hash, score_text, generated, recorded_at = row
        assert isinstance(document, str), "a TEXT column returns text"
        assert isinstance(score_text, str), "a TEXT column returns text"
        digest = _document_digest(document)
        if digest != code_hash:
            raise ProposalContentError(
                f"node {node!r}'s stored {PROPOSAL_DOCUMENT_NAME} does not "
                f"hash to the code_hash the row carries: the stored document "
                f"is {digest} and the row says {code_hash}. The column holds "
                f"the digest of the exact source the sandbox executed, and "
                f"feature 206's history law recomputes it over the text it "
                f"reads — so this row would be handed to the authoring step as "
                f"a *truncated* proposal, which is the failure that law exists "
                f"to refuse, arriving from the store rather than from the "
                f"loader. Refusing the read rather than reporting a digest no "
                f"text agrees with (feature 207)."
            )
        return ProposalRecord(
            node_id=node,
            campaign_id=campaign,
            proposal=document,
            code_hash=code_hash,
            score=ScoreRecord.from_json(score_text, node),
            generated_at=_parse_instant(generated, node, "generated_at"),
            recorded_at=_parse_instant(recorded_at, node, "recorded_at"),
            recorded=recorded,
            detail=detail,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ProposalStore(path={str(self.path)!r})"


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The convention every store in this workspace uses, restated here so this
    store states its own contract and the refusal is this module's own error
    class.  A non-SQLite scheme is refused by name (the spec's single-machine
    allowance is what a stdlib store can speak), and an in-memory URL is
    refused too: a recorded proposal must outlive the recording call — the
    round that reads it, and the replay that re-derives its figure, run in
    another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ProposalHistoryStoreUnavailableError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            f"store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the tree's node "
            f"rows already live in (feature 207)."
        )
    if parsed.netloc not in ("", "localhost"):
        raise ProposalHistoryStoreUnavailableError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 207)."
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise ProposalHistoryStoreUnavailableError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            f"database would die with the connection that opened it, and "
            f"feature 207's proposal-plus-score pair *is* the replayable "
            f"history — the round that reads it and the replay that re-derives "
            f"its figure both run in another process (feature 207)."
        )
    return Path(path)


# ── The law — the composed handle ─────────────────────────────────────────────


class ProposalHistoryStore:
    """Feature 207's law: the store, when the deployment has one.

    The value a composed application carries, in the shape
    :class:`signal_agent.StatedMechanism` gives feature 211 and
    :class:`signal_agent.SignalContract` gives feature 205 — so a caller
    holding the composed component can ask feature 207's questions without
    importing this submodule by name.

    **It carries a store, and the store is optional.**  ``store=None`` is the
    state a deployment reaches by naming no ``DATABASE_URL``, and it is a
    *discoverable* state rather than a broken one — the stance
    :meth:`signal_agent.MechanismStore.resolve` takes for its own ``None``.  It
    is not an empty store: an empty store answers *no proposal is recorded
    here* about every id, while this says there is no database to have recorded
    one in — and a proposal recorded into nothing is a history no round will
    ever replay.

    **Why one component and not two.**  The writer and the reader are one
    feature's subject: a caller holding the history read separately from the
    writer would be able to assemble a round's history from a store it cannot
    record into, which is exactly the half-wired shape the sentence's *"persists
    … which together form"* is meant to hold together — the argument
    :class:`signal_agent.StatedMechanism` makes for its own pairing.  So they
    are one handle, one seat and one registration.

    **What the handle does not re-implement.**  Every verb delegates to
    :class:`ProposalStore`; there is no second spelling of the state machine,
    the ordering or the identity check.  What this class adds is
    discoverability, the composed seam, and the one named refusal a deployment
    with no database needs — :meth:`_required_store`.
    """

    __slots__ = ("_store",)

    def __init__(self, store: ProposalStore | None = None) -> None:
        self._store = store

    # -- The write ----------------------------------------------------------

    def persist(
        self,
        node_id: Any,
        proposal: Any,
        *,
        score: Any = None,
        generated_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ProposalRecord:
        """Record one node's proposal document plus its score record.

        Delegated to :meth:`ProposalStore.persist` — this facade adds
        discoverability and the composed seam, and restating the four states
        here would be a second thing to keep in sync with them.  Raises
        :class:`~signal_agent.errors.ProposalHistoryStoreUnavailableError` when
        the component was composed with no store.
        """
        return self._required_store().persist(
            node_id, proposal, score=score, generated_at=generated_at, now=now
        )

    # -- The reads ----------------------------------------------------------

    def load(self, node_id: Any) -> ProposalRecord | None:
        """Read one node's recorded pair back, or ``None`` when unrecorded.

        ``None`` means *this node's proposal has never been recorded*, never
        *the node is absent* (which raises) and never *the read failed* (which
        raises).  The three-way distinction :meth:`ProposalStore.load` states.
        """
        return self._required_store().load(node_id)

    def history(
        self, campaign_id: Any, *, node_ids: Iterable[Any] | None = None
    ) -> tuple[PriorProposal, ...]:
        """A campaign's recorded pairs, as the values feature 206 judges.

        Delegated to :meth:`ProposalStore.history`, and this is the member's
        own seam: the tuple this returns is
        :class:`~signal_agent.PriorProposal` — feature 206's type — so a
        caller can hand it straight to
        :meth:`~signal_agent.ProposalHistory.admit` and the two features cannot
        disagree about what a history is made of.
        """
        return self._required_store().history(campaign_id, node_ids=node_ids)

    def counted(self, campaign_id: Any) -> int:
        """How many of a campaign's nodes have a recorded pair."""
        return self._required_store().counted(campaign_id)

    def recorded_nodes(self, campaign_id: Any) -> tuple[str, ...]:
        """The ids of a campaign's nodes that have a recorded pair, sorted."""
        return self._required_store().recorded_nodes(campaign_id)

    # -- Composition ---------------------------------------------------------

    @property
    def store(self) -> ProposalStore | None:
        """The store this law was composed with, or ``None``.

        Exposed so a caller can tell *this deployment has no history store*
        from *this deployment's history store holds no proposal* without
        catching an exception to find out — the distinction
        :attr:`signal_agent.StatedMechanism.store` draws for its own ``None``.
        Reading it refuses nothing: the store holds no capability.
        """
        return self._store

    def _required_store(self) -> ProposalStore:
        """The store, or a named refusal saying there is none.

        The one place
        :class:`~signal_agent.errors.ProposalHistoryStoreUnavailableError` is
        raised in this class, so the store-backed verbs report the same fact in
        the same words.
        """
        if self._store is None:
            raise ProposalHistoryStoreUnavailableError(
                f"this signal-agent member was composed with no proposal "
                f"history store: {DATABASE_URL_ENV} names no relational store "
                f"in this deployment, so there is no {NODE_PROPOSAL_TABLE} "
                f"table to record feature 207's {PROPOSAL_DOCUMENT_NAME} and "
                f"{SCORE_RECORD_NAME} in or read them back from. This is not "
                f"an empty store — an empty store would answer `no proposal is "
                f"recorded here` about every node, while this says there is no "
                f"database to have recorded one in, and a proposal recorded "
                f"into nothing is a history no round will ever replay. Point "
                f"{DATABASE_URL_ENV} at the tree store the discovery tree's "
                f"node rows live in, or ask the law's `store` property first "
                f"and treat its `None` as a refusal to proceed (feature 207)."
            )
        return self._store

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ProposalHistoryStore(store={'set' if self._store else 'none'})"


def proposal_history_store(
    env: Mapping[str, str] | None = None,
) -> ProposalHistoryStore:
    """The proposal-history law, composed from the environment.

    The module-level convenience every feature in this member ships beside its
    component: a caller — an operator script, a suite, the campaign driver —
    that wants feature 207's answers without standing up an application.  The
    component is what the factory builds and what a composed caller should use;
    this is the same law, composed from ``DATABASE_URL`` in one call.

    It **never** returns ``None``, and it never raises for a missing database.
    The law composes ``store=None`` rather than refusing to exist, so a
    deployment with no ``DATABASE_URL`` still gets a handle whose
    :attr:`ProposalHistoryStore.store` says so — and whose store-backed verbs
    raise :class:`~signal_agent.errors.ProposalHistoryStoreUnavailableError`
    when they are called.  Returning ``None`` here would make the feature
    unavailable in exactly the deployment that has the least other protection,
    which is backwards; the same argument
    :func:`signal_agent._mechanism.stated_mechanism` makes for its own.

    A function rather than a module-level instance so an importer never shares
    state with another importer of the same file under the loader's second name
    — the discipline every other law function in this member follows.
    """
    return ProposalHistoryStore(ProposalStore.resolve(env))
