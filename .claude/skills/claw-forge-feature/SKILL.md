---
name: claw-forge-feature
description: >-
  Plan and dispatch new feature work through claw-forge rather than editing
  code directly. Use when asked to build, add, implement, or extend any
  feature, capability, page, endpoint, or module in this project — and
  before writing implementation code for one.
---

# Shipping a feature through claw-forge

This project is driven by claw-forge: features are specified, validated,
planned into a task DAG, and implemented by parallel agents in isolated
worktrees. Writing the code by hand bypasses the file-claim locks, the
acceptance gate and the merge-gating that make that parallelism safe.

## Step 1 — Triage. Not everything belongs here.

**Route into claw-forge** when the work spans more than one file, or the
user described an *outcome* ("users should be able to log in with Google")
rather than an edit.

**Just do it directly** for a typo, a rename, a config value, a
single-function change, or a question about the code.

If it is genuinely ambiguous, ask one question. Do not guess: routing a
one-line fix into a spec interview is worse than the reverse.

## Step 2 — Say which route you took

Before starting the interview, tell the user you are routing this through
claw-forge and roughly what that involves. A wrong triage should cost one
sentence to veto, not a completed interview.

## Step 3 — Write the spec

Read `.claude/commands/create-spec.md` and execute it. If that file is
absent — a dev-checkout install scaffolds only a stub — say so and write the
spec against `app_spec.example.xml` instead. Do not stop; a missing command
file is a scaffolding gap, not a reason to abandon the route.

It already detects
greenfield versus brownfield and handles both; do not re-derive that here.

If the user would rather explore the idea before committing to a shape,
brainstorm first — the spec is the design artifact, so it should be written
against a shape you both agree on.

## Step 4 — Gate the spec: zero errors AND zero warnings

```bash
claw-forge validate-spec --json <spec-file>
```

Read the JSON. The spec is ready when:

```
clean_deterministic == true
```

- `clean_deterministic` is the gate. It is `clean` computed over the layers
  that answer the same way twice — everything outside `nondeterministic_layers`
  (2 and 5, which call a model). Two runs over a byte-identical spec have been
  measured at 31 warnings and then 5, so gating on `clean` could withhold
  `plan` from a spec no edit would improve.
- `clean` (`error_count == 0 AND warning_count == 0 AND
  skipped_layers == []`) is still the honest whole-spec verdict and is
  still worth **reporting**. A Layer 5 finding is often real. Report those
  warnings to the user; do not loop on them. A skipped layer holds `clean`
  false — that reads "not fully measured", never "broken", and no spec
  edit clears it.
- `passed` is **not** the gate — it counts errors only.
- `info_count` is **never** a blocker. Gap 13 and Gap 17 are INFO-only
  advisories that fire on claw-forge's own reference specs; waiting for
  them to clear means waiting forever.
- Check `skipped_checks` too. `layer4_filesystem` means no project root was
  found, so Gaps 5/10/15 never resolved `touches_files` against a real tree —
  and Gap 10 is what decides whether file-claim locking is armed at all. Pass
  `--project <dir>` and re-run; a clean Layer 4 without it is not the same
  bill of health. `project_root` reports which tree the answer was measured
  against.
- Check `skipped_layers`. A skipped layer is not a clean layer (and it
  holds `clean` false). Layers 2 and 5 need a model; Layer 6 needs a
  `spec_brief.yaml`. **You are usually the model** — Claude Code does not
  pass its own credential to tool subprocesses, so unless the shell
  exports one, claw-forge cannot make the call itself from here; Layer 5
  can be answered by you (`validate-spec --emit-completeness-prompt` →
  `--completeness-response`; see `.claude/commands/fix-spec.md`). Layer 2
  is one call per category and stays skipped. Say
  which ones did not run rather than reporting a clean bill of health.

## Step 5 — Repair loop, bounded

Not clean? Read `.claude/commands/fix-spec.md` and execute it, then
re-validate.

**Exception — a missing input is not a spec defect.** If a finding's layer
also appears in `skipped_layers`, no spec edit can clear it: the layer never
ran. A spec with no Anthropic credential is the common case — the skip
notice is a WARNING on brownfield (INFO on greenfield), and either way the
layer lands in `skipped_layers`, which alone keeps `clean` false for as
long as the input is missing. Say which input is missing (e.g. no Anthropic
credential is set, so Layer 2 could not run) and move on to Step 6 instead
of repairing. Layer 5 is the exception:
you can answer it yourself, so a Layer 5 skip is worth one round-trip
before you accept it.

**Stop after 5 iterations.** Show the user the remaining issues and ask
how to proceed. An unbounded repair loop is a run that never starts.

## Step 6 — Plan

```bash
claw-forge plan <spec-file>
```

## Step 7 — STOP. Ask before dispatching.

`claw-forge run` spawns parallel agents, writes to git, consumes provider
tokens and runs unattended for hours. **Never start it without an explicit
yes.**

Report first: how many tasks, how many waves, the configured concurrency,
and anything that looks wrong. Then ask.

## Step 8 — Check the tree, then run

Check `git status` before dispatching. Commit anything the run should
build on — worktrees branch from HEAD, so uncommitted work is invisible
to every agent, and restoring it after the run conflicts with the code
the agents just wrote in those files. Everything else must **not** be
committed to the target branch just to get clean: a broken commit turns
the acceptance-gate baseline red, which (by default) silently disarms
verification for the whole run. Park unrelated WIP on a branch of its
own, or let startup's smart sweep handle it — dirty tracked files go to
a `claw-forge-auto-<ts>` stash, untracked files are **archived to
`.claw-forge/orphans/<ts>/`, not stashed**, and both are recorded in
`.claw-forge/sweeps/<ts>.json` quoting the stash's commit SHA. The
`claw-forge-ops` skill covers recovering them afterwards.

```bash
claw-forge run
```

Then use the `claw-forge-ops` skill to monitor it.
