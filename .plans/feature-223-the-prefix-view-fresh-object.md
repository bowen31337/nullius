# Feature 223 — the prefix view as a fresh object

**app_spec.xml, "Exploration Policy Runtime", feature 223** (`covers="cq-16"`, `plugin="policy-runtime"`, `depends_on=217`):
*System constructs the prefix view as a fresh object, which returns only revealed nodes so unrevealed nodes are absent rather than filtered.*

Authoritative spec: docs/nullius-tech-architecture.md §10.2, in full:

> `prefix_view()` constructs a fresh object exposing only revealed nodes. It is not a filtered view over the full tree; unrevealed nodes are not present in the returned structure at all. A policy cannot reach them by introspection, attribute walking, or a stray `__dict__` access.

with §10.1's call site — `batch = policy.select(prefix_view(revealed))` — naming the moment the object exists for, and docs/alpha-engine-prd.md §415/§637 carrying the hard constraint ("prefix-only information. No unrevealed scores…").

## Context — why this feature, and what it is not

Feature 217 built the question: a `PolicyQuestion` over a `CampaignTree`, with `observed()` returning `{node_id: Observation}` over the question's own reveal set — a mapping that is already prefix-only *as a return value*. But the question itself is the **runtime's** object, and must be: `reveal()` refuses a node outside the tree by looking it up *in the tree*, and every observation is the tree's honest payload-derived reading. A caller holding the question can walk `question._tree` to every node the campaign holds — `PolicyQuestion` has `__slots__` and no guard on the private names, because the runtime that owns it is trusted with them.

223 is the hand-off between the two audiences. What *authored policy code* is handed is a different object by law:

| feature | owns | the object's audience |
|---|---|---|
| 217 | the question — reveal set + honest readings, over the tree | the runtime (trusted with the address seam) |
| **223** | **the prefix view — a fresh snapshot holding only the revealed cells** | **the policy (trusted with nothing but the prefix)** |

**What it is not (the split is the feature):**

* it is not a *filtered view* — a filter would hold the tree and screen it, making the barrier a predicate (one more function to get right on one more path) and leaving the whole campaign one attribute-walk away behind the filter's subject. The view holds prefix data and only prefix data; there is nothing to filter *over*;
* it is not the question made safe — the question keeps its seam; the runtime needs it, and hollowing 217's object would break `reveal`'s refusal contract. The projection is additive, 217 untouched;
* it is not features 224/225 — blocking `best_so_far`/`budget_spent` and the import allowlist are *their own* refusals layered on the policy's environment; 223 is the object those features will defend, not the defense itself;
* it is not a component — no store, no deployment state; a pure construction over a question, reached directly from the member exactly as `plan_grid` (229), `screen_policy` (230/231) and `read_beta` (226) are.

## The house shape this follows (do not invent a new one)

The construction is `PolicyQuestion`'s own: hand-written `__slots__`, a private store, read-only accessors, a `__repr__` that names the count. Not `@dataclass(frozen=True, slots=True)` (used elsewhere in the workspace) for a reason this feature found empirically: the slots rebuild binds the generated `__setattr__` closure to the *pre-rebuild* class, and a non-field assignment on the rebuilt class dies inside `super()` with a bare `TypeError` — an unnamed failure in no vocabulary, where this member refuses *and names*. Hand-written, the guard is one method every spelling of the act lands in, and the refusal is an `AttributeError` — what `hasattr`-catchers catch — whose message states the law.

## Design decisions

### 1. "Absent rather than filtered" is a fact about the object graph, not a predicate

The view's only state is `_cells`: a tuple of the *copied* frozen observations, ascending by node id. No tree, no question, no reveal set — not under an attribute, not in a slot, not anywhere a policy could walk to. `__slots__ = ("_cells",)` means the class has no `__dict__` at all, so §10.2's "stray `__dict__` access" raises before it reads a thing — stronger than finding prefix data there. And where the question *refuses* a node outside the tree (`PolicyAddressError`), the view has no verb for asking: no `node`, no `meta`, no `reveal`. The refusal is structural — one seam weaker than a guard, which is why cq-16 is answered by a construction and not by a check.

### 2. "Fresh object" has two halves — identity and snapshot

*Identity*: every `prefix_view()` call constructs a new object; two views of one reveal set are `==` but `is not`. *Snapshot*: the observations are copied out at construction, never aliased to live question state, so a view held while the question reveals more answers the prefix it was built over. The contrary design — a live view over the question — would let a policy read the prefix extending without revealing: a reveal by other means, the exact leak §10.2 exists to close.

### 3. The factory reads `observed()`, not the tree

§10.1 spells `prefix_view(revealed)`; here the reveal set and the honest readings over it live behind the question, and reading them there makes the view's readings *the question's* — one implementation of the reading (217's), not a second derivation from the raw tree that could drift. The seam is duck-typed (`callable(observed)`, nothing else) for the module-loader double-import reason the tree seam already documents: a composed question may be a *second* `PolicyQuestion` class object an `isinstance` would refuse. What it reads, it validates: a non-mapping answer, or a mapping whose keys disagree with the observations they carry (two names for one cell), is refused here — in `PolicyTreeError`, translated at the seam, never a bare `AttributeError`/`ValueError` escaping past a caller's single `except PolicyRuntimeError`.

### 4. Cells are checked by name, not by `isinstance`

`_cell_node_id` is the one place a cell becomes an addressable id, shared by every guard (constructor, factory agreement check, `observed()`, `__contains__`) so "validated twice" is one rule read twice. It demands the read side of an observation — the id plus the five fields 217 froze — *by name*, so the composed member's twin `PolicyObservation` class fronts the view as readily as the member's own.

### 5. Writes are refused at every spelling, reads are always fresh copies

`__setattr__`/`__delattr__` refuse *any* name (public, private, shadow) with an `AttributeError` naming the law: a policy cannot hand itself a longer prefix it did not earn, nor attach state beside the earned cells — the same boundary `EpisodeBeta`'s setter draws around the scalar. `observed()` returns a fresh dict per call (the `PolicyObservation.row()` guarantee), so a policy scribbling on the mapping it read moves its own copy, not the prefix. `cells` is public on purpose — the way `CampaignTree.nodes` is: a policy that walks it finds revealed cells, which is exactly what it is allowed to find.

### 6. No new error class

The refusals reuse `PolicyTreeError`: they are the answer surface's own contract (the thing handed in did not front the read side; the mapping was not keyed by the ids its cells were earned on), the same family the question's constructor refusals belong to. A sixth error class would split one contract across two names — the lesson 186 recorded ("no fourth error class") and errors.py's "the five subclasses" count states.

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/prefix.py` | **new** — `PrefixView`, `prefix_view`, `_cell_node_id` |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | exports (`PrefixView`, `prefix_view`) + docstring paragraph |
| `packages/policy-runtime/tests/test_prefix.py` | **new** — 23 tests |
| `src/app/modules/policy-runtime/__init__.py` | seat docstring paragraph (223 reached directly, like 226/229/230/231) |

No new `@register` component (a pure construction over a question, exactly as 226/227/228/229 take none); no central registry, router, app factory, middleware, settings or migration edited; no change to 217's `PolicyQuestion` (the projection is additive). The member imports no sibling member — `collections.abc` and `.errors` only at runtime.

## Verification

* member suite `packages/policy-runtime/tests`: **213 → 236 passed** (no existing test edited; the new `test_prefix.py` contributes **23**). Green under both the system python (conftest bootstrap) and `uv run pytest`.
* `ruff check --no-cache`: `prefix.py` and `test_prefix.py` **clean**; the member `__init__.py` reports the **same 4 findings as HEAD** (RUF022 + 3× UP037, all pre-existing); the seat file's N999 is a filename artifact (the hyphenated seat name) present on HEAD, and the seat edit is docstring-only.
* repo-level acceptance gate `uv run pytest` (`testpaths=tests`): **1060 passed** — it does not collect a member's own suite [[acceptance-gate-ignores-member-suites]], so both were run; the worktree needed `uv sync --all-packages` with `UV_CACHE_DIR` pointed inside the worktree first [[repo-test-env-gaps]], [[uv-cache-dir-sandbox-workaround]].
