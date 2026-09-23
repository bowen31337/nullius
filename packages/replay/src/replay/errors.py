"""The replay member's error vocabulary — one base class, split by repair.

The base class for every failure of the replay path, and the eight subclasses
the transition, the round loop, the terminal pick, the resident read, the
observability write and the ``recomputation_suspected`` alert raise.  One base
class so a caller — the dreaming loop, a nightly runner, an operator script, a
later feature in this category (246–255 all depend on feature 245) — can catch
every failure of the replay path with a single ``except``, the discipline
:mod:`bootstrap.errors`, :mod:`artifacts._errors`, :mod:`discovery.errors` and
:mod:`policy_runtime.errors` each state for their own member.

The subclasses split by **what the caller must do about it**, which is the
split that matters on this path rather than which line of code failed:

* :class:`ReplayTreeError` — the *stored tree's* contract was broken: a tree
  whose nodes cannot be read, a node that cannot be named, an edge that
  reaches nowhere, a node the tree does not hold, a node recording more than
  one child.  The repair is a different tree, or a repaired store: the replay
  was asked to walk something that is not a walkable stored campaign, and no
  amount of re-running changes that;
* :class:`ChildGenerationRefused` — the replay itself was asked to *generate*
  a child, which is the one act app_spec.xml feature 245 names as refused:
  *"System rejects any attempt to generate a new child during replay, because
  a stored tree reveals only recorded children."*  This is not a fact about
  the tree — a perfectly stored campaign raises it — it is a fact about the
  **call**: a caller handed the replay a generator, and the replay path has no
  generative transition.  The repair is on the caller's side of the seam: run
  the act online (feature 239's ``CONTINUE(v)``, in the discovery member's
  loop) and replay the tree it wrote;
* :class:`ReplayPickError` — the *terminal requirement's* ask was malformed:
  a scorer that is not callable, a carrier that is not an episode's commit
  record (no termination read to perform), a termination read that cannot say
  whether a pick was emitted, a record whose ``terminate()`` raised.  The
  repair is the argument handed to the requirement — and, deliberately, the
  **miss is not here at all**: a policy that emitted no pick is *scored*
  ``-inf``, never refused, which is feature 249's whole point;
* :class:`ReplayReturnsError` — the *resident material's* contract was broken:
  a carrier that cannot pin an axis, an arena whose pin refuses, a hold that
  answers no dense array, a resident array of some other campaign, a released
  read asked to answer, a malformed campaign id or horizon.  The repair is a
  different arena or a repaired store — or, for the released read, a fresh
  read — never a re-run over the same broken residence;
* :class:`ParquetReadRefused` — the replay itself was asked to read campaign
  returns **from Parquet**, which is the one act app_spec.xml feature 251
  names as replaced: *"System reads campaign returns from the pinned resident
  array rather than from Parquet on each replay."*  Like
  :class:`ChildGenerationRefused` this is not a fact about the campaign — a
  perfectly resident axis raises it — it is a fact about the **call**: a
  caller handed the read a loader, and the replay path has no Parquet
  spelling.  The repair is on the caller's side of the seam: pin the axis in
  a resident arena (feature 175) and hand the *arena* to the read;
* :class:`ReplayMetricsError` — the *observability report's* contract was
  broken: a population that is not one (empty, not a population, a carrier
  that is not a measured duration, a duration that is not a finite
  non-negative real), or a metrics store that cannot take the read or the
  write (unconfigured, unsupported scheme, locked, corrupt rows).  The repair
  is a real population or a repaired store — never a re-summarise over a
  population that already measured, which is the naive re-run the feature
  refuses for the same reason 251's read refuses a re-sweep;
* :class:`RecomputationSuspectedError` — **not a broken contract at all, but
  the alert itself**: the replay path was *told* something, and what it was
  told is that a replay took long enough that docs §10.4's cost model has
  broken.  app_spec.xml, "Replay Engine", feature 253: *"System emits a
  ``recomputation_suspected`` alert when a replay exceeds 200 milliseconds,
  because the cost model has then broken."*  The repair is not the replay's —
  a slow replay is a **correct** replay, measured and persisted, never refused
  (feature 252's law, and 254 keeps its tail as measured) — it is the
  *deployment's*: §15's recovery row is *"revert to stored-float artifacts"*,
  so the caller checks the resident read (251) and the walk (245) before the
  next dreaming cycle.  The class is also raised for a carrier that is not a
  measured replay (a bare number, a duration that is not a finite non-negative
  real, a flag that is not a bool, a carrier whose flag disagrees with its own
  duration), which is a broken *ask* — reported as one, never as a cost model
  that broke.

The eight are deliberately *not* two classes, because they have one repair
each and the repairs are in different places: a broken tree is repaired at
the store, a broken residence at the arena or the store, a handed-in
generator or loader at the caller, a broken loop ask or terminal ask at the
caller, a broken report at the population or the
metrics store, and a suspected recomputation at the deployment's replay path.
A caller that re-derived one from the other would be unable to tell an
operator *which* knob to turn, which is the same argument
:mod:`policy_runtime.errors` states for keeping
:class:`~policy_runtime.PolicyFilesystemError` and
:class:`~policy_runtime.PolicyImportError` apart.

All are :class:`ReplayError`, so the one base class catches every way a
replay's transition, round loop, terminal pick, returns read, latency report
and cost-model alert can
fail — the property a dreaming loop that replays a policy across two hundred
stored worlds depends on, where one malformed tree or one unreadable campaign
must be a catchable value rather than an escape that ends the cycle.  The
alert's being in this vocabulary is load-bearing rather than convenient: a
dreaming loop that already catches :class:`ReplayError` around each replay
must not have the one loud thing a broken cost model produces escape it as an
uncaught exception, because that would end the cycle instead of telling the
operator about it.

:class:`ChildGenerationRefused` is **not** a child of
:class:`ReplayTreeError`, :class:`ParquetReadRefused` is **not** a child of
:class:`ReplayReturnsError`, and both non-nestings are the load-bearing half
of the split: a caller that catches the tree's or the residence's failures in
order to skip a bad world must not silently skip the refusal that says *the
replay path has no generative transition at all* or *no Parquet spelling at
all*, because neither is a fact about the world and the skip would hide a
broken caller from every world in the pool.

:class:`ReplayMetricsError` **refuses the report, never the replay.**  A slow
population — one whose tail passes docs §10.4's ~200 ms point — is persisted
as measured, because feature 252's law (*measures and persists; never
refuses*) is the parent of this class's feature and the alert on the tail is
253's, not the store's.  The class refuses only what a report *is*: a
population that is not one, or a store that cannot take it.  A caller that
caught it to skip a bad deployment would be skipping the deployment's only
supervision of the 50 ms target, so the repair the messages name is always
*fix the population or the store*, never *drop the report*.

:class:`RecomputationSuspectedError` **is not a child of
:class:`ReplayMetricsError**, and the non-nesting is the load-bearing half of
its split for the same reason the other two non-nestings are: the report's
class is caught by a caller that wants to skip a bad *summary* — a broken
population, a store that will not take the write — and the alert is not a
summary at all.  A caller that skipped a campaign because its latency report
could not be written would, under a nesting, also be silently skipping the
one emission that says the *cost model of the architecture has broken*: the
two facts have different repairs (fix the store, versus go and look at the
replay path) and the second must reach an operator from every deployment,
configured store or not.  The alert's durability is the caller's logger or
monitor, so it depends on no store and no report — which is exactly why it
cannot be reachable only through one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only; alert.py imports this module
    from .alert import RecomputationSuspected

__all__ = [
    "ChildGenerationRefused",
    "ParquetReadRefused",
    "RecomputationSuspectedError",
    "ReplayError",
    "ReplayMetricsError",
    "ReplayPickError",
    "ReplayReturnsError",
    "ReplayRoundError",
    "ReplayTreeError",
]


class ReplayError(Exception):
    """The base class for every failure of the replay path.

    One ``except`` catches the whole path's vocabulary, the discipline every
    member in this workspace keeps for its own seam.  Raised nowhere itself:
    this is the class a caller catches, and the subclasses below are what a
    caller reads.
    """


class ReplayTreeError(ReplayError):
    """The stored tree a replay was told to walk is not one it can walk.

    app_spec.xml feature 245's *"a stored tree reveals only recorded
    children"* read from the other side: the transition derives each child
    from the tree's own recorded edges, so a tree whose edges cannot be read —
    or whose edges do not land anywhere, or which records more than one child
    for a node — names no deterministic transition at all.  Each of those
    failures is refused here, naming the node the read failed on, rather than
    being silently absorbed; the module docstring for
    :mod:`replay.transition` argues each one.

    The repair is a different tree or a repaired store, never a re-run: the
    replay was handed something that is not a walkable stored campaign, and
    re-running the replay over the same bytes would fail the same way.
    """


class ChildGenerationRefused(ReplayError):
    """The replay was asked to generate a child — the one act feature 245 refuses.

    app_spec.xml feature 245: *"System rejects any attempt to generate a new
    child during replay, because a stored tree reveals only recorded
    children."*  docs/nullius-tech-architecture.md §10.1 states the same law
    as the asymmetry the whole cost argument rests on: *"Online transition is
    stochastic (the agent may generate a different child from the same
    workspace). Replay transition is deterministic: it reveals the child
    already recorded."*

    Raised by :meth:`replay.ReplayTransition.transition` when a caller hands
    it a generator — the callable shape of the online act (feature 239's
    agent seam, which resumes a workspace and asks for a refined signal).  The
    refusal fires **before** the tree is read and before the generator is
    called, for the reason feature 146's inference seam states for its own
    refusal: a child generated inside a replay would already be the drift the
    refusal exists to prevent — the prefix would carry a node no stored tree
    contributed and two replays of one tree would be free to differ — so a
    refusal that generated first and raised afterwards would have spent the
    thing it was refusing to spend.

    The message names §10.1's asymmetry and the repair (run the act online
    where the tree is written, then replay the recorded tree), because the
    caller who reached for a generator is the caller who has to move the act
    rather than retry it.
    """


class ReplayReturnsError(ReplayError):
    """The resident campaign returns a replay was told to read cannot be read.

    app_spec.xml, "Replay Engine", feature 251: *"System reads campaign
    returns from the pinned resident array rather than from Parquet on each
    replay"* — read from the resident side: the replay's campaign-returns
    read pins one ``(campaign, horizon)`` axis through a resident pin arena
    (feature 175's ``CampaignPins``, reached duck-typed because a member
    never imports another member) and answers the array the arena holds.
    Every failure of that side is refused here, naming the campaign and the
    axis it is about: a carrier that cannot pin, an arena whose pin refuses
    (translated, whatever class the arena raised — the arena's vocabulary
    belongs to the artifacts member, and a caller catching *this* member's
    base class must still catch a campaign no replay can read), a hold that
    answers no dense resident array, a resident array naming another
    campaign, a read released and asked to answer, a second release, and a
    malformed campaign id or horizon refused before the arena is touched.

    The repair is a different arena or a repaired store — the replay was
    handed something that is not a readable resident axis — or, for the
    released read, a fresh read over the same arena.  Never a re-run over
    the same broken residence: it would fail the same way, and (for a
    released read) re-opening would load again, which is the naive
    per-replay sweep the feature exists to refuse.
    """


class ReplayRoundError(ReplayError):
    """The round loop's ask is malformed — the loop's one refusal vocabulary.

    app_spec.xml feature 248: *"System loops policy selection until no batch
    is selected or the round cap is reached, which returns the revealed
    set."*  The loop is the outer ``while rounds < K2`` of
    docs/nullius-tech-architecture.md §10.1's ``replay()`` — the part feature
    245's plan cedes ("The loop, the round cap and the 'no batch selected'
    termination are feature 248's") — and it drives feature 245's transition,
    a caller-supplied ``select`` closure and the read-side question.  Its
    three refusals share one repair, and the repair is on the caller's side of
    the call:

    * the **non-callable ``select``** — the loop is handed the callable shape
      of ``policy.select(prefix_view(...))`` (the caller wires the closure over
      the policy and the prefix view; a member never imports another member, so
      the loop cannot name either), and a value that is not callable names no
      policy to call.  The refusal fires **before the tree is opened and before
      the first round runs**, for the reason feature 245's generator refusal
      and feature 251's loader refusal fire first: a loop that opened a
      transition and read a tree and then discovered it had no policy to call
      would have spent the walk it was meant to guard against spending;
    * the **non-positive ``round_cap``** — ``K2`` is a required argument,
      validated a positive integer, with no default and no module constant
      (docs §10.1's ``K2`` is a symbolic bound and the repository forbids an
      absolute target, prd §436).  A ``bool``, a zero, a negative or a
      non-``int`` names no loop: zero or negative would terminate before a
      single round (a silent no-op that reads as a completed replay), and a
      non-``int`` breaks the ``rounds < round_cap`` comparison.  Refused
      before the transition is opened, naming the value;
    * a **carrier with no callable ``probe_batch``** — the loop keeps the
      question's reveal set equal to the transition's revealed set through one
      verb, feature 217's ``probe_batch`` (idempotent, all-or-nothing,
      ascending, returning only the cells newly revealed), and a question that
      fronts the campaign through no such verb cannot be reconciled to the
      walk.  Refused naming what arrived, in this member's vocabulary.

    **Not a subclass of** :class:`ReplayTreeError`, and the non-nesting is the
    load-bearing half of the split, the same argument this module makes for
    :class:`ChildGenerationRefused` and :class:`ParquetReadRefused`: a caller
    that catches the tree's failures in order to skip a bad world must not
    silently skip the refusal that says *the loop was handed no callable
    policy at all* or *a round cap that names no loop*, because neither is a
    fact about the world and the skip would hide a broken caller from every
    world in the pool.  A malformed *tree*, by contrast, still surfaces as
    feature 245's :class:`ReplayTreeError` through the loop — the loop opens
    the transition and lets its refusal propagate, because the tree's
    unfitness is a statement about the tree, repaired at the store, not a
    statement about the loop's arguments.

    The repair is the argument handed to the loop — a callable ``select``, a
    positive ``round_cap``, a question that fronts the campaign — never a
    re-run over the same malformed ask, which would refuse the same way.
    """


class ReplayPickError(ReplayError):
    """The terminal requirement's ask is malformed — the miss is not one.

    app_spec.xml, "Replay Engine", feature 249: *System requires the committed
    pick from the policy at termination, which returns negative infinity when
    none is emitted.*  docs/nullius-tech-architecture.md §10.1 places the act
    — ``pick = policy.commit()  # MANDATORY`` — as the replay's last line
    after feature 248's loop has returned, and the sentence's second clause is
    what this class is *not* about: a policy that emitted no pick is **scored**
    ``-inf`` (:data:`replay.NON_COMMITTING_SCORE`), never refused, because the
    miss is a score the comparison keeps (below every committing policy,
    equal to every other miss — prd §438, docs §598, and feature 222's
    policy-runtime half of the same stance).  What is refused here is the
    *ask*, and the repair is on the caller's side of the call:

    * the **non-callable scorer** — the answer's wiring.  The score of a made
      pick is the replay's own arithmetic (§10.3's ``score(pick, book, epoch,
      revealed, rounds)``), curried by the caller and handed to the
      requirement; a value that cannot be called names no arithmetic, and is
      refused here rather than escaping as a bare :class:`TypeError` from
      inside the call;
    * a **carrier that is not an episode's commit record** — the requirement
      performs the termination read itself (that is what *at termination*
      means: the act, not a value someone else froze), through exactly one
      verb, feature 222's idempotent ``terminate()``.  A carrier with no such
      verb — a frozen termination read included — names no act to take;
    * a **termination read that cannot say** — a read carrying no ``pick`` at
      all is a different fact from ``pick is None`` (the miss), and the two
      have different repairs.  Scoring the first as the second would hand
      broken wiring ``-inf``, and a caller skipping "the non-committing
      policy" would silently skip every record it failed to read — the same
      argument the member's other non-nestings make;
    * a **``terminate()`` that raised** — translated into this vocabulary and
      chained to the record's own refusal, so a caller catching the replay's
      base class still catches an episode whose termination could not be read.

    The two argument checks fire **before the record is touched**, and the
    order is load-bearing: the requirement's one act spends a one-way door
    (feature 222's termination close), and a refusal that had terminated
    first would freeze the episode with no score and no retry — the caller
    could not fix the scorer and ask again, because the door only closes.
    **A refused ask terminates nothing.**

    **Not a subclass of** :class:`ReplayRoundError`, and the non-nesting is
    the load-bearing half of the split, the same argument this module makes
    for :class:`ChildGenerationRefused` and :class:`ParquetReadRefused`: the
    loop's malformed ask and the terminal requirement's malformed ask are
    different repairs (fix the ``select``/``round_cap``/``question``, versus
    fix the ``scorer``/the record), and a caller catching the loop's failures
    must not silently skip the refusal that says the terminal seam was handed
    no scorer — that one is not a fact about the loop and the skip would hide
    a broken caller from every replay the loop completes.

    The repair is the argument handed to :func:`replay.committed_pick` — a
    callable scorer and the episode's commit record — never a re-run over a
    *miss*, which is not a failure at all: re-requiring a terminated episode
    is idempotent, and re-deciding one is the one-way door's business
    (feature 222's), not this member's.
    """


class ParquetReadRefused(ReplayError):
    """The replay was asked to read campaign returns from Parquet — refused.

    app_spec.xml feature 251: *"System reads campaign returns from the pinned
    resident array rather than from Parquet on each replay."*
    docs/nullius-tech-architecture.md §9.3 states the law as an instruction
    with a number on it — *"Load each campaign's signal returns once as a
    single dense ``float32`` array of shape ``(nodes × T)`` and pin it in
    RAM"* — because *"200 worlds × 40 policy versions done naively is ~160 GB
    per dreaming cycle"*, and §10.4 states the premise of its performance
    target the same way: *"A replay is pure array arithmetic over cached
    Parquet."*  A replay that swept Parquet per run would be the bottleneck
    the resident arrays exist to remove, and feature 253's
    ``recomputation_suspected`` alert is the timing shadow of exactly that
    collapse.

    Raised by :func:`replay.resident_returns` (and the composed component's
    spelling of it) when a caller hands the read a ``loader`` — the callable
    shape of the Parquet sweep, feature 174's
    ``load_campaign_returns(store, campaign, horizon=...)`` being its
    spelling.  The refusal fires **before the arena is touched and before
    the loader is called**, for the reason feature 245's refusal fires
    first: a read that swept Parquet first and raised afterwards would have
    spent the I/O it was refusing to spend.

    Not a subclass of :class:`ReplayReturnsError`, for the same reason
    :class:`ChildGenerationRefused` is not a subclass of
    :class:`ReplayTreeError`: a caller catching the residence's failures to
    skip a bad campaign must not silently skip the refusal that says the
    replay path has *no Parquet spelling at all*, because that one is not a
    fact about the campaign and the skip would hide a broken caller from
    every campaign in the pool.

    The message names the law, §9.3's number and the repair (pin the axis in
    a resident arena and hand the arena), because the caller who reached for
    a loader is the caller who has to move the read rather than retry it.
    """


class ReplayMetricsError(ReplayError):
    """The observability report a population was summarised into is not one.

    app_spec.xml, "Replay Engine", feature 254: *"System persists replay
    latency at p50 and p99 into the observability metrics store"* — read from
    the reporting side: a population of feature 252's measured durations is
    summarised into the two percentiles docs §16 names among the research
    metrics (*"replay latency p50/p99"*) and written into the store an
    operator reads them from.  Every failure of that side is refused here:
    a population that is not one (empty, not iterable, a carrier that is not
    a measured duration, a duration that is not a finite non-negative real
    number, a snapshot instant that names no row), and a metrics store that
    cannot take the write or answer the read (unconfigured, an unsupported
    URL scheme, a locked or unwritable database, rows whose samples do not
    read back as the population they claim).

    **Refuses the report, never the replay.**  A slow population — one whose
    tail passes docs §10.4's ~200 ms broken-cost-model point — is persisted
    as measured, because feature 252's law (*measures and persists; never
    refuses a slow replay*) is this class's feature's parent, and the alert
    on the tail is feature 253's ``recomputation_suspected``, not the
    store's.  What is refused is what a report *is*: a figure no population
    measured, or a write that did not land.  A latency that measured but
    never landed is surfaced (chained to the store's own refusal), never
    swallowed — the state the feature exists to rule out, exactly as a cost
    model that resolved but never persisted is feature 59's and a latency
    distribution that measured but never landed is feature 67's.

    The repair is a real population or a repaired store, never a re-run over
    a population that already measured: re-measuring to fix a broken
    *report* would spend the replays again for a figure the caller already
    holds, the same naive re-run feature 251's read refuses on its side.
    """


class RecomputationSuspectedError(ReplayError):
    """The ``recomputation_suspected`` alert — feature 253's emission, by type.

    app_spec.xml, "Replay Engine", feature 253: *"System emits a
    ``recomputation_suspected`` alert when a replay exceeds 200 milliseconds,
    because the cost model has then broken."*  docs/nullius-tech-architecture.md
    §10.4 is the argument, and its third sentence is the whole feature: *"If a
    replay exceeds ~200 ms, something is recomputing rather than reading, and
    the cost model of the architecture has broken."*

    **This is not a failure of the replay — it is the alert about one.**  A
    replay that took 300 ms is a *correct* replay: it walked recorded children,
    it read the resident array, it produced its answer.  Feature 252 states the
    law this class's feature inherits — *measures and persists; never refuses a
    slow replay* — and its sibling (254) persists the slow tail as measured.
    What has failed is the *deployment's* premise: §10.4's target rests on a
    replay being pure array arithmetic over cached Parquet, and a replay that
    recomputed instead of reading means the resident read (feature 251) or the
    recorded-child walk (feature 245) has stopped being what it is.  §15's
    recovery row is *"revert to stored-float artifacts"*, so the repair is an
    operator's — check the read and the walk before the next dreaming cycle —
    and it is never *drop the replay*.

    Raised by :func:`replay.emit_recomputation_suspected` when a measured replay
    passed the broken-cost-model point, carrying the
    :class:`~replay.alert.RecomputationSuspected` record on its ``alert``
    attribute — the shape :class:`~canary.CanaryDeterminismBrokenError`,
    :class:`~nulloracle.UnrecoverableStateError` and ``snapshot``'s
    ``CorruptionError`` take, and for the same reason: raising *is* the
    emission, so a monitor that catches the alert to keep sweeping eight thousand
    replays still has the structured record in hand, and a caller that knows
    nothing about alerts still cannot miss one.

    **Not a subclass of** :class:`ReplayMetricsError`, and not of any other
    subclass here: see this module's docstring for why a caller skipping a bad
    *report* must not silently skip the alert, and why the alert must be
    reachable from a deployment that configured no store at all.  It *is* a
    :class:`ReplayError`, so a dreaming loop's single ``except ReplayError``
    catches it — the one loud thing a broken cost model produces must not escape
    as an uncaught exception and end the cycle in place of telling the operator.

    Also raised for a *broken ask*: a carrier that is not a measured replay (a
    bare number, a duration that is not a finite non-negative real, a flag that
    is not a bool, or a carrier whose flag disagrees with its own duration).
    That is a different fact from the alert — a caller's mistake, not a cost
    model's — and the messages say which, so an operator paged by this class can
    tell the two apart by reading the one they were sent.
    """

    #: The structured record of the alert.  Present on every emission
    #: :func:`replay.emit_recomputation_suspected` raises; ``None`` only on a
    #: hand-built error with no diagnosis behind it, and on the
    #: carrier-is-not-a-replay refusals — those carry no record because no
    #: measurement produced one.
    alert: RecomputationSuspected | None

    def __init__(
        self,
        message: str,
        alert: RecomputationSuspected | None = None,
    ) -> None:
        super().__init__(message)
        self.alert = alert
