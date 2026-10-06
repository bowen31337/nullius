"""``deploy/dreaming/incumbent.example.py`` is a working ``dream`` incumbent.

``bug_spec_run8_operator_findings.xml``: ``dream --incumbent PATH`` requires a
screened policy file, but the repository shipped none an operator could
start from — the only admissible incumbent lived inside
``test_dream_cli.INCUMBENT_SOURCE``, a test fixture rather than a committed
file. This suite is the regression test for the fix: it proves the shipped
example file itself, read off disk, satisfies the same contract that
fixture does.

One test per claim the fix's own acceptance criteria make:

* **admitted** — :func:`policy_runtime.screen_policy` adopts the file's
  source unchanged.
* **scores** — :func:`orchestrator._bootstrap_eval.score_on_world` drives it
  over one persisted bootstrap world and returns a committed pick with a
  finite score.
* **one cycle exits 0** — a full ``orchestrator.dream.main`` run over a
  40-world tmp pool, with this file as ``--incumbent``, commits and prints
  its one summary line.

The third test reuses :mod:`test_dream_cli`'s own migrated-pool and fake-app
fixtures (``_migrated_pool``, ``_APP``) rather than re-deriving them, the
same "reuse a sibling suite's doubles" precedent
``test_bingx_rebalance.py`` sets for ``test_bingx_mirror.py``'s. The
iteration id is pinned to one this module's own probing confirmed is
tie-free for this exact incumbent, pool seed and round cap: ``dream``'s
selection is refused (``selection_malformed``) when two revised candidates
land on the identical aggregated score, which a distance-minimising policy
like this one hits for *some* iteration ids (the jitter reviser's seed) and
not others — the same reason ``test_dream_cli.py`` itself pins "cycle-5" and
"cycle-8" rather than a fresh id per run. No test opens a network connection
or reads a real credential, and no state is kept at module scope across
tests, so the suite passes under pytest-xdist.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from bootstrap import BootstrapPool
from orchestrator._bootstrap_eval import score_on_world
from orchestrator.dream import EXIT_OK, main
from policy_runtime import CommittedPick, screen_policy

from test_dream_cli import _APP, _migrated_pool  # isort: skip

#: Three parents up from this file is the repository root, the same
#: resolution test_dream_cli.py and test_closeout_cli.py use.
REPO_ROOT = Path(__file__).resolve().parents[3]
INCUMBENT_PATH = REPO_ROOT / "deploy" / "dreaming" / "incumbent.example.py"
INCUMBENT_SOURCE = INCUMBENT_PATH.read_text(encoding="utf-8")

#: Enough worlds to clear the ladder floor (20) but stay on the capped rung
#: (below 50) — test_dream_cli.py's own POOL_WORLD_COUNT, so a world pool
#: built here needs no --round-cap tuning beyond that suite's own.
POOL_WORLD_COUNT = 40
POOL_SEED = 20261006
ROUND_CAP = 5

#: Confirmed by direct probing (not a guess): at this pool seed and round
#: cap, "dream-b" is one of several iteration ids that commits this exact
#: incumbent's widened candidate set to a clean argmax, and it is
#: deterministic — rerunning this exact (incumbent, pool, iteration id, seed)
#: reproduces the identical winner every time, because dreaming.revise_policy
#: and dreaming.commit_selection are both pure functions of their inputs.
ITERATION_ID = "dream-b"


def test_incumbent_example_is_admitted_by_screen_policy() -> None:
    decision = screen_policy(INCUMBENT_SOURCE)

    assert decision.adopted, decision.detail


def test_incumbent_example_scores_a_finite_committed_pick_on_one_world(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'incumbent-world.db'}"
    pool = BootstrapPool(database_url)
    persisted = pool.persist_worlds(count=POOL_WORLD_COUNT, pool_seed=POOL_SEED)
    world = pool.world(persisted.worlds[0].world_id)

    result = score_on_world(INCUMBENT_SOURCE, world, round_cap=ROUND_CAP)

    assert isinstance(result.pick, CommittedPick)
    assert math.isfinite(result.score)


def test_one_dream_cycle_over_a_tmp_pool_exits_0_with_the_incumbent_example(
    tmp_path: Path,
) -> None:
    database_url = _migrated_pool(tmp_path, world_count=POOL_WORLD_COUNT)
    env = {"DATABASE_URL": database_url}
    lines: list[str] = []

    exit_code = main(
        [
            "--incumbent", str(INCUMBENT_PATH),
            "--iteration-id", ITERATION_ID,
            "--round-cap", str(ROUND_CAP),
        ],
        env=env,
        emit=lines.append,
        app=_APP,
    )

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["n_bootstrap"] == POOL_WORLD_COUNT
    assert math.isfinite(payload["train_mean"])
    assert math.isfinite(payload["holdout_mean"])
