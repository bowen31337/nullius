# Feature 219 — the meta accessor, structural cell metadata

**app_spec.xml, "Exploration Policy Runtime", feature 219** (`plugin="policy-runtime"`, `depends_on=217`):
*System exposes a meta accessor which returns structural cell metadata including branch, depth, parent and theme_root.*

Authoritative spec: docs/nullius-tech-architecture.md §11, the fourth line of the identical `question.*` interface:

> ```
> question.meta(node_id)     -> CellMeta          # structural: branch, depth, parent, theme_root
> ```

and the two paragraphs that say why it exists — §11.1:

> `theme_root` is exposed in `meta()` because **the overfit signature is only partly family-invariant**.

> A single global threshold averages the inverted features into uselessness, or learns the majority family's sign and actively mis-ranks the minority. The policy writes **family-conditional thresholds routed through the same `_schedule(beta)` dict** …

and line 634, the static check feature 230's admission gate screens for:

> **Static checks before any policy is admitted:** no absolute score constants, no hardcoded node ids, no imports outside the allowlist, `plan_grid` overridden on every path, `commit()` reachable on every terminating path, `theme_root` used only via `meta()`.

prd §195 draws the consequence from the other end:

> `theme_root` is already in `meta()`, so expose it to the policy and let the policy-development agent write family-conditional thresholds routed through the same `_schedule(beta)` dict.

## Context — why this feature, and what it is not

§11's interface has two *read* verbs, and they read two different things. `observed()` reads a cell's **honest in-sample score**, and §10.2's barrier makes that read prefix-only: a policy sees the reading of a cell only after it has revealed it. `meta()` reads a cell's **structure** — where it sits in the tree and which research theme its branch was planted in — and structure is not what the barrier withholds. §11.1 states the requirement directly: `theme_root` is exposed *because* the overfit signature inverts across families, so a policy cannot be written at all without knowing which family a candidate cell belongs to, and a policy is authored *before* the cells it will condition are revealed.

The member's neighbours are already in place and each defers to this one by name:

| feature | what it is | its relation to 219 |
|---|---|---|
| 217 | the tree, the question, `observed()` | 219 is the fourth line of the same §11 interface, over the same tree |
| 228 | family-conditional thresholds | keyed on *"the slug `meta()` exposes"* — it cannot read one until this exists |
| 230 | admission static checks | screens for *"`theme_root` used only via `meta()`"* — this accessor is that sentence's subject |
| 184 | the sibling pool's `CellMeta` | the identical-interface precedent, and the shape this one must match |
| 236 | per-branch difficulty census | groups revealed refinements *by branch* — the grouping `branch` names |

`commit.py:16` already anticipates it in prose — *"the prefix, the frontier and meta (218/219) shape it, probe_batch (220) spends…"*.

**What it is not:**

* it is **not a fourth error vocabulary** — every refusal here is one the member already owns. A node outside the tree is `PolicyAddressError` (the address seam `reveal` and `probe_batch` route through); a corrupt structural record and a parent chain with no origin are `PolicyTreeError`. Both are `PolicyRuntimeError`, so a caller's own `except` catches every way a structural read can fail. Feature 236's "split by repair" rule is what a *new* sentence needs; there is no new sentence here;
* it is **not a component and not a seat** — a component is state a deployment holds, and this accessor closes over no deployment state at all: no store, no file, no clock, no environment. `CAMPAIGN_TREE_COMPONENT` stays the member's single registered surface;
* it is **not a widening of the surface** — `meta` takes an argument, so it is not an *answer name* a deployment may configure (`surface.py` refuses it on that ground), and it stays off the prefix view (223's construction) like every other question verb;
* it is **not 218** — 218 is the *frontier*, the set of expandable cells, a different question over the same tree;
* it does **not** restate feature 241 — *which* themes may exist is committed config, and a legal-set check here would be a second spelling of a config-bound law;
* it does **not** normalise — a slug is carried verbatim, so "Momentum " is reported as "Momentum " rather than approved or rewritten.

## Design decisions

### 1. All four fields derived from the tree or read from the node — never stored beside either

The alternative is a `meta` column, or a side table, and it fails on the fact that a campaign tree is *rebuilt* from the artifact store: `_resolve_tree()` reads each node's payload bytes and takes `payload.get("parent_id")` and `int(payload.get("depth", 0))` — so a node's declared `depth` is a fact some writers state and others do not, while the **edges are the tree**. A meta derived from the edges cannot disagree with the tree it describes; a meta read from a column can, and does, on the first writer that omitted it.

| field | source | why |
|---|---|---|
| `parent` | `CampaignNode.parent_id`, via `tree.node(node_id)` | the tree validated this edge when it was built, so a parent a meta names is always a node the tree holds |
| `depth` | **counted** along the parent walk | derived, not read — `r0a` in the test tree carries no `depth` key and still answers `1`; the sibling pool's `Σ|step|` is computed the same way |
| `branch` | the origin the walk terminates at | the grouping feature 236's per-branch census is taken over, and it is the campaign's own notion of a branch (`discovery.manifest`: *"A branch is a root (`parent_id` IS NULL), a refine is a non-root"*) |
| `theme_root` | the cell's own payload, by name | §9.1's `theme_root TEXT NOT NULL` column as the node froze it; `discovery.expansion` inherits it unchanged through a refinement |

### 2. `branch` is the **origin** of the branch, and `None` at that origin

This is the one field no document defines for a campaign node, so the choice is argued rather than assumed. Three candidates were on the table, each with real support elsewhere in the repo:

* **the axis moved** — bootstrap's reading (*"the axis the node's last legal step from its parent moved"*, `Axis | None`). Rejected: a campaign node's payload carries no axis, nothing in §9.1's `node` schema stores one, and inventing a vocabulary for a field whose *type* the sibling pool declares as a different type would make the identical-interface claim false in the one place a policy might branch on it. (`difficulty.py` reads "branch" as the *theme root* and `flipdepth.py` as a *node carrying a drawn flip depth* — three members, three meanings, so the field's meaning must come from the doc (§595's comment) and from what the campaign's own code already calls a branch.)
* **the immediate parent** — rejected as a duplicate of `parent`, which §595 already names separately; two fields carrying one fact is how one of them goes stale.
* **the branch origin (built)** — the node at the top of the parent walk, the one whose own `parent_id` is `None`.

And `None` **at** the origin, rather than the origin's own id, because that is what the sibling pool answers for its root (*"no parent and therefore no step that reached it"*). `meta.branch is None` therefore means *this cell is a branch origin* on **both** pools, so a policy's branch-grouping logic runs unmodified against either — the identical-interface law (feature 184/190, docs §10.6) read at this field. The id-at-origin alternative would make the campaign answer `"r0"` and the bootstrap answer `None` for structurally identical cells.

### 3. Structure answers for **unrevealed** cells; there is no prefix gate here

The temptation is to gate `meta()` on the reveal set, since 223/224 gate everything else. The reasons not to:

* §11.1's whole argument is that a policy writes **family-conditional thresholds** — code authored before the run, conditioned on a slug it must read for cells it has not yet revealed. A reveal-gated accessor makes that impossible and the feature vacuous;
* §10.2's barrier withholds **scores**; cq-8 withholds `is_null` altogether. Neither says a word about the tree's shape, and the shape is what §11.1 *requires* exposed;
* feature 184's accessor refuses only a node *"outside the lattice"* — no reveal gate — so a gate here would put the barrier's edge in a different place on the two pools and break the identical interface;
* the security question is whether a *reading* leaks. It cannot: the accessor reads four keys and returns four fields, and `test_meta_carries_no_reading_from_the_payload` pins that a payload carrying `r2_insample`, `ic_insample`, `n_periods`, `n_features` **and `is_null`** yields exactly `{branch, depth, parent, theme_root}` and no `is_null` anywhere in the rendered row.

What the accessor *does* gate is the thing a policy could use to reason about a campaign it never saw: a node the tree does not hold is refused through the tree's own address seam.

### 4. `theme_root` absent answers `None`; `theme_root` present-but-unnamable is **refused**

Both distinctions are load-bearing and they answer differently.

* **Absent → `None`.** The honest null this member already states one field over: `PolicyObservation.from_node` reads its metrics *"by name, defaulting to `None` when the payload carries no such metric — a node that carries no in-sample reading is a structural node, not a scored leaf, and its observation says so rather than inventing a number"*. A cell whose record declares no family reports no family. The key present with value `None` is the same statement.
* **Present but not a name → refused.** A blank string, a number, a nested object is a *corrupt structural record*, not a silent absence, and a family that cannot be named cannot be conditioned. Refused naming the node and the value — the member's never-coerce stance (`families._theme_key` refuses a `theme_root` key that is not a non-empty string; `bootstrap.CellMeta` checks its own key the same way).

The third decision inside this one: **nothing is normalised and no legal set is consulted.** Feature 241's committed config is the ceiling on which themes exist, and restating it here — even as a warning — would be a second spelling of a config-bound law. The same reason feature 228's key check refuses to hold the legal list.

**One deliberate divergence from the sibling pool, recorded so it is a decision and not an oversight.** Feature 184's `CellMeta` declares `theme_root: str` — never `None` — because a bootstrap world is constructed *from* a family and always knows its own. This one declares `str | None`, and the reason is upstream of the accessor: the campaign's node model is `(node_id, parent_id, depth, payload)` and the family arrives as §9.1's `theme_root` payload column, which a given writer may or may not have stated — the member's own canonical test tree carries `{"depth": 0}` and no family at all, exactly as `_resolve_tree()` reads `payload.get("depth", 0)` because some writers omit even *that*. Making the field total here would mean either refusing a tree the deployment's own store can hold (including this member's canonical fixture) or inventing a slug, and an invented family is the one outcome §11.1's argument cannot survive: a policy would condition on a family that does not exist. The three other fields agree with bootstrap field-for-field and type-for-type; this one carries the campaign's own honesty about an unstated column. The portability a policy loses is one `None` check on one field, and it loses it in the direction of *not being silently misled*.

### 5. The walk is **bounded** — a cycle or a missing link is refused, not followed

`CampaignTree.__post_init__` validates that every parent reference resolves to a node in the tree, so a *dangling* reference cannot be built through the constructor. It has no reason to walk, so a **closed** chain (a cycle) passes the constructor untouched — and a walk from such a cell never terminates. Both shapes are refused with `PolicyTreeError` naming the cell and the offending reference: a cell with no branch origin has no structure to report, which is the honest answer for a malformed tree rather than a hang or an invented root.

The missing-link case is tested on a carrier that *eludes* the constructor's check — the shape a tree mutated past its constructor, or built by another implementation, has — because the accessor must refuse the malformed tree rather than trust the check that was supposed to make it impossible.

### 6. Duck-typed seam, validated reads, translated vocabulary

The module loader imports the member under a synthetic name and re-executes it, so the composed tree `create_app()` hands out is a *second* `CampaignTree` class object — an `isinstance` would refuse the very tree composition produces. So the seam reads `tree.nodes` and `tree.node` and validates what it reads: a node id that cannot be named, a payload that is not a mapping, a `node()` that raises — each refused in this module's vocabulary rather than escaping as a bare `AttributeError`/`ValueError`/`TypeError` a caller's `except PolicyRuntimeError` would miss.

One exception is deliberate: a `PolicyAddressError` from the tree is **propagated unchanged**, because the tree's refusal already names the node and the tree, and re-spelling it here would be a second sentence for one law.

### 7. A pure function of `(tree, node_id)`, and `CellMeta` is frozen

Nothing is cached, nothing is stored on the question, nothing is remembered from a previous read — so two reads answer equal frozen values whatever happened in between, and a second question over the same nodes answers identically. That is what §10.6's *"a policy is portable without modification"* needs at this seam, and it is why the value is frozen: a node's structure is a fact about where it sits, not something a reveal can move, so a policy comparing two cells cannot move either one's structure. `cell_meta(tree, node_id)` is the one spelling; `PolicyQuestion.meta` is a **delegation** to it, exactly as `observed`/`reveal`/`probe_batch` all route through `_observe`.

### 8. Placement: a new submodule, not an addition to `__init__`

`meta.py` holds `CellMeta`, `cell_meta`, and `THEME_ROOT_KEY`; `__init__.py` gains the import block entry, the sorted `__all__` entries and the accessor method. Every prior feature in this member with its own value type took the same route (`budget.py`, `families.py`, `planning.py`, `commit.py`, `prefix.py`, `surface.py`), because `__init__.py` is import-cheap by law and a value type's long argument belongs beside its behaviour.

## Invariants that must not move

* `test_prefix.py:193` — the prefix view carries **no** `meta` verb: it is a *question* verb, and a policy holding a prefix view holds only readings. Unchanged.
* `test_surface.py:244,625` — `"meta"` stays an *unconfigured* answer name, refused because it needs an argument. Unchanged; `test_meta.py` pins the `TypeError`.
* the member's prefix-only law — no unrevealed cell's **reading** is reachable. `test_meta_carries_no_reading_from_the_payload` pins the structural read as its inverse.
* the 475-test baseline → **502 passed** (27 new). The `__init__.py` ruff result is byte-identical to the pre-change baseline (I001 at 276, RUF022 at 371, 3×UP037 at 530/627/693 — all pre-existing); `meta.py` is lint-clean, and `test_meta.py` carries only the same I001 the sibling test files carry.

## Files

* `packages/policy-runtime/src/policy_runtime/meta.py` — **new**. `THEME_ROOT_KEY`, `CellMeta`, `cell_meta`, and the bounded walk.
* `packages/policy-runtime/src/policy_runtime/__init__.py` — `PolicyQuestion.meta`, the import block entry, four `__all__` entries, the module docstring paragraph.
* `packages/policy-runtime/tests/test_meta.py` — **new**. 27 tests.
* `src/app/modules/policy-runtime/__init__.py` — the seat's docstring paragraph, in the established voice.
* `.plans/feature-219-the-meta-accessor.md` — this file.
