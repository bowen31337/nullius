"""Feature 230, the admission gate — a policy is admitted only if static checks
find none of the three barrier-breaking anti-patterns.

app_spec.xml, "Exploration Policy Runtime", feature 230: *System rejects a
policy admission when static checks detect absolute score constants, hardcoded
node ids or an unreachable commit path.*  docs/nullius-tech-architecture.md §634
names the checks verbatim — "no absolute score constants, no hardcoded node ids,
… ``commit()`` reachable on every terminating path" — and they are the paper's
hard constraints restated as an admission gate: prefix-only, no absolute score
targets, and ``commit()`` mandatory (a policy that terminates without committing
scores ``-inf``; docs §436, §438).

Feature 230 is the *read side* of that enforcement, and it is deliberately
narrow: it owns the verdict gate a caller runs against a policy's authored
**source** — parse it, walk it, answer admitted or refused, why, in what words.
It does **not** run a policy, score a policy, replay a campaign, or read a
store — those are the *discovery* member's features (232–237), which build on
this one's guarantee that an admitted policy is clean.  The split is the feature:
229 says *a plan must exist and be well-formed*; 230 says *the policy's source
must not break the information barrier*; 233–237 say *the plan's contents must
be sound*.  Keeping them apart is why 230 ``depends_on=229`` and 231–237 build
on 230 — a caller cannot admit a policy it has not first screened.

**A law, not a policy.**  The requirement is a property of *any* policy's
source: whatever it does, it must not carry an absolute score constant, a
hardcoded node id, or a terminating path that never reaches ``commit()``.  That
is a check the runtime makes on the policy's authored code — the same shape
:func:`plan_grid` (feature 229) and :func:`sandbox.screen_module` (feature 167)
take: a gate that returns a verdict, never raises, and lets the caller decide.
The policy-runtime member owns that gate for the admission path.

**The three checks, each its own reason, split by repair.**  The gate answers in
order — readability, then absolute score, then node id, then commit — and each
step's refusal is its own :class:`AdmissionReason`, so a retrying agent is told
*which* contract it broke and how to repair it, not a disjunction.  The order is
the order of the sentence: the most fundamental problem (the source cannot be
read) is named first, the most policy-specific (a path that never commits) last.

**No false negatives over false positives — that is the barrier's whole point.**
The information barrier (docs §10.2) is a hard rule, not a heuristic, and the
gate enforces it that way.  A policy that compares an *observed* metric to an
absolute number (``observed[c].r2_insample > 0.8``) is *flagged* — because the
barrier forbids a policy authoring *any* absolute score constant, and a policy
that needs one has already broken the contract; refusing it and naming the
literal is the correct, safe answer.  The alternative — trying to prove the left
side "is not a score" — is a false-negative machine that lets ``score >= 0.8``
through, which is the exact leak the barrier exists to prevent.  This is the
same stance [[featsel-argmax-not-equality-pinned]] records elsewhere: pin the
property, do not rationalise the exception away.

**The node-id detector is address-shaped, not a dictionary.**  A node id in this
system is an *indexed address* — ``n0``, ``d+9.i+0.s+0.a+0`` — lowercase,
segment-joined, and carrying a digit (node ids are indexed, never a bare word).
The detector matches that shape and requires both a letter and a digit, so a
theme root (``momentum``, ``value``), a calibration status (``VOID``), prose in
a message, and a UUID (excluded by pattern) are never mistaken for a node id.
A bare word like ``"root"`` is deliberately *not* flagged — it is as likely an
English word as an address, and refusing on it would be a false positive; the
safe direction is to miss the rare bare-word root rather than to flag legitimate
vocabulary.

**Commit reachability is intra-procedural and inline.**  The gate walks each
top-level function that contains a ``commit()`` call and asks whether every
terminating path (``return``, ``raise``, or falling off the end) is preceded, on
its own path, by a ``commit()``.  A function with no ``commit()`` call is treated
as a helper and not held to the reachability standard — the committing happens
elsewhere — but a source that contains *no* ``commit()`` at all is refused,
because ``commit()`` is mandatory.  The boundary is documented and deliberate: a
policy that commits only inside a helper it then calls, while its own body has an
early return, is not modelled across the call boundary; the canonical policy
commits inline at its terminal, and refusing what the analysis cannot prove is
the safe direction for a barrier check.

Stdlib only, and import-cheap: :mod:`ast`, :mod:`re`, :mod:`enum`, :mod:`typing`
and the member's own errors — no third-party import at module scope, so the
factory's scan (which imports this member to fire its ``@register`` builder) pays
nothing for the gate.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from .errors import PolicyAdmissionRefusal

__all__ = [
    "AdmissionReason",
    "PolicyAdmissionDecision",
    "screen_policy",
]


class AdmissionReason(str, Enum):
    """Why a policy's source was admitted or refused — the audit vocabulary.

    A :class:`str` enum whose *value* is the token every refusal's detail opens
    with, so the reason is greppable in an admission log without a lookup table
    and a reader never has to match a sentence to a category by eye.  The six
    are split by *repair*, not by which check happened to fail: two policies
    that both break the barrier for different reasons are two different prompts
    to the retrying agent, so they are two reasons.
    """

    #: Admitted: the source is readable, parses, and carries no absolute score
    #: constant, no hardcoded node id, and no terminating path that fails to
    #: reach ``commit()``.
    CLEAN = "clean"

    #: Refused: the source is not text, is blank, or does not parse, so the
    #: checks cannot read it.  Its own reason because the repair is at the
    #: *submission*, not the barrier — a screen cannot admit what it cannot
    #: read, and passing it would be reporting clean over code it never checked,
    #: the vacuous green no admission gate may allow (the stance
    #: :func:`sandbox.screen_module` takes on feature 167).
    UNREADABLE_SOURCE = "unreadable-source"

    #: Refused: the source carries an absolute score constant — a numeric
    #: literal compared against something (``>= 0.8``, ``< 0.5``, ``== 0.75``).
    #: The barrier forbids a policy authoring *any* absolute score target, so a
    #: policy that compares anything to an absolute number has already broken
    #: the contract; the repair is "remove the absolute score constant".
    ABSOLUTE_SCORE = "absolute-score"

    #: Refused: the source carries a hardcoded node id — a string literal shaped
    #: like an indexed address (``"n0"``, ``"d+9.i+0"``).  A node id is the one
    #: address a node is revealed or committed on, and a policy that names one is
    #: reading past the prefix the barrier promises it; the repair is "address
    #: cells through ``question.*``, never by a literal id".
    HARDCODED_NODE_ID = "hardcoded-node-id"

    #: Refused: a terminating path — a ``return``, a ``raise``, or falling off
    #: the end — is reachable without a preceding ``commit()``.  ``commit()`` is
    #: mandatory, so a path that can end without committing is a policy that can
    #: score on a pick it never made; the repair is "commit on every path".
    UNREACHABLE_COMMIT = "unreachable-commit"


#: A node id is an indexed address: lowercase alphanumeric segments joined by
#: ``.``, ``+``, ``-`` or ``_`` — the spelling the planted tree (``n0``) and the
#: bootstrap lattice (``d+9.i+0.s+0.a+0``) both use.  Uppercase (a calibration
#: status like ``VOID``), whitespace (prose in a message) and a bare word
#: (``momentum``, ``value``) do not match — and a UUID is excluded separately.
_ADDRESS_RE = re.compile(r"^[a-z0-9]+(?:[.+\-_][a-z0-9]+)*$")

#: A UUID — lowercase hex in the 8-4-4-4-4 shape — matches ``_ADDRESS_RE`` and
#: carries digits, so it is excluded on its own pattern: a world or campaign id
#: a policy legitimately carries is not a node address.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _is_numeric_constant(node: ast.AST) -> bool:
    """Whether ``node`` is a numeric literal — an ``int`` or ``float``, not a bool.

    ``bool`` is an ``int`` subclass, so ``True``/``False`` are excluded: a
    ``is_null = True`` flag is not an absolute score, and the affinity trap the
    workspace's SQLite layer guards is the same one guarded here.
    """
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    )


def _looks_like_node_id(text: object) -> bool:
    """Whether a string literal is shaped like an indexed node address.

    Matches ``_ADDRESS_RE`` (lowercase, segment-joined) and requires *both* a
    letter and a digit — the digit because node ids are indexed (``n0``,
    ``d+9``), the letter because a bare number string (``"2024"``, ``"123"``)
    is more likely a count than an address.  A UUID is excluded by pattern, so
    the world/campaign ids a policy legitimately carries are never mistaken for
    a hardcoded node id.
    """
    if not isinstance(text, str) or not text:
        return False
    if _UUID_RE.match(text):
        return False
    if not _ADDRESS_RE.match(text):
        return False
    return any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text)


class _CommitFinder(ast.NodeVisitor):
    """Does a subtree perform a ``commit()`` — a ``.commit(...)`` attribute call.

    Matches ``question.commit(node_id)`` by the method name alone, so the gate is
    blind to whatever the policy names its question (``q``, ``ctx``, ``question``)
    — the interface is the attribute, not the binding.  It does **not** descend
    into a nested ``def``/``lambda``/``class``: a commit defined in a nested
    scope is not performed when the enclosing statement runs, so counting it
    would let a path look committed when it is not.
    """

    def __init__(self) -> None:
        self.found = False

    def visit(self, node: ast.AST) -> None:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            return  # a nested scope's commit is not this statement's commit
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
        ):
            self.found = True
            return
        super().visit(node)


def _contains_commit(node: ast.AST) -> bool:
    """Whether ``node``'s subtree performs a ``commit()`` (not through a nested scope)."""
    finder = _CommitFinder()
    finder.visit(node)
    return finder.found


def _contains_break(node: ast.AST) -> bool:
    """Whether ``node``'s subtree contains a ``break`` — a way out of a loop.

    A ``while True`` that can ``break`` is not truly infinite: the break exits
    the loop to whatever follows, so the post-loop path is reachable and must be
    judged.  A ``while True`` with no break loops forever, so nothing after it
    runs — the conservative "the loop may never complete" rule does not apply.
    """
    return any(isinstance(n, ast.Break) for n in ast.walk(node))


def _is_infinite_while(stmt: ast.AST) -> bool:
    """Whether a ``while`` loops forever — a constant-truthy test and no break.

    ``while True:`` (and the ``while 1:`` / ``while "x":`` spellings) with no
    ``break`` never completes, so control never reaches the statements after it,
    and the loop itself is not a fall-off point.  The canonical policy is exactly
    this shape — an unbounded walk that returns its commit from inside the loop
    (docs §476) — so it must be admitted, not refused as "falling off without a
    commit".  Any non-constant test (``while frontier:``) is treated as finite:
    it may never run, so the post-loop path is reachable and judged.
    """
    if not isinstance(stmt, ast.While):
        return False
    test = stmt.test
    return (
        isinstance(test, ast.Constant)
        and bool(test.value)
        and not _contains_break(stmt)
    )


def _function_contains_commit(func: ast.AST) -> bool:
    """Whether a function performs a ``commit()`` anywhere, nested scopes included.

    Descends everywhere (a plain :func:`ast.walk`), because the question here is
    only *is this function commit-related at all* — the gate that decides whether
    to hold it to the reachability standard.  A function with no ``commit()``
    call anywhere is a helper whose committing happens elsewhere, and is not
    checked for reachability; a source with no ``commit()`` anywhere is refused
    by the mandatory-commit check before any function is examined.
    """
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "commit"
        for n in ast.walk(func)
    )


def _top_level_functions(tree: ast.AST) -> list[ast.AST]:
    """The functions a policy's committing path can live in.

    Module-level ``def``/``async def`` — the canonical policy is one top-level
    function — plus the methods of a module-level ``class`` (a class-based
    policy commits in a method).  Nested helpers and comprehensions are not
    returned: they are not the policy's terminal path.  A method's committing
    path is checked the same way a function's is, because a method that returns
    without committing is the same barrier break.
    """
    functions: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node)
        elif isinstance(node, ast.ClassDef):
            functions.extend(
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return functions


def _scan_suite(
    body: Sequence[ast.stmt], seen_commit: bool
) -> tuple[list[ast.stmt], bool]:
    """Scan a statement suite for terminating paths that never reach a commit.

    Returns ``(offenders, can_fall_off_without_commit)``:

    * **``offenders``** — the ``return``/``raise`` statements reachable on some
      path through this suite without a ``commit()`` having been seen on that
      path.  A ``return question.commit(x)`` is not an offender: the commit is
      performed *in* the terminating statement, so it is checked before the
      return is judged.
    * **``can_fall_off_without_commit``** — whether control can reach the end of
      this suite (an implicit ``return None``) without a ``commit()`` having
      been seen.  A suite that ends in a committing return cannot fall off.

    ``if``/``else`` is path-sensitive: both branches are scanned with the
    ``seen_commit`` inherited from before the ``if``, and the ``if`` is
    commit-safe afterwards only if it was already safe before or *both* branches
    are.  ``for``/``while`` and ``try`` are scanned for offenders inside, but a
    loop does not guarantee its body ran, so it cannot make the post-loop path
    commit-safe — the conservative answer for a barrier check.
    """
    offenders: list[ast.stmt] = []
    live = True  # statements after a terminating one are dead
    seen = seen_commit
    for stmt in body:
        if not live:
            break
        if isinstance(stmt, (ast.Return, ast.Raise)):
            if not (seen or _contains_commit(stmt)):
                offenders.append(stmt)
            live = False  # nothing after a bare return/raise is reachable
        elif isinstance(stmt, ast.If):
            then_off, then_falls = _scan_suite(stmt.body, seen)
            else_off, else_falls = _scan_suite(stmt.orelse, seen)
            offenders.extend(then_off)
            offenders.extend(else_off)
            # The if can fall off without a commit if either branch can — unless
            # a commit was already seen before the if, in which case every path
            # through it is commit-safe.
            falls = (then_falls or else_falls) if not seen else False
            if falls:
                seen = False  # a no-commit path reaches the statements after
            else:
                seen = True  # both branches committed (or it was committed before)
                live = False  # both branches terminate: what follows is dead code
        elif isinstance(stmt, (ast.For, ast.While)):
            loop_off, _ = _scan_suite(stmt.body, seen)
            orelse_off, _ = _scan_suite(stmt.orelse, seen)
            offenders.extend(loop_off)
            offenders.extend(orelse_off)
            if isinstance(stmt, ast.While) and _is_infinite_while(stmt):
                # A ``while True`` with no break never completes, so control
                # never reaches the statements after it — the loop is not a
                # fall-off point, and what follows is dead code.  The canonical
                # policy is exactly this shape (an unbounded walk that returns
                # its commit from inside the loop), so it must be admitted.
                live = False
            # A finite loop (or a ``for``) may never run, so it cannot make the
            # post-loop path commit-safe; ``seen`` is unchanged, and an unsafe
            # return inside is already noted above.
        elif isinstance(stmt, ast.Try):
            for sub in (stmt.body, stmt.orelse, stmt.finalbody):
                sub_off, _ = _scan_suite(sub, seen)
                offenders.extend(sub_off)
            for handler in stmt.handlers:
                handler_off, _ = _scan_suite(handler.body, seen)
                offenders.extend(handler_off)
            # Conservatively, a try does not guarantee the post-try path committed.
        else:
            # An ordinary statement: an assignment, a probe, a loop step.  It
            # performs a commit only if it contains a ``commit()`` call.
            if _contains_commit(stmt):
                seen = True
    return offenders, (live and not seen)


@dataclass(frozen=True)
class PolicyAdmissionDecision:
    """One policy's admission verdict: admitted or refused, why, in what words,
    naming what was wrong.

    The shape every gate in this workspace takes (:class:`signal_agent.
    SourceAdoption`, :class:`sandbox.ModuleDecision`, feature 229's
    :class:`PlanGridDecision`) — a returned verdict, never a raised exception, so
    the caller diagnoses *why* a policy was not admitted.  ``adopted`` is
    *computed* from the reason, never assumed — the same "computed, never
    assumed" stance those decisions take — and ``offenders`` carries the
    offending literals and lines (for a refusal), so a caller that has checked
    ``adopted`` reads exactly what to repair rather than a sentinel.
    """

    reason: AdmissionReason
    detail: str
    #: The offending literals and lines, for a refusal; empty for an admission.
    #: A policy that hardcodes two node ids names both, so the author repairs
    #: them all rather than resubmitting to learn the rest — the same
    #: "name every offender" stance :func:`sandbox.screen_module` takes.
    offenders: tuple[str, ...] = field(default=())
    #: The admitted source, for an admission; ``None`` for every refusal.
    #: Carried so a caller that has checked ``adopted`` reads the source it
    #: admitted rather than re-invoking the gate — and returned *unchanged* by
    #: :meth:`require`, so the bytes a later stage hashes are exactly these.
    source: str | None = None

    @property
    def adopted(self) -> bool:
        """Whether the policy's source may be admitted — computed from reason."""
        return self.reason is AdmissionReason.CLEAN

    def require(self) -> str:
        """Return the admitted source, or raise :class:`PolicyAdmissionRefusal`.

        The bridge between the gate's returned verdict and the exception a caller
        wants on its last line before admitting a policy: an admitted source is
        returned unchanged (adoption is a judgement, never an edit — the bytes a
        later stage hashes are exactly these), so a caller can write ``source =
        law.screen_policy(source).require()`` and have feature 230 enforced
        there rather than remembered.  A refusal raises naming the policy, so the
        admission log and the retry prompt say the same thing.
        """
        if self.source is None:
            raise PolicyAdmissionRefusal(self.detail)
        return self.source

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PolicyAdmissionDecision(reason={self.reason.value!r}, "
            f"adopted={self.adopted}, offenders={len(self.offenders)})"
        )


def _refusal(
    reason: AdmissionReason,
    offenders: Sequence[str],
    *,
    lead: str,
    tail: str,
) -> PolicyAdmissionDecision:
    """A refusal decision — the reason token, every offender, and the sentence.

    One builder so every refusal renders the same way: the reason's value token
    leads (greppable), the offenders are listed (name every offender, so the
    author repairs them all), and the barrier rationale closes.  The gate returns
    these; it never raises.
    """
    listed = "; ".join(offenders)
    return PolicyAdmissionDecision(
        reason=reason,
        detail=(
            f"{reason.value}: {lead} — {listed}. {tail} (feature 230)."
        ),
        offenders=tuple(offenders),
    )


def screen_policy(source: object) -> PolicyAdmissionDecision:
    """Admit one policy's authored source only if static checks find it clean.

    The feature's verb.  Takes the policy's authored **source** — the text a
    policy is admitted as — and answers whether it may be admitted, in order,
    each step's own reason:

    1. **it is readable** — a non-string, a blank string, or source that does not
       parse is refused with :attr:`AdmissionReason.UNREADABLE_SOURCE`; a gate
       cannot admit what it cannot read, and passing it would be reporting clean
       over code it never checked — the vacuous green no admission screen may
       allow, the same stance :func:`sandbox.screen_module` takes;
    2. **it carries no absolute score constant** — every ``ast.Compare`` with a
       numeric literal operand is an offender, refused with
       :attr:`AdmissionReason.ABSOLUTE_SCORE`; the barrier forbids a policy
       authoring *any* absolute score target, so a policy that compares anything
       to an absolute number has broken the contract, and no attempt is made to
       prove the other side "is not a score" — that would be the false negative
       that lets ``score >= 0.8`` through;
    3. **it carries no hardcoded node id** — every string literal shaped like an
       indexed address (``_ADDRESS_RE``, with a letter and a digit, a UUID
       excluded) is an offender, refused with :attr:`AdmissionReason.
       HARDCODED_NODE_ID`; a node id is the one address a node is revealed or
       committed on, and a policy that names one is reading past the prefix;
    4. **its commit is reachable on every terminating path** — each top-level
       function that contains a ``commit()`` call is walked, and a ``return``, a
       ``raise``, or falling off the end that is reachable without a preceding
       ``commit()`` is an offender, refused with :attr:`AdmissionReason.
       UNREACHABLE_COMMIT``; a source with no ``commit()`` at all is refused the
       same way, because ``commit()`` is mandatory.

    Returns a :class:`PolicyAdmissionDecision` — admitted or refused, why, in
    what words, naming every offender — never raising.  The checks are a pure
    read of the source's AST: no I/O, no store, no campaign, so the gate is
    import-cheap and free of a hard dependency on the store, the same reason
    feature 229's :func:`plan_grid` defers nothing to module scope.
    """
    if not isinstance(source, str) or not source.strip():
        described = type(source).__name__ if not isinstance(source, str) else "blank source"
        return _refusal(
            AdmissionReason.UNREADABLE_SOURCE,
            (f"source is {described!r}",),
            lead=(
                "a policy must be admitted as a non-empty string of Python source, "
                "and the gate cannot judge code it cannot read"
            ),
            tail=(
                "Passing unreadable source would be reporting clean over code the "
                "gate never checked — the vacuous green no admission screen may "
                "allow, so the policy is refused before any barrier is judged"
            ),
        )

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as broken:
        where = getattr(broken, "lineno", None)
        message = getattr(broken, "msg", broken)
        location = f"line {where}: " if where is not None else ""
        return _refusal(
            AdmissionReason.UNREADABLE_SOURCE,
            (f"{location}{message}",),
            lead="a policy's source does not parse, so its anti-patterns are unknowable",
            tail=(
                "'unknown' is not 'clean': a submission whose imports and literals "
                "cannot be read is refused rather than waved through on the half of "
                "it that happened to parse"
            ),
        )

    # (2) Absolute score constants — a numeric literal compared against something.
    score_offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for operand in operands:
                if _is_numeric_constant(operand):
                    op_text = " ".join(
                        type(op).__name__.lower() for op in node.ops
                    ) or "compared"
                    score_offenders.append(
                        f"line {node.lineno}: absolute score constant "
                        f"{operand.value!r} ({op_text})"
                    )
    if score_offenders:
        return _refusal(
            AdmissionReason.ABSOLUTE_SCORE,
            score_offenders,
            lead=(
                "the policy carries an absolute score constant — a numeric literal "
                "compared against something, which is an absolute score target"
            ),
            tail=(
                "The information barrier forbids a policy authoring any absolute "
                "score target, and a policy that compares anything to an absolute "
                "number has already broken the contract; no attempt is made to "
                "prove the other side 'is not a score', because that is the false "
                "negative that lets an absolute target through"
            ),
        )

    # (3) Hardcoded node ids — a string literal shaped like an indexed address.
    node_offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _looks_like_node_id(node.value)
        ):
            node_offenders.append(
                f"line {node.lineno}: hardcoded node id {node.value!r}"
            )
    if node_offenders:
        return _refusal(
            AdmissionReason.HARDCODED_NODE_ID,
            node_offenders,
            lead="the policy carries a hardcoded node id — a string literal shaped like an indexed address",
            tail=(
                "A node id is the one address a node is revealed or committed on, "
                "and a policy that names one by a literal is reading past the "
                "prefix the barrier promises it; cells are addressed through "
                "question.*, never by a literal id"
            ),
        )

    # (4) Commit reachability — every terminating path must reach a commit().
    commit_offenders: list[str] = []
    functions = _top_level_functions(tree)
    has_commit_anywhere = any(_function_contains_commit(fn) for fn in functions)
    if not has_commit_anywhere:
        commit_offenders.append("the source contains no commit() call at all")
    else:
        for func in functions:
            if not _function_contains_commit(func):
                continue  # a helper with no commit: the committing happens elsewhere
            name = getattr(func, "name", "<policy>")
            offenders, falls_off = _scan_suite(func.body, seen_commit=False)
            for off in offenders:
                commit_offenders.append(
                    f"{name} line {off.lineno}: a return/raise reachable with no "
                    f"commit() on its path"
                )
            if falls_off:
                commit_offenders.append(
                    f"{name}: can finish (fall off the end) without reaching commit()"
                )
    if commit_offenders:
        return _refusal(
            AdmissionReason.UNREACHABLE_COMMIT,
            tuple(commit_offenders),
            lead="a terminating path is reachable without a preceding commit()",
            tail=(
                "commit() is mandatory — a policy that terminates without "
                "committing scores -inf — so a path that can end without a "
                "commit() is a policy that can score on a pick it never made; "
                "commit on every terminating path"
            ),
        )

    return PolicyAdmissionDecision(
        reason=AdmissionReason.CLEAN,
        detail=(
            f"{AdmissionReason.CLEAN.value}: the policy's source carries no "
            f"absolute score constant, no hardcoded node id, and no terminating "
            f"path that fails to reach commit() — every check in feature 230 is "
            f"satisfied and the policy is admitted (feature 230)."
        ),
        source=source,
    )
