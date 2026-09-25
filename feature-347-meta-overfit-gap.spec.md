# Feature 347 — Meta-overfit gap store

**Feature index:** 347 (depends on 341)
**Shape:** plugin (`ops`)
**Feature sentence (app_spec.xml):** *System persists the train-versus-holdout world score gap as the meta-overfitting indicator.*

347. System persists the train-versus-holdout world score gap as the meta-overfitting indicator
Description: The ops member adds one member-owned table, `ops_meta_overfit_gap`, in the relational store `DATABASE_URL` names — the same "single Postgres metrics table" allowance docs §16 permits and the surfaces features 341/350 already resolve. It is the persistence half of §16's research-metrics line ("train-vs-holdout world score gap (meta-overfit)") and the instrument for §15's failure row ("Dreaming overfits the pool | Holdout-world score diverges from train-world score"). The store accepts the two halves' levels and world counts handed over already measured and **computes the one difference the sentence names** — `train_mean − holdout_mean` — refusing a caller-stated gap at every spelling. Delivered as one store module `ops.meta_overfit` plus its app-package seat accessor, the two-file shape feature 350 takes. No route, no dashboard, no schema file: the table is brought up idempotently on first connect, so no revision is written and no shared schema is touched.
Depends on: 341

## 1. The sentence, read as a feature

The verb — *"System persists"* — is the ops member's half and, as with feature 350 one row over, the whole of what this feature adds. It is docs §16's *"single Postgres metrics table"* allowance: a relational store, `sqlite:///` on a single machine, `CREATE TABLE IF NOT EXISTS` on connect, one member-owned table.

What the sentence names is a **figure**, and the figures are docs':
§16 lists it among the per-campaign research metrics as *"train-vs-holdout world score gap (meta-overfit)"*; §15's risk table states the reader — *"Dreaming overfits the pool | Holdout-world score diverges from train-world score | Cap `M` per §10.3.1; rotate the 70/30 split; block dreaming below 20 worlds"*; §10.3.1 supplies the discipline the split exists for (*"select on train, report on holdout"*) and §12.1 the failure it guards (*"the dreaming loop overfits its own replay pool"*).

### 1.1 Why the gap is the observable half of a failure that announces itself nowhere else

Selection takes a max over `M` revisions (feature 274's argmax). A max is biased upward by construction, and the winner's advantage on the worlds that chose it reads exactly like an edge. Feature 278's 70/30 split is the mitigation — selection reads the train half, reporting reads the holdout half — and this feature is the split's *instrument*: the two halves have two levels, their difference is a number, and that number is the only place the overfitting is visible from. A positive gap **is** §15's row: the train half reads better than the half the selection never touched, which is what selection manufactured. The sign is the headline, exactly as it is for feature 340's cost difference one domain over.

### 1.2 What this feature is not, and why that is the feature rather than a gap

It is **not a reader of the pool, and it takes no mean.** The per-world scores are the replay member's rows (feature 255's `replay_score.score`, the out-of-sample IR feature 281 pairs over); the halves are the dreaming member's partition (feature 278's `PoolSplit`, feature 279's rotation, whose `is_holdout` predicate `0109`'s column carries). The level of each half is an aggregate only the caller — the cycle holding the split and the scores — can honestly take. Reaching for either member would make this table's construction depend on two siblings the factory scan could not promise are on `sys.path` at build time, and would grow a second spelling of a partition and a mean those members already own. So the store **reads no pool and computes no mean**: it accepts the two halves' levels and their world counts handed over already measured — the same "hand over, never derive" barrier feature 350 states for its four metrics and 267 and 340 state for their pairs.

It is **not a caller-stated gap.** A gap is not a measurement; it is the answer to *how far apart were the two halves*, and the sentence names it as the persisted figure. So there is no parameter for it, at any spelling, on any verb — the identical stance feature 340 takes toward its `difference_bps` ("a caller-supplied difference would let the system persist an unreconciled claim — two figures and a third that disagrees with both"). Two sides stated, one difference computed, stored beside the sides that produced it so a reader can check the subtraction rather than trust it.

It is **not a verdict.** Whether a gap *is* meta-overfitting is §15's remedy's judgment, reached by the loop that holds `M`, the split's rotation and the pool size. A threshold here would be this member inventing a bar the documents put elsewhere, so none is spelled — the value carries only the weaker fact the two levels already carry.

It is **not a route, a dashboard, or a new field on anyone else's table.** 341's route and 342/343's lamps are the expose features; 351's dashboard is the render; the gap does not land as a column on `replay_score`, on `cycle_holdout` or anywhere else — those tables have their own subjects and owners.

It is **not features 344-346's research-metrics rows.** §16 lists several per-campaign figures; the sentence names one, and the closed set here is one row — a table holding a figure nobody measured would be the corruption this store exists to refuse.

What this feature *does* that nothing else does: it makes the divergence a **stored, trended fact** — a member-owned `ops_meta_overfit_gap` table, a `record` verb that validates both levels, both counts and the instant and computes the gap itself, a point read that answers `None` for a cycle that closed no gap out, and a trend read that answers the whole history oldest-first.

## 2. The persistence, made structural

### 2.1 The table: `ops_meta_overfit_gap`

Member-first, in the relational store `DATABASE_URL` names, created idempotently on connect so no migration step is needed and no shared schema file is touched. Named `ops_meta_overfit_gap` — member (`ops`) first, subject second — the way `scoring_fdr_deploy` and `ops_live_metrics` are named, so a reader of the store can tell whose research row it is holding.

Seven columns, one row per **dreaming cycle**:

| column | type | meaning |
| --- | --- | --- |
| `iteration_id` | TEXT NOT NULL, PRIMARY KEY | the cycle's own name (feature 270's freeze, feature 279's rotation — *the rotation a cycle's split is taken at is the cycle's own name*) |
| `train_mean` | REAL NOT NULL | the train half's level, handed over already measured |
| `holdout_mean` | REAL NOT NULL | the holdout half's level, on the same terms |
| `train_worlds` | INTEGER NOT NULL | worlds the train level was taken over (> 0) |
| `holdout_worlds` | INTEGER NOT NULL | worlds the holdout level was taken over (> 0) |
| `gap` | REAL NOT NULL | **derived**: `train_mean − holdout_mean` |
| `recorded_at` | TEXT NOT NULL | ISO 8601 UTC, second resolution — a label, not a measurement |

The key is `iteration_id` because the 70/30 split is taken **per cycle** (§10.3.1's `rotate_each_cycle=True`) and this figure is a property of one cycle's split and the scores its halves read. One row per cycle: the write is an upsert on that key, so a re-run of the same cycle's measurement refreshes the measured columns rather than appending a second row.

`train_worlds` and `holdout_worlds` are **context, never weights** — the same reasoning feature 279 carries `world_count` beside its holdout worlds, so a reader can tell a 35/15 gap from a 3/1 one. They enter no arithmetic: the gap is the difference of the two levels and nothing else, and stating that plainly is the point.

### 2.2 The verb: `record(iteration_id, *, train_mean, holdout_mean, train_worlds, holdout_worlds, recorded_at=None)`

The one write. The ask is validated whole **before a connection is opened** — a malformed ask never reaches the store, so a refused record leaves no half-written row and no database file at all (the ordering feature 267 and 350 state):

- the cycle must be non-empty text (stripped — a padded spelling joins the same row);
- each level must be a **finite real**: `bool` refused before `Real` (a flag where a level belongs would persist a figure nobody measured), and `-inf`/`+inf`/NaN refused **by name**, with the refusal saying why — a replay that emitted no pick is scored `-inf` (feature 249's floor, the miss), so a half on which every world missed has no level to compare, and a NaN would compare false against everything while looking exactly like a data point;
- **no sign bound and no magnitude bound** on either level or on the gap: an out-of-sample IR has no structural limit the way a correlation's `[−1, 1]` does, and the sign of the gap *is* the headline;
- the **difference must itself be finite**: two levels are each gated one at a time, but their subtraction can still overflow the double range (`1e308 − (−1e308)` is `+inf`) — a gap that is not a number is refused by name, and refused *before the connection opens*, not on the read-back after the INSERT has landed, so a refused ask never leaves a row the store would then refuse to read (which would wedge every later trend read);
- each count must be a **positive whole number**: `bool` refused before `int`, a fractional world refused (`35.0` is not a world — coercing it would be this store inventing a split size), and `0`/negative refused, because a half with no worlds has a level that is a mean of nothing and §10.3.1 needs both halves to exist;
- the instant, if given, must be a non-empty string — it orders the trend, so a value that is not a nameable instant orders nothing; absent, the write stamps its own (UTC, second resolution).

The gap is then computed **once, here or nowhere**, and the returned `MetaOverfitGap` is read back inside the same transaction as the write, so the answer's fields are the row's own rather than the arguments'.

### 2.3 The value: `MetaOverfitGap`

A frozen, slotted dataclass over the table's seven columns, one type serving the write and the read. Validated in `__post_init__` rather than only through the store, because `dataclasses.replace` and unpickling rebuild instances past a factory's nose and because SQLite's columns are dynamically typed — a hand-edited row is reachable on the read path. The one check beyond the field validators is the table's **own arithmetic**: `gap` must equal `train_mean − holdout_mean` exactly, and a row where it does not is a row lying about its own subtraction — refused rather than served, because §15's remedy and §16's metric trust the stored difference without recomputing it.

### 2.4 The reads: `gap(iteration_id)` and `history()`

- `gap(iteration_id)` — the point read, answering `None` for a cycle that closed no gap out. `None` is the honest absent answer, never a zero: `0.0` is a *measurement* (a cycle whose halves read identically — no overfitting), and a caller that could not tell them apart would read a clean cycle out of a missing row. The same stance feature 267's `fdr` takes toward an unclosed campaign and 350's `latest` toward an unrecorded metric.
- `history()` — every cycle's gap on record, ordered by `(recorded_at, iteration_id)`, oldest first: the trend §15's remedy watches the divergence across, with the cycle's id breaking same-instant ties so two reads of one history return the same sequence. An empty tuple is the honest answer for a deployment that has closed no cycle out — a discoverable state, not an exception and never a fabricated first point.

Neither read recomputes a figure; each answers what was written. Both refuse — never skip — a stored row no gap row could be, naming the cycle the bad row came from so an operator gets the row to repair rather than a complaint about a value with no address.

### 2.5 The store, addressed the way every member store addresses it

`DATABASE_URL` — the one ambient the member's route, dashboard and live-metrics store already compose on, **imported from `ops.live_metrics` rather than re-spelled**, so the member holds one name for the database every one of its tables lives in. `sqlite:///` on a single machine, schema created idempotently on connect. The class resolves its path lazily, so constructing one performs no I/O — composition-time work must not touch the disk. The store's own failures (an unspeakable scheme, a host on a sqlite URL, a URL with no path, a locked or unwritable database) surface in this member's vocabulary with the original chained, never swallowed — a divergence that measured but never landed is the state this feature exists to rule out, because §15's remedy *cap `M`* is read off these rows and a missing row reads as a quiet cycle.

`resolve()` answers the store `DATABASE_URL` names, or `None` when it names none (absent, empty and whitespace-only all unset) — the degrade-don't-break stance every store-bound builder here takes.

## 3. The component beside the member's other three

`OPS_META_OVERFIT_COMPONENT_NAME` (`ops-meta-overfit`) registers a builder that resolves `DATABASE_URL` and answers `None` when nothing names a store — the same stance the route's, the dashboard's and the live-metrics store's builders take: the factory builds every component on every `create_app()` call, and a deployment without a relational store must still compose. *No store is configured* and *the store is broken* are different facts, and only the second may ever be quiet.

It is the member's fourth component name and its third store-bound one — the growth the member's own registration reserved when feature 341 landed and the app-package seat reserved beside it (*"344-347's and 350's persisted metrics arrive as this member's own tables"*). The store is reached from the app package through a composition accessor (`meta_overfit_component`), the same accessor-per-component shape the seat takes for the member's other three.

## 4. The refusal vocabulary

One new `OpsError` subclass — `MetaOverfitGapError` — for the store's refusals, split by *where the refusal happens* the way the member's error docstring states (a surface per subclass; the store is this feature's surface). It is the store-surface sibling of `LiveMetricError` one feature over and carries the same asymmetry: an **absent** indicator is a discoverable state answered as an absence, while a **broken** one is refused, because a divergence that is quietly defaulted is exactly the overfitting this category exists to make visible. A caller that catches it catches a gap that could not be persisted or read, with the original chained — never taken down by `sqlite3.Error` from a module the store's caller never imported.

## 5. What the feature deliberately does not touch

No edit to `app_spec.xml` (feature 347's sentence is already there). No route, no dashboard, no render. No import of the dreaming, replay or scoring members at module scope or builder time — the levels are handed over, so the store stays stdlib-only and import-cheap, and composing it performs no sibling import and no I/O. No new table for any other feature's figure. No edit to `src/app/middleware.py`, `src/app/settings.py`, `migrations/versions/**` or `alembic/versions/**`: the schema is created idempotently on connect, as every member store in this workspace does, and registration is the member's own `@register` in its `__init__` under the auto-discovery scan.

## 6. Testing plan

A real SQLite file in a `tmp` directory — the persistence law is honestly testable only against the thing it persists into. The suite pins:

- **the round trip** — what `record` writes, `gap`/`history` read back, every column to the bit;
- **the gap is the store's own arithmetic** — `gap` appears in no signature, `0.9/0.3` answers `0.6`, a holdout-ahead row answers negative, equal halves answer exactly `0.0` (a measurement, not an absence), and a value constructed with a disagreeing gap is refused;
- **one cycle, one row** — the seven columns' shape, two cycles as two rows, the upsert refreshing the measurement rather than appending, and `recorded_at` preserved across the refresh (the answer reflects the row's instant, not the retry's);
- **the ordering of the ask** — a nameless cycle, a non-finite level (`-inf`/`inf`/NaN, each refused by name), a `bool` level, a `None`/text level, a fractional/`bool`/zero/negative count, an unnameable instant, and **two individually-finite levels whose difference overflows** (`1e308` against `-1e308`) are all refused before a connection is opened (no database file appears, so no wedged row);
- **both halves are levels, not rates** — negative and large levels honoured (no sign or magnitude bound), counts entering no arithmetic (same levels, different counts, same gap);
- **an absence is not a zero** — `gap` answers `None` and `history` an empty tuple for a cycle/deployment that measured nothing;
- **the trend's order** — oldest-first by `(recorded_at, iteration_id)`, ties broken by the cycle;
- **a stored row that is not a gap row is refused, never served** — a hand-edited `gap` disagreeing with its halves, a text level, a zero count, a blank cycle, and a pair of stored levels whose own subtraction overflows each refused with the cycle named;
- **the store's own failures** — no `DATABASE_URL` (resolve → `None`), an unspeakable scheme (refused at first use, not construction), a host on a sqlite URL, a URL with no path, a blank URL at construction, and a database that will not open (surfaced chained in `MetaOverfitGapError`) on both the write and the read paths;
- **construction performs no I/O** — the URL is held, the path resolved lazily, the file appears at the first verb;
- **the component and the seat** — the builder resolves the store or answers `None`, the scan registers exactly the member's four components, the three spellings of the component name agree, the seat's `EXPECTED_EXPORTS` grows by exactly the new names, the store composes over the same database as the route and the live-metrics store, and composing it touches no disk.
