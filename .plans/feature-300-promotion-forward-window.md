# Feature 300 — the promotion timestamp, and the forward window it opens

**app_spec.xml, "Promotion & Epoch Governance", feature 300**
(`shape="plugin"`, `plugin="promotion"`, `depends_on="293"`): *System timestamps
every promoted signal at promotion, which creates its forward measurement
window.*

Declared file-claim scope: `src/app/modules/promotion/**`, `packages/promotion/**`.

## What the sentence means, and what it does not

Every noun in it is already in the schema. `promotion_registry`
(`migrations/versions/0108_forward_and_universe_tables.py`) holds
`decided_at TIMESTAMPTZ` — feature 293's stamp — and 293's own module names this
feature as its downstream reader three times:

- `decision.py:585` — *"feature 300's forward measurement window opens at this stamp"*
- `decision.py:362` — *"the readers asking it (feature 294's epoch charge, feature 300's forward window, feature 360's invariant)"*
- `errors.py:374` — *"feature 300 opens the forward measurement window at this stamp"*

and `criteria.py:263` already carries `min_forward_days` — *"the forward window
the promoted signal must be measured over … the window feature 300 timestamps
open."*

So the three facts the sentence names are **which signal** was promoted
(`promotion_registry.node_id`, closed), **when** (`decided_at`), and **how long**
the window runs. The window's *end* is derived — `decided_at + days` — which is
why the row carries neither an end date nor a duration column.

**The tempting alternative — reading `forward_record.promoted_at` — is the wrong
table, and the plan refuses it by name.** `forward_record` belongs to the
`forward` plugin (created by feature 108; features 332-340 are
`plugin="forward"`), and its writer is feature 332's `POST /forward/promote`
(*"Register a promoted signal and start its forward window"*). Feature 300 is
`plugin="promotion"` with `depends_on="293"` — the decision — so its job is the
*promotion-side* timestamp 332 reads, not a second writer of another plugin's
table with `observed_on`/`live_ic` columns only 333/335 fill.

## The decisions this feature takes

**1. A read, not a write.** There is nothing to persist: `decided_at` *is* the
promotion timestamp, and the row cannot be closed twice (293's `_UPDATE_SQL`
carries `AND decided_at IS NULL`). So this feature *answers* the window. A new
column would need an `ALTER TABLE` on a table whose six columns the spec declares
and whose DDL stops at `0108` — the refusal `blocking.py` argues at length.

**2. It reads through 293's own seam, and spells no `SELECT` of its own.**
`PromotionDecisions.decision(node)` already answers *this node's row, open or
closed* and already refuses the two-row and corrupt-row cases in its own
vocabulary. A second registry `SELECT` here would be a second reading of one
table — the discipline `decision.py:639` states when it reuses
`pre_register._READ_SQL` rather than restating it. So `PromotionWindows` is
constructed over a `PromotionDecisions` (duck-checked, like
`PreRegisterEndpoint` duck-checks `pre_register`) and owns no connection, no
bootstrap and no DDL at all.

**3. Only a *closed* row opens a window.** An open row is a pre-registration —
the evaluation has not run, so there is no promotion to timestamp. Refused by
name, with the repair being 293's act, not answered with a `None` start.

**4. No merit judgement — the opposite of 299.** 299's `record_block` refuses a
call whose figures contradict the finding. This feature refuses nothing about
merit: whether the promotion *stands* is the deciding evaluation's, and the
mismatch check is 292's.

## The window's length is the caller's, and that is forced, not chosen

`promotion_registry` holds `criteria_hash`, not the criteria document, and
sha256 is one-way — so `min_forward_days` **cannot** be recovered from the row.
Two resolutions, both rejected on existing boundaries:

- **Rejected — put the length on the row.** `ALTER TABLE` on a table this member
  may not edit. Same argument as `blocking.py`'s three reasons.
- **Rejected — recompute the hash from a caller's criteria document and compare.**
  That is *feature 292's* `criteria_mismatch`, and `decision.py:44-51` states the
  boundary explicitly: *"this module does not pronounce it; nothing here spells
  `criteria_mismatch`."* A window store doing this would re-implement 292 behind
  another name.

So `forward_days` arrives as a required keyword, and the record **carries the
`criteria_hash` it was read under** — the row's own value — so a later reader
sees which criteria set the window was opened against. That field is what makes
the length auditable rather than merely asserted; the repair for a wrong length
is 292's comparison, run by the caller holding the document.

## Implementation

### `packages/promotion/src/promotion/forward.py` (new)

The member's eighth module, in the shape `blocking.py` and `calibration.py`
take: module docstring stating the law and the boundaries, `__all__`, named
column constants, validators that translate sibling refusals at the seam, a
frozen record, a store, and module-level spellings.

- **Constants.** `PROMOTED_AT_COLUMN = DECIDED_AT_COLUMN` — one column, two
  readers' names for it (293 calls it *the decision's stamp*; this calls it *the
  promotion's instant*), the value read off `pre_register` rather than re-spelled.
  Plus `WINDOW_DAYS_COLUMN`, `OPENS_AT_COLUMN`, `CLOSES_AT_COLUMN`.
- **`PromotionWindow`** (`@dataclass(frozen=True, slots=True)`): `node_id`,
  `criteria_hash`, `epoch_id`, `opened_at` (aware-UTC), `window_days` (positive
  int); derived `closes_at` and `horizon` as **properties** (not fields, so they
  stay out of the value's identity), plus methods taking the instant they are
  asked about: `elapsed_by(instant)`, `remaining_at(instant)`, `open_at(instant)`,
  `elapsed_days(instant)`, and `row()`. Validated in `__post_init__` — the read
  path rebuilds it past a factory's nose, so the checks live there
  (`blocking.py`'s move). A zero-day window is refused: it is a window that never
  opened. The dataclass spelling is what buys equality over the five stored
  fields, which the module-level tests rely on; properties rather than fields is
  what keeps `closes_at` from colliding with a generated slot.
- **`window_closes_at(opened_at, days)`** — the arithmetic on its own, for a
  caller holding the stamp and the horizon but not the record. Validates the
  horizon *before* adding, so a malformed length is refused as a length rather
  than surfacing as a `TypeError` from inside `timedelta`.
- **`_closes_at(opened_at, days)`** — the one place the sum is taken, and the
  reason it exists is the least obvious decision in this feature. A horizon can
  be a legal count and still have no computable end: `999_999_999` is the largest
  `timedelta` will accept, but the *sum* with a real stamp leaves
  `datetime.max`, and `10**10` is not even a legal `timedelta` argument. The
  first attempt at this bounded the count statically
  (`MAX_WINDOW_DAYS = dt.timedelta.max.days`) and **was wrong in both
  directions** — too loose, because `999_999_999` passed the bound and then
  leaked a bare `OverflowError`; and necessarily too tight, because the
  reachable ceiling is a function of `opened_at`, so no static figure is
  correct. The constant was removed, and the check lives where the sum is
  actually taken: `OverflowError` is caught and re-raised as
  `PromotionWindowError` naming both figures. Both `PromotionWindow.closes_at`
  and `window_closes_at` route through it, and `__post_init__` calls it **eagerly**
  so construction refuses a record whose end is uncomputable — otherwise a
  property read would explode after a caller's `try` around the constructor had
  already returned, which is the worst possible shape for this defect. Later
  property reads are consequently infallible.
- **`PromotionWindows`**: `__init__(decisions)` duck-checked on the store's **two**
  read verbs — `decision` for one node's row and `decisions` for the listing —
  and refusing a class object as well as a non-store, since a class passes a bare
  verb check and then fails confusingly on the first call; `from_env(env)` →
  `None` without a `DATABASE_URL`; `decisions` property; then
  - `window(node_id, *, forward_days)` → `PromotionWindow`
  - `windows(*, forward_days)` → `tuple[PromotionWindow, ...]`, skipping open rows

  Read-only: no `record_*`, no write SQL, no `_connect`, no `SELECT`. The
  duck-typed store is why the loader's synthetic-name copies work.
- **Module-level** `promotion_window(node_id, *, forward_days, database_url=None, env=None)`
  and `promotion_windows(...)`, resolving the URL exactly as
  `decision._resolved_url` does, restated in this feature's vocabulary.

### `packages/promotion/src/promotion/errors.py` (extend)

`PromotionWindowError(PromotionError)` — the member's sixth class, a **sibling**
rather than a face of `PromotionDecisionError`. In the tree's own terms (split by
repair): 293's class says *a decision happened and was not recorded* and its
repair is to the write; this says *a window could not be opened* and its repair
is to the **registration state** — pre-register first, or wait for the decision —
a different act with a different caller (the forward member, not the promotion
path's last line). Code word
`PROMOTION_WINDOW_ERROR_CODE = "promotion_window_unopened"`, spelled beside the
other two and distinct from both.

Faces **gathered** in the one class, for the reason 299's and 293's are: this
feature's caller is also a gate, and a gate's one failure mode is silence. A
window that quietly did not open leaves the `forward_record` writer with no start
instant — the state `0108`'s docstring names: *"a row that lost its promotion
timestamp would be an observation with no vintage."*

### `packages/promotion/src/promotion/__init__.py` (extend)

Re-export the new names; add them to `__all__`; update the "seven modules"
docstring paragraph to eight in the same voice as its neighbours. The one
component and the one `build_*` name are **unchanged** — no state is composed by
this feature, the argument `blocking.py` and `calibration.py` both make.

### `packages/promotion/tests/test_promotion_forward.py` (new)

House style: the boundary first (never writes `forward_record`, never spells
`criteria_mismatch`, never imports another member, authors no DDL, composes no
component); then the arithmetic (`closes_at`, `elapsed_by`, `open_at` at both
edges — the half-open interval); the read; the open-row and absent-row refusals;
two reads comparing equal; the vocabulary; the module-level spellings. The store
holds the raw-`SELECT` fixture to prove nothing was written.

Two tests are worth naming because they exist to catch a *specific* later
mistake. `test_the_listing_answers_every_promoted_signal_not_just_one` uses a
four-row fixture (two closed, two open, distinct stamps): every other listing
test used a single row, so truncating the listing to `decisions()[:1]` left all
fifty pre-existing tests green — the word "every" in the sentence was untested
until this fixture existed. And
`test_a_record_whose_end_is_uncomputable_is_refused_at_construction` pins the
eager sum in `__post_init__`, so a later author who moves the check back out to
`closes_at` (where it reads more naturally) fails there rather than in
production.

## Verification

```sh
cd packages/promotion && PYTHONPATH=src:../../src uv run --no-sync pytest tests/ -q
```

Baseline **330 passed**; the suite now stands at **386 passed**, with the
existing tests green — the four files asserting `build_*` and the seat's
`__all__` stay untouched by design. Then `ruff check` on the four touched files
only (never `--stdin-filename`).

The repo-level `tests/` suite still errors on collection in
`test_contract_violation.py` and `test_signal.py`: both are the pre-existing
`polars`/`pyarrow` environment gap (neither file mentions promotion), unchanged
by this feature.

## Out of scope, named so it is not read as an omission

- No writer of `forward_record` — feature 332's (`plugin="forward"`).
- No `criteria_mismatch` — 292's. No epoch charge — 294's.
- No route: the spec's API summary lists no promotion route beyond
  `/promotion/pre-register`, so this answers a Python seam like 293, 298 and 299.
