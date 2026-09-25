# Feature 346 — Discovery-rate store

**Feature index:** 346 (depends on 341)
**Shape:** plugin (`ops`)
**Feature sentence (app_spec.xml):** *System persists discoveries per 1000 budget-charging trials, excluding null nodes from the denominator.*

346. System persists discoveries per 1000 budget-charging trials, excluding null nodes from the denominator
Description: The ops member adds one member-owned table, `ops_discovery_rate`, in the relational store `DATABASE_URL` names — the same "single Postgres metrics table" allowance docs §16 permits and the surfaces features 341/350/347 already resolve. It is the persistence half of §16's research-metrics line ("discoveries per 1000 *budget-charging* trials") and of prd §11's secondary scorecard row ("Discoveries per 1,000 trials charged (nulls excluded from the denominator) | trending up"). The store accepts three counts handed over already measured — the campaign's standing discoveries, its budget-charging trial count (feature 93's `K_effective`) and the ledger's plain row count — and **computes the one quotient the sentence names**, `discoveries ÷ budget_charging_trials × 1000`, refusing a caller-stated rate at every spelling. Delivered as one store module `ops.discovery_rate` plus its app-package seat accessor, the two-file shape features 350 and 347 take. No route, no dashboard, no schema file: the table is brought up idempotently on first connect, so no revision is written and no shared schema is touched.
Depends on: 341

## 1. The sentence, read as a feature

The verb — *"System persists"* — is the ops member's half and, as with features 350 and 347 one row over, the whole of what this feature adds.

What the sentence names is a **figure**, and the figure is docs': §16 lists it among the per-campaign research metrics as *"discoveries per 1000 **budget-charging** trials"*, and prd §11's scorecard carries it as the one **secondary** metric graded by a *direction* rather than a bar — *"Discoveries per 1,000 trials charged (nulls excluded from the denominator) | trending up"*.

### 1.1 The denominator's identity is the whole of the second clause

§8 states what `charges_budget` is for:

> A null node's signal was never compared to real forward returns, so it consumed agent calls and CPU but **no statistical degrees of freedom**. It must not inflate `K` in the deflation term.

Feature 93's `K_effective` is the count that filter produces — *"the count of the trials that spent statistical budget"* — and `packages/ledger/src/ledger/keffective.py` says plainly what the two counts are:

> `K_effective` is never the number of rows the ledger holds: `TrialLedger.count` is that number and stays deliberately plain, while this is the count *of the trials that spent statistical budget*.

That divergence **is** the null nodes, and it is the only place the sentence's second clause can be honoured from. A store that divided by the ledger's row count would answer a *smaller* rate exactly in proportion to how many nulls a campaign planted — the flattering direction, which is precisely the direction prd §11's *"trending up"* target would then reward. So the denominator is the budget-charging count, and the raw ledger count is carried **beside** it so the exclusion is checkable rather than merely labelled.

### 1.2 What this feature is not, and why that is the feature rather than a gap

It is **not a reader of the ledger, and it counts no pick.** The discoveries are the selection surface's count (feature 274's argmax, feature 222's terminal commit — the picks that stayed standing); the budget-charging trial count is the ledger member's derivation (feature 93); the ledger's raw row count is the ledger store's own plain number. Reaching for the ledger member would make this table's construction depend on a sibling the factory scan could not promise is on `sys.path` at build time, and would grow a second spelling of the `charges_budget` filter feature 93 already owns. So the store **reads no ledger and counts no discovery**: it accepts the three counts handed over already measured — the same "hand over, never derive" barrier feature 350 states for its four metrics, 347 for its two halves, 267 for its pair and 340 for its two costs.

It is **not a caller-stated rate.** A rate is not a measurement; it is the answer to *how many discoveries per 1000 budget-charging trials*, and the sentence names it as the persisted figure. So there is no parameter for it, at any spelling, on any verb — the identical stance feature 340 takes toward its `difference_bps` and 347 toward its `gap`. Three counts stated, one quotient computed, stored beside the counts that produced it so a reader can check the division rather than trust it. The multiplication by 1000 is inside the store's arithmetic too, because **the unit is part of the figure**: a caller handed the bare quotient would be handed a number whose unit lives in prose, and the first surface to divide by a hundred, or to plot it beside `FDR_deploy`'s `[0, 1]`, would be showing a figure nobody measured.

It is **not a verdict.** Whether a rate is *good* is prd §11's scorecard's judgment, reached by the loop that reads the trend against the campaigns that came before it. A threshold here would be this member inventing a bar the documents put elsewhere, so none is spelled.

It is **not an absence-detector.** A campaign that found nothing **measured** exactly that: zero is a rate the store persists happily, never refuses, because prd §11's *"trending up"* is a direction a flat zero is the honest bottom of. Only the *absence of a row* is an absence.

It is **not a route, a dashboard, or a new field on anyone else's table.** 341's route and 342/343's lamps are the expose features; 351's dashboard is the render; the rate does not land as a column on `trial_ledger`, on `scoring_fdr_deploy` or anywhere else — those tables have their own subjects and owners.

It is **not features 344/345/347's research-metrics rows.** §16 lists several per-campaign figures; the sentence names one, and the closed set here is one row — a table holding a figure nobody measured would be the corruption this store exists to refuse.

What this feature *does* that nothing else does: it makes the yield a **stored, trended fact** — a member-owned `ops_discovery_rate` table, a `record` verb that validates three counts and the instant and computes the quotient itself, a point read that answers `None` for a campaign that closed no row out, and a trend read that answers the whole history oldest-first.

## 2. The persistence, made structural

### 2.1 The table: `ops_discovery_rate`

Member-first, in the relational store `DATABASE_URL` names, created idempotently on connect so no migration step is needed and no shared schema file is touched. Named `ops_discovery_rate` — member (`ops`) first, subject second — the way `scoring_fdr_deploy`, `ops_live_metrics` and `ops_meta_overfit_gap` are named.

Six columns, one row per **campaign** (§16: *"**Research metrics** (per campaign)"*):

| column | type | meaning |
| --- | --- | --- |
| `campaign_id` | TEXT NOT NULL, PRIMARY KEY | the campaign's id in canonical UUID text — the join law feature 267's per-campaign row already keys on |
| `discoveries` | INTEGER NOT NULL | the campaign's standing pick count, handed over already measured (`>= 0`) |
| `budget_charging_trials` | INTEGER NOT NULL | **the denominator**: feature 93's `K_effective` — the trials whose `charges_budget` is true (`> 0`) |
| `ledger_trials` | INTEGER NOT NULL | the ledger's plain row count, carried beside the denominator so the exclusion is checkable (`>= the denominator`) |
| `rate` | REAL NOT NULL | **derived**: `discoveries ÷ budget_charging_trials × 1000` |
| `recorded_at` | TEXT NOT NULL | ISO 8601 UTC, second resolution — a label, not a measurement |

One row per campaign: the write is an upsert on `campaign_id`, so a re-run of the same campaign's measurement refreshes the measured columns rather than appending a second row. The key is canonicalised to UUID text so a mixed-case or braced spelling upserts onto the one row rather than making one campaign look like two.

`ledger_trials` is **the check's other operand and nothing else** — the rate is `discoveries ÷ budget_charging_trials` and only that. Its presence is what makes *"excluding null nodes from the denominator"* verifiable: `ledger_trials − budget_charging_trials` is the null nodes the sentence excludes, visible by subtraction, and that is feature 93's own arithmetic stated as a column. The pair also carries the counts' *scale*, so 3 discoveries over 1,200 is not confused with 3 over 120,000.

### 2.2 The verb: `record(campaign_id, *, discoveries, budget_charging_trials, ledger_trials, recorded_at=None)`

The one write. The ask is validated whole **before a connection is opened** — a malformed ask never reaches the store, so a refused record leaves no half-written row and no database file at all (the ordering features 267, 350 and 347 state):

- the campaign must be a UUID (or its text, in any spelling `uuid.UUID` parses), canonicalised; anything else is refused, because an id that cannot join the tree's campaign key names no campaign a rate could be persisted for;
- each count must be a **whole number**: `bool` refused before `int` (a flag where a count belongs would persist a figure nobody measured), and a fractional count refused rather than coerced — `14.0` trials is not a count of trials, and coercing it would be this store inventing a denominator the caller never stated;
- the **denominator must be at least 1**: a rate over no budget-charging trials is undefined (a ledger of nothing but null nodes charges nothing), and answering `0.0` for `0/0` would persist the quietest possible claim about a campaign whose research yield was never measured;
- `discoveries` may be **zero** and must not be negative: zero is a measurement, a negative count is not;
- `ledger_trials` must be at least 1 and **at least the denominator** — feature 93's `K_effective` is a *subset* count of the ledger's rows, and the ledger is append-only with no UPDATE and no DELETE (§8, enforced by role grants), so a row claiming more charges than were ever recorded cannot be produced honestly and would put a flattering denominator into prd §11's trend;
- each count must fit the row's **signed 64-bit `INTEGER` column**: a count past it is refused here, in this member's vocabulary, rather than surfacing as a raw `OverflowError` from the driver's binding step — which is neither this member's error nor a measurement anybody made;
- the instant, if given, must be a non-empty string — it orders the trend, so a value that is not a nameable instant orders nothing; absent, the write stamps its own (UTC, second resolution).

There is deliberately **no bound relating `discoveries` to either count**: a committed pick need not have come from a trial this campaign charged (prd §4.2's resident book is selected across campaigns), so a rate above 1000 is possible, is a measurement, and clamping it would be this store inventing a bound the documents do not state.

The rate is then computed **once, here or nowhere**, and the returned `DiscoveryRate` is read back inside the same transaction as the write, so the answer's fields are the row's own rather than the arguments'.

### 2.3 The value: `DiscoveryRate`

A frozen, slotted dataclass over the table's six columns, one type serving the write and the read. Validated in `__post_init__` rather than only through the store, because `dataclasses.replace` and unpickling rebuild instances past a factory's nose and because SQLite's columns are dynamically typed — a hand-edited row is reachable on the read path. Two checks span more than one field, and both are the table's own accounting: the charged trials must not exceed the ledger's rows, and `rate` must equal `discoveries ÷ budget_charging_trials × 1000` *exactly* — a row where it does not is a row lying about its own division, refused rather than served, because prd §11's grade is read off this column.

### 2.4 The reads: `rate(campaign_id)` and `history()`

- `rate(campaign_id)` — the point read, answering `None` for a campaign that closed no row out. `None` is the honest absent answer, never a zero: `0.0` is a *measurement* (a campaign that made no discoveries), and a caller that could not tell them apart would read a barren research programme out of a missing row. The same stance feature 267's `fdr` takes toward an unclosed campaign, 347's `gap` toward an unclosed cycle and 350's `latest` toward an unrecorded metric.
- `history()` — every campaign's rate on record, ordered by `(recorded_at, campaign_id)`, oldest first: the trend prd §11 grades the metric's *direction* across, with the campaign's id breaking same-instant ties so two reads of one history return the same sequence. An empty tuple is the honest answer for a deployment that has closed no campaign out.

Neither read recomputes a figure; each answers what was written. Both refuse — never skip — a stored row no rate row could be, naming the campaign the bad row came from so an operator gets the row to repair rather than a complaint about a value with no address.

### 2.5 The store, addressed the way every member store addresses it

`DATABASE_URL` — the one ambient the member's route, dashboard and other stores already compose on, **imported from `ops.live_metrics` rather than re-spelled**, so the member holds one name for the database every one of its tables lives in. `sqlite:///` on a single machine, schema created idempotently on connect. The class resolves its path lazily, so constructing one performs no I/O — composition-time work must not touch the disk. The store's own failures (an unspeakable scheme, a host on a sqlite URL, a URL with no path, a locked or unwritable database) surface in this member's vocabulary with the original chained, never swallowed — a rate that measured but never landed is the state this feature exists to rule out.

`resolve()` answers the store `DATABASE_URL` names, or `None` when it names none (absent, empty and whitespace-only all unset) — the degrade-don't-break stance every store-bound builder here takes.

## 3. The component beside the member's other four

`OPS_DISCOVERY_RATE_COMPONENT_NAME` (`ops-discovery-rate`) registers a builder that resolves `DATABASE_URL` and answers `None` when nothing names a store — the same stance the route's, the dashboard's and the other two stores' builders take: the factory builds every component on every `create_app()` call, and a deployment without a relational store must still compose. *No store is configured* and *the store is broken* are different facts, and only the second may ever be quiet.

It is the member's fifth component name and its fourth store-bound one — the growth the member's own registration reserved when feature 341 landed and the app-package seat reserved beside it (*"344-346's arrive as their own tables under the same allowance"*). The store is reached from the app package through a composition accessor (`discovery_rate_component`), the same accessor-per-component shape the seat takes for the member's other four.

## 4. The refusal vocabulary

One new `OpsError` subclass — `DiscoveryRateError` — for the store's refusals, split by *where the refusal happens* the way the member's error docstring states (a surface per subclass; the store is this feature's surface). It is the third of the store-surface siblings (`LiveMetricError` and `MetaOverfitGapError` are the other two) and carries the same asymmetry with one addition the other two do not need: an **absent** rate is a discoverable state answered as an absence, a **zero** rate is a measurement the store persists happily, and only a rate that could not have been divided is refused — because a flattering denominator is precisely the failure the sentence's second clause exists to prevent. A caller that catches it catches a rate that could not be persisted or read, with the original chained — never taken down by `sqlite3.Error` from a module the store's caller never imported.

## 5. What the feature deliberately does not touch

No edit to `app_spec.xml` (feature 346's sentence is already there). No route, no dashboard, no render. No import of the ledger, scoring, dreaming or replay members at module scope or builder time — the counts are handed over, so the store stays stdlib-only and import-cheap, and composing it performs no sibling import and no I/O. No new table for any other feature's figure. No edit to `src/app/middleware.py`, `src/app/settings.py`, `migrations/versions/**` or `alembic/versions/**`: the schema is created idempotently on connect, as every member store in this workspace does, and registration is the member's own `@register` in its `__init__` under the auto-discovery scan.

## 6. Testing plan

A real SQLite file in a `tmp` directory — the persistence law is honestly testable only against the thing it persists into. The suite pins:

- **the round trip** — what `record` writes, `rate`/`history` read back, every column to the bit;
- **the rate is the store's own arithmetic** — `rate` appears in no signature, `12 / 4000 × 1000` answers `3.0` (and *not* `0.003` — the unit is per 1000), a denser campaign reads higher, and a value constructed with a disagreeing rate is refused;
- **the denominator's identity** — the stored rate equals `discoveries / budget_charging_trials × 1000` and demonstrably *not* `discoveries / ledger_trials × 1000`, which would have been the smaller, flattering figure; two rows with the same discoveries and denominator but different ledger sizes read the same rate (the ledger count enters no arithmetic); a campaign that planted no nulls shows the two counts equal;
- **zero is a measurement, not an absence** — a zero-discovery row is persisted and read back as `0.0`, never refused; `rate` answers `None` and `history` an empty tuple for a campaign/deployment that measured nothing; and a rate above 1000 is persisted unclamped;
- **one campaign, one row** — the six columns' shape, two campaigns as two rows, the upsert refreshing the measurement rather than appending, and `recorded_at` preserved across the refresh (the answer reflects the row's instant, not the retry's);
- **the ordering of the ask** — a non-UUID id (with UUID objects and mixed-case/braced spellings canonicalising onto the one row), a fractional/`bool`/text/`None` count for each of the three, a zero or negative denominator, a negative discovery count, a zero ledger size, a count past the column's 64-bit range (with the largest storable count admitted), an unnameable instant, and **a denominator above the ledger's own size** are all refused before a connection is opened (no database file appears, so no wedged row);
- **the trend's order** — oldest-first by `(recorded_at, campaign_id)`, ties broken by the campaign;
- **a stored row that is not a rate row is refused, never served** — a hand-edited `rate` disagreeing with its counts, a text/NaN/inf rate, a zero denominator, a count past the column's range, a row whose denominator exceeds its ledger, and a blank campaign each refused with the campaign named;
- **the module reads no sibling and no clock** — an AST check over the module's code with docstrings stripped: only stdlib and this member's own modules are imported, and no ledger/scoring/dreaming/replay import appears anywhere (the prose may name the ledger — the figure's owner is stated where it is delegated to — while the code may not);
- **the store's own failures** — no `DATABASE_URL` (resolve → `None`), an unspeakable scheme (refused at first use, not construction), a host on a sqlite URL, a URL with no path, a blank URL at construction, and a database that will not open (surfaced chained in `DiscoveryRateError`) on both the write and the read paths;
- **construction performs no I/O** — the URL is held, the path resolved lazily, the file appears at the first verb;
- **the component and the seat** — the builder resolves the store or answers `None`, the scan registers exactly the member's five components, the three spellings of the component name agree, the seat's `EXPECTED_EXPORTS` grows by exactly the new names, the store composes over the same database as the route and the meta-overfit gap store, composing it touches no disk, and the error is rooted at `OpsError`.
