# Feature 291 — pre-registering promotion criteria, and hashing them before the decision

**app_spec.xml, "Promotion & Epoch Governance", feature 291**
(`shape="plugin"`, `plugin="promotion"`): *System exposes POST
/promotion/pre-register, which returns a criteria hash recorded before the
deciding evaluation runs.*

The first feature of a **new member**, `packages/promotion/` — the spec's
whole promotion category (291–300) is plugin-scoped to `promotion`, and this
is the feature the other nine depend on (`292 → 291`, `293 → 291`, `294 →
293`, and so on down to 300).

## The law, and why it is a route rather than a helper

`docs/alpha-engine-prd.md` §13 states it as item 7 of the invariants that
*"violating any of these silently invalidates the system"*:

> 7. Promotion criteria are pre-registered and hashed before the evaluation
>    that decides them.

— and closes the section with *"Enforce in CI, not in code review."* §M4
states the deployment it was written for: *"Pre-register success criteria in a
hashed file **before** the shadow run starts."* Feature 360 is the CI
invariant that polices the ordering.

A CI invariant can only check an ordering some component actually performs, so
this feature is the component that performs it. That is the whole argument for
the shape: the route is not a convenience wrapper around a hash function, it
is the *thing* feature 360 will read the timestamps of.

**"Exposes" means a Python seam, not an HTTP server.** There is no
fastapi/flask/starlette anywhere in this workspace; every "exposes" feature in
the spec landed as a frozen request value, a frozen response value, an
endpoint class carrying a `route` class attribute, and a `from_env`
classmethod. `packages/ledger/src/ledger/debit.py` is the template this
endpoint follows line for line.

## The ordering is a property of the schema, not a convention

`promotion_registry` (migration `0108`) declares six columns:

| column | who writes it |
|---|---|
| `id UUID PRIMARY KEY DEFAULT` | the table |
| `node_id UUID NOT NULL REFERENCES node(id)` | this feature |
| `epoch_id TEXT NOT NULL REFERENCES epoch_ledger(epoch_id)` | this feature |
| `criteria_hash CHAR(64) NOT NULL` | this feature |
| `pre_registered_at TIMESTAMPTZ NOT NULL` | this feature |
| `decided_at TIMESTAMPTZ` | feature 293, when the evaluation has run |

Two timestamps, two writers, and the *nullable* one is the feature: the row is
inserted while the decision is still open, so `decided_at` is NULL at the
moment the hash is recorded, and no later write can move the hash to a time
after the decision — the hash row already exists at an instant the decision
has not yet stamped. `0108`'s own comment says exactly this: *"`decided_at` is
nullable because the row is written while the decision is still open, which is
the only ordering under which pre-registration means anything."*

**The insert cannot name `decided_at`, and that is deliberate.** `_INSERT_SQL`
names four columns; the nullable one takes its `NULL` from the schema rather
than from a value this module passed. A version that wrote `decided_at = NULL`
explicitly would be a statement that *chose* a NULL, and a later feature
editing that clause could choose otherwise; the absent column is a statement
with no opinion to edit. The law is enforced by the *shape* of the writer, not
by a check the writer remembers to make — pinned by a test that parses the
column list and asserts the exact four items (`id` is absent too: `0108`
declares a `DEFAULT` that mints a UUID on both dialects, and a
writer-supplied identity would be a second minter).

## The six criteria, each one published by something this workspace ships

`CRITERIA_FIELDS`, in order, is the closed set the body must state:

| term | the passage that states it |
|---|---|
| `theta` | §12's M3 exit *"Paired ΔIR > 0.3"*; §11.0's selection bar is the same figure from the other side |
| `alpha` | §12's M3 exit states it beside the bar: *"p < 0.05"* |
| `max_fdr_deploy` | §11 makes `FDR_deploy` the primary metric with target *"< 25% at π₀ = 0.9"* |
| `min_worlds` | §11.0's pool bands (*"< 20 worlds: do not run dreaming"*, *"50+: full dreaming"*) and §12's *"≥50 worlds"* |
| `min_coverage_strata` | §C7's coverage ledger; the risk it answers is §14's *"Replay pool is regime-monotone \| High"* |
| `min_forward_days` | §13.4 and arch §M4's 90 days |

The set is **closed both ways**: a body missing a term is refused, and a body
carrying a misspelled seventh term is refused rather than ignored — a
misdirected criterion silently dropped is a criterion the promotion was never
judged against.

`theta` is the one term with no interval: it is an *advantage*, and §11.0
contemplates bars that are not the M3 default, so a floor would be this module
legislating a bar no milestone stated. `alpha` and `max_fdr_deploy` are
probabilities held to `[0, 1]` — α above 1 is not a level, and a ceiling above
1 refuses nothing, which makes it a criterion no promotion could fail. The
three counts are `int` and non-negative, `bool` refused explicitly (every
count validator in this workspace states the reason: `True` is `1` in Python).
A fractional count is **refused rather than coerced** — a fractional world is
not a world, and coercing it would be this module inventing a pool size the
caller did not state.

## The hash is over a canonical document, not over the prose

Two prose spellings of one criterion differ in whitespace, in key order, and
in whether a number was written `0.3` or `0.30`. A hash over the prose would
call those two *criteria*, and a promotion decided under the first would be
refused under the second for a difference nobody decided — which is feature
292's mismatch, produced by feature 291's hash. So the hash is taken over a
canonical document: the six terms as one JSON object, `sort_keys=True`,
`separators=(",", ":")`, then `hashlib.sha256(text.encode("utf-8")).hexdigest()`
— the spelling `criteria_hash CHAR(64)` holds, and the rule the workspace
states for every digest (`artifacts`' `code_hash`, `dreaming`'s).

`0.3` and `0.30` therefore *are* one bar (both canonicalise to the same
float); `50` and `50.0` are *not* one pool (the second is refused). That
asymmetry is the module's, and it is argued in the docstring.

## Re-registration: same hash is a retry, different hash is a refusal

A node's criteria are fixed the first time they are recorded.

- **Same criteria again** → a *retry* (the response was lost, the worker died,
  the caller posted twice). It returns the standing row untouched,
  `pre_registered_at` included. The reason is the coverage ledger's: the
  criteria did not change, so the instant they were fixed did not either, and
  re-stamping would claim a freshness the retry does not have.
- **Different criteria** → **refused**. Immutability is the feature; a body
  that could rewrite the hash would make §13 item 7 vacuous.

**That refusal is not feature 292's.** 292 is *"System rejects a promotion
whose recorded criteria hash differs from the pre-registered value, which
returns a `criteria_mismatch` error message"* — a verdict about *evidence*
read at deciding time. This refusal is a WET write at registration time. So it
is `PromotionError` (the ask face: re-send with the criteria you meant), not a
`criteria_mismatch` verdict, and `promotion.errors`' docstring says so — which
is why a test has to strip docstrings (`conftest.code_of`) before asserting
that the module never names 292's error.

## The error tree: two classes, split by repair

`PromotionError` carries **the ask** — a body that is not the six terms, or a
criteria document that is not the document the hash is *of*. Nothing was read
and nothing was written; the repair is to re-send.

`PromotionStoreError` carries **the address and the write** — a `DATABASE_URL`
this member cannot speak, a database it cannot bring to the revision the row
needs, a row that did not land. Every message opens
`PROMOTION_REGISTRY_ERROR_CODE = "promotion_registry_unwritable"`, the
greppable word, in the family `full_history_fit` / `illegal_theme` /
`pool_frozen` establish. The repair is to the deployment.

The split is the repair's, never the code path's: a malformed body is
refusable without a database at all, and a caller that gathered the two would
read *the store refused me* where the truth is *the body was not the six
terms*. The tree is open — 292's verdict and 295's retirement refusal land
beside it, the way `DiversityClaimError` sits beside `CoverageError`.

## Schema: the member authors no DDL

The one `INSERT` needs `node`, `epoch_ledger` and `promotion_registry` to
exist, and **none of the three is this member's to declare** — `node` is
feature 232's campaign record, `epoch_ledger` is feature 105's sealing
process, `promotion_registry` is `0108`'s.

`bootstrap_schema` runs the **owning migrations' own `statements("sqlite")`
tuples**, loaded by file path, in the chain order `0118 → 0110 → 0108`. Zero
authored DDL, so drift is impossible; each migration's *whole* tuple runs
rather than one statement lifted out (taking one would be this member editing
another's schema, where running the tuple is what "the migration is the
author" means), and nothing is over-created because every statement is
`IF NOT EXISTS`.

**The order is the chain's, not SQLite's demand — and the difference is worth
recording because it is easy to get backwards.** SQLite does **not** resolve a
foreign key's parent at `CREATE TABLE`; it resolves at the **first row
write** (verified against SQLite 3.45.1, the workspace's own), so a
registry-only database is *declared* happily and then refuses every `INSERT`
with `no such table: main.<parent>` — and it names only *one* of the two
missing parents. Postgres validates at `CREATE TABLE`. `0108` states the rule
twice and says which is which; its own words for the tolerance are the ones to
keep: *"That is a tolerance, not a licence: the dependency is real and is
stated twice."* The suite pins the tolerance *and* the dependency it is not a
licence to ignore, and the assertions accept whichever parent SQLite chooses
to name.

## Registration and the seat

One component, `promotion`, registered unprefixed — the `ledger` / `artifacts`
/ `canary` / `discovery` / `regime` precedent for a member's first and only
component. `PromotionCriteria` and the *(migration, table)* order are values;
the **endpoint is deliberately not registered**, because a route is not a
component and the store is what a composed application holds.

`src/app/modules/promotion/__init__.py` is the seat: it answers one question
via `application.get("promotion")`, imports only `app.module_loader` at module
scope, and puts the member class under `TYPE_CHECKING`. The composed
`app.order` carries `promotion` between `policy-runtime` and `providers`.

## Files

| file | what |
|---|---|
| `packages/promotion/src/promotion/criteria.py` | the six-term value, its validators, the canonical document, the hash |
| `packages/promotion/src/promotion/pre_register.py` | the endpoint, the request/response, the record, the store, the bootstrap's caller |
| `packages/promotion/src/promotion/schema.py` | the DDL adapter — the three owners' own statements, by path |
| `packages/promotion/src/promotion/errors.py` | `PromotionError`, `PromotionStoreError`, the code word |
| `packages/promotion/src/promotion/__init__.py` | re-exports, `@register("promotion")`, `COMPONENT_NAME` |
| `packages/promotion/pyproject.toml` | the workspace member |
| `src/app/modules/promotion/__init__.py` | the seat |
| `packages/promotion/tests/` | conftest + criteria / schema / pre-register / component / cross-member suites |
| `.plans/feature-291-promotion-pre-registration.md` | this document |
