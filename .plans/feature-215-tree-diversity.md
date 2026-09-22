# Feature 215 — `tree_diversity`, a count of distinct mechanism clusters per campaign

**app_spec.xml, "Hypothesis Authoring Agent", feature 215** (`plugin="signal-agent"`, `depends_on=207`):
*System computes tree_diversity as the count of distinct mechanism clusters per campaign, which returns the figure per authoring model.*

Authoritative spec: docs/nullius-tech-architecture.md §14.1 (line 862), inside the "Measuring model adequacy on this task" block:

```
mechanism_discrimination = corr( IS_gain, OOS_gain | real branches )
tree_diversity           = distinct mechanism clusters per campaign
```

and the paragraph that reads it (line 866):

> A strong agent produces refinements whose in-sample improvement *predicts* sequestered-epoch improvement. A weak agent produces noise-chasing variations and the correlation collapses even on real branches.

with the surrounding argument (line 869) naming what diversity is *for*:

> Avoid distilling a small model on a frontier model's successful proposals after M3: it narrows toward one family's distribution, and **diversity is precisely what roots need**.

and the reporting rule that pairs it with 214 (lines 871–879) — *"Freeze the cohort… Both trivial baselines appear in every table… Calibration beside accuracy… Paired bootstrap over the cohort"* — of which rule 1 (*freeze the cohort, hash its inputs*) and rule 2 (*every table carries its constant baseline*) are the two this feature's shape has to answer.

## Context — why this feature, and what it is not

Feature 207 built the writer. `node_proposal` holds, per node, the proposal document + a score snapshot, and `ProposalStore.history(campaign)` reads them back. This feature is **the first reader of that store that is not itself the authoring loop** — the docs' own sentence for what 207 exists for (`additions_spec_207.xml:109`: *"depended on by features 214 and 215 (mechanism discrimination and tree diversity, which read the persisted score records across a campaign's real branches)"*).

So the subject is a **measurement over a campaign's recorded proposals**, reported **per authoring model** — the M2 model-adequacy instrument that runs *before* the M3 gate (§14.1: *"Run this at M2, before the M3 gate. Two campaigns per candidate model, roughly $60"*).

**What it is not:**

* it is **not feature 214**. 214 is the *correlation* `corr(IS_gain, OOS_gain | real branches)` — a different statistic over different columns (the metric pair), keyed on the *real/null* discriminant, persisting `mechanism_discrimination`. This feature counts *clusters*. They share a source (207's rows) and a report (both per campaign, both per model stratum) and nothing else. 214 is not on this branch; this feature must not build it, and must not import it;
* it is **not feature 210's anti-convergence gate**. 210 answers a *yes/no about one proposal against a campaign's history* — is this the 400th parameter tweak? — and its module docstring says so explicitly (`_anti_convergence.py:64`): *"nothing here prices a proposal or measures how converged a tree is — that figure is feature 215's, and it is a count of distinct mechanism clusters rather than anything this module computes."* 210 measures **one** proposal; 215 counts **the whole tree**. Different arity, different consumer (a gate blocks a write; a metric is reported). The *clustering rule* is where they touch, and the decision below settles which one 215 borrows;
* it is **not feature 211's stated mechanism read**. `StatedMechanism.stated()` exists and looks like a shortcut, but §9.1 annotates that column `dedup + human review ONLY, never scored` and 211's law ships an *always-refusing* barrier (`scored_input`) enforcing it. A diversity figure derived from the rationale is a figure conditioned on what a model said about itself — exactly what that barrier forbids. See decision 2; this is the feature's most load-bearing call;
* it is **not a persisted artifact**. §14.1's sentence for 214 is *"persists mechanism_discrimination per campaign"*; 215's is *"computes … which returns the figure"* — a **returned value**, not a row. No table, no `_SCHEMA`, no write path;
* it is **not a component**. No store, no deployment state, no `@register`; a free function reached directly from the member exactly as `plan_grid` (229), `screen_policy` (230/231), `read_beta` (226), `episode_commit` (222) and `world_census` (186) are. Registering an eleventh component for a question that resolves no configuration of its own would put a name in the registry for nothing — 186's own argument, and this feature's shape is 186's.

## The house shape this follows (do not invent a new one)

**Feature 186's `world_census` is the precedent, and it is close enough to copy deliberately rather than rediscover.** A counting law over a member-owned/external table, duck-typed at its seam, refusing an absent table rather than answering a zero, grouping into a value object with validating `__post_init__`, no component, no write. The differences are the ones the sentence dictates: the figure is **grouped by authoring model** (186's is a flat pair), the grouping key comes from a **joined** column (186's two figures come from its own arguments), and the "cluster" needs a *defined identity* (186's counts were over ids already in the database).

Everything else follows the member's established conventions verbatim: `Final[str]` constants for every column and table name; refusals that open with their own greppable token; a module docstring that argues each decision at the point it bites; stdlib-only (`sqlite3`, `collections.abc`, `dataclasses`, `typing`) so the factory's scan pays nothing.

## Design decisions

### 1. **A cluster is a code-hash class, not a skeleton class and not a mechanism digest** — *this is the feature*

"Distinct mechanism clusters" needs a definition, and this member owns **three** candidate identities, each built for a different question. The decision is which one *diversity* means, and the answer is forced by what 207 stores.

| candidate | what it identifies | where it lives | why not |
|---|---|---|---|
| `mechanism_digest(stated_mechanism)` | the agent's *stated claim* | 211 | **Refused — the barrier.** See decision 2 |
| `skeleton_digest(source)` | the source's *structure, constants erased* | 210 | Refused — **wrong granularity for a count** |
| `code_hash` (the document's sha256) | *this exact proposal* | 207 (stored) | **This one** |

The skeleton question deserves the argument, because it is the tempting one (it is literally "the mechanism's shape", which *sounds* like what the docs mean by "mechanism cluster"). Three reasons it loses:

* **It is 210's unit, and 210 says so.** 210's module docstring pre-answers this feature: its verdict is *"a yes-or-no about one structure against one campaign's history"* and the diversity figure is *"a count of distinct mechanism clusters rather than anything this module computes."* Borrowing `skeleton_digest` here would make this feature a second spelling of 210's comparison — and the member's rule (`mechanism.py`: *"a digest that disagreed with its neighbours on case would make one value look like two"*) is that a **derived key has one owner**. If diversity is ever to be skeleton-based, that is a change to what a cluster *is*, argued once, not a second call site;
* **erasing constants makes the count blind to exactly the collapse §14.1 warns about at *depth*.** §14.1: *"At roots, a weak model's failure mode is proposing the 400th variant of one indicator — every node scores plausibly."* The anti-convergence gate stops the 400th variant **being written**. But a tree where a weak model wrote 40 *structurally distinct* variants that all curve-fit noise is a **low-diversity** tree by every reading the docs give, and skeleton-erasure scores it as 40 distinct clusters. `code_hash` counts it as 40 proposals that are, in fact, 40 different mechanisms-stated-in-code — which is honest about what was written. Neither count is "the convergence measure"; this one is the count the sentence asks for;
* **it forces this module to parse source.** `skeleton_digest` raises `AntiConvergenceError` on unparseable text (its docstring says so — the conformance screen runs first). A *reporting* function that can be taken down by one malformed document in an old row is a reporting function that stops reporting; a count should not be able to fail on its inputs' syntax.

**So a cluster is a distinct `code_hash`** — i.e. the number of distinct proposal documents the campaign recorded — and the module says plainly, in its own docstring and at the constant, what that means and the three alternatives it rejected with their reasons. This is the one place a reader must not be able to guess wrong, because "distinct mechanism clusters" would otherwise be read as the skeleton.

**The count is over the stored rows, and it is per campaign.** Not global: PRD §9 makes the campaign the unit of search, which 210 states for its own comparison set (*"two campaigns exploring one structure from different angles are two campaigns, not one collapse"*). A deployment that wants the pooled figure sums strata — the pooled figure is the *sum*, and it is deliberately not offered as a method, because a pooled count over a campaign id is a different question (the same restraint 186 applies to `total`: named where it means something, absent where it invites the wrong read).

### 2. **The `stated_mechanism` column is refused as the clustering key, and 211's barrier is cited rather than re-implemented**

`StatedMechanism.stated()` returns every stored rationale, and `mechanism_digest` is right there. Using them would be a bug, and a subtle one — the figure *looks* like a measurement and is a function of what models claim about themselves.

Three authorities, all already cited in this member's own vocabulary, agree:

* §9.1's annotation on the column: `-- dedup + human review ONLY, never scored`;
* 211's `scored_input` refusal sentence (`_mechanism.py:640`): *"a score conditioned on the rationale would make `agent_model_id` stratification (PRD §5a), the M3 paired comparison (arch §14.1) and the beta-three deflation term functions of what a model said about itself."* **This feature is the `agent_model_id` stratification** — its own sentence says *"returns the figure per authoring model"* — so it is precisely the reader that sentence names;
* 210's docstring: *"a weak model asked for the 400th variant states it confidently in fresh prose, so the claim differs while the structure repeats."* A diversity count over claims therefore counts *prose variation as diversity* — the flattering direction, which §14.1 rule 2 warns about (*"the direction of the error is always flattering"*, in the baseline context, and the same asymmetry).

**How it is refused without re-implementing anything:** the module never imports `_mechanism` and never reads `MECHANISM_COLUMN`. Its SQL selects `node_proposal.code_hash` and `node.agent_model_id` and nothing else. The structural guarantee is stronger than a guard: a column that is not selected cannot leak into the figure. The docstring states the decision and cites 211's sentence, so a later reader who reaches for the rationale finds the argument rather than the temptation.

**This is also why the module does not take a `StatedMechanism` handle.** A signature that accepted one would make the wrong read reachable.

### 3. **The per-model grouping key is `node.agent_model_id`, joined, and a row whose model is unrecorded is refused rather than bucketed**

*"returns the figure per authoring model"* — the figure is **one number per model**, so the answer is a mapping, not a scalar. The key is 0115's `agent_model_id` on `node` (feature 203's pinned provider/model/version triple, *"a pinned snapshot … the only real guarantee"*, PRD §5a), which is **`NOT NULL` in the migration** and which 207's own schema note explains it deliberately did **not** copy: *"`agent_model_id` is deliberately absent from the table … a reader that wants it joins."* This feature is that reader, and it joins.

The join has three cases and each is decided:

* **a `node_proposal` row whose node exists and carries a model** — counted into that model's bucket;
* **a `node_proposal` row whose node does not exist** — refused, naming the node. 207 refuses this state at write time (`ProposalNodeNotRecordedError`), so a row in it is a database that has lost a node (an FK-less table, a hand edit). Silently dropping it would understate a diversity figure; `COUNT(DISTINCT)` over a join is the classic silent-drop site, and §14.1 rule 2's warning applies;
* **a row whose `agent_model_id` is NULL or blank** — refused, naming the node. The column is `NOT NULL` in the chain, so this is a brought-forward or hand-edited database; a `None` bucket would be a stratum labelled "unknown" that a report would print as if it were a model. 186 makes the identical call for a nullable world id (`IS NOT NULL` in its count) and for an absent table (*"a value the census cannot vouch for into a figure §12.1's ladder blocks dreaming on"*).

Join spelling: a single `LEFT JOIN`-free **inner** `JOIN node ON node.id = node_proposal.node_id`, and the row count is reconciled against `node_proposal`'s own count **before** the grouped count is trusted — so a missing node surfaces as a refusal instead of as a quietly smaller number. That reconciliation is one extra `SELECT COUNT(*)`, and it is the whole of rule 1's "freeze the cohort" made checkable: the cohort the report describes is the cohort the table holds.

### 4. **A campaign with no recorded proposals answers zero clusters, not a refusal — and an absent `node_proposal` table answers a refusal, not zero**

The two states are different facts and 186 argues both directions for its own pair; the assignment here is forced by which state a caller is *reading*:

* **table present, no rows for this campaign** → `tree_diversity == 0`, an empty mapping or a mapping with one zero per (no) model. This is the honest state of a campaign that has not proposed yet — 207's *"a campaign that has not proposed anything yet"* — and a refusal here would make the first call of every campaign an error;
* **no `node_proposal` table at all** → **refuse**, naming the table and 207. There is no history to count, and 207 itself refuses in this state (`ProposalHistoryStoreUnavailableError`; `_connect` creates the table, so an absent table means this member's own DDL has never run). Answering zero would be inventing a measurement — 186's exact sentence for its absent `replay_score`: *"``n_financial = 0`` is a **blocking** answer … a mis-pointed database would halt dreaming with a number this member made up rather than with a refusal an operator can read."* Here zero is not blocking but it is *flattering to a bad agent*, which is worse: it is indistinguishable from "the model wrote one cluster".

The probe is `sqlite_master`, read-only, the idiom 207 (`_NODE_TABLE_EXISTS_SQL`), 232 and 239 all use — restated rather than imported, because a sibling's private constant is not a promise.

### 5. **The answer is a value object with a validating `__post_init__`, and it is not a bare mapping**

`TreeDiversity` holds **one field per model**, and its shape is decided by rule 2 of §14.1's reporting rules — *"Both trivial baselines appear in every table"* — read together with what the sentence asks for. The concrete form:

* `.by_model` — `dict[str, int]`, the figure per authoring model. **This is the feature's return**;
* `.campaign_id` — the scope, carried so a report line is self-describing and a caller cannot confuse two campaigns' figures;
* `.proposals` — how many rows the cohort held in total (the reconciliation in decision 3), so a reader can see the denominator beside the counts. Without it a "3" is uninterpretable; with it, *"3 clusters over 40 proposals"* is the figure §14.1 actually reasons about.

**On the baselines specifically:** §14.1 rule 2's degenerate baseline for a diversity count is **1** — a tree where every proposal is the same mechanism, the lowest value the metric can take and the one a perfectly-converged weak agent produces. It is not a field: it is the *floor*, stated in the docstring and in `TreeDiversity`'s own docstring, and the thing `.by_model` is read against. Adding a `baseline: int = 1` field would be a constant dressed as a measurement. What the class must not do is *hide* the denominator, which is why `.proposals` is a field and not a derived `sum`.

`__post_init__` validates (186's precedent, same three-line shape): every key a non-empty string, every value a non-negative whole int refusing `bool` (the `True is 1` trap 186 and 221 both guard), `proposals` a non-negative int, and — the one check 186 has no analogue for — **no model's count may exceed the cohort size**, because that is the one arithmetic that would mean the join fanned out (a duplicate `node.id`, a second row per node). `campaign_id` must be canonical UUID text.

`.row()` returns a fresh mapping per call — the shape a report writes (186's `.row()`, and the guarantee 223's `observed()` makes) — and it is `.by_model` **plus** the scope and denominator under their own keys, since a row that dropped the denominator is the uninterpretable table rule 2 exists to prevent. Frozen, equal by all three fields, `__repr__` naming the models and the cohort.

### 6. **Duck-typed at the seam, read-only, and the figure is a plain `int`**

The function takes the **207 law or its store** (whatever fronts `history` and a `path`) — duck-typed, not `isinstance`, for the module-loader double-import reason 186 states (`_counting_pool`): `create_app()` re-executes the member under a synthetic name, so the composed store is a *second* `ProposalStore` class object and an `isinstance` gate would refuse the very store the composition seam serves. What is checked is the surface actually called, and it is checked **before anything touches the disk** (186's reasoning: a refusal arriving after a table was created is a validation that ran too late). Two names, not three: `counted`/`recorded_nodes` are deliberately **not** required, because the denominator is read on the connection the clusters are read on (see below) and a required verb that is never called is a shape check that would refuse stores it has no reason to.

**The read is the store's own `path`**, opened read-only here for the counting queries, because the *clustering* half needs the join and 207's `history()` deliberately hands back `PriorProposal` values (feature 206's type, three fields, no model) — using it would mean a second query for the models and a join in Python over a table SQLite can group in one statement.

**As built, the denominator is read on the *same connection* as the grouped read, not through `counted()`.** The plan proposed delegating it to the store's own verb (186's `world_count()` move); building it showed the stronger form, and the difference is worth stating. `counted()` opens its *own* connection, so a delegation would read the cohort in one transaction and the clusters in another — and a writer recording on another thread between them would leave the figure describing a cohort the table no longer holds, which is precisely the drift the sentence *"so the figure cannot describe a cohort other than the one the table holds"* claims cannot happen. One connection makes rule 1's *"freeze the cohort"* a property of the read rather than a comparison a caller has to make. It also drops an optional verb from the seam: `_proposal_history` checks `history` and `path` and needs nothing else, and the store's `counted()` remains available — and remains what a *driver* uses — without this feature depending on it.

**The returned counts are plain `int`**, deliberately not a wrapper type. 221's `StatisticalBudget` is a `float` subclass because a policy compares it in authored code and the denomination is the feature; here the consumer is a report, the denomination is in the attribute name (`by_model`), and a wrapper would only add an unwrap. `int` is also what makes the value JSON-serializable into a campaign manifest with no adapter — §14.1's cohort is a *report*.

**No new error class.** Every refusal here is a fact about the *store, the tree or the cohort* — not about a proposal, not about a source, not about a theme. The repairs are: run 207's DDL, fix the tree, fix the row. 207's own `ProposalHistoryStoreUnavailableError` and `ProposalNodeNotRecordedError` already name two of them, and the member's discipline (186's *"no fourth error class"*, 223's decision 6) is that a new class must buy a distinction a caller's `except` can act on.

**As built, one class was minted anyway: `DiversityCohortError`** — and the reversal is worth recording, because the plan's proposed alternative (`ProposalContentError`) does not survive contact with that class's own docstring. `ProposalContentError` is 207's *"a document a caller is about to store is wrong"*: its repair is *fix the document before writing it*. Three of this feature's refusals have that repair and belong nowhere near it — the tree has not reached `0115` (**run the migration**), a handle is not a proposal history (**pass the store**), and a `campaign_id` is not a UUID (**fix the argument**). A caller's `except ProposalContentError:` handler exists to re-validate a proposal document; letting it catch *run the migration chain* is the error-vocabulary failure this member's own suite already pins for other seams. So `DiversityCohortError` is a **sibling of `AgentSourceError`**, in the same relation `MechanismColumnError` and `ProposalNodeNotRecordedError` stand in, with the member's three-repairs distinction stated in its docstring. The count of classes is unchanged from the plan's intent — one new name, argued — not one per refusal.

### 7. **`real branches` is not this feature's filter — and the module says why in one sentence**

§14.1's `mechanism_discrimination` line carries `| real branches`; the `tree_diversity` line does **not**. Two facts reinforce it: the *real / null* discriminant lives where the evaluation ran (`replay_score`/target path; `is_null` is *"absent from the tree store entirely"*, app_spec 447, and *"never which returns is_null in any form"*, 456), and `node_proposal` records no such flag. So this feature applies **no null filter**, and the docstring records that this is a reading of the spec's own two lines rather than an omission — a later reader who notices the asymmetry finds it already answered. If a null filter is ever wanted, the flag has to exist first, and that is a different feature.

### 8. **No component, no seat, and the member's `__init__` widens by exactly one import block**

Reached directly: `from signal_agent import tree_diversity`. `src/app/modules/signal-agent/` gains **no new file** — the directory's convention is *one seat per composed component*, and this feature composes nothing; 230/231 (also componentless) are reached from the member and the seat module says so in its own docstring. Adding a seat for a pure function would be a second spelling to keep in sync.

## Files

**Layout (the plugin's own directory — auto-discovery; no central registry is touched):**

| path | change |
|---|---|
| `packages/signal-agent/src/signal_agent/_diversity.py` | **new** — the law: two SQL constants, `TreeDiversity`, `tree_diversity()`, the seam check |
| `packages/signal-agent/src/signal_agent/__init__.py` | **edit** — one import block + `__all__` entries + a docstring paragraph for feature 215 |
| `packages/signal-agent/src/signal_agent/errors.py` | **edit** — `DiversityCohortError` + its `__all__` entry (decision 6's reversal, argued there) |
| `packages/signal-agent/tests/test_diversity.py` | **new** — the feature's suite |
| `packages/signal-agent/tests/conftest.py` | **edit** — add the fixtures the new suite needs (a `node_proposal` + `node` database built through the real migrations) |
| `.plans/feature-215-tree-diversity.md` | **new** — this plan |

**No edit** to: `src/app/middleware.py`, `src/app/settings.py`, `migrations/versions/**`, `alembic/versions/**`, any registry/router/entry-points table or app factory, or any other package. **No migration is written** — this feature reads two tables it does not own (207's `node_proposal`, 0118's `node`) and creates nothing.

## Tests

`packages/signal-agent/tests/test_diversity.py`, built on a real database from the **real migrations** (`0118_node_table` + `0117_identity_trio` + `0115_agent_model_trio` + `0114_node_metrics` + `0113_node_indexes` **last**, loaded by file path — the conftest's established discipline) plus 207's own `ProposalStore.persist` writes, so the rows the counter reads are rows the real writer produced.

**As built, 24 cases, all passing** (`packages/signal-agent/tests/test_diversity.py` — the 12 planned headings, with case 5, 10 and 12 each split into their behavioural and structural halves), and two facts the plan did not have:

* **`0113` must be applied last, or not at all.** It creates no column and no table — three `CREATE INDEX` statements, on `(campaign_id, parent_id)`, on `code_hash` and on `agent_model_id` — so it depends on *three* other migrations' columns, and on SQLite an index against a missing column is an `OperationalError` rather than a silent no-op (0113's own docstring records the measurement). The fixture's first draft applied the dispatcher's order and died with `no such column: code_hash`. Workable order: `0118`, `0117`, `0115`, `0114`, `0113`.
* **`0116` is deliberately absent from the fixture.** Its three `NOT NULL` provenance hashes are features 70/§4.2/60's subjects and this suite can only plant placeholders — a fabricated `evaluator_hash` is not a more honest row than an absent one, it is a row that looks evaluated. Stopping the chain at the columns this feature groups by keeps every row's fields meaning what they say, and keeps `plant_node`'s `PLANTED_CONSTRAINED_COLUMNS` claim about 0117 exactly true.

Cases:

1. **the feature's sentence** — three nodes, two models, code hashes distributed so model A has 2 clusters over 2 proposals and model B has 1 over 3; asserts `by_model == {"A": 2, "B": 1}` and `proposals == 5`;
2. **per-model is the point** — the same campaign's *pooled* distinct count is 2 and one model's *own* count is 2 while the other's is 1; asserts the figure is not the pooled number repeated;
3. **a cluster is a `code_hash`, not a skeleton** — two proposals differing **only in a numeric literal** are **two** clusters (the assertion that pins decision 1, and the one that would silently pass if `skeleton_digest` had been borrowed);
4. **identical documents are one cluster** — the same document recorded against two nodes is one cluster over two proposals (the other half of decision 1);
5. **`stated_mechanism` never enters** — two nodes with the *same* stated mechanism and *different* code hash are two clusters; and the module is asserted **not** to select the column (a source-level assertion over the module's own SQL constants), pinning decision 2;
6. **empty campaign is zero** — a campaign with no recorded proposals answers zero clusters, and the answer is a real `TreeDiversity`, not a refusal;
7. **absent table is a refusal** — a database with no `node_proposal` table raises `ProposalHistoryStoreUnavailableError` naming it; asserts it does **not** answer zero;
8. **a row whose node is gone is refused** — a `node_proposal` row inserted against a node id the tree does not hold raises, naming the node; asserts the reconciliation of decision 3 (a silently-smaller count fails this test);
9. **a NULL model is refused, not bucketed** — a NULL `agent_model_id` raises rather than producing an `""`/`None` stratum;
10. **the value object's invariants** — a count exceeding `proposals`, a negative count, a `bool` count, and a non-UUID `campaign_id` are each refused; equality and frozen-ness hold; `.row()` is fresh per call (`is not` across two calls, `==` by value) and carries the denominator;
11. **the seam** — a non-store (a string, an object with no `history`) is refused before the disk is touched (asserted by pointing it at a path that does not exist and checking the refusal names the *shape*, not the file);
12. **no null filter, and the module has no write path** — a tree carrying no null flag counts every row (decision 7), and the module's source is asserted to contain no `INSERT`/`UPDATE`/`DELETE` (decision 6's read-only claim).

Then the **composed** check in `test_component.py`'s idiom is deliberately **skipped** — there is no component to compose and no seat to reach — and that absence is itself asserted once in the new suite (the feature is exported from the member and appears in no registry), so a later feature cannot add a component for it without a test noticing.

**Run both suites** (memory: the acceptance gate collects `tests/` only and a member suite is **not** graded):
* `PYTHONPATH=src:packages/signal-agent/src uv run pytest packages/signal-agent -q` → **578 passed** (554 before this feature; `test_diversity.py` contributes 24);
* `uv run pytest -q` at the root → **1060 passed**;
* ruff **on the files I touch only**, compared against a sibling (`_proposal.py`) — repo lint is red on main. `_diversity.py`, `errors.py`, `conftest.py` and `test_diversity.py` are **clean**; `__init__.py` reports exactly its HEAD baseline (1 pre-existing `F811` on `PROPOSAL_HISTORY_COMPONENT_NAME`, verified with `git show HEAD:… | ruff check --stdin-filename … -`), so this feature adds no finding.

## Out of scope

* **feature 214** (`mechanism_discrimination`, the IS/OOS correlation) and **216** (persisting it per candidate model) — no correlation is computed, no metric pair is read, nothing is persisted;
* **feature 207's store** — written by that feature; this one only reads (`path`, `counted` where available), and edits no file in it;
* migration/alembic edits, `src/app/middleware.py`, `src/app/settings.py`, the app factory, any registry, and any seat file under `src/app/modules/signal-agent/`;
* a persisted diversity row, a baseline field, a null-branch filter, and a pooled-across-campaigns figure — each declined in the docstring with its reason.
