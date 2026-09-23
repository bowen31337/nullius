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

**Stdlib only, and import-cheap.**  ``collections.abc``, ``dataclasses``,
``datetime`` and ``typing`` beside the factory's registration protocol; no
numerics, no Polars, no PyArrow, no environment and no clock.  A member
whose import pulled a
numerical stack in would make every factory scan pay for a dependency the replay
path itself may not use — §12's determinism contract prohibits a GPU in the
replay path and §11.2's materialization row keeps inference out of it, and the
cheapest way to keep both is to have nothing here that could.
"""

from __future__ import annotations

from typing import Any

from app.module_loader import register

from .duration import (
    REPLAY_DURATION_ALERT_THRESHOLD,
    REPLAY_DURATION_TARGET,
    ReplayDuration,
    measure_replay,
)
from .errors import (
    ChildGenerationRefused,
    ParquetReadRefused,
    ReplayError,
    ReplayReturnsError,
    ReplayTreeError,
)
from .returns import RESIDENT_READ_POLICY, ReplayReturns, resident_returns
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
    "ChildGenerationRefused",
    "ParquetReadRefused",
    "REPLAY_DURATION_ALERT_THRESHOLD",
    "REPLAY_DURATION_TARGET",
    "RESIDENT_READ_POLICY",
    "ReplayDuration",
    "ReplayEngine",
    "ReplayError",
    "ReplayReturns",
    "ReplayReturnsError",
    "ReplayTransition",
    "ReplayTreeError",
    "build_replay_engine",
    "child_map",
    "measure_replay",
    "recorded_child",
    "replay_component",
    "replay_roots",
    "replay_transition",
    "resident_returns",
    "resolve_tree",
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
