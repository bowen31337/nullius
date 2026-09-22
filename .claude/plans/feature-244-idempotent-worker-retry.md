# Feature 244 — the idempotent retry of an interrupted evaluation worker

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 244:
*System retries an interrupted evaluation worker idempotently, so
spot-instance reclamation returns no duplicate ledger debit.*
`plugin="discovery"`, `depends_on="238"`.

Footprint: `packages/discovery/**`, `src/app/modules/discovery/**`.

## What already exists, and what this feature therefore is

Feature 238 landed the pool: `run_batch(worker, jobs, *, width)` runs a
batch across the campaign's W concurrent slots and captures every
worker failure as a value on its `WorkerResult` — and its docstring
names this feature twice: *"an interruption is a fact the **caller**
observes and retries, never a half-run the pool silently tore down"*
and *"feature 244's idempotent retry needs the failure it retries to
arrive as a fact about one job."*  §14's compute-topology row states
the whole contract — eval workers are *"Spot-eligible.  Failures
retry; ledger debits are idempotent by `node_id`"* — and that row is
two halves owned by two members: the ledger owns the idempotence
(feature 95's `debit`, append-only-when-no-row, answered by the prior
sequence on a retry), and the discovery member owns the retry.  The
evaluator's own debit step (`evaluator._debit`) already speaks the
idempotent spelling; what no feature has landed is the retry that
makes the pair a system property.

So the feature is the caller-side retry seam: `retry_interrupted(
worker, results, *, retries, width)` — take the results the pool
answered *interrupted*, re-run their jobs across the same W slots
under a caller-stated retry budget, and yield one `RetriedResult` per
interrupted job.

## Decisions

**1. An interruption is `WorkerInterrupted`, and only that.**  A new
`DiscoveryError` subclass in `errors.py` — the worker-of-record's
translation of reclamation (the sandbox child dying of the cloud's
signal, the host going away) into the one fact this seam can act on.
Two deliberate exclusions, both pinned by tests:

* an **evaluation failure** (`RuntimeError`, `timeout`, a
  `DiscoveryError` refusal out of the expansion) is *not* an
  interruption: §6.1 step 11 debits a failed node because *"a failed
  evaluation still consumed a hypothesis"*, so the attempt is
  completed, debited and logged (feature 240's "including failures")
  — re-running it would spend compute to replace an outcome the tree
  already holds.  Handing such a result to the retry is **refused**.
* a bare `KeyboardInterrupt` is *not* an interruption either: that is
  the operator's halt, and a system that retries its operator's stop
  cannot be stopped.  Reclamation arrives translated, or not at all.

`is_interruption(result)` is exported as the public predicate so the
caller filters its stream with the same classifier the seam uses.

**2. The idempotence is the identity law: the retry re-runs
`result.job`, and cannot name anything else.**  The seam's input is
*results*, not jobs — it reads the job off the interrupted result, so
a retry is structurally the same ask the interrupted run carried, and
the debit the re-run posts keys on the same `node_id` the first run
did.  §14's contract then answers: one row, prior sequence.  A retry
that minted a fresh node id would be a charge the ledger dutifully
appends — the duplicate this feature exists to prevent — and the
guard is doubled: **two interrupted results naming one job are
refused**, because that caller has already double-dispatched one node
and the retry of both would be the duplicate debit in person.  The
law is pinned inside the value too: `RetriedResult.__post_init__`
refuses an outcome whose result and interruptions do not answer one
job.

**3. Rounds through feature 238's pool, at the campaign's width.**
Each retry round is one `run_batch` dispatch of the still-interrupted
jobs at the same `width` (required, no default — the re-dispatch runs
on the campaign that authorized the first one).  Within a round the
as-each-completes law is inherited unchanged: a fast re-run's outcome
is yielded the moment it lands, never withheld for a slow sibling.
The boundary *between* rounds is a barrier and cannot help but be:
a re-run cannot start before the interrupted run it replaces has
ended.  `retries` is required with no default — a default would be
this module inventing an interruption policy; the budget is the
campaign loop's, stated per call.

**4. The outcome is one value, `RetriedResult(result, interruptions)`.**
`result` is the standing attempt — the re-run that answered (success
or evaluation failure alike; a failure that happens on the re-run is
a value, 238's law, not a reason to retry again) or, when the budget
is spent and the last run was itself interrupted, the last
interruption.  `interruptions` is every interrupted attempt that was
followed by another run, so `len(interruptions)` is exactly the
retries consumed and `attempts = len(interruptions) + 1` always.
`exhausted` says the standing outcome is itself an interruption —
feature 240's to log, the campaign loop's to act on; the seam never
loops forever.  Frozen, validated in `__post_init__` (one job across
result and interruptions; every interruption really an interruption)
— the discipline `CampaignRecord` states for rebuilt instances.

**5. The refusals are `BatchDispatchError`, eager, and the pool's own
are restated.**  The retry's ask-level refusals join 238's class
because the repair is the same — re-consider the ask, nothing was
run: a `retries` that is not a genuine positive integer (`bool`
refused), a result that is not a `WorkerResult`, a result that is not
an interruption, two results naming one job.  The `worker` and
`width` predicates are restated here (the fourth restatement of the
count predicate — clip, record, dispatch, re-dispatch — which this
member's precedent treats as law rather than drift) so the refusal
fires on the *call*, before the results iterable is consumed and
before any slot starts: `retry_interrupted` is a plain function that
refuses the ask and returns the stream, exactly `run_batch`'s shape.
An empty input answers an empty stream and starts no slots — 242's
termination discipline, inherited.

**6. No component, no seat.**  The retry inherits 238's reason rather
than merely borrowing it: it exists for the length of one call, holds
nothing between calls, and its two numbers (`retries`, `width`) are
per-call facts the caller states — a builder would have to bake a
budget no campaign stated.  The member's registered surface stays
feature 232's single store; `test_component.py` is untouched.

**7. The payoff is pinned against the real ledger, cross-member.**
`test_retry.py`'s final class composes the real `ledger.TrialLedger`
(in-function import + path bootstrap + `importorskip`, the
`test_cross_member.py` remedy) behind a worker that debits its node
and is then reclaimed, and pins §14's row end to end: the retry
re-posts the debit, the ledger answers with the prior sequence, and
the table holds **one row** for the node — plus the other order
(reclaimed before the debit: the retry's debit is the only one) and
the exhausted case (several attempts, still one row).  The member
itself imports no sibling; the composition lives only in the test,
where the workspace contract permits it.

## Files

* `packages/discovery/src/discovery/retry.py` — the feature:
  `retry_interrupted`, `RetriedResult`, `is_interruption`.
* `packages/discovery/src/discovery/errors.py` — `WorkerInterrupted`
  plus its module-docstring paragraph (and `BatchDispatchError`'s
  paragraph grows the retry's asks).
* `packages/discovery/src/discovery/__init__.py` — re-exports; the
  docstring's fourth-module and no-component paragraphs.
* `packages/discovery/tests/test_retry.py` — the laws: the retry law
  (an interrupted job runs again; twice-reclaimed runs again across
  rounds; exhausted stands interrupted), the identity law (the same
  job object, never a minted ask; one job per outcome; duplicates
  refused), the classification law (only the marker retries; an
  evaluation failure and an operator's halt both refused), the budget
  law (required, genuine count, exactly that many re-runs), the
  dispatch law (the pool's refusals restated and eager; round liveness
  — an answered re-run not withheld by a slow sibling; width
  respected), and the ledger composition (one row per node through
  reclamation, retry and exhaustion).
