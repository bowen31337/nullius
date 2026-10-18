"""The M3 incumbent — ``deploy/dreaming/incumbent.m3.py``.

docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md, Addendum 3:
*"The incumbent is ``deploy/dreaming/incumbent.m3.py`` (CONTRACT
``question``), admitted by the strict gate."* Addendum 3's own *"The refused
attempt"* records why the two shipped policies cannot be it: cycle
``m3-attempt-1`` swept 41 candidates of ``deploy/dreaming/incumbent.m2.py``
over the 45 bootstrap train worlds and was refused at selection with
``selection_ungrounded`` — every candidate abstained on **all 45**, because
the M2 fixed rule only picks among nodes that are already evaluated and a
bootstrap world reveals nothing until a policy asks. And
``deploy/dreaming/incumbent.example.py``, which does explore, raises
``TypeError`` on a financial world: it subtracts from ``observation.r2_train``,
which is ``None`` on a node whose ``ic_mean`` is ``NULL``.

This suite is the regression test for the fix, and its two halves pin both
motivating defects beside the new module's own behaviour:

* :func:`test_the_m2_rule_abstains_on_every_bootstrap_domain` — the refused
  attempt's cause, reproduced: the M2 rule misses on every world of all three
  domains.
* :func:`test_the_example_incumbent_raises_on_a_financial_world` — the second
  shipped policy's defect, reproduced through the real financial replay.
* everything else — the new module: admitted under the strict question-contract
  rule, exploring and committing on one world per bootstrap domain, deciding
  once on a financial world (committing the z-top node when it clears,
  abstaining when it does not or when too few nodes carry a reading, never
  raising on a ``NULL``-``ic_mean`` node), and still admissible after the
  jitter reviser has revised it.

Fixtures only: a throwaway, migrated SQLite database per test (``0111``'s
``campaign`` table and ``0118``/``0114``'s ``node`` table, the lighter set
``test_dream_financial_worlds.py`` already proves is enough to drive
:func:`orchestrator._financial_eval.score_on_financial_world` directly), and a
tmp store holding one persisted bootstrap world per domain. The expensive,
sandboxed act — the out-of-sample read a committed financial pick is scored by
— is the one thing stubbed, monkeypatched onto
:mod:`orchestrator._financial_eval` exactly as ``test_dream_financial_worlds.py``
and ``test_m2_incumbent_equivalence.py`` stub it, because a real sealed snapshot
and a real sandbox are ``test_closeout_commit_oos.py``'s concern, not this
suite's. No test opens a network connection or reads a real credential, and no
state is kept at module scope across tests, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import math
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import dreaming
import policy_runtime
import pytest
from artifacts import ArtifactStore
from bootstrap import FEATSEL_DOMAIN, POOL_DOMAIN, SYMREG_DOMAIN, BootstrapPool
from orchestrator import _financial_eval, _policy
from orchestrator._bootstrap_eval import score_on_world
from orchestrator._financial_eval import FinancialEvalContext, score_on_financial_world
from policy_runtime import CommittedPick
from replay import NON_COMMITTING_SCORE

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the resolution every sibling closeout,
# dream and incumbent suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
DREAMING_DIR = REPO_ROOT / "deploy" / "dreaming"

INCUMBENT_M3_PATH = DREAMING_DIR / "incumbent.m3.py"
INCUMBENT_M2_PATH = DREAMING_DIR / "incumbent.m2.py"
INCUMBENT_EXAMPLE_PATH = DREAMING_DIR / "incumbent.example.py"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: The three generated bootstrap domains — the domains Addendum 3's selection
#: aggregate is read over, and one world of each is what the exploration half
#: of this suite is asserted against.
BOOTSTRAP_DOMAINS = (POOL_DOMAIN, FEATSEL_DOMAIN, SYMREG_DOMAIN)

#: The pool seed :mod:`test_dream_cli` and :mod:`test_incumbent_example` both
#: draw their own pools from, reused here so this suite adds no new pool to
#: the corpus.  The hpo domain's own ``persist_worlds`` band is 40-50 worlds —
#: a store-level decision the pool refuses to round away — so the hpo draw is
#: 40 while the featsel and symreg draws seat only the single world this suite
#: reads.
POOL_SEED = 20261006
HPO_WORLD_COUNT = 40

#: The round cap the exploration half is scored at.  Addendum 3's rule needs
#: two rounds to see anything (round one reveals the root, round two the
#: root's neighbours) and five is enough for each domain's first world to
#: carry ``min_observed`` readings and clear ``commit_z`` — the same cap
#: ``test_dream_cli.py`` and ``test_incumbent_example.py`` run their own sweeps
#: at.
ROUND_CAP = 5

#: A fixture financial campaign whose top reading clears the commit — five
#: nodes with a reading, one standing far above the rest.  Mean ``0.8``,
#: population deviation ``1.1045…``, so the top node's z-score is ``1.99``,
#: above the ``1.5`` ``commit_z`` is worth at ``beta = 0.5``.
CLEARING_VALUES = (0.1, 0.2, 0.3, 0.4, 3.0)
#: A fixture campaign that does **not** clear: five readings on a shallow
#: ramp, whose top stands ``1.41`` deviations out — above zero, below the bar.
#: This is the fixture that tells ``commit_z`` from "the deviation is non-zero".
NOT_CLEARING_VALUES = (1.0, 1.05, 1.1, 1.15, 1.2)
#: A fixture campaign with too few readings for the z-score to mean anything:
#: four nodes carry a value, ``min_observed`` is five, so the policy abstains
#: whatever the spread — this fixture's top stands ``1.73`` deviations out and
#: would clear if the floor were ignored.
TOO_FEW_VALUES = (0.1, 0.2, 0.3, 3.0)


def _m3_source() -> str:
    return INCUMBENT_M3_PATH.read_text(encoding="utf-8")


# -- Fixtures: one bootstrap world per domain, one financial campaign ---------


def _persisted_world(tmp_path: Path, domain: str) -> Any:
    """One world of ``domain``, persisted into a tmp store and read back.

    A fresh database per call, so no test depends on another's draw, and the
    pool seed :mod:`test_dream_cli` already uses — the same pool, not a second
    one.  ``persist_worlds`` gates the hpo count to its own 40-50 band, so
    only the featsel and symreg draws are narrowed to the one world read; a
    domain's world is drawn from its ``(pool_seed, index)``, so narrowing the
    count changes which worlds are seated, never what they are.
    """
    database_url = f"sqlite:///{tmp_path / f'{domain}.db'}"
    pool = BootstrapPool(database_url)
    count = HPO_WORLD_COUNT if domain == POOL_DOMAIN else 1
    persisted = pool.persist_worlds(count=count, pool_seed=POOL_SEED, domain=domain)
    return pool.world(persisted.worlds[0].world_id)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_m3_incumbent_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database carrying the ``campaign``
    and ``node`` tables — the two :func:`score_on_financial_world` reads."""
    url = f"sqlite:///{tmp_path / 'm3-incumbent.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _financial_campaign(database_url: str, values: tuple[float, ...]) -> tuple[str, dict[str, float]]:
    """A fixture financial campaign: one root node per value, plus a node the
    replay reveals but cannot read.

    Every node is planted as a root (no ``parent_id``), the shape
    ``test_dream_financial_worlds.py`` and ``test_m2_incumbent_equivalence.py``
    both plant, so the campaign's tree needs no parent chain.  ``ic_mean`` and
    ``ic_tstat`` are planted equal — :func:`orchestrator._live_tree.
    live_question` folds a node's ``ir_tstat``-or-``ic_tstat`` reading into
    ``ic_insample``, and this table carries no ``ir_tstat`` — so the reading a
    policy sees is exactly the value planted here.  The last node carries
    ``ic_mean IS NULL``: a node that failed, whose payload freezes empty and
    which :func:`live_question` therefore leaves out of its own reveal, while
    :func:`replay.run_replay` still seeds the tree's roots into the question
    before the first ``select`` — the state that makes
    ``deploy/dreaming/incumbent.example.py`` raise.

    Answers ``(campaign_id, {node_id: value})``, so a test can name the node it
    expects the rule to commit and the one it expects never to see.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url
    )
    planted: dict[str, float] = {}
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        for index, value in enumerate(values):
            node_id = f"n{index}"
            connection.execute(
                "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
                "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, ?, ?)",
                (node_id, campaign_id, "macro", value, value),
            )
            planted[node_id] = value
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, NULL, NULL)",
            ("n-failed", campaign_id, "macro"),
        )
    return campaign_id, planted


def _write_code_artifact(artifact_dir: Path, campaign_id: str, node_id: str) -> None:
    store = ArtifactStore(artifact_dir)
    store.write(campaign_id, node_id, "code.py", "# a stored node's signal\n")
    store.commit(campaign_id, node_id)


def _stub_evaluate_on_dates(
    node_id: str, _code: str, *, context: Any, oracle: Any, dates: Any
) -> tuple[Any, float]:
    """A deterministic stand-in for the real, sandboxed out-of-sample read.

    A pure function of ``node_id``, so a committed pick's score is a fact
    about *which* node was committed rather than a coincidence of the fixture
    — and two different commits would (with overwhelming probability)
    disagree.  The real evaluator's own correctness is
    ``test_closeout_commit_oos.py``'s concern, not this suite's.
    """
    digest = hash(node_id) % 1000
    return SimpleNamespace(ic_tstat=2.5), digest / 1000.0


def _financial_context(database_url: str, tmp_path: Path) -> FinancialEvalContext:
    artifact_dir = tmp_path / "artifacts"
    return FinancialEvalContext(
        evaluation=SimpleNamespace(
            database_url=database_url,
            artifact_dir=artifact_dir,
            evaluation_dates=(dt.date(2026, 1, 1),),
            oos_dates=(dt.date(2026, 6, 1),),
            closes={},
            horizon=1,
        )
    )


def _score_financially(
    source: str,
    database_url: str,
    tmp_path: Path,
    values: tuple[float, ...],
    monkeypatch: pytest.MonkeyPatch,
    *,
    count_select_calls: bool = False,
) -> tuple[Any, str, dict[str, float], list[int]]:
    """Replay ``source`` over one fixture financial campaign.

    Answers ``(terminal_pick, campaign_id, planted_values, select_call_count)``.
    Every planted node's code artifact is written, because a real campaign
    evaluates and stores *every* node's code and not only the one later
    committed to — a policy that reached for a different node must be told
    apart by this suite's assertions, never by a missing artifact.  When
    ``count_select_calls`` is set, :func:`replay.run_replay` is wrapped once to
    count how many times the candidate's own ``select`` is asked, which is how
    Addendum 3's *"it decides once over the whole tree"* is asserted.
    """
    campaign_id, planted = _financial_campaign(database_url, values)
    artifact_dir = tmp_path / "artifacts"
    for node_id in (*planted, "n-failed"):
        _write_code_artifact(artifact_dir, campaign_id, node_id)
    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub_evaluate_on_dates)

    calls: list[int] = []
    if count_select_calls:
        real_run_replay = _financial_eval.run_replay

        def _counting_run_replay(select: Any, question: Any, tree: Any, *, round_cap: int) -> Any:
            def _counting_select(asked: Any) -> Any:
                calls.append(1)
                return select(asked)

            return real_run_replay(_counting_select, question, tree, round_cap=round_cap)

        monkeypatch.setattr(_financial_eval, "run_replay", _counting_run_replay)

    context = _financial_context(database_url, tmp_path)
    result = score_on_financial_world(source, campaign_id, context=context)
    return result, campaign_id, planted, calls


# -- Admission ----------------------------------------------------------------


def test_m3_incumbent_is_admitted_under_the_strict_question_contract() -> None:
    """``screen_policy`` adopts the module, and the loader reads it as a
    question-contract policy — the strict rule Addendum 3 names, which follows
    every path of ``select`` through same-module helpers and requires a
    ``commit()`` or an ``abstain()`` on each."""
    source = _m3_source()

    decision = policy_runtime.screen_policy(source)

    assert decision.adopted, decision.detail
    assert decision.reason is policy_runtime.AdmissionReason.CLEAN

    loaded = _policy.load_exploration_policy(
        {_policy.EXPLORATION_POLICY_ENV: str(INCUMBENT_M3_PATH)}
    )
    assert loaded.contract == _policy.QUESTION_CONTRACT


# -- The two defects the fix answers ------------------------------------------


@pytest.mark.parametrize("domain", BOOTSTRAP_DOMAINS)
def test_the_m2_rule_abstains_on_every_bootstrap_domain(tmp_path: Path, domain: str) -> None:
    """Addendum 3's *"The refused attempt"*, reproduced: ``m3-attempt-1``'s
    incumbent abstained on every bootstrap world of every domain, so selection
    — which runs on bootstrap worlds only — had no evidence to select on.  A
    bootstrap world reveals nothing until a policy asks, and the M2 fixed rule
    only picks among nodes that are already evaluated."""
    world = _persisted_world(tmp_path, domain)

    result = score_on_world(INCUMBENT_M2_PATH.read_text(encoding="utf-8"), world, round_cap=ROUND_CAP)

    assert result.pick is None
    assert result.score == NON_COMMITTING_SCORE


def test_the_example_incumbent_raises_on_a_financial_world(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second shipped policy's defect, reproduced through the real
    financial replay: ``incumbent.example.py`` subtracts from
    ``observation.r2_train``, which is ``None`` on the node the replay reveals
    without a reading (``ic_mean IS NULL``), so it raises where a candidate
    must survive.  :func:`_score_financially` is driven directly rather than
    through its own return value, because the call it makes is the assertion:
    the new module is scored over the identical fixture in the test below and
    does not raise."""
    campaign_id, planted = _financial_campaign(database_url, CLEARING_VALUES)
    artifact_dir = tmp_path / "artifacts"
    for node_id in (*planted, "n-failed"):
        _write_code_artifact(artifact_dir, campaign_id, node_id)
    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub_evaluate_on_dates)

    with pytest.raises(TypeError):
        score_on_financial_world(
            INCUMBENT_EXAMPLE_PATH.read_text(encoding="utf-8"),
            campaign_id,
            context=_financial_context(database_url, tmp_path),
        )


# -- The new module explores every bootstrap domain ---------------------------


@pytest.mark.parametrize("domain", BOOTSTRAP_DOMAINS)
def test_m3_incumbent_explores_past_the_root_and_commits_on_a_bootstrap_world(
    tmp_path: Path, domain: str
) -> None:
    """One world per bootstrap domain: the fixed module widens the frontier
    past the root, reads the readings it reveals through ``r2_train``, and
    commits a node that is not the root — the evidence the refused attempt
    could not produce."""
    world = _persisted_world(tmp_path, domain)

    result = score_on_world(_m3_source(), world, round_cap=ROUND_CAP)

    assert isinstance(result.pick, CommittedPick)
    assert result.score != NON_COMMITTING_SCORE
    assert math.isfinite(result.score)
    # The root alone never clears ``commit_z``: round one abstains and answers
    # the roots, and only a widened frontier can produce a commit at all.
    assert result.pick.node_id != world.canonical_node()


def test_m3_incumbent_commits_the_same_node_twice_on_one_bootstrap_world(tmp_path: Path) -> None:
    """Determinism: the same source, world and round cap answer the same pick
    and the same score twice — each call imports the candidate fresh, so no
    module state survives an episode."""
    world = _persisted_world(tmp_path, SYMREG_DOMAIN)

    first = score_on_world(_m3_source(), world, round_cap=ROUND_CAP)
    second = score_on_world(_m3_source(), world, round_cap=ROUND_CAP)

    assert first.pick is not None and second.pick is not None
    assert first.pick.node_id == second.pick.node_id
    assert first.score == second.score


# -- The new module decides a financial world ---------------------------------


def test_m3_incumbent_commits_the_z_top_node_when_it_clears(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The financial half of Addendum 3's rule, over a tree that is fully
    revealed before the first call: with five readings in hand and the top
    standing far above the rest, that node is committed — and it *is* the
    highest reading, not the highest ``r2_train`` (which is ``ic_mean ** 2``
    and would discard the sign: ``-3.0`` and ``3.0`` share it)."""
    result, _campaign_id, planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, CLEARING_VALUES, monkeypatch
    )

    top = max(sorted(planted), key=lambda node_id: (planted[node_id], node_id))
    assert result.pick is not None
    assert result.pick.node_id == top
    assert result.pick.node_id != "n-failed"
    assert math.isfinite(result.score)
    assert result.score != NON_COMMITTING_SCORE


def test_m3_incumbent_breaks_a_clearing_tie_by_node_id_ascending(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Addendum 3: *"It commits the highest-valued node (ties by node id
    ascending)"* — the order :func:`orchestrator.closeout._commit_top_node`
    breaks its own tie by.

    The tie has to *clear* to be a tie at all: two nodes sharing the top
    reading drag the mean up and the spread out, so the tied pair only reaches
    ``commit_z`` when the rest of the set sits well below them.  Here eight
    readings at ``0.0`` and two at ``5.0`` give a mean of ``1.0`` and a
    population deviation of ``2.0`` — a top z-score of exactly ``2.0`` — and
    the two tied nodes are named so that the one the policy must pick is the
    *higher* id: ``n0`` sorts after ``z9``, and the fixture's own nodes are
    planted ``n0``…``n7``, so the tie is planted on the first/last pair rather
    than on adjacent ids.
    """
    values = (5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0)
    result, _campaign_id, planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, values, monkeypatch
    )

    tied = sorted(
        (node_id for node_id, value in planted.items() if value == 5.0)
    )
    assert len(tied) == 2
    # The tie is real — both nodes would clear on their own reading — and the
    # winner is the ascending-first of the pair, not merely the lower id of
    # two commits the loop happened to try in order.
    assert result.pick is not None
    assert result.pick.node_id == tied[0] == "n0"


def test_m3_incumbent_commits_the_higher_reading_when_the_sign_is_all_that_differs(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sign-blindness Addendum 3 names as the shipped example's second
    defect: the only observation field both pools share, ``r2_train``, is
    ``ic_mean ** 2`` on a financial world, so it discards the sign — and the
    node with the largest *magnitude* is then the one a rule ranking by
    ``r2_train`` prefers, profitable or not.

    The fixture makes the two rules disagree head-on.  The four nodes with the
    largest magnitudes are all negative (readings ``-1.0`` … ``-1.15``, each
    an ``r2_train`` of about ``1.32``); the one node with a *positive* reading
    is the smallest in magnitude (``0.5``, an ``r2_train`` of ``0.25``) and so
    the highest reading of the five.  A sign-blind rule commits ``-1.15``;
    this policy commits ``0.5`` — and does so through ``commit_z`` rather than
    by accident, since the positive top stands about ``1.99`` population
    deviations above the set's mean.
    """
    values = (0.5, -1.0, -1.05, -1.1, -1.15)
    result, _campaign_id, planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, values, monkeypatch
    )

    # The negative nodes carry the largest magnitudes; the positive one is the
    # highest *reading*, which is the quantity this policy ranks by.
    assert max(planted, key=lambda node_id: abs(planted[node_id])) == "n4"
    assert result.pick is not None
    assert result.pick.node_id == "n0"
    assert planted[result.pick.node_id] == 0.5


def test_m3_incumbent_abstains_when_the_top_does_not_clear(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Five readings, none standing ``commit_z`` above the rest: the policy
    takes no position, and declares it (``abstain()`` clears the register, so
    the episode reads as the miss it decided rather than as a fall-off)."""
    result, _campaign_id, _planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, NOT_CLEARING_VALUES, monkeypatch
    )

    assert result.pick is None
    assert result.score == NON_COMMITTING_SCORE


def test_m3_incumbent_abstains_when_the_deviation_is_zero(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Five readings, all equal: there is no "above the rest" to point at, so
    a zero deviation never clears, however small ``commit_z`` becomes."""
    result, _campaign_id, _planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, (1.0, 1.0, 1.0, 1.0, 1.0), monkeypatch
    )

    assert result.pick is None
    assert result.score == NON_COMMITTING_SCORE


def test_m3_incumbent_abstains_when_too_few_nodes_carry_a_reading(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four readings against a floor of five: the z-score is not computed at
    all.  The fixture's top would clear the bar comfortably if the floor were
    ignored, so this test tells ``min_observed`` from ``commit_z``."""
    result, _campaign_id, _planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, TOO_FEW_VALUES, monkeypatch
    )

    assert result.pick is None
    assert result.score == NON_COMMITTING_SCORE


def test_m3_incumbent_decides_a_financial_world_in_one_call(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Addendum 3: *"On a financial world it then returns no batch, so it
    decides once over the whole tree, as the M2 rule does."*  The fixture
    clears, so the commit is real, and ``select`` is still asked exactly once:
    a second call could only re-decide a tree it has already seen."""
    result, _campaign_id, _planted, calls = _score_financially(
        _m3_source(), database_url, tmp_path, CLEARING_VALUES, monkeypatch,
        count_select_calls=True,
    )

    assert result.pick is not None
    assert len(calls) == 1


def test_m3_incumbent_survives_a_null_ic_mean_node(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The node that breaks ``incumbent.example.py``: the fixture plants one
    node with ``ic_mean IS NULL``, which ``live_question`` freezes an empty
    payload for and leaves out of its own reveal, while the replay still seeds
    the tree's root set into the question before the first ``select``.  The
    module must read it as "no reading" and carry on — here committing the
    clearing node — rather than raising on a ``None``."""
    result, _campaign_id, _planted, _calls = _score_financially(
        _m3_source(), database_url, tmp_path, CLEARING_VALUES, monkeypatch
    )

    assert result.pick is not None
    assert result.pick.node_id != "n-failed"


# -- The jitter reviser still produces admissible candidates ------------------


def test_jitter_revisions_of_the_m3_incumbent_are_admitted(tmp_path: Path) -> None:
    """Addendum 3's cycle revises this incumbent with the ``jitter`` reviser,
    and every candidate is swept before it is scored — so a revision of this
    module must still be admitted.  The reviser moves numeric literals only,
    and every threshold here is a literal routed through one ``_schedule``,
    so a revision moves the whole rule from one place without touching its
    shape."""
    source = _m3_source()

    candidates = dreaming.revise_policy(source, 3, seed="m3-incumbent")

    assert len(candidates) == 3
    for candidate in candidates:
        assert candidate.source != source
        decision = policy_runtime.screen_policy(candidate.source)
        assert decision.adopted, decision.detail


def test_a_jitter_revision_of_the_m3_incumbent_still_decides_both_pools(
    tmp_path: Path, database_url: str, tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admission is not enough: a revision moves ``commit_z`` (band ``±10%``,
    so between roughly ``1.35`` and ``1.65``), and a cycle's evidence comes
    from what its candidates *score*.  So a revision is driven over both
    pools — a bootstrap world, where it must still explore past the root and
    commit, and a financial world, where it must still decide once and commit
    the node the top reading points at.  This is the property that makes
    "one parameter decides the commit in both pools" hold for the candidates
    selection actually measures, not only for the incumbent itself."""
    revision = dreaming.revise_policy(_m3_source(), 1, seed="m3-incumbent")[0].source

    world = _persisted_world(tmp_path_factory.mktemp("bootstrap"), SYMREG_DOMAIN)
    bootstrap_result = score_on_world(revision, world, round_cap=ROUND_CAP)
    assert bootstrap_result.pick is not None
    assert bootstrap_result.pick.node_id != world.canonical_node()

    financial, _campaign_id, planted, _calls = _score_financially(
        revision, database_url, tmp_path, CLEARING_VALUES, monkeypatch
    )
    assert financial.pick is not None
    assert planted[financial.pick.node_id] == max(CLEARING_VALUES)
