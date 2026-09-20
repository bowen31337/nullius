# Feature 62 — discount-token fee reduction

app_spec.xml, "Cost Model & Fill Simulation", feature 62 (depends_on 61):
*System applies a discount-token fee reduction when configured, which
returns an effective 7.5 bps rate in place of 10 bps.*

## Scope

File-claim scope: `src/app/modules/cost-model/**`, `packages/cost-model/**`.
No shared file needs editing, and no migration/store/router: the sentence asks
for an effective *rate*, not a row. The config key already exists and is
already carried by the shipped document
(`fees.discount_token: BNB  # → 7.5 bps`), currently *tolerated and not read*
by feature 61 (see `test_fees.py::test_the_discount_token_field_is_not_read`).

## Design — new module `packages/cost-model/src/cost_model/discount.py`

Sits beside the schedule it reduces, exactly as `queue_penalty.py` does for
the gate it layers on. Resolves from the same single cached parse.

**The reduction is a rate substitution, not a second charge.** `reduce()`
returns a `FeeSchedule` whose rates are already reduced; the post-cost series
then comes from feature 61's own `FeeSchedule.apply`. That keeps the fee
arithmetic in exactly one place — feature 69's promise and §6.2's `β₄`, from
the discount side. `apply()` is literally `self.reduce(schedule).apply(...)`,
asserted structurally in the tests.

Public surface:

- `DISCOUNT_TOKEN_KEY = "discount_token"` (imports `FEES_KEY` from `fees`).
- `DEFAULT_DISCOUNT_FRACTION = 0.25` — 25% off, which is §6.2's own comment
  (`10 → 7.5`) and `docs/alpha-engine-prd.md` §10's "0.1% maker/taker;
  0.075% with BNB deduction". Spelled as the *reduction* so its legal range
  (0…1) is the range a reduction has.
- `FeeDiscount` (frozen dataclass) — `token: str | None = None`,
  `fraction: float = DEFAULT_DISCOUNT_FRACTION`:
  - `configured` — `token is not None`: the feature's *"when configured"* as
    the switch every other method reads.
  - `retained_fraction` — `1 - fraction`, derived so the two cannot disagree.
  - `reduction_bps(bps)` / `effective_bps(bps)` — 10 → 2.5 off → 7.5.
  - `effective_rate(schedule, side)` — `effective_bps(schedule.rate(side))`,
    side coerced by feature 61's own `_coerce_side`.
  - `reduce(schedule) -> FeeSchedule` — both sides reduced, venue carried
    through. *Both* sides because §6.2 carries one `discount_token` per
    schedule and PRD §10 states one deduction on the fee, not a
    side-selective one.
  - `apply(schedule, returns, side)` — feature 61's charge at the reduced rate.
  - `summary()` — token, configured, fraction, retained fraction.
  - Validation: `fraction` a real in `[0, 1]` (above 1 would pay the trader —
    a rebate, which §6.2 has no field for); `token` `None` or a non-blank
    string.
- `discount_fee_schedule(schedule, discount)` — the sentence as a function,
  delegating to `FeeDiscount.reduce` (sibling-module stance).
- `resolve_fee_discount(model=None)` — demands the `fees` block (a discount
  with no fee to reduce prices nothing) and treats `discount_token` as
  *optional*: absent → unconfigured `FeeDiscount`, which is the "when
  configured" clause's ordinary case. Present but blank/non-string → refused
  as a defect of the signed artifact. `taker_bps`/`maker_bps` belong to 61
  and are not read here.

Deliberate refusals, stated in the docstring:
- **No token whitelist and no per-token table.** Any non-blank token name
  configures the reduction. A table mapping BNB → 25% and everything else to
  nothing would be a behaviour §6.2's document does not carry.
- **The reduction is not a document field.** §6.2 names the token and writes
  the arithmetic only as a comment, so the fraction is the library's constant
  — the same stance `require_trade_through: true` and
  `exp_decay_vs_queue_depth` take.
- **The reduction is a share of the venue's own rate, not a constant.**
  `effective_bps` subtracts from the rate it was handed, so a schedule
  pricing 20 bps becomes 15, never the one venue's 7.5.

Wiring:
- `packages/cost-model/src/cost_model/__init__.py` — imports, `__all__`, and a
  feature-62 paragraph in the existing running style (after feature 69's,
  where the discount paragraph belongs chronologically).
- `service.py` — `CostModelService.fee_discount()` resolving from
  `self.document`, mirroring `fees()` / `queue_penalty()` / `passive()`;
  cross-reference from `fees()`'s feature-62 paragraph.
- `errors.py` — no new exception type. Extended `CostModelConfigError`'s and
  `CostModelFillError`'s docstrings to name feature 62 (the defect split: a
  blank token is the document's, an out-of-range fraction is the caller's).
- `fees.py` — four docstring/comment updates where the module said
  `discount_token` "belongs to feature 62, not read here" and now can point at
  the resolver that reads it. No behaviour change; `test_fees.py`'s
  "tolerated and not read" test stays true and untouched.

## Tests — `packages/cost-model/tests/test_discount.py`

Same shape as `test_queue_penalty.py` / `test_fees.py`: a module docstring
mapping each clause of the sentence to its test group, then:

- **the reduction is applied** — the shipped document's 10 bps reaches 7.5 on
  both sides; `reduction_bps` names the 2.5 difference; the reduction is a
  share of the venue's own rate (20 → 15); the venue survives `reduce`.
- **the post-cost series uses the reduced rate** — the series comes back at
  `fee_bps == 7.5`, costs strictly less than the undiscounted one by exactly
  2.5 bps, is subtracted rather than scaled, and preserves length and order.
  Plus the structural claim: `apply` == `reduce(schedule).apply`.
- **when configured** — the shipped document is configured; a document with no
  token resolves *unconfigured* and returns the schedule's own rate (not a
  silent repricing); a YAML null token is the absent field; a blank or
  non-string token is refused; a hand-built `FeeDiscount()` defaults to
  unconfigured; any token name configures.
- **the fraction contract** — 0.25 is the document's arithmetic (checked
  against the definition, not a remembered constant); 0.0 and 1.0 are legal;
  out-of-range, non-finite and boolean fractions are refused; impossible rates
  refused; a zero rate survives.
- **schedule-only, frozen, summary** — a non-schedule is refused; an unknown
  side is refused by feature 61's coercion; the reduced value is the shared
  library's `FeeSchedule` type; `summary()` explains the reduction and says
  `configured: false` when there is none.
- **resolver** — the shipped default; the single-parse seam; non-mapping
  document / missing or non-mapping `fees` refused; the schedule's own fields
  not read here.
- **service seam** — `CostModelService.from_env().fee_discount()` matches the
  default; the documented 10 → 7.5 end to end; a supplied document's token
  routes through; a document without one composes an unconfigured discount;
  the discount and the schedule read one cached parse.
- **exports** — the five public names in `cost_model.__all__`, and the
  package-level names are the module's own objects.

## Verification

1. `uv run pytest packages/cost-model/tests -q` — 445 passed (was 382).
2. `uv run pytest tests -q` — 973 passed (the repo-level acceptance gate).
3. `uv run ruff check` on each changed file — "All checks passed!", matched
   against a sibling (`queue_penalty.py`) as the baseline, since repo lint is
   red on main.
4. Smoke test through the composed application
   (`create_app().get("cost-model")`): token `BNB`, taker/maker 10.0 → 7.5,
   series charged at 7.5.
