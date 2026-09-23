"""The replay plugin: the deterministic replay engine over a stored discovery tree.

app_spec.xml, "Replay Engine", feature 245: *System rejects any attempt to
generate a new child during replay, because a stored tree reveals only recorded
children.*  docs/nullius-tech-architecture.md §10 is the engine, and §10.1's
``replay()`` skeleton is the feature in code; the sentence under it is why the
whole category exists — *"Online transition is stochastic (the agent may
generate a different child from the same workspace). Replay transition is
deterministic: it reveals the child already recorded. That asymmetry is the
source of the cost advantage."*

**This package is the Replay Engine category's root.**  Features 246, 247, 248
and 251 all declare ``depends_on=245``, and each of them is a *rule about what a
replay may touch* — never the evaluator, never the sandbox, read the pinned
array rather than Parquet.  Feature 245 is the object those rules are rules
about: the replay's own transition over a stored tree.  It lives in
:mod:`replay.transition`, and everything in this module is the member's
registration and its public surface.

**What a replay is, in one paragraph.**  A completed discovery campaign is a tree
of nodes that were *expanded* — feature 239's ``CONTINUE(v)`` resumed a
workspace, asked the agent for one refined signal, and feature 240 persisted it
as a child.  That act is stochastic and expensive: run it again on the same
workspace and the agent may write a different child.  A replay does not run it
again.  It walks the tree that was *recorded*, reaching each node's child by
reading the edge expansion already wrote — so a replay of one policy over one
tree is a pure function of frozen bytes, and costs a lookup rather than an agent
call.  That is why dreaming is cheap (docs §1, P5: *"The replay engine has read
access to the artifact store and zero access to the evaluator or sandbox. This
is what makes dreaming free"*), and why a replay that generated a child would
collapse the cost model of the entire system.

**The refusal is the feature, and it sits at one seam.**  A module that merely
*documented* "we reveal the recorded child" would guard nothing — the next
driver could call an agent for one node and nothing would stop it.  So the
transition's one verb carries the seam: :meth:`ReplayTransition.transition`
accepts a ``generator`` — the callable shape of the online act — and refuses it
with :class:`~replay.ChildGenerationRefused` **before the tree is read and
before the generator is called**.  One verb, one seam, one place to look; the
ordering is feature 146's, and for the same reason (a refusal that ran the call
first would have spent the thing it was refusing to spend).

**A member never imports another member, so the tree arrives duck-typed.**  The
campaign tree a replay walks is the policy-runtime member's ``CampaignTree``
(``(node_id, parent_id, depth, payload)``, feature 217) — the same node model
the frozen evaluator and the nightly canary address — but this member owns no
copy of it and names no sibling package.  The tree arrives through the app
namespace (``app.modules.policy-runtime``, the seat feature 217 ships) and the
transition validates what it *reads* — the tree's ``nodes``, a node's
``node_id`` and ``parent_id``, the tree's ``node`` — rather than
``isinstance``-ing it, because the module loader imports a member under a
synthetic name and re-executes it, so the tree ``create_app()`` hands out may be
a *second* class object of the same name.  Every failure is translated into this
member's own vocabulary (:mod:`replay.errors`), so a caller's single
``except ReplayError`` catches every way a transition can fail.

**The component is the deployment's, and the transition is the episode's.**  The
``@register`` builder at the foot of this module contributes the member's one
component — ``replay``, the name the spec's ``plugin="replay"`` carries — which
is a **stateless facade**: it holds no tree, no store and no deployment state,
and resolves the campaign a replay walks only when a caller asks for it
(:meth:`~replay.ReplayEngine.tree`), never at composition.  The reason is
mechanical: the tree lives in the policy-runtime member's component, whose
builder reaches the artifact store's seat, whose builder composes the
application again — and since the factory builds *every* registered component on
every ``create_app()``, a builder that resolved the tree would walk that cycle
from inside composition and make ``create_app()`` recurse rather than return.
Resolving at the call site turns the same absence into an answerable
:class:`~replay.ReplayTreeError` instead of a hang, so a deployment with no
committed campaign still *composes* — a replay path with nothing to replay is a
state, not a broken application.

The :class:`~replay.ReplayTransition` itself is *not* a component either: it is
per-replay state over one tree, built by the round that holds it, the same
stance the policy-runtime member takes for its prefix view (223), its answer
surface (224) and its commit record (222).  Later features in this category
register their own components beside this one under ``replay-<suffix>`` names —
the ``artifacts-code-hash-dedup`` precedent — rather than a second ``replay``,
which would put two components of one name in the registry and let the later
import silently win.

**Feature 249 — the committed pick at termination — completes the loop feature
248 stopped short of, and registers nothing.**  app_spec.xml, "Replay
Engine", feature 249: *System requires the committed pick from the policy at
termination, which returns negative infinity when none is emitted.*  It is
docs §10.1's last two lines — ``pick = policy.commit()  # MANDATORY`` and the
miss-arm of ``return score(pick, book, epoch, revealed, rounds)`` — and it
lives in :mod:`replay.pick`: the round loop (248) returns the revealed set
and stops, and this is the terminal read over that return.  The pick is
required from the episode's commit record (feature 222's
:class:`~policy_runtime.EpisodeCommit`, the door the policy's
``question.commit(node_id)`` went through — reached duck-typed, because a
member never imports another member) by performing the termination read
itself (``terminate()``, the one verb the module reads off the record), and
the answer is the pair migration 0109 shapes the ``replay_score`` row
around: the pick absent-able, the score always present.  A policy that
emitted no pick is *scored* :data:`~replay.NON_COMMITTING_SCORE` — the total
order's floor, the same value feature 222 spells in the policy-runtime
member, spelled again here because a member never imports another member and
pinned equal by the wiring suite — and the scorer the caller hands in (the
replay's own arithmetic, curried over the book, the epoch, the rounds and
the revealed set 248's loop returns) is **never called** on the miss: taking
the callable rather than a number is the design point, the same seam feature
222 drew on its side.  The refusals (:class:`~replay.ReplayPickError`, the
eighth sibling) are the *ask* — a non-callable scorer, a carrier with no
termination read, a read that cannot say whether a pick was emitted
(refused, never scored as a miss) — and the two argument checks fire before
the record is touched, so a refused ask terminates nothing.  No component,
no store, no clock: the composed facade gains the verb
(:meth:`~replay.ReplayEngine.pick`) rather than a ``replay-``prefixed
component the spec does not ask for.

**Feature 251 — the campaign-returns read — takes the same stance and registers
nothing.**  app_spec.xml, "Replay Engine", feature 251: *System reads campaign
returns from the pinned resident array rather than from Parquet on each
replay.*  It lives in :mod:`replay.returns`: a replay reads a campaign's
returns by pinning the campaign's ``(campaign_id, horizon)`` axis through a
resident pin arena (feature 175's ``CampaignPins`` — per-replay state that
member deliberately never composed, so it arrives as a duck-typed argument the
way the tree arrives at the transition) and answering the one resident array
the arena holds, for the read's lifetime, released when the replay lets go.
The Parquet spelling is refused at the verb it would arrive through: a
handed-in ``load`` — the callable shape of feature 174's sweep — is refused
with :class:`~replay.ParquetReadRefused` *before the arena is touched and
before the loader is called*, the ordering of feature 245's generator refusal
for its reason (a refusal that read first would have spent the I/O it was
refusing to spend).  §9.3 puts the number the naive reading costs (*"200
worlds × 40 policy versions done naively is ~160 GB per dreaming cycle"*) and
§10.4 the premise of the 50 ms target (*"a replay is pure array arithmetic
over cached Parquet"*); the read is the law that keeps both true.  The
:class:`~replay.ReplayReturns` is per-replay state beside the transition, and
the composed facade gains the verb (:meth:`~replay.ReplayEngine.returns`)
rather than a ``replay-``prefixed component the spec does not ask for.

**Feature 252 — the replay's measured duration — takes the same stance and
registers nothing.**  app_spec.xml, "Replay Engine", feature 252: *System
persists the measured duration of each policy and world replay, which completes
in under 50 milliseconds on a single core.*  It is the *measurement* half of the
cost argument the category is made of — the parent (251) is what makes a replay
cheap, and the two children (253's ``recomputation_suspected`` alert past 200 ms
and 254's latency percentiles) are both consumers of the duration this feature
measures — and it lives in :mod:`replay.duration`: a replay is timed over its
own acts with :func:`time.perf_counter` (monotonic, so a sub-50 ms interval
cannot read negative; the one clock this module touches, never wall-clock
:func:`time.time`), and the :class:`~replay.duration.ReplayDuration` record
carries that measured duration and the two keys of the replay it measured (the
policy version and the world id), deriving from the one number the two readings
the children read — :attr:`~replay.duration.ReplayDuration.within_target` and
:attr:`~replay.duration.ReplayDuration.exceeds_alert_threshold`.  The record
**measures and persists; it never refuses** a slow replay, because its children
require it not to (253 permits a replay to reach 200 ms and only alerts there,
and 254 persists the whole distribution).  The measurement wraps the replay's
own acts and reaches nothing downstream — no evaluator, no sandbox, the very
things 246/247 forbid the replay path from touching — and the record is
per-replay state beside the transition, so the composed facade gains nothing and
there is no ``replay-``prefixed component.  It does not widen ``replay_score``
(feature 255's table, a separate lineage); the record stays this module's own.

**Feature 253 — the ``recomputation_suspected`` alert — is the other child the
parent named, and it registers nothing either.**  app_spec.xml, "Replay
Engine", feature 253: *System emits a ``recomputation_suspected`` alert when a
replay exceeds 200 milliseconds, because the cost model has then broken.*
docs §10.4's third sentence is the whole argument — *"If a replay exceeds
~200 ms, something is recomputing rather than reading, and the cost model of
the architecture has broken"* — and it names a **diagnosis**, not a failure of
the replay's result: a slow replay is still a correct replay.  So it lives in
:mod:`replay.alert`: :func:`~replay.alert.emit_recomputation_suspected` reads
one of 252's measured records, and when the replay passed the point — the flag
:attr:`~replay.duration.ReplayDuration.exceeds_alert_threshold`, which 252
derives from the one measured number and which this feature therefore reads
rather than recomputing, the stance :mod:`replay.metrics` states on its side
(*"not a second place the threshold could live"*) — it emits
:class:`~replay.RecomputationSuspectedError` carrying a
:class:`~replay.alert.RecomputationSuspected` record; when it did not, it
returns ``None`` and writes nothing, the shape :func:`canary.halt_dreaming`
gives §12's own ``if``.  Raising *is* the emission, the workspace's alert
convention (canary's ``determinism_broken``, nulloracle's
``unrecoverable_state``, snapshot's corruption alert), so the alert is
catchable by type and the record rides on the error.  **It does not refuse the
replay** — 252 explicitly permits a replay to reach 200 ms and only alerts
there — and it keeps **no store** and **no component**: 254's table already
persists the very duration the alert is about, the alert's durability is the
caller's logger or monitor, and the member's one ``@register`` contribution
stays the facade above.  Feature 252's and 254's docstrings both name 253 as
the emission they deliberately stopped short of; this is where it lands.

**Feature 254 — replay latency at p50 and p99 — is the writer the parent
predicted, and it registers nothing either.**  app_spec.xml, "Replay
Engine", feature 254: *System persists replay latency at p50 and p99 into
the observability metrics store.*  docs §16 names the metric among the
research metrics (*"replay latency p50/p99"*) and states the store as a
sentence with a scale on it — *"Prometheus + Grafana, or a single Postgres
metrics table ... At this scale the simpler option is defensible"* — and the
workspace's spelling of the simpler option is the one relational store
every member store already addresses by ``DATABASE_URL``.  So feature 252's
prediction (*"There is no observability member in this workspace yet —
feature 254 would be the first to write one"*) lands as :mod:`replay.metrics`:
a population of the parent's :class:`~replay.duration.ReplayDuration`
records is summarised at p50 and p99 (the linear method, restated in pure
Python because a member never imports another member and the replay path
may not grow a numerical stack) and persisted into this member's own table
in that store, created idempotently on connect — the samples as the source
of truth, the two percentiles as the derived view over them, one row per
summarising instant so the table is a history of snapshots.  The population
is read duck-typed (the loader's synthetic-name wrinkle again), the report
is refused — never the replay — when the population is not one or the store
cannot take the write (:class:`~replay.ReplayMetricsError`, the fifth
subclass), and the slow tail is persisted as measured, because 252's law
is the parent of this feature and the alert on the tail is 253's.  No
component: a store addressed by ``DATABASE_URL`` is never composed, the
stance every store in this workspace takes, so the member's one
``@register`` contribution stays the facade above.

**Stdlib only, and import-cheap.**  ``collections.abc``, ``contextlib``,
``dataclasses``, ``datetime``, ``json``, ``math``, ``os``, ``sqlite3``,
``time``, ``typing``, ``urllib.parse`` beside the factory's registration
protocol; no numerics, no Polars, no PyArrow.  A member whose import pulled
a numerical stack in would make every factory scan pay for a dependency the
replay path itself may not use — §12's determinism contract prohibits a GPU
in the replay path and §11.2's materialization row keeps inference out of
it, and the cheapest way to keep both is to have nothing here that could.
The one ambient the member reaches is the one the workspace's stores share
(``DATABASE_URL``, feature 254's metrics table), and the one wall clock it
reads stamps that table's row key — the *walk-time* modules (the
transition, the read, the duration) consult no environment and no clock,
and the only clock a duration is ever measured on remains 252's
:func:`time.perf_counter`.
"""

from __future__ import annotations

from typing import Any

from app.module_loader import register

from .alert import (
    RECOMPUTATION_SUSPECTED,
    RecomputationSuspected,
    emit_recomputation_suspected,
    recomputation_suspected_error,
    suspected_recomputation,
)
from .duration import (
    REPLAY_DURATION_ALERT_THRESHOLD,
    REPLAY_DURATION_TARGET,
    ReplayDuration,
    measure_replay,
)
from .errors import (
    ChildGenerationRefused,
    ParquetReadRefused,
    RecomputationSuspectedError,
    ReplayError,
    ReplayMetricsError,
    ReplayPickError,
    ReplayReturnsError,
    ReplayRoundError,
    ReplayScoreError,
    ReplayTreeError,
)
from .metrics import (
    REPLAY_LATENCY_METHOD,
    REPLAY_LATENCY_QUANTILES,
    REPLAY_LATENCY_TABLE,
    ReplayLatency,
    load_latest_replay_latency,
    load_replay_latency,
    persist_replay_latency,
    replay_latency,
)
from .pick import NON_COMMITTING_SCORE, TerminalPick, committed_pick
from .returns import RESIDENT_READ_POLICY, ReplayReturns, resident_returns
from .rounds import run_replay
from .score import REPLAY_SCORE_TABLE, persist_replay_score
from .transition import (
    ReplayEngine,
    ReplayTransition,
    child_map,
    recorded_child,
    replay_roots,
    replay_transition,
    resolve_tree,
)

__all__ = [
    "COMPONENT_NAME",
    "NON_COMMITTING_SCORE",
    "RECOMPUTATION_SUSPECTED",
    "REPLAY_DURATION_ALERT_THRESHOLD",
    "REPLAY_DURATION_TARGET",
    "REPLAY_LATENCY_METHOD",
    "REPLAY_LATENCY_QUANTILES",
    "REPLAY_LATENCY_TABLE",
    "REPLAY_SCORE_TABLE",
    "RESIDENT_READ_POLICY",
    "ChildGenerationRefused",
    "ParquetReadRefused",
    "RecomputationSuspected",
    "RecomputationSuspectedError",
    "ReplayDuration",
    "ReplayEngine",
    "ReplayError",
    "ReplayLatency",
    "ReplayMetricsError",
    "ReplayPickError",
    "ReplayReturns",
    "ReplayReturnsError",
    "ReplayRoundError",
    "ReplayScoreError",
    "ReplayTransition",
    "ReplayTreeError",
    "TerminalPick",
    "build_replay_engine",
    "child_map",
    "committed_pick",
    "emit_recomputation_suspected",
    "load_latest_replay_latency",
    "load_replay_latency",
    "measure_replay",
    "persist_replay_latency",
    "persist_replay_score",
    "recomputation_suspected_error",
    "recorded_child",
    "replay_component",
    "replay_latency",
    "replay_roots",
    "replay_transition",
    "resident_returns",
    "resolve_tree",
    "run_replay",
    "suspected_recomputation",
]

#: The component name the replay member registers under — the plugin name the
#: spec's features carry (``plugin="replay"``), so the component key, the
#: app-namespace seat (``src/app/modules/replay``) and the spec cannot drift
#: apart.  **One component per member name.**  A later feature in this category
#: that needs one of its own registers under a ``replay-`` prefixed name beside
#: this one, never under this name: registering two components under one name
#: puts both in the registry and lets the later import silently win, the hazard
#: ``app.module_loader`` documents and the ``artifacts-code-hash-dedup``
#: precedent avoids.
COMPONENT_NAME = "replay"


def replay_component(app: Any = None) -> ReplayEngine | Any:
    """Return the composed replay component — feature 245's stateless facade.

    With ``app`` given, the component is read from that application; without
    it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``replay`` component is registered — an absent
    component is a discoverable state, not an exception, exactly as an empty
    workspace is for the factory.

    Deliberately the *composition* accessor and nothing more: it does not
    re-export the transition's verbs, the roots, the child lookup or the tree
    resolution — a caller who has the engine calls
    :meth:`~replay.ReplayEngine.transition`,
    :meth:`~replay.ReplayEngine.over` and
    :meth:`~replay.ReplayEngine.tree` on it — and a second spelling of those
    here would be a second thing to keep in sync.  This answers exactly one
    question: *what is the composed replay component?*
    """
    from app.module_loader import create_app

    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)


@register(COMPONENT_NAME)
def build_replay_engine() -> ReplayEngine:
    """Component builder: the replay path's stateless facade — feature 245.

    Takes no arguments — that is the factory's registration protocol — and
    returns a :class:`~replay.ReplayEngine`, which holds nothing at all.  The
    builder is deliberately *free of I/O and of resolution*: the campaign tree
    a replay walks is resolved by the caller that needs one
    (:func:`~replay.resolve_tree`, reached through
    :meth:`~replay.ReplayEngine.tree`), never here.

    **Why not resolve the tree at build time.**  The tree lives in the
    policy-runtime member's component, whose builder resolves it through the
    artifact store's seat, whose builder composes the application again — so a
    builder that resolved the tree would be walking a cycle *inside*
    ``create_app()``, and since the factory builds every registered component
    on every call, composition would recurse rather than return.  That cycle
    is pre-existing and is why the seat-bound builders in this workspace
    degrade to ``None``; this member declines to widen it, and resolves at the
    call site instead, where a missing campaign is an answerable refusal.

    The consequence is the honest one: a deployment with no committed campaign
    still *composes* — a replay path with nothing to replay is a state, not a
    broken application — while a caller that asks for the deployment's tree
    gets :class:`~replay.ReplayTreeError` naming the absence.
    """
    return ReplayEngine()
