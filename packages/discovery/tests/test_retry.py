"""The four laws of the idempotent retry — pinned as behaviour.

app_spec.xml feature 244: *System retries an interrupted evaluation
worker idempotently, so spot-instance reclamation returns no duplicate
ledger debit.*  The sentence carries exactly four claims, and this
suite pins each as an observable behaviour rather than trusting the
implementation's shape:

**The retry law — an interrupted worker is run again.**  §14's table
row states the topology's whole contract — eval workers are
*"Spot-eligible.  Failures retry; ledger debits are idempotent by
``node_id``"* — and the retry half of it is this member's.  A job whose
result carries :class:`~discovery.errors.WorkerInterrupted` is re-run,
and re-run again across rounds while the cloud keeps taking it, until
it answers or the caller's budget is spent — and a budget spent on a
still-interrupted job *stands* interrupted, a value for the tree
(feature 240) and not a reason to keep spending rounds nobody asked
for.

**The identity law — the re-run is the same ask, never a minted one.**
The seam's input is *results*, not jobs: it reads the job off the
interrupted result, so the worker is called with the very value the
first run was called with, and the debit the re-run posts keys on the
same ``node_id`` the first run's did.  That is the whole of
"idempotently" as this feature owns it — §14's other half (the
ledger's idempotent debit) answers it with one row and the prior
sequence.  The one ask that would break the property, two interrupted
results naming one job, is refused: that caller has already
double-dispatched a node, and the retry of both would be the duplicate
debit in person.

**The classification law — only an interruption retries.**  An
evaluation failure is a *completed* attempt: §6.1's step 11 debits it
because *"a failed evaluation still consumed a hypothesis"*, and
feature 240 logs it — re-running it would spend compute to replace an
outcome the tree already holds.  A bare ``KeyboardInterrupt`` is the
operator's halt, not the cloud's.  Neither is retried, and neither is
silently skipped: handing either to the seam is refused, so an attempt
can never fall out of the caller's accounting between the pool's
stream and the retry's.

**The budget law — the retry count is the caller's, and exact.**
``retries`` is required with no default (§14 states no number, so a
default would be this module inventing an interruption policy), held
to a genuine positive integer, and consumed exactly: ``retries=2``
buys at most two re-runs per job, ``len(interruptions)`` on the
outcome is precisely the retries that job spent, and ``attempts`` is
always one more than that.

Beside the four laws, the suite pins the dispatch shape the retry
inherits from feature 238 (rounds run on the campaign's width, an
answered re-run is yielded the moment it lands and never withheld for
a slower sibling, the refusals fire on the call before the caller's
stream is consumed, an empty input answers nothing and starts no
slots), the outcome value's own contract (frozen, one job across
result and interruptions, an interruption is the only thing that may
precede a re-run), and — in the final class, against the real ledger
member — the sentence's own payoff: a worker debited and then
reclaimed, retried, and the trial table holding **one** row.

The worker throughout is a stand-in, not the evaluation: feature 239's
expansion is the callable a deployment passes, and the retry's
contract with it is the pool's — one call per job, the job read off
the interrupted result.  A test that needed the real evaluator to
prove the retry would be testing the evaluator; what feature 244 owns
is which jobs re-run, what they are re-run *as*, and what the ledger
can therefore charge for them.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from discovery import (
    BatchDispatchError,
    DiscoveryError,
    RetriedResult,
    WorkerInterrupted,
    is_interruption,
    retry_interrupted,
)
from discovery.workers import WorkerResult, run_batch

#: How long a held job waits for its release before giving up — the
#: liveness tests' patience.  Long enough that a barrier-shaped retry
#: fails the assertion rather than passing by scheduling luck, short
#: enough never to hang the suite.
GATE_TIMEOUT_S = 5.0

#: The provenance triple a trial charge must carry (feature 87): the
#: frozen evaluator, the sealed snapshot and the cost model, each the
#: sha256 hexdigest shape its owning feature computes.  Three distinct
#: 64-hex literals rather than one repeated, so a seam that mixed the
#: columns up could not pass by symmetry.
PROVENANCE = {
    "evaluator_hash": "a" * 64,
    "snapshot_hash": "b" * 64,
    "cost_model_hash": "c" * 64,
}


def _reclaimed(jobs: list[Any], *, width: int = 1) -> list[WorkerResult]:
    """The interrupted results a batch of reclaimed jobs yields.

    The honest way to produce the retry's input: dispatch the batch
    through the real pool with a worker whose machine is always taken,
    and keep what the stream answered.  The results are therefore the
    pool's own values — slot names and all — not hand-built stand-ins,
    and the seam under test is exercised exactly as its caller holds
    it: on the output of feature 238.
    """
    def always_reclaimed(job: Any) -> Any:
        raise WorkerInterrupted(
            f"spot reclamation mid-evaluation of {job!r}"
        )

    results = list(run_batch(always_reclaimed, jobs, width=width))
    assert all(is_interruption(r) for r in results)
    return results


class _Scripted:
    """A worker whose script is: be reclaimed ``n`` times, then answer.

    Counts *its own* calls per job, because that is the only history a
    worker has — the seam cannot know the run that produced the input
    result, and the tests keep the two honest by construction: the
    input comes from :func:`_reclaimed` (a different worker, always
    reclaimed) and the script starts counting at the retry's first
    re-run.
    """

    def __init__(self, reclaims: dict[Any, int] | None = None) -> None:
        self._reclaims = dict(reclaims or {})
        self.calls: list[Any] = []

    def __call__(self, job: Any) -> Any:
        self.calls.append(job)
        left = self._reclaims.get(job, 0)
        if left > 0:
            self._reclaims[job] = left - 1
            raise WorkerInterrupted(
                f"spot reclamation mid-evaluation of {job!r} "
                f"(reclaims left after this one: {left - 1})"
            )
        return f"scored:{job}"


# -- The retry law ----------------------------------------------------------------


def test_an_interrupted_job_is_run_again() -> None:
    # The feature's own verb, as behaviour: a job the cloud took away is
    # re-run, and the outcome the caller holds afterwards is the re-run's
    # answer — not the interruption, and not a silent second question.
    worker = _Scripted(reclaims={})  # answers on its first re-run
    outcomes = list(
        retry_interrupted(worker, _reclaimed(["node-a"]), retries=1, width=1)
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.ok
    assert outcome.result.value == "scored:node-a"
    assert outcome.job == "node-a"
    assert worker.calls == ["node-a"]  # exactly one re-run


def test_a_job_reclaimed_twice_is_retried_across_rounds() -> None:
    # Reclamation is §14's *scheduled event, not an accident*: the same
    # job can be taken twice in its life — once before the caller
    # observed it, once on the re-run.  The retry spends a round on each
    # reclamation and the job answers on the third run of its life: two
    # interruptions survived, attempts == 3.
    worker = _Scripted(reclaims={"node-a": 1})
    outcomes = list(
        retry_interrupted(worker, _reclaimed(["node-a"]), retries=2, width=1)
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.ok
    assert outcome.attempts == 3
    assert len(outcome.interruptions) == 2
    assert worker.calls == ["node-a", "node-a"]


def test_the_outcome_records_every_attempt_it_survived() -> None:
    # The record feature 240 persists is attempt by attempt: the
    # interruptions tuple is every interrupted attempt that was followed
    # by another run — the observed one first — and the standing result
    # is the last run, so the complete history is
    # interruptions + (result,) and attempts is always len + 1.
    worker = _Scripted(reclaims={"n": 1})
    observed = _reclaimed(["n"])
    outcome = next(retry_interrupted(worker, observed, retries=3, width=1))
    assert outcome.interruptions[0] is observed[0]
    assert [type(i.error) for i in outcome.interruptions] == [
        WorkerInterrupted,
        WorkerInterrupted,
    ]
    assert outcome.attempts == len(outcome.interruptions) + 1 == 3
    assert outcome.ok


def test_an_unspent_budget_is_not_consumed() -> None:
    # The budget is a ceiling, not a target: a job that answers on its
    # first re-run costs one retry and the rounds stop — no make-work
    # re-dispatch of answered jobs, and the worker never hears the job
    # again however many re-runs were authorised.
    worker = _Scripted(reclaims={})  # answers on the first re-run
    outcomes = list(
        retry_interrupted(worker, _reclaimed(["a", "b"]), retries=5, width=2)
    )
    assert len(outcomes) == 2
    assert all(o.ok and o.attempts == 2 for o in outcomes)
    assert sorted(worker.calls) == ["a", "b"]


def test_an_exhausted_budget_stands_interrupted() -> None:
    # The seam never loops forever and never decides for itself when to
    # stop believing: the budget is spent, the last run was itself
    # reclaimed, and the honest outcome is that last interruption —
    # not ok, exhausted, a value for the tree to log.
    worker = _Scripted(reclaims={"n": 99})  # reclaimed every run
    outcomes = list(
        retry_interrupted(worker, _reclaimed(["n"]), retries=2, width=1)
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.exhausted
    assert not outcome.ok
    assert isinstance(outcome.result.error, WorkerInterrupted)
    assert outcome.attempts == 3
    assert len(worker.calls) == 2  # exactly the budget, no more


def test_a_failure_on_the_re_run_is_a_value_not_another_round() -> None:
    # A re-run that *fails* — the evaluation itself, not the machine —
    # is 238's "a failed run is a value": the outcome stands on it, not
    # exhausted, and the retry does not spend another round on it, for
    # the same reason it refuses evaluation failures as input.
    observed = _reclaimed(["n"])
    flaky_calls: list[Any] = []

    def flaky(job: Any) -> Any:
        flaky_calls.append(job)
        raise RuntimeError("evaluation failed on the re-run")

    outcome = next(retry_interrupted(flaky, observed, retries=3, width=1))
    assert not outcome.ok
    assert not outcome.exhausted
    assert isinstance(outcome.result.error, RuntimeError)
    assert flaky_calls == ["n"]  # one re-run; the failure ended it


# -- The identity law -------------------------------------------------------------


def test_the_retry_runs_the_same_job_the_interruption_carried() -> None:
    # "Idempotently" as this feature owns it, pinned by identity: the
    # job handed to the worker IS the job read off the interrupted
    # result — the same object, not a copy, not a re-minted ask — so
    # the re-run's ledger debit keys on the same node_id the first
    # run's did and §14's idempotent debit answers with one row.
    job = object()  # identity-comparable, equality-meaningless
    observed = _reclaimed([job])
    seen: list[Any] = []

    def recording(worker_job: Any) -> Any:
        seen.append(worker_job)
        return "scored"

    outcome = next(retry_interrupted(recording, observed, retries=1, width=1))
    assert len(seen) == 1
    assert seen[0] is job
    assert outcome.job is job


def test_an_outcome_answers_exactly_one_job() -> None:
    # The identity law pinned inside the value: the standing result and
    # every interruption it survived name one job, so a consumer
    # correlating outcomes by job — the pool's own discipline — can
    # never see a retried outcome span two of them.
    worker = _Scripted(reclaims={"a": 1, "b": 1})
    outcomes = list(
        retry_interrupted(worker, _reclaimed(["a", "b"]), retries=2, width=2)
    )
    by_job = {o.job: o for o in outcomes}
    assert set(by_job) == {"a", "b"}
    for job, outcome in by_job.items():
        assert all(i.job == job for i in outcome.interruptions)
        assert outcome.result.job == job


def test_two_interrupted_results_for_one_job_are_refused() -> None:
    # The one ask whose retry IS the duplicate ledger debit: two
    # interrupted results naming one job mean the caller already
    # double-dispatched a single node, and re-running both would post a
    # second charge the ledger appends.  Refused as an ask, before any
    # slot starts — the guard is the feature's own sentence, enforced.
    worker = _Scripted()
    with pytest.raises(BatchDispatchError, match="one job"):
        retry_interrupted(
            worker, _reclaimed(["node", "node"]), retries=1, width=2
        )
    assert worker.calls == []


def test_equal_but_distinct_jobs_are_still_one_node() -> None:
    # Jobs correlate by value, not by identity (the pool echoes what
    # the batch held): two results whose jobs compare equal are the
    # double dispatch above even though no object is shared.
    worker = _Scripted()
    with pytest.raises(BatchDispatchError):
        retry_interrupted(
            worker,
            _reclaimed(["same-id"]) + _reclaimed(["same-id"]),
            retries=1,
            width=1,
        )


# -- The classification law -------------------------------------------------------


def test_is_interruption_is_true_of_exactly_the_marker() -> None:
    # The classifier the seam and its caller share: one class, the
    # worker-of-record's translation of reclamation.  Everything else —
    # a completed run, an evaluation failure, a refusal out of the
    # expansion, an operator's halt — is false, because retrying any of
    # them re-spends or ignores an attempt the tree already holds.
    ok = WorkerResult(slot=0, job="n", value=1)
    failed = WorkerResult(slot=0, job="n", error=RuntimeError("timeout"))
    halted = WorkerResult(slot=0, job="n", error=KeyboardInterrupt("^C"))
    interrupted = _reclaimed(["n"])[0]
    assert not is_interruption(ok)
    assert not is_interruption(failed)
    assert not is_interruption(halted)
    assert is_interruption(interrupted)


def test_a_completed_run_is_refused_not_retried() -> None:
    # A result with no error is an answered job: the tree holds the
    # attempt, and the retry of it would be a re-spend of an evaluation
    # that finished.  Refused loudly — a silent skip would drop an
    # attempt out of the caller's accounting between stream and seam.
    worker = _Scripted()
    with pytest.raises(BatchDispatchError, match="no interruption"):
        retry_interrupted(
            worker,
            [WorkerResult(slot=0, job="done", value="scored")],
            retries=1,
            width=1,
        )
    assert worker.calls == []


def test_an_evaluation_failure_is_refused_not_retried() -> None:
    # The load-bearing exclusion: §6.1's step 11 debits a failed node
    # because "a failed evaluation still consumed a hypothesis", so the
    # attempt is completed, charged and logged — re-running it would
    # spend compute to replace an outcome the tree already holds.  The
    # refusal names the repair (filter with is_interruption), not a
    # re-run.
    worker = _Scripted()
    failed = WorkerResult(slot=0, job="n", error=RuntimeError("oom"))
    with pytest.raises(BatchDispatchError, match="evaluation failure"):
        retry_interrupted(worker, [failed], retries=1, width=1)
    assert worker.calls == []


def test_an_operators_halt_is_not_reclamation() -> None:
    # A bare KeyboardInterrupt is the operator's halt, and a system that
    # retries its operator's stop cannot be stopped.  Reclamation
    # arrives translated into the marker, or not at all.
    worker = _Scripted()
    halted = WorkerResult(
        slot=0, job="n", error=KeyboardInterrupt("operator halt")
    )
    with pytest.raises(BatchDispatchError):
        retry_interrupted(worker, [halted], retries=1, width=1)
    assert worker.calls == []


def test_a_non_result_is_refused() -> None:
    # The seam reads the job it re-runs off the interrupted result
    # itself — that is the identity law — so an input that is not a
    # WorkerResult is an ask with no identity to preserve, refused
    # whether it is the job spelled bare, a string, or an exception.
    worker = _Scripted()
    for bad in ["node-a", 7, WorkerInterrupted("the fact, not a result")]:
        with pytest.raises(BatchDispatchError, match="not a"):
            retry_interrupted(worker, [bad], retries=1, width=1)  # type: ignore[list-item]
    assert worker.calls == []


def test_the_marker_is_part_of_the_member_s_one_except() -> None:
    # The base class's promise holds for the fact as well as the
    # refusals: a caller catching DiscoveryError catches an
    # interruption, so the orchestrator's whole path — planning,
    # dispatch, reclamation — is one except.
    assert issubclass(WorkerInterrupted, DiscoveryError)


# -- The budget law ---------------------------------------------------------------


def test_the_budget_is_required_with_no_default() -> None:
    # §14 states no number — "Failures retry" — so a default would be
    # this module inventing an interruption policy.  The caller states
    # the budget per call, exactly as it states the width.
    worker = _Scripted()
    observed = _reclaimed(["n"])
    with pytest.raises(TypeError, match="retries"):
        retry_interrupted(worker, observed, width=1)  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, "2", None])
def test_the_budget_refuses_non_counts(bad: Any) -> None:
    # A genuine positive integer or nothing: ``True`` is not a budget,
    # zero re-runs is an ask to retry by not retrying, and a fractional
    # or textual count is a number no caller stated.
    worker = _Scripted()
    with pytest.raises(BatchDispatchError, match="retries"):
        retry_interrupted(worker, _reclaimed(["n"]), retries=bad, width=1)


def test_the_budget_is_consumed_exactly() -> None:
    # retries=2 buys at most two re-runs per job, for every job, and a
    # job still interrupted after them stands exhausted — the third
    # re-run nobody authorized never happens.  Job "a" is reclaimed on
    # every run (two re-runs, exhausted); job "b" is reclaimed once on
    # its re-run and answers on the second (attempts == 3: observed,
    # reclaimed, answered).
    worker = _Scripted(reclaims={"a": 99, "b": 1})
    outcomes = {
        o.job: o
        for o in retry_interrupted(
            worker, _reclaimed(["a", "b"]), retries=2, width=2
        )
    }
    assert outcomes["a"].exhausted and outcomes["a"].attempts == 3
    assert outcomes["b"].ok and outcomes["b"].attempts == 3
    assert worker.calls.count("a") == 2
    assert worker.calls.count("b") == 2


# -- The dispatch law -------------------------------------------------------------


def test_a_round_runs_on_the_campaign_s_width() -> None:
    # The re-dispatch is a dispatch: it runs on the campaign record's
    # workspace_count — the W the first dispatch ran at — and a round of
    # W jobs that can only proceed as a group of exactly W (a Barrier
    # of W parties) completes, which is unprovable unless the retry
    # really re-ran them W-at-once.
    width = 3
    barrier = threading.Barrier(width)

    def synchronised(job: str) -> str:
        barrier.wait(timeout=GATE_TIMEOUT_S)
        return job

    outcomes = list(
        retry_interrupted(
            synchronised, _reclaimed(["a", "b", "c"]), retries=1, width=width
        )
    )
    assert len(outcomes) == 3
    assert all(o.ok for o in outcomes), [str(o.result.error) for o in outcomes]
    assert {o.result.slot for o in outcomes} == set(range(width))


def test_a_round_never_exceeds_the_width() -> None:
    # A width a campaign did not authorize is a dispatch no campaign
    # authorized, on the re-run as on the first run: with width=2 and
    # five interrupted jobs, no result names a slot outside the two the
    # round was given.  (Which of the two slots a job lands on is the
    # deque race's — a slot that wakes first may take every instant
    # job — so the ceiling is the honest assertion, not full occupancy;
    # the barrier test above is the one that proves W slots really run
    # at once.)
    worker = _Scripted(reclaims={})
    outcomes = list(
        retry_interrupted(
            worker, _reclaimed(list("abcde")), retries=1, width=2
        )
    )
    assert len(outcomes) == 5
    assert {o.result.slot for o in outcomes} <= {0, 1}


@pytest.mark.parametrize("bad", [0, -1, True, 2.5, "4", None])
def test_the_width_refuses_non_counts(bad: Any) -> None:
    # The pool's own predicate, restated for the re-dispatch: the W a
    # campaign was planned with is a count, and a retry at any other
    # width is a dispatch no campaign authorized.
    worker = _Scripted()
    with pytest.raises(BatchDispatchError, match="width"):
        retry_interrupted(worker, _reclaimed(["n"]), retries=1, width=bad)


def test_a_worker_that_cannot_be_called_is_refused() -> None:
    # The re-run is one call per job on the same callable the batch was
    # dispatched on; a retry onto something that cannot be called is a
    # retry no round could begin.
    with pytest.raises(BatchDispatchError, match="callable"):
        retry_interrupted(
            "not-callable", _reclaimed(["n"]), retries=1, width=1  # type: ignore[arg-type]
        )


def test_the_ask_is_refused_on_the_call_not_at_first_consumption() -> None:
    # run_batch's own shape, inherited: retry_interrupted is a plain
    # function that refuses the ask and returns the stream, so a
    # malformed retry is refused before any slot starts — the refusal
    # below is raised by the call itself, with no next() anywhere.
    worker = _Scripted()
    with pytest.raises(BatchDispatchError):
        retry_interrupted(worker, _reclaimed(["n"]), retries=True, width=1)
    with pytest.raises(BatchDispatchError):
        retry_interrupted(worker, _reclaimed(["n"]), retries=1, width=0)


def test_a_refused_ask_never_consumes_the_caller_s_stream() -> None:
    # The results iterable is the caller's own fact — the pool's answer
    # it carries must survive a refused ask intact — so every refusal
    # fires before the stream is read, and a one-shot generator handed
    # to a refused retry is still fully unread afterwards.
    worker = _Scripted()
    consumed: list[WorkerResult] = []

    def one_shot() -> Any:
        for result in _reclaimed(["n"]):
            consumed.append(result)
            yield result

    with pytest.raises(BatchDispatchError):
        retry_interrupted(worker, one_shot(), retries=0, width=1)
    assert consumed == []


def test_nothing_interrupted_answers_nothing() -> None:
    # Feature 242's termination discipline, inherited: nothing
    # interrupted is nothing to retry, and that judgement is the
    # caller's — an empty stream, no rounds, no slots, no error.
    worker = _Scripted()
    assert list(retry_interrupted(worker, [], retries=3, width=4)) == []
    assert worker.calls == []


def test_an_answered_re_run_is_not_withheld_for_a_slow_sibling() -> None:
    # The pool's liveness law, inherited by the round: a fast re-run's
    # outcome is yielded the moment its slot finishes, while its
    # sibling's re-run is still in flight — a retry that materialised a
    # round before answering (the barrier 238 refuses, rebuilt a layer
    # up) could never pass this.
    release = threading.Event()

    def evaluation(job: str) -> str:
        if job == "held":
            assert release.wait(timeout=GATE_TIMEOUT_S), "never released"
        return job

    stream = retry_interrupted(
        evaluation, _reclaimed(["held", "fast"]), retries=1, width=2
    )
    first = next(stream)
    # Received while the sibling's re-run is still held: the release has
    # not been set, so "held" cannot have finished — the fast answer
    # arrived mid-round, not after it.
    assert first.job == "fast"
    assert first.ok
    assert not release.is_set()
    release.set()
    rest = list(stream)
    assert [o.job for o in rest] == ["held"]
    assert all(o.ok for o in rest)


def test_a_job_answered_in_round_one_is_yielded_before_round_two_exists() -> None:
    # The between-rounds boundary is per-job in effect: a job that
    # answers on its first re-run is handed back before the next round
    # is dispatched, because a re-run cannot be needed before the run
    # it replaces has ended — and one that answered needs no replacing.
    worker = _Scripted(reclaims={"answers-fast": 0, "answers-slow": 2})
    stream = retry_interrupted(
        worker, _reclaimed(["answers-slow", "answers-fast"]), retries=3, width=2
    )
    first = next(stream)
    assert first.job == "answers-fast"
    assert first.attempts == 2
    # At most one re-run of the slow job has even started when the fast
    # outcome is handed back — round two is dispatched only after this
    # generator resumes past the yield, which is a fact about generator
    # suspension, not about thread scheduling (the slow job's own re-run
    # thread may or may not have reached its first line yet, so the
    # honest bound is "fewer than two", not "exactly one").
    assert worker.calls.count("answers-slow") < 2
    second = next(stream)
    assert second.job == "answers-slow"
    assert second.ok and second.attempts == 4


# -- The outcome value ------------------------------------------------------------


def test_the_outcome_is_frozen() -> None:
    # A mutable outcome would let a consumer edit what the tree is
    # about to log; frozen, like every value this member hands a
    # caller, and the suite says so in the one place it is tried.
    observed = _reclaimed(["n"])
    outcome = next(
        retry_interrupted(_Scripted(), observed, retries=1, width=1)
    )
    with pytest.raises(FrozenInstanceError):
        outcome.result = observed[0]  # type: ignore[misc]


def test_the_value_refuses_an_outcome_with_no_interruptions() -> None:
    # A retried outcome earns its name: nothing interrupted means no
    # retry happened, and a value claiming one would be a run the
    # caller never made.  Held in __post_init__ because
    # dataclasses.replace rebuilds instances past a factory's nose.
    answered = WorkerResult(slot=0, job="n", value=1)
    with pytest.raises(BatchDispatchError, match="interruptions"):
        RetriedResult(result=answered, interruptions=())


def test_the_value_refuses_a_completed_attempt_as_an_interruption() -> None:
    # Only an interruption may precede a re-run — the value's own
    # statement of the classification law, so a hand-built outcome
    # cannot smuggle a completed attempt into a retry's history.
    answered = WorkerResult(slot=0, job="n", value=1)
    failed = WorkerResult(slot=0, job="n", error=RuntimeError("oom"))
    with pytest.raises(BatchDispatchError):
        RetriedResult(result=answered, interruptions=(failed,))


def test_the_value_refuses_an_outcome_spanning_two_jobs() -> None:
    # The identity law, pinned inside the value: the standing result
    # and every interruption answer one job, because an outcome
    # spanning two is the duplicate-debit fact this feature refuses to
    # produce — even for a caller that builds the value by hand.
    mine = _reclaimed(["mine"])[0]
    answered = WorkerResult(slot=0, job="other", value=1)
    with pytest.raises(BatchDispatchError, match="one job"):
        RetriedResult(result=answered, interruptions=(mine,))


# -- The payoff, against the real ledger ------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_SRC = REPO_ROOT / "packages" / "ledger" / "src"


def _ledger():
    """The ledger member, imported in-function and by path if need be.

    ``importorskip`` rather than a bare import: a workspace that does
    not carry the sibling should lose these tests and nothing else —
    the same remedy ``test_cross_member.py`` spells for the null-oracle
    member.  The path insert is that file's bootstrap applied to this
    sibling: member suites are not installed into each other's
    environments, and the composition this class pins is the one the
    workspace contract permits — in a test, never in the member.
    """
    import sys

    if str(LEDGER_SRC) not in sys.path:
        sys.path.insert(0, str(LEDGER_SRC))
    return pytest.importorskip(
        "ledger", reason="the ledger member is not in this workspace"
    )


class TestSpotReclamationChargesOnce:
    """§14's row end to end: *Failures retry; ledger debits are
    idempotent by* ``node_id``.

    The worker of record debits its node and is then reclaimed — the
    exact order §14's contract exists for: the row landed, the response
    never made it back, the machine went away.  The retry re-runs the
    job, the re-run's debit keys on the same ``node_id`` (the identity
    law above is what guarantees it), and the ledger's own idempotence
    answers: one row, prior sequence, ``appended=False``.  Neither half
    alone is the sentence's payoff — this class is the two halves
    composed, which is why it drives the real ``TrialLedger`` through
    its public ``debit`` seam rather than a stub.
    """

    def _store(self, ledger, tmp_path):
        return ledger.TrialLedger(f"sqlite:///{tmp_path / 'trial.db'}")

    def test_a_reclaimed_worker_s_retry_debits_the_node_once(
        self, tmp_path
    ) -> None:
        # The headline: debit landed, then reclamation, then retry.  The
        # original run is the worker itself dispatched through the pool —
        # the honest construction, because the narrative needs the FIRST
        # run to be the one that debited and was taken.  The trial table
        # holds one row for the node; both debits answered with the same
        # sequence; only the first appended.
        ledger = _ledger()
        store = self._store(ledger, tmp_path)
        node, campaign = uuid.uuid4(), uuid.uuid4()
        debits: list[tuple[int, bool]] = []

        def evaluation(job: str) -> float:
            record, appended = store.debit(
                str(job),
                str(campaign),
                "ok",
                True,
                epoch_id="epoch-7",
                **PROVENANCE,
            )
            debits.append((record.seq, appended))
            if len(debits) == 1:
                raise WorkerInterrupted(
                    "reclaimed after the debit landed, before the "
                    "answer made it back"
                )
            return 0.42

        interrupted = list(run_batch(evaluation, [str(node)], width=1))
        assert is_interruption(interrupted[0])
        outcomes = list(
            retry_interrupted(evaluation, interrupted, retries=1, width=1)
        )
        assert len(outcomes) == 1 and outcomes[0].ok
        assert outcomes[0].attempts == 2
        assert [seq for seq, _ in debits] == [1, 1]
        assert [appended for _, appended in debits] == [True, False]
        assert store.count() == 1  # no duplicate ledger debit
        assert store.rows()[0].node_id == str(node)

    def test_a_reclamation_before_the_debit_charges_on_the_retry_alone(
        self, tmp_path
    ) -> None:
        # The other order: the machine went away before the charge was
        # posted, so the retry's debit is the first the node ever sees —
        # one row, one append, and the idempotence is never even
        # exercised.  Both orders of the same scheduled event cost one
        # hypothesis, never zero and never two.
        ledger = _ledger()
        store = self._store(ledger, tmp_path)
        node, campaign = uuid.uuid4(), uuid.uuid4()
        runs: list[str] = []

        def evaluation(job: str) -> float:
            runs.append(job)
            if len(runs) == 1:
                raise WorkerInterrupted("reclaimed before the debit")
            store.debit(
                str(job),
                str(campaign),
                "ok",
                True,
                epoch_id="epoch-7",
                **PROVENANCE,
            )
            return 0.5

        interrupted = list(run_batch(evaluation, [str(node)], width=1))
        assert is_interruption(interrupted[0])
        outcomes = list(
            retry_interrupted(evaluation, interrupted, retries=1, width=1)
        )
        assert outcomes[0].ok
        assert len(runs) == 2
        assert store.count() == 1

    def test_a_reclamation_storm_still_charges_the_node_once(
        self, tmp_path
    ) -> None:
        # Exhausted, the property still holds: every run debits before
        # the machine is taken, the ledger answers every post after the
        # first with the prior row, and after four attempts — the
        # original and three retried — the table holds one row.  The
        # budget ends the spending of *compute*; nothing ever spends a
        # second hypothesis.
        ledger = _ledger()
        store = self._store(ledger, tmp_path)
        node, campaign = uuid.uuid4(), uuid.uuid4()
        debits: list[tuple[int, bool]] = []

        def evaluation(job: str) -> float:
            record, appended = store.debit(
                str(job),
                str(campaign),
                "ok",
                True,
                epoch_id="epoch-7",
                **PROVENANCE,
            )
            debits.append((record.seq, appended))
            raise WorkerInterrupted("reclaimed every run")

        interrupted = list(run_batch(evaluation, [str(node)], width=1))
        assert is_interruption(interrupted[0])
        outcomes = list(
            retry_interrupted(evaluation, interrupted, retries=3, width=1)
        )
        assert len(outcomes) == 1 and outcomes[0].exhausted
        assert outcomes[0].attempts == 4
        assert [seq for seq, _ in debits] == [1, 1, 1, 1]
        assert debits[0][1] is True and all(
            not appended for _, appended in debits[1:]
        )
        assert store.count() == 1
