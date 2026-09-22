# Feature 211 — the stated mechanism string

**app_spec.xml, "Hypothesis Authoring Agent", feature 211**
(`plugin="signal-agent"`, `depends_on=205`):
*System persists a stated mechanism string used for deduplication and human
review, never as a scored input.*

Authoritative spec:

* `docs/nullius-tech-architecture.md` §9.1 —
  `stated_mechanism  TEXT,   -- dedup + human review ONLY, never scored`
* `docs/alpha-engine-prd.md` §4 / schema block —
  `stated_mechanism: str   # agent's economic rationale; used for dedup`
  `# and human review ONLY. Never scored.`
* `app_spec.xml` feature 98 (core, already landed) creates the *column*:
  `0117_identity_trio.py` adds `stated_mechanism TEXT` to `node`, bare and
  nullable, and its docstring already argues the nullability at length.
* Feature 102 (core, landed) creates the `code_hash` index whose comment is
  `-- dedup`; feature 179 (`artifacts.CodeHashIndex`) is the dedup *gate*.

So the column exists, is nullable by design, and has **no writer**. That is
this feature.

Footprint: `packages/signal-agent/**`, `src/app/modules/signal-agent/**`.

## What feature 211 is, and what it deliberately is not

The sentence decomposes into four claims, and the split between them is the
whole design:

1. **the stated mechanism string** — the agent's own economic rationale for a
   proposal, *as the agent stated it*. Not a summary of the source, not a
   classification this member derives, not a theme root. It is the one free-text
   field on the node row, and its whole value is that a human reads what the
   agent *claimed it was doing*.
2. **persists** — it lands on `node.stated_mechanism` (feature 98's column),
   through the same compare-then-set / one-connection / one-transaction
   discipline every store in this workspace keeps.
3. **used for deduplication and human review** — two *readers* the value must
   serve. Dedup is 179's `CodeHashIndex` over `code_hash`; the mechanism is the
   *semantic* companion axis ("the same economic claim resubmitted in different
   code"), and a human review queue is the other. Neither is a scored path.
4. **never as a scored input** — and this is the load-bearing clause. The
   mechanism must not be able to reach any number the system reports. The
   feature's real content is a **barrier**, not a field.

**Why the barrier is the feature.** A nullable `TEXT` column with a writer is
trivial. What is not trivial — and what feature 110 (`nulloracle.schemaguard`,
"keeps `is_null` absent from the tree store") is this house's precedent for — is
making the *non-scoring* a property that a future change cannot quietly break.
The failure mode is specific and quiet: the moment `stated_mechanism` is
reachable as a numeric input to the evaluator, scoring, or a policy, then
`agent_model_id` stratification, the M3 paired comparison and the deflation
term all become functions of **prose an LLM wrote** — a leakage channel from
the authoring model straight into the headline figure. It would not look like a
bug. It would look like a feature ("let the policy condition on the mechanism").

## Decisions

### 1. The law lives in a new submodule `signal_agent/_mechanism.py`

Sibling of `_authoring.py` (205), `_themes.py` (212), `_dead_territory.py`
(213) — the established shape for a feature this member owns. It holds:

* `MechanismReason` (`enum.StrEnum`) — the audit vocabulary, split by *repair*:
  `STATED` ("stated_mechanism"), `NOT_A_STATEMENT` ("not_a_statement"),
  `BLANK_STATEMENT` ("blank_statement"). Same discipline as `AdoptionReason`,
  `ThemeReason`, `DeadTerritoryReason`: the value is the token its own detail
  opens with, so a refusal never opens with another reason's headline.
* `MechanismRecord` — a frozen value: the stored string, its node id, and the
  three derived facts the two named readers need (`digest`, `words`,
  `superseded`). Constructor refuses nothing (the `SourceAdoption`,
  `ThemeAdmission`, `DeadTerritoryVerdict` discipline); refusals live at
  `require()`.
* `StatedMechanism` — **the law** (a gate, not a store): the pure function from
  a proposal's stated mechanism to a `MechanismRecord`. It carries no database
  and no campaign.
* `MechanismStore` — the write/read path onto `node.stated_mechanism`, keyed by
  node id, `resolve()`/`from_env()` off `DATABASE_URL` like
  `AgentModelPins.resolve` and `CodeHashIndex.resolve`.
* The scoring barrier's vocabulary (decision 3) — the module that *answers*
  "may this column be a scored input?" is the same module that owns the column.

`MechanismStatement` is **not** the name: "record" vs "statement" would be two
coins for one side. `StatedMechanism` (the law) and `MechanismRecord` (what a
persist left behind) is the split the other three features already use.

### 2. One new component, `signal-agent-stated-mechanism`

The member carries three components today and the registry is keyed by name, so
a fourth unprefixed `signal-agent` would *replace* feature 205's law. The name
sorts as `signal-agent` < `signal-agent-dead-territory` <
`signal-agent-stated-mechanism` < `signal-agent-themes`, so all four stay
contiguous in the name-sorted `app.order`. The existing `test_component.py`
contiguity test must be updated from three to four.

The builder takes **two** facts and cannot be one zero-argument builder, because
it must hold both a store and the barrier:

```python
@register("signal-agent-stated-mechanism")
def build_stated_mechanism() -> StatedMechanism:
    return StatedMechanism(MechanismStore.resolve())
```

`StatedMechanism` is composed **always**, with `store=None` when nothing names a
database — a discoverable state, not an error, the `CodeHashIndex.resolve` /
`AgentModelPins.resolve` stance, because the factory builds every registered
component on every `create_app()` and a builder that raised would take
composition down for the whole workspace. The **barrier** is store-independent
and therefore always answerable; `persist`/`load`/`duplicates`/`stated` raise a
named `MechanismStoreUnavailableError` when composed without one, which is the
"a caller that must persist has to treat `None` as a refusal to proceed"
reading `build_agent_model_pins`' docstring already states for its own `None`.

One component rather than two (a bare `signal-agent-stated-mechanism` law plus a
`signal-agent-stated-mechanism-store`) because the store and the barrier are one
feature's subject: a caller holding the barrier separately from the writer would
be able to persist into a tree it cannot ask about, which is exactly the
half-wired shape the sentence's two clauses are supposed to hold together.

Construction performs **no I/O**: the URL is translated on first use, never at
build time.

### 3. The barrier: `MechanismRecord` is not a number, and `require_scored_input` refuses

This is the clause the feature is about, and it gets three seams so that "never
scored" is checkable rather than conventional:

* **No numeric coercion, structurally.** `MechanismRecord` implements
  `__slots__` with no `__float__`, `__int__`, `__index__`, and its `digest` is a
  `str`, not a number. A caller that tried `float(record)` gets a `TypeError`
  from Python, not a silently-ordered value. A test pins each of the three
  dunder refusals, because the failure mode is a *later* edit adding one.
* **`StatedMechanism.scored_input(record)` → `ScoredInputVerdict`, always
  refused.** The affirmative answer is a value whose `scored` is `False` and
  whose `detail` opens with `NEVER_SCORED_CODE` (`never_scored`), naming the
  column, §9.1's annotation verbatim, and what the score actually is (the
  evaluator's metrics over the signal source, feature 85). `require_scored_input`
  raises `MechanismNotScoredError` — the bridge for a caller on its last line
  before it would feed the value into a scorer.
* **The dedup reader takes the mechanism as a string key, and says so.**
  `MechanismStore.duplicates(mechanism)` answers the *semantic* dedup question —
  the stored nodes whose `stated_mechanism` states the same mechanism (same
  digest, i.e. same normalized statement), which is §9.1's `-- dedup` reading.
  It is a **report**, not a gate: feature 179's `CodeHashIndex` remains the gate
  that refuses an exact duplicate *before* a trial is charged, and this member
  must not restate or re-implement it. The two axes are different — identical
  code is one hypothesis, identical *claim* with different code is the 400
  parameter-tweaks failure §14.1 names at roots — so this one informs a human
  and a retry prompt rather than charging anything.

**Why the dedup reader is not a second dedup gate.** If it refused, this member
would own a second reject-before-charge path, and 179's serialized-probe
argument (the `BEGIN IMMEDIATE` write lock closing 0113's two-writers race)
would have to be re-derived here against a *text* key with no index behind it.
That is a different feature's question and a worse answer. The honest shape is:
179 gates on content, 211 reports on claim.

### 4. Normalization, or: what "the same mechanism" means

Dedup on a free-text field is only meaningful if two spellings of one claim
compare equal, so the record carries a `digest`:

* `canonical_mechanism(text)` — strip, collapse internal whitespace runs to one
  space, `casefold()`. **Deliberately not** a stemmer, a synonym map or an
  embedding: those would be this member inventing a semantic equivalence the
  spec does not state, and a false merge is worse than a miss (it hides a
  genuinely distinct hypothesis from human review). The docstring says so, and
  `-- dedup` in §9.1 is the only authority claimed.
* `digest` is the sha256 hexdigest of that canonical form, in the same
  lowercase-hex spelling `source_code_hash` and `artifacts.canonical_code_hash`
  both use. It is a **key**, never a number and never a score.
* The stored column keeps the agent's **verbatim** text. Normalization is for
  comparison only — storage never rewrites what the agent said, for the same
  reason `SignalContract.adopt` returns the source unmodified and
  `DeadTerritoryGate.admit` returns the root unmodified.

### 5. The write path: `MechanismStore`, and the nullability is the fact

Feature 98's column is `TEXT` bare-nullable and `0117`'s docstring argues the
null is a positive fact ("an agent that states no mechanism has left nothing to
review, and a NULL records that rather than fabricating a rationale no one
wrote"). So the store must be able to write *nothing* honestly rather than
fabricate:

* `persist(node_id, mechanism)` — validate both, prove the column exists
  (naming revision `0117_identity_trio` when the tree has not reached it, the
  `PinColumnError` discipline), then answer the stored state:
  * no node row → `MechanismNodeNotRecordedError` (a mechanism is a column on a
    node; writing one for an id the tree does not hold would mean writing a row
    this member does not own);
  * `None`/blank offered on a row holding nothing → the **unstated** write, a
    `NULL`, `recorded=True`, `reason=NOT_A_STATEMENT`. This is the honest
    persistence of "the agent stated no mechanism" and it is *not* a refusal —
    refusing would force a caller to invent text;
  * the same mechanism already stored → `recorded=False`, idempotent retry
    (the `NodePin.stamped=False` precedent);
  * a **different** mechanism already stored → `MechanismConflictError`, naming
    both. A node's stated mechanism is history — it is what the agent said when
    the proposal was made, and it is the key a human review queue and the
    semantic dedup reader both hang on — so re-stating it would silently
    re-point both readers at a claim no author made.
  * an empty row → the `UPDATE`.
* `load(node_id)` → `MechanismRecord | None`; `None` means *this row records no
  stated mechanism*, which is the unstated state and not an absent node (an
  absent node raises). Three-way distinction preserved, matching `load()`
  elsewhere in the workspace.
* `duplicates(mechanism)` → the stored `(node_id, stated_mechanism)` pairs whose
  digest matches. It is a read for review, and it excludes nothing: it names
  every holder, so a human decides.
* `stated()` → the rows whose `stated_mechanism` is non-NULL, in insertion
  order. This is the "human review" half of the sentence made concrete.

There is deliberately no `unreviewed()` and no `reviewed_at` column. Feature 211
persists the *statement*; a review *workflow* would need its own state on the
row, which is schema this member does not own and a seat no sentence here
assigns it. A read that lists what has been stated is the whole of the review
half, and naming it `unreviewed` would claim a state machine that does not
exist.

`MechanismStore` deliberately does **not** create the `node` table or the
column: both are core schema (features 97/98) this member does not own, and the
`_pin_store.py` docstring's argument applies verbatim.

### 6. Error vocabulary: two new classes, no new base

`signal_agent/errors.py` grows:

* `MechanismStatementError(SignalAgentError)` — the *statement* contract: a
  proposal's stated mechanism could not be established as text (not a string,
  or blank where a statement was required), or the row already states a
  different one. Sibling, not subclass, of `AgentSourceError` — the subject is
  the rationale the agent gave, not the source it wrote, and an operator asking
  "how often did the agent state no mechanism?" must be able to grep for it.
* `MechanismNotScoredError(SignalAgentError)` — the *barrier*. Raised by
  `require_scored_input` only. It is deliberately **not** under
  `AgentSourceError`: it is not a refusal of a proposal and no re-prompt
  repairs it; it is a refusal of the *caller* wiring the record into a scorer,
  which is a bug in this system rather than in an agent's answer. The
  `ThemeSetError`/`DeadTerritorySetError` split (deployment/config vs proposal)
  is the precedent for separating it.
* Plus three deployment-side siblings, none under `AgentSourceError`:
  `MechanismNodeNotRecordedError` (no such node), `MechanismColumnError` (the
  tree has not reached `0117_identity_trio`) and
  `MechanismStoreUnavailableError` (the component was composed with no
  `DATABASE_URL`). Each names a *deployment* fact, no agent action repairs any
  of them, and the campaign driver's retry logic must not see one and re-prompt
  — the `ThemeSetError` argument, restated for this feature's three.

I will **not** refactor feature 205/212/213's existing classes.

### 7. The app seat, `src/app/modules/signal-agent/mechanism.py`

A fourth seat beside `__init__.py` (205), `themes.py` (212) and
`dead_territory.py` (213), same shape: import the member only under
`TYPE_CHECKING`, answer `None` when nothing is registered, re-export nothing but
the component name and the accessor. The docstring states what the seat's `None`
means — *no `signal-agent-stated-mechanism` component was registered*, which is
**not** "the agent stated no mechanism" (that is a value the law returns).

### 8. Tests: `test_mechanism.py` (new) + `test_component.py` (extended)

New module, ~450 lines, asserting the four claims separately:

* **the string** — verbatim storage, no rewrite; the canonical form and digest
  are comparison-only.
* **persists** — against a real SQLite tree built by running
  `0118_node_table.py` then `0117_identity_trio.py` **by file path**, the
  `packages/providers/tests/conftest.py` discipline (never a hand-written
  `CREATE TABLE`); a tree that has not reached `0117` refused by name; a missing
  node refused; the unstated write; the idempotent retry; the conflict.
* **dedup and review** — `duplicates()` finds two spellings of one claim and
  does not merge two distinct ones; `stated()` lists the stated rows and skips
  the unstated ones; the module does **not** re-implement 179 (assert the two
  readers coexist and that `CodeHashIndex` is untouched).
* **never scored** — `scored_input` always refuses; `require_scored_input`
  raises `MechanismNotScoredError` opening with `never_scored`;
  `float()`/`int()`/`__index__` on the record all raise `TypeError`; the record
  exposes no numeric field; the digest is `str`.

`conftest.py` grows the DB fixtures for this member (a `mechanism_database`
built from the two migrations) and a `mechanism` fixture for the law, following
the file's existing style; the module docstring's "no environment isolation
here" paragraph needs a sentence, since this law's store *does* read
`DATABASE_URL` (the law itself still does not).

`test_component.py` extends to four components: the registration test, the
second-composition test, the contiguity test (three → four), and a
`_assert_is_the_mechanism_law` behaviour check.

## Verification

* `UV_CACHE_DIR=$PWD/.claw-forge/tmp/uvcache uv run --all-packages pytest
  packages/signal-agent -q` — the member suite (119 green today).
* Same command for `packages/providers`, `packages/artifacts`,
  `packages/nulloracle` — the neighbours whose tables/columns this feature reads.
* `uv run pytest` at the root — the acceptance gate collects `tests/` only, and
  the memory note says member suites are **not** graded there, so both must run.
* `uv run python -c "import signal_agent"` with `PYTHONPATH` per the workspace
  bootstrap, and a `create_app()` that lists four contiguous
  `signal-agent*` components.
* Ruff on the files I touch only (repo lint is red on `main`; compare against a
  sibling rather than trying to make the whole tree clean).

## Explicitly out of scope

* No edit to any migration (features 97/98 own the table and column).
* No edit to `src/app/middleware.py`, `src/app/settings.py`,
  `migrations/versions/**`, or any central registry/router/entry-points table
  or app factory.
* No LLM call, no prompt text, no store of proposal documents (features 206,
  207, 208).
* No mechanism clustering or `mechanism_discrimination` (features 214, 215,
  216) — this feature only makes the field persist and stay out of scoring.
