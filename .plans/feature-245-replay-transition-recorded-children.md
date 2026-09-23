# Feature 245 — the replay transition: a stored tree reveals only recorded children

**app_spec.xml, "Replay Engine", feature 245** (`shape="plugin" plugin="replay"`, no dependencies — it is the category's root):
*System rejects any attempt to generate a new child during replay, because a stored tree reveals only recorded children.*

Authoritative spec: docs/nullius-tech-architecture.md §10.1, whose `replay()` skeleton
(line 464–476) is the feature in code:

```python
def replay(policy, tree, book, epoch) -> ReplayResult:
    revealed = {tree.root}
    rounds = 0
    while rounds < K2:
        batch = policy.select(prefix_view(revealed))       # prefix-only
        if not batch:
            break
        for v in batch:
            child = tree.child_of(v)                       # DETERMINISTIC
            if child:
                revealed.add(child)
        rounds += 1
    pick = policy.commit()                                  # MANDATORY
    return score(pick, book, epoch, revealed, rounds)
```

and the sentence that follows it (line 482), which is this feature's whole reason for
existing:

> Online transition is stochastic (the agent may generate a different child from the
> same workspace). Replay transition is deterministic: it reveals the child already
> recorded. That asymmetry is the source of the cost advantage.

This is the **root of the Replay Engine category**: features 246, 247, 248, 251 all
declare `depends_on=245`, and every one of them is a rule about what a replay may touch.
245 is the object they are rules about — the replay's own transition over a stored tree.

## Context — why this feature, and what it is not

The whole category is a *cost* argument stated as prohibitions (docs §1, P5): replay must
be free, must be deterministic, must never invoke evaluation, must never compute what it
could read. 245 is the first and the most foundational of those prohibitions: **a replay
does not mint nodes.** It walks a tree whose edges were already written by the online
discovery loop — feature 239's `CONTINUE(v)`, one refined signal per expansion — and
"reaches" a child by *revealing a node that is already there*, never by generating one.

| feature | the rule over a replay | the object |
|---|---|---|
| **245 `transition`** | ***never generate a child — reveal the recorded one*** | **the walk over the stored tree** |
| 246 | never reach the evaluator | the replay's imports |
| 247 | never reach the evaluator *or the sandbox* (`forbidden_dependency`) | the replay's imports |
| 248 | loop selection to the round cap, return the revealed set | the rounds |
| 251 | read the pinned resident array, not Parquet | the reads |

**What it is not:**

* **not feature 218's `legal_actions`** — the policy-facing frontier returns *every* child
  of a position (a batch to select from) and is a pure function of the tree reached from
  the policy-runtime member. 245's transition is the *runtime's* act on one selected node:
  it advances the prefix by the child the tree recorded. 218 is what a policy may *ask*;
  245 is what the replay may *do*. Both read the same recorded edges, and neither invents
  one — 218 already states this in as many words (*"it is deliberately not feature 239's
  expansion: nothing here generates a child"*), which is the sentence 245 exists to make
  true of the runtime rather than only of the policy's view;
* **not feature 239's expansion** — the online generative act, in the discovery member,
  which resumes a workspace and asks the agent for exactly one refined signal. A replay
  reaches the *same* node by a different route: it reads the child that expansion already
  wrote. The two are the two halves of §10.1's asymmetry;
* **not feature 220's `probe_batch`** — the policy's own reveal verb, which grows the
  question's reveal set from cells the policy *chose*. The transition grows the replay's
  prefix from the child the tree *recorded*; a policy cannot use it and the replay cannot
  use `probe_batch` to reach a node the tree never wrote;
* **not feature 231 / the static admission gate** — that screens a policy's *source*
  before an episode; this refuses a *call* the replay could make while walking.

## Design decisions

### 1. The refusal is on the one verb through which a generation could enter

The feature's word is *attempt*. A refusal that only described the law would guard
nothing, so the transition's single verb carries the seam: `transition(selected,
generator=...)` refuses **before reading anything** when a generator is handed in. The
generator is exactly the online act's shape — a callable that would mint the child from
the parent's workspace (feature 239's agent seam) — and the refusal names §10.1's
asymmetry and the repair (read the recorded child), the way feature 146's inference seam
refuses a call made from the replay path. There is *one* verb and *one* seam, so there is
exactly one place a generation could enter the replay, and it refuses there.

### 2. The child is read off the recorded edges — the same seam 218 reads

The child is derived from the tree's own `nodes` (`parent_id` naming the selected node),
addressing the selected node through the tree's `node(node_id)`. No new attribute is
demanded of a tree, so the composed `CampaignTree` (policy-runtime) and any duck-typed
tree both work, and the docs' `tree.child_of(v)` is *this* derivation read on this pool's
node model — the same relationship 218's `legal_actions` states for the same document.
(`child_of` appears nowhere in the docs but that one skeleton line, so it is pseudocode
rather than an API on any real class: `recorded_child(tree, selected)` is the correct
reading for this pool's node model.)

**Derived once per transition, not once per step** (`child_map`). Measured while checking
this module's own "it costs a lookup" claim: a per-step re-derivation is O(N), so a walk
was O(N²) — 159 µs/step on a 500-node campaign, 684 µs/step on a 2 000-node one, i.e.
**76.5 ms for a 500-node campaign's transitions alone** against the **50 ms** the sibling
feature 252 budgets for an entire replay. Deriving parent → child once and reading it per
step gives 4.9 µs/step (2.33 ms for the same walk) — ~33×. The claim in the docstrings is
now the measured one. The same refactor moved the cardinality refusal (below) to
construction, where it belongs.

### 3. Exactly one recorded child, or none

§10.1's `child = tree.child_of(v)` is singular, and it is singular by the online loop's
own cardinality — feature 239's expansion "creates **exactly one** refined signal" per
selected node, so a stored campaign tree records at most one child per node. A node
recording **more than one** is a tree no deterministic transition can walk ("it reveals
*the* child already recorded" names no node), so it is refused naming the node rather than
silently picking one — a pick would be a choice the replay has no rule for, and two
replays of one tree would be free to differ.

**Refused at construction, not at the offending step.** The ambiguity is a property of the
*stored tree*, not of the selection that happens to reach it, so a replay that refused only
when the policy chose the ambiguous node would walk a tree it can never finish, spend
rounds doing it, and report a prefix whose incompleteness nothing in the answer explained.
(It is also what the derived parent → child map requires: the map cannot be built at all
when a node records several children.) The message names *every* child recorded for the
node, not the pair the walk happened to meet first.

### 4. The prefix is the transition's, seeded at the roots

`revealed` starts as the tree's **parentless nodes** — docs' `{tree.root}` read on a
themed campaign, which has one root per planted theme (prd §215, feature 218's
`legal_roots`), not the single canonical root a bootstrap lattice has. Each transition
adds the recorded child (`revealed.add(child)`, §10.1's own line) and the verb is
idempotent, because `add` is: a replay re-walked over one tree lands in the same prefix.
The loop, the round cap and the "no batch selected" termination are feature 248's; this
module owns one step.

### 4b. What is defended, and what deliberately is not

Probing for a route around the refusal (feature 245's word is *attempt*) found that a caller
holding a transition can write into its own state: `transition.revealed.add("invented")`
puts a node the tree never recorded into the prefix. `children` — the derived parent → child
map added for the cost fix — had the same exposure, so it is now a read-only
`MappingProxyType` (free: nothing writes it after construction) and pinned by a test.

The rest of the object is **not** defended, and saying so is more useful than a guard that
only half-works:

* `revealed` is a plain mutable set *by design* — §10.1's loop calls `revealed.add(child)`
  once per selected node, and a per-step copy is the quadratic cost this module avoids. A
  caller that writes into it can corrupt the prefix.
* A `__setattr__` freeze was written and then **removed**: it broke construction (the
  dataclass binds the field default before `__post_init__`), and even working it would guard
  only `children`/`tree`, leaving `revealed.add` open. Partial machinery implying total
  safety is worse than an accurate boundary.

The line is that feature 245 is a law about the **replay path**, not about objects held in
memory: its refusal sits on the verb a generator would arrive through (`transition`), and its
claim is that no replay *act* mints a child. A caller editing a transition's state is not
taking a transition, it is corrupting one. That is why the property is pinned where a driver
actually arrives and documented instead of over-engineered.

### 5. Reading the transition is not the policy's read

The prefix the transition grows is reported ascending (`prefix()`), the §12 ordering rule
stated for a search frontier — a replay that enumerates without sorting still walks
deterministically. The prefix view (223), the answer surface (224) and the commit record
(222) are the *policy's* objects and are not restated here.

### 6. A component, on the plugin name the spec states — and a *stateless* one

The member registers one `@register` component under `replay` — the object a composed
application carries. It holds nothing: a `ReplayEngine` facade with empty `__slots__`, whose
one verb opens a `ReplayTransition` over a tree the caller hands it, and whose `tree()` verb
resolves the *deployment's* campaign tree at **call time** through the app namespace
(`app.modules.policy-runtime`, the seat feature 217 ships) rather than by importing the
member, since a member never imports another member.

**Why the builder resolves nothing** (the load-bearing detail, found by measurement). The
campaign tree lives in the policy-runtime member's component, whose builder resolves it
through the artifact store's seat, whose builder composes the application again. A builder
here that resolved the tree would walk that cycle *from inside* `create_app()` — and since
the factory builds every registered component on every call, composition would **recurse
rather than return** (observed: an unbounded `create_app → build_* → _resolve_tree →
create_app` cycle, `create_app()` never completing). The cycle is pre-existing — it is why
the seat-bound builders in this workspace degrade to `None` — and this member declines to
widen it: resolution moves to the call site, where a missing campaign is an answerable
`ReplayTreeError` rather than a hang. The consequence is the honest one: a deployment with
no committed campaign still *composes* — a replay path with nothing to replay is a state,
not a broken application — while a caller that asks for the deployment's tree is refused by
name.

Later features in this category register their own components beside it under
`replay-<suffix>` names (the `artifacts-code-hash-dedup` precedent), never a second
`replay` — two components of one name put both in the registry and let the later import
silently win.

## Footprint

```
packages/replay/pyproject.toml                      new member (uv workspace by convention)
packages/replay/src/replay/__init__.py              package docstring, exports, @register component
packages/replay/src/replay/errors.py                ReplayError / ReplayTreeError / ChildGenerationRefused
packages/replay/src/replay/transition.py            feature 245 (replay_roots, child_map, recorded_child, ReplayTransition, ReplayEngine)
packages/replay/tests/{conftest,test_transition,test_component}.py
src/app/modules/replay/__init__.py                  the app seat
tests/replay/{conftest,test_plugin_wiring}.py       repo-level wiring + the walk over the real CampaignTree
uv.lock                                             the member entry (every member-adding commit carries it)
```

No shared file is edited: the workspace glob `packages/*` already declares the member, and
the app factory scans it by convention. (No `mcp__features__feature_report_shared_edit` was
needed.)

## Verification

* `uv run pytest packages/replay/tests` — 73 passed (the member suite; note a bare
  `uv run pytest` skips it, since `pytest.ini` sets `testpaths = tests`);
* `uv run pytest tests/` — 1074 passed (the repo suite, `tests/replay/` included);
* the two trees are run as **separate** invocations, not one: `packages/*/tests/conftest.py`
  files are all named `conftest`, so collecting a member suite and `tests/` in one run makes
  `from conftest import ...` resolve to whichever loaded first. This is a **pre-existing**
  workspace-wide collision — `packages/signal-agent/tests` + `tests/feature-store` fail
  identically — not something this feature introduced.
* `uv run ruff check packages/replay src/app/modules/replay tests/replay` — **All checks
  passed** (the sibling baseline is not clean: `packages/policy-runtime/src/policy_runtime/
  __init__.py` carries 5, and 19 of 34 policy-runtime files would be reformatted).
