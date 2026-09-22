# Feature 196 — the serving provider of every root call, persisted

**Spec sentence.** *System persists the serving provider on every root-depth
call routed to the rotated frontier model tier.*

**Shape.** plugin, member `providers`, `depends_on=192`.

**Files.** `packages/providers/src/providers/_root.py` (feature 196's module),
`_root_errors.py` (its error vocabulary), `__init__.py` (import block, `__all__`,
two constants, one builder), `src/app/modules/providers/__init__.py` (seat
widened by one name and one accessor), `packages/providers/tests/test_root.py`,
`test_root_component.py`, `conftest.py` (a feature-196 fixture section).

---

## The architecture law

`docs/nullius-tech-architecture.md` §14.1, the role table:

```
| Signal agent, roots (depth 0–1) | ~50 | Frontier, rotated across 2–3 providers | 200K | $17 |
```

and the paragraph under it:

> **Rotating providers at roots is the cheapest mitigation available** for the
> convergence failure mode. Different model families carry different priors and
> propose structurally different mechanisms, at zero incremental token cost, and
> it hedges outages.

§14.2's roots row names the three — `claude-opus-5`, `gpt-5.6-sol`,
`gemini-3.1-pro`, *"Rotate all three. Different families, different priors,
different mechanisms proposed."* — and its preamble supplies the law that keeps
those names out of this module:

> rates move monthly … the selection logic is stable, the numbers are not.

`docs/alpha-engine-prd.md` §409 states the same split from the PRD's side:
*"Roots get a frontier model rotated across providers; depth gets a cheap model
with a 1M context."* §14.1 also documents the failure this feature's gate
exists for: `deepseek-v4-flash` was retired 2026-09-10 while the ID kept
accepting calls, and the completion reported the *serving* model.

## Where this sits relative to its siblings

| feature | its fact |
| --- | --- |
| 192 | the completion seam: one normalized answer, and *who served it* is **reported**, not assumed |
| 201 | routes a depth call to an endpoint — *"does not persist … the call's own record is where it would belong"* |
| **196** | **records which provider served each root call** |
| 197 | persists the per-campaign rotation — *what was assigned* |
| 198 | gates a depth model on its verified served context |
| 199 | the verified-context gate: a **stated** measurement, with no independent recomputation available |
| 203 | pins `node.agent_model_id` — *which model authored this node* |

196 and 197 are the two halves of one sentence's subject: 197 decides the
rotation, 196 records its outcome. A store that did both would be deciding an
assignment on the way to writing it down. 196 and 203 are the two questions a
root node's provenance answers: 203 says which authoring triple wrote the node,
196 says which of the rotated families took the call — and a campaign rotating
across three providers writes three providers into one campaign, which is the
axis 203's triple cannot express and the axis an M3 comparison stratifies on.

## Design decisions

**D1 — a seventh error base, `RootProviderError`.** The taxonomy splits by
*question*, not by call site. The six existing bases answer: a call failed
(192), a node's author cannot be named (203), a depth model was refused
(198/199), a window could not be found (202), an endpoint went unchosen (201),
a rate was never measured (200). None of them answers *which of the rotated
families took this root call*. Putting this under `DepthModelError` would put a
**root** fact under the **depth** role's name; putting it under
`BatchRoutingError` would take ground `_batch.py` explicitly reserves.

**D2 — the sentence is a conditional on the call.** *"every **root-depth**
call"*. §14.1 rotates providers at roots and nowhere else, and every depth call
shares one cheap model, so a depth call's provenance row would say what all its
siblings say and bury the stratum the rotation exists to expose. A depth call is
refused as `UnrotatedCampaignError` and **not** recorded — the repair is 198's
gate or 203's triple.

**D3 — the recorded provider must come from the tier's declared set, checked
before any row is written.** `UnknownRootProviderError`. The record's whole
value is that *"this root was proposed by a different family than the last one"*
can be believed; accepting anything a completion reports is exactly how §14.1's
documented silent re-route writes itself into the provenance as though someone
had chosen it. Membership rather than a comparison, so a member and a serving
provider are the same value type (`FrontierProvider`), as
`DepthModel`/`CachePrice` are for their own selections.

**D4 — the call's declaration is verified against the tree.** `RootCall` carries
`node_id`, `campaign_id` and `depth`; the store probes feature 97's `node` table
read-only and requires the node to exist, the campaign to match and the depth to
match — and re-applies the root boundary to the **tree's** depth, so a caller
cannot describe a depth-2 node as depth 0 and launder it into the root stratum.
This is where 196 is deliberately stronger than 199's gate, which had to accept
a stated measurement (*"a caller can hand this gate a fabricated
measurement"*): here the facts are rows and the store checks them. `node` is
**probed, never created** — it is `0118`'s, and a store that invented it would be
writing a schema it does not own.

**D5 — a member-owned table, keyed by the node.** `root_serving_provider`, one
row per root call, created lazily by the store's first `record` with `CREATE
TABLE IF NOT EXISTS` — the `bootstrap_world` / `depth_run_window` /
`depth_cache_rate` precedent, and no edit to the shared migration chain. Keyed by
`node_id` because *one root call is one node*, which is also the whole
idempotence story: the identical record answers the stored row (`recorded=False`,
original `recorded_at`); a different one is `RootProviderConflictError`, naming
both.

**D6 — the declared tier is not persisted on the row.** Feature 202's store
persists its premise (the card the window was chosen against). The temptation
here is refused for a specific reason: the tier is **197's per-campaign record**,
and a copy on every root row would be a second spelling of 197's fact written by
a different feature and kept in sync by nobody. The row records the outcome; a
reader wanting the premise asks 197 by campaign id.

**D7 — the module holds no model name.** `FrontierTier` is a shape, validated for
canonical order, duplicate members and emptiness. A tier of one is admitted (a
deployment that has added its first family is a real state, and refusing it would
leave that deployment's first campaign with no provenance at all); diversity is
feature 215's `tree_diversity` metric, not a constructor's judgment. An empty
tier is refused: it declares the campaign rotates across nobody, so the record
could never be written.

**D8 — recognition by parts, answers re-made.** Everything crossing the seam is
recognised via `object.__getattribute__` over a `_PARTS` tuple and rebuilt from
this module's classes — the double-import remedy every seam in this package
makes. `FrontierTier.__contains__` goes through it too, so a member built from
the workspace's *other* copy is not refused by a tier that plainly declares it.

**D9 — `recorded` tri-state as a this-call flag.** `RootCallProvider.recorded` is
`True` when the returned record's call wrote the row, `False` when it answered a
stored row or a read — carried through `_reissued`, which serves both cases.
`RootCallProvider` re-verifies the root boundary on construction: a record at
depth ≥ 2 cannot exist past the gate, and reading one back would launder a depth
call's row into the rotation's table.

## Files

| file | change |
| --- | --- |
| `packages/providers/src/providers/_root.py` | new — the module |
| `packages/providers/src/providers/_root_errors.py` | new — the seventh base + 4 subclasses |
| `packages/providers/src/providers/__init__.py` | import block, `__all__` (+25), `ROOT_SERVING_PROVIDER_COMPONENT`, `build_root_provider_rotation` |
| `src/app/modules/providers/__init__.py` | `ROOT_SERVING_PROVIDER_NAME`, `root_serving_providers_component`, docstring (three → four services, four → five registrations) |
| `packages/providers/tests/conftest.py` | feature-196 section: `tree_database`, `root_call`, `frontier_tier`, `root_serving_providers` |
| `packages/providers/tests/test_root.py` | new — 52 tests |
| `packages/providers/tests/test_root_component.py` | new — 10 tests |
| `packages/providers/tests/test_pin_component.py` | seat `__all__` widened (6 → 8) |
| `packages/providers/tests/test_served.py` | seat `__all__` widened; registrations four → five |

## Tests

`test_root.py` — the configuration (canonical order, value equality, empty
refused, duplicate refused, bare string / mapping refused, blank and non-string
names, foreign-copy recognition); the call (canonical ids, shape-only depth,
`bool` refused, negative refused, non-UUID refused, duck-typed row); the gate
(depth call refused naming both sides, boundary at `ROOT_TIER_MAX_DEPTH`
recorded, `ROOT_TIER_MAX_DEPTH + 1 == LARGE_HISTORY_FROM_DEPTH`, undeclared
provider refused before any database is opened, node not in the tree, no `node`
table naming `0118_node_table`, campaign contradiction naming both values, depth
contradiction, tree's own depth overriding the claim); the record (row contents,
writer-stamped instant spelling `…T04:15:00.123Z`, offset conversion, naive
refused, idempotent re-issue answering the stored row and leaving one row,
conflict naming both families, two roots in one campaign as two rows, foreign
store re-made); construction (`resolve` with unset/blank/set, no I/O at
construction, non-sqlite refused, `:memory:` refused, blank URL refused); the
free function (lands the row, reads the environment, refuses by name when
nothing names a store, lets the store's refusal through unwrapped).

`test_root_component.py` — registration under its own name; composition by scan;
a second composition still holds it (the submodule-registration trap); the
builder answering `None` with no `DATABASE_URL` and a bound store with one,
creating nothing; the builder taking no arguments; the seat's name pinned against
the member's; the seat carrying exactly two exports and re-exporting no records;
the accessor reading the application it is handed; the composed copy's vocabulary
asserted by class *name*.

## Verification

- `uv run pytest packages/providers/tests` — **698 passed** (was 636).
- `uv run pytest` (the acceptance gate's own collection) — **1060 passed**, the
  baseline held.
- Both run as separate commands; six test basenames collide across trees and a
  combined invocation aborts collection.

## Explicitly out of scope

- Choosing which declared provider serves which root call — feature 197.
- The rotation's diversity metric — feature 215.
- Persisting the declared tier per campaign — feature 197's record is where it
  lives.
- Any rate, price or window — §14.2's numbers move and this module holds none.
- Recording a depth call's provider — refused by design (D2).
