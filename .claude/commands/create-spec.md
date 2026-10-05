---
description: Interview and write the project's app_spec.xml (features, not bugs) for claw-forge plan
argument-hint: [what you want to build, or a path to existing docs]
model: claude-opus-5
---

# Create Project Spec (XML)

Generate an AutoForge-compatible XML project specification for claw-forge. This produces 150-400+
granular feature bullets that become individual agent tasks.

Supports two modes:
- **Greenfield**: building a new project from scratch → produces `app_spec.txt`
- **Brownfield**: adding features to an existing project → produces `additions_spec.xml`

---

## Brief-Driven Mode (non-interactive)

**Check this before anything else — before the Auto-Detect check below.**

```bash
test -f spec_brief.yaml && echo "BRIEF" || echo "NO BRIEF"
```

### No brief → today's behavior, byte-for-byte

If `spec_brief.yaml` does **not** exist, this section does not apply and
**everything below it runs exactly as written** — the Auto-Detect check, the
Brownfield Flow, and every interactive phase of the Greenfield Flow including
Phase 2.5's stack question, Phase 3.25 Step 2's "Sound right?", Step 3.5's
`[p]/[s]`, Phase 3.5 Step 2's `[s]/[k]/[q]`, and Phase 5's "Does this look
right?".  Nothing is skipped, reworded, or defaulted.

This is the **back-compat floor** and it is non-negotiable.  It mirrors
`<layout>`: a spec that declares none gets `default_layout()` and
byte-identical legacy behavior.  A change that makes the no-brief path
diverge from what is documented below has broken this command regardless of
what it improved.

### Brief present → resolve, never ask

`spec_brief.yaml` is a decision record that was resolved *before* synthesis
(see `claw-forge brief init | extract | check`).  Its existence means every
judgment call this command would otherwise stop and ask about **already has
an answer**.  So:

> **Ask the user nothing that the brief answers.**  No questions, no
> confirmations, no "sound right?", no `[s]/[k]/[q]` prompt.  Resolve,
> record, write the files.

This follows the house rule the rest of the harness enforces without
exception: *a judgment call must never halt an unattended run — default
conservatively and record it.*  See the runtime invariant ceiling (`observe`,
never `raise`), `preflight_warnings` ("advisory only, never a liveness
gate"), and `handle_uncommitted_at_startup: smart` ("never aborts").

**The one exception is the confirm gate**, below — and it is not an
exception to the rule so much as an application of it.  The gate never
halts: with `--yes` it does not run at all, and without `--yes` it runs
only when the brief contains entries the harness is genuinely not
confident about.  A fully-resolved brief produces an empty gate, and then
this mode really does ask nothing.

Read the brief first, and check it:

```bash
claw-forge brief check spec_brief.yaml
```

`brief check` is **advisory here, not a gate**.  Report what it says and keep
going: a field the brief got wrong, left empty, or spelled unrecognizably is
treated as *absent*, which falls through to the policy default and is
recorded as a `by: defaulted` decision.  Aborting because the decision record
had a typo would reintroduce exactly the halt this mode exists to remove.

#### What the brief resolves

Greenfield/Brownfield selection is unchanged — run the Auto-Detect check
below and enter the flow it picks.  Inside that flow, every interactive
decision point resolves from the brief instead of from the user:

| Interview point | Today's prompt | Resolved from |
|---|---|---|
| Phase 1 — identity | project name, one-liner | `identity.name`, `identity.domain` |
| Phase 2 — quick vs detailed | asks the user | **Quick**, unless this invocation already supplied technical detail (docs, `$ARGUMENTS`, the conversation) |
| Phase 2.5 — stack & layout | asks the stack | `stack.layout_profile` → the `<layout>` in the table below.  Empty ⇒ emit no `<layout>` (single-package default) |
| Phase 3 — core features | conversational elicitation | derived from `competency_questions` + `constraints` + whatever this invocation already supplied |
| Phase 3.25 Step 2 — shape grouping | "Sound right?" | accept the grouping as classified; a feature the classifier cannot place takes `policies.unclassifiable_shape` |
| Phase 3.25 Step 3.5 — partition | `[Enter] partition (recommended)` / `[s] keep serialized` | `policies.plugin_partitioning` (`partition` \| `keep-serialized`).  Interactive default is **partition** for 4+ feature plugins; the autonomous policy default stays `keep-serialized` |
| Phase 3.5 Step 2 — overlap | `[s] serialize` / `[k] keep parallel` / `[q] quit` | `policies.overlap_resolution` (`serialize` \| `keep-parallel`).  **`[q] quit` is not representable** — a policy whose value is "abort the run" is the failure mode this table removes |
| Phase 4 — technical details | asks | `constraints`, plus this invocation's context |
| Phase 5 — "Does this look right?" | asks before writing | write the files directly |

**Competency questions are where the features come from.**  The brief holds
*decisions, never content* — there are no feature bullets in it — but
`competency_questions` are the user's intent in answerable form ("Can a user
sign up, create a project, and add a task?").  Expand each one into the
bullets that make it answerable, and keep the unmet ones for the
`<category name="End-to-End Verification">` journeys Phase 5 would otherwise
have to invent.

**A field the brief has no answer for still does not become a question.**
Take the conservative option, and record it as a decision with
`by: defaulted`.  That record is the whole point: a run that guessed at
everything is distinguishable from one that resolved everything only if the
guesses are written down.

#### The confirm gate — review only what is uncertain

A brief usually resolves everything, and then this mode genuinely asks
nothing.  But a brief assembled from documents can carry entries the
harness is *not* confident about — a constraint paraphrased rather than
quoted, a competency question inferred from the domain template, a layout
detected somewhere other than the repo root.  The confirm gate shows those
and **only** those.

```bash
claw-forge brief gate            # human render
claw-forge brief gate --json     # the same selection, machine-readable
```

The selector is `claw_forge.spec.brief.gate_items(brief)` — pure, and the
single place `policies.confidence_floor` is applied.  An entry is shown
when it is flagged `needs_review`, or when it carries evidence whose
confidence is **below** the floor (exactly at the floor passes).  An
unflagged `defaulted` entry is never shown: its 0.0 is a constant the
writer stamped, not a measurement, so comparing it to a threshold would
put all seven policy keys in every gate.  Items sort by priority ascending,
then confidence ascending — most urgent and least certain first.

**Render the gate items and nothing else.**  Not the confident entries, not
the policy table, not a summary of the brief.  The whole value of this step
is that it is four rows instead of fifty questions; a gate that grows to the
length of the interview it replaces has failed.

Show the header the command prints — `N of M entries need your attention
(X extracted · Y inferred · Z needs-your-call)` — then the rows, then offer
exactly three options:

```
[Enter]  accept the shown defaults — you have read them and they are fine
[e]      open spec_brief.yaml in $EDITOR, then re-run `claw-forge brief gate`
[y]      accept everything without reading it, recorded as deferrals
```

`[Enter]` and `[y]` write the *same values*; what differs is the audit.
`[Enter]` means a human looked, so each entry is recorded with
`needs_review: false` and a rationale naming the gate.  `[y]` means nobody
looked, so each is recorded as a **deferral** — provenance carried through
unchanged, `needs_review` forced on.  Overwriting `by` with `defaulted`
would erase how the value actually arrived; what `[y]` adds is only that no
human read it, which is exactly what the flag already means.

The gate does not write `spec_brief.yaml`.  A confirmed entry keeps its
`needs_review` flag on disk, so a later run re-gates it — deliberate for
now: the decision record is the audit, and silently editing the artifact
the user is reviewing is a bigger change than this step should make.

#### `--yes` — the fully autonomous path

```
/create-spec --yes
```

Skip the gate entirely.  Do not render it, do not prompt, accept every
default, and record **every** gate item as a deferral.  The records come
from the canonical writer, so they cannot drift from the format below:

```bash
claw-forge brief gate --deferrals >> spec_decisions.jsonl
```

That command *prints*; it writes no file.  `spec_decisions.jsonl` keeps
exactly one writer — this command's synthesis step — and the deferral lines
are appended alongside the decisions it emits for the table above.

`grep 'deferred by --yes' spec_decisions.jsonl` then answers "what did this
run skip past?", and it answers it whether the run skipped one entry or
forty.  That is the point: `--yes` is allowed to be silent, but it is not
allowed to be *unaccountable*.

#### Emit `spec_decisions.jsonl`

Write it **beside `app_spec.txt`**, at the project root, in the same step
that writes the spec.  One JSON object per line, no wrapping array:

```json
{"field": "policies.overlap_resolution", "chosen_value": "serialize", "by": "defaulted", "source": "tier:standard", "confidence": 0.0, "needs_review": false, "rationale": "features 14 and 18 both touch the auth router"}
{"field": "stack.layout_profile", "chosen_value": "pnpm-monorepo", "by": "detected", "source": "pnpm-workspace.yaml, apps/web, apps/api", "confidence": 1.0, "needs_review": false, "rationale": "markers matched at the repo root"}
```

Keys, in order: `field`, `chosen_value`, `by`, `source`, `confidence`,
`span` (omit when there is none), `needs_review`, `rationale`.  `by` is one
of the five provenance classes — `elicited`, `detected`, `extracted`,
`inferred`, `defaulted` — and it is **derived from how the value arrived,
never self-reported**.  The canonical writer and reader for this format are
`claw_forge.spec.brief.write_decisions` / `read_decisions`; the format is
defined as whatever `write_decisions` emits.

Record one line per decision point in the table above that you actually
resolved — including the ones that came out as today's default.  A decision
record that only lists the surprising choices cannot answer "did anything
ask a human?", which is the question it exists to answer.

#### Report at the end

Phase 6's next-steps block still applies.  Add one line before it:

```
📝 Resolved <N> decisions from spec_brief.yaml without asking
   (<D> defaulted, <R> flagged needs_review) → spec_decisions.jsonl
```

When the gate ran, or `--yes` skipped it, add its outcome too — a run that
deferred is not the same as a run that resolved, and the report is where
that difference is cheapest to notice:

```
🚦 Confirm gate: <G> of <M> entries shown · <A> confirmed, <F> deferred
```

---

## Auto-Detect Mode

**First**: decide whether this directory already contains source code.

```bash
# Brownfield if a prior claw-forge run left a manifest, OR the directory
# already carries a language manifest / the legacy plugin root.
ls brownfield_manifest.json pyproject.toml package.json go.mod Cargo.toml \
   Gemfile build.gradle pom.xml composer.json 2>/dev/null | head -1
test -d src/plugins && echo src/plugins
```

- Any output → run the **Brownfield Flow** below
- No output → run the **Greenfield Flow** below

**Why not just `test -f brownfield_manifest.json`?** That was the old gate, and
it was wrong in the one case that matters most: `brownfield_manifest.json` is
written **only** by the post-run hook of a completed *greenfield* build
(`orchestrator/run_cli.py`). A project claw-forge did not build never has one,
so every genuinely brownfield repo silently took the greenfield flow — the
flow that assumes nothing exists yet.

**Why not `.git`?** `.git` is in the harness's own `_BROWNFIELD_MARKERS`
(`spec/validator.py`), but that list is only ever consulted *after* the spec
has already declared `mode="brownfield"`, so a bare repo costs nothing there.
Here the detection stands alone, and a greenfield project that ran `git init`
first — which `claw-forge run` does automatically — would be misrouted into
the brownfield flow. A repo with no code is greenfield.

---

## Brownfield Flow

> Use when adding features to an existing codebase.

### Step 1: Load manifest (if any) + check for hotspot report

If `brownfield_manifest.json` exists, read it and extract:
- `stack` (language, framework, database)
- `test_baseline` (N tests, X% coverage)
- `conventions` (naming style, patterns, etc.)

**If it does not exist — the normal case for a repo claw-forge did not
build — derive the same three values instead of stopping.** Never invent a
`test_baseline`; either measure it or say it is unmeasured.

```bash
# stack + conventions: read whatever manifests are present
ls pyproject.toml package.json go.mod Cargo.toml pom.xml build.gradle 2>/dev/null
# conventions: linters/formatters/type-checkers actually configured
grep -lE 'ruff|mypy|pytest' pyproject.toml 2>/dev/null
ls .eslintrc* eslint.config.js biome.json tsconfig.json 2>/dev/null
```

For `test_baseline`, **run the suite** and record the real numbers — this is
the value the acceptance gate's own startup probe will independently
re-measure (`probe_baseline_suite`), so a guess here will be contradicted at
run time. If you cannot run it, write
`unmeasured — run the suite before relying on this` rather than a number.

Confirm the derived values with the user before continuing; they are the
project's owner and will spot a wrong framework guess immediately.

Optionally write the result to `brownfield_manifest.json` so later
invocations skip this step:

```json
{
  "stack": "FastAPI / React / Postgres",
  "test_baseline": "measured 2026-09-09: 312 passed, 0 failed, 87% coverage",
  "conventions": "ruff, mypy strict, pytest"
}
```

Then check whether `boundaries_report.md` is present in the project root
(emitted by a prior `claw-forge boundaries audit`).  If it exists and
contains entries with score >= 5.0, surface them to the user before
proceeding:

```
Found a boundaries audit at boundaries_report.md.  These files are
extension hotspots — adding new features as <feature shape="plugin">
will collide with them unless they're refactored first:

  cli/main.py        score=8.4  pattern=registry
  core/router.py     score=6.7  pattern=route_table

Recommended:
  claw-forge boundaries apply --auto

Refactoring these into plugin-extensible patterns first will let your
new features land cleanly as plugins.

Proceed anyway?  [y / yes]   Refactor first?  [b / boundaries]
```

If the user picks `b`, stop the slash command — they'll come back
after the refactor.  If they pick `y`, record the hotspot list as a
warning in `<existing_context>` and continue to Step 1.5.

If `boundaries_report.md` doesn't exist, continue to Step 1.5 silently.

### Step 1.5: Determine the layout

**Do this before Step 2**, because the `plugin=` vs `touches_files=`
answers you collect there only mean something once you know where this
repo actually keeps its code.

This is the brownfield counterpart of the greenfield flow's Phase 2.5.
Without it a brownfield spec declares no `<layout>`, every
`shape="plugin"` feature derives its footprint from the implicit
`single-package` default — `src/plugins/{plugin}/**` — and on a repo
claw-forge did not build, that matches **zero files**.  A footprint that
matches nothing does not merely fail validation: file-claim locking never
collides, `select_disjoint_footprint_batch` believes every task is
disjoint, and parallel agents edit the same files.

Detect it with the brief, which already runs the harness's own
`detect_layout()` — deterministic, offline, no API key, no model call:

```bash
# Reads spec_brief.yaml if it exists; brief init refuses to overwrite one.
test -f spec_brief.yaml || claw-forge brief init
sed -n '/^stack:/,/^competency/p' spec_brief.yaml
```

### Raising the brief from documents — you answer the prompts

> **You are usually the model — probe before assuming a credential.**
> Claude Code holds its *own* credential in the session process and does not
> pass it to tool subprocesses. Unless this machine's shell exports its own
> `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` (some do — check with
> `echo ${ANTHROPIC_API_KEY:+SET}${ANTHROPIC_AUTH_TOKEN:+SET}`), a
> `claw-forge` command you run from here has no credential, and a layer that
> needs a model will report that it was skipped. That is not a spec defect
> and not something to work around by hunting for a key — answer the prompt
> yourself, using the `--emit-prompts` / `--responses` seam below.
> claw-forge keeps the deterministic half: prompt rendering, span
> verification, provenance, merging. You supply only the reply. If the
> probe printed `SET`, the credentialed path just works and the seam is
> unnecessary.

When the user has PRDs, architecture notes or transcripts, extraction can
raise the brief's confidence before you ask anything. Emit the prompts,
answer them, feed them back:

```bash
mkdir -p .claw-forge
claw-forge brief extract <docs...> --emit-prompts > .claw-forge/bx-prompts.json
```

That file holds a `system` string and four passes, each with a `name` and a
rendered `prompt`. Answer each one using `system` as your instructions, add
your reply as a `"response"` field on that pass, save the whole object, and:

```bash
claw-forge brief extract <docs...> --responses .claw-forge/bx-answers.json
```

Pass the **same documents** both times — span verification re-reads them to
check every extracted value against a verbatim quote, and that is what
separates a 0.9-confidence fact from a 0.3 `needs_review` guess. A pass you
leave unanswered costs only its own fields. `.claw-forge/` is gitignored;
delete both files when you are done.

Read `stack.layout_profile` and its `_provenance`, then take **one** of
three branches:

| What the brief says | What it means | Do this |
|---|---|---|
| `layout_profile: <name>`, `needs_review: false` | Markers matched at the repo root | Emit `<layout profile="<name>"/>`.  Confirm the profile name with the user in one line. |
| `layout_profile: <name>`, `needs_review: true` | Markers matched, but **not at the root** — a zoned or polyglot tree | Read the bindings from `_provenance.source` (e.g. `apps/api=uv-workspace, apps/web=pnpm-single-app`) and propose a zoned `<layout>`.  Confirm before writing — a flat profile would be wrong here. |
| `layout_profile: ''`, `source: no layout marker matched` | No known profile fits this repo | Emit **no** `<layout>`, and require an explicit `touches_files=` on **every** feature in Step 2.  Do not fall back to `plugin=` alone — that is the zero-match case above. |

Profile names map exactly as in the greenfield table further down
(`pnpm-monorepo`, `pnpm-single-app`, `uv-workspace`, `go-service`,
`maven-single-module`).  A zoned layout looks like:

```xml
<layout>
  <zone root="apps/api" profile="uv-workspace"/>
  <zone root="apps/web" profile="pnpm-single-app"/>
</layout>
```

**Never invent a profile that the brief did not report.** Declaring
`pnpm-monorepo` on a repo without `pnpm-workspace.yaml` produces
footprints that are wrong in a *new* way rather than empty, and Gap 15
will contradict you at validation time.  When nothing matched, explicit
`touches_files` is the correct answer, not a guess.

### Step 2: Gather addition details

Ask the user (one at a time):

1. **What are you adding?** Give it a name and one-sentence summary.
   - Example: "Stripe payments — let users subscribe to Pro plan via Stripe Checkout"

2. **Where does it live in the codebase?**
   - **Plugin** (lives in its own directory): "I'll add `plugins/payments/`
     for the Stripe code."  Used when the addition is vertical and isolated.
   - **Core** (cross-cutting): "I'll edit `core/middleware/auth.py` and
     `core/db/models/user.py`."  Used when the addition modifies shared
     infrastructure.

   For each feature, record either `plugin="<name>"` (plugin shape) or
   `touches_files="..."` (core shape).  This populates the new
   `<feature shape>` attributes in Phase 3 of the parser, which lets
   the dispatcher schedule for parallel safety.

   **What `plugin="<name>"` alone is worth depends on Step 1.5:**

   - **A layout was detected** — `plugin="payments"` is enough.  The
     profile's `plugin_roots` expand it into real directories
     (`apps/api/src/modules/payments/**`, …), so ask only for the plugin
     slug and let derivation do the rest.
   - **No layout matched** — `plugin="payments"` derives
     `src/plugins/payments/**`, which does not exist in this repo.  Ask
     for the actual directories instead and write them as
     `touches_files="app/billing/**,app/api/routes/billing.py"`.  Keep
     `plugin=` too if it names something real; it is the `touches_files`
     that has to be true.

   Ask for paths **relative to the repo root**, and prefer a directory
   glob (`app/billing/**`) over a file list — a feature that names five
   exact files usually turns out to touch a sixth.

3. **What must NOT change?** List any constraints.
   - Example: "Must not modify auth flow. All 47 existing tests must stay green."

4. **List the features to add in plain English** (one per line, action-verb format):
   - Example: "User can add a payment method via Stripe Elements"
   - Aim for 10–50 features for a medium addition.

5. **Break them into implementation phases** (optional — offer to auto-group):
   - Example: Phase 1: Stripe integration / Phase 2: Subscription UI / Phase 3: Webhooks

### Step 3: Generate `additions_spec.xml`

Use the brownfield template (`templates/app_spec.brownfield.template.xml`) and fill in:
- `<project_name>` from the addition name
- `<addition_summary>` from the summary
- `<existing_context>` from `brownfield_manifest.json` (manifest values win)
- `<layout>` from Step 1.5 — **omit the element entirely** when no profile
  matched; an omitted `<layout>` is the legitimate single-package default,
  whereas a guessed one is a wrong answer the validator will contradict
- `<features_to_add>` from the feature list
- `<integration_points>` from the code-touch areas
- `<constraints>` from the "must not change" list
- `<implementation_steps>` from the phases

`<layout>` is parsed **before** features, so put it above `<features_to_add>`.

Write the file as `additions_spec.xml` in the project root.

Then verify the footprints resolve, before handing the user a spec that
looks finished:

```bash
claw-forge validate-spec additions_spec.xml --project-root .
```

Gap 10 (*footprint matches zero real files*) is an always-ERROR and is the
check that catches a layout guessed wrong or a `plugin=` that needed
explicit `touches_files`. A path the feature will **create** belongs in
`creates="..."` on the `<feature>`, not in `touches_files=` — Gap 10 skips
declared-new paths while file claims still lock them, so never clear the
error by dropping a new file's entry. Fix and re-run until it is clean — do
not present the spec as done while it is red.

### Step 4: Show next steps

```
✅ Brownfield spec created: additions_spec.xml

📊 Summary:
  Features to add: <N>
  Phases: <K>
  Integration points: <M>
  Constraints: <C>

Next steps:
  1. Review additions_spec.xml — add/remove features as needed
  2. Run: claw-forge validate-spec additions_spec.xml --project-root .
  3. Run: claw-forge plan additions_spec.xml
  4. Run: claw-forge run --concurrency 3

💡 Tip: Be specific about constraints — agents will treat them as hard rules.
   "All existing tests must stay green" = agents run tests before committing.
```

> **Why `plan` and not `add --spec`:** `plan` is what writes tasks into the
> state DB, and it is also what persists the spec's `<existing_context>`,
> `<integration_points>` and `<constraints>` into the session manifest so
> every dispatched agent receives them. `add --spec` parses and reports on a
> spec but does not create tasks. The tip above about constraints being hard
> rules is true **on the `plan` → `run` path**.
>
> Step 2 is worth running with `--project-root`: with `mode="brownfield"` and
> real files on disk, validate-spec's filesystem checks (Gaps 5, 10, 15, 16)
> become active and will catch `touches_files` that match nothing — the most
> common brownfield spec defect, because plugin footprints otherwise default
> to `src/plugins/{plugin}/**`.

### Example: Brownfield spec for Stripe payments

```xml
<project_specification mode="brownfield">
  <project_name>MyApp — Stripe Payments</project_name>
  <addition_summary>
    Add Stripe Checkout integration so users can subscribe to the Pro plan.
    Handles subscription lifecycle, webhooks, and billing portal access.
  </addition_summary>
  <existing_context>
    <stack>Python / FastAPI / PostgreSQL</stack>
    <test_baseline>47 tests passing, 87% coverage</test_baseline>
    <conventions>snake_case, async handlers, pydantic v2 models</conventions>
  </existing_context>
  <features_to_add>
    <category name="Payments">
      <feature index="1" shape="plugin" plugin="payments">
        <description>User can add a payment method via Stripe Elements</description>
      </feature>
      <feature index="2" shape="plugin" plugin="payments" depends_on="1">
        <description>User can subscribe to Pro plan via Stripe Checkout</description>
      </feature>
      <feature index="3" shape="core"
               touches_files="src/core/db/models/user.py">
        <description>Extends User model with stripe_customer_id field</description>
      </feature>
    </category>
  </features_to_add>
  <integration_points>
    Extends User model with stripe_customer_id field
    Adds /payments router alongside existing /auth and /projects routers
    New StripeService class in services/stripe_service.py
  </integration_points>
  <constraints>
    Must not modify existing auth flow
    All 47 existing tests must stay green
    Follow existing async handler pattern in routers/
  </constraints>
  <implementation_steps>
    <phase name="Stripe Integration">
      User can add a payment method via Stripe Elements
      System creates Stripe customer on first payment attempt
    </phase>
    <phase name="Subscription Flow">
      User can subscribe to Pro plan via Stripe Checkout
      Webhook handler processes subscription.created events
      User can access billing portal to manage subscription
    </phase>
  </implementation_steps>
  <success_criteria>
    All new features implemented and tested
    Existing test suite still 100% green
    Coverage maintained above 87%
  </success_criteria>
</project_specification>
```

---

## Greenfield Flow

> Use when building a new project from scratch.

### Phase 1: Project Identity

Ask the user (one at a time, conversationally):

1. **What are you building?** Get the project name and a 2-3 sentence description.
2. **Who is it for?** Target audience / users.
3. **What problem does it solve?** The core value proposition.

Summarize back: "So we're building **X** — a tool that helps **Y** by **Z**. Sound right?"

---

### Phase 2: Quick vs Detailed

Ask the user:

> **How detailed do you want to go?**
>
> - **Quick** (5 min): I'll derive the tech stack, database schema, and API from your features.
>   Good for MVPs.
> - **Detailed** (15 min): We'll go through tech stack, database design, API structure, and UI
>   layout together. Better for production apps.

Wait for their choice.

---

### Phase 2.5: Stack & Layout

Once the stack is known (asked here in Quick mode; refined in Phase 4 in
Detailed mode), pick the **layout profile** — it decides which directories
`shape="plugin"` footprints expand into and which shared seams the
harness will guard:

| Stack answer | `<layout>` to emit |
|---|---|
| Python/FastAPI/Django single service | *(none — single-package default)* |
| TS full-stack (decoupled UI + API, pnpm/turbo) | `<layout profile="pnpm-monorepo"/>` |
| Single TS/React/Next app | `<layout profile="pnpm-single-app"/>` |
| Python with uv workspace packages | `<layout profile="uv-workspace"/>` |
| Go service | `<layout profile="go-service"/>` |
| Java/Kotlin service (Maven) | `<layout profile="maven-single-module"/>` |
| **Python API + TS web (the AI-app default)** | zones — see below |

Hybrid (polyglot) example — one zone per subtree plus the generated
API-client contract:

```xml
<layout>
  <zone root="apps/api" profile="uv-workspace"/>
  <zone root="apps/web" profile="pnpm-single-app"/>
  <contract path="packages/api-client/**"
            regen="pnpm --filter api-client generate"/>
</layout>
```

**Foundation feature (MANDATORY for any declared layout — validator
Gap 14 ERRORs without it).** Author it as the FIRST feature, depended on
by every other feature, `shape="core"`, description containing
"Scaffold the workspace skeleton", `touches_files` covering the
workspace-root configs. It must scaffold the profile's discovery
machinery so feature agents never edit shell files:

- `pnpm-monorepo`: `pnpm-workspace.yaml` (apps/* + packages/* globs),
  `turbo.json`, `tsconfig.base.json`, both app shells, the API
  module-loader (glob-mounts `modules/*/index.ts`), file-based routing
  for web, shared test config.
- `uv-workspace`: `pyproject.toml` `[tool.uv.workspace]`, app factory
  with a module loader scanning `src/app/modules/*`.
- `go-service`: `cmd/server/main.go` + the append-only
  `cmd/server/modules.go` blank-import block + module registry.
- `maven-single-module`: `pom.xml` (framework BOM/parent + surefire),
  application entrypoint with component scan over `app.modules`, shared
  test config.
- Hybrid: both zones' scaffolds + the contract codegen pipeline.

**The scaffolded test config MUST bound workers and heap.** Write this into
the foundation feature's description so the config lands before any other
feature can run a suite.

Every modern test runner sizes itself to the *machine*, which is correct
alone and wrong under `claw-forge run`. Measured on an 11-CPU / 18 GB box:
one `vitest run` spawns 10 concurrent forks (`availableParallelism() - 1`)
and each fork inherits V8's default heap limit of **4288 MB** — because V8
derives that from total system RAM, with no knowledge that siblings exist.
That is 42.9 GB of heap entitlement from a *single* suite, a 2.4x
over-subscription before `--concurrency` (default 5) or the acceptance gate
running the same suite a second time multiply it.

```ts
// vitest.config.ts — the foundation task must emit these two lines.
export default defineConfig({
  test: {
    maxWorkers: 2,      // NOT availableParallelism() - 1
    fileParallelism: true,
  },
})
```

Equivalents: jest `maxWorkers` in `jest.config`, pytest `-n 2` (never
`-n auto`) in `addopts`, `cargo test -- --test-threads=2`.

This is **not** redundant with the harness's own guard
(`agent/toolchain.py:apply_node_memory_env`, which caps heap and workers by
environment on every dispatch path). The two cover different populations:
the harness guard binds only harness-launched runs, while the committed
config is what protects CI and a developer's own `npm test` — neither of
which the harness ever touches. Declare both.


Ordered seams (middleware chains, migrations, bundler configs) are
core-task territory — never put them in a plugin feature's
`touches_files` (Gap 11 warns and names the seam tier).

Note for Phase 3.25 Step 3.5 (partitioning): in a multi-root layout,
partition **per root template** — e.g. an 8-feature `tasks` plugin in a
pnpm-monorepo partitions `apps/api/src/modules/tasks/routes/**` etc.,
same all-or-nothing granularity rule applied within each root.

---

### Phase 3: Core Features (Conversational)

This is the most important phase. Ask the user to describe their app's main functionality in
natural language. Guide them through categories:

> **Let's map out what your app does.** Describe the main things a user can do — I'll turn each
> one into specific, testable feature bullets.
>
> Let's start with: **What happens when a user first opens your app?**
> (Registration, onboarding, landing page?)

After each response, derive granular bullets and confirm:

```
From what you described, I'm generating these features:

**Authentication & User Management (5 bullets)**  →  XML: <category name="Authentication &amp; User Management">
- User can register with email and password (returns 201 with user_id)
- User can login with email and password (returns 200 with a JWT access_token)
- System issues a refresh_token on login (saved to the refresh_tokens table)
- ...

Does this capture it? Anything to add or change?
```

The heading name in bold becomes the `name` attribute of a `<category>` element in `<core_features>`.
Keep a note of each confirmed heading — you will use them verbatim as `name` attributes in Phase 5.

Continue through categories:
- **Authentication & user management**
- **Core functionality** (the main thing the app does)
- **Data management** (CRUD, search, filtering, pagination)
- **UI/UX** (responsive design, loading states, error handling, notifications)
- **API layer** (validation, error responses, pagination format)
- **Admin features** (if applicable)
- **Integrations** (third-party services, webhooks, notifications)

**Target: 150-400 bullets total — a guide, not a ceiling.** Measured across nine real specs
the range is 114-316, so a large application legitimately runs past the top of this band.

**Never drop a capability to stay inside the number.** The count is an *output* of how much
the app does, not a budget the app must fit. Breadth (how many capabilities you enumerate)
and depth (how finely each one is split) are independent axes, and trading breadth away to
hold a total is the one failure `claw-forge validate-spec` cannot catch for you: Layers 1-4
are each a function of the spec, so a capability you never wrote has no checker. If the app
genuinely does more, write more bullets.

Each bullet should be a testable behavior starting with an action verb:
- "User can..." / "System returns..." / "API validates..." / "UI displays..."

#### Bullet-writing rules (the validator contract)

`claw-forge validate-spec` runs four layers over every bullet. Write bullets that pass it
the first time — each rule below maps directly to a check that otherwise emits a WARNING or
ERROR that `/fix-spec` would have to clean up.

1. **Start with a recognised subject prefix** (Layer 1, WARNING otherwise). The bullet's
   first word must be one of: `User can` / `User cannot` / `System` / `API` / `UI` / `App` /
   `Admin` / `Service` / `Backend` / `Frontend` / `Database` / `Agent` / `Webhook` /
   `Background`. ✗ "Password reset link in email" → ✓ "System sends a password reset link to
   the user email".

2. **Embed one measurable outcome** (Layer 1, WARNING otherwise). Each bullet must contain a
   recognised observable result. The validator looks for any of: `returns <NNN>` /
   `(returns …` / `displays` / `shows` / `redirects to` / `saves to` / `emits` / `sends` /
   `creates` / `persists` / a `snake_case` field name / `HTTP <NNN>` / `<NNN> error` /
   `error message` / `toast notification`. ✗ "Handle errors appropriately" → ✓ "API returns
   422 with a field-level errors array when validation fails".

3. **One action per bullet — never compound** (Layer 1, **ERROR** otherwise). Do not join two
   actions with a connector. The validator hard-rejects these substrings: `and then`,
   `and also`, `and after`, `and receive`, `and redirect`, `and create`, `and send`,
   `and return`, `then login`, `then register`. ✗ "User can login and receive a JWT" → split
   into two bullets: "User can login …" and "System issues a JWT …". (Plain "and" between
   *nouns* — "email and password", "title and description" — is fine; only the listed
   action-joining phrases are rejected.)

4. **At least 6 words, no vague filler** (Layer 1, WARNING otherwise). Bullets under 6 words,
   or containing `etc` / `various` / `multiple` / `some` / `things` / `stuff` / `items`, are
   flagged. Enumerate instead of summarising.

5. **Cover every table and endpoint** (Layer 3, WARNING otherwise). Each table name in
   `<database_schema>` and each path in `<api_endpoints_summary>` must appear in at least one
   bullet. Mention table names verbatim (e.g. a bullet that references the `refresh_tokens`
   table) so the coverage cross-reference resolves.

6. **One edit-verify cycle** (Layer 4, INFO/WARNING otherwise). A feature should be
   completable by editing one production file plus its test. If a bullet requires creating
   or wiring several modules, it is several bullets. This is a **rework budget, not a
   capability limit**: a feature is the dispatcher's unit of retry, so a failure re-does
   everything it contained — measured rework cost is flat from 1 to 4 files and rises
   steeply beyond, and a ten-module retry produced a silent correctness regression.
   ✗ "System scaffolds the auth plugin and wires it into the router" → split into a
   skeleton bullet plus one bullet per behaviour. Watch for the words the validator
   watches for: `scaffold`, `set up`, `wire`, `bootstrap`, `initialise`, `integrate`,
   `end to end`. **`shape="integration"` features are exempt** — they exist to touch files
   other features own, so a broad footprint there is correct, not a defect.

---

### Phase 3.25: Architectural Shape

After confirming the feature list with the user (Phase 3) and before
overlap analysis (Phase 3.5), classify each feature as either a
**plugin** (vertical, lives in its own directory) or **core**
(cross-cutting, edits files used by every plugin).  The classification
ends up in the emitted XML as `<feature shape>` / `<feature plugin>`
attributes — the dispatcher reads these for parallel-safe scheduling.

#### Step 1 — Group features by likely shape

Read through the confirmed feature list and silently group:

- **Plugin candidates**: features whose description names a single
  domain noun ("user", "task", "billing", "notifications") and whose
  acceptance criteria all read like "user can …" or "system returns …
  for the X resource".  These typically own their own data model,
  routes, and tests, and can be added or removed without touching
  sibling plugins.
- **Core candidates**: features that say "all endpoints …", "every
  request …", "uniform error format", "shared logging", "global rate
  limit", "authentication middleware", "database migrations".  These
  are cross-cutting — they're touched by every plugin's request path.

A feature can be plugin-shape even if it depends on a core concern.
"User can register" is plugin-shape (lives in `plugins/auth/`) even
though it relies on the core `core/db/` connection pool.

#### Step 2 — Confirm with the user

Present the grouping back, naming the plugin directories:

```
Looking at your features, I'd structure them as:

Plugins (parallel-safe — each in its own directory):
  • plugins/auth/      — registration, login, password reset (5 features)
  • plugins/profile/   — view/edit profile, avatar upload (4 features)
  • plugins/tasks/     — CRUD, search, tag filter, pagination (8 features)

Core (cross-cutting — touch every plugin's request path):
  • core/middleware/   — JWT validation, request logging (2 features)
  • core/errors/       — RFC7807 error envelope (1 feature)
  • core/db/           — connection pool, migrations runner (2 features)

Sound right?  Edits welcome:
  - Reclassify a feature: "move feature 14 to core"
  - Rename a plugin:      "rename profile to user-profile"
  - Add a category:       "add plugins/notifications"
```

The user can:
- **Accept** → record the classification.
- **Edit** by line: "move 14 to core", "rename profile to user-profile",
  "split tasks into tasks-crud and tasks-search".
- **Skip** → emit the spec without `shape`/`plugin` attributes (legacy
  behaviour).  Phase 5 emits unchanged.

#### Step 3 — Persist the classification

Build a per-feature dict in memory:

```
feature_shape[<index>] = {
    "shape": "plugin" | "core",
    "plugin": "<plugin_name>" | None,         # set when shape="plugin"
    "touches_files": ["..."] | None,           # set when shape="core" only
}
```

Phase 5 reads this when emitting `<feature>` elements.  Plugin features
get `shape="plugin" plugin="X"` and the parser auto-derives `touches_files`.
Core features get `shape="core" touches_files="..."` (the prose from Step
2 — typically a single file path the user names — becomes the
`touches_files` value).

#### Step 3.5 — Partition large plugins (throughput)

Count the features per plugin from Step 3.  Any plugin with **4+
features** would otherwise serialize: they all share the auto-derived
`src/plugins/<name>/**` footprint, file-claims are exact-string, so the
dispatcher runs them one at a time — and `validate-spec`'s **Gap 17**
parallelism advisory flags exactly this group once the sequential steps it
forces approach the spec's ideal makespan.  Partitioning the plugin into
disjoint sub-globs is the
built-in remedy, so for a plugin at or over the threshold **partition by
default** and confirm the split with the user:

```
plugins/tasks/ has 8 features — un-partitioned they run one at a time.
I'll partition by concern for parallelism:

  • src/plugins/tasks/routes/**    — CRUD endpoints (3 features)
  • src/plugins/tasks/models/**    — schema + queries (2 features)
  • src/plugins/tasks/search/**    — search + filters (3 features)

[Enter] partition (recommended)   [s] keep serialized
```

**Autonomous / brief-driven synthesis does not ask** — honor
`policies.plugin_partitioning` verbatim.  Its default is `keep-serialized`
in every tier *by design*: an unattended run must not dispatch a split it
only guessed, because a mis-placed feature collides silently (see the
disjointness check below).  Partition-by-default is the *interactive*
posture, where a human validates the split before it ships.

**All-or-nothing rule (CRITICAL):** if you partition, EVERY feature in
that plugin gets an explicit non-overlapping sub-glob
(`touches_files="src/plugins/tasks/routes/**"`) — never leave one feature
on the whole-plugin glob while siblings use sub-globs.  A whole-plugin
glob is a structural *superset* of every sub-glob, so the claim layer and
the dispatcher's disjoint-footprint filter detect the overlap and
**serialize** the mixed features — silently defeating the partition you
just made, for the same throughput as not partitioning at all.  It does
**not** corrupt anything (`validate-spec` flags the mix as a Gap 13
**INFO**, not a warning) — but it wastes the whole exercise.

**Disjointness self-check (before you emit):** the chosen sub-globs must
be mutually non-overlapping, and each must name a real sub-directory under
the plugin root — `routes/`, `models/`, `search/`, not two globs that
share a deeper prefix.  The genuine hazard is **not** the mix above (that
merely serializes): it is a **mis-placed feature** — one you file under
`routes/**` that will in fact also write `models/…`.  Two features on
truly-disjoint sub-globs dispatch in parallel, so a feature writing
outside its declared bucket collides with the sibling that owns that
bucket, and **nothing catches it** — the declared globs *are* disjoint.
So place every feature in exactly one bucket, and confirm it with the
user.  A feature that genuinely spans two buckets (the plugin's
`__init__`/wiring feature, a cross-cutting concern) is **not**
partitionable: emit it first on the whole-plugin glob or a narrow named
file (e.g. `src/plugins/tasks/__init__.py`) and give the partitioned
siblings `depends_on` edges to it — it then runs alone in an earlier wave,
so its structural overlap with the sub-globs never causes a parallel
collision.

**Safe fallback:** if the features do not fall into a clean set of
disjoint concern directories, or you cannot confidently place every one of
them in exactly one bucket, keep the whole-plugin glob for every feature.
Serialized is always correct; a guessed split that collides at runtime is
worse than slow.  This is why autonomous synthesis keeps `keep-serialized`
in every tier — it cannot verify a split it only guessed — and why
partition-by-default is the interactive posture, where a human validates
each feature truly lives in one bucket.

**Confirming the remedy:** a correct partition splits one large footprint
group into N smaller ones, each needing a fraction of the sequential steps,
so re-running `validate-spec` should show the Gap 17 advisory no longer
naming this plugin's footprint.

#### Step 4 — Shape rules (the validator contract)

Layer 4 of `validate-spec` is strict by default. Apply these rules while classifying so the
spec passes without `/fix-spec`:

- **A contracts / shared-types subsystem is `shape="contracts"`, not `core`.** It owns the
  files every other spec excludes, so it needs an explicit `touches_files`
  (e.g. `packages/contracts/**`). Write it as a **few large features, not many atomic
  ones**: every feature shares that one footprint so splitting buys no parallelism, and the
  contracts must be mutually consistent. `shape="contracts"` is exempt from the Gap 16
  blast-radius advisory precisely so this stays expressible — do **not** "fix" such a spec
  by splitting it.
- **If a `spec_brief.yaml` exists, every feature you derive from a competency question
  carries `covers="cq-N"`.** Layer 6 checks that each question is covered by at least one
  feature; an uncovered question with a declared `priority: 1` is an **ERROR** that blocks
  `plan`. That link is what makes "did we cover the PRD?" answerable — so emit it while
  authoring, when you still know which question you are expanding.
  - **Brownfield additions specs in a project with a brief: declare subsystems in
    `umbrella.yaml` FIRST.** With no umbrella manifest, Layer 6 holds *every* spec to
    *every* competency question in the brief — a small additions spec adding one
    capability reports every other subsystem's questions as uncovered ERRORs, and no
    edit to that spec can ever clear them. The fix is never a stub feature with an
    unrelated `covers=` (that falsifies traceability for good): add an `umbrella.yaml`
    where each subsystem names its `spec:` path and the question ids it `owns:`, and
    Layer 6 narrows that spec's uncovered-question check to exactly those ids. One-time
    setup per project; every later additions spec validates against only its own
    questions. Verify with `claw-forge umbrella check`.

- **Migration / schema work is always `shape="core"`** (Gap 8, **ERROR** otherwise). If a
  feature description contains any of `migration`, `alembic`, `database schema`, `DDL`,
  `foreign key`, `primary key`, `create table`, `alter table`, `drop table`, `add column`,
  `drop column`, `alter column`, `create index`, or `unique constraint`, it mutates alembic's
  shared revision tree and **must** be emitted as
  `shape="core" touches_files="migrations/versions/**"`. Never classify a migration feature as
  a plugin — parallel agents would write colliding revision files.

- **`shape="plugin"` must carry `plugin=`** (Gap 1, **ERROR** otherwise). Every plugin feature
  needs a `plugin="<slug>"` attribute (or an explicit `touches_files=`). Derive the slug from
  the category name: lowercase, non-alphanumerics → dashes (e.g. "User Profile" →
  `plugin="user-profile"`).

- **Keep core `touches_files` narrow** (Gap 3, ERROR in strict). A core feature's
  `touches_files` glob must not overlap any plugin directory. Use specific paths like
  `src/core/middleware/auth.py` or `src/core/**`, never a blanket `src/**` that would swallow
  `src/plugins/<name>/`.

#### Failure modes

- **User skips classification** → emit Phase 5 unchanged; no `shape`
  attributes.  The legacy parsing path still works; the dispatcher's
  file-claim layer treats every feature as opt-out (no locking
  attempted).
- **A feature can't be classified** (LLM unsure or user says "I don't
  know") → leave that feature unclassified in `feature_shape`.  Phase 5
  emits without `shape` for that feature.
- **User declares a plugin name that conflicts with an existing
  filesystem path** in brownfield mode → warn but accept (the
  boundaries-harness can refactor the colliding file later).

---

### Phase 3.5: Overlap Analysis

After confirming the feature list with the user, audit for **merge-conflict risk** between
features that would be dispatched in parallel. The earlier you serialize known-overlapping
features, the fewer wasted agent runs you'll have downstream.

#### Step 1 — Run the analysis prompt on the bullet list

Number the confirmed bullets from Phase 3 starting at 1. Then, as the LLM executing
`/create-spec`, mentally apply the following prompt to that numbered list:

> You are auditing a feature spec for merge-conflict risk. Below are N feature bullets, each
> numbered. Find pairs where implementing both would force conflicting edits to the same
> file or function — i.e. they would both modify the same hunks if scheduled in parallel.
>
> A pair is overlapping ONLY if changing one without the other would force a merge
> conflict. Belonging to the same category alone is not overlap.
>
> Return JSON only:
> ```json
> [{"a": <int>, "b": <int>, "surface": "<file_or_concept>", "rationale": "<one sentence>"}]
> ```
> Empty list `[]` if no overlaps. No prose outside the JSON.

#### Step 2 — Resolve each overlap interactively

For every entry returned, present:

```
Overlap detected:
  #<a>  <description of feature a>
  #<b>  <description of feature b>
  Shared surface: <surface>
  Rationale: <rationale>

Resolution? [s] serialize (#<b> depends on #<a>)  [k] keep parallel  [q] quit
```

- **`s`** → record an explicit edge: feature `<b>` will be emitted with `depends_on="<a>"` so
  the runtime DAG runs `<a>` first and `<b>` only after.
- **`k`** → record the user's decision to keep parallel; do not flag this pair again on retry.
- **`q`** → abort `/create-spec` cleanly; do not write any files.

If the user selects `m` (merge), explain that merging is out of scope for this phase — they
can manually combine the bullets in Phase 3 and re-run, or pick `s` for now.

#### Step 3 — Persist resolutions through Phase 5

In memory, build a list `serialized_pairs: list[tuple[int, int]]` of `(later, earlier)`
feature numbers from each `s` decision. When Phase 5 emits the XML, every feature that
appears as `later` in any pair must use the new `<feature>` element form with explicit
attributes:

```xml
<core_features>
  <category name="DSL Compiler">
    <feature index="14">
      <description>System displays parse errors on stderr</description>
    </feature>
    <feature index="18" depends_on="14">
      <description>System displays side-by-side diff in terminal</description>
    </feature>
  </category>
</core_features>
```

Multiple dependencies are comma-separated: `depends_on="14,15,16"`. Features without edges
may continue using the legacy bullet form; both coexist within the same `<category>`.

`depends_on=""` (empty) is a **third, distinct** declaration: it means "this feature is a
root". Omitting the attribute leaves the feature open to phase-keyword inference; writing it
empty freezes it with no predecessors. Use the empty form for anything that must start in
wave 1.

When Phase 3.25 classification was accepted, combine `shape`/`plugin` with `index` and
`depends_on` in the same element:

```xml
<!-- Phase 3.25 + Phase 3.5 combined: plugin-shape + dependency edge -->
<feature index="14" shape="plugin" plugin="auth">
  <description>User can register with email and password</description>
</feature>
<feature index="18" shape="plugin" plugin="auth" depends_on="14">
  <description>System sends welcome email after registration</description>
</feature>
<feature index="20" shape="core"
         touches_files="src/core/middleware/auth.py">
  <description>All endpoints validate JWT on incoming requests</description>
</feature>
```

#### Failure modes

- **LLM returns malformed JSON** → re-prompt once with the schema; if still bad, skip the
  analysis with a one-line warning ("could not analyze overlaps; emitting spec without
  explicit edges") and continue to Phase 4.
- **Empty feature list** (Phase 3 produced 0 bullets) → skip Phase 3.5; downstream
  validation handles the empty-spec case.
- **No overlaps detected** (`[]`) → skip directly to Phase 4 with one line: "No overlap
  risk detected — features can run in parallel."

---

### Phase 4: Technical Details (Detailed mode only)

If the user chose **Detailed**, ask about:

1. **Tech stack preferences:**
   - Frontend: React/Vue/Svelte/Next.js? Styling: Tailwind/CSS modules?
   - Backend: Python (FastAPI/Django) / Node (Express/Fastify) / Go / Rust?
   - Database: SQLite/PostgreSQL/MySQL/MongoDB?

2. **Database schema:** Walk through the main tables/collections based on the features.

3. **API structure:** REST vs GraphQL? Authentication method (JWT, session, OAuth)?

4. **UI layout:** Dashboard style? Sidebar navigation? Single page or multi-page?

For **Quick** mode, derive sensible defaults from the features (React + Vite, FastAPI,
SQLite for dev / PostgreSQL for prod, JWT auth, REST API).

---

### Phase 5: Generate the Spec

Generate two files:

#### `app_spec.txt` (XML format)

Use the template structure from `claw_forge/spec/app_spec.template.xml` but filled with the
user's project details. The XML must include:

- `<project_specification>` root element
- `<project_name>`, `<overview>`, `<target_audience>`
- `<layout>` when Phase 2.5 chose a non-default layout (profile sugar or
  `<zone>` children + `<contract>`), plus its mandatory foundation feature
  as feature index 1
- `<technology_stack>` with `<frontend>`, `<backend>`, `<database>`, `<communication>`, `<infrastructure>`
- `<prerequisites>` with environment setup bullet list
- `<core_features>` with categorized bullet lists (this is the bulk — 150-400 bullets)
- `<database_schema>` with `<tables>` containing `<table name="…">` / `<column>` elements
- `<api_endpoints_summary>` with `<domain name="…">` sections
- `<ui_layout>` with main structure
- `<design_system>` with color palette, typography, animations
- `<key_interactions>` with `<interaction number="N" name="…">` flows
- `<implementation_steps>` with `<phase name="…">` elements
- `<success_criteria>` with `<functionality>`, `<ux>`, and `<technical_quality>`

**Important:** Use `&amp;` for `&` in XML content. Each bullet in `<core_features>` becomes one
agent task.

**CRITICAL — `<core_features>` element format:**
Each category group inside `<core_features>` MUST be a `<category name="…">` element with the
full human-readable name as the `name` attribute. The name becomes the task category shown in the
Kanban board and used for routing and filtering.

✅ Correct — `<category name="…">` with descriptive names:
```xml
<core_features>
  <category name="Authentication &amp; User Management">
    - User can register with email and password (returns 201 with user_id)
    - User can login and receive JWT access_token and refresh_token
  </category>
  <category name="Receipt Scanning">
    - System sends the receipt image to OpenAI Vision API…
  </category>
  <category name="API Layer">
    - API returns consistent JSON envelope: { "data": ..., "error": null }
  </category>
</core_features>
```

❌ Wrong — bare snake_case tags lose display names; generic `<category>` loses all names:
```xml
<core_features>
  <authentication>...</authentication>     <!-- loses "&amp; User Management" -->
  <category>...</category>                 <!-- BAD: every task becomes "Category" -->
</core_features>
```

Use the exact heading confirmed with the user in Phase 3 as the `name` attribute.

**REQUIRED — final `<category name="End-to-End Verification">`:**
Always end `<core_features>` with an End-to-End Verification category containing
one `<feature>` per primary user journey, each declared `shape="core"` and
`touches_files="tests/e2e/**"`. These become the terminal tasks that write and
run e2e/integration tests against the fully-assembled app — the difference
between "units pass" and "the app actually runs". List the *real* journeys you
captured in Phase 3 (signup → core action → result), not a generic placeholder.

```xml
<core_features>
  ... feature categories ...
  <category name="End-to-End Verification">
    <feature index="40" shape="core" touches_files="tests/e2e/**">
      <description>System passes an end-to-end test of the primary journey (sign up, create a project, add a task) in which the app boots and the board displays the new task (Playwright/pytest test under tests/e2e/)</description>
    </feature>
    <feature index="41" shape="core" touches_files="tests/e2e/**">
      <description>System passes API integration tests where each documented endpoint returns 200 on the happy path and returns the documented 4xx error on key error cases</description>
    </feature>
  </category>
</core_features>
```

Why a real task, not prose: e2e steps written only inside `<phase>`/`<success_criteria>`
text are never materialized as tasks, so no agent writes them and they go
missing. Declaring them as `shape="core"` features makes them scheduled,
merge-gated, terminal task nodes. (If you omit this, `claw-forge plan` injects a
single fallback "End-to-End Verification" task automatically — but authoring the
specific journeys here is better: they're visible, editable, and split per flow.)
When `agent.acceptance_gate` is enabled, the project's test command — now
including these e2e tests — must pass before each task can complete.

**CRITICAL — `<database_schema>` format:**
Use `<table name="…">` with `<column>` children for each table. Full SQL-style column definitions.

```xml
<database_schema>
  <tables>
    <table name="users">
      <column>id UUID PRIMARY KEY DEFAULT gen_random_uuid()</column>
      <column>email VARCHAR(255) UNIQUE NOT NULL</column>
      <column>password_hash VARCHAR(255) NOT NULL</column>
      <column>created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()</column>
    </table>
    <table name="refresh_tokens">
      <column>id UUID PRIMARY KEY DEFAULT gen_random_uuid()</column>
      <column>user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE</column>
      <column>token_hash VARCHAR(255) NOT NULL UNIQUE</column>
      <column>expires_at TIMESTAMP WITH TIME ZONE NOT NULL</column>
    </table>
  </tables>
</database_schema>
```

**CRITICAL — `<api_endpoints_summary>` format:**
Use `<domain name="…">` sections with plain-text route lines (no bullet prefix needed).

```xml
<api_endpoints_summary>
  <domain name="Authentication">
    POST   /api/auth/register   - Register new user account
    POST   /api/auth/login      - Log in and receive JWT tokens
    POST   /api/auth/logout     - Log out and invalidate refresh token
  </domain>
  <domain name="Receipts">
    POST   /api/receipts/upload - Upload image and trigger OCR
    GET    /api/receipts        - List receipts with filters and pagination
    GET    /api/receipts/{id}   - Get single receipt with line items
    PUT    /api/receipts/{id}   - Update receipt fields
    DELETE /api/receipts/{id}   - Delete receipt and associated file
  </domain>
</api_endpoints_summary>
```

**CRITICAL — `<implementation_steps>` format:**
Use `<phase name="…">` elements with plain-text task lines inside.

**Phase titles must share a keyword with every category name** (Gap 9, ERROR in strict).
The validator infers each feature's dependencies from the phase whose title overlaps its
category name. A feature whose category shares **no word** with any phase title gets no
inferred deps and is flagged — under strict (the default) that's an ERROR, one per feature.
Generic titles like "Phase 2: Core Features" share nothing with a category like "Receipt
Scanning" and trip the whole category. **Derive phase titles from your category names** so
each category maps onto a phase: name the phase after the category (or include the category's
key noun). This clears Gap 9 for every feature in the category at once — no `depends_on`
surgery required.

**Prefer the category's full name in the phase title, not just one of its words.** Matching is
best-overlap: a category binds to the phase whose title shares the *most* words with it, so
`Answer Generation` (phase 9) and `Answer Surface` (phase 13) each bind to their own phase even
though they share "Answer". But a phase title carrying only the shared word (`Phase 9: Answers`)
ties both categories to it, and a tie goes to the earliest phase — which binds the later
category to the wrong predecessor. Naming the phase after the full category name makes the
binding unambiguous.

**But a matching phase title also *enables* inference for that category**, and inference
makes every feature in phase N depend on every feature in phase N-1. If a feature in that
category is genuinely a root — foundation work, a shared contract, anything that should start
in wave 1 — give it `depends_on=""`. An empty declaration is honoured as "runs first" and is
never overwritten by inference; an *absent* one is not a declaration at all. Skip this and a
spec that declares three roots plans as a graph one task wide at level 0, and the run opens at
an effective concurrency of 1 no matter what `--concurrency` says. `claw-forge plan` prints
tasks-per-wave — check that the first number is not 1.

```xml
<implementation_steps>
  <phase name="Phase 1: Authentication &amp; User Management">
    Implement users and refresh_tokens tables
    Implement POST /api/auth/register and POST /api/auth/login
  </phase>
  <phase name="Phase 2: Receipt Scanning">
    Implement the receipts table and OCR pipeline
    Build the receipt review UI
  </phase>
  <phase name="Phase N: End-to-End Verification">
    Write and run the e2e/integration tests for the primary user journeys
    Confirm the app boots and the happy paths pass end-to-end
  </phase>
</implementation_steps>
```

**Always end with a `End-to-End Verification` phase** whose title matches the
final `<category name="End-to-End Verification">`. Because phase-N features
depend on phase-(N-1)'s, the e2e features inherit a dependency on the prior
phase — and transitively on the whole build — so they dispatch **last**, after
every feature has merged and the full app is available to test. The shared
"End-to-End Verification" keyword between the category and this phase also
clears Gap 9 for the e2e features.

#### `claw-forge.yaml`

```yaml
providers:
  - name: claude-oauth
    type: oauth
    enabled: true
    priority: 10

agent:
  max_concurrent_agents: 5
  # Two independent retry budgets. A failed task is re-pended and dispatched
  # again in a later wave with its own error_message in the retry preamble.
  # `agent` covers "the agent gave up" and "the acceptance gate went red";
  # `infra` covers a broken box, which no number of agent retries can fix.
  agent_retry_attempts: 2
  infra_retry_attempts: 2
```

Every key here is one claw-forge actually reads — check `claw-forge.yaml`'s
own scaffolded comments for the full set. The feature list is **not** part of
this file; `claw-forge plan app_spec.xml` writes it to the state DB.

Show both files to the user and ask: "Does this look right? I'll write these files now."

**Brief-Driven Mode skips this confirmation** — a brief on disk already
answered it.  Write the files directly and record the choice.

Then write:
```bash
# Write app_spec.txt to project root
# Write claw-forge.yaml to project root
# Brief-Driven Mode only: write spec_decisions.jsonl to project root
```

---

### Phase 6: Next Steps

After writing files, show:

```
✅ Project spec created!

📊 Summary:
  Features: <N> across <M> categories
  Phases: <K> implementation steps
  Tables: <T> database tables
  Endpoints: <E> API endpoints

Next steps:
  1. Review app_spec.txt — add/remove features as needed
  2. Run: claw-forge validate-spec app_spec.txt
     → Issues found? Run /fix-spec, then re-run validate-spec until clean
  3. Run: claw-forge plan app_spec.txt
  4. Run: claw-forge run --concurrency 5

   validate-spec is strict by default (since v0.8.46): Layer 4 shape gaps
   3, 5, and 9 are ERRORs, and the migration-shape gap 8 is an ERROR too.
   Pass --soft-shape only to opt out during a migration on-ramp.
   /create-spec emits shape-annotated <feature> elements and
   category-aligned phase titles throughout, so the spec is expected to
   pass on first run; if it doesn't, /fix-spec will auto-repair the
   failing elements.

💡 Tip: Each feature bullet = one agent task. More specific bullets = better agent output.
   Aim for 150-400 bullets for a full application; more if the app genuinely does more.

💡 Tip: Features with `shape="plugin"` in your spec can be dispatched
   in parallel without merge conflicts (their `touches_files` are
   disjoint by construction).  Within ONE plugin, features share a
   footprint and serialize — partition big plugins into sub-globs
   (Phase 3.25 Step 3.5) when wall-clock matters.  Features with
   `shape="core"` serialize single-flight via the scheduler's
   cross-cutting rule.  See docs/commands.md → "claw-forge run" for
   parallelism settings.
```
