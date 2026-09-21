# Feature 230 — Policy-admission static checks

**app_spec.xml, "Exploration Policy Runtime", feature 230** (`plugin="policy-runtime"`, `depends_on=229`):
*System rejects a policy admission when static checks detect absolute score constants, hardcoded node ids or an unreachable commit path.*

Authoritative spec: docs §634 — "Static checks before any policy is admitted: no
absolute score constants, no hardcoded node ids, … `commit()` reachable on every
terminating path". The paper's hard constraints (docs §436, §634): prefix-only, no
unrevealed scores, no hardcoded node ids, no absolute score targets, and `commit()`
mandatory (a policy that terminates without committing scores −∞).

## Context — why this feature, and what it is not

A policy is authored text against the identical `question.*` interface (docs §11,
C4): `observed()`, `legal_actions()`, `legal_roots()`, `probe_batch()`,
`budget_remaining()`, `plan_grid(ctx)`, and the **mandatory terminal**
`question.commit(node_id)`. Feature 229 (this member's `plan_grid`) admits a policy
only if its planning hook returns a non-null plan. Feature 230 is the next gate on
the same admission path: **admit a policy's authored source only if static analysis
finds none of the three barrier-breaking anti-patterns**.

The three, as the spec names them:

1. **Absolute score constants** — a literal absolute score target in the policy body
   (`>= 0.8`, `> 0.5`, `== 0.75`, `threshold = 0.3`). This is the paper's "no
   absolute score targets": a policy that hard-codes a score level overfits the
   calibration of the pool it was written against and fails to transfer. The
   barrier's whole point (§10.2, cq-8) is that a policy never *sees* an absolute
   score, so authoring one is evidence it was tuned off the answer key.
2. **Hardcoded node ids** — a string literal that is a node address in the policy
   body (`"n0"`, `"d+9.i+0.s+0.a+0"`, `"root"`, `"n123"`). A node id is the one
   address a node is revealed/committed on (§185: "node ids aren't UUIDs"); a
   policy that names one is reading past the prefix the barrier promises it — it
   knows a cell it was not shown.
3. **Unreachable commit path** — a terminating path in the policy that never reaches
   `commit()`. `commit()` is mandatory (§438: "A policy that terminates without
   committing scores −∞"); a path that can end without committing is a policy that
   can score on a pick it never made, so it is refused at admission.

**What it is not (the split is the feature):** it does not *run* a policy, *score* a
policy, *replay* a campaign, or *learn* anything — those are the discovery member's
features (232–237), which build on this one's guarantee that an admitted policy is
clean. It does not judge a plan's *contents* (theme diversity is 234's; width/depth
is 235's) — that is 229's neighbour. It is the **read side**: a pure gate over source
that returns a verdict, never raises, and lets the caller decide — the exact shape
229's `plan_grid` and sandbox's `screen_module` take. Feature 231 (deferred: reject a
policy that loads a checkpoint / calls inference) builds on this one's seam.

## The house shape this follows (do not invent a new one)

- **Verdict gate, not exception:** `screen_policy(source) -> PolicyAdmissionDecision`
  returns `adopted` (computed from `reason`), `reason` (a `str` enum whose value is
  the token each refusal's detail opens with — greppable in an admission log), and
  `detail` (the full sentence). Nothing raises here — the pipeline runs it over every
  candidate and one bad policy must not crash an unattended evaluator. Follows
  feature 229's `PlanGridDecision` and sandbox's `ModuleDecision` exactly.
- **`require()` is the bridge:** the one method that raises, on the caller's last line
  before admitting a policy — `source = law.screen_policy(source).require()`. A
  refusal raises `PolicyAdmissionRefusal` naming the policy, so the admission log and
  the retry prompt say the same thing. Follows 229's `PlanGridDecision.require` and
  signal_agent's `SourceAdoption.require`.
- **Reason enum split by *repair*, not by which check failed** (229's discipline):
  two policies that both break the barrier for different reasons are two different
  prompts to the retrying agent, so they are two reasons.
- **Error vocabulary in `errors.py`, subclassing the member's `PolicyRuntimeError`**
  so a caller catching the read-side path's one base class catches an admission
  refusal too (the single-except discipline `bootstrap.errors` / `artifacts._errors`
  state).
- **`@register` only in the package `__init__`, never a submodule** (memory: a
  submodule's registration fires only on first `create_app()`). This feature adds **no
  new component** — like 229's `plan_grid`, it is a pure function over source with no
  store, no deployment state, no I/O. The existing `policy-runtime` component (the
  campaign tree, feature 217) is untouched. The gate is reached directly by a caller
  (`from policy_runtime import screen_policy`) exactly as 229's `plan_grid` is.
- **Stdlib only, import-cheap:** `ast` is stdlib; no third-party import at module
  scope, so the factory's scan (which imports this member to fire its `@register`)
  pays nothing.
- **A member never imports another member.** The gate uses `ast` and the member's own
  errors. It does not import `sandbox`, `canary`, or any sibling.
- **Tests live in the member's own suite** (`packages/policy-runtime/tests/`), NOT the
  repository-level `tests/` (memory: the acceptance gate ignores member suites, and
  same-basename files collide under one pytest run). Run explicitly.

## Implementation

### 1. `packages/policy-runtime/src/policy_runtime/admission.py` (new module)

Stdlib only (`ast`, `enum`, `typing`, `collections.abc`), importing `.errors`.

**`AdmissionReason(str, Enum)`** — the audit vocabulary, split by repair:

- `CLEAN = "clean"` — admitted: no anti-pattern found.
- `ABSOLUTE_SCORE = "absolute-score"` — a literal absolute score constant.
- `HARDCODED_NODE_ID = "hardcoded-node-id"` — a literal node-address string.
- `UNREACHABLE_COMMIT = "unreachable-commit"` — a terminating path that never reaches `commit()`.
- `UNREADABLE_SOURCE = "unreadable-source"` — the source is not text / does not parse (a screen cannot admit what it cannot read — the vacuous-green defence sandbox's `screen_module` applies).

**`PolicyAdmissionDecision`** (frozen dataclass): `reason`, `detail`, and
`offenders: tuple[str, ...]` (the offending literals / line references, for the
refusal's reader — the sandbox screen lists every offending import term; this lists
every offending literal). `adopted` is a computed property (`reason is CLEAN`).
`require() -> str` returns the source on admission, raises `PolicyAdmissionRefusal`
on refusal.

**`screen_policy(source: object) -> PolicyAdmissionDecision`** — the feature's verb,
in order, each step's own reason:

1. **readability** — not a non-empty string → `UNREADABLE_SOURCE`; does not parse →
   `UNREADABLE_SOURCE` (carrying the syntax error, as sandbox does). Nothing is judged
   over code that cannot be read.
2. **absolute score constants** — walk the tree for `ast.Compare` nodes whose right
   operand is a numeric constant, plus bare numeric constants in a score-target
   position. Detect `obs_expr <op> number` (where `<op>` is one of `== != < <= > >=`)
   and `number` standing alone as an assigned/returned target. The offending literal
   is recorded. **Deliberately conservative — no false negatives over false
   positives:** a policy legitimately comparing an *observed metric* to a number
   (e.g. `observed[c].r2_insample > 0.5`, `budget_remaining() < 5`) WILL be flagged,
   because the barrier forbids a policy authoring *any* absolute score constant, and
   a policy that needs one has already broken the contract; refusing it and naming the
   literal is the correct, safe answer. The alternative (trying to prove the left side
   is "not a score") is a false-negative machine that lets `score >= 0.8` through. The
   memory note [[featsel-argmax-not-equality-pinned]] is the same stance: pin the
   property, don't rationalise the exception away.
   - Concretely: any `ast.Constant` whose value is an `int`/`float` (not `bool`, not
     complex) that appears as the right operand of a comparison, or as a bare
     numeric literal compared/assigned as a threshold, is an offender. Left operand is
     not inspected for what it names — the presence of an absolute numeric target is
     the offence.
3. **hardcoded node ids** — walk the tree for `ast.Constant` string literals that look
   like node addresses. A node id is a short, address-shaped token (the planted tree
   uses `n0`/`n1`; the bootstrap lattice uses `d+9.i+0.s+0.a+0`; §185: "node ids
   aren't UUIDs"). Detection: a string literal matching the address shape — a run of
   `[a-z0-9]` segments joined by `.`, `+`, `-`, `_`, or a bare short token like `n0`,
   `root`, `n123` — is an offender. **Exclude** the known API/keyword strings a policy
   legitimately uses (`"momentum"`, `"value"` theme roots, `"VOID"` calibration
   status, etc.) via a small denylist of non-address words, and exclude anything that
   is clearly a message/longer prose. Conservative: the address shape (`\b[a-z][a-z0-9]*([.+\-_][a-z0-9]+)*\b`, lower-case, short, no spaces, no uppercase UUID pattern) is what a node id *is*; a UUID (`[0-9a-f]{8}-…`) is explicitly NOT a node id and is not flagged. The offending literal is recorded.
4. **unreachable commit path** — control-flow reachability of a `commit` call. Parse
   to an AST; find every `ast.Call` whose `func` is an `ast.Attribute` with
   `attr == "commit"` (i.e. `X.commit(...)` — the canonical `question.commit(node_id)`,
   the interface name; the object is not pinned because a policy may name the question
   anything). Build a reachability model over the function bodies: a `return`/`raise`
   that is reachable without a preceding `commit` on its path marks an unreachable
   commit. Concretely, walk each top-level `def`/`lambda` body and flag any `return`
   or `raise` statement (and any function whose body can fall off the end) that is not
   preceded, on its own statement-path, by a `commit()` call. A policy whose every
   terminating path passes through `commit()` is admitted; one with a `return` before
   any `commit` (e.g. `if cond: return None` at the top) is refused. This is the
   "commit() reachable on every terminating path" rule, enforced structurally.
   - Implementation: a lightweight intra-procedural reachability — for each function,
     walk statements in order; track whether a `commit()` has been seen on the current
     path; a `return`/`raise`/fall-off-end reached with no `commit` seen is an
     unreachable-commit offender. (Intra-procedural, not inter-procedural — a helper
     function that commits and is called is not modelled across the call boundary; the
     canonical policy commits inline at its terminal, and a policy that delegates its
     commit to a helper is rare and, if it does, the helper's `commit()` is still
     present in the source — the gate checks that *some* path reaches a `commit`, and
     a policy that commits at all in its main body passes. This is the same
     degrade-toward-no-false-admission stance: if in doubt, the absence of a reachable
     inline commit is the safe refusal.)

The first anti-pattern found wins (return that decision); the order is
readability → absolute-score → hardcoded-node-id → unreachable-commit, so the retry
prompt names the most fundamental problem first.

### 2. `packages/policy-runtime/src/policy_runtime/errors.py` (extend)

Add `PolicyAdmissionRefusal(PolicyRuntimeError)` — raised by `require()` on a refused
admission, naming the policy. Sits beside `PolicyTreeError`/`PolicyAddressError` as a
third subclass, split by *which contract* was violated (the module docstring's stated
discipline).

### 3. `packages/policy-runtime/src/policy_runtime/__init__.py` (extend)

Import and re-export `AdmissionReason`, `PolicyAdmissionDecision`,
`PolicyAdmissionRefusal`, `screen_policy`; add to `__all__`. **No new `@register`.**
The existing `build_campaign_tree` component is untouched.

### 4. `src/app/modules/policy-runtime/__init__.py` (extend docstring only)

No code change — the feature adds no component. Optionally extend the module docstring
to note the member also exposes the admission gate (`screen_policy`) reached directly,
as 229's `plan_grid` is, so a reader knows the seat is not the whole of the member.
(No new helper — the gate is pure and reached from the member directly.)

### 5. `packages/policy-runtime/tests/test_admission.py` (new suite)

Pinned against the three anti-patterns plus the admitted/canonical case, following the
existing `test_planning.py` docstring style (each test a claim, citing the feature and
docs section). Cases:

- **admits a clean policy** — the canonical `def policy(question): … return question.commit(current)` (the greedy walk from `test_symreg_question.py`, adapted) is admitted with `CLEAN`.
- **admits a clean policy with observed-metric comparisons** — a policy that compares an observed metric (`observed[c].r2_insample`) to a number is… (decide: per conservative design, this WILL be flagged as absolute-score; the test pins that the barrier forbids it — OR the test uses a non-numeric comparison like `len(frontier) > 0`). I'll write the clean policy to use only non-numeric-threshold logic (`max(...)`, `len(...) > 0`, string/attribute access) so it is genuinely clean, AND add a separate test pinning that `observed[c].r2_insample > 0.8` is refused (documenting the conservative no-false-negative stance).
- **refuses an absolute score constant** — `if observed[c].r2_insample >= 0.8: …` → `ABSOLUTE_SCORE`, literal `0.8` in offenders, `>= 0.8` style. Also `threshold = 0.5`.
- **refuses a hardcoded node id** — `question.commit("n0")` or `question.reveal("d+9.i+0")` → `HARDCODED_NODE_ID`, the literal in offenders.
- **admits a UUID-looking string** — a policy using a UUID literal is NOT flagged (proving the node-id detector excludes UUIDs).
- **refuses an unreachable commit** — a policy with `if cond: return None` before any `commit()` → `UNREACHABLE_COMMIT`.
- **admits a policy that commits on every path** — `return question.commit(a) if cond else question.commit(b)` → `CLEAN`.
- **refuses non-source / unparsable source** — `42`, `""`, `"def ("` → `UNREADABLE_SOURCE`.
- **`require()` raises `PolicyAdmissionRefusal` naming the reason on refusal; returns source on admission.**
- **`PolicyAdmissionRefusal` is a `PolicyRuntimeError`** — single-except discipline.
- **the decision never raises from `screen_policy`** — every refusal is a returned value.

### 6. Additions spec — `additions_spec_230.xml`

New file mirroring the `additions_spec_217.xml` structure (brownfield mode):
`<project_name>` "nullius — feature 230 (System rejects a policy admission when static
checks detect absolute score constants, hardcoded node ids or an unreachable commit
path)", `<addition_summary>`, `<existing_context>` (the module loader, the verdict-gate
shape of 229/sandbox, the `question.*` interface and the mandatory `commit()`),
`<features_to_add>` with `<feature>` blocks for the reason enum, the decision,
`screen_policy`'s three checks, the error, and the exports, `<integration_points>`,
`<constraints>` (no new component, no `@register` in a submodule, no member import, no
central file edited, stdlib only, all suites green), `<implementation_steps>`,
`<success_criteria>`. This is the claw-forge workflow's required input.

## Files changed (all within declared footprint)

- `packages/policy-runtime/src/policy_runtime/admission.py` — new (the gate).
- `packages/policy-runtime/src/policy_runtime/errors.py` — add `PolicyAdmissionRefusal`.
- `packages/policy-runtime/src/policy_runtime/__init__.py` — export the gate.
- `src/app/modules/policy-runtime/__init__.py` — docstring only (no code).
- `packages/policy-runtime/tests/test_admission.py` — new suite.
- `additions_spec_230.xml` — new spec.

**No shared file is edited.** No registry, router, app factory, middleware, settings,
or migration. No new `@register`. No member import.

## Verification

```bash
# worktree-local uv cache (sandbox: ~/.cache is read-only)
export UV_CACHE_DIR="$(pwd)/.claw-forge/tmp/uv-cache"

# the new member suite (the acceptance gate does NOT collect this — run explicitly)
uv run pytest packages/policy-runtime/tests/ -q

# confirm the existing 71 policy-runtime tests still pass
uv run pytest packages/policy-runtime/tests/ -q   # expect 71 + new = green

# lint only the changed files against a sibling (repo lint is red on main:
# mypy absent, 163 pre-existing ruff errors — do not run run.sh lint)
uv run ruff check packages/policy-runtime/src/policy_runtime/admission.py \
                     packages/policy-runtime/src/policy_runtime/errors.py \
                     packages/policy-runtime/tests/test_admission.py
```

Acceptance: the new suite is green; the canonical clean policy is admitted; each of
the three anti-patterns is refused with its own reason and the offending literal
named; `require()` raises `PolicyAdmissionRefusal` (a `PolicyRuntimeError`); the
existing 71 tests stay green; `additions_spec_230.xml` validates (compare its profile
to sibling 217's — Layer-6 cq INFO findings are expected by construction, per
[[additions-spec-validate-baseline]], and never block).

## Risks / judgment calls (flagged for review)

- **Conservative absolute-score detection** will flag a policy that compares an
  observed metric to a literal number. This is deliberate (no false negatives over
  false positives — the barrier forbids authoring any absolute score constant) and is
  pinned by a test. If the reviewer wants the opposite trade-off, that is a one-line
  change to the detector, but it would be a spec regression.
- **Intra-procedural commit reachability** does not model a commit delegated to a
  helper function across a call boundary. The canonical policy commits inline; a
  policy that commits only inside a helper would be refused. This is the safe
  direction (refuse-don't-admit a possibly-uncommitted policy).
- **Node-id shape heuristic** uses a regex + denylist; a node id shaped like a common
  English word could false-positive, but the address shape (lower-case, short, no
  spaces, segment-joined) plus the denylist of known non-address words keeps that
  rare, and a false positive is the safe refusal.
