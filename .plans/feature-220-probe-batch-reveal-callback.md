# Feature 220 — `probe_batch(cells, on_reveal=...)`, the batch reveal

**app_spec.xml, "Exploration Policy Runtime", feature 220** (`plugin="policy-runtime"`, `depends_on=217`):

> *System exposes probe_batch accepting selected cells with a reveal callback, which returns revealed observations.*

docs/nullius-tech-architecture.md §596 and prd §421 both spell it in the identical `question.*` interface:

```python
question.probe_batch(cells, on_reveal=...)
```

## What exists today

The category is landed through 217 (observed), 221 (budget), 222 (commit), 223 (prefix view), 224 (surface), 225 (guard), 226–228 (beta/schedule/families), 229 (plan_grid), 230/231 (admission). **218 (frontier) and 219 (meta) are not yet built**, and there is **no `probe_batch` on `PolicyQuestion`** — a fact the member's own text records as pending: `commit.py:16` says *"the frontier and meta (218/219) shape it, probe_batch (220) spends budget to extend it"*, and the seat lists *"218's frontier, 219's meta, 220's probe, 222's commit"* as the features that build on the question seam.

What 217 did leave behind is the **write side under the wrong name**:

- `PolicyQuestion.reveal(node_id)` — one cell, records it, returns its observation;
- `PolicyQuestion.reveal_many(node_ids)` — a batch, returns the newly-revealed observations;
- the observation construction inlined in `observed()` as `PolicyObservation.from_node(self._tree.node(node_id))`.

`reveal_many` is already a batch reveal in everything but name: idempotent on the revealed set, all-or-nothing (it validates every cell against the tree *before* revealing any, so a bad cell refuses whole), returning `{node_id: Observation}` for the newly-revealed cells only. **But it has no `on_reveal` callback, no documented ordering guarantee, and is not the name the spec, the docs and four sibling members use.**

The name is not cosmetic. Four places already spell `question.probe_batch(...)` in code that is *live today* and fails against a `PolicyQuestion`:

- `packages/policy-runtime/tests/test_admission.py:69,73` — the live question fed to the canonical policy;
- `packages/policy-runtime/tests/test_admission.py:183,382` and `test_learned.py:349` — the canonical policy source text, screened by the admission gate;
- `packages/bootstrap/src/bootstrap/_trial.py:429–434` — feature 185's trial recorder duck-types on a **callable `probe_batch`** and refuses an object without one;
- `packages/discovery/src/discovery/planner.py:202` — feature 233's `EPISODE_SURFACE` lists `probe_batch` as a §11 reading verb, and `packages/discovery/tests/test_planner.py:828` walks `dir(PolicyQuestion)` asserting **every public method is a name the planning boundary refuses**.

So `probe_batch` is the identical-interface seam: one policy written once against §11 must run unmodified across both pools, and today the financial-campaign side of that seam is spelled `reveal_many`.

## Design

### 1. `probe_batch(cells, on_reveal=None)` — the spec's verb, on `PolicyQuestion`

One new method in `packages/policy-runtime/src/policy_runtime/__init__.py`, the batch reveal with the callback:

```python
def probe_batch(self, cells, on_reveal=None) -> dict[str, PolicyObservation]:
```

Semantics, each pinned by the sentence and by feature 184's shipped precedent (`bootstrap._question.BootstrapQuestion.probe_batch`, lines 423–455):

| property | the law |
|---|---|
| **arguments** | `cells` is an iterable of node ids; `on_reveal` is an optional callable taking one node id. Keyword-or-positional, matching §11's `probe_batch(cells, on_reveal=...)` and bootstrap's signature exactly. |
| **dedup + order** | `sorted(set(cells))` — a duplicate in the batch is one cell, and the whole call runs in ascending node-id order, the ordering rule docs §12 states for a search frontier. |
| **all-or-nothing** | every cell is validated against the tree *before* any is revealed (`self._tree.node(candidate)`), so a batch naming one cell the tree does not hold is refused with `PolicyAddressError` naming the node and the tree, and **reveals none of them** — the reveal set is never left half-applied. |
| **returns the new cells** | `{node_id: PolicyObservation}` for the cells revealed *by this call* — an already-revealed cell is not re-returned; the call is idempotent on the revealed set. |
| **the callback** | `on_reveal(node_id)` is called **once per newly revealed cell**, in the same ascending order, and never for a cell the question already held. `None` (the default) means no hook — a policy that wants only the return value passes nothing. |
| **order of acts** | reveal the cells, *then* fire the callbacks, *then* return the mapping — so a hook that reads `question.observed()` inside `on_reveal` sees the batch already applied, and a hook that raises leaves the reveal set correct rather than half-written. |

**A non-callable `on_reveal` is refused up front** — before any cell is revealed — in the member's own vocabulary rather than as a bare `TypeError` escaping from inside the loop. This is the error-vocabulary discipline every seam in this member keeps ([[error-vocabulary-at-member-seams]]): the caller's `except PolicyRuntimeError` must catch it.

### 2. `reveal_many` becomes a thin delegation, not a second implementation

`reveal_many(node_ids)` is **kept and re-pointed at `probe_batch`** (`return self.probe_batch(node_ids)`), so:

- the two batch verbs cannot drift — one implementation, shared, exactly as `observed()` and `probe_batch` share one spelling of "a node's observation";
- existing callers (`test_question.py`, `test_observed.py`, `test_prefix.py`, feature 233's `EPISODE_SURFACE`) keep working unchanged;
- the member stops having two names for one act with subtly different guarantees.

`reveal` (single cell) is unchanged: it is the one-cell verb.

### 3. `observed()` and `probe_batch()` share one `_observe`

Today the observation construction is inlined in `observed()`. Factoring it into `PolicyQuestion._observe(node_id)` — the spelling bootstrap's own question already uses (`_question.py:341`) — means an observation made by a sweep and one made by a single reveal cannot drift. Behaviour-neutral: same `PolicyObservation.from_node(self._tree.node(node_id))`, same ordering.

### 4. One test file, `packages/policy-runtime/tests/test_probe.py`

New file (the suite's file-per-feature convention: `test_observed.py` 217, `test_prefix.py` 223, `test_surface.py` 224, `test_commit.py` 222, `test_budget.py` 221). Header docstring in the member's house style; pins at minimum:

- the batch is revealed and `{node_id: Observation}` returned, ascending, one observation per cell;
- idempotence: re-probing returns `{}` and the callback does not re-fire;
- `on_reveal` fires once per **newly** revealed cell, in ascending order, and not at all for a cell already held;
- the callback receives the node id, and a hook reading `observed()` inside the hook sees the applied batch;
- all-or-nothing: a batch naming an unknown cell refuses with `PolicyAddressError` and leaves `revealed` empty and `observed()` unchanged;
- dedup: `["n2","n1","n2"]` reveals two cells and fires two callbacks;
- `on_reveal=None` (default and explicit) is silent;
- a non-callable `on_reveal` is refused *before* any cell is revealed, in the member's vocabulary;
- `probe_batch` and `reveal_many` agree cell-for-cell and observation-for-observation;
- the returned observations are equal to the ones `observed()` reports, to the last field;
- the reveal set is still prefix-only after a probe (nothing outside the tree is reachable).

### 5. Docstring and seat updates

- `packages/policy-runtime/src/policy_runtime/__init__.py` — module docstring gains a feature 220 paragraph; `__all__` unchanged (no new public symbol — the method lives on the class).
- `src/app/modules/policy-runtime/__init__.py` — a paragraph in the seat's "reached directly, no seat" list, matching 221–226: `probe_batch` belongs to the round a replay runs, not to the composed application.
- `packages/policy-runtime/tests/test_admission.py` — the live-question walk at lines 68–73 calls `question.probe_batch` against a real `PolicyQuestion`; **verify it now passes** rather than editing it.
- `packages/discovery/src/discovery/planner.py` — **no edit**: `probe_batch` is already in `EPISODE_SURFACE`, so the cross-member pin should stay green. Verified by running discovery's suite.

### 6. Not touched (explicitly)

- **No new error class.** A batch naming a cell outside the tree is the tree's own `PolicyAddressError`, the class `reveal`/`reveal_many` already refuse through — one contract read at three verbs. The `on_reveal` refusal reuses `PolicyTreeError`, the answer surface's own contract.
- **No component, no seat, no `@register`.** Feature 220 is a method on the question, like `reveal_many`; there is nothing to compose.
- **No new module** — the verb lands on `PolicyQuestion` in `__init__.py`, where `observed`/`reveal`/`reveal_many`/`budget_remaining` already are.
- **No budget arithmetic.** §11's `probe_batch` is the batch verb; feature 221's `budget_remaining` already reports the statistical budget, and `commit.py`'s own text says probe_batch *"spends budget to extend"* the prefix — the spending is the caller's accounting (feature 185's `charges_budget` row), not this verb's. Nothing is decremented here.
- **No central registry, router, app factory, middleware, settings or migration edit.**
- No member imports a sibling: the member stays stdlib-only + `app.module_loader`.

## Verification plan

1. `uv run pytest packages/policy-runtime/tests -q` — baseline **445 passed** (measured this session); expect 445 + the new tests, with **no existing test edited**.
2. `uv run pytest packages/discovery/tests -q` — the cross-member pin (`dir(PolicyQuestion)` ⊆ `EPISODE_SURFACE`) must stay green. Discovery is outside my footprint, so if that pin were to fail I would report it via `mcp__features__feature_report_shared_edit` rather than edit `planner.py` — the analysis says `probe_batch` is already a member.
3. `uv run pytest packages/bootstrap/tests -q` — feature 185's `_probing_question` duck-type and 184's own `probe_batch` tests must stay green.
4. `uv run pytest -q` — the repo acceptance gate, baseline **1060 passed** (measured this session, after `uv sync --all-packages`, [[repo-test-env-gaps]]).
5. `ruff check --no-cache` on every file touched, against the **HEAD baseline**: `__init__.py` reports exactly 5 findings at HEAD (I001:217, RUF022:307, UP037:463/560/626); the new test file must be clean. (No mypy in this environment — [[repo-lint-is-red-on-main]].)

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/__init__.py` | `PolicyQuestion.probe_batch`; `_observe` factor; `reveal_many` → delegation; module docstring paragraph |
| `packages/policy-runtime/tests/test_probe.py` | **new** — feature 220's suite |
| `src/app/modules/policy-runtime/__init__.py` | seat docstring paragraph |
