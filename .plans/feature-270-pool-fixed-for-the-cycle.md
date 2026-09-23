# Feature 270 — The replay pool held fixed for the cycle

**app_spec.xml, "Dreaming Loop & Meta-Selection", feature 270**
(`shape="plugin"`, `plugin="dreaming"`, no `depends_on`): *System rejects a
replay pool mutation during a dreaming iteration, holding the pool fixed for
the cycle.*

New member: `packages/dreaming/`, seat at `src/app/modules/dreaming/`. One
component, `"dreaming"`.

## The sentence, and why its qualifier is load-bearing

PRD §C5 states the rule as the **first clause of the outer loop** rather than
as a caveat on it:

> Per outer iteration: **hold the replay pool fixed**, run `M` code revisions
> of `π`, evaluate each on every stored tree, select the argmax under §7.

§12.1 gives the reason, and it is a reason about *validity* rather than about
tidiness:

> The dreaming loop **overfits its own replay pool**. The paper's guarantee
> `V^{m★} ≥ V^0` holds on the *fixed history*; selecting the max over `M`
> revisions scored on a handful of worlds is the same multiple-testing problem
> one level up.

So the guarantee is a guarantee **about a fixed history**, which means the
history has to actually be fixed. Feature 280's selection bar is a *paired*
statistic over worlds a policy pair was scored on: it is only meaningful if
both policies in the pair saw the same worlds with the same scores. A pool that
grew between the first candidate's replay and the `M`-th's would make the
comparison a comparison of two different tournaments — and **nothing in the
result would look wrong**. The scores would be finite, the argmax would be some
candidate, and the bar would be met or not. §12 names exactly this shape:
*"non-determinism does not announce itself; it just slowly makes every
conclusion wrong."*

## Three members already obeyed this rule; none enforced it

Established by reading the sibling members before writing anything:

- **`tripwires.excise` (feature 132)** exists to *"excise a poisoned subtree
  from the replay pool"* and takes the one decision that makes it compatible
  with feature 270 — **it never deletes a row**. Its docstring states the
  reason in this feature's own terms: *"Feature 270 forbids exactly that
  mutation. An excision that deleted rows would be a pool mutation, and it
  would have to reconcile itself with a rule that says the pool must not move
  while a cycle is walking it — a contradiction this design does not have,
  because a read-time refusal moves nothing."*
- **`canary._void` (feature 144)** makes the identical call for the identical
  reason (void by *derived marker*, never by deletion).
- **`bootstrap._census` (feature 186)** reads the pool's two halves and writes
  neither.

Three members were built to this rule before this module existed. What was
missing — and what this feature adds — is the **refusal**, and an account of
which cycle is holding what.

## The design decision that shapes everything: a trigger, not a wrapper

A Python guard is a rule its caller can walk around by opening the database
itself — and the pool's writers are **not all this member's callers**. The
replay member (features 245-255) writes `replay_score`; the bootstrap member
(features 188/191) authors `bootstrap_world`; an operator bisecting a
deployment's pool has a `sqlite3` shell. **A rule about a store has to live in
the store.**

So the enforcement is a `BEFORE INSERT`/`UPDATE`/`DELETE` trigger per pool table
per operation — six triggers — each aborting the statement when an un-released
hold row is present. `CycleFreeze.guard()` is a *translation*, not the rule: it
turns the database's abort into `PoolFrozenError` naming the holding iteration,
so a caller that used this member reads a message in its own vocabulary, and a
caller that bypassed it is refused identically by SQLite, with the raw abort.

`BEFORE` rather than `AFTER`: an `AFTER` trigger would let the write happen and
then raise, and on a delete would already have removed the row the abort exists
to protect.

## `pool_freeze` — the one table this member creates

```
id            TEXT    NOT NULL PRIMARY KEY,   -- hash of (iteration, opened_at)
iteration_id  TEXT    NOT NULL,
opened_at     TEXT    NOT NULL,
released_at   TEXT,                           -- NULL while the hold is open
commitment    TEXT    NOT NULL,               -- pool membership digest at open
world_count   INTEGER NOT NULL                -- pool size at open
```

Member-owned and created lazily beside the only module that writes it — the
shape `canary._halt` takes for `canary_dream_halt` and `tripwires.poison` for
its marks. Never migrated in the shared chain: that would be an order-sensitive
edit to `migrations/versions/**`, which this feature's file claim excludes, and
the table has one writer so its shape is a fact about this feature rather than
about the database's history.

**A released hold stays as a row.** *"When was the pool held, and by which
cycle?"* is a question an operator asks after the fact, and a row deleted on
release could not answer it.

## At most one open hold, enforced by the table

```sql
CREATE UNIQUE INDEX IF NOT EXISTS one_open_pool_freeze
    ON pool_freeze ((1)) WHERE released_at IS NULL;
```

The index is over a **constant expression**, which is the load-bearing detail
and was found by experiment rather than by reasoning: the obvious
`UNIQUE (id) WHERE released_at IS NULL` does **not** enforce the invariant,
because each hold's `id` differs so every row is distinct under it. A constant
gives SQLite a single index key to collide on — *there is at most one open row*
— which is a fact about the table rather than a convention of this module's
callers. §12.1 runs one cycle at a time (feature 279 rotates one holdout split
per cycle, feature 277 caps one revision count per cycle), so two open holds
would be two cycles walking one pool with neither able to say which scores were
whose.

The `INSERT` has **no `ON CONFLICT` arm** deliberately: an upsert that silently
rewrote the open row would be two cycles sharing one hold — the state the index
exists to make impossible, not one a statement should paper over.

## The commitment — what makes "held fixed" observable

`CycleFreeze.commitment` is a digest over the pool's **membership**:
`replay_score.id` and `bootstrap_world.world_id`, each table read in sorted
order, with the table names and per-table counts folded in. `verify()` re-reads
and compares.

Two properties follow, and both are properties feature 280's bar needs:

- it is a **pure function of the pool's contents** — an unchanged pool
  re-commits to the identical digest in any process, so a hold can *record* a
  commitment and later *check* it; and
- a pool that moved **anyway** — triggers dropped, a database restored from
  backup, a table swapped by hand — is **detected** rather than assumed away.
  A boolean "frozen" flag would report a clean cycle over a pool that had
  moved. This is what makes the claim falsifiable rather than promissory.

**Membership and not scores.** A score is what the cycle itself writes: the
replay member writes one `replay_score` row per `(policy, world)` pair as it
evaluates each candidate, and those rows are the cycle's **output**. A
commitment that folded scores in would count every candidate's own evidence as
a mutation of the fixed history, which would refuse the loop its own work.
What must not move is *which worlds the tournament is held over* — §C5's "every
stored tree", §10.3.1's *"every candidate revision against every stored
world"*. Pinned by `test_the_commitment_ignores_the_scores_the_cycle_writes`.

**Ordering, not counting.** A reader that hashed only a size would miss a world
swapped for another of the same size. Pinned by
`test_the_commitment_covers_which_worlds_and_not_how_many`.

`verify()` answers `False` rather than raising: a pool that moved is not this
method's to reject — the hold may have been released deliberately, a test may
be pinning that the guard *can* be evaded, an operator may be moving rows on
purpose to reproduce a fault. What the loop needs is a **judgement it can act
on**, the shape `discovery.manifest.admit_completed_campaigns` takes. A pool
that is *absent* is the other case and **is** a refusal, because *"did not
move"* and *"cannot compare"* are different facts.

## The window — what "for the cycle" means

The hold is **open-then-release**, scoped to one outer iteration. Between
iterations the pool is free again, which is what lets the campaign loop add a
completed campaign (feature 243) and a new campaign's tree join the pool. §C5
permits writes between cycles; a release that still refused them would make the
pool unusable for the loop that owns it. Pinned both ways:
`test_a_release_frees_the_pool` and
`test_a_release_underneath_a_writer_frees_the_pool_immediately`.

The commitment is read **before** the hold row is written, and that order is
the honest one rather than an accident: what the hold promises is *the pool as
it was when the iteration opened*, so the reading that defines the promise
cannot itself happen under it.

## Restraint: what this member does not do

| not this member's | whose |
|---|---|
| the §12.1 ladder floor (`pool_too_thin`, "below 20 worlds do not run dreaming") | **feature 275** — a precondition on a run that has not started; this member's subject is a cycle that *is* going. Its own code, deliberately not carried here. |
| running the `M` revisions | features 271-274 |
| the holdout split rotation | feature 279 |
| the paired statistic and its bar | feature 280 |
| the argmax persisted to `policy_revision` | features 276-277 |
| the pool's own tables | `0109` (`replay_score`), features 188/191 (`bootstrap_world`) — this member **never writes them**, not even to create them |

`pool_bootstrap_schema()` exists in `dreaming.layout` for this member's *suite*
to stand a pool up, and is deliberately **not** run by `dreaming.cycle`: a
member that authored the pool's schema would be legislating a schema three
features short of it — the stance `tripwires.excise` states for its own `0109`
bootstrap.

## The restatement, and how it is kept honest

No member in this workspace imports another. A trigger cannot be written over a
table whose name is not known, so `dreaming.layout` **restates** the pool's two
spellings with provenance — `REPLAY_SCORE_TABLE`, `REPLAY_SCORE_COLUMNS` (all
eight, in `0109`'s order), `WORLD_TABLE`, `WORLD_COLUMNS` (as feature 191
widened it), `DATABASE_URL_ENV` — and `packages/dreaming/tests/
test_cross_member.py` pins them against their owners:

- the column names against **`0109`'s own `statements()`** output, parsed;
- the same names against SQLite's `PRAGMA table_info` after running **`0109`'s
  own `apply()`** — so the pin is against a built schema, not a stale constant;
- feature 191's widening (a nullable `seed`, no `188`-era `domain`/`pool_seed`)
  against the restatement's own stand-in DDL; and
- the **seam**: a 40-world pool authored by `bootstrap`'s own `persist_worlds`
  over a database migrated by `0109`, held, and a raw `DELETE` refused — the one
  assertion the data pins cannot make.

Sibling imports live *inside* test functions (with `importorskip`), so a
missing sibling costs one test rather than the suite's collection — the
discipline `packages/discovery/tests/test_cross_member.py` documents.

## Two mechanics found by experiment, not by reading

Both are pinned by tests so a later "improvement" fails where it is made:

1. **`RAISE(ABORT, ...)` takes a string literal and nothing else.** The
   obvious `'prefix ' || (SELECT iteration_id ...) || ' suffix'` is a
   `near "||": syntax error` at `CREATE TRIGGER` time — not a message that goes
   unbuilt at run time. So the trigger says `an iteration` (floored) and the
   *Python* side names the holder, from `_GUARD_TEMPLATE` — one sentence spelled
   once so the two ends of one refusal cannot drift.
2. **`FOR EACH ROW` means a write matching zero rows is not refused.** Correct,
   and correct for this feature's own reason: the sentence forbids a pool
   *mutation*, and a statement leaving the pool byte-for-byte as it was has not
   mutated it. Pinned by `test_a_statement_that_matches_no_row_is_not_a_mutation`.

## Composition

`@register("dreaming")` lives in `packages/dreaming/src/dreaming/__init__.py`
**and not in a submodule** — a submodule's registration fires only on the first
`create_app()` of a process. The builder takes no arguments, never raises, and
returns `CycleFreeze.resolve()` — `None` when `DATABASE_URL` names no store —
per the workspace's *degrade, don't break* rule. It performs **no I/O** and
**acquires no hold**: §C5's hold is per outer iteration, so an application that
held a pool from composition time would hold it for as long as the process
lived — a dreaming cycle that never ends.

The seat is `src/app/modules/dreaming/`, exporting exactly `COMPONENT_NAME` and
`cycle_freeze_component`, discovered by the loader's scan. Nothing edits the app
factory, middleware, settings, a registry, a router table, an entry-points
table, or `migrations/versions/**`. The member joins the workspace by
`packages/*` glob + `uv.lock`, both of which needed no hand edit beyond
`uv lock` picking up `packages/dreaming/pyproject.toml`.

`"dreaming"` sorts between `"discovery"` and `"evaluator"`; the existing
suite's `app.order` assertions are membership and adjacency checks rather than
a pinned full list, and are untouched.

## Files

| file | what |
|---|---|
| `packages/dreaming/pyproject.toml` | the member manifest |
| `packages/dreaming/src/dreaming/__init__.py` | docstring, re-exports, `@register`, `build_cycle_freeze` |
| `packages/dreaming/src/dreaming/errors.py` | `DreamingError`, `FreezeRequestError`, `PoolFrozenError` |
| `packages/dreaming/src/dreaming/layout.py` | the restated pool spellings + stand-in DDL |
| `packages/dreaming/src/dreaming/cycle.py` | `CycleFreeze`, `FreezeRecord`, the schema, the guards |
| `packages/dreaming/tests/` | conftest + 4 suites, 99 tests |
| `src/app/modules/dreaming/__init__.py` | the seat |
| `.plans/feature-270-pool-fixed-for-the-cycle.md` | this document |
