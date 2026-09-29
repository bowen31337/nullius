"""Feature 344's store: the planted-null calibration pair, per campaign,
in the relational store the deployment names.

app_spec.xml, "Observability & Dashboards", feature 344: *System persists
sensitivity and specificity on planted nulls per campaign into the metrics
store.*  docs/nullius-tech-architecture.md §16 lists the figure among the
research metrics it fixes the grain of in its own parenthesis (line 909) —
*"**Research metrics** (per campaign): ``FDR_deploy`` at π₀ = 0.9,
sensitivity/specificity on planted nulls, Type-B depth past the flip in
Type-D worlds, …"* — and prd §11's scorecard carries it as the one row
whose target is a *verb about tracking* rather than a bar (line 539):

    | **Secondary** | Sensitivity / specificity on planted nulls
      (base-rate independent) | tracked, not targeted |

The prd also names the pair's first consumer a section later — §12's M2
exit (line 590): *"a measured baseline on planted nulls — sensitivity,
specificity, and per-commit OOS IR"* — and the guilt-free reason the
figure is worth a row at all (line 185): *"Sensitivity to small
perturbations: jitter a lookback ±10%, drop 20% of the universe, shift the
window start by 5 days."*

**The pair is feature 266's, and this feature exists to land it.**  §4.1.3
states why the pair and not the raw rate (line 144): *"Sensitivity and
specificity are base-rate independent, so measure them where you have
power for both, then reweight."*  The scoring member's calibration seam
(:meth:`scoring.NullPickScorer.calibration_figures`, feature 266) answers
them as :class:`~scoring.CalibrationFigures` — ``sensitivity`` =
``TP / (TP + FN)``, *of the planted reals, the fraction the policy found*,
and ``specificity`` = ``TN / (TN + FP)``, *of the planted nulls, the
fraction the policy correctly left alone* — each a finite real in ``[0,
1]``.  That feature's own docstring reserves this one twice over: it
*"persists nothing: the per-campaign row docs §16 lists among the research
metrics (line 909) is the ops member's feature (344's), which reads these
figures and stores them."*  Feature 267's docstring says the same in the
other direction — *"the research-metrics row that carries 266's pair is the
ops member's (feature 344)"* — and so does this member's own package
docstring.  This store is that reservation kept: it lands one campaign's
pair as one row and answers the row back, unchanged.

**The store owns no measurement, and it derives nothing.**  The member's
law, stated in its package docstring, is delegation, and it holds here as
it holds for every store beside this one.  The pair is the scoring member's
answer over the campaign's planted population joined to its committed
picks, and the labels the fractions condition on never leave the scorer's
process — prd §4.2 grants the sidecar key to exactly one component.  So the
store **computes neither figure**: it accepts the pair handed over already
measured — the same *"hand over, never derive"* barrier feature 267 states
for its pair, feature 350 for its four live metrics, feature 346 for its
three counts, feature 347 for its two halves and feature 345 for its one
count — and validates each against the shape its name fixes.  Where feature
346 computes its quotient and 347 its difference, nothing here is derived:
the two figures go into two columns and come back out of them.

**The two figures are not a compact statistic, and that is why the pair is
trended rather than summarised.**  The documents leave the store no way to
reduce the pair to one number.  §4.1.3's reweighting (``FDR_deploy = π₀(1 −
specificity) / [π₀(1 − specificity) + (1 − π₀)·sensitivity]``) needs a base
rate, and *that* base rate is π₀ = 0.9 — a constant, not a parameter,
because a caller able to pick the base rate could pick the figure the
target is judged on (feature 267's own argument, and `scoring/
DEPLOYMENT_BASE_RATE` is where it is spelled).  The two base rates prd
§4.1.3 does name — the campaign's ~0.25 plant and the 0.9 deployment — are
1.0 and 0.9, whose projection collapses the pair to ``1 − specificity`` and
``sensitivity`` respectively, i.e. to one figure wearing the other's name,
which is not a summary of both.  So this store invents no blend, no
average and no rate over the two: it holds each in its own column, and
whatever compares rows across campaigns compares two figures — the
``(1 − specificity, sensitivity)`` plane feature 261's switch penalty and
feature 269's accounting both already reason in, with no base rate to
pick.

**The pair is trended as two figures, and this store adds nothing to it.**
The sentence's object is a *trend* — prd §11's *"tracked"* — and the
temptation is to give it a resolution to move inside.  This store declines
it, on three grounds.  A caller-stated interval would be an *unreconciled
claim persisted on trust*: nothing would tie it to the figure beside it,
which is the argument feature 347 states when it derives its gap rather than
accepting one.  A store-derived interval has no document behind it — prd
§4.1.3 fixes the pair's *independence*, not a resolution per figure, and no
line in §11, §16 or the prd names a band over a class-conditional figure.
And the feature's own sentence says what to persist — *"persists sensitivity
and specificity on planted nulls per campaign"* — two figures, per campaign.
So the row is the campaign's key, the two figures, and the instant it was
written: a store that lands exactly what was measured and takes no position
on how precisely.  What makes the pair trendable across rows is the
members' shared key (below), not a column this store invents: whichever
report or surface later reads these rows compares two figures across
campaigns, the ``(1 − specificity, sensitivity)`` plane feature 261's switch
penalty and feature 269's accounting both already reason in.

**One row per campaign, keyed by the campaign's canonical id.**  §16 fixes
the grain in its own parenthesis — *"**Research metrics** (per campaign)"* —
so the key is the campaign id, canonicalised to UUID text so a mixed-case or
braced spelling upserts onto the one row rather than making one campaign
look like two.  The canonicalisation is the join law the workspace already
states: feature 267's ``FDR_deploy`` row, feature 346's discovery-rate row
and feature 345's Type-B depth row are keyed this way because the value
joins ``node.campaign_id`` and every reader of the campaign row resolves it,
and this table's rows land under the same key so an operator reads one
campaign's base-rate-reweighted rate, its research yield, its Type-B count
and its calibration pair off one identity, in one query.  The write is an
upsert on that key, on the siblings' reasoning restated for this row: the
pair is a deterministic function of the campaign's planted population and
its committed picks — both append-only facts no later run rewrites — so a
re-run is the *same measurement* written twice rather than a second
occurrence, and the upsert's refresh arm deliberately does not touch
``recorded_at``: the first instant the campaign's pair was taken is a fact
about the trend's history a retry must not rewrite.  The trend is read
oldest-first by ``(recorded_at, campaign_id)``, the direction prd §11's
*"tracked"* is read in, the ordering rule §12 states and every store in this
workspace restates.

**The store is the workspace's one relational store, addressed the way
every member store addresses it.**  ``DATABASE_URL`` — the one ambient this
member's route, dashboard and other stores already compose on, imported
from :mod:`ops.live_metrics` rather than re-spelled, so the member holds
**one** name for the database every one of its tables lives in — with
``sqlite:///`` on a single machine (docs §16's *"single Postgres metrics
table … the simpler option is defensible"*), the schema created idempotently
on connect (``CREATE TABLE IF NOT EXISTS``, the contract every store in this
workspace states) so no migration step is needed and no shared schema file
is touched.  The class resolves its path lazily, so constructing one
performs no I/O: composition-time work must not touch the disk.  The ask is
validated whole — campaign, both figures, the instant — **before a
connection is opened**, so a malformed ask never reaches the store and a
refused record leaves no half-written row and no database file at all.  The
store's own failures (a scheme it cannot speak, a locked or unwritable
database) surface in this member's vocabulary
(:class:`~ops.errors.NullCalibrationError`, the original chained), never
swallowed — a pair that measured but never landed is the state this feature
exists to rule out, because prd §11 tracks the pair across these rows and a
missing row reads as a campaign nobody calibrated.

**The component beside the member's other stores.**  This is the ops
member's seventh component name and its sixth store-bound one — the growth
the member's own registration reserved when feature 341 landed and the
app-package seat reserved beside it (*"344's … arrive as their own tables
under the same allowance"*).  The component name,
:data:`OPS_NULL_CALIBRATION_COMPONENT_NAME` (``ops-null-calibration``),
registers a builder that resolves ``DATABASE_URL`` and answers ``None`` when
nothing names a store — the degrade-don't-break stance every store-bound
builder here takes, for the reason the route's, the dashboard's and the
other five stores' take it: the factory builds every component on every
``create_app()`` call, and a deployment without a relational store must
still compose.

**What this law deliberately does not do.**  It computes neither figure
(feature 266's verb, over the process feature 265 built and the sidecar prd
§4.2 grants to one component); it computes no ``FDR_deploy`` (feature 267's
arithmetic over exactly this pair, and `scoring.fdr_deploy` is where it
lives); it renders no verdict — prd §11's target is *"tracked, not
targeted"*, so a threshold or a grade here would be this member inventing
the bar the prd pointed somewhere else on purpose; it prices nothing (β₂
charges the raw rate, feature 258, and no β-term reads a class-conditional
figure — §11's scorecard tracks these); it opens no route (§16's surfaces
are feature 341's route and 342/343's lamps and coverage); it renders no
dashboard (351's sentence and the member's); and it persists no row but its
own — the live metrics are 350's, the meta-overfit gap 347's, the discovery
rate 346's, the Type-B depth 345's, and the ``FDR_deploy`` rows the scoring
member's (feature 267).

Stdlib-only, like the rest of the member: :mod:`datetime` for the row's
label, :mod:`sqlite3` for the store, :mod:`contextlib`/:mod:`pathlib`/
:mod:`urllib.parse` for the connection's plumbing, :mod:`os` for the resolve
door, :mod:`uuid` for the key's canonical spelling, :mod:`math` for the
finiteness gate, and :mod:`dataclasses` for the value — no third-party
import at module scope, so the factory's scan (which imports this package to
fire its ``@register`` builders) pays nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import NullCalibrationError
from .live_metrics import DATABASE_URL_ENV

__all__ = [
    "NULL_CALIBRATION_TABLE",
    "OPS_NULL_CALIBRATION_COMPONENT_NAME",
    "NullCalibration",
    "NullCalibrations",
]

#: The component name the calibration store registers under — this member's
#: seventh, beside :data:`~ops.OPS_COMPONENT_NAME` (the fdr-deploy route),
#: :data:`~ops.OPS_DASHBOARD_COMPONENT_NAME` (the dashboard),
#: :data:`~ops.OPS_LIVE_METRIC_COMPONENT_NAME` (the live-metrics store),
#: :data:`~ops.OPS_META_OVERFIT_COMPONENT_NAME` (the meta-overfit gap store),
#: :data:`~ops.OPS_DISCOVERY_RATE_COMPONENT_NAME` (the discovery-rate store)
#: and :data:`~ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME` (the Type-B depth store),
#: the way ``bootstrap-pool`` sits beside ``bootstrap``.  The growth was
#: reserved by the member's own registration when feature 341 landed and the
#: app-package seat reserved beside it (*"344's … arrive as their own tables
#: under the same allowance"*), spelled here once, imported by the member's
#: ``__init__``, and read by name through the composed application.
#: Prefixed with the member's own name because a composed application's
#: ``order`` is name-sorted and the store must sort *beside* — never inside —
#: the member's other components.
OPS_NULL_CALIBRATION_COMPONENT_NAME = "ops-null-calibration"

#: The table the calibration rows live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on connect so
#: no migration step is needed and no shared schema file is touched.  Named
#: member-first and subject-second (the way ``scoring_fdr_deploy``,
#: ``ops_discovery_rate`` and ``ops_type_b_depth`` are named) so a reader of
#: the store can tell whose research row it is holding: the ops member's, for
#: the pair §16 lists among the per-campaign research metrics as
#: *"sensitivity/specificity on planted nulls"*.
NULL_CALIBRATION_TABLE = "ops_null_calibration"

_SCHEMA = f"""
-- Feature 344: the planted-null calibration pair, per campaign — docs §16's
-- research metrics, line 909: "sensitivity/specificity on planted nulls",
-- and prd §11's secondary scorecard row: "Sensitivity / specificity on
-- planted nulls (base-rate independent) | tracked, not targeted".
--
-- The primary key is `campaign_id`, the campaign's id in canonical UUID
-- text — §16 fixes the grain in its own parenthesis ("Research metrics (per
-- campaign)"), and the canonical spelling is the join law feature 267's
-- FDR_deploy row, feature 346's discovery-rate row and feature 345's Type-B
-- depth row already key on, so a mixed-case or braced spelling upserts onto
-- the one row rather than making one campaign look like two, and an
-- operator reads one campaign's figures off one identity.  One row per
-- campaign: the write is an upsert on this key, so a re-run of the same
-- campaign's measurement refreshes the measured columns rather than
-- appending a second row.
--
-- `sensitivity` and `specificity` are feature 266's own figures — TP/(TP+FN)
-- and TN/(TN+FP) over the campaign's planted population join — handed over
-- already measured by the caller that ran the calibration verb, never
-- recomputed here.  Each is a finite real in [0, 1]: a fraction of one
-- planted class, bounded by construction.  Both ends are measurements and
-- both are honored — 0.0 sensitivity is a campaign that found none of its
-- reals, 1.0 specificity one that wrongly declared nothing — and neither is
-- an absence.
--
-- The two figures are the whole table.  No derived column, no blend and no
-- rate over the two: §4.1.3's reweighting needs a base rate, and that base
-- rate is a constant the scoring member fixes
-- (`scoring/DEPLOYMENT_BASE_RATE`, feature 267's own argument), so a base
-- rate a caller could state would be one a caller could pick the figure's
-- grade with.  And the two base rates prd §4.1.3 does name — the campaign's
-- ~0.25 plant and the 0.9 deployment — are 1.0 and 0.9, whose projection
-- collapses the pair to `1 - specificity` and `sensitivity` respectively:
-- one figure wearing the other's name, which is not a summary of both.  So
-- the pair is stored as two figures and read as two figures, the way prd
-- §11's scorecard row reads it.
--
-- `recorded_at` is a label, not a measurement: when the row was written
-- (ISO 8601 UTC, second resolution — string order is chronological, which is
-- the order the trend read answers, the direction prd §11's "tracked" is
-- read in).  The upsert's refresh arm deliberately does not touch it — a
-- re-run of a campaign's pair is the same measurement (the campaign's
-- planted population and its committed picks are append-only facts), and the
-- first instant the row was computed is a fact about the trend's history a
-- retry must not rewrite.
CREATE TABLE IF NOT EXISTS {NULL_CALIBRATION_TABLE} (
    campaign_id         TEXT NOT NULL,  -- canonical UUID text: the row's key
    sensitivity         REAL NOT NULL,  -- feature 266's TP/(TP+FN), a fraction in [0, 1]
    specificity         REAL NOT NULL,  -- feature 266's TN/(TN+FP), a fraction in [0, 1]
    recorded_at         TEXT NOT NULL,  -- ISO 8601 UTC: when this row was written
    PRIMARY KEY (campaign_id)
);
"""

#: The per-campaign write: an upsert on the campaign's key.  ``ON CONFLICT``
#: refreshes the measured columns — a re-run is the same measurement written
#: twice — and leaves ``recorded_at`` alone, for the reason the schema comment
#: above spells.
_UPSERT = f"""
INSERT INTO {NULL_CALIBRATION_TABLE} (
    campaign_id, sensitivity, specificity, recorded_at
) VALUES (?, ?, ?, ?)
ON CONFLICT(campaign_id) DO UPDATE SET
    sensitivity = excluded.sensitivity,
    specificity = excluded.specificity
"""

#: One campaign's row, every column of it — the read the point answer is
#: rebuilt from, positional in the SELECT's order (the store conventions of
#: this workspace spell no row factory; the SELECT is the contract).
_SELECT_ROW = (
    f"SELECT campaign_id, sensitivity, specificity, recorded_at "
    f"FROM {NULL_CALIBRATION_TABLE} WHERE campaign_id = ?"
)

#: Every campaign's row, oldest first — the trend read, in the direction prd
#: §11's *"tracked"* is read in.  ``(recorded_at, campaign_id)`` so two reads
#: of one history return the same sequence whatever the storage engine's
#: accident (§12's ordering rule).
_SELECT_HISTORY = (
    f"SELECT campaign_id, sensitivity, specificity, recorded_at "
    f"FROM {NULL_CALIBRATION_TABLE} "
    f"ORDER BY recorded_at ASC, campaign_id ASC"
)


@dataclass(frozen=True, slots=True)
class NullCalibration:
    """One calibration row, as the table holds it.

    The four fields are the table's four columns: which campaign the pair
    belongs to, the two base-rate-independent figures, and the moment the row
    was written.  One type serves the write and the read —
    :meth:`NullCalibrations.record` returns what landed,
    :meth:`NullCalibrations.history` rebuilds what stands — so the row an
    operator reads and the row the table holds cannot be two things that
    disagree.

    **Frozen**, because a caller who could edit either figure in memory could
    revise a calibration prd §11's trend is read off after the trend consumed
    it — the in-memory spelling of the revision the value layer refuses — and
    because equality over the stored fields is what makes the record
    idempotent across a retry.

    Validated in :meth:`__post_init__` rather than only through the store, for
    the reason every sibling record states: ``dataclasses.replace`` and
    unpickling both rebuild instances past a factory's nose, and the *read*
    path needs the same check the write path does — SQLite's columns are
    dynamically typed, so a hand-edited row is reachable here.
    """

    #: The campaign whose planted population and committed picks the pair was
    #: taken over — the row's key, in canonical UUID text, the spelling
    #: feature 267's, 346's and 345's rows are keyed on.
    campaign_id: str
    #: **Sensitivity** — feature 266's ``TP / (TP + FN)``: of the planted
    #: reals, the fraction the campaign's committed picks found.  ``0.0`` is a
    #: campaign that found none of its reals (the honest answer for a policy
    #: that committed to nothing at all); ``1.0`` one that found every one.
    sensitivity: float
    #: **Specificity** — feature 266's ``TN / (TN + FP)``: of the planted
    #: nulls, the fraction the campaign correctly left uncommitted — the class
    #: ``1 − specificity`` a false discovery rides on.
    specificity: float
    #: When this row was written — a label, not a measurement, and the field
    #: the trend read orders by.
    recorded_at: str

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the same
        # discipline feature 340's record, feature 347's and every sibling
        # value in this workspace follow.
        object.__setattr__(self, "campaign_id", _the_campaign(self.campaign_id))
        object.__setattr__(
            self, "sensitivity", _the_figure(self.sensitivity, "sensitivity")
        )
        object.__setattr__(
            self, "specificity", _the_figure(self.specificity, "specificity")
        )
        object.__setattr__(self, "recorded_at", _the_instant(self.recorded_at))

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a later reporter or expose-surface reads the row through:
        the table's four columns under the record's own field names.
        """
        return {
            "campaign_id": self.campaign_id,
            "sensitivity": self.sensitivity,
            "specificity": self.specificity,
            "recorded_at": self.recorded_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"NullCalibration(campaign_id={self.campaign_id!r}, "
            f"sensitivity={self.sensitivity!r}, "
            f"specificity={self.specificity!r})"
        )


def _the_campaign(value: Any) -> str:
    """The row's key — the campaign id in canonical UUID text, or a refusal.

    The canonicalisation is the join law this workspace already states
    (feature 267's per-campaign row is keyed this way because the value joins
    ``node.campaign_id`` and every reader of the campaign row resolves it;
    features 345's and 346's rows land under the same key, and this table's
    rows join all of them), restated here in this member's own words rather
    than imported: a member spells the join it performs in its own words, and
    the cross-member suites pin the spellings agree.  A :class:`uuid.UUID` or
    text one parses is canonicalized through :mod:`uuid`, so a mixed-case or
    braced spelling upserts onto the one row rather than making one campaign
    look like two — and anything else is refused, because an id that cannot
    join the tree's campaign key names no campaign a calibration pair could be
    persisted for.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise NullCalibrationError(
        f"campaign {value!r} ({type(value).__name__}) is not a UUID: the "
        f"per-campaign row is keyed by the campaign id that joins "
        f"node.campaign_id and the member's other research rows (feature "
        f"267's FDR_deploy row, 346's discovery-rate row, 345's Type-B depth "
        f"row), so an id that cannot join them names no campaign a "
        f"calibration pair could be persisted for — and §16's research "
        f"metrics are per campaign, so a row attributed to no campaign is a "
        f"figure nobody can track. Hand the campaign's id — a UUID or its "
        f"text, in any spelling uuid.UUID parses (feature 344)"
    )


def _the_figure(value: Any, field: str) -> float:
    """One calibration figure — a fraction of one planted class, or a refusal.

    The same quantity, the same bound, one spelling: ``[0, 1]`` is the fact
    feature 266's own value layer states for the pair (its
    :func:`~scoring._calibration._require_figure`), and this store restates it
    for the two columns it holds rather than importing it — a member spells
    its own contract, and importing the scoring member's private helper would
    put a sibling's module on this store's import path for a bound that is one
    line to state.

    ``int`` admitted and narrowed (``0`` and ``1`` are measurements), ``bool``
    refused before it (a ``bool`` is an ``int`` in Python's hierarchy and not
    a fraction of a planted class), NaN and ±inf refused because a figure that
    is not a measurement cannot condition on a class, and an out-of-bound
    figure refused rather than clamped — the likeliest thing wearing either
    name being a *count* of found reals or of clean nulls handed where the
    fraction belongs, which clamped to an endpoint would persist a calibration
    nobody measured.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NullCalibrationError(
            f"{field} must be feature 266's calibration figure — a fraction "
            f"of one planted class (TP/(TP+FN) for sensitivity, TN/(TN+FP) "
            f"for specificity) handed over already measured — as a real "
            f"number in [0.0, 1.0], got {value!r} "
            f"({type(value).__name__}). prd §4.1.3's pair is what "
            f"FDR_deploy is reweighted from, and a value that is not a real "
            f"is not a fraction of a class (feature 344, prd §4.1.3)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise NullCalibrationError(
            f"{field} must be finite, got {narrowed!r}: a NaN would make one "
            f"half of feature 266's pair a NaN the reweighting silently "
            f"drops, and an infinity is not a fraction of a planted class "
            f"(feature 344, prd §4.1.3)"
        )
    if not 0.0 <= narrowed <= 1.0:
        raise NullCalibrationError(
            f"{field} must be a figure in [0.0, 1.0], got {narrowed!r}: the "
            f"figure is a fraction of one planted class — the reals it "
            f"found, or the nulls it left alone — so it is bounded by "
            f"construction. A value outside the bound is not a high figure; "
            f"it is a number that has stopped being one, and the likeliest "
            f"thing wearing its name is a *count* of nodes, which feature "
            f"266's verb refuses to let out and this store refuses to "
            f"receive (feature 344, prd §4.1.3)"
        )
    return narrowed


def _the_instant(recorded_at: Any) -> str:
    """The row's label — the caller's instant, or the wall clock's now.

    ``recorded_at`` defaults to *now* (UTC, second resolution — the spelling
    :meth:`datetime.datetime.isoformat` produces and the one the trend read's
    ``ORDER BY`` stays chronological under), because a caller that closed a
    campaign out at a known instant passes it so the row's label matches the
    measurement rather than the write.  An explicit instant must be a
    non-empty string — it orders the trend, and a label that is not a nameable
    instant orders nothing.
    """
    if recorded_at is None:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise NullCalibrationError(
            f"a calibration row's recorded_at is an ISO 8601 UTC string — got "
            f"{recorded_at!r} ({type(recorded_at).__name__}). The instant is "
            f"the label the trend's order reads, so a value that is not a "
            f"nameable instant orders prd §11's track by nothing; pass the "
            f"instant the campaign's pair was measured at, or nothing and let "
            f"the write stamp its own (feature 344)"
        )
    return recorded_at


class NullCalibrations:
    """§16's planted-null calibration pair, in the relational store the
    deployment names.

    Constructed with the database URL it persists into; :meth:`record` lands
    one campaign's pair as its row, :meth:`calibration` answers one campaign's
    pair, and :meth:`history` answers every campaign's oldest-first — the
    sequence prd §11 tracks the figures across (*"tracked, not targeted"*).
    The class resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every store in
    this workspace states — and the schema is created idempotently on the
    first connect, so no migration step is needed.

    Hand-written with ``__slots__`` and no ``__dict__``: a store is a holder,
    not a value, and there is no shadow state beside the URL for a caller to
    park a figure in.  Not frozen: the URL it holds is live deployment state,
    and the rows live in the database, never in the process — the store caches
    none of the pairs it wrote, so a pair read back is a fact about the world
    rather than about this process's history.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: Any) -> None:
        # The URL is held, not resolved: validating it would touch the
        # filesystem or parse a scheme, and constructing a store is
        # composition-time work (the builder runs on every create_app()) that
        # must not refuse.  A URL this store cannot speak is refused by name
        # at first use, where the operator's repair belongs.
        if not isinstance(database_url, str) or not database_url.strip():
            raise NullCalibrationError(
                f"the calibration store is constructed with a database URL, "
                f"and this one is not a non-empty string (got "
                f"{database_url!r}, {type(database_url).__name__}): pass the "
                f"relational store to persist the planted-null pair into — "
                f"sqlite:///path/to/store.db, the spelling every member store "
                f"in this workspace takes (feature 344, docs §16)"
            )
        self._database_url = database_url.strip()
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Any = None) -> NullCalibrations | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        calibration component — a discoverable state, not an exception — while
        the caller that must persist a pair is the one that must not find
        itself in it.  The split is the one every resolve-shaped builder in
        this workspace states: this method answers *what is composed*, and the
        caller who needs a row and resolves ``None`` refuses to proceed rather
        than silently persisting nowhere — a trend with a hole in it exactly
        where a campaign's calibration was measured is the quietly-defaulted
        figure this category exists to rule out, and prd §11 tracks the figures
        across these rows.
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

        Nothing is created at construction — the URL is translated (and a URL
        this store cannot speak is refused by name) the first time an operation
        needs it, which is the same laziness every store class in this
        workspace states for the same reason.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The verbs ------------------------------------------------------------

    def record(
        self,
        campaign_id: Any,
        *,
        sensitivity: Any,
        specificity: Any,
        recorded_at: Any = None,
    ) -> NullCalibration:
        """Persist one campaign's planted-null calibration pair — feature 266's
        two figures, handed over already measured.

        ``campaign_id`` names the campaign (canonicalised to UUID text, §16's
        per-campaign grain, the row's key); ``sensitivity`` and
        ``specificity`` are **feature 266's own figures** —
        :class:`scoring.CalibrationFigures`' fields, ``TP/(TP+FN)`` and
        ``TN/(TN+FP)`` over the campaign's planted population, which the
        caller that ran the calibration verb hands over verbatim because the
        fractions, the labels beneath them and the join that produces them are
        the scoring member's and the null oracle's, never this store's;
        ``recorded_at`` defaults to *now* (UTC, second resolution), and a
        caller that closed the campaign out at a known instant passes it so the
        row's label matches the measurement.

        **The store computes nothing**, and there are deliberately no
        parameters for any derived quantity at any spelling — no base rate (a
        caller able to pick π₀ could pick the figure feature 267's target is
        judged on), no ``FDR_deploy`` (267's arithmetic over exactly this
        pair), no blend, no average, no rate over the two and no interval
        around either: a caller-stated interval would be an unreconciled
        claim persisted on trust, and the pair's own documents fix no
        resolution for one.  The two figures are what the sentence
        (*"persists sensitivity and specificity on planted nulls per
        campaign"*) asks this store to land, so they are the two figures it
        lands.

        The ask is validated whole — the campaign, both figures, the instant —
        **before a connection is opened**, so a malformed ask never reaches
        the store and a refused record leaves no half-written row and no
        database file at all.  The write is an upsert on the campaign's key:
        the pair is a deterministic function of the campaign's planted
        population and its committed picks — both append-only facts — so a
        re-run is the same measurement written twice, the measured columns
        refresh and the row's original ``recorded_at`` stands, the law feature
        267 states for its own per-campaign row.

        Returns:
            The :class:`NullCalibration` **the table holds** — read back inside
            the same transaction as the write, so the figures and the instant
            in the answer are the row's own rather than the arguments'.

        Raises:
            NullCalibrationError: The ask, refused — an id that is not a UUID,
                a figure that is not a finite real in ``[0, 1]`` (a ``bool``,
                a count, text, ``None``, NaN, an infinity), an instant that is
                not a nameable label; and any failure of the store itself,
                chained to the original and deliberately not swallowed — a
                pair that measured but never landed is the state this feature
                exists to rule out.
        """
        campaign = _the_campaign(campaign_id)
        measured = _the_figure(sensitivity, "sensitivity")
        clean = _the_figure(specificity, "specificity")
        instant = _the_instant(recorded_at)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _UPSERT,
                    (
                        campaign,
                        measured,
                        clean,
                        instant,
                    ),
                )
                row = connection.execute(_SELECT_ROW, (campaign,)).fetchone()
        except NullCalibrationError:
            raise
        except (sqlite3.Error, OSError) as exc:
            # The store's own failure, translated: a caller catching this
            # member's base class must catch a pair that measured but never
            # landed, and the original is chained so the operator still sees
            # the database's own words — never swallowed, never retried over a
            # measurement that already landed.
            raise NullCalibrationError(
                f"could not persist the planted-null calibration for campaign "
                f"{campaign!r} into the store: {exc!r}. The pair is docs §16's "
                f"research metric and prd §11's secondary scorecard row, whose "
                f"grade (*tracked*) is read across these rows — so a pair that "
                f"measured but never landed is the state feature 344 exists to "
                f"rule out, and a missing row reads as a campaign nobody "
                f"calibrated. The failure is surfaced, and the repair is the "
                f"store's (the original refusal is chained), never a "
                f"re-measure over a campaign whose planted population and "
                f"committed picks the append-only ledger already holds "
                f"(feature 344, docs §16, prd §11)"
            ) from exc
        if row is None:  # pragma: no cover - the write landed in this transaction
            raise NullCalibrationError(
                f"the calibration pair for campaign {campaign!r} could not be "
                f"read back after the write. prd §11 tracks these figures "
                f"across campaigns, so a row this store cannot vouch for is a "
                f"calibration an operator would be tracking blind (feature "
                f"344)"
            )
        return _record_from_row(row)

    def calibration(self, campaign_id: Any) -> NullCalibration | None:
        """One campaign's standing pair, or ``None`` when it holds none.

        The point read — the answer to *what were this campaign's sensitivity
        and specificity on the planted nulls?* for a caller holding one
        campaign.  ``None`` is the honest absent answer (the campaign has
        closed no row out, or this deployment never measured one), never a
        pair of zeros: ``0.0`` is a *measurement* — a campaign that found none
        of its reals — where ``None`` is an absence, and a caller that could
        not tell them apart would read a research programme that found nothing
        out of a missing row.  The same stance feature 267's ``fdr`` takes
        toward an unclosed campaign, feature 345's ``depth`` and 346's ``rate``
        toward the same, feature 347's ``gap`` toward an unclosed cycle and
        feature 350's ``latest`` toward an unrecorded metric.
        """
        campaign = _the_campaign(campaign_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_SELECT_ROW, (campaign,)).fetchone()
        except NullCalibrationError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise NullCalibrationError(
                f"could not read the calibration pair for campaign "
                f"{campaign!r} from the store: {exc!r}. The pair is prd §11's "
                f"secondary scorecard row, so a store that cannot be asked is "
                f"surfaced rather than answered around; the repair is the "
                f"store's (the original refusal is chained) (feature 344, docs "
                f"§16, prd §11)"
            ) from exc
        return None if row is None else _record_from_row(row)

    def history(self) -> tuple[NullCalibration, ...]:
        """Every campaign's pair on record, oldest first — the trend read.

        prd §11 grades the pair by *tracking*, not against a bar —
        *"Sensitivity / specificity on planted nulls (base-rate independent) |
        tracked, not targeted"* — so a reading is a comparison against what
        came before it, and that is the order this answers in: by the row's own
        instant, with the campaign's id breaking same-instant ties (§12's
        ordering rule).  An empty tuple is the honest answer for a deployment
        that has closed no campaign out: a discoverable state, not an exception
        and never a fabricated first point.

        The store computes no direction of its own and no statistic over the
        sequence: whether the figures are moving is the reader's judgment, and
        a slope, an average or a verdict here would be this member inventing
        the very reading prd §11 pointed at *"tracked"* on purpose.  What the
        rows carry is what the judgment needs — two figures per campaign, and
        nothing over them.

        Fails with :class:`~ops.errors.NullCalibrationError` when the store
        could not be read, and when a stored row is not a row this store could
        have written — the refusal, not a skip: a skipped row is a campaign's
        calibration wearing a shrug, and prd §11's track is read across this
        sweep.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(_SELECT_HISTORY).fetchall()
        except NullCalibrationError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise NullCalibrationError(
                f"could not read the calibration history from the store: "
                f"{exc!r}. The sequence is what prd §11's *tracked* is read "
                f"across, so a store that cannot be asked is surfaced rather "
                f"than answered around; the repair is the store's (the "
                f"original refusal is chained) (feature 344, docs §16, prd "
                f"§11)"
            ) from exc
        return tuple(_record_from_row(row) for row in rows)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the store and the URL it holds — a URL is not a secret, and a
        # repr is a debugging aid — and nothing else: the rows live in the
        # database, and the figures are the caller's.
        return f"{type(self).__name__}({self._database_url!r})"

    # -- The connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The URL is translated on first use (a scheme this store cannot speak is
        refused by name here, at the operation that needed it), the schema is
        created idempotently (``CREATE TABLE IF NOT EXISTS``, the contract
        every store in this workspace states), and the caller owns the
        connection — use it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection


def _record_from_row(row: Any) -> NullCalibration:
    """Rebuild one stored row, refusing a value no calibration row can be.

    The refusal is the point: this table is written by this store, but SQLite
    will accept anything another tool inserts, and a row wearing an id that is
    not a campaign or a figure that is not a fraction of a class would
    otherwise reach prd §11's trend as a calibration nobody measured.  The
    value layer performs the validation (one spelling of it, shared with the
    write path) and this re-read *names the campaign the bad row came from*, so
    an operator gets the row to repair rather than a complaint about a value
    with no address — the discipline feature 340's ``_from_row`` and features
    345/346/347's state for their own tables, restated in this member's
    vocabulary.
    """
    try:
        return NullCalibration(
            campaign_id=row[0],
            sensitivity=row[1],
            specificity=row[2],
            recorded_at=row[3],
        )
    except NullCalibrationError as refusal:
        raise NullCalibrationError(
            f"{refusal} — the row this came from is the planted-null "
            f"calibration recorded for campaign {row[0]!r} at {row[3]!r}, "
            f"holding sensitivity {row[1]!r} and specificity {row[2]!r} "
            f"(feature 344)"
        ) from refusal


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — this store's own spelling
    of the translation every store in this workspace performs.

    Only ``sqlite:///`` speaks (docs §16's single-machine allowance), any other
    scheme refused loudly rather than silently mis-parsed so a misrouted
    Postgres URL cannot hide behind a mysterious file, no host but
    ``localhost`` admitted, and a URL with no path refused — the same three
    refusals the live-metrics store, the meta-overfit gap store, the
    discovery-rate store and the Type-B depth store beside this one state for
    their own connections, restated because a member states its own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise NullCalibrationError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            f"calibration store speaks sqlite:/// (docs §16's 'single Postgres "
            f"metrics table', the simpler option the section defends at this "
            f"scale), the same refusal every store in this workspace documents "
            f"— a Postgres metrics table arrives with the versioned migration "
            f"member, and pretending to speak it here would hide a misrouted "
            f"URL behind a mysterious file (feature 344)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise NullCalibrationError(
            f"the calibration store's sqlite {DATABASE_URL_ENV} must not carry "
            f"a host, got {parsed.netloc!r} (feature 344)"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise NullCalibrationError(
            f"the calibration store's sqlite {DATABASE_URL_ENV} carries no "
            f"database path (feature 344)"
        )
    return Path(path)
