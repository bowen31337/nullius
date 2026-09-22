# Feature 227 — every threshold is routed through one schedule mapping derived from beta

**app_spec.xml, "Exploration Policy Runtime", feature 227** (`plugin="policy-runtime"`, `depends_on=226`):
*System routes every threshold through one schedule mapping derived from beta, which returns all thresholds as a single mapping.*

Authoritative spec: docs/nullius-tech-architecture.md §609 —

> `beta` is read once in `__init__`, fixed for the episode, routed through a single
> `_schedule(beta) -> dict` so every threshold moves together. Swept on a grid
> offline. This is carried over from the paper unchanged because it is what makes
> cross-cycle comparison legible.

and docs/alpha-engine-prd.md §7.4, which names the thresholds beta governs:

> Keep the paper's single-scalar discipline verbatim: one `beta` controlling
> explore/exploit, patience, and pruning aggressiveness; **fixed within an
> episode** ... Add one role: `beta` also gates **overfit aversion**. High beta
> tolerates longer branches before demanding OOS confirmation; low beta prunes on
> the first sign of the §4.5 signature.

## Context — why this feature, and what it is not

Feature 226 is the *value* half of the beta knob: `EpisodeBeta` is the scalar, read once and fixed. Feature 227 is the *derivation* half: what downstream derives from that scalar is *every threshold in the episode*, and this feature is the one place that derivation happens. §609's law has two clauses — *the scalar is one number and it does not move* (226) and *every threshold is derived from it, together* (227) — and they are two different failures: a scalar that moved, and a schedule that forgot a threshold.

Feature 227 is the threshold schedule:

* :func:`policy_runtime.schedule` — `beta -> dict`, the one derivation point that returns *all* the thresholds as a single frozen mapping keyed by :data:`SCHEDULE_KEYS`.

**What it is not (the split is the feature):**

* it is not the scalar — **feature 226** owns `EpisodeBeta` / `read_beta`, and the scalar reaches the schedule already validated, so the schedule is pure arithmetic over it and does not re-check finiteness;
* it is not the grid sweep — §609 says the sweep is *offline*, an evaluation over finished episodes, not a runtime act; the schedule is the *parameterization* the sweep replaces, stated as named constants;
* it is not the per-cycle default — "chosen per cycle from live evidence" is a dreaming-loop decision;
* it is not family conditioning — feature 228's `theme_root`-keyed thresholds, which are *routed through the same `_schedule(beta)` dict* (docs §11.1) and build on this feature's guarantee that the mapping exists.

226 says *the scalar is one number and it does not move*. 227 says *every threshold is derived from it, together*. Two features because they are two different failures.

**No component.** The schedule belongs to the *episode* the replay opens, not to the composed application, so feature 227 adds no `@register` component and no store. The existing `policy-runtime` component (feature 217's campaign tree) is untouched.

## The house shape this follows (do not invent a new one)

Feature 226's `EpisodeBeta` already states the value half one module over: a value type that cannot be moved, the shape feature 10's `contract.MarketWindow` takes. Feature 227 is that shape restated for the *thresholds the scalar derives* rather than the scalar itself:

| `policy_runtime.EpisodeBeta` (feature 226) | `policy_runtime.schedule` (feature 227) |
|---|---|
| the scalar, fixed | the thresholds, derived |
| refuses every reassignment path | there is no other derivation path |
| `MappingProxyType`-style: no `__dict__`, no shadow | `MappingProxyType` over a fresh dict: read-only, never aliased |
| one number the episode is compared under | one mapping every threshold is read from |

The two share one derivation point, and that is the feature: there is no `explore_threshold(beta)` and no `patience(beta)` — a caller that needs a threshold reads it from the mapping `schedule` returns, so a threshold reached anywhere else would be a *second beta*, the drift the single-scalar discipline exists to prevent, arriving through a second formula instead of through a reassignment.

## Design decisions

### 1. One mapping, and it is the only way to a threshold

`schedule` returns the whole set of thresholds as a single `types.MappingProxyType`. There is no free function that derives one threshold on its own. The mapping carries *all* the thresholds on every call — never a subset — so a schedule that forgot a threshold is refused by the tests, not silently partial. The four thresholds the paper names are always present, always the same four keys (`SCHEDULE_KEYS`), whatever the scalar is. "Every threshold moves together" is a fact about the code rather than a promise in a docstring.

### 2. A pure function of beta, and nothing else

`schedule` consults no store, no clock, no configuration and no episode state — it is `beta -> dict` and nothing more, so the same scalar returns the identical mapping however it is asked, and two cycles opened at one scalar are comparable because they explored under the identical thresholds. That is the legibility §609 says the discipline exists to protect. The tests pin determinism (50 readings of one scalar are identical), the identity of two cycles, and that the mapping is a fresh object per call (never aliased).

### 3. The thresholds move together, but not identically

Each threshold is a deterministic, monotonic function of the scalar, so the mapping moves together with beta — but not identically, each at its own steepness:

| threshold | direction | band |
|---|---|---|
| `explore_exploit` | rises with beta | `(0, 1)` |
| `patience` | rises with beta | `(1, 10)` |
| `prune_aggressiveness` | falls with beta (sharp) | `(0, 1)` |
| `overfit_aversion` | falls with beta (gentle) | `(0, 1)` |

Pruning and overfit aversion both fall, but at different scales (`_PRUNE_SCALE = 0.5`, `_OVERFIT_SCALE = 1.5`), so a sweep over beta discriminates them rather than collapsing them into one. The test `test_the_falling_thresholds_are_two_curves_not_one` pins that the two falling thresholds are two curves, not one.

### 4. A finite scalar always derives finite thresholds

Feature 226 imposes no band on beta, so a beta of `1e9` is a legitimate grid point. The naive `1 / (1 + exp(-z))` would raise `OverflowError` on it, so `_sigmoid` is the numerically stable form: split on the sign of `z`, the decaying exponential underflows to zero rather than the growing one overflowing. Either way a finite scalar saturates to 0 or 1 instead of raising. The tests pin saturation both ways and that every threshold is finite for `1e9`, `1e308` and their negatives. (Found by probing the edge case after the first pass — 226's un-banded domain means the schedule's arithmetic must be honest for the whole of it.)

### 5. The returned mapping is frozen

A threshold is a recorded fact — what a policy explored under, and what its score was earned under — and a policy comparing two cycles must not be able to move either. So the mapping is a `MappingProxyType` over a freshly built dict: read-only, so a caller that holds it cannot reassign or delete a threshold, and a fresh dict per call so two calls never alias. The tests pin that an assignment and a deletion both raise `TypeError`.

### 6. The scalar reaches here already validated

`schedule` does not re-check that beta is a finite real number — `read_beta` refused anything else at the top of the episode (feature 226), so the schedule is pure arithmetic over the float. Re-validating here would be a second spelling of 226's guard, and a second spelling of a pure gate is a second thing to keep in sync. The split is deliberate and kept: the scalar is validated there, derived from here. The module imports nothing from `.beta` — the scalar is read as the float it is, so the schedule does not depend on the value type it derives from.

## The four thresholds — why these, and why these bands

The four keys are the ones docs §7.4 names: explore/exploit, patience, pruning aggressiveness, overfit aversion. They are kept as named constants (`EXPLORE_EXPLOIT`, `PATIENCE`, `PRUNE_AGGRESSIVENESS`, `OVERFIT_AVERSION`) so a caller reads a threshold by its name rather than a string literal, and so "all thresholds" has exactly one spelling (`SCHEDULE_KEYS`).

The bands are the *default parameterization the sweep replaces* — §609 says the sweep is offline and the deployment's business — so they are stated as named constants (`_PATIENCE_FLOOR`, `_PATIENCE_SPAN`, `_PRUNE_SCALE`, `_OVERFIT_SCALE`) rather than hidden in the formula, exactly as feature 226 states that it imposes *no* band. This is the same "a ceiling the code holds is stated, not hidden" stance feature 241's `legal_themes.json` and feature 167's allowlist take, minus the committed document: §609's sweep is the deployment's, so hardcoding these into a JSON file would be inventing a ceiling no document states.

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/schedule.py` | **new** — `schedule`, `_sigmoid`, the four threshold constants, `SCHEDULE_KEYS` |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | exports (`schedule`, `SCHEDULE_KEYS`, the four constants) + docstring |
| `packages/policy-runtime/tests/test_schedule.py` | **new** — 25 tests |

No new `@register` component; no central registry, router, app factory,
middleware, settings, or migration edited; the member imports no sibling member
(`math`, `types` and the typing helpers only — not even `.beta`, since the
scalar reaches the schedule already validated as the float it is).

## Verification

* member suite `packages/policy-runtime/tests`: **149 → 174 passed** (feature 230's
  and 231's suites unedited and green). The new `test_schedule.py` contributes **25**.
* `uv run ruff check` on the two new files (`schedule.py`, `test_schedule.py`): clean.
* The four findings in the touched `__init__.py` are pre-existing on `main` —
  measured by `git show HEAD:...__init__.py` and re-running the identical command,
  which reports the same four. The insertions made here are alphabetically correct,
  so the count is unchanged.
* **NB:** the repository-level acceptance gate (`uv run pytest`, `testpaths=tests`)
  does **not** collect a member's own suite
  [[acceptance-gate-ignores-member-suites]] — **both must be run**. It also needs
  `uv sync --all-packages` first in a fresh worktree, or `tests/` fails to
  collect on a missing `polars`/`pyarrow` [[repo-test-env-gaps]].
