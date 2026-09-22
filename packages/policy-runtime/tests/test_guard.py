"""Feature 225, the runtime guard — a running policy reaches no file and no
module outside the ceiling.

app_spec.xml, "Exploration Policy Runtime", feature 225 (``depends_on=223``):
*System rejects filesystem access from the policy runtime plus any import
outside the configured allowlist.*  The sentence the tests below pin is
docs/nullius-tech-architecture.md §10.2's, stated as law:

    The policy runtime additionally blocks: ``question.best_so_far``,
    ``question.budget_spent``, filesystem access, and any import outside an
    allowlist.

The two halves are one feature's and are tested as one, because the *reason*
they are one feature is the claim most worth pinning: neither channel can see
both halves.  The filesystem half has to be an audit hook — a refusal that
lands before the operation runs — and the import half has to be a wrap of
:func:`builtins.__import__`, because a module already in :data:`sys.modules`
raises no audit event and calls no ``find_spec`` at all.  A guard built on
audit events alone would refuse ``import time`` and admit ``import os``, which
is the worst available failure mode for a barrier: the dangerous module is the
one most likely to be preloaded.  So the tests below pin *both* channels, and
they pin the cached imports separately from the fresh ones for exactly that
reason.

Three properties are worth stating because they are what make this an
enforcement rather than a decoration, and each has tests below:

* **the refusal lands before the effect.**  A policy's ``open`` is refused
  *and* the file is never touched; its import is refused *and* the module never
  loads.  A guard that refused afterwards would be a log line;
* **outside the extent, the interpreter is untouched.**  The application's own
  I/O — the factory's scan, the artifact store, the replay's own bookkeeping —
  and the test suite's own I/O run their files and imports exactly as before.
  The audit hook cannot be removed, so this is the property that keeps the
  install from being a global mutilation;
* **the ceiling is the deployment's, not this module's.**  ``covers`` answers
  from feature 167's committed ``sandbox-imports`` document, resolved through
  the workspace seat, so a deployment that widens the sandbox's allowlist
  widens the policy runtime's in the same edit — the two cannot drift into
  disagreeing about what a Z1 policy may import.

The policy under test is executed as a real module — registered in
:data:`sys.modules` under :data:`POLICY_MODULE_NAME` and ``exec``'d — rather
than as a def inside this file, because the guard's subject *is* that module
identity: the import half judges an import by ``globals["__name__"]``, so a
policy defined in a test function would be judged as a test.  The helper below
is therefore the fixture every test is written in: it is how a policy exists,
and naming it once keeps each test reading as a claim about the guard rather
than a construction of a module.
"""

from __future__ import annotations

import builtins
import os
import sys
import types

import pytest
from policy_runtime import (
    GUARD_ACTIVE,
    POLICY_MODULE_NAME,
    PolicyCeiling,
    PolicyFilesystemError,
    PolicyGuard,
    PolicyImportError,
    PolicyRuntimeError,
    guard_policy,
)

#: The canonical sanctioned policy: the modules the committed ceiling names,
#: imported the ways a real policy imports them — a plain import, a ``from``
#: import of a submodule, a ``from`` import of a name, and a decorator from a
#: ceiling term, which is how a real policy is written.  The ``choose``
#: function is a policy in miniature: it imports what it was allowed, it reads
#: the question through the one seam it has, it holds its answer in a dataclass,
#: and it reaches nothing else.  Every test that asserts the guard *admits*
#: something runs this, so "the guard admits a real policy" is one claim pinned
#: once — and the transitive loads it forces (``statistics`` importing
#: ``numbers``, which no ceiling names) are pinned here too, since the guard
#: must admit a policy for the interpreter's diligence as well as its own.
SANCTIONED_POLICY = """
import math
import statistics
import decimal
import fractions
import datetime
import itertools
import functools
import random

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class Choice:
    node: str
    score: float = 0.0


def choose(question):
    revealed = question.observed()
    ranked = OrderedDict()
    ranked["n2"] = Choice("n2", statistics.mean([1, 2, 3]))
    best = ranked["n2"]
    assert isinstance((best.node,), Sequence)
    return math.floor(best.score) + len(ranked) + len(revealed)
"""


def policy(
    source: str,
    name: str = POLICY_MODULE_NAME,
    namespace: dict | None = None,
) -> types.ModuleType:
    """Execute ``source`` as a module, and return it — how a policy exists here.

    The module is registered in :data:`sys.modules` under ``name`` before it
    runs, and that registration is load-bearing rather than tidiness: a policy's
    ``import`` statements pass ``globals["__name__"]`` to
    :func:`builtins.__import__`, so the name it runs under is the subject the
    guard judges it by, and a policy whose module were never registered would be
    a subject the guard could not name.  The same registration is what
    :mod:`dataclasses` looks up when a policy uses ``@dataclass``.

    A ``namespace`` is merged into the module's globals before execution, for
    the tests that need to hand a policy something to call.
    """
    module = types.ModuleType(name)
    if namespace:
        module.__dict__.update(namespace)
    sys.modules[name] = module
    exec(compile(source, "<policy>", "exec"), module.__dict__)  # noqa: S102
    return module


class FakeQuestion:
    """The one seam a policy has: ``observed()``, and nothing else.

    Deliberately minimal.  Feature 223's view is prefix-only and feature 224
    defends its attribute surface; this member's tests are about the *world*
    the policy runs in rather than the object it holds, so the question here is
    the smallest object that lets a policy be a policy — and, as a plain Python
    object rather than a :class:`~policy_runtime.PrefixView`, it keeps these
    tests independent of feature 223's construction.

    Its return *shape* is the real one, though, and that is deliberate rather
    than incidental: :meth:`PolicyQuestion.observed` reports the revealed cells
    as a mapping, not a count, so a policy written against this double is
    written against the interface it will actually be handed.  A double that
    returned a bare int would let a policy pass here and fail over a real
    question — which is exactly the failure this test module exists to avoid.
    """

    def __init__(self, observed: dict | None = None) -> None:
        self._observed = {"n0": {}, "n1": {}} if observed is None else observed

    def observed(self) -> dict:
        return self._observed


@pytest.fixture
def fake_question() -> FakeQuestion:
    # Named ``fake_question`` rather than ``question`` deliberately: the
    # conftest defines a ``question`` fixture over feature 223's real
    # ``PolicyQuestion``, and a same-named fixture in this module would shadow it
    # for every test here — the failure being a test that *looks* like it is
    # exercising the real question while silently holding this double.  Both are
    # useful and both are therefore named.
    return FakeQuestion()


# ---------------------------------------------------------------------------
# the law, in one piece: the sanctioned policy runs, a reaching one does not
# ---------------------------------------------------------------------------


def test_sanctioned_policy_runs_clean_inside_the_extent(
    fake_question: FakeQuestion,
) -> None:
    # The load-bearing negative: a guard that refused everything would satisfy
    # every refusal test below and be useless.  The canonical policy imports the
    # ceiling's modules, including the transitive loads those imports perform
    # (``statistics`` imports ``numbers``, which no ceiling names), and reaches
    # no file.  It must run.
    with guard_policy():
        module = policy(SANCTIONED_POLICY)
        # ``math.floor(mean([1, 2, 3]))`` is 2, the ranking holds the one cell
        # the policy ranked, and the double reports two revealed cells.
        assert module.choose(fake_question) == 2 + 1 + 2


def test_a_policy_runs_inside_the_extent_over_the_real_question(
    tree: object, question: object
) -> None:
    # The canonical test above uses this module's minimal ``FakeQuestion``, which
    # keeps it independent of feature 223's construction.  This one closes the
    # other half of the claim: the guard admits a *real* policy over the member's
    # own ``PolicyQuestion`` — the conftest's canonical tree, reached through the
    # same ``policy_question()`` the replay uses — so the guard is shown to sit
    # over the interface it is actually built for rather than over a test double.
    # The policy reads the question through ``observed()`` and reaches nothing
    # else, which is the whole of a permitted policy's surface.
    from policy_runtime import PolicyQuestion

    assert isinstance(question, PolicyQuestion)
    with guard_policy():
        module = policy(SANCTIONED_POLICY)
        assert module.choose(question) == 2 + 1 + len(question.observed())
    # And the same real question does not make a reaching policy admissible.
    reaching = "def choose(question):\n    return open('/etc/hostname').read()\n"
    with guard_policy():
        module = policy(reaching)
        with pytest.raises(PolicyFilesystemError):
            module.choose(FakeQuestion())


def test_sanctioned_policy_is_pure_and_repeatable(fake_question: FakeQuestion) -> None:
    # The guard must not be a state machine: the same policy run twice inside
    # the extent — the second time with every module it imports already cached,
    # the case the audit channel cannot see — gives the same answer.
    with guard_policy():
        module = policy(SANCTIONED_POLICY)
        assert module.choose(fake_question) == module.choose(fake_question)


def test_filesystem_access_is_refused_and_the_file_is_never_touched(tmp_path) -> None:
    # The refusal must land *before* the effect.  The policy opens a file that
    # exists and that it could read, so the only thing standing between it and
    # the bytes is the guard — and the guard's refusal is checked against a
    # sentinel the file's content would have replaced, so a guard that let the
    # read happen and refused afterwards fails this test.
    target = tmp_path / "revealed_by_other_means.txt"
    target.write_text("a node no reveal ever earned")
    policy_source = (
        "def choose(question):\n"
        f"    with open({str(target)!r}) as handle:\n"
        "        return handle.read()\n"
    )
    with guard_policy():
        module = policy(policy_source)
        with pytest.raises(PolicyFilesystemError) as refusal:
            module.choose(FakeQuestion())
    assert "a node no reveal ever earned" not in str(refusal.value)


def test_import_outside_the_ceiling_is_refused_and_the_module_never_loads() -> None:
    # The same "before the effect" claim for the import half, and it is checked
    # the way it can be checked: a module that does not exist is refused *for
    # the ceiling* rather than for its absence — ``PolicyImportError``, not
    # ``ModuleNotFoundError``.  The refusal is the ceiling's, so the module is
    # never looked for, which is what "the module never loads" means.
    source = "def choose(question):\n    import a_module_no_deployment_names\n"
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError):
            module.choose(FakeQuestion())


# ---------------------------------------------------------------------------
# the import half, and the finding it is built around: cached imports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "os",
        "sys",
        "pathlib",
        "subprocess",
        "socket",
        "shutil",
        "tempfile",
        "json",
        "time",
    ],
)
def test_cached_modules_are_refused(name: str) -> None:
    # **The test the whole design turns on.**  Every name here is already in
    # ``sys.modules`` when the policy imports it — the test suite itself
    # imported half of them at the top of this file — so the import executes as
    # a dictionary lookup with no audit event and no ``find_spec`` call.  A
    # guard built on the audit channel or on a meta-path finder admits every
    # one of these, silently, and admits ``os`` most silently of all.  They are
    # refused because the import half wraps ``builtins.__import__``, which every
    # spelling of an import goes through whether the module is cached or not.
    assert name in sys.modules, "the premise: this module is cached, not fresh"
    source = f"def choose(question):\n    import {name}\n    return {name}\n"
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError) as refusal:
            module.choose(FakeQuestion())
    assert name in str(refusal.value)


def test_a_freshly_loaded_module_is_refused_too() -> None:
    # And the uncached case, so the two are shown to be the *same* law rather
    # than one law plus a special case: a module this process has not loaded is
    # refused by the same check, at the same seam, with the same error.
    relative = "a_module_this_process_has_never_loaded"
    sys.modules.pop(relative, None)
    source = f"def choose(question):\n    import {relative}\n"
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError):
            module.choose(FakeQuestion())


@pytest.mark.parametrize(
    "spelling",
    [
        "return __import__('os')",
        "import importlib\n    return importlib.import_module('subprocess')",
        "import importlib\n    return getattr(importlib, 'import_' + 'module')('socket')",
        "from os import listdir\n    return listdir('/')",
    ],
)
def test_the_hiding_spellings_are_refused(spelling: str) -> None:
    # Feature 230 and 231 screen a policy's *source*, and feature 231's own
    # docstring states their honest limit: a policy that spells the loader
    # dynamically evades a static screen.  These are those spellings — a bare
    # ``__import__``, ``importlib.import_module``, the same reached through
    # ``getattr`` on a name built from strings.  None of them is a literal a
    # parser could refuse, and all of them are refused here, because every one
    # routes through the function the guard wrapped.  This is the gap feature
    # 225's sentence exists to close.
    source = f"def choose(question):\n    {spelling}\n"
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError):
            module.choose(FakeQuestion())


@pytest.mark.parametrize(
    "call",
    [
        "os.path.exists('pyproject.toml')",
        "os.stat('pyproject.toml')",
        "os.access('pyproject.toml', os.R_OK)",
        "os.readlink('/proc/self/cwd')",
    ],
)
def test_the_stat_family_is_unreachable_even_though_it_raises_no_event(
    call: str,
) -> None:
    # A fact about the audit channel that would be a hole in a one-channel
    # guard: CPython raises **no** audit event for ``os.stat``,
    # ``os.path.exists``, ``os.access`` or ``os.readlink`` — the metadata calls
    # the interpreter instruments least.  A guard built on the filesystem half
    # alone would let a policy *probe* the filesystem freely, learning which
    # paths exist and what they are, which is a reveal by other means even when
    # no bytes are read.
    #
    # It is not a hole here, and this test is the claim: the call needs ``os``
    # bound in the policy's own namespace, and the only ways to get it —
    # ``import os``, ``from os import ...``, a computed name, a bare
    # ``__import__`` — are all refused by the *import* half before the call can
    # be written.  The two halves cover each other's blind spots, which is the
    # argument for enforcing them as one feature rather than two.
    source = f"def choose(question):\n    import os\n    return {call}\n"
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError):
            module.choose(FakeQuestion())


def test_a_path_the_policy_computed_is_refused_like_a_literal_one() -> None:
    # §10.2's *"filesystem access from the policy runtime"* is about the reach,
    # not the spelling, and this is the case that makes it a runtime law rather
    # than a fifth static check: the path is assembled at run time out of pieces
    # no parser can join, so features 230/231 cannot see it and the audit
    # channel catches it at the call.  A policy that revealed a node id and
    # built a filename from it is refused exactly as one that wrote the literal.
    source = (
        "def choose(question):\n"
        "    path = '/' + 'etc' + '/' + 'hostname'\n"
        "    with open(path) as handle:\n"
        "        return handle.read()\n"
    )
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyFilesystemError):
            module.choose(FakeQuestion())


def test_a_relative_import_is_refused() -> None:
    # A submitted policy is one module, not a package with siblings — the same
    # reading feature 167's screen takes.  ``level`` is the third refusal rather
    # than a fallthrough, because a relative import resolves against the
    # policy's own package and the runtime has no siblings to offer: refusing it
    # as "outside the ceiling" would name the wrong reason.
    #
    # The policy calls the two-argument ``__import__`` form — the same call the
    # compiler emits for ``from . import sibling``, at the level CPython passes
    # for a single dot — so the *guard's* refusal is what is under test rather
    # than CPython's resolution of a synthetic package, which would fail first
    # with an ``ImportError`` of its own and hide the law behind an accident.
    source = (
        "def choose(question):\n"
        "    return __import__('sibling', globals(), locals(), ('sibling',), 1)\n"
    )
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError) as refusal:
            module.choose(FakeQuestion())
    assert "relative" in str(refusal.value)


def test_a_relative_import_names_the_dots_it_refused() -> None:
    # The detail is what an operator reads, so the refusal names the spelling
    # that was refused: a two-level relative import says ``..``, not ``.``.  A
    # refusal that said only "relative import refused" would leave the operator
    # re-reading the policy to find out which one.
    source = (
        "def choose(question):\n"
        "    return __import__('sibling', globals(), locals(), ('sibling',), 2)\n"
    )
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyImportError) as refusal:
            module.choose(FakeQuestion())
    assert "..'sibling'" in str(refusal.value)


def test_a_helper_the_runtime_hands_in_keeps_its_own_imports() -> None:
    # A policy does not import the runtime's helpers — they are handed in, as
    # the question is.  Such a helper performs its own imports under its own
    # module name, so those are not the policy's and are not judged: a caller
    # that supplies a scoring utility with its own dependencies must not have to
    # add them to the deployment's allowlist on the policy's behalf.
    helper = types.ModuleType("runtime_supplied_helper")
    sys.modules["runtime_supplied_helper"] = helper
    exec(  # noqa: S102 - the helper exists to be called, not to be imported
        compile(
            "import statistics\ndef score(xs):\n    return statistics.mean(xs)\n",
            "<helper>",
            "exec",
        ),
        helper.__dict__,
    )
    source = "def choose(question):\n    return score([1, 2, 3])\n"
    with guard_policy():
        module = policy(source, namespace={"score": helper.score})
        assert module.choose(FakeQuestion()) == 2


def test_a_helper_that_reaches_the_filesystem_is_refused_all_the_same() -> None:
    # The other half of the same boundary, and the reading of §10.2's *"from
    # the policy runtime"* that the guard takes: the filesystem half refuses
    # across the whole extent rather than only within the policy's own frames,
    # because "the policy caused it" is the honest reading and a frame rule
    # cannot tell a policy's own ``open`` from one a helper it called made.  The
    # consequence is stated in the module docstring rather than hidden: a
    # runtime that must persist during an episode does its I/O at the episode's
    # seams.
    helper = types.ModuleType("reaching_helper")
    sys.modules["reaching_helper"] = helper
    exec(  # noqa: S102 - a helper whose reach must be refused
        compile(
            "def peek():\n    return open('/etc/hostname').read()\n",
            "<helper>",
            "exec",
        ),
        helper.__dict__,
    )
    source = "def choose(question):\n    return peek()\n"
    with guard_policy():
        module = policy(source, namespace={"peek": helper.peek})
        with pytest.raises(PolicyFilesystemError):
            module.choose(FakeQuestion())


def test_a_sibling_module_is_not_caught_by_the_subject_rule() -> None:
    # The discrimination, from the other side: only the policy's *own* imports
    # are judged.  A module the policy calls performs its own imports under its
    # own name, and those are not the policy's — which is what lets a policy
    # import an allowlisted module whose dependencies are outside the ceiling.
    # ``statistics`` imports ``numbers``, and the ceiling names neither.
    source = (
        "import statistics\ndef choose(question):\n    return statistics.mean([1, 2])\n"
    )
    with guard_policy():
        module = policy(source)
        assert module.choose(FakeQuestion()) == 1.5


# ---------------------------------------------------------------------------
# the channels, and the two things each is chosen for
# ---------------------------------------------------------------------------


def test_the_audit_hook_is_installed_once_however_many_episodes_open() -> None:
    # CPython offers no way to *remove* an audit hook, so an install per episode
    # would judge every filesystem call once per episode ever opened — duplicate
    # refusals scattered through a run.  The install is therefore once per
    # process and the arming is per episode, and the flag is what says so.
    guard_policy().install()
    first = guard_policy().install()
    assert first.installed


def test_the_import_channel_is_a_wrap_and_delegates_when_dormant() -> None:
    # The import half is an *edit* to the interpreter, not an interposition, so
    # the property to pin is that it is transparent: off the extent it forwards
    # to the function it replaced, argument for argument.  A wrapper that
    # swallowed, cached or rewrote its arguments would be a change to importing
    # for the whole application.
    guard_policy().install()
    assert builtins.__import__ is not _ORIGINAL_IMPORT_AT_IMPORT
    # ``import collections.abc`` binds the *root* package, which is what
    # ``__import__`` returns and what the original returned before the wrap —
    # the wrap is transparent, so the same call gives the same object.
    assert __import__("collections.abc") is _ORIGINAL_IMPORT_AT_IMPORT(
        "collections.abc"
    )
    assert __import__("collections.abc") is sys.modules["collections"]


def test_nothing_is_refused_outside_the_extent(tmp_path) -> None:
    # **The property that keeps the install from being a global mutilation.**
    # The audit hook cannot be uninstalled and ``__import__`` is one function
    # for the interpreter, so the guard is *armed* per episode.  Outside every
    # extent this module's own test suite — and the factory's scan, and the
    # artifact store — must read its files and import its modules exactly as
    # before.
    guard_policy().install()
    target = tmp_path / "an_ordinary_file.txt"
    target.write_text("readable")
    with target.open() as handle:
        assert handle.read() == "readable"
    assert os.listdir(tmp_path) == [target.name]
    assert __import__("subprocess") is sys.modules["subprocess"]
    assert GUARD_ACTIVE.get() is False


def test_the_extent_is_restored_when_the_episode_raises() -> None:
    # The extent must not leak: an episode that failed — the common case, since
    # a refusal *is* an exception — must leave the interpreter unguarded.  The
    # context variable is restored on the way out however the episode ended,
    # which is why the mark is a context variable rather than a module flag.
    with (
        pytest.raises(ValueError, match="the policy's own failure"),
        guard_policy(),
    ):
        raise ValueError("the policy's own failure")
    assert GUARD_ACTIVE.get() is False


def test_a_refusal_does_not_leave_the_extent_armed() -> None:
    # And the same for the refusal that *is* the feature: catching a
    # ``PolicyFilesystemError`` and carrying on is what a caller testing several
    # policies does, and the next policy must be judged from a clean mark.
    source = "def choose(question):\n    return open('/etc/hostname')\n"
    with guard_policy():
        module = policy(source)
        with pytest.raises(PolicyFilesystemError):
            module.choose(FakeQuestion())
    assert GUARD_ACTIVE.get() is False


def test_guards_nest_and_the_inner_ceiling_holds_only_for_its_extent() -> None:
    # A narrower box tested inside a wider one — the composition a deployment
    # audits with.  The inner episode is judged by its own ceiling; the moment
    # it ends the outer one is back in force, because the bindings are saved and
    # restored per entry rather than assigned once.
    narrow = PolicyCeiling(terms=("math",))
    source = "def choose(question):\n    import statistics\n    return 1\n"
    with guard_policy() as outer:
        with guard_policy(ceiling=narrow):
            module = policy(source)
            with pytest.raises(PolicyImportError):
                module.choose(FakeQuestion())
        assert outer.covers("statistics") is True
        module = policy(source)
        assert module.choose(FakeQuestion()) == 1


def test_the_extent_does_not_leak_into_a_thread_the_policy_did_not_spawn() -> None:
    # A context variable is scoped to the extent that set it, so a thread the
    # policy did not spawn does not inherit the mark.  This matters because the
    # guard is process-wide state: a worker that inherited a refusal would
    # refuse the application's own I/O for as long as the episode ran.
    import threading

    reached: list[bool] = []

    def worker() -> None:
        reached.append(GUARD_ACTIVE.get())

    with guard_policy():
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert reached == [False]


# ---------------------------------------------------------------------------
# the ceiling is the deployment's, and it is a read
# ---------------------------------------------------------------------------


def test_the_ceiling_is_the_committed_configured_document() -> None:
    # "The configured allowlist" means *the* allowlist — singular, the one the
    # deployment already has rather than one this module declares.  That
    # document is feature 167's committed ``sandbox-imports`` ceiling, so the
    # two boxes can never drift into disagreeing about what a Z1 policy may
    # import.
    with guard_policy() as guard:
        terms = guard.terms()
    assert "math" in terms
    assert "statistics" in terms
    assert "os" not in terms
    assert "subprocess" not in terms
    assert len(terms) > 5


def test_the_ceiling_is_read_not_restated() -> None:
    # The ceiling's terms come from the committed document, compared
    # entry-for-entry — so a term added to the sandbox's allowlist appears here
    # without an edit to this member, and a term removed here is one the
    # deployment removed.  The document is read as data: this member does not
    # interpret it, and the compile that does belongs to the sandbox.
    import json
    from pathlib import Path

    document = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "sandbox"
        / "src"
        / "sandbox"
        / "imports_allowlist.json"
    )
    committed = json.loads(document.read_text())["allow"]
    with guard_policy() as guard:
        assert list(guard.terms()) == list(committed)


def test_covers_admits_a_term_and_everything_under_it() -> None:
    # Feature 167's coverage rule, read through this member's ceiling: an entry
    # admits the term *and its submodules* — importing a submodule executes the
    # package, so the entry that admits the package admits it.  A parent of an
    # entry is not covered: importing the parent executes it, and the entry
    # never named it.
    ceiling = PolicyCeiling(terms=("collections.abc",))
    assert ceiling.covers("collections.abc") is True
    assert ceiling.covers("collections.abc.xyz") is True
    assert ceiling.covers("collections") is False
    assert "collections.abc" in ceiling
    assert "os" not in ceiling


def test_the_two_halves_are_independent_laws() -> None:
    # The import half and the filesystem half are *separate* refusals, and this
    # pins that neither is derived from the other.  A ceiling that names ``os``
    # admits the import — the ceiling is the deployment's law and the guard does
    # not second-guess it — and the policy still cannot use it to reach a file,
    # because the filesystem half refuses the access regardless.  A guard whose
    # filesystem half were merely "os is not allowlisted" would fail this test.
    loose = PolicyCeiling(terms=("os",))
    with guard_policy(ceiling=loose):
        module = policy("import os\ndef choose(question):\n    return os.sep\n")
        assert module.choose(FakeQuestion()) == os.sep
    reaching = "import os\ndef choose(question):\n    return os.listdir('/')\n"
    with guard_policy(ceiling=loose):
        module = policy(reaching)
        with pytest.raises(PolicyFilesystemError):
            module.choose(FakeQuestion())


def test_an_empty_ceiling_refuses_every_import() -> None:
    # The strictest ceiling there is, and it is the fallback's fail-closed
    # direction: a deployment whose allowlist cannot be resolved refuses every
    # import a policy makes rather than waving them through.  A policy that
    # cannot be told what it may import is not one to admit.
    with guard_policy(ceiling=PolicyCeiling(terms=())) as guard:
        assert guard.covers("math") is False
        module = policy("def choose(question):\n    import math\n    return 1\n")
        with pytest.raises(PolicyImportError):
            module.choose(FakeQuestion())


def test_a_non_string_term_names_no_module_and_is_covered_by_nothing() -> None:
    # Defensive, and the conservative direction: ``covers`` is asked about a
    # term derived from an import statement, so a caller asking it about
    # something else must not be told yes by a coincidental substring match.
    ceiling = PolicyCeiling(terms=("math",))
    assert ceiling.covers(None) is False
    assert ceiling.covers("") is False
    assert ceiling.covers("maths") is False


def test_the_guard_exposes_the_ceiling_it_judges_by() -> None:
    # The read side: "which modules may a policy import here?" is a question a
    # deployment should be able to answer without running a policy to find out.
    # The guard answers it from the configured document rather than from a
    # claim in a runbook, and answering widens nothing — the ceiling holds no
    # capability, which is why the guard is a law rather than a box.
    guard = PolicyGuard()
    assert guard.covers(guard.terms()[0]) is True
    assert guard.subject == POLICY_MODULE_NAME
    assert isinstance(repr(guard), str)


def test_constructing_a_guard_arms_nothing() -> None:
    # A guard is a *value*; entering it is what arms the interpreter.  A caller
    # that builds a guard to read its ceiling — an operator audit — must not
    # thereby guard the application.
    PolicyGuard()
    assert GUARD_ACTIVE.get() is False


def test_the_configured_ceiling_is_resolved_at_most_once_per_process() -> None:
    # The resolution's cost is why this is pinned: the workspace seat's bare call
    # *composes the deployment* — a scan of every member and a build of every
    # component, seconds of work — and a guard is constructed per policy.  A
    # resolution per construction would pay that for every policy that ever ran,
    # so the ceiling is resolved once and read thereafter, and this asserts the
    # identity of the resolved object rather than merely its equal terms.
    first = guard_policy()
    second = guard_policy()
    assert first.ceiling is second.ceiling


def test_an_application_handed_over_is_read_rather_than_recomposed() -> None:
    # And the escape from even that first cost: a running system holds its
    # application already, and hands it over so the ceiling is read from the
    # application it is actually running inside rather than from a fresh
    # composition of the same roots.  A composed app is not *required* — the
    # bare form works and is what every other test here uses — but a caller that
    # has one should never pay for a second.
    from app.module_loader import create_app

    application = create_app()
    guard = guard_policy(app=application)
    assert guard.covers("math") is True
    assert guard.covers("os") is False


def test_an_explicit_ceiling_is_never_second_guessed() -> None:
    # A caller that resolved its own ceiling — an operator replaying an episode
    # under the terms it ran under — must get exactly the ceiling it passed,
    # with no resolution and no memo consulted.  The distinction matters because
    # the configured ceiling is a fact about deployment time and a passed one is
    # a fact about a historical episode, and the two can legitimately differ.
    narrow = PolicyCeiling(terms=("math",))
    assert guard_policy(ceiling=narrow).ceiling is narrow


# ---------------------------------------------------------------------------
# the vocabulary at the member's seam
# ---------------------------------------------------------------------------


def test_both_errors_are_the_members_own_and_are_kept_apart() -> None:
    # The two refusals are one feature's and they are two error classes, for the
    # reason this member keeps every pair apart: they are repaired differently.
    # A refused import is repaired by asking the deployment to widen its
    # allowlist or by removing the import; a refused file read is repaired by
    # routing the data through the question.  Both are this member's errors, so
    # a caller catching :class:`PolicyRuntimeError` catches both.
    assert issubclass(PolicyFilesystemError, PolicyRuntimeError)
    assert issubclass(PolicyImportError, PolicyRuntimeError)
    assert not issubclass(PolicyImportError, PolicyFilesystemError)
    assert not issubclass(PolicyFilesystemError, PolicyImportError)


def test_each_refusal_names_its_operation_and_its_feature(
    fake_question: FakeQuestion,
) -> None:
    # A refusal an operator reads must say what was refused and why, and the
    # detail is checked rather than assumed: the filesystem refusal names the
    # audit event and its argument, the import refusal names the module, and
    # both cite the feature so the sentence a caller is held to is findable.  A
    # refusal that said only "refused" would leave the operator guessing which
    # of the two halves they had met.
    filesystem_source = "def choose(question):\n    return open('/etc/hostname')\n"
    with guard_policy():
        module = policy(filesystem_source)
        with pytest.raises(PolicyFilesystemError) as file_refusal:
            module.choose(fake_question)
    detail = str(file_refusal.value)
    assert "open" in detail
    assert "feature 225" in detail

    import_source = "def choose(question):\n    import socket\n    return socket\n"
    with guard_policy():
        module = policy(import_source)
        with pytest.raises(PolicyImportError) as import_refusal:
            module.choose(fake_question)
    detail = str(import_refusal.value)
    assert "socket" in detail
    assert "feature 225" in detail


def test_the_extent_mark_is_a_public_name_a_caller_can_read() -> None:
    # The mark is exported because a caller that wants to know whether it is
    # inside an episode — a runtime deciding where to do its own I/O — must be
    # able to ask rather than infer it from a frame.
    assert GUARD_ACTIVE.get() is False
    with guard_policy():
        assert GUARD_ACTIVE.get() is True
    assert GUARD_ACTIVE.get() is False


#: The ``builtins.__import__`` that was in place when this test module was
#: imported — captured at import time so ``test_the_import_channel_is_a_wrap…``
#: can show the guard replaced it, rather than reading the value the guard had
#: already installed.
_ORIGINAL_IMPORT_AT_IMPORT = builtins.__import__
