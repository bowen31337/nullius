"""Feature 4, the exploration policy — the law that picks the next batch.

additions_spec_campaign_driver.xml, "Exploration Policy" category, feature 4:
*System creates the exploration policy that selects the next batch of nodes to
expand, with orchestrator._policy.load_exploration_policy(env=None). The
policy's select(prefix_view) answers a list of node ids.*

One test per claim the feature sentence makes:

* **the baseline, unconfigured** — an unset or blank
  ``NULLIUS_EXPLORATION_POLICY`` answers :class:`~orchestrator._policy.BaselinePolicy`
  at the module's default width, highest ``ic_insample`` first, at most one
  per theme root per batch, ties broken by node id, and ``[]`` for a view with
  no revealed node.
* **the admitted path** — a named file whose text :func:`policy_runtime.screen_policy`
  admits is imported as :data:`policy_runtime.POLICY_MODULE_NAME`, runs under
  :func:`policy_runtime.guard_policy` on every call (a filesystem reach and an
  import outside the ceiling are both refused, at import time and at call
  time), and its top-level ``select`` becomes the policy.
* **the refusals** — a refused admission, an unreadable file, an admitted file
  with no ``select``, and a malformed answer (non-list, a duplicate id, an id
  outside the view) all raise :class:`~orchestrator._policy.PolicyLoadError`,
  naming the module's own code word.

This suite builds real :class:`policy_runtime.PrefixView` objects from real
:class:`policy_runtime.PolicyObservation` cells rather than mocking either —
the seam under test is exactly "does a real view get ranked and validated
correctly" — and runs real source text through the real
:func:`policy_runtime.screen_policy` gate and :func:`policy_runtime.guard_policy`
guard, the same discipline :mod:`test_live_tree` and policy-runtime's own
:mod:`test_guard` keep for their seams. No test opens a network connection or
reads a real credential.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from orchestrator._policy import (
    DEFAULT_BASELINE_WIDTH,
    EXPLORATION_POLICY_ENV,
    POLICY_LOAD_CODE,
    BaselinePolicy,
    ExplorationPolicy,
    PolicyLoadError,
    load_exploration_policy,
)
from policy_runtime import (
    POLICY_MODULE_NAME,
    PolicyFilesystemError,
    PolicyImportError,
    PolicyObservation,
    PrefixView,
)

# ---------------------------------------------------------------------------
# Building real prefix views, without a campaign tree or a question
# ---------------------------------------------------------------------------


def _observation(node_id: str, ic_insample: float | None) -> PolicyObservation:
    return PolicyObservation(
        node_id=node_id,
        r2_insample=None if ic_insample is None else ic_insample**2,
        ic_insample=ic_insample,
        n_periods=500,
        n_features=1,
    )


def _view(**ic_by_node: float) -> PrefixView:
    return PrefixView(cells=[_observation(node_id, ic) for node_id, ic in ic_by_node.items()])


class _ThemedView:
    """A prefix-view double that also answers ``meta(node_id).theme_root``.

    The real :class:`~policy_runtime.PrefixView` carries no theme at all (see
    :mod:`orchestrator._policy`'s module docstring for why), so this is the
    only way to exercise :class:`~orchestrator._policy.BaselinePolicy`'s
    per-theme cap: a double that duck-types the richer ``meta()`` seam the
    baseline reads when a view happens to expose one.
    """

    def __init__(self, cells: dict[str, PolicyObservation], themes: dict[str, str]) -> None:
        self._cells = cells
        self._themes = themes

    def observed(self) -> dict[str, PolicyObservation]:
        return dict(self._cells)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._cells

    def meta(self, node_id: str) -> Any:
        return _Meta(self._themes[node_id])


class _Meta:
    def __init__(self, theme_root: str) -> None:
        self.theme_root = theme_root


# ---------------------------------------------------------------------------
# BaselinePolicy, direct
# ---------------------------------------------------------------------------


def test_baseline_ranks_by_ic_insample_descending() -> None:
    view = _view(n1=0.2, n2=0.9, n3=0.5)
    assert BaselinePolicy(3).select(view) == ["n2", "n3", "n1"]


def test_baseline_breaks_ties_by_node_id() -> None:
    view = _view(b=0.5, a=0.5, c=0.5)
    assert BaselinePolicy(3).select(view) == ["a", "b", "c"]


def test_baseline_caps_the_batch_at_its_width() -> None:
    view = _view(n1=0.9, n2=0.8, n3=0.7, n4=0.6)
    assert BaselinePolicy(2).select(view) == ["n1", "n2"]


def test_baseline_answers_empty_for_a_view_with_no_revealed_node() -> None:
    assert BaselinePolicy(5).select(_view()) == []


def test_baseline_width_must_be_a_positive_int() -> None:
    for bad_width in (0, -1, 1.5, True, "3", None):
        with pytest.raises(PolicyLoadError) as excinfo:
            BaselinePolicy(bad_width)  # type: ignore[arg-type]
        assert POLICY_LOAD_CODE in str(excinfo.value)


def test_baseline_without_a_theme_signal_fills_the_batch() -> None:
    # The real PrefixView carries no theme_root at all, so every node stands
    # as its own singleton theme -- the cap must never collapse a real,
    # bare view's batch to one pick merely because no theme exists to divide.
    view = _view(n1=0.9, n2=0.8, n3=0.7)
    assert BaselinePolicy(3).select(view) == ["n1", "n2", "n3"]


def test_baseline_caps_at_one_pick_per_theme_root() -> None:
    cells = {
        node_id: _observation(node_id, ic)
        for node_id, ic in (("n1", 0.9), ("n2", 0.8), ("n3", 0.7), ("n4", 0.6))
    }
    themes = {"n1": "momentum", "n2": "momentum", "n3": "value", "n4": "value"}
    view = _ThemedView(cells, themes)

    # Highest ic first is n1 (momentum); n2 is also momentum and is skipped;
    # n3 (value) is next distinct theme; n4 (value) is skipped too.
    assert BaselinePolicy(3).select(view) == ["n1", "n3"]


def test_baseline_one_per_theme_root_still_breaks_remaining_ties_by_node_id() -> None:
    cells = {
        node_id: _observation(node_id, ic)
        for node_id, ic in (("z", 0.5), ("a", 0.5), ("m", 0.9))
    }
    themes = {"z": "value", "a": "value", "m": "momentum"}
    view = _ThemedView(cells, themes)

    # m (momentum, 0.9) ranks first; among the 0.5 tie, "a" sorts before "z",
    # and only one of them (the momentum theme is already used by "m", so the
    # tie is purely within "value") is taken for the second, distinct theme.
    assert BaselinePolicy(2).select(view) == ["m", "a"]


# ---------------------------------------------------------------------------
# load_exploration_policy: unset environment -> the baseline
# ---------------------------------------------------------------------------


def test_unset_env_answers_the_default_baseline() -> None:
    policy = load_exploration_policy(env={})
    assert isinstance(policy, ExplorationPolicy)
    view = _view(**{f"n{i}": float(i) for i in range(DEFAULT_BASELINE_WIDTH + 2)})
    # The default baseline's own width caps the answer -- it is not simply
    # "every revealed node".
    assert len(policy.select(view)) == DEFAULT_BASELINE_WIDTH


def test_blank_env_value_is_treated_as_unset() -> None:
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: "   "})
    assert policy.select(_view(n1=0.1)) == ["n1"]


def test_env_none_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EXPLORATION_POLICY_ENV, raising=False)
    policy = load_exploration_policy(env=None)
    assert policy.select(_view()) == []


# ---------------------------------------------------------------------------
# load_exploration_policy: a named file that cannot even be read
# ---------------------------------------------------------------------------


def test_refuses_a_policy_file_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.py"
    with pytest.raises(PolicyLoadError) as excinfo:
        load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(missing)})
    assert POLICY_LOAD_CODE in str(excinfo.value)


# ---------------------------------------------------------------------------
# load_exploration_policy: screen_policy refuses the source
# ---------------------------------------------------------------------------


NO_COMMIT_SOURCE = "def select(prefix_view):\n    return list(prefix_view.observed())\n"


def test_refuses_a_source_screen_policy_refuses(tmp_path: Path) -> None:
    source_file = tmp_path / "policy.py"
    source_file.write_text(NO_COMMIT_SOURCE, encoding="utf-8")

    with pytest.raises(PolicyLoadError) as excinfo:
        load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    message = str(excinfo.value)
    assert POLICY_LOAD_CODE in message
    assert "unreachable-commit" in message


# ---------------------------------------------------------------------------
# load_exploration_policy: the admitted path
# ---------------------------------------------------------------------------

#: A policy admitted by policy_runtime.screen_policy: no absolute score
#: constant, no hardcoded node id, and every terminating path's own return
#: statement performs the required `.commit(...)` call directly (so the
#: static reachability check, which is path-sensitive but not loop-aware, is
#: satisfied without needing an unbounded `while True`).
ADMITTED_SELECT_SOURCE = """
class _Sink:
    def commit(self, value):
        return value


def select(prefix_view):
    sink = _Sink()
    observed = prefix_view.observed()
    if not observed:
        return sink.commit([])
    ranked = sorted(observed, key=lambda node_id: (-observed[node_id].ic_insample, node_id))
    return sink.commit(ranked[:2])
"""


def _write(tmp_path: Path, source: str, name: str = "policy.py") -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_admitted_policy_is_imported_as_the_policy_module_name(tmp_path: Path) -> None:
    source_file = _write(tmp_path, ADMITTED_SELECT_SOURCE)
    load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    assert POLICY_MODULE_NAME in sys.modules
    assert sys.modules[POLICY_MODULE_NAME].__name__ == POLICY_MODULE_NAME
    assert callable(sys.modules[POLICY_MODULE_NAME].select)


def test_admitted_policys_select_answers_the_configured_batch(tmp_path: Path) -> None:
    source_file = _write(tmp_path, ADMITTED_SELECT_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    view = _view(n1=0.9, n2=0.8, n3=0.7)
    assert policy.select(view) == ["n1", "n2"]


def test_admitted_policys_select_runs_under_the_guard_for_every_call(
    tmp_path: Path,
) -> None:
    reaching_source = """
class _Sink:
    def commit(self, value):
        return value


def select(prefix_view):
    sink = _Sink()
    data = open("/etc/hostname").read()
    return sink.commit([])
"""
    source_file = _write(tmp_path, reaching_source)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    with pytest.raises(PolicyFilesystemError):
        policy.select(_view(n1=0.1))


def test_admitted_policy_is_guarded_at_import_time_too(tmp_path: Path) -> None:
    importing_source = """
import subprocess


class _Sink:
    def commit(self, value):
        return value


def select(prefix_view):
    sink = _Sink()
    return sink.commit([])
"""
    source_file = _write(tmp_path, importing_source)

    with pytest.raises(PolicyImportError):
        load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})


def test_refuses_an_admitted_file_with_no_select_function(tmp_path: Path) -> None:
    no_select_source = ADMITTED_SELECT_SOURCE.replace("def select(", "def choose(")
    source_file = _write(tmp_path, no_select_source)

    with pytest.raises(PolicyLoadError) as excinfo:
        load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    assert POLICY_LOAD_CODE in str(excinfo.value)


# ---------------------------------------------------------------------------
# The answer is checked -- for the admitted path, where it actually bites
# ---------------------------------------------------------------------------


def _policy_from(tmp_path: Path, select_body: str) -> ExplorationPolicy:
    source = f"""
class _Sink:
    def commit(self, value):
        return value


def select(prefix_view):
    sink = _Sink()
{select_body}
"""
    source_file = _write(tmp_path, source)
    return load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})


def test_refuses_a_non_list_answer(tmp_path: Path) -> None:
    # A bare integer, not a hardcoded-node-id-shaped literal, so the static
    # gate admits the source and the shape check is what actually bites.
    policy = _policy_from(tmp_path, "    return sink.commit(42)")
    with pytest.raises(PolicyLoadError) as excinfo:
        policy.select(_view(n1=0.1))
    assert POLICY_LOAD_CODE in str(excinfo.value)


def test_refuses_a_duplicate_id_in_the_answer(tmp_path: Path) -> None:
    # A UUID-shaped literal is excluded from the hardcoded-node-id check
    # (feature 230), so this source is admitted and the duplicate is what the
    # answer check catches.
    uuid_literal = "123e4567-e89b-12d3-a456-426614174000"
    policy = _policy_from(
        tmp_path, f"    return sink.commit(['{uuid_literal}', '{uuid_literal}'])"
    )
    with pytest.raises(PolicyLoadError) as excinfo:
        policy.select(_view(n1=0.1))
    assert POLICY_LOAD_CODE in str(excinfo.value)


def test_refuses_an_id_outside_the_view(tmp_path: Path) -> None:
    policy = _policy_from(tmp_path, "    return sink.commit(['ghost'])")
    with pytest.raises(PolicyLoadError) as excinfo:
        policy.select(_view(n1=0.1))
    assert POLICY_LOAD_CODE in str(excinfo.value)


# ---------------------------------------------------------------------------
# The module's surface
# ---------------------------------------------------------------------------


def test_module_surface() -> None:
    import orchestrator._policy as policy_module

    assert set(policy_module.__all__) == {
        "DEFAULT_BASELINE_WIDTH",
        "EXPLORATION_POLICY_ENV",
        "POLICY_LOAD_CODE",
        "BaselinePolicy",
        "ExplorationPolicy",
        "PolicyLoadError",
        "load_exploration_policy",
    }
    assert issubclass(PolicyLoadError, Exception)
    assert isinstance(POLICY_LOAD_CODE, str) and POLICY_LOAD_CODE
    assert isinstance(DEFAULT_BASELINE_WIDTH, int) and DEFAULT_BASELINE_WIDTH > 0
