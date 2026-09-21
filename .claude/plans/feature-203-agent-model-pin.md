# Feature 203 — `agent_model_id` as a provider/model/version triple

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 203:
*System persists `agent_model_id` per node as a provider, model and version
triple rather than a rolling alias.* `plugin="providers"`, `depends_on=192`.

Footprint: `packages/providers/**`, `src/app/modules/providers/**`.

## What already exists, and what this feature therefore is

* `packages/providers` (feature 192) ships the provider *interface* — `Provider`,
  `Completion`, `Request`, `Message`, `Usage`, `RecordingProvider`, `Exchange`
  — registers `providers` (builder returns `None`, contributes no component),
  and has **no app-namespace seat** (`src/app/modules/providers/` does not
  exist yet).
* The `node.agent_model_id` **column** is owned by the core migration
  `migrations/versions/0115_agent_model_trio.py` (feature 100) — `TEXT NOT
  NULL`, added by `ALTER TABLE` — and its index `node_agent_model_id` by 0113.
  The `node` **table** is `0118_node_table.py` (feature 97). Both are
  core-task territory and are *not* edited here.
* `0115`'s docstring already states this feature's law from the column's side:
  *"the model as a provider/model/version triple, 'pinned, not a rolling
  alias' (feature 203's own words; §14.1's mitigation 2)"*, and hands the
  write path the check: *"the write path refuses what the column cannot
  represent"*. `packages/evaluator`'s `_persist_store` says the tree member
  fills `agent_model_id` in "from its own side of the seam" — the *meaning* of
  the value is unowned. Feature 203 owns it.
* Engine facts that shape the design (verified, and quoted by 0115): on a
  chain-built database the column is `NOT NULL` and every node row therefore
  already carries a string at insert — but **nothing in the schema constrains
  that string's shape**. `TEXT NOT NULL` accepts `'deepseek-flash'`, which is
  exactly the §14.1 failure (DeepSeek retiring `deepseek-v4-flash` on
  2026-09-10 while continuing to accept the id). The law that a stored value
  *is* a triple lives at the seam, not in the DDL — which is why the spec puts
  it in the `providers` plugin.
* `0115` names the one state the constraint could not cover: a populated
  table, where the bare `NOT NULL` refuses to land, and *"the repair is a
  backfill, not a spell"*. This feature's write path is that backfill.

## Decisions

**1. Two new modules in the member, plus the seat.**

* `providers/_pin_errors.py` — `ModelPinError` base + `RollingAliasError`,
  `ModelPinConflictError`, `NodeNotRecordedError`, `PinColumnError`. Its own
  base, *not* under 192's `ProviderError`: `_errors.py` argues its taxonomy is
  the *call* seam's failure modes and no other, and "a node is stamped with a
  rolling alias" is not a call that failed. Catching it as a provider failure
  would mis-answer "did the provider contract break?".
* `providers/_pinning.py` — `ModelPin` (frozen `provider`/`model`/`version`),
  the rendering to the column's `TEXT` spelling and its inverse,
  `require_agent_model_id`, and the column/revision constants.
* `providers/_pin_store.py` — `AgentModelPins`, the node-keyed store over
  `DATABASE_URL`, and the `NodePin` result record.
* `src/app/modules/providers/__init__.py` — the member's app-namespace seat
  (absent today), exposing `agent_model_pins_component`.

**2. The triple is three parts, structurally — this is the whole feature.**
`ModelPin` cannot be built from one string. `parse`/`require_agent_model_id`
refuse any value that is not exactly three non-empty, separator-free parts:
`'deepseek-flash'` and `'deepseek/flash'` are both rolling aliases (a
provider/model pair without a version names a *re-routing* target), and the
refusal says so in those words. No date is required of the version — PRD §14.1
mitigation 2 prefers *dateless ids documented as pinned snapshots*, so
demanding a date would refuse the ids the PRD recommends.

**3. The store never creates or alters the schema.**
`AgentModelPins` writes the one column on the one row of a table two core
migrations own — the discovery member's `CampaignRecords` stance. It refuses a
table without the column, naming revision 0115 (deliberate divergence from
discovery's "let SQLite's `no such table` escape": here the failure *is* "the
authoring-model column does not exist", and naming the migration is the
actionable report).

**4. Five reachable behaviours, each a test.**
`persist(node_id, pin)`:

| state | answer |
|---|---|
| column/table absent | `PinColumnError`, names node + 0115 |
| node row absent | `NodeNotRecordedError`, names the node |
| stored value not a triple | `RollingAliasError` — refuses to paper over it |
| stored value is a different triple | `ModelPinConflictError` — a node's author is history |
| stored value is the same triple | `NodePin(stamped=False)` — idempotent retry |
| stored value is NULL (the backfill state 0115 names) | writes it, `stamped=True` |

`load(node_id)` answers the `ModelPin`, `None` for a NULL value, and refuses an
unrecorded node (a node that cannot be addressed is not a node with no pin).

**5. The NULL/backfill case cannot be produced by the migration chain** — 0115
emits a bare `NOT NULL`, which lands on an empty table and is refused on a
populated one. So the suite builds that shape from **0115's own constants**:
every column `COLUMNS` names, at 0115's own `_column_type`, with the constraint
clause dropped — the additive first step of the repair 0115 calls a backfill.
(Not "minus `NOT_NULL_COLUMNS`": that filter, the obvious first guess, yields
*only* the nullable columns and leaves `agent_model_id` itself out, so the tree
could not hold a node at all. Corrected against a failing run.)

**5a. Two engine facts the first draft of the suite got wrong, both verified.**
(a) The `NOT NULL` on this column is not the only one — `agent_sampling` carries
it too, so a planted node row must supply *both* or the insert is refused; hence
`PLANTED_CONSTRAINED_COLUMNS`, pinned against `0115.NOT_NULL_COLUMNS` by the
fixture. (b) `plant_node` therefore supplies a real author **by default**: on a
chain-built tree, planting a node *is* recording its author, and
`agent_model_id=None` is how a test asks for the backfill state — which only the
nullable tree can hold and the chain-built tree correctly refuses. That refusal
is itself asserted, through the DBAPI, as the schema's half of feature 203.

**5b. The alias refusal names the node, and that was a defect the suite caught.**
`require_agent_model_id` can only name the *value* it was handed — at a bare
string seam that is all there is. A value read out of the column is different:
the store knows which row it came from, and `agent_model_id` is repaired *per
node*, so a report naming only the value leaves an operator to go and grep for
it. `_parse_stored` translates at that seam, keeping the parser's message
verbatim on the new exception. The other three store refusals already named the
row; this one was the exception, and the test asserting it is what found it.

**6. The suite runs the migrations, never hand-written DDL** (discovery's
conftest discipline): `0118` for the tree, `0115` for the trio, loaded by file
path because `migrations/` is not a package.

**6a. The loader's double import, and the two bugs it caused (found by an
end-to-end smoke test through `create_app()`, not by the suite).** The factory
imports every member twice — by file path as `_nullius_scanned_<dir>`, and as
the importable member — so `ModelPin` is *two distinct classes over one source
file*. `isinstance` across them is `False` for every value, and dataclass
`__eq__` likewise. Two consequences, both caught only when driving the composed
store:

* `require_agent_model_id` rejected a pin built from the *other* copy with the
  not-a-string message — telling a caller they "have not pinned a model at all"
  about this feature's own type. Fixed by recognising a pin by its **parts**
  (`_pin_parts_or_none`, via `object.__getattribute__` so a hostile
  `__getattr__` cannot fabricate a triple) — the same duck-typing
  `feature_store/persistence.py` uses at this seam for this exact reason.
* A recognised pin is now **re-made from its parts** rather than passed through.
  Passing it through made the store answer a conflict whose two sides were the
  same string, because the stored value parses to *this* module's class and the
  caller's pin was the other one. Re-making normalizes to one class, so
  equality, `NodePin.pin` and the value a caller gets back are all consistent.

A third instance is **not** a defect and is left alone: the composed store
raises the *scanned* copy's error classes, so a caller's
`except providers.ModelPinConflictError` does not catch them. That is
workspace-wide (verified — `discovery.CampaignOrderError` behaves identically),
it is documented (`nulloracle`'s `raised_named` fixture,
`feature-store/test_registration.py`, `snapshot/tests/test_component.py`), and
the established answer is to assert on the class *name*. `test_pin_component.py`
now pins that name and its `_nullius_scanned_providers` module, so the next
reader meets the wrinkle in this package rather than in a deployment.

**7. The wiring is one `@register` in the package `__init__`, and one seat.**
`build_agent_model_pins()` registers under `agent-model-pins`; the seat
`src/app/modules/providers/__init__.py` exposes `agent_model_pins_component`.
The suite composes **twice** on purpose — a registration in a submodule fires
only on the first `create_app()` of a process, so a single-call test cannot see
that defect. Two facts about the loader the suite had to be written around:
it imports each member under `_nullius_scanned_<dir>`, so a *scanned* store is
not an `isinstance` of the directly-imported `AgentModelPins` (compared by name
instead); and the member *does* import `app.module_loader` for `register` —
every member in this workspace does — so the direction asserted is that the
member never imports its own **seat** (which would be an import cycle closing
at composition time).

## Wiring

`@register("agent-model-pins")` in `packages/providers/src/providers/__init__.py`
(a second component beside 192's `providers`, following `bootstrap`,
`artifacts`, `sandbox`); builder resolves `DATABASE_URL` and returns `None`
when nothing names a store. No central registry, router, factory, middleware,
settings or migration is edited.
