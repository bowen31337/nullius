"""Features 246 and 247 in the assembled system — the wall, the component, the mark.

app_spec.xml, "Replay Engine", feature 246: *System rejects every replay-path
call reaching the evaluator, granting the replay engine read access to the
artifact store alone.*  Feature 247: *System rejects any replay-path call
reaching the evaluator or the sandbox, which returns a ``forbidden_dependency``
error message.*  The member's own suite
(``packages/replay/tests/test_dependencies.py``) pins the law over a patched
mark; this suite pins the two things a member's suite structurally cannot:

* **the mark is feature 146's** — the replay path the wall reads is the
  :class:`~contextvars.ContextVar` the *canary* member owns, entered by the
  member's own ``replaying()`` context manager and by feature 142's
  :func:`~canary.replay_pair`.  This is the only place the two members' halves
  of one law are checked against each other: the wall against the mark a real
  replay is run under.  A member never imports another member, so the replay
  member reaches it through ``importlib`` — and a suite, which may import both,
  says whether the two spellings agree;
* **the mark is *one* fact** — this module restates feature 146's mark rather
  than reading it.  The check is a substitution: patch the canary member's
  predicate and the wall moves with it, which a second
  :class:`~contextvars.ContextVar` would make impossible;
* **the composed facade carries the wall** — ``create_app()`` over the declared
  workspace hands out an engine whose ``dependencies`` property is the wall,
  read by name from the composed application rather than by importing the
  member.

**Nothing here asserts ``isinstance`` or ``pytest.raises(<canonical class>)``
across the composition seam.**  The module loader imports each workspace member
under a synthetic name (``_nullius_scanned_<name>``) and re-executes it, so the
``ForbiddenDependencyError`` the composed component raises is a *second* class
object with the same name and the same source.  The checks below name the
behaviour and compare ``type(exc).__name__``, the same answer
``tests/replay/test_plugin_wiring.py`` gives for that wrinkle.

The canary member is reached by ``importlib`` here for the same reason the
member under test reaches it that way, and the checks that need it are skipped
where it is not on this process's path — the state the member handles by
answering *not marked*, which ``test_the_wall_is_silent_where_no_mark_exists``
pins.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import replay

from app.module_loader import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_SRC = REPO_ROOT / "packages" / "replay" / "src"


def _canary():
    """The canary member, or ``None`` when it is not on this process's path."""
    try:
        return importlib.import_module("canary")
    except Exception:  # noqa: BLE001 - a member that is not scanned is a skip, not a failure
        return None


@pytest.fixture(scope="module")
def app():
    """The composed application — ``create_app()`` scans every member."""
    return create_app()


@pytest.fixture
def canary():
    """The canary member, or a skip when this environment does not carry it."""
    member = _canary()
    if member is None:
        pytest.skip("the canary member is not on this process's path")
    return member


@pytest.fixture
def spy():
    """A target that records every call — the "it never ran" witness."""

    class _Spy:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def __call__(self, *args: object, **kwargs: object) -> str:
            self.calls.append((args, kwargs))
            return "ran"

    return _Spy()


# ---------------------------------------------------------------------------
# The member is scanned and its wall composes
# ---------------------------------------------------------------------------


def test_the_member_is_a_declared_workspace_member() -> None:
    # The registration chain starts here: a member whose pyproject.toml is
    # missing is not scanned, so no deployment carries the wall.
    assert (REPLAY_SRC.parent / "pyproject.toml").is_file()
    assert (REPLAY_SRC / "replay" / "dependencies.py").is_file()


def test_the_member_declares_no_new_dependency() -> None:
    # The seam that reads the canary member's mark is an ``importlib`` at call
    # time, not an import statement, so this member's pyproject.toml keeps its
    # one-dependency shape — the workspace root and nothing else — and the
    # factory's scan pays nothing for a wall reached only by a caller about to
    # span a replay path.  A member that had *imported* a sibling would show up
    # here as a second dependency.
    text = (REPLAY_SRC.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dependencies = ["nullius"]' in text
    for sibling in ("canary", "evaluator", "sandbox", "artifacts", "policy-runtime"):
        assert f'"{sibling}"' not in text.split("dependencies")[1].split("\n")[0], (
            sibling
        )


def test_composition_carries_the_replay_path(app) -> None:
    assert replay.COMPONENT_NAME in app.order
    assert app.get(replay.COMPONENT_NAME) is not None


def test_the_composed_component_fronts_the_wall(app) -> None:
    # The one place a feature in this category asks the composed application
    # for the replay path — and the wall is on it, as a property rather than a
    # second ``replay-``prefixed component.
    engine = app.get(replay.COMPONENT_NAME)
    wall = engine.dependencies
    assert type(wall).__name__ == "ReplayPathDependencies"
    assert wall.refuses("evaluator") is True
    assert wall.refuses("sandbox") is True
    assert wall.refuses("artifacts") is False


def test_the_composed_wall_is_the_members_own(app) -> None:
    # The property a deployment depends on: the wall reached through the
    # composed application answers what the member's own spelling answers, so
    # there is no route to a second implementation by holding the component.
    engine = app.get(replay.COMPONENT_NAME)
    for name in ("evaluator", "sandbox", "artifacts", "artifact_store"):
        assert engine.dependencies.refuses(name) is replay.replay_path_forbids(name)


# ---------------------------------------------------------------------------
# The mark is feature 146's — one fact, not two
# ---------------------------------------------------------------------------


def test_the_canary_member_ships_the_mark_this_wall_reads() -> None:
    # The seam's precondition.  The wall reads ``canary.is_replaying`` through
    # ``importlib``; if the canary member stopped carrying that predicate the
    # wall would silently answer *not marked* for every replay — a wall that
    # never fires, which is the failure mode placement invites.
    member = _canary()
    if member is None:
        pytest.skip("the canary member is not on this process's path")
    assert callable(getattr(member, "is_replaying", None))
    assert callable(getattr(member, "replaying", None))


def test_a_real_replay_path_marks_the_wall(canary, spy) -> None:
    # **The cross-member seam.**  Inside the canary member's own replay path —
    # the extent feature 142's ``replay_pair`` enters around every nightly
    # replay — the wall refuses a forbidden reach.  Neither member may import
    # the other, so this is the only place the two halves of one law meet.
    assert replay.is_replaying() is False
    with canary.replaying():
        assert replay.is_replaying() is True
        with pytest.raises(replay.ForbiddenDependencyError) as raised:
            replay.reach(replay.EVALUATOR_DEPENDENCY, spy)
        assert type(raised.value).__name__ == "ForbiddenDependencyError"
        assert str(raised.value).startswith(replay.FORBIDDEN_DEPENDENCY_CODE)
    assert spy.calls == []
    assert replay.is_replaying() is False


def test_nested_extents_unwind_to_still_marked(canary, spy) -> None:
    # Feature 146's context manager restores rather than clears, so an extent
    # entered from inside another unwinds to *still replaying* — both extents
    # are the replay path, which is what makes a nested replay-shaped extent (a
    # runner reading a pair back inside the replay) guarded at every depth
    # rather than only at the outermost ``with``.
    with canary.replaying():
        with canary.replaying():
            assert replay.is_replaying() is True
            with pytest.raises(replay.ForbiddenDependencyError):
                replay.reach(replay.SANDBOX_DEPENDENCY, spy)
        assert replay.is_replaying() is True
    assert replay.is_replaying() is False
    assert spy.calls == []


def test_the_wall_is_silent_where_no_mark_exists(monkeypatch, spy) -> None:
    # A deployment that did not scan the canary member has no marked replay
    # path.  The honest answer is *not marked* — an absent component is a
    # discoverable state, not an exception — so the wall delegates rather than
    # refusing calls in an extent no replay entered.
    from replay import dependencies

    monkeypatch.setattr(dependencies, "_replay_path_mark", lambda: None)
    assert replay.is_replaying() is False
    assert replay.reach(replay.EVALUATOR_DEPENDENCY, spy) == "ran"
    assert spy.calls == [((), {})]


def test_the_wall_rides_the_mark_the_canary_member_owns(canary, monkeypatch) -> None:
    # **The one-fact check.**  If this member owned its own
    # :class:`~contextvars.ContextVar`, substituting the canary member's
    # predicate would leave the wall where it was.  So the substitution is made
    # at the *canary* end — the member that owns the mark — and the wall is
    # asked to move with it: a wall that still answered ``False`` after the
    # owning member said ``True`` would be reading a different mark.
    from replay import dependencies

    member = dependencies._replay_path_mark()
    assert member is not None, "the wall must find the canary member's predicate"
    monkeypatch.setattr(canary, "is_replaying", lambda: True)
    assert replay.is_replaying() is True
    spy = type("S", (), {"calls": [], "__call__": lambda self: self.calls.append(1) or "ran"})()
    with pytest.raises(replay.ForbiddenDependencyError):
        replay.reach(replay.SANDBOX_DEPENDENCY, spy)
    assert spy.calls == []


# ---------------------------------------------------------------------------
# The grant, through the composed spelling
# ---------------------------------------------------------------------------


def test_a_granted_reach_is_delegated_inside_a_real_extent(canary, spy) -> None:
    # §1's other half, inside the mark a real replay sets: the artifact store
    # is *what the replay engine has read access to*, and the wall must not
    # intercept it — a wall that refused every name while marked would refuse
    # the very read §1 promises, and would be the reason dreaming was not free.
    with canary.replaying():
        assert replay.reach("artifacts", spy, "campaign") == "ran"
    assert spy.calls == [(("campaign",), {})]


def test_the_composed_wall_delegates_the_granted_reach(canary, spy, app) -> None:
    engine = app.get(replay.COMPONENT_NAME)
    with canary.replaying():
        assert engine.dependencies.reach("artifact_store", spy) == "ran"
    assert spy.calls == [((), {})]


# ---------------------------------------------------------------------------
# The wall is the member's own vocabulary, composed
# ---------------------------------------------------------------------------


def test_the_composed_refusal_carries_the_code(canary, app, spy) -> None:
    # Feature 247's sentence names the code the refusal returns, and the code is
    # not the composed spelling's to change: whatever module object the loader
    # executed the wall under, the message opens with the same word.  The mark
    # is the *canary member's* real one — the composed wall reads it through the
    # same one-fact seam the composed component's own module does — so this check
    # needs no substitution at all.
    engine = app.get(replay.COMPONENT_NAME)
    with canary.replaying(), pytest.raises(Exception) as raised:
        engine.dependencies.evaluator(spy)
    assert type(raised.value).__name__ == "ForbiddenDependencyError"
    assert str(raised.value).startswith(replay.FORBIDDEN_DEPENDENCY_CODE)
    assert str(raised.value) == str(replay.refused_dependency(replay.EVALUATOR_DEPENDENCY, spy))
    assert spy.calls == []


def test_the_member_registers_one_component_still() -> None:
    # Features 246 and 247 add no component: the wall is a fact about the path,
    # so the member's one ``@register`` contribution stays feature 245's facade
    # — the rule the package ``__init__`` states (one component per member
    # name), and the reason the wall rides the facade as a property.
    from app.module_loader import Registration, scan_components

    components = scan_components(REPLAY_SRC, registry=Registration())
    assert [component.name for component in components] == [replay.COMPONENT_NAME]
