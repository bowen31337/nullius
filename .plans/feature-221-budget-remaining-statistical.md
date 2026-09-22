# Feature 221 — `budget_remaining()`, statistical and not compute

**app_spec.xml, "Exploration Policy Runtime", feature 221** (`plugin="policy-runtime"`, `depends_on=217`):
*System exposes budget_remaining, which returns statistical budget rather than compute budget.*

Authoritative spec: docs/nullius-tech-architecture.md §597, the second read verb in the identical `question.*` interface:

> `question.budget_remaining()  # statistical, not compute`

repeated verbatim in docs/alpha-engine-prd.md §422's §C4 listing, and made a *discriminant* rather than a footnote by two documents that state the two resources apart:

* prd §4.1.1 (line 123) — *"**Null nodes cost compute, not statistical power.** A null node's signal was never compared to real forward returns, so it consumes agent calls and CPU but **not degrees of freedom**. It must not count toward `K` in the deflation term, and must not debit epoch usage in the trial ledger. Since compute is cheap and degrees of freedom are the binding resource (§1.3)…"*;
* prd §705's replacement table — `β₁ N (agent calls)` → `β₁ · trials charged (statistical budget)` — with §315's reason: *"Backtests are embarrassingly parallel and cheap. Parallelism is not the bottleneck. Data is."*

and the architecture document's §8 `trial_ledger` DDL, which carries the discriminant on the row itself:

> `charges_budget BOOLEAN NOT NULL  -- FALSE for null nodes`
> `charge_units REAL NOT NULL       -- 1.0 default; CV folds may cost more`

## Context — why this feature, and what it is not

Every other feature in this category is a *refusal*. 221 is the one that **answers**: §11's interface has exactly two read verbs a policy's own mandate needs — `observed()`, which 217 built, and `budget_remaining()`, which is this one — and the second is the one a policy terminates on. The feature's whole content is therefore not "add a method" but *which quantity the method returns*, and the system already meters two things it calls budgets:

| | the statistical budget | the compute budget |
|---|---|---|
| what it is | degrees of freedom — *"hypotheses I implicitly tested"* (prd §363) | the machine |
| the column | §8's `charges_budget` (feature 90's directive) | §8's `charge_units` (feature 89) |
| the law | §10.3's score, `− β₁ · trials_charged`; §345's null bar `≈ √(2 ln K)` | §5.2's `Limits(cpu_s=30, mem_mb=2048, pids=32)` (features 162/163) |
| other meters | feature 93's `K_effective` per epoch | the agent's calls, §10.1's fixed round count `K2` |
| binding? | **yes** — *"degrees of freedom are the binding resource"* (prd §123) | no — *"compute is cheap"* |

The two are already separated in this repo's own words, in the member that owns the other side of the column: `packages/bootstrap/src/bootstrap/_trial.py` says of the row it writes, *"It carries no `charge_units` — §8's unit prices **compute** ('1.0 default; CV folds may cost more'), §10.6's zero cost is **statistical**, and the spec keeps the two facts apart on the very row that names them."*

**What it is not:**

* it is not a second `K_effective` — feature 93's count is keyed *by epoch* and sums repeats within one on purpose (its own `derive_k_effective` collapses repeated `(epoch, charges_budget)` pairs); this account is not keyed by epoch at all, and its spend is a flat count of charged trials. Different key, different law, different member (the ledger's vs. this one's), and neither imports the other;
* it is not feature 224's surface — 224 refuses the **name** `budget_spent` at the object a policy is handed; this builds the **arithmetic** underneath it, and keeps 224's law structurally one seam below (a reading holds one float, so there is no `spent` to walk to);
* it is not feature 162/163 — those meter the machine, and this feature's sentence is precisely that this verb does not report theirs;
* it is not feature 226's fixed scalar — beta is *fixed by the deployment*; a budget reading is a *measurement of a spend that keeps happening*, so the account is read live and only a *reading already taken* is immovable;
* it is not a component — no store, no deployment state, no `@register`; a pure function of a stated allowance and the rows it was handed, reached directly from the member exactly as `read_beta` (226), `prefix_view` (223), `policy_surface` (224), `episode_commit` (222), `plan_grid` (229) and `screen_policy` (230/231) are.

## Design decisions

### 1. The spend is a count of directives, never a sum of weights — *this is the feature*

`BudgetAccount.charged` is `sum(1 for charge in charges if charge)`. §8's `charge_units` is **never read**, and the module says so in its own docstring with the ledger member's words (*"prices compute"*). This is the one arithmetic that must not drift, for three reasons that all point the same way:

* a five-fold cross-validation is **one hypothesis** tested against the same forward returns — feature 93 counts *rows* for exactly this reason, and a weighted sum would make the budget a function of the evaluation's implementation rather than of the claim being tested;
* summing units would be the compute budget arriving through the arithmetic rather than through the verb — the same substitution prd §705 records the system as having already made once;
* the count is what `β₁ · trials_charged` multiplies (prd §320), so a sum here would put a second, differently-weighted `K` beside the deflated one.

Pinned three ways: five evaluations of which two charged spend exactly two; a single evaluation charged `charge_units=12.0` spends one; and the arithmetic is *asserted not to equal* the unit sum in either direction.

### 2. A row that cannot say is refused — and `charge_units`-without-`charges_budget` is refused *by name*

The tempting design is `getattr(row, "charges_budget", False)` — a row that cannot say is treated as not charging. That is refused because it moves the count in the one direction an honest counter must never move by accident: it **understates** the spend. So a row missing the field raises, a row carrying a non-bool raises, and `None` raises (present-but-not-a-bool is a different failure from absent, and both are named).

The case with its own message is the realistic defeat: a caller holding §8's `charge_units` — a *compute* measurement — and asking for a statistical spend. That refusal quotes `_UNIT_FIELD`, the ledger's "prices compute", and prd §705, so the caller learns what it actually handed over.

The SQLite spelling is read: the member's own memory records that a `BOOLEAN` column returns `int` 0/1 ([[sqlite-dbapi-affinity-traps]]), and `validated_charges_budget` on the ledger's side of this same column accepts exactly that, so `0`/`1` are coerced while `2`, `-1`, `"true"` and `3.0` are refused. `bool` is tested *first*, because `True` is an `int` and the two must not be indistinguishable at the one seam where the difference is the whole law.

### 3. The account is the runtime's; the reading is the policy's — 224's law, one seam below

224 refuses the *name* `budget_spent` at the surface, and its module records why: *"`budget_remaining()` is offered; `budget_spent` — what it has already cost — is not."* An account that held the allowance and the charges would answer `spent` the instant a policy could reach it, so what `question.budget_remaining()` returns is a **`StatisticalBudget`** — one float — and never the account. The withheld number is unreachable because there is no attribute to find, which is the same **structural** argument 223 makes (absent rather than filtered) applied to the budget. `__slots__ = ()` is the mechanism, and `allowance`, `charges`, `spent`, `charged`, `evaluations` and `account` are all pinned absent.

### 4. `StatisticalBudget` is a `float` subclass, and the type is the denomination

The construction feature 226 chose for `EpisodeBeta`, for the same reason: the figure is compared against a threshold in authored policy code (`while question.budget_remaining() > 0`), printed, JSON-serialized, sorted and added to, and a wrapper would put an unwrap at every one of those seams. What the type adds is the one thing a bare float cannot state and the whole of what this feature is about — *this number is degrees of freedom*. It round-trips `copy`/`deepcopy`/`pickle` to the same type (a bare float would lose the denomination across a replay worker).

### 5. The reading is **live**; a reading already taken is **not** — and the two are not in tension

This is the one place the implementation was corrected by a test rather than by reasoning, and it is worth recording. The first cut had the question hold a pre-read `StatisticalBudget`; the replay-in-miniature test — reveal one cell per round until the budget is spent — ran its loop guard to exhaustion instead of stopping at two, because a frozen figure cannot tell a policy when to stop. The verb exists for exactly that loop (§11: the policy *"must terminate when no batch is selected"*).

So the question holds the **account** and reads `remaining` afresh on every call, and `StatisticalBudget` refuses every reassignment path of a reading already taken. The two rules are two halves of one fact — **the budget changes; a reading of it does not** — and `_Recharging` in the suite is the smallest object with the account's shape, pinning both at once (the figure falls from 4 to 2 across two charges while the held reading stays 4, and the two are different objects). 226's fixed scalar is the *contrast*, not the precedent: beta is fixed by the deployment, this is a measurement.

### 6. A bare number is refused where the question's budget belongs

`policy_question(tree, 5.0)` raises. `5.0` names no resource, and *"is this five trials or five seconds?"* is the question the feature exists to answer — so the substitution is refused at the seam rather than wrapped through `budget_account()` (which would make the bare float *look like* a budget). The seam is duck-typed — `isinstance` would refuse the very account the module loader re-executes under a synthetic name — and reads `remaining`, a **property** rather than a verb, which is why the check is a read and not `callable()`.

### 7. The account is a frozen *value*; a replay's live spend is a duck-typed account

`BudgetAccount` is a frozen dataclass with `__post_init__` validation, so an account that exists is one the doctrine could have produced, and two accounts of one campaign's charges are **equal values** — §10.1's determinism requirement, restated for the budget. It deliberately does not mutate: a mutable account would make a reading depend on when it was taken, in a way nothing could reproduce. The live case (a replay recording charges as rounds complete) is served by decision 5's duck-typed seam rather than by making this value mutable, which is the split the question already draws between the tree it fronts and the reveal set it owns.

### 8. Nothing is read off a row but the directive

The account keeps one bool per row: no epoch, no node, no units, no timestamp. The epoch is feature 93's key, the unit is feature 89's cost, the node is the tree's — copying any of them here would be a second ledger free to drift from the first. Pinned by equality: a row carrying the whole of §8 produces an account equal to one carrying a bare `charges_budget`. The row itself is not held either (mutating it after the read moves nothing).

### 9. `UNBOUNDED_BUDGET` for an unstated ceiling, not `0` and not a refusal

`inf`, and the reading is not this module's invention: `BootstrapQuestion.budget_remaining` answers exactly this for §10.6's *"zero statistical-budget cost"* (its own docstring: *"the whole budget, always"*), so feature 184's identical-interface law holds for this verb across both pools. `0` would be a lie in the dangerous direction — a policy would stop before spending anything on a deployment that stated no ceiling — and refusing would make a budgetless question unconstructible, which is what every existing call site of feature 217's factory constructs. `0` *stated* is a different fact and is legal (exhausted immediately).

### 10. A new error class, and only one

`PolicyBudgetError` is the tenth subclass. Unlike 186's "no fourth error class" case ([[feature-186-world-census]]), no existing class covers this contract: `BetaFixedError` is the nearest sibling — both guard a number read during an episode and both refuse reassignment — but beta is *fixed* while a budget reading is a *measurement*, so the refusal here is against a value that names no budget rather than against a value that moved after it was set. `PolicyAnswerSurfaceError` is the other candidate and is wrong for the other reason: it is the one class that doubles `AttributeError`, and a budget that names no number is not a surface refusing a name. It is kept apart from both in the module docstring, and it stays a `PolicyRuntimeError` so the single-`except` discipline holds. errors.py's count ("nine subclasses") is updated to ten.

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/budget.py` | **new** — `StatisticalBudget`, `BudgetAccount`, `budget_account`, `STATISTICAL_UNIT`, `COMPUTE_UNITS`, `UNBOUNDED_BUDGET` |
| `packages/policy-runtime/src/policy_runtime/errors.py` | `PolicyBudgetError` + module-docstring paragraph (nine → ten) |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | exports + docstring paragraph; `PolicyQuestion.__slots__` gains `_budget`; `PolicyQuestion.budget_remaining()`; `__init__`/`policy_question` take an optional `budget` |
| `packages/policy-runtime/tests/test_budget.py` | **new** — 50 tests |
| `src/app/modules/policy-runtime/__init__.py` | seat docstring paragraph (reached directly, like 222/223/224/225/226/229/230/231) |

No new `@register` component; no central registry, router, app factory, middleware, settings or migration edited; no change to 217/223/224/225/226 (all additive — the new parameter is optional and defaults to `None`). The member imports no sibling member: `math`, `numbers`, `collections.abc`, `dataclasses` and `.errors` only.

## Verification

* member suite `packages/policy-runtime/tests`: **395 → 445 passed** (no existing test edited; `test_budget.py` contributes **50**).
* repo acceptance gate `uv run pytest` (`testpaths=tests`): **1060 passed**, unchanged — it does not collect a member's own suite ([[acceptance-gate-ignores-member-suites]]), so both were run. The worktree needed `uv sync --all-packages` with `UV_CACHE_DIR` inside the worktree first ([[repo-test-env-gaps]], [[uv-cache-dir-sandbox-workaround]]).
* `ruff check --no-cache`: `budget.py`, `errors.py`, `test_budget.py` **clean**. The member `__init__.py` reports **exactly the 5 findings HEAD reports** (I001:217, RUF022:307, UP037:463/560/626 — the same categories at shifted line numbers), and the seat file's only finding is `N999`, which every dashed seat directory in `src/app/modules/` carries ([[repo-lint-is-red-on-main]]). The one finding introduced during the work — an unused `noqa: BLE001` — was removed rather than left.
* An adversarial edge-case pass — run after the first commit, against the *spec* rather than the code — found **three seams where a bare exception escaped the member**, the error-vocabulary leak a member seam must not have ([[error-vocabulary-at-member-seams]]): `float(10**400)` raises `OverflowError` out of both the reading and the allowance (a `numbers.Real` check is not the same guarantee as "a float can carry it"); a charge row whose `charges_budget` is a *property that raises* leaked its own exception from the factory; and the live account read inside `budget_remaining()` could leak one mid-episode, where it would reach authored policy code naming no contract that the policy's own `except PolicyRuntimeError` could catch. All three are now translated (the third passing an already-`PolicyBudgetError` through unchanged, so a specific message survives), and each is pinned by a test. Feature 226's `read_beta` performs the same `OverflowError` translation at its own seam — the sibling precedent was checked before writing it. An unused `noqa: BLE001` I first added for the row read was removed by restructuring the two attribute reads under one handler, rather than suppressed.
* The three design corrections were all *test-found*, and are recorded above rather than smoothed over: the frozen reading (decision 5), the refusal message for a bare number (decision 6), and the three escapes above.
* **All 16 member suites run**, not just this one — the repo gate collects only `tests/` ([[acceptance-gate-ignores-member-suites]]), so a cross-member pin would otherwise go unchecked. Fifteen are green (policy-runtime 445, sandbox 1264, nulloracle 1386, canary 800, ingest 764, discovery 681, providers 582, signal-agent 554, bootstrap 520, cost-model 502, ledger 475, artifacts 466, snapshot 400, tripwires 394, universe 318). The evaluator suite has **4 pre-existing failures** in `test_debit.py` (a `TrialRecordError` on `epoch_id`, feature 88/105's column, nothing to do with this feature): verified pre-existing by checking out `7cd0dcf` — the commit before this work — into a scratch worktree and reproducing the same 4 failures there. Not touched, not in this footprint.
* The cross-member pin that *does* cover this feature was checked rather than assumed: `packages/discovery/tests/test_planner.py::test_the_episode_surface_covers_the_question_api_it_projects` walks `PolicyQuestion`'s public reads and asserts each is in the planning boundary's `EPISODE_SURFACE`. `budget_remaining` is already a member of that set, so the pin passes — and the walk independently confirms the new method is visible on the class (reads: `budget_remaining`, `observed`, `reveal`, `reveal_many`).
* Composition with feature 224 verified rather than assumed: a policy is handed a **surface**, not the question, and 224 builds a fresh one per round — so the live reading reaches a policy (round 1 reads 4.0, round 2 reads 2.0 after two charges) while a *held* surface keeps its snapshot (still 4.0) and `best_so_far`/`budget_spent` stay unreachable beside it. Had surfaces been built once per episode, the live reading would have been dead code in practice; it is not.
