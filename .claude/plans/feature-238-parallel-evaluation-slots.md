# Feature 238 — W parallel evaluation workers, run as concurrent slots

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 238:
*System runs W parallel evaluation workers as concurrent slots, which
returns batch results as each worker completes.* `plugin="discovery"`,
`depends_on="232"`.

Footprint: `packages/discovery/**`, `src/app/modules/discovery/**`.

## What already exists, and what this feature therefore is

`packages/discovery` exists (feature 232 landed the campaign record and the
`discovery` component; feature 241 added the legal theme set). Feature 238 is
the member's third module and the first one about the inner loop itself:

* PRD §5 loop 1 states the thing in four words — *"`W` parallel workers =
  concurrent evaluation slots"* — beside `CONTINUE(v)` (feature 239's
  expansion) and *"every attempt is logged to the tree with its full
  artifact"* (feature 240's persistence).
* The component map (architecture §3) places the dispatch:
  `POLBOX -->|batch selection| DISC` and `DISC --> SAGENT`.
* `W` is feature 232's `workspace_count` — the same number §4.1.1's
  `φ = clip(max(2/W, 0.15), 0.15, 0.35)` divides by, validated by the
  record's own predicate.

So the feature is the dispatch seam: `run_batch(worker, jobs, *, width)` —
run one selected batch across the campaign's W slots, yield each
`WorkerResult(slot, job, value, error)` the moment its slot finishes.

## Decisions

**1. No component, no seat.** The pool exists only for the length of one
call: the dispatch creates its slots, the stream's end joins them, nothing
persists between batches. A builder would have to bake the width at
composition time — a pool whose W was decided by the process rather than the
campaign record is precisely the invented-campaign refusal the missing
default states. The member's registered surface stays feature 232's single
store; the 241-inherited reasoning is restated in `__init__.py`'s docstring.

**2. Slots are threads, not processes.** A slot is a concurrency lane, not
an isolation boundary: the evaluation a slot drives already has its process
isolation (§5.2's sandboxed child), and the PRD's "multiprocessing" row is
satisfied by those children — the slot's thread blocks on the child's
result while W−1 siblings do the same. A process pool would demand a pickle
boundary the worker of record (239's expansion, closing over stores and
workspace handles) does not survive. Threads also give 244's idempotent
retry its premise: a slot that has taken a job runs it to completion; an
interruption is observed and retried, never a half-run the pool tore down.

**3. As-completed, not a barrier.** The return is a generator yielding in
completion order — the sentence's own clause (*"which returns batch results
as each worker completes"*). Completion order is deliberately not smoothed
into submission order: each result self-identifies (`job` echoed, `slot`
named), so a caller needing determinism sorts by `job`. §12 binds
arithmetic and persistence; the pool performs none and writes nothing, so a
timing-dependent *delivery* order with fixed values is not a §12 violation —
and hiding it behind an internal sort would move the nondeterminism
somewhere nobody had named.

**4. A failed run is a value.** Worker exceptions are captured on the
result (`error`, `value=None`, `ok` False) and the batch continues — the
sandbox's discipline restated at the dispatch layer, because 240 persists
attempts "including failures" and 244 retries a failure that arrived as a
fact about one job. The per-job catch is `BaseException` on purpose: an
`Exception`-only catch would let a worker's exit kill its slot's thread and
hang the stream on an answer that never arrives. Corollary (the pool's one
invariant, pinned as such): **every job is answered exactly once, whatever
its outcome.**

**5. `width` is required, validated by 232's predicate, and there is no
default.** `BatchDispatchError` (new, beside the other three in
`errors.py`) for a width that is not a genuine positive integer, a worker
that is not callable, or jobs that are not a batch — including a bare
`str`/`bytes`, which iterating would turn into a batch of characters the
policy never selected. Validation is eager: `run_batch` is a plain function
that refuses the ask and returns the generator, so a malformed dispatch
never reads the batch (the jobs iterable is consumed only after worker and
width pass) and starts no threads.

**6. Lifecycle.** Exhausted, the generator joins its slots before
`StopIteration`. Closed early, the handout stops; a running job finishes
(threads cannot be killed mid-evaluation) and its answer is discarded. A
batch smaller than W starts only that many slots, filling from slot 0; an
empty batch starts none and answers nothing — feature 242's *"policy
selects no batch"* termination is the caller's judgement, and the pool's
answer to nothing selected is an empty stream, not an error.

## Files

* `packages/discovery/src/discovery/workers.py` — the feature: `run_batch`,
  `WorkerResult`, `SLOT_THREAD_PREFIX`.
* `packages/discovery/src/discovery/errors.py` — `BatchDispatchError`, plus
  the module docstring's fourth-class paragraph.
* `packages/discovery/src/discovery/__init__.py` — re-exports; docstring
  paragraphs (three modules; 238 inherits 241's no-component decision).
* `packages/discovery/tests/test_workers.py` — 39 tests: the W law (a
  `Barrier` of exactly W parties completes; concurrency reaches and never
  exceeds W; slots reused; two batches nest), the return law (completion
  order; liveness — a held job's sibling answer consumed while the held job
  still runs), the answer law (every job exactly once; `Exception` and
  `BaseException` and this member's own `DiscoveryError` all captured as
  values), the refusals (eager, on the call, before the batch is read), the
  empty batch, the lifecycle (no leaked threads; close abandons pending
  jobs), and the 232→238 seam (a planned campaign's `workspace_count` is
  the width, `W = 1` included).
