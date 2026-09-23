"""The replay member's error vocabulary — one base class, split by repair.

The base class for every failure of the replay path, and the two subclasses
the transition raises.  One base class so a caller — the dreaming loop, a
nightly runner, an operator script, a later feature in this category (246–255
all depend on feature 245) — can catch every failure of the replay path with a
single ``except``, the discipline :mod:`bootstrap.errors`,
:mod:`artifacts._errors`, :mod:`discovery.errors` and
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
  loop) and replay the tree it wrote.

The two are deliberately *not* one class, because they have one repair each
and the repairs are in different places: a broken tree is repaired at the
store, a handed-in generator is repaired at the caller.  A caller that
re-derived one from the other would be unable to tell an operator *which* knob
to turn, which is the same argument :mod:`policy_runtime.errors` states for
keeping :class:`~policy_runtime.PolicyFilesystemError` and
:class:`~policy_runtime.PolicyImportError` apart.

Both are :class:`ReplayError`, so the one base class catches every way a
replay's transition can fail — the property a dreaming loop that replays a
policy across two hundred stored worlds depends on, where one malformed tree
must be a catchable value rather than an escape that ends the cycle.

:class:`ChildGenerationRefused` is **not** a child of
:class:`ReplayTreeError`, and that is the load-bearing half of the split: a
caller that catches the tree's failures in order to skip a bad world must not
silently skip the refusal that says *the replay path has no generative
transition at all*, because that one is not a fact about the world and the
skip would hide a broken caller from every world in the pool.
"""

from __future__ import annotations

__all__ = [
    "ChildGenerationRefused",
    "ReplayError",
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
