# Feature 216 — `mechanism_discrimination`, persisted per candidate model

`app_spec.xml`, "Hypothesis Authoring Agent":

> System persists mechanism_discrimination per candidate model before the gate
> milestone, so a weak agent is not misread as a failed thesis

`shape="plugin"`, `plugin="signal-agent"`, `depends_on="214"`.

## Context — why this feature, and what it is not

Feature 214 persists §14.1's model-adequacy correlation **per campaign**, and its
own plan states what it leaves here:

> What this feature leaves 216 is the **frozen cohort**: the row carries a digest
> of the pairs the figure was computed over, so 216's stratified reading can be
> shown to be over the same inputs.

Two authorities say why the stratification is not optional. PRD §13 invariant 5a
(line 640):

> Every node records `agent_model_id`. Provider aliases re-route silently; a
> pinned snapshot or a self-hosted checkpoint hash is the only real guarantee.
> **M3 results are reported per model stratum as well as pooled.**

and architecture §14.1 (line 791, mitigation 3):

> **Record and stratify.** `agent_model_id` is indexed for exactly this; report
> M3 results per model stratum as well as pooled.

The purpose clause in 216's own sentence is the sharper statement of the same
thing, and it is a *risk row* before it is a feature. PRD §14 (line 662):

| Failure | Likelihood | Mitigation |
|---|---|---|
| Agent model silently re-routed mid-pool | High | `agent_model_id` per node; self-host pinned weights for M3-feeding campaigns; stratify (arch §14.1) |

and the risk row this feature exists for (line 663):

| Failure | Likelihood | Mitigation |
|---|---|---|
| **Signal agent too weak, read as a failed thesis** | High | Measure `mechanism_discrimination` at M2, before the gate (arch §14.1) |

§14.1's instrument paragraph carries both the timing and the budget (line 867):

> **Run this at M2, before the M3 gate.** Two campaigns per candidate model,
> roughly $60. Skip it and a weak signal agent will present as a failed thesis,
> and you will disprove the wrong hypothesis.

"Two campaigns per candidate model" is the grain in one clause: at M2 the unit of
the *reading* is the campaign (214's) and the unit of the *comparison* is the
model (this feature's). A pooled figure over both models is what lets a weak
agent's collapsed correlation be read as the thesis failing rather than the
agent failing — which is the failure the sentence names.

**What this feature is not.**

* It is not 214. 214 computes and persists the figure *per campaign* over a
  caller-declared real-branch cohort; this persists the same figure *attributed
  to one candidate model*, into its own table, with its own frozen-cohort digest.
  214 is edited nowhere.
* It is not 215. 215 *derives* its strata by `GROUP BY node.agent_model_id` over a
  whole campaign's proposals and returns a mapping with no row behind it; here the
  model is a **declared and verified** input and the figure is written down.
* It is not a gate, a milestone state, or a verdict. No milestone is a value in
  this workspace (see decision 6); "before the gate milestone" is a *timing*
  claim, and decision 6 makes it structural rather than a check.
* It is not the pooled figure. 214 owns that row, and this feature cannot produce
  one (decision 2).

## The house shape this follows (do not invent a new one)

* **A member-owned table created lazily** with `CREATE TABLE IF NOT EXISTS`, never
  declared in the shared migration chain — the precedent `bootstrap_world` (188),
  `depth_run_window` (202), `bootstrap_trial` (185), `depth_cache_rate` (200),
  `node_proposal` (207), `campaign_ks_guard` (123) and 214's own
  `campaign_discrimination` all set. `migrations/versions/**` is core-task
  territory and is not edited.
* **Refresh, not append**: the primary key is the grain, and a re-reading
  refreshes the row (123's grain, 214's).
* **Measure before writing**, so a refused reading leaves no row claiming it
  happened (123's ordering, 214's).
* **One new error class**, a *sibling* of the member's others, with 207's and
  214's classes reused unchanged where they name the same fact and the same
  repair.
* **No component and no seat file.** The reading resolves no configuration of its
  own — the tables, the column and the figure's shape are facts about state
  existing builders expose — so it is a free function reached as
  `from signal_agent import mechanism_discrimination_by_model`, exactly as 186's
  `world_census`, 215's `tree_diversity` and 214's `mechanism_discrimination`
  are. `src/app/modules/signal-agent/` gains nothing.
* **Stdlib only** at module scope, so the factory's scan pays nothing for this
  module.

## Design decisions

### 1. **The candidate model is a declared argument, verified against the tree — not a derived stratum**

`mechanism_discrimination_by_model(history, campaign_id, model, real_branches)`,
where `model` is an `agent_model_id` string and `real_branches` is the same
caller-declared cohort 214 takes. Every declared branch's `node.agent_model_id`
is read and required to equal the declaration, by name, before any figure is
computed.

Two alternatives were available and both are refused:

* **Derive the strata** by grouping the declared cohort by `node.agent_model_id`,
  the way 215 groups. Refused because a cohort is the one thing this member may
  not assemble after the fact (214's rule 1, argued at `_validated_cohort`), and
  because deriving would *tolerate* the exact provenance failure §14.1 calls
  "not hypothetical": a campaign run in August and re-run in September under the
  same model string, silently serving a different model, would stratify into two
  tidy small-`n` rows rather than being refused. Stratifying around a mixed pool
  is what §14.1's mitigation 3 asks of the **M3 paired comparison**; the M2
  instrument is asked to *measure a candidate model*, and a figure attributed to
  a model that did not author every branch in it is the misreading the sentence
  exists to prevent.
* **Derive the cohort** from the model (`all of this model's recorded branches`).
  Refused for 214's reason word for word: §14.1's formula carries `| real
  branches`, the discriminant is not readable from anything this member may open
  (§7.1, §4.2), and the store holds both halves. A model-scoped cohort of every
  proposal would mix the exactly-zero half in.

**Why a declaration is checkable here when realness is not.** 214 cannot verify
its cohort, and says so; this feature can, because `agent_model_id` is a column
on a table this member may read (§9.1 line 405, indexed at line 418 for exactly
this stratification). That asymmetry is the feature: the stratum is the half of
the reading that *is* verifiable, so a mismatch is refused rather than hashed and
reported.

### 2. **There is no default model and no pooled answer**

A missing, blank or non-string model is refused; an "all models" request is
unrepresentable in the signature. §14.1's own diagnosis of the failure is a
*pooled* reading — *"a weak signal agent will present as a failed thesis"* — and
the architecture's answer is a per-stratum report. A default would restore the
pooled read by omission, which is the one thing this feature must not offer, so
the argument 214 makes for refusing a default cohort (*"a caller that could just
correlate everything would get a number that silently mixes the exactly-zero
half"*) is made here one level up: a caller that could just ask for "the figure"
gets the number this feature exists to prevent.

The pooled figure is not lost — it is 214's, per campaign, in
`campaign_discrimination`, one call away. What this feature declines is producing
it *instead of* the stratified one.

### 3. **The grain is the `(campaign_id, model)` pair, in a table this member owns**

`campaign_model_discrimination`, primary key `(campaign_id, model)`, both
`NOT NULL`. The pair and not the model alone: §14.1 budgets *"two campaigns per
candidate model"*, so a candidate model's M2 evidence **is** two rows, one per
campaign, and a table keyed on the model alone could hold only the second.

`campaign` (0111) carries `ks_pvalue` and `calibration_status` and no
discrimination column, and `migrations/versions/**` is not editable; a column on
214's `campaign_discrimination` is equally out — that table's primary key is the
campaign, and 214's own suite pins its columns.

**The composite key is spelled `NOT NULL` beside `PRIMARY KEY`** for the reason
0111's docstring and 214's schema quote: SQLite accepts NULL — and several — in a
rowid table's bare `PRIMARY KEY`, so a second NULL-keyed row would split a
reading from its identity while still being counted as a distinct key.

**No `CHECK` constraints.** Validation lives in the value object and in the read
path's *reconstruction*, which is 214's answer to the defence 123 gets from
writing its figure onto two rows.

### 4. **The in-sample and out-of-sample halves are 214's reads, reused — the arithmetic has one owner**

This module imports `_pearson`, `_interval`, `_require_spread`,
`_require_correlation`, `_read_is_half`, `_read_oos_half`, `_require_tables`,
`_require_campaign`, `_utc_now` and `MechanismDiscrimination` from
`signal_agent._discrimination`, and reuses the public `IS_GAIN_METRIC`,
`MINIMUM_PAIRS` and `CONFIDENCE_LEVEL`.

The member's standing rule is that each module *restates* what it reads — that is
why 215 and 214 each restate their table and column names. But that rule is
about **names**, not about **definitions**: a second `_pearson` here would be a
second definition of the same statistic, and a second Fisher-z interval a second
definition of the interval §14.1 rule 3 requires. The precedent for reaching a
sibling inside the member is feature 213's `_themes._SLUG_RE`, reached "through
`:mod:`signal_agent._themes` rather than re-spelled", with the argument written
at the constant.

The refusals those helpers raise are `DiscriminationCohortError`'s, and their
messages name feature 214 — which is correct rather than sloppy: what they refuse
is 214's law (the cohort cannot be paired; the arithmetic cannot answer), the
repair is unchanged, and 214 is this feature's declared dependency. The `(feature
214)` in the text tells the operator where the figure's definition lives.

What this module **does** restate, with its own messages, is every *check about
its own subject*: the handle's shape, the campaign id, the cohort, the model, the
`node` table and its model column, and the model-attribution walk.

### 5. **216's frozen-cohort digest carries the model, and deliberately differs from 214's over the same branches**

§14.1 rule 1: *"Freeze the cohort before any model runs, and hash its inputs."*
The model is an input to a model-scoped figure, so the digest's header lines are
`[campaign, model, policy_version, IS_GAIN_METRIC, repr(CONFIDENCE_LEVEL)]`
followed by the same id-sorted `(branch, is_gain, oos_gain)` triples 214 hashes.

Consequence, stated rather than left to be discovered: measuring one campaign's
one model with both features over the *same* branch list yields **two different
digests**, and that is the honest reading — the two rows are two different
readings (one about a campaign, one about a model) and a colliding digest would
claim they were the same inputs. 214's plan sentence is satisfied by the
*mechanism*: this row is auditable the same way, so a report can show which
branches and which gains produced it.

### 6. **"Before the gate milestone" is made structural: the reading needs nothing the gate produces**

No milestone, gate verdict, `LOFO` result or `FDR_deploy` figure exists as a value
anywhere in this workspace — the only occurrences of "M2"/"M3" in code are
comments and docstrings citing the architecture (§14.1 line 867, §20; the
`0113`/`0115` migration prose; feature 187's `bootstrap._claim`, which takes the
gate's *world count* as a caller-supplied keyword precisely because the gate
itself is not a stored state). Inventing a milestone row here would be a second
system.

So the timing clause is discharged the only way it can be: **the instrument must
be computable from what exists before the gate, and must not read anything the
gate produces.** This module reads `node_proposal` (207), `node` (0118/0115),
`replay_score` (0109) and `campaign` (0111) — every one of them a pre-M3 table —
and its suite pins that claim structurally: no gate, milestone, verdict, LOFO or
`FDR_deploy` token appears in the module's code or in any of its SQL constants,
and no table outside that set is named.

The purpose clause has a second consequence, and it is decision 2: a reading that
can be *pooled* is a reading that can misattribute a weak agent's collapse, so
the pooled form is not producible from this module at all.

### 7. **One new error class, and 214's and 207's reused where they name the same fact**

| what happened | repair | class |
|---|---|---|
| the handle is not 207's law/store | pass the proposal-history store | `DiscriminationCohortError` (214's, unchanged) |
| the campaign id is not UUID text, or the cohort is not a non-empty set of ids | fix the argument | `DiscriminationCohortError` (214's) |
| the model is not a non-blank string | name the candidate model | **`CandidateModelError`** (new) |
| no `node` table, or no `agent_model_id` column on it | run the chain to `0118`/`0115` | **`CandidateModelError`** |
| a declared branch's node is absent, or carries no model | fix the tree, or the cohort | **`CandidateModelError`** |
| a declared branch's node is authored by **another model** | declare the model that authored it, or stratify | **`CandidateModelError`** |
| fewer than four declared branches | expand the campaign | `DiscriminationCohortError` (214's) |
| no `node_proposal` / no `replay_score` / no `campaign` table | run the chain | `ProposalHistoryStoreUnavailableError` (207's) / `DiscriminationCohortError` (214's) |
| a declared branch with a missing half, or runs spanning two revisions | freeze a cohort the store can pair | `DiscriminationCohortError` (214's) |
| a constant series, an exactly perfect `r`, a non-finite gain | the cohort cannot answer | `DiscriminationCohortError` (214's) |
| a stored row that does not reconstruct into a reading | the row is corrupt | `CandidateModelError` |

`CandidateModelError` is a **sibling** of `DiversityCohortError` and
`DiscriminationCohortError`, not a subclass of either. The distinction is
load-bearing: 214's class means *this cohort cannot be paired or cannot answer* —
repair the campaign — while this one means *this reading cannot be attributed to
the candidate model it was declared for* — repair the model declaration or
stratify the campaign. A caller that caught 214's class while holding a mixed
campaign would re-measure rather than fix the attribution.

It is deliberately **not** an `AgentSourceError`: nothing here is about a
proposal's source, and no re-prompt of a model adds a missing column or
un-mixes a campaign.

The two states 207 already names keep 207's classes: an absent `node_proposal`
table raises `ProposalHistoryStoreUnavailableError`, and an unparseable score
document raises `ProposalContentError` — *"the same fact with the same repair,
whoever asks."*

### 8. **Reads: one row, and the per-model table**

* `load_model_discrimination(history, campaign_id, model)` — the read-back half,
  `None` when this campaign has never been measured for that model. Reconstructs
  through both validating constructors, so a hand-edited row fails to load rather
  than loading as a plausible-looking reading (214's defence, taken the same way
  because this feature likewise has no second row to reconcile against).
* `load_model_discriminations(history, campaign_id)` — the mapping §14.1's
  *"report M3 results per model stratum as well as pooled"* is a report made of,
  keyed by model in sorted order, a `MappingProxyType` over a private copy
  (215's `by_model` shape). Empty for a campaign measured for no model — which is
  not the same state as an absent table, and the module draws the same three-way
  distinction 214's single load draws.

### 9. **No component, no seat, and nothing written outside this feature's footprint**

Reached as `from signal_agent import mechanism_discrimination_by_model`. No
`@register`, so `test_the_nine_laws_stay_contiguous_in_the_name_sorted_order`
stays true unchanged, and `src/app/modules/signal-agent/` gains no file. No
migration, no `campaign` column, no edit to `middleware.py`, `settings.py`, the
app factory, any registry, or any other package.

## Files

| path | change |
|---|---|
| `packages/signal-agent/src/signal_agent/_candidate.py` | **new** — the law: the SQL constants, `ModelDiscrimination`, `mechanism_discrimination_by_model`, the two loaders, the digest |
| `packages/signal-agent/src/signal_agent/errors.py` | **edit** — `CandidateModelError` + its `__all__` entry |
| `packages/signal-agent/src/signal_agent/__init__.py` | **edit** — one import block, `__all__` entries, one docstring paragraph |
| `packages/signal-agent/tests/conftest.py` | **edit** — `plant_campaign_reading` (a 214 row, by calling 214's law), `record_gain` reuse |
| `packages/signal-agent/tests/test_candidate.py` | **new** — the feature's suite |
| `.plans/feature-216-mechanism-discrimination-per-candidate-model.md` | **new** — this plan |

**No edit** to: `src/app/middleware.py`, `src/app/settings.py`,
`migrations/versions/**`, `alembic/versions/**`, any registry/router/entry-points
table or the app factory, `_discrimination.py`, `_diversity.py`, or any other
package.

## Tests

`packages/signal-agent/tests/test_candidate.py`, on the database feature 214's
suite already builds (`create_discrimination_schema`: `0118` → `0117` → `0115` →
`0114` → `0113` last, plus `0109` and `0111`), with the in-sample half written by
**207's own `ProposalStore.persist`** and the out-of-sample half inserted into
`0109`'s table.

Cases (headings):

1. **the sentence** — a cohort of one model's real branches with both halves; the
   row lands in `campaign_model_discrimination` keyed by the `(campaign, model)`
   pair, and the correlation and both bounds equal 214's own arithmetic over the
   same branches;
2. **`persists`, and reads back** — the returned value equals what
   `load_model_discrimination` answers for the same pair;
3. **the stratum is verified, not trusted** — a cohort with one branch authored by
   another model is refused, naming the branch, the declared model and the stored
   one; a branch whose node carries a blank model is refused; a declared branch
   whose node is absent is refused;
4. **no default and no pooled answer** — a missing, blank, non-string or `bool`
   model is refused; there is no call that answers a campaign's figure without a
   model;
5. **the grain is the pair** — two models measured over one campaign leave two
   rows, and re-measuring one leaves two rows with the second changed (refresh,
   not append);
6. **`load_model_discriminations` is the per-model table** — the mapping is keyed
   by model in sorted order, is read-only, is fresh per call, and is empty for a
   campaign measured for no model;
7. **the floors and the arithmetic are 214's** — three declared branches, a
   constant series, an exactly perfect correlation: each refused with
   `DiscriminationCohortError`, none answered with a number;
8. **nothing is written when a refusal fires** — the measure-first ordering,
   asserted by counting rows;
9. **the frozen cohort** — the digest is stable under a re-ordered cohort, changes
   when a gain changes, and **differs from 214's digest over the same branches**
   (the model is an input to this reading and not to that one);
10. **the module reads nothing the gate produces** — no gate/milestone/verdict/
    `LOFO`/`FDR_deploy` token in the code (comments and docstrings stripped), no
    `is_null` or other null-discriminant name, and every `*_SQL` constant opening
    with a read or the one owned `CREATE` and naming only the four pre-M3 tables
    plus this feature's own;
11. **a hand-edited row fails to load** — a correlation of `2.0` written straight
    into the table is refused on read;
12. **the value object's invariants** — a blank model, a non-UUID campaign, a
    marker class built from another model: each refused; equality, hash and
    frozen-ness hold; `row()` is fresh per call, nests the interval, and carries
    the model;
13. **the spellings agree** — this module's `node`/`agent_model_id`/`node_proposal`
    literals equal 215's and 207's, asserted rather than left to drift;
14. **no component and no seat** — no `build_` name in the module, the member's
    registry unchanged, and this directory gains no seat file.

Then both suites: the member's own
(`PYTHONPATH=src:packages/signal-agent/src uv run pytest packages/signal-agent -q`)
and the repository gate (`uv run pytest -q`), with the real measured numbers
recorded here rather than guessed. Ruff on the touched files only, compared
against a sibling — the repo lint is red on main.

### Measured

* `test_candidate.py` — **43 passed** (14 headings above, 43 cases counting the
  parameterised ones).
* the member's own suite, whole —
  `PYTHONPATH=src:packages/signal-agent/src uv run pytest packages/signal-agent -q`
  → **664 passed in 20.36s**.  Feature 214's plan recorded 578 before its own
  work; 214 took it to 621 and this feature adds 43.
* the repository gate, `uv run pytest -q` → **1060 passed in 312.76s**.
  *A note on the first run of this*: it reported **29 failed, 6 errors** — all
  of them in `tests/nulloracle/{test_sidecar_persistence,test_selection_persistence,
  test_key_resolution,test_plan_gate}.py`, and all of them
  `ModuleNotFoundError: No module named 'cryptography'`.  The venv was missing a
  dependency that `nulloracle` declares, and `uv sync --all-packages` fixed it;
  with the dependency present the same command is 1060 passed with no failures.
  Worth recording rather than quietly re-running, because the shape of that first
  output — failures in a package this feature does not touch — reads exactly like
  collateral damage from this feature's edits.
* ruff, touched files only: `_candidate.py`, `errors.py`, `test_candidate.py` →
  **All checks passed**.  `conftest.py` was not edited by this feature and is
  clean.  `__init__.py` carries **3 findings, all pre-existing** — verified by
  linting `git show HEAD:.../__init__.py`, which reports the same I001 (line
  352), RUF022 (line 542) and F811 (line 838); feature 216's edits add none.

### What developing this suite changed in the module

Two findings from the suite, both recorded in place rather than here:

* `_validated_scope` — the listing's validator.  The first version passed an
  empty-string model through a three-argument validator, and `_validated_model`
  correctly refused it, so the "unused" argument was a value the validator had to
  be told to tolerate.  Split into `_validated_scope(history, campaign_id)` and
  `_validated_reading_arguments(history, campaign_id, model)`.
* ruff's three unused imports (`uuid`, `Iterable`, `UTC`) — removed after both
  suites were green, and both re-run afterwards.

The suite's own `_import_statements` helper was **replaced by `_imports`** in the
course of getting it to work: the token-rebuilding version reported *zero* imports
in a file that has thirteen, a false green in exactly the kind of case that exists
to prevent one.  The replacement parses with `ast` and answers the question the
cases actually ask — *is this name imported, and from where* — instead of
approximating it from spacing.  Likewise `test_the_module_reads_nothing_the_gate
_produces`'s table scan went through two wrong versions (whitespace-splitting,
which reported a dozen English words and local variables as table names; and
upper-casing the whole statement, which folded a spliced-in constant's *value*
together with the keywords around it) before settling on a statement-verb-led
scan over `ast`-rendered strings.

## Out of scope

* **a migration, a `campaign` column, a component, a seat file, an edit to 214's
  table or 214's module** — each declined in the module docstring with its reason;
* **a pooled figure, a default model, an "all models" read, and a derived
  stratum** — decision 2 and decision 1;
* **a relation to 214's digest** (a superset/composition proof) — declined: a
  sha256 is not a Merkle node, containment is not showable from digests, and the
  honest guarantee is that this row is auditable the same way;
* **a precondition that 214's campaign row exists** — declined as a gratuitous
  ordering: 214's row is per campaign and per cohort, so its presence would prove
  nothing about *this* cohort, and the repair it would demand ("pool a campaign
  you do not need pooled") is not a repair for anything;
* **the M3 paired comparison, the paired bootstrap (§14.1 rule 4), `FDR_deploy`
  and the LOFO transfer test** — the gate's arithmetic, over a different table;
* **the per-commit observation, a `policy_version` filter, a derived gain, and the
  constant-baseline column (§14.1 rule 2)** — each declined in the module
  docstring with its reason.
