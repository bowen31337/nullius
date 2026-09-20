"""Feature 167's law: a submitted module importing outside the allowlist is refused.

app_spec.xml, "Untrusted Code Sandbox", feature 167: *System rejects a
submitted module importing anything outside the configured allowlist, which
returns a disallowed_import error message.*  docs/nullius-tech-architecture.md
§5.2 supplies the posture this law serves — *"LLM-authored code is untrusted
code. Treat it that way."* — and three later sections name the control
itself: §10.2 ("any import outside an allowlist"), §11.1 ("no imports
outside the allowlist", among the static checks *before any policy is
admitted*), and §12's determinism row ("``time``, ``datetime.now``,
``random`` without seed blocked by the import allowlist").  Where feature
157 refused a *run* whose box was not gVisor's, this law refuses the
*module a run would execute*, and it refuses it earlier: statically, at the
moment the module is offered to the box (§5.2's ``code=node.code``), before
anything executes.  The sentence decomposes into four claims, each owned
here as a seam rather than a comment:

* **a submitted module** — the subject, and the reason the law has two
  audiences with two shapes.  The submission is *untrusted* source text,
  offered by the pipeline §6.1 runs unattended over thousands of
  candidates, so the screen *answers* it with a
  :class:`ModuleDecision` — the same shape-reasoning feature 157's gate
  applies to runs, and a screen that raised per module would turn one bad
  candidate into a crashed evaluator.  The *allowlist* it is screened
  against is written by trusted code (an operator, a deployment manifest,
  a CI check recompiling the committed artifact), so a document that
  cannot be read is refused with an exception the caller cannot ignore
  (:class:`~sandbox.errors.AllowlistDocumentError`) — the split §5.2's own
  two moments dictate, with the audiences 157 holds apart arriving here in
  the same order: compile the trusted configuration, answer the untrusted
  subject.

* **importing anything** — totality, and it is the word that decides the
  reading.  Every import *statement* the source contains, in every shape
  it can be written — ``import os``, ``import os.path as p`` (the alias
  does not launder the term), ``from math import sqrt``,
  ``from decimal import Decimal as D`` — and wherever it sits: module
  level, nested in a function, guarded by a condition.  An import that
  executes on *some* path is an import, and a screen that read only the
  top of the file would be reporting clean over the half it never
  checked.  Two spellings are outside the ceiling *by construction*: a
  relative import (``from . import sibling``) names a package the box does
  not hold — a submitted module is one module, not a package with
  siblings — and the allowlist's terms are absolute dotted names, so no
  configuration can ever vouch for one; and a star import's term carries
  the star, which no well-formed entry covers.

* **the configured allowlist** — a ceiling, held as a committed document.
  :data:`COMMITTED_IMPORTS_ALLOWLIST` ships beside the law that checks it,
  the same posture feature 157's :data:`~sandbox.isolation.COMMITTED_ISOLATION_POLICY`
  and feature 149's committed egress policy take: the deployment's
  configuration is a file in the repository, compiled through
  :func:`compile_imports_allowlist` under the same refusal as any change
  to it — never a constant in the code, because a ceiling the code held
  could not be widened or narrowed by the deployment that owns it.
  Coverage is by *prefix*: an entry admits the term itself and everything
  under it (``polars`` admits ``polars.DataFrame`` and ``polars.lazyframe``),
  and never its parent — importing a parent executes the parent, so
  ``numpy`` is not admitted by an entry that names only ``numpy.linalg``.
  A document that lists no terms is *legal*: an empty allowlist is the
  strictest ceiling there is, refusing every submission that imports
  anything — the deliberate contrast with feature 157's compile, which
  refuses a policy that names no components, because a membership law
  that vouches for nothing has no subject while a ceiling that admits
  nothing is the strongest version of itself.

* **which returns a disallowed_import error message** — the answer's own
  words, and the reason they are returned rather than raised.  The
  feature's sentence does not say the rejection *raises*; it says it
  *returns a message*, so the decision's :attr:`ModuleDecision.detail` —
  beginning with the greppable code :data:`DISALLOWED_IMPORT_CODE`
  (``disallowed_import``), the feature's own subject written as a token,
  the discipline :data:`~sandbox.isolation.ISOLATION_REQUIRED_CODE`
  applies to feature 157's — *is* the error message the sentence names,
  and :meth:`ModuleDecision.require` is the bridge that turns it into
  :class:`~sandbox.errors.DisallowedImportError` for a caller on the last
  line before it would have executed the module.  The message names every
  offending term with its line, never only the first: the reader of the
  refusal is the author of the submission, and a screen that reported one
  offender at a time would be resubmitted to learn the rest.

**One allowlist, not one per box.**  The sentence says "the configured
allowlist"; §10.2 and §11.1 both say "the allowlist", singular; and the
committed artifact is one ceiling every box
:data:`~sandbox.isolation.COMMITTED_ISOLATION_POLICY` covers submits
against.  The two Z1 boxes execute different code (a signal in the signal
sandbox, a policy module in the policy runtime) but the *control* this
feature adds is the same control on the same box, and splitting it per
component would be a second membership law this sentence never asked for.

**The committed default and §12's row.**  The artifact lists the
deterministic stdlib working set (the same six arithmetic modules feature
139's committed default carries), ``datetime`` and ``random`` — both
present because the deterministic spellings need the modules: a datetime
built from explicit arguments is a value, and the seeded RNG §12's next
row sanctions is ``random.Random(seed)`` — the structure modules, the
``__future__`` compiler directive, and the payload stack (``polars``,
``numpy``, ``pyarrow``, §5.1's polars-native contract and §5.2's Arrow IPC
channel).  ``time`` is absent because it has no sanctioned spelling: every
use of it is a wall-clock read.  The *call-level* floor §12's row also
names (``datetime.now``, unseeded draws) is feature 139's law at the
search seam — this member screens the sandbox seam, the two moments one
submission passes through, and this member deliberately holds no copy of
that floor: the sandbox is the box untrusted code is put inside, so its
own law depends on nothing another member could be handed, the same
reason :mod:`sandbox.errors` shares no hierarchy with the canary's.

**Honest limits.**  This module reads import *statements*; it is not a
dataflow analysis and not a runtime interception.  A submission that
reaches a module by spelling it dynamically — ``__import__("os")``,
:mod:`importlib`, a string handed to ``exec`` — evades this screen, and
the screen is honest about that: it is the *admission* check, the first
layer, and the enforcement behind it is the box itself — feature 157's
gVisor underneath, 158's network namespace, 159's mountless filesystem,
160's seccomp — exactly as feature 157's law is the policy-time half of a
runtime a production runner provides.  What holds is that the committed
document cannot drift to a wider ceiling without the compile noticing a
term it cannot read, that the screen's answer is *computed* from the
compiled allowlist rather than hardcoded to "yes", and that *which* terms
a deployment admits is a value the compiled allowlist carries and a
caller can read (:meth:`ImportsAllowlist.terms`) — so "these are the
modules sandboxed code may import" is a fact about the deployment rather
than a line in a runbook.

Stdlib-only, like the rest of the member: ``ast`` to read the
submission's imports, ``json`` to read the committed document, and no
process, network or container runtime anywhere.  The module is the law
and the committed artifact is what an operator applies.
"""

from __future__ import annotations

import ast
import enum
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from .errors import (
    AllowlistDocumentError,
    DisallowedImportError,
)

__all__ = [
    "COMMITTED_IMPORTS_ALLOWLIST",
    "DISALLOWED_IMPORT_CODE",
    "IMPORTS_COMPONENT_NAME",
    "IMPORTS_POLICY_KIND",
    "ImportsAllowlist",
    "ModuleDecision",
    "ModuleReason",
    "SandboxImports",
    "committed_imports_allowlist",
    "compile_imports_allowlist",
    "load_imports_allowlist",
    "sandbox_imports",
    "screen_module",
]

#: The marker a document declares itself with — the same discipline feature
#: 157's committed isolation policy and feature 149's committed egress
#: artifact take, so a stray JSON file carrying an ``allow`` key cannot be
#: read as this configuration.
IMPORTS_POLICY_KIND: Final[str] = "sandbox-imports"

#: The committed artifact, shipped beside the law that checks it, so a
#: checkout cannot hold one without the other.
COMMITTED_IMPORTS_ALLOWLIST: Final[Path] = Path(__file__).with_name(
    "imports_allowlist.json"
)

#: The greppable code every import refusal carries — feature 167's own
#: subject written as a token, the feature's sentence naming it in so many
#: words ("which returns a disallowed_import error message").  An operator
#: grepping a log for the rejection finds it by the feature's own words,
#: whichever tense the refusal arrived in.
DISALLOWED_IMPORT_CODE: Final[str] = "disallowed_import"

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, not instead of it: the factory's registry is keyed by name
#: and a later registration of the same name replaces the earlier one, so
#: the category's later features each take their own seat on the member
#: (the tripwires' and the canary's established shape) rather than
#: overwriting the isolation law's.
IMPORTS_COMPONENT_NAME: Final[str] = "sandbox-imports"

#: A well-formed allowlist term: dotted Python identifiers, anchored at both
#: ends so a leading relative dot, a trailing dot or an empty segment is
#: refused rather than silently matched.  The same shape feature 139's
#: term grammar takes, spelled here rather than shared by import — one
#: provenance per member, and the sandbox depends on nothing outside it.
_TERM_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


def _require_str_list(document: Mapping, key: str) -> list[Any]:
    """Return ``document[key]`` as a list, refusing anything else.

    The ``allow`` list is the configuration's whole subject, and a compiler
    that guessed at the meaning of a stray string or mapping would be
    writing policy rather than reading it.
    """
    value = document.get(key)
    if not isinstance(value, list):
        raise AllowlistDocumentError(
            f"a sandbox import allowlist's {key!r} must be a list of dotted "
            f"module terms, got {type(value).__name__}: {value!r}. The list "
            f"is the ceiling's whole content — the modules a submitted "
            f"module may import — and a document that cannot enumerate them "
            f"cannot be compiled (feature 167)."
        )
    return value


def _iter_imports(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Every import the tree makes, as ``(line, term)`` pairs.

    The term is the term as the import *executes* it, joined for
    from-imports (``from math import sqrt`` yields ``math.sqrt``) so a
    binding that lands on a subpackage is judged as the subpackage, and
    verbatim for plain imports (``import os.path as p`` yields ``os.path``
    — the alias does not launder the term).  A relative import yields its
    dotted spelling (``.mod``, ``.`` for a bare ``from . import x``),
    which no well-formed allowlist entry covers: a submitted module is one
    module, not a package with siblings, and a relative import names a
    package the box does not hold.  ``ast.walk`` carries the totality —
    every import statement wherever it sits, because an import that
    executes on some path is an import.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.level:
                    # A relative import, spelled as written: ``from . import
                    # x`` → ``.x``, ``from .mod import x`` → ``.mod.x``,
                    # ``from .. import x`` → ``..x``.  The spelling is for
                    # the refusal's reader; the verdict is fixed regardless,
                    # because no well-formed entry begins with a dot.
                    dots = "." * node.level
                    term = (
                        f"{dots}{node.module}.{alias.name}"
                        if node.module
                        else f"{dots}{alias.name}"
                    )
                else:
                    term = (
                        f"{node.module}.{alias.name}"
                        if node.module
                        else alias.name
                    )
                yield node.lineno, term


class ImportsAllowlist:
    """A compiled allowlist: the ceiling a submission is screened against.

    What :func:`compile_imports_allowlist` returns is not the document — it
    is the document plus the guarantee that every term in it is a
    well-formed dotted name, listed once.  Holders (the screen, an operator
    script, a CI check that recompiles the committed artifact) cite that
    guarantee rather than re-derive it, which is why the screen's refusal
    can say "outside the configured allowlist" and mean a set that was
    validated.

    Coverage is by prefix and only downward: an entry admits the term
    itself and everything under it, never its parent — importing a parent
    executes the parent, so an entry naming ``numpy.linalg`` does not
    admit ``numpy``.  That direction is the difference between a ceiling
    and a wishlist.
    """

    __slots__ = ("_term_set", "_terms", "kind")

    def __init__(self, *, kind: str, terms: tuple[str, ...]) -> None:
        self.kind = kind
        self._terms = terms
        # The membership probe in ``covers`` checks each ancestor of a term
        # against a set, so one scan of the document's terms answers every
        # depth at once.  Built once here — the allowlist is immutable
        # after compile — rather than per probe: the screen calls ``covers``
        # once per import, and a ceiling that re-derived itself per call
        # would be doing the compile's work on the refusal's clock.
        self._term_set = frozenset(terms)

    def terms(self) -> tuple[str, ...]:
        """Every term the ceiling admits, in document order."""
        return self._terms

    def covers(self, term: object) -> bool:
        """Whether the ceiling admits an import term.

        Prefix coverage: an entry admits the term itself and everything
        under it.  A term that is not a string names no module and is
        covered by nothing — the conservative answer, the same one the
        screen's refusal gives it.
        """
        if not isinstance(term, str):
            return False
        parts = term.split(".")
        for depth in range(1, len(parts) + 1):
            if ".".join(parts[:depth]) in self._term_set:
                return True
        return False

    def __contains__(self, term: object) -> bool:
        # The duck-checkable spelling of ``covers`` — "is this import
        # allowed?" is the question a caller holding the ceiling asks.
        return self.covers(term)

    def __len__(self) -> int:
        return len(self._terms)

    def __iter__(self) -> Iterator[str]:
        return iter(self._terms)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ImportsAllowlist(kind={self.kind!r}, terms={list(self._terms)!r})"
        )


def compile_imports_allowlist(document: Any) -> ImportsAllowlist:
    """Compile an import allowlist, refusing one that cannot be read.

    The seam the configuration turns on.  The document is read whole —
    marker, then terms — and each term is held to the grammar before an
    :class:`ImportsAllowlist` is handed out, so no caller ever screens a
    submission against a ceiling holding a term no import could match.  A
    refusal propagates as an exception, the compile-time half of "System
    rejects" (feature 167): the document that would have widened the box
    past what the deployment wrote is never applied.

    A document that lists no terms compiles: an empty allowlist is the
    strictest ceiling there is, refusing every submission that imports
    anything — the opposite reading from feature 157's compile, which
    refuses a policy naming no components, and deliberately so: a
    membership law that vouches for nothing has no subject, while a
    ceiling that admits nothing is the strongest version of itself.
    """
    if not isinstance(document, Mapping):
        raise AllowlistDocumentError(
            f"a sandbox import allowlist must be a mapping, got "
            f"{type(document).__name__}: {document!r}. An allowlist is a "
            f"structured document, and a compiler that guessed at the "
            f"meaning of a stray list or string would be writing policy "
            f"rather than reading it — refused, fail closed (feature 167)."
        )

    marker = document.get("policy")
    if not isinstance(marker, str) or not marker.strip():
        raise AllowlistDocumentError(
            f"a sandbox import allowlist's 'policy' must be a non-empty "
            f"string, got {marker!r} ({type(marker).__name__}). A document "
            f"that does not say what it is cannot be trusted to say what "
            f"submitted code may import (feature 167, refused fail closed)."
        )
    if marker != IMPORTS_POLICY_KIND:
        raise AllowlistDocumentError(
            f"a sandbox import allowlist must declare itself "
            f"{IMPORTS_POLICY_KIND!r}, got {marker!r}. A stray JSON file "
            f"carrying an 'allow' key is not this configuration — refused, "
            f"fail closed (feature 167)."
        )

    raw_terms = _require_str_list(document, "allow")
    terms: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_terms):
        if not isinstance(raw, str) or not _TERM_RE.match(raw):
            raise AllowlistDocumentError(
                f"a sandbox import allowlist's term #{index + 1} must be a "
                f"dotted Python module name, got {raw!r}. A term that is "
                f"not one — a relative dot, a star, an empty segment, a "
                f"padded spelling — names no module an allowlist can "
                f"judge, and a ceiling compiled with it would be a ceiling "
                f"with a hole no import could match (feature 167, refused "
                f"fail closed)."
            )
        if raw in seen:
            raise AllowlistDocumentError(
                f"{raw!r} appears twice in the import allowlist. One term "
                f"listed twice is not a wider ceiling, it is one term "
                f"described twice — and the applied policy would be "
                f"whichever spelling came last, which is drift with extra "
                f"steps. Refused (feature 167)."
            )
        seen.add(raw)
        terms.append(raw)

    return ImportsAllowlist(kind=IMPORTS_POLICY_KIND, terms=tuple(terms))


def load_imports_allowlist(
    path: Path = COMMITTED_IMPORTS_ALLOWLIST,
) -> ImportsAllowlist:
    """Read and compile an allowlist from disk, refusing an unreadable file.

    Reads through the same law as any change to it would be: the committed
    artifact is not privileged, so a drift written to disk is refused
    exactly as a drift compiled in memory (feature 167).
    """
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise AllowlistDocumentError(
            f"could not read the sandbox import allowlist at {path}: {exc}. "
            f"An allowlist that cannot be read is not a ceiling that "
            f"refuses everything gracefully — it is a deployment whose box "
            f"has no configured ceiling at all, and a caller that carried "
            f"on would be screening submissions against nothing while "
            f"believing it was screening them against this file "
            f"(feature 167)."
        ) from exc
    except ValueError as exc:
        raise AllowlistDocumentError(
            f"the sandbox import allowlist at {path} is not valid JSON: "
            f"{exc}. Refused rather than read partially: an allowlist "
            f"compiled from a partially-parsed document is one whose file "
            f"and whose ceiling disagree (feature 167)."
        ) from exc
    return compile_imports_allowlist(document)


def committed_imports_allowlist() -> ImportsAllowlist:
    """The committed artifact, compiled through the same law as any change.

    The posture an operator gets without writing a stanza — and the
    document feature 167's own tests hold to §12's row, so "sandboxed code
    imports nothing outside the committed ceiling" is a checked fact about
    a file in the repository rather than a claim in a runbook.
    """
    return load_imports_allowlist(COMMITTED_IMPORTS_ALLOWLIST)


class ModuleReason(enum.StrEnum):
    """Why a submission was admitted or refused — the audit vocabulary.

    One enumeration carries the acceptance and the refusals, the same
    single-fact-two-polarities shape :class:`sandbox.isolation.RunReason`
    takes: ``by-allowlist`` names the ceiling the submission was admitted
    against, and the refusals name what the screen found instead.
    """

    #: Admitted: every import the module makes is inside the configured
    #: allowlist, by the prefix rule.  Reading the string is proof the
    #: compiled ceiling was consulted — a screen hardcoded to "yes" could
    #: never produce the refusal that shares its enum.
    BY_ALLOWLIST = "by-allowlist"

    #: Refused: the module imports one or more terms outside the configured
    #: allowlist.  Feature 167's headline, and the reason a *module*
    #: rather than a configuration is refused at the screen — the pipeline
    #: offers thousands of submissions against one ceiling.
    OUTSIDE_ALLOWLIST = "outside-allowlist"

    #: Refused: the submission is not source text at all.  A screen cannot
    #: admit what it cannot read, and passing it would be reporting clean
    #: over code it never checked — the vacuous green no admission screen
    #: may allow.
    UNREADABLE_SOURCE = "unreadable-source"

    #: Refused: the source text does not parse, so the imports it makes are
    #: unknowable.  "Unknown" is not "inside": a submission whose imports
    #: cannot be read is refused rather than waved through on the half of
    #: it that happened to be readable.
    UNPARSABLE_SOURCE = "unparsable-source"


class ModuleDecision:
    """The screen's whole answer: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed*
    from the compiled ceiling rather than set by a constant: the screen
    reads every import the module makes and admits only when each is
    covered.  ``detail`` carries the ``disallowed_import`` message the
    feature's sentence names — the one place the law explains itself at
    refusal time, naming every offending term with its line and the
    ceiling it was screened against.
    """

    __slots__ = ("admitted", "detail", "reason")

    def __init__(self, *, admitted: bool, reason: ModuleReason, detail: str) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail

    def require(self) -> None:
        """Raise :class:`~sandbox.errors.DisallowedImportError` if refused.

        The bridge between the screen's returned message and the exception
        a launcher wants: a caller that must not proceed *at any cost* —
        the last line before it would have executed the module — calls
        ``require()`` on the decision it was handed and turns the refusal
        into the error type the compile's siblings raise, so the screen's
        returned shape and the caller's raised one carry one message and
        can never say different things.  A decision that admitted the
        submission is a no-op, so a caller can use it unconditionally.
        """
        if not self.admitted:
            raise DisallowedImportError(self.detail)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ModuleDecision(admitted={self.admitted}, reason={self.reason!r})"


def screen_module(source: object, allowlist: ImportsAllowlist) -> ModuleDecision:
    """Answer one submission: admitted only when every import is covered.

    The order of the checks is the order of the sentence.  The submission's
    *readability* is settled first — a screen cannot admit what it cannot
    read — then its parse, then the imports themselves, which are the only
    thing that can admit.  Every answer is a value; nothing is raised
    here, because the pipeline runs this over every candidate and one bad
    submission must not crash an unattended evaluator.  A caller that must
    not proceed turns the answer into an exception with
    :meth:`ModuleDecision.require`.
    """
    if not isinstance(allowlist, ImportsAllowlist):
        raise AllowlistDocumentError(
            f"the allowlist to screen a submission against must be a "
            f"compiled ImportsAllowlist, got {type(allowlist).__name__}; "
            f"the ceiling is a validated value, not a loose sequence a "
            f"screen would have to re-validate mid-refusal (feature 167)."
        )

    if not isinstance(source, str) or not source.strip():
        described = type(source).__name__ if not isinstance(source, str) else "blank source"
        return ModuleDecision(
            admitted=False,
            reason=ModuleReason.UNREADABLE_SOURCE,
            detail=(
                f"{DISALLOWED_IMPORT_CODE}: a submitted module must be a "
                f"non-empty string of Python source, got {described!r}. "
                f"The screen cannot admit what it cannot read, and passing "
                f"it would be reporting clean over code it never checked — "
                f"the submission is refused before anything executes "
                f"(feature 167)."
            ),
        )

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as broken:
        where = getattr(broken, "lineno", None)
        message = getattr(broken, "msg", broken)
        location = f"line {where}: " if where is not None else ""
        return ModuleDecision(
            admitted=False,
            reason=ModuleReason.UNPARSABLE_SOURCE,
            detail=(
                f"{DISALLOWED_IMPORT_CODE}: a submitted module does not "
                f"parse — {location}{message}. A screen cannot judge the "
                f"imports of source it cannot read, and 'unknown' is not "
                f"'inside': the submission is refused rather than waved "
                f"through (feature 167)."
            ),
        )

    ceiling_terms = allowlist.terms()
    ceiling_listed = ", ".join(ceiling_terms) if ceiling_terms else "nothing allowed"
    imports = list(_iter_imports(tree))
    offenders = [(line, term) for line, term in imports if not allowlist.covers(term)]

    if offenders:
        listed = "; ".join(f"line {line}: {term!r}" for line, term in offenders)
        return ModuleDecision(
            admitted=False,
            reason=ModuleReason.OUTSIDE_ALLOWLIST,
            detail=(
                f"{DISALLOWED_IMPORT_CODE}: a submitted module imports "
                f"{len(offenders)} of its {len(imports)} import terms "
                f"outside the configured allowlist ({allowlist.kind}, "
                f"{len(ceiling_terms)} terms: {ceiling_listed}) — {listed}. "
                f"A module the allowlist never named is one this "
                f"deployment never vouched for, and §5.2's posture is the "
                f"law's own first line: 'LLM-authored code is untrusted "
                f"code. Treat it that way.' The submission is refused "
                f"before anything executes, naming every offender so the "
                f"author repairs them all rather than resubmitting to "
                f"learn the rest (feature 167)."
            ),
        )

    return ModuleDecision(
        admitted=True,
        reason=ModuleReason.BY_ALLOWLIST,
        detail=(
            f"submitted module admitted: all {len(imports)} of its import "
            f"terms are inside the configured allowlist ({allowlist.kind}, "
            f"{len(ceiling_terms)} terms). The answer is about imports "
            f"only — the screen is the admission check, and the box "
            f"beneath it is what enforces (feature 167)."
        ),
    )


class SandboxImports:
    """Feature 167's law, as the value a composed application carries.

    A stateless facade over :mod:`sandbox.imports` and the committed
    allowlist it compiled — the same shape :class:`sandbox.SandboxIsolation`
    gives feature 157 — so a caller holding the composed component can ask
    the feature's question, *may this submitted module execute, given its
    imports?*, without importing the member's submodules by name or
    re-reading the artifact.  It carries the compiled ceiling and nothing
    else: no runner, no process, no handle on the box, because the feature
    is a law about what a submission may import rather than a mechanism
    that executes anything.

    **``require`` is the verb a launcher wants.**  :meth:`screen` returns
    the gate's decision as a value, for a caller that wants to branch;
    :meth:`require` turns a refusal into the exception
    (:class:`~sandbox.errors.DisallowedImportError`) a launcher that must
    not proceed calls immediately before it would have run the module.

    **The delegation is deliberately thin** — each method is one call into
    :mod:`sandbox.imports` — because a second implementation of the
    coverage rule or the screen here would be a second thing to keep in
    sync with the law, and the member's one-provenance rule exists so that
    cannot happen.  What the class adds is discoverability (the factory's
    scan composes it) and a single duck-checkable seam.
    """

    __slots__ = ("_allowlist",)

    def __init__(self, allowlist: ImportsAllowlist) -> None:
        self._allowlist = allowlist

    @property
    def allowlist(self) -> ImportsAllowlist:
        """The compiled import allowlist this component carries.

        Exposed so a caller — a CI check recompiling the committed
        artifact, an operator asking which modules this deployment admits
        — reads the ceiling rather than re-deriving it.  Reading it widens
        nothing: the allowlist holds no capability, which is the point of
        the component being a facade rather than a runner.
        """
        return self._allowlist

    def screen(self, source: object) -> ModuleDecision:
        """Answer whether a submitted module may execute, given its imports.

        The verb the pipeline's admission step wants: one call, the
        submission's source, and the decision — whose refusal detail is
        the ``disallowed_import`` message the feature's sentence names.
        """
        return screen_module(source, self._allowlist)

    def require(self, source: object) -> None:
        """Refuse unless the submitted module's imports are all covered.

        The launcher's verb: raises
        :class:`~sandbox.errors.DisallowedImportError` — carrying the
        screen's own sentence — when the submission is refused, and
        returns ``None`` when it is admitted, so a caller can put it on
        the last line before it would have executed the module and have
        the law enforced there rather than remembered.
        """
        self.screen(source).require()

    def covers(self, term: object) -> bool:
        """Whether the configured ceiling admits one import term.

        The read side of the law: *may sandboxed code import this?* is a
        question a deployment should be able to answer without submitting
        a module to find out, and answering it from the compiled artifact
        is what makes the ceiling a fact about the deployment rather than
        a claim in a runbook.  ``False`` for a term the allowlist does not
        cover is the answer the screen's refusal gives it too.
        """
        return self._allowlist.covers(term)

    def terms(self) -> tuple[str, ...]:
        """The terms this deployment admits, in document order."""
        return self._allowlist.terms()


def sandbox_imports() -> SandboxImports:
    """The import law, compiled fresh — for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran*
    the law would have nothing to run it *on*, since the law needs a
    submission to answer for.  This is the module-level convenience the
    member's own tests and any operator script reach, and it is the same
    call :func:`sandbox.build_sandbox_imports` makes minus the
    composition.
    """
    return SandboxImports(committed_imports_allowlist())
