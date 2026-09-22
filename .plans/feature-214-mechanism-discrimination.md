# Feature 214 — `mechanism_discrimination`, persisted per campaign

**app_spec.xml, "Hypothesis Authoring Agent", feature 214** (`plugin="signal-agent"`, `depends_on=207`):
*System persists mechanism_discrimination per campaign, computed as the correlation between in-sample gain and out-of-sample gain across real branches.*

Authoritative spec: docs/nullius-tech-architecture.md §14.1 (line 861), inside the "Measuring model adequacy on this task" block:

```
mechanism_discrimination = corr( IS_gain, OOS_gain | real branches )
tree_diversity           = distinct mechanism clusters per campaign
```

with the paragraph that reads the first line (line 865):

> A strong agent produces refinements whose in-sample improvement *predicts* sequestered-epoch improvement. A weak agent produces noise-chasing variations and the correlation **collapses even on real branches**.

the paragraph that says when it is run and why it exists (line 867):

> **Run this at M2, before the M3 gate.** Two campaigns per candidate model, roughly $60. Skip it and a weak signal agent will present as a failed thesis, and you will disprove the wrong hypothesis.

the M2 gate's own wording (line 994), which is where "fixed exploration" comes from:

> | **M2** | … | Baseline sensitivity, specificity and **per-commit OOS IR under fixed exploration** |

and the reporting rule that is this feature's shape constraint (line 877):

> 3. **Calibration beside accuracy.** `mechanism_discrimination` is a correlation; **report its interval, not the point** (`design.md` §9).

Paired with feature 216 (`depends_on="214"`): *"System persists mechanism_discrimination per candidate model before the gate milestone, so a weak agent is not misread as a failed thesis."*

## Context — why this feature, and what it is not

Feature 207 built the writer: `node_proposal` holds, per node, the proposal document plus a snapshot of the seven metrics the evaluation wrote. Feature 215 (`tree_diversity`) landed as its first reader. Feature 214 is **the second reader, and the only one that also writes**: it correlates each real branch's *in-sample* gain against the *out-of-sample* gain its commits earned, and persists one reading per campaign.

`additions_spec_207.xml:109` names both readers from the writer's side: *"depended on by features 214 and 215 (mechanism discrimination and tree diversity, which read the persisted score records across a campaign's real branches)"*.

**What it is not:**

* it is **not feature 215**. 215 counts *clusters* and returns a figure; 214 correlates a *pair of metrics* and persists the figure. 215's own module docstring draws the line: *"It is not feature 214's correlation — that is a different statistic over a different pair of columns (the metric pair, keyed on the real/null discriminant)"*, and *"`§14.1`'s sentence for 214 is `persists mechanism_discrimination per campaign` while 215's is `computes … which returns the figure`, so the figure is a returned value with no row behind it."* 215's `test_diversity.py` asserts its module has **no write path**; this feature's has exactly one, into its own table;
* it is **not feature 216.** 216 is the *per candidate model* stratification. §14.1 budgets *"two campaigns per candidate model"*, so at M2 the campaign is already the model's unit and 214's sentence stays per campaign. What this feature leaves 216 is the **frozen cohort**: the row carries a digest of the pairs the figure was computed over, so 216's stratified reading can be shown to be over the same inputs;
* it is **not feature 123's KS guard** (`nulloracle.ksguard`), though it borrows that feature's *persistence shape* wholesale (one row per campaign, primary key = campaign, refresh-not-append, measure-before-write, read-back). 123 measures whether nulls are *detectable*; this measures whether in-sample improvement *predicts* out-of-sample improvement. Two different questions about the same campaign;
* it is **not a null-branch detector**, and this is the feature's hardest boundary — see decision 2.

## The house shape this follows (do not invent a new one)

Two precedents, each covering one half of the sentence:

* **the counting/computing half** — feature 186's `world_census` and feature 215's `tree_diversity`: a free function over a duck-typed handle, stdlib-only, refusals that name the losing revision, no `@register`;
* **the persisting half** — feature 123's `nulloracle.ksguard`: a store class plus two module functions (`persist_*` / `load_*`), the arithmetic split from the store so it can be exercised with no database in the way, one row per campaign, `CREATE TABLE IF NOT EXISTS` on a table this member owns, measure first so a refused reading leaves no row, and a read-back so the value a caller is handed is the value the store holds.

**No component and no seat**, by feature 185's argument rather than 215's: `bootstrap._trial` owns `bootstrap_trial` and resolves the **same** `DATABASE_URL` the pool resolves, and deliberately registers no second component, because *"a second store over the same URL would be two names for one deployment fact"*. This feature's store must point at the very database 207's proposal store points at — the figure joins `node_proposal` to `replay_score` inside one file — so 207's component (`signal-agent-proposal-history`) is already the deployment seat for it. A tenth `signal-agent-*` name would be a second name for one fact; `src/app/modules/signal-agent/` gains no seat file for the same reason.

## Design decisions

### 1. **The in-sample gain is `ir_marginal` from 207's stored score record — the one metric that is a gain by definition**

Seven metrics sit in the score snapshot (`0114`'s columns, feature 101). *"In-sample **gain**"* selects one, and the selection is forced rather than chosen: exactly one of the seven is defined as a difference.

docs/alpha-engine-prd.md §6.2 states it as an equation — `ir_marginal(v | book) = IR(book ∪ {v}) − IR(book)` — and §6.1 step 9 is the step that computes it (*"marginal_ir — orthogonalize vs. current book → ir_marginal"*). Feature 83's module docstring names the column as its landing place. `ir_standalone` is a *level* (the equal-weight book's IR, feature 80), `ic_mean`/`ic_tstat` are the correlation and its t-statistic, `turnover` and `cost_adjusted_ir` are costs, `perturb_stability` is robustness. §14.1 says *"refinements whose in-sample **improvement** predicts sequestered-epoch improvement"* — a difference — and `ir_marginal` is the difference the evaluator measured, against the same book the pick would join.

**Read from the snapshot, not from `node.ir_marginal`.** 207 snapshots the metrics at the moment the round read them, and its own docstring says why: a history that joined `node` *"would therefore answer a different question each time it was asked: what does this node score now? rather than what did this proposal score when the round read it?"* — and feature 240 refreshes `node` in place on every retry, so the live column genuinely moves. §12's determinism wants a completed reading to be re-readable, so the IS half comes from the pair feature 207 froze. This is also what 215's docstring promises of 214: *"the persisted score records"*.

**Not a difference against the parent.** `node.parent_id` exists and "refinement improvement" could be read as `child − parent`. Refused: the evaluator persists no per-parent delta, so computing one here would be an arithmetic this module invented — the direction §14.1's rule 2 warns about (*"the direction of the error is always flattering"*) — and it would make every root (no parent) unmeasurable, while the book-relative gain is measured for every node the evaluator reached.

A `None` `ir_marginal` is **not** a zero: 207's own law is that *"a `None` metric is an absent measurement, not a zero"* (0114 declares all seven nullable because *"a pre-metric row has no honest value to assert"*). A cohort member whose snapshot carries no `ir_marginal` is refused by name.

### 2. **The real-branch cohort is a required argument, never derived — and the module cannot name `is_null`**

This is the feature's load-bearing call. §14.1's formula carries the qualifier `| real branches`; the discriminant is `is_null`, and **it is not readable from any store this member may open**:

* §7.1: *"There is no `is_null` column anywhere in the tree store. Not hidden, not nulled out, not `SELECT`-excluded. **Absent.** The only way to learn a node's status is to hold the sidecar key"* — and the sidecar is *"readable by ONE service account"*;
* §4.2: `is_null` *"is visible to exactly one component: the replay scorer"*;
* app_spec 447 (feature 110): *"System keeps is_null absent from the tree store entirely, which rejects any proposed node column named is_null"*; app_spec 456 (feature 113): the endpoint *"never which returns is_null in any form"*; app_spec 354 the merge gate: *"System rejects the merge when any symbol named is_null is reachable outside the scorer package"*;
* 207's `node_proposal` records no such flag, and 215's suite already pinned that there is *"nothing to filter on"*;
* even the machinery that knows — feature 123's guard row — *"carries counts, not scores, and not one node id"*.

So the cohort is **declared by the caller**, and that is the same shape §7.4 already sanctions for the one other job that needs the partition: *"a job holding the sidecar key runs a two-sample KS test on in-sample score distributions, null nodes vs. real nodes"*. The signature takes `real_branches` — an iterable of branch ids the caller knows to be real — and the module:

* **never names `is_null`**, in a symbol, a constant or a string: this feature is built so invariant 354 stays true, and the suite asserts the token appears nowhere in the module;
* **refuses to default it**, so a caller cannot "just correlate everything" and get a number that silently mixes the exactly-zero half;
* **cannot verify the cohort's membership**, and says so plainly rather than pretending otherwise. What it can do is make the cohort it was given *auditable*, which is decision 5's digest.

**Why the filter is not cosmetic.** §4.1: *"true out-of-sample edge of a null branch is **exactly zero by construction**"* — a null branch contributes points whose y is ~0 whatever their x, which attenuates the correlation mechanically. §14.1's warning is that the collapse must remain visible *even* after that half is removed. Correlating over a mixed cohort would therefore flatter a weak agent twice: once by attenuation and once by giving a null-heavy tree more points.

`real_branches` is required, positional-or-keyword, and named for the spec's own phrase.

### 3. **A branch is one point: the out-of-sample gain is the mean of the scores the runs committed to it earned**

`replay_score` (0109, feature 255) is one row per *(policy, world)* run carrying `policy_version`, `world_id`, `beta`, `score`, `committed_pick` and `is_holdout`. Feature 256 fixes what `score` is: *"the per-world objective **starting from out-of-sample information ratio of the committed pick**"* — the out-of-sample reading of a pick, which is precisely the M2 gate's *"per-commit OOS IR"* and the number §14.1's second sentence means by *"sequestered-epoch improvement"*.

Two readings of the pairing were available:

* **per branch** (chosen) — the sentence's unit is the branch (*"across real branches"*), so a refinement committed in several worlds is **one** point: the mean of the scores its commits earned. The alternative — one observation per run — repeats the same x for every world the branch was chosen in, so a single much-picked node would carry the correlation by frequency rather than by contrast, and the figure would stop being a statement about the *cohort of refinements*;
* **per commit** (refused, recorded here) — no aggregation at all, but the branch is then no longer the unit, and `n` becomes a count of runs.

The mean is over exactly the rows that name the branch, and the value object carries **both denominators**: `pairs` (branches) and `runs` (rows drawn on). §14.1's rule 2 (*"a metric reported without its constant baseline is uninterpretable"*) read as a structural requirement: a correlation printed without the number of points behind it is a number nobody can check.

**A cohort member with no run is refused, not dropped.** Rule 1 is explicit — *"A cohort assembled after seeing results is a selection, not a sample"* — and a figure computed over whatever subset happened to have both halves is a cohort assembled after the fact *by availability*, which is the same failure one step removed. So every declared branch must supply both halves, and a missing half is refused by name, saying which half.

**A campaign whose runs span more than one `policy_version` is refused.** §14.1's instrument runs at M2 *"under fixed exploration"* (arch §994), and rows under two revisions are two policies' commits; correlating across them would attribute one policy's discrimination to a campaign. An optional `policy_version` **filter** was the alternative and is refused for rule 1's reason: a filter lets a caller silently correlate a subset of the campaign's runs — a cohort assembled after seeing results, by hand.

### 4. **The floors are §14.1's rule 3, and they are refusals rather than a `0.0`**

*"Report its interval, not the point"* is not a formatting instruction, it is the feature's floor. The interval is Fisher's z-transform (`z = atanh(r)`, `se = 1/√(n−3)`, `tanh(z ± 1.96·se)`), computed with `statistics.NormalDist().inv_cdf` — stdlib, no magic constant — and it forces **`pairs ≥ 4`**: below that `n − 3 ≤ 0` and no interval exists, so there is no reading to report under the rule. (The campaign planner's floor of two real roots, PRD §121, is a *planning* floor and sits below this one; a campaign planned to its own floor still cannot be *reported* on, and rule 3 is why.)

Refused rather than answered with something, each naming itself:

* **`pairs < 4`** — no interval can be formed;
* **a constant series on either side** — a correlation with no variance is undefined, and `0.0` would be a *claim* (no discrimination) where the truth is that the cohort cannot answer; the flattering/unflattering direction cuts both ways here, which is exactly why the answer is a refusal;
* **`|r|` at exactly 1** — `atanh(±1)` diverges, so an exactly perfect correlation admits no interval under the transform either (the Pearson value is clamped into `[-1, 1]` first, so a float overshoot of 1.0000000000000002 lands on the same refusal);
* **a non-finite gain** — `∞`/`NaN` in a snapshot (Python's `json` decoder accepts `Infinity`) or in a `REAL` column is a measurement that failed, not a large one.

An empty cohort is refused by the same argument: a Type-R campaign whose draw left no real branch must be told so, not handed a figure about nothing.

### 5. **The row is this member's own table, and it carries a digest of the frozen cohort**

`campaign` (0111) carries `ks_pvalue` and `calibration_status` and **no** discrimination column; `migrations/versions/**` is core-task territory this feature must not edit. So the reading lives in a table this member owns and creates lazily — `campaign_discrimination`, the precedent `bootstrap_world` (188), `depth_run_window` (202), `bootstrap_trial` (185), `depth_cache_rate` (200) and 207's own `node_proposal` all set — under feature 123's exact grain: **`campaign_id` is the primary key**, so a re-reading refreshes rather than appends, and the store **refuses a campaign it does not hold** (*"a p-value is a fact about a campaign, and writing it onto a row this store invented would fabricate the campaign the number belongs to"* — 123's sentence, true here word for word).

**Unlike 123, there is no headline column to mirror onto, and therefore no half to reconcile.** 123 writes `campaign.ks_pvalue` *and* its provenance row in one transaction and refuses a reader that sees one without the other. This feature may not add a column to a shared table, so the member-owned row **is** the record — and the defence 123 gets from reconciliation is taken instead by *reconstruction*: the read path rebuilds the value through its own validating constructor, so a hand-edited row (a correlation outside `[-1, 1]`, a point outside its own interval, `runs < pairs`) fails to load rather than loading as a plausible-looking reading.

**The cohort digest is rule 1 made structural.** §14.1: *"Freeze the cohort before any model runs, and hash its inputs."* The row carries `sha256` over the exploration policy and the ordered `(node_id, is_gain, oos_gain)` triples, in node-id order so two callers freezing the same cohort in different orders hash alike. A report that publishes a figure then publishes the hash of the inputs behind it, and a re-computation over a different cohort is *visible* as a different digest. This is the honest limit of what the module can do about a cohort it cannot verify (decision 2): it cannot prove membership, so it makes the input auditable.

### 6. **One new error class, and 207's two reused where they name the same prerequisite**

Refusals split by *repair*, the member's standing test:

| what happened | repair | class |
|---|---|---|
| the handle is not 207's law/store | pass the proposal-history store | **`DiscriminationCohortError`** (new) |
| the campaign id is not UUID text, the cohort is not a set of UUIDs, or is empty | fix the argument | **`DiscriminationCohortError`** |
| the store holds no `campaign` row (or no `campaign` table) | run the chain to `0111` | **`DiscriminationCohortError`** |
| no `replay_score` table | run the chain to `0109` | **`DiscriminationCohortError`** |
| a cohort member has no recorded proposal / no `ir_marginal` | freeze a cohort the store can pair | **`DiscriminationCohortError`** |
| a cohort member has no committed run | same | **`DiscriminationCohortError`** |
| the runs span policy versions | fix the exploration to one revision | **`DiscriminationCohortError`** |
| too few pairs, a constant series, `\|r\| = 1`, a non-finite gain | the cohort cannot answer | **`DiscriminationCohortError`** |
| no `node_proposal` table | run 207's DDL | `ProposalHistoryStoreUnavailableError` (207's, unchanged) |
| no `node` table | run the chain to `0118` | `ProposalNodeNotRecordedError` (207's, unchanged) |
| a stored score record that does not parse | the row is corrupt | `ProposalContentError` (207's, unchanged) |

`DiscriminationCohortError` is a **sibling** of `DiversityCohortError`, not a reuse of it: the two name different objects (*a cohort of pairs* vs *a cohort of proposals*) and a caller's handler for one must not silently accept the other — the same relation `MechanismColumnError` and `ProposalNodeNotRecordedError` stand in, and the argument 215 gives for not folding its own refusals into `ProposalContentError`. It is deliberately **not** an `AgentSourceError`: nothing here is about a proposal's source, and no re-prompt repairs a cohort.

### 7. **The store's path and the handle's path must be the same file**

The figure joins `node_proposal` (207's table, in the store `history` names) to `replay_score` (0109's, in the same database) *inside one SQL statement*, so the two must be one file. A store pointed elsewhere would write the reading into a database the cohort is not in. Refused by name rather than left to produce a `no such table` from the wrong SQLite file — feature 185's *"one deployment fact"* argument made checkable.

### 8. **No component, no seat, and nothing written outside this feature's footprint**

Reached as `from signal_agent import ...`, exactly as 186's `world_census` and 215's `tree_diversity` are. No `@register`, so `test_the_nine_laws_stay_contiguous_in_the_name_sorted_order` stays true unchanged and `src/app/modules/signal-agent/` gains no file. No migration, no `campaign` column, no edit to `middleware.py`, `settings.py`, the app factory, any registry or any other package.

## Files

| path | change |
|---|---|
| `packages/signal-agent/src/signal_agent/_discrimination.py` | **new** — the law: the SQL constants, `MechanismDiscrimination`, `DiscriminationStore`, `persist_mechanism_discrimination`, `load_mechanism_discrimination`, the arithmetic |
| `packages/signal-agent/src/signal_agent/errors.py` | **edit** — `DiscriminationCohortError` + its `__all__` entry |
| `packages/signal-agent/src/signal_agent/__init__.py` | **edit** — one import block, `__all__` entries, one docstring paragraph |
| `packages/signal-agent/tests/conftest.py` | **edit** — `create_discrimination_schema`, `plant_campaign`, `plant_run`, `record_gain`, two fixtures |
| `packages/signal-agent/tests/test_discrimination.py` | **new** — the feature's suite |
| `.plans/feature-214-mechanism-discrimination.md` | **new** — this plan |

**No edit** to: `src/app/middleware.py`, `src/app/settings.py`, `migrations/versions/**`, `alembic/versions/**`, any registry/router/entry-points table or the app factory, or any other package.

## Tests

`packages/signal-agent/tests/test_discrimination.py`, on a database built from the **real migrations** (`0118`, `0117`, `0115`, `0114`, `0113` **last**, plus `0109` for `replay_score` and `0111` for `campaign`), with the in-sample half written by **207's own `ProposalStore.persist`** (carrying an explicit `ScoreRecord`) and the out-of-sample half inserted into `0109`'s table — the replay member has no writer in this workspace yet, so the fixture writes those rows and says so, the way 215's suite writes its orphan row by hand for the one state the real writer refuses.

Cases (headings):

1. **the sentence** — a cohort of real branches with both halves; the correlation and both interval bounds equal an independent `statistics.correlation` + `math.atanh/tanh` computation in the test; `pairs` and `runs` are the counts the store holds;
2. **`persists`** — the row exists in `campaign_discrimination` after the call, and the returned value equals what `load` reads back (the read-back discipline);
3. **the IS half is the snapshot, not the live column** — a node whose live `node.ir_marginal` disagrees with the recorded snapshot; the figure follows the snapshot;
4. **the OOS half is the mean of the branch's runs** — one branch committed in three worlds contributes one point at the mean, and `runs` counts the rows drawn on;
5. **`| real branches` is the caller's declaration** — a branch in the store that is *not* in the cohort is excluded from both the arithmetic and the counts; the module names no `is_null` token anywhere in its source, and imports no sibling member (structural, both halves);
6. **a declared branch with a missing half is refused** — no recorded proposal; a recorded proposal whose snapshot carries no `ir_marginal`; no committed run — each naming the branch and the half;
7. **a declared branch from another campaign is refused** by name;
8. **the floors** — three pairs, a constant in-sample series, a constant out-of-sample series, an exactly ±1 correlation, an infinite score: each refused, none answered with a number;
9. **one policy version** — runs under two revisions are refused, naming both;
10. **the store refuses a campaign it does not hold**, and writes nothing when any refusal fires (the measure-first ordering, asserted by counting rows);
11. **refresh, not append** — a second reading over a changed cohort leaves one row, and the second reading is what `load` answers;
12. **the path check** — a store pointed at another database is refused;
13. **the value object's invariants** — a correlation outside `[-1, 1]`, a point outside its own interval, `pairs < 4`, `runs < pairs`, a `bool` count, a non-UUID campaign id, a short digest: each refused at construction; equality and frozen-ness hold; `row()` is fresh per call and nests the interval;
14. **the frozen cohort** — the digest is stable under a re-ordered cohort and changes when a gain changes (rule 1);
15. **a hand-edited row fails to load** — a correlation of `2.0` written straight into the table is refused on read;
16. **no component and no seat** — the feature is exported from the member, `signal-agent-discrimination` appears in no composed application, and this directory gains no seat file.

Then both suites: the member's own (`PYTHONPATH=src:packages/signal-agent/src uv run pytest packages/signal-agent -q`, **578 passed** before this feature) and the repository gate (`uv run pytest -q`), with the real measured numbers recorded here rather than guessed. Ruff on the touched files only, compared against a sibling — the repo lint is red on main.

## Out of scope

* **feature 216** (per candidate model) — this row is per campaign, as 214's sentence says; the cohort digest is what lets 216's stratified reading be over the same frozen inputs;
* **feature 215** — read-only here, and edited nowhere;
* **feature 123's guard, the sidecar and every `is_null`-bearing symbol** — this module names none of them and reads none of them;
* a migration, a `campaign` column, a component, a seat file, a per-model figure, a per-commit observation, a `policy_version` filter, and any derived gain (parent difference, `ir_standalone`, `cost_adjusted_ir`): each declined in the module docstring with its reason.
