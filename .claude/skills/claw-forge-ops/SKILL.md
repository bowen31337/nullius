---
name: claw-forge-ops
description: >-
  Inspect and control an in-flight claw-forge run. Use when asked what the
  run is doing, whether it is stuck, why a task failed, or to pause,
  resume, requeue, or stop it.
---

# Operating a claw-forge run

## Reading state

For the full procedure, read `.claude/commands/claw-forge-status.md` and
execute it — it covers `claw-forge status` and how to read its output.

**Never assume the state service is on port 8420.** When the base port is
taken — routinely another project's service on a shared box — claw-forge
falls back to `port+1 … port+4` and records the choice nowhere.
`claw-forge status` discovers the right port by matching
`/info.project_path`. Hand-writing a port reaches a stranger's run.

For the provider pool specifically, read `.claude/commands/pool-status.md`
and execute it.

Other read commands: `claw-forge worktrees list`, `claw-forge stash list`.

`claw-forge state` is **not** one of them — it *starts* a state service. Running
it against a project that already has one puts a second service on the same
`state.db`, which is the two-process failure described below.

## Recovering changes the startup sweep took

Startup cleans the checkout before any worktree exists: dirty tracked
files go to a `claw-forge-auto-<ts>` stash; untracked files are
**archived to `.claw-forge/orphans/<ts>/`, not stashed** — do not hunt
the stash stack for a file that was archived, and do not report it as
data loss. `.claw-forge/sweeps/<ts>.json` records both halves, quoting
the stash's commit SHA.

Restore with `claw-forge stash apply <sha>` — the SHA from the sweep
record or `claw-forge stash list`, never a `stash@{N}` index (the boot
baseline and every mid-run leak capture push onto the same stack, so
indices shift under you) and never `pop`. **Never restore while a run
is live**: the leak watch keeps the checkout HEAD-clean and will
re-sweep the dirt, attributing it to an innocent task.

## `DISPATCHER OFFLINE` is not proof

If `status` reports the dispatcher offline, **confirm that reading belongs
to this project's service before acting on it.**

Starting a second `claw-forge run` against live worktrees puts two
processes on the same git repository and the same file-claim table, which
assume a single-process state service. This has happened in the field: a
stale service on `:8420` answered for a session it had never heard of, and
the advice to "resume with `claw-forge run`" would have corrupted a healthy
run on `:8421`.

When in doubt, show the user what you see and ask.

## Pause is not Stop

These are different and must not be conflated:

- **`claw-forge pause`** — a *soft* drain. In-flight agents keep working and
  finish; no new tasks dispatch. Resume with `claw-forge resume`.
- **Stop All** (from the Kanban UI) — a *hard* stop. Every in-flight agent
  coroutine is cancelled, discarding whatever each had accumulated.

Say which one you are doing. Never describe a hard stop as a pause.

## Re-running failed work

```bash
claw-forge reset          # requeue tasks; clears retry counters and failure_scope
claw-forge input          # answer pending human-input questions
```

A task that went terminal keeps its dependents `pending`, not `blocked`, so
resetting the parent re-arms the whole subtree.

## Diagnosing a failure

`claw-forge status` reports a `failure_scope` per failed task:

| Scope | Meaning |
|---|---|
| `agent` | the agent's work was wrong — a real test failure |
| `infrastructure` | the box or the environment failed; the agent's budget is untouched |
| `integration` | a merge or worktree-sync conflict |
| `unknown` | classification was ambiguous; treat as agent-ish |

The classifier is a heuristic, not an oracle. If both agent and
infrastructure patterns match, it reports `unknown` deliberately.
