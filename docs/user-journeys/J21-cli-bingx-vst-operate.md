---
id: J21-cli-bingx-vst-operate
title: Operate the BingX VST paper bot (mirror, rebalance, flatten, heartbeat, alert)
persona: Operator
source: additions_spec_bingx_vst_mirror.xml, additions_spec_bingx_vst_stage2.xml, additions_spec_bingx_vst_alerts.xml; PRD §8 C9–C10; architecture §13.2–13.3, §17; CLAUDE.md "BingX VST bot"
status: blocked
last_checked: run 9
evidence: screenshots/run-7/J21-step1-mirror-help.txt, screenshots/run-7/J21-step1-rebalance-help.txt, screenshots/run-7/J21-step1-flatten-help.txt, screenshots/run-7/J21-step1-heartbeat-help.txt, screenshots/run-7/J21-step1-alert-help.txt, screenshots/run-7/J21-step2a-mirror-no-keys.txt, screenshots/run-7/J21-step2b-rebalance-no-keys.txt, screenshots/run-7/J21-step3-flatten-no-keys.txt, screenshots/run-7/J21-step4a-heartbeat-empty-store.txt, screenshots/run-7/J21-step4b-alert-test-no-token.txt, screenshots/run-9/J21-step4a-heartbeat-empty-store.txt
---

# J21 — Operate the BingX VST paper bot

The Stage 1–2 operator commands that J15's dry run does not cover. Live steps
place orders on VST (simulated funds) using real keys from 1Password. When
the owner has not authorised them for a run, they are recorded as
**blocked (by choice)**.

## Preconditions

- Workspace synced. For the no-cost steps: no `BINGX_VST_*` or `TELEGRAM_*`
  values in the environment, sockets patched to raise, and a scratch
  `DATABASE_URL` (never `~/.local/share/nullius/vst.db`).
- The synthetic book: `packages/router/tests/fixtures/bingx_vst/synthetic_book.json`.

## Steps

1. Run `--help` on `router.bingx_mirror`, `bingx_rebalance`,
   `bingx_flatten`, `bingx_heartbeat` and `bingx_alert`.
   Expect: each exits `0`. The help states that `--place` or `--confirm` is
   needed before anything changes, and states the exit-code meanings.
2. Run `bingx_mirror --book <synthetic>` and `bingx_rebalance --book
   <synthetic>` with no keys.
   Expect: a non-zero exit and one line saying `vst_credentials_missing` that
   names both variables (never their values). No traceback and no connection.
3. Run `bingx_flatten` (no `--confirm`) with no keys.
   Expect: the same one-line credentials refusal. Nothing is cancelled or
   closed.
4. Run `bingx_heartbeat --max-age-hours 5` against an empty scratch store,
   and `bingx_alert --test`, with no Telegram token.
   Expect: exit `1` (the bot is stale or absent; the test was not delivered),
   no traceback. The heartbeat also prints its verdict as one JSON line
   (`"verdict": "absent"`).
5. *(live, VST)* Run `./run.sh vst --book <book> --status`, then
   `./run.sh vst-rebalance --book <book>` twice in the same slot.
   Expect: the first rebalance exits `0`, `1` or `3` as documented. The
   second changes nothing.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
