"""The bootstrap member's error vocabulary.

One base class (:class:`BootstrapError`) so a caller — the replay engine,
the dreaming loop, an operator script, a later feature in this category —
can catch every failure of the bootstrap path with a single ``except``.
The subclasses split by *which contract* was violated, not by which line
of code failed, the discipline
:mod:`artifacts._errors` and :mod:`sandbox.errors` state for their own
trees:

* :class:`BootstrapWorldError` — the world contract.  A world that cannot
  be *named* as the thing it claims to be: a world id, axis, cell or
  setting that is empty, misspelled, out of range for the world it is
  asked of, or describes a cell no lattice can reach from the world's
  root.  docs/nullius-tech-architecture.md §10.6.1's provenance rule is
  the same rule seen from the other end — *"An upstream that changes is a
  different world, not an updated one"* — so a world whose recorded
  identity does not describe the world asked for is refused rather than
  silently answered from a neighbouring one.  Raised before any label is
  computed, so a refused ask answers no score at all.

* :class:`BootstrapScoringError` — the *label* contract, and the one
  refusal that is about the truth rather than the address.  The world's
  honest label could not be computed: the fitted design is rank-deficient
  at the cell asked for (a setting whose columns the world's own sample
  does not span), or the held-out split has no variance to measure R²
  against.  This is the refusal that keeps the category's guarantee —
  *"honest labels"* — from degrading into a plausible number: a score
  invented where the arithmetic had no answer would be a ground truth
  that is not ground truth, which is the one failure a bootstrap pool
  cannot absorb, because the whole point of the pool is that its labels
  can be trusted as the reference the financial worlds are calibrated
  against (§10.6, §10.6.1).

* :class:`BootstrapPoolError` — the *pool* contract (feature 188, and
  the store contract feature 185's trial ledger shares).  The replay
  pool could not be authored or read as the thing the caller asked: a
  size outside the 40-50 band §10.6 targets, a ``DATABASE_URL`` the
  store cannot speak or that names no durable database, a world id the
  pool does not hold, or a draw that would put one world into the pool
  under two names.  Each refusal is about the *pool's* integrity rather
  than about any one world — a pool that silently absorbed a short draw
  or a duplicated seed would under-report the very precondition
  (§10.3.1's pool size) the pool exists to satisfy.  The trial ledger
  (:mod:`bootstrap._trial`) refuses with the same class — an object that
  is not a question, a payload a trial row cannot be attributed from, a
  record that says a bootstrap trial charged budget — because its
  refusals are the same *kind* of fact (the ask was never about a world)
  and the caller's repair is the same: re-consider the ask, not the
  world.

The split matters to the two callers this category has.  A *policy* under
replay asks a world for cells and needs :class:`BootstrapWorldError` to be
distinguishable from :class:`BootstrapScoringError`, because the repairs
differ: the first is "ask a cell this world has", the second is "this
world cannot answer any cell of this shape" — and a pool builder
(feature 188) that catches a scoring refusal knows to draw another world
rather than to re-aim the ask.  The pool's own refusals are a third
thing again — "the ask was never about a world" — which is why they sit
beside the other two under the same base rather than being folded into
either.
"""

from __future__ import annotations

__all__ = [
    "BootstrapError",
    "BootstrapPoolError",
    "BootstrapScoringError",
    "BootstrapWorldError",
]


class BootstrapError(Exception):
    """Base class for every failure of the bootstrap world path."""


class BootstrapWorldError(BootstrapError):
    """The world could not be addressed as the thing the caller named.

    A world id that is not a usable identifier, an axis the world does not
    have, a cell outside the world's lattice, a setting of the wrong type
    or outside the values the axis declares, a lattice step that jumps
    past a root, or a node id that does not name a cell this world holds.

    Every message names the world, the axis or the node involved, so an
    operator reading a replay's failure can tell *which* world refused and
    *what about it* — the same "name the subject in the refusal" discipline
    :class:`artifacts.ArtifactNotFoundError` applies to a missing node.
    """


class BootstrapScoringError(BootstrapError):
    """The world's honest label could not be computed for the cell asked.

    The rank-deficient fit and the variance-free holdout split.  Kept
    apart from :class:`BootstrapWorldError` because the cell *was* a legal
    cell of the world — the ask was well-formed and the world reached the
    arithmetic — and it is the arithmetic that had no answer.  A caller
    that conflated the two would go looking for a misspelled axis when the
    real fact is that this world, at this cell, has no label to give.

    Deliberately *not* a silent ``NaN`` or a zero: a bootstrap world's
    whole contribution to the pool is that its labels are exact
    (docs/nullius-tech-architecture.md §10.6 — *"They give perfect labels,
    zero statistical-budget cost, and no dependence on market time"*), and
    a stand-in score would be a false ground truth reaching every policy
    comparison scored against this world.
    """


class BootstrapPoolError(BootstrapError):
    """The replay pool could not be authored or read as the thing asked.

    Feature 188's own refusals, and every one of them is about the pool's
    integrity rather than about any world in it: a size outside the 40-50
    band, a database the store cannot speak or that would not outlive the
    process that authored into it, a world id the pool does not hold, and
    a draw that would seat one world under two names.  Feature 185's
    trial ledger (:mod:`bootstrap._trial`) refuses with this class too —
    an object that is not a question, a payload a trial row cannot be
    attributed from, a hand-built record that says a bootstrap trial
    charged budget — because those refusals are the same kind of fact:
    the ask was never about a world, and the repair is to re-consider
    the ask rather than re-aim or re-draw it.

    Kept as its own class — beside the world and scoring contracts rather
    than under either — because the caller's repair differs from both: a
    world refusal is re-aimed, a scoring refusal is re-drawn, and a pool
    refusal is *re-considered* (the deployment, the size, or the id was
    wrong before any world was reached).  And kept under
    :class:`BootstrapError` so the single ``except`` that catches the
    bootstrap path catches the pool's failures too.
    """
