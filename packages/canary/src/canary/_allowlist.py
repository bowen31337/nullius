"""No wall clock in searched code — the import allowlist.

app_spec.xml feature 139 (this category's, in "Determinism Guarantees &
Nightly Canary", depending on feature 135): *"System rejects a
searched-code import of time, datetime.now or unseeded random through
the import allowlist."* It is §12's determinism table row — "No wall
clock in searched code | ``time``, ``datetime.now``, ``random`` without
seed blocked by the import allowlist" — and the row the prerequisites
state from the pipeline side: no wall-clock reads in searched code,
because a score that depends on when it was computed is a score no
frozen pair can reproduce. The searched code is the code the loop
dreams up — the candidate signals submitted as source — and this module
is the seam those submissions are screened at before they ever run.

Where features 135 and 140 parse declarations a deployment already
wrote, and feature 146 refuses a call at runtime, this one refuses a
*submission at admission*: source text the search produced, checked
statically before it is executed anywhere. Four decisions carry the
feature, and each is a reading of one word in it.

**The word is *allowlist*, and an allowlist is a ceiling — §12 is the
floor no ceiling can lift.** A deployment configures which modules
searched code may import (an evaluator image admitting its numeric
stack, a sparser one admitting the stdlib working set), and that
ceiling is this module's configuration — resolved from
:data:`IMPORT_ALLOWLIST_ENV`, defaulted to
:data:`DEFAULT_IMPORT_ALLOWLIST`, carried by the composed service at
``service.allowlist``. But the three entrances the row names are
refused *under every configuration*: an allowlist that admits ``time``
is itself refused, at construction, naming every offending entry —
because the allowlist is the mechanism §12's row blocks these terms
"through", and a mechanism whose configuration could switch the
contract off would not be the mechanism the row names. So the floor
(:data:`WALL_CLOCK_MODULES`, :data:`CLOCK_CONSTRUCTORS`, the unseeded
``random`` spellings) is applied twice, in the one predicate
:func:`_floor_refusal` both applications share: once when a deployment
declares an allowlist, and once over every import and call the searched
code actually makes. A wider ceiling can only ever admit more
deterministic modules; it can never admit the clock.

**The word is *import*, and the refusal is over the three shapes an
import can put the clock behind.** Not a dataflow analysis and not a
runtime interception — the terms the row itself names, read off the
submission's syntax tree:

* the ``time`` module, refused at the import in every form — ``import
  time``, ``from time import time``, ``from time import monotonic`` —
  because every spelling of that module *is* the clock, and a
  ``time.sleep`` or a ``time.time`` behind an alias is the same read;
* the ``datetime`` clock constructors — ``now``, ``utcnow`` and
  ``today``, reached through any binding the imports created (``import
  datetime`` then ``datetime.datetime.now()``, ``from datetime import
  datetime as dt`` then ``dt.now()``, ``from datetime import date``
  then ``date.today()``) — while the ``datetime`` module itself stays
  importable, because a datetime built from explicit arguments is a
  value like any other and refusing the module would refuse
  deterministic date arithmetic;
* the module-level ``random`` RNG — ``random.random()``,
  ``random.uniform(...)``, and ``random.seed(...)`` too, because
  reseeding the global stream is still drawing from it — while the
  *seeded* spelling, ``random.Random(seed)``, is the one §12's own next
  row sanctions ("Seeded RNG | ``seed`` passed into ``signal()``;
  stored on the node"). A :class:`random.SystemRandom` is refused with
  the rest: it ignores seeds by construction, which is the property the
  refusal exists to keep out, not one it can excuse.

The call check resolves each call to a dotted term through the names
the submission's own imports bound (:func:`_resolve_term`), so an alias
cannot launder the clock — ``from datetime import datetime as clock``
still resolves ``clock.now()`` to ``datetime.datetime.now`` — and a
call on a value the imports did not bind (a parameter, a local
instance, ``random.Random(seed).uniform(...)``) is not this module's
to judge: the seed reached it, which is the sanctioned spelling. The
dynamic spellings — ``importlib.import_module("time")``, ``__import__``
— are deliberately not chased here: runtime import enforcement is the
sandbox member's seam (app_spec.xml features 630 and 819, "any import
outside the configured allowlist"), and restating it would be a second
provenance for a mechanism that already has one. This module is the
determinism *floor* of that same allowlist — the part that must hold
even where the sandbox is not deployed.

**The refusal is complete and it lands before the code runs.** One
:class:`~canary.CanaryImportError` names every offender — every refused
import and every refused call, each with its line and the reason the
term is refused — because a screen that reported only the first would
be resubmitted to learn the rest, and the author of searched code (the
loop, or the operator debugging it) reads the whole refusal in one
message. And the screen refuses what it cannot read: source that is
not a string, or does not parse, is refused rather than waved through,
because a screen that silently passed unparseable text would be the
vacuous green the nightly canary must never allow — checked nothing,
reported clean. A submission with *no* imports is a different case and
passes: the screen checked the whole tree and the code reaches for
nothing, which is clean, not vacuous.

**The verdict is a value; the refusal is the feature.** On clean
searched code :func:`screen_imports` returns a
:class:`SearchedImports` — the imports it found with their lines, and
the ``datetime``/``random`` calls it resolved and cleared — so a
nightly report or an admission record can file *what the code reaches
for and that it was clean* rather than merely that it did not raise.
The refusal, when the code reaches for the clock, is raised rather
than returned — a submission that reads the wall clock is stopped at
admission, before it can score, because the score it would produce is
unfrozen by construction and the repair is to fix the code, not to
record its output.

What this module deliberately does **not** do is execute, intercept,
or persist. It never runs the submission (the evaluation path's job,
inside the container feature 135 pins); it hooks nothing at runtime
(feature 146's guard is the runtime seam this package carries, and the
sandbox owns dynamic imports); it writes no table — the refusal is the
event, raised where the submission arrives, and the clean-path evidence
is the verdict value the caller may keep. Stdlib only — ``ast``, ``re``
and a dataclass — with no polars, no pyarrow, no lake and no
environment read at import, for the reason the whole category states:
this package is imported on every factory scan and on the replay path
§1 keeps free of moving parts, and the screen must not be the member
that made either expensive.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Optional

from ._errors import CanaryImportError

__all__ = [
    "ALLOWED",
    "CLOCK_CONSTRUCTORS",
    "DEFAULT_IMPORT_ALLOWLIST",
    "IMPORT_ALLOWLIST_ENV",
    "REFUSED",
    "SEEDED_RANDOM_CONSTRUCTORS",
    "WALL_CLOCK_MODULES",
    "ImportAllowlist",
    "SearchedImports",
    "allowlist_from_env",
    "classify_import",
    "screen_imports",
]

#: The classification of a term the floor does not refuse. The ceiling —
#: allowlist membership — is a separate question :func:`classify_import`
#: does not answer; this constant names only the floor's verdict.
ALLOWED = "allowed"

#: The classification of a term the determinism floor refuses, whatever
#: the allowlist says. The pair :data:`ALLOWED`/:data:`REFUSED` mirrors
#: the device sweep's CPU/GPU pair: two values, one per verdict, so the
#: classifier's callers cannot invent a third.
REFUSED = "refused"

#: The modules refused at the import in every form — §12's row names
#: ``time`` as a bare module, and every attribute of it is a spelling of
#: the same clock, so the root alone decides. A module joined to this set
#: later is refused by the same three rules, with no other change.
WALL_CLOCK_MODULES = frozenset({"time"})

#: The ``datetime`` constructors that read the clock — the spellings
#: §12's row collects under ``datetime.now``. ``utcnow`` is the same
#: read under the deprecated UTC spelling; ``today`` is the same read on
#: the ``date`` class. Refused wherever a call resolves onto them; the
#: ``datetime`` module itself stays importable, because a datetime built
#: from explicit arguments is a value, not a clock read.
CLOCK_CONSTRUCTORS = frozenset({"now", "utcnow", "today"})

#: The ``random`` constructors that carry a seed — the one sanctioned
#: spelling of randomness in searched code, §12's own next row ("Seeded
#: RNG | ``seed`` passed into ``signal()``; stored on the node").
#: ``SystemRandom`` is deliberately absent: it ignores its seed by
#: construction, which is the non-determinism this floor refuses, not a
#: spelling of its repair.
SEEDED_RANDOM_CONSTRUCTORS = frozenset({"Random"})

#: The module roots whose *calls* the screen resolves and judges, beside
#: the imports it always judges: the two families the floor governs
#: below the module level — the datetime clock constructors and the
#: module-level random stream. A call on any other import (``math.sqrt``)
#: is the allowlist ceiling's business at import time only.
_GOVERNED_CALL_ROOTS = frozenset({"datetime", "random"})

#: A well-formed import term: dotted Python identifiers, anchored at both
#: ends so a leading relative dot, a trailing dot or an empty segment is
#: refused rather than silently matched, and a star import (``random.*``)
#: is refused too — a term that binds everything at once is the one term
#: no allowlist can judge.
_TERM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

#: The environment variable naming the searched-code import allowlist —
#: the deployment's ceiling, comma-separated dotted module terms. Unset
#: means :data:`DEFAULT_IMPORT_ALLOWLIST`; set and blank means the
#: strictest ceiling (nothing allowed); set to a term the floor refuses
#: is a refusal naming this variable, because an allowlist is how the
#: contract is enforced, not a way around it.
IMPORT_ALLOWLIST_ENV = "NULLIUS_SEARCHED_IMPORTS"

#: The default allowlist: the deterministic stdlib working set a signal
#: plausibly needs. ``time`` is absent by construction; ``datetime`` is
#: present because a datetime built from arguments is a value; ``random``
#: is present because the seeded spelling needs the module. A deployment
#: widens or narrows this through :data:`IMPORT_ALLOWLIST_ENV` — never
#: past the floor, which this constant satisfies by construction and a
#: configured value is checked against at resolution.
DEFAULT_IMPORT_ALLOWLIST_TERMS: tuple[str, ...] = (
    "math",
    "decimal",
    "fractions",
    "statistics",
    "itertools",
    "functools",
    "datetime",
    "random",
)


def _floor_refusal(term: str) -> Optional[str]:
    """The determinism floor's reason a term is refused, or ``None``.

    The one predicate every application of the floor shares — the
    allowlist's own construction, the import check and the call check —
    so the three can never disagree about what the contract refuses.
    Each reason states the repair, because the reader of the refusal is
    the author of the searched code (the loop, or the operator debugging
    it), and §12's row is enforceable only if its refusal is actionable.
    """
    parts = term.split(".")
    root = parts[0]
    leaf = parts[-1]
    if root in WALL_CLOCK_MODULES:
        return (
            f"{term!r} is the wall clock (architecture §12, 'No wall "
            "clock in searched code'): every spelling of the time module "
            "reads an instant the replay cannot reproduce, so two runs of "
            "one seeded signal can score against different 'now's and "
            "diverge — read time as an argument the caller passes in"
        )
    if root == "datetime" and len(parts) >= 2 and leaf in CLOCK_CONSTRUCTORS:
        return (
            f"{term!r} reads the wall clock (architecture §12): a datetime "
            "constructed from the clock is a different value on every run, "
            "and the replay would faithfully compare a number nothing "
            "froze — construct datetimes from explicit arguments, or read "
            "them from the data"
        )
    if root == "random" and len(parts) >= 2 and leaf not in SEEDED_RANDOM_CONSTRUCTORS:
        return (
            f"{term!r} draws from the module-level random stream, which no "
            "seed the search recorded ever seeded (architecture §12, "
            "'Seeded RNG | seed passed into signal(); stored on the node'): "
            "draw randomness through random.Random(seed) with the seed "
            "passed in, so the draw is a function of the frozen seed"
        )
    return None


def classify_import(term: object) -> str:
    """The determinism floor's verdict on an import term — refused or not.

    The one place a term is read, so the refusal path and the recording
    path cannot disagree about what a term classifies as (the role
    :func:`~canary.classify_device` plays for the device sweep). A term
    is a dotted Python name as an import statement spells it — ``time``,
    ``datetime.datetime``, ``random.Random`` — classified as
    :data:`REFUSED` when the floor refuses it (:data:`WALL_CLOCK_MODULES`
    roots, ``datetime`` clock constructors, unseeded ``random``
    spellings) and :data:`ALLOWED` otherwise. A value that is not a
    well-formed dotted name is refused with a reason rather than
    classified: a relative import (``.sibling``), a star import
    (``random.*``) or a malformed term names no module an allowlist can
    judge, and passing it would be the vacuous green the canary must
    never allow. This function answers the *floor* only — whether the
    allowlist's ceiling also admits the term is
    :meth:`ImportAllowlist.covers`, a separate question with a separate
    owner.
    """
    if not isinstance(term, str) or not _TERM_RE.match(term):
        raise CanaryImportError(
            f"a searched-code import term must be a dotted Python name, "
            f"got {term!r}: a term that is not one — a relative import, a "
            "star import, a malformed spelling — names no module an "
            "allowlist can judge, and a screen that passed it would be "
            "reporting clean over a term it never checked"
        )
    return REFUSED if _floor_refusal(term) is not None else ALLOWED


def _resolve_term(node: ast.expr, provenance: dict[str, str]) -> Optional[str]:
    """The dotted term a call's callee reaches for, or ``None``.

    Walks the attribute chain down to a name and joins the attributes to
    the term that name was bound from — so ``dt.now()`` resolves to
    ``datetime.datetime.now`` when ``dt`` was bound by
    ``from datetime import datetime as dt``, and an alias cannot launder
    the clock. ``None`` when the chain does not land on an import-bound
    name: a parameter, a local, or a call's own result (the seeded
    ``random.Random(seed).uniform(...)`` spelling) reaches outside what
    the imports declared, and the floor does not guess at it — the seed
    reached the value, which is the sanctioned shape.
    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    base = provenance.get(current.id)
    if base is None:
        return None
    return ".".join([base, *reversed(parts)])


def _iter_imports(
    tree: ast.AST,
) -> Iterator[tuple[int, str, str]]:
    """Every import the tree makes, as ``(line, term, binding)``.

    ``import a.b.c`` yields the term ``a.b.c`` bound to the name ``a``
    (the package root is what a plain ``import`` binds); ``from a.b
    import c as d`` yields ``a.b.c`` bound to ``d``; a relative import
    yields its dotted spelling (``.mod.x``), which
    :func:`classify_import` refuses as a term no allowlist can judge —
    searched code is one submitted module, not a package with siblings
    the search froze. Alias bindings are recorded so the call check can
    resolve through them.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = alias.asname or alias.name.split(".")[0]
                yield node.lineno, alias.name, binding
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            for alias in node.names:
                term = f"{base}.{alias.name}" if base else alias.name
                binding = alias.asname or alias.name
                yield node.lineno, term, binding


@dataclass(frozen=True)
class ImportAllowlist:
    """The searched-code import allowlist — the ceiling, floor-checked.

    Feature 139's mechanism as a value: the dotted module terms searched
    code may import, sorted and deduplicated. Construction validates
    every term against the determinism floor and refuses — naming every
    offender at once — an allowlist that admits one, because the
    allowlist is how §12's row is enforced and a configuration that
    could lift the contract would not be an enforcement of it. The
    floor is the same predicate the screen applies to submissions, so a
    term can never be simultaneously refused in code and allowed by
    configuration, or the reverse.

    Coverage is by prefix: an entry ``math`` admits ``math`` and
    ``math.sqrt``; an entry ``datetime.datetime`` admits exactly the
    datetime class and its (floor-checked) attributes. The ceiling
    admits modules and names; which *attributes* of them are poison is
    the floor's question, and it stays answered in exactly one place.
    """

    #: The allowed terms, sorted and deduplicated. May be empty — the
    #: strictest ceiling, refusing every import — which is a valid
    #: deployment stance, never a vacuous one.
    terms: tuple[str, ...]

    def __post_init__(self) -> None:
        # The floor is checked here so it cannot be skipped by whichever
        # spelling built the value — the default constant, the
        # environment read or a caller's explicit construction all pass
        # through this one validation, and an allowlist that admitted
        # the clock would be the contract's off-switch wearing its name.
        if isinstance(self.terms, str) or not isinstance(self.terms, Iterable):
            raise CanaryImportError(
                "an import allowlist must be a sequence of dotted module "
                f"terms, got {type(self.terms).__name__}; a single string "
                "would be one term iterated letter by letter, which admits "
                "nothing and refuses nothing legibly"
            )
        checked: list[str] = []
        refusals: list[str] = []
        for term in self.terms:
            if not isinstance(term, str) or not _TERM_RE.match(term):
                raise CanaryImportError(
                    f"an import allowlist entry must be a dotted Python "
                    f"name, got {term!r}: an entry that is not one names no "
                    "module, so the allowlist could not say whether searched "
                    "code had stayed inside it"
                )
            reason = _floor_refusal(term)
            if reason is not None:
                refusals.append(
                    f"{term}: {reason}; an allowlist is how this contract is "
                    "enforced, not a way around it — refuse the entry"
                )
                continue
            checked.append(term)
        if refusals:
            raise CanaryImportError(
                "the import allowlist admits terms the determinism contract "
                f"refuses — {len(refusals)} of {len(refusals) + len(checked)} "
                "entries refused:\n  " + "\n  ".join(refusals)
            )
        object.__setattr__(self, "terms", tuple(sorted(set(checked))))

    # -- The ceiling --------------------------------------------------------

    def covers(self, term: str) -> bool:
        """Whether the allowlist admits an import term.

        Prefix coverage: an entry admits the term itself and everything
        under it. The floor is *not* consulted here — a covered term can
        still be floor-refused, and the screen applies both, in the one
        place that can name which one spoke.
        """
        return any(
            term == entry or term.startswith(entry + ".") for entry in self.terms
        )

    def __contains__(self, term: object) -> bool:
        # The duck-checkable spelling of `covers` — "is this import
        # allowed?" is the question a caller holding the allowlist asks.
        return isinstance(term, str) and self.covers(term)

    def __iter__(self) -> Iterator[str]:
        return iter(self.terms)

    def __len__(self) -> int:
        return len(self.terms)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ImportAllowlist(terms={self.terms!r})"

    # -- The screen ----------------------------------------------------------

    def screen(self, source: str) -> "SearchedImports":
        """Screen searched code against this allowlist — the verb.

        The composed spelling of :func:`screen_imports`, so a caller
        holding the allowlist the service resolved screens a submission
        with the same ceiling and the same floor as one importing the
        member: one provenance, two spellings, no third behaviour.
        """
        return screen_imports(source, self)


#: The default allowlist — see :data:`DEFAULT_IMPORT_ALLOWLIST_TERMS`.
#: Built at import through the same validation a configured value passes
#: through, so a default that ever drifted past the floor would fail the
#: member's import loudly rather than first failing a submission quietly.
DEFAULT_IMPORT_ALLOWLIST = ImportAllowlist(DEFAULT_IMPORT_ALLOWLIST_TERMS)


@dataclass(frozen=True)
class SearchedImports:
    """Searched code, screened and clean — the verdict as a value.

    Feature 139's passing case: what the code reaches for (every import
    term, with its line) and what the screen cleared below the module
    level (the ``datetime`` and ``random`` calls it resolved, with their
    lines). Frozen and ordered, so an admission record or a nightly
    report can file one verdict per submission and compare them. A
    :class:`SearchedImports` only ever exists when the whole submission
    passed — a refusal is raised before this value is built — so it is
    the audit that no clock was reached for, not a bare "did not
    raise". No ``__len__`` is defined deliberately: a clean screen of
    import-free code is a completed check, and ``bool()`` falling back
    to a length would read it as failure.
    """

    #: Every import found, as ``(line, term)``, sorted by line then term.
    imports: tuple[tuple[int, str], ...]

    #: The governed-family calls resolved and cleared, as
    #: ``(line, term)`` — the datetime constructions and seeded random
    #: draws the screen checked below the module level.
    calls: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        # A verdict is a statement about code a screen actually read, so
        # each entry is validated before the value exists — the same
        # stance DevicePaths takes for the paths it records.
        imports = tuple(self.imports)
        calls = tuple(self.calls)
        for label, entries in (("imports", imports), ("calls", calls)):
            for entry in entries:
                if (
                    not isinstance(entry, tuple)
                    or len(entry) != 2
                    or not isinstance(entry[0], int)
                    or isinstance(entry[0], bool)
                    or entry[0] < 1
                    or not isinstance(entry[1], str)
                    or not entry[1].strip()
                ):
                    raise CanaryImportError(
                        f"a searched-code verdict records {label} as "
                        f"(line, term) pairs; {entry!r} is not one: a line "
                        "is a positive integer and a term a dotted name, so "
                        "a record that cannot say where and what was "
                        "checked cannot be filed against a submission"
                    )
        object.__setattr__(self, "imports", tuple(sorted(imports)))
        object.__setattr__(self, "calls", tuple(sorted(calls)))

    @property
    def terms(self) -> tuple[str, ...]:
        """The import terms found, unique, in order of first appearance."""
        seen: dict[str, None] = {}
        for _, term in self.imports:
            seen.setdefault(term, None)
        return tuple(seen)

    @property
    def modules(self) -> tuple[str, ...]:
        """The module roots the code reaches for, sorted and unique."""
        return tuple(sorted({term.split(".")[0] for _, term in self.imports}))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"SearchedImports(imports={self.imports!r}, calls={self.calls!r})"
        )


def screen_imports(
    source: object,
    allowlist: Optional[ImportAllowlist] = None,
) -> SearchedImports:
    """Screen searched code — refuse the clock, admit the rest.

    The feature's verb. Parses the submission, judges every import
    against the floor and the ceiling, resolves every import-bound call
    to a term and judges the governed families, and either raises one
    collective :class:`~canary.CanaryImportError` naming every offender
    with its line and reason — or returns the
    :class:`SearchedImports` the clean submission earned. The
    allowlist defaults to :data:`DEFAULT_IMPORT_ALLOWLIST`; a caller
    holding a deployment's ceiling hands it in (the composed service's
    ``allowlist.screen(source)`` is the same call through the resolved
    value). Source that is not a string, or does not parse, is refused:
    a screen that passed what it could not read would be reporting
    clean over code it never checked.
    """
    if not isinstance(source, str) or not source.strip():
        described = type(source).__name__ if not isinstance(source, str) else "blank source"
        raise CanaryImportError(
            f"searched code must be a non-empty string of Python source, "
            f"got {described!r}: the screen cannot admit what it cannot "
            "read, and passing it would be the vacuous green the nightly "
            "canary must never allow"
        )
    try:
        tree = ast.parse(source)
    except SyntaxError as broken:
        raise CanaryImportError(
            f"searched code does not parse — line {broken.lineno}: "
            f"{broken.msg}: the screen cannot judge the imports of source "
            "it cannot read, and a submission that does not parse is "
            "refused rather than waved through"
        ) from broken
    ceiling = DEFAULT_IMPORT_ALLOWLIST if allowlist is None else allowlist
    if not isinstance(ceiling, ImportAllowlist):
        raise CanaryImportError(
            "the import allowlist to screen against must be an "
            f"ImportAllowlist, got {type(ceiling).__name__}; the ceiling is "
            "a validated value, not a loose sequence a screen would have to "
            "re-validate mid-refusal"
        )
    provenance: dict[str, str] = {}
    failures: list[str] = []
    imports: list[tuple[int, str]] = []
    for lineno, term, binding in _iter_imports(tree):
        try:
            classification = classify_import(term)
        except CanaryImportError as refusal:
            failures.append(f"line {lineno}: {refusal}")
            continue
        if classification == REFUSED:
            # `_floor_refusal` re-derived rather than cached: the term
            # just passed the classifier, so the reason exists and the
            # one predicate stays the single provenance of both.
            failures.append(f"line {lineno}: {_floor_refusal(term)}")
            continue
        if not ceiling.covers(term):
            failures.append(
                f"line {lineno}: {term!r} is outside the import allowlist "
                f"({', '.join(ceiling.terms) or 'nothing allowed'}): "
                "searched code imports only what the deployment admitted, "
                "and a module the allowlist never named is one the "
                "determinism contract was never checked against"
            )
            continue
        provenance[binding] = term
        imports.append((lineno, term))
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        term = _resolve_term(node.func, provenance)
        if term is None or term.split(".")[0] not in _GOVERNED_CALL_ROOTS:
            continue
        reason = _floor_refusal(term)
        if reason is not None:
            failures.append(f"line {node.lineno}: {reason}")
            continue
        calls.append((node.lineno, term))
    if failures:
        raise CanaryImportError(
            "searched code reaches for what the import allowlist refuses — "
            f"{len(failures)} of {len(failures) + len(imports) + len(calls)} "
            "imports and calls refused:\n  "
            + "\n  ".join(failures)
            + "\nSearched code reads the clock through its arguments and "
            "draws randomness through a seeded random.Random — pass the "
            "seed in (architecture §12)"
        )
    return SearchedImports(tuple(imports), tuple(calls))


def allowlist_from_env(env: Optional[Mapping[str, str]] = None) -> ImportAllowlist:
    """Resolve the searched-code import allowlist from an environment.

    Reads :data:`IMPORT_ALLOWLIST_ENV` out of ``env`` — the same mapping
    seam the pin and device sweeps resolve through, so a test or an
    operator can hand the resolution an environment without touching
    the process — or the process environment when ``env`` is ``None``.
    An unset variable is the default allowlist (the deterministic
    stdlib working set), not a refusal: a deployment that declared
    nothing still has a ceiling, exactly as a deployment that declared
    no device still runs on the CPU. A variable that is set and blank
    is the strictest ceiling — nothing allowed — which is a stance, not
    a gap. A variable whose terms the floor refuses is a refusal naming
    the variable and every offending term, because configuring the
    contract away is the one reading this resolution exists to prevent.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    raw = source.get(IMPORT_ALLOWLIST_ENV)
    if raw is None:
        return DEFAULT_IMPORT_ALLOWLIST
    if not isinstance(raw, str):
        raise CanaryImportError(
            f"{IMPORT_ALLOWLIST_ENV} (the searched-code import allowlist) "
            f"must be a comma-separated string of dotted module terms, got "
            f"{raw!r}: an allowlist the screen cannot parse is a ceiling "
            "no submission can be judged under"
        )
    terms = [piece.strip() for piece in raw.split(",")]
    terms = [term for term in terms if term]
    try:
        return ImportAllowlist(tuple(terms))
    except CanaryImportError as refusal:
        raise CanaryImportError(
            f"{IMPORT_ALLOWLIST_ENV} (the searched-code import allowlist): "
            f"{refusal}"
        ) from refusal
