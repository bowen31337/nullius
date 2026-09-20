# Feature 64 — queue-position penalty on every passive fill

app_spec.xml, "Cost Model & Fill Simulation", feature 64 (depends_on 63):
*System charges a queue-position penalty in basis points on every passive
fill, so a zero-maker venue still returns a nonzero cost.*

## Scope

File-claim scope: `src/app/modules/cost-model/**`, `packages/cost-model/**`.
No shared file needs editing. The config key already exists
(`fill_model.passive.queue_position_penalty_bps: 1.5`), so §6.2's document
needs no change — the value is already carried and is currently *tolerated
and not read* by features 63/65/66.

## Design — new module `packages/cost-model/src/cost_model/queue_penalty.py`

Sits beside the gate it layers on, exactly as `fill_probability.py` does for
feature 65. Resolves from the same single cached parse.

Public surface:

- `QUEUE_POSITION_PENALTY_KEY = "queue_position_penalty_bps"` (plus local
  `FILL_MODEL_KEY` / `PASSIVE_KEY` spellings, as in the sibling modules).
- `_BPS_PER_UNIT = 10_000.0` — the same constant `book_walk.py` uses, and
  the unit §6.2's fee schedule speaks. Spelled once in each module rather
  than imported across, matching how the member already does it.
- `QueuePenalty` (frozen dataclass) — the penalty as a value:
  - fields: `penalty_bps: float`, `fill: PassiveFillDecision`
  - `penalty_fraction = penalty_bps / 10_000`
  - `charged: bool` — `fill.fills` (the penalty is charged *on* the fill)
  - `cost_bps: float` — the penalty in bps actually charged: `penalty_bps`
    when the order filled, `0.0` when it did not. This is the sentence's
    "on every passive fill": no fill, no charge.
  - `cost_fraction` — `cost_bps / 10_000`, the number a caller multiplies
    into a notional or adds to a fee.
  - `is_zero_cost` / `nonzero_cost` — the audit hook for the feature's
    *"so a zero-maker venue still returns a nonzero cost"*: a fill at any
    configured `penalty_bps > 0` returns nonzero, even when `maker_bps` is
    `0.0`. (Note the property is about this penalty alone; the venue's maker
    fee is features 61-62 and is not read here.)
  - `summary()` — a persistable mapping, mirroring the sibling modules.
  - Validation: `penalty_bps` must be a finite, non-negative real (a rebate
    would make the penalty a credit, which it is not; a NaN/±inf is refused
    as non-finite), `fill` must be a `PassiveFillDecision`.
- `charge_queue_position_penalty(fill, penalty_bps) -> QueuePenalty` — the
  sentence as a function.
- `QueuePositionPenaltyModel` (frozen dataclass) — `penalty_bps` field with
  the §6.2 default `1.5` (matching the shipped document, as
  `PassiveFillModel`/`FillProbabilityModel` default from the document), a
  `__post_init__` validation, and `.charge(fill)` delegating to the module
  function.
- `resolve_queue_position_penalty_model(model=None)` — demands the §6.2
  shape (`fill_model` → `passive` → `queue_position_penalty_bps`) and
  refuses every missing/non-mapping level by name, mirroring the three
  existing resolvers verbatim in structure and error-message style. `None`
  reads the shipped default.

Deliberate refusals, stated in the docstring (matching the library's
one-behaviour stance):
- A **strictly positive** penalty is not demanded; `0.0` is a legal document
  value (a venue that genuinely charges nothing) and is answered with an
  honest zero cost rather than refused.
- Missing `queue_position_penalty_bps` **is** refused: unlike feature 63's
  `require_trade_through` (which tolerates the sibling fields), this field
  *is* this feature's one input, and defaulting a cost to zero silently is
  exactly the "simulator will lie" failure `docs/alpha-engine-prd.md` §10
  names.

Wiring:
- `packages/cost-model/src/cost_model/__init__.py` — import and `__all__`
  the new symbols; add a docstring paragraph for feature 64 in the existing
  running style (feature 63 → 65 → 66 → 67 order is already chronological;
  insert feature 64's paragraph after feature 63's).
- `service.py` — add `CostModelService.queue_penalty()` resolving from
  `self.document`, mirroring `passive()` / `fill_probability()` /
  `aggressive()`.
- `errors.py` — extend `CostModelFillError`'s docstring to name feature 64
  (the class already covers 63/65/66; no new exception type).

No migration, no store, no router: the sentence asks for a charge, not a row
— feature 79's evaluator `apply_costs` is the persisting step and consumes
the shared library through its injected `CostSchedule` seam.

## Tests — `packages/cost-model/tests/test_queue_penalty.py`

Same shape as `test_fill_probability.py` / `test_passive_fill.py`: a module
docstring mapping each clause of the sentence to its test group, then:

- **the penalty is charged on every fill** — a filled decision is charged
  exactly `penalty_bps`; the charge is the *fill's* consequence.
- **a rejected fill is charged nothing** — a touch-only decision
  (`fills=False`) costs `0.0`, and `charged is False`.
- **a zero-maker venue still returns a nonzero cost** — the headline case:
  at the document's `1.5` bps a filled passive order returns
  `cost_bps == 1.5 != 0`, asserted against the shipped document via the
  resolver, i.e. the zero-maker scenario.
- **bps arithmetic** — `1.5 bps == 0.00015` as a fraction, checked against
  the definition rather than the implementation's output; the constant is
  `10_000`, not `100` or `1_000_000`.
- **the value is honest about its evidence** — `summary()` round-trips the
  fill's own gate and limit price; the two cannot disagree.
- **input contract** — negative / NaN / inf penalty refused; a boolean
  refused (`isinstance(True, int)`); a non-`PassiveFillDecision` fill
  refused; frozen (`AttributeError` on assignment).
- **resolver** — the shipped default resolves to `1.5`; a document whose
  penalty is `0.0` resolves (legal); each missing level (`fill_model`,
  `passive`, the key) and each non-mapping level is refused; the passive
  section's *other* fields are tolerated and not read.
- **service seam** — `CostModelService.from_env().queue_penalty()` matches
  the module function, and reads the one cached parse alongside
  `passive()` / `fill_probability()` / `aggressive()`.

Also update the sibling suites' "other fields are tolerated and not read"
comments/tests only if a name collides — they currently say
`queue_position_penalty_bps` belongs to feature 64, which stays true; no
edit expected.

## Verification

1. `uv run pytest packages/cost-model/tests -q` (currently 256 passing after
   `uv sync --all-packages`; the env needed pyyaml/polars/pyarrow, per the
   known repo gap).
2. `uv run pytest tests -q` for the repo-level acceptance gate.
3. Ruff on the changed files only, compared against a sibling's baseline
   (repo lint is red on main).
