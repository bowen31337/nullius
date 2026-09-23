# Feature 285 — the promotion block on regime coverage

**app_spec.xml, "Regime Coverage Strata", feature 285**
(`shape="plugin"`, `plugin="regime"`, `depends_on="284"`): *System rejects a
promotion when the target deployment regime has coverage below the configured
threshold.*

A seventh sentence in the existing regime member (`packages/regime/`), not a new
member, and the judgment `regime.__init__` has been promising since feature 283:
*"feature 285's promotion block and feature 289's diversity refusal are
thresholds applied to counts the caller read through this store."*

## The sentence, and the PRD line it enforces

PRD §C7 states the rule as an action taken at the door:

> - Maintain an explicit ledger: `{high-vol trend: 2, low-vol chop: 14, crash: 0, …}`.
> - **Block promotion** when the regime being deployed into has coverage below threshold.

The §14 risk table files the hazard as **High** — *"Replay pool is
regime-monotone"* — mitigated by *"§C7 coverage ledger with promotion block"*.
So this feature is the *block*: the ledger feature 283 writes and feature 284
reads becomes the gate a promotion has to clear, and the sentence's subject is
one **named stratum** — *the target deployment regime* — not the ledger's shape.

## The figure is one stratum's count; feature 289's figure is how many hold worlds

The distinction from its sibling is the whole design, and both siblings are
judged over the same reading (feature 284's `CoverageLedger`):

| feature | question | figure |
|---|---|---|
| 289 (diversity) | is the pool *spread* across regimes? | how many strata hold ≥ 1 world |
| **285 (this one)** | is the regime I am *deploying into* covered? | how many worlds *that one stratum* holds |

`CoverageLedger.covered` is the wrong view here — a pool covered in three strata
of which the target holds zero passes it. `len(ledger)` is wrong — naming a
stratum is not covering it. The figure is the row for the target regime:
`world_count`, read through the ledger's own one-stratum lookup, which
`coverage.py` already reserved for exactly this caller (*"the caller that holds
one stratum's name (a promotion gate asking after its deployment regime, feature
285)"*).

## One class, several faces — the `CoverageError` precedent, not the 289 one

`rejects_undercovered_promotion(ledger, *, regime, threshold)` **raises**
`PromotionCoverageError` and returns otherwise, so the caller that calls it on
its last line is stopped before the promotion is published — the shape 275's
`rejects_thin_pool` and 289's `rejects_regime_diverse_claim` take.

Where 289 split an *ask* face from a *verdict* face inside one class, this
feature's faces are gathered in one class with a longer list, following
`CoverageError`'s reasoning: *the caller's position is the same in every case* —
the promotion is not admitted, and the next step is to read which face the
message names. That matters more here than anywhere else in the member, because
the caller is a **gate**: a design that raised a second class for a malformed
threshold would let a caller's single `except PromotionCoverageError` miss it,
and the promotion would proceed through the hole. Silence is the one outcome a
block must not have.

Faces, refused in this order:

1. **the reading** — nothing handed in, a string, a carrier with no readable
   one-stratum lookup. A **store** handed in where the reading belongs is
   refused by its repair (*call `ledger()` on it first*), the sibling seams'
   argument: a verdict over a live store is a verdict about a pool that can move
   under it.
2. **the regime** — a target that is not non-empty text, through feature 283's
   own validator, translated at the seam.
3. **the threshold** — not a positive whole count of worlds. A `bool` is not a
   count; zero is refused because *coverage ≥ 0* admits every promotion, which is
   §C7's block legislated away through the configuration.
4. **the absence** — the target regime is **not named** by the ledger at all.
   Refused rather than read as zero: `0107` detail 1 keeps *named and empty*
   (`crash: 0`) apart from *never named* (no row), and reporting an uncounted
   regime as a zero would be the collapse the member forbids everywhere else.
   Same class, different message, because the repair differs — the first needs
   worlds, the second needs the stratum *named* (the census does both).
5. **the verdict** — the target regime's stored-world count is below the
   configured threshold. Refused with a message opening
   `coverage_below_threshold`, stating the figure, the regime, the threshold,
   §C7, and the repair.

## The boundary, and why the threshold has no default

Rejected *below* the threshold, so at exactly the threshold the promotion stands
and there is no upper edge — the asymmetry 275's floor and 289's floor both have.
That is the sentence's own comparison (`below`), and it is what a coverage
threshold means: meeting it is enough.

`threshold` is a **required keyword with no default**, the shape feature 261's
`switch_cost` takes. 289's floor could default to three because its sentence
*spelled* the number; this sentence spells none, and it names the figure as
*"the configured threshold"*. A default here would be this module legislating a
coverage floor no deployment configured — §C7's blindness re-legislated from the
configuration side — so the number has exactly one owner: the deployment.

## No component, no table, no seat edit, no router

Feature 283's single registered store stays the member's whole composed surface.
This feature persists nothing (a verdict is not evidence — the ledger's rows are),
counts nothing (the figure is the reading's), and touches no seat: the promotion
plugin's own features (291–300, including 299's *persisting a blocking reason*)
are another member's, and reach this refusal the way every cross-member seam in
this workspace is reached — by restating the code word.

`COVERAGE_BELOW_THRESHOLD_CODE = "coverage_below_threshold"` is that seam, in the
family `pool_too_thin` / `full_history_fit` / `no_origin` / `not_regime_diverse`
already establish.

## Files

| file | what |
|---|---|
| `packages/regime/src/regime/promotion.py` | the judgment, its validator, the code word |
| `packages/regime/src/regime/errors.py` | `PromotionCoverageError`, the reserved sibling seat |
| `packages/regime/src/regime/__init__.py` | re-exports, docstring |
| `packages/regime/tests/test_promotion.py` | feature 285's claims |
| `.plans/feature-285-promotion-coverage-block.md` | this document |
