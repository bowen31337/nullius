# Feature 231 — Policy admission refuses a learned component

**app_spec.xml, "Exploration Policy Runtime", feature 231** (`plugin="policy-runtime"`, `depends_on=230`):
*System rejects a policy admission that loads a model checkpoint or calls inference, because a learned component stays deferred until the triage measurement decides it.*

Authoritative spec: docs §11.2 — "Learned components in the policy — deferred,
with conditions": *"The §4.5 overfit signature is a classifier in everything but
name, and it is tempting to build it as one. Nothing in this architecture does.
The policy writes thresholds; dreaming revises them. **That stays true until the
M1 triage measures the perturbation-stability AUC**"* — a decision §11.2 records
*"so it is not quietly reopened by whoever next reads §4.5"*. §634 lists the
static checks before any policy is admitted; §12's determinism table carries the
closing row (*"**No inference in the replay path** | Replay calls no model of any
kind"*); §15 files the failure: *"Learned component reached the replay path
un-materialized | Canary drift; replay score varies with batch shape or thread
count"*.

## Context — why this feature, and what it is not

Feature 230 (this member's `admission.py`) landed the admission gate: three
static checks over a policy's authored source — no absolute score constants, no
hardcoded node ids, `commit()` reachable on every terminating path. Feature 231
is the **fourth check on that same gate**, not a second gate. The spec's own
phrasing is the tell: 230 says "rejects a policy admission when static checks
detect…"; 231 says "rejects a policy admission that loads…". Both are refusals
of an *admission*, and §634 lists them in one sentence ("Static checks before any
policy is admitted").

The refusal is of the **call in the source**, not of a model class, and the split
from feature 146 is deliberate. Canary's `_inference.py` refuses a model
inference call made *from the replay path* — a runtime call-site fact, held as a
`ContextVar` mark. Its own docstring names feature 231 by number as "a later
member's" question: *"Which models may exist at all is the admission checks'
question (a later member's, app_spec.xml feature 231) — and a refusal that tried
to answer it here would be the canary deciding policy admission."* This feature
is that question, and it is answered **statically, at admission**, from the
source alone: nothing about *where* a call is made, nothing about which model
classes are legal — just that a policy's authored source reaches for one at all.

**Why this is a check and not a config document.** The house keeps a
deployment's *ceiling* in a committed JSON artifact — feature 167's
`imports_allowlist.json`, feature 157's `isolation_policy.json`, feature 241's
`legal_themes.json`. This one is deliberately **not** a document. §11.2's
deferral is the system's own decision, lifted by the M1 triage measurement and
nothing else; a JSON file would make reopening the question a configuration
edit, which is precisely the *"quietly reopened"* the section forbids. Widening
it belongs in a commit to `learned.py`, in review, with the AUC in hand.

**What it is not:** it does not admit, materialize, or record anything —
§11.2's four admission rows (CPU-deterministic, materialized at evaluation time,
Z0-derived and hashed, holdout-disjoint) are the M1 triage's, and a registry
here would be a second place the deferral could drift. It does not run a policy
or read a store. It adds no component.

## The house shape this follows (do not invent a new one)

- **The existing gate, extended.** `screen_policy` returns the same
  `PolicyAdmissionDecision`; `require()` raises the same `PolicyAdmissionRefusal`
  (already a `PolicyRuntimeError`); the reason is a new
  `AdmissionReason.LEARNED_COMPONENT`. One verdict, one exception to catch, one
  log line. `errors.py` needs **no code change** — docstring only.
- **Reason enum split by *repair*** (229/230's discipline). 230's three tell an
  author how to fix a policy's *shape*; this one tells them the *premise* does
  not yet hold — the repair is to wait, and to write against `question.*`.
- **The check runs LAST**, after commit reachability. A policy whose `commit()`
  is unreachable is broken whatever else it carries; a policy that commits
  correctly on every path is wrong only about what may exist yet. The retrying
  agent repairs the shape before the premises.
- **Detector separate from the gate.** `learned.find_learned_component(tree)` is
  a pure function over an AST answering *what was found*, never *what it means*;
  `screen_policy` judges. The same split `.planning` keeps from the component.
- **Conservative, no false negatives over false positives** — 230's stated
  stance, applied to a deferral rather than a barrier. A policy that hands a
  modeled path to a call it never reaches is refused and named.
- **No new `@register`; `@register` only in the package `__init__`.** The gate is
  a pure function over source — no store, no deployment state, no I/O.
- **Stdlib only, import-cheap:** `ast`. No member imports another member.
- **Tests live in the member's own suite** (`packages/policy-runtime/tests/`),
  NOT the repository-level `tests/` — the acceptance gate ignores member suites.

## The three shapes, each detected on its own terms

1. **A model-framework import** — the enabling condition. Root module name of
   every `ast.Import`/`ast.ImportFrom`, matched against a named set (`torch`,
   `tensorflow`, `sklearn`, `transformers`, `onnxruntime`, `xgboost`,
   `lightgbm`, `jax`, …). `pickle` is in the set as the checkpoint
   *serialization*, not as a framework. `math` is deliberately not — the set is
   named frameworks, not "any import at all": feature 167 owns the deployment's
   ceiling, this owns the deferral. Both refusals are correct without being
   duplicates.
2. **A checkpoint load** — matched **two ways**, because either half of the
   phrase can be the whole of the evidence:
   - *by verb alone*: `from_pretrained`, `load_state_dict`, `load_checkpoint`,
     `read_checkpoint`, `load_weights`, `unpickle`, `InferenceSession`, … — no
     legitimate policy calls one, matched as attribute **and** bare name;
   - *by path alone*: a string literal whose leaf ends in a model-artifact
     suffix (`.pt .pth .ckpt .safetensors .onnx .pkl .pickle .joblib .h5
     .tflite .gguf .mlmodel .mar .npy .npz .pb …`) handed to **any** call —
     positional and keyword arguments both read.
   - **`.bin` is deliberately NOT a suffix**: this system's own ingest writes
     `.bin` snapshots. A `.bin` *load* is still caught by its load verb.
3. **An inference call** — matched on the **attribute name only**:
   `model.predict(x)`, `net.forward(t)`, `llm.generate(prompt)`. A bare
   `predict(x)` is deliberately **not** flagged — a policy's own helper can be
   named anything, and refusing a policy for a function name is the false
   positive that has nothing to do with the deferral. `score`, `fit`, `train`
   are absent from the verb set: ordinary English in this system's own
   vocabulary (§14's reporting, the scoring path).

The whole tree is walked, nested scopes included — and that is a **contrast with
230's commit matcher**, not an oversight. A nested `def load_weights(...)` never
*runs* when the enclosing statement does, so 230 does not count it as a commit;
but a `model.predict(...)` inside a nested helper runs exactly when the helper is
called, so the deferral is broken by it just the same.

## Implementation

### 1. `packages/policy-runtime/src/policy_runtime/learned.py` (new module)

Stdlib only (`ast`). Exports `find_learned_component(tree) -> list[str]` —
offenders as `"line N: <what>"`, sorted by line so they read down the policy the
way its author will. Module-level frozensets `_FRAMEWORKS`, `_LOAD_CALLS`,
`_INFERENCE_CALLS`, tuple `_CHECKPOINT_SUFFIXES`; helpers `_import_roots`,
`_callee_name`, `_is_checkpoint_path`, `_call_arguments`.

### 2. `packages/policy-runtime/src/policy_runtime/admission.py` (extend)

- `AdmissionReason.LEARNED_COMPONENT = "learned-component"`.
- Step 5 in `screen_policy` after commit reachability, calling
  `find_learned_component(tree)`.
- `_refusal` cites `feature 231` for this reason, `feature 230` otherwise.
- Docstrings updated: the module header, the enum ("six" → "seven"), the order
  paragraph, `screen_policy`'s numbered list, `require`.

### 3. `packages/policy-runtime/src/policy_runtime/__init__.py` (extend)

Import and re-export `find_learned_component`; add to `__all__`. **No new
`@register`.** The existing `build_campaign_tree` component is untouched.

### 4. `packages/policy-runtime/src/policy_runtime/errors.py` (docstring only)

Name the fourth check in the module docstring. No code change —
`PolicyAdmissionRefusal` already covers it, because it is the same refusal.

### 5. `src/app/modules/policy-runtime/__init__.py` (docstring only)

Note that 231's check is the fourth on 230's gate, so it needs no seat of its
own.

### 6. `packages/policy-runtime/tests/test_learned.py` (new suite, 22 tests)

A `_policy(*lines)` helper builds a source whose body is the given lines and
whose terminal commits — so each test varies exactly one thing (the learned
component) and observes feature 231's reason rather than 230's reachability.
Pinned: each of the three shapes; every offender named; the framework import in
both spellings; `pickle`; an ordinary stdlib import *not* flagged; the bare
helper *not* flagged; `.bin` *not* flagged but `.bin` + load verb refused;
`UNREACHABLE_COMMIT` named before `LEARNED_COMPONENT` when both are present;
`require()` raising `PolicyAdmissionRefusal`/`PolicyRuntimeError`; the reason
token leading the detail and the detail naming the *deferral*; the detector read
directly (source-ordered, empty for a clean AST).

### 7. `additions_spec_231.xml` (new spec)

Mirrors `additions_spec_230.xml` (brownfield, `layout profile="uv-workspace"`).
Features 231, 231a–231d. Validates to the same by-construction Layer-6 profile
as its siblings (see Verification).

## Files changed (all within declared footprint)

- `packages/policy-runtime/src/policy_runtime/learned.py` — **new** (the detector).
- `packages/policy-runtime/src/policy_runtime/admission.py` — reason + step 5 + docstrings.
- `packages/policy-runtime/src/policy_runtime/__init__.py` — export the detector.
- `packages/policy-runtime/src/policy_runtime/errors.py` — docstring only.
- `src/app/modules/policy-runtime/__init__.py` — docstring only.
- `packages/policy-runtime/tests/test_learned.py` — **new** suite.
- `additions_spec_231.xml`, `.plans/feature-231-*.md` — **new** workflow artifacts.

**No shared file is edited.** No registry, router, app factory, middleware,
settings, or migration. No new `@register`. No member import.

## Verification

```bash
export UV_CACHE_DIR="$(pwd)/.claw-forge/tmp/uv-cache"

# the member suite — 100 before this feature, 122 after (test_learned.py: 22)
uv run pytest packages/policy-runtime/tests/ -q

# 230's own 100 tests must pass UNEDITED — this feature must not require
# touching a sibling feature's suite
uv run pytest packages/policy-runtime/tests/test_admission.py -q

# lint only the changed files (repo lint is red on main — do not run run.sh lint)
uv run ruff check packages/policy-runtime/src/policy_runtime/learned.py \
                     packages/policy-runtime/src/policy_runtime/admission.py \
                     packages/policy-runtime/src/policy_runtime/errors.py \
                     packages/policy-runtime/tests/test_learned.py

# the additions spec — compare its profile to sibling 230's
claw-forge validate-spec --json additions_spec_231.xml
```

Measured results:

- `packages/policy-runtime/tests/` — **122 passed** (100 pre-existing + 22 new).
- `test_admission.py` — **100 passed, unedited**.
- `ruff` on the new/changed source and test files — **all checks passed**. The
  five findings in the *touched* files (RUF022 `__all__` not sorted, three
  UP037, N999 for the `policy-runtime` seat directory) are **pre-existing on
  HEAD** — verified against `git show HEAD:…` — and match the repo's known
  red-on-main baseline.
- `validate-spec` — 16 errors, **all Layer 6 `traceability`** (`cq-N` covered by
  no feature), 12 warnings, 1 info. Sibling `additions_spec_230.xml` is 15
  Layer-6 traceability errors / 15 warnings; `additions_spec_217.xml` is 15/14.
  A per-feature additions spec never carries the whole spec's question set, so
  this is the by-construction baseline, not a defect ([[additions-spec-validate-baseline]]).
  `covers="cq-15"` is claimed because this feature genuinely protects it — §15's
  failure row for an un-materialized learned component *is* "replay score varies
  with batch shape or thread count".

## Risks / judgment calls (flagged for review)

- **`covers="cq-15"` is a judgment.** The feature's contribution to
  replay-score determinism is indirect — it refuses at admission what §12/§15
  forbid at replay — while feature 146 (canary) is the direct control. Claimed
  because the failure mode it prevents is verbatim §15's row; a reviewer who
  reads cq-15 as strictly the canary's may want it dropped, which restores the
  profile to 230's exactly.
- **The verb lists are a judgment about vocabulary.** `_INFERENCE_CALLS` omits
  `score`/`fit`/`train` because they are ordinary English here, and a policy
  helper legitimately named `score` would be a false positive with no relation
  to the deferral. A reviewer wanting maximum strictness could add them, at the
  cost of refusing legitimate policies.
- **`.bin` excluded from checkpoint suffixes** because this system's own ingest
  writes `.bin` snapshots. The suffix alone is weak evidence; the load verb is
  strong evidence and still fires. Both directions are pinned by tests.
- **Import set vs. feature 167 overlap.** `torch` is refused both by 167's
  allowlist screen and by this check. That is correct — 167 answers "is this
  inside the deployment's ceiling?", which a deployment may change tomorrow;
  231 answers "is this the deferral §11.2 recorded?", which no deployment may
  change at all. Neither call site reaches into the other's member.
- **Static analysis reads source, not behaviour.** `getattr(torch, "load")(…)`
  evades this screen, exactly as it evades 167's. Stated as an honest limit in
  the module docstring, matching 167's own posture.
