# Feature 168 — a structured fail class from every sandboxed run

## What the spec asks for

app_spec.xml, category "Untrusted Code Sandbox" (`plugin="sandbox"`,
`depends_on="163"`) — the category's **last** feature:

> **168** — System returns a structured fail class of **ok, timeout, error or
> tripwire_fail** from **every sandboxed run**

The four words are §9.1's declaration (`fail_class TEXT, -- ok | timeout |
error | tripwire_fail`) and §8's ledger vocabulary (`outcome TEXT NOT NULL`),
whose meanings `docs/nullius-tech-architecture.md` §8 fixes:

* `ok` — the pipeline ran to its persist step; the node was scored.
* `timeout` — the sandbox's hard kill (§5.2: "Hard kill, recorded as
  `fail_class=timeout`").
* `error` — the evaluation failed any other way: a crash, a refused contract,
  an unraisable in the sandbox.
* `tripwire_fail` — step 10's leakage tripwires rejected the node.

**The sentence decomposes into three claims**, and they are what the tests take
in order:

1. **returns** — a *value*, not a raise. Feature 163 already settled this stance
   for its own class ("the kill is a value, because §6.1 step 11 charges the
   trial even so"), and 168 generalises it to all four.
2. **structured** — not a bare string: the word *and* what produced it, so
   "why did this node die?" is answerable from the record.
3. **from every sandboxed run** — totality. There is no run that escapes
   classification and no fifth value; `ok` is a member of the vocabulary, not
   the absence of one.

## Relationship to the six laws already in this member

168 is the **vocabulary owner** the other six hand off to. Two handoffs are
already written into the code and are the reason this feature exists:

* **Feature 163** restates §9.1's four in `sandbox/timeout.py`
  (`NODE_FAIL_CLASSES`) and says exactly why in its own comment: *"Feature 168
  is the law that owns this vocabulary from the sandbox side; this module knows
  it in order to leave the other three values alone."* Its
  `timed_out_record` **refuses to write over** a class it did not produce —
  "a quarantined seccomp violation that reads as a timeout, a crash that reads
  as a hang" — and its test suite names the owner: *"re-labelling it is feature
  168's job."*
* **Feature 161** (`sandbox_escape`, a genuine seccomp verdict) is **not one of
  §9.1's four**. Someone has to translate the sandbox stack's *internal*
  vocabulary into the column's closed one, and that is this law.

So the one-provenance rule decides the shape: **168 restates rather than
imports** (the box untrusted code goes inside must not depend on the member that
drives it), and `sandbox/timeout.py` is **left untouched** — its restatement is
load-bearing for its own refusal, and its suite pins it as data.

## Footprint

`src/app/modules/sandbox/**` and `packages/sandbox/**` — the declared claim.
Everything lands inside those two trees. No central registry, router, factory,
migration or `pyproject.toml` edit: the member joins the workspace by convention
and the seventh control registers under its own component name.

## Design

### 1. `packages/sandbox/src/sandbox/failclass.py` — feature 168's law (new)

**No committed artifact, and that is stated rather than omitted.** Features 165
and 166 argued the same and their argument applies here verbatim: the four-value
vocabulary is §9.1's *declaration*, not a deployment knob — a deployment cannot
set it to something else, and the mapping from an internal class into the four
is fixed by §8's own definitions of the words. A
`failclass_policy.json` would be a knob nobody turns. (This is the reading I'd
flag for review; see "The one judgement" below for the alternative.)

Constants, each with provenance stated as data:

| constant | value | why |
|---|---|---|
| `FAIL_CLASS_COMPONENT_NAME` | `"sandbox-failclass"` | the seventh seat (registry replaces by name) |
| `NODE_FAIL_CLASSES` | `("ok", "timeout", "error", "tripwire_fail")` | §9.1's four, in its declaration order |
| `OK_FAIL_CLASS` / `TIMEOUT_FAIL_CLASS` / `ERROR_FAIL_CLASS` / `TRIPWIRE_FAIL_CLASS` | the four, spelled once each | the words a caller branches on |
| `SANDBOX_RUNNER_CLASSES` | `("timeout","oom","crash","violation","payload","empty")` | the runner's six, restated from `SandboxResult`'s own docstring |
| `SANDBOX_ESCAPE_CLASS` | `"sandbox_escape"` | feature 161's seccomp verdict |
| `FAIL_CLASS_TABLE` | a `Mapping` source → one of the four | **the feature**, as data |
| `SOURCE_CLASSES` | `tuple(FAIL_CLASS_TABLE)` | the vocabulary this law can read |
| `FAIL_CLASS_REQUIRED_CODE` | `"fail_class_required"` | greppable token, unreadable subject |
| `FAIL_CLASS_UNKNOWN_CODE` | `"fail_class_unknown"` | greppable token, vocabulary drift |

**The table is the feature, and totality is true by construction:**

```
ok, timeout, error, tripwire_fail        -> themselves   (§9.1's own spelling, pass-through)
timeout                                  -> timeout       (the runner's wall/CPU kill)
oom, crash, violation, payload, empty    -> error         (§8's "failed any other way")
sandbox_escape                           -> error         (feature 161, the handoff)
```

Every source in `SANDBOX_RUNNER_CLASSES` and `SANDBOX_ESCAPE_CLASS` is a key, and
the image is exactly `NODE_FAIL_CLASSES` — so "every run gets one of the four"
is a property of the data structure, not a hope. The suite pins both directions
(every source lands in the four; every one of the four is reachable).

**One classifier, so nothing can disagree about what a class is** (the discipline
`classify_duration` holds in 163):

```python
def classify_fail_class(value: Any) -> str | None:
    """One recorded class -> one of §9.1's four, or None."""
```

`None` for anything unplaceable, and the *caller* decides which refusal that
earns — an unreadable subject and a drifted vocabulary have different repairs.

**The structured value — `FailClass`**, and its invariant (the `TimeoutKill`
precedent: a store row is rebuilt from outside the law, so the object checks
itself):

* `fail_class: str` — §9.1's word, nothing else accepted.
* `source: str | None` — the internal class it was read from (`"oom"`,
  `"sandbox_escape"`), or `None` when the class arrived already in §9.1's
  spelling.
* `node_id`, `component`, `detail` — what an operator correlates on and reads.
* `ok` property, `row()` giving §9.1's own shape.
* Constructor refusals: a word outside the four; a `source` outside the
  vocabulary; and **a `source` whose table target disagrees with the word** —
  `FailClass("error", source="timeout")` is a record that contradicts itself.

**The gate — `classify_run(subject, *, node_id=None, component=None) ->
FailClassDecision`** answers an *offered run*, following 163's three-reason
decision shape rather than raising:

* the **subject** may be a recorded class text, a `Mapping` (§9.1's row), the
  runner's own result object, a `TimeoutKill` from feature 163, a tripwire
  verdict, or a raised exception. Classes are read through the *same* field
  trio 163 persists them under (`fail_class`, `outcome`, `terminal_class`),
  which is what makes a §8 ledger row, a §9.1 node row and a tripwire verdict's
  `outcome` all arrive without a second reader.
* **`None` + a `problems` field** decides the `ok` leg: an empty list is the
  runner saying the node was scored (`ok`); a non-empty one is a refused
  contract (§8's "failed any other way" → `error`) — the evaluator's own rule,
  restated.
* a **raised exception is `error`**, *including a raised `TimeoutError`*: the
  sandbox records its kills as values and never raises, so a timeout that
  arrives raised is a host-side failure wearing a familiar name. This is the
  sharpest judgement in the law and gets its own test.
* reasons: `CLASSIFIED`, `UNREADABLE_SUBJECT`, `UNKNOWN_CLASS`.
* `require()` returns the `FailClass` and **never `None`** — because `ok` *is* a
  fail class here. That is the feature's own "every", made operational, and the
  one place this law's verb shape differs from all six siblings'.

**Unreadable is not `ok`, and it is not `error` either.** A subject carrying
*neither* a class field *nor* a `problems` field says nothing about how the run
ended (an unevaluated §9.1 row, a bare object), and reading it as `ok` would be
the "absence that reads as a result" failure 166 states for its own missing
vector. An unknown *class* is refused by name rather than folded into `error`,
matching the evaluator's own classifier ("a drifted vocabulary must not become
a fabricated fifth outcome") — folding a misspelt `"TimeOut"` into `error` would
silently convert every wall-clock kill into a generic crash.

**The component value — `SandboxFailClass`**, `__slots__ = ()`: it carries no
policy, no artifact and no state, the first law in this member with nothing to
hold. Verbs: `check(subject)`, `require(subject)` (never `None`), `classes()`
(§9.1's four, the read side) and `sources()` (the vocabulary, so the totality
claim is checkable by a deployment). Every verb is one call into the module.

**Honest limits**, stated in the docstring as 157 states its own: this law
classifies *a reported outcome*; it does not run, kill, measure or detect
anything, and it cannot see a run whose termination nobody recorded. The
classification is only as good as the class the runner wrote down.

**It does not persist.** The feature's verb is *returns*; the write half is
already owned by 163's `timed_out_record` and feature 91's ledger. `row()` hands
a caller the store's shape and stops there — adding a `record()` verb here would
be a second writer for one column.

Stdlib-only (`enum`, `collections.abc`, `dataclasses`, `typing`) — no `json`,
because there is no artifact to read.

### 2. `packages/sandbox/src/sandbox/errors.py` — three classes

* `SandboxFailClassError(SandboxError)` — the contract: a run's outcome could
  not be stated as one of §9.1's four. Its bullet goes in the module docstring
  beside the other six.
* `UnclassifiedRunError(SandboxFailClassError)` — the refusal: the subject says
  nothing about how the run ended. Messages begin with `fail_class_required`.
* `UnknownFailClassError(SandboxFailClassError)` — the refusal: a class outside
  the vocabulary the sandbox stack records. Messages begin with
  `fail_class_unknown` and name the offending class *and* the vocabulary, so an
  operator sees which side drifted.

### 3. `packages/sandbox/src/sandbox/__init__.py` — the seventh component

Re-export the law's public names; add `SandboxFailClass` and
`@register(FAIL_CLASS_COMPONENT_NAME)` `build_sandbox_fail_class()`
(zero-argument, compiles no artifact, never `None`, never raises — the factory
builds every component on every `create_app()`); extend the module docstring
with the seventh seat, the 163→168 handoff and the 161 translation; extend
`__all__`.

### 4. `src/app/modules/sandbox/__init__.py` — the seat

`FAIL_CLASS_COMPONENT_NAME = "sandbox-failclass"` beside the other six,
`sandbox_fail_class_component(app=None)` mirroring the other six accessors
including the `None`-means-unregistered contract, a docstring paragraph
(including the no-artifact note — a non-`None` component here proves only that
the law is loaded, the 165/166 reading), and `__all__`. No shared file is
edited.

### 5. Tests (`packages/sandbox/tests/`)

* **`test_failclass_law.py`** (new) — the sentence clause by clause:
  * *the vocabulary*: §9.1's four in §9.1's order, pinned as data; the table's
    image is exactly the four; every one of the four is reachable; every source
    the stack records is a key (totality, both directions).
  * *every run gets a class*: a parametrised sweep over every source, plus a
    kill from feature 163, a tripwire verdict, a §9.1 row, an exception and a
    `None`-class/`problems=[]` result — each *returns* a structured `FailClass`
    whose word is one of the four, with no raise anywhere; and `require()`
    returns an object for **all** of them, `ok` included.
  * *the translation*: `timeout`→`timeout`; `oom`/`crash`/`violation`/
    `payload`/`empty`→`error`; `sandbox_escape`→`error` (161's handoff,
    quoting 163's test comment); `tripwire_fail`→`tripwire_fail`; a raised
    `Exception`→`error`; and a raised `TimeoutError`→`error`, not `timeout`.
  * *the structure*: the word, the source, the node, the detail, `row()`, a
    fresh dict per call; `FailClass` refuses a word outside the four, a source
    outside the vocabulary, and a source that disagrees with its own word.
  * *the refusals*: a bare object → `UNREADABLE_SUBJECT`; a null class with no
    `problems` field → `UNREADABLE_SUBJECT`; an unknown class text → the
    distinct `UNKNOWN_CLASS` reason, with a *different* sentence; `require()`
    raises the greppable token; both reasons raise one error class.
  * *the conformant run*: `None` + `problems=[]` → `ok`; `None` + non-empty
    problems → `error`; a class beside problems → the class governs.
  * *the facade*: `__slots__ == ()`, no state, thin delegation (verb answers
    agree with the module functions), fresh per call, `classes()`/`sources()`.
  * *the cross-member spellings*: restated as data, then asserted to agree with
    `ledger.OUTCOMES`, `evaluator.TRIAL_OUTCOMES`, `evaluator._debit`'s six and
    `tripwires.time_shuffle.TRIPWIRE_OUTCOMES` (imported in-function, so a
    sibling's absence degrades one test rather than collection).
* **`test_failclass_component.py`** (new) — the plugin seam: the component-name
  spelling, the **seven**-name pinned list, the six earlier laws still beside
  the seventh, the zero-arg builder, never `None`, survives a second
  composition, the composed law returns a class for a crash / for `ok` / for a
  kill, the refusal pinned by class *name* across the loader's module-copy
  seam, and the seat's name / accessor / `None` / no-second-vocabulary.
* **`_documents.py`** — new builders `runner_result(...)` (a duck-typed
  stand-in for the runner's result, the `SeedRecordRow` precedent),
  `fail_class_record(...)` (§9.1's row / §8's ledger row) and `tripwire_outcome(...)`
  (the verdict's shape), plus the class constants; fresh per call, the suite's
  existing rule; **no change to any existing builder**, so features 157–166
  keep their subjects.
* **Six existing files pin the component list and must gain one name each**
  (`test_component.py`, `test_imports_component.py`, `test_seed_component.py`,
  `test_thread_component.py`, `test_transfer_component.py`,
  `test_timeout_component.py`), and two of them pin the seat's `__all__` as an
  exact set (`test_component.py`, `test_imports_component.py`); the
  "exactly six components" comments in all six are updated to seven.

### Verification

* `uv run --all-packages pytest packages/sandbox -q` — the member suite, 571
  passing at baseline, must be green.
* `uv run --all-packages pytest -q` — the repo-level `tests/` tree, which is
  what the acceptance gate grades; unaffected by this footprint, run to be sure.
* `ruff check` on the touched files only, compared against a sibling file's
  baseline (the repo's lint is red on `main`).

## The one judgement worth flagging

**No committed artifact.** Features 157, 167, 164 and 163 each ship one because
each is a *configuration* a deployment writes down (which isolation, which
imports, which pins, how long). 168's subject is a *vocabulary and a mapping*
that §9.1 and §8 fix — a deployment cannot set it differently, and 165/166
already established "no artifact, and here is the argument" as a legitimate
answer in this member. If the reviewer prefers an artifact
(`failclass_policy.json` carrying the table, with a compile that refuses a
mapping outside the four), the law's gate is unaffected: it reads the table
either way, and `FAIL_CLASS_TABLE` would simply be built from the compiled
document. I've taken the no-artifact reading because inventing a file here would
be inventing a knob nobody turns, which is 166's stated objection.
