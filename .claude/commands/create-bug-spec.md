---
description: Interview for one or more bugs and write a bug_spec.xml for claw-forge plan-bugs
argument-hint: [bug description, or path(s) to bug_report.md]
allowed-tools: [Read, Write, Glob, Grep, Bash]
model: claude-opus-5
---

# /create-bug-spec

Turn a set of reported bugs into a `bug_spec.xml` that `claw-forge plan-bugs`
can dispatch in parallel.

A bug spec is to bugs what `app_spec.xml` is to features: N units of work, each
with an architectural **shape**, a **footprint**, and **dependency edges**. Those
three attributes are what let the dispatcher run several fixes concurrently
without them colliding — and they are exactly what a human gets wrong by hand, so
deriving them from the repo is the main value of this command.

For a single trivial bug, `claw-forge fix "<description>"` is faster and needs no
spec. Use this when there are several bugs, or when a fix must be ordered
relative to another.

## Flow

### Phase 0 — Ingest existing bug reports (check this first)

A `bug_report.md` — from `/create-bug-report`, or written from
`templates/bug_report.template.md` — already contains the answers Phase 1 asks
for. When one exists, read it instead of re-interviewing the user.

**Find the reports, in this order:**

1. **`$ARGUMENTS` names a file or glob** → those are the reports. Accept several:
   `/create-bug-spec bugs/*.md`, or a directory, or a list of paths.
2. **Otherwise, probe the project** — and *only* offer what you find:

   ```bash
   ls bug_report*.md bugs/*.md .claw-forge/bug-reports/*.md 2>/dev/null
   ```

   If any turn up, **ask before using them**: show each file's title line and
   its modification date, then "Ingest these, or start a fresh interview?"
   Never ingest silently. A stale `bug_report.md` left over from an earlier
   `claw-forge fix` would otherwise become a queued task nobody asked for.
3. **Nothing found, or `$ARGUMENTS` is prose** → skip to Phase 1 and run the
   interview exactly as written below. This is the back-compat floor: with no
   report on disk, this command behaves as it always has.

**Map each report onto one bug.** These headings are all recognised, including
the aliases in parentheses — match them case-insensitively:

| Report section | Bug spec |
|---|---|
| `# Bug: <title>` (first H1) | `<title>` |
| Symptoms (*problem*, *issue*) | `<symptoms>` |
| Reproduction steps (*steps to reproduce*, *repro*) | `<reproduction_steps>` |
| Expected behaviour (*expected*) | `<expected>` |
| Actual behaviour (*actual*, *current behavior*) | `<actual>` |
| Constraints (*requirements*, *must not change*) | `<constraints>` |
| Affected scope (*affected files*, *suspected files*) | **a lead for Phase 2 — never written as `touches_files`** |
| Regression test required | dropped — every bug agent is held to it by the dispatch prompt |
| Environment | dropped — a bug spec has no field for it |

**Affected scope is a hypothesis, not a footprint.** It is what a human
suspected when filing ("probably the auth module"), so treat it as the first
place to *look* in Phase 2 and confirm it against the repo. Never copy it into
`touches_files` unedited: the file-claim layer enforces whatever lands there, so
a half-right footprint fences the fix to the half that was right — worse than
declaring nothing.

**Then ask only for what a report cannot carry:**

- **Severity** — reports have no severity section. Ask once, for all the bugs
  together: "Any of these critical or high? Everything else I'll file as
  medium." Default `medium`.
- Shape, footprint, `caused_by` and ordering come from Phases 2–4 as usual.

Report what you took: "Read 3 reports → 3 bugs. Severity and footprints still
to settle." Then continue at Phase 2.

### Phase 1 — Collect the bugs

**Skip this phase for any bug Phase 0 already read from a report.** Run it only
for bugs with no report — including the case where the user wants to add one
more alongside the ingested ones.

For each bug, ask (one at a time, and stop asking once the user says that's all):

1. "What's broken? One sentence." → `<title>`
2. "Any other observable symptoms — error text, who's affected, how often?" → `<symptoms>`
3. "Exact steps to reproduce?" → `<reproduction_steps>`
4. "What should happen instead?" → `<expected>`
5. "What happens now?" → `<actual>`
6. "Anything that must NOT change while fixing this?" → `<constraints>`
7. "How bad is it — critical, high, medium, low?" → `severity`

**At least one of symptoms or reproduction steps is required.** The agent must
write a failing test before fixing anything, and it cannot do that from a title
alone. This binds ingested reports exactly as it binds interviewed bugs: if a
report parses to a title and nothing else, ask the user for symptoms or repro
steps rather than writing an untestable bug into the spec. `validate-bug-spec`
only *warns* about this, so it will not stop you — catching it here is the
enforcement.

### Phase 2 — Derive shape and footprint (do not ask; propose)

For a bug that came from a report, its **Affected scope** is the first place to
look — confirm or correct it against the repo, then derive the footprint below.
Do not treat it as the answer.

Inspect the repo, then propose each bug's shape and show your reasoning:

```bash
ls -d src/plugins/*/ src/features/*/ apps/*/ packages/*/ 2>/dev/null
```

- The fix lives inside one vertical directory → `shape="plugin" plugin="<name>"`.
  The footprint is derived from the layout profile; do not write
  `touches_files` too.
- The fix touches cross-cutting files several verticals share → `shape="core"`
  plus an explicit `touches_files`. **Required** — a core bug with no footprint
  is a parse error, because the dispatcher fences a task by its declared
  footprint.
- The fix must edit files other features own — a registry, router, entry-points
  table, composition root → `shape="integration"`. It runs alone, and its
  footprint is advisory.
- Anything involving a database migration is `shape="core"`. Parallel revisions
  off one parent merge cleanly and still leave the chain multi-headed.

Then locate the real files, so the footprint is not aspirational:

```bash
grep -rl "<a symbol from the bug report>" src/ 2>/dev/null | head
```

A file the fix must **create** (a missing `conftest.py`, a new config module)
goes in `creates=`, never in `touches_files=` — the validator rejects a
`touches_files` entry that matches nothing on disk, and dropping the entry
under-declares the footprint and gets the agent flagged by the post-merge
audit. `creates=` entries are unioned into the footprint (file claims lock
them), exempt from the existence check, and warned about if they already
exist.

**Two bugs with overlapping footprints can never run in parallel.** If you can
give them disjoint footprints, do; if not, say so, because the user is trading
throughput for it.

### Phase 3 — Propose `caused_by` (optional)

If the project has been run by claw-forge, offer to link each bug to the feature
that introduced it:

```bash
claw-forge status
```

`caused_by` takes the feature's **name as displayed**, never a UUID. It records
provenance and, when the parent feature has not merged yet, orders the fix after
it. An unresolvable reference is only a warning — the bug still plans.

### Phase 4 — Order the bugs

Ask only where it is genuinely ambiguous: "does any of these have to be fixed
before another?" → `depends_on="<index>"`, using 1-based indices of bugs in this
file. Bug-to-bug only.

### Phase 5 — Write the file

Write `bug_spec.xml` to the project root, following `bug_spec.example.xml`. Then
validate, and do not stop until it is clean:

```bash
claw-forge validate-bug-spec bug_spec.xml
```

Fix every ERROR. Report WARNINGs to the user with what each one costs — they do
not block planning, but a footprint that overlaps pending feature work is worth
knowing about before you queue the fix.

### Phase 6 — Offer to plan

Show the user the bug count, each bug's shape, and which bugs can run in
parallel. Then ask: "Plan these now?"

If yes:

```bash
claw-forge plan-bugs bug_spec.xml
```

Tell them the tasks are queued and that `claw-forge run` dispatches them — or
that they join a live run on its next wave, if one is already going.

## Notes

- Each bug agent follows a reproduce-first protocol: a failing regression test
  comes before the fix, and the suite must be green after. That is enforced in
  the dispatch prompt, so you do not need to restate it in the spec.
- A bug fix is **not** forgiven a test failure that already exists on the target
  branch, unlike a feature task. Fixing that failure is the assignment.
- Severity maps to scheduler priority above the whole feature range, so a
  critical bug outranks every queued feature.
