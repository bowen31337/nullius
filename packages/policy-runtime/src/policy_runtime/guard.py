"""Feature 225, the runtime guard — a running policy reaches no file and no
module outside the ceiling.

app_spec.xml, "Exploration Policy Runtime", feature 225 (``depends_on=223``):
*System rejects filesystem access from the policy runtime plus any import
outside the configured allowlist.*  It is docs/nullius-tech-architecture.md
§10.2's closing sentence, stated as law:

    The policy runtime additionally blocks: ``question.best_so_far``,
    ``question.budget_spent``, filesystem access, and any import outside an
    allowlist.

§11.1 names the same two halves among the *"static checks before any policy is
admitted"* — *"no imports outside the allowlist"* — and §5.2's control table
gives the box the same shape from the mechanism side (``filesystem=False``, no
mounts), while §3's zone map states the posture in one line: *"Z1 — Mutated by
the loop | Signal code, exploration policy code | … Sandboxed: no network, no
FS, seccomp, cgroup limits"*.

**223 made the object prefix-only; 225 makes the *episode* prefix-only.**  The
prefix view (feature 223) is the object a policy holds, and it is prefix-only
by construction — there is nowhere in it an unrevealed node could be.  That
closes the graph a policy is *handed*.  It does not close the world the policy
*runs in*: a policy holding a perfectly prefix-only view can still call
``open("/etc/passwd")``, or ``import subprocess``, and read something no reveal
ever earned it.  Feature 224 defends the view's attribute surface; feature 225
defends the interpreter the policy executes on.  Both take ``depends_on=223``
for the same reason: 223 is the object they defend, and each defends a
different face of it.

**Why this is a runtime guard and not a fifth static check.**  Features 230
and 231 screen a policy's authored **source** before it is admitted, and they
are the right first layer — cheap, total over the text, and they name every
offender at once.  :mod:`.learned` states their honest limit in its own words:
*"a policy that reaches a model by spelling the loader dynamically — a name
built from a string — evades this screen."*  Feature 225's sentence is not
about the source.  It says **"filesystem access from the policy runtime"** —
the reach itself, while it happens — and no static screen can answer that,
because a path assembled at runtime out of the cells a policy revealed is not a
literal any parser can read.  The two are complementary rather than duplicated,
and the split is the one this member already keeps: 230/231 judge what a policy
*is*; 225 refuses what a policy *does*.

**The two halves are enforced by the two channels that can see them, and the
import half's channel is the finding this module is built around.**

* **Filesystem access is refused at the call, from the interpreter's own audit
  channel.**  :func:`sys.addaudithook` is the one seam below the surface a
  static screen cannot reach, and it is what makes "reached for the
  filesystem" a fact about the interpreter rather than a promise about the
  policy: ``open``, ``os.listdir``, ``os.scandir``, ``os.remove``,
  ``os.mkdir``, ``shutil.copyfile`` and their kind all raise audit events
  *before* the operation runs, so the refusal lands before a byte is touched.
  This is deliberately the same control §5.2's box enforces from the outside,
  read here from the inside, so the guard holds even where no box is deployed —
  the same "the floor must hold where the sandbox is not" reasoning feature
  139's determinism floor states for its own ceiling.

* **Imports are refused at the import — and there the audit channel is not
  enough.**  An ``import`` audit event fires only when the import machinery
  actually *loads* a module; a module already in :data:`sys.modules` is
  imported with no event and no ``find_spec`` call at all (``import os`` in a
  process that has already imported ``os`` is a dictionary lookup).  A screen
  built on audit events alone would therefore refuse ``import time`` and admit
  ``import os`` — the worst available failure mode for a barrier, since the
  dangerous module is precisely the one most likely to be preloaded.  The
  import half is enforced **above** the machinery instead, by wrapping
  :func:`builtins.__import__`, the one function *every* spelling of an import
  goes through — ``import x``, ``from x import y``,
  ``importlib.import_module``, a bare ``__import__`` — cached or not.

**The subject is the policy's module, not whoever happens to be running.**
Both channels are process-global in CPython — an audit hook cannot be removed
and ``__import__`` is one function for the interpreter — so the guard is
installed once and *armed* per episode.  The arming is a
:class:`contextvars.ContextVar`, set on entry and restored on exit however the
episode ends, and every refusal is gated on it.  Two consequences follow, and
both are the feature:

* **outside the extent nothing changes.**  A test suite, the factory's scan,
  the artifact store, the replay engine's own bookkeeping — all of it runs with
  the guard dormant, reads its files and imports its modules exactly as before.
  A guard that refused everything everywhere would take the application down
  rather than refuse a policy;
* **inside the extent, only the policy's own imports are judged.**  A policy
  importing a *sanctioned* module fresh makes the machinery load it, and that
  load reads the module's file and imports its own dependencies in turn
  (``statistics`` imports ``numbers``, which no ceiling names).  Refusing those
  would refuse the policy for the interpreter's diligence, so the import half
  judges a term only when the import executes *from the policy's own module*.
  ``globals["__name__"]`` is the discriminator, and it is exact rather than a
  frame heuristic: CPython hands ``__import__`` the globals of the module whose
  bytecode contains the import statement.

**The extent is the policy's episode, and that boundary is deliberate.**  The
filesystem half refuses within the whole extent, not merely within the
policy's own frames — because the alternative, judging frames, cannot tell a
policy's own ``open`` from the same call made by a helper the policy invoked,
and "the policy caused it" is the honest reading of §10.2's *"filesystem access
from the policy runtime"*.  The consequence is worth stating plainly: a runtime
that must persist during an episode does its I/O at the episode's seams — which
is where a replay's reveals are written anyway — rather than inside the extent,
and the extent is therefore entered around the policy's *execution* and not
around the loop that drives it.

**A context variable, and the same reasoning feature 146 gives for its own
mark.**  The extent must not leak: an episode that ends must not leave the next
caller guarded, and a thread the policy did not spawn must not inherit a
refusal.  A :class:`~contextvars.ContextVar` is scoped exactly to the extent
that set it, so the guard is armed for the policy and for nothing else — the
choice :func:`canary.replaying` makes for the replay path's own mark.

**The ceiling is the *configured* allowlist, read rather than restated.**  The
sentence says *"the configured allowlist"*, and the load-bearing words are
**configured** and **the**: not "an allowlist this module declares", but the
one the deployment already has.  That document exists — feature 167's
``sandbox-imports`` ceiling, committed at
``packages/sandbox/src/sandbox/imports_allowlist.json`` and compiled by
``sandbox.imports.compile_imports_allowlist`` — and §10.2 says *"the
allowlist"*, singular, exactly as feature 167's own module observes of the two
Z1 boxes.  So :class:`PolicyCeiling` is a **read** of that ceiling: it resolves
it through the composed ``sandbox-imports`` component — a member reaches a
sibling through ``app.*``, never through the sibling's import name — and
answers membership by asking the compiled object feature 167 produced, so the
prefix rule has one implementation in this workspace.

**Honest limits, stated as this member states every other one.**  This is a
guard *inside* the process, and it is not a sandbox.  It reads the calls that
go through CPython's instrumentation; a policy that reaches a file through a C
extension performing the syscall itself is not refused here — §5.2's gVisor box
is the enforcement that closes that, and this module says so rather than
pretending to be it.  One spelling narrows the import half further, and it is
worth naming rather than leaving to be discovered: a ``from``-import of a name
that is a *submodule* CPython has not yet loaded (``from xml import etree``
where ``xml`` is cached and ``etree`` is not) executes in the machinery *below*
:func:`builtins.__import__` and so is not judged.  The gap is narrow by
construction — the module imported through it must be one an allowlisted
package's own directory already contains, and every further import that module
makes once it is running *is* judged — and the filesystem half still holds
throughout the extent, which is what §10.2's sentence actually asks for.

What holds is that the two halves the feature's sentence names are refused
*where they happen*, that each refusal names the operation and its argument,
that the ceiling is the deployment's own configuration rather than a constant
in this file, and that outside the extent the interpreter is left exactly as it
was found.

Stdlib only, and import-cheap: :mod:`builtins`, :mod:`contextvars`, :mod:`sys`,
a :mod:`dataclasses` value and the member's own errors — no third-party import
at module scope, and the install is deferred to the first episode that asks for
it, so the factory's scan pays nothing for the guard.
"""

from __future__ import annotations

import builtins
import sys
import threading
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Self

from .errors import (
    PolicyFilesystemError,
    PolicyImportError,
)

__all__ = [
    "GUARD_ACTIVE",
    "POLICY_MODULE_NAME",
    "PolicyCeiling",
    "PolicyGuard",
    "guard_policy",
]

#: Whether a policy's episode is inside the guarded extent.  A
#: :class:`~contextvars.ContextVar` rather than a module flag, for the reason
#: :func:`canary.replaying` states for its own mark: a module flag is
#: process-global state one unclosed episode could leave armed for every later
#: caller, while a context value is scoped exactly to the extent that set it —
#: set on entry, restored on exit however the extent ends, and invisible to a
#: thread the policy did not spawn.  Default ``False``, so a process that never
#: opens an episode is never guarded.
GUARD_ACTIVE: ContextVar[bool] = ContextVar(
    "policy_runtime_guard_active", default=False
)

#: The module name a guarded episode's policy executes under — the name a
#: runtime registers a policy's module as, and the discriminator the import
#: half compares each importer against.  Spelled once here so the name a policy
#: runs under and the name the guard judges are one string, which the tests pin
#: by executing a policy under exactly this name.
POLICY_MODULE_NAME = "policy_runtime_policy"

#: The one audit event outside those families that is still a filesystem
#: access: the builtin :func:`open`, which the interpreter raises under its own
#: bare name rather than under a module prefix.  :func:`io.open` and
#: :meth:`pathlib.Path.open` raise the same event, so one name covers the three
#: spellings of opening a file.
_OPEN_EVENT = "open"

#: The audit-event families that *are* filesystem access, by the prefix that
#: carries each.  A prefix rule rather than an exhaustive list, and
#: deliberately: a filesystem operation CPython instruments raises an event
#: named after the module performing it, so naming the *families* means a call
#: this module's author did not enumerate is refused too.  The cost is that a
#: non-filesystem event in one of these families would be refused as well —
#: which is the safe direction for a barrier, and the reason the rule refuses
#: rather than carefully filters.
_FILESYSTEM_EVENT_PREFIXES = (
    "glob.",
    "os.",
    "pathlib.",
    "shutil.",
    "tempfile.",
)

#: The import-machinery frame names the transitive-load allowance recognises.
#: A *fresh* import of a sanctioned module makes the machinery load it, and that
#: load reads files and imports the module's own dependencies — work the policy
#: asked for but did not perform.  It is recognised from the audit channel's
#: frames, where the leaf is the loader rather than any module.
_IMPORT_MACHINERY_NAMES = ("importlib",)
_IMPORT_MACHINERY_FILES = ("<frozen importlib", "<frozen zipimport")

#: Whether the *current thread* is inside a sanctioned module's first load.
#: A :class:`threading.local` and not a context variable: the flag must be
#: visible to the code an import runs *in place* — the imported module's
#: top-level statements, and whatever they call — rather than only to contexts
#: derived from this one, and it must not be visible to a thread the policy
#: spawned (a thread is not an import).  Set around the delegated load, and
#: read only by the filesystem half.
_LOADING = threading.local()


def _loading() -> bool:
    """Whether this thread is inside a sanctioned module's first load."""
    return getattr(_LOADING, "sanctioned", False)


def _mark_loading(active: bool) -> bool:
    """Set this thread's load mark, returning the mark it replaced.

    Returned rather than assumed, so a module whose import triggers another
    sanctioned import restores the *outer* load's mark on the way out instead
    of clearing it — nested imports are the norm, not the exception.
    """
    previous = getattr(_LOADING, "sanctioned", False)
    _LOADING.sanctioned = active
    return previous


@dataclass(frozen=True)
class PolicyCeiling:
    """The ceiling a policy's imports are judged against — the configured
    allowlist, read rather than restated.

    The configured allowlist is feature 167's ``sandbox-imports`` ceiling:
    committed at ``packages/sandbox/src/sandbox/imports_allowlist.json`` and
    compiled by ``sandbox.imports.compile_imports_allowlist``.  A deployment
    that widens or narrows the sandbox's allowlist widens or narrows the policy
    runtime's in the same edit, so the two can never drift into disagreeing
    about what a Z1 submission may import — which is what *"the configured
    allowlist"* means when §10.2 says *"the"*.

    :attr:`compiled` holds the object feature 167 produced when one could be
    resolved, so membership is asked of that object and the prefix rule has one
    implementation in this workspace.  :attr:`terms` is the read side a caller
    audits with, and it is what the fallback scan walks for a deployment that
    composed no sandbox — still the same document, still one provenance.
    """

    #: The terms the ceiling admits, in document order — the read side, so
    #: *"which modules may a policy import?"* is a fact about the deployment
    #: rather than a claim in a runbook.
    terms: tuple[str, ...] = field(default=())
    #: The compiled ceiling feature 167 produced, when one was resolved.  Held
    #: so the prefix rule is the sandbox's own implementation rather than a
    #: second spelling of it here.
    compiled: Any = None

    def covers(self, term: object) -> bool:
        """Whether the ceiling admits an import term — the one membership rule.

        Asked of the compiled ceiling when one is held, so the prefix coverage
        (an entry admits the term and everything under it, never its parent —
        importing a parent executes the parent) is the sandbox's own rule; the
        term-by-term scan is the fallback for a deployment that named no
        sandbox, applying that same rule over the same document's terms.  A
        term that is not a string names no module and is covered by nothing —
        the conservative answer.
        """
        if self.compiled is not None:
            return bool(self.compiled.covers(term))
        if not isinstance(term, str) or not term:
            return False
        entries = set(self.terms)
        parts = term.split(".")
        for depth in range(1, len(parts) + 1):
            if ".".join(parts[:depth]) in entries:
                return True
        return False

    def __contains__(self, term: object) -> bool:
        # The duck-checkable spelling of ``covers`` — "is this import allowed?"
        # is the question a caller holding the ceiling asks.
        return self.covers(term)

    def __len__(self) -> int:
        return len(self.terms)

    def __iter__(self) -> Iterator[str]:
        return iter(self.terms)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PolicyCeiling(terms={list(self.terms)!r})"


def _ceiling_from_seat(app: Any) -> PolicyCeiling:
    """The configured allowlist as the composed application answers it.

    Resolved through the composed application rather than through the sandbox
    package's import name: a workspace member never imports another member, and
    reaches a sibling's shared shapes through ``app.*``.  The
    ``sandbox-imports`` component (``create_app().get("sandbox-imports")``)
    is the composed spelling of the ceiling, so what the policy runtime
    enforces is literally the object the composed application carries.

    A deployment with no sandbox composed is not an error: the committed
    document is then read directly — still the same file, still the same
    ceiling.  A sandbox that *is* composed but whose artifact fails to compile
    is the caller's to hear about, so the read catches only the seat's absence
    and lets a compile refusal propagate rather than hiding a drifted artifact
    behind a guard that had quietly fallen back to a second reading of it.

    ``app`` is passed through rather than defaulted here, and the distinction is
    the point: a *bare* ``create_app()`` composes the deployment's application
    from scratch — a scan of every member and a build of every component — so a
    caller that already holds an application (the running system, for feature
    225's own case) must hand it over instead of paying for a second
    composition to read one configuration document.
    """
    try:  # pragma: no cover - the import path is the composed application's
        from app.module_loader import create_app
    except ImportError:
        return PolicyCeiling(terms=tuple(_committed_document_terms()))
    # "sandbox-imports" is the sandbox member's own component name.
    component = (app if app is not None else create_app()).get("sandbox-imports")
    if component is None:
        return PolicyCeiling(terms=tuple(_committed_document_terms()))
    return PolicyCeiling(terms=tuple(component.terms()), compiled=component)


#: The ceiling resolved once for this process, when no application was handed
#: over.  Composing a deployment to read one configuration document is work
#: worth doing *once* rather than once per episode: a guard is constructed per
#: policy, so a resolution per construction would re-scan the workspace and
#: rebuild every component for every policy that ever ran.  The memo is what
#: keeps the read side free after the first episode, and a caller holding an
#: application skips even that first cost by passing it.
_RESOLVED: PolicyCeiling | None = None


def _committed_ceiling(app: Any = None) -> PolicyCeiling:
    """The configured allowlist — the ceiling a policy's imports are judged by.

    Resolved once per process, and from the application the caller already has
    where there is one: :func:`_ceiling_from_seat` states why the distinction
    between a handed-over application and a bare seat call matters.  The memo
    belongs here rather than in :class:`PolicyCeiling` because it is a fact
    about *this process's* deployment rather than about the document — two
    ceilings over the same terms are the same law, and a caller that resolved
    its own passes it explicitly rather than relying on this one.
    """
    if app is not None:
        return _ceiling_from_seat(app)
    global _RESOLVED
    if _RESOLVED is None:
        _RESOLVED = _ceiling_from_seat(None)
    return _RESOLVED


def _committed_document_terms() -> list[str]:
    """The committed allowlist's terms, read from the document itself.

    The fallback for a deployment that composed no sandbox.  The path is
    spelled here rather than imported from the sandbox package — this member
    reaches another member's *seat*, never its import name — and the read is a
    plain :mod:`json` load of a document whose *contents* this module does not
    interpret: the compile that interprets them belongs to the sandbox, and a
    deployment that has one gets that compile.

    A document that cannot be read resolves to the empty ceiling — the
    strictest ceiling there is, refusing every import a policy makes.  That is
    the fail-closed direction a barrier requires: a policy that cannot be told
    what it may import is not one to wave through.
    """
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "sandbox"
        / "src"
        / "sandbox"
        / "imports_allowlist.json"
    )
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return []
    terms = document.get("allow") if isinstance(document, dict) else None
    if not isinstance(terms, list):
        return []
    return [term for term in terms if isinstance(term, str)]


#: Whether this process has installed the guard's two channels.  A module-level
#: flag, and deliberately *not* the context variable: the audit hook and the
#: ``__import__`` wrap are process-wide edits, so "have they been made?" is a
#: fact about the process rather than about any extent.  The *arming* — whether
#: the edits refuse anything — is the context variable's, and the two are
#: separate on purpose: one is an install that cannot be undone, the other a
#: mark that is set and restored.
_INSTALLED = False

#: The :func:`builtins.__import__` this module found when it installed, kept so
#: the wrapper delegates rather than re-wrapping itself on a later install.
_ORIGINAL_IMPORT = builtins.__import__

#: The name of the module a guarded episode's policy executes under — the
#: discriminator the import half compares each importer against.  A module-level
#: binding because :func:`_guarded_import` runs on the interpreter's hot path,
#: and written only by :class:`PolicyGuard` arming, so "which subject is
#: guarded?" has one answer at a time.
_SUBJECT = POLICY_MODULE_NAME

#: The ceiling the import half consults.  A module-level binding for the same
#: hot-path reason: a resolution per import would re-read the workspace seat for
#: every term a policy names.  Written by :class:`PolicyGuard` arming, and the
#: default admits nothing — so a process that somehow armed the mark without a
#: guard fails closed rather than open.
_CEILING: PolicyCeiling = PolicyCeiling()


def _install_once() -> None:
    """Install the audit hook and the ``__import__`` wrap — at most once.

    The once-only guard is this flag and not the caller's, because CPython
    gives no way to remove an audit hook: a second install would judge every
    filesystem call twice and scatter duplicate refusals through an episode.
    Both channels are installed here, together, so a process is guarded at both
    doors or neither — a half-installed guard would refuse ``open(...)`` while
    admitting ``import os``, which is precisely the leak the two halves exist
    to close together.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    sys.addaudithook(_audit_refusal)
    builtins.__import__ = _guarded_import
    _INSTALLED = True


def _audit_refusal(event: str, args: tuple[Any, ...]) -> None:
    """The filesystem half — refuse an access inside the guarded extent.

    Called by the interpreter for *every* audited event, so the first thing it
    does is return: the extent must be armed, and the event must be one a
    filesystem access raises.  Both checks are cheap and both are required — an
    unarmed process must pay nothing, and an armed one must not refuse the
    interpreter's own bookkeeping (an exception being formatted, a warning
    being raised) as though the policy had reached for a file.

    Two allowances are made, and both are the import machinery's rather than
    the policy's: a fresh import of a *sanctioned* module reads that module's
    file (innermost frame: the loader), and a module that reads a data file or
    a resource while its top-level statements execute is initialising rather
    than reaching (§5.2's public APIs offer "manifest, code only" for exactly
    this reason).  Everything else inside the extent is refused before the
    operation runs.
    """
    if not GUARD_ACTIVE.get():
        return
    if event != _OPEN_EVENT and not event.startswith(_FILESYSTEM_EVENT_PREFIXES):
        return
    try:
        frame = sys._getframe(1)
    except ValueError:  # pragma: no cover - an audit event with no Python frame
        # An audited operation can be raised from a C extension with no Python
        # frame beneath it.  The allowance is *checked* rather than assumed, so
        # a stack too shallow to read falls through to the refusal: an
        # unreadable origin is not evidence the policy was innocent, and this
        # is the fail-closed direction a barrier takes.
        frame = None
    if frame is not None:
        name = frame.f_globals.get("__name__", "")
        filename = frame.f_code.co_filename
        if name.startswith(_IMPORT_MACHINERY_NAMES) or filename.startswith(
            _IMPORT_MACHINERY_FILES
        ):
            return  # the loader reading a module the policy was allowed to import
    if _loading():
        # A sanctioned module's own initialisation, or code it called while
        # initialising: the load the policy was admitted, not a reach by it.
        return
    argument = args[0] if args else None
    raise PolicyFilesystemError(
        f"filesystem access refused: a policy inside its guarded episode may "
        f"reach no file, and the operation {event!r} on {argument!r} was "
        f"refused before it ran (feature 225, docs §10.2). A policy sees only "
        f"the cells it has revealed — through question.observed() and the "
        f"prefix view — so anything it needs from outside that prefix arrives "
        f"as an argument the runtime passes in, never by reaching for it"
    )


def _importer_name(globals_: Any) -> str:
    """The name of the module an import executes from — the guard's subject.

    CPython hands :func:`builtins.__import__` the *globals of the module whose
    bytecode contains the import statement*, so ``globals_["__name__"]`` names
    the importer exactly: the policy's own module for the policy's own imports,
    and the module being loaded for the transitive imports that loading
    performs.  That is the discrimination the guard is built on, and it is
    exact rather than a stack heuristic.

    An importer that supplies no globals — a bare ``__import__("x")``, which is
    the spelling a policy reaches for when it is hiding a name from a static
    screen, and :func:`importlib.import_module`'s own delegation — falls back
    to the caller's frame, whose ``__name__`` is the module whose bytecode made
    the call.  That is the same discrimination by the same fact, read one way
    when the arguments carry it and another when they do not, so the hiding
    spelling is judged rather than waved through.  Only the *immediate* caller
    is consulted: a module a policy called performs its own imports under its
    own name, which is what keeps the transitive-load allowance working.
    """
    if isinstance(globals_, dict):
        name = globals_.get("__name__")
        if isinstance(name, str):
            return name
    try:
        frame = sys._getframe(2)
    except ValueError:  # pragma: no cover - a stack too shallow to name
        # Only reachable from a caller with no Python frame beneath this
        # function, which is a C-level entry the guard does not see in
        # practice.  Returning no name rather than raising is the load-bearing
        # part: an exception here would crash an import the guard was only
        # asked to judge, turning a barrier into an outage.
        return ""
    name = frame.f_globals.get("__name__", "")
    return name if isinstance(name, str) else ""


def _guarded_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """The import half — refuse a term outside the ceiling, then delegate.

    Installed over :func:`builtins.__import__`, the one function *every*
    spelling of an import goes through: ``import x``, ``from x import y``,
    ``importlib.import_module("x")`` and a bare ``__import__("x")`` are all
    this call, cached or not.  That totality is why the import half lives here
    rather than on the audit channel, where a cached module raises no event at
    all.

    The term is judged only when the import executes *from the guarded
    subject*: a policy importing a sanctioned module fresh makes the machinery
    load it and *its* dependencies in turn (``statistics`` imports ``numbers``,
    which no ceiling names), and refusing those would refuse the policy for the
    interpreter's diligence.  A relative import is refused outright — a
    submitted policy is one module, not a package with siblings, the same
    reading feature 167's screen takes.

    A refusal raises :class:`~policy_runtime.PolicyImportError` *before*
    delegating, so the module never loads and the policy never receives a
    binding.  A *delegated* load of a sanctioned term is wrapped in the load
    mark the filesystem half reads, so a module that reads a resource while it
    initialises is not mistaken for the policy reaching for one — the mark is
    set around the load and cleared after it, however the load ended.  Off the
    extent, and for every importer but the subject, this is the original
    function untouched: the delegation is deliberately thin — no caching, no
    counting, no rewriting of the arguments — because anything more would make
    this member own importing rather than refuse it.
    """
    if GUARD_ACTIVE.get() and _importer_name(globals) == _SUBJECT:
        if level:
            dots = "." * level
            raise PolicyImportError(
                f"relative import refused: a policy is one module in the "
                f"runtime, not a package with siblings, and {dots}{name!r} "
                f"names a sibling no submitted policy has (feature 225, "
                f"docs §10.2)"
            )
        root = name.split(".", 1)[0]
        if not _CEILING.covers(root):
            raise PolicyImportError(
                f"import refused: {name!r} is outside the configured "
                f"allowlist, and a policy imports only what the deployment "
                f"admitted (feature 225, docs §10.2: 'any import outside an "
                f"allowlist'). A policy reaches for the question — "
                f"question.observed(), the prefix view, the schedule — and for "
                f"the deterministic modules the configured ceiling names; a "
                f"module it never named is one this deployment never vouched "
                f"for, so the import is refused before the module loads"
            )
        if _loads_anything(name, fromlist):
            previous = _mark_loading(True)
            try:
                return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
            finally:
                _mark_loading(previous)
    return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


def _loads_anything(name: str, fromlist: Any) -> bool:
    """Whether this delegated import will execute a module's top-level code.

    True when the term itself is not yet in :data:`sys.modules`, or when a name
    in ``fromlist`` still has to be loaded — the two shapes under which the
    machinery runs a module's statements and the module may read a resource on
    its own behalf.  A cached term with nothing missing executes no top-level
    code, so it is not marked: an allowlisted module already in
    :data:`sys.modules` cannot hide a reach behind its import, and the policy
    that names it is judged on what it does next.
    """
    if name.split(".", 1)[0] not in sys.modules:
        return True
    for entry in fromlist or ():
        if isinstance(entry, str) and f"{name}.{entry}" not in sys.modules:
            return True
    return False


class PolicyGuard:
    """Feature 225's law, as the value a policy's episode is run inside.

    The two halves of §10.2's sentence — *filesystem access* and *any import
    outside an allowlist* — as one object.  It carries the configured ceiling
    and nothing else: no policy, no tree, no store, because the feature is a
    law about what a *running* policy may reach rather than a mechanism that
    runs anything.

    **It is its own context manager.**  ::

        with guard_policy() as guard:
            ...                       # the policy's episode
            guard.covers("math")      # -> True: the read side, inside the extent

    Entering installs the two channels if this process has not yet (so a caller
    gets the law whether or not it installed explicitly), binds this guard's
    ceiling and subject for the extent, and arms the mark; leaving restores all
    three however the episode ended — a policy that returns, that raises, or
    that is interrupted leaves the interpreter exactly as it was found.

    **Two guards nest, and the inner one wins for its extent.**  The bindings
    are saved and restored per entry, so an episode run inside another episode
    is judged by its own ceiling for as long as it runs — the composition a
    deployment tests a narrower box under — and the outer guard is back in
    force the moment the inner extent ends.

    **The channels are installed once and armed per episode.**  CPython offers
    no way to uninstall an audit hook and only one ``__import__`` to wrap, so
    :meth:`install` performs both edits once per process and every later extent
    merely flips the mark.  That is why the install is idempotent and why the
    guard is a value a deployment holds rather than a function that patches the
    interpreter per call: the install is a property of the running application,
    the arming a property of the episode.
    """

    # Hand-written slots rather than ``@dataclass(slots=True)``: the two
    # enter/exit bindings below are *not* fields — they are an extent's
    # bookkeeping, written on entry and read on exit — and a slots dataclass
    # rebuilds ``__setattr__`` against the pre-rebuild class, so a non-field
    # assignment on one dies inside ``super()`` with a bare :exc:`TypeError`
    # (the same trap feature 223's ``PrefixView`` records for its own object).
    __slots__ = ("_ceiling", "_restore", "_subject", "_token")

    def __init__(
        self,
        ceiling: PolicyCeiling | None = None,
        *,
        subject: str = POLICY_MODULE_NAME,
        app: Any = None,
    ) -> None:
        self._ceiling = ceiling if ceiling is not None else _committed_ceiling(app)
        self._subject = subject
        # Written by ``__enter__``; declared here so the object's full state is
        # one list rather than a field set plus a surprise.
        self._restore: tuple[str, PolicyCeiling] = (POLICY_MODULE_NAME, PolicyCeiling())
        self._token: Any = None

    @property
    def ceiling(self) -> PolicyCeiling:
        """The configured allowlist this guard judges imports against.

        Exposed so a caller — a deployment audit, an operator asking which
        modules a policy may import — reads the ceiling rather than re-deriving
        it.  Reading it widens nothing: the ceiling holds no capability, which
        is the point of the guard being a law rather than a box.
        """
        return self._ceiling

    @property
    def subject(self) -> str:
        """The module name whose own imports this guard judges.

        The discriminator the import half compares each importer against: a
        policy's module for the policy's imports, and every other module for
        the transitive loads the machinery performs on the policy's behalf.
        """
        return self._subject

    @property
    def installed(self) -> bool:
        """Whether this process has installed the guard's two channels."""
        return _INSTALLED

    def covers(self, term: object) -> bool:
        """Whether the configured ceiling admits one import term.

        The read side of the import half: *may a policy import this?* is a
        question a deployment should be able to answer without running a policy
        to find out, and answering it from the configured document is what
        makes the ceiling a fact about the deployment rather than a claim in a
        runbook.
        """
        return self._ceiling.covers(term)

    def terms(self) -> tuple[str, ...]:
        """The terms the configured ceiling admits, in document order."""
        return self._ceiling.terms

    def install(self) -> PolicyGuard:
        """Install the two channels, once per process — idempotent.

        Performs the one-time edits an arming cannot perform itself: the audit
        hook (which CPython cannot remove, and which therefore sits inert
        outside every extent) and the ``__import__`` wrap (one function for the
        interpreter, so the same reasoning applies).  A second call is a no-op
        — two composed guards, or a composed guard plus an episode, must not
        produce two hooks, or every filesystem call would be judged twice.
        """
        _install_once()
        return self

    def __enter__(self) -> Self:
        """Arm the guard for one policy's episode — the feature's extent.

        Binds this guard's ceiling and subject, arms the mark, and returns the
        guard so the extent's body reads the very ceiling it is judged by.
        """
        global _SUBJECT, _CEILING
        self.install()
        self._restore = (_SUBJECT, _CEILING)
        _SUBJECT = self._subject
        _CEILING = self._ceiling
        self._token = GUARD_ACTIVE.set(True)
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Disarm, restoring the interpreter's previous state.

        Restores the outer extent's ceiling and subject (or the module's own
        defaults when there is no outer extent) and resets the mark, however
        the episode ended.  Nothing is suppressed: the exception that ended the
        episode — a refusal, or the policy's own failure — propagates
        unchanged, which is what makes the guard an enforcement rather than an
        error handler.
        """
        global _SUBJECT, _CEILING
        GUARD_ACTIVE.reset(self._token)
        _SUBJECT, _CEILING = self._restore

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PolicyGuard(terms={len(self._ceiling)}, "
            f"subject={self._subject!r}, installed={_INSTALLED})"
        )


def guard_policy(
    policy_module: str = POLICY_MODULE_NAME,
    *,
    ceiling: PolicyCeiling | None = None,
    app: Any = None,
) -> PolicyGuard:
    """Construct the guard for one policy's episode — the feature's verb.

    The one factory: a :class:`PolicyGuard` over the *configured* allowlist,
    ready to be entered as the extent a policy runs inside.  ::

        with guard_policy() as guard:
            policy_function(prefix_view(question))

    ``policy_module`` names the module the policy's own code executes under —
    the subject the import half judges.  It defaults to
    :data:`POLICY_MODULE_NAME`, which is the name a runtime registers a
    policy's module as, and a caller running its policy under a different name
    passes the one it used: what matters is that the name the policy *executes*
    under and the name the guard compares importers against are the same
    string, which is why the default lives in one place.

    ``ceiling`` overrides the configured allowlist, for a caller that resolved
    one itself — a test, an operator replaying an episode under the terms it
    ran under, a deployment auditing a narrower box than the sandbox's.
    Omitted, the configured ceiling is resolved: the workspace's composed
    ``sandbox-imports`` law where one is composed, and the committed document
    read directly where none is.

    ``app`` is the composed application to resolve that law from, and a running
    system should pass the one it holds: the seat's bare call *composes* the
    deployment — a scan of every member and a build of every component — and a
    guard is constructed per policy, so a caller that already has an
    application hands it over rather than paying for a second composition to
    read one document.  Omitted, the resolution is memoised for the process, so
    even the first episode pays for it at most once.

    The returned guard is *not* yet armed — entering it is what arms it, so a
    caller that constructs a guard and never enters it has changed nothing
    about the interpreter beyond the inert install.
    """
    return PolicyGuard(ceiling, subject=policy_module, app=app)
