# Feature 228 — family-conditional thresholds keyed on theme_root

**app_spec.xml, "Exploration Policy Runtime", feature 228** (`plugin="policy-runtime"`, `depends_on=227`):
*System supports family-conditional thresholds keyed on theme_root, which returns a global default for a theme carrying no evidence yet, expressed as policy-authored thresholds rather than a fitted classifier.*

Authoritative spec: docs/nullius-tech-architecture.md §11.1 —

> The policy writes **family-conditional thresholds routed through the same `_schedule(beta)` dict**, shrunk toward a global default so a new theme starts at the prior and differentiates as evidence accumulates. No hierarchical Bayesian machinery required; the dreaming loop finds the conditioning if the worlds contain the contrast.

and docs/alpha-engine-prd.md §195, which names both the disease and the guardrail:

> **Consequence: partial pooling, not a global classifier.** A single classifier trained across families averages the inverted features into uselessness, or learns the majority family's sign and actively mis-ranks the minority. Model `P(null | features, theme_root)` with family-specific behaviour shrunk toward a global prior. […] `theme_root` is already in `meta()`, so expose it to the policy and let the policy-development agent write family-conditional thresholds routed through the same `_schedule(beta)` dict.

> **Read "model `P(null | …)`" as a functional form, not as a mandate to train one.** The default implementation is family-conditional thresholds written by the policy-development agent — code, revised by dreaming, deterministic under replay.

## Context — why this feature, and what it is not

The beta knob has three halves, one per feature, and each is a different failure:

| feature | owns | failure it prevents |
|---|---|---|
| 226 | the scalar — `EpisodeBeta`, read once, fixed | a scalar that moves mid-episode |
| 227 | the mapping — `schedule(beta) -> dict`, all four thresholds | a threshold derived outside the one mapping |
| **228** | **the family dimension — thresholds keyed on `theme_root`** | **a family threshold that stops being routed through the schedule** |

§11.1's reason: the §4.5 overfit signature is only partly family-invariant. Contribution concentration (Gini) and rolling-IC non-stationarity *invert* across families — a single global threshold averages the inverted features into uselessness. So the runtime must let a policy condition its thresholds per theme — while keeping §609's single-scalar discipline intact: family thresholds still derive from the one beta through the one schedule.

**What it is not (the split is the feature):**

* it is not a classifier — §11.2 defers that decision to the M1 triage, feature 231 refuses a policy that reaches for one at admission, and **this module is the positive half of that refusal**: the thing the policy writes *instead*. Plain floats authored by the policy-development agent — an adjustment per threshold, an evidence count per theme — composed by arithmetic. No model class, no checkpoint, no inference; the dreaming loop revises the *numbers*.
* it is not a change to `schedule` — 227's law is "a pure function of beta, and nothing else"; family conditioning arrives as a *second* derivation that calls the first, never as a widened signature (which would be the second beta arriving through a parameter).
* it is not the legal-theme ceiling — feature 241's `legal_themes.json` owns which slugs may exist; this module's refusal on a key is structural only (a non-empty string), because restating a config-bound ceiling in code is the second spelling both features exist to prevent.
* it is not the evidence *recorder* — who counts a theme's evidence (finished campaigns, revealed cells) is the dreaming loop's business; the conditional arrives authored, carrying its count.

## The house shape this follows (do not invent a new one)

| `schedule` (227) | `family_schedule` (228) |
|---|---|
| the global mapping, derived from beta | the theme-keyed lookup *over* that mapping |
| pure function of beta | pure function of (beta, authored conditionals) |
| all four keys, never partial | all four keys on every lookup, whatever the theme |
| fresh frozen mapping per call | fresh frozen mapping per lookup |
| no other derivation path | no key outside the one mapping — refused as a second beta |

Value type: `FamilyConditional` is the frozen-authored-input shape `GridPlan` takes; `FamilySchedule` is the composed lookup the way `PolicyQuestion` is the composed read side — built by one factory verb (`family_schedule`), never by a caller assembling internals.

## Design decisions

### 1. The authored conditional is an *adjustment* plus *evidence*, not a second dict of absolute thresholds

"Routed through the same `_schedule(beta)` dict" has exactly one honest reading: the family threshold must still be a function of beta. Absolute per-theme values would freeze while beta moved — the second beta, arriving as a table. So a conditional authors, per threshold key, an additive delta, and the composition anchors at the schedule's beta-derived value:

```
family(theme, key) = schedule(beta)[key] + w(theme) * delta(theme, key)
```

A partial conditional is legitimate — a theme may condition only the thresholds whose §4.5 meaning inverts for it (Gini-driven ones), leaving the robustness family at the global value. An *empty* conditional is refused: one that adjusts nothing conditions nothing.

### 2. Shrinkage: `w = evidence / (evidence + PRIOR_STRENGTH)`

The classic partial-pooling ratio — "family-specific behaviour shrunk toward a global prior… no hierarchical Bayesian machinery required" is *literally* this formula: empirical-Bayes shrinkage without the Bayes.

* evidence `0` → weight `0` → the theme's thresholds **are** `schedule(beta)`, to the bit (the arithmetic adds `0.0`). "A new theme starts at the prior" holds even for a theme the policy has already authored a conditional for — authored intent, no evidence, prior answer.
* evidence grows → weight rises monotonically → the theme *differentiates*, its thresholds interpolating between the prior and the authored position — never past it, never at full strength for any finite evidence the arithmetic can distinguish.
* `PRIOR_STRENGTH = 6.0` is the knob: the evidence at which a conditional is trusted at half strength. A default parameterization stated as a named constant, the dreaming loop's tuning to replace — exactly the way 227 states `_PATIENCE_FLOOR` rather than hiding it, and for the same reason: no document states a number, so none is invented beyond a stated default.

The evidence unit is deliberately abstract (units the dreaming loop records under a theme — campaigns, cells); the runtime takes the magnitude and refuses a negative or non-finite one.

### 3. The unknown theme is not an error — it is the headline

`thresholds(theme_root)` answers the global default for any key not carrying evidence, so a campaign opening a theme the pool has never seen explores under the prior — §11.1's "a new theme starts at the prior" as a lookup fact, not a configuration step. Every answer, known theme or not, carries all four keys: the family path cannot narrow the schedule.

### 4. Routed through the same schedule, or refused

The composition *calls* `schedule(beta)` — the one mapping — and derives from what it returns. An adjustment naming a key outside `SCHEDULE_KEYS` is refused with the member's own vocabulary: a threshold derived anywhere but through the one mapping is a second beta (§609), arriving here through a family key instead of a second formula. Consequently family thresholds still move with beta — anchored at the schedule, they cannot drift independently of the scalar.

### 5. The seam is duck-typed, and validates what it reads

`family_schedule` accepts any object carrying `theme_root`/`evidence`/`adjustments` — `isinstance` is the wrong test under the module loader's double-import (the tree/question seam's own documented reason) — and validates *what it reads*: a text evidence, a NaN adjustment or an unkeyable theme reaching composition through a foreign carrier is refused here, in this module's error vocabulary, rather than escaping as a `ValueError` or silently poisoning every threshold with NaN. The constructor and the seam share one spelling of each guard (private validators), so "validated twice" is one rule read twice, not two rules.

### 6. Value-type stance

`FamilyConditional` is frozen and validated at construction; its adjustments are copied into a read-only mapping, never aliased to the authoring dict. Every `thresholds()` call returns a fresh frozen mapping — read-only, never aliased. Determinism: same beta plus same authored numbers answers identically every time, so a replay under one authored policy is legible across cycles — §609's cross-cycle discipline, extended to the family dimension. New error class `FamilyThresholdError` (`PolicyRuntimeError` subclass, the fifth contract): the family-routing law — a conditional that cannot be keyed, an adjustment outside the one mapping, a magnitude that is not one, two conditionals for one theme.

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/families.py` | **new** — `FamilyConditional`, `FamilySchedule`, `family_schedule`, `PRIOR_STRENGTH`, shared validators |
| `packages/policy-runtime/src/policy_runtime/errors.py` | `FamilyThresholdError` (fifth contract) + docstring paragraph |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | exports + docstring paragraph; repairs the orphaned "third-party import at module scope" fragment 227's commit left in the docstring |
| `packages/policy-runtime/tests/test_families.py` | **new** — 39 tests |

No new `@register` component (the conditioning belongs to the episode the replay opens, exactly as 226/227 take none); no central registry, router, app factory, middleware, settings or migration edited; no seat edit under `src/app/modules/policy-runtime/` (227 set the precedent: a component-less pure derivation is reached from the member directly). The member imports no sibling member — `collections.abc`, `math`, `numbers`, `types` and `.schedule`/`.errors` only.

## Verification

* member suite `packages/policy-runtime/tests`: **174 → 213 passed** (no existing test edited;
  the new `test_families.py` contributes **39**). Green under both the system
  python (conftest bootstrap) and `uv run pytest`.
* `ruff check --no-cache` on the new files (`families.py`, `test_families.py`)
  and `errors.py`: clean. `__init__.py` carries **5 pre-existing findings on
  `HEAD`** (I001, RUF022, 3× UP037 — ruff's cache can under-report; compare
  with `--no-cache`); the edited file reports **the same 5, same rules** —
  the insertions added zero.
* repo-level acceptance gate `uv run pytest` (`testpaths=tests`):
  **1060 passed** — it does not collect a member's own suite
  [[acceptance-gate-ignores-member-suites]], so both were run; the fresh
  worktree needed `uv sync --all-packages` with `UV_CACHE_DIR` pointed inside
  the worktree first [[repo-test-env-gaps]], [[uv-cache-dir-sandbox-workaround]].
