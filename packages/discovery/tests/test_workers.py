"""The three laws of the W evaluation slots — pinned as behaviour.

app_spec.xml feature 238: *System runs W parallel evaluation workers as
concurrent slots, which returns batch results as each worker completes.*
The sentence carries exactly three claims, and this suite pins each as an
observable behaviour rather than trusting the implementation's shape:

**The W law — W slots, concurrently.**  A slot is a *concurrency lane*,
and the pool's width is the campaign record's ``workspace_count``
(feature 232's W, the same number §4.1.1's φ divides by).  The pinned
behaviour: with W slots and W jobs that can only proceed together (a
``threading.Barrier`` of exactly W parties), the batch completes — which
is unprovable unless W workers genuinely ran at once; with more jobs than
slots, the observed concurrency *reaches* W and *never exceeds* it; and
with fewer jobs than W, only that many slots ever run, filling from slot
0 — a slot is capacity, not an obligation.

**The return law — as each completes, not when the batch does.**  A slow
evaluation must not withhold a fast one's answer: the stream yields a
result the moment its slot finishes, which is pinned twice — by order
(the slow job's result arrives last though it was submitted first) and
by liveness (a held-open job's sibling result is consumed *while the
held job is still running*, which no barrier-shaped implementation can
survive).  Every result self-identifies — the ``job`` it answers, the
``slot`` that ran it — because completion order is the machine's timing
and correlation by arrival order would be the barrier rebuilt one layer
up.

**The answer law — every job answered exactly once, failures included.**
A worker that raises is a value on its result, never a death of the
stream: the caller counting results counts attempts (PRD §5: *"every
attempt is logged to the tree with its full artifact"* — feature 240's
"including failures"), and ``BaseException`` is captured as deliberately
as ``Exception``, because an exception escaping a slot would kill its
thread and leave the stream waiting on an answer that never arrives.

Beside the three laws, the suite pins the refusal vocabulary (a
``width`` that is not the count a campaign was planned with, a worker
that cannot be called, a ``jobs`` that is not a batch — each refused on
the *call*, before the batch is even read), the empty batch (no slots,
no error — feature 242's termination is the caller's judgement), and the
lifecycle (no slot thread outlives the stream, exhausted or closed; a
closed stream abandons its pending jobs but lets running ones finish).

The worker throughout is a stand-in, not the evaluation: feature 239's
expansion — resume a workspace, produce one refined signal — is the
callable a deployment passes, and the pool's contract with it is one
call per job.  A test that needed the real evaluator to prove dispatch
would be testing the evaluator; what feature 238 owns is the W, the
concurrency, and the order the answers come back in.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import FrozenInstanceError
from typing import Any

import discovery
import pytest
from discovery import BatchDispatchError, DiscoveryError
from discovery.workers import SLOT_THREAD_PREFIX, WorkerResult, run_batch

#: How long a "slow" job holds its slot in the ordering tests.  Two
#: orders of magnitude above thread-start jitter and two below the
#: suite's patience — enough that a completion-order violation is a
#: wrong design rather than a loaded machine.
SLOW_S = 0.25

#: How long a gated job waits for its release before giving up.  Long
#: enough that a liveness failure is a definitive failure, short enough
#: that a barrier-shaped implementation fails the assertion rather than
#: hanging the suite.
GATE_TIMEOUT_S = 5.0

#: The sleep that keeps every slot demonstrably busy in the reuse and
#: concurrency-cap tests, so slot engagement is a property of the pool
#: rather than of how fast a lambda returns.
BUSY_S = 0.02


def _echo(job: Any) -> Any:
    """The stand-in evaluation: one call, one answer, never fails."""
    return job


def _busy(job: Any) -> Any:
    """A stand-in that holds its slot long enough to be observed busy."""
    time.sleep(BUSY_S)
    return job


def _slot_threads() -> list[str]:
    """The evaluation slots currently alive, by thread name."""
    return [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith(SLOT_THREAD_PREFIX)
    ]


# -- The answer law ----------------------------------------------------------------


def test_every_job_is_answered_exactly_once() -> None:
    # The pool's one invariant, total over outcomes: a batch of seven
    # jobs across three slots answers seven times — no job twice (the
    # duplicate a non-atomic handout would produce), no job never (the
    # lost answer a crashing slot would produce).
    jobs = [f"node-{n}" for n in range(7)]
    results = list(run_batch(_busy, jobs, width=3))
    assert len(results) == 7
    assert Counter(r.job for r in results) == Counter(jobs)
    assert all(r.ok for r in results)
    assert {r.value for r in results} == set(jobs)


def test_a_result_names_the_slot_that_ran_it() -> None:
    # Slot identity is part of the result, because "which slot ran this"
    # is the fact a retry (feature 244) and an audit both want, and the
    # thread that ran it is gone by the time the answer is consumed.
    results = list(run_batch(_busy, list(range(9)), width=3))
    assert {r.slot for r in results} == {0, 1, 2}
    assert all(0 <= r.slot < 3 for r in results)


def test_a_batch_smaller_than_width_fills_slots_from_zero() -> None:
    # W is capacity, not an obligation to occupy: two jobs on an
    # eight-slot pool run on the first two slots and the other six never
    # exist.  A pool that started W threads for N < W jobs would be
    # paying for slots no campaign's work reached.
    results = list(run_batch(_busy, ["a", "b"], width=8))
    assert {r.slot for r in results} == {0, 1}


def test_the_result_echoes_the_job_it_answers() -> None:
    # Correlation is by the echoed job, never by arrival order — the
    # batch is node ids here, exactly the shape §5's loop dispatches,
    # and a result that could not say which ask it answers would force
    # the caller back into submission order.
    batch = ["7f45…root", "aa19…root", "03c7…leaf"]
    results = list(run_batch(_echo, batch, width=3))
    assert sorted(r.job for r in results) == sorted(batch)


def test_a_raising_worker_is_a_value_not_a_stream_death() -> None:
    # The sandbox's discipline at the dispatch layer: a failed run is
    # reported, not raised.  The failing job's result carries the
    # exception itself, an empty value, and answers "not ok" — and the
    # sibling jobs' answers are unaffected.
    def flaky(job: str) -> str:
        if job == "fails":
            raise RuntimeError(f"signal raised: {job}")
        return job

    results = list(run_batch(flaky, ["a", "fails", "c"], width=3))
    assert len(results) == 3
    by_job = {r.job: r for r in results}
    failure = by_job["fails"]
    assert not failure.ok
    assert failure.value is None
    assert isinstance(failure.error, RuntimeError)
    assert "signal raised" in str(failure.error)
    assert by_job["a"].ok and by_job["c"].ok


def test_a_worker_refusal_from_this_member_is_reported_not_raised() -> None:
    # A DiscoveryError out of a worker is still an evaluation failure
    # carried on its result, not a dispatch refusal raised through the
    # stream: BatchDispatchError is reserved for asks the pool could not
    # begin, and a worker that raises mid-batch is emphatically not
    # that.  The seam matters because the expansion (feature 239) will
    # raise this member's own planning vocabulary when a workspace is
    # malformed, and the batch must answer the rest of the batch anyway.
    def refuses(job: int) -> int:
        if job == 1:
            raise DiscoveryError("expansion refused this workspace")
        return job

    results = list(run_batch(refuses, [0, 1, 2], width=3))
    assert len(results) == 3
    assert Counter(r.ok for r in results) == Counter({True: 2, False: 1})


def test_a_base_exception_from_a_worker_is_captured_too() -> None:
    # The per-job catch is BaseException on purpose: an Exception-only
    # catch would let a worker's exit kill its slot's thread and leave
    # the stream blocked on a result that never arrives — a hang, which
    # is a worse failure than any the capture could hide.  Captured, the
    # exit is data, and the invariant (one answer per job) holds for
    # exits as for errors.

    def exits(job: int) -> int:
        if job == 1:
            raise KeyboardInterrupt("a worker was interrupted mid-evaluation")
        return job

    results = list(run_batch(exits, [0, 1, 2, 3], width=2))
    assert len(results) == 4
    by_job = {r.job: r for r in results}
    assert isinstance(by_job[1].error, KeyboardInterrupt)
    assert sum(1 for r in results if r.ok) == 3


def test_the_batch_survives_a_failing_worker() -> None:
    # Six jobs, the fourth fails, the pool is two slots wide: the answer
    # law survives slot reuse — the slot whose job failed takes the next
    # job and the batch still answers all six.
    def flaky(job: int) -> int:
        if job == 3:
            raise ValueError("oom")
        time.sleep(BUSY_S)
        return job

    results = list(run_batch(flaky, list(range(6)), width=2))
    assert len(results) == 6
    assert Counter(r.ok for r in results) == Counter({True: 5, False: 1})


# -- The W law ---------------------------------------------------------------------


def test_w_slots_run_at_once() -> None:
    # The feature's own arithmetic, made behavioural: W jobs that can
    # only proceed as a group of exactly W (a Barrier of W parties)
    # complete — impossible unless the pool really runs W workers
    # concurrently.  A serial or W-1 implementation breaks the barrier,
    # the broken barrier is captured as a failed result, and the
    # all-ok assertion fails naming it.
    width = 4
    barrier = threading.Barrier(width)

    def synchronised(job: int) -> int:
        barrier.wait(timeout=GATE_TIMEOUT_S)
        return job

    results = list(run_batch(synchronised, list(range(width)), width=width))
    assert all(r.ok for r in results), [str(r.error) for r in results]
    assert {r.slot for r in results} == set(range(width))


def test_the_pool_reaches_w_and_never_exceeds_it() -> None:
    # The cap from both sides: with more jobs than slots, observed
    # concurrency must reach W (the slots are real) and never pass it
    # (the campaign authorized exactly W).  A pool that overflowed its
    # width would be running evaluations no campaign paid for; one that
    # never reached it would be a serialization wearing a pool's name.
    width = 2
    lock = threading.Lock()
    active = 0
    high_water = 0

    def tracked(job: int) -> int:
        nonlocal active, high_water
        with lock:
            active += 1
            high_water = max(high_water, active)
        time.sleep(BUSY_S)
        with lock:
            active -= 1
        return job

    results = list(run_batch(tracked, list(range(10)), width=width))
    assert len(results) == 10
    assert high_water == width


def test_slots_are_reused_across_the_batch() -> None:
    # A slot is a lane, not a job: eight jobs on two slots come back
    # answered by exactly two slots, each having run several jobs — the
    # shape §5 means by "concurrent evaluation slots" as opposed to a
    # thread per job.
    results = list(run_batch(_busy, list(range(8)), width=2))
    assert len(results) == 8
    slots = Counter(r.slot for r in results)
    assert set(slots) == {0, 1}
    assert all(count >= 2 for count in slots.values())


def test_two_batches_run_concurrently_and_independently() -> None:
    # The pool is per-call, not a process-wide singleton — the decision
    # behind "no component".  A worker that dispatches its own inner
    # batch must get a working pool with its own slots, and the outer
    # batch must answer around it.  (A process-wide pool with a baked
    # width would deadlock or refuse here.)
    def dispatching(job: int) -> int:
        inner = list(run_batch(_echo, [job * 10, job * 10 + 1], width=2))
        return sum(r.value for r in inner if r.ok)

    results = list(run_batch(dispatching, [0, 1], width=2))
    assert all(r.ok for r in results)
    assert sorted(r.value for r in results) == [1, 21]


# -- The return law ----------------------------------------------------------------


def test_results_arrive_in_completion_order_not_submission_order() -> None:
    # The slow job was submitted first and finishes last; the stream
    # must say so.  A barrier-shaped implementation — materialise, then
    # yield — would pass a "all results present" check and fail exactly
    # this one, which is why the ordering is pinned on the yielded
    # sequence and not on a set.
    def variable(job: int) -> int:
        if job == 0:
            time.sleep(SLOW_S)  # submitted first, finishes last
        return job

    order = [r.job for r in run_batch(variable, [0, 1, 2, 3], width=4)]
    assert order[-1] == 0
    assert order[0] != 0
    assert sorted(order) == [0, 1, 2, 3]


def test_the_stream_does_not_wait_for_the_batch() -> None:
    # Liveness, the strongest form of "as each worker completes": one
    # job is held open on a gate only the test controls, and the held
    # job's sibling answer must be consumable *while the held job is
    # still running*.  A barrier yields nothing until every job is done,
    # so it fails the finished-flag assertion (and only after the gate
    # times out, so the failure is an assertion, not a hang).
    gate = threading.Event()
    held_finished = threading.Event()

    def worker(job: str) -> str:
        if job == "held":
            gate.wait(timeout=GATE_TIMEOUT_S)
            held_finished.set()
        return job

    stream = run_batch(worker, ["held", "free"], width=2)
    first = next(stream)
    assert first.job == "free"  # the fast answer, not the held one
    assert first.ok
    assert not held_finished.is_set()  # and the held job is still running
    gate.set()  # release it, and its answer arrives
    second = next(stream)
    assert second.job == "held"
    assert held_finished.is_set()
    with pytest.raises(StopIteration):
        next(stream)


def test_the_return_is_a_stream_not_a_materialised_list() -> None:
    # The spelling of "returns batch results as each worker completes":
    # an iterator, its own iterator, with results appearing one ``next``
    # at a time — not a list built before the first answer was due.
    stream = run_batch(_echo, [1, 2], width=2)
    assert iter(stream) is stream
    assert hasattr(stream, "__next__")
    assert not isinstance(stream, list)


# -- The refusals ------------------------------------------------------------------


@pytest.mark.parametrize(
    "width",
    [0, -1, -12, True, False, "4", "wide", 2.5, 4.0, None, [4]],
)
def test_a_width_that_is_not_a_count_is_refused(width: Any) -> None:
    # The same predicate the campaign record applies to its
    # workspace_count, restated for the dispatch: True is not a count,
    # "4" is not a count, 0 divides by zero in §4.1.1, and a list is
    # not even a number.  Each refusal names the campaign field the bad
    # value came from, so the operator reads which record to fix.
    with pytest.raises(BatchDispatchError) as raised:
        run_batch(_echo, [1, 2], width=width)
    assert "workspace_count" in str(raised.value)


def test_the_width_has_no_default() -> None:
    # A default width would be this module inventing a campaign: the
    # width a batch runs at is a planning-time fact the record holds,
    # so the argument is required and Python's own refusal is the right
    # one — a TypeError on the missing keyword, not a silent W=1.
    with pytest.raises(TypeError):
        run_batch(_echo, [1, 2])  # type: ignore[call-arg]


def test_a_worker_that_cannot_be_called_is_refused() -> None:
    # The worker is the evaluation; a non-callable one is an ask no
    # slot could begin, refused here rather than surfacing as the same
    # plumbing error on every result of the batch.
    with pytest.raises(BatchDispatchError) as raised:
        run_batch(42, [1], width=2)
    assert "callable" in str(raised.value)


def test_a_bare_string_is_one_ask_without_its_brackets() -> None:
    # "node-9f2a…" iterated is a batch of thirty-something characters,
    # every one of which the pool would faithfully answer exactly once —
    # which is precisely why it must be refused: the pool would dispatch
    # a batch nobody selected.
    with pytest.raises(BatchDispatchError) as raised:
        run_batch(_echo, "node-9f2a", width=2)
    assert "brackets" in str(raised.value)
    with pytest.raises(BatchDispatchError):
        run_batch(_echo, b"node-9f2a", width=2)


def test_a_value_with_nothing_to_iterate_is_not_a_batch() -> None:
    with pytest.raises(BatchDispatchError):
        run_batch(_echo, 7, width=2)


def test_refusals_fire_on_the_call_not_on_first_consumption() -> None:
    # run_batch is a plain function that validates eagerly and returns
    # the generator — the one-shape fix for the generator-function trap
    # where nothing runs until the first next().  A refusal deferred to
    # consumption would have the caller believe a malformed dispatch was
    # accepted; the test proves the batch was never even read, by
    # handing an iterable that records the fact.
    read: list[int] = []

    def jobs() -> Any:
        for job in (1, 2, 3):
            read.append(job)
            yield job

    with pytest.raises(BatchDispatchError):
        run_batch(_echo, jobs(), width=0)
    assert read == []  # the ask was refused whole, before anything was read
    assert _slot_threads() == []  # and no slot was ever started


def test_the_width_refusal_is_the_records_own_predicate() -> None:
    # The dispatch and the record agree on what a W is — pinned across
    # the two spellings so the pool can never accept a width the record
    # would have refused (or refuse one it accepted): the classes differ
    # because the acts differ, but both sit under DiscoveryError and
    # both answer the same bad values the same way.
    for bad in (True, "4", 0, 2.5):
        with pytest.raises(DiscoveryError):
            run_batch(_echo, [1], width=bad)


# -- The empty batch ---------------------------------------------------------------


def test_an_empty_batch_starts_no_slots_and_answers_nothing() -> None:
    # The policy selected nothing (feature 242's termination condition):
    # the pool's answer is an empty stream — not an error, because
    # terminating on an empty selection is the caller's judgement, and
    # not a slot, because there is nothing for one to run.
    assert list(run_batch(_echo, [], width=4)) == []
    assert _slot_threads() == []


# -- The lifecycle -----------------------------------------------------------------


def test_exhaustion_leaves_no_slot_threads_behind() -> None:
    # The stream's finally joins its slots: while the batch has work
    # pending the W slots are alive and named (a deployment's thread
    # dump can find them), and the moment the last answer is consumed
    # none remain.  A pool that leaked its threads would bleed one
    # thread per batch per W into a long-running orchestrator.
    stream = run_batch(_busy, list(range(6)), width=3)
    first = next(stream)
    assert first is not None
    assert len(_slot_threads()) == 3  # the batch is mid-flight
    remaining = list(stream)
    assert len(remaining) == 5
    assert _slot_threads() == []


def test_closing_the_stream_abandons_pending_jobs() -> None:
    # The early-exit contract: close() stops the handout, a running job
    # finishes (threads cannot be killed mid-evaluation — the property
    # feature 244's idempotent retry builds on), and its answer is
    # discarded because the consumer asked for no more.  The third job
    # is the pin: it sits behind a gated second on a one-slot pool, so
    # after the close joins the slot, nothing can ever run it.
    gate = threading.Event()
    ran: list[str] = []

    def worker(job: str) -> str:
        ran.append(job)
        if job == "gated":
            # Short enough that close()'s join of the running slot is a
            # fraction of a second; the gate is what makes "gated" hold
            # the slot while the close happens.
            gate.wait(timeout=0.3)
        return job

    stream = run_batch(worker, ["fast", "gated", "tail"], width=1)
    first = next(stream)
    assert first.job == "fast"
    assert first.ok  # exactly one answer was ever delivered
    stream.close()
    with pytest.raises(StopIteration):
        next(stream)
    gate.set()
    assert "tail" not in ran  # abandoned, never started


def test_a_closed_stream_stays_closed() -> None:
    # Closing is terminal: the generator's contract is that a closed
    # generator answers StopIteration forever after, and the pool adds
    # no second life to it.
    stream = run_batch(_echo, [1, 2], width=2)
    stream.close()
    with pytest.raises(StopIteration):
        next(stream)


# -- The campaign seam (feature 232 → 238) -----------------------------------------


def test_the_width_is_the_campaign_record_s_workspace_count(records, campaign_id):
    # The depends_on, made behavioural: a campaign is planned with W,
    # its record carries W, and the batch the orchestrator dispatches
    # for that campaign runs at exactly that W — the record's field is
    # the pool's width, spelled by the caller that holds the record.
    # (A pool that took its width from anywhere else — an environment
    # variable, a default — would be a campaign nobody planned.)
    record = records.create(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id
    )
    assert record.workspace_count == 4
    results = list(
        run_batch(_busy, list(range(8)), width=record.workspace_count)
    )
    assert len(results) == 8
    assert {r.slot for r in results} == {0, 1, 2, 3}  # exactly the record's W


def test_a_record_whose_w_is_one_dispatches_one_slot(records, campaign_id):
    # The degenerate campaign, and it is legal: W = 1 plans (φ is
    # clipped to the ceiling), and its batch runs on a single slot.
    # The seam must not quietly widen a thin campaign.
    record = records.create(
        discovery.TYPE_D_CAMPAIGN_TYPE, 1, campaign_id=campaign_id
    )
    results = list(
        run_batch(_echo, ["only", "second"], width=record.workspace_count)
    )
    assert {r.slot for r in results} == {0}


# -- The result value --------------------------------------------------------------


def test_the_result_is_frozen_and_reports_its_own_state() -> None:
    # A result is the record of an attempt: mutation would let a
    # consumer edit the outcome of an evaluation the tree is about to
    # log, and ``ok`` is the one predicate a consumer treats as "did
    # this attempt produce anything" — present for both the value case
    # and the error case, shaped like the sandbox's own ``ok``.
    ok = WorkerResult(slot=0, job="a", value="score-vector")
    assert ok.ok and ok.value == "score-vector" and ok.error is None
    failed = WorkerResult(slot=1, job="b", error=RuntimeError("timeout"))
    assert not failed.ok and failed.value is None
    with pytest.raises(FrozenInstanceError):
        ok.slot = 3  # type: ignore[misc]
