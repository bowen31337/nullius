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
* **declared abstention, question contract** — a ``CONTRACT = "question"``
  fixture whose ``select`` calls ``question.abstain()`` is admitted, answers
  its batch through :meth:`~orchestrator._policy.ExplorationPolicy.select`
  without the ``AttributeError`` the bare front raised, and its declaration
  reaches the real one-way door (:class:`policy_runtime.PolicyCommitError`
  for a commit that follows it); driven through the real
  :func:`~orchestrator._campaign.run_campaign` round loop, against a
  throwaway fully migrated SQLite database, it runs one round that expands
  exactly the ids it returns.

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

import datetime as dt
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import discovery
import providers
import pytest
import signal_agent
from orchestrator._campaign import STOP_ROUND_CAP, run_campaign
from orchestrator._policy import (
    DEFAULT_BASELINE_WIDTH,
    EXPLORATION_POLICY_ENV,
    POLICY_LOAD_CODE,
    PREFIX_VIEW_CONTRACT,
    QUESTION_CONTRACT,
    BaselinePolicy,
    ExplorationPolicy,
    PolicyLoadError,
    load_exploration_policy,
)
from policy_runtime import (
    POLICY_MODULE_NAME,
    UNBOUNDED_BUDGET,
    CampaignTree,
    PolicyCommitError,
    PolicyFilesystemError,
    PolicyImportError,
    PolicyObservation,
    PolicyQuestion,
    PrefixView,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up — the same resolution
# test_m2_incumbent_equivalence.py and test_incumbent_example.py use to reach
# the real deploy/dreaming/*.py files this suite also drives.
REPO_ROOT = Path(__file__).resolve().parents[3]
INCUMBENT_M2_PATH = REPO_ROOT / "deploy" / "dreaming" / "incumbent.m2.py"
INCUMBENT_EXAMPLE_PATH = REPO_ROOT / "deploy" / "dreaming" / "incumbent.example.py"

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
# The question contract -- additions_spec_dreaming_m3.xml, "Dreaming
# Preconditions", feature 6
# ---------------------------------------------------------------------------
#
# A question-contract module declares CONTRACT = "question" and is called
# with the campaign's live question (a real policy_runtime.PolicyQuestion
# over a real policy_runtime.CampaignTree here, built directly rather than
# through a live campaign database -- the seam under test is "does
# ExplorationPolicy wire select(question) and validate its answer
# correctly", exactly as the prefix-view tests above build real PrefixView
# objects rather than a live campaign).


#: A question-contract fixture admitted by policy_runtime.screen_policy --
#: every terminating path of ``select`` reaches its own ``question.commit(``
#: call directly, the same structure deploy/dreaming/incumbent.example.py
#: itself uses (see that module's own docstring).
QUESTION_CONTRACT_SOURCE = """
CONTRACT = "question"


def select(question):
    observed = question.observed()
    if not observed:
        roots = question.legal_roots()
        question.commit(roots[0])
        return list(roots)
    ranked = sorted(observed, key=lambda node_id: (-observed[node_id].ic_insample, node_id))
    question.commit(ranked[0])
    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier
"""


def _question(payloads: dict[str, tuple[str | None, int, dict[str, Any]]]) -> PolicyQuestion:
    return PolicyQuestion(CampaignTree.freeze(payloads))


def test_unmarked_admitted_module_keeps_the_prefix_view_contract(tmp_path: Path) -> None:
    source_file = _write(tmp_path, ADMITTED_SELECT_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    assert policy.contract == PREFIX_VIEW_CONTRACT


def test_unset_env_baseline_is_the_prefix_view_contract() -> None:
    policy = load_exploration_policy(env={})
    assert policy.contract == PREFIX_VIEW_CONTRACT


def test_question_marked_module_is_loaded_with_the_question_contract(tmp_path: Path) -> None:
    source_file = _write(tmp_path, QUESTION_CONTRACT_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    assert policy.contract == QUESTION_CONTRACT


def test_question_contract_select_with_nothing_observed_commits_a_root_and_returns_roots(
    tmp_path: Path,
) -> None:
    source_file = _write(tmp_path, QUESTION_CONTRACT_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    question = _question({"root-b": (None, 0, {}), "root-a": (None, 0, {})})

    # question.commit("root-a") is reached inside select() -- without the
    # merged front's commit door this call raises AttributeError, the exact
    # bug additions_spec_dreaming_m3.xml's audit names.
    assert policy.select(question) == ["root-a", "root-b"]


def test_question_contract_select_with_observed_nodes_commits_and_returns_the_frontier(
    tmp_path: Path,
) -> None:
    source_file = _write(tmp_path, QUESTION_CONTRACT_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    question = _question(
        {
            "root": (None, 0, {"ic_insample": 0.5}),
            "child": ("root", 1, {}),
        }
    )
    question.reveal_many(["root"])

    assert policy.select(question) == ["child"]


def test_question_contract_caps_at_the_campaign_width(tmp_path: Path) -> None:
    source_file = _write(tmp_path, QUESTION_CONTRACT_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    question = _question({"root-a": (None, 0, {}), "root-b": (None, 0, {})})
    assert policy.select(question)[:1] == ["root-a"]


#: Commits a legal root, then answers a batch an id outside it.
_BAD_ANSWER_QUESTION_SOURCE = """
CONTRACT = "question"


def select(question):
    roots = question.legal_roots()
    question.commit(roots[0])
    return ["ghost"]
"""

#: Commits a legal root, then repeats one id in its own answer.
_DUPLICATE_ANSWER_QUESTION_SOURCE = """
CONTRACT = "question"


def select(question):
    roots = question.legal_roots()
    question.commit(roots[0])
    return [roots[0], roots[0]]
"""

#: Commits a legal root, then answers something that is not a sequence at all.
_NON_SEQUENCE_ANSWER_QUESTION_SOURCE = """
CONTRACT = "question"


def select(question):
    roots = question.legal_roots()
    question.commit(roots[0])
    return 42
"""


def test_question_contract_refuses_an_id_outside_the_tree(tmp_path: Path) -> None:
    source_file = _write(tmp_path, _BAD_ANSWER_QUESTION_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    question = _question({"root": (None, 0, {})})

    with pytest.raises(PolicyLoadError) as excinfo:
        policy.select(question)
    assert POLICY_LOAD_CODE in str(excinfo.value)


def test_question_contract_refuses_a_duplicate_id_in_the_answer(tmp_path: Path) -> None:
    source_file = _write(tmp_path, _DUPLICATE_ANSWER_QUESTION_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    question = _question({"root": (None, 0, {})})

    with pytest.raises(PolicyLoadError) as excinfo:
        policy.select(question)
    assert POLICY_LOAD_CODE in str(excinfo.value)


def test_question_contract_refuses_a_non_sequence_answer(tmp_path: Path) -> None:
    source_file = _write(tmp_path, _NON_SEQUENCE_ANSWER_QUESTION_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    question = _question({"root": (None, 0, {})})

    with pytest.raises(PolicyLoadError) as excinfo:
        policy.select(question)
    assert POLICY_LOAD_CODE in str(excinfo.value)


def test_question_contract_accepts_a_tuple_answer_like_incumbent_m2(tmp_path: Path) -> None:
    # incumbent.m2.py answers () -- a tuple, not a list -- on its
    # non-committing path; the question contract's own validator must accept
    # it, unlike the stricter prefix-view contract's list-only check.
    tuple_answer_source = """
CONTRACT = "question"


def select(question):
    roots = question.legal_roots()
    question.commit(roots[0])
    return ()
"""
    source_file = _write(tmp_path, tuple_answer_source)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    question = _question({"root": (None, 0, {})})

    assert policy.select(question) == []


# ---------------------------------------------------------------------------
# Declared abstention — question.abstain() through the front, beside commit()
# ---------------------------------------------------------------------------
#
# The front's commit door carries two ways through it (policy_runtime's own
# EpisodeCommit: "one door, two ways through it, and no episode takes both"),
# and a question-contract policy that declares it commits nothing must reach
# the same door commit() does rather than an AttributeError. The abstaining
# fixture's own return goes through a _Sink's commit() — the device
# ADMITTED_SELECT_SOURCE already uses — because the static gate demands every
# terminating path reach a commit() call and counts the attribute, not the
# receiver, so the fixture is admitted today and after abstain() is counted
# wherever commit() is.

#: A question-contract fixture that declares it commits nothing: reaches its
#: own ``question.abstain()`` and answers the legal roots as its batch.
ABSTAINING_QUESTION_SOURCE = """
CONTRACT = "question"


class _Sink:
    def commit(self, value):
        return value


def select(question):
    sink = _Sink()
    roots = question.legal_roots()
    question.abstain()
    return sink.commit(list(roots))
"""

#: The same declaration, followed by the one act the door refuses after it —
#: the probe that tells a real abstention from a silent no-op.
_ABSTAIN_THEN_COMMIT_QUESTION_SOURCE = """
CONTRACT = "question"


def select(question):
    roots = question.legal_roots()
    question.abstain()
    question.commit(roots[0])
    return list(roots)
"""


def test_question_contract_abstaining_select_returns_its_batch(tmp_path: Path) -> None:
    source_file = _write(tmp_path, ABSTAINING_QUESTION_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    question = _question({"root-b": (None, 0, {}), "root-a": (None, 0, {})})

    # question.abstain() is reached inside select() -- without the front's
    # own abstain door this call raises AttributeError, the fault this
    # feature closes ("'_QuestionContractFront' object has no attribute
    # 'abstain'"), and the batch it answers is exactly the ids it names.
    assert policy.select(question) == ["root-a", "root-b"]


def test_question_contract_abstain_reaches_the_real_commit_door(tmp_path: Path) -> None:
    source_file = _write(tmp_path, _ABSTAIN_THEN_COMMIT_QUESTION_SOURCE)
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    question = _question({"root-a": (None, 0, {}), "root-b": (None, 0, {})})

    # The declaration landed on the EpisodeCommit the front joins, not on a
    # stub: the commit that follows it is refused by the door's own one-act
    # law, naming the abstention. A front whose abstain() were a silent
    # no-op would let this select return its batch instead of raising.
    with pytest.raises(PolicyCommitError) as excinfo:
        policy.select(question)
    assert "abstained" in str(excinfo.value)


# ---------------------------------------------------------------------------
# An unknown CONTRACT is refused at load, not at the first round
# ---------------------------------------------------------------------------

UNKNOWN_CONTRACT_SOURCE = """
CONTRACT = "bogus"


def select(question):
    roots = question.legal_roots()
    question.commit(roots[0])
    return []
"""


def test_unknown_contract_is_refused_at_load(tmp_path: Path) -> None:
    source_file = _write(tmp_path, UNKNOWN_CONTRACT_SOURCE)

    with pytest.raises(PolicyLoadError) as excinfo:
        load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})

    message = str(excinfo.value)
    assert POLICY_LOAD_CODE in message
    assert "bogus" in message


# ---------------------------------------------------------------------------
# The real dreaming deploy files -- additions_spec_dreaming_m3.xml feature 6's
# own named test subjects
# ---------------------------------------------------------------------------


def test_incumbent_m2_is_admitted_as_a_question_contract_policy() -> None:
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(INCUMBENT_M2_PATH)})
    assert policy.contract == QUESTION_CONTRACT

    # Nothing clears the M2 fixed rule's discovery bar -- select() commits
    # nothing and answers its non-committing (), accepted as [].
    question = _question({"root": (None, 0, {"ic_insample": 0.1})})
    question.reveal_many(["root"])
    assert policy.select(question) == []


def test_incumbent_m2_commits_the_node_that_clears_the_bar(tmp_path: Path) -> None:
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(INCUMBENT_M2_PATH)})

    # ic_insample 3.0 clears the M2 rule's fixed 2.0 discovery bar -- this
    # exercises question.commit(...) through the merged front without
    # raising, the exact AttributeError additions_spec_dreaming_m3.xml's
    # audit names ("_campaign.py:752 ... AttributeError: 'PrefixView' object
    # has no attribute 'legal_roots'").
    question = _question({"root": (None, 0, {"ic_insample": 3.0})})
    question.reveal_many(["root"])
    assert policy.select(question) == []


def test_incumbent_example_is_admitted_as_a_question_contract_policy() -> None:
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(INCUMBENT_EXAMPLE_PATH)})
    assert policy.contract == QUESTION_CONTRACT

    question = _question({"root-a": (None, 0, {}), "root-b": (None, 0, {})})
    assert policy.select(question) == ["root-a", "root-b"]


# ---------------------------------------------------------------------------
# One campaign round driven by an abstaining question-contract policy
# ---------------------------------------------------------------------------
#
# The verification this feature is judged by: a CONTRACT = "question" fixture
# that abstains drives one *live* campaign round without error, and the round
# expands exactly the ids the policy returns. The harness is this suite's own
# copy of the one test_campaign.py, test_campaign_resume.py and
# test_concurrent_evaluation.py each carry (there is no shared conftest): a
# throwaway fully migrated SQLite database, the three fakes the campaign spec
# names explicitly, and the real run_campaign round loop.


CAMPAIGN_MIGRATION = "0111_campaign_table"

#: The assembled chain the tree's columns fill, in the order the chain
#: actually widens it — ``0118`` creates ``node`` empty, and only then do
#: ``0117``-``0114`` add their ``NOT NULL`` columns.
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
    "0114_node_metrics",
)

CAMPAIGN_SOURCE = "def signal(ctx):\n    return ctx.close.pct_change(20)\n"
CAMPAIGN_PROPOSAL = "Mechanism: fades crowded carry.\n```python\n" + CAMPAIGN_SOURCE + "```\n"

#: Real, well-formed pins — the same literals test_campaign.py already
#: exercises, reused here rather than invented.
ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
DEPTH_PIN = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
SAMPLING = providers.AgentSampling(temperature=0.4, seed=7)
USAGE = providers.Usage(input_tokens=1_000, output_tokens=200)

#: A single-member frontier tier naming exactly :data:`ROOT_PIN`'s own
#: family, for the reason test_campaign.py gives: a tier of one member is
#: always assigned to itself, so every root records cleanly.
ROOT_TIER = providers.FrontierTier(
    providers=(providers.FrontierProvider(ROOT_PIN.provider, ROOT_PIN.model),)
)


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner."""
    versions_dir = REPO_ROOT / "migrations" / "versions"
    path = versions_dir / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the campaign and "
            "node tables' own migrations rather than hand-writing their DDL"
        )
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_policy_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'abstaining-round-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


class _CampaignContext:
    """The subset of ``orchestrator._context.EvaluationContext`` the round reads.

    The same fake test_campaign.py's own ``_Context`` is — the provenance
    trio, the database URL, the artifact directory and the evaluation grid's
    length (``evaluation_periods``, for
    :func:`~orchestrator._live_tree.live_question`) — plus the one
    evaluation slot explained below.
    """

    def __init__(self, database_url: str, artifact_dir: Path) -> None:
        self.database_url = database_url
        self.evaluator_hash = hashlib.sha256(b"evaluator").hexdigest()
        self.snapshot_hash = hashlib.sha256(b"snapshot").hexdigest()
        self.cost_model_hash = hashlib.sha256(b"cost-model").hexdigest()
        self.artifact_dir = artifact_dir
        self.evaluation_dates = (dt.date(2026, 1, 2), dt.date(2026, 1, 3))
        # One evaluation slot, the knob bug_spec_evaluation_throughput.xml
        # added for exactly this duck-typed context: this suite's only
        # campaign round expands a two-node batch, and two concurrent
        # first writers race the attempt store's own ensure-column
        # fallback (``ALTER TABLE node ADD COLUMN fail_class``) in a
        # fresh database. Serial slots keep the throwaway-DB test
        # deterministic; the round loop, the batch and the expansion are
        # unchanged by it.
        self.evaluation_workers = 1


class _SequenceAuthor:
    """``author.author_root`` for planting, ``author(workspace)`` for expansion."""

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        record = providers.AuthoringRecord(
            node_id=str(root_id),
            campaign_id=campaign_id,
            depth=0,
            role="root",
            pin=ROOT_PIN,
            sampling=SAMPLING,
            usage=USAGE,
            served_model=ROOT_PIN.model,
            tier=ROOT_TIER,
        )
        return SimpleNamespace(
            code=CAMPAIGN_SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=CAMPAIGN_PROPOSAL,
            record=record,
        )

    def __call__(self, workspace: Any) -> Any:
        child_id = discovery.refined_node_id(workspace.node_id)
        record = providers.AuthoringRecord(
            node_id=child_id,
            campaign_id=workspace.campaign_id,
            depth=workspace.depth + 1,
            role="depth",
            pin=DEPTH_PIN,
            sampling=SAMPLING,
            usage=USAGE,
            served_model=DEPTH_PIN.model,
        )
        return SimpleNamespace(
            code=CAMPAIGN_SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=CAMPAIGN_PROPOSAL,
            record=record,
        )


class _FakeEvaluator:
    """A fake evaluator answering one fixed, budget-charging evaluation."""

    def __init__(self) -> None:
        self._score = signal_agent.ScoreRecord(ic_mean=0.1, ic_tstat=2.0)

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        return SimpleNamespace(
            node_id=node_id,
            fail_class=None,
            score=self._score,
            charges_budget=True,
        )


class _FakeSidecarSelection:
    """The Type-R seal this test never reads back."""

    def persist(self, campaign_id: str) -> None:
        return None


def test_an_abstaining_question_contract_policy_drives_one_campaign_round(
    tree_database: str, tmp_path: Path
) -> None:
    author = _SequenceAuthor()
    evaluator = _FakeEvaluator()
    sidecar = _FakeSidecarSelection()
    events: list[dict[str, Any]] = []
    context = _CampaignContext(tree_database, tmp_path / "artifacts")
    source_file = _write(tmp_path, ABSTAINING_QUESTION_SOURCE, name="abstaining.py")
    policy = load_exploration_policy(env={EXPLORATION_POLICY_ENV: str(source_file)})
    assert policy.contract == QUESTION_CONTRACT

    result = run_campaign(
        campaign_type="Type-D",
        workspaces=2,
        rounds=1,
        width=2,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=policy,
        context=context,
        sidecar_selection=sidecar,
        emit=events.append,
    )

    # The fixture abstains and answers both planted roots as its batch, so
    # the round expands exactly those ids -- one refined child per root,
    # neither more nor fewer -- and the round cap, not an AttributeError
    # from the abstain() call, is what stops the campaign. The round event
    # pins the batch the loop actually dispatched: both of the policy's
    # ids, unsliced (width 2) and unshrunk.
    assert result.stop_reason == STOP_ROUND_CAP
    assert result.rounds_run == 1
    assert len(result.roots) == 2
    round_events = [event for event in events if event["event"] == "round"]
    assert len(round_events) == 1
    assert round_events[0]["batch_size"] == 2
    expanded = {discovery.refined_node_id(root_id) for root_id in result.roots}
    assert set(result.nodes) == expanded
    assert len(result.nodes) == 2


# ---------------------------------------------------------------------------
# The module's surface
# ---------------------------------------------------------------------------


def test_module_surface() -> None:
    import orchestrator._policy as policy_module

    assert set(policy_module.__all__) == {
        "DEFAULT_BASELINE_WIDTH",
        "EXPLORATION_POLICY_ENV",
        "POLICY_LOAD_CODE",
        "PREFIX_VIEW_CONTRACT",
        "QUESTION_CONTRACT",
        "BaselinePolicy",
        "ExplorationPolicy",
        "PolicyLoadError",
        "load_exploration_policy",
    }
    assert issubclass(PolicyLoadError, Exception)
    assert isinstance(POLICY_LOAD_CODE, str) and POLICY_LOAD_CODE
    assert isinstance(DEFAULT_BASELINE_WIDTH, int) and DEFAULT_BASELINE_WIDTH > 0
    assert PREFIX_VIEW_CONTRACT != QUESTION_CONTRACT
