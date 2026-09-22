"""W parallel evaluation workers, run as concurrent slots — feature 238.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 238: *System
runs W parallel evaluation workers as concurrent slots, which returns
batch results as each worker completes.*  docs/alpha-engine-prd.md §5's
loop 1 states the same fact in four words the PRD's own bullet block
spells — *"``W`` parallel workers = concurrent evaluation slots"* — and
this module is that bullet: the dispatch seam where the batch the policy
selected meets the W slots the campaign was planned with, and where each
result is handed back the moment the slot that produced it finishes.

**Where W comes from, and why there is no default.**  ``W`` is feature
232's ``workspace_count`` — the campaign record's well count, the same
``W`` §4.1.1's ``φ = clip(max(2/W, 0.15), 0.15, 0.35)`` is derived from
and the one §5's loop 1 runs across.  :func:`run_batch` takes it as a
required keyword argument with **no default**, because a default would be
this module inventing a campaign: the width a batch runs at is a
planning-time fact the record already holds, and a pool that silently
serialized (``W = 1``) or silently widened would be running a different
campaign than the one whose fraction was planted.  The caller that planned
the campaign passes ``width=record.workspace_count``; the validation here
is feature 232's own predicate restated — a genuine positive integer,
``bool`` refused — for the same reason ``_validated_workspace_count``
restates :func:`discovery.campaign.null_fraction`'s: the *act* differs
(planning a count vs. sizing a dispatch), so each names its own refusal,
but the *kind of value* is one and a drift between the two spellings would
be a pool wider or narrower than the campaign that authorized it.

**Slots are threads, and that is a decision about where isolation lives.**
A slot is a *concurrency lane*, not an isolation boundary: the thing a slot
drives is one evaluation, and an evaluation's process isolation is
§5.2's sandbox — the child process with hard rlimits the evaluator member
runs every signal in.  The PRD's parallelism row (``multiprocessing, with
Ray only if scaling past one machine``) is satisfied by exactly those
children: a slot's thread blocks on a sandboxed child's result while W−1
siblings do the same, which is the shape "concurrent evaluation slots"
names.  A process pool here would add a *second* isolation layer the
architecture never asks for, and it would pay for it twice — every job and
every worker callable would have to cross a pickle boundary, and the
worker of record (feature 239's expansion, which closes over stores and
workspace handles no pickle can carry) does not survive one.  Threads also
carry the property feature 244's idempotent retry builds on: a thread
cannot be killed mid-job, so a slot that has taken a job runs it to
completion — an interruption is a fact the *caller* observes and retries,
never a half-run the pool silently tore down.

**As each worker completes, not when the batch does.**  The return is a
*stream*, not a list: :func:`run_batch` yields each
:class:`WorkerResult` the instant its slot puts it on the queue, so a slow
evaluation never withholds a fast one's answer.  That is the clause the
feature's own sentence hangs on — *"which returns batch results as each
worker completes"* — and the component map (§3) says who consumes it:
``POLBOX -->|batch selection| DISC`` hands the orchestrator its batch, and
the orchestrator hands each attempt to §5's *"every attempt is logged to
the tree with its full artifact"* as it lands (feature 240's persistence
streams per attempt rather than waiting out the slowest branch).  A
barrier — materialise everything, then sort — would be simpler and is
exactly what the sentence refuses: with W slots and one slow branch, a
barrier reports W−1 finished evaluations only after the Wth ends.

**Completion order is the machine's; the results' identity is not.**  The
stream's order is timing's, which varies run to run and machine to
machine, and that is deliberately *not* smoothed over here: each
:class:`WorkerResult` carries the ``job`` it answers and the ``slot`` that
ran it, so a caller that needs a deterministic order (a manifest, a
comparison against a replay) sorts by ``job`` and has one — §12's
determinism contract binds the *arithmetic* a system performs and the
*persistence* it writes, and this pool performs none and writes nothing:
workers see their job alone, no shared mutable state, no ordering the pool
imposes on the values themselves.  What §12 forbids is a replay whose
numbers move with thread count; a stream whose *delivery order* moves with
timing while every value is fixed is not that, and hiding it behind a sort
would only move the nondeterminism into a place nobody had named.

**A failed run is a value.**  A worker that raises does not raise through
the stream: the exception is captured on the result
(:attr:`WorkerResult.error`, with :attr:`WorkerResult.value` empty) and
the batch continues, so the caller hears about every attempt — the
evaluator sandbox's own discipline for its failures, restated at the
dispatch layer because the two consumers downstream both need it: feature
240 persists *every* attempt "including failures", and feature 244's
idempotent retry needs the failure it retries to arrive as a fact about
one job, not as the death of the batch.  The corollary is the pool's one
invariant, and it is total: **every job in the batch is answered exactly
once, whatever its outcome** — a caller counting results counts attempts,
never slots, never successes.

**The refusals, and they all fire before any slot starts.**
:class:`~discovery.errors.BatchDispatchError` for a ``width`` that is not
a genuine positive integer, a ``worker`` that is not callable, or a
``jobs`` that is not a batch (not iterable at all, or a bare ``str``/
``bytes`` — one ask spelled without its brackets, which iterating would
silently turn into a batch of characters).  The validation is *eager*:
:func:`run_batch` is a plain function that checks the ask and returns the
generator, rather than a generator function whose body would not run
until the first ``next()`` — a refusal deferred to first consumption
would have a caller believe the dispatch was accepted, and the fix for
that illusion is spelled before any thread exists.

**Lifecycle, including the ways a stream ends early.**  Exhausted, the
generator joins its slots before raising ``StopIteration`` — no thread
outlives the batch.  Closed early (``gen.close()``, or the generator
falling out of scope and being finalised), the pool stops handing out
jobs; a slot already running a job finishes it — the cannot-kill property
above — and that result is discarded rather than delivered, because the
consumer that closed the stream has said it wants no more answers.  A
batch smaller than ``width`` starts only ``min(width, len(jobs))`` slots
(a slot is capacity, not an obligation) and an empty batch starts none
and answers nothing: the pool's answer to feature 242's *"policy selects
no batch"* is an empty stream, not an error, because termination on an
empty selection is the caller's judgement to make and the pool's job is
to have made no slots for it.

**No component, for the reason feature 241's config doc states and this
feature inherits.**  The factory's registration protocol is for *state a
deployment holds* — a store, a device, a materialised pool of worlds —
and this pool exists only while a batch is running: it is created by the
call, joined by the call's end, and holds nothing between batches.  A
builder for it would have to return either a fresh pool per composition
(a function wearing a component's name) or a singleton whose width was
baked at startup — which would be the default-width refusal in another
spelling, a pool that outlived the campaign that authorized it.  The
member's one registered name stays feature 232's campaign store.

**Stdlib only, and import-cheap.**  ``threading``, ``queue``, ``deque``
and a dataclass; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for the dispatch, and a composed application that never
dispatches a batch never starts a thread.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from queue import SimpleQueue
from typing import Any

from .errors import BatchDispatchError

__all__ = [
    "SLOT_THREAD_PREFIX",
    "WorkerResult",
    "run_batch",
]

#: The name every slot thread carries, prefixed so a deployment's thread
#: dump (and this member's own suite) can tell an evaluation slot from
#: every other thread a composed application runs.  Diagnostic, not an
#: identity: two pools in one process — a caller dispatching a batch from
#: inside a worker, say — may share a name, and the slot a result actually
#: came from is :attr:`WorkerResult.slot`, not the thread's name.
SLOT_THREAD_PREFIX = "discovery-slot-"


@dataclass(frozen=True)
class WorkerResult:
    """One job's answer, from the slot that ran it.

    The atom the stream yields, and the whole of what "batch results"
    means: the ``job`` (echoed exactly as the batch held it, because
    completion order is timing's and a result that did not say which ask
    it answers would force the caller back to submission order — the
    barrier this feature refuses, rebuilt one layer up), the ``slot``
    that ran it (``0``-based index into the W concurrent slots; a batch
    smaller than W leaves the higher-indexed slots unfilled), the
    ``value`` the worker returned, and the ``error`` it raised if it
    raised.

    Frozen, the discipline :class:`~discovery.campaign.CampaignRecord`
    states for its own reasons and this one repeats for the caller's: a
    result is the record of an attempt, and a mutable one would let a
    consumer edit the outcome of an evaluation the tree is about to
    log.  Constructed only by the pool — the fields are data, not a
    public constructor contract — and never validated, because there is
    nothing here to validate: every field is either the caller's own
    ``job`` echoed back, a slot index the pool minted, or whatever the
    worker answered.
    """

    #: The slot that ran the job — its index among the batch's W
    #: concurrent slots, ``0``-based.
    slot: int
    #: The ask this result answers, exactly as the batch held it.  The
    #: correlation key: a caller matches results to its batch by this
    #: field, never by arrival order.
    job: Any
    #: What the worker returned — present exactly when :attr:`error` is
    #: ``None``.
    value: Any = None
    #: What the worker raised, captured rather than propagated — *a
    #: failed run is a value*, so the batch answers every attempt and
    #: feature 240's persistence can record the failure with the rest.
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        """True when the slot's worker answered rather than raised.

        The one state a consumer treats as a usable evaluation — the
        same shape :class:`SandboxResult`'s ``ok`` gives the evaluator's
        own failures, and for the same reason: the interesting split is
        *did this attempt produce anything*, not *did the pool survive*,
        which it always did.
        """
        return self.error is None


# -- Validation ------------------------------------------------------------------


def _validated_width(width: Any) -> int:
    """Refuse a width that is not the W a campaign was planned with.

    Feature 232's own predicate — ``_validated_workspace_count``'s in
    :mod:`discovery.campaign` — restated here for the third time in
    the member (the clip's, the record's, and now the dispatch's), which
    is precedent rather than drift: each restatement names its own act
    while holding the kind of value fixed, and the alternative — calling
    the campaign module's validator — would raise the *planning*
    refusal from the *dispatch* ask, putting a caller's ``except`` in the
    wrong module for the same reason :mod:`discovery.errors` keeps its
    classes split by repair.

    ``True`` is refused as loudly as ``"4"``: a bool is not a count, a
    fractional or textual width is not a number of slots, ``0`` would be
    a campaign of no wells dispatched as no slots, and a negative width
    is not a thing at all.  Each refusal names ``workspace_count`` so the
    operator reads which field of which record the bad number came from.
    """
    if isinstance(width, bool) or not isinstance(width, int):
        raise BatchDispatchError(
            f"width must be a positive integer, got {width!r} "
            f"({type(width).__name__}); width is the campaign record's "
            f"workspace_count — the W the campaign was planned with and "
            "§5's 'W parallel workers = concurrent evaluation slots' — so "
            "a width that is not a count is a dispatch no campaign "
            "authorized"
        )
    if width < 1:
        raise BatchDispatchError(
            f"width must be at least 1, got {width!r}; §4.1.1's fraction "
            "divides by this W and §5's loop runs W parallel workers, so "
            "a campaign of zero or negative wells has no slots to "
            "dispatch a batch across — pass the campaign record's "
            "workspace_count"
        )
    return width


def _validated_worker(worker: Any) -> Callable[[Any], Any]:
    """Refuse a worker the pool cannot call.

    The worker *is* the evaluation — feature 239's expansion, a
    deployment's evaluator driver, a test's stand-in — and the pool's
    whole behaviour on it is one call per job.  Anything not callable
    would fail inside the first slot as a captured error on the first
    result, which is the honest place for an *evaluation* to fail and
    the wrong place for a dispatch that was never going to run: a
    non-callable worker fails all W slots identically, and a batch whose
    every result is the same plumbing error is an ask refused late.
    """
    if not callable(worker):
        raise BatchDispatchError(
            f"worker must be callable to be run as an evaluation slot, "
            f"got {worker!r} ({type(worker).__name__}); the worker is the "
            "evaluation W slots run — one call per job — and a batch "
            "dispatched onto something that cannot be called is a batch "
            "no slot could begin"
        )
    return worker


def _validated_jobs(jobs: Any) -> list[Any]:
    """Materialise the batch, refusing what is not one.

    The batch is iterated **once, here, before any slot starts** — the
    policy's selection is a sequence the caller already holds, and a
    lazy re-iteration per slot would be a second reading of an ask the
    orchestrator dispatched once (and a generator consumed by slot 0,
    silently feeding slots 1..W−1 nothing).  Two refusals:

    * not iterable at all — there is no batch to dispatch;
    * a bare ``str``/``bytes`` — one ask spelled without its brackets.
      Iterating a string would hand the slots a batch of single
      characters, every one of which would be answered exactly once by
      the pool's invariant, which is precisely why it must be refused
      *here*: the pool would faithfully dispatch a batch nobody
      selected.
    """
    if isinstance(jobs, (str, bytes)):
        raise BatchDispatchError(
            f"jobs must be a batch of asks, got {jobs!r} "
            f"({type(jobs).__name__}); a bare string is one ask without "
            "its brackets, and iterating it would dispatch a batch of "
            "characters the policy never selected — pass a sequence "
            "([the_ask], or the selected batch itself)"
        )
    try:
        return list(jobs)
    except TypeError as exc:
        raise BatchDispatchError(
            f"jobs must be a batch the pool can iterate, got {jobs!r} "
            f"({type(jobs).__name__}); the batch is the policy's "
            "selection handed to W slots, and a value with nothing to "
            "iterate is a batch with no asks in it"
        ) from exc


# -- The slots -------------------------------------------------------------------


def _run_slot(
    index: int,
    worker: Callable[[Any], Any],
    pending: deque[Any],
    results: SimpleQueue[WorkerResult],
    stop: threading.Event,
) -> None:
    """One slot's loop: take a job, run it, answer it — until none or stop.

    The loop is the whole of a slot's life, and its two exits are the
    two the module docstring names: the pending deque runs empty (the
    batch is done), or the stop flag is set (the stream closed early).
    ``deque.popleft`` is atomic, which is what makes the handout
    race-free without a lock — one pop, one job, exactly one slot per
    job.

    The per-job catch is ``BaseException`` deliberately.  ``Exception``
    would let a worker's ``SystemExit`` or ``KeyboardInterrupt`` escape
    the slot, kill its thread, and leave the driving generator waiting
    on a result that will never arrive — a stream that hangs on a
    worker's exit is a worse failure than any the capture could hide.
    Captured, the exception is data like any other, and the pool's
    invariant (one answer per job, whatever the outcome) holds for
    exits as for errors.
    """
    while not stop.is_set():
        try:
            job = pending.popleft()
        except IndexError:
            return  # the batch is answered; the slot's work is done
        try:
            value = worker(job)
        except BaseException as exc:  # noqa: BLE001 - a failed run is a value
            results.put(WorkerResult(slot=index, job=job, error=exc))
        else:
            results.put(WorkerResult(slot=index, job=job, value=value))


def _drive(
    worker: Callable[[Any], Any],
    jobs: list[Any],
    width: int,
) -> Iterator[WorkerResult]:
    """The stream itself: start the slots, yield each answer as it lands.

    Separated from :func:`run_batch` so the *ask* can be refused eagerly
    while the *stream* stays lazy — a generator function's body does not
    run until its first ``next()``, and a refusal that only fired on
    consumption would have the caller believe a malformed dispatch was
    accepted.

    The accounting is exact by construction and needs no timeouts:
    every job is popped by exactly one slot, every pop is answered by
    exactly one ``put``, so ``len(jobs)`` results are queued in total
    and the loop below yields exactly that many — the stream ends when
    the batch is answered, not when a queue goes quiet.  The ``finally``
    is the stream's two endings: exhausted (slots already idle; the
    joins return immediately) or closed early (the stop flag halts the
    handout, running jobs finish — threads cannot be killed mid-job —
    and their answers are left on the queue, discarded, because the
    consumer that closed the stream asked for no more of them).
    """
    slots = min(width, len(jobs))
    pending: deque[Any] = deque(jobs)
    results: SimpleQueue[WorkerResult] = SimpleQueue()
    stop = threading.Event()
    threads = [
        threading.Thread(
            target=_run_slot,
            args=(index, worker, pending, results, stop),
            name=f"{SLOT_THREAD_PREFIX}{index}",
        )
        for index in range(slots)
    ]
    for thread in threads:
        thread.start()
    try:
        for _ in jobs:
            yield results.get()
    finally:
        stop.set()
        for thread in threads:
            thread.join()


def run_batch(
    worker: Callable[[Any], Any],
    jobs: Iterable[Any],
    *,
    width: Any,
) -> Iterator[WorkerResult]:
    """Run one batch across W concurrent evaluation slots — feature 238's verb.

    *System runs W parallel evaluation workers as concurrent slots, which
    returns batch results as each worker completes*, as one call: the
    worker is the evaluation (one call per job — feature 239's expansion,
    a deployment's evaluator driver), ``jobs`` is the batch the policy
    selected, and ``width`` is the campaign record's ``workspace_count``
    — the W the campaign was planned with, required and defaulted to
    nothing (see the module docstring for why a default width would be
    this module inventing a campaign).

    Returns an iterator over :class:`WorkerResult`, **in completion
    order**: each result is yielded the moment the slot that ran it
    finishes, so consuming the stream is itself the as-each-completes
    behaviour the feature names.  The caller that needs a deterministic
    order sorts by ``job``; the pool imposes none on the values.

    Every job is answered exactly once whatever its outcome — a worker
    that raises is captured on its result, not propagated, so the batch
    survives its own failures and a caller counting results counts
    attempts.  An empty batch yields nothing and starts no slots; a
    batch smaller than ``width`` starts only that many slots, filling
    from slot 0.

    Refuses :class:`~discovery.errors.BatchDispatchError` — before any
    slot starts, on the call itself rather than at first consumption —
    for a width that is not a genuine positive integer, a worker that is
    not callable, or jobs that are not a batch.  Nothing else raises:
    slot failures are values, and the stream's own lifecycle (exhausted
    or closed) joins every thread it started.
    """
    # Worker and width first, jobs last: the two former are facts about
    # the *ask* and are refused without reading the batch, so a caller
    # whose width is malformed never has its jobs iterable consumed —
    # the ask is refused as an ask, whole, before anything is read.
    _validated_worker(worker)
    _validated_width(width)
    batch = _validated_jobs(jobs)
    if not batch:
        # The policy selected no batch: feature 242's termination is the
        # caller's judgement, and this pool's answer to nothing selected
        # is nothing — no slots, no error, an empty stream.
        return iter(())
    return _drive(worker, batch, width)
