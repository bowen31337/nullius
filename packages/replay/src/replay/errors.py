"""The replay member's error vocabulary — one base class, split by repair.

The base class for every failure of the replay path, and the five subclasses
the transition, the resident read and the observability write raise.  One
base class so a caller — the dreaming loop, a nightly runner, an operator
script, a later feature in this category (246–255 all depend on feature 245)
— can catch every failure of the replay path with a single ``except``, the
discipline :mod:`bootstrap.errors`, :mod:`artifacts._errors`,
:mod:`discovery.errors` and :mod:`policy_runtime.errors` each state for
their own member.

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
  refuses for the same reason 251's read refuses a re-sweep.

The five are deliberately *not* two classes, because they have one repair
each and the repairs are in different places: a broken tree is repaired at
the store, a broken residence at the arena or the store, a handed-in
generator or loader at the caller, a broken report at the population or the
metrics store.  A caller that re-derived one from the other would be unable
to tell an operator *which* knob to turn, which is the same argument
:mod:`policy_runtime.errors` states for keeping
:class:`~policy_runtime.PolicyFilesystemError` and
:class:`~policy_runtime.PolicyImportError` apart.

All are :class:`ReplayError`, so the one base class catches every way a
replay's transition, returns read and latency report can fail — the property
a dreaming loop that replays a policy across two hundred stored worlds
depends on, where one malformed tree or one unreadable campaign must be a
catchable value rather than an escape that ends the cycle.

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
"""

from __future__ import annotations

__all__ = [
    "ChildGenerationRefused",
    "ParquetReadRefused",
    "ReplayError",
    "ReplayMetricsError",
    "ReplayReturnsError",
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
