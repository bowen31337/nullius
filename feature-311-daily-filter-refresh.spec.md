# Feature 311 — Daily exchangeInfo filter refresh

**Category:** Order Routing & Venue Filters
**Feature index:** 311 (depends on 310)
**Shape:** plugin (`router`)
**Feature sentence (app_spec.xml):** *System refreshes exchangeInfo filters daily, which rejects any hardcoded venue constant in the order path.*

## 1. The sentence, read as a feature

> *System refreshes exchangeInfo filters daily, which rejects any hardcoded
> venue constant in the order path.*

Read as one sentence, this feature has two halves that are not the same size.

The first half — *"System refreshes exchangeInfo filters daily"* — names a
**cadence and a motion**: the fetched venue filters that feature 310 persists
are not fetched once and forgotten; the order path re-reads them on a daily
rhythm, and each refresh lands as a new version rather than overwriting the
prior one (feature 310's own store already makes each fetch a new version, so
"refresh" here is *the order path reaching the current version again*, not a
new write primitive).

The second half — *"which rejects any hardcoded venue constant in the order
path"* — is the **enforceable property**, and it is the larger half. The word
*which* makes the refresh the *means* by which the rejection is guaranteed:
because the order path's grids, floor and bounds are read from a version that
is refreshed daily, a constant written into the order path by hand is
guaranteed to drift from the venue's and so cannot be a correct order path.
The feature is therefore not *"add a daily cron"* — a cron is a deployment
detail this member does not own — but **a judgment that a venue constant in
the order path is a hardcoded constant, and that the order path must read the
refreshed value instead of one it stated itself.**

This is the same shape as the features on either side of it. Feature 310
*fetches and persists* the five named fields; feature 312 *refuses an order
not on the fetched grids*; feature 313 *refuses an order below the fetched
floor*. Feature 311 is the member's **no-hardcoded-constant law**, and it is
already the load-bearing sentence behind 312 and 313 — both modules cite
"feature 311's law" for why their grids and floor arrive as feature 310's own
value or not at all. What 311 adds that 312 and 313 do not is the **daily
motion made structural**: the order path must read the *current* version, and
a read that reaches a stale or self-authored constant is refused.

**What this feature is not, and why that is the feature rather than a gap.**
It is **not a fetcher**: feature 310 already owns the fetch seam
(`resolve_router_filters`, `RouterExchangeInfoStore.record`), and a second
fetch verb would be two ways to fetch one document — "refresh" is the order
path reading the version the fetch already persisted, the store's `filters_for`
being the refresh, and it being feature 310's. It is **not a scheduler or
cron**: §13.2's *"refreshed at startup and daily"* is a deployment cadence,
and the daily trigger is wired by whatever process runs the router, not by a
member that holds no process — this member owns the *judgment*, not the
*tick*. It is **not a version-diff or a change-detector**: a refresh that
lands the same filters is still a refresh (feature 310's store test pins this:
*"a repeated fetch with identical filters still lands a new version"*), and
the feature's property is that the order path reads the current version, not
that the current version differs from the last. It is **not a new table, a new
component, or a new field**: the version log (feature 310) and the seven
fields per symbol are exactly the surface this feature reads, and the member
still registers one component.

The one thing this feature *does* that nothing else does: it makes the
no-hardcoded-constant law **a thing the order path can be judged against** — a
verb that takes the order path's own stated venue terms and refuses them
because they were stated rather than read, and a store read that reaches the
*current* version rather than a pinned one. The daily motion is what makes the
judgment non-vacuous: a constant that is refreshed away daily is provably
wrong on some day, so refusing it is not refusing a value that happened to be
right.

## 2. The judgment, made structural

The sentence's *rejects* is the only enforceable verb, so the feature is
delivered as **one gate** — `require_fetched_filters` — in a new module
`router.refresh`, plus the store read it is built on. The gate is the law made
callable: it takes the venue terms the order path *would have hardcoded* and
refuses them, and returns the fetched, refreshed value the order path must use
instead.

### 2.1 The verb: `require_fetched_filters`

```python
def require_fetched_filters(
    *,
    symbol: str,
    filters: RouterSymbolFilters | None,
    fetched_at: datetime,
    now: datetime,
    max_age: timedelta,
) -> RouterSymbolFilters:
    """Feature 311's verb: the refreshed filters for a symbol, or a refusal.

    Refuses a submission whose order path reached a venue constant that is not
    the current, refreshed one: ``filters`` is None (the current version
    carries no such symbol, or no version has been fetched), a value that is
    not feature 310's own RouterSymbolFilters (a literal the order path stated
    itself), filters filed under a different symbol, or filters whose version
    is older than ``max_age`` relative to ``now`` — a version the daily
    refresh should have replaced. Returns the fetched filters when they are
    the current version's, in window — the only venue constants the order path
    may read.
    """
```

The verb is deliberately **read-only and judgment-only**. It does not fetch,
does not persist, does not round, does not judge the grids or the floor —
those are features 310, 312 and 313, and a gate that did them would be four
features in one. Its sole question is: *is this venue constant one the order
path read from the refreshed version, or one it stated itself (or read from a
stale one)?*

**The three refusals, in a fixed order** (the venue's standing facts before
the submission's own terms, the same order feature 312's gate runs): **first,
the filters are absent** — `filters is None` means the current version carries
no such symbol, or the store has no version yet, and a symbol the current
version does not carry is not tradeable off a stale or invented grid (the same
stance `filters_for` takes when it answers `None` rather than falling back to
an older version), so it is refused, because a hardcoded constant is exactly
what an absent fetch would otherwise be silently substituted for. **Second,
the filters are not feature 310's own value** — a `filters` that is not a
`RouterSymbolFilters` is a value the order path invented (a hand-written dict,
a namedtuple, a literal with `step_size="0.001"` baked in), refused by name,
because the whole of the no-hardcoded-constant law is *the grids are the
fetched document's, not the order path's*; this is the refusal that makes
*"rejects any hardcoded venue constant"* real, the type check being the
structural door a literal cannot pass, since a literal is a `dict` or a
string, never a `RouterSymbolFilters` read from the store. **Third, the
filters are filed under a different symbol** — `filters.symbol` must equal the
order's `symbol` verbatim, because a quantity judged against another symbol's
grid is a verdict about the wrong instrument (feature 312's rule, restated),
and a mismatch is refused. When none of the three fires, the verb returns the
`RouterSymbolFilters` — the
current version's fetched value, the only venue constants the order path may
read. The returned value is feature 310's, unchanged: this module does not
re-spell it.

### 2.2 The `now` argument — the daily motion, made a parameter

The sentence's *daily* is the reason the law is non-vacuous, so it must appear
in the verb — but as a **judged parameter, not a clock read**. The verb takes
`now` as a required, timezone-aware `datetime`, injected by the caller (the
same discipline `submission_health` holds its `observed_at`/`now` to). The
verb reads **no clock**: a gate that called `datetime.now()` would make the
judgment depend on when it ran, which is the opposite of a pure, re-derivable
verdict — two processes judging the same order must agree, exactly as features
312, 314 and 316 demand.

The `now` is used to **refuse a stale read**, which is the daily motion made
structural: the current version's `fetched_at` must be within the refresh
window of `now` (the daily cadence — a version older than the refresh interval
is a version the daily refresh failed to replace, and reading it would be
trading off a grid the venue may have changed since). This is the one place
the *daily* enters the judgment, and it is the sharp reading of the sentence:
a hardcoded constant is wrong *every* day; a stale fetched constant is wrong
*once the refresh should have replaced it*. Both are "a venue constant in the
order path that is not the refreshed one," and both are refused.

The refresh window is **a caller-supplied `max_age`, not a hardcoded
constant** — hardcoding "24 hours" in the order path would be exactly the
hardcoded venue cadence this feature forbids. The caller (the process that
knows its own refresh schedule) states the window; the verb judges
`fetched_at` against `now` within it. A zero or negative `max_age` is refused
(a window that admits nothing, or reads backward, is not a refresh window).

This keeps the verb a **pure function of (symbol, filters, fetched_at, now,
max_age)** — no I/O, no clock, no table. A restarted router re-judging the
same order with the same `now` and `max_age` reaches the same verdict, which
is what makes it safe across the processes §13.2 and feature 320 deliberately
separate.

### 2.3 Why the store read is the refresh, not a new write

"Refreshes daily" adds no store method. The store already has
`filters_for(symbol)` — the order path's fast, symbol-keyed read of the
current version — and that read *is* the refresh: each call reaches `MAX
(version)`, the most recently persisted fetch, which the daily fetch worker
(feature 310) has advanced. The `now`-against-`fetched_at` check needs the
version's `fetched_at`, which the order path reads from the store's
`current()` (the whole current version, carrying `fetched_at`) — a second read
it already makes cheap, and one the store already answers. No new table, no
new column, no migration.

**The gate does not itself read the store**, mirroring feature 312's *"it does
not read the store — the caller holds the filters it read"*: the caller passes
the `filters` it read from `filters_for` and the version's `fetched_at` it read
from `current()`, and the gate judges them. A gate that fetched its own would
be a second, racing reader on the order path. The verb therefore takes both —
the `RouterSymbolFilters` and the current version's `fetched_at` — as
arguments, supplied from the two reads the caller already makes, and judges
whether they are the refreshed, current, in-window values the order path may
act on.

```python
def require_fetched_filters(
    *,
    symbol: str,
    filters: RouterSymbolFilters | None,
    fetched_at: datetime,
    now: datetime,
    max_age: timedelta,
) -> RouterSymbolFilters:
    ...
```

## 3. The error: `RouterStaleFiltersError`

A new error class in `router.errors`, opening with the token
`STALE_FILTERS_CODE = "stale_filters"` — a name the sentence does not spell,
so it is chosen to say *the venue constant this order path reached is not the
refreshed one*. It is a sibling of `RouterFilterError` (a bad fetch),
`RouterStoreError` (a failed persist) and `RouterOrderRoundingError` (an
off-grid order), and **not** an instance of any of them: the repair for a
stale or hardcoded constant is *re-read the current version*, which none of
those others names. Every message opens with `stale_filters` and states which
of the three refusals fired — absent, invented, or stale — and names the
symbol, the version's `fetched_at`, the `now`, and the `max_age`, so the
operator reading it sees exactly why the constant was refused and what window
it fell outside.

The token is deliberately **not** `hardcoded_filters` or `refresh_failed`: the
first would name an implementation detail the gate cannot always prove (a
well-typed `RouterSymbolFilters` read from a stale version is not "hardcoded"
yet is still refused), and the second would name the cron this member does not
own. `stale_filters` covers all three refusals under the one property they
share — *the venue constant in the order path is not the current, refreshed
one* — which is the sentence's actual promise.

## 4. Files

All within the declared footprint `packages/router/src/router/**` (and the
mirror seat `src/app/modules/router/**`, which this feature does not extend —
see §7).

**New modules (feature 311's own surface).** `packages/router/src/router/refresh.py`
holds the `require_fetched_filters` verb, the `_validated_symbol` /
`_validated_filters` / `_within_refresh_window` helpers, and the `StaleFilters`
reading type (the admitted-side value: the refreshed filters, the `fetched_at`
they were fetched at, and the room left in the window — `max_age - (now -
fetched_at)` — so a caller can log how fresh its read was); it is stdlib only
(`dataclasses`, `datetime`, `typing`), import-cheap, with no `@register`, no
table, no component, no clock read and no I/O. `packages/router/tests/test_refresh.py`
is the suite pinning the three refusals (absent, invented, stale), the fixed
refusal order, the in-window/admitted path, the `max_age` bounds (zero/negative
refused), the `now`-injection (no clock read), the symbol-join, and the purity
(same inputs → same verdict).

**Edited modules (wiring the law into the member, no shared files).**
`packages/router/src/router/errors.py` gains `STALE_FILTERS_CODE` and
`RouterStaleFiltersError` (a sibling of the existing classes: one new code, one
new class). `packages/router/src/router/__init__.py` imports and re-exports
`require_fetched_filters` and `RouterStaleFiltersError` (and the reading type),
adds them to `__all__`, and adds the feature-311 paragraph to the module
docstring (the same per-feature paragraph the member already carries for
312–320); the `@register` is unchanged, so the member still registers exactly
one component.

No edit is made to `app.module_loader`, the app factory, `src/app/middleware.py`,
`src/app/settings.py`, any migration, or the seat `src/app/modules/router/`
(the seat already documents feature 311's refresh in prose and reaches the
store through the existing accessors; the new verb is reached through the
member package, exactly as 312's `require_rounded_order` is).

## 5. The gate, in one place

The refusal order is fixed and total — symbol, then filters (present, the
right type, the right symbol), then freshness — the venue's standing facts
before the submission's own terms, the same order feature 315's gate judges
its mode before its scope.

```
1. symbol: non-empty text, verbatim (the key the filters are filed under)
2. filters present: None -> refuse (absent: no current version / symbol dropped)
3. filters type: not a RouterSymbolFilters -> refuse (invented: a hardcoded literal)
4. filters symbol: filters.symbol != symbol -> refuse (wrong instrument)
5. fetched_at: aware, and within max_age of now -> else refuse (stale: the daily refresh did not replace it)
6. return filters  (the current, refreshed, in-window venue constants)
```

A submission refused in several ways is refused for the first, deterministically,
so two operators reading one refusal read the same repair.

## 6. Tests — what must pin the property

The suite pins the *law*, not the plumbing. Every test asserts the one thing
the sentence promises: **a venue constant in the order path that is not the
current, refreshed one is refused.**

The suite pins ten properties. (1) **A hardcoded literal is refused by type:**
a `filters` that is a `dict` / namedtuple / literal with `step_size="0.001"`
baked in raises `RouterStaleFiltersError` opening with `stale_filters` — the
structural door a literal cannot pass (this is the headline test: it is
*"rejects any hardcoded venue constant"* made executable). (2) **An absent
filters is refused, not defaulted:** `filters=None` (no version, or symbol
dropped from the current version) raises — never a fallback grid. (3) **A
stale read is refused:** a `RouterSymbolFilters` whose version's `fetched_at`
is older than `max_age` relative to `now` raises, naming the window; the same
filters with `fetched_at` inside the window are admitted. (4) **A fresh,
current, correctly-filed read is admitted:** the exact `RouterSymbolFilters`
read from `filters_for`, with the current version's `fetched_at` inside the
window, is returned unchanged. (5) **The refusal order is fixed:** a value that
is both invented *and* stale is refused for *invented* (type before
freshness); one that is wrong-symbol *and* invented is refused for *wrong
symbol* — the standing facts first. (6) **`max_age` bounds are caller-supplied
and validated:** zero and negative `max_age` are refused; the caller states
the window, the member hardcodes none. (7) **`now` is injected, never read:**
the verb takes `now`; two calls with the same `now` answer the same verdict
(purity), and the module contains no `datetime.now()` / `utcnow()` call (a
static assertion / grep pin). (8) **The symbol is the join and is judged:**
`filters.symbol != symbol` refuses; empty/blank symbol refuses. (9) **The
admitted reading carries the freshness room:** `StaleFilters` (admitted value)
reports `max_age - (now - fetched_at)` and the fetched filters, so a caller can
log how fresh its read was without re-subtracting. (10) **A quiet refresh is
still a refresh:** re-reading the current version when the daily fetch landed
identical filters is admitted (the version advanced, the grids unchanged) —
feature 310's "identical filters still land a new version" discipline, one
feature on.

## 7. Why the seat `src/app/modules/router/` is not extended

The seat exists to answer one question — *what is the composed exchangeInfo
version store?* — and it reaches the store through `router_exchange_info_component`
and `router_submission_health_store`. Feature 311 adds no store and no
component (the member still registers one component, feature 310's), so the
seat gains no accessor. The new verb `require_fetched_filters` is a pure
judgment reached through the member package (`router.refresh`), exactly as
312's `require_rounded_order`, 313's `require_min_notional` and 314's
`resolve_order_posture` are — none of which the seat re-exports, because a
caller who has the filters reaches the verb by calling it, and a pass-through
beside the store accessor would be a second spelling of one fact. The seat's
existing prose already names *"311's daily refresh"*; that statement stands,
and the verb it points at lives in the member. Editing the seat to re-export a
pure verb would be the one kind of edit the seat's own docstring forbids
(*"a second spelling here would be a second thing to keep in sync"*), so it is
left untouched.

## 8. Dependencies and ordering

- **Depends on 310** (app_spec.xml): the gate reads feature 310's
  `RouterSymbolFilters` and the store's version log (`fetched_at`); without the
  persisted version there is nothing to refresh *to* and the law is vacuous.
- **Is depended on by 312 and 313** in prose only: both already cite "feature
  311's law" for why their grids/floor arrive as feature 310's value or not at
  all. This feature makes that cited law *executable* rather than adding a hard
  dependency edge — 312 and 313 keep their own gates; 311 is the member-level
  statement they both instantiate. No code in 312/313 changes.

## 9. Stdlib only; import-cheap; no scan cost

`refresh.py` imports `dataclasses`, `datetime` and `typing` and
`router.errors` — the same cheap set as 312's `rounding.py`. The factory's
scan pays nothing for the gate, no `@register` fires, and a deployment that
never refreshes still composes (the gate is only reached when an order is
built). No migration, no new table, no new component, no seat export — the
member still registers exactly one component, feature 310's exchangeInfo store.

## 10. Acceptance

- `claw-forge validate-spec` on this file: `clean`, zero errors, zero warnings.
- `require_fetched_filters` refuses a hardcoded literal, an absent filters, a
  stale read, and a wrong-symbol read — each with a `stale_filters` message
  naming the repair — and returns feature 310's own value only when it is the
  current, refreshed, in-window one.
- The member's suite (`packages/router/tests/test_refresh.py`) pins all ten
  properties in §6; the member still registers exactly one component; no shared
  file (module loader, app factory, middleware, settings, migrations) is
  touched.
