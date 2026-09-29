"""Features 246 and 247 — the dependency wall, its refusals and its one seam.

app_spec.xml, "Replay Engine", features 246 and 247: *System rejects every
replay-path call reaching the evaluator, granting the replay engine read
access to the artifact store alone*, and *System rejects any replay-path call
reaching the evaluator or the sandbox, which returns a ``forbidden_dependency``
error message.*  This suite pins the law; the wiring suite
(``tests/replay/test_dependency_wiring.py``) pins the cross-member seam — that
the mark this wall reads is feature 146's, and that the composed facade carries
the wall.

**What the tests below are written against.**  The wall's whole behaviour turns
on one predicate — *is this dynamic extent the replay path?* — and the member
under test may not import the canary member (a member never imports another
member), so the suite reaches the mark the same way the module does: through
``importlib``, lazily, duck-typed.  Where the canary member is importable the
tests span a *real* replay path (``canary.replaying()``) so the assertion is
about the mark a deployment actually sets; where it is not, the tests span one
by patching the module's own ``_replay_path_mark`` — the seam's single
indirection — and say so.  Everything else is exercised over hand-rolled
targets that record whether they were called, which is how *the refusal fires
before the call* is testable at all.
"""

from __future__ import annotations

import pytest
from replay import (
    EVALUATOR_DEPENDENCY,
    FORBIDDEN_DEPENDENCIES,
    FORBIDDEN_DEPENDENCY_CODE,
    SANDBOX_DEPENDENCY,
    ForbiddenDependencyError,
    ReplayEngine,
    ReplayError,
    ReplayPathDependencies,
    dependency_feature,
    is_replaying,
    reach,
    refused_dependency,
    replay_path_forbids,
    validate_dependency_name,
)
from replay.dependencies import MESSAGE_PHRASES


def _canary_mark():
    """The canary member's ``replaying`` context manager, or ``None``.

    Reached exactly as the module under test reaches it — never imported at
    this suite's module scope, because the member's ``pyproject.toml``
    declares one dependency and a suite that imported a sibling directly would
    hide a member-imports-member mistake in the *tests* rather than in the
    code.  ``None`` when the canary member is not on this process's path, which
    is the state the patch-based tests below cover.
    """
    import importlib

    try:
        canary = importlib.import_module("canary")
    except Exception:  # noqa: BLE001 - a member that is not scanned is a skip, not a failure
        return None
    mark = getattr(canary, "replaying", None)
    return mark if callable(mark) else None


class _Spy:
    """A target that records every call — the "it never ran" witness.

    A callable object rather than a bare function so ``_target_name`` reads
    ``a _Spy instance`` off it, which is the instance half of the naming rule.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> str:
        self.calls.append((args, kwargs))
        return "ran"

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "<Spy>"


@pytest.fixture
def marked(monkeypatch: pytest.MonkeyPatch):
    """Span a replay path for the duration of one test.

    Uses the canary member's real mark where it is importable — so the test is
    about the mark feature 142's nightly replay actually sets — and otherwise
    patches the module's one indirection (``_replay_path_mark``) with a
    predicate that answers ``True``.  Both spellings produce the same state:
    :func:`replay.is_replaying` answers ``True``.
    """
    mark = _canary_mark()
    if mark is not None:
        with mark():
            yield
        return
    from replay import dependencies

    monkeypatch.setattr(dependencies, "_replay_path_mark", lambda: (lambda: True))
    yield


# ---------------------------------------------------------------------------
# §1's set — the prohibition, and the grant it comes with
# ---------------------------------------------------------------------------


def test_the_two_forbidden_dependencies_are_the_specs_two() -> None:
    # §1: *"zero access to the evaluator or sandbox"*.  Two names, spelled as
    # the sentences spell them, and the set is exactly those two — a third name
    # would be a prohibition §1 does not state.
    assert FORBIDDEN_DEPENDENCIES == frozenset({"evaluator", "sandbox"})
    assert EVALUATOR_DEPENDENCY == "evaluator"
    assert SANDBOX_DEPENDENCY == "sandbox"


def test_the_code_is_the_specs_word() -> None:
    # Feature 247's sentence names the code it returns — *"which returns a
    # ``forbidden_dependency`` error message"* — so the token is not this
    # member's to choose, and every refusal must open with it.
    assert FORBIDDEN_DEPENDENCY_CODE == "forbidden_dependency"


def test_each_forbidden_dependency_is_named_in_the_specs_own_words() -> None:
    # The message reads like the sentence it enforces: the spec writes *"the
    # evaluator"* and *"the sandbox"*, and a phrase table missing an entry
    # would be a KeyError at raise time — the one place a message must not
    # fail to build.
    assert set(MESSAGE_PHRASES) == FORBIDDEN_DEPENDENCIES
    assert MESSAGE_PHRASES[EVALUATOR_DEPENDENCY] == "the evaluator"
    assert MESSAGE_PHRASES[SANDBOX_DEPENDENCY] == "the sandbox"


def test_the_wall_forbids_the_evaluator_and_the_sandbox() -> None:
    assert replay_path_forbids("evaluator") is True
    assert replay_path_forbids("sandbox") is True


def test_the_wall_grants_every_other_dependency_by_not_naming_it() -> None:
    # §1's positive half — *"read access to the artifact store"* — honored as
    # the *absence* of a prohibition.  A closed allowlist of two names would
    # have made every other name a false refusal on the replay path, and the
    # artifact store is the name that matters most: it is what §1 grants.
    for granted in ("artifacts", "artifact_store", "artifact store", "book", "ledger"):
        assert replay_path_forbids(granted) is False


def test_a_blank_name_is_refused_where_a_name_belongs() -> None:
    # The wall's subject is *which* dependency a call reached for, so a name
    # that names nothing can produce no refusal that says what was refused.
    # The blank-string case is refused for the reason the transition refuses a
    # blank ``parent_id``: it is neither absent nor a name.
    for blank in ("", "   ", "\t"):
        with pytest.raises(ForbiddenDependencyError) as raised:
            replay_path_forbids(blank)
        assert FORBIDDEN_DEPENDENCY_CODE in str(raised.value)


def test_a_non_string_name_is_refused() -> None:
    for wrong in (None, 246, 247.0, b"evaluator", ["evaluator"]):
        with pytest.raises(ForbiddenDependencyError) as raised:
            replay_path_forbids(wrong)
        message = str(raised.value)
        assert FORBIDDEN_DEPENDENCY_CODE in message
        assert type(wrong).__name__ in message


def test_validate_dependency_name_answers_the_name_it_was_handed() -> None:
    # The one spelling of the argument check, shared by every verb here, so
    # they cannot disagree about what a name is.
    assert validate_dependency_name("evaluator") == "evaluator"
    assert validate_dependency_name("artifacts") == "artifacts"


# ---------------------------------------------------------------------------
# The refusal — inside the mark, before the call
# ---------------------------------------------------------------------------


def test_a_forbidden_reach_inside_the_path_is_refused(marked: None) -> None:
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError) as raised:
        reach(EVALUATOR_DEPENDENCY, spy)
    assert FORBIDDEN_DEPENDENCY_CODE in str(raised.value)


def test_the_target_never_runs_when_the_reach_is_refused(marked: None) -> None:
    # **The ordering is the feature.**  §1's collapse *is* an evaluation that
    # ran: a refusal that called the evaluator first and raised afterwards would
    # have spent the container, the ledger's trial and the wall clock it was
    # refusing to spend, and would have produced a score no frozen pair
    # contributed.  The spy is the witness — it records every call, and it
    # records none.
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError):
        reach(EVALUATOR_DEPENDENCY, spy, "positional", keyword="value")
    assert spy.calls == []


def test_the_sandbox_is_refused_too(marked: None) -> None:
    # Feature 247's half of the sentence — *"or the sandbox"* — refused by the
    # same verb with the same code, because the two features share one repair.
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError) as raised:
        reach(SANDBOX_DEPENDENCY, spy)
    assert spy.calls == []
    assert FORBIDDEN_DEPENDENCY_CODE in str(raised.value)


def test_the_refusal_names_which_dependency_and_which_feature(marked: None) -> None:
    # An operator reading the line has a replay path that reached for something
    # and needs to know *what* and *why*.  The evaluator is feature 246's
    # sentence; the sandbox is 247's (the one that adds *"or the sandbox"* and
    # names the code).
    with pytest.raises(ForbiddenDependencyError) as evaluator:
        reach(EVALUATOR_DEPENDENCY, _Spy())
    assert "the evaluator" in str(evaluator.value)
    assert "feature 246" in str(evaluator.value)

    with pytest.raises(ForbiddenDependencyError) as sandbox:
        reach(SANDBOX_DEPENDENCY, _Spy())
    assert "the sandbox" in str(sandbox.value)
    assert "feature 247" in str(sandbox.value)


def test_the_refusal_quotes_the_architecture_sentence(marked: None) -> None:
    # §1 line 32 is the sentence the whole feature is made of, and it is the
    # sentence an operator must be able to grep the log for.
    with pytest.raises(ForbiddenDependencyError) as raised:
        reach(EVALUATOR_DEPENDENCY, _Spy())
    message = str(raised.value)
    assert "§1" in message
    assert "zero access to the evaluator or sandbox" in message
    assert "the cost model of the entire system collapses" in message


def test_the_refusal_says_nothing_was_spent(marked: None) -> None:
    # The message must answer the operator's first question — *did this run?* —
    # because the answer is what makes the refusal a repair rather than an
    # incident.
    with pytest.raises(ForbiddenDependencyError) as raised:
        reach(SANDBOX_DEPENDENCY, _Spy())
    assert "before it was made" in str(raised.value)
    assert "nothing was spent" in str(raised.value)


def test_the_refusal_states_the_repair(marked: None) -> None:
    # The repair is the other half of §1's sentence — read what the evaluation
    # already wrote — and it is different for the two dependencies only because
    # the stored things are named differently.
    with pytest.raises(ForbiddenDependencyError) as evaluator:
        reach(EVALUATOR_DEPENDENCY, _Spy())
    assert "Read the stored node and its artifact instead" in str(evaluator.value)

    with pytest.raises(ForbiddenDependencyError) as sandbox:
        reach(SANDBOX_DEPENDENCY, _Spy())
    assert "Read the artifact the sandboxed run already wrote instead" in str(
        sandbox.value
    )


def test_the_refusal_names_the_target_so_the_call_site_is_findable(marked: None) -> None:
    # A refusal that named only the dependency would leave the operator with a
    # replay path full of candidate call sites.  A function names itself; an
    # instance names its type.
    def an_evaluation_call() -> None:  # pragma: no cover - never called
        pass

    with pytest.raises(ForbiddenDependencyError) as named:
        reach(EVALUATOR_DEPENDENCY, an_evaluation_call)
    assert "an_evaluation_call" in str(named.value)

    with pytest.raises(ForbiddenDependencyError) as typed:
        reach(EVALUATOR_DEPENDENCY, _Spy())
    assert "_Spy instance" in str(typed.value)


def test_a_bare_reach_is_named_as_one(marked: None) -> None:
    # A caller looping over dependencies to check them names the dependency and
    # no target.  ``repr(None)`` would be indistinguishable from a target that
    # *is* ``None``, which is a different fact about the caller's code.
    with pytest.raises(ForbiddenDependencyError) as raised:
        reach(EVALUATOR_DEPENDENCY)
    assert "a bare reach" in str(raised.value)


def test_the_refusal_is_built_not_raised_by_the_message_builder() -> None:
    # ``refused_dependency`` is the whole message as a value, so a suite (or a
    # monitor) can read the operator-facing line without manufacturing a raise.
    refusal = refused_dependency(EVALUATOR_DEPENDENCY, _Spy())
    assert isinstance(refusal, ForbiddenDependencyError)
    assert FORBIDDEN_DEPENDENCY_CODE in str(refusal)


def test_a_granted_name_is_refused_by_the_builder_not_indexed() -> None:
    # §1's prohibition covers two names and *grants* the rest, so a caller may
    # hand the builder a name the wall does not forbid — an audit walking the
    # dependencies a deployment resolves is the obvious one.  Before this was
    # total that call raised a bare ``KeyError`` out of the phrase table: a
    # fault in the wall's *own* tables reported for a name the wall simply does
    # not refuse, which names no dependency at all and lands outside both this
    # member's vocabulary and the caller's ``except ReplayError``.
    for granted in ("artifacts", "artifact_store", "book", "ledger"):
        with pytest.raises(ForbiddenDependencyError) as raised:
            refused_dependency(granted, _Spy())
        message = str(raised.value)
        assert FORBIDDEN_DEPENDENCY_CODE in message
        assert granted in message, "the refusal must name what it was asked about"
        assert "replay_path_forbids" in message, "and point at the verb that answers"


def test_the_builder_refuses_a_granted_name_in_the_walls_vocabulary() -> None:
    # The alignment with ``dependency_feature``, which answers the same question
    # the same way: a function that is only meaningful about a forbidden
    # dependency refuses a caller who asks it about a granted one, rather than
    # inventing an answer.  Both are ``ForbiddenDependencyError``, both name the
    # name, and both send the caller to ``replay_path_forbids``.
    with pytest.raises(ForbiddenDependencyError) as builder:
        refused_dependency("artifacts", _Spy())
    with pytest.raises(ForbiddenDependencyError) as feature:
        dependency_feature("artifacts")
    for raised in (builder, feature):
        assert "artifacts" in str(raised.value)
        assert "replay_path_forbids" in str(raised.value)


def test_a_granted_name_still_answers_through_the_predicate() -> None:
    # And the repair the refusal names is real: the verb it sends the caller to
    # answers about the very name the builder refused to build a line for.  A
    # refusal that pointed at a function which also refused would be a loop.
    assert replay_path_forbids("artifacts") is False


def test_the_builder_still_refuses_a_name_that_names_nothing() -> None:
    # The refusal grew no blind spot: a value that cannot name a dependency is
    # still refused by the check every verb here shares — the argument check
    # fires first, so this stays the message it always was.
    for wrong in ("", "   ", None, 246, b"artifacts"):
        with pytest.raises(ForbiddenDependencyError) as raised:
            refused_dependency(wrong, _Spy())
        assert FORBIDDEN_DEPENDENCY_CODE in str(raised.value)


def test_the_refusal_is_a_replay_error(marked: None) -> None:
    # The one base class, so a dreaming loop's single ``except ReplayError``
    # catches a forbidden reach — the property the member's error module states
    # for every one of its subclasses.
    with pytest.raises(ReplayError):
        reach(SANDBOX_DEPENDENCY, _Spy())


def test_the_refusal_is_not_a_round_error() -> None:
    # The non-nesting is load-bearing: a caller that catches the loop's
    # malformed ask to skip a bad world must not silently skip the wall — in a
    # dreaming loop that would turn §1's one prohibition into a per-world skip
    # that reports itself as nothing at all.
    from replay import ReplayRoundError, ReplayTreeError

    for sibling in (ReplayRoundError, ReplayTreeError):
        assert not issubclass(ForbiddenDependencyError, sibling)
    assert ForbiddenDependencyError.__bases__ == (ReplayError,)


# ---------------------------------------------------------------------------
# The grant — a granted dependency is delegated, mark or no mark
# ---------------------------------------------------------------------------


def test_a_granted_reach_is_delegated_off_the_path() -> None:
    # The evaluation path's ordinary business: an evaluator is *meant* to run
    # there (§6's pipeline, §5.2's sandbox), so the seam must not be a refusal
    # that only refuses — no caller would route through a wall that blocked
    # everything.
    spy = _Spy()
    assert reach(EVALUATOR_DEPENDENCY, spy, 1, two=2) == "ran"
    assert spy.calls == [((1,), {"two": 2})]


def test_a_granted_reach_is_delegated_on_the_path_too(marked: None) -> None:
    # **The half that keeps dreaming free.**  §1 forbids two names and grants
    # the rest; the artifact store is what it grants, and a replay's read of it
    # (feature 251's resident read, feature 239's node rows) is a call the wall
    # must not intercept.  A seam that refused every name while the mark was set
    # would refuse the very read §1 promises, and would be the reason dreaming
    # was *not* free.
    spy = _Spy()
    assert reach("artifacts", spy, "campaign", horizon=3) == "ran"
    assert spy.calls == [(("campaign",), {"horizon": 3})]


def test_the_arguments_and_the_result_pass_through_untouched() -> None:
    # The delegation is deliberately thin: no caching, no counting, no retries,
    # no validation of the target.  What a caller hands in is what the target
    # gets, and what the target returns is what the caller gets.
    sentinel = object()

    def target(*args: object, **kwargs: object) -> object:
        return sentinel

    assert reach("artifacts", target, 1, 2, three=3) is sentinel


def test_a_non_callable_granted_target_fails_with_the_calls_own_type_error() -> None:
    # Off the replay path the seam delegates — so a non-callable target is the
    # *call's* failure, not this member's refusal.  (On the path, for a
    # forbidden dependency, the refusal fires first, because the feature
    # rejects the call whatever the thing reached for turns out to be.)
    with pytest.raises(TypeError):
        reach("artifacts", "not callable")


def test_a_non_callable_forbidden_target_is_refused_before_it_could_fail(
    marked: None,
) -> None:
    # The refusal is of the *call*, not of the thing reached for: on the replay
    # path the wall refuses a reach for the evaluator before it could discover
    # that the target was not even callable.
    with pytest.raises(ForbiddenDependencyError):
        reach(EVALUATOR_DEPENDENCY, "not callable")


def test_a_blank_name_is_refused_before_anything_is_delegated() -> None:
    # The wall's own argument is checked in *either* state: a wall asked about
    # nothing has no answer to give, on the replay path or off it.
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError):
        reach("", spy)
    assert spy.calls == []


# ---------------------------------------------------------------------------
# The mark — one fact, feature 146's, read and never restated
# ---------------------------------------------------------------------------


def test_off_the_path_nothing_is_marked() -> None:
    assert is_replaying() is False


def test_the_mark_is_entered_and_restored(marked: None) -> None:
    assert is_replaying() is True


def test_the_mark_is_read_not_restated(monkeypatch: pytest.MonkeyPatch) -> None:
    # **The load-bearing seam.**  This module must not carry a second
    # ``ContextVar``: a replay guarded by one marker would be unguarded by the
    # other, which is the daily failure mode of two spellings of one law.  The
    # module reads the canary member's predicate through one indirection, and
    # patching that indirection moves the wall — proof that the mark is read
    # rather than owned here.
    from replay import dependencies

    monkeypatch.setattr(dependencies, "_replay_path_mark", lambda: (lambda: True))
    assert is_replaying() is True
    with pytest.raises(ForbiddenDependencyError):
        reach(EVALUATOR_DEPENDENCY, _Spy())


def test_an_absent_canary_member_leaves_the_path_unmarked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A deployment where the canary member was not scanned has no replay path
    # marked at all.  The honest answer is *not marked* — the same "an absent
    # component is a discoverable state, not an exception" stance the member's
    # builders take — rather than inventing a mark no other guard
    # shares, which would let this wall refuse calls in an extent no replay
    # entered.
    from replay import dependencies

    monkeypatch.setattr(dependencies, "_replay_path_mark", lambda: None)
    assert is_replaying() is False
    spy = _Spy()
    assert reach(EVALUATOR_DEPENDENCY, spy) == "ran"
    assert spy.calls != []


def test_a_canary_member_with_no_predicate_is_the_same_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The indirection answers ``None`` for a module that is not importable and
    # for one that carries no such predicate: both are *there is no mark to
    # read*, and neither is a reason a replay's read should fail.
    import importlib

    class _Bare:
        pass

    monkeypatch.setattr(importlib, "import_module", lambda name: _Bare())
    assert is_replaying() is False


def test_an_unimportable_canary_member_is_the_same_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    def _boom(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", _boom)
    assert is_replaying() is False


# ---------------------------------------------------------------------------
# dependency_feature — which sentence fired
# ---------------------------------------------------------------------------


def test_the_evaluator_is_feature_246s_and_the_sandbox_247s() -> None:
    assert dependency_feature(EVALUATOR_DEPENDENCY) == 246
    assert dependency_feature(SANDBOX_DEPENDENCY) == 247


def test_a_granted_dependency_has_no_forbidding_feature() -> None:
    # This is the one function here that is only meaningful about a forbidden
    # dependency, so a caller asking it about the artifact store has asked a
    # question with no answer and is told so rather than handed a made-up
    # number.
    with pytest.raises(ForbiddenDependencyError):
        dependency_feature("artifacts")


def test_a_blank_name_has_no_forbidding_feature() -> None:
    with pytest.raises(ForbiddenDependencyError):
        dependency_feature("")


# ---------------------------------------------------------------------------
# The wall as a value — the composed facade's property
# ---------------------------------------------------------------------------


def test_the_wall_holds_nothing() -> None:
    # A wall that is a fact about where a call sits, not a thing a deployment
    # configures: no allowlist, no registry, no toggle — a wall that could be
    # switched off would not be §1's *"zero access"*.
    assert ReplayPathDependencies.__slots__ == ()
    wall = ReplayPathDependencies()
    assert not hasattr(wall, "__dict__")


def test_the_wall_refuses_the_evaluator_by_name(marked: None) -> None:
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError):
        ReplayPathDependencies().evaluator(spy)
    assert spy.calls == []


def test_the_wall_refuses_the_sandbox_by_name(marked: None) -> None:
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError):
        ReplayPathDependencies().sandbox(spy)
    assert spy.calls == []


def test_the_wall_delegates_a_granted_reach(marked: None) -> None:
    assert ReplayPathDependencies().reach("artifacts", lambda: "read") == "read"


def test_the_wall_delegates_the_evaluator_off_the_path() -> None:
    assert ReplayPathDependencies().evaluator(lambda: "scored") == "scored"


def test_the_wall_answers_whether_it_refuses() -> None:
    wall = ReplayPathDependencies()
    assert wall.refuses("evaluator") is True
    assert wall.refuses("sandbox") is True
    assert wall.refuses("artifacts") is False
    assert wall.refuses("artifact_store") is False


def test_the_wall_repr_names_itself() -> None:
    assert repr(ReplayPathDependencies()) == "ReplayPathDependencies()"


def test_the_composed_facade_carries_the_wall() -> None:
    # The facade gains a property, not a ``replay-``prefixed component: the
    # wall is a fact about the path (§1, §12), so there is nothing to misset,
    # nothing to resolve and no second name the spec does not ask for.
    engine = ReplayEngine()
    assert isinstance(engine.dependencies, ReplayPathDependencies)
    assert engine.dependencies.refuses("evaluator") is True


def test_the_facade_hands_back_a_fresh_wall_each_time() -> None:
    # Returning a fresh value costs nothing (empty ``__slots__``, no state),
    # while a cached one would be one more piece of state on a facade whose
    # whole property is that it holds none.
    engine = ReplayEngine()
    assert engine.dependencies is not engine.dependencies


def test_the_facade_still_holds_nothing() -> None:
    # The property feature 245's component is built on, restated after this
    # feature's arrival: adding the wall must not have put state on the facade.
    assert ReplayEngine.__slots__ == ()
    assert not hasattr(ReplayEngine(), "__dict__")


def test_the_facade_wall_refuses_inside_the_mark(marked: None) -> None:
    # End to end through the composed spelling: the wall a caller reaches from
    # the application is the same law as the module-level verb.
    spy = _Spy()
    with pytest.raises(ForbiddenDependencyError):
        ReplayEngine().dependencies.evaluator(spy)
    assert spy.calls == []


# ---------------------------------------------------------------------------
# The vocabulary is exported, and complete
# ---------------------------------------------------------------------------


def test_the_wall_is_reachable_from_the_member_root() -> None:
    # A caller holding the member rather than the composed application reaches
    # every half of the wall from one import, the way it reaches every other
    # feature's surface.
    import replay

    for name in (
        "EVALUATOR_DEPENDENCY",
        "SANDBOX_DEPENDENCY",
        "FORBIDDEN_DEPENDENCIES",
        "FORBIDDEN_DEPENDENCY_CODE",
        "MESSAGE_PHRASES",
        "ForbiddenDependencyError",
        "ReplayPathDependencies",
        "dependency_feature",
        "is_replaying",
        "reach",
        "refused_dependency",
        "replay_path_forbids",
        "validate_dependency_name",
    ):
        assert name in replay.__all__, name
        assert getattr(replay, name) is not None


def test_the_error_class_is_in_the_members_vocabulary() -> None:
    from replay.errors import __all__ as error_names

    assert "ForbiddenDependencyError" in error_names


def test_the_member_imports_no_sibling_to_read_the_mark() -> None:
    # The seam is an ``importlib`` at call time, not an import statement: this
    # member's module graph must not reach a sibling package at import, or every
    # factory scan would pay for a wall reached only by a caller about to span a
    # replay path — and the member's one-dependency ``pyproject.toml`` would be
    # a lie about its own code.
    import ast
    from pathlib import Path

    import replay

    source_root = Path(replay.__file__).resolve().parent
    forbidden = {"canary", "evaluator", "sandbox", "artifacts", "policy_runtime"}
    for module in sorted(source_root.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not (roots & forbidden), f"{module.name} imports {roots & forbidden}"


def test_the_wall_reaches_the_mark_by_importlib() -> None:
    # The other half of the check above, stated positively: the one sibling
    # reach is spelled as a dynamic import of the member by name, so patching
    # that indirection is what moves the wall (see the tests above).
    import inspect

    from replay import dependencies

    source = inspect.getsource(dependencies._replay_path_mark)
    assert "importlib" in source
    assert 'import_module("canary")' in source
