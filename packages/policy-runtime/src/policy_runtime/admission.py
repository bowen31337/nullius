"""Features 230 and 231, the admission gate — a policy is admitted only if
static checks find none of the barrier-breaking anti-patterns.

app_spec.xml, "Exploration Policy Runtime", feature 230: *System rejects a
policy admission when static checks detect absolute score constants, hardcoded
node ids or an unreachable commit path.*  docs/nullius-tech-architecture.md §634
names the checks verbatim — "no absolute score constants, no hardcoded node ids,
… ``commit()`` reachable on every terminating path" — and they are the paper's
hard constraints restated as an admission gate: prefix-only, no absolute score
targets, and ``commit()`` mandatory (a policy that terminates without committing
scores ``-inf``; docs §436, §438).

Feature 231 adds the fourth check to the same gate — *System rejects a policy
admission that loads a model checkpoint or calls inference, because a learned
component stays deferred until the triage measurement decides it* (app_spec.xml
feature 231; docs §11.2, §12, §15).  It is a sibling of 230's three rather than a
second gate: the refusal is returned by this module's :func:`screen_policy`,
carried by this module's :class:`PolicyAdmissionDecision`, raised by this
module's :meth:`PolicyAdmissionDecision.require`, and reported under its own
:class:`AdmissionReason`, so the retrying agent is told *which* decision it ran
ahead of.  The detector itself lives in :mod:`.learned` — the shape of what a
learned component looks like in source is 231's business, and this module's is
the verdict — the same split :mod:`.planning` keeps from the component.

The checks run in order — readability, absolute score, node id, commit, learned
component — so the most fundamental problem is named first.

Feature 230 is the *read side* of that enforcement, and it is deliberately
narrow: it owns the verdict gate a caller runs against a policy's authored
**source** — parse it, walk it, answer admitted or refused, why, in what words.
It does **not** run a policy, score a policy, replay a campaign, or read a
store — those are the *discovery* member's features (232–237), which build on
this one's guarantee that an admitted policy is clean.  The split is the feature:
229 says *a plan must exist and be well-formed*; 230 says *the policy's source
must not break the information barrier*; 231 says *it must not reach for a
learned component either*; 233–237 say *the plan's contents must be sound*.
Keeping them apart is why 230 ``depends_on=229`` and 231–237 build
on 230 — a caller cannot admit a policy it has not first screened.

**A law, not a policy.**  The requirement is a property of *any* policy's
source: whatever it does, it must not carry an absolute score constant, a
hardcoded node id, or a terminating path that never reaches ``commit()``.  That
is a check the runtime makes on the policy's authored code — the same shape
:func:`plan_grid` (feature 229) and :func:`sandbox.screen_module` (feature 167)
take: a gate that returns a verdict, never raises, and lets the caller decide.
The policy-runtime member owns that gate for the admission path.

**The checks, each its own reason, split by repair.**  The gate answers in
order — readability, then absolute score, then node id, then commit, then
learned component — and each step's refusal is its own
:class:`AdmissionReason`, so a retrying agent is told *which* contract it broke
and how to repair it, not a disjunction.  The order is the order of the
sentence: the most fundamental problem (the source cannot be read) is named
first, the most policy-specific (a path that never commits) last, and the one
that is a *deferral* rather than a barrier (feature 231's) after it — because a
policy with no reachable ``commit()`` is broken whatever else it carries, while
a policy that commits correctly on every path is wrong only about what may
exist.

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

**Commit reachability — inline, or followed through a same-module helper for a
question-contract policy.**  The gate asks whether every terminating path
(``return``, ``raise``, or falling off the end) reaches a *terminating act* —
``commit()`` or ``abstain()`` — since abstaining is a decision a policy is
allowed to declare, not a silent fall-off, and the two are counted wherever
either is (docs/preregistration/2026-10-17-m3-dreaming.md: an abstained arm is
scored as a flat book).  Which paths are asked about depends on the contract the
module declares:

* **A module that declares ``CONTRACT = "question"``** is called through one
  entrypoint, its top-level ``select``, so the walk starts there and every one of
  ``select``'s terminating paths must reach a ``commit()`` or an ``abstain()``
  *on that path*, or a call to a same-module top-level function that itself
  reaches one on every one of its paths — followed transitively, with a cycle
  counted as not satisfying.  That is what closes the helper loophole: a
  ``select`` that keeps ``.commit(`` out of its own body, calls a one-line
  ``_commit`` helper only on the branch where a node clears the bar, and returns
  or falls off otherwise is refused, because the helper-shaped abstention it
  performs on the other branch is exactly the path the check exists to find.
* **Every other module** — the ``select(prefix_view)`` rankers, which declare no
  marker — is judged as it always was, with ``abstain()`` counted like
  ``commit()``: each top-level function that itself contains a terminating act is
  walked, and a function with none is a helper not held to the standard, because
  the committing happens elsewhere.  A source with neither ``commit()`` nor
  ``abstain()`` anywhere is refused either way, because one of the two is
  mandatory.

Stdlib only, and import-cheap: :mod:`ast`, :mod:`re`, :mod:`enum`, :mod:`typing`
and the member's own errors — no third-party import at module scope, so the
factory's scan (which imports this member to fire its ``@register`` builder) pays
nothing for the gate.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from .errors import PolicyAdmissionRefusal
from .learned import find_learned_component

__all__ = [
    "AdmissionReason",
    "PolicyAdmissionDecision",
    "screen_policy",
]


class AdmissionReason(str, Enum):
    """Why a policy's source was admitted or refused — the audit vocabulary.

    A :class:`str` enum whose *value* is the token every refusal's detail opens
    with, so the reason is greppable in an admission log without a lookup table
    and a reader never has to match a sentence to a category by eye.  The
    reasons are split by *repair*, not by which check happened to fail: two
    policies that both break the barrier for different reasons are two different
    prompts to the retrying agent, so they are two reasons.  (Feature 230's
    spec prose counts "the six" as the vocabulary stood then; the value of each
    member is the contract, not the tally, so this docstring does not restate a
    count that every later check would have to re-edit.)
    """

    #: Admitted: the source is readable, parses, and carries no absolute score
    #: constant, no hardcoded node id, no terminating path that fails to reach
    #: ``commit()``, and no learned component.
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
    #: the end — is reachable without a preceding ``commit()`` or ``abstain()``.
    #: One of the two is mandatory (an episode that ends with neither scores
    #: ``-inf`` and has declared nothing), so a path that can end without either
    #: is a policy that can score on a pick it never made and never said it would
    #: not make; the repair is "commit() or abstain() on every path" — and, for
    #: a module declaring ``CONTRACT = "question"``, on every path of ``select``
    #: once same-module helpers are followed.
    UNREACHABLE_COMMIT = "unreachable-commit"

    #: Refused: the source reaches for a learned component — it imports a model
    #: framework, loads a checkpoint, or calls inference (feature 231).  Its own
    #: reason because the repair is not a repair at all but a *wait*: docs §11.2
    #: defers the learned component until the M1 triage measures the
    #: perturbation-stability AUC, and §12 forbids inference in the replay path
    #: outright, so a policy written against one is written against a premise
    #: the system has not yet decided — the repair is "write the policy against
    #: ``question.*`` and the thresholds dreaming revises; a learned component is
    #: not available".
    LEARNED_COMPONENT = "learned-component"


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


#: The method names that count as an episode's terminating act in the
#: reachability walk.  ``commit()`` is the pick; ``abstain()`` is the *declared*
#: decision to make none (docs/preregistration/2026-10-17-m3-dreaming.md makes an
#: abstained arm a legitimate outcome, scored as a flat book rather than as the
#: fall-off it used to be indistinguishable from), so both are acts a terminating
#: path may end on, and every walk below counts them wherever it counts either.
_TERMINATING_ACTS = ("commit", "abstain")

#: The value of the module-level ``CONTRACT`` marker that names the question
#: contract — the one contract whose policy is called through a single
#: ``select(question)`` entrypoint, and therefore the one the gate judges as a
#: whole program rather than function by function.
_QUESTION_CONTRACT = "question"


class _TerminatingActFinder(ast.NodeVisitor):
    """Does a subtree perform a terminating act — a ``.commit(...)`` or
    ``.abstain()`` attribute call.

    Matches ``question.commit(node_id)`` and ``question.abstain()`` by the
    method name alone, so the gate is blind to whatever the policy names its
    question (``q``, ``ctx``, ``question``) — the interface is the attribute, not
    the binding.  It does **not** descend into a nested ``def``/``lambda``/
    ``class``: an act defined in a nested scope is not performed when the
    enclosing statement runs, so counting it would let a path look committed
    when it is not.
    """

    def __init__(self, methods: Sequence[str] = _TERMINATING_ACTS) -> None:
        self.found = False
        self._methods = methods

    def visit(self, node: ast.AST) -> None:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            return  # a nested scope's act is not this statement's act
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in self._methods
        ):
            self.found = True
            return
        super().visit(node)


def _contains_act(node: ast.AST) -> bool:
    """Whether ``node`` performs a ``commit()`` or ``abstain()`` (not nested).

    The one predicate the reachability walk uses for "this statement is where a
    path terminates", so ``abstain()`` counts exactly where ``commit()`` does.
    """
    finder = _TerminatingActFinder()
    finder.visit(node)
    return finder.found


class _CalledNameFinder(ast.NodeVisitor):
    """Which of ``names`` a subtree *calls*, directly or as ``return helper(x)``.

    A call is a ``Name`` — ``_commit(q, best)`` — never an attribute, because
    what can be followed is a same-module top-level function and nothing else.
    Like :class:`_TerminatingActFinder` it does not descend into a nested scope:
    a helper named inside a closure is that closure's call, not this
    statement's.  It also does not descend into a comprehension or a generator,
    and that one is not tidiness: ``[_settle(q, n) for n in nodes]`` calls the
    helper *once per element*, so an empty ``nodes`` never calls it at all.
    Following a call the statement may make zero times would report an act the
    statement does not guarantee — the safe direction is to not see it.
    """

    def __init__(self, names: Sequence[str]) -> None:
        self.found: set[str] = set()
        self._names = set(names)

    def visit(self, node: ast.AST) -> None:
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.ClassDef,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in self._names
        ):
            self.found.add(node.func.id)
        super().visit(node)


def _called_helpers(node: ast.AST, helpers: Mapping[str, ast.AST]) -> set[str]:
    """The same-module top-level helpers ``node`` calls by name."""
    finder = _CalledNameFinder(tuple(helpers))
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


def _function_contains_act(func: ast.AST) -> bool:
    """Whether a function performs a ``commit()`` or ``abstain()`` anywhere.

    Descends everywhere (a plain :func:`ast.walk`), because the question here is
    only *does this function terminate an episode at all* — the gate that decides
    whether to hold it to the reachability standard.  A function with neither act
    anywhere is a helper whose terminating happens elsewhere, and is not checked
    for reachability; a source with neither act anywhere is refused by the
    mandatory-act check before any function is examined.
    """
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _TERMINATING_ACTS
        for n in ast.walk(func)
    )


def _module_functions(tree: ast.AST) -> dict[str, ast.AST]:
    """The module's own top-level functions, keyed by name.

    What a question-contract ``select`` may *call*: a same-module top-level
    ``def``/``async def``.  Class methods and nested helpers are not followed —
    they are not what the policy's entrypoint names, and the boundary is the
    module's top level, the same one the loader reaches ``select`` through.
    """
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _question_contract_marker(tree: ast.AST) -> bool:
    """Whether the module declares ``CONTRACT = "question"`` at its top level.

    The marker the loader (:func:`orchestrator._policy._module_contract`) reads
    to decide which interface the module answers to, read here straight off the
    AST — a module-level assignment to ``CONTRACT`` whose value is the string
    ``"question"``, in either the plain or the annotated (``CONTRACT: Final``)
    spelling, since the loader reads whichever binding the module ends up with.
    A marker in any other spelling, value, or scope is not the marker, and the
    module is judged by the unmarked rule.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            ]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if "CONTRACT" not in names:
            continue
        value = node.value
        if (
            isinstance(value, ast.Constant)
            and value.value == _QUESTION_CONTRACT
        ):
            return True
    return False


class _SelectCallGraph:
    """Follows a question-contract ``select``'s calls, transitively, within the module.

    The question contract is called through one entrypoint, so the reachability
    question is asked of the module as a whole: a terminating path is safe when
    it reaches a ``commit()``/``abstain()`` on that path or routes through a
    same-module top-level function that reaches one on *every* one of its own
    paths.  This walks that relation.

    A helper already on the walk's own stack is a **cycle**, and a cycle does not
    satisfy the standard: the only way a mutually recursive pair could answer
    "yes" is to assume the answer, which is precisely the reasoning a barrier
    check may not use.  Answers are cached, so a helper called on twenty branches
    is scanned once.
    """

    def __init__(self, functions: Mapping[str, ast.AST]) -> None:
        self._functions = dict(functions)
        self._safe: dict[str, bool] = {}
        self._active: set[str] = set()

    def performs_act(self, stmt: ast.AST) -> bool:
        """Whether ``stmt`` guarantees a terminating act when it runs to completion.

        Either it writes ``.commit(``/``.abstain(`` itself, or every same-module
        helper it calls is itself safe — *every*, because a statement that calls
        two helpers with an unsafe one first may end inside that unsafe one.  A
        statement that calls a helper which only *sometimes* acts guarantees
        nothing, which is the whole point of following it.
        """
        if _contains_act(stmt):
            return True
        called = _called_helpers(stmt, self._functions)
        if not called:
            return False
        return all(self._is_safe(name) for name in called)

    def _is_safe(self, name: str) -> bool:
        """Whether the named top-level function reaches an act on every path."""
        if name in self._safe:
            return self._safe[name]
        if name in self._active:
            return False  # a cycle: assuming the answer is not an answer
        func = self._functions.get(name)
        if func is None:
            return False
        self._active.add(name)
        try:
            offenders, falls_off = _scan_suite(
                func.body, False, performs_act=self.performs_act
            )
            safe = not offenders and not falls_off
        finally:
            self._active.discard(name)
        self._safe[name] = safe
        return safe

    def called_helpers(self, stmt: ast.AST) -> tuple[str, ...]:
        """The same-module helpers ``stmt`` calls — named in a refusal's detail."""
        return tuple(sorted(_called_helpers(stmt, self._functions)))


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
    body: Sequence[ast.stmt],
    seen_act: bool,
    *,
    performs_act: Callable[[ast.stmt], bool] = _contains_act,
) -> tuple[list[ast.stmt], bool]:
    """Scan a statement suite for terminating paths that never reach an act.

    An *act* is a ``commit()`` or an ``abstain()`` — either terminates the
    episode, so every count below counts them alike.

    Returns ``(offenders, can_fall_off_without_act)``:

    * **``offenders``** — the ``return``/``raise`` statements reachable on some
      path through this suite without an act having been seen on that path.  A
      ``return question.commit(x)`` is not an offender: the act is performed *in*
      the terminating statement, so it is checked before the return is judged.
    * **``can_fall_off_without_act``** — whether control can reach the end of
      this suite (an implicit ``return None``) without an act having been seen.
      A suite that ends in a committing return cannot fall off.

    ``if``/``else`` is path-sensitive: both branches are scanned with the
    ``seen_act`` inherited from before the ``if``, and the ``if`` is act-safe
    afterwards only if it was already safe before or *both* branches are.
    ``for``/``while`` and ``try`` are scanned for offenders inside, but a loop
    does not guarantee its body ran, so it cannot make the post-loop path
    act-safe — the conservative answer for a barrier check.

    ``performs_act`` is the one seam between the two rules.  By default a
    statement acts when it writes the act itself, which is the rule for a module
    that declares no contract: its committing happens inline.  A
    question-contract :class:`_SelectCallGraph` hands in a follower instead,
    which also counts a statement that calls a same-module helper that acts on
    every one of its own paths.
    """
    offenders: list[ast.stmt] = []
    live = True  # statements after a terminating one are dead
    seen = seen_act
    for stmt in body:
        if not live:
            break
        if isinstance(stmt, (ast.Return, ast.Raise)):
            if not (seen or performs_act(stmt)):
                offenders.append(stmt)
            live = False  # nothing after a bare return/raise is reachable
        elif isinstance(stmt, ast.If):
            then_off, then_falls = _scan_suite(
                stmt.body, seen, performs_act=performs_act
            )
            else_off, else_falls = _scan_suite(
                stmt.orelse, seen, performs_act=performs_act
            )
            offenders.extend(then_off)
            offenders.extend(else_off)
            # The if can fall off without an act if either branch can — unless
            # an act was already seen before the if, in which case every path
            # through it is act-safe.
            falls = (then_falls or else_falls) if not seen else False
            if falls:
                seen = False  # a no-act path reaches the statements after
            else:
                seen = True  # both branches acted (or it acted before)
                live = False  # both branches terminate: what follows is dead code
        elif isinstance(stmt, (ast.For, ast.While)):
            loop_off, _ = _scan_suite(
                stmt.body, seen, performs_act=performs_act
            )
            orelse_off, _ = _scan_suite(
                stmt.orelse, seen, performs_act=performs_act
            )
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
            # post-loop path act-safe; ``seen`` is unchanged, and an unsafe
            # return inside is already noted above.
        elif isinstance(stmt, ast.Try):
            for sub in (stmt.body, stmt.orelse, stmt.finalbody):
                sub_off, _ = _scan_suite(sub, seen, performs_act=performs_act)
                offenders.extend(sub_off)
            for handler in stmt.handlers:
                handler_off, _ = _scan_suite(
                    handler.body, seen, performs_act=performs_act
                )
                offenders.extend(handler_off)
            # Conservatively, a try does not guarantee the post-try path acted.
        else:
            # An ordinary statement: an assignment, a probe, a loop step.  It
            # acts only if it contains a ``commit()``/``abstain()`` call — or,
            # under a question contract, calls a helper that does.
            if performs_act(stmt):
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
        law.screen_policy(source).require()`` and have features 230 and 231
        enforced there rather than remembered.  A refusal raises naming the
        policy, so the admission log and the retry prompt say the same thing.
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
    author repairs them all), and the rationale closes — citing the feature the
    refusal belongs to, 231's learned-component deferral or 230's barrier, so a
    reader of the log can follow the sentence back to the spec.  The gate returns
    these; it never raises.
    """
    listed = "; ".join(offenders)
    feature = "231" if reason is AdmissionReason.LEARNED_COMPONENT else "230"
    return PolicyAdmissionDecision(
        reason=reason,
        detail=(
            f"{reason.value}: {lead} — {listed}. {tail} (feature {feature})."
        ),
        offenders=tuple(offenders),
    )


def _question_contract_offenders(tree: ast.AST) -> list[str]:
    """The terminating paths of a question-contract ``select`` that reach no act.

    The strict rule, asked of the module as a whole because the contract is
    called through one entrypoint: ``select`` must exist at the module's top
    level, and every terminating path through it — a ``return``, a ``raise``, or
    falling off the end — must reach a ``commit()`` or ``abstain()`` on that
    path, or route through a same-module top-level function that itself reaches
    one on every one of its paths (followed transitively; a cycle does not
    satisfy).  This is what the module's own ``CONTRACT = "question"`` marker
    buys into, and it is why the helper loophole — ``select`` keeping ``.commit(``
    out of its own body and calling a one-line helper on one branch only — is
    refused here rather than waved through as a helper it does not judge.

    One offender per terminating statement, each naming its line, so the refusal
    points at the path to repair.  A module with no top-level ``select`` names
    that instead: there is no entrypoint whose reachability could be judged, and
    a marker promising an interface the module does not define is a refusal, not
    a silent pass.
    """
    functions = _module_functions(tree)
    graph = _SelectCallGraph(functions)
    select = functions.get("select")
    if select is None:
        promised = (
            "CONTRACT = 'question' promises a top-level select(question) "
            "entrypoint, and the module defines none"
        )
        return [promised]

    offenders: list[str] = []
    paths, falls_off = _scan_suite(
        select.body, seen_act=False, performs_act=graph.performs_act
    )
    for stmt in paths:
        kind = type(stmt).__name__.lower()
        helpers = graph.called_helpers(stmt)
        through = (
            f" (it calls {', '.join(helpers)}, which does not satisfy the "
            f"standard on every path)"
            if helpers
            else ""
        )
        offenders.append(
            f"select line {stmt.lineno}: a {kind} reachable with no commit() or "
            f"abstain() on its path{through}"
        )
    if falls_off:
        offenders.append(
            "select: can finish (fall off the end) without reaching commit() "
            "or abstain()"
        )
    return offenders


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
    4. **its commit is reachable on every terminating path** — a ``commit()`` or
       an ``abstain()`` (either terminates the episode; ``abstain()`` is the
       declared way to commit nothing) — each top-level function that contains
       one is walked, and a ``return``, a ``raise``, or falling off the end that
       is reachable without a preceding one is an offender, refused with
       :attr:`AdmissionReason.UNREACHABLE_COMMIT`.  A source with neither at all
       is refused the same way, because one of the two is mandatory.  A module
       that declares ``CONTRACT = "question"`` is judged more strictly, and from
       its one entrypoint: every terminating path of ``select`` must reach an
       act, or route through a same-module top-level function that does on every
       one of its own paths, followed transitively — see
       :func:`_question_contract_offenders`, and the module docstring's
       reachability paragraph for why the marker buys into it.
    5. **it reaches for no learned component** (feature 231) — a model-framework
       import, a checkpoint load, or an inference call is an offender, refused
       with :attr:`AdmissionReason.LEARNED_COMPONENT`; docs §11.2 defers the
       learned component until the M1 triage's AUC decides it, so a policy that
       builds one has run ahead of a decision the system has not made.  The
       detector is :func:`learned.find_learned_component`, and it runs **last**:
       a policy whose ``commit()`` is unreachable is broken whatever else it
       carries, while a policy that commits correctly is wrong only about what
       may exist, so the reachability is named first.

    Returns a :class:`PolicyAdmissionDecision` — admitted or refused, why, in
    what words, naming every offender — never raising.  The checks are a pure
    read of the source's AST: no I/O, no store, no campaign, so the gate is
    import-cheap and free of a hard dependency on the store, the same reason
    feature 229's :func:`plan_grid` defers nothing to module scope.

    The first refusal found wins, and the order is the order above: the most
    fundamental problem is named first, so the retrying agent repairs the
    policy's *shape* before its *premises*.  Feature 231's check is last because
    it is the one that is a deferral rather than a broken barrier — a policy
    that never reaches ``commit()`` is broken whatever else it carries.
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

    # (4) Commit/abstain reachability — every terminating path must reach one.
    #     A question-contract module is judged from its one entrypoint, with
    #     same-module helpers followed; every other module keeps the inline rule.
    commit_offenders: list[str] = []
    functions = _top_level_functions(tree)
    has_act_anywhere = any(_function_contains_act(fn) for fn in functions)
    if not has_act_anywhere:
        commit_offenders.append(
            "the source contains no commit() or abstain() call at all"
        )
    elif _question_contract_marker(tree):
        commit_offenders.extend(_question_contract_offenders(tree))
    else:
        for func in functions:
            if not _function_contains_act(func):
                continue  # a helper with no act: the acting happens elsewhere
            name = getattr(func, "name", "<policy>")
            offenders, falls_off = _scan_suite(func.body, seen_act=False)
            for off in offenders:
                commit_offenders.append(
                    f"{name} line {off.lineno}: a return/raise reachable with no "
                    f"commit() or abstain() on its path"
                )
            if falls_off:
                commit_offenders.append(
                    f"{name}: can finish (fall off the end) without reaching "
                    f"commit() or abstain()"
                )
    if commit_offenders:
        return _refusal(
            AdmissionReason.UNREACHABLE_COMMIT,
            tuple(commit_offenders),
            lead=(
                "a terminating path is reachable without a preceding commit() "
                "or abstain()"
            ),
            tail=(
                "commit() is mandatory — a policy that terminates without "
                "committing scores -inf — and abstain() is the declared way to "
                "commit nothing, so a path that can end with neither is a policy "
                "that can score on a pick it never made and never said it would "
                "not make; commit() or abstain() on every terminating path"
            ),
        )

    # (5) Learned components — a framework import, a checkpoint load, or a call
    # to inference (feature 231).  Last, because it is the one refusal that is a
    # deferral rather than a broken barrier: a policy with no reachable commit()
    # is broken whatever else it carries, while a policy that commits correctly
    # is wrong only about what may exist yet (docs §11.2).
    learned_offenders = find_learned_component(tree)
    if learned_offenders:
        return _refusal(
            AdmissionReason.LEARNED_COMPONENT,
            learned_offenders,
            lead=(
                "the policy reaches for a learned component — it imports a model "
                "framework, loads a checkpoint, or calls inference, and none of "
                "those are available to a policy"
            ),
            tail=(
                "The learned component is deferred until the M1 triage measures "
                "the perturbation-stability AUC (docs §11.2) — the policy writes "
                "thresholds and dreaming revises them, and that stays true until "
                "the measurement decides otherwise — while inference in the "
                "replay path is forbidden outright (docs §12). A policy is "
                "written against question.* and the thresholds dreaming revises "
                "it to; it is not written against a model"
            ),
        )

    return PolicyAdmissionDecision(
        reason=AdmissionReason.CLEAN,
        detail=(
            f"{AdmissionReason.CLEAN.value}: the policy's source carries no "
            f"absolute score constant, no hardcoded node id, no terminating "
            f"path that fails to reach commit() or abstain(), and no learned "
            f"component — "
            f"every check in features 230 and 231 is satisfied and the policy is "
            f"admitted (features 230, 231)."
        ),
        source=source,
    )
