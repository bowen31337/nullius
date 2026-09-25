"""System rejects the merge when any symbol named is_null is reachable
outside the scorer package.

app_spec.xml feature 354 — the "System Invariant CI Gates" category's
information-barrier gate, ``covers="cq-19"`` — is the merge-time form of
the one law the whole null-oracle category exists to serve.
docs/alpha-engine-prd.md §4.2 states it at its widest::

    `is_null` is visible to **exactly one component**: the replay scorer.

    It must never appear in:
    - the discovery agent's prompt or context,
    - the exploration policy's `observed()` prefix,
    - any stored artifact the policy can read during replay,
    - any log the policy-development agent reads between revisions.

    Violating this silently voids all calibration. Enforce it with a
    type-level barrier, not a code review.

§13 restates it as the second numbered invariant (*"`is_null` is readable
by exactly one component: the replay scorer"*), the success criteria state
it as this gate's own sentence (*"No symbol named is_null is reachable
outside the scorer package"*), and docs/nullius-tech-architecture.md §1
names the stake in its P2: the null labels are *"the one secret whose leak
silently voids every calibration number the system has ever produced, and
you would not notice."*  The runtime faces of the barrier refuse the *read*
and the *column* — the sealed sidecar opens for one service account
(feature 109), the tree store refuses the column by name (feature 110),
the ``/target`` route returns two series no caller can tell apart (feature
114), and the prefix interface hands a policy only what it has revealed
(feature 217).  This gate refuses the *name*: a merge that ships a symbol
called ``is_null`` anywhere the bit may not live is rejected before any
process imports it, which is the only moment the refusal is free — the
sentence's own closing instruction ("Enforce it with a type-level
barrier, not a code review") is a description of this file.

**The first term: a symbol named ``is_null``.**  A *symbol* is a name the
interpreter binds in a namespace somebody else can address, and the merge
ships it in exactly nine spellings, all judged here: a module assignment
(``is_null = False`` at module body — the "temporary" debug flag), a class
field (a dataclass, TypedDict, NamedTuple or enum member carrying the bit
— the shape prd §6.1's artifact schema spells for its ``hidden:`` block,
which is why fields are judged and not merely importable names), a class
named ``is_null``, a method (a ``@property`` a record gains, an accessor a
store grows), a plain function, a parameter (a callable's keyword is part
of its interface, and ``inspect.signature`` publishes it), an import that
binds the name (``from nulloracle import NullAssignment as is_null`` —
the smuggling shape, lawful inside the homes and refused everywhere
else), a ``global`` statement's store (a function binding the module's
namespace), and an attribute store (``self.is_null = value`` — a field a
class never declared, created on the object at run time).  What is *not* a
symbol is stated as hard as what is: a *local* variable binds a namespace
no other code can name — the oracle's own route reads the bit into a
local *"read here and carried no further"* (``nulloracle/target.py``'s
``post``), and the scorer's own read is a local too, because *"the number
flows out; the labels do not"* (docs §10.3); a *string* is data, not a
binding — ``FORBIDDEN_COLUMN = "is_null"`` names the bit to refuse it, and
the discovery member's planning context carries ``"is_null"`` inside the
very vocabulary it exists to forbid, which is the barrier spelled as a
refusal rather than breached by one; and a *use* is not a binding — a
call-site keyword and a ``getattr(entry, "is_null", None)`` reach a
binding that is judged where it is defined, one finding per symbol rather
than one per mention.  The comparison is exact and case-sensitive, because
Python resolves attribute names case-sensitively: ``IS_NULL`` is another
symbol, where the tree store's guard casefolds because SQLite's columns
do not (``nulloracle/schemaguard.py`` states the contrast in its own
docstring) — and near-misses are other symbols too: ``is_null_root`` is
the selection's lawful verb, and a gate that widened itself to substrings
would refuse the shipped code the spec itself spells.

**The second term: outside the scorer package.**  The scorer *process* is
feature 265's component — the thing that holds the sidecar key, lives in
the ``scoring`` member, and computes the figures that need the labels
(``scoring-null-pick-rate``; the KS guard's sanctioned job runs beside the
sealed file it reads).  The bit's one home is §7.1's sidecar, whose
plaintext schema the spec spells out — ``{node_id: {is_null: bool,
perm_seed: int, block_days: int}}`` — and that schema *is*
``nulloracle.NullAssignment``: a frozen dataclass whose ``is_null`` field
is the spec's own spelling, exported because the sealed bytes' keys are
deliberately not shortened for a second process's audit tools.  So the
sentence's "scorer package" cannot mean the scoring member alone — that
reading refuses the spec's own §7.1 schema and every merge that carries
it — and it does not need to: the two members the bit's legitimate life
spans are exactly the two the shipped code already confines it to.
:data:`SCORER_PACKAGES` below names them (``nulloracle`` — where the bit
lives; ``scoring`` — the one component that may read it), read against
the loader's own workspace declaration so a merge that renamed or deleted
either home trips the pin, and *audited, not trusted*: the stands class
holds that the null-oracle member's reachable ``is_null`` symbols are
exactly §7.1's one field, and that the scoring member exposes **none at
all** — the scorer's barrier is its own design ("no accessor for the held
sidecar, no label cache", feature 265's words), and this gate witnesses
it as standing state.  The exemption is the declared member, not the
string "scoring" on a path: the scorer's *app seat*
(``src/app/modules/scoring/scorer.py``) is the application layer, ships
no symbol of the name, and is refused the moment it grows one.

**Why a binding audit over namespaces, and not a grep.**  A merge carries
source, and reachability is a fact about the namespaces that source
binds: a name stored at a module body is an attribute of the module every
importer can read; a name stored at a class body is an attribute of every
instance; a name stored inside a function is private to it.  The
evaluator below walks the AST with Python's own scope rule — module and
class bodies bind addressable namespaces, functions (and lambdas, and
comprehensions, which carry scopes of their own) bind locals, ``global``
re-opens the module namespace, and an attribute store binds the *object*,
not the function it sits in — so a merge cannot hide the bit behind a
spelling the grammar offers: ``for is_null in …`` at a module body, a
``with … as is_null``, a match-pattern capture, an ``except … as`` at a
module body are all stores in an addressable namespace, and each is named
with its kind and its qualified name so the operator reads the break off
the source rather than re-deriving it.  A grep for the word would catch
all of those and also every docstring, every refusal vocabulary and every
sealed-payload key — the shipped tree carries the spelling lawfully in a
dozen places and the *symbol* in exactly one — so the audit is on the
binding, stated once.

**What this gate is not, asserted as hard as what it is.**  It is not
feature 110's tree-store guard — that refuses a *column* on the ``node``
table, casefolded the way SQLite resolves names, and its own boundary
comment says the wider sweep *"is §4.2's and feature 354's to police"*;
this gate is that wider sweep, over symbols rather than DDL, and the
migration tree is SQL this gate does not read.  It is not feature 123/124's
KS guard — §7.4's job is the one sanctioned consumer of the labels, and
its statistic deliberately carries sizes instead of node ids.  It is not
feature 265's scorer design — the no-label-cache promise is the member's
own, pinned here as standing state rather than claimed as this gate's
refusal, because the sentence refuses the name *outside* and the inside
is §4.2's grant.  It is not feature 355's prefix-score barrier — that
gate polices what a prefix-only caller may *read* through the question
interface; this one polices whether the name exists to be read at all,
one layer below any interface.  It is not the member suites — those pin
the barrier from inside each member; this gate reads what a merge
carries, from outside every member, and adds the face no member-side
test can promise: a symbol named ``is_null`` reachable outside the two
homes refuses the merge whatever else the merge does.  And it is not a
use-audit: a call-site keyword and a string-keyed ``getattr`` are judged
at the binding they reach, and a spelling with no binding behind it is
data — the gate refuses symbols, not mentions.

**Why CI, and why the harm is silent.**  A symbol named ``is_null`` in a
non-exempt package is not a wrong value the type system or a test fixture
would catch — it is a *reachable fact* about which nodes were planted,
shipped where the barrier promised no such fact could be reached from.
The discovery agent's context, the policy's prefix, the stored artifacts
a replay reads and the logs a policy-development agent scans are the four
surfaces §4.2 names, and every one of them starts with a name somebody
bound; the leak does not error, it *voids* — every calibration number the
system has produced becomes a number over a world whose labels were
visible, and §1's whole point is that you would not notice.  The names
ship in merges, so the refusal belongs at merge time, over the source the
merge ships, with no process imported and no connection opened (pinned
statically below) — an audit that had to run the system to judge it would
be an audit after the leak.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

# ── The workspace, read the way the loader declares it ───────────────────────

#: tests/invariants/test_is_null_symbol_reachability.py → tests/invariants →
#: tests → the repository root — the tree whose production source this gate
#: judges, and the anchor every module name below is resolved against.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The application factory's module, handed to the loader's own resolvers as
#: their starting point — the same spelling tests/invariants/conftest.py uses
#: to put every member on ``sys.path``, so the gate and the conftest can never
#: disagree about which tree is the workspace.
LOADER = REPO_ROOT / "src" / "app" / "module_loader.py"

from app.module_loader import workspace_members

#: The application layer's own member identity — the ``src`` tree the factory
#: and the module seats live in. It is a subject of this gate like any member,
#: and never an exempt one: the seats compose the components, they are not the
#: components (the scorer's app seat is pinned below to carry no symbol and to
#: be refused the moment it grows one).
APP_MEMBER = "app"

#: The members the bit's legitimate life spans — the sentence's "scorer
# package" at the width the shipped code itself decides, because §7.1's sealed
#: schema *is* ``{node_id: {is_null, perm_seed, block_days}}`` and refusing the
#: member that owns it would refuse the spec's own spelling.  ``nulloracle``:
#: the sidecar, the one place the bit lives.  ``scoring``: feature 265's scorer
#: process, the one component §4.2 grants a read.  Member identities here are
#: the declared member directories' names (``packages/<name>``), which for the
#: two homes coincide with their import names; read against the loader's
#: workspace declaration in the gate-reading class below, so a merge that
#: renamed or deleted either home trips the pin rather than widening the audit
#: to cover a name that no longer exists.
SCORER_PACKAGES: frozenset[str] = frozenset({"nulloracle", "scoring"})

# ── The law's own spelling, restated as data ─────────────────────────────────

#: The one name this gate refuses — prd §4.2's own, kept exact and
#: case-sensitive because Python resolves attribute names case-sensitively:
#: ``IS_NULL`` is another symbol (the tree store's guard casefolds for the
#: opposite reason, SQLite's), and ``is_null_root`` is the selection's lawful
#: verb rather than a near-miss worth refusing.
IS_NULL = "is_null"

#: One reachable binding of that name: the kind (one of :data:`BINDING_KINDS`),
#: the qualified name the operator reads off the source, and the line it
#: binds on.
Binding = tuple[str, str, int]

#: One finding: the member, the module (repository-relative), the kind, the
#: qualified name and the line — every fact the refusal names, sorted, so the
#: operator reads the whole shape of the break rather than its first edge.
Finding = tuple[str, str, str, str, int]

#: The nine spellings a merge can ship the name in — the vocabulary of the
#: first term, stated once so the refusal's kinds are legible as data.
BINDING_KINDS: tuple[str, ...] = (
    "module",
    "field",
    "class",
    "method",
    "function",
    "parameter",
    "import",
    "global",
    "attribute",
)

#: The namespace kinds the scope walk tracks.  A store binds whichever of
#: these encloses it — a module body and a class body are addressable from
#: outside (an importer, a holder of the object); a function body is not, and
#: neither is a comprehension or a lambda, which carry scopes of their own.
_MODULE_NS = "module"
_CLASS_NS = "class"
_FUNCTION_NS = "function"

#: Scope markers that contribute nothing to a qualified name but close a
#: function namespace around everything inside them.
_COMP = "<comp>"
_LAMBDA = "<lambda>"


def _parameters_of(arguments: ast.arguments) -> list[ast.arg]:
    """Every parameter node a signature declares, positional-only through
    keyword-only, ``*args`` and ``**kwargs`` included.

    A parameter's name is part of a callable's interface — the keyword a
    caller spells and ``inspect.signature`` publishes — so every parameter
    is judged wherever the callable sits, not only public ones: a merge
    that hides the bit in a private helper's keyword has still shipped the
    name as an interface.
    """
    declared = [
        *getattr(arguments, "posonlyargs", []),
        *arguments.args,
        *arguments.kwonlyargs,
    ]
    if arguments.vararg is not None:
        declared.append(arguments.vararg)
    if arguments.kwarg is not None:
        declared.append(arguments.kwarg)
    return declared


def _own_globals(function: ast.AST) -> frozenset[str]:
    """The names ``function`` declares global *itself* — its own scope's
    declaration, not a nested scope's.

    ``global is_null`` re-opens the module namespace for the stores of the
    function that declares it, so those stores bind a module attribute and
    are reachable; the walk needs the declared set at hand when it reaches
    them.  Nested functions and classes are cut off, because their own
    ``global`` statements (or absence) govern their own scopes.
    """
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
            ):
                continue
            if isinstance(child, ast.Global):
                names.update(child.names)
            visit(child)

    visit(function)
    return frozenset(names)


def reachable_bindings(source: str, module: str = "<source>") -> tuple[Binding, ...]:
    """Every binding of the name ``is_null`` that ``source`` ships in a
    namespace somebody else can address — the first term, as data.

    Walks the AST with Python's own scope rule: a name stored at a module
    body binds a module attribute (an importer can read it); a name stored
    at a class body binds a class attribute (a holder of any instance can
    read it, which is why a dataclass field, a TypedDict key, a NamedTuple
    slot and an enum member are all the one spelling ``field``); a name
    stored inside a function — a lambda, a comprehension, a loop target, a
    ``with`` alias, an ``except`` alias, a walrus — binds a local nobody
    outside can name, and is not a symbol; a ``global`` declaration's store
    re-opens the module namespace; and an attribute store binds the
    *object*, wherever the store sits, because the instance carries the
    attribute out of the function that set it.  ``def``/``class``/import
    names follow the same rule at the scope they bind in — a class body's
    fields are judged even when the class is local to a function, for the
    same reason an attribute store is.  Parameters are judged for every
    callable, public or private, for the reason :func:`_parameters_of`
    states.  Sorted, so the reading is deterministic and matches
    :func:`merge_refusal`'s order; an empty result is a module that ships
    the name only as data or as locals.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(
            f"{module} does not parse ({exc}); this gate judges the code a "
            "merge ships, and code it cannot read is code it cannot bless — "
            "a module that fails here is refused before any finding is "
            "counted, not skipped"
        ) from exc

    found: list[Binding] = []

    def qualified(scope: Sequence[str], name: str) -> str:
        return ".".join((*scope, name))

    def store_in(namespace: str, scope: Sequence[str], line: int) -> None:
        """One ``Store`` of the name in the namespace that encloses it."""
        if namespace == _FUNCTION_NS:
            return  # a local: private to the function, not a symbol
        if namespace == _CLASS_NS:
            found.append(("field", qualified(scope, IS_NULL), line))
        else:
            found.append(("module", IS_NULL, line))

    def visit(
        node: ast.AST,
        scope: tuple[str, ...],
        namespace: str,
        declared_global: frozenset[str],
    ) -> None:
        for child in ast.iter_child_nodes(node):
            # The scope the child's own descendants are walked in.  Only a
            # function, lambda, comprehension or class changes it; every
            # other node's subtree stays in this node's namespace, which is
            # what makes the walk scope-faithful: a ``for`` target at a
            # module body, a ``with`` alias, a walrus and a match capture
            # are stores in whatever namespace textually encloses them.
            next_scope, next_ns, next_global = scope, namespace, declared_global
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name == IS_NULL:
                    if namespace == _CLASS_NS:
                        found.append(("method", qualified(scope, IS_NULL), child.lineno))
                    elif namespace == _MODULE_NS:
                        found.append(("function", IS_NULL, child.lineno))
                    # inside a function the def binds a local name: not a symbol
                for argument in _parameters_of(child.args):
                    if argument.arg == IS_NULL:
                        found.append(
                            (
                                "parameter",
                                qualified((*scope, child.name), IS_NULL),
                                child.lineno,
                            )
                        )
                next_scope, next_ns, next_global = (
                    (*scope, child.name),
                    _FUNCTION_NS,
                    _own_globals(child),
                )
            elif isinstance(child, ast.ClassDef):
                if child.name == IS_NULL and namespace != _FUNCTION_NS:
                    found.append(("class", qualified(scope, IS_NULL), child.lineno))
                next_scope, next_ns, next_global = (*scope, child.name), _CLASS_NS, frozenset()
            elif isinstance(child, ast.Lambda):
                for argument in _parameters_of(child.args):
                    if argument.arg == IS_NULL:
                        found.append(
                            (
                                "parameter",
                                qualified((*scope, _LAMBDA), IS_NULL),
                                child.lineno,
                            )
                        )
                next_scope, next_ns, next_global = (*scope, _LAMBDA), _FUNCTION_NS, frozenset()
            elif isinstance(
                child,
                (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
            ):
                # A comprehension is a scope of its own: its targets are as
                # private as any local, even at a module body.
                next_scope, next_ns, next_global = (*scope, _COMP), _FUNCTION_NS, frozenset()
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    if bound == IS_NULL:
                        if namespace == _CLASS_NS:
                            found.append(("field", qualified(scope, IS_NULL), child.lineno))
                        elif namespace == _MODULE_NS:
                            found.append(("import", IS_NULL, child.lineno))
                        # inside a function the import binds a local: not a symbol
            elif isinstance(child, ast.Name) and child.id == IS_NULL:
                if isinstance(child.ctx, ast.Store):
                    if namespace == _FUNCTION_NS:
                        if IS_NULL in declared_global:
                            found.append(("global", IS_NULL, child.lineno))
                        # otherwise a local: private, not a symbol
                    else:
                        store_in(namespace, scope, child.lineno)
            elif isinstance(child, ast.Attribute) and child.attr == IS_NULL:
                if isinstance(child.ctx, ast.Store):
                    # An attribute store binds the object, not the scope it
                    # sits in: the instance carries the name out of the
                    # function that set it, so it is reachable wherever the
                    # store is.  The target is spelled out (``self.is_null``)
                    # because the object's class is not statically known.
                    found.append(
                        ("attribute", f"{ast.unparse(child.value)}.{IS_NULL}", child.lineno)
                    )
            elif isinstance(child, (ast.MatchAs, ast.MatchStar, ast.ExceptHandler)):
                # A match-pattern capture and an ``except`` alias are stores
                # in whatever namespace textually encloses them — private as
                # locals, published as module or class bindings.
                if child.name == IS_NULL:
                    store_in(namespace, scope, child.lineno)
            visit(child, next_scope, next_ns, next_global)

    visit(tree, (), _MODULE_NS, frozenset())
    return tuple(dict.fromkeys(found))


def module_refusal(member: str, source: str, module: str = "<source>") -> tuple[Finding, ...]:
    """The findings one shipped module refuses the merge for.

    Empty when ``member`` is one of :data:`SCORER_PACKAGES` — the sentence
    refuses the name *outside* the scorer's packages, and the inside is
    §4.2's grant (the homes' own interiors are audited as standing state in
    the class below, not refused here).  Otherwise every reachable binding
    :func:`reachable_bindings` reads is a finding, each named with the
    member, the module, the kind, the qualified name and the line.
    """
    if member in SCORER_PACKAGES:
        return ()
    return tuple(
        sorted(
            (member, module, kind, name, line)
            for kind, name, line in reachable_bindings(source, module)
        )
    )


def production_modules() -> tuple[tuple[str, str, str], ...]:
    """Every ``(member, module, source)`` a merge ships — the gate's subject.

    The application layer (``src/``) first, then every member the loader's
    own workspace declaration resolves, each walked at the root the module
    loader scans for it — ``packages/<name>/src`` for a src-layout member,
    the member directory itself for a flat one (the loader scans the parent
    so flat and src layouts interoperate at import time; the audit
    attributes the member its own directory, because ownership — not
    import mechanics — is what the exemption keys on).  The subject follows
    the declaration rather than a hard-coded list for the reason the
    suite's conftest states: a list here could quietly disagree with the
    loader and audit a tree production would never compose.  Members'
    test trees are not walked: they are not composed, and the null-oracle
    member's own suite legitimately builds §7.1 records; ``bench/`` and
    ``infra/`` are not composed either, and the migration tree is SQL —
    the *column* on the tree store is feature 110's subject, not this
    gate's.
    """
    modules: dict[tuple[str, str], str] = {}

    def harvest(member: str, root: Path) -> None:
        for path in sorted(root.rglob("*.py")):
            modules[(member, str(path.relative_to(REPO_ROOT)))] = path.read_text(
                encoding="utf-8"
            )

    harvest(APP_MEMBER, REPO_ROOT / "src")
    for member_directory in workspace_members(LOADER):
        src = member_directory / "src"
        harvest(member_directory.name, src if src.is_dir() else member_directory)
    return tuple(
        (member, module, source) for (member, module), source in sorted(modules.items())
    )


def merge_refusal(modules: Iterable[tuple[str, str, str]] | None = None) -> tuple[Finding, ...]:
    """The gate itself: every reachable ``is_null`` symbol outside the two
    homes, over the production source a merge ships.

    The merge-time form of feature 354's sentence.  Empty means no symbol
    of the name is reachable outside :data:`SCORER_PACKAGES` and the merge
    stands.  Every finding names the member, the module, the binding kind,
    the qualified name and the line, sorted, so the refusal is
    deterministic and the operator reads the break off the source rather
    than re-deriving it.  Computed from the source as data — nothing is
    imported, opened as a connection, or run.
    """
    if modules is None:
        modules = production_modules()
    findings: list[Finding] = []
    for member, module, source in modules:
        findings.extend(module_refusal(member, source, module))
    return tuple(sorted(findings))


def shipped_module(member: str, relative: str) -> tuple[str, str, str]:
    """One shipped module as the gate's subject tuple — the composition the
    refused-class tests below build their hostile merges from.

    Reads the repository's own file (a missing one fails with the path in
    the message, the same discipline the ledger gate loads its migration
    with), so a test's "the shipped module plus one hostile line" judges
    the code that actually ships rather than a fixture that happens to
    share its shape.
    """
    path = REPO_ROOT / relative
    if not path.is_file():
        raise AssertionError(
            f"{relative} is not at {path}; this test holds the gate against "
            "the shipped module it names, so it needs the file to be where "
            "the tree keeps it"
        )
    return member, relative, path.read_text(encoding="utf-8")


def shipped_source(member: str, relative: str) -> str:
    """One shipped module's source, on its own — for the stands-class
    witnesses that read a single file's bindings."""
    return shipped_module(member, relative)[2]


# ── The gate reads the source the merge ships ────────────────────────────────


class TestTheGateReadsTheSourceTheMergeShips:
    """The subject is the loader's own declaration; the judgement is a pure
    function of a member and a source; code that does not parse is refused,
    never skipped."""

    def test_the_subject_is_the_loaders_own_declaration(self) -> None:
        # The audited members are exactly the workspace's declaration plus
        # the application layer — read through workspace_members(), the same
        # resolver the module loader composes with, never a hard-coded list.
        # A member the declaration adds is audited from its first merge, and
        # a member it removes takes its exemption with it if it had one.
        declared = frozenset(member.name for member in workspace_members(LOADER))
        subject = frozenset(member for member, _, _ in production_modules())
        assert subject == declared | {APP_MEMBER}

    def test_the_two_homes_are_declared_members_that_ship_source(self) -> None:
        # The exemption is keyed on declared member identities, so a merge
        # that renamed or deleted a home trips this pin rather than letting
        # the audit sweep a name that no longer resolves.  Both homes carry
        # modules, too — an exempt member with no source would be an
        # exemption over nothing, and the stands-class audit below could
        # not witness it.
        declared = frozenset(member.name for member in workspace_members(LOADER))
        subject = frozenset(member for member, _, _ in production_modules())
        assert SCORER_PACKAGES <= declared
        assert SCORER_PACKAGES <= subject

    def test_the_app_tree_is_subject_and_never_exempt(self) -> None:
        # The seats compose the components; they are not the components.
        # The scorer's app seat sits under a path spelled "scoring" and is
        # still judged: the exemption is the declared member, not a string
        # on a path, and a gate keying on the path would wave the seat's
        # own leak through.  The shipped seat carries no symbol — standing
        # state — and the hostile line below is refused under the
        # application layer's own member identity.
        seat = "src/app/modules/scoring/scorer.py"
        source = shipped_source(APP_MEMBER, seat)
        assert module_refusal(APP_MEMBER, source, seat) == ()
        line = source.count("\n") + 2  # the appended module-level flag's line
        hostile = (APP_MEMBER, seat, source + "\nis_null = False  # for the dashboard\n")
        assert merge_refusal([hostile]) == ((APP_MEMBER, seat, "module", IS_NULL, line),)

    def test_a_module_that_does_not_parse_is_refused(self) -> None:
        # A merge gate judges the code a merge ships; code it cannot read is
        # code it cannot bless.  A production module that fails to parse
        # fails the gate loudly, naming the module — never silently skipped,
        # because a skip would pass for a merge that shipped anything.
        with pytest.raises(AssertionError, match="weird_module.py does not parse"):
            reachable_bindings("def broken(:\n", "weird_module.py")

    def test_the_judgement_is_a_pure_function_of_its_subject(self) -> None:
        # The evaluators' inputs are a member and a source and nothing
        # else — the same static discipline the ledger and provenance gates
        # apply to theirs.  Nothing that could open, drive or settle a
        # connection appears in the judgement: a gate that had to import or
        # run the system to judge it would be an audit after the leak, and
        # importing the tree is exactly what a poisoned symbol waits for.
        for evaluator in (reachable_bindings, module_refusal, merge_refusal):
            tree = ast.parse(inspect.getsource(evaluator))
            database_names = [
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr
                in {
                    "connect",
                    "cursor",
                    "execute",
                    "executescript",
                    "commit",
                    "rollback",
                }
            ]
            assert database_names == [], evaluator.__name__

    def test_the_kinds_are_the_nine_spellings_of_a_symbol(self) -> None:
        # The first term's vocabulary, stated as data once, and the shipped
        # tree's bindings read only from it — so a spelling the walk gains
        # without a kind here, or a kind with no spelling, fails rather
        # than drifts.  Every kind is refused somewhere in the refused
        # class below; the pin here is that the two halves cannot disagree.
        seen = {
            kind
            for _, module, source in production_modules()
            for kind, _, _ in reachable_bindings(source, module)
        }
        assert seen <= set(BINDING_KINDS)
        assert BINDING_KINDS == (
            "module",
            "field",
            "class",
            "method",
            "function",
            "parameter",
            "import",
            "global",
            "attribute",
        )


# ── A merge whose bit stays home stands ──────────────────────────────────────


class TestAMergeWhoseBitStaysHomeStands:
    """The tree as it ships names no reachable ``is_null`` symbol outside the
    two homes — and inside them, exactly the symbols the spec itself spells."""

    def test_no_symbol_is_reachable_outside_the_two_homes(self) -> None:
        # The load-bearing stands case: over every production module the
        # loader declares — the application layer and every member — the
        # gate names nothing.  The merge stands by construction, and this
        # is the fact every refused case below is a mutation of.
        assert merge_refusal() == ()

    def test_the_null_oracle_holds_exactly_the_schema_s_field(self) -> None:
        # The homes' audit, first half: the null-oracle member's one
        # reachable symbol of the name is §7.1's own — NullAssignment's
        # ``is_null``, the sealed schema's spelling, the field the sidecar's
        # bytes carry under the same key.  The exemption is not a wildcard
        # over the member: a second symbol there (a diagnostic, a cache, an
        # accessor the oracle grew) fails this witness and is looked at,
        # because every symbol past the schema's one is a surface the
        # sealed file never needed.
        assignment = "packages/nulloracle/src/nulloracle/assignment.py"
        assert reachable_bindings(shipped_source("nulloracle", assignment), assignment) == (
            ("field", "NullAssignment.is_null", 215),
        )

    def test_the_scorer_member_exposes_no_symbol_at_all(self) -> None:
        # The homes' audit, second half: the scoring member ships *no*
        # reachable symbol of the name, not one.  "The number flows out;
        # the labels do not" (docs §10.3) is the scorer's own design — no
        # accessor for the held sidecar, no label cache (feature 265's
        # words) — and the member's reads are locals: the rate is the only
        # thing that crosses the process boundary.  Pinned as standing
        # state, so a scorer that grew a symbol of the name is seen here
        # even though the sentence would not refuse it.
        scorer_modules = [
            (module, source)
            for member, module, source in production_modules()
            if member == "scoring"
        ]
        assert scorer_modules  # the member ships source; the audit has a subject
        for module, source in scorer_modules:
            assert reachable_bindings(source, module) == (), module

    def test_the_oracles_route_reads_the_bit_into_a_local(self) -> None:
        # The oracle's own serving route resolves §7.2's branch — the one
        # computation the member exists for — and it does it with a local:
        # ``is_null = self._is_null(...)`` inside ``post``, "read here and
        # carried no further", the module's own comment.  The private
        # ``_is_null`` helper is a near-miss of the name and another symbol
        # entirely.  A member of the homes standing does not rest on the
        # exemption alone: the route ships no symbol either, and a reader
        # can check the discipline without decrypting anything.
        target = "packages/nulloracle/src/nulloracle/target.py"
        source = shipped_source("nulloracle", target)
        assert reachable_bindings(source, target) == ()
        # …and the near-misses the module really carries are present, so
        # the empty reading above is the gate judging a tree that carries
        # the spelling, not a tree that forgot it.
        assert "def _is_null(" in source
        assert "is_null = getattr(assignment" in source

    def test_the_surfaces_the_barrier_names_carry_no_symbol(self) -> None:
        # §4.2's four surfaces, restated as the members that own them: the
        # discovery agent's context (discovery), the policy's prefix
        # (policy-runtime), the stored artifacts a replay reads (snapshot,
        # feature-store, artifacts) and the logs a policy-development agent
        # scans (dreaming).  Each member's modules are named here in their
        # own right, because the global stands case is the conjunction of
        # exactly these — the sentence's "outside the scorer package" is
        # these packages, and each one ships no symbol.
        for named in (
            "discovery",
            "policy-runtime",
            "snapshot",
            "feature-store",
            "artifacts",
            "dreaming",
        ):
            member_modules = [
                (module, source)
                for member, module, source in production_modules()
                if member == named
            ]
            assert member_modules, named  # a surface with no source is a pin on nothing
            for module, source in member_modules:
                assert module_refusal(named, source, module) == (), module

    def test_the_leak_detectors_own_local_stands(self) -> None:
        # The tripwires member — the leak *detector* — computes its triage
        # AUC over two caller-handed populations, and the class marker
        # inside the statistic's tie-handling is a comprehension target:
        # ``1.0 if is_null else 0.0 for _, is_null in …``.  A scope of its
        # own, private to the expression — the caller's own labels folded
        # into a rank sum, never the sealed bit.  The tree ships the name
        # there today and the gate names nothing, which is the locals rule
        # holding in a non-exempt member rather than only inside the homes.
        triage = "packages/tripwires/src/tripwires/triage.py"
        source = shipped_source("tripwires", triage)
        assert reachable_bindings(source, triage) == ()
        assert "if is_null else" in source


# ── A merge that ships the name outside the homes is refused ─────────────────


class TestAMergeThatShipsTheNameOutsideTheHomesIsRefused:
    """Any binding of the name, in any of the nine spellings, in any member
    the bit may not live in — the merge is refused and the refusal names
    the member, the module, the kind and the symbol."""

    def test_a_debug_flag_at_module_level_is_refused(self) -> None:
        # The quiet drift: a module-level flag "for the dashboard", the
        # shape every leak actually arrives in.  The refusal names the
        # member, the module, the kind and the line, so the operator reads
        # the break off the source.
        hostile = ("ops", "ops/metrics.py", "is_null = False  # for the dashboard\n")
        assert merge_refusal([hostile]) == (
            ("ops", "ops/metrics.py", "module", IS_NULL, 1),
        )

    def test_the_policy_observation_gaining_the_field_is_refused(self) -> None:
        # The canonical leak, in the record whose own docstring promises it
        # never carries the bit: "never ``is_null`` (readable by exactly one
        # component, the replay scorer — prd §4.2, cq-8)".  A merge that
        # adds the field breaks that promise and this gate refuses it —
        # the hidden section of prd §6.1's schema is the scorer's, not the
        # observation's.
        hostile = (
            "from dataclasses import dataclass\n"
            "\n"
            "\n"
            "@dataclass(frozen=True)\n"
            "class PolicyObservation:\n"
            "    node_id: str\n"
            "    r2_insample: float | None\n"
            "    ic_insample: float | None\n"
            "    is_null: bool\n"
            "    n_periods: int | None\n"
            "    n_features: int | None\n"
        )
        assert merge_refusal(
            [("policy-runtime", "policy_runtime/__init__.py", hostile)]
        ) == (
            ("policy-runtime", "policy_runtime/__init__.py", "field", "PolicyObservation.is_null", 9),
        )

    @pytest.mark.parametrize(
        ("spelling", "kind"),
        [
            ("    is_null: bool\n", "field"),
            ("    is_null: bool = False\n", "field"),
            ("    is_null = False\n", "field"),
        ],
    )
    def test_every_class_body_spelling_of_the_field_is_refused(
        self, spelling: str, kind: str
    ) -> None:
        # A dataclass annotation, a defaulted annotation and a plain class
        # attribute are the one binding spelled three ways — a class body
        # store — and each refuses the merge as a ``field``, because the
        # holder of any instance can read all three.  TypedDict and
        # NamedTuple arrive as the same annotation the dataclass does, and
        # an enum member as the same plain store, which is why they need
        # no cases of their own.
        hostile = "class Record:\n" + spelling + "    node_id: str\n"
        assert merge_refusal([("snapshot", "snapshot/record.py", hostile)]) == (
            ("snapshot", "snapshot/record.py", kind, "Record.is_null", 2),
        )

    def test_a_property_a_record_grows_is_refused_as_a_method(self) -> None:
        # The accessor shape: a ``@property`` named for the bit is a method
        # binding, and the refusal says so — a record that *computes* the
        # name is a record that publishes it.
        hostile = (
            "class NodeRecord:\n"
            "    @property\n"
            "    def is_null(self) -> bool:\n"
            "        return False\n"
        )
        assert merge_refusal([("artifacts", "artifacts/node.py", hostile)]) == (
            ("artifacts", "artifacts/node.py", "method", "NodeRecord.is_null", 3),
        )

    def test_a_plain_function_named_for_the_bit_is_refused(self) -> None:
        # The helper nobody asked for: a module-level predicate whose name
        # is the bit's.  The finding is the ``function`` binding — the name
        # an importer can call — not the body it wraps.
        hostile = "def is_null(node_id: str) -> bool:\n    return False\n"
        assert merge_refusal([("universe", "universe/labels.py", hostile)]) == (
            ("universe", "universe/labels.py", "function", IS_NULL, 1),
        )

    def test_a_class_named_for_the_bit_is_refused(self) -> None:
        # The name as a type: a class whose *name* is the bit's binds the
        # module's namespace just as surely as a flag does, and annotating
        # a parameter with it spells the leak into every signature that
        # uses it.
        hostile = "class is_null:\n    pass\n"
        assert merge_refusal([("promotion", "promotion/marks.py", hostile)]) == (
            ("promotion", "promotion/marks.py", "class", IS_NULL, 1),
        )

    def test_a_keyword_parameter_is_refused(self) -> None:
        # A callable's keyword is part of its interface — the word a caller
        # spells and ``inspect.signature`` publishes.  Judged for a private
        # helper exactly as for a public verb, because the merge shipped
        # the name as an interface the moment it shipped the keyword.
        hostile = (
            "def label(entry, *, is_null: bool = False) -> float:\n"
            "    return 0.0 if is_null else entry\n"
        )
        assert merge_refusal([("evaluator", "evaluator/label.py", hostile)]) == (
            ("evaluator", "evaluator/label.py", "parameter", f"label.{IS_NULL}", 1),
        )

    def test_an_import_binding_is_the_smuggling_shape_and_is_refused(self) -> None:
        # The one spelling that moves the *schema's own* symbol outward:
        # importing under the name binds ``is_null`` in the importing
        # module's namespace, and the merge that ships it has made the
        # sealed file's field an ordinary attribute of a non-exempt module.
        # Lawful inside the homes (the scope class below pins that); a leak
        # everywhere else.
        hostile = "from nulloracle import NullAssignment as is_null\n"
        assert merge_refusal([("book", "book/hints.py", hostile)]) == (
            ("book", "book/hints.py", "import", IS_NULL, 1),
        )

    def test_a_module_level_loop_target_is_refused(self) -> None:
        # The store a grep might excuse: a ``for`` target at a module body
        # binds the module's namespace exactly as an assignment does — the
        # loop the loader runs is the loop that publishes the name.
        hostile = "labels = {}\nfor is_null in ():\n    pass\n"
        assert merge_refusal([("regime", "regime/walk.py", hostile)]) == (
            ("regime", "regime/walk.py", "module", IS_NULL, 2),
        )

    def test_a_global_statement_reopens_the_module_and_is_refused(self) -> None:
        # ``global is_null`` is a store in the function's clothing: the
        # declaration re-opens the module namespace, and the store binds a
        # module attribute any importer reads.  The refusal names the
        # ``global`` kind, so the operator sees which spelling hid it.
        hostile = "def _load():\n    global is_null\n    is_null = True\n"
        assert merge_refusal([("router", "router/config.py", hostile)]) == (
            ("router", "router/config.py", "global", IS_NULL, 3),
        )

    def test_an_attribute_store_is_refused_wherever_it_sits(self) -> None:
        # A field a class never declared: ``self.is_null = value`` binds
        # the *object*, not the function it sits in, and the instance
        # carries the name out of the method that set it.  The refusal
        # spells the target (``self.is_null``) because the object's class
        # is not statically known — the operator greps the store, not a
        # declaration that does not exist.
        hostile = (
            "class Cache:\n"
            "    def remember(self, entry):\n"
            "        self.is_null = getattr(entry, 'is_null', False)\n"
        )
        assert merge_refusal([("replay", "replay/cache.py", hostile)]) == (
            ("replay", "replay/cache.py", "attribute", f"self.{IS_NULL}", 3),
        )

    def test_the_shipped_policy_runtime_plus_one_hostile_line_is_refused(self) -> None:
        # The load-bearing regression case: the gate catches a future edit
        # to a real module.  The policy runtime's own __init__ — the module
        # PolicyObservation lives in — plus one appended line is refused,
        # because a finding anywhere in a shipped module refuses the merge
        # that ships the module, not only the modules a fixture invented.
        member, module, source = shipped_module(
            "policy-runtime", "packages/policy-runtime/src/policy_runtime/__init__.py"
        )
        hostile = (
            member,
            module,
            source + "\nis_null = False  # temporary, for a bug report\n",
        )
        assert merge_refusal([hostile]) == (
            (member, module, "module", IS_NULL, source.count("\n") + 2),
        )

    def test_the_shipped_app_seat_plus_one_hostile_line_is_refused(self) -> None:
        # The mirror of the homes' exemption, stated as a refusal: the
        # scorer's app seat — a module whose path is spelled "scoring" — is
        # refused the moment it grows the name, because the exemption is
        # the declared member and the seat is the application layer.  A
        # gate keyed on path substrings would wave this through.
        member, module, source = shipped_module(APP_MEMBER, "src/app/modules/scoring/scorer.py")
        hostile = (member, module, source + "\nis_null = None\n")
        assert merge_refusal([hostile]) == (
            (member, module, "module", IS_NULL, source.count("\n") + 2),
        )


# ── The finding is exactly the name and nothing else ─────────────────────────


class TestTheFindingIsExactlyTheNameAndNothingElse:
    """The gate refuses exactly a binding of the name ``is_null`` outside the
    two homes — never a near-miss, never a string, never a case variant,
    never a local, never a use, and never the homes' own interiors."""

    def test_near_miss_names_are_other_symbols(self) -> None:
        # Exactly as wide as the sentence: ``is_null_root`` is the
        # selection's lawful verb (a public method the shipped tree
        # carries), and ``_is_null`` is the oracle's private helper.  A
        # gate that widened itself to substrings would refuse the shipped
        # code the spec itself spells — the same discipline the tree
        # store's guard states for its near-miss columns.
        selection = "packages/nulloracle/src/nulloracle/selection.py"
        source = shipped_source("nulloracle", selection)
        assert "def is_null_root(" in source  # the near-miss is really there
        assert reachable_bindings(source, selection) == ()

    def test_a_string_is_data_not_a_symbol(self) -> None:
        # The tree ships the *spelling* lawfully in a dozen places, and two
        # of them are refusals in their own right: the tree store's guard
        # holds ``FORBIDDEN_COLUMN = "is_null"`` — the constant's name is
        # FORBIDDEN_COLUMN, its value the word the guard refuses — and the
        # discovery member's planning context carries "is_null" inside the
        # vocabulary it exists to forbid.  Neither binds the name; both are
        # the barrier spelled as a refusal, and the gate refuses symbols,
        # not mentions.
        schemaguard = "packages/nulloracle/src/nulloracle/schemaguard.py"
        guard_source = shipped_source("nulloracle", schemaguard)
        assert 'FORBIDDEN_COLUMN = "is_null"' in guard_source
        assert reachable_bindings(guard_source, schemaguard) == ()

        planner = "packages/discovery/src/discovery/planner.py"
        planner_source = shipped_source("discovery", planner)
        assert '"is_null",' in planner_source  # a non-exempt member naming it to refuse it
        assert reachable_bindings(planner_source, planner) == ()

    def test_the_uppercase_spelling_is_another_symbol(self) -> None:
        # Python resolves attribute names case-sensitively, so ``IS_NULL``
        # is a different symbol — where the tree store's guard casefolds
        # because SQLite's columns do not ("``IS_NULL`` is ``is_null`` in
        # every query", its own docstring).  A merge that ships the
        # uppercase name is not this sentence's finding; it is also not a
        # leak, because no reader of the bit resolves attributes by folding
        # case.  The audit is exact, like the name.
        hostile = "IS_NULL: bool = False\n"
        assert merge_refusal([("ledger", "ledger/constants.py", hostile)]) == ()

    def test_a_local_variable_is_private_and_stands(self) -> None:
        # The locals rule, stated over the scorer's own idiom: a function's
        # stores bind a namespace no other code can name, and the shipped
        # tree leans on that twice inside the homes and once outside them
        # (the tripwires witness in the stands class).  A merge could ship
        # a local named ``is_null`` in any member and this gate would not
        # refuse it — the *value* may not cross a seam, but that is §4.2's
        # runtime face; the *name* never became reachable.
        hostile = (
            "def label(entry):\n"
            "    is_null = getattr(entry, 'is_null', None)\n"
            "    return 0.0 if is_null else 1.0\n"
        )
        assert merge_refusal([("ops", "ops/label.py", hostile)]) == ()

    def test_a_comprehension_target_and_an_alias_are_private(self) -> None:
        # Scopes of their own: a comprehension's targets bind its implicit
        # scope even at a module body, and a ``with``/``except`` alias
        # inside a function is a local.  The grammar offers no shortage of
        # private spellings, and none of them is a symbol.
        hostile = (
            "sums = [1.0 if is_null else 0.0 for _, is_null in pairs]\n"
            "\n"
            "\n"
            "def read(stream):\n"
            "    with stream as is_null:\n"
            "        pass\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError as is_null:\n"
            "        pass\n"
        )
        assert merge_refusal([("sandbox", "sandbox/scan.py", hostile)]) == ()

    def test_a_call_site_keyword_is_judged_at_the_callee(self) -> None:
        # A use, not a binding: a call-site keyword names the callee's
        # parameter, and the parameter is judged where it is defined — one
        # finding per symbol, never one per mention.  The shape here is the
        # null-oracle member's own (feature 122's writers construct §7.1's
        # records with ``is_null=``), and a gate that counted mentions
        # would refuse the writer that seals the bit away.
        hostile = (
            "from nulloracle import NullAssignment\n"
            "\n"
            "assignment = NullAssignment(\n"
            "    node_id='00000000-0000-4000-8000-000000000000',\n"
            "    is_null=True,\n"
            "    perm_seed=7,\n"
            ")\n"
        )
        assert merge_refusal([("bootstrap", "bootstrap/plant.py", hostile)]) == ()

    def test_a_string_keyed_getattr_reaches_a_judged_binding(self) -> None:
        # The scorer's own read, shipped outside the homes: a ``getattr``
        # by string reaches the schema's field, which is judged where it
        # lives (``NullAssignment.is_null``, inside the home, pinned in the
        # stands class).  The gate refuses the bindings a merge ships, not
        # the uses it makes of bindings already judged — a use-audit would
        # be a different, unbounded sentence, and the duck-read here is
        # exactly the seam the scorer's process is documented to use.
        hostile = "value = getattr(entry, 'is_null', None)\n"
        assert merge_refusal([("canary", "canary/probe.py", hostile)]) == ()

    def test_payload_keys_and_docstrings_are_data(self) -> None:
        # The sealed bytes' own key is a string in a dict, the payload the
        # sidecar encrypts — §7.1's spelling again, as data.  Docstrings
        # mention the bit throughout the shipped tree (this file among
        # them), and the gate has never counted a word: the finding is a
        # binding, and text is not one.
        hostile = (
            '"""A record whose docstring says is_null many times. is_null."""\n'
            "PAYLOAD = {'is_null': True}\n"
            "__all__ = ['is_null']\n"
        )
        assert merge_refusal([("providers", "providers/schema.py", hostile)]) == ()

    def test_the_homes_own_interiors_are_not_this_gates_finding(self) -> None:
        # The sentence refuses the name *outside* the scorer's packages;
        # the inside is §4.2's grant to the one component.  A field, a
        # method, a flag and an import inside either home are lawful by the
        # sentence this gate enforces — pinned here so the gate is sound
        # against the venue by construction, and so narrowing the exemption
        # is a change somebody argues for in this file, not a silent one.
        interior = (
            "from nulloracle import NullAssignment as is_null\n"
            "\n"
            "is_null = True\n"
            "\n"
            "\n"
            "class Entry:\n"
            "    is_null: bool\n"
            "\n"
            "    def is_null(self) -> bool:  # a shadowing method, still inside\n"
            "        return False\n"
        )
        for home in sorted(SCORER_PACKAGES):
            assert merge_refusal([(home, f"{home}/interior.py", interior)]) == (), home


# ── The refusal is a named, sorted, total reading ────────────────────────────


class TestTheRefusalIsNamedSortedAndTotal:
    """Every finding carries the member, module, kind, symbol and line, in a
    deterministic order, over a subject with no gaps."""

    def test_every_finding_names_all_five_facts(self) -> None:
        # The operator-facing form: a refusal that named only the module
        # would send the reader hunting for the binding.  Each finding is
        # (member, module, kind, symbol, line) — the member whose exemption
        # was asked about, the module that ships the symbol, the spelling
        # it shipped, the qualified name and the line it binds on.
        hostile = "is_null = False\n\n\nclass Record:\n    is_null: bool\n"
        findings = merge_refusal([("dreaming", "dreaming/state.py", hostile)])
        assert findings == (
            ("dreaming", "dreaming/state.py", "field", "Record.is_null", 5),
            ("dreaming", "dreaming/state.py", "module", IS_NULL, 1),
        )

    def test_the_findings_are_sorted_so_the_refusal_is_deterministic(self) -> None:
        # Sorted by the whole tuple, so two runs of the gate over the same
        # merge name the same break in the same order — the discipline the
        # ledger gate gives its collisions and the provenance gate its
        # gaps.  The record's field and the module's own store are both
        # named, and the field reads first.
        hostile = (
            "class Record:\n"
            "    is_null: bool\n"
            "\n"
            "def is_null(node_id):\n"
            "    return False\n"
        )
        findings = merge_refusal([("signal-agent", "signal_agent/labels.py", hostile)])
        assert findings == tuple(sorted(findings))
        assert len(findings) == 2
        assert findings[0][2] == "field"
        assert findings[1][2] == "function"

    def test_the_subject_leaves_no_member_unaudited(self) -> None:
        # Total over the subject: every member the loader declares ships
        # modules and is audited, the application layer beside them, so
        # there is no member whose merge could arrive unaudited and no
        # exemption that is not also an audited identity.  The stands pass
        # already parsed every one of those modules — an unparseable
        # module is refused loudly, pinned above.
        declared = frozenset(member.name for member in workspace_members(LOADER)) | {APP_MEMBER}
        audited = frozenset(member for member, _, _ in production_modules())
        assert audited == declared
