# Feature 233 — Planning may read only prior campaign manifests

**app_spec.xml, "Discovery Orchestrator & Campaigns", feature 233**
(`plugin="discovery"`, `depends_on=232`): *System rejects a plan_grid implementation
that inspects the current episode, because planning may read only prior campaign
manifests.*

Authoritative spec, docs/nullius-tech-architecture.md §605–§606:

```python
def plan_grid(self, ctx: GridPlanningContext) -> GridPlan:
    """Runs BEFORE a campaign. May read only prior campaign manifests.
    Must return a non-None plan on every path, including empty history."""
```

and PRD §426: *"Plus `plan_grid(context) -> GridPlan(branch_count=W, refine_count=R)`,
run **before** a campaign, using only prior-campaign manifests. Never inspects the
current episode."* §11.1, §634 and the §15 control table (`"Single-theme campaign
slipped through" | plan_grid assertion | Hard fail at planning time; the campaign is
never created`) put the planning hook on the hard-constraint side, beside the
information barrier.

## The seam this feature owns — why it lands in *this* member

Feature 229 (policy-runtime, `planning.py`) already built the planning *law* — a
non-null `plan_grid` on every path including empty history — and it says in as many
words that the boundary is not its own:

> the hook cannot read past the prior-manifests-only boundary (**that boundary is
> feature 233's check**; 229 hands the hook a context with nothing in it and asks
> only "did it return a plan?")

Feature 229 tests the hook against a *synthetic empty* context built by the law. It
therefore cannot answer 233's question, and it deliberately does not pretend to.
233 is the caller-side check on the same path: the orchestrator runs the hook
against the *real* prior manifests before it opens a campaign — the step feature
232's record is created for and feature 234 fails at *"so the campaign is never
created"*.

**It lands in `packages/discovery` and not beside 229 in policy-runtime**, for two
independent reasons:

1. **Footprint and the workspace contract.** The declared claim scope is
   `packages/discovery/**`. No member imports another, so discovery cannot reach
   `policy_runtime.plan_grid` or `GridPlanningContext` — it *restates* the spelling
   it needs, which is what this member already does for the sqlite path
   translation, the node-id canonicalization, the `sqlite_master` probe, §4.1.1's
   clip and §7.3's regimes.
2. **The subject is the orchestrator's planning *step*, not the policy's plan
   *value*.** 235 owns the plan a hook returns and the counts it derives; 234 owns
   the theme-diversity judgement; 236/237 own the depth allocation. 233 owns one
   thing: **what a planning hook may read**, judged at the moment the orchestrator
   runs it.

## The design: the aperture — a context with no episode in it

Feature 223 is the member's precedent for this shape and the reason it is the right
one: *"Absent rather than filtered — the distinction the sentence turns on … the
barrier is a fact about what the object is made of."* 233 is that same construction
applied to the planning context:

* **`PlanContext` holds prior manifests and the runtime's ceilings, and nothing
  else.** `prior_campaigns` (the prior campaign manifests, feature 242's values),
  `max_branches`, `max_refinements` — the three reads 229's `GridPlanningContext`
  already fixes a hook's author against, restated here so a hook written for 229
  runs unmodified. No question, no tree, no reveal set, no frontier, no budget, no
  current campaign id: there is nowhere in the object the current episode *could*
  be, so a hook cannot reach it by attribute walking or a stray `__dict__` (the
  class carries `__slots__` and no dictionary at all — 223's exact construction).

* **Every episode-shaped name is refused *and recorded*, at the reach.**
  `__getattr__` fires only after normal lookup fails, so the permitted three reads
  work and anything else lands there. A name on `EPISODE_SURFACE` — the current
  episode's own vocabulary: §11's question API (`question`, `observed`,
  `legal_actions`, `legal_roots`, `meta`, `probe_batch`, `budget_remaining`,
  `commit`, `reveal`), feature 224's blocked pair (`best_so_far`, `budget_spent`),
  and the campaign's live state (`tree`, `episode`, `node`/`nodes`, `frontier`,
  `campaign`/`campaign_id`, `cells`, `is_null`, `score`, `select`, `run`) — raises
  :class:`PlanInspectionError` **and is appended to the context's record before
  raising**.

* **The record is the load-bearing half.** A hook that writes
  `getattr(ctx, "question", None)` swallows the `AttributeError` a plain refusal
  would raise — and is *still* refused, because the reach is a fact the context
  recorded. The seam reads the record after the call and refuses naming **every**
  attribute the hook reached for (the "name every offender" discipline
  `ThemeSet.assign_all` and `admit_completed_campaigns` both state). This is what
  makes the feature a check rather than a hope.

* **The call shape is the second face of the same predicate.** A hook that demands
  a parameter beyond the context — `def plan_grid(self, ctx, question)`, handed over
  unbound — is an implementation that expects the episode at its signature. Refused
  by binding the hook's signature against the one argument planning has;
  keyword-only parameters with defaults and `**kwargs` are admitted, because they
  can run without the episode.

### The seam's verb, in order

```
plan_grid(hook, *, prior_campaigns=(), max_branches=0, max_refinements=0)
```

1. **the ask is well formed** — `hook` callable, `prior_campaigns` a batch of this
   member's `CampaignManifest` (a bare string is *not* iterated into characters:
   `ThemeSet.assign_all`'s stated guard), the two ceilings genuine non-negative
   ints. Refused with `CampaignPlanningError` — malformed asks, before anything runs.
2. **the hook's call shape takes the context alone** — otherwise
   `PlanInspectionError` with the `demands_episode` code. An unavailable
   signature (a C callable) skips this check rather than refusing a legitimate
   callable; the record still guards the reads.
3. **run the hook under a freshly built `PlanContext`** — a new context per call, so
   nothing a hook wrote between calls can move the next one (223's freshness).
4. **judge the record** — a hook that reached is refused, naming every attribute;
   a hook that reached and *then* failed is refused the same way with the hook's own
   error chained as the cause (**the recorded reach wins over the hook's own
   failure** — the reach is the fact this feature exists to catch); a hook that
   raised without reaching propagates its own error unchanged (**this seam is not
   the non-null judge** — that is 229's law, and the split is the feature).

Admitted, the seam returns the hook's own return value unchanged: feature 235's plan
law and 229's non-null law judge it, not this one — an admission is a judgement,
never an edit (242's `admit_completed_campaigns` states the same).

### Error taxonomy

One new class in `errors.py`: `PlanInspectionError(DiscoveryError)`, **not** a
subclass of `CampaignPlanningError` — the repair differs in kind (a malformed ask is
re-sent corrected; an implementation that reached for the episode is *rewritten*),
the reason `IllegalThemeError` and `VoidCampaignError` are siblings too. It carries
both faces of one predicate — *did this implementation reach for the current
episode?* — split by how, the same "one class, both faces" shape
`IllegalThemeError`'s docstring already documents:

| code | face |
|---|---|
| `inspects_episode` | the hook read an episode-shaped name off the planning context |
| `demands_episode` | the hook's call shape requires a parameter planning does not have |

Both codes are module constants, greppable at the head of the message, in the
`ILLEGAL_THEME` / `VOID_CAMPAIGN_CODE` tradition. The spec names no `… error message`
phrase for 233, so the tokens are this member's own and the docstring says so.

### Honest limits (stated in the module docstring, not hidden)

* A hook that reaches the episode **through a module global or its own `self`** — a
  policy object constructed with the question, a path assembled at runtime — is not
  caught: the seam judges what the hook reads *from the planning context*, which is
  the surface planning is given. This is 230's stated dynamic-spelling limit in this
  member's own words; the *write* half is closed by the object's attribute protocol.
* §11.1 legitimately fixes `beta` and the thresholds on the policy object in
  `__init__`, so inspecting `self` is *not* evidence of anything — which is exactly
  why a `self`-walk would be a false-positive machine.
* `PlanContext` refuses **every** assignment and deletion (223's `PrefixView`
  construction): a hook cannot rewrite the history it was handed, and the refusal is
  the attribute protocol's own `AttributeError`, naming the law.

## What this feature is not

* **No new `@register` component.** The planner's seam is a pure function over a
  hook and the manifests a caller holds — no store, no URL, no deployment state, and
  no builder that could ever return `None`. It inherits feature 241's reason
  (*"a function wearing a component's name"*) and 242's sharper one (*a component is
  built on every `create_app()`*). `"discovery"` stays the member's single
  registered name, and the component suite's "exactly one unprefixed component" /
  `app.order` adjacency assertions are untouched.
* **No store, no I/O, no campaign.** Pure, like 229's law: the caller reads prior
  manifests through feature 242's `CampaignManifests.completed()` — one reader, one
  authority on what a completed campaign holds — and hands them in. No
  `DATABASE_URL`, no `sqlite3`, no file.
* **No static source screen.** 230/231 already own the source face for the
  policy-runtime family, and a name-based screen is the heuristic the aperture
  replaces with a construction.
* **No migration, no shared file.** Nothing touches `migrations/**`,
  `src/app/middleware.py`, `src/app/settings.py`, the app factory, or the module
  registry — 233 is a new submodule in this member's own package.

## Files

All inside the declared footprint (`packages/discovery/**`,
`src/app/modules/discovery/**`) except the two spec artifacts at the repo root,
which are feature-specific filenames no sibling owns.

| file | change |
|---|---|
| `packages/discovery/src/discovery/planner.py` | **new** — the aperture, the episode surface, the two codes and the `plan_grid` seam. Stdlib only (`inspect`, `collections.abc`, `functools`-free); no third-party import at module scope, so the factory's scan pays nothing. |
| `packages/discovery/src/discovery/errors.py` | add `PlanInspectionError` + `__all__`, extend the taxonomy narrative |
| `packages/discovery/src/discovery/__init__.py` | export the new names; docstring paragraph on the module and why 233 adds no component |
| `packages/discovery/tests/test_planner.py` | **new** suite (no basename collision — unlike `test_planning.py`, which policy-runtime already holds; members are collected together in practice) |
| `src/app/modules/discovery/__init__.py` | docstring only — the seat notes the member also exposes the planning seam, reached directly as 229's `plan_grid` is (the change feature 225 made to the policy-runtime seat) |
| `additions_spec_233.xml` | **new** — the claw-forge workflow's required input, mirroring `additions_spec_230/231.xml`; feature-specific name, so it does not touch the shared `additions_spec.xml` a sibling task edits |
| `.plans/feature-233-planning-may-read-only-prior-manifests.md` | this plan, at the repo's six-sibling convention path |

## Tests — `packages/discovery/tests/test_planner.py`

Members' style: each test a claim, long narrative docstrings citing the feature and
docs section, refusals pinned **by class and by code constant** rather than by prose
(the `test_themes.py` / `test_manifest.py` discipline).

1. **A hook that plans from the prior manifests alone is admitted** and its return
   value comes back as the *same object* (a judgement, never an edit).
2. **The legitimate reads work** — `prior_campaigns`, `max_branches`,
   `max_refinements` — including the **empty-history** context (`prior_campaigns=()`),
   the path §11 names.
3. **Every episode-shaped read is refused**, parametrised over an *independently
   transcribed* tuple of names (from §11's question API, feature 224's blocked pair
   and PRD §426 — not from `EPISODE_SURFACE`, which would agree with itself), with
   the `inspects_episode` code leading the message and the offending name in it.
4. **A hook that swallows the refusal is still refused** — `getattr(ctx, "question",
   None)` returning a perfectly good plan — the load-bearing test of the record.
5. **A hook that reached and then raised** is refused as an inspection with the
   hook's error chained (`__cause__`), while **a hook that raised without reaching
   propagates its own error unchanged**.
6. **Every reach is named** — a hook that swallows two reaches names both.
7. **The call shape** — `(self, ctx, question)` unbound → `demands_episode`; an
   optional keyword-only parameter and `**kwargs` → admitted.
8. **The aperture is episode-free by construction** — episode names are absent from
   `__slots__`, there is no `__dict__` (223's stray-access case), and assignment /
   deletion are refused.
9. **Malformed asks are `CampaignPlanningError`** — a non-callable hook, a bare
   string standing in for a batch, an entry that is not a manifest, a `bool` /
   negative / non-int ceiling.
10. **Freshness** — two calls build distinct contexts, so a hook cannot carry state
    across planning calls.
11. **Error-class discipline** — `PlanInspectionError ⊂ DiscoveryError`, and not a
    `CampaignPlanningError` nor a `VoidCampaignError` (the sibling suite's own test).
12. **A cross-member pin, inside this file** (not in `test_cross_member.py`, which
    sibling tasks in this member also edit): with `pytest.importorskip` and the
    sibling's `src/` added to `sys.path` the way `test_cross_member.py` does it,
    assert `EPISODE_SURFACE` covers `policy_runtime.PolicyQuestion`'s public reading
    methods — so a sibling that grows a new episode accessor is caught here rather
    than silently escaping the boundary.

## Verification

```bash
export UV_CACHE_DIR="$(pwd)/.claw-forge/tmp/uv-cache"

# the member suite — the acceptance gate ignores member suites, so run it explicitly
uv run pytest packages/discovery/tests -q      # baseline today: 513 passed, 1 skipped

# the graded suite must not move
uv run pytest tests -q

# lint only what I changed, compared against the same files at HEAD
# (run.sh lint is unusable on this repo: mypy absent, 163 pre-existing ruff errors)
uv run ruff check packages/discovery/src/discovery/planner.py \
                     packages/discovery/src/discovery/errors.py \
                     packages/discovery/src/discovery/__init__.py \
                     packages/discovery/tests/test_planner.py \
                     src/app/modules/discovery/__init__.py
```

Acceptance: the new suite green; the member suite at its 513-passed baseline (no
existing test edited unless a *true* claim about it changed); `tests/` unmoved; the
new module adds no component (`app.order` and the component suite untouched); no
shared or order-sensitive file edited.

## Judgment calls flagged for review

* **Aperture, not a static source screen.** The rejected thing is *observed* rather
  than inferred from names, and the record closes the swallow hole a plain refusal
  would leave. Cost: a hook reaching the episode through a global or `self` escapes
  — documented, not hidden.
* **Raising, not a verdict object.** The discovery member's planning path raises
  named refusals (`assign_theme`, `admit_completed_campaigns`, `finish_campaign`),
  and the orchestrator cannot proceed without a plan; 229 already owns the
  verdict + `require()` shape for the policy-runtime family. If a reviewer wants
  `PlanDecision` + `require()` for symmetry with 229, that is a small, local change
  — but it would be a second spelling of the same gate in one workspace.
* **The `demands_episode` face is in scope.** It is the same sentence ("an
  implementation that inspects the current episode") read at the call shape, and the
  member's discipline splits reasons by repair. Removing it is a two-line deletion if
  a reviewer reads 233 more narrowly.
