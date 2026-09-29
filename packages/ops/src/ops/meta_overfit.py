"""Feature 347's store: the train-versus-holdout world score gap, in the
relational store the deployment names.

app_spec.xml, "Observability & Dashboards", feature 347: *System persists
the train-versus-holdout world score gap as the meta-overfitting
indicator.*  docs/nullius-tech-architecture.md §16 lists the figure among
the per-campaign research metrics — *"train-vs-holdout world score gap
(meta-overfit)"* — and §15's failure table states what reads it, in the
row the whole dreaming discipline exists to answer:

    | **Dreaming overfits the pool** | Holdout-world score diverges from
      train-world score | Cap `M` per §10.3.1; rotate the 70/30 split;
      block dreaming below 20 worlds |

**The gap is the *observable* half of a failure that announces itself
nowhere else.**  §12.1's warning is that *"the dreaming loop overfits its
own replay pool"*, and prd §12 opens on the same failure one level out
(*"you have built the most compute-efficient overfitting machine ever
assembled"*).  What makes it dangerous is that it does not look wrong:
selection takes a max over ``M`` revisions (feature 274), a max is biased
upward by construction, and the winner's advantage on the worlds that
chose it reads exactly like an edge.  Feature 278's split is the
mitigation — selection reads the train half, reporting reads the holdout
half — and this feature is the split's *instrument*: the two halves have
two levels, their difference is a number, and that number is the only
place the overfitting is visible from.  A positive gap is §15's row —
the train half reads better than the half the selection never touched,
which is what selection manufactured.  The sign is the headline, exactly
as it is for feature 340's cost difference one domain over.

**The store owns no figure and no half's level.**  The member's law,
stated in its package docstring, is delegation, and it holds here: the
per-world scores are the replay member's rows (feature 255's
``replay_score.score``, the out-of-sample IR feature 281 pairs over), the
halves are the dreaming member's partition (feature 278's ``PoolSplit`` /
feature 279's rotation, whose ``is_holdout`` predicate ``0109``'s column
carries), and the level of each half is an aggregate only the caller —
the cycle that holds the split and the scores — can honestly take.
Reaching for either member from here would make this table's
construction depend on two siblings the factory scan could not promise
are on ``sys.path`` at build time, and would grow a second spelling of a
partition and a mean that those members already own.  So the store
**reads no pool and computes no mean**: it accepts the two halves'
levels and their world counts handed over already measured — the same
"hand over, never derive" barrier feature 350 states for its four
metrics, feature 267 for its pair and feature 340 for its two costs.

**What it *does* compute is the one difference the sentence names.**  A
gap is not a measurement; it is the answer to *how far apart were the
two halves*, and the sentence names it as the persisted figure.  So there
is no parameter for it, at any spelling, on the ask or anywhere else —
the identical stance feature 340 takes toward its ``difference_bps``
(*"a caller-supplied difference would let the system persist an
unreconciled claim — two figures and a third that disagrees with both"*)
— and the store's own arithmetic is the one spelling of it.  Two sides
stated, one difference computed, the difference stored beside the sides
that produced it so a reader can check the subtraction rather than trust
it.

**Both levels are finite reals, and the refusal of ``-inf`` is stated
rather than silent.**  A replay that emitted no pick is scored ``-inf``
(feature 249's floor, the miss §16's replay record counts), so a half on
which every world missed has a *level* of ``-inf`` — and a level that is
not a number is not a level: ``-inf`` and ``+inf`` refuse, and a NaN
refuses loudest of all, because a NaN in a difference compares false
against everything and would ride into the trend §15's remediation reads
while looking exactly like a data point (*"Non-determinism does not
announce itself; it just slowly makes every conclusion wrong"* is §12's
sentence about the same shape of failure).  There is deliberately **no
sign bound and no magnitude bound** on either level or on the gap: an
out-of-sample IR is a real with no structural limit the way a
correlation's ``[−1, 1]`` is, the two halves' difference is signed by
construction, and clamping either would answer a gap nobody measured.

**The two counts are context, and they are carried because a reader must
have them.**  A gap taken over 3 train worlds against 1 holdout world is
not the same indicator as one taken over 35 against 15 — the same
reasoning feature 279 carries ``world_count`` beside its holdout worlds
(*"so the record says which 70/30 it was rather than only that it was
one"*) — so each count is persisted beside the levels, validated as a
**positive whole number** rather than as a *weight*: a fractional world
is not a world (feature 267's own count law), and a zero would name a
half that holds nothing, whose level is a mean of nothing.  They enter no
arithmetic: the gap is the difference of the two levels and nothing else,
and stating that plainly is the point — a column that quietly weighted
something would be a second spelling of the aggregate, taken here instead
of where the split's membership lives.

**One row per cycle, keyed by the cycle's own name.**  The key is
``iteration_id`` — the identity every per-cycle record in this workspace
already carries (feature 270's freeze, feature 279's holdout rotation,
whose own judgment is that *"the rotation a cycle's split is taken at is
the cycle's own name"*) — because the split is taken **per cycle**
(§10.3.1's ``rotate_each_cycle=True``) and this figure is a property of
one cycle's split and its scores.  The write is an upsert on that key, on
feature 267's reasoning stated for this row: the figure is deterministic
in the split and the pool feature 270 holds fixed for the cycle, so a
re-run is the *same measurement* written twice rather than a second
occurrence, and the upsert's refresh arm deliberately does not touch
``recorded_at`` — the first instant the cycle's gap was computed is a
fact about the trend's history a retry must not rewrite.  The trend is
read oldest-first by ``(recorded_at, iteration_id)``, the direction §15's
remediation watches the divergence in and the §12 ordering rule every
store in this workspace restates.

**An absent indicator is answered as an absence, never defaulted.**  A
deployment whose loop has closed no cycle out answers ``None`` from the
point read and an empty tuple from the sweep — a discoverable state, not
an exception and never a zero, because ``0.0`` is a *measurement* (a
cycle whose two halves read identically — no overfitting) where ``None``
is an absence, and a caller that could not tell them apart is the caller
this category exists to keep honest.  The split is feature 267's toward
an unclosed campaign and feature 350's toward an unrecorded live metric,
restated because a member states its own contract.

**The store is the workspace's one relational store, addressed the way
every member store addresses it.**  ``DATABASE_URL`` — the one ambient
this member's route, dashboard and live-metrics store already compose on,
imported from :mod:`ops.live_metrics` rather than re-spelled, so the
member holds **one** name for the database every one of its tables lives
in — ``sqlite:///`` on a single machine (docs §16's *"single Postgres
metrics table ... the simpler option is defensible"*), the schema created
idempotently on connect (``CREATE TABLE IF NOT EXISTS``, the contract
every store in this workspace states) so no migration step is needed and
no shared schema file is touched.  The class resolves its path lazily, so
constructing one performs no I/O: composition-time work must not touch
the disk.  The ask is validated whole — cycle, both levels, both counts,
the instant — **before a connection is opened**, so a malformed ask never
reaches the store and a refused record leaves no half-written row and no
database file at all.  The store's own failures (a scheme it cannot
speak, a locked or unwritable database) surface in this member's
vocabulary (:class:`~ops.errors.MetaOverfitGapError`, the original
chained), never swallowed — a divergence that measured but never landed
is the state this feature exists to rule out, because §15's remedy *cap
``M``* is read off these rows and a missing row reads as a quiet cycle.

**The component beside the member's other stores.**  This is the ops
member's fourth component name and its third store-bound one — the growth
the member's own registration reserved when feature 341 landed and the
app-package seat reserved beside it (*"344-347's and 350's persisted
metrics arrive as this member's own tables"*).
:data:`OPS_META_OVERFIT_COMPONENT_NAME` (``ops-meta-overfit``) registers a
builder that resolves ``DATABASE_URL`` and answers ``None`` when nothing
names a store — the degrade-don't-break stance every store-bound builder
here takes, for the reason the route's, the dashboard's and the
live-metrics store's take it: the factory builds every component on every
``create_app()`` call, and a deployment without a relational store must
still compose.

**What this law deliberately does not do.**  It computes no half's level
and reads no pool (each is the source member's derivation, handed over
already measured); it decides no verdict — whether a gap *is* meta-
overfitting is §15's remedy's judgment, reached by the loop that holds
``M``, the split and the pool size, and a threshold here would be this
member inventing a bar the documents put elsewhere; it opens no route —
§16's observability surfaces are feature 341's route and 342/343's lamps
and coverage; it renders no dashboard (351's sentence and the member's);
and it persists no row but its own — the live metrics are 350's, the
research-metrics rows 344-346's, the FDR_deploy rows the scoring member's
(feature 267).

Stdlib-only, like the rest of the member: :mod:`datetime` for the row's
label, :mod:`math` for the finiteness gate, :mod:`sqlite3` for the store,
:mod:`contextlib`/:mod:`pathlib`/:mod:`urllib.parse` for the connection's
plumbing, :mod:`dataclasses` for the value, :mod:`numbers` for the
figures — no third-party import at module scope, so the factory's scan
(which imports this package to fire its ``@register`` builders) pays
nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import MetaOverfitGapError
from .live_metrics import DATABASE_URL_ENV

__all__ = [
    "META_OVERFIT_TABLE",
    "OPS_META_OVERFIT_COMPONENT_NAME",
    "MetaOverfitGap",
    "MetaOverfitGaps",
]

#: The component name the meta-overfit store registers under — this
#: member's fourth, beside :data:`~ops.OPS_COMPONENT_NAME` (the fdr-deploy
#: route), :data:`~ops.OPS_DASHBOARD_COMPONENT_NAME` (the dashboard) and
#: :data:`~ops.OPS_LIVE_METRIC_COMPONENT_NAME` (the live-metrics store)
#: the way ``bootstrap-pool`` sits beside ``bootstrap``.  The growth was
#: reserved by the member's own registration when feature 341 landed and
#: the app-package seat reserved beside it (*"344-347's and 350's
#: persisted metrics arrive as this member's own tables"*), spelled here
#: once, imported by the member's ``__init__``, and read by name through the
#: composed application.  Prefixed with the member's own name because a
#: composed application's ``order`` is name-sorted and the store must sort
#: *beside* — never inside — the member's other components.
OPS_META_OVERFIT_COMPONENT_NAME = "ops-meta-overfit"

#: The table the meta-overfit gap rows live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on
#: connect so no migration step is needed and no shared schema file is
#: touched.  Named member-first and subject-second (the way
#: ``scoring_fdr_deploy`` and ``ops_live_metrics`` are named) so a reader
#: of the store can tell whose research row it is holding: the ops
#: member's, for the gap §16 lists among the per-campaign research metrics
#: under the name *"(meta-overfit)"*.
META_OVERFIT_TABLE = "ops_meta_overfit_gap"

_SCHEMA = f"""
-- Feature 347: the train-versus-holdout world score gap per dreaming
-- cycle — docs §16's research metrics, line 909: "train-vs-holdout world
-- score gap (meta-overfit)", and the observable half of §15's failure row
-- "Dreaming overfits the pool | Holdout-world score diverges from
-- train-world score".
--
-- The primary key is `iteration_id` (the cycle's own name — feature 270's
-- freeze and feature 279's rotation both key on it), because the 70/30
-- split is taken per cycle (§10.3.1's `rotate_each_cycle=True`) and this
-- figure is a property of one cycle's split and the scores its halves
-- read.  One row per cycle: the write is an upsert on this key, so a
-- re-run of the same cycle's measurement refreshes the measured columns
-- rather than appending a second row.
--
-- `train_mean` and `holdout_mean` are the two halves' levels — the source
-- members' aggregates, handed over already measured, never recomputed
-- here.  `gap` is derived: `train_mean - holdout_mean`, computed by the
-- store because a caller-stated difference would be an unreconciled claim
-- persisted on trust; a positive gap is §15's row (the train half reads
-- better than the half selection never touched), a negative one is the
-- honest direction.  Both levels are finite reals with no sign or
-- magnitude bound (-inf, +inf and NaN are refused: a half whose level is
-- not a number has no level to compare).
--
-- `train_worlds` and `holdout_worlds` are the counts each level was taken
-- over — the context a reader needs to tell a 35/15 gap from a 3/1 one,
-- the way feature 279 carries `world_count` beside its holdout worlds.
-- They enter no arithmetic: the gap is the difference of the two levels
-- and nothing else.  Each is a positive whole number, because a
-- fractional world is not a world and a zero names a half whose level is
-- a mean of nothing.
--
-- `recorded_at` is a label, not a measurement: when the row was written
-- (ISO 8601 UTC, second resolution — string order is chronological, which
-- is the order the trend read answers, the direction §15's "cap M"
-- remediation watches the divergence in).  The upsert's refresh arm
-- deliberately does not touch it — a re-run of a cycle's gap is the same
-- measurement (the pool feature 270 holds fixed, the deterministic split,
-- the append-only score rows), and the first instant the row was computed
-- is a fact about the trend's history a retry must not rewrite.
CREATE TABLE IF NOT EXISTS {META_OVERFIT_TABLE} (
    iteration_id  TEXT NOT NULL,  -- the cycle's own name: the split's rotation seam
    train_mean    REAL NOT NULL,  -- the train half's level (finite, unbounded)
    holdout_mean  REAL NOT NULL,  -- the holdout half's level (finite, unbounded)
    train_worlds  INTEGER NOT NULL,  -- worlds the train level was taken over (> 0)
    holdout_worlds INTEGER NOT NULL,  -- worlds the holdout level was taken over (> 0)
    gap           REAL NOT NULL,  -- derived: train_mean - holdout_mean
    recorded_at   TEXT NOT NULL,  -- ISO 8601 UTC: when this row was written
    PRIMARY KEY (iteration_id)
);
"""

#: The per-cycle write: an upsert on the cycle's own key.  ``ON CONFLICT``
#: refreshes the measured columns — a re-run is the same measurement
#: written twice — and leaves ``recorded_at`` alone, for the reason the
#: schema comment above spells.
_UPSERT = f"""
INSERT INTO {META_OVERFIT_TABLE} (
    iteration_id, train_mean, holdout_mean, train_worlds, holdout_worlds,
    gap, recorded_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(iteration_id) DO UPDATE SET
    train_mean     = excluded.train_mean,
    holdout_mean   = excluded.holdout_mean,
    train_worlds   = excluded.train_worlds,
    holdout_worlds = excluded.holdout_worlds,
    gap            = excluded.gap
"""

#: One cycle's row, every column of it — the read the point answer is
#: rebuilt from, positional in the SELECT's order (the store conventions of
#: this workspace spell no row factory; the SELECT is the contract).
_SELECT_ROW = (
    f"SELECT iteration_id, train_mean, holdout_mean, train_worlds, "
    f"holdout_worlds, gap, recorded_at FROM {META_OVERFIT_TABLE} "
    f"WHERE iteration_id = ?"
)

#: Every cycle's row, oldest first — the trend read, in the direction §15's
#: remediation watches the divergence in.  ``(recorded_at, iteration_id)``
#: so two reads of one history return the same sequence whatever the
#: storage engine's accident (§12's ordering rule).
_SELECT_HISTORY = (
    f"SELECT iteration_id, train_mean, holdout_mean, train_worlds, "
    f"holdout_worlds, gap, recorded_at FROM {META_OVERFIT_TABLE} "
    f"ORDER BY recorded_at ASC, iteration_id ASC"
)


@dataclass(frozen=True, slots=True)
class MetaOverfitGap:
    """One meta-overfit gap row, as the table holds it.

    The seven fields are the table's seven columns: which cycle's split the
    gap belongs to, the two halves' levels, the world counts each level was
    taken over, the difference the store computed between them, and the
    moment the row was written.  One type serves the write and the read —
    :meth:`MetaOverfitGaps.record` returns what landed,
    :meth:`MetaOverfitGaps.history` rebuilds what stands — so the row an
    operator reads and the row the table holds cannot be two things that
    disagree.

    **Frozen**, because a caller who could edit ``gap`` in memory could
    revise an overfit indicator after §15's remediation consumed it — the
    in-memory spelling of the revision the value layer refuses — and
    because equality over the stored fields is what makes the record
    idempotent across a retry.

    Validated in :meth:`__post_init__` rather than only through the store,
    for the reason every sibling record states: ``dataclasses.replace`` and
    unpickling both rebuild instances past a factory's nose, and the *read*
    path needs the same check the write path does — SQLite's columns are
    dynamically typed, so a hand-edited row is reachable here.  The one
    check beyond the field validators is the table's own arithmetic:
    ``gap`` must equal ``train_mean − holdout_mean`` exactly, and a row
    where it does not is a row lying about its own subtraction — refused
    rather than served, because the readers downstream (§15's "cap ``M``",
    §16's metric) trust the stored difference without recomputing it.
    """

    #: The cycle whose split and scores the gap was taken over — feature
    #: 270's and 279's own identity, the row's key.
    iteration_id: str
    #: The train half's level — the selection half's aggregate, handed over
    #: already measured (feature 278's "select on train").
    train_mean: float
    #: The holdout half's level — the reporting half's aggregate, the half
    #: the selection never touched (feature 278's "report on holdout").
    holdout_mean: float
    #: How many worlds the train level was taken over.  Context, never a
    #: weight: a gap over 3 worlds is not the indicator a gap over 35 is.
    train_worlds: int
    #: How many worlds the holdout level was taken over, on the same terms.
    holdout_worlds: int
    #: The store's own answer: ``train_mean − holdout_mean``, computed,
    #: never stated by the caller.  Positive is §15's row — the train half
    #: reads better than the half selection never touched.
    gap: float
    #: When this row was written — a label, not a measurement, and the
    #: field the trend read orders by.
    recorded_at: str

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline feature 340's record and every sibling value in
        # this workspace follow.
        object.__setattr__(self, "iteration_id", _the_cycle(self.iteration_id))
        object.__setattr__(
            self, "train_mean", _the_level(self.train_mean, "train_mean")
        )
        object.__setattr__(
            self, "holdout_mean", _the_level(self.holdout_mean, "holdout_mean")
        )
        object.__setattr__(
            self, "train_worlds", _the_count(self.train_worlds, "train_worlds")
        )
        object.__setattr__(
            self,
            "holdout_worlds",
            _the_count(self.holdout_worlds, "holdout_worlds"),
        )
        object.__setattr__(self, "gap", _the_level(self.gap, "gap"))
        object.__setattr__(self, "recorded_at", _the_instant(self.recorded_at))
        # The table's own arithmetic, checked on the value so no path —
        # write, read, replace, unpickle — can carry a gap that disagrees
        # with the levels stored beside it.  The comparison is exact on
        # purpose: both sides round-trip through SQLite as the same IEEE
        # doubles this subtraction was computed from, so anything but exact
        # equality is a hand that edited one of the three, and §15's
        # remediation reads this difference in order to act on it.
        # _the_difference is the one spelling of the subtraction — and it
        # refuses a difference that overflowed two finite levels, which a
        # bare subtraction here would have accepted.
        recomputed = _the_difference(
            self.train_mean, self.holdout_mean, cycle=self.iteration_id
        )
        if self.gap != recomputed:
            raise MetaOverfitGapError(
                f"the meta-overfit gap row for cycle {self.iteration_id!r} "
                f"carries a gap of {self.gap!r} that its own halves "
                f"(train {self.train_mean!r}, holdout {self.holdout_mean!r}) "
                f"do not subtract to ({recomputed!r}). The two levels are "
                f"the row's truth and the gap a derived view over them, so a "
                f"row that disagrees with its own measurement is an "
                f"indicator no reader could act on — and §15's remedy for "
                f"dreaming overfitting (*cap M per §10.3.1*) is read off "
                f"these rows. The repair is the store's, never a re-measure "
                f"over a cycle whose pool feature 270 already froze "
                f"(feature 347, docs §15-§16)"
            )

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a later reporter or expose-surface reads the row through:
        the table's seven columns under the record's own field names.
        """
        return {
            "iteration_id": self.iteration_id,
            "train_mean": self.train_mean,
            "holdout_mean": self.holdout_mean,
            "train_worlds": self.train_worlds,
            "holdout_worlds": self.holdout_worlds,
            "gap": self.gap,
            "recorded_at": self.recorded_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"MetaOverfitGap(iteration_id={self.iteration_id!r}, "
            f"train_mean={self.train_mean!r}, "
            f"holdout_mean={self.holdout_mean!r}, gap={self.gap!r})"
        )


def _the_cycle(value: Any) -> str:
    """The row's key — the cycle's own name, or a refusal.

    Non-empty text, stripped, matching the one spelling of what a dreaming
    iteration is in this workspace (feature 270's ``iteration_id`` and
    feature 279's rotation, whose own judgment is that *the rotation a
    cycle's split is taken at is the cycle's own name*).  Stated here
    rather than imported, because a member spells the key it joins in its
    own words; a value that names no cycle names no split and no gap.
    """
    if not isinstance(value, str) or not value.strip():
        raise MetaOverfitGapError(
            f"a meta-overfit gap is keyed by the cycle it was measured over "
            f"— a non-empty string, got {value!r} ({type(value).__name__}). "
            f"The gap is a property of one cycle's 70/30 split and the "
            f"scores its halves read, so a value that names no cycle names "
            f"no split to have measured a divergence on, and its row would "
            f"be an indicator attributed to no tournament (feature 347)"
        )
    return value.strip()


def _the_level(value: Any, field: str) -> float:
    """Narrow one half's level — or the gap — to a finite ``float``.

    Two gates, each refused rather than resolved, the discipline feature
    340's ``_validated_bps`` states for its own two figures:

    * **a finite real.**  ``bool`` is refused first (``True`` is ``1``, and
      a flag where a level belongs would persist a figure nobody measured),
      and anything that is not a :class:`~numbers.Real` is refused with it
      — text, ``None``, a sequence — because a level is one number.
    * **finite.**  ``-inf`` and ``+inf`` are refused *by name*, and the
      refusal says why: a replay that emitted no pick is scored ``-inf``
      (feature 249's floor, the miss), so a half on which every world
      missed has a level of ``-inf`` — and a level that is not a number is
      not a level to subtract.  A NaN is refused for the same reason
      loudest of all: it compares false against everything and would ride
      into the trend §15's remediation reads while looking exactly like a
      data point.

    There is deliberately **no sign bound and no magnitude bound**: an
    out-of-sample IR has no structural limit the way a correlation's
    ``[−1, 1]`` does, and the sign of the gap *is* the headline — the
    direction of §15's divergence — so a negative level or a negative gap
    is a measurement, not a mistake.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MetaOverfitGapError(
            f"{field} must be a half's level — a finite real number, the "
            f"source member's aggregate handed over already measured — got "
            f"{value!r} ({type(value).__name__}). A level that is not one "
            f"number is not a measurement any reader of §15's divergence "
            f"can act on, and the likeliest thing wearing its name at this "
            f"seam is a count of worlds or a flag (feature 347)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise MetaOverfitGapError(
            f"{field} must be finite — got {narrowed!r}. A replay that "
            f"emitted no pick is scored -inf (feature 249's floor, the miss "
            f"§16's replay record counts), so a half on which every world "
            f"missed has no level to compare: a level that is not a number "
            f"subtracts to nothing an operator could read, and a NaN would "
            f"compare false against everything and ride into the trend "
            f"§15's remediation reads while looking exactly like a data "
            f"point. The repair is the cycle's (a half with a measurable "
            f"level), never the store's (feature 347)"
        )
    return narrowed


def _the_difference(train: float, holdout: float, *, cycle: Any) -> float:
    """The gap — ``train − holdout``, computed here or nowhere, and *checked*.

    The one spelling of the store's arithmetic, shared by the write path
    (:meth:`MetaOverfitGaps.record`, which stores what this answers) and by
    the value layer (:meth:`MetaOverfitGap.__post_init__`, which verifies a
    stored row against it), so the two cannot drift apart.

    **Both operands being finite does not make their difference finite, and
    that is why this is a function rather than a bare ``-``.**  Two levels
    near the top of the double range — ``1e308`` and ``-1e308`` — are
    perfectly good measurements one at a time, and their difference
    overflows to ``+inf``: a gap that is not a number, produced by an
    arithmetic step nobody guarded because both halves passed their own
    gates.  A two-sided IR whose halves read that far apart is not a
    measurement of divergence; it is a subtraction that fell off the end of
    the number line, and §15's remedy is read off these rows — so it is
    refused *by name*, at the door, with the same reasoning the level gate
    states for a ``-inf`` that arrived as a level: a gap that is not a
    number is not an indicator anybody can act on.

    The check is deliberately **before any connection**, on the write path
    as well as the read path.  The read path reaches it through the value
    layer's own ``__post_init__``, which recomputes this difference over the
    stored levels and refuses a row that disagrees; the write path calls it
    first so a row this store would refuse to read back is never inserted —
    otherwise the INSERT would land, the read-back would refuse its own row,
    and the ask that was supposed to be validated whole *before* the store
    was touched would instead have written a permanently unreadable row that
    makes every later :meth:`~MetaOverfitGaps.history` refuse.  The failure
    is the caller's (two levels too far apart to subtract), never the
    store's, and the repair is the cycle's.
    """
    difference = train - holdout
    if not math.isfinite(difference):
        raise MetaOverfitGapError(
            f"the meta-overfit gap for cycle {cycle!r} is not a finite real: "
            f"train_mean {train!r} minus holdout_mean {holdout!r} is "
            f"{difference!r}. Both halves are measurements one at a time and "
            f"each passed its own gate, but their difference overflowed the "
            f"double range — a gap that is not a number is not a divergence "
            f"any reader of §15's *dreaming overfits the pool* row could act "
            f"on, and a store that persisted one would carry an indicator "
            f"nothing can compare (feature 347, docs §15-§16)"
        )
    return difference


def _the_count(value: Any, field: str) -> int:
    """One half's world count — a positive whole number, or a refusal.

    Held to ``int`` rather than coerced into it: ``14.0`` is refused where a
    count of worlds belongs, because a fractional world is not a world and
    coercing it would be this module inventing a split size the caller did
    not state — the count law feature 267 and the promotion member's
    ``min_worlds`` both state.  ``bool`` is refused before ``int`` (a
    ``bool`` *is* an ``int`` in Python's hierarchy and is not a count of
    worlds), and a non-positive count is refused by name: a half with zero
    worlds has a level that is a mean of nothing, and §10.3.1's split needs
    both halves to exist — the refusal feature 278 states for a fraction
    that empties one, restated for the row that would record it.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise MetaOverfitGapError(
            f"{field} must be a count of worlds — a whole number, got "
            f"{value!r} ({type(value).__name__}). The count is the context a "
            f"reader needs to tell a 35/15 gap from a 3/1 one, and a "
            f"fractional world is not a world: coercing it would be this "
            f"store inventing a split size the caller never stated "
            f"(feature 347)"
        )
    if value < 1:
        raise MetaOverfitGapError(
            f"{field} must be at least 1 — got {value!r}. The gap is taken "
            f"between two halves of a pool, and a half holding no worlds has "
            f"a level that is a mean of nothing: §10.3.1's *select on train, "
            f"report on holdout* needs both halves to exist, which is the "
            f"refusal feature 278 states for a fraction that empties one, "
            f"restated for the row that would record it (feature 347)"
        )
    return value


def _the_instant(recorded_at: Any) -> str:
    """The row's label — the caller's instant, or the wall clock's now.

    ``recorded_at`` defaults to *now* (UTC, second resolution — the spelling
    :meth:`datetime.datetime.isoformat` produces and the one the trend
    read's ``ORDER BY`` stays chronological under), because a caller that
    closed a cycle out at a known instant passes it so the row's label
    matches the measurement rather than the write.  An explicit instant must
    be a non-empty string — it orders the trend, and a label that is not a
    nameable instant orders nothing.
    """
    if recorded_at is None:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise MetaOverfitGapError(
            f"a meta-overfit gap row's recorded_at is an ISO 8601 UTC string "
            f"— got {recorded_at!r} ({type(recorded_at).__name__}). The "
            f"instant is the label the trend's order reads, so a value that "
            f"is not a nameable instant orders nothing; pass the instant the "
            f"cycle's gap was measured at, or nothing and let the write "
            f"stamp its own (feature 347)"
        )
    return recorded_at


class MetaOverfitGaps:
    """§16's meta-overfit indicator, in the relational store the
    deployment names.

    Constructed with the database URL it persists into; :meth:`record`
    lands one cycle's gap as its row, :meth:`gap` answers one cycle's
    indicator, and :meth:`history` answers every cycle's oldest-first — the
    trend §15's remediation watches the divergence in.  The class resolves
    its path lazily, so constructing one performs no I/O — composition-time
    work must not touch the disk, the contract every store in this
    workspace states — and the schema is created idempotently on the first
    connect, so no migration step is needed.

    Hand-written with ``__slots__`` and no ``__dict__``: a store is a
    holder, not a value, and there is no shadow state beside the URL for a
    caller to park a figure in.  Not frozen: the URL it holds is live
    deployment state, and the rows live in the database, never in the
    process — the store caches none of the gaps it wrote, so a gap read
    back is a fact about the world rather than about this process's
    history.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: Any) -> None:
        # The URL is held, not resolved: validating it would touch the
        # filesystem or parse a scheme, and constructing a store is
        # composition-time work (the builder runs on every create_app())
        # that must not refuse.  A URL this store cannot speak is refused
        # by name at first use, where the operator's repair belongs.
        if not isinstance(database_url, str) or not database_url.strip():
            raise MetaOverfitGapError(
                f"the meta-overfit store is constructed with a database URL, "
                f"and this one is not a non-empty string (got "
                f"{database_url!r}, {type(database_url).__name__}): pass the "
                f"relational store to persist the train-versus-holdout gap "
                f"into — sqlite:///path/to/store.db, the spelling every "
                f"member store in this workspace takes (feature 347, docs "
                f"§16)"
            )
        self._database_url = database_url.strip()
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Any = None) -> MetaOverfitGaps | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no meta-overfit component — a discoverable state, not an exception —
        while the caller that must persist a gap is the one that must not
        find itself in it.  The split is the one every resolve-shaped
        builder in this workspace states: this method answers *what is
        composed*, and the caller who needs a row and resolves ``None``
        refuses to proceed rather than silently persisting nowhere — a
        trend with a hole in it exactly where the overfitting showed is the
        quietly-defaulted number this category exists to rule out, and
        §15's remedy *cap ``M``* is read off these rows.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store persists into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this store cannot speak is refused by name) the first time an
        operation needs it, which is the same laziness every store class in
        this workspace states for the same reason.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The verbs ------------------------------------------------------------

    def record(
        self,
        iteration_id: Any,
        *,
        train_mean: Any,
        holdout_mean: Any,
        train_worlds: Any,
        holdout_worlds: Any,
        recorded_at: Any = None,
    ) -> MetaOverfitGap:
        """Persist one cycle's train-versus-holdout gap — the difference the
        store computes between the two halves' levels handed over.

        ``iteration_id`` names the cycle (feature 270's and 279's own
        identity, the row's key); ``train_mean`` and ``holdout_mean`` are
        the two halves' levels, handed over **already measured** by the
        caller that holds the split and the scores — the store reads no
        pool and computes no mean; ``train_worlds`` and ``holdout_worlds``
        are the counts each level was taken over; ``recorded_at`` defaults
        to *now* (UTC, second resolution), and a caller that closed the
        cycle out at a known instant passes it so the row's label matches
        the measurement.

        **The gap is the store's own arithmetic**, ``train_mean −
        holdout_mean``, and there is no parameter for it at any spelling: a
        caller-stated difference would let the system persist two levels
        and a third number that disagrees with both, and §15's remedy reads
        this difference in order to act on it — feature 340's stance toward
        its own ``difference_bps``, restated for §16's indicator.

        The ask is validated whole — cycle, both levels, both counts, the
        instant — **before a connection is opened**, so a malformed ask
        never reaches the store and a refused record leaves no half-written
        row and no database file at all.  The write is an upsert on the
        cycle's key: the figure is deterministic in the split and the pool
        feature 270 holds fixed for the cycle, so a re-run is the same
        measurement written twice — the measured columns refresh and the
        row's original ``recorded_at`` stands, the law feature 267 states
        for its own per-campaign row.

        Returns:
            The :class:`MetaOverfitGap` **the table holds** — read back
            inside the same transaction as the write, so the gap, the
            counts and the instant in the answer are the row's own rather
            than the arguments'.

        Raises:
            MetaOverfitGapError: The ask, refused — a cycle that is not
                non-empty text, a level that is not a finite real (a
                ``bool``, a ``None``, a ``-inf`` from an all-miss half, a
                NaN), a count that is not a positive whole number, an
                instant that is not a nameable label; and any failure of
                the store itself, chained to the original and deliberately
                not swallowed — a divergence that measured but never landed
                is the state this feature exists to rule out.
        """
        cycle = _the_cycle(iteration_id)
        train = _the_level(train_mean, "train_mean")
        holdout = _the_level(holdout_mean, "holdout_mean")
        train_size = _the_count(train_worlds, "train_worlds")
        holdout_size = _the_count(holdout_worlds, "holdout_worlds")
        instant = _the_instant(recorded_at)
        # The subtraction is the store's, computed once, here or nowhere —
        # and *checked* here, before a connection is opened.  The value's own
        # construction re-validates every field and the arithmetic beside it,
        # so the write path and the read path share one spelling of what a
        # gap row is; but the arithmetic is called on this side of the
        # connection too, because a difference that overflowed two
        # individually-finite halves is exactly the ask that must not land:
        # otherwise the INSERT would succeed and the read-back would refuse
        # its own row, leaving a permanently unreadable gap in the very trend
        # §15's remedy is read off.
        gap = _the_difference(train, holdout, cycle=cycle)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _UPSERT,
                    (
                        cycle,
                        train,
                        holdout,
                        train_size,
                        holdout_size,
                        gap,
                        instant,
                    ),
                )
                row = connection.execute(_SELECT_ROW, (cycle,)).fetchone()
        except MetaOverfitGapError:
            raise
        except (sqlite3.Error, OSError) as exc:
            # The store's own failure, translated: a caller catching this
            # member's base class must catch a divergence that measured but
            # never landed, and the original is chained so the operator
            # still sees the database's own words — never swallowed, never
            # retried over a measurement that already landed.
            raise MetaOverfitGapError(
                f"could not persist the meta-overfit gap for cycle {cycle!r} "
                f"into the store: {exc!r}. The train-versus-holdout gap is "
                f"docs §16's meta-overfit research metric and the observable "
                f"half of §15's *dreaming overfits the pool* row, whose "
                f"remedy (*cap M per §10.3.1*) is read off these rows — so a "
                f"divergence that measured but never landed is the state "
                f"feature 347 exists to rule out, and a missing row reads as "
                f"a quiet cycle. The failure is surfaced, and the repair is "
                f"the store's (the original refusal is chained), never a "
                f"re-measure over a cycle whose pool feature 270 already "
                f"froze (feature 347, docs §15-§16)"
            ) from exc
        if row is None:  # pragma: no cover - the write landed in this transaction
            raise MetaOverfitGapError(
                f"the meta-overfit gap for cycle {cycle!r} could not be read "
                f"back after the write. §15's remedy for dreaming "
                f"overfitting is read off these rows, so a row this store "
                f"cannot vouch for is an indicator an operator would be "
                f"steering by blind (feature 347)"
            )
        return _record_from_row(row)

    def gap(self, iteration_id: Any) -> MetaOverfitGap | None:
        """One cycle's standing indicator, or ``None`` when it holds none.

        The point read — the answer to *how far apart did this cycle's two
        halves read?* for a caller holding one cycle.  ``None`` is the
        honest absent answer (the cycle closed no gap out, or this
        deployment never measured one), never a zero: ``0.0`` is a
        *measurement* — a cycle whose halves read identically, no
        overfitting — where ``None`` is an absence, and a caller that could
        not tell them apart would read a clean cycle out of a missing row.
        The same stance feature 267's ``fdr`` takes toward an unclosed
        campaign and feature 350's ``latest`` toward an unrecorded metric.
        """
        cycle = _the_cycle(iteration_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_SELECT_ROW, (cycle,)).fetchone()
        except MetaOverfitGapError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise MetaOverfitGapError(
                f"could not read the meta-overfit gap for cycle {cycle!r} "
                f"from the store: {exc!r}. The divergence is the one place "
                f"§15's *dreaming overfits the pool* is visible from, so a "
                f"store that cannot be asked is surfaced rather than "
                f"answered around; the repair is the store's (the original "
                f"refusal is chained) (feature 347, docs §15-§16)"
            ) from exc
        return None if row is None else _record_from_row(row)

    def history(self) -> tuple[MetaOverfitGap, ...]:
        """Every cycle's gap on record, oldest first — the trend read.

        §16 lists the figure among the research metrics and §15's remedy
        watches it *across* cycles — a divergence that widens as ``M`` or
        the pool thins is the failure the row exists to make visible — so
        that is the order this answers in: by the row's own instant, with
        the cycle's id breaking same-instant ties (§12's ordering rule).  An
        empty tuple is the honest answer for a deployment that has closed
        no cycle out: a discoverable state, not an exception and never a
        fabricated first point.

        Fails with :class:`~ops.errors.MetaOverfitGapError` when the store
        could not be read, and when a stored row is not a gap row this
        store could have written — the refusal, not a skip: a skipped row
        is a divergence wearing a shrug, and §15's remedy acts on this
        sweep.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(_SELECT_HISTORY).fetchall()
        except MetaOverfitGapError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise MetaOverfitGapError(
                f"could not read the meta-overfit gap history from the "
                f"store: {exc!r}. The trend is the sequence §15's remedy "
                f"(*cap M per §10.3.1*, rotate the split) is read across, so "
                f"a store that cannot be asked is surfaced rather than "
                f"answered around; the repair is the store's (the original "
                f"refusal is chained) (feature 347, docs §15-§16)"
            ) from exc
        return tuple(_record_from_row(row) for row in rows)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the store and the URL it holds — a URL is not a secret, and
        # a repr is a debugging aid — and nothing else: the rows live in
        # the database, and the gaps are the caller's.
        return f"{type(self).__name__}({self._database_url!r})"

    # -- The connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The URL is translated on first use (a scheme this store cannot
        speak is refused by name here, at the operation that needed it),
        the schema is created idempotently (``CREATE TABLE IF NOT
        EXISTS``, the contract every store in this workspace states), and
        the caller owns the connection — use it as a context manager to
        commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection


def _record_from_row(row: Any) -> MetaOverfitGap:
    """Rebuild one stored row, refusing a value no gap row can be.

    The refusal is the point: this table is written by this store, but
    SQLite will accept anything another tool inserts, and a row wearing a
    cycle no split was taken at, a level that is not a measurement, a
    half-size that is not a count of worlds, or a gap that disagrees with
    the two levels beside it would otherwise reach §15's remedy and §16's
    metric as a divergence nobody measured.  The value layer performs the
    validation (one spelling of it, shared with the write path) and this
    re-read *names the cycle the bad row came from*, so an operator gets
    the row to repair rather than a complaint about a value with no
    address — the discipline feature 340's ``_from_row`` states for its own
    ledger, restated in this member's vocabulary.
    """
    try:
        return MetaOverfitGap(
            iteration_id=row[0],
            train_mean=row[1],
            holdout_mean=row[2],
            train_worlds=row[3],
            holdout_worlds=row[4],
            gap=row[5],
            recorded_at=row[6],
        )
    except MetaOverfitGapError as refusal:
        raise MetaOverfitGapError(
            f"{refusal} — the row this came from is the meta-overfit gap "
            f"recorded for cycle {row[0]!r} at {row[6]!r}, holding train "
            f"{row[1]!r} over {row[3]!r} world(s) against holdout "
            f"{row[2]!r} over {row[4]!r} world(s) (feature 347)"
        ) from refusal


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — this store's own
    spelling of the translation every store in this workspace performs.

    Only ``sqlite:///`` speaks (docs §16's single-machine allowance), any
    other scheme refused loudly rather than silently mis-parsed so a
    misrouted Postgres URL cannot hide behind a mysterious file, no host
    but ``localhost`` admitted, and a URL with no path refused — the same
    three refusals the live-metrics store beside this one and the replay
    member's metrics store state for their own connections, restated
    because a member states its own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise MetaOverfitGapError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            f"meta-overfit store speaks sqlite:/// (docs §16's 'single "
            f"Postgres metrics table', the simpler option the section "
            f"defends at this scale), the same refusal every store in this "
            f"workspace documents — a Postgres metrics table arrives with "
            f"the versioned migration member, and pretending to speak it "
            f"here would hide a misrouted URL behind a mysterious file "
            f"(feature 347)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise MetaOverfitGapError(
            f"the meta-overfit store's sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 347)"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise MetaOverfitGapError(
            f"the meta-overfit store's sqlite {DATABASE_URL_ENV} carries no "
            f"database path (feature 347)"
        )
    return Path(path)
