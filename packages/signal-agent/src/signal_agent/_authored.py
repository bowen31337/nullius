"""Feature 6 — a model's answer, read as one proposal: source, rationale, text.

*"System parses a model's answer with
``signal_agent._authored.parse_authored(text)``, and it creates a
``ParsedProposal(code, stated_mechanism, proposal)``, where ``proposal`` is
the full raw text."*

**Where this sits: the answer half of the authoring seam.**  The authoring
prompt (feature 5) asks for a *shape* — exactly one ```` ```python ```` fenced
block holding the whole signal source, and one line starting ``Mechanism:``
stating the mechanism — and this module is the half that checks the answer
paid it.  The author (feature 7) calls it between the provider's completion
and the gates: the completion's content goes in, and what comes out is the
code the contract will adopt, the rationale the node's column will record, and
the text the history will persist.  Nothing else in this member reads a
model's answer, which is why the module stays deliberately small: it
is a pure function over one string, with no state, no store and no
configuration, so every claim it makes can be tested by handing it text.

**Why "single" is the load-bearing word of the block rule.**  *Code is the
body of the answer's single ```` ```python ```` fenced block*, and the three
refusals — zero blocks, several blocks, a blank body — are one refusal about
one thing: the answer did not carry exactly one block of source.  Two blocks
are not a formatting nuisance but an *ambiguity about which source the model
proposes*, and a parser that silently picked (the first, the longest, the one
that compiles) would spend the round on a guess no downstream gate can catch,
because both blocks can be conforming signals.  §14.1 prices that guess —
*"a bad proposal is caught by the evaluator at a cost of one trial charge"* —
so the count is named and refused rather than spent; the retry (feature 7)
is one message away and quotes this refusal's own code word back to the model.
Zero blocks and a blank body are the same refusal at the other end: an answer
with no source in it proposes no source, and the parse is where the agent
contract's own requirement — discovery reads ``.code`` as *non-blank* text —
is established for the LLM path, rather than letting a blank reach
``contract.adopt`` and be refused there as a *conformance* defect it is not.
The source was never there to be non-conforming; the *answer* is what is
wrong, and the refusal says so.

**Why ``proposal`` is the raw text, whole.**  §14.1's reading rule — every
prior ``proposal.md`` *in full*, not a sample, not recent cycles — is a
requirement about what the next round reads, and what the next round reads is
what this parse handed the history (feature 207 persists this field verbatim
as the node's proposal document).  A parser that returned only the block, or a
trimmed rendering of the answer, would make replay a claim about text no model
sent: the prose around the block is the model's own words about its own
proposal, and discarding it at the door is the truncation feature 206 refuses,
committed by the one component that had the whole answer in hand.  So
:func:`parse_authored` stores the very object it was given — no copy, no
strip, no normalisation — and the identity claim is pinned in this member's
suite as a claim about ``is``, not merely about equality.

**Why a missing mechanism line is ``None`` and a blank one is ``""``.**  One
refusal per contract.  The *format's* code half is refused here; the
*statement* half belongs to feature 211's law, which judges a rationale at
persist time and refuses one whose canonical form is empty.  A missing line is
not a parse failure — discovery's agent contract carries ``.stated_mechanism``
as optional, and 0117's nullable column exists precisely to record an agent
that stated no mechanism *honestly* rather than fabricate a rationale no one
wrote — so the parse reports the absence (``None``) and lets the statement
law, not the parser, be the one that says what may be recorded.  A line that
exists but says nothing after its colon is ``""`` for the same reason: the
line was stated, the text after it strips to nothing, and whether that may be
persisted is 211's question.  The extraction itself is the sentence's own
rule, taken literally: the *first* line starting ``Mechanism:``, the text
after the prefix, stripped of whitespace and of nothing else — case-folding
and punctuation are ``canonical_mechanism``'s comparisons to make, not the
parser's, and a parser that "fixed" the spacing or the spelling of a stated
rationale would be editing the agent's words on their way into history.

**The error, and where it sits in the vocabulary.**
:class:`AuthoredOutputError` is defined in this module — the feature's own
sentence says so, and it is the workspace convention (:mod:`signal_agent.
errors`'s whole layout): a refusal is a typed error that opens with a
greppable code word and lives in the module that raises it.  It subclasses
:data:`~signal_agent.SignalAgentError` so a caller's single ``except`` still
catches every failure of the authoring path, and it is a **sibling** of
:class:`~signal_agent.AgentSourceError` rather than a subclass.  The subject
here is the *answer's shape*, judged before any source exists to be
non-conforming (zero blocks means there is no source at all); the subject
there is a source that failed the declared contract.  The repairs are the
same — re-prompt, which is why feature 7's retry loop names both classes at
its ``except`` — but the greps differ, and the member's rule is that a class
buys a query: *"how often did the model answer in the wrong shape?"* is a
prompt-and-model question this class answers, and *"how often was the source
non-conforming?"* is a contract-communication question feature 205's own
refusal answers.  Folding the first into the second would make the operator's
count of malformed answers depend on reading message text.

**What this module deliberately does not do.**  It imports nothing outside
the standard library and this package — pinned by test, because the
constraint is the feature's and not a mood: the parser is model-agnostic and
provider-agnostic, readable and testable as a pure function over fixture
text with no provider, no discovery and no nulloracle anywhere near it
(design principle 2 — the agent path sees metrics, never null status, and a
parser that could not see them by construction is the strongest form of that
guarantee).  It is line-based Markdown, not a Markdown implementation: fence
matching keeps to CommonMark's own rules where they bite (a closing fence
carries no info string, an unclosed fence runs to the end of the text), with
one deliberate lenience — leading whitespace on a fence line, because answers
arrive indented — and it is not Python-aware, because judging the
*source* inside the block is the contract's job (feature 205) and a parser
that peeked at the syntax would silently second-guess it.  And it transforms
nothing: the code is the body between the fences byte for byte, so the
``code_hash`` §9.1 records is a hash of what the model wrote, not of what a
parser chose to keep.
"""

from __future__ import annotations

from typing import Final

from .errors import SignalAgentError

__all__ = [
    "AUTHORED_OUTPUT_CODE",
    "AuthoredOutputError",
    "ParsedProposal",
    "parse_authored",
]

#: The code word every refusal this module raises opens with — the token the
#: spec's own sentence names, spelled once so the raise sites, the retry
#: message that quotes them (feature 7) and an operator's grep all read the
#: same string.  It is its own word rather than a spelling of feature 205's
#: ``conforms`` vocabulary for the reason the class docstring states: the
#: subject is the answer's shape, not the source's conformance.
AUTHORED_OUTPUT_CODE: Final[str] = "authored_output"

#: Markdown's fence marker, spelled once.  A fence line is a line whose
#: stripped form starts with this; the text after it (stripped) is the fence's
#: *info string*, and the string that makes a fence the answer's python fence
#: is ``python`` below.
_FENCE_MARKER: Final[str] = "```"

#: The info string that makes a fenced block count as the answer's source —
#: exactly this word, case-folded, and not a near miss.  The authoring format
#: names ```` ```python ```` (feature 5), and a parser that guessed at
#: spellings the format never asked for (``py``, ``python3``) would quietly
#: admit blocks the prompt did not request while refusing to say which
#: spelling it accepted.
_PYTHON_INFO: Final[str] = "python"

#: The prefix that marks a line as the agent's stated mechanism — feature 5's
#: own spelling, exact: at the start of the line, capital ``M``, one colon.
#: A parser that accepted ``mechanism:`` or an indented variant would be
#: recognising lines the format never asked for, on the model's behalf.
_MECHANISM_PREFIX: Final[str] = "Mechanism:"

#: The parts equality compares — spelled once so ``__eq__``, ``__hash__`` and
#: ``__slots__`` cannot disagree about what a proposal *is*.  Duck-read by
#: name rather than by ``isinstance``, for the loader-double-import reason
#: the class docstring states.
_PROPOSAL_FIELDS: Final[tuple[str, ...]] = ("code", "stated_mechanism", "proposal")


class AuthoredOutputError(SignalAgentError):
    """A model's answer is not the one-block shape the authoring format asked for.

    Raised by :func:`parse_authored` — and only there — for the three shapes
    the feature's own sentence refuses (no ```` ```python ```` block, several
    of them, a block whose body is blank) and for the one shape beneath all
    of them (a value that is not text at all, so there is no answer to read).
    The message opens with :data:`AUTHORED_OUTPUT_CODE` and then names *which*
    shape it holds and why the parse refused to repair it, because the caller
    that catches it (feature 7's retry loop) quotes the refusal back to the
    model as the defect to fix — a message that said only "invalid output"
    would send the model a complaint it could not act on.

    **It subclasses :class:`~signal_agent.SignalAgentError` and is a sibling
    of :class:`~signal_agent.AgentSourceError`, and the asymmetry is the
    module docstring's own argument.**  The refusals under that base are
    facts about *source the agent wrote* — a signal that does not compile,
    does not declare the entrypoint, opens outside the legal set — and each
    is a judgment feature 205's contract or its gates make about code that
    exists.  This refusal fires *before* any of that: zero blocks means no
    code exists to judge, and a blank body never reaches the contract.  The
    repairs are the same (re-prompt — feature 7 retries both classes by
    name), but the queries are not, and a caller or operator counting
    malformed answers must not have to read message text to separate them
    from non-conforming sources.
    """


class ParsedProposal:
    """One model's answer, split into the three things the pipeline reads.

    The value :func:`parse_authored` returns, and the shape of the feature's
    own sentence: ``code`` (the body of the single ```` ```python ```` block,
    verbatim), ``stated_mechanism`` (the text after the first line starting
    ``Mechanism:``, stripped, or ``None``) and ``proposal`` (the full raw
    answer).  The three are the three destinations downstream — the contract
    adopts ``code``, the node's column records ``stated_mechanism``, the
    history persists ``proposal`` — so the value is the seam between one
    answer and the three stores that will hold parts of it, and the fields
    are held separately *because* they are read separately: nothing
    downstream re-parses the proposal to recover a field this object already
    carries, which is what keeps the answer's reading in one place.

    **The constructor refuses nothing**, for :class:`~signal_agent.
    PriorProposal`'s own reason: an unusable answer is :func:`parse_authored`'s
    judgment, and a constructor that raised would make the parse's own
    refusals unreachable for the common case where the caller built the value
    first and asked afterwards.

    **Equality is over the parts, never by ``isinstance``** — the module
    loader imports every member twice, once by file path under a synthetic
    name and once as the importable member, so an ``isinstance`` check
    against this class would be false for a value built from the other import
    of this same file.  The parts are the whole truth about the value, and
    equality over them survives both imports.
    """

    __slots__ = _PROPOSAL_FIELDS

    def __init__(
        self, code: str, stated_mechanism: str | None, proposal: str
    ) -> None:
        self.code = code
        self.stated_mechanism = stated_mechanism
        self.proposal = proposal

    def __eq__(self, other: object) -> bool:
        """Equal when all three parts are equal — never by ``isinstance``."""
        if not all(hasattr(other, name) for name in _PROPOSAL_FIELDS):
            return NotImplemented
        return (
            self.code == other.code
            and self.stated_mechanism == other.stated_mechanism
            and self.proposal == other.proposal
        )

    def __hash__(self) -> int:
        return hash((self.code, self.stated_mechanism, self.proposal))

    def __repr__(self) -> str:
        """The value's shape — lengths, never the text it holds.

        The proposal is a model's whole answer and the mechanism is its
        rationale; a repr that printed either would put prose into log lines
        and terminals, and quoting a proposal anywhere but its own artifact
        is the truncation feature 206 refuses, in miniature.  The lengths say
        everything a log needs — that the parse answered, and with how much —
        and the fields are one attribute away for the caller that needs them.
        """
        mechanism = (
            "None" if self.stated_mechanism is None
            else f"{len(self.stated_mechanism)} chars"
        )
        return (
            f"ParsedProposal(code_chars={len(self.code)}, "
            f"stated_mechanism={mechanism}, "
            f"proposal_chars={len(self.proposal)})"
        )


def parse_authored(text: str) -> ParsedProposal:
    """Read one model's answer as one proposal — or refuse it by name.

    The whole of the feature: split the answer into the code the sandbox will
    execute, the rationale the node will record and the text the history will
    persist, refusing — never repairing — an answer that is not the one-block
    shape the authoring format asked for.  The refusals, in the order they
    are checked:

    * **not text** — there is no answer to read at all, and the caller that
      holds this value handed the parse something other than a completion's
      content;
    * **zero blocks** — the answer proposes no source, and nothing is
      recovered from the prose around the gap: a parser that adopted text it
      was not handed would be authoring, not parsing;
    * **several blocks** — which block is the proposal would be this
      function's guess, and both can be conforming signals, so no downstream
      gate catches the wrong pick; the count is refused and named instead of
      spent;
    * **a blank body** — the fence is there but carries nothing adoptable,
      and the refusal names the answer's shape rather than letting a blank
      reach the conformance gates wearing a defect it is not.

    Each message opens with :data:`AUTHORED_OUTPUT_CODE`, because feature 7's
    retry loop quotes the refusal's code word back to the model and an
    operator greps for the same token in a campaign log.

    ``stated_mechanism`` is never a reason to refuse — see the module
    docstring for the one-refusal-per-contract argument — and neither is the
    prose around the block: the answer is the proposal, whole.
    """
    if not isinstance(text, str):
        raise AuthoredOutputError(
            f"{AUTHORED_OUTPUT_CODE}: an authored answer must be text, got "
            f"{type(text).__name__}; the answer is the one artefact this "
            f"module reads, and neither half of it — the fenced block that "
            f"becomes source, the {_MECHANISM_PREFIX} line that becomes the "
            f"stated rationale — can be scanned out of a value that is not "
            f"text. The caller owes this parse the completion's content "
            f"exactly as the provider returned it (feature 6)."
        )
    bodies = _python_block_bodies(text)
    if not bodies:
        raise AuthoredOutputError(
            f"{AUTHORED_OUTPUT_CODE}: the answer carries no "
            f"{_FENCE_MARKER}{_PYTHON_INFO} fenced block. The authoring "
            f"format asks for exactly one holding the whole signal source "
            f"(feature 5), so an answer without one proposes no source at "
            f"all, and nothing is recovered from the prose around the gap — "
            f"a parser that adopted text it was not handed would be "
            f"authoring, not parsing (feature 6)."
        )
    if len(bodies) > 1:
        raise AuthoredOutputError(
            f"{AUTHORED_OUTPUT_CODE}: the answer carries {len(bodies)} "
            f"{_FENCE_MARKER}{_PYTHON_INFO} fenced blocks where the "
            f"authoring format asks for exactly one. Which block is the "
            f"proposal would be this parse's guess, and both can be "
            f"conforming signals no downstream gate could catch — the trial "
            f"charge §14.1 prices would be spent on the guess — so the "
            f"count is named and refused instead (feature 6)."
        )
    code = bodies[0]
    if not code.strip():
        raise AuthoredOutputError(
            f"{AUTHORED_OUTPUT_CODE}: the answer's "
            f"{_FENCE_MARKER}{_PYTHON_INFO} fenced block has a blank body. "
            f"A fence with nothing in it carries no source for the contract "
            f"to adopt and no code for a node to open on — the agent's own "
            f"contract requires non-blank code — and the refusal names the "
            f"answer's shape rather than letting a blank reach the "
            f"conformance gates as a source defect it is not (feature 6)."
        )
    return ParsedProposal(
        code=code,
        stated_mechanism=_first_stated_mechanism(text),
        proposal=text,
    )


def _fence_info(line: str) -> str | None:
    """A line's fence info string, or ``None`` when the line is not a fence.

    A fence line is a line whose stripped form starts with the marker —
    leading whitespace is tolerated, because models indent fences inside
    lists and answers arrive indented.  The info string is the marker's
    remainder, stripped: ```` ```python ```` answers ``python``, ```` ``` ````
    answers ``""`` (the shape a *closing* fence wears), and a plain prose
    line answers ``None``.

    The three answers are all the scanner needs, which is why there is no
    fence *object*: a fence is fully described by what follows its marker,
    and every rule the block scanner applies is a comparison on this string.
    """
    stripped = line.strip()
    if not stripped.startswith(_FENCE_MARKER):
        return None
    return stripped[len(_FENCE_MARKER):].strip()


def _python_block_bodies(text: str) -> list[str]:
    """Every python-fenced body in an answer, in order, byte for byte.

    One pass over the answer's lines, keeping to CommonMark's fence rules
    rather than inventing parser-specific ones, because the fences a model
    writes are Markdown and the least surprising reading of them is the one
    every Markdown renderer already agrees on:

    * a fence **opens** at a fence line with any info string, and the block
      is a *python* block when that info string is ``python`` (case-folded —
      models write ```` ```Python ````), and nothing else: near-miss info
      strings are not python blocks, so they count as neither source nor
      refusal on their own;
    * a fence **closes** at the next line whose info string is empty — a
      closing fence carries no info string, so a ```` ```json ```` line
      inside an open block is *content*, not a boundary;
    * a fence left **unclosed** runs to the end of the text, and its body is
      the remainder — the block still counts as one, so an answer truncated
      mid-fence is refused (or adopted) as the one block it visibly meant,
      not as zero;
    * the body is the lines between the fences, joined unchanged — nothing
      is stripped from the ends, because the ``code_hash`` downstream is a
      hash of what the model wrote and the parse refuses to be the answer's
      first transformer.

    The scanner is line-based and Markdown-shaped, not Python-aware: a bare
    fence line inside the source's own docstring closes the block, exactly as
    every Markdown renderer would read it.  Judging what is *inside* the
    block is the contract's job (feature 205); this function's whole subject
    is where the block ends.
    """
    lines = text.split("\n")
    bodies: list[str] = []
    index = 0
    while index < len(lines):
        info = _fence_info(lines[index])
        if info is None:
            index += 1
            continue
        start = index + 1
        index = start
        while index < len(lines) and _fence_info(lines[index]) != "":
            index += 1
        if info.casefold() == _PYTHON_INFO:
            bodies.append("\n".join(lines[start:index]))
        # Step past the closing fence (or harmlessly past the end when the
        # fence never closed), so a fence line never does double duty as the
        # opener of the block it just closed.
        index += 1
    return bodies


def _first_stated_mechanism(text: str) -> str | None:
    """The text after the answer's first ``Mechanism:`` line, stripped.

    The feature's own rule, taken literally: the *first* line that starts
    with the prefix, wherever in the answer it stands — the scanner reads the
    raw lines in order and does not track fences, because the parse takes the
    model at its word about where it stated its rationale and a
    structure-aware scan that skipped a mechanism stated inside the code
    fence would silently turn a stated mechanism into an unstated one.  A
    second line starting the same way is the model's own redundancy and is
    ignored, not refused: the format asked for one line and the first one is
    the statement.

    ``None`` means no line started with the prefix at all — the honest
    *unstated* state 0117's nullable column records — and ``""`` means a line
    started with it and said nothing, which is feature 211's refusal to make
    at persist, not the parser's.  Stripping is whitespace-only; comparing
    and canonicalising spellings is ``canonical_mechanism``'s subject.
    """
    for line in text.split("\n"):
        if line.startswith(_MECHANISM_PREFIX):
            return line[len(_MECHANISM_PREFIX):].strip()
    return None
