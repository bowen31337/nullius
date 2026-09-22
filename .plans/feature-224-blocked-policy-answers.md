# Feature 224 — the policy answer surface, blocked over `best_so_far` and `budget_spent`

**app_spec.xml, "Exploration Policy Runtime", feature 224** (`plugin="policy-runtime"`, `depends_on=223`):
*System blocks policy access to best_so_far and budget_spent, which rejects an attribute walk that attempts to reach them.*

Authoritative spec: docs/nullius-tech-architecture.md §10.2, second sentence:

> The policy runtime additionally blocks: `question.best_so_far`, `question.budget_spent`, filesystem access, and any import outside an allowlist.

and the sentence it follows from — prd §12 invariant 3 — *"The exploration policy sees **prefix-only** information. No unrevealed scores, no absolute score targets, no hardcoded node ids."*

## Context — why this feature, and what it is not

The category's four refusals sit at four different seams, and the split is the whole design:

| feature | refuses | the seam | the mechanism |
|---|---|---|---|
| 223 | an unrevealed *node* | the object the policy holds | construction — nowhere to hold one |
| **224** | **an episode's *answers*** | **the object the policy is handed** | **an allowlist over attribute reads** |
| 225 | a file, an import | the interpreter the policy runs on | an audit hook + an `__import__` wrap |
| 230/231 | a policy's *source* | admission, before it runs | static AST checks |

§10.2's sentence names four things; 225 takes the last two (filesystem, imports) and 224 takes the first two. They are one sentence but not one feature, because the pair 224 owns is not a *reach* at all: `best_so_far` is the best score the replay has seen so far, `budget_spent` is the statistical budget already debited — both facts about **the episode**, not about the campaign, and both read by an *attribute access* rather than by a call the guard could catch.

**What it is not:**

* it is not 223's construction — the prefix view is unchanged, and a caller may still build one (223's tests do);
* it is not 225's guard — nothing here installs an audit hook, wraps an import, or reads a ceiling. 224 refuses a read of *its own surface*, which needs no interpreter instrumentation and no extent; the refusal is structural and holds whether or not an episode is running;
* it is not 230/231 — those judge a policy's authored **source** before admission; this refuses the **object** the admitted policy is handed;
* it is not a component — no store, no deployment state; a pure construction over an episode, reached directly from the member exactly as `prefix_view` (223), `read_beta` (226), `plan_grid` (229) and `screen_policy` (230/231) are.

## Design decisions

### 1. An allowlist, not a denylist of the two names — the feature's sentence names the mechanism

The description says it *"rejects an attribute walk that attempts to reach them"*, and only one of three available designs actually stops a walk:

* **allowlist (built)** — answer the names the deployment configured, refuse every other. A walk answers nothing it was not handed, so a field the runtime grows *next quarter* is unreachable the day it is added rather than the day someone remembers to block it. Same construction as feature 167's imports ceiling and 225's own ceiling;
* **denylist of two** — stops those two reads and nothing else; a policy reaches `context.best_score`, `runtime.dollars_spent` or a private `_best` the moment one exists. It also cannot be honest about its own refusal: with no configured set, "blocked" and "absent" are indistinguishable to the walk, so the refusal would have to claim a law it cannot see;
* **no wrapper** — which is what 225 rightly does with *its* halves, because a file and an import are caught where they happen. An attribute read is not: the episode holds the answer and the policy reads it, and the surface is the only seam between those two facts.

**The two names are therefore not a special case in the code.** They are refused for the reason every other unlisted name is refused — not configured — and the module keeps no list of them in the walk path. Where the pair *is* named is `FORBIDDEN_ANSWERS`, which the **constructor** reads: a deployment asking for the very surface the feature forbids is the realistic way this feature is defeated (a banned-name list arriving from 225's armed guard as a list of answers), so the constructor refuses it rather than trusting the deployment's care. The gate checks it first only so a policy that reaches `best_so_far` is told *why* rather than merely *absent*.

### 2. The surface does not hold the episode — the leak this feature exists to close

The refusal is theatre if the object one attribute away is the thing being defended. The first implementation stored `getattr(episode, name)`, and for §11's verb-shaped answers that is a **bound method** — so `surface.observed.__self__.best_so_far` was the entire barrier gone, one `__self__` from every answer. Verified, then fixed: `_answer_value` **calls** the answer and stores the *result*, copying a mapping. `gc.get_referents` and a data-graph walk both confirm no `Episode` is reachable from the surface.

This is feature 223's *absent rather than filtered* restated one level out — the same argument, the same outcome: a surface that held the episode and screened reads would put the episode one `object.__getattribute__`, one `type(surface).__mro__` walk, or one `vars(surface._episode)` away.

The read-once is simultaneously the **snapshot** half: an episode that reveals more after construction does not move a held surface. Verified by a counting test as well as a value test.

### 3. Every answer is a callable

§11's `question.*` interface is verb-shaped all the way down (`observed()`, `legal_actions()`, `budget_remaining()`), so a surface answering a name with a bare *value* would hand a policy a different interface from the one §11 specifies for the same name — the identical-interface requirement 217 opens the member with, applied to the surface. `_accessor` closes over the copied value and returns it per call; a deployment that configures its own *reader* gets a delegating callable whose result is never stored (no leak through that branch either).

### 4. The refusal is an `AttributeError` **and** a `PolicyRuntimeError`

The only doubly-based class in the error vocabulary, and the doubling *is* the feature: an attribute walk is spelled `getattr`, `hasattr`, `contextlib.suppress(AttributeError)` or a `dir()`-driven loop, and every one terminates on the attribute protocol's own error. A refusal that were only a `PolicyRuntimeError` would raise *through* a walk that had already decided the name was absent, so `hasattr(surface, "best_so_far")` would answer a question about the law rather than about the surface. All four spellings are tested.

### 5. One sentence for every unconfigured name

Private names (`_answers`, `__dict__`, `__init__`), dunders the class does not define, and ordinary names the deployment did not admit all get the **same** refusal, so the object offers no way to tell a name that *exists* from one that does not — the property that makes the surface opaque rather than merely closed. Pinned by comparing the two sentences with the caller's own name substituted out.

### 6. Reduction is refused in this member's vocabulary

`copy`/`pickle` are attribute-walk routes like any other — each rebuilds an equivalent object, i.e. a second set to reshape and a route to answers the gate never sees. They are refused, and the four reduction dunders are *forwarded* through the gate (they answer with methods that raise) so `__reduce__` can speak: CPython's default is a bare `copy.Error`/`PicklingError`, an unnamed failure a caller catching `PolicyRuntimeError` would miss. All three routes tested.

### 7. What the gate deliberately answers

`__class__` (the interpreter's protocol; resolves to the *class*, which carries no answer and no episode) and the reduction dunders (which raise). Nothing else private. `__dir__` returns the configured set — the interpreter filters `dir()` through `getattr` with a default anyway, so answering directly makes the enumeration honest rather than incidental, and every name it yields is one the gate answers.

### 8. The default is the safe posture, not the law

§10.2 names two attributes blocked and stops. `DEFAULT_ANSWERS = ("observed", "budget_remaining")` is what an unconfigured deployment gets — the two §11 answers that are already prefix-only. `budget_remaining()` is offered because a policy's own mandate needs it to terminate; `budget_spent` is exactly what that offer leaves out.

### 9. No new error class beyond the one

`PolicyAnswerSurfaceError` is the eighth subclass and the only addition. The configuration refusals, the gate refusals, and the "this episode cannot answer that name" refusal are one law at three moments, so they share one class — the discipline errors.py's count and 186's "no fourth error class" both state.

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/surface.py` | **new** — `PolicySurface`, `policy_surface`, `DEFAULT_ANSWERS`, `FORBIDDEN_ANSWERS`, the gate helpers |
| `packages/policy-runtime/src/policy_runtime/errors.py` | `PolicyAnswerSurfaceError` + module-docstring paragraph (seven → eight) |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | exports + docstring paragraph |
| `packages/policy-runtime/tests/test_surface.py` | **new** — 75 tests |
| `src/app/modules/policy-runtime/__init__.py` | seat docstring paragraph (reached directly, like 223/225/226/229/230/231) |

No new `@register` component; no central registry, router, app factory, middleware, settings or migration edited; no change to 217/223/225 (the surface is additive). The member imports no sibling member — `collections.abc` and `.errors` only at runtime.

## Verification

* member suite `packages/policy-runtime/tests`: **286 → 361 passed** (no existing test edited; `test_surface.py` contributes **75**).
* repo acceptance gate `uv run pytest` (`testpaths=tests`): **1060 passed** — it does not collect a member's own suite ([[acceptance-gate-ignores-member-suites]]), so both were run; the worktree needed `uv sync --all-packages` with `UV_CACHE_DIR` inside the worktree first ([[repo-test-env-gaps]], [[uv-cache-dir-sandbox-workaround]]).
* `ruff check --no-cache`: `surface.py`, `test_surface.py`, `errors.py` **clean**.  The member `__init__.py` and the seat file report the **same 17 findings as HEAD** (same categories, same files) — verified by stashing and diffing the full member's lint output, not by eyeballing ([[repo-lint-is-red-on-main]]).
* Attack-surface checks beyond the suite: `gc.get_referents` + a data-graph walk find no `Episode` and no answer value (excluding type objects, whose `__module__` dict carries this module's own prose); `hasattr`/`getattr`-with-default/`suppress`/`dir()`-walk all behave; `copy`/`deepcopy`/`pickle` all refuse in the member's own vocabulary.
* Two limits of the *class construction*, found by an independent adversarial probe and **identical in feature 223's `PrefixView`** — recorded in the docstring and pinned as facts rather than engineered around: `vars(surface)` raises CPython's bare `TypeError` (the check is on the type's `tp_dictoffset` in C, before any attribute access; a `__dict__` that made the route speak is the very stray dictionary §10.2 names), and `object.__setattr__` reaches any slot directly, as on every slots class. What *survives* the second route is the guarantee that matters and is now pinned by test: the gate tests `FORBIDDEN_ANSWERS` **before** the answer set, so a surface whose answers were rewritten to contain `best_so_far` still refuses it — the pair is a property of the class, not of the mapping it holds.
