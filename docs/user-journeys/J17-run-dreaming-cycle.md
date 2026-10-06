---
id: J17-run-dreaming-cycle
title: Run one dreaming cycle and read which policy it selected (Loop 2)
persona: Operator
source: PRD §5 Loop 2, §12 M1.5 + M3 (the gate), §12.1; architecture §10.3.1, §10.6, §20; app_spec.xml key_interaction 3 "Dreaming cycle", success_criteria "a dreaming cycle completes and selects a policy revision"
status: pass
last_checked: run 9
evidence: screenshots/run-9/J17-step1-dream-help.txt, screenshots/run-9/J17-step1b-migrate.txt, screenshots/run-9/J17-step1c-migrate-rerun.txt, screenshots/run-9/J17-step3-dream-thin-pool.txt, screenshots/run-9/J17-step2a-fill.txt, screenshots/run-9/J17-step2b-fill-rerun.txt, screenshots/run-9/J17-step2c-fill-other-seed.txt, screenshots/run-9/J17-step4a-dream.txt, screenshots/run-9/J17-step4b-dream-same-seed.txt, screenshots/run-9/J17-step4c-reviser-llm.txt, screenshots/run-9/J17-step4d-write-selected-refuses.txt, screenshots/run-9/J17-step4a-selected-policy.py.txt
---

# J17 — Run one dreaming cycle

After campaigns have filled the replay pool, the operator runs the middle
loop: the pool is frozen, the policy-development agent writes `M`
revisions, each revision is replayed over every stored world without
touching the evaluator, and the argmax under the meta-selection bar becomes
`π_{t+1}`. The PRD calls this milestone **THE GATE** (M3), and the operator
must be able to run it and read its outcome. Bootstrap worlds (M1.5) make
up the pool's numbers before enough financial campaigns exist.

## Preconditions

- A research store, and a pool that is either thin (fewer than 20 worlds)
  or seeded with 20 or more bootstrap worlds.
- Policy-development agent keys for the live revision step (costs money).

## Steps

1. Look for the operator command that runs a dreaming cycle, in the
   README, CLAUDE.md, `run.sh` verbs, `python -m <member>` entry points and
   `deploy/systemd/`.
   Expect: one documented command, such as `./run.sh dream` or
   `python -m dreaming.cycle`, with `--help`.
1b. Prepare a fresh research store with `./run.sh migrate`.
   Expect: exit `0`; the store holds every table the dreaming cycle and the
   pool read (`replay_score`, `policy_revision`, `node`, …), and a rerun
   changes nothing.
2. Fill the pool with bootstrap worlds (PRD M1.5: 40–50 worlds, each
   carrying `source_commit` and `dataset_manifest_hash`).
   Expect: an operator command that fills the pool and reports `n_worlds`
   and `n_financial` separately.
3. Run the cycle against a pool of fewer than 20 worlds.
   Expect: a non-zero exit with one line saying `pool_too_thin`, and no
   model call.
4. *(live, costs money)* Run the cycle against 20 or more worlds.
   Expect: `M` capped at 10 (because the pool has fewer than 50 worlds), a
   70/30 train/holdout split, one `replay_score` row per (revision, world),
   and the selected revision named together with its train-vs-holdout gap.
   Re-running with the same pool and the same revisions selects the same
   revision.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
