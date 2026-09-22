# Feature 226 — beta is read once and fixed for the episode

**app_spec.xml, "Exploration Policy Runtime", feature 226** (`plugin="policy-runtime"`, `depends_on=217`):
*System rejects a reassignment of the beta scalar after initialization, holding it fixed for the whole episode.*

Authoritative spec: docs/nullius-tech-architecture.md §609 —

> `beta` is read once in `__init__`, fixed for the episode, routed through a single
> `_schedule(beta) -> dict` so every threshold moves together. Swept on a grid
> offline. This is carried over from the paper unchanged because it is what makes
> cross-cycle comparison legible.

and docs/alpha-engine-prd.md §7.4, which states the paper's own discipline:

> Keep the paper's single-scalar discipline verbatim: one `beta` controlling
> explore/exploit, patience, and pruning aggressiveness; **fixed within an
> episode**; swept on a grid during offline evaluation; default chosen per cycle
> from live evidence and prior sweeps. It is good design and it is what makes
> cross-cycle comparison legible.

## Context — why this feature, and what it is not

A policy is handed the identical `question.*` interface during replay (docs §11).
The *search behaviour* that interface drives is governed by one scalar: `beta`
controls explore/exploit, patience and pruning aggressiveness. §609's law is that
`beta` is read **once**, at initialization, and then **does not move for the whole
episode** — because every threshold the policy explores under is derived from it
(feature 227's `_schedule(beta) -> dict`, "so every threshold moves together").

Feature 226 is the *value* half of that knob:

* :class:`EpisodeBeta` — the scalar, fixed. A `float` subclass that refuses every
  path by which a caller could move it.
* :func:`read_beta` — the one sanctioned moment it is read, at initialization.

**What it is not (the split is the feature):**

* it is not the threshold schedule — **feature 227** owns `_schedule(beta)`,
  the mapping every threshold is routed through;
* it is not the grid sweep — §609 says the sweep is *offline*, an evaluation over
  finished episodes, not a runtime act;
* it is not the per-cycle default — "chosen per cycle from live evidence and prior
  sweeps" is a dreaming-loop decision (feature 228's neighbourhood);
* it is not family conditioning — feature 228's `theme_root`-keyed thresholds.

226 says *the scalar is one number and it does not move*. 227 says *every
threshold is derived from it, together*. Two features because they are two
different failures: a schedule that forgets a threshold, and a scalar that moved.

**No component.** The scalar belongs to the *episode* the replay opens, not to the
composed application, so feature 226 adds no `@register` component and no store.
The existing `policy-runtime` component (feature 217's campaign tree) is untouched.

## The house shape this follows (do not invent a new one)

Feature 10's `contract.MarketWindow` already states this exact law one component
over: a decision time fixed at construction, every reassignment path refused, a
second call to the initializer refused, slots so the object cannot grow shadow
attributes. Feature 226 is that shape restated for a scalar rather than a window,
and the correspondences are deliberate:

| `contract.MarketWindow` (feature 10) | `policy_runtime.EpisodeBeta` (feature 226) |
|---|---|
| `t` fixed at construction | `beta` bound in `__new__` |
| `__setattr__`/`__delattr__` raise | same, raising `BetaFixedError` |
| `__init__` refused a second time | a second `__init__` reaches no bind |
| `__slots__` so no shadow state | `__slots__ = ()` so no `__dict__` at all |

## Design decisions

### 1. A scalar, not a wrapper

`EpisodeBeta` **is** a `float`, rather than an object holding one behind a `.value`
a consumer unwraps. The beta of an episode is read by the schedule (227), by the
replay's arithmetic, and by the `replay_score` row recording which scalar a score
was earned under (feature 106: `beta REAL NOT NULL`; feature 349's log record
carries `beta` too). A wrapper would put a conversion at every one of those seams
— the drift the law exists to prevent, arriving through the wrapper instead of
through a reassignment. So it compares, hashes, rounds, formats, `json`-encodes
and binds as the float it is, and is simply not movable.

### 2. The refusal is on every path, including the ones a value type leaves open

| attempt | result |
|---|---|
| `beta.value = 0.9` | `BetaFixedError` |
| `beta._value = 0.9` | `BetaFixedError` |
| `beta.anything = 0.9` | `BetaFixedError` (no slots — nothing to attach) |
| `del beta.value` | `BetaFixedError` |
| `object.__setattr__(beta, "value", 0.9)` | `AttributeError` — no slot to rebind; the value lives in the float's own storage, which is not an attribute |
| `beta.__init__(0.9)` | no effect — the value was bound in `__new__`, which the second call never reaches |

`__slots__ = ()` is load-bearing, exactly as it is for `MarketWindow`: with a
`__dict__` the guard would still refuse `value` but a caller could attach shadow
state beside the scalar. With no slots and no `__dict__`, there is nothing to
rebind and nothing to attach, so the read-only guarantee is a fact about the type
rather than a promise in a docstring.

### 3. No band — refuse only what is not a magnitude

`read_beta` accepts any `numbers.Real` (`beta = 1` is a legitimate grid point, the
exploit-only end of the sweep) and refuses a `bool`, text, `None`, a `Decimal`, a
`complex`, other objects, and non-finite numbers. It does **not** refuse `0.0`, a
negative value, or any finite magnitude.

Three reasons. First, §7.4 says which values are tried is "swept on a grid during
offline evaluation" and defaults "chosen per cycle" — the *deployment's* and the
*dreaming loop's* business, not this law's; refusing a value no document forbids
would be inventing a contract (the direction feature 241's `legal_themes.json`
settles in the other direction: a ceiling a deployment owns is a committed
document; a law that isn't one is not). Second, `bool` is an `int` subclass, so
`beta = True` would otherwise silently read as `1.0` — the same affinity trap the
workspace's SQLite layer guards. Third, text is refused rather than coerced,
because coercion is how a mistyped configuration becomes a silent episode; a
`Decimal` is refused for the same reason in a different costume (it is a *decimal*
number while the scalar's arithmetic is binary floating point, so accepting one
means the episode ran at a precision the config did not name).

Non-finite numbers *are* refused: a NaN beta compares false against everything, so
no threshold derived from it is a threshold; an infinite beta is a magnitude no
grid yields and no threshold survives.

**The conversion's own exception is translated, not propagated.** `float(10**400)`
raises `OverflowError`; letting it escape would hand a caller catching
`PolicyRuntimeError` an exception it does not catch — precisely the
error-vocabulary leak at a member seam that
[[error-vocabulary-at-member-seams]] records. `__new__` catches it and re-raises
`BetaFixedError` with `from`, so *every* refusal from this law is the member's own
type. (Found by probing edge cases after the first pass, not by reasoning about
the happy path.)

### 4. Both sides of the law are pinned

The feature reads as two enforcement points and the tests pin both:

* the **read** — `read_beta` refuses a value that is not a finite real number, so
  an episode is only ever opened on a magnitude;
* the **guard** — `EpisodeBeta` refuses every path by which the scalar could move
  afterwards, so the magnitude the episode was opened on is the magnitude it is
  scored under.

### 5. Error vocabulary — its own class, the same base

`BetaFixedError ⊂ PolicyRuntimeError`, as a sibling of `PolicyAdmissionRefusal`
rather than a child of it. They are two different contracts in two different
places: the admission gate judges a policy's authored *source* **before** an
episode begins and is repaired by resubmitting; this one guards a value
**during** an episode and is not repaired at all — a different beta is a different
episode. A caller that catches a policy refusal and retries the authoring agent is
not the caller that should catch a moved scalar. Both still answer
`PolicyRuntimeError`, so the member's single-except discipline holds. (This is the
same "translate at the seam, don't reuse another contract's error type" rule
[[error-vocabulary-at-member-seams]] records.)

## Files

| file | change |
|---|---|
| `packages/policy-runtime/src/policy_runtime/beta.py` | **new** — `EpisodeBeta`, `read_beta` |
| `packages/policy-runtime/src/policy_runtime/errors.py` | `BetaFixedError` + docstring |
| `packages/policy-runtime/src/policy_runtime/__init__.py` | exports + docstring |
| `src/app/modules/policy-runtime/__init__.py` | docstring only (the seat is not the path) |
| `packages/policy-runtime/tests/test_beta.py` | **new** — 27 tests |

No new `@register` component; no central registry, router, app factory,
middleware, settings, or migration edited; the member imports no sibling member
(`math`, `typing` and the member's own error only).

## Verification

* member suite `packages/policy-runtime/tests`: **122 → 149 passed** (feature 230's
  and 231's suites unedited and green; 231's suite is 22 of the 122). The new
  `test_beta.py` contributes **27**.
* `uv run ruff check` on the two new files (`beta.py`, `test_beta.py`): clean.
* The five findings remaining in the touched files are pre-existing on `main` —
  measured by stashing the change and re-running the identical command, which
  reports the same five: `RUF022` (`__all__` not sorted, about the
  `PolicyAddressError`/`PolicyAdmissionDecision` pair, untouched here) and
  `UP037` ×3 and `N999` (the hyphenated `policy-runtime` seat directory) in
  `__init__.py`, plus `N999` in the seat. The insertions made here are
  alphabetically correct, so the count is unchanged.
* **NB:** the repository-level acceptance gate (`uv run pytest`, `testpaths=tests`)
  does **not** collect a member's own suite
  [[acceptance-gate-ignores-member-suites]] — **both must be run**. It also needs
  `uv sync --all-packages` first in a fresh worktree, or `tests/` fails to
  collect on a missing `polars`/`pyarrow` [[repo-test-env-gaps]].
  Result: **1060 passed** (318 s).
