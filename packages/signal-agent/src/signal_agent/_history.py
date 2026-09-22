"""Feature 206 — the history is read in full, or it is not a history.

*"Agent rejects a truncated history sample, reading every prior proposal in
full before proposing."*

PRD §C3 states the requirement as a rule about the *run*, not about the
proposal that comes out of it: *"The requirement to read the complete history
before proposing"*, in the same paragraph that draws the flawed-mechanism
versus located-bug distinction and insists on the explicit anti-convergence
clause.  Architecture §14.1 says what *complete* means, because the sentence
alone can be read as satisfied by any sufficiently long context window: the
authoring step reads *"every prior ``proposal.md`` **in full** — not a sample,
not recent cycles"*, and by the late rounds that is ~500K tokens.  Two
requirements are bundled in that clause and this law refuses them separately,
because they fail in different places: *every* is about the **set** of prior
proposals the assembler reached for, and *in full* is about each one it
reached for.

**Why the refusal is a returned value and not an exception.**  What a run does
about a truncated history is not this law's decision.  Feature 209 owns
whether a branch is retried at all, and a caller that wanted to *measure*
handed history — to log how often an assembler silently dropped a proposal,
which is exactly the question §14.1 says is untested: *"Truncating complete
proposals is a different operation from compressing them into prose, and is
probably safer — but it is an untested assumption and should be measured
before it is relied on"* — cannot do that through a raise.  So the verdict is
the value, ``admit`` never raises, and :meth:`ProposalHistory.require` is the
one place the exception exists, for a caller whose last line before proposing
wants it.

**The mechanism that makes this law honest.**  A law that only reads the
caller's own declarations — a ``sampled_from`` key, a ``truncated`` flag — is
satisfied by silence, and the whole failure mode §14.1:773 worries about is a
loader that truncates *without saying so*.  So the load-bearing check is
recomputed identity: an entry that carries both prior ``proposal`` text and
the ``code_hash`` §9.1 recorded for it is refused when
:func:`~signal_agent.source_code_hash` over the carried text disagrees with
the recorded digest.  A cut read cannot pass that check by staying quiet, and
a loader that wants to truncate has to admit it in a declaration, which is
refused too.  The declared-length fallback (``total``/``total_chars``) catches
the same thing when the digest is not available, and is weaker on purpose: it
is the caller's own arithmetic about its own read.

**What this law deliberately does not do.**  It does not pattern-scan proposal
text for truncation markers.  A marker is a convention, not an encoding: a
proposal may legitimately *quote* one — §14.1's own sentence would be such a
quote if it appeared in a ``proposal.md`` — and a genuinely truncated one may
carry no marker at all.  A scan would therefore produce both false refusals and
false admissions while looking like rigour.

**The boundary with feature 208.**  §14.1:773 draws the line this member
follows: *truncating* a proposal is a different operation from *compressing*
it into prose.  A summary *of one prior proposal* handed over as that
proposal's text is a sample of that proposal, and is refused here
(:data:`SAMPLED_HISTORY_CODE`).  Prose guidance *about the history* — a
synthesised narrative the prompt injects instead of the proposals — is feature
208's subject and is not this law's; this law never reads a summary as a
history, and never refuses one for being a summary of a summary.

**The asymmetry at the error.**  :class:`~signal_agent.TruncatedHistoryError`
is a *sibling* of :class:`~signal_agent.AgentSourceError`, not a subclass —
the discipline :class:`~signal_agent.FlawedMechanismError` states: a caller's
pre-existing ``except AgentSourceError:`` handler repairs by re-prompting the
agent, and re-prompting an agent whose prompt was assembled from a cut history
buys another proposal from the same cut history.  The repair here is to fix the
run's assembly, so the class must not be reachable through that clause.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Iterable, Mapping
from typing import Final

from ._authoring import source_code_hash
from .errors import TruncatedHistoryError

#: The name the plugin registers this law's component under.  Hyphenated like
#: its siblings so the seven stay contiguous in the loader's name-sorted
#: ``app.order``, and suffixed rather than bare so a later registration cannot
#: replace the plugin's own ``signal-agent`` component by colliding with it.
HISTORY_COMPONENT_NAME: Final[str] = "signal-agent-history"

#: The token a *complete* history's sentence opens with.  The feature's own
#: subject written as a word, so an operator grepping a campaign log for the
#: rounds that read the whole history finds them by it — the mirror of
#: :data:`~signal_agent.CONFORMS_CODE` on the adoption side, and the same
#: asymmetry :data:`~signal_agent.LEGAL_THEME_CODE` has: an admission is not a
#: code an operator greps a campaign for.
COMPLETE_HISTORY_CODE: Final[str] = "complete_history"

#: Refused: a prior proposal was handed over cut short.  §14.1's *"in full"*.
TRUNCATED_HISTORY_CODE: Final[str] = "truncated_history"

#: Refused: the history is a subset of the prior proposals — §14.1's *"not a
#: sample, not recent cycles"*.  Separate from :data:`TRUNCATED_HISTORY_CODE`
#: because the repairs are separate: this one is about which proposals the
#: assembler went and got, that one is about how much of each it carried.
SAMPLED_HISTORY_CODE: Final[str] = "sampled_history"

#: Refused: a prior proposal the caller declared should be here is not, and
#: nothing was handed over in its place — so the history silently dropped it.
#: Its own code rather than :data:`SAMPLED_HISTORY_CODE` because a declaration
#: of loss is a *loud* sample and this is the quiet one, and because the
#: sentence names the node, which is the repair.
MISSING_PROPOSAL_CODE: Final[str] = "missing_proposal"

#: Refused: what was handed over is not a history at all.  The caller's wiring
#: is wrong, not the history's contents — the same split
#: :class:`~signal_agent.AdoptionReason` draws between a value that was never
#: source and a proposal to refuse.
NOT_A_HISTORY_CODE: Final[str] = "not_a_history"

#: How many offending entries a refusal's sentence names before it stops and
#: counts the rest.  Bounded for the same reason
#: :data:`~signal_agent.MAX_LISTED_COMPLAINTS` is: the message is read by a
#: human fixing an assembler, and an unbounded list of a thousand dropped
#: proposals is a message nobody reads.
MAX_LISTED_OFFENDERS: Final[int] = 8

#: The fields an entry may carry, by name.  Read from a mapping key or an
#: attribute, so a caller may hand over its own record type — the duck-typed
#: seam feature 184's question and feature 190's adapter both use.
_ENTRY_FIELDS: Final[tuple[str, ...]] = ("node_id", "proposal", "code_hash")

#: Keys whose presence says the entry is a *subset chosen by a rule* — the
#: loader declaring "I took the last N", "I took the recent ones", "this is a
#: summary".  Refused regardless of value, including an empty collection: the
#: declaration is the admission, and a loader that carries the key at all is
#: describing an operation §14.1 forbids.  Sorted so the module reads the same
#: in every checkout.
_SAMPLED_DECLARATIONS: Final[frozenset[str]] = frozenset(
    {
        "dropped",
        "excluded",
        "first_n",
        "head",
        "last_n",
        "limit",
        "omitted",
        "recent",
        "recent_only",
        "sample",
        "sampled",
        "sampled_from",
        "slice",
        "summary",
        "summary_of",
        "tail",
        "trimmed",
    }
)

#: Keys whose presence says the entry was *cut short* — the same proposal, but
#: not all of it.
_TRUNCATED_DECLARATIONS: Final[frozenset[str]] = frozenset(
    {"cut", "cut_off", "elided", "incomplete", "partial", "truncated"}
)

#: Flags that assert wholeness.  Only an explicit ``False`` refuses: a
#: ``full: None`` is a record that never filled the field in, which
#: :data:`_TOTAL_KEYS`' check and the recomputed digest still govern, and
#: treating "unset" as "cut" would refuse every record type that carries the
#: field as optional.
_WHOLE_FLAGS: Final[tuple[str, ...]] = ("complete", "full", "in_full", "whole")

#: Keys declaring how much the source held before the read.  An entry carrying
#: one of these is checked: a declared total that no carried text can account
#: for is a cut read admitting it under another name.
_TOTAL_KEYS: Final[tuple[str, ...]] = ("total", "total_chars")

__all__ = [
    "COMPLETE_HISTORY_CODE",
    "HISTORY_COMPONENT_NAME",
    "MAX_LISTED_OFFENDERS",
    "MISSING_PROPOSAL_CODE",
    "NOT_A_HISTORY_CODE",
    "SAMPLED_HISTORY_CODE",
    "TRUNCATED_HISTORY_CODE",
    "HistoryReason",
    "HistoryVerdict",
    "PriorProposal",
    "ProposalHistory",
    "proposal_history",
]


class PriorProposal:
    """One prior proposal as the history carried it — identity plus text.

    The value a caller holds after a history was admitted, so the caller that
    wanted to *read* the history has something to read.  It is deliberately the
    same three fields §9.1's ``node`` row carries into the authoring step:
    ``node_id`` (which proposal this is, so a proposal can cite the one it
    departs from), ``proposal`` (the text, whole), and ``code_hash`` (what the
    tree recorded for it, so identity survives this member being imported
    twice by the loader).

    **The constructor refuses nothing.**  Wholeness is
    :meth:`ProposalHistory.admit`'s judgment — an entry handed over cut is a
    fact to refuse, and a constructor that raised on it would make this law's
    own verdict unreachable for the common case where the caller built the
    value first and asked afterwards.
    """

    __slots__ = ("code_hash", "node_id", "proposal")

    def __init__(self, node_id: str, proposal: str, code_hash: str = "") -> None:
        self.node_id = node_id
        self.proposal = proposal
        self.code_hash = code_hash

    def __eq__(self, other: object) -> bool:
        """Equal when the parts are equal — never by ``isinstance``.

        The loader imports every member twice, once by file path under a
        synthetic name and once as the importable member, so an
        ``isinstance`` check against this class would be false for a value
        built from the other import of the same file.  Equality over the parts
        is the same statement and survives that.
        """
        if not all(hasattr(other, name) for name in _ENTRY_FIELDS):
            return NotImplemented
        return (
            self.node_id == other.node_id
            and self.proposal == other.proposal
            and self.code_hash == other.code_hash
        )

    def __hash__(self) -> int:
        return hash((self.node_id, self.proposal, self.code_hash))

    def __repr__(self) -> str:
        return (
            f"PriorProposal(node_id={self.node_id!r}, "
            f"chars={len(self.proposal)}, code_hash={self.code_hash!r})"
        )


class HistoryReason(enum.StrEnum):
    """Why a history was admitted or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`HistoryVerdict.detail` opens with, so the reason is greppable in a
    campaign log without a lookup table and a refusal never opens with another
    reason's headline — the discipline
    :class:`~signal_agent.AntiConvergenceReason` states for its own.  The four
    refusals are split by *repair*: a subset needs the assembler to fetch more
    proposals, a cut read needs it to fetch more of each, a silent drop needs
    the node it dropped fetched, and a value that was never a history is a
    caller's bug rather than a history's defect.
    """

    #: Admitted: every prior proposal the run declared is here, whole.  Its
    #: detail opens with :data:`COMPLETE_HISTORY_CODE` rather than with this
    #: value, the one place this enum and its codes differ — the same asymmetry
    #: :attr:`~signal_agent.AntiConvergenceReason.NOVEL` has against
    #: :data:`~signal_agent.NOVEL_CODE`.  "complete" is the reason a caller
    #: branches on; "complete_history" is the word a log line opens with.
    COMPLETE = "complete"

    #: Refused: a prior proposal was carried cut short.  §14.1's *"in full"*.
    #: Spelled as the code itself, so branching on the value and grepping for
    #: it are the same string.
    TRUNCATED = TRUNCATED_HISTORY_CODE

    #: Refused: the history is a sample — a subset by rule, or a summary of a
    #: proposal rather than the proposal.
    SAMPLED = SAMPLED_HISTORY_CODE

    #: Refused: a declared prior proposal is absent, with nothing in its place.
    MISSING = MISSING_PROPOSAL_CODE

    #: Refused: what was handed over is not a history of prior proposals.
    NOT_A_HISTORY = NOT_A_HISTORY_CODE


class HistoryVerdict:
    """What the law decided about one history, plus the history it admitted.

    Read-only in the sense that matters: every field is set once, in
    :func:`_verdict`, from the *reason* and the entries that produced it —
    :attr:`complete` is never a constant a caller could set, and a verdict
    cannot disagree with its own reason.  The same shape
    :class:`~signal_agent.DeadTerritoryVerdict` and
    :class:`~signal_agent.AntiConvergenceVerdict` use.

    :attr:`entries` is empty on **every** refusal, including the ones where a
    prefix of the history was readable.  That is deliberate: the subset a law
    admitted before it found the hole *is* a sample, and returning it would let
    a caller propose from exactly the history this feature exists to refuse.
    The offending entries are carried separately, in :attr:`offenders`, for the
    message and for a log — named, never quoted, because this law's subject is
    which proposals were missing and the text of a proposal belongs in §9.2's
    artifact directory.
    """

    __slots__ = ("complete", "detail", "entries", "offenders", "reason")

    def __init__(
        self,
        reason: HistoryReason,
        detail: str,
        *,
        entries: Iterable[PriorProposal] = (),
        offenders: Iterable[str] = (),
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.offenders = tuple(offenders)
        #: Computed from the reason, never passed in: a verdict whose
        #: ``complete`` flag disagreed with its reason would be a value a
        #: caller could branch on twice and get two answers.
        self.complete = reason is HistoryReason.COMPLETE
        self.entries = tuple(entries) if self.complete else ()

    def require(self) -> tuple[PriorProposal, ...]:
        """Return the admitted history, or raise :class:`TruncatedHistoryError`.

        The only place this law raises.  A caller whose next line is the
        authoring call wants the raise; a caller measuring handed history
        branches on :attr:`complete` instead and never constructs the
        exception — which is why the verdict exists at all.
        """
        if not self.complete:
            raise TruncatedHistoryError(self.detail)
        return self.entries

    def __repr__(self) -> str:
        return (
            f"HistoryVerdict({self.reason.value!r}, "
            f"entries={len(self.entries)}, offenders={len(self.offenders)})"
        )


class _Entry:
    """One working entry while the history is being read — before judgment.

    Internal, and the only place the *declarations* are kept: the law's
    verdicts are made from the parts below, and keeping the raw declarations
    out of :class:`PriorProposal` means an admitted history cannot carry a
    ``sampled_from`` key a later reader would have to re-interpret.

    :attr:`recognised` is what makes the silent-drop loophole closed: an entry
    that named a node but yielded no text and no declaration is not "an entry
    with an empty proposal", it is an entry this law does not know how to
    read as a whole proposal — and the only safe reading of "I have this
    node's identity and none of its text" is that it was dropped.
    """

    __slots__ = (
        "code_hash",
        "declared_total",
        "loss",
        "node_id",
        "proposal",
        "recognised",
    )

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.proposal: str = ""
        self.code_hash: str = ""
        self.declared_total: int | None = None
        self.loss: HistoryReason | None = None
        self.recognised: bool = False


def _canonical_node_id(node_id: str) -> str:
    """A node id spelled the one way §9.1 spells it.

    UUID text canonicalised through :class:`uuid.UUID` so two spellings of the
    same node — uppercase, braces, a ``urn:uuid:`` prefix — are one id, which
    is the discipline :func:`~signal_agent._mechanism._validated_node_id`
    states for the nodes this member persists.  Anything that is not UUID text
    is kept stripped and unjudged: a caller may legitimately be reading a
    history from before ids were UUIDs, and refusing the spelling would be a
    refusal about this member's conventions rather than about the history.
    """
    text = node_id.strip()
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError):
        return text


def _field(entry: object, name: str) -> object:
    """Read one field from a mapping key or an attribute, or ``None``.

    The duck-typed seam: a caller hands over its own record type, a mapping, or
    a mapping-like object, and the law reads the three fields it knows by name
    without demanding a class — the same seam feature 190's ported-world
    adapter uses at feature 184's question interface.
    """
    if isinstance(entry, Mapping):
        return entry.get(name)
    return getattr(entry, name, None)


def _has(entry: object, name: str) -> bool:
    """Whether the entry carries the named field *at all* — key or attribute.

    The sibling of :func:`_field`, and the two must be used together: a
    declaration is read as present-and-truthy, so a caller handed a record
    type (``Record(node_id=..., truncated=True)``) must have its declarations
    honoured exactly as a mapping's are.  Reading only mappings would make this
    law's whole judgment depend on which shape the caller's loader produced —
    and the loader that silently truncates is the one most likely to hand over
    a typed record rather than a bare dict.
    """
    if isinstance(entry, Mapping):
        return name in entry
    return hasattr(entry, name)


def _declared_loss(entry: object) -> HistoryReason | None:
    """Which loss the entry's own declarations admit to, if any.

    Sampled before truncated when both are present: a loader that took the
    last N *and* cut them is describing a subset, and the subset is the repair
    a reader can act on without re-reading anything.

    Truthiness, not presence, for the declarations — with one exception.  A
    ``dropped: []`` is a loader that carried the key describing an operation it
    did not perform, and refusing that would refuse a record for its field
    names; the field *set* is not the offense, the loss is.  The whole-flags
    are the exception: they assert wholeness, so only an explicit ``False``
    refuses, and ``full: None`` stays a record that never filled the field in
    (the digest and :data:`_TOTAL_KEYS` still govern it).
    """
    for name in sorted(_SAMPLED_DECLARATIONS):
        if _has(entry, name) and _field(entry, name):
            return HistoryReason.SAMPLED
    for name in sorted(_TRUNCATED_DECLARATIONS):
        if _has(entry, name) and _field(entry, name):
            return HistoryReason.TRUNCATED
    for flag in sorted(_WHOLE_FLAGS):
        if _has(entry, flag) and _field(entry, flag) is False:
            return HistoryReason.TRUNCATED
    return None


def _declared_total(entry: object) -> int | None:
    """The length the loader says the proposal had before it read it.

    Positive integers only, and ``bool`` excluded by name: ``True`` is an
    ``int`` in Python, and a record carrying ``total: True`` is a record whose
    author wrote a flag where a count belongs — reading it as ``1`` would
    manufacture a truncation out of a type error.  The same affinity trap
    :func:`~signal_agent.locate_defect` guards at the diagnosis seam.
    """
    for name in _TOTAL_KEYS:
        value = _field(entry, name)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value > 0:
            return value
    return None


def _named(entry: object, index: int) -> str:
    """What to call an entry that did not name itself.

    Positional, and prefixed so a positional name can never be mistaken for a
    §9.1 node id: ``prior-3`` says "the fourth thing in the sequence you
    handed me", and a reader who saw it in a refusal knows to look at the
    assembler rather than at the tree.  The same convention
    :func:`~signal_agent._anti_convergence._held_digests` uses for a bare
    digest, and the same documented ambiguity: a bare string handed over as a
    prior proposal is **one** proposal, not an iterable of characters.
    """
    node_id = _field(entry, "node_id")
    if isinstance(node_id, str) and node_id.strip():
        return _canonical_node_id(node_id)
    return f"prior-{index}"


def _resolve(entry: object, index: int) -> _Entry:
    """Read one handed-over item into a working entry, or say it is unreadable.

    Five shapes are recognised, widest first, because a caller assembling a
    prompt has whatever its own loader produced:

    * a bare ``str`` — a prior proposal's **text**, the one-field case, since
      the common loader carries text and can look up the identity from the
      tree.  Named positionally; there is no id to name it by.
    * a ``(node_id, proposal)`` pair, or a longer sequence read positionally —
      the shape a caller that has both and no record type reaches for.
    * a mapping or an object carrying ``node_id`` / ``proposal`` /
      ``code_hash`` by name — the record case, and the only one that can carry
      declarations.
    * anything else: unrecognised.  Not refused *here* — the law refuses it,
      with the caller's index, because a refusal about one entry is the law's
      sentence to write and a helper that raised would put this member's error
      vocabulary in two places.
    """
    if isinstance(entry, str):
        resolved = _Entry(_named(entry, index))
        resolved.proposal = entry
        resolved.recognised = True
        return resolved

    if isinstance(entry, (tuple, list)):
        parts = list(entry)
        if len(parts) in (2, 3) and all(isinstance(p, str) for p in parts):
            resolved = _Entry(_canonical_node_id(parts[0]))
            resolved.proposal = parts[1]
            resolved.code_hash = parts[2] if len(parts) == 3 else ""
            resolved.recognised = True
            return resolved
        return _Entry(f"prior-{index}")

    if isinstance(entry, Mapping) or any(
        hasattr(entry, name) for name in _ENTRY_FIELDS
    ):
        resolved = _Entry(_named(entry, index))
        proposal = _field(entry, "proposal")
        if isinstance(proposal, str):
            resolved.proposal = proposal
        code_hash = _field(entry, "code_hash")
        if isinstance(code_hash, str):
            resolved.code_hash = code_hash
        resolved.declared_total = _declared_total(entry)
        resolved.loss = _declared_loss(entry)
        #: An entry is read as a proposal when it carried one, *or* when it
        #: declared how much of one there was.  The second arm is what makes
        #: the cut read visible: ``{"node_id": n, "proposal": "half…",
        #: "truncated": True}`` has no other way to be seen, and
        #: ``{"node_id": n}`` alone stays unrecognised on purpose.
        resolved.recognised = bool(
            resolved.proposal or resolved.loss or resolved.declared_total
        )
        return resolved

    return _Entry(f"prior-{index}")


def _entries_of(history: object) -> list[_Entry] | None:
    """Every entry the handed-over history contains, or ``None`` if it is not one.

    A bare ``str`` and a single mapping are each **one** entry, not a history:
    the caller handed a proposal where a sequence of proposals belongs, and at
    the feature-206 seam that is precisely the truncated *sample* — §14.1's
    *"not a sample"* — so it must not be read as a one-proposal history that
    happens to be complete.  Reading it as one entry would admit the exact
    input this law exists to refuse.

    ``None`` is not a history either — it is the absence of one.  An *empty*
    sequence is: a run that has never proposed has read the whole of a history
    that is empty, and refusing that would block the first proposal of every
    campaign.  A mapping with no sequence in it is not a history, and is
    refused rather than treated as empty for the same reason a bare string is.
    """
    if isinstance(history, (str, bytes, Mapping)):
        return None
    if not isinstance(history, Iterable):
        return None
    return [_resolve(entry, index) for index, entry in enumerate(history)]


def _declared_priors(prior_nodes: object) -> list[str]:
    """Canonicalise the node ids the caller says the history must cover.

    The caller's own statement of what "every prior proposal" means for this
    round — usually its tree query's result.  A bare string is **one** node,
    not an iterable of characters: the ambiguity is documented at
    :func:`~signal_agent._anti_convergence._held_digests`, and getting it wrong
    would refuse a one-node history for missing ``node-``, ``o``, ``d``.
    """
    if prior_nodes is None:
        return []
    if isinstance(prior_nodes, str):
        return [_canonical_node_id(prior_nodes)]
    if not isinstance(prior_nodes, Iterable) or isinstance(prior_nodes, Mapping):
        return []
    return [
        _canonical_node_id(node)
        for node in prior_nodes
        if isinstance(node, str) and node.strip()
    ]


def _listed(offenders: list[str]) -> str:
    """Name the offenders, bounded, with the rest counted.

    Sorted and de-duplicated: the sentence is read by a human fixing an
    assembler, and the same node appearing twice because two checks found it is
    one problem to fix.  The count is of *distinct* offences for the same
    reason — an inflated number is a misleading one.
    """
    unique = sorted(dict.fromkeys(offenders))
    shown = unique[:MAX_LISTED_OFFENDERS]
    named = ", ".join(shown)
    if len(unique) > MAX_LISTED_OFFENDERS:
        return f"{named} and {len(unique) - MAX_LISTED_OFFENDERS} more"
    return named


class ProposalHistory:
    """The law: a history is read in full, or it is not a history.

    Stateless — every method takes the history it judges, so the same object
    serves every round of a campaign and there is no per-run state to keep in
    step with the tree.  The same shape
    :class:`~signal_agent.DeadTerritoryGate` and
    :class:`~signal_agent.AntiConvergenceGate` use, and the reason a caller
    composes this into its own authoring step rather than hanging it off an
    application object.

    Two methods, split by what the caller wants back.  :meth:`complete` is the
    query a monitoring caller asks — *was this round's history whole?* — and
    answers with a bool, because a dashboard has no use for a sentence.
    :meth:`admit` is the same judgment carrying the entries and the refusal's
    reason, for a caller whose next line is the authoring call.  They cannot
    disagree: :meth:`complete` is defined in terms of :meth:`admit`, and the
    second observation of the same history costs one pass over the entries.

    :meth:`admit` never raises.  :meth:`require` on the returned verdict is the
    one place :class:`~signal_agent.TruncatedHistoryError` exists.
    """

    __slots__ = ()

    def complete(
        self,
        history: object,
        *,
        prior_nodes: object = (),
    ) -> bool:
        """Whether the handed history is whole.  A thin read of :meth:`admit`."""
        return self.admit(history, prior_nodes=prior_nodes).complete

    def admit(
        self,
        history: object,
        *,
        prior_nodes: object = (),
    ) -> HistoryVerdict:
        """Judge one handed-over history against §14.1's *in full* clause.

        Three checks, in this order, each with its own reason, because a caller
        reading the refusal is fixing one thing and the first hole is the one
        its reader hit:

        1. **Is it a history at all?**  A bare string, a lone mapping, ``None``,
           a number — :data:`NOT_A_HISTORY_CODE`.  The caller's wiring is wrong
           and its assembler is not what needs changing.  An *empty* sequence
           passes: an empty history is a history, and it is whole.
        2. **Is each entry whole?**  A declaration of loss refuses it as
           :data:`SAMPLED_HISTORY_CODE` or :data:`TRUNCATED_HISTORY_CODE`
           depending on which loss it admits to; an entry that named a node and
           produced no text and no declaration refuses it as
           :data:`MISSING_PROPOSAL_CODE`, since the only safe reading of "this
           node's identity and none of its text" is that it was dropped.  An
           entry carrying both text and the ``code_hash`` §9.1 recorded is
           checked by *recomputed identity* —
           :func:`~signal_agent.source_code_hash` over the carried text must
           equal the recorded digest — and refused as
           :data:`TRUNCATED_HISTORY_CODE` when it does not.  That check is the
           law's load-bearing one: it needs no declaration, so a loader that
           silently cut a proposal cannot pass by staying quiet.
        3. **Is every declared prior here?**  Each id in ``prior_nodes`` that no
           entry covered refuses it as :data:`MISSING_PROPOSAL_CODE`, naming
           the holes.  This is the check §14.1's *"not a sample, not recent
           cycles"* is about: the set, not the contents.

        ``prior_nodes`` is the caller's statement of what "every prior
        proposal" means for this round — normally its ``node`` query's result.
        Omitted, check 3 is vacuous and checks 1 and 2 still hold; that is the
        honest default, since a law that invented its own notion of "every
        prior proposal" would be reading the tree behind the caller's back.

        **The refusal's reason is the first offence in the caller's own order**
        — the first hole a reader of the history hits — and its sentence names
        every offence, bounded by :data:`MAX_LISTED_OFFENDERS`, because the run
        has to fix all of them anyway and a second pass would find what the
        first could have said.  An entry's text is never quoted in it: this
        law's subject is which proposals a run failed to read, and the text of
        a proposal belongs in §9.2's artifact directory.

        **The admitted history is returned whole, in the caller's order, and
        never a superset.**  Entries keep the position the caller gave them,
        because a proposal's prompt reads the history in an order and this law
        has no business reordering it; and nothing is added — an admitted
        history is exactly what was handed over, which is what makes
        :attr:`HistoryVerdict.entries` safe to propose from.
        """
        entries = _entries_of(history)
        if entries is None:
            return _verdict(
                HistoryReason.NOT_A_HISTORY,
                f"{NOT_A_HISTORY_CODE}: a history of prior proposals was "
                f"expected, got {type(history).__name__}; §14.1 requires the "
                f"authoring step to read every prior proposal.md, so this "
                f"round's input is a wiring fault rather than a history with "
                f"a hole in it",
            )

        cut: list[str] = []
        sampled: list[str] = []
        dropped: list[str] = []
        admitted: list[PriorProposal] = []
        first_offence: HistoryReason | None = None

        for entry in entries:
            # The name is whatever the entry called itself, and a positional
            # placeholder only when it called itself nothing — including for an
            # entry this law could not read: "we have node n1's identity and
            # none of its proposal" is a fixed-by-fetching-n1 problem, and a
            # sentence that said ``prior-0`` instead would send its reader to
            # the wrong place.
            name = entry.node_id
            offence: HistoryReason | None = None

            if not entry.recognised:
                dropped.append(name)
                offence = HistoryReason.MISSING
            elif entry.loss is HistoryReason.SAMPLED:
                sampled.append(name)
                offence = HistoryReason.SAMPLED
            elif entry.loss is HistoryReason.TRUNCATED:
                cut.append(name)
                offence = HistoryReason.TRUNCATED

            # Declared length before emptiness: an entry that says how long
            # its proposal was and hands over less — including nothing — has
            # admitted the gap arithmetically, and calling that a *drop* would
            # name the wrong repair (fetch the node, rather than finish the
            # read of a node already in hand).
            if offence is None:
                if entry.declared_total is not None and (
                    len(entry.proposal) != entry.declared_total
                ):
                    cut.append(name)
                    offence = HistoryReason.TRUNCATED
                elif not entry.proposal:
                    # Named, no text, nothing declared.  The quiet drop, and
                    # the loophole this law exists to close: there is no
                    # admitted shape for "I have this node's identity and none
                    # of its proposal".
                    dropped.append(name)
                    offence = HistoryReason.MISSING
                elif (
                    entry.code_hash
                    and source_code_hash(entry.proposal) != entry.code_hash
                ):
                    cut.append(name)
                    offence = HistoryReason.TRUNCATED

            if offence is None:
                admitted.append(
                    PriorProposal(
                        node_id=entry.node_id,
                        proposal=entry.proposal,
                        code_hash=entry.code_hash,
                    )
                )
            elif first_offence is None:
                # The first hole a reader of the history hits is the reason
                # reported; the check that found it is an implementation detail
                # of *which proposal* is unreadable, not of *how*.
                first_offence = offence

        covered = {entry.node_id for entry in admitted}
        holes = [
            node for node in _declared_priors(prior_nodes) if node not in covered
        ]

        # A hole is always the *last* offence a reader hits, whatever order the
        # entries came in: it is discovered by the coverage check at the end,
        # not while reading the history.  So a history with both a cut proposal
        # and a hole is reported as cut — the reader's first problem is the one
        # in front of it — and only a history whose *entries* are all readable
        # is reported as missing anything.
        if first_offence is not None:
            return _refusal(first_offence, cut=cut, sampled=sampled, dropped=dropped)

        if holes:
            return _verdict(
                HistoryReason.MISSING,
                f"{MISSING_PROPOSAL_CODE}: declared prior proposals are absent "
                f"— {_listed(holes)}; the history must cover every prior "
                f"proposal the round declared, and a proposal read without "
                f"them is a proposal that cannot avoid repeating them",
                offenders=holes,
            )

        return _verdict(
            HistoryReason.COMPLETE,
            f"{COMPLETE_HISTORY_CODE}: every prior proposal was read in full, "
            f"{len(admitted)} of them, in the order the round assembled them; "
            f"not a sample and not recent cycles",
            entries=admitted,
        )


def _offenders(cut: list[str], sampled: list[str], dropped: list[str]) -> list[str]:
    """Every distinct offending node, in a stable order, for the message.

    De-duplicated because the count is part of the sentence: the same node
    found by two checks is one proposal to go and read, and an inflated number
    is a misleading one.  Sorted rather than kept in encounter order so two
    runs over the same history produce the same sentence — a refusal an
    operator diffs between rounds should not move because a dict did.
    """
    return sorted(set(cut) | set(sampled) | set(dropped))


def _refusal(
    reason: HistoryReason,
    *,
    cut: list[str],
    sampled: list[str],
    dropped: list[str],
) -> HistoryVerdict:
    """Write the refusal for the first offence, naming every offence.

    The reason is the first hole a reader of the history hits — it decides
    *which* code the sentence opens with — while the sentence itself names
    every offending node, because the run has to fix all of them anyway and a
    second pass would find what the first could have said.
    """
    offenders = _offenders(cut, sampled, dropped)
    named = _listed(offenders)
    if reason is HistoryReason.SAMPLED:
        headline = (
            f"{SAMPLED_HISTORY_CODE}: the history is a sample, not the prior "
            f"proposals — {named} were declared taken by a rule (a count, a "
            f"recency window, or a summary of the proposal rather than the "
            f"proposal)"
        )
    elif reason is HistoryReason.TRUNCATED:
        headline = (
            f"{TRUNCATED_HISTORY_CODE}: a prior proposal was read cut short "
            f"— {named}"
        )
    else:
        headline = f"{MISSING_PROPOSAL_CODE}: a declared prior proposal is absent — {named}"
    return _verdict(
        reason,
        f"{headline}; §14.1 requires every prior proposal.md in full — not a "
        f"sample, not recent cycles — and a proposal proposed from a history "
        f"the agent never fully read is a proposal from a history the agent "
        f"never saw",
        offenders=offenders,
    )


def _verdict(
    reason: HistoryReason,
    detail: str,
    *,
    entries: Iterable[PriorProposal] = (),
    offenders: Iterable[str] = (),
) -> HistoryVerdict:
    """Build a verdict.  The one construction site, so no verdict is hand-made."""
    return HistoryVerdict(reason, detail, entries=entries, offenders=offenders)


def proposal_history() -> ProposalHistory:
    """The law, for a caller composing it directly.

    A function rather than a module-level instance so an importer never shares
    state with another importer of the same file under the loader's second
    name — the discipline every other law function in this member follows.  The
    object is stateless, so the cost of a fresh one is a ``__slots__``
    allocation and the benefit is that no caller can be surprised by another's.
    """
    return ProposalHistory()
