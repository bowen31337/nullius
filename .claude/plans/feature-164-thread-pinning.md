# Feature 164 — a sandbox invocation missing the thread-pinning environment is rejected

## What the spec asks for

app_spec.xml, category "Untrusted Code Sandbox" (`plugin="sandbox"`,
`depends_on="157"`):

> **164** — System rejects a sandbox invocation **missing the thread-pinning
> environment**

§5.2 of `docs/nullius-tech-architecture.md` names the environment in its one
call site:

```python
result = sandbox.run(
    entrypoint="signal", code=node.code, payload=window.to_arrow(),
    limits=Limits(...), seed=node.seed,
    env={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
)
```

and §12's determinism table gives the row this feature is the sandbox-side half
of: `Single-threaded numerics | OMP_NUM_THREADS=1, MKL_NUM_THREADS=1 in every
eval worker`. §5.2's closing line states the stakes: *"Thread-count pinning is
not a performance setting. Multi-threaded BLAS reductions are non-deterministic
in float, which breaks P3."*

**Relationship to feature 137 (`canary._threads`, already landed).** 137 is the
*sweep* — "rejects an **evaluation worker** started without OMP/MKL set to 1" —
and it reads a worker's environment and its measured pool. 164 is the same fact
one layer out: the **sandbox invocation** §5.2 dispatches *into* that worker.
Two features, two subjects, one law; the sandbox member does not import the
canary member (the box untrusted code goes inside must not depend on the
member that drives it), so the two cap names are **restated with a provenance
comment**, exactly as feature 165 restates `NULLIUS_SIGNAL_SEED` against
`evaluator._sandbox` and pins the spelling as *data* in its suite.

## Footprint

`src/app/modules/sandbox/**` and `packages/sandbox/**` — the declared claim.
Everything lands inside those two trees. No central registry, router, factory,
migration or `pyproject.toml` edit: the member already joins the workspace by
convention and the fifth control registers under its own component name.

## Design

### 1. `packages/sandbox/src/sandbox/threads.py` — feature 164's law (new)

A law about the *environment a run is dispatched with*, in the shape the
member's other four laws established (module + committed artifact + component +
seat).

Constants:

| constant | value | why |
|---|---|---|
| `PINNING_POLICY_KIND` | `"sandbox-thread-pinning"` | the document marker (§157/167 discipline) |
| `COMMITTED_PINNING_POLICY` | `Path(__file__).with_name("pinning_policy.json")` | the artifact ships beside the law |
| `SINGLE_THREADED` | `"1"` | §12's value, spelled once |
| `THREAD_PINNING_CODE` | `"thread_pinning_required"` | the greppable token every refusal carries |
| `ENV_OMP` / `ENV_MKL` | `"OMP_NUM_THREADS"` / `"MKL_NUM_THREADS"` | the spellings the committed artifact uses |
| `POOL_FLOOR_VARIABLE` | `"POLARS_MAX_THREADS"` | the third name the module knows, mirroring 137 |

Artifact (`compile_pinning_policy` / `load_pinning_policy` /
`committed_pinning_policy`), refusing whole rather than partially:

```json
{
  "policy": "sandbox-thread-pinning",
  "caps": [
    {"name": "OMP_NUM_THREADS", "value": "1", "layer": "the OpenMP-parallel BLAS kernels"},
    {"name": "MKL_NUM_THREADS", "value": "1", "layer": "the Intel MKL threading layer"}
  ],
  "pool_floors": ["POLARS_MAX_THREADS"]
}
```

Compile rules — this is where the artifact is held to the law:
* the marker must be `PINNING_POLICY_KIND` (`ThreadPinningDocumentError`);
* `caps` non-empty, each a block with a non-empty `name`, a `value`, and a
  non-empty `layer` (the layer is what a refusal names, so an operator learns
  *which* library was left threaded);
* a `value` that is not `SINGLE_THREADED` is refused with
  **`ThreadPinningRequired`** — a policy that pins a reduction to two threads is
  not a thread-pinning policy, and admitting it would make the law vacuous;
* duplicate names refused (one name is one knob, not two blocks);
* `pool_floors` entries must be names, disjoint from `caps`.

Compiled value `ThreadPinningPolicy`: `caps` (tuple of `ThreadCap(name, value,
layer)`), `pool_floors`, `value(name)`, `required_names()`, `pins()`.

The gate `check_thread_pinning(subject, policy) -> ThreadDecision`:

* the **subject** is a `Mapping` (an environment) or an object carrying a
  `Mapping` `.env` — so the launcher can hand either law the *same*
  `SandboxInvocation` feature 165 already describes (`law.require(invocation)`),
  or a plain env. Anything else is a refusal, not a raise, like every gate here;
* each required cap is classified — absent/blank (including an empty mapping) is
  `WITHOUT_PINNING`; present at anything but the pin (an integer other than 1,
  `"auto"`, `""`, a non-string, a `bool`) is `THREADED_CAP`, decided by a
  restated `strtol`-shaped grammar so the same spellings feature 137 accepts are
  the ones this law accepts;
* a declared pool floor wider than the pin is `THREADED_POOL` — it outranks the
  caps inside the library that reads it, which is 137's stated reason for
  knowing the name;
* nothing is raised: the answer is a `ThreadDecision(admitted, reason, detail,
  missing, threaded)` whose `require()` raises. `missing`/`threaded` name the
  offending variables so the audit line is actionable.

`SandboxThreads` (the component value, `__slots__ = ("_policy",)`):
`policy`, `required()`, `value(name)`, `pins()`, `pool_floors()`,
`check(subject=None)`, and **`require(subject=None) -> dict[str, str]`** — the
launcher's verb: refuse, or return the environment to hand the box, a **copy
with the pins written** (never the caller's mapping, the copy-then-write
discipline `SandboxInvocation.with_seed` / `evaluator._sandbox._child_env` use).
`None` means the process environment, so the most literal reading of the
feature — *this invocation is missing the pinning environment* — is a refusal
by default.

**It refuses rather than repairs.** A declared non-pin value is refused, not
overwritten: the deployment wrote something, and silently repairing it in the
launcher is the drift this member refuses everywhere (157 refuses the whole
document, 165 refuses to overwrite a record). The repair lives where feature 137
put it — the worker is *started* under the pins — and this law's refusal says so.

**Honest limits** (stated in the docstring, as 157 states its own): the law
reads the environment; a launcher that smuggles `OMP_NUM_THREADS=4` into the
child's argv or that recomputes the env after the check is not visible here, and
the *measured* pool is feature 137's sweep against a loaded library, not this
module's. What holds is that §5.2's call site cannot be dispatched through this
seam without the pins, and that the refusal names the variable and the layer.

Stdlib-only (`enum`, `json`, `re`, `collections.abc`, `pathlib`) — the module
spawns nothing, imports no other member, and reads no environment at import.

### 2. `packages/sandbox/src/sandbox/errors.py` — two classes

* `SandboxThreadPinningError(SandboxError)` — the contract: a run was dispatched
  without the thread-pinning environment. Its bullet goes in the module
  docstring beside the other five, on the same reasoning (a threaded reduction
  produces a *different last bit*, which is P3's invisible failure and not a
  crash).
* `ThreadPinningRequired(SandboxThreadPinningError)` — the refusal itself, every
  message beginning with `thread_pinning_required`;
* `ThreadPinningDocumentError(SandboxThreadPinningError)` — the artifact could
  not be read as a policy (sibling, not subclass, of the refusal — the split
  157's and 167's pairs draw).

### 3. `packages/sandbox/src/sandbox/__init__.py` — the fifth component

Re-export the law's public names; add `SandboxThreads` and
`@register(THREADS_COMPONENT_NAME)` `build_sandbox_threads()` (zero-argument,
compiles the committed artifact, never `None`, never raises — the factory builds
every component on every `create_app()`); extend the module docstring with the
fifth seat and the 137/164 division; extend `__all__`.

### 4. `src/app/modules/sandbox/__init__.py` — the seat

`THREADS_COMPONENT_NAME = "sandbox-threads"` beside the other four (the registry
replaces a name's earlier registration, so the fifth control gets its own name),
`sandbox_threads_component(app=None)` mirroring the other four accessors
including the `None`-means-unregistered contract, a docstring paragraph, and
`__all__`. No shared file is edited.

### 5. Tests (`packages/sandbox/tests/`)

* `test_thread_law.py` — the sentence clause by clause: the classifier's
  spellings (`"1"`, `" 1 "`, `"+1"`, `"01"`, `1` capped; `"2"`, `"0"`, `""`,
  `"auto"`, `"1.0"`, `True`, `None` refused); both §12 caps required by *and*;
  absent / blank / wrong-value refusals with their own reasons; the pool floor;
  subject shapes (mapping, invocation-like, unreadable); `require` returns a
  copy with the pins and never mutates the base; `check` and `require` never
  disagree; the env spelling is pinned as data (`"OMP_NUM_THREADS"`, `"1"`)
  rather than imported from `canary`; the error family.
* `test_thread_artifact.py` — the committed artifact: shipped, compiles, holds
  exactly the two §12 names at the pin plus the floor; drift (value `"2"`, a
  missing cap, a duplicate, a foreign marker, a non-mapping, unreadable file)
  refused, with the *whole* document refused rather than the block skipped.
* `test_thread_component.py` — the plugin seam: name spelling, the five-name
  pinned list, the four earlier laws still beside the fifth, zero-arg builder,
  never `None`, survives a second composition, the composed law refuses an
  unpinned env (pinned by class *name* across the loader's module-copy seam),
  and the seat's name / accessor / `None` / no-second-vocabulary / `__all__`.
* `_documents.py` — new builders `thread_pinned_env()`, `unpinned_env()`,
  `pinning_document(...)`, `committed_pinning_document()` (fresh per call, the
  suite's existing rule); **no change to `invocation()`'s defaults**, so
  feature 165's tests keep their subject.
* Four existing files pin the component list / seat vocabulary and must be
  extended by one name each: `test_component.py`, `test_imports_component.py`,
  `test_seed_component.py`, `test_transfer_component.py`.

### Verification

* `uv run --all-packages pytest packages/sandbox -q` (the member suite: 339
  passing today) and the repo-level `uv run pytest -q` (the acceptance gate's
  suite — unaffected by this footprint but run to be sure).
* Lint only the touched files (`ruff check` against the member, compared to a
  sibling file's baseline as the repo's lint is red on `main`).

## The one judgement worth flagging

**The committed artifact (`pinning_policy.json`) is new here.** Features 166 and
165 have none, and their docstrings argue why: their subjects are a format and a
value a run is *handed*. 164's subject is closer to 157's and 167's — the
*environment a deployment configures a run with* — so it ships the artifact, the
compile refusal, and the "a non-`1` pin is not a pin" check that makes the file
a real constraint rather than decoration. If the reviewer prefers the 165/166
shape (no file, constants only), the law's gate is unaffected: it reads the
compiled policy either way, and the module-level `committed_pinning_policy()`
would simply build the same policy from those constants.
