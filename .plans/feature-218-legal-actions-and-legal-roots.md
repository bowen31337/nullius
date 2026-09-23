# Feature 218 — `legal_actions()` and `legal_roots()`, the two remaining verbs of §11's read side

**app_spec.xml, "Exploration Policy Runtime", feature 218** (`plugin="policy-runtime"`, `depends_on=217`):
*System exposes legal_actions which returns open frontier nodes plus legal_roots which returns available research themes.*

Authoritative spec: docs/nullius-tech-architecture.md §593–594, the third and fourth lines of §11's identical `question.*` interface:

> ```python
> question.legal_actions()   -> list[node_id]
> question.legal_roots()     -> list[node_id]
> ```

and its mirror in docs/alpha-engine-prd.md §419–420, which carries the one comment that fixes the semantics:

> ```python
> question.legal_actions()   -> list[node_id]                # roots + open frontiers
> question.legal_roots()     -> list[node_id]
> ```

Feature 217 shipped the first line of that listing (`observed()`), 219 the fourth-from-… (`meta()`), 220 (`probe_batch`), 221 (`budget_remaining`) and 222 (`commit`). **218 is the pair §11 lists immediately under `observed()`, and it is the only gap left in the listing.** The member's own `CANONICAL_POLICY` (`tests/test_admission.py:68`) is written against them already and cannot be admitted-and-described without them:

```python
(root,) = question.legal_roots()
question.probe_batch([root])
current = root
while True:
    frontier = list(question.legal_actions(current))
    question.probe_batch(frontier)
    if not frontier:
        return question.commit(current)
```

## Context — why this feature, and what it is not

Two questions a policy asks *before* it can ask anything else: **where may I start?** and **what may I do from here?** `observed()` (217) cannot answer either — it reports what has already been looked at, and a policy at round 0 holds an empty mapping and no move. 218 is the pair that makes a walk a walk: `legal_roots()` names the nodes a walk may begin from, `legal_actions(node_id)` names the nodes one legal step on from where the policy stands, and the *emptiness of the second* is the "no batch selected" signal PRD §436 makes the termination test.

The feature sentence's two halves are one act seen from two sides, and PRD §215 says so in four words — *"Root = a fresh research theme (§9)"*, restated as the table row *"Root | Research theme (§9.3)"* (§699). So `legal_roots()` returning *node ids* (§11's `list[node_id]`, and the only thing `probe_batch([root])` can accept) **is** "available research themes": each root is a theme's opening node, and the id is how a node is addressed. The two readings are not in tension; the id is the spelling, the theme is the meaning.

**What it is not:**

| feature | answers | the seam | state consulted |
|---|---|---|---|
| 217 `observed` | *what have I seen?* | the question's reveal set | the reveal set |
| **218 `legal_actions` / `legal_roots`** | ***where may I move?*** | **the tree's edges** | **none — the tree alone** |
| 219 `meta` | *what is this cell's structure?* | the tree's edges + the node's record | none — the tree alone |
| 220 `probe_batch` | *show me these* | the reveal set (write) | the reveal set |
| 221 `budget_remaining` | *may I afford it?* | the account | the account |
| 222 `commit` | *here is my answer* | the episode | the episode |

* it is **not 219's meta** — `meta` reports where a cell *is* (branch, depth, parent, theme_root); 218 reports what a *move* is. `meta(root).theme_root` names the theme a root is planted in; `legal_roots()` names the root. Different questions, different verbs, deliberately both answered for unrevealed nodes (see decision 3);
* it is **not a component** — no store, no deployment state, no configuration. A pure function of the tree, reached directly from the member exactly as `cell_meta` (219), `prefix_view` (223), `policy_surface` (224), `read_beta` (226), `plan_grid` (229), `screen_policy` (230/231) and `episode_commit` (222) are;
* it is **not feature 241's** legal-theme set. *Which* themes may exist is `discovery.themes`' committed config, and both `discovery/themes.py:83` and `signal_agent/_guidance.py:93` already name 218 as a *different* act: *"feature 218's `legal_roots()` is the policy-facing runtime's accessor — the themes a policy may open a walk in — and answering a policy is a different act from refusing a planner."* Nothing here restates that ceiling;
* it is **not framework 239's expansion** — nothing here generates a child. `legal_actions` reads the edges the tree already recorded (app_spec.xml:885: *"a stored tree reveals only recorded children"*).

## Design decisions

### 1. `legal_actions(node_id)` answers the node's **children** — the edges, one legal step

The tree records `(node_id, parent_id, depth, payload)`. A node's legal moves are precisely the nodes that name it as their parent: one edge, no invention, and the whole set of them is what a policy may select as its next batch. That is the sibling pool's law read on this pool's structure — `world.legal_moves(node_id)` returns *"the neighbours of `node_id` — one legal step"* — so the two pools answer the same *kind* of thing: the moves available from where you stand.

**A node with no recorded children answers `[]`, and that is the load-bearing answer, not a gap.** PRD §436's *"must terminate when no batch is selected"* and feature 3/242's *"the policy has selected no batch"* are exactly this empty list; a leaf is a position with no move, and a verb that refused there would leave a policy unable to distinguish *nowhere left to go* from *you asked wrongly*. Terminating is a decision, and this verb hands the policy the fact it decides on.

### 2. `legal_actions(None)` answers the **roots** — where a walk may begin

`None` means *from the start*. Both §11 listings spell the verb `legal_actions()` with no argument, and PRD §419's comment is the reading: **"roots + open frontiers"** — the roots when no position is named, the open frontier when one is. So the no-arg call and `legal_roots()` agree, `legal_actions(node_id) == legal_roots()` for `node_id=None`, and one spelling of "the nodes a walk may begin from" serves both verbs.

This is the one place the pair deliberately diverges from the bootstrap pool's *shape*, and it is a fact about the campaign pool rather than a drift:

* `world.legal_moves(None)` answers the root's *neighbours*, because a bootstrap lattice has **one** canonical root that is not itself a choice — the walk's start is fixed, so the only moves "from the start" are its neighbours;
* a themed campaign has **several** roots, one per theme planted (§11.1's `plan.theme_roots`, PRD §215), and *which theme to open* **is** the policy's first action. The campaign's "moves from the start" are therefore the roots themselves.

Every *positional* call — every call the member's own `CANONICAL_POLICY` and the bootstrap pool's `_greedy_walk` actually make — answers the identical kind of thing on both pools. The divergence is confined to the no-argument form, which is the form whose meaning is a choice of starting point, and it is documented rather than glossed.

### 3. The answer is a **pure function of the tree** — the reveal set is never consulted

`legal_actions` and `legal_roots` return node ids and nothing else. An id carries no reading: no score, no `is_null` (cq-8), no absolute target, and no unrevealed node's *value*. What it does carry is **structure** — that a node exists and sits one step on — which is the same class of fact feature 219 established is deliberately open: *"structure is the tree's shape, not the reading §10.2's barrier withholds — scores are"*, and the sibling pool refuses only a node *"outside the lattice"*, not an unrevealed one.

Two independent reasons this must not depend on the reveal set:

* **the identical-interface law** — `BootstrapQuestion.legal_actions` reads `world.legal_moves(node_id)` and never consults `_revealed`. A reveal-dependent campaign answer would break portability in the *walk*: a policy that re-read its frontier, stable on bootstrap, would see it collapse to `[]` on a campaign tree and terminate early. The statefulness of the interface lives in `observed()`, and putting it in a second verb is how the two pools stop being one interface;
* **purity** — this member states it as a property of the question (*"every other answer is a pure function of `(tree, node_id)`"*), and it is what makes a frontier reproducible across replays of one tree.

Neither verb grows the reveal set: reading where you may go is not going. `PolicyQuestion.__slots__` is unchanged — the question's private state is still exactly the reveal set, which `test_question.py` pins as *"the whole of the question's private state"*.

### 4. `legal_roots()` is the tree's **parentless nodes** — and the themes are what those roots *are*

The roots are the nodes whose `parent_id` is `None` — the same test `discovery.manifest` uses for a branch (*"A branch is a root (`parent_id IS NULL`)"*). Ascending by node id, so a policy that enumerates without sorting sees a deterministic order (§12's ordering rule, restated for a search frontier, as `observed()` and `legal_moves` both do).

The set is derived from `parent_id` and **not** from `meta().theme_root`, deliberately. Two parentless nodes in one theme are two roots a policy may start from; collapsing them to "one node per theme" would answer a question about the *theme set* through an accessor whose subject is *nodes*, and would silently drop a legal starting point. The themes a root belongs to are then read where §634 confines them — `meta(root).theme_root` — so 218 answers "where may I start?" and 219 answers "what is that place?", and the legal-theme ceiling stays feature 241's.

### 5. A free function per verb, and a thin delegation from the question

`frontier.py` holds `legal_roots(tree)` and `legal_actions(tree, node_id=None)`; `PolicyQuestion.legal_roots()` and `.legal_actions(node_id=None)` delegate. This is exactly `meta.py`'s split (`cell_meta` behind `PolicyQuestion.meta`) and 224's (`policy_surface` behind the surface): the question is the *runtime's* object, and a report, a test or a later feature in this category that wants the frontier over a tree should read it through one derivation rather than reconstruct the walk. The free functions carry §11's own vocabulary because `discovery.planner` and `signal_agent._guidance` already refer to `legal_roots` by that name as *"feature 218's own vocabulary"*.

The module consults nothing but the tree it is handed — no store, no clock, no environment, no reveal set — so it is import-cheap and `__init__.py` keeps its relative-import discipline.

### 6. Seam discipline: duck-typed reads, this member's vocabulary

The module loader imports the package under a synthetic name and re-executes it, so the tree `create_app()` hands out may be a *second* `CampaignTree` class object and `isinstance` would refuse the very tree composition produces ([[module-loader-register-only-in-init]]). `frontier.py` therefore validates **what it reads** — `tree.nodes`, `node.node_id`, `node.parent_id`, `tree.node(id)` — and translates every failure into `PolicyRuntimeError`'s subclasses, so a caller's own `except PolicyRuntimeError` catches every way a frontier read can fail ([[error-vocabulary-at-member-seams]]):

* a node id the tree does not hold → **`PolicyAddressError`**, raised by the tree's own `node()` seam and **passed through unchanged**, so the sentence naming the node and the tree survives rather than being re-spelled (the rule `meta.py:_addressed_node` states);
* a value that is not a node id at all — a number, an empty or whitespace string — → `PolicyAddressError`, in `meta()`'s exact vocabulary: *"a value that is not an id names none"*;
* a tree whose `nodes` cannot be read, whose nodes carry no usable `node_id`, or whose `parent_id` is neither absent nor a string → `PolicyTreeError`, naming what arrived;
* **a broken edge, in either of the two ways an edge can fail to be one** → `PolicyTreeError`. Both were found by an adversarial probe *after* a green run, and neither is a refusal the first implementation had:
  * **dangling** — a node naming a parent the tree does not hold. It is neither a root (its parent is not absent) nor any position's legal move (no node names *it*), so both verbs omitted it **in silence**, leaving a policy unable to tell *I cannot walk this tree* from *there is no move there*;
  * **self-parenting** — a node naming *its own* id. Worse rather than gentler, and this is the one that would look like *success*: its parent **is** present, so it is not a root, and it appears in exactly one frontier — its own. `legal_actions("a")` answered `["a"]`, handing a policy a legal step from a position to the same position. That step advances nothing, and a walk taking it loops forever on one node while its frontier **still reads as non-empty** — the one failure a termination test cannot catch, because the frontier never empties.

  Feature 217's constructor refuses a dangling reference at build time, but a duck-typed or composed tree reaches these verbs without passing that validation, so the check lives here too. The cycle half is deliberately the same law `meta._walk_to_origin` (219) enforces (*"its parent chain revisits 'a'"*), so the member's two accessors cannot disagree about whether such a tree is readable. **General lesson: a duck-typed seam that reads a structure must re-validate what the real constructor guarantees, because composition bypasses the constructor.**

**No new error class.** 218 refuses nothing 217's vocabulary cannot already name — a missing node is an address failure and a malformed tree is a tree failure — so `errors.py` is untouched and its count stays as 224 left it (*"the eighth subclass and the only addition"*).

### 7. No new component, no shared edit

The member's registered surface stays 217's single `policy-runtime` campaign tree component. Nothing here needs a store or deployment state, so no `@register` and no central registry, router, entry-points table, app factory, middleware, settings or migration is touched. The only file outside the member is the member's own app-namespace seat, and there the change is a docstring paragraph — the established pattern for every feature in this category reached directly from the member rather than composed.

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/frontier.py` | **new** — `legal_roots`, `legal_actions`, the seam helpers |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | `from .frontier import legal_actions, legal_roots`; two delegating methods on `PolicyQuestion`; `__all__`; module-docstring paragraph |
| `packages/policy-runtime/tests/test_frontier.py` | **new** — the feature's suite |
| `src/app/modules/policy-runtime/__init__.py` | seat docstring paragraph (reached directly, like 219/220/221/222/223/224/225/229/230/231) |

Deliberately **unchanged**: `prefix.py` (feature 223's law — `test_prefix.py:193` asserts the view answers neither `legal_actions` nor `meta`, and the frontier belongs to the question, not to the object the policy holds), `errors.py`, `meta.py`, and every existing test.

No new `@register` component; no central registry, router, app factory, middleware, settings or migration edited; the member imports no sibling member — `collections.abc`/`typing` and `.errors` only.

## Verification

* member suite `packages/policy-runtime/tests`: **502 → 548 passed** (no existing test edited; `test_frontier.py` contributes **46**).
* repo acceptance gate `uv run pytest` (`testpaths=tests`): **1060 passed, EXIT=0** — it does not collect a member's own suite ([[acceptance-gate-ignores-member-suites]]), so both were run.
* `ruff check --no-cache` on the changed files, compared against the **same 19-finding HEAD baseline** measured before the edit (I001, C408 at `test_tree.py:76`, N999 on the hyphenated seat module) — compared by stashing and diffing the full output, never by eyeballing ([[repo-lint-is-red-on-main]]).
* the claims tested beyond the obvious: the walk **terminates** (a leaf answers `[]` and the policy commits on it); the frontier is **stable across a probe** (the portability property that keeps one policy running on both pools); the answer is **unchanged by the reveal set** (two questions over one tree, one revealed and one not, answer identical frontiers); neither verb **grows** the reveal set; the two verbs **compose with 217/220/222** into a terminating walk over a themed, multi-root tree; and the free functions and the methods answer the **same** values (the one-derivation claim).
