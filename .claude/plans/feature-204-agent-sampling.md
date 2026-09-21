# Feature 204 — `agent_ckpt_hash` and the `agent_sampling` record

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 204:
*System persists `agent_ckpt_hash` for self-hosted weights plus `agent_sampling`
recording temperature, top_p, thinking and seed.* `plugin="providers"`,
`depends_on=203`. Footprint: `packages/providers/**`,
`src/app/modules/providers/**`.

## What already exists

* Feature 203 (committed, `54c2987`) shipped `providers/_pinning.py`
  (`ModelPin`, `require_agent_model_id`, `AGENT_MODEL_ID_COLUMN`),
  `providers/_pin_errors.py` (its own `ModelPinError` base, unrelated to
  `ProviderError`), `providers/_pin_store.py` (`AgentModelPins`, `NodePin`)
  and the seat `src/app/modules/providers/`.
* The **schema is already there and is not touched**: `0115_agent_model_trio`
  (feature 100, core) adds all three columns —
  `agent_model_id TEXT NOT NULL`, `agent_ckpt_hash CHAR(64)` (nullable),
  `agent_sampling JSONB NOT NULL` / `TEXT` on SQLite. `0115`'s own docstring
  already states feature 204's law from the column's side, including the four
  `agent_sampling` keys and the reading of the nullability split.
* So this feature is exactly the mirror of 203: **the trio's second and third
  columns have no writer.** 203 owns the first.

## Decisions

**1. Two new modules, no new component, no new error base.**

* `providers/_sampling.py` — `AgentSampling` (the four keys of the spec's
  schema comment), `require_agent_sampling`, the canonical JSON rendering and
  its inverse, `AGENT_SAMPLING_COLUMN`.
* `providers/_ckpt.py` — `require_agent_ckpt_hash`, the sha256-shape refusal,
  `hosted_api_weights()`, `AGENT_CKPT_HASH_COLUMN`.
* `_pin_store.py` grows: `AgentWeights` (the answer record), `NodeProvenance`
  (the read record), `persist_weights`, `load_provenance`, plus the two
  narrowed call sites the refactor below forces.
* `_pin_errors.py` grows two classes under 203's existing base:
  `AgentSamplingMalformedError`, `CkptHashMalformedError`. **Not**
  `InvalidModelPinError`, and not a second base — a malformed sampling record
  and a bad checkpoint hash are the same *kind* of failure 203's taxonomy is
  built for (*a node's authoring record could not be pinned*), and a caller
  catching `ModelPinError` must keep getting every one of them.
* No new `@register`: 204 adds columns to the row 203 already writes, so the
  composed `agent-model-pins` store is the seam. A third component would be a
  second handle on one service.

**2. `AgentSampling` is four required keys, not four optional ones.**
`temperature`, `top_p`, `thinking`, `seed` — `to_dict()` always emits all four,
`require_agent_sampling` accepts a missing key **only** when the value is
exactly the default the prompt would have sent (`0.0`, `1.0`, `False`, `0`),
and refuses a missing key that would have meant anything else. The reason is
the column's own justification: *"NOT NULL because the sampling parameters are
known at authoring time even when they are defaults: there is no node whose
dice are unknown, only unrecorded ones."* A partial dict handed back as-is
stores `{"temperature": 0.0}` where four settings decided the output — a record
that looks complete to every downstream reader and is not.

Ranges: `temperature` in `[0, 2]` (the range `providers.Request` already
enforces — restating it differently would let a request the interface accepts
be unrecordable), `top_p` in `(0, 1]`, `thinking` a strict `bool`, `seed` a
non-negative int inside the signed 64-bit range (`sandbox.seed.SEED_MAX`'s
boundary, restated — this member imports no other member) with **no `bool`
coercion anywhere**.

**3. The rendering is canonical JSON and the hash is over it.**
`json.dumps(..., sort_keys=True, separators=(",", ":"))` — the spelling
`cost_model.identity.canonical_cost_model` and
`artifacts._execution._render_trace` both use — so two equal samplings are one
stored string and key order is never part of a node's dice. `require_agent_sampling`
parses the stored *text* strictly (non-string, non-object, non-finite float →
refusal) and re-makes through the record, so a stored value and a built one
compare by value.

**4. `seed` is mandatory and refuses `None`.**
The spec names four keys and the column is `NOT NULL`; a sampling with no seed
is the one case where replay cannot reproduce the node, which is the whole
reason the record exists. `None` is refused, not defaulted — a defaulted seed
would *look* like replayability. (`sandbox.seed`'s `resolve_seed` draws the
same line: records with no seed are refused, not backfilled.)

**5. `agent_ckpt_hash` is nullable, and the nullability is the fact.**
Architecture §9.1's comment on the column is *"non-null for self-hosted
weights"* and the PRD's is the same. So: `None` ⟺ hosted-API weights, and that
case is **recorded explicitly** — `AgentWeights.ckpt_hash is None` rather than
an omitted write — while a rollback of a recorded checkpoint hash, or a hash
over a hosted-API node, is refused (`CkptHashConflictError`). The failure the
refusal prevents is not a wrong hash but a **pool read as homogeneous that is
not**, which is §14.1's provenance failure arriving through the one column the
triple cannot see.
`require_agent_ckpt_hash` accepts 64 hex in either case (folded, like
`artifacts.canonical_code_hash`) and refuses a short hash, a `sha256:`-prefixed
reference, a non-hex token and a non-string.

**6. `hosted_api_weights()` exists so `None` is a value rather than an omission.**
An explicit constructor for the hosted-API case; the store normalizes `None`
callers to it, so one fact has one representation.

**7. The store's shape, and the check-203-then-204 ordering.**
`persist_weights(node_id, *, ckpt_hash, sampling)` writes the row 203 already
wrote — a second column on one row, same compare-then-set, same one
connection/one transaction/one commit. It refuses, in this order: a malformed
ask (before opening anything), a tree store without the columns
(`PinColumnError`, naming 0115), a node the tree does not hold
(`NodeNotRecordedError`), a row that records **no authoring model** (a new
`NodeProvenanceError` — the row half of that class's "a record that carries no
`agent_model_id`" reading), a value that is not a triple (`RollingAliasError`),
a stored checkpoint hash that disagrees (`CkptHashConflictError`), and a stored
sampling that disagrees (`SamplingConflictError`). The triple is checked
*before* the weights because `agent_model_id` decides whether the checkpoint
hash column is even meaningful: a node whose author is an alias cannot have its
weights reasoned about, and reporting a hash conflict for such a row would be
the plausible answer that hides the real one.

`load_provenance(node_id)` returns `NodeProvenance(model, ckpt_hash, sampling)`
or `None` for a *recorded* hosted-API node; an unrecorded node and a row with
no authoring model are refusals, so "hosted-API weights" is never confused with
"nobody wrote this down".

**8. The 203 refactor, and the one constant 204 owns.**

* 203's module docstring says *"the value written is `str(triple)` — the one
  rendering feature 203 declares — and this is the only place in this package
  that spells the column's value"*. That sentence becomes false the moment a
  second column is written, so `_write` is split into `_write_triple` /
  `_write_weights` and the claim is corrected rather than left to rot.
* `NodePin` and `NodeProvenance` carry a `recorded` flag meaning *this call
  wrote this* — `None` when nothing was written, `True` when written. The two
  rows are two calls, so a bool would force `persist_weights` to assert a write
  that may have been the earlier call's, which is exactly the property
  `AgentModelPins`' docstring is absolute about.
* `_require_column` becomes `_require_columns(*columns)` with `_require_column`'s
  exact messages preserved; 204 adds `AGENT_SAMPLING_COLUMN` to the tuple
  *between* the two 203 columns, so a tree missing a column reports the **first
  absent one** and 203's own messages are reached unreworded.

**9. The suite extends 203's fixtures rather than inventing a second tree.**
`plant_node` grows `agent_ckpt_hash` (passed through where the column exists);
`nullable_trio_database` is reused unchanged for the "row records no authoring
model" state; a `weights_database` fixture adds a tree whose `agent_sampling`
and `agent_ckpt_hash` accept NULL, built from 0115's own `COLUMNS` /
`COLUMN_TYPES` / `_column_type` — the same additive step 0115 calls *"a
backfill"* — because on a chain-built tree both NOT NULL columns land on the
empty table and the rollback state it refuses must still be reachable.

## Wiring

Nothing to wire. `build_agent_model_pins` is already registered and already
composes the store; 204 is two more columns on the row 203 writes, reached
through `agent_model_pins_component`. No central registry, router, factory,
middleware, settings or migration is edited.

## What the tests found

Two defects, both in the *store* rather than in the values — neither visible
from reading the code, and both found by driving a state the suite can build:

**1. A NULL hash on a written row is hosted weights, not an absence — and the
first implementation read it as an absence.** `_answer_weights` compared the
hash only when the row held one, so a hosted-API row (hash NULL) accepted any
digest written over it: `recorded=True`, the row's scores moved into another
weight stratum, `230_weights_spread`'s comparison argument silently restated.
On a chain-built tree — the shipping one — this is reachable with one call,
because 0115's `NOT NULL` means a chain-built row always has a *written* record
while `agent_ckpt_hash` is nullable by design. The refusal's own message calls
this "the worst form of it" — and it was the case the comparison never saw.

The row's **sampling** is what settles it, and that is the fix: the two columns
are written together, so a non-NULL sampling means *the record is written* and
the hash's NULL is then §9.1's hosted fact rather than "nothing here yet". A
row whose sampling is NULL is the un-backfilled state and stays writable.
Consequence, stated in `_write_weights`' docstring: *every* state reaching the
write has a NULL sampling, and the hash beside it is either NULL or the agreed
digest — so the two guarded statements are still both needed, but for a
different reason than the draft claimed (the combined form would skip the hash
in the split state, not in the hosted one).

**2. `load_provenance` refused the very row `persist_weights` exists to
repair.** A NULL `agent_sampling` was passed straight into the parser, which
refused it — but that NULL is the un-backfilled state `weights_database` exists
to make reachable, and a reader meeting it should be told *these dice are not
recorded*, not *what is here is not four settings*. `NodeProvenance.sampling`
is now `AgentSampling | None` and there is a null-tolerating wrapper beside
`_parse_stored_ckpt_or_hosted`, deliberately **not** symmetric with it: a NULL
hash is a recorded fact, a NULL sampling is a to-do, and the record reports both
as the columns hold them rather than forcing one reading onto the other.

Also settled against the code rather than a reading: `require_agent_ckpt_hash`
folds surrounding whitespace with the case, which is
`artifacts._dedup.canonical_code_hash`'s exact rule (`value.strip().casefold()`);
a test was written asserting the opposite and corrected to pin the behaviour
instead.
