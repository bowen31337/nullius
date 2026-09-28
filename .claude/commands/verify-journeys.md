# Verify user journeys in a real browser

Close the loop between "claw-forge says the tasks are done" and "a person can
actually use the app". claw-forge's gates verify tests and merges; they cannot
see a broken button, a dead route, or a journey the spec never declared. This
command finds those by walking the app the way a user would, keeping evidence,
and feeding what it finds back into claw-forge until nothing is left.

**The contract: never assert a journey works without a screenshot that shows
it, and never file a bug without the journey + screenshot that prove it.**

## Step 0 — Ask before you drive

Do not launch into this silently: it takes over a tab in the user's real
browser, saves screenshots of whatever renders, and Phase 3 can dispatch
claw-forge runs that cost real money and hours. Present a short plan first
and get a yes:

- what app/URL will be verified and how you'll start it if it isn't running
- where journeys + screenshots will be written (below)
- that failures become specs, and that you will ask again before dispatching

## Where things live

All artifacts go under `<project>/.claw-forge/journeys/`:

```
.claw-forge/journeys/
├── 01-signup.md            one file per journey
├── 02-create-task.md
├── _run-log.md             what was verified when
└── screenshots/
    └── 01-signup/          step-numbered PNGs per journey
```

Why there and not the project root: claw-forge's startup gate archives
**untracked** root files into `.claw-forge/orphans/` before every run, so
evidence parked at the root disappears on the next `claw-forge run`.
`.claw-forge/` is exempt from that sweep and already gitignored.

## Phase 1 — Write every user journey

A journey is one user goal, end to end ("sign up and land on the dashboard"),
not one click. Enumerate them from, in order of authority:

1. The app spec — every `<feature>` implies at least one journey; a feature
   nobody can reach through the UI is itself a finding.
2. The running app — walk the navigation and note reachable flows the spec
   never mentions.
3. README / route tables — for journeys with no UI entry point.

One file per journey, numbered in rough dependency order (auth before things
behind auth). Small apps have 3–8 journeys; if you have 25, you are writing
test cases, not journeys — merge steps back into goals.

Journey file shape (front matter is machine-greppable; re-verification reads
`status` and `evidence`):

```markdown
---
id: 02-create-task
title: Create a task and see it on the board
persona: signed-in user
source: app spec feature "Task creation"   # or "discovered in UI"
status: untested          # untested | pass | fail | blocked
last_checked: —
evidence: —               # screenshots/02-create-task/ once verified
---

## Preconditions
- App running at http://localhost:3000
- Logged in as the test user (journey 01 passed)

## Steps
1. Click "New task" in the header.
   Expect: a task form opens with title and description fields.
2. Type "Buy milk" in the title, submit.
   Expect: the form closes; "Buy milk" appears in the Todo column.
3. Reload the page.
   Expect: "Buy milk" is still on the board (persisted).

## Result
- Verdict:
- Failing step (if any):
- Expected vs observed:
- Evidence:
```

Every step carries its own Expect — a step without an expectation cannot
fail, and a step that cannot fail verifies nothing. The last step should
prove durability where it applies (reload, revisit): "it appeared" and "it
saved" are different facts.

## Phase 2 — Verify each journey in a real browser

Use browser-harness if it is installed (`browser-harness -c '...'`); if it is
not on this machine, say so and agree an alternative with the user (another
browser-automation tool, or manual walkthrough with the user driving) —
do not silently downgrade to "I read the code and it looks right".

Ground rules:

- Start the app the project's own way (`npm run dev`, `uv run …`, whatever
  the README says) and record the command + URL in `_run-log.md`. If it
  cannot start, that is finding #1 — stop and report.
- First navigation is `new_tab(url)`, never `goto_url` (that clobbers the
  user's active tab).
- Screenshot-first: capture, act, capture again to verify the action took.
  Save every step's screenshot to `screenshots/<journey-id>/<NN>-<label>.png`
  — the after-shot is the evidence the journey file cites.
- Auth wall → stop and ask the user for a test account. Never type
  credentials you found in files or screenshots.
- Verdicts: `pass`, `fail` (failing step + expected vs what the screenshot
  shows), or `blocked` (couldn't attempt — say why, and name the journey it
  depends on).
- **Blocked is not pass.** Seeding state directly (localStorage, DB inserts)
  to reach a screen is a diagnostic, never a verdict — a journey passes only
  when a real user's path reaches the expectation. Label diagnostics as
  diagnostics.

Do not stop at the first failure: finish the sweep so Phase 3 sees the whole
picture (journeys behind a failure are `blocked`, not skipped silently).

## Phase 3 — Turn findings into specs and run claw-forge until clean

Classify every `fail`/`blocked`/gap, then **show the user the findings table
and the specs you propose, and get a yes before dispatching anything**.

| Finding | Route |
|---|---|
| One bug in an existing feature | `bug_report.md` → `claw-forge fix --report bug_report.md` |
| Several bugs | bug spec (see `.claude/commands/create-bug-spec.md`) → `claw-forge plan-bugs` → `claw-forge run` |
| Missing feature (journey has no code behind it) | add features to the app spec → `claw-forge validate-spec` → `claw-forge plan` → `claw-forge run` |
| Spec ambiguity (app does something defensible the journey didn't expect) | ask the user which is intended before filing |

Every bug's evidence section quotes the journey id, the failing step, and the
screenshot path — the fix agent receives your words verbatim and cannot see
your browser session. Write reports from symptom and evidence, not your guess
at the fix; if you saw a console error or a 404, put it in Evidence as an
observation. Check the spec's `<out_of_scope>` before proposing a "missing"
feature — it may be deliberately out.

**The loop:** after each run completes, re-verify the journeys the run's
tasks touched; when they pass, re-run the full sweep (fixes regress
neighbours). Every re-verification updates the journey files in place and
appends to `_run-log.md`. Done means: every journey `pass` on the latest full
sweep, no `blocked`, no unfiled finding. Report the final table (journey →
status → evidence path). If the same journey fails the same way after two fix
rounds, stop looping and bring both rounds' evidence to the user — a third
identical run is not the answer.
