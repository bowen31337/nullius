---
id: J16-cli-run-campaign
title: Run one discovery campaign (Loop 1, the inner loop)
persona: Operator
source: PRD §5 Loop 1, §12 M2; architecture §14.1 (agent pinning), §17; app_spec.xml key_interaction 1 "Campaign run"
status: blocked
last_checked: run 9
evidence: screenshots/run-9/J16-step1-campaign-help.txt, screenshots/run-9/J16-step3-campaign-unconfigured.txt, screenshots/run-8/J16-step6a-closeout-help.txt, screenshots/run-9/J16-step6b-closeout-no-sidecar.txt, screenshots/run-8/J16-step6c-closeout-demo-campaign.txt
---

# J16 — Run one discovery campaign

The operator runs the inner exploration loop once: the orchestrator plants
theme roots, assigns planted nulls, lets the fixed policy expand the tree,
evaluates every child inside the OS sandbox, and stops on budget or
saturation. Before spending money, the operator confirms that each pinned
model is the one actually being served (architecture §14.1: a silently
re-routed alias confounds M3). The surface is the shell: `./run.sh campaign`
under `op run --env-file=.env.campaign.tpl`, which runs
`python -m orchestrator.campaign`, plus `python -m providers.live_check`.

Live steps cost real LLM money. In a run where the owner has not authorised
spend, they are recorded as **blocked (by choice)**, never as pass.

## Preconditions

- Workspace synced. For the no-cost steps: no `NULLIUS_*` keys in the
  environment, sockets patched to raise (so a faulty refusal cannot reach a
  provider), and a scratch `DATABASE_URL`.
- For the live steps: `.env.campaign.tpl` with the research keys, the
  authoring and evaluation configs from `deploy/campaign/*-config.example.json`,
  and an OS sandbox (`runsc` or acknowledged `bwrap`).

## Steps

1. Run `python -m orchestrator.campaign --help`.
   Expect: exit `0`; usage names `--type`, `--workspaces`, `--rounds`,
   `--width`, `--allowance`, and says it prints one JSON line per event
   followed by a summary line.
2. Run `python -m providers.live_check --help`, then
   `python -m providers.live_check --pin anthropic/claude-opus-5/x` with no key.
   Expect: help exits `0`. The keyless call exits non-zero with one line
   naming `NULLIUS_ANTHROPIC_API_KEY` (never its value) and no traceback. No
   connection is attempted.
3. Run `python -m orchestrator.campaign --type discovery --workspaces 4
   --rounds 1` with nothing configured.
   Expect: a non-zero exit and one line naming the missing component and the
   repair. No traceback and no model call.
4. *(live, costs money)* Run `python -m providers.live_check --pin <each
   authoring pin>` under `op run`.
   Expect: one JSON line per pin, confirming the served model matches the pin.
5. *(live, costs money)* Run `./run.sh campaign --type discovery
   --workspaces 16 --rounds 2 --allowance <small>`.
   Expect: JSON event lines, then a summary line naming a stop condition. The
   research store holds node rows carrying `agent_model_id` and the provenance
   triple. Running `orchestrator.resume_campaign` on the same id adds no
   second set of roots.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
