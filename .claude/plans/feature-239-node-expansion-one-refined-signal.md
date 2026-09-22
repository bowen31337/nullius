# Feature 239 — expand a selected node by resuming its workspace

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 239:
*System expands a selected node by resuming its workspace, which creates
exactly one refined signal for evaluation.* `plugin="discovery"`,
`depends_on="238"`.

Footprint: `packages/discovery/**`, `src/app/modules/discovery/**`.

## What already exists, and what this feature therefore is

The member holds four modules (232's campaign record, 241's legal theme
set, 238's worker pool, 244's idempotent retry), and two of them name
this feature as a missing collaborator:

* `workers.py` calls it **the worker of record** — *"feature 239's
  expansion, a deployment's evaluator driver"* — the callable the pool
  runs one call per job, which *"closes over stores and workspace
  handles no pickle can carry"*.
* `retry.py` + `errors.py` state the constraint that shapes it:
  §14's *"ledger debits are idempotent by ``node_id``"* holds across a
  reclamation only if *"a re-run that minted a fresh node id"* never
  happens — the retry re-runs `result.job`, so **the expansion's node id
  must be a function of its ask**, or 244's identity law is decorative.
* PRD §5 loop 1 is the sentence's source: *"`CONTINUE(v)` = resume node
  `v`'s workspace, generate and evaluate one refined signal"*; §14.1
  fixes what resuming is at depth (*"given a mechanism and a diagnostic,
  make a targeted change"*); §10.1 notes the online transition is
  *stochastic in content* — a different child from the same workspace.
* `0118_node_table.py` names this feature as the consumer of the
  `parent_id` edge.

So the feature is the worker of record: `NodeExpansion(agent, url)` —
a callable taking the selected node, reading that node's workspace from
the tree, asking the agent seam for the refinement, and answering
**exactly one** `RefinedSignal` for evaluation.

## Decisions

**1. The ask is a node id, and the tree is the only source of the
workspace.** The policy's `legal_actions()` answers node ids; the
expansion canonicalizes the ask through `uuid.UUID` (the same
canonicalization campaign ids get), reads the node's row (the five
structural columns 0118 owns), and refuses — naming the node — when the
tree holds no such row or no table at all. A rich ask carrying workspace
facts would smuggle state past the tree read and defeat the resumption
law's teeth: you cannot resume a workspace the tree does not hold. The
artifact-side history (code, prior proposals, scores) stays the agent
driver's to assemble — it closes over the stores; this module's
resumption proof is the tree row, the workspace value it builds from it,
and the parentage the refined signal carries.

**2. The refined signal's node id is derived, never minted.**
`uuid.uuid5(EXPANSION_NAMESPACE, parent_id)` — one refined-signal slot
per selected node. This is the structural completion of 244's identity
law: same ask → same node id → one ledger debit, however many
reclamations intervene. Content stays stochastic (§10.1); identity does
not. The derivation is pinned inside `RefinedSignal.__post_init__` (the
`RetriedResult` pattern): a signal whose id is not its parent's
derivation is not a CONTINUE(v) this member made.

**3. Exactly one, with teeth.** The agent seam (`agent(workspace) ->
answer`) is duck-read: an `answer` that is a sized collection of
candidates must hold exactly one (zero → refusal; two or more → refusal
— several refinements are several dispatches, each its own debited
attempt); the one candidate must carry `code` as non-blank text, and may
carry `stated_mechanism` (absent → the honest NULL of 0117; present but
blank/non-text → refusal). A bare string is refused rather than guessed
into a code-only construction: §9.1's construction is the pair, and a
seam that silently dropped the mechanism would manufacture "the agent
stated nothing". Conformance to the signal ABI is *not* re-checked here
— that is feature 205's law in the authoring member, and no member
imports another; this module refuses shapes and cardinality, not
signatures. `code_hash` is computed here (the fourth spelling of three
stdlib lines, each member's documented precedent).

**4. Refusals raise `ExpansionError`; the agent's exceptions pass
through untouched.** One new class beside the other five, carrying both
faces (the tree's — no such node — and the seam's — not one signal),
because for both the caller's repair is the same: the attempt fails as a
value on the pool's `WorkerResult` and feature 240 logs it. Passthrough
is load-bearing in both directions: `WorkerInterrupted` must arrive as
itself (`is_interruption` is a class check — the retry depends on it),
and an agent failure must arrive as itself (§6.1 step 11: a failed
evaluation still consumed a hypothesis; §238: a failed run is a value).

**5. No persistence, no component, no seat.** Feature 240 persists every
attempt "including failures"; this feature creates the signal *for*
evaluation — `row()` is the node-shaped hand-off (the seven node-row
columns; `code` travels as the attribute because §9.1 stores the hash
and §9.2's artifact directory stores the text). No component, for the
inherited reason with its own face: a builder would have to bake the
deployment's agent driver at composition time, and the factory has no
agent to bake — the registered surface stays feature 232's single store,
so the component suite and the seat's pinned exports are untouched.

## Files

* `packages/discovery/src/discovery/expansion.py` — the feature:
  `EXPANSION_NAMESPACE`, `refined_node_id`, `NodeWorkspace`,
  `RefinedSignal`, `NodeExpansion`, `expand_node`.
* `packages/discovery/src/discovery/errors.py` — `ExpansionError`, plus
  the module docstring's sixth-class paragraph.
* `packages/discovery/src/discovery/__init__.py` — re-exports; a 239
  paragraph in the docstring.
* `packages/discovery/tests/test_expansion.py` — the four laws as
  behaviour (selection/resumption, derived identity + the 244 seam,
  cardinality, evaluation hand-off), the refusals, the passthrough, the
  238 composition (the expansion as `run_batch`'s worker), and the
  232→239→244 chain end to end.
