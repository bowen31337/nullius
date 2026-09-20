"""The nightly canary replay — feature 142's verb.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 142: *System
replays the canary pair nightly, which returns a score compared against a
recorded constant.*  docs/nullius-tech-architecture.md §12 closes its
determinism table with the nightly canary — *"replay a frozen policy*
``π_canary`` *over a frozen tree* ``T_canary`` *and assert the score matches a
recorded constant to* ``1e-12``" — and line 677 spells the same test as code::

    if abs(score - CANARY_EXPECTED) > 1e-12:
        halt_dreaming()
        alert("replay determinism broken — pool untrustworthy")

This module is the ``score`` in that snippet: it takes the frozen pair feature
141 persisted and runs the policy over the tree, once, to a single float — the
nightly replay's score — and hands that float back to the caller, which is the
caller that owns the comparison (§12's ``abs(score - CANARY_EXPECTED) > 1e-12``,
feature 143) and the recording (the store's ``recorded_score``).

Three decisions shape this module, and each is a reading of one word in the
feature: *replays*.

**The replay is a pure function of the frozen pair, and reads nothing else.**
The score is ``policy(tree)`` and nothing more — no environment, no wall clock,
no database, no seed table.  A replay that read anything outside the pair would
be a different score every night, and the nightly canary's whole power is that
the only thing allowed to change between the night the constant was recorded and
the night it is checked is the machine — which is exactly what §12's table pins
away.  So :func:`replay_pair` takes a :class:`~canary.CanaryReferencePair` and
returns a :class:`CanaryReplayResult`, and a caller that hands it the pair it
froze gets back the score that pair replays to, however the pair arrived.  This
is the same discipline :mod:`canary._reference` states for the frozen bytes: the
replay is a pure function of the thing it replays, so a recorded pair and a
replayed one are the same function applied to the same argument.

**The score is computed, not asserted, and the verdict is left to the caller.**
Feature 142's clause is "returns a score compared against a recorded constant" —
the module computes the score and *carries* the recorded constant and the
tolerance so the comparison is one expression, but it does not *decide* the
comparison's consequence.  :class:`CanaryReplayResult` reports ``score``,
``recorded_score``, ``deviation`` and ``within_tolerance`` — the four terms of
§12's ``abs(score - CANARY_EXPECTED) > 1e-12`` — and leaves the halt-dreaming to
feature 143, which owns it.  A replay that also halted would be a canary that
decided its own alert, the same coupling the store refuses when it leaves
``recorded_score`` ``Nullable``: this feature *replays and measures*, the next
one *decides and alerts*, and a module that did both would bury the ``1e-12``
threshold where no operator could audit it.  The result is a value, not a
verdict, so a nightly report can record the deviation for every pair it checked
rather than stopping at the first one that moved.

**The tree is replayed in a stable order, and the score is a plain float.**  The
tree is its nodes in a stable order — :func:`replay_pair` walks the nodes sorted
by ``node_id``, the same rendering :func:`canary.tree_hash` hashes over, so the
walk the score is computed from is the walk the tree's identity is the identity
of.  A node's contribution is read from its canonical payload, never from a raw
walk, so the score is a function of the frozen bytes rather than of whichever
order a dict happened to iterate in.  The score itself is a Python ``float`` —
the same kind of value the store's ``recorded_score`` ``REAL`` column holds and
§12's ``1e-12`` compares — not a wrapped or rounded thing: a replay that rounded
its own score before returning it would be editing the number the comparison is
about, and the comparison is the one thing in the system that must never be
edited.

What this module deliberately does **not** do is resolve, persist, or alert.  It
does not resolve a store or a pair: the pair is handed in, already frozen and
already read back — the store owns the reading (feature 141's verb) and this
module only replays what it is given, so a freshly-read pair and a pair built by
hand replay through the same code.  It does not persist the score: writing the
constant back to ``recorded_score`` is the caller's, on the night the constant is
first recorded, and feature 144's void marker is the feature after that.  It does
not alert or halt: that is feature 143's ``1e-12`` and its ``determinism_broken``
alert, and the ``1e-12`` must sit in exactly one place in the code so an operator
auditing "why did dreaming halt" finds it once.  A replay that also wrote or also
halted would be the threshold nobody could audit.

**Stdlib only, and import-cheap.**  ``json`` and a dataclass; no polars, no
pyarrow, no lake, no environment and no numerics, so importing this member on
every factory scan (including the replay path §1 keeps away from anything that
could perturb it) still costs composition nothing.  The score is a plain sum
over the tree's nodes — the canary is "the cheapest high-value test in the
system" (§12), and a nightly replay that pulled a numerical stack in to score a
frozen policy would be paying for a computation the frozen bytes already made
cheap.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._errors import CanaryError
from ._reference import CanaryReferencePair

__all__ = [
    "DEFAULT_TOLERANCE",
    "CanaryReplay",
    "CanaryReplayResult",
    "CanaryReplayScoreError",
    "replay_pair",
]

#: The tolerance the nightly canary compares its score against the recorded
#: constant to — §12's ``1e-12`` and line 677's ``abs(score - CANARY_EXPECTED)
#: > 1e-12``.  A constant, not a knob: widening it is "never the fix" (§12, the
#: determinism-break row — "Widening the canary tolerance is never the fix"),
#: because a tolerance that forgives the divergence is a canary that has stopped
#: catching it.  Kept here as the one spelling so feature 143's halt and this
#: module's ``within_tolerance`` read the same threshold, and an operator
#: auditing why dreaming halted finds the ``1e-12`` in exactly one place.
DEFAULT_TOLERANCE = 1e-12


def _score_policy(policy: dict, tree_nodes: list[dict]) -> float:
    """The policy's score over the tree's nodes, in a stable order.

    The whole of the replay's computation, stated once so the score is one
    function of the frozen bytes: each node contributes the numeric value of its
    ``"score"`` payload key (defaulting to ``0.0`` when a node carries no score —
    a structural node, not a scored leaf), weighted by its ``"weight"`` (a leaf's
    own weight, defaulting to ``1.0``), and the contributions are summed in
    ``node_id`` order.  Sorted order rather than insertion order: the tree is its
    nodes as a set (that is what :func:`canary.tree_hash` hashes), and a score
    that depended on the order a walk happened to visit them would be a different
    score on a machine whose dict iteration differed — the very thing the nightly
    canary exists to be invariant to.

    A node whose ``"score"`` is not a real number is refused by name: a score the
    replay cannot place on the number line is not a score the ``1e-12``
    comparison could reach, and reporting it as ``0.0`` would hide a frozen tree
    that had drifted into something the canary could no longer measure.
    """
    total = 0.0
    for node in sorted(tree_nodes, key=lambda node: node.get("node_id", "")):
        raw_score = node.get("score", 0.0)
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise CanaryReplayScoreError(
                f"canary tree node {node.get('node_id', '<unknown>')!r} carries a "
                f"score of {raw_score!r}, not a real number: the nightly replay "
                "scores the frozen tree to a single float the recorded constant "
                "is compared to, and a score that is not a number is not a score "
                "the 1e-12 comparison could reach"
            )
        weight = node.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise CanaryReplayScoreError(
                f"canary tree node {node.get('node_id', '<unknown>')!r} carries a "
                f"weight of {weight!r}, not a real number: the nightly replay "
                "weights each node's contribution, and a weight that is not a "
                "number is not a contribution the score could sum"
            )
        total += float(raw_score) * float(weight)
    return total


@dataclass(frozen=True)
class CanaryReplayResult:
    """The nightly replay's outcome — the score, and the comparison it feeds.

    Feature 142's "a score compared against a recorded constant", as a value:
    the replayed :attr:`score`, the :attr:`recorded_score` it is compared against
    (``None`` for a pair not yet replayed — the same ``Nullable`` the store keeps,
    so "not yet replayed" stays distinguishable from "replayed to zero"), the
    :attr:`deviation` between them, and whether that deviation is
    :attr:`within_tolerance` of §12's ``1e-12``.  Frozen and hashable, so a
    nightly report can file one result per pair and compare them across nights.

    The four fields are exactly the four terms of §12's ``abs(score -
    CANARY_EXPECTED) > 1e-12`` — the score, the expected constant, the absolute
    difference, and the boolean the ``>`` produces — carried rather than decided,
    because the decision (halt dreaming, emit the ``determinism_broken`` alert) is
    feature 143's, and a report over several pairs wants every deviation recorded,
    not the first one that moved stopping the rest.  :attr:`within_tolerance` is
    the honest reading of the comparison — "the deviation is at most the
    tolerance" — and is ``True`` for a pair with no recorded score yet, where
    there is nothing to deviate from and so nothing to break.
    """

    #: The score the frozen pair replays to — ``policy(tree)``.
    score: float
    #: The recorded constant the score is compared against.  ``None`` for a pair
    #: not yet replayed — the store's ``recorded_score`` is ``Nullable`` for the
    #: same reason, so a freshly-frozen pair is "not yet replayed", not "zero".
    recorded_score: float | None
    #: ``abs(score - recorded_score)`` — ``None`` when there is nothing to
    #: compare against yet.  The deviation the ``1e-12`` is applied to.
    deviation: float | None
    #: Whether the deviation is within §12's ``1e-12`` — the comparison's
    #: boolean, left undecided as to consequence.  ``True`` when no recorded
    #: score exists yet, where there is nothing to deviate from.
    within_tolerance: bool
    #: The tolerance the comparison used — §12's ``1e-12``.  Stated on the
    #: result so a report can show which threshold a ``within_tolerance`` was
    #: measured against, rather than a reader having to find it in the code.
    tolerance: float

    def __post_init__(self) -> None:
        # A result is a statement about a score some path actually computed, so
        # every field is checked against the others before the value exists.
        # The alternative — trusting the constructor — is a record that can say
        # "within tolerance" while carrying a deviation past the tolerance,
        # which is precisely the shape of a report nobody can act on: §12's
        # whole point is that non-determinism "does not announce itself", and a
        # self-contradicting result would announce the wrong thing.
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise CanaryReplayScoreError(
                f"a canary replay result carries a score of {self.score!r}, not a "
                "real number: the score is the float the nightly replay computed "
                "and the recorded constant is compared to, and a score that is "
                "not a number is not a score the 1e-12 comparison could reach"
            )
        if (
            self.recorded_score is not None
            and (
                isinstance(self.recorded_score, bool)
                or not isinstance(self.recorded_score, (int, float))
            )
        ):
            raise CanaryReplayScoreError(
                f"a canary replay result carries a recorded_score of "
                f"{self.recorded_score!r}, not a real number or None: it is the "
                "constant the nightly replay compares its score against, and a "
                "non-number is not a constant a comparison could reach"
            )
        if isinstance(self.tolerance, bool) or not isinstance(self.tolerance, (int, float)):
            raise CanaryReplayScoreError(
                f"a canary replay result carries a tolerance of {self.tolerance!r}, "
                "not a real number: the tolerance is §12's 1e-12, the threshold the "
                "deviation is measured against, and a non-number is not a threshold "
                "a comparison could apply"
            )
        if self.tolerance < 0:
            raise CanaryReplayScoreError(
                f"a canary replay result carries a tolerance of {self.tolerance!r}: "
                "the tolerance is an absolute deviation the score may stray by, and "
                "a negative tolerance names no band around the recorded constant"
            )
        if self.recorded_score is None:
            if self.deviation is not None:
                raise CanaryReplayScoreError(
                    "a canary replay result carries a deviation without a recorded "
                    f"score (deviation={self.deviation!r}): the deviation is "
                    "abs(score - recorded_score), and with no recorded constant there "
                    "is nothing to deviate from — a freshly-frozen pair is 'not yet "
                    "replayed', and a fabricated deviation would read as a break that "
                    "never happened"
                )
        else:
            expected = abs(self.score - self.recorded_score)
            if self.deviation is None:
                raise CanaryReplayScoreError(
                    "a canary replay result carries a recorded score without a "
                    "deviation: the deviation is abs(score - recorded_score), and a "
                    "result that compared a score to a constant must carry how far "
                    "apart they were"
                )
            if isinstance(self.deviation, bool) or not isinstance(self.deviation, (int, float)):
                raise CanaryReplayScoreError(
                    f"a canary replay result carries a deviation of "
                    f"{self.deviation!r}, not a real number: it is abs(score - "
                    "recorded_score), and a non-number is not a distance a "
                    "comparison could measure"
                )
            if self.deviation < 0:
                raise CanaryReplayScoreError(
                    f"a canary replay result carries a deviation of "
                    f"{self.deviation!r}: a deviation is an absolute distance and is "
                    "never negative"
                )
            if abs(self.deviation - expected) > 0:
                raise CanaryReplayScoreError(
                    "a canary replay result's deviation "
                    f"({self.deviation!r}) does not equal abs(score - recorded_score) "
                    f"({expected!r}): the deviation is the distance the nightly "
                    "replay reports and the 1e-12 is applied to, and a result whose "
                    "deviation disagrees with its own score and constant would lie "
                    "to the operator reading it"
                )
        expected_within = (
            True
            if self.recorded_score is None
            else self.deviation is not None and self.deviation <= self.tolerance
        )
        if self.within_tolerance != expected_within:
            raise CanaryReplayScoreError(
                "a canary replay result reports within_tolerance="
                f"{self.within_tolerance!r}, but the deviation {self.deviation!r} "
                f"against the tolerance {self.tolerance!r} makes it "
                f"{expected_within!r}: within_tolerance is abs(score - "
                "recorded_score) <= tolerance, and a result that disagrees with its "
                "own deviation and tolerance would tell the operator the canary "
                "passed when it did not"
            )

    @property
    def broken(self) -> bool:
        """The verdict under the spelling the rest of the workspace uses.

        §15's recovery table names the failure "Replay non-determinism", and the
        rest of the workspace spells a failed check ``not ok``; this is
        ``not within_tolerance`` under the name a caller reaching for "did the
        canary break" will try first — the boolean feature 143 halts dreaming on.
        ``True`` only when there is a recorded score to break against, so a pair
        not yet replayed is never reported as broken.
        """
        return not self.within_tolerance

    @property
    def message(self) -> str:
        """One human-readable sentence: the verdict, and what it rests on.

        Composed rather than stored, because every part of it is already a field
        — a stored copy would be a second place for the verdict's wording to live,
        and a result edited after the fact would then disagree with its own
        message.  A passing result names the score and the recorded constant and
        the tolerance; a breaking one names the deviation and points at §15's
        recovery, because the operator reading it is deciding whether the
        determinism the canary guards has broken.
        """
        if self.recorded_score is None:
            return (
                f"the canary pair replays to {self.score} but has no recorded "
                "constant yet: it has not been replayed to a recorded score, so "
                "there is nothing to compare against — the nightly replay records "
                "the constant on the first night, and only then can a later night "
                "deviate from it"
            )
        state = "within tolerance" if self.within_tolerance else "has drifted"
        return (
            f"the canary pair replays to {self.score}, against the recorded "
            f"constant {self.recorded_score}: deviation {self.deviation} "
            f"is {state} of the {self.tolerance} tolerance"
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "ok" if self.within_tolerance else "broken"
        return (
            f"CanaryReplayResult(score={self.score}, "
            f"recorded_score={self.recorded_score!r}, deviation={self.deviation!r}, "
            f"{state})"
        )


class CanaryReplayScoreError(CanaryError):
    """The frozen pair could not be replayed to a score.

    Raised when the frozen tree carries a ``score`` or ``weight`` that is not a
    real number, so the replay cannot sum the tree to a single float.  A
    subclass of :class:`~canary.CanaryError` so a caller — the nightly runner, an
    operator's health check — can catch every failure of the canary's assertions
    with a single ``except``, but deliberately **not**
    :class:`~canary.CanaryImageError` (a moved pin) and **not**
    :class:`~canary.CanaryReproducibilityError` (divergent bytes): the three are
    three different breaks of §12's contract with three different repairs.  A
    tree that cannot be scored is a frozen reference that has drifted into
    something the canary can no longer measure — the repair is to re-freeze the
    pair, not to re-pin an image or bisect a diff — and the class split is what
    makes that legible at the ``except``.

    Deliberately raised for a tree that is *unscorable*, not for a tree that
    *diverges*: a divergence between the replayed score and the recorded constant
    is the nightly canary's ordinary, expected result — the thing it exists to
    report — and reporting it as an error would make the canary's pass path an
    exception.  A tree that cannot be scored at all is a different failure: the
    replay could not produce a number to compare, which is a broken reference,
    not a broken determinism.
    """


def replay_pair(pair: CanaryReferencePair, *, tolerance: float = DEFAULT_TOLERANCE) -> CanaryReplayResult:
    """Replay a frozen canary pair to its score, compared against its constant.

    Feature 142's sentence, executed: take the frozen pair feature 141 persisted
    — one :class:`~canary.CanaryPolicy` and one :class:`~canary.CanaryTree` — run
    the policy over the tree once, in a stable order, and return the score the
    replay produces together with the comparison it feeds.  The policy is read
    from ``pair.policy.policy`` (the frozen mapping) and the tree from
    ``pair.tree.nodes`` (the frozen nodes), both reconstructed from the pair's
    own canonical bytes, so a pair read back from the store and a pair built by
    hand replay through the same code to the same score.

    The score is ``sum(node.score * node.weight)`` over the nodes sorted by
    ``node_id`` — a plain float, the same kind of value the store's
    ``recorded_score`` holds and §12's ``1e-12`` compares.  The comparison is
    reported, not decided: the result carries :attr:`CanaryReplayResult.deviation`
    and :attr:`CanaryReplayResult.within_tolerance`, the four terms of §12's
    ``abs(score - CANARY_EXPECTED) > 1e-12``, and leaves the halt-dreaming to
    feature 143.  A pair not yet replayed — ``recorded_score`` is ``None`` —
    replays to a result with no deviation and nothing broken, so the first night
    records the constant rather than breaking against a constant that does not
    exist.

    A tree that carries a ``score`` or ``weight`` that is not a real number is
    refused with :class:`CanaryReplayScoreError`, naming the node: the replay
    could not place the tree on the number line, so there is no score to compare,
    and that is a broken reference rather than a broken determinism.
    """
    if not isinstance(pair, CanaryReferencePair):
        raise CanaryError(
            f"replay_pair takes a CanaryReferencePair — a frozen policy and tree "
            f"together — got {pair!r}; the nightly replay replays the frozen pair, "
            "and a pair missing either half cannot be replayed"
        )
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        raise CanaryError(
            f"replay_pair's tolerance must be a real number, got {tolerance!r}: it "
            "is §12's 1e-12, the threshold the deviation is measured against, and "
            "a non-number is not a threshold a comparison could apply"
        )
    if tolerance < 0:
        raise CanaryError(
            f"replay_pair's tolerance must be non-negative, got {tolerance!r}: a "
            "tolerance is an absolute deviation the score may stray by, and a "
            "negative tolerance names no band around the recorded constant"
        )
    policy = pair.policy.policy
    score = _score_policy(policy, [node.content for node in pair.tree.nodes])
    recorded = pair.recorded_score
    deviation = None if recorded is None else abs(score - recorded)
    within = (
        True
        if recorded is None
        else deviation is not None and deviation <= tolerance
    )
    return CanaryReplayResult(
        score=score,
        recorded_score=recorded,
        deviation=deviation,
        within_tolerance=within,
        tolerance=tolerance,
    )


class CanaryReplay:
    """Feature 142's nightly replay, as the value a composed application carries.

    A stateless facade over :func:`replay_pair`, so a caller holding the composed
    canary component can reach the replay without importing this member's
    submodules by name — the same role :class:`~tripwires.TimeShuffleTripwire`
    plays for the leakage probe, the evaluator's service plays for features 70+,
    and :class:`~canary.BitReproducibility` plays for feature 145.  The class
    carries no state: ``__slots__`` is empty and it defines no ``__init__``, which
    is the honest shape for a check that is a pure function of the frozen pair it
    is handed and reads nothing from the environment.  There is no seed, no
    window and no store to configure here — the pair is the argument to the call
    that uses it — so two callers replaying two pairs can never observe each
    other, and there is nothing a deployment could misset.

    The delegation is deliberately *thin* — the method is one call to the
    function that owns the computation — because a second implementation of the
    score is exactly what this package's one-provenance rule forbids.  What this
    class adds is discoverability (the factory's scan composes it, through
    :attr:`canary.CanaryService.replay`) and a single duck-checkable seam for the
    app seat and the features that follow, not arithmetic.
    """

    __slots__ = ()

    def pair(
        self,
        pair: CanaryReferencePair,
        *,
        tolerance: float = DEFAULT_TOLERANCE,
    ) -> CanaryReplayResult:
        """Replay a frozen pair to its score, compared against its constant.

        Feature 142's whole sentence, through the composed component: run the
        frozen policy over the frozen tree once, in a stable order, and return the
        :class:`CanaryReplayResult` — the score, the recorded constant, the
        deviation and the ``1e-12`` tolerance band.  Same function, same result,
        same refusal as :func:`replay_pair` — a caller reaching the replay through
        the composed application and one importing the member agree by
        construction.
        """
        return replay_pair(pair, tolerance=tolerance)
