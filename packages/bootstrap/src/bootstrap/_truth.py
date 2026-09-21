"""The ground truth of every node — feature 189's calibration reference.

app_spec.xml, "Bootstrap Worlds", feature 189: *System labels every
bootstrap node with ground truth, which returns perfect sensitivity and
specificity references for calibration.*  docs/nullius-tech-
architecture.md §10.6 states the property the feature stands on — the
bootstrap worlds *"give perfect labels, zero statistical-budget cost, and
no dependence on market time"* — and §10.3 names the two quantities those
labels make exactly computable: *"sensitivity/specificity on planted
nulls"*, the base-rate-independent pair the research metrics carry and
the inputs ``FDR_deploy`` is reweighted from.  On a financial world both
numbers are *estimates* — measured against nulls the oracle planted, on
the campaigns a run happened to run, with the sampling error a finite
pool of commits carries.  On a bootstrap world they can be *references*:
exact numbers, computed against labels that are facts of the world rather
than measurements of a run.  This module is those labels and that
computation.

**What a ground-truth class is, and why it is binary.**  §7.1's sidecar
holds one bit per node — ``is_null`` — and every sensitivity and
specificity the system ever reports is a confusion matrix over that bit:
a policy declares nodes discoveries, the truth says which of them were,
and ``TP/(TP+FN)`` and ``TN/(TN+FP)`` fall out.  A bootstrap world's
honest label (:meth:`~bootstrap.HyperparameterWorld.label`) is a real
number, so the ground truth this module adds is the *class* read off
that number: a node is a **discovery** when its held-out ``R²`` clears
the world's published evidential bar (:data:`DISCOVERY_BAR`) and a
**null** when it does not.  The class is derived, never stored beside
the score, so the two cannot disagree — the same "read off, not
recorded" discipline :class:`~bootstrap._question.CellMeta` applies to a
node's structure.

**Why an absolute, published bar.**  The bar could have been relative —
a fraction of the world's own best cell, a margin over the root — and
each of those would quietly change what "discovery" means from world to
world, which is exactly what a *reference* must not do: §10.3's
sensitivity and specificity are comparable across worlds because they
are rates against one standard, and §10.6's bootstrap pool is the
reference half of that comparison.  One absolute bar keeps the standard
fixed while the worlds vary — and it is the only shape that ports, because
a :class:`~bootstrap.PortedWorld` (feature 190) hands over scores and
nothing beside them: no truth to decompose, no noise to bound, just the
one ``R²`` scale every bootstrap world already reports on.  The bar's
grounds are stated with it (:data:`DISCOVERY_BAR`); the property the pool
actually needs — that both classes are populated on every world, §7.3's
*"a tree needs ≥2 null and ≥2 real roots to contribute to both
sensitivity and specificity"* — is pinned by this member's tests over
the pool's own seed band rather than asserted here.

**Perfect, and what perfect means.**  The labels are pure functions of
``(world, node)`` (:mod:`bootstrap._stream`'s content addressing and
:mod:`bootstrap._fit`'s exactly-rounded arithmetic), the class is one
comparison against an exactly-representable bar, the counts are
integers, and the ratios are one correctly-rounded division each — so a
sensitivity read off a :class:`GroundTruth` is not an estimate of the
world's number but the world's number, reproducible to the last bit
(§12).  That is the sense in which the references are *perfect*, and it
has a concrete checkpoint: the declaration that names exactly the
discoveries (:meth:`GroundTruth.perfect`) scores sensitivity ``1.0`` and
specificity ``1.0`` — not approximately, not on average, exactly.  A
policy's measured rates on a financial pool are then calibrated against
something: the same policy's rates on worlds where the answer key is
published.

**A client of the 184 seam, not a second interface.**  Feature 184
(:mod:`bootstrap._question`) built the one object a policy is handed and
duck-typed the world it wraps, because the module loader hands out a
second copy of the world class under a synthetic name and an
``isinstance`` gate would refuse the very world ``create_app()``
serves.  :func:`ground_truth` rides that same seam and adds no new one:
it asks a world for the answer surface every bootstrap world already
exposes — ``cells()``, ``label(node_id)``, ``world_id`` — so the authored
world, the ported world and the composed world are labeled through one
code path with no ``isinstance`` anywhere.  What it deliberately does
*not* take from 184 is the question itself: a labeling is not a walk.  It
has no reveal order to honour, no frontier to answer from and no commit
to record, so wrapping the world in reveal bookkeeping to read every
label would be paying for state the labeling cannot use — the question
is the *policy's* view of a world and the ground truth is the *scorer's*,
and the two read the same lattice without sharing the object that holds
the walk.

**"Every" is a precondition, and it is enforced.**  The feature's own
sentence says *every* bootstrap node, and a reference computed over
59 of 60 cells would silently misstate every denominator it reported —
the same quiet corruption §10.6.1's provenance rule exists to keep out
of the pool.  So :func:`ground_truth` labels each cell of ``cells()``
and lets a cell that cannot be labeled refuse the whole reference
(:class:`~bootstrap.errors.BootstrapScoringError`, naming the node and
the world it could not answer): the committed world's ridge floor keeps
every cell answerable, and a world configured otherwise reports that it
has no reference to give rather than giving a partial one.  A score that
is not a real number is refused for the same reason — a ``nan`` compared
against the bar classifies as a null, and a null that is merely a
missing number is a stand-in wearing a class.

**What this module does not do.**  It computes no ``FDR_deploy``
(§10.3's reweighting is a statement about the deployment base rate and
belongs to the scorer that holds ``π₀``), persists nothing (features 188
and 191 own the pool's rows), charges no budget (feature 185's
``charges_budget`` is the trial's fact) and scores no policy — it scores
a *declaration*, the set of nodes a caller says are discoveries, which
is the shape §10.3's rates are computed over and the thing every caller
from §10.1's single ``commit`` upward accumulates into.  The module is
the answer key and the arithmetic over it; what is done with the numbers
is the caller's own feature.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .errors import BootstrapScoringError, BootstrapWorldError

__all__ = [
    "DISCOVERY_BAR",
    "ConfusionMatrix",
    "GroundTruth",
    "NodeTruth",
    "ground_truth",
]

#: The evidential bar a node's honest score must clear to be labelled a
#: discovery — the world's published standard for what counts as found.
#:
#: ``0.5``: a discovery is a setting whose model explains at least *half*
#: the variance of data it was never fitted on.  Four grounds make this
#: the bar rather than a taste, and each is the kind of ground the world's
#: other published constants stand on:
#:
#: * **It is beyond what noise can reach.**  The holdout split carries
#:   :data:`~bootstrap._world.PRICED_ROWS` / :data:`~bootstrap.
#:   _world.HOLDOUT_STRIDE` = 32 rows, and the scale on which a skill-less
#:   fit's held-out ``R²`` fluctuates is the reciprocal square root of
#:   that, ≈ 0.18 — the committed world's degree-1 cells (the family that
#:   cannot express the truth's curvature at all) top out near +0.22 and
#:   mostly sit below zero, as a family with no skill should.  A bar at
#:   0.5 stands ≈ 2.8 of those scales above no-skill: a score that clears
#:   it is a fact about the model, not a fact about the draw.
#: * **It is under what truth can reach.**  The world publishes its own
#:   model, and the score that model's own coefficients would earn on the
#:   holdout — the oracle — is exactly computable from
#:   :meth:`~bootstrap._world.Dataset.truth_for` (≈ 0.96 on the committed
#:   world).  Over the pool's whole 50-seed band the oracle's floor is
#:   ≈ 0.52: above the bar on every world — narrowly, on the hardest —
#:   so no world of the pool declares the truth's own family unreachable
#:   while still holding cells that clear the bar.
#: * **Both classes hold on every pool world.**  §7.3: *"a tree needs ≥2
#:   null and ≥2 real roots to contribute to both sensitivity and
#:   specificity"* — the floor problem, and the reason a bar that emptied
#:   either class would take every world of the pool out of calibration
#:   at once.  Over the pool's band every world labels at least 3 of its
#:   60 cells discoveries and at least 20 nulls at this bar (pinned by
#:   this member's tests, the way :data:`~bootstrap._world.NOISE_SCALE`
#:   is pinned — against a sweep of seeds rather than one).
#: * **It is exactly representable.**  ``0.5`` is a power of two, so the
#:   comparison ``score >= bar`` is bit-stable on every platform that
#:   spells float64 the IEEE way — §12's determinism contract met by the
#:   construction of the constant rather than by a tolerance around it.
#:
#: The bar is a parameter of :func:`ground_truth` as well as a constant
#: here, for the caller that deliberately calibrates against a different
#: evidential standard — a stricter bar for a reference that counts only
#: near-oracle settings, a bar at ``0.0`` for the bare beats-the-mean
#: standard.  A bar outside ``[0, 1]`` is refused rather than clamped: a
#: bar below zero would classify nodes with *negative* out-of-sample skill
#: as discoveries, and a bar above 1 names a standard no coefficient of
#: determination can meet — either is a corruption of the reference, not a
#: loosening of it.
DISCOVERY_BAR = 0.5


def _validated_bar(bar: Any) -> float:
    """Check an evidential bar and return it as a plain finite float.

    The one spelling of what a bar must be, shared by :func:`ground_truth`,
    :meth:`NodeTruth.from_score` and the :class:`GroundTruth` constructor,
    so the three cannot disagree about which standards are speakable.  A
    ``bool`` is refused where a bar is expected for the reason
    :class:`~bootstrap.HyperparameterSetting` refuses one on an axis:
    ``True`` is ``1`` in Python, so a flag where a bar belongs would
    silently name the strictest standard this module can speak.
    """
    if isinstance(bar, bool) or not isinstance(bar, (int, float)):
        raise BootstrapWorldError(
            f"an evidential bar is a real number — got {bar!r} "
            f"({type(bar).__name__}); the bar is the standard a node's "
            "honest score is classified against, and a value that is not "
            "a number names no standard at all"
        )
    value = float(bar)
    if not math.isfinite(value):
        raise BootstrapWorldError(
            f"an evidential bar is a finite real number — got {bar!r}; a "
            "bar that is not a number classifies no node, and one that "
            "is infinite classifies them all the same way, so neither is "
            "a standard a calibration reference can stand on"
        )
    if not 0.0 <= value <= 1.0:
        raise BootstrapWorldError(
            f"an evidential bar lies in [0, 1] — got {value!r}; R² is the "
            "fraction of variance explained, a score below zero is worse "
            "than predicting the mean, and a bar outside the band names "
            "a standard that either crowns no-skill cells discoveries or "
            "that no coefficient of determination can meet"
        )
    return value


@dataclass(frozen=True)
class NodeTruth:
    """One node's ground truth — its honest score and the class that reads off it.

    A frozen value, because a node's truth is a *fact about the world*
    rather than a fact about a run: two callers holding the truth of one
    node must not be able to move each other's, and a scorer reading it
    twice gets the same class.  It carries the node's honest held-out
    ``R²`` beside the class, so the label and the number it was read off
    travel together — a class without its score could not be audited
    against the world's own :meth:`~bootstrap.HyperparameterWorld.label`,
    and a score without its class is feature 181's deliverable, not this
    one's.

    ``world_id`` is carried for the reason :class:`~bootstrap.
    _question.Observation` carries it: §10.6's pools are *reported per
    pool*, and a confusion matrix aggregated across worlds needs every
    label to say which world it was earned on.  Constructed through
    :meth:`from_score` — the one place the class is read off the score —
    or directly (by a test pinning an edge), and validated either way:
    an id that is not a non-empty string, or a score that is not a
    finite real number, is refused before the value can reach a
    confusion matrix, because a label that cannot say which world it
    belongs to or how well the node scored is not a ground truth.
    """

    node_id: str
    world_id: str
    score: float
    is_discovery: bool

    def __post_init__(self) -> None:
        for name, value in (("node_id", self.node_id), ("world_id", self.world_id)):
            if not isinstance(value, str) or not value.strip():
                raise BootstrapWorldError(
                    f"a node truth's {name} is a non-empty string — got "
                    f"{value!r} ({type(value).__name__}); §10.6's pools are "
                    "reported per pool, and a label that cannot say which "
                    "world it was earned on cannot be attributed to one"
                )
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise BootstrapScoringError(
                f"node {self.node_id!r} of world {self.world_id!r} has no "
                f"ground-truth class to give: its honest score is "
                f"{self.score!r} ({type(self.score).__name__}), which is not "
                "a real number — the class is read off the score, and a "
                "score that is not a number reads off no class at all"
            )
        if not math.isfinite(float(self.score)):
            raise BootstrapScoringError(
                f"node {self.node_id!r} of world {self.world_id!r} has no "
                f"ground-truth class to give: its honest score is "
                f"{self.score!r}, which is not finite — a NaN compared "
                "against the bar classifies as a null, and a null that is "
                "merely a missing number is a stand-in wearing a class"
            )

    @classmethod
    def from_score(
        cls,
        node_id: str,
        world_id: str,
        score: float,
        *,
        bar: float = DISCOVERY_BAR,
    ) -> NodeTruth:
        """Build the node truth a score makes — the class, read off once.

        The one place a score becomes a class, so "a node is a discovery
        when its honest score clears the bar" has exactly one
        implementation and no caller's spelling of it can drift: every
        ground truth is made here, the way every observation is made by
        :meth:`~bootstrap._question.Observation.from_fit`.  The
        comparison is inclusive — a score exactly at the bar is a
        discovery — because the bar is the standard a score must *meet*,
        not exceed, and a boundary score excluded would make the
        reference disagree with itself between a bar of ``0.5`` and a
        score of ``0.5``.
        """
        checked = _validated_bar(bar)
        return cls(
            node_id=node_id,
            world_id=world_id,
            score=score,
            is_discovery=float(score) >= checked,
        )

    def row(self) -> dict[str, Any]:
        """The node truth as a store-shaped mapping — a fresh dict per call.

        The row a calibration report writes down per node: the address,
        the world it was earned on, the honest score, and the class the
        bar read off it.  Fresh per call, never shared, for the reason a
        frozen value's ``row()`` is always fresh — a caller that mutated
        a shared dict would be editing the report, not the truth.
        """
        return {
            "node_id": self.node_id,
            "world_id": self.world_id,
            "score": self.score,
            "is_discovery": self.is_discovery,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"NodeTruth(node_id={self.node_id!r}, "
            f"world_id={self.world_id!r}, score={self.score!r}, "
            f"is_discovery={self.is_discovery!r})"
        )


@dataclass(frozen=True)
class ConfusionMatrix:
    """A declaration scored against the ground truth — §10.3's four counts.

    The confusion matrix of a *declaration* — the set of nodes a caller
    has said are discoveries — against a :class:`GroundTruth`'s labels:
    true positives (declared and discoveries), false positives (declared
    and nulls), false negatives (discoveries left undeclared) and true
    negatives (nulls left undeclared).  Four integers, and everything
    §10.3 measures on planted nulls derives from them:

    * :attr:`sensitivity` — ``TP / (TP + FN)``, *of the world's real
      discoveries, the fraction the declaration found*;
    * :attr:`specificity` — ``TN / (TN + FP)``, *of the world's nulls,
      the fraction the declaration correctly left alone*.

    Both denominators are facts about the *world's* labeled population,
    not about the declaration (every discovery is either found or
    missed; every null is either declared or not), which is why the two
    rates are base-rate independent in §10.3's sense and why an empty
    class is a refusal rather than a default: a world whose labels hold
    no discoveries cannot calibrate sensitivity at all — there is nothing
    there to be sensitive to — and answering a number about an empty
    class would be a stand-in where the reference's whole value is that
    it never gives one.

    Frozen, and equal by its four counts, so a policy's score on a world
    is a value a report can hold, compare and re-derive; the counts are
    not validated because, like :class:`~bootstrap._fit.FitResult`'s
    floats, they are made by the one arithmetic that computes them and a
    hand-built matrix is a test's prerogative.
    """

    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    @property
    def sensitivity(self) -> float:
        """``TP / (TP + FN)`` — of the real discoveries, the fraction found.

        One correctly-rounded division of two integers, so the number is
        exact and order-independent (§12) — the property that makes this
        a *reference* rather than an estimate.  Refuses with
        :class:`~bootstrap.errors.BootstrapWorldError` when the labels
        hold no discoveries at all: ``0/0`` is not a sensitivity of zero
        (a declaration cannot find what no node is) but a world that
        cannot calibrate the rate, and the refusal names it as that
        rather than defaulting a number about an empty class.
        """
        found = self.true_positives + self.false_negatives
        if found == 0:
            raise BootstrapWorldError(
                "sensitivity is undefined against labels that hold no "
                f"discoveries (true positives={self.true_positives}, false "
                f"negatives={self.false_negatives}) — a world whose every "
                "node is a null has nothing for a declaration to find, and "
                "a calibration reference refuses the rate rather than "
                "answering a number about an empty class"
            )
        return self.true_positives / found

    @property
    def specificity(self) -> float:
        """``TN / (TN + FP)`` — of the nulls, the fraction left undeclared.

        The twin of :attr:`sensitivity` on the other class, and the one
        §10.3's ``FDR_deploy`` reweighting leans on hardest (it is
        ``1 − specificity`` that a false discovery rides on).  Refuses
        when the labels hold no nulls, for the twin's reason: a world of
        nothing but discoveries cannot measure what a declaration
        wrongly declared, because it cannot be wrong.
        """
        clean = self.true_negatives + self.false_positives
        if clean == 0:
            raise BootstrapWorldError(
                "specificity is undefined against labels that hold no "
                f"nulls (true negatives={self.true_negatives}, false "
                f"positives={self.false_positives}) — a world whose every "
                "node is a discovery cannot be wrongly declared against, "
                "and a calibration reference refuses the rate rather than "
                "answering a number about an empty class"
            )
        return self.true_negatives / clean

    def row(self) -> dict[str, int]:
        """The matrix as a store-shaped mapping — a fresh dict per call.

        The four counts a calibration report aggregates across worlds;
        the two rates are derived properties rather than stored fields,
        so a persisted row cannot hold a sensitivity the counts do not
        recompute to.
        """
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ConfusionMatrix(tp={self.true_positives}, fp={self.false_positives}, "
            f"tn={self.true_negatives}, fn={self.false_negatives})"
        )


@dataclass(frozen=True)
class GroundTruth:
    """Every node of one world, labelled — the calibration reference.

    Built by :func:`ground_truth` (or by hand, for a test pinning an
    edge): the world's id, one :class:`NodeTruth` per cell of its lattice
    in ascending node order, and the bar the classes were read off.  The
    labels are *the world's own* — every score is the world's honest
    :meth:`~bootstrap.HyperparameterWorld.label`, carried unchanged — so
    the reference cannot drift from the world it calibrates against, and
    the bar is carried with them because two ground truths over one
    world at different bars are different references, not two spellings
    of one.

    The population the labels describe is what §7.3's floor problem
    asks of a calibration world, and this class makes it answerable as a
    fact: :attr:`discovery_count` and :attr:`null_count` are the two
    sides of the floor, and a world that empties either side has no rate
    to calibrate on it (the :class:`ConfusionMatrix` refusals say so
    when asked).  A labeling is also *order-free* — nothing here depends
    on which node was labelled first, because nothing about a label ever
    did — so two ground truths of one ``(world, bar)`` pair are equal to
    the last field, the property a calibration checkpoint replays on.

    Construction refuses the labelings that could not serve as a
    reference at all: no nodes (a world with nothing to label has no
    ground truth to give), a duplicated node id (two labels for one node
    is not a labeling but a contradiction), labels drawn from more than
    one world (§10.6 reports the pools separately, and a reference that
    straddled two worlds could not be attributed to either), and a bar
    outside the band :func:`_validated_bar` states.  The labels are
    sorted once, here, into the lattice's own ascending node order — a
    labeling is a set of labels, and the order they were handed in is no
    fact of the world — so every enumeration downstream
    (:attr:`labels`, :meth:`discoveries`, :meth:`nulls`) is the same
    order without each caller sorting.
    """

    world_id: str
    labels: tuple[NodeTruth, ...]
    bar: float = DISCOVERY_BAR

    def __post_init__(self) -> None:
        if not isinstance(self.world_id, str) or not self.world_id.strip():
            raise BootstrapWorldError(
                f"a ground truth is labelled with its world's id — got "
                f"{self.world_id!r} ({type(self.world_id).__name__}); §10.6's "
                "pools are reported per pool, and a reference that cannot "
                "say which world it calibrates against attributes its "
                "counts to none"
            )
        checked = _validated_bar(self.bar)
        labels = tuple(self.labels)
        if not labels:
            raise BootstrapWorldError(
                f"the ground truth of world {self.world_id!r} holds no "
                "labels — a world with no nodes to label has no reference "
                "to give, and an empty labeling would calibrate every rate "
                "against nothing"
            )
        for label in labels:
            if not isinstance(label, NodeTruth):
                raise BootstrapWorldError(
                    f"the ground truth of world {self.world_id!r} is made of "
                    f"node truths — got {label!r} "
                    f"({type(label).__name__}); a label that is not one is "
                    "not a label the reference can score a declaration "
                    "against"
                )
            if label.world_id != self.world_id:
                raise BootstrapWorldError(
                    f"the ground truth of world {self.world_id!r} holds a "
                    f"label earned on {label.world_id!r} (node "
                    f"{label.node_id!r}) — §10.6 reports the pools "
                    "separately, and a reference straddling two worlds "
                    "cannot be attributed to either"
                )
        ordered = tuple(sorted(labels, key=lambda label: label.node_id))
        seen: set[str] = set()
        for label in ordered:
            if label.node_id in seen:
                raise BootstrapWorldError(
                    f"the ground truth of world {self.world_id!r} holds two "
                    f"labels for node {label.node_id!r} — a node's truth is "
                    "one label, and two is a contradiction rather than a "
                    "labeling"
                )
            seen.add(label.node_id)
        # Normalised once, here: the world id is checked, the bar is a
        # finite float in the band, and the labels are the caller's own
        # tuples in the lattice's own order — every enumeration below
        # reads this canonical shape and cannot disagree with another's.
        object.__setattr__(self, "bar", checked)
        object.__setattr__(self, "labels", ordered)
        object.__setattr__(self, "_index", {label.node_id: label for label in ordered})

    # -- The population -------------------------------------------------------

    def __len__(self) -> int:
        """How many nodes the reference labels — every cell of the world."""
        return len(self.labels)

    @property
    def nodes(self) -> tuple[str, ...]:
        """Every labelled node id, ascending — the world's whole lattice."""
        return tuple(label.node_id for label in self.labels)

    def truth(self, node_id: str) -> NodeTruth:
        """One node's ground truth, or the reference's refusal.

        Refuses with :class:`~bootstrap.errors.BootstrapWorldError`,
        naming the node and the world, for a node the labels do not hold
        — the same bound ``commit`` and ``probe_batch`` apply on the
        question side: a caller cannot ask after a node the world never
        showed, and a truth for a cell outside the labeling would be
        answering for a node the reference knows nothing about.
        """
        if isinstance(node_id, str) and node_id in self._index:
            return self._index[node_id]
        raise BootstrapWorldError(
            f"the ground truth of world {self.world_id!r} holds no node "
            f"{node_id!r} — the reference labels the {len(self.labels)} "
            "cells of the world's own lattice, and a truth asked of a "
            "node outside it would be answering for a cell the world "
            "never held"
        )

    def is_discovery(self, node_id: str) -> bool:
        """Whether the labels hold ``node_id`` a discovery."""
        return self.truth(node_id).is_discovery

    def score(self, node_id: str) -> float:
        """The honest score ``node_id``'s class was read off."""
        return self.truth(node_id).score

    def discoveries(self) -> tuple[str, ...]:
        """The world's true discoveries, ascending — the answer key's positive half.

        Also *the perfect declaration*: naming exactly these nodes is the
        policy that finds every discovery and declares no null, and
        :meth:`calibrate` scores it exactly ``1.0`` / ``1.0`` — the
        reference point the feature's own sentence names.
        """
        return tuple(
            label.node_id for label in self.labels if label.is_discovery
        )

    def nulls(self) -> tuple[str, ...]:
        """The world's true nulls, ascending — the answer key's negative half.

        Named for §7.1's vocabulary: these are the nodes whose score did
        not clear the bar, the planted-null side of the confusion the
        financial pool measures and this pool *knows*.
        """
        return tuple(
            label.node_id for label in self.labels if not label.is_discovery
        )

    @property
    def discovery_count(self) -> int:
        """How many of the world's nodes are true discoveries."""
        return sum(1 for label in self.labels if label.is_discovery)

    @property
    def null_count(self) -> int:
        """How many of the world's nodes are true nulls."""
        return sum(1 for label in self.labels if not label.is_discovery)

    # -- The calibration ------------------------------------------------------

    def calibrate(self, declared: Iterable[str]) -> ConfusionMatrix:
        """Score a declaration against the labels — the reference arithmetic.

        ``declared`` is the set of nodes a caller says are discoveries —
        §10.1's replay commits one node per world, and the campaigns of a
        pool accumulate those commits into exactly this shape, the one
        §10.3's rates are computed over.  Duplicates are collapsed and
        order is ignored (a declaration is a set, and two callers naming
        the same nodes in different orders have made the same
        declaration), and every node must be one the world holds: a
        declaration naming a cell outside the lattice is refused,
        all-or-nothing before any count is taken, for the reason
        ``probe_batch`` refuses there — a policy cannot declare a node
        it was never shown, and a half-scored declaration would leave the
        caller holding counts it could not attribute to any policy.

        The counts are integers and the rates are single divisions, so
        the answer is exact: the same declaration scores the identical
        sensitivity and specificity on every platform, every replay,
        every time — the property that makes this a calibration
        *reference* rather than one more measurement.
        """
        if isinstance(declared, (str, bytes)):
            raise BootstrapWorldError(
                f"a declaration is an iterable of node ids — got "
                f"{declared!r}; a single node id where a declaration "
                "belongs would be read as a sequence of characters, and a "
                "calibration over its letters is not a calibration at all"
            )
        named: set[str] = set()
        for node_id in declared:
            if not isinstance(node_id, str):
                raise BootstrapWorldError(
                    f"a declaration names node ids — got {node_id!r} "
                    f"({type(node_id).__name__}); the reference scores the "
                    "nodes a caller says are discoveries, and a value that "
                    "is not a node id names none"
                )
            named.add(node_id)
        for node_id in sorted(named):
            self.truth(node_id)  # refuses a node the world does not hold
        discoveries = set(self.discoveries())
        nulls = set(self.nulls())
        return ConfusionMatrix(
            true_positives=len(named & discoveries),
            false_positives=len(named & nulls),
            true_negatives=len(nulls) - len(named & nulls),
            false_negatives=len(discoveries) - len(named & discoveries),
        )

    def perfect(self) -> ConfusionMatrix:
        """The reference a perfect declaration earns — the feature's headline.

        :meth:`calibrate` over :meth:`discoveries` — declare exactly the
        world's true discoveries — which scores sensitivity ``1.0`` and
        specificity ``1.0`` *exactly*, because the labels the declaration
        is scored against are the same labels it was built from.  That
        circularity is the point and is not a trick: on a financial world
        the same perfect declaration exists only behind the sidecar key
        and its rates are still measured through a policy's behaviour;
        here the answer key is published, so the perfect rates are
        computable outright — the reference numbers a measured policy's
        sensitivity and specificity are calibrated against, returned by
        the labeling the feature's own sentence promises.
        """
        return self.calibrate(self.discoveries())

    def row(self) -> dict[str, Any]:
        """The reference as a store-shaped summary — a fresh dict per call.

        What a calibration report writes down per world: the world the
        labels belong to, the bar they were read off, and the two sides
        of §7.3's floor as counts.  The labels themselves are the
        :class:`NodeTruth` rows, one per node, and are not folded in
        here — a summary a caller can hold beside the labels it
        summarises is worth more than one that embeds them.
        """
        return {
            "world_id": self.world_id,
            "bar": self.bar,
            "nodes": len(self.labels),
            "discoveries": self.discovery_count,
            "nulls": self.null_count,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"GroundTruth(world_id={self.world_id!r}, "
            f"nodes={len(self.labels)}, "
            f"discoveries={self.discovery_count}, nulls={self.null_count}, "
            f"bar={self.bar!r})"
        )


def ground_truth(world: Any, *, bar: float = DISCOVERY_BAR) -> GroundTruth:
    """Label every node of a bootstrap world with its ground truth.

    The one factory for the reference, the way :func:`~bootstrap.
    question_for` is the one factory for the question: a world in, the
    :class:`GroundTruth` a scorer expects out.  The world is duck-typed
    over the same answer surface feature 184's seam calls through —
    ``cells()``, ``label(node_id)`` and ``world_id`` — so the authored
    world, a :class:`~bootstrap.PortedWorld` and the composed world the
    module loader serves are labelled through one code path, with no
    ``isinstance`` anywhere to refuse the loader's own copy (see
    :mod:`bootstrap._question` for why that gate would break the
    composition seam).

    Every cell of ``cells()`` is labelled with the world's own honest
    score, classed by :meth:`NodeTruth.from_score` against ``bar``, and
    *every* means every: a cell whose label refuses
    (:class:`~bootstrap.errors.BootstrapScoringError`) refuses the whole
    reference, naming the node and the world — a labeling that silently
    skipped a cell would misstate every denominator the reference ever
    reported, and the feature's sentence does not say "every node but
    one".  The committed world's ridge floor keeps all of its cells
    answerable, so the refusal is a guard for a world configured
    otherwise, not this one's routine path.

    Refuses, before any cell is labelled, a world without the answer
    surface (naming what is missing) or with a blank id (a reference that
    cannot say which world it calibrates), and refuses a ``bar`` outside
    the band :data:`DISCOVERY_BAR`'s docstring states.  Never charges a
    budget, consults a clock or writes a row — the labels are a pure
    function of ``(world, bar)``, so the same call answers the identical
    reference on every platform and in every process (§12).
    """
    required = ("cells", "label", "world_id")
    missing = [name for name in required if not hasattr(world, name)]
    if missing:
        raise BootstrapWorldError(
            f"the ground truth labels a bootstrap world — got {world!r} "
            f"({type(world).__name__}), which has no {', '.join(missing)}; "
            "the reference is read off the same answer surface the "
            "question interface calls through, and an object that is not "
            "a world names no cells a calibration could be scored over"
        )
    # The id is touched, not the dataset: the world's identity is its id
    # (or, for a ported world, its provenance), and a reference over an
    # unnamed world would attribute its counts to no pool — §10.6's
    # report-per-pool rule, the same check the question's constructor
    # makes for the same reason.
    if not isinstance(world.world_id, str) or not world.world_id.strip():
        raise BootstrapWorldError(
            f"the ground truth labels a named world — got id "
            f"{world.world_id!r}; §10.6's pools are reported per pool, and "
            "a reference over an unnamed world could not attribute its "
            "counts to one"
        )
    checked = _validated_bar(bar)
    cells = tuple(sorted(world.cells()))
    if not cells:
        raise BootstrapWorldError(
            f"world {world.world_id!r} holds no cells — a world with "
            "nothing to label has no ground truth to give, and an empty "
            "reference would calibrate every rate against nothing"
        )
    labels = tuple(
        NodeTruth.from_score(
            node_id,
            world.world_id,
            world.label(node_id).r2_holdout,
            bar=checked,
        )
        for node_id in cells
    )
    return GroundTruth(world_id=world.world_id, labels=labels, bar=checked)
