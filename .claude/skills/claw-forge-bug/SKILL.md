---
name: claw-forge-bug
description: >-
  Route defect work through claw-forge. Use when something is broken,
  failing, erroring, regressed, or behaving wrong — a failing test, a
  stack trace, a 500, a bug report — before starting to debug or patch.
---

# Fixing bugs through claw-forge

claw-forge treats a bug the way it treats a feature: a unit of work with a
shape, a footprint and dependency edges, so several fixes can run in
parallel without colliding.

## First: understand, then dispatch

This skill is about **dispatching** fixes. If the defect is not yet
understood — no reproduction, no root cause — debug it systematically
first. Dispatching an agent at a symptom produces a patch on a symptom.

## Step 1 — Triage on count and coupling, not severity

| Situation | Route |
|---|---|
| One isolated defect, root cause known | `claw-forge fix "<description>"` |
| Several defects | write a bug spec (Step 2) |
| One fix that must land after another | write a bug spec (Step 2) |

Severity is not the signal. A single critical bug is still one unit of
work; three trivial ones that touch the same module still need ordering.

## Step 2 — Write a bug spec

Read `.claude/commands/create-bug-spec.md` and execute it. If that file is
absent — a dev-checkout install scaffolds only a stub — say so and write the
bug spec against `bug_spec.example.xml` instead. Do not stop; a missing
command file is a scaffolding gap, not a reason to abandon the route.

For a formal
report to hand to someone else first, `.claude/commands/create-bug-report.md`
produces one.

Then gate it exactly like a feature spec:

```bash
claw-forge validate-bug-spec <bug-spec-file>
```

Fix every error and every warning before planning. INFO findings never
block.

```bash
claw-forge plan-bugs <bug-spec-file>
```

## Step 3 — Tell the truth about what is running

**`claw-forge fix` and `claw-forge plan-bugs` do not dispatch anything.**
They write rows into the project's existing session. The work runs when a
`claw-forge run` wave picks it up.

So after either command:

- If a run is already in flight, say the fix is **queued** and will be
  picked up on the next wave.
- If no dispatcher is live, say so, and **ask** before starting one.

Reporting a queued fix as a running fix is the specific failure this rule
exists to prevent.

## Step 4 — STOP before dispatching

Same rule as feature work: `claw-forge run` spawns parallel agents, writes
to git and runs for hours. Report what will be dispatched, then ask. Never
start it without an explicit yes.
