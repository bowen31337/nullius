"""Feature 209's law: the diagnosis that decides whether a branch is worth retrying.

app_spec.xml, "Hypothesis Authoring Agent", feature 209: *Agent distinguishes
a flawed core mechanism from a sound idea undermined by a located bug, which
returns a retry decision for only the second case.*  The requirement it states
is quoted verbatim from the PRD, which keeps it among the three things the
discovery agent's defining prompt takes from the paper's Listing 1 *"nearly
verbatim"* (docs/alpha-engine-prd.md §C3)::

    The distinction between a flawed core mechanism and a good idea let down
    by a bug — the former is not worth retrying, the latter is, but only with
    the bug actually located in code rather than guessed from the write-up.

docs/nullius-tech-architecture.md §14.1 supplies the second half, and it is
what turns that sentence from a taste into a computation::

    Depth is narrow (given a mechanism and a diagnostic, make a targeted
    change) and is verified downstream.
    ...
    A bad proposal is caught by the evaluator at a cost of one trial charge.

*Given a mechanism and a diagnostic, make a targeted change.*  A targeted
change needs a **target**, and a target is a place in code.  A branch whose
failure has no such place is a branch where the targeted change has nowhere to
point — and what is left to change is then the mechanism itself.  That is the
whole of the distinction, and this module is it, in three clauses.

**"distinguishes a flawed core mechanism from a sound idea undermined by a
located bug."**  The distinguishing evidence is a *resolved code location*:
:func:`locate_defect` reads the position a caller claims against the proposal's
own parse tree and answers either a :class:`LocatedDefect` — a line, a column,
the enclosing symbol *derived from the tree*, and the proposal's own line of
text verbatim — or ``None``.  Nothing else in this member can answer it.
Feature 205's :meth:`SignalContract.adopt` says whether the sandbox can
*invoke* the source, and a 400th variant of one indicator is perfectly
invokable.  Feature 210's gate says whether the campaign already holds the
structure.  Feature 211's law persists what the agent *claims* and guards it
from the scoring path.  None of them says where, in the code, a failure is —
and "where" is the entire content of §14.1's *targeted change*.

**"which returns a retry decision for only the second case."**  ``retry`` is
the one field a caller must check, and it is *computed* from the reason rather
than set by a constant — the same "computed, never assumed" stance
:class:`signal_agent.SourceAdoption`, :class:`signal_agent.ThemeAdmission`,
:class:`signal_agent.DeadTerritoryVerdict` and
:class:`signal_agent.AntiConvergenceVerdict` take for their own answers.  It is
``True`` for exactly one of the three reasons, and the other two are refusals
with different repairs.  It is returned, never raised: a driver that has to
decide *whether* to spend a trial charge needs the answer as a value, and
:meth:`MechanismDiagnosis.require` is the only place this law's exception
appears — on the last line before a retry prompt, where a caller that has not
established a location must not be allowed to write one.

**"but only with the bug actually located in code rather than guessed from the
write-up."**  This is the clause the shape of the API is built around, and it
is a *provable* property rather than a promise: **the write-up cannot buy a
retry.**  A caller hands in ``complaints`` — the sentences another member's
validator or the sandbox itself reported the failure with, exactly the
``problems`` feature 205's :class:`~signal_agent.SourceAdoption` carries and
the ``detail``/``fail_class`` an evaluation returns — and those sentences can
move the verdict only *between the two refusals*.  ``retry`` is ``True`` if and
only if a defect resolves in the proposal's own source; no amount of reported
prose changes that, and a complaint that names no position in the code is
precisely §C3's *guess from the write-up*, answered the same way a branch whose
code is exactly what the agent meant to write is answered.  Returning ``True``
on a well-argued complaint would be this law's vacuous green — the shape every
gate in this member refuses — and it would be worse here than elsewhere,
because §14.1 prices the mistake: a bad proposal costs one trial charge, and a
retry of a flawed mechanism spends one to learn nothing.

**What makes a location *located*.**  Two things, and both are checked rather
than trusted:

* the position must be a line **the proposal's own parse tree occupies** —
  :func:`_code_lines` is the set of lines on which a node begins, so a line
  that is blank, a comment, or past the end of the source is not a location
  where code is, and a caller that guessed one is refused;
* the enclosing **symbol is derived**, never accepted: :func:`_enclosing_symbol`
  walks the tree for the innermost definition spanning the position, so a
  caller cannot claim the defect is in ``signal`` when the line it named is
  inside a helper.  The verdict carries the proposal's own text at that line as
  well (``LocatedDefect.source_line``), so a retry prompt built from a verdict
  quotes the agent's code byte-for-byte rather than a summary of it.

A line number is required to be **an ``int`` and nothing else**: ``"line 40"``,
``7.0``, ``"7"`` and ``True`` are all refused, because a position parsed out of
prose is exactly the guess this feature is about.  ``bool`` is excluded on
purpose — it is an ``int`` subclass, the affinity trap this workspace's SQLite
layer guards and feature 210 guards for its own reason, guarded here because
``True`` would otherwise resolve as line 1.

**The source that does not parse is the one location the parser hands over.**
:func:`first_defect` asks :func:`ast.parse` — through the same
``<signal-source>`` filename :func:`contract.signal._require_signal_module`
compiles under and the sandbox child compiles under, so the anchor a retry
prompt quotes is the one every other reader of a proposal uses — and returns
the ``SyntaxError``'s own position when there is one.  This is not feature 205's
signature check restated: it is about *parsing*, and a source that does not
parse has a defect at a line and a column whether or not it would also have
declared the entrypoint.  A source that **does** parse yields ``None``, and
that is the feature's most important default: a well-formed signal that failed
has no located bug, so what the failure implicates is the mechanism.

**Why the member's third reason is not a fourth error class.**  ``errors.py``
recorded, before this law existed, that the vocabulary deliberately had no
*retry* class: "a flawed core mechanism" and "a sound idea undermined by a
located bug" are two answers feature 209 attributes to a diagnosis, and a
retry-decision error with no raiser would be a shape the caller had to reason
about for nothing.  The reasoning holds and this module is what satisfies it.
The retry decision is a returned value; the vocabulary gains exactly one class,
:class:`~signal_agent.errors.FlawedMechanismError`, and it is the *refusal* —
the answer that says **do not** retry.  It is a sibling of
:class:`~signal_agent.errors.AgentSourceError` rather than a subclass, and that
is the member's sharpest inheritance decision: the three refusals under
``AgentSourceError`` (illegal theme, dead territory, convergence) all assert
the same repair — re-prompt the agent — so a caller written before any of them
existed must not lose them through a clause that stopped matching.  This
refusal asserts the *opposite* repair.  A caller's ``except AgentSourceError:``
handler exists to re-prompt, and letting it catch "the mechanism is flawed"
would make it spend trial budget on the branch the diagnosis just said to
close — which is the one thing feature 209 exists to prevent.  The subject is
also, like feature 211's rationale, the *mechanism* rather than the source; the
source is exactly what the sentence holds blameless.

**Why this is a sixth component and not a parameter of an earlier law.**  The
member's components each answer one feature's question, and the registry is
keyed by name — a sixth builder taking ``signal-agent`` would *replace* feature
205's law rather than sit beside it, the registry-replacement hazard
:data:`signal_agent.THEMES_COMPONENT_NAME` names.
``signal-agent-diagnosis`` sorts between ``signal-agent-dead-territory`` and
``signal-agent-stated-mechanism`` in the name-sorted ``app.order``, so all six
stay contiguous in the category they belong to.

**It compiles no artifact and reads no environment.**  Features 212, 213 and
210 ship committed documents because their subjects are configured; feature
209's subject is a proposal and a failure, both handed in.  So this is the
member's second builder of feature 205's shape — a stateless law whose
construction computes nothing and can fail at nothing — and like
:class:`signal_agent.SignalContract` it carries **no** proposal, campaign,
node, store or prompt: a component that held one would let two branches'
verdicts be read through each other, and the diagnosis is about one proposal at
one moment.

Stdlib only, and import-cheap — :mod:`ast`, :mod:`enum`, :mod:`typing` and the
member's own errors — so the factory's scan, which imports this package to fire
its ``@register``, pays nothing for it.
"""

from __future__ import annotations

import ast
import enum
from collections.abc import Iterable
from typing import Final

from .errors import FlawedMechanismError

__all__ = [
    "DIAGNOSIS_COMPONENT_NAME",
    "FLAWED_MECHANISM_CODE",
    "LOCATED_BUG_CODE",
    "MAX_LISTED_COMPLAINTS",
    "MODULE_SYMBOL",
    "NOT_A_DIAGNOSIS_CODE",
    "SIGNAL_SOURCE_FILENAME",
    "DiagnosisReason",
    "DiagnosisVerdict",
    "LocatedDefect",
    "MechanismDiagnosis",
    "first_defect",
    "locate_defect",
    "mechanism_diagnosis",
]

#: The component name this law registers under — beside feature 205's
#: ``signal-agent``, feature 210's ``signal-agent-anti-convergence``, feature
#: 213's ``signal-agent-dead-territory``, feature 211's
#: ``signal-agent-stated-mechanism`` and feature 212's ``signal-agent-themes``.
#: The registry is keyed by name and a later registration of the same name
#: *replaces* the earlier one, so the category's later features each take their
#: own seat on the member rather than overwriting an earlier law.  Prefixed for
#: that reason — an unprefixed ``signal-agent`` a sixth time would replace
#: feature 205's law — and ``signal-agent-diagnosis`` sorts between
#: ``signal-agent-dead-territory`` and ``signal-agent-stated-mechanism`` in the
#: name-sorted ``app.order``, keeping the member's six components contiguous in
#: the category they belong to.
DIAGNOSIS_COMPONENT_NAME: Final[str] = "signal-agent-diagnosis"

#: The filename every reader of a proposal compiles it under.  Spelled here as
#: well as in :func:`contract.signal._require_signal_module` and in the
#: evaluator sandbox's embedded child runner, and spelled identically on
#: purpose: the whole claim of a *located* bug is that the position names a
#: place in the source the sandbox actually executes, so a retry prompt that
#: quoted a different anchor than the traceback did would be quoting a
#: location nobody else can find.  This member's suite pins the agreement
#: rather than asserting it — the contract member's own refusal for a source
#: that does not compile carries this filename, so the two spellings are held
#: to one string by a test.
SIGNAL_SOURCE_FILENAME: Final[str] = "<signal-source>"

#: The symbol a defect carries when it sits in no definition — a module-level
#: failure, or a source that does not parse at all.  Angle-bracketed to match
#: Python's own convention and to make it unmistakable in a log line for
#: something that is not a name the agent wrote.
MODULE_SYMBOL: Final[str] = "<module>"

#: The token a retrying verdict's detail opens with — *a defect is located in
#: the proposal's own source*.  Its mirror is the refusal, which opens with
#: :data:`FLAWED_MECHANISM_CODE` instead; an admission is not a code an
#: operator greps a campaign for, the same asymmetry
#: :data:`signal_agent.NOVEL_CODE` has against
#: :attr:`signal_agent.AntiConvergenceReason.PARAMETER_TWEAK`.
#: ``located_bug`` rather than ``retry`` because §C3's own word for the
#: admitted case is *"a good idea let down by a bug ... only with the bug
#: actually located in code"* — the verdict is admitted on a property of the
#: proposal, and ``retry`` is the consequence rather than the finding.
LOCATED_BUG_CODE: Final[str] = "located_bug"

#: The greppable code feature 209's own refusal carries — its subject written
#: as a token, so an operator grepping a campaign log for the branches the
#: diagnosis told the driver not to re-open finds them by the feature's own
#: words.  This is the code one verdict carries, not the code every refusal
#: carries: the not-a-diagnosis case below opens with its own, for the reason
#: :attr:`DiagnosisReason.NOT_A_DIAGNOSIS` states.
FLAWED_MECHANISM_CODE: Final[str] = "flawed_mechanism"

#: The code the not-a-diagnosis refusal opens with — its own, not
#: :data:`FLAWED_MECHANISM_CODE`, the discipline feature 210's
#: ``NOT_A_PROPOSAL_CODE`` and feature 213's ``NOT_A_ROOT_CODE`` already
#: follow: a refusal that opened with the feature's headline while its own text
#: says there was no failure to diagnose would be reporting a research finding
#: about a branch that never failed.
NOT_A_DIAGNOSIS_CODE: Final[str] = "not_a_diagnosis"

#: How many complaint sentences a refusal's detail quotes before it summarises
#: the rest.  A bound rather than the whole list because a contract validator
#: returns one problem per failing property and a pathological source can
#: return many, and a paragraph that quoted all of them would be one nobody
#: reads.  Named as data so the read side and its test share one number.
MAX_LISTED_COMPLAINTS: Final[int] = 4


def _parse(source: str) -> tuple[ast.Module | None, SyntaxError | None]:
    """Parse ``source`` under the shared filename.  Exactly one half is ``None``.

    The have-your-cake shape the two callers below need: :func:`locate_defect`
    wants the *tree* and must be able to say "there is none", while
    :func:`first_defect` wants the *failure* and must be able to say "there is
    none".  Raising here and catching at one of them would make the other
    re-parse, and two parses of one proposal are two answers to one question.
    """
    try:
        return ast.parse(source, filename=SIGNAL_SOURCE_FILENAME), None
    except SyntaxError as exc:
        return None, exc


def _code_lines(tree: ast.Module) -> frozenset[int]:
    """The lines of a parsed source on which a node *begins*.

    The set :func:`locate_defect` resolves a claimed position against.  A node's
    *start* rather than its span, deliberately: a function spans its blank
    lines and its comments, and a claimed defect on line 3 of a body that has
    nothing on line 3 is a position where no code is.  Anchoring on starts makes
    "the parse tree occupies this line" mean *this line is where something
    begins*, which is what a traceback line and a syntax error's ``lineno``
    both are.

    Everything with a ``lineno`` is included, not only statements: an
    ``ast.arg`` and an ``ast.alias`` are code too, and a defect located at a
    parameter or an import name is exactly the sort of place a signature or an
    allowlist failure sits.
    """
    return frozenset(
        line
        for node in ast.walk(tree)
        if isinstance(line := getattr(node, "lineno", None), int)
    )


def _unparsed_code_lines(source: str) -> frozenset[int]:
    """The lines of a source that does *not* parse which carry text.

    The stand-in for :func:`_code_lines` in the one case where there is no tree
    to ask.  A line that is blank or entirely a comment cannot be what the
    parser broke on, so the set is every other line — permissive on purpose,
    because a source the parser could not read has no structure to hold a
    position to, and refusing a position inside it would refuse the very case
    :func:`first_defect` exists to answer.
    """
    return frozenset(
        index
        for index, text in enumerate(source.splitlines(), start=1)
        if text.strip() and not text.lstrip().startswith("#")
    )


def _enclosing_symbol(tree: ast.Module | None, line: int) -> str:
    """The innermost definition spanning ``line``, or :data:`MODULE_SYMBOL`.

    Derived from the tree rather than accepted from the caller, and that is the
    point: a caller naming a line is naming a *place*, and what is at that place
    is a fact about the proposal.  A diagnosis that let a caller assert the
    symbol as well would be one a caller could point at ``signal`` while the
    line it named sits inside a helper — a located bug that is located in the
    wrong function, which is the guess this feature refuses arriving one level
    down.
    """
    if tree is None:
        return MODULE_SYMBOL
    found: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None = None
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        if node.lineno <= line <= end and (found is None or node.lineno >= found.lineno):
            found = node
    return found.name if found is not None else MODULE_SYMBOL


class LocatedDefect:
    """A defect at a place in a proposal's own source.

    What :func:`locate_defect` and :func:`first_defect` hand back and what
    :meth:`DiagnosisVerdict.require` returns, so a caller about to write a retry
    prompt holds *the line of code* rather than a sentence about it.  That is
    §C3's *"only with the bug actually located in code"* as a type: the retry
    prompt is built from :attr:`source_line`, which is the proposal verbatim.

    Five fields, and each is a different statement about one position:

    * :attr:`line` and :attr:`column` — where, 1-based, in the proposal;
    * :attr:`symbol` — the innermost definition the position sits in, **derived
      from the parse tree** by :func:`_enclosing_symbol` and never accepted from
      a caller;
    * :attr:`source_line` — the proposal's own text at :attr:`line`, verbatim,
      carried rather than left to the caller because "the retry prompt quotes
      the code" and "the caller re-reads the code" are exactly the pair that can
      drift;
    * :attr:`problem` — the sentence that reported the defect, when one came
      with it: the parser's own message for :func:`first_defect`, and whatever
      the caller supplied for :func:`locate_defect`.  Empty is a legitimate
      value and is not a missing field: a traceback line names a position and no
      sentence, and a caller that has the position has the diagnosis.

    **Its constructor refuses nothing.**  A caller holding a defect is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`signal_agent.SourceAdoption` and
    :class:`signal_agent.AntiConvergenceVerdict` state for their own
    constructors.  The refusals live at :func:`locate_defect`.
    """

    __slots__ = ("column", "line", "problem", "source_line", "symbol")

    def __init__(
        self,
        *,
        line: int,
        column: int,
        symbol: str,
        source_line: str,
        problem: str = "",
    ) -> None:
        self.line = line
        self.column = column
        self.symbol = symbol
        self.source_line = source_line
        self.problem = problem

    @property
    def filename(self) -> str:
        """The filename the position is in — :data:`SIGNAL_SOURCE_FILENAME`.

        The same anchor the contract member compiles a proposal under and the
        sandbox child executes it under, so a retry prompt that quotes
        ``defect.render()`` quotes a location a human can open in the tree's own
        artifact and a machine can match against a traceback.
        """
        return SIGNAL_SOURCE_FILENAME

    def render(self) -> str:
        """One line: the anchor, the symbol, and the reported sentence.

        The read side a retry prompt and a campaign log both want, spelled once
        so the two cannot disagree.  ``<signal-source>:12:5 (in signal): ...``
        is the shape, and it opens with the filename for the reason
        :data:`SIGNAL_SOURCE_FILENAME` states.
        """
        where = (
            f"{SIGNAL_SOURCE_FILENAME}:{self.line}:{self.column} "
            f"(in {self.symbol})"
        )
        if self.problem:
            return f"{where}: {self.problem}"
        return f"{where}: {self.source_line.strip()}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"LocatedDefect({SIGNAL_SOURCE_FILENAME}:{self.line}:{self.column}, "
            f"symbol={self.symbol!r})"
        )


def locate_defect(
    source: object, line: object, column: object = 1, problem: str = ""
) -> LocatedDefect | None:
    """Resolve a claimed position against a proposal, or answer ``None``.

    The half of this law that does the distinguishing.  A caller claims *the bug
    is at line N*; this reads the claim against the proposal's own parse tree
    and answers a :class:`LocatedDefect` when the claim is a place in the code
    and ``None`` when it is not.  A claim that does not resolve is not an
    error — it is the absence of the evidence, which
    :meth:`MechanismDiagnosis.diagnose` turns into a refusal.

    **What does not resolve**, and each for its own reason:

    * a position that is not an ``int`` — ``"line 40"``, ``"40"``, ``40.0``;
      a position parsed out of prose is the guess §C3 names, and accepting one
      would make the write-up decide after all;
    * ``True`` and ``False``, which are ``int`` subclasses and would otherwise
      resolve as lines 1 and 0 — the affinity trap this workspace's SQLite
      layer guards, guarded here because a boolean is not a position;
    * a line the parse tree does not occupy — past the end of the source, blank,
      or a comment.  A position where no code begins is not a place a defect can
      be *located in code*;
    * anything that is not text, or is blank text, as the proposal.

    ``column`` is carried for the prompt and is **not** the anchor: it is
    normalised to ``1`` when it is not a positive ``int``, because a
    ``SyntaxError``'s own offset is occasionally past the end of its line and
    a law that refused the parser's own answer would refuse the one position
    that is authoritative by construction.  The *line* is what is verified.
    """
    if not isinstance(line, int) or isinstance(line, bool):
        return None
    if not isinstance(column, int) or isinstance(column, bool) or column < 1:
        column = 1
    if not isinstance(source, str) or not source.strip():
        return None

    tree, _error = _parse(source)
    resolvable = (
        _code_lines(tree) if tree is not None else _unparsed_code_lines(source)
    )
    if line not in resolvable:
        return None

    lines = source.splitlines()
    return LocatedDefect(
        line=line,
        column=column,
        symbol=_enclosing_symbol(tree, line),
        source_line=lines[line - 1],
        problem=problem,
    )


def first_defect(source: object) -> LocatedDefect | None:
    """The defect the parser itself names, or ``None`` when the source parses.

    The common case, and the only position this law derives rather than
    verifies: a proposal that does not compile has a defect at the place the
    parser stopped, and ``SyntaxError`` carries that place as ``lineno`` and
    ``offset``.  Nothing is guessed — the parser *is* the reader of the code —
    and the position is rendered under :data:`SIGNAL_SOURCE_FILENAME` because
    that is the filename the parse ran under.

    A source that **does** parse answers ``None``, and that answer is the
    feature's most important default rather than an absence.  The syntax check
    that passes is exactly the case §C3 is about: the code does what the agent
    meant it to, the failure came from elsewhere, and there is no bug in the
    source to point a targeted change at.  What that leaves is the mechanism —
    which is why :meth:`MechanismDiagnosis.diagnose` refuses the retry for it.

    This is deliberately **not** feature 205's signature check restated.  It
    asks whether the source parses, not whether it declares the entrypoint with
    the declared parameters; a source can parse perfectly and still fail the
    contract, and *that* failure is feature 205's to report.  What arrives here
    is the report.

    The parser's line is clamped into range and is *not* re-checked against
    :func:`_code_lines`: an unexpected end-of-file reports a line one past the
    last, and a law that substituted a position of its own for the parser's
    would be locating the defect where it felt like it rather than where the
    code broke.
    """
    if not isinstance(source, str) or not source.strip():
        return None
    _tree, error = _parse(source)
    if error is None:
        return None

    lines = source.splitlines()
    reported = error.lineno if isinstance(error.lineno, int) else 1
    line = min(max(reported, 1), max(len(lines), 1))
    return LocatedDefect(
        line=line,
        column=error.offset if isinstance(error.offset, int) and error.offset >= 1 else 1,
        symbol=MODULE_SYMBOL,
        source_line=lines[line - 1] if lines else "",
        problem=str(error),
    )


class DiagnosisReason(enum.StrEnum):
    """Why a branch was found worth retrying or not — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token its own
    :attr:`DiagnosisVerdict.detail` opens with — so the reason is greppable in
    a campaign log without a lookup table, and a refusal never opens with
    another reason's headline.  The three are split by *repair*, not by which
    check happened to fail, the discipline
    :class:`signal_agent.AdoptionReason` states for its own: a caller handed a
    retryable branch re-prompts it with the located defect quoted, a caller
    handed a flawed mechanism closes the branch and opens another, and a caller
    handed neither has asked about something that did not fail.

    **``retry`` is ``True`` for exactly one of the three**, which is the whole
    of feature 209's second clause.
    """

    #: Retrying: a defect resolves in the proposal's own source, so the idea
    #: behind the branch is not what failed — the code is.  Its detail opens
    #: with :data:`LOCATED_BUG_CODE` rather than with this value, the one place
    #: this enum and its codes differ — the same asymmetry
    #: :attr:`signal_agent.AntiConvergenceReason.NOVEL` has against
    #: :data:`signal_agent.NOVEL_CODE`.  "retryable" is the property a caller
    #: branches on; "located_bug" is the word a log line opens with, and an
    #: admission is not a code an operator greps a campaign for.
    RETRYABLE = "retryable"

    #: Refused: something was reported against this branch and nothing in its
    #: source explains it.  PRD §C3's *"a flawed core mechanism"* — "the former
    #: is not worth retrying" — and this law's headline.  The refusal is the
    #: feature's own decision, which is why it is the one reason that raises:
    #: re-prompting here spends a trial charge to learn nothing (§14.1).  The
    #: reason carries the complaints verbatim, because "not worth retrying" is
    #: not actionable and "the reported failures were X, Y, Z and none of them
    #: is in the code" is.  Spelled as the code itself, so branching on the
    #: value and grepping for it are the same string.
    FLAWED_MECHANISM = FLAWED_MECHANISM_CODE

    #: Refused: there is no diagnosis to make — no complaint was reported, so
    #: no failure happened to diagnose, or the proposal is not source at all.
    #: Its own reason rather than a spelling of the case above because the
    #: repair is different in kind: a flawed mechanism is a research finding
    #: about a branch, and this is a bug at the *call site* (a driver asking
    #: whether to retry something that never failed, or handing in something
    #: that is not a proposal).  An operator looking for a mechanism to abandon
    #: would be looking in the wrong place.  Spelled as the code itself, for the
    #: same reason :attr:`FLAWED_MECHANISM` is.
    NOT_A_DIAGNOSIS = NOT_A_DIAGNOSIS_CODE


class DiagnosisVerdict:
    """One branch's diagnosis: retry or not, why, at what location, in what words.

    ``retry`` is the one field a caller must check, and it is *computed* from the
    reason rather than set by a constant — the same "computed, never assumed"
    stance the member's four other verdicts take for their own answers.  The
    object carries everything the callers downstream need and nothing else:

    * :attr:`defect` — the :class:`LocatedDefect` a retry is admitted on, and
      ``None`` for every refusal.  Carried rather than left to the caller
      because :meth:`require` returns it and because the retry prompt is built
      from it, and a caller that re-located the defect later is exactly the pair
      that can drift;
    * :attr:`complaints` — the sentences the failure was reported with, in the
      order the caller supplied them, carried verbatim so the retry prompt and
      the campaign log can quote what was actually wrong rather than a
      summary.  **It is not what the verdict turns on**: see the module
      docstring's account of the write-up;
    * :attr:`detail` — one operator-facing paragraph, the sentence a campaign
      log records, opening with the code of the reason that produced it.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`signal_agent.SourceAdoption` and
    :class:`signal_agent.AntiConvergenceVerdict` state for their own
    constructors.  The refusals live at :meth:`require`.
    """

    __slots__ = ("complaints", "defect", "detail", "reason", "retry")

    def __init__(
        self,
        *,
        reason: DiagnosisReason,
        detail: str,
        defect: LocatedDefect | None = None,
        complaints: Iterable[str] = (),
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.complaints = tuple(complaints)
        self.defect = defect
        self.retry = reason is DiagnosisReason.RETRYABLE

    def require(self) -> LocatedDefect:
        """Return the located defect, or raise the feature's own refusal.

        The bridge between the law's returned answer and the exception a caller
        wants on the last line before it writes a retry prompt, and it is the
        place feature 209's *"only with the bug actually located in code"* is
        enforced rather than remembered: a retrying verdict returns the
        :class:`LocatedDefect`, whose :attr:`~LocatedDefect.source_line` is the
        proposal verbatim — so a caller that writes
        ``defect = law.require(source, complaints)`` and quotes
        ``defect.render()`` **cannot** build a retry prompt out of a write-up,
        because there is no write-up in the value it was handed.

        A refusal raises :class:`~signal_agent.errors.FlawedMechanismError` with
        this verdict's own sentence — for both refusals, since a caller on its
        last line wants the exception either way and the *reason* is what
        separates them to a caller branching on the returned value, the shape
        :meth:`~signal_agent.SignalThemeGate.require` takes for its two.
        """
        if not self.retry:
            raise FlawedMechanismError(self.detail)
        assert self.defect is not None  # retryable implies a defect, by construction
        return self.defect

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        where = "" if self.defect is None else f", {self.defect.line}:{self.defect.column}"
        return (
            f"DiagnosisVerdict(reason={self.reason.value!r}, retry={self.retry}"
            f"{where}, complaints={len(self.complaints)})"
        )


def _reported(complaints: object) -> tuple[str, ...]:
    """Normalise a failure report into the sentences the verdict carries.

    A bare ``str`` is read as **one** complaint rather than as an iterable of
    characters, which is the one inference this module makes about its caller's
    data and is spelled out here rather than hidden: a caller quoting a single
    validator sentence — ``adoption.problems[0]``, a ``SandboxResult.detail`` —
    is the common case, and reading it as twenty complaints would make the
    count in a refusal's detail nonsense.  The same documented inference
    :func:`signal_agent._anti_convergence._held_digests` makes about a digest.
    """
    if isinstance(complaints, str):
        return (complaints,)
    return tuple(complaints) if isinstance(complaints, Iterable) else ()


def _quoted(complaints: tuple[str, ...]) -> str:
    """The complaint list as a bounded, quoted fragment for a refusal's detail."""
    listed = "; ".join(repr(text) for text in complaints[:MAX_LISTED_COMPLAINTS])
    if len(complaints) > MAX_LISTED_COMPLAINTS:
        listed = f"{listed}; ... ({len(complaints) - MAX_LISTED_COMPLAINTS} more)"
    return listed


class MechanismDiagnosis:
    """Feature 209's law, as the value a composed application carries.

    A facade over this module — the same shape
    :class:`signal_agent.SignalContract` gives feature 205 and
    :class:`signal_agent.AntiConvergenceGate` gives feature 210 — so a caller
    holding the composed component can ask feature 209's question, *is this
    branch worth retrying, and if so where is the bug?*, without importing the
    submodule by name:

    * *is this branch worth retrying?* — :meth:`diagnose`, :meth:`retry` and
      :meth:`require`;
    * *is this position a place in this proposal?* — :meth:`locate`, the read
      side, and the same predicate :meth:`diagnose` runs, so a caller asking
      *would this location count?* and a caller asking for a verdict cannot get
      two answers.

    **It carries nothing.**  No proposal, no complaint, no campaign, no node, no
    store, no prompt: both the source and the failure are handed *in* on every
    call, because a component shared across a campaign that held one would let
    two branches' verdicts be read through each other — the property
    :class:`signal_agent.SignalContract` states for its own handle.

    **It compiles no artifact.**  Unlike features 212's, 213's and 210's gates
    there is no committed document behind this law: what counts as a located bug
    is *a position the proposal's own parse tree occupies*, which is a fact
    about the source rather than a deployment decision, so there is nothing to
    compile and no drifted-artifact state for the composed component to be in.
    That is why :func:`signal_agent.build_mechanism_diagnosis` has no fallback
    branch — feature 205's builder is the member's other one of that shape.

    **Every verb is one call into the law above it** — :func:`locate_defect`,
    :func:`first_defect` and :class:`DiagnosisVerdict` — because a second
    implementation of the resolution rule or the refusal wording here would be a
    second thing to keep in sync with the law, which is the drift this member's
    one-provenance rule exists to prevent.  What the class adds is
    discoverability (the factory's scan composes it) and a single
    duck-checkable seam for the category's remaining features.
    """

    __slots__ = ()

    def locate(
        self, source: object, line: object, column: object = 1, problem: str = ""
    ) -> LocatedDefect | None:
        """The position ``line`` in ``source``, or ``None`` if it is not one.

        The read side, and the same predicate :meth:`diagnose` runs, so a caller
        — a driver building a retry prompt, a dashboard counting how often a
        branch's failure resolved to code — can ask *is this a place in the
        proposal?* without a verdict object.  Answers ``None`` rather than
        raising, because this is the *asking* verb: a caller branching on the
        answer gets a value, and the caller that wants the refusal named calls
        :meth:`diagnose`.
        """
        return locate_defect(source, line, column, problem)

    def diagnose(
        self,
        source: object,
        complaints: object = (),
        *,
        line: object = None,
        column: object = 1,
        problem: str = "",
    ) -> DiagnosisVerdict:
        """Judge one branch: retry it only if a defect resolves in its code.

        The feature's verb.  In order, and each step's own reason:

        1. **it is a proposal** — a non-string, or a string with nothing in it,
           is refused with :attr:`DiagnosisReason.NOT_A_DIAGNOSIS`.  There is
           nothing to locate a defect in, so there is nothing to diagnose, and
           this is a bug in the call that built the proposal (or a caller that
           skipped feature 205's conformance check) rather than a finding about
           a mechanism;
        2. **a defect resolves in the code** — when ``line`` is given it is
           resolved by :meth:`locate`; when it is not, :func:`first_defect`
           asks the parser.  Either way a :class:`LocatedDefect` admits the
           retry with :attr:`DiagnosisReason.RETRYABLE`, carrying the defect
           and the complaints;
        3. **otherwise, the mechanism is what failed** — a complaint was
           reported and nothing in the source explains it, so the branch is
           refused with :attr:`DiagnosisReason.FLAWED_MECHANISM`.  PRD §C3's
           *"the former is not worth retrying"*: a targeted change needs a
           target, and absent one the only thing left to change is the idea.
           With no complaint at all this is
           :attr:`DiagnosisReason.NOT_A_DIAGNOSIS` instead — a branch that did
           not fail is not a retry candidate.

        **``line`` is a claim that is *tried*, and the parser is always asked
        on the retry path — and the write-up is neither.**  A caller with a
        traceback — the sandbox's ``crash`` detail, a validator's
        ``SyntaxError`` — passes the position it names, and a position that
        does not resolve is discarded rather than allowed to shadow the source.
        The order matters and is this way round on purpose: ``first_defect`` is
        the parser's own reading of the code, so a caller cannot *reduce* this
        law's answer by passing a worse claim than the parser would have made.
        A wrong hint changes the *located* position and the sentence that names
        it; it can never turn a retry into a refusal.  A caller that must be
        told its own claim was bad asks :meth:`locate` directly, where a
        position is graded on its own.

        What a caller can *never* do is buy a retry with prose: ``complaints``
        cannot move ``retry`` from ``False`` to ``True``, whatever it says.
        That asymmetry is feature 209's second and third clauses, and it is the
        reason this method returns a value rather than raising.

        **Neither the source nor the complaints are modified.**  This law judges
        a branch; it does not repair one — a gate that edited a proposal "into a
        located bug" would be authoring it, the stance
        :meth:`~signal_agent.AntiConvergenceGate.admit` and
        :meth:`~signal_agent.SignalThemeGate.admit` take toward their own
        inputs.
        """
        reported = _reported(complaints)

        if not isinstance(source, str) or not source.strip():
            described = (
                type(source).__name__
                if not isinstance(source, str)
                else f"a string of {len(source)} character(s) containing no source"
            )
            return DiagnosisVerdict(
                reason=DiagnosisReason.NOT_A_DIAGNOSIS,
                complaints=reported,
                detail=(
                    f"{NOT_A_DIAGNOSIS_CODE}: a defect can only be located in a "
                    f"proposal's own source, and what arrived is {described}. "
                    f"Feature 209 distinguishes a flawed core mechanism from a "
                    f"sound idea undermined by a bug *located in code*, so a "
                    f"submission with no code has no location to be located at — "
                    f"this is a bug in the call that built the proposal (or a "
                    f"caller that skipped feature 205's conformance check) rather "
                    f"than a finding about a mechanism, and the answer is not a "
                    f"retry (feature 209)."
                ),
            )

        # The claimed position is tried first and the parser is asked
        # unconditionally, so a hint can move *where* the defect is and can
        # never make one disappear: the parser's reading of the source is not
        # something a caller gets to override with a worse claim.  Both are
        # cheap — one parse each at most, and no parse at all when the claim
        # already resolved.
        defect = locate_defect(source, line, column, problem)
        if defect is None:
            defect = first_defect(source)

        if defect is not None:
            return DiagnosisVerdict(
                reason=DiagnosisReason.RETRYABLE,
                defect=defect,
                complaints=reported,
                detail=(
                    f"{LOCATED_BUG_CODE}: a defect is located in the proposal's "
                    f"own source at {defect.render()}, so what failed is the "
                    f"code rather than the idea behind it. "
                    f"docs/alpha-engine-prd.md §C3 keeps this distinction in the "
                    f"discovery agent's defining prompt 'nearly verbatim': 'a "
                    f"flawed core mechanism and a good idea let down by a bug — "
                    f"the former is not worth retrying, the latter is, but only "
                    f"with the bug actually located in code rather than guessed "
                    f"from the write-up.' docs/nullius-tech-architecture.md "
                    f"§14.1 gives the depth role the same shape — 'given a "
                    f"mechanism and a diagnostic, make a targeted change' — and "
                    f"this is that target: retry this branch with the mechanism "
                    f"kept and the defect at {SIGNAL_SOURCE_FILENAME}:"
                    f"{defect.line} repaired, quoting that line in the prompt. "
                    f"Retrying is admitted (features 209, 205; PRD §C3, §14.1)."
                ),
            )

        if reported:
            # Reachable only when the source is source-and-parses *and* a
            # complaint was reported — both earlier branches have already
            # returned otherwise, so there is no second parser reading to make
            # here.  Stated because the crispness is the feature: a refusal
            # with this reason *means* the proposal the sandbox could invoke
            # failed anyway, which is §C3's "flawed core mechanism" almost
            # verbatim, and a reader of the sentence should not have to
            # reconstruct that from the control flow.
            return DiagnosisVerdict(
                reason=DiagnosisReason.FLAWED_MECHANISM,
                complaints=reported,
                detail=(
                    f"{FLAWED_MECHANISM_CODE}: {len(reported)} complaint(s) were "
                    f"reported against this branch ({_quoted(reported)}) and no "
                    f"position in the proposal's own source was established as "
                    f"the defect — the source parses, so the parser has no "
                    f"position to hand over, and no position was claimed against "
                    f"it. PRD §C3 names this the case that is 'not worth "
                    f"retrying': docs/nullius-tech-architecture.md §14.1 gives "
                    f"depth 'given a mechanism and a diagnostic, make a targeted "
                    f"change', and a targeted change needs a target — absent one "
                    f"there is nothing to point a repair at, and what is left to "
                    f"change is the mechanism itself. §14.1 also prices the "
                    f"mistake: 'A bad proposal is caught by the evaluator at a "
                    f"cost of one trial charge.' Do not retry this branch — "
                    f"re-prompting spends another charge with no target to aim "
                    f"it at. Open a different mechanism instead, and if a defect "
                    f"*is* in the source, locate it: pass the position the "
                    f"diagnostic names, and a position is a line the proposal's "
                    f"own parse tree occupies (feature 209)."
                ),
            )

        return DiagnosisVerdict(
            reason=DiagnosisReason.NOT_A_DIAGNOSIS,
            complaints=reported,
            detail=(
                f"{NOT_A_DIAGNOSIS_CODE}: the proposal's source parses and no "
                f"complaint was reported against it, so there is no failure to "
                f"diagnose. This law decides whether a *failed* branch is worth "
                f"retrying (feature 209, PRD §C3) — a branch that did not fail "
                f"has no mechanism to find flawed and no bug to locate, and "
                f"answering 'retry' here would be a green tick on a diagnosis "
                f"nobody made. docs/nullius-tech-architecture.md §14.1: 'A bad "
                f"proposal is caught by the evaluator at a cost of one trial "
                f"charge' — that charge, and the evaluator's report of what went "
                f"wrong, is what this law is asked about. If the branch did "
                f"fail, hand its failures in as complaints (feature 209)."
            ),
        )

    def retry(
        self,
        source: object,
        complaints: object = (),
        *,
        line: object = None,
        column: object = 1,
        problem: str = "",
    ) -> bool:
        """Whether this branch is worth retrying — the decision, on its own.

        The read side of the decision, and the same predicate :meth:`diagnose`
        runs, so a driver that only has to branch can ask without a verdict
        object and without the two answers drifting apart.  ``True`` only for
        :attr:`DiagnosisReason.RETRYABLE`, which is feature 209's *"for only the
        second case"* stated as a return type.
        """
        return self.diagnose(
            source, complaints, line=line, column=column, problem=problem
        ).retry

    def require(
        self,
        source: object,
        complaints: object = (),
        *,
        line: object = None,
        column: object = 1,
        problem: str = "",
    ) -> LocatedDefect:
        """Refuse unless a defect is located in the proposal's own source.

        The caller's verb: raises
        :class:`~signal_agent.errors.FlawedMechanismError` — carrying the law's
        own sentence — when the branch is not worth retrying, and returns the
        :class:`LocatedDefect` when it is, so a caller can put it on the last
        line before it writes a retry prompt and have PRD §C3 enforced there
        rather than remembered.
        """
        return self.diagnose(
            source, complaints, line=line, column=column, problem=problem
        ).require()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "MechanismDiagnosis()"


def mechanism_diagnosis() -> MechanismDiagnosis:
    """The law, for a caller that wants it directly.

    Not a component — the ``@register`` builder in this member's ``__init__``
    is, and this is the same call minus the composition.  The member's own tests
    and any operator script reach here.

    Like :func:`signal_agent.signal_contract` and unlike
    :func:`signal_agent.signal_theme_gate` this reads no committed artifact:
    there is nothing beside it to drift, so it cannot raise a named refusal
    here, and that is a property of the feature rather than a missing check.
    """
    return MechanismDiagnosis()
