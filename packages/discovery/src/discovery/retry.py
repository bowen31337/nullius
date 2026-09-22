"""The idempotent retry of an interrupted evaluation worker — feature 244.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 244: *System
retries an interrupted evaluation worker idempotently, so spot-instance
reclamation returns no duplicate ledger debit.*  docs/nullius-tech-
architecture.md §14 states the whole contract in one table row — eval
workers are *"Spot-eligible.  Failures retry; ledger debits are
idempotent by* ``node_id``*" — and that row is two halves owned by two
members.  The ledger owns the idempotence: feature 95's
``debit(node_id, …)`` appends only when the node holds no row and
answers a second POST with the *prior* sequence, on one connection,
inside one transaction.  This module owns the retry.  The sentence
this module implements exists because the pair only holds when the
retry is **the same attempt in identity**: a re-run that minted a
fresh node id would post a charge the ledger dutifully appends, and
the reclamation §14 calls *a scheduled event, not an accident* would
quietly cost two hypotheses where the system spent one.  The retry's
whole design serves that one property.

**Where the retry sits, and whose act it is.**  Feature 238's pool
answers every job exactly once, and its docstring names this feature
twice: *"a thread cannot be killed mid-job, so a slot that has taken a
job runs it to completion — an interruption is a fact the **caller**
observes and retries, never a half-run the pool silently tore down"*
and *"feature 244's idempotent retry needs the failure it retries to
arrive as a fact about one job, not as the death of the batch."*  So
the pool is untouched and the retry is its caller: take the results
the stream answered *interrupted*, re-run their jobs, yield one
:class:`RetriedResult` per interrupted job.  The two features compose
rather than merge because they answer different questions — the pool
answers *"what did the batch's W slots produce?"*, this seam answers
*"what happened to the jobs the cloud took away?"* — and a pool that
retried internally would be a pool that answered neither question
honestly: its every-job-once invariant is over *attempts*, and a
retry is a new attempt the tree (feature 240) must see separately.

**What an interruption is, and — just as deliberately — is not.**
:class:`~discovery.errors.WorkerInterrupted` is the marker: the
worker of record translates reclamation into it (the sandbox child
dying of the provider's signal, the host going away), feature 238's
pool captures it on the result like any failure, and
:func:`is_interruption` is true of exactly that class.  Two exclusions
are load-bearing, and both are pinned by the suite:

* an **evaluation failure is not an interruption.**  §6.1's step 11
  debits a failed node because *"a failed evaluation still consumed a
  hypothesis"* — the attempt is completed, charged and logged
  (feature 240's *"including failures"*), and re-running it would
  spend compute to replace an outcome the tree already holds.  A
  result carrying any other error, handed to this seam, is **refused**
  (:class:`~discovery.errors.BatchDispatchError`), not retried: the
  repair is the caller's filter, not the worker's re-run.
* a bare ``KeyboardInterrupt`` is not an interruption either.  That is
  the operator's halt, and a system that retries its operator's stop
  cannot be stopped.  Reclamation arrives translated, or not at all.

**The identity law — the retry re-runs ``result.job``, and cannot name
anything else.**  The seam's input is *results*, not jobs: it reads the
ask off each interrupted result, so a retry is structurally the same
ask the interrupted run carried — the worker is called with the very
value the first run was called with, and the debit the re-run posts
keys on the same ``node_id`` the first run's did.  §14's contract then
answers it: one row, prior sequence, ``appended=False``.  A caller
cannot misuse the seam into a fresh identity because there is no
parameter for one; the one way to make this seam double-charge is to
hand it **two interrupted results naming one job**, which is refused
below for exactly that reason — that caller has already
double-dispatched one node, and the retry of both would be the
duplicate ledger debit this feature exists to prevent, in person.

**Rounds through the pool, at the campaign's width.**  One retry round
is one :func:`~discovery.workers.run_batch` dispatch of the
still-interrupted jobs at the same ``width`` — required, no default,
restated by this module's own predicate for the same reason
:mod:`discovery.workers` restates the campaign's: the act differs
(a re-dispatch is not the dispatch it resumes), so it names its own
refusal, and a width a campaign did not authorize is refused on the
call.  Within a round, the as-each-completes law is inherited
unchanged: a fast re-run's outcome is yielded the moment its slot
finishes, never withheld for a slow sibling.  The boundary *between*
rounds is a barrier and cannot help but be — a re-run cannot start
before the interrupted run it replaces has ended, so a job reclaimed
again waits for its own round to end before its next one begins.  The
barrier is per-job in effect, not per-batch: a job that answered in
round one is yielded before round two exists.

**The budget is the caller's, and there is no default.**  ``retries``
is required — a default would be this module inventing an interruption
policy, exactly as a default ``width`` would be it inventing a
campaign — and validated as a genuine positive integer (``bool``
refused).  It is the number of re-runs this call may make per job: the
caller whose workers run on §14's spot tier states how many
reclamations a campaign tolerates before the job stands.  The seam
never loops forever, and never decides for itself when to stop
believing: when the budget is spent and the last run was itself
interrupted, the outcome **stands interrupted** (``exhausted``), a
value like any other for feature 240 to log and the campaign loop to
act on.

**The outcome is one frozen value.**  :class:`RetriedResult` carries
the standing ``result`` — the re-run that answered, success or
evaluation failure alike (a failure on the re-run is 238's *a failed
run is a value*, not a reason to retry again), or the last
interruption when exhausted — and ``interruptions``, every
interrupted attempt that was followed by another run, so
``len(interruptions)`` is exactly the retries consumed and
``attempts`` is always ``len(interruptions) + 1``.  Validated in
``__post_init__``: every interruption really is one, and the result
and the interruptions answer **one job** — the identity law, pinned
inside the value itself, because ``dataclasses.replace`` and
unpickling both rebuild instances past a constructor's nose.

**The refusals are eager, and they all fire before any slot starts.**
:class:`~discovery.errors.BatchDispatchError` — 238's class, joined
rather than twinned, because the repair is the same *re-consider the
ask* — for a ``worker`` that is not callable, a ``retries`` or
``width`` that is not a genuine positive integer, a value that is not
a :class:`~discovery.workers.WorkerResult` at all, a result that is
not an interruption (a completed run or an evaluation failure), and
two results naming one job.  :func:`retry_interrupted` is a plain
function that refuses the ask and returns the stream, exactly
:func:`~discovery.workers.run_batch`'s shape: a refusal deferred to
first consumption would have a caller believe a malformed retry was
accepted, and the fix for that illusion is spelled before any thread
exists — including before the caller's results iterable is consumed,
so a refused ask never reads the caller's stream.  An empty input
answers an empty stream and starts no slots (feature 242's
termination discipline, inherited): nothing interrupted means nothing
to re-run, and that is not this seam's judgement to overturn.

**No component, and it inherits 238's reason rather than borrowing
it.**  The retry exists for the length of one call: it holds no state
between calls, and its two numbers — the budget and the width — are
per-call facts the caller states, so a builder would have to bake a
retry policy no campaign ever stated.  The member's registered surface
stays feature 232's single store, and the campaign loop reaches this
verb the only way the spec allows: by calling it with the campaign's
own width and its own tolerance.

**Stdlib only, and import-cheap.**  Nothing at module scope but
``typing`` and a dataclass over this member's own values; the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for the retry, and a composed application that never suffers
a reclamation never starts a thread for one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from .errors import BatchDispatchError, WorkerInterrupted
from .workers import WorkerResult, run_batch

__all__ = [
    "RetriedResult",
    "is_interruption",
    "retry_interrupted",
]


# -- Classification ---------------------------------------------------------------


def is_interruption(result: WorkerResult) -> bool:
    """True when one result's failure is an interruption — retryable.

    The classifier this seam and its caller share, so the stream the
    caller filters and the jobs the seam re-runs can never be two
    different sets.  It is true of exactly one shape:
    :attr:`WorkerResult.error` is a
    :class:`~discovery.errors.WorkerInterrupted` — §14's reclamation,
    translated by the worker of record into the marker.

    Everything else is false, and the two falsities that matter are
    deliberate:

    * a **completed run** (``error is None``, an evaluation failure, a
      refusal out of the expansion) — §6.1's step 11 already charged it
      and feature 240 already logs it; it is an attempt the tree holds,
      not a job the cloud took away;
    * a raw ``KeyboardInterrupt`` — the operator's halt, which a seam
      that retried it would be refusing to hear.

    A hand-rolled predicate on message text would drift with every
    worker's phrasing; the class is the contract, and this function is
    its one spelling.
    """
    return isinstance(result.error, WorkerInterrupted)


# -- Validation -------------------------------------------------------------------


def _validated_worker(worker: Any) -> Callable[[Any], Any]:
    """Refuse a worker the re-dispatch cannot call.

    :func:`discovery.workers._validated_worker`'s ask restated for the
    re-dispatch — the same "precedent rather than drift" the width
    predicate already carries (the clip's, the record's, the dispatch's
    and now the retry's spelling of one kind of value), each naming its
    own act while the alternative — importing the sibling module's
    private validator — would couple this module to a name the pool
    never promised.  A non-callable worker fails every round of the
    retry identically, which is the honest place an *evaluation*
    fails and the wrong place for an ask that was never going to run.
    """
    if not callable(worker):
        raise BatchDispatchError(
            f"worker must be callable to be retried as an evaluation "
            f"slot, got {worker!r} ({type(worker).__name__}); the retry "
            "re-runs the interrupted worker — one call per job, on the "
            "same jobs the interrupted attempts carried — and a retry "
            "dispatched onto something that cannot be called is a "
            "retry no round could begin"
        )
    return worker


def _validated_count(value: Any, field: str, act: str) -> int:
    """Refuse a count that is not a genuine positive integer.

    One spelling for the two numbers this seam demands: ``retries`` (the
    budget the caller states) and ``width`` (the campaign's W, the same
    number the pool's own predicate refuses).  ``bool`` is refused as
    loudly as ``"2"`` — ``True`` is not a budget and not a width — and
    ``0`` is refused because a retry of zero re-runs is an ask to retry
    by not retrying, while a width of zero is the pool's own refusal
    restated.  Each message names the field and carries the act's own
    sentence, so the operator reads which number of which call came in
    wrong.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchDispatchError(
            f"{field} must be a positive integer, got {value!r} "
            f"({type(value).__name__}); {act}"
        )
    if value < 1:
        raise BatchDispatchError(
            f"{field} must be at least 1, got {value!r}; {act}"
        )
    return value


def _validated_results(results: Any) -> list[WorkerResult]:
    """Materialise the interrupted results, refusing what is not them.

    The input is iterated **once, here, before any slot starts** — the
    caller's stream is its own fact, and a lazy re-iteration per round
    would be a second reading of a stream the pool already answered.
    Three refusals, each naming the act it refuses:

    * a value that is not a :class:`~discovery.workers.WorkerResult` at
      all — a job, a bare string, an exception — is not a fact about one
      job this seam could read an ask off;
    * a result that is **not an interruption** — a completed run, or an
      evaluation failure — is refused rather than skipped, because a
      silent skip would drop an attempt out of the caller's accounting
      while a silent retry would re-spend a hypothesis §6.1 already
      charged.  The repair is the caller's: filter the stream with
      :func:`is_interruption`, the classifier this seam itself uses;
    * two results naming **one job** — the caller has double-dispatched
      one node, and a retry of both would run the node twice and post
      the second charge the ledger appends: the duplicate ledger debit
      this feature exists to prevent, arriving as the ask itself.
    """
    if isinstance(results, (str, bytes)):
        raise BatchDispatchError(
            f"results must be the pool's interrupted results, got "
            f"{results!r} ({type(results).__name__}); a bare string is "
            "not a batch of results, and iterating it would hand this "
            "seam a character at a time — pass the interrupted "
            "WorkerResults the pool answered"
        )
    try:
        batch = list(results)
    except TypeError as exc:
        raise BatchDispatchError(
            f"results must be the pool's results this seam can iterate, "
            f"got {results!r} ({type(results).__name__}); the retry "
            "re-runs the jobs the interrupted results carry, and a "
            "value with nothing to iterate names no interruptions"
        ) from exc
    seen: list[Any] = []
    for result in batch:
        if not isinstance(result, WorkerResult):
            raise BatchDispatchError(
                f"a retry's input is the pool's results; got {result!r} "
                f"({type(result).__name__}), which is not a "
                f"WorkerResult. The retry reads the job it re-runs off "
                "the interrupted result itself — that is the identity "
                "law that keeps a re-run's ledger debit on the same "
                "node_id — so an input that is not a result is an ask "
                "with no identity to preserve"
            )
        if result.error is None:
            raise BatchDispatchError(
                f"the result for {result.job!r} carries no interruption "
                f"(error is None: the job was answered, by slot "
                f"{result.slot}); a completed run is an attempt the "
                "tree already holds, not a job the cloud took away — "
                "filter the stream with is_interruption() before "
                "retrying, and do not re-spend an evaluation that "
                "finished"
            )
        if not isinstance(result.error, WorkerInterrupted):
            raise BatchDispatchError(
                f"the result for {result.job!r} carries "
                f"{type(result.error).__name__}, which is an evaluation "
                "failure, not an interruption: §6.1's step 11 already "
                "charged the attempt ('a failed evaluation still "
                "consumed a hypothesis') and feature 240 logs it, so "
                "the retry would re-spend a hypothesis the tree "
                "already holds. Only WorkerInterrupted retries — "
                "filter the stream with is_interruption()"
            )
        for job in seen:
            if job == result.job:
                raise BatchDispatchError(
                    f"two interrupted results name one job ({result.job!r}); "
                    "the caller has double-dispatched a single node, and "
                    "retrying both would run the node twice and post the "
                    "second charge the ledger appends — the duplicate "
                    "ledger debit feature 244 exists to prevent, arriving "
                    "as the ask itself. Dispatch a node once per batch, "
                    "or split the retries across calls that never share "
                    "a job"
                )
        seen.append(result.job)
    return batch


# -- The outcome ------------------------------------------------------------------


@dataclass(frozen=True)
class RetriedResult:
    """One job's standing outcome after the retry — and what it cost.

    The atom the retry stream yields.  ``result`` is the standing
    attempt: the re-run that *answered* — a success or an evaluation
    failure alike, because a failure that happens on the re-run is a
    value the tree logs (238's law) and not a reason to spend another
    round — or, when the budget was spent and the last run was itself
    interrupted, the last interruption.  ``interruptions`` is every
    interrupted attempt that was followed by another run, in the order
    they happened, starting with the result the caller observed; so
    ``len(interruptions)`` is exactly the number of retries consumed,
    ``attempts`` is always ``len(interruptions) + 1``, and the complete
    history of the job across the retry is ``interruptions + (result,)``
    — the record feature 240 persists, attempt by attempt.

    Frozen and validated in ``__post_init__``, the discipline
    :class:`~discovery.campaign.CampaignRecord` states: a mutable
    outcome would let a consumer edit what the tree is about to log,
    and ``dataclasses.replace`` and unpickling both rebuild instances
    past a constructor's nose.  The validation pins the identity law
    inside the value itself — the result and every interruption answer
    **one job**, because a retried outcome that spanned two jobs would
    be exactly the duplicate-debit fact this feature refuses to produce.
    """

    #: The standing attempt — the re-run that answered, or the last
    #: interruption when the budget was spent first.
    result: WorkerResult
    #: Every interrupted attempt that was followed by another run,
    #: oldest first — the first element is the result the caller
    #: observed and handed to :func:`retry_interrupted`.
    interruptions: tuple[WorkerResult, ...]

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # normalization below is canonicalization, not mutation of the
        # caller's values, and it is the only write this object takes.
        interruptions = tuple(self.interruptions)
        if not interruptions:
            raise BatchDispatchError(
                "a retried outcome carries the interruptions it "
                "survived; got none, which names a run that was never "
                "retried and is not this value"
            )
        for interrupted in interruptions:
            if not isinstance(interrupted, WorkerResult):
                raise BatchDispatchError(
                    f"a retried outcome's interruptions are the pool's "
                    f"results; got {interrupted!r} "
                    f"({type(interrupted).__name__})"
                )
            if not isinstance(interrupted.error, WorkerInterrupted):
                raise BatchDispatchError(
                    f"the attempt for {interrupted.job!r} recorded as an "
                    f"interruption carries {type(interrupted.error).__name__}"
                    "; only an interrupted attempt may precede a re-run, "
                    "and a value claiming otherwise is not a retry this "
                    "seam produced"
                )
        if not isinstance(self.result, WorkerResult):
            raise BatchDispatchError(
                f"a retried outcome's standing result is the pool's "
                f"result; got {self.result!r} "
                f"({type(self.result).__name__})"
            )
        job = self.result.job
        for interrupted in interruptions:
            if interrupted.job != job:
                raise BatchDispatchError(
                    f"a retried outcome answers one job; the standing "
                    f"result names {job!r} and an interruption names "
                    f"{interrupted.job!r}. The identity law — the retry "
                    "re-runs the interrupted attempt's own ask, so "
                    "every run of the job debits one node_id — is what "
                    "keeps §14's 'no duplicate ledger debit' true, and "
                    "an outcome spanning two jobs is the duplicate it "
                    "exists to prevent"
                )
        object.__setattr__(self, "interruptions", interruptions)

    @property
    def job(self) -> Any:
        """The ask this outcome answers — the standing attempt's job.

        Echoed from ``result`` rather than held as a field, so the two
        cannot drift: the outcome's job *is* the job the re-run that
        answered it carried, and the validation above has already held
        every interruption to the same one.
        """
        return self.result.job

    @property
    def ok(self) -> bool:
        """True when the standing attempt answered rather than raised.

        The one state a consumer treats as a usable evaluation — the
        same shape :attr:`WorkerResult.ok` gives, and for the same
        reason: the interesting split is *did this attempt produce
        anything*, not *did the retry survive*, which surviving an
        interruption never guarantees.
        """
        return self.result.ok

    @property
    def exhausted(self) -> bool:
        """True when the budget was spent and the job still stands interrupted.

        The standing result is itself an interruption: the caller
        stated ``retries`` re-runs, every one of them was reclaimed,
        and the honest answer is the last interruption — a value for
        feature 240 to log and the campaign loop to act on, not a
        reason for this seam to keep spending rounds it was not given.
        """
        return is_interruption(self.result)

    @property
    def attempts(self) -> int:
        """How many runs this job has had: the original, plus every re-run.

        Always ``len(interruptions) + 1`` — every interrupted attempt
        was followed by another run (that is what makes it an
        interruption *retried*), and the standing result is the last
        run, whatever it ended in.
        """
        return len(self.interruptions) + 1


# -- The retry itself -------------------------------------------------------------


def _retry(
    worker: Callable[[Any], Any],
    batch: list[WorkerResult],
    retries: int,
    width: int,
) -> Iterator[RetriedResult]:
    """The stream itself: rounds of the pool, one outcome per job.

    Separated from :func:`retry_interrupted` so the *ask* can be
    refused eagerly while the *stream* stays lazy — the same split
    :func:`discovery.workers.run_batch` makes for the same reason.

    A round is one :func:`~discovery.workers.run_batch` dispatch of the
    still-interrupted jobs, and the round's stream is consumed
    *as each worker completes*: a job whose re-run answered is yielded
    the moment its slot finishes, while its reclaimed sibling's re-run
    is still in flight — the liveness law inherited from the pool.  A
    job interrupted *again* joins the next round, which begins only
    when this round's stream ends: the between-rounds boundary is the
    retry's own nature, since a re-run cannot start before the run it
    replaces has ended.

    The per-job record is ``[job, [every interrupted run so far]]`` —
    matched by job equality, which the input validation has already
    held to one record per job.  When a re-run answers, the record's
    list is exactly the interruptions it survived and the re-run is
    the standing result; when the budget ends with jobs still
    interrupted, each such job's *last* run stands as its result and
    the rest as the interruptions it survived.
    """
    pending: list[list[Any]] = [
        [result.job, [result]] for result in batch
    ]
    for _ in range(retries):
        if not pending:
            return
        still_pending: list[list[Any]] = []
        round_stream = run_batch(
            worker, [record[0] for record in pending], width=width
        )
        for result in round_stream:
            record = _record_for(pending, result)
            if is_interruption(result):
                # Reclaimed again: this run joins the interruptions the
                # next round exists to answer.  It is appended to the
                # record's list — every run so far, all interrupted —
                # and the record stays pending.
                record[1].append(result)
                still_pending.append(record)
            else:
                # Answered — success or evaluation failure alike: the
                # failure is a value for the tree, not a reason to
                # spend another round.  Yielded the moment it lands,
                # never withheld for a slower sibling's re-run.
                yield RetriedResult(
                    result=result, interruptions=tuple(record[1])
                )
        pending = still_pending
    # The budget is spent.  Each job still interrupted stands on its
    # last run: that run is the outcome, the ones before it are the
    # interruptions it survived — attempts == len(interruptions) + 1
    # still, because the standing result is a run this call made.
    for job_history in pending:
        yield RetriedResult(
            result=job_history[1][-1],
            interruptions=tuple(job_history[1][:-1]),
        )


def _record_for(
    pending: list[list[Any]], result: WorkerResult
) -> list[Any]:
    """The pending record one round-result answers, by its job.

    Linear by equality rather than a dict: the pool's jobs are the
    caller's own values and carry no promise of hashability, and the
    input validation has already refused two results naming one job,
    so the first record whose job equals the result's is the only one
    it can be.  A miss is impossible by construction — every job in
    the round's batch came from a record — and the assertion below
    states that as a check rather than leaving it as folklore, because
    a silent miss would drop a job out of the retry with no answer at
    all, which is the one outcome this seam must never produce.
    """
    for record in pending:
        if record[0] == result.job:
            return record
    raise AssertionError(  # pragma: no cover - unreachable by construction
        f"the round answered a job no record holds ({result.job!r}); "
        "every job dispatched this round came from one"
    )


def retry_interrupted(
    worker: Callable[[Any], Any],
    results: Iterable[WorkerResult],
    *,
    retries: Any,
    width: Any,
) -> Iterator[RetriedResult]:
    """Retry interrupted evaluation workers idempotently — feature 244's verb.

    *System retries an interrupted evaluation worker idempotently, so
    spot-instance reclamation returns no duplicate ledger debit*, as one
    call: ``worker`` is the evaluation (the same callable the batch was
    dispatched on — feature 239's expansion, a deployment's evaluator
    driver), ``results`` is the pool's interrupted results — the jobs
    §14's reclamation took away — ``retries`` is the budget the caller
    states for how many re-runs each job may cost, and ``width`` is the
    campaign record's ``workspace_count``, the W the first dispatch ran
    at and this one re-runs at.

    Returns an iterator over :class:`RetriedResult`, one per
    interrupted job, **in completion order within each round**: a
    re-run's outcome is yielded the moment its slot finishes, and a
    job reclaimed again waits for the next round, which cannot start
    before the run it replaces has ended.  The caller that needs a
    deterministic order sorts by ``job`` — the pool's own discipline,
    inherited rather than re-smoothed.

    **The idempotence is structural**: the job each re-run carries is
    read off the interrupted result itself, so the re-run is the same
    ask the first run was, the debit it posts keys on the same
    ``node_id``, and §14's contract — *"ledger debits are idempotent by
    ``node_id``"* — answers the retry with the prior sequence instead
    of a second charge.  The one ask that would break the property,
    two interrupted results naming one job, is refused below.

    Refuses :class:`~discovery.errors.BatchDispatchError` — on the
    call itself, before the results iterable is consumed and before
    any slot starts — for a worker that is not callable, a ``retries``
    or ``width`` that is not a genuine positive integer, a value that
    is not a :class:`~discovery.workers.WorkerResult`, a result that
    is not an interruption (a completed run or an evaluation failure
    the tree already holds), and two results naming one job.  An empty
    input yields nothing and starts no slots: nothing interrupted is
    nothing to retry, and that judgement is the caller's.
    """
    # Worker first, then the two counts, then the results — the first
    # three are facts about the *ask*, refused without reading the
    # caller's stream, so a malformed retry never consumes the results
    # iterable it was handed (the stream is the caller's own fact, and
    # the pool's answer it carries must survive a refused ask intact).
    _validated_worker(worker)
    _validated_count(
        retries,
        "retries",
        "the budget is the caller's statement of how many re-runs a "
        "job may cost — §14 gives no number and this module invents "
        "none, so a retries that is not a count is a budget no caller "
        "stated",
    )
    _validated_count(
        width,
        "width",
        "the re-dispatch runs on the campaign record's workspace_count "
        "— the W the first dispatch ran at — so a width that is not "
        "that count is a dispatch no campaign authorized",
    )
    batch = _validated_results(results)
    if not batch:
        # Nothing was interrupted: the caller's stream answered, and
        # this seam's answer to nothing to retry is nothing — no
        # slots, no rounds, an empty stream (feature 242's termination
        # discipline, inherited: the judgement is the caller's).
        return iter(())
    return _retry(worker, batch, retries, width)
