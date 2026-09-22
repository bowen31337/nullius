# Feature 199 — reject a depth model whose *verified served* context limit is below the campaign history size

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 199 (shape=plugin,
plugin=providers, depends_on=198):

> System rejects a depth model whose verified served context limit is below the
> campaign history size, rather than trusting a published figure

Architecture §14.1 is the law it implements, and it is the *verification* layer
of feature 198's criterion:

> **A model with a 256K window physically cannot execute the defining prompt of
> this system in a mature wide campaign.** Such models are confined to
> early-depth nodes, narrow campaigns, and the §10.6 bootstrap worlds, where
> histories are short and self-contained. **Verify the served context limit
> (`--max-model-len`), not the marketing number.**

§14.1 also fixes the size facts the refusals quote: ~1k tokens per
`proposal.md` plus its `score.json`; ~500K tokens of history in a 500-node
campaign by the late rounds; ~300K on the **average** depth call, beyond 600K
on the late ones (§14.2's surcharge table rests on the same measurement).

## Where this sits relative to 198 (already landed)

`packages/providers/src/providers/_depth.py` gates a candidate against a **fixed
1M-token bar** read off the candidate's **declared** card (`DepthModel`'s
`context_tokens`). Its own docstring already reserves this feature's ground:

> Feature 199 — *rejects a depth model whose verified served context limit is
> below the campaign history size, rather than trusting a published figure* — is
> the verification layer: §14.1's *"verify the served context limit
> (`--max-model-len`), not the marketing number"*, **measured against a specific
> campaign's history rather than the 1M bar.**

So 199 is a second, *campaign-specific* question over a different fact: not the
number the rate card publishes, but **the number the deployment actually
serves**, compared against **this campaign's** history. 198's record is
deliberately *not* an input — a fact the criterion does not read is a fact that
would drift.

## Design decisions

### D1 — The two facts, and the one the gate must never read

* **`ServedContextLimit`** — the measurement: `model`, `served_tokens`,
  `verified`. Shape-validated on construction, **not** judged (the record/gate
  split feature 198 states for `DepthModel`: describing a model is not serving
  one, and a registry may describe limits nobody has probed yet).
* **`history_tokens`** — the campaign's history size, **taken as an argument
  the caller states**, never derived. Direct precedent: `choose_run_window`'s
  `duration` — *"the scheduler has no length of its own to know … the launcher
  that knows its own expected span is the caller that states it."* This module
  likewise invents no tokenizer and bakes no `~1k tokens/proposal` estimate: the
  module **carries no numeric bar at all**, because the bar here is the
  campaign's own and it changes per campaign.
* **`DepthModel.context_tokens` is deliberately not an input.** That is the
  published figure, and the sentence's whole content is that the criterion must
  not run on it.

### D2 — `verified` is a stated state, not a forgotten field

The sentence's *"rather than trusting a published figure"* is only enforceable
if the two states are representable, so `verified` is a **strict `bool` with no
default** — the discipline `BatchEndpoint.available` keeps (*"a state a caller
states, not one it forgets"*), restated for the same reason. `published_figure()`
names the refused state at the call site, mirroring `flat_pricing()`: a caller
who holds only the marketing number **says so**, and the gate refuses it by
name instead of silently accepting a figure nobody measured.

### D3 — Two refusals, both joining `DepthModelError` (**not** a new base)

The property is a conjunction — *a verified served limit at or above the
campaign's history* — so it fails in exactly two ways, each with its own repair:

| refusal | meaning | repair |
|---|---|---|
| `ServedContextUnverifiedError` | the number is a published figure, not a served measurement | re-probe the served model (`--max-model-len`) |
| `ServedContextBelowHistoryError` | verified, and under this campaign's history | shorten/narrow the campaign, or a larger served window |

**Both join feature 198's `DepthModelError`** rather than minting a seventh base.
Reason: 198 and 199 answer *the same question* — *may this model take the depth
role's calls?* — asked at the same moment (before any call is placed and any node
is authored), by the same actor, on the same axis (**the model's capacity**).
The package's other bases split along *different* axes: provenance record (203/204,
which share one base because "the columns are one row"), money (200), timing
(202), endpoint (201), call contract (192). A caller's
`except DepthModelError:` should mean *"my depth model was refused"* whichever
layer refused it, and forcing two `except` clauses here would be the collapse the
taxonomy exists to prevent.

This extends `_depth_errors.py`'s "exactly two" section to four, exactly as
feature 204 extended `_pin_errors.py`'s to nine.

### D4 — Ordering: **verification first, then comparison**

198's ordering is a decision (physics before economics). 199's is the analogue
and is just as load-bearing: **an unverified number cannot be compared at all.**
You cannot *conclude* "this model's served limit is below the history" from a
published figure — that is precisely the trap the sentence names. So:

1. **shape** — the served record's parts, then the history as a positive int;
2. **verified?** → `ServedContextUnverifiedError` (covers *unverified and
   too small*: the comparison never runs);
3. **holds the history?** (`served_tokens >= history_tokens`) →
   `ServedContextBelowHistoryError`.

The boundary is "at least" on both sides, pinned in the suite, as 198's is:
a served limit exactly equal to the history **admits** (the window holds the
whole history — the bar met is the bar met).

### D5 — The answer: `VerifiedServedContext`

`model`, `served_tokens`, `history_tokens`, frozen and value-equal, with
`headroom_tokens` **derived, never stored** — the `MeasuredCacheRate.hit_rate`
discipline. The margin is the operationally interesting figure (§14.1 reasons in
margins: 600K of a 1M window on the late calls), and it is non-negative by
construction because the record only exists past the gate. A bare "admitted"
bool would throw that figure away.

### D6 — No component, no seat, no shared-file edit

199 is a pure criterion: it persists nothing, owns no table, resolves no
`DATABASE_URL`, and places no call — the same stance feature 201 states for its
routing, so it is **imported directly** and registers nothing. Consequences:

* no `@register` builder, no table constant, no `_served.py`→seat accessor;
* `src/app/modules/providers/__init__.py` (the seat) is **untouched** — its
  `__all__` is pinned by `test_pin_component.py:305`;
* **no shared/order-sensitive file is edited**: no migration, no `settings.py`,
  no `middleware.py`, no app factory, no central registry. Registration-free by
  construction, which is what lets this land in parallel.

## Files

| file | change |
|---|---|
| `packages/providers/src/providers/_served.py` | **new** — `ServedContextLimit`, `VerifiedServedContext`, `require_served_context`, `published_figure`, `UNVERIFIED_SERVED_LIMIT`; local shape guards (restated, not imported — `_cache`/`_schedule` each restate `_validated_campaign_id`/`_require_instant` for "each module states its own contract"); duck-typed recognition by parts across the loader's double import, exactly as `require_depth_model` does |
| `packages/providers/src/providers/_depth_errors.py` | add the two subclasses under `DepthModelError`; rewrite the base + "why exactly two" sections to four, adding the shared-base reasoning (D3) and 199's ordering (D4) |
| `packages/providers/src/providers/__init__.py` | re-export the five public names + the two errors; `__all__` insertions in the file's existing case-sensitive sort; one docstring paragraph for feature 199 after 198's |
| `packages/providers/src/providers/_depth.py` | one-line cross-reference to `:mod:`providers._served`` in the paragraph that already reserves 199's ground (no behaviour change) |
| `packages/providers/tests/test_served.py` | **new** — the suite below |
| `.plans/feature-199-verified-served-context-limit.md` | this plan |

Untouched: the seat (`src/app/modules/providers/**`), every migration, every
other member, `packages/providers/tests/conftest.py`.

## Tests (`packages/providers/tests/test_served.py`)

Self-contained like `test_depth.py` (registry constants at module scope; no
conftest edit). Candidates are §14.2's registry, so a regression answers *"which
real model would we now refuse?"*:

1. **the sentence's core** — a *published* figure large enough to hold a 500K
   history is refused (`ServedContextUnverifiedError`): the number's
   **provenance**, not its magnitude, is the subject. This is the load-bearing
   test, and its message must name `--max-model-len` and "marketing number".
2. §14.2's depth row (deepseek-flash / gemini-3.1-flash-lite / claude-haiku-4-5,
   verified at 1M) admits a ~500K history, and the answer's `headroom_tokens` is
   the difference.
3. boundary both sides: `served == history` admits, `served == history - 1`
   refuses as `ServedContextBelowHistoryError`, message quoting both counts.
4. the self-hosted 262K tier (Ornith) verified at 262,144 refused for a 500K
   history — §14.1's *"physically cannot execute the defining prompt of this
   system"*, and the refusal confines it (early depth / narrow campaigns /
   bootstrap worlds).
5. ordering: unverified **and** too small → the *unverified* refusal (D4).
6. malformed descriptions → the **base**, exactly:
   non-record candidate (bare string / dict / list / `None`); blank name;
   `served_tokens` / `history_tokens` as `bool`, `str`, float, `0`, negative.
   Message names the offending part.
7. recognition by **parts, not class**: a `SimpleNamespace` with the three parts
   is admitted, `admitted is not offered`, and the answer is this module's class;
   re-gating its own answer is idempotent; a `__getattr__` hook cannot fabricate.
8. the answer record: frozen (`FrozenInstanceError`), value-equal, `headroom_tokens`
   derived and never negative, `recorded`-free surface pinned via
   `dataclasses.fields` (three fields, in order).
9. taxonomy: both new classes are direct `DepthModelError` subclasses; neither
   under `ProviderError` / `ModelPinError` / `ValueError`; and the **error
   surface is exactly the four** (`DepthModelError`'s subtree) — the
   `test_pin_errors.py` pattern, which fails if a class is exported and forgotten.
10. module bakes **no bar**: `providers` exposes no `MIN_HISTORY_TOKENS`-style
    constant, and the gate refuses/accepts purely on its `history_tokens`
    argument.
11. no component, no seat: the plugin still registers exactly its four names and
    none matching `served`; `providers` exposes no `SERVED_CONTEXT_TABLE` /
    `build_served_context*`; the seat's `__all__` is unchanged (6 names).
12. exports: every new public name is in `providers.__all__`.

## Verification

* `uv run pytest packages/providers -q` — the member suite (582 green at
  baseline) plus the new file.
* `uv run pytest tests -q` — the acceptance gate's own tree, since the root
  `pytest.ini` `testpaths = tests` means a bare run collects **only** `tests/`
  and a member suite is not graded; both must be run.
* `uv run python -c "import providers"` under
  `PYTHONPATH=src:packages/providers/src` — import-cheapness (stdlib only, no
  dial, no I/O).
* Lint only the touched files against a sibling's profile; the repo's `run.sh
  lint` is red on `main` (mypy absent, pre-existing ruff errors), so it is not a
  signal.

## Explicitly out of scope

* **198's 1M bar** — untouched; 199's bar is the campaign's own history.
* **The published figure as an upper bound.** Rejected deliberately: making
  `DepthModel.context_tokens` a ceiling would put the *published* number back
  inside the criterion, and a stale registry entry would then refuse a *correct*
  measurement — the opposite of what the sentence asks. `verified` is a stated
  fact, like `duration` in feature 202; there is no honest independent
  recomputation available here (feature 206 had one — a code hash — which is why
  it could close that loophole and this feature must state it instead).
* **Feature 200's cache-hit economics** and **206's history contents** — the
  history's *size* is this feature's operand, its *text* and completeness are
  206's.
