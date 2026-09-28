---
name: claw-forge-verify
description: >-
  Journey-based verification of an app claw-forge built: write every user
  journey to a local folder, check each one in a real browser with
  screenshots as evidence, and turn failures into claw-forge bug specs or
  spec features until every journey passes. Use this whenever a claw-forge
  run has just completed, or when the user asks to verify the app, QA the
  build, test user journeys, check it in a browser, find gaps between spec
  and product, or asks "does it actually work?" — even if they don't name
  a tool. It drives the user's real browser and can lead to paid runs, so
  it always proposes a plan and asks before starting.
---

# Verifying a claw-forge build

claw-forge's own gates verify tests and merges; they cannot see a broken
button, a dead route, or a journey the spec never declared. This skill is
the outer check: walk the app the way a user would, keep evidence, feed
what breaks back into claw-forge.

## First: ask, then drive

Present a short plan (what URL, where evidence goes, that failures become
specs) and get a yes before touching the browser — it takes over a tab in
the user's real Chrome, and the fix loop can dispatch runs that cost real
money and hours. Ask **again** before any dispatch.

## The procedure

Read `.claude/commands/verify-journeys.md` and execute it. If that file is
absent — a dev-checkout install scaffolds only a stub — say so and proceed
from the three-phase outline below rather than abandoning the route:

1. **Journeys** — one file per user goal under `.claw-forge/journeys/`
   (that folder survives claw-forge's startup sweep; the project root does
   not), each step carrying its own expectation.
2. **Browser verification** — browser-harness, screenshot before and after
   every action, evidence saved under `.claw-forge/journeys/screenshots/`.
   Verdicts are `pass` / `fail` / `blocked` — **a journey a real user
   cannot reach is `blocked`, never `pass`**, no matter what state-seeding
   diagnostics show.
3. **Findings → claw-forge** — one bug → `bug_report.md` +
   `claw-forge fix --report`; several → a bug spec via
   `.claude/commands/create-bug-spec.md` then `claw-forge plan-bugs`;
   missing features → spec additions then `claw-forge plan`. Re-verify
   after every run; loop until every journey passes. Two identical
   failures on the same journey → stop and bring the user the evidence.

## Tell the truth about what ran

`claw-forge fix` and `plan-bugs` queue work; a `claw-forge run` executes
it. Report queued as queued, and never start a run without an explicit
yes.
