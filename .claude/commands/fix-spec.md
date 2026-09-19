---
description: Fix Spec Issues
model: claude-opus-5
---

# Fix Spec Issues

Run `claw-forge validate-spec` on the project spec, then iteratively fix all reported issues
— errors **and** warnings — until the spec is fully clean. Rewrites only the offending bullets;
never restructures the spec.

## Modes

```
/fix-spec               # interactive — Manual Review stops and asks (today's behavior)
/fix-spec --autonomous  # unattended — Manual Review is recorded, the command continues
```

`--autonomous` exists because Manual Review (Step 7) is the last place spec repair still
halts an unattended run, which violates the house rule the rest of the harness follows:
*a judgment call must never halt an unattended run — default conservatively and record it.*

**Two policies drive it**, read from `spec_brief.yaml` at the repo root when one exists:

| Policy | Values | Effect on repair |
|---|---|---|
| `policies.manual_review` | `default-and-record` (default) · `halt` | `default-and-record` → Step 7's items are written to `deferred_decisions.yaml` and repair continues. `halt` → the interactive block still applies, **even with `--autonomous`**: a recorded intent to be asked outranks a flag. |
| `policies.gap13_repair` | `widen` (default) · `complete-partition` | Selects the *direction* of the Gap 13 (mix) repair — see the Gap 13 row in Step 4. |

Reading the policies — the brief is plain YAML at the repo root, so read it directly:

```bash
ls spec_brief.yaml 2>/dev/null            # brief present?
sed -n '/^policies:/,/^[a-z_]*:/p' spec_brief.yaml
```

An absent file is not an error — it means the defaults below apply.

**Back-compat floor — no brief present:**

- **without `--autonomous`** → nothing changes. The interactive Manual Review block applies,
  exactly as it does today. A human who typed the command without the flag is present.
- **with `--autonomous`** → the conservative `Policies()` defaults apply
  (`manual_review: default-and-record`, `gap13_repair: widen`), because the flag *is* the
  explicit request to run unattended. `gap13_repair: widen` is today's behavior, so the
  repair itself is unchanged; only Step 7 stops blocking.

## Step 0: Handle parse-blocking errors

Run `claw-forge validate-spec <spec-file>` (after Step 1 finds the file). If
output starts with `Failed to parse spec:`, the spec has a parser-level
violation that must be fixed before any layer-based fixes can run.

**For unrecognized shape values** (e.g. `shape='ploogin'`):
1. Read the spec file. Find the `<feature shape='ploogin' ...>` element.
2. Compute Levenshtein distance from `'ploogin'` to `'plugin'` and `'core'`.
   - If best match is `'plugin'` with distance ≤ 2 → replace with `shape="plugin"`.
   - If best match is `'core'` with distance ≤ 2 → replace with `shape="core"`.
   - Otherwise → list under Manual Review (see Step 7).
3. Re-run validate-spec.

**For `<feature shape='core'>` missing `touches_files=`:**
This cannot be auto-fixed — `touches_files` requires domain knowledge of
which files the feature touches. List under Manual Review (see Step 7).

**For `<layout>` parse errors:**
- *Unknown layout profile* → the error lists the known names
  (`single-package`, `pnpm-monorepo`, `pnpm-single-app`, `uv-workspace`,
  `go-service`, `maven-single-module`); Levenshtein-match the typo
  (distance ≤ 2 → replace),
  else Manual Review.
- *`profile=` combined with `<zone>` children* → keep the `<zone>`
  children, drop the `profile=` attribute (the zones are the more
  specific declaration).
- *Nested/duplicate zone roots* → Manual Review (which subtree owns the
  zone is a design decision).
- *Inline `<root>` missing `{plugin}` or `/**` suffix* → append `/**`
  when only the suffix is missing; a template with no `{plugin}`
  placeholder goes to Manual Review.
- *`<seam>` unknown tier* → default to `tier="ordered"` (the
  conservative choice — serializes instead of parallelizing).
- *`<contract>` missing `path=`/`regen=`* → Manual Review (the regen
  command is stack knowledge).

If parse-blocked after fixes, report the remaining error and stop.

## Step 1: Find the spec file

Look for the spec in the current directory:

```bash
ls app_spec.txt app_spec.xml additions_spec.xml 2>/dev/null | head -1
```

If multiple exist, prefer `app_spec.txt`, then `app_spec.xml`, then `additions_spec.xml`.
If none found, ask the user: "Which spec file should I fix?"

## Step 2: Run validate-spec

```bash
claw-forge validate-spec <spec-file> 2>&1
```

Strict shape validation is **on by default** (since v0.8.46), so Layer 4
shape gaps (3, 5, 9) and the migration-shape gap (8) surface as ERRORs and
get fixed in this same iteration — no flag needed. Add `--soft-shape` only
if the project hasn't yet shape-annotated its spec and you're knowingly
tolerating mixed-form output.

Capture the full output. **Do not use the exit code to decide whether to stop** — exit 0
only means no errors, but warnings are still present and worth fixing.

Instead, read the summary line at the bottom of the output:
- `✅ Spec passed validation — no issues` → fully clean, nothing to fix. Report and stop.
- `⚠ Spec passed validation with N warning(s)` → warnings present. Continue to Step 3.
- `✗ Spec has N error(s)` → errors present. Continue to Step 3.

## Step 3: Parse the issues

From the validator output, extract every reported issue. For each one note:
- **Severity** (ERROR `✗` or WARNING `⚠`)
- **Layer** (1 = structural, 2 = LLM eval, 3 = coverage gap)
- **Category** (e.g. `task-management`, `auth`)
- **Message** (what's wrong)
- **Suggestion** (the → line, if present)
- **Bullet** (the exact quoted bullet text, if present)

Fix errors first (they block planning), then warnings.

## Step 4: Fix the issues

Read the spec file. For each issue, rewrite only the affected bullet(s) using the rules below.
Do not reorder bullets, add new categories, or remove bullets that weren't flagged.

### Layer 1 fixes

| Issue type | Severity | Rule |
|---|---|---|
| Compound bullet (`contains "and"`) | ERROR | Split into two separate bullets on consecutive lines |
| Vague / no measurable outcome | WARNING | Add a concrete, testable outcome (status code, field name, count) |
| Not starting with action verb | WARNING | Rewrite to start with: User can / System / API / Admin |
| Too long (> ~25 words) | WARNING | Trim to the essential behaviour; move detail to a parenthetical |

**Examples:**

```
# BEFORE (compound — ERROR):
- User can create and edit a task

# AFTER (split):
- User can create a task with title, description, due_date, and priority (returns 201 with task_id)
- User can edit a task's title, description, due_date, or priority (returns 200 with updated fields)
```

```
# BEFORE (vague — WARNING):
- Handle errors appropriately

# AFTER:
- API returns 422 with a field-level errors array when request validation fails
```

```
# BEFORE (no verb — WARNING):
- Password reset link in email

# AFTER:
- System sends a password reset link to the user's email (link expires after 1 hour)
```

### Layer 2 fixes (LLM eval — low score on a dimension)

The LLM scored a category below the threshold. The message names the dimension and category.
Read all bullets in that category and apply targeted rewrites:

| Dimension | What to improve |
|---|---|
| Testability | Add observable outcomes: HTTP status, response fields, DB state, UI element |
| Atomicity | Each bullet = one action; split any that describe more than one |
| Specificity | Replace vague words (appropriate, correct, valid) with exact values |
| Error coverage | Add bullets for the main failure cases (invalid input, not found, unauthorized) |

Re-read the full category after rewrites to confirm it now clearly covers all four dimensions.

### Layer 4 fixes (architectural shape)

| Issue | Severity | Rule |
|---|---|---|
| Gap 1: `shape="plugin"` missing `plugin=` and `touches_files=` | ERROR | Add `plugin="<category-slug>"` to the `<feature>` element. Slug: lowercase, replace non-alphanumerics with dashes, collapse repeats, strip leading/trailing dashes. |
| Gap 6: vertical category, no shape declared | WARNING / ERROR strict | Convert each unannotated bullet in the flagged category to `<feature shape="plugin" plugin="<category-slug>">…<description>{bullet text}</description></feature>`. Preserve the original bullet text verbatim inside `<description>`. |
| Gap 8: feature description suggests migration / DB-schema work, not declared `shape="core"` | WARNING / ERROR strict | Replace the existing `shape=`/`plugin=`/`touches_files=` attributes with `shape="core" touches_files="migrations/versions/**"`. Migration-touching features mutate alembic's revision tree (a global shared resource) — `shape="core"` makes the dispatcher single-flight them, preventing parallel agents from writing duplicate `revision="N"` migrations. |
| Gap 9: feature has no explicit `depends_on=` and category doesn't match any phase title | WARNING / ERROR strict | If the feature is **not** first in its category: add `depends_on="<index-of-prev-feature-in-same-category>"` to the `<feature>` element. If the feature **is** first in its category (no predecessor in same category): route to the Manual Review block — the user must confirm it's a foundation feature with no predecessors. |
| Gap 4 (typo): handled in Step 0 | (parse-time) | See Step 0. |
| Gap 13 (mix): plugin mixes footprint granularity — one feature's `dir/**` glob contains a sibling's footprint | INFO | Structural overlap means the mix *serializes* rather than colliding — advisory, never blocks. **Repair direction is `policies.gap13_repair`** (default `widen`) — see below the table. |
| Gap 13 (sharing): 4+ features in one plugin share the identical footprint | INFO | Advisory only — never blocks validation. Do NOT auto-fix: partitioning is a design choice. Route to Manual Review with a proposed sub-directory split (routes/models/services) and let the user pick "partition as proposed" or "keep serialized". |
| Gap 14: declared `<layout>` but no `shape="core"` workspace-foundation feature | ERROR | Insert a new first feature: `<feature index="1" shape="core" touches_files="<workspace-root configs from the error's suggestion>"><description>Scaffold the workspace skeleton: <the foundation requirements listed in the suggestion></description></feature>`, renumber is NOT needed (use the next free index if 1 is taken and add `depends_on="<its index>"` to every other feature). |
| Gap 15: zone's declared profile contradicts on-disk markers | WARNING | Do NOT auto-switch — the spec wins by design (mid-migration layouts are legitimate). Route to Manual Review quoting the rival profile from the message; the user picks "switch to <rival>" or "keep (migrating)". |
| Gap 16: feature's blast radius looks large (multi-module prose, or ≥5 declared files) | INFO / WARNING | Do **NOT** auto-fix — splitting a feature is a design choice only the author can make (same posture as Gap 13 sharing). Route to Manual Review with a proposed split: one bullet per observable outcome named in the description, preserving the original wording in each. The user picks "split as proposed" or "keep as one". Under `--autonomous`, record as a deferred decision rather than rewriting feature boundaries unattended. `shape="integration"` never trips this gap. |

**Gap 13 (mix) — the two repair directions**

The validator can see that a plugin mixes a whole-directory glob with a sub-glob; it cannot
see whether that is a botched partition or a partition in progress. Those want opposite
repairs, so the choice is a recorded policy rather than a guess:

| `policies.gap13_repair` | Repair | When it is right |
|---|---|---|
| `widen` *(default)* | Drop the narrower features' explicit `touches_files=` so the parser re-derives `src/plugins/<name>/**`. Safe, deterministic, restores serialization. | The partition was accidental. The user can re-partition properly later (all features → non-overlapping sub-globs, per /create-spec Phase 3.25 Step 3.5). |
| `complete-partition` | Keep the sub-globs and give the *whole-glob* features explicit non-overlapping `touches_files=` of their own, so every feature in the plugin is partitioned at the same granularity. | The partition was deliberate — the user wanted these features to run in parallel, and widening would silently take that away. |

`complete-partition` needs a footprint for each un-partitioned feature and can only propose
one from the feature's own description. When no non-overlapping split is derivable, **fall
back to `widen`** and record the fallback (Step 7) — a wrong partition collides at dispatch
time, and the conservative direction is the one that serializes.

**Examples:**

```
# BEFORE (Gap 1 — ERROR):
<feature shape="plugin">
  <description>User can register with email and password</description>
</feature>

# AFTER (category was "Authentication"):
<feature shape="plugin" plugin="authentication">
  <description>User can register with email and password</description>
</feature>
```

```
# BEFORE (Gap 6 — WARNING; category "User Profile"):
<category name="User Profile">
  - User can edit their profile name (returns 200)
  - User can edit their profile avatar (returns 200)
  - User can delete their profile (returns 204)
</category>

# AFTER:
<category name="User Profile">
  <feature index="N" shape="plugin" plugin="user-profile">
    <description>User can edit their profile name (returns 200)</description>
  </feature>
  <feature index="N+1" shape="plugin" plugin="user-profile">
    <description>User can edit their profile avatar (returns 200)</description>
  </feature>
  <feature index="N+2" shape="plugin" plugin="user-profile">
    <description>User can delete their profile (returns 204)</description>
  </feature>
</category>
```

```
# BEFORE (Gap 8 — WARNING; migration work mis-shaped as plugin):
<feature shape="plugin" plugin="tickets">
  <description>Add a migration creating the app.tickets table</description>
</feature>

# AFTER:
<feature shape="core" touches_files="migrations/versions/**">
  <description>Add a migration creating the app.tickets table</description>
</feature>
```

```
# BEFORE (Gap 9 — WARNING; Storage category shares no keywords with any phase):
<category name="Storage &amp; Repository Pattern">
  <feature index="35" shape="core" touches_files="src/storage/vec.py" depends_on="30">
    <description>System sqlite-vec extension loaded at connection time</description>
  </feature>
  <feature index="36" shape="core" touches_files="src/storage/event_log.py">
    <description>System NDJSON event log writer appends one JSON line per event</description>
  </feature>
</category>

# AFTER (prev feature in same category is index 35):
<category name="Storage &amp; Repository Pattern">
  <feature index="35" shape="core" touches_files="src/storage/vec.py" depends_on="30">
    <description>System sqlite-vec extension loaded at connection time</description>
  </feature>
  <feature index="36" shape="core" touches_files="src/storage/event_log.py" depends_on="35">
    <description>System NDJSON event log writer appends one JSON line per event</description>
  </feature>
</category>
```

```
# BEFORE (Gap 13 mix — INFO; whole-glob + sub-glob in one plugin):
<feature index="20" shape="plugin" plugin="tasks">
  <description>User can create a task (returns 201)</description>
</feature>
<feature index="21" shape="plugin" plugin="tasks"
         touches_files="src/plugins/tasks/search/**">
  <description>User can search tasks by keyword (returns 200)</description>
</feature>

# AFTER (widen back to one granularity — parser re-derives the shared glob):
<feature index="20" shape="plugin" plugin="tasks">
  <description>User can create a task (returns 201)</description>
</feature>
<feature index="21" shape="plugin" plugin="tasks">
  <description>User can search tasks by keyword (returns 200)</description>
</feature>
```

**Gaps that cannot be auto-fixed** (Gap 3 overlap, Gap 5 missing dir, Gap 7
long chain, Gap 9 first-in-category, Gap 13 partitioning of a shared
footprint): list under Manual Review (see Step 7) — these require domain
judgment.

### Layer 3 fixes (coverage gaps)

A table, column, endpoint, or auth flow exists in the spec metadata but has no corresponding
bullet. Add the missing bullet(s) in the most relevant category:

```
# Gap: table "notifications" has no bullets
# Add to Notifications category:
- System creates a notification record when a task is assigned to a user
- User can list their notifications (paginated, 20 per page, newest first)
- User can mark a notification as read (sets read_at timestamp)
```

## Step 5: Write the fixed spec

Write the full corrected spec back to the same file. Preserve:
- All XML structure (tags, attributes, whitespace between sections)
- All non-flagged bullets verbatim
- Category order and names

## Step 6: Re-run validate-spec

Use the same command as Step 2 — strict shape is on by default, so shape
gaps introduced during the rewrite get caught immediately.

```bash
claw-forge validate-spec <spec-file> 2>&1
```

Read the summary line (same as Step 2):
- `✅ Spec passed validation — no issues` → fully clean. Report success (see output format below).

If issues remain: go back to Step 4 for another pass. Repeat up to **3 times total**.

If issues still remain after 3 passes, list them and ask the user:
"These issues may require domain knowledge to resolve — should I attempt another pass,
or would you like to fix them manually?"

## Step 7: Manual Review block

Some issues cannot be auto-fixed without domain knowledge. Surface each in
a structured list at the end of fix-spec output. **Under `--autonomous` this
block is written to `deferred_decisions.yaml` instead of asked — see Step 7a;
the items and their fields are identical either way.** For each item include:

- **Feature** — exact bullet text and any relevant attribute (touches_files, plugin)
- **Question** — the specific decision the user must make
- **Candidate fixes** — 2–3 concrete options (a, b, c) the user can adopt by editing the spec

Issue types that go here:

| Issue | Why manual |
|---|---|
| Gap 3: core/plugin `touches_files` overlap | Requires deciding which feature owns the conflicting file |
| Gap 5: `plugin="X"` references nonexistent directory | Could be typo, could be missing scaffold, could need creation |
| Gap 7: long core-on-core dependency chain | Requires architectural decomposition |
| Step 0: `shape="core"` missing `touches_files` | File list is domain knowledge |
| Step 0: `shape` typo with Levenshtein distance > 2 | Cannot guess intent |
| Gap 9: feature is first in its category with no explicit depends_on= | Foundation feature vs cross-category predecessor is domain knowledge |

**Example block (appended to output):**

```
Manual review needed (3 items):

  1. [billing] core feature touches_files overlap with src/plugins/billing/
     Feature: "All endpoints validate JWT" (touches_files: src/**)
     Question: which feature owns billing/auth.py — core or the billing plugin?
     Candidate fixes:
       a) Narrow core to src/core/**, src/middleware/**
       b) Move the plugin's auth.py to src/core/billing-auth.py
       c) Drop the overlap by excluding the plugin glob

  2. [profile] plugin="profile" references nonexistent directory
     Question: typo, or does the plugin not exist yet?
     Candidate fixes:
       a) Rename to plugin="profiles" (closest existing dir, distance 1)
       b) Override with explicit touches_files=
       c) Create src/plugins/profile/ via boundaries apply

  3. [auth-chain] depends_on chain of 5 core features
     Chain: auth-base → jwt-mw → rate-limit → audit-log → metrics
     Question: can any link be reshaped as a plugin instead of core?
     Suggestion: factor jwt-mw into a shape="plugin" plugin="jwt"
     by isolating its files to src/plugins/jwt/.

  4. [Storage & Repository Pattern] feature 29 is first in its category with no explicit depends_on=
     Feature: "System Repository abstract base classes define one interface per resource..."
     Question: should this depend on any prior-category foundation feature, or is it a true foundation?
     Candidate fixes:
       a) Declare it a foundation feature — leave depends_on absent (the cycle-safe default
          gives it no predecessors)
       b) Rename a phase title to include a category keyword like "storage" or "repository"
          so phase inference picks it up
       c) Add cross-category depends_on= pointing at an appropriate predecessor
          (e.g. a config-loader feature index)
```

The user reads, picks (a/b/c) by editing the spec, then re-runs `/fix-spec`.

## Step 7a: `--autonomous` — record the block instead of asking

When `--autonomous` is passed **and** `policies.manual_review` is `default-and-record`
(its default), Step 7's list is not printed as a question. It is written to
`deferred_decisions.yaml` beside the spec, and the command **continues to its normal
success report** — a deferred item is not a failure, it is a decision nobody has made yet.

The fields map one-to-one onto the interactive block, so nothing is lost by not asking:

| Manual Review | `deferred_decisions.yaml` |
|---|---|
| the item's heading (`[billing] …`) | `field` |
| **Feature** — the bullet and its attributes | `context` |
| **Question** | `question` |
| **Candidate fixes** (a/b/c) | `candidates` (a list) |
| *(new)* why it was not answered | `reason` |

**Canonical form** — one mapping at the root, entries under `deferrals:`:

```yaml
deferrals:
- field: gap-3:billing
  question: which feature owns billing/auth.py — core or the billing plugin?
  candidates:
  - Narrow core to src/core/**, src/middleware/**
  - Move the plugin's auth.py to src/core/billing-auth.py
  - Drop the overlap by excluding the plugin glob
  reason: 'deferred by --autonomous: policies.manual_review = default-and-record'
  context: 'Feature: "All endpoints validate JWT" (touches_files: src/**)'
- field: gap-13:tasks
  question: complete the partition for feature 20, or widen 21 back to the plugin glob?
  candidates:
  - 'Set touches_files="src/plugins/tasks/crud/**" on feature 20 (completes the partition)'
  - Drop feature 21's touches_files= so both re-derive src/plugins/tasks/**
  reason: 'deferred by --autonomous: no non-overlapping split derivable, fell back to widen'
```

Rules for writing it:

- **Overwrite, never append.** The file renders what *this* run could not decide. Carrying
  an entry the user has since resolved forward would fill the queue with ghosts.
- **Write it even when empty** (`deferrals: []`). An absent file means "autonomous repair
  never ran"; an empty list means "it ran and deferred nothing", and those are different
  facts worth being able to tell apart.
- **Every entry needs candidates.** An entry with a question and no options is a report that
  something is wrong, not a decision anyone can make — if no option is derivable, say so as
  a candidate ("no automatic fix; the file list is domain knowledge").
- `claw_forge/spec/brief.py` owns the schema: `Deferral`, `dump_deferrals` (pure),
  `write_deferrals`, `read_deferrals`. Read a hand-edited queue back through
  `read_deferrals` rather than re-parsing it — it accepts a bare list too, and it raises
  rather than silently reporting an empty queue for a file it could not understand.

When `policies.manual_review` is `halt`, `--autonomous` **does not apply** to Step 7: the
interactive block is printed and the command stops, exactly as without the flag. A recorded
intent to be asked outranks a flag on the command line.

### Output format under `--autonomous`

Append to the success report rather than replacing it:

```
📋 3 decisions deferred → deferred_decisions.yaml

  gap-3:billing      which feature owns billing/auth.py?
  gap-5:profile      typo, or does the plugin not exist yet?
  gap-13:tasks       complete the partition, or widen back?

Review and edit the spec, then re-run: /fix-spec
```

## Output format

On success:
```
✅ Spec fixed: <spec-file>

  Pass 1: 6 issues (3 errors, 3 warnings) → 2 remaining
  Pass 2: 2 issues (0 errors, 2 warnings) → 0 remaining

  Fixed:
    ✗ [task-management] Split compound bullet "User can create and edit a task"
    ✗ [auth] Rewrote compound bullet "User can register and then login"
    ✗ [api] Added action verb to "Error responses from the API"
    ⚠ [auth] Added measurable outcome to "Handle errors appropriately"
    ⚠ [notifications] Added 3 bullets for uncovered "notifications" table
    ⚠ [auth] Rewrote vague bullet "Password reset link in email"

Next: claw-forge plan <spec-file>
```

On partial fix (issues remain after 3 passes):
```
⚠ 2 issues remain after 3 fix passes:

  ⚠ [auth] Score 6.5 on Specificity — some bullets still use vague language
    → Consider adding exact field names, status codes, or error messages

  ⚠ [notifications] Coverage gap: endpoint POST /api/notifications/bulk-read
    → Add: "User can mark multiple notifications as read in one request (accepts array of ids)"

Fix these manually in <spec-file>, then re-run: claw-forge validate-spec <spec-file>
```
