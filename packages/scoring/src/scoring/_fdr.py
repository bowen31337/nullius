"""Feature 267, the deployed false discovery rate — prd §4.1.3's
reweighting of feature 266's pair at the deployment base rate, persisted
as one row per campaign.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 267:
*System persists FDR_deploy per campaign, computed by reweighting
sensitivity and specificity to a deployment base rate of 0.9.*  It
declares ``depends_on="266"`` — the pair is the measurement this
projection is priced on — and it is the category's closing arithmetic:
docs/alpha-engine-prd.md §4.1.3 states the formula (line 147) and the
number this module spells once as :data:`DEPLOYMENT_BASE_RATE`::

    FDR_deploy = π₀(1 − specificity) / [ π₀(1 − specificity) +
                                         (1 − π₀)·sensitivity ]
                                     with π₀ ≈ 0.9

Why the reweighting exists is §4.1.3's own argument (lines 141-151): in
real quant research the fraction of hypotheses with zero true edge is
roughly 90-95%, while a campaign plants nulls at the φ §4.1.1's floor
rule shades to ~0.25, so *"calibrating on a 25%-null population and
deploying into a 92%-null reality produces a systematically
under-skeptical policy"* — and the fix is not to raise φ (which would
gut discovery throughput) but to *"measure them where you have power
for both, then reweight"*, because sensitivity and specificity are
conditional within a ground-truth class and the campaign's design
constant cancels.  docs/nullius-tech-architecture.md §10.3 lines
509-515 places the emission inside the scorer's own paragraph — *"The
scorer also emits ``FDR_deploy``, reweighted to the deployment base
rate"* — and closes with the sentence the next feature (268's) enforces
at the dashboard: *"**``FDR_deploy`` is the dashboard number.  The raw
rate never is.**"*  prd §11 makes the figure the system's primary
metric (line 536: *"``FDR_deploy`` — base-rate-reweighted false
discovery rate (§4.1.3)"*, target *"< 25% at π₀ = 0.9"*), prd §12's M3
exit reads it across campaigns (line 598: *"`FDR_deploy` improves at π₀
= 0.9"*), and docs §16 lists it first among the research metrics (line
909: *"per campaign: ``FDR_deploy`` at π₀ = 0.9"*) — the per-campaign
row this module persists is that figure's own seat, and §16's *"at
π₀ = 0.9"* is why the base rate travels in the row beside the number.

**The pair is handed over, never derived — the barrier holds at the
store.**  The division is the one feature 258's β₂ term states for the
rate and keeps for every figure after it: the rate is *"handed over,
never derived here"*, because deriving it means reading ``is_null``, the
bit prd §4.2 grants to exactly one component — and feature 266's pair
is two more answers off the same held labels, computed by the verb that
process grew.  This module consumes the measurement exactly as 258
consumes the rate: :func:`fdr_deploy` takes the pair duck-typed (any
carrier exposing ``sensitivity`` and ``specificity``, feature 266's
:class:`~scoring.CalibrationFigures` among them — never an
``isinstance``, because the loader imports members under synthetic
names and a class check would refuse the very value composition
produced), and the store persists what it is handed.  Nothing here
holds a sidecar key, reads a label, or grows a second seam the barrier
would have to hold: the campaign's close-out asks the process for the
pair (266's verb), hands it here, and the labels stay where §4.2 put
them — which is also why this store is honestly testable without a
sidecar: its whole input is the pair and the campaign's name.

**One corner is undefined at every base rate, and it is refused.**  The
denominator ``π₀(1 − specificity) + (1 − π₀)·sensitivity`` vanishes
exactly when both its terms do — ``specificity 1.0`` (no null was ever
committed) and ``sensitivity 0.0`` (no real was ever found) — and any
commitment is to a real or to a null, so that pair is precisely feature
266's honest answer for *a campaign that committed to nothing* (the
corner that verb deliberately answers, ``0.0`` and ``1.0``, where the
rate's own empty ask is refused).  The projection of that corner is
``0/0``: a false discovery rate is a fraction of *declarations*, a
campaign that declared none has no fraction at any π₀, and reading the
corner as ``0.0`` would answer *"a flawless policy"* for one that never
ran — the stand-in §4.1.3 refuses to buy.  The refusal is this
feature's own and not 266's, because the two stances answer different
questions about different denominators: the pair *is* measurable over a
planted population that committed to nothing, and the reweighted rate
over its declarations *is not* — the same shape of split, one feature
apart, that 266's docstring states against 265's empty-pick refusal.
Every other corner is a measurement and both ends are honoured:
``specificity 1.0`` with any sensitivity found reweights to ``0.0``
(a campaign that never committed a null projects to no false
discoveries), and ``sensitivity 0.0`` with any specificity below one
reweights to ``1.0`` (a campaign that finds no reals projects every
declaration false — the honest reading of a policy that only ever
commits to noise).

**Per campaign, keyed by the campaign's own id.**  The row's unit is
the feature's own clause — *per campaign* — and the key is the
campaign id in the canonical spelling every reader of the campaign
resolves: canonical UUID text, the law the discovery member's planner
states for the value that joins ``node.campaign_id`` (restated here,
never imported, for the reason every seam in this workspace restates a
sibling's boundary: a member spells the join it performs in its own
vocabulary, and the cross-member suites pin the spellings agree).  A
re-run of a campaign's close-out upserts onto the one row —
refresh-not-append, the stance the discrimination refresh takes for its
own per-campaign figure — because the figures are deterministic in the
plant and the picks, so a second ask that agreed is the same
measurement written twice, and the refresh arm deliberately does not
touch ``computed_at``: the first instant the row was computed is a fact
about the trend's history a retry must not rewrite.

**The row carries the measurement, and the figure is a derived view
over it.**  :data:`FDR_DEPLOY_TABLE`'s truth columns are the pair —
``sensitivity`` and ``specificity``, the measurement 266 made — beside
the ``base_rate`` the projection was taken at and the ``fdr_deploy``
the formula answers; reading a row back *rebuilds* the figure from the
pair under the one constant, never trusting the denormalised column, so
the row round-trips and a stored figure that disagrees with its own
pair is refused by name — the law the replay member's latency store
states for its samples and this store restates for its pair.  The base
rate is persisted with the figure because §16's own line carries the
qualifier — *"``FDR_deploy`` at π₀ = 0.9"* — and a reader of a stored
number must never have to guess which projection it was; a row whose
base rate is not the deployment's is refused rather than recomputed at
what it finds, because a figure reweighted at a rate nobody pinned is a
number nobody targeted.

**The store is the workspace's one relational store, addressed the way
every member store addresses it.**  ``DATABASE_URL``, ``sqlite:///`` on
a single machine (docs §16's *"single Postgres metrics table ... the
simpler option is defensible"*, the spelling the replay member's
metrics store and the bootstrap member's pool take), the schema created
idempotently on connect — ``CREATE TABLE IF NOT EXISTS``, the contract
every store in this workspace states — so no migration step is needed
and no shared schema file is touched.  The class resolves its path
lazily, so constructing one performs no I/O: composition-time work must
not touch the disk.  The ask is validated whole — campaign, pair,
reweighting — before a connection is opened, the ordering this member
states for every read and the replay member states for its write: a
broken ask never reaches the store.  The store's own failures (no
configured ``DATABASE_URL``, a scheme it cannot speak, a locked or
unwritable database) surface in this module's vocabulary with the
original chained, never swallowed — a figure that measured but never
landed is the state this feature exists to rule out, exactly as a cost
model that resolved but never persisted is feature 59's.

**The component beside the objective and the process.**  This is the
member's third component name and its second store-bound one — the
growth this member's own registration reserved when feature 265 landed
(*"feature 267's FDR store when it lands"*) and the app-package seat
reserved beside it (*"another component name, another sibling seat,
this module's surface untouched"*).  :data:`FDR_COMPONENT_NAME`
(``scoring-fdr-deploy``) registers a builder that resolves
``DATABASE_URL`` and answers ``None`` when nothing names a store — the
degrade-don't-break stance every store-bound builder here takes, for
the same reason the pool's and the scorer's builders take it: the
factory builds every component on every ``create_app()`` call, and a
deployment without a relational store must still compose.  *No store is
configured* and *the store is broken* are different facts, and only the
second may ever be quiet; a caller that needs the row refuses to
proceed rather than persisting nowhere — the same split the scorer
seat's ``None`` states against the objective seat's.

**What this law deliberately does not do.**  It stores no raw
in-campaign rate — not as a column, not as a fallback figure — because
prd §4.1.3's sentence (*"the raw in-campaign rate is an artifact of a
design choice and must never be the figure on the dashboard"*) is the
next feature's rejection (268's) and this table exists to be the number
that rejection leaves standing; a caller handing the rate where the
pair belongs is refused with the substitution named.  It computes no
sensitivity or specificity (feature 266's verb on the process) and
reads no label (feature 265's grant).  It charges nothing — no β-term
reads this figure, because a term over a base-rate projection would
steer the loop on a projection of what the policy *would* do rather
than the error it made, the argument feature 258's docstring states and
the accounting holds for the same reason.  It computes no verdict on
the trend — M3's *"`FDR_deploy` improves"* is a reader's comparison
across the rows :meth:`FdrDeployStore.history` answers, and a store
that grew a verdict would be the gate living in two places.  It renders
no dashboard (268's sentence and the observability member's) and
persists no row but its own: the ``replay_score`` row is the replay
plugin's (feature 255), the research-metrics row is the ops member's
(feature 344, which reads the pair 266 measures into its own store),
and this table's one subject is the reweighted figure per campaign.

Stdlib only, and import-cheap: :mod:`datetime` for the row's label,
:mod:`math` for the finiteness gate, :mod:`os` for the one ambient the
workspace's stores share, :mod:`sqlite3` for the store,
:mod:`uuid` for the key, :mod:`contextlib`/:mod:`pathlib`/:mod:`urllib.parse`
for the connection's plumbing, :mod:`numbers` for the figures — no
third-party import at module scope, so the factory's scan (which
imports this package to fire its ``@register`` builders) pays nothing
for the law.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import uuid
from contextlib import closing
from numbers import Real
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._nullpicks import RATE_BOUND
from .errors import FdrDeployError

__all__ = [
    "DATABASE_URL_ENV",
    "DEPLOYMENT_BASE_RATE",
    "FDR_COMPONENT_NAME",
    "FDR_DEPLOY_TABLE",
    "FdrDeployStore",
    "fdr_deploy",
]

#: The environment variable naming the relational store — the one
#: spelling every member store in this workspace already uses (the
#: bootstrap member's pool, the replay member's metrics and score rows,
#: the discovery member's campaign records), restated here so this
#: module states its own contract and imports no sibling's.  §16's
#: "single Postgres metrics table", ``sqlite:///`` on a single machine.
DATABASE_URL_ENV = "DATABASE_URL"

#: The deployment base rate π₀ — feature 267's own number, spelled once.
#: prd §4.1.3 fixes it ("with π₀ ≈ 0.9", line 148) on the ground the
#: section opens with ("the fraction of hypotheses with zero true edge
#: is roughly 90-95%", line 141); §11's primary target carries the same
#: qualifier ("< 25% at π₀ = 0.9", line 536) and §12's M3 exit reads the
#: figure at it (line 598).  A constant, not a parameter: the projection
#: this module answers is *the* deployment projection, the number the
#: dashboard and the M3 gate read, and a caller able to pick a π₀ would
#: be able to pick the figure the target is judged on.  The reweighting
#: at any other base rate is a different number nobody asked this seam
#: for.
DEPLOYMENT_BASE_RATE: float = 0.9

#: The component name the FDR_deploy store registers under — this
#: member's third, beside :data:`~scoring.COMPONENT_NAME` (the
#: objective) and :data:`~scoring.SCORER_COMPONENT_NAME` (the scorer
#: process) the way ``bootstrap-pool`` sits beside ``bootstrap``.  The
#: growth was reserved by the member's own registration when 265 landed
#: ("267's FDR store when it lands ... another component name, another
#: sibling seat"), spelled here once, imported by the member's
#: ``__init__``, and read by name through the composed application.
#: Prefixed
#: with the member's own name because a composed application's
#: ``order`` is name-sorted and the store must sort *beside* — never
#: inside — the member's other components.
FDR_COMPONENT_NAME = "scoring-fdr-deploy"

#: The table the per-campaign FDR_deploy rows live in — this member's
#: own, in the relational store ``DATABASE_URL`` names, created
#: idempotently on connect so no migration step is needed and no shared
#: schema file is touched.  Named member-first and figure-second (the
#: way ``bootstrap_world`` and ``replay_score`` are named) so a reader
#: of the store can tell whose research row it is holding: the ops
#: member's metrics store is 344's, and this one is the scoring
#: member's own.
FDR_DEPLOY_TABLE = "scoring_fdr_deploy"

_SCHEMA = f"""
-- Feature 267: FDR_deploy per campaign, reweighted to the deployment
-- base rate (docs §16's research metrics, line 909: "FDR_deploy at
-- π₀ = 0.9"; docs §10.3 lines 509-515: the scorer emits it because the
-- figures are base-rate independent while the raw in-campaign rate is
-- an artifact of φ).
--
-- The primary key is `campaign_id` (canonical UUID text) — the unit the
-- feature's own sentence names. One row per campaign, keyed by the id
-- that joins `node.campaign_id` and the discovery member's campaign
-- record (feature 232's), so a reader of the trend resolves each figure
-- to the campaign whose plant and picks measured it.
--
-- `sensitivity` and `specificity` are the source of truth: feature
-- 266's measured pair, handed over already computed. `fdr_deploy` is a
-- derived view over them under the formula at the stored `base_rate`,
-- and every read rebuilds it from the pair rather than trusting the
-- column, so a row round-trips losslessly and one that disagrees with
-- its own pair is refused, not read. `base_rate` travels with the
-- figure because §16's own line carries the qualifier — "at π₀ = 0.9" —
-- and a reader must never guess which projection a stored number was.
--
-- `computed_at` is a label, not a measurement: when the row was
-- written (ISO 8601 UTC, second resolution — string order is
-- chronological, which is the order the history read answers, the
-- direction prd §12's M3 "improves" reads across). The upsert's
-- refresh arm deliberately does not touch it — a re-run of a campaign's
-- close-out is the same measurement (the figures are deterministic in
-- the plant and picks), and the first instant the row was computed is
-- a fact about the trend's history a retry must not rewrite.
CREATE TABLE IF NOT EXISTS {FDR_DEPLOY_TABLE} (
    campaign_id TEXT NOT NULL,  -- canonical UUID text: the campaign the pair was measured on
    base_rate   REAL NOT NULL,  -- π₀ the figure was reweighted at (0.9)
    sensitivity REAL NOT NULL,  -- the measurement: feature 266's first figure
    specificity REAL NOT NULL,  -- the measurement: feature 266's second figure
    fdr_deploy  REAL NOT NULL,  -- derived: π₀(1−spec)/[π₀(1−spec)+(1−π₀)·sens]
    computed_at TEXT NOT NULL,  -- ISO 8601 UTC: when this row was written
    PRIMARY KEY (campaign_id)
);
"""

#: The per-campaign write: an upsert on the campaign's own key.
#: ``ON CONFLICT`` refreshes the measured columns — a re-run of the same
#: campaign's close-out is the same measurement written twice — and
#: leaves ``computed_at`` alone, for the reason the schema comment
#: above spells.
_UPSERT = f"""
INSERT INTO {FDR_DEPLOY_TABLE} (
    campaign_id, base_rate, sensitivity, specificity, fdr_deploy, computed_at
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(campaign_id) DO UPDATE SET
    base_rate   = excluded.base_rate,
    sensitivity = excluded.sensitivity,
    specificity = excluded.specificity,
    fdr_deploy  = excluded.fdr_deploy
"""

#: One campaign's row, every column of it — the read the reader rebuilds
#: the figure from, positional in the SELECT's order (the store
#: conventions of this workspace set no row factory).
_SELECT_ROW = (
    f"SELECT campaign_id, base_rate, sensitivity, specificity, "
    f"fdr_deploy, computed_at FROM {FDR_DEPLOY_TABLE} WHERE campaign_id = ?"
)

#: Every campaign's row, oldest first — the trend read, in the direction
#: prd §12's M3 exit reads ("FDR_deploy improves", a falling sequence).
_SELECT_HISTORY = (
    f"SELECT campaign_id, base_rate, sensitivity, specificity, "
    f"fdr_deploy, computed_at FROM {FDR_DEPLOY_TABLE} "
    f"ORDER BY computed_at ASC, campaign_id ASC"
)


# -- the reweighting ---------------------------------------------------------


def fdr_deploy(figures: object) -> float:
    """Answer §4.1.3's projection — feature 266's pair, reweighted to
    the deployment base rate — as one bare ``float`` in ``[0, 1]``.

    ``figures`` is the calibration measurement the projection is priced
    on, handed over already computed: feature 266's
    :class:`~scoring.CalibrationFigures` or any carrier exposing its
    two figures (``sensitivity`` and ``specificity``), read duck-typed
    and validated as read — a real, finite number in ``[0, 1]`` each —
    because the loader imports members under synthetic names and a
    class check would refuse the very value composition produced, and
    because a duck-typed carrier owes the proof a constructor no longer
    stands behind.  A bare number is refused outright, and the refusal
    names the likeliest one: the raw in-campaign rate, the figure prd
    §4.1.3 bars from the dashboard and this seam refuses as an input —
    it is not the pair, and no arithmetic on one number can recover the
    two the formula needs.

    The arithmetic is the formula spelled once:
    ``π₀(1 − specificity) / [π₀(1 − specificity) + (1 − π₀)·sensitivity]``
    at :data:`DEPLOYMENT_BASE_RATE`.  Both ends of ``[0, 1]`` are
    measurements and both are honoured — ``0.0`` the projection of a
    campaign that never committed a null, ``1.0`` the projection of one
    that finds no reals and declares anyway.  The one corner refused is
    ``sensitivity 0.0`` with ``specificity 1.0``: feature 266's honest
    answer for a campaign that committed to nothing, whose projection
    is ``0/0`` at every base rate — a rate over declarations is
    undefined for a campaign that made none, and unknown is not zero
    (the stance this family takes toward every empty denominator, from
    the rate's empty ask to the figures' empty classes).

    Deterministic and pure: the same pair answers the same figure to
    the bit — three products, one sum, one division — with no clock, no
    store and no environment inside the verb.
    """
    sensitivity, specificity = _the_figures(figures)
    return _reweighted(sensitivity, specificity)


# -- the store ----------------------------------------------------------------


class FdrDeployStore:
    """§16's per-campaign FDR_deploy rows, in the relational store the
    deployment names.

    Constructed with the database URL it writes to; :meth:`persist`
    lands one campaign's reweighted figure as its row,
    :meth:`fdr` reads one campaign's figure back (rebuilt from the pair
    the row carries, never from the denormalised column), and
    :meth:`history` answers every campaign's figure oldest-first — the
    sequence prd §12's M3 *"improves"* is read across.  The class
    resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every
    store in this workspace states — and the schema is created
    idempotently on the first connect, so no migration step is needed.

    Hand-written with ``__slots__`` and no ``__dict__``: a store is a
    holder, not a value, and there is no shadow state beside the URL
    for a caller to park a figure in.  Not frozen: the URL it holds is
    live deployment state, and the rows live in the database, never in
    the process — the store holds no cache of the figures it wrote, the
    same stance the campaign planner's store takes, so a figure read
    back is a fact about the world rather than about this process's
    history.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: str) -> None:
        # The URL is held, not resolved: validating it would touch the
        # filesystem or parse a scheme, and constructing a store is
        # composition-time work (the builder runs on every
        # create_app()) that must not refuse.  A URL this store cannot
        # speak is refused by name at first use, where the operator's
        # repair belongs.
        if not isinstance(database_url, str) or not database_url.strip():
            raise FdrDeployError(
                f"the FDR_deploy store is constructed with a database URL, "
                f"and this one is not a non-empty string (got "
                f"{database_url!r}, {type(database_url).__name__}): pass the "
                f"relational store to persist the per-campaign rows into — "
                f"sqlite:///path/to/store.db, the spelling every member "
                f"store in this workspace takes (feature 267, docs §16)"
            )
        self._database_url = database_url.strip()
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Any = None) -> FdrDeployStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names
        none.

        An empty or whitespace-only value counts as unset.  Absent is
        not an error: it is a deployment without a relational store,
        which composes no FDR_deploy component — a discoverable state,
        not an exception — while the close-out that must persist the
        campaign's figure is the caller that must not find itself in
        it.  The split is the one every resolve-shaped builder in this
        workspace states: this method answers *what is composed*, and
        the caller who needs a row and resolves ``None`` refuses to
        proceed rather than silently persisting nowhere — a trend with
        a hole in it where a campaign's figure should be is exactly
        the quietly-defaulted number this feature exists to rule out.
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

        Nothing is created at construction — the URL is translated (and
        a URL this store cannot speak is refused by name) the first
        time an operation needs it, which is the same laziness every
        store class in this workspace states for the same reason.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The verbs ------------------------------------------------------------

    def persist(
        self,
        campaign: object,
        figures: object,
        *,
        computed_at: str | None = None,
    ) -> float:
        """Persist one campaign's FDR_deploy — the pair reweighted at
        :data:`DEPLOYMENT_BASE_RATE` — and answer the figure written.

        ``campaign`` is the campaign's id — a :class:`uuid.UUID` or text
        one parses, canonicalized to the spelling that joins
        ``node.campaign_id`` and the discovery member's campaign record.
        ``figures`` is feature 266's measurement, handed over already
        computed (see :func:`fdr_deploy` for the carrier contract and
        the refusals of a pair that cannot be reweighted).
        ``computed_at`` defaults to *now* (UTC, second resolution); a
        caller that closed the campaign out at a known instant passes
        it so the row's label matches the close-out, not the write.

        The ask is validated whole and the figure reweighted **before a
        connection is opened** — a malformed ask never reaches the
        store, the ordering this member states for every read — and the
        write is an upsert on the campaign's key: a re-run of the same
        campaign's close-out refreshes the measured columns and keeps
        the row's original ``computed_at``, because the figures are
        deterministic in the plant and picks and the first instant the
        row was computed is a fact about the trend's history a retry
        must not rewrite.

        Any failure of the write — an unconfigured store, an unsupported
        URL scheme, a locked or unwritable database — surfaces as
        :class:`~scoring.FdrDeployError`, chained to the original and
        deliberately not swallowed: a figure that measured but never
        landed is the state this feature exists to rule out.

        Returns:
            The ``float`` that was written — the same figure
            :func:`fdr_deploy` answers for the pair, so a caller that
            persists gets the number it stored without computing it
            twice.
        """
        campaign_id = _canonical_campaign_id(campaign)
        sensitivity, specificity = _the_figures(figures)
        figure = _reweighted(sensitivity, specificity)
        instant = _instant_of(computed_at)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _UPSERT,
                    (
                        campaign_id,
                        DEPLOYMENT_BASE_RATE,
                        sensitivity,
                        specificity,
                        figure,
                        instant,
                    ),
                )
        except FdrDeployError:
            raise
        except (sqlite3.Error, OSError) as exc:
            # The store's own failure, translated: a caller catching
            # this member's base class must catch a figure that measured
            # but never landed, and the original is chained so the
            # operator still sees the database's own words — never
            # swallowed, never retried over a pair that already
            # measured.
            raise FdrDeployError(
                f"could not persist FDR_deploy for campaign {campaign_id!r} "
                f"into the store: {exc!r}. The per-campaign figure is docs "
                f"§16's first research metric and prd §11's primary target, "
                f"so a figure that measured but never landed is the state "
                f"feature 267 exists to rule out — the failure is surfaced, "
                f"and the repair is the store's (the original refusal is "
                f"chained), never a re-run over a campaign that already "
                f"measured (feature 267, docs §16)"
            ) from exc
        return figure

    def fdr(self, campaign: object) -> float | None:
        """Read one campaign's persisted figure, or ``None`` when the
        campaign has none.

        The figure is **rebuilt from the pair the row carries** —
        :func:`fdr_deploy`'s one formula over the stored ``sensitivity``
        and ``specificity`` — never read from the denormalised
        ``fdr_deploy`` column, so the answer is the projection of the
        measurement that was written and cannot drift from it.  A row
        whose stored figure disagrees with its own pair, or whose base
        rate is not the deployment's, is refused by name: a corrupt row
        is a figure no dashboard and no M3 gate could rely on, and
        refusing it is how the rest of the trend stays trustworthy.

        ``None`` is the honest answer for a campaign whose close-out
        never persisted — a discoverable state, not an exception, and
        never a zero: ``0.0`` is a *measurement* (a campaign that
        projected to no false discoveries) where ``None`` is an
        absence, and a caller that cannot tell them apart is the caller
        §4.1.3's under-skeptical policy was made of.
        """
        campaign_id = _canonical_campaign_id(campaign)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_SELECT_ROW, (campaign_id,)).fetchone()
        except FdrDeployError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise FdrDeployError(
                f"could not read FDR_deploy for campaign {campaign_id!r} "
                f"from the store: {exc!r}. The per-campaign figure is the "
                f"number the dashboard and prd §12's M3 exit read, so a "
                f"store that cannot be asked is surfaced rather than "
                f"answered around; the repair is the store's (the original "
                f"refusal is chained) (feature 267, docs §16)"
            ) from exc
        if row is None:
            return None
        return _row_figure(row)

    def history(self) -> list[tuple[str, float, str]]:
        """Read every campaign's persisted figure, oldest first.

        ``(campaign_id, fdr_deploy, computed_at)`` triples ordered by
        the row's instant — the sequence prd §12's M3 exit reads across
        (*"`FDR_deploy` improves at π₀ = 0.9"*, a falling sequence) and
        the trend the dashboard's headline number is watched on.  An
        empty list is the honest answer for a deployment that has never
        closed a campaign out: a discoverable state, not an exception.

        Each figure is rebuilt from the pair its row carries, with the
        same corruption refusal :meth:`fdr` states — one bad row refuses
        the whole read rather than quietly answering a trend with a
        fabricated point in it.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(_SELECT_HISTORY).fetchall()
        except FdrDeployError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise FdrDeployError(
                f"could not read the FDR_deploy history from the store: "
                f"{exc!r}. The history is the sequence prd §12's M3 exit "
                f"reads the system's primary metric across, so a store "
                f"that cannot be asked is surfaced rather than answered "
                f"around; the repair is the store's (the original refusal "
                f"is chained) (feature 267, docs §16)"
            ) from exc
        return [(str(row[0]), _row_figure(row), str(row[5])) for row in rows]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the store and the URL it holds — a URL is not a secret,
        # and a repr is a debugging aid — and nothing else: the rows
        # live in the database, and the figures are the caller's.
        return f"{type(self).__name__}({self._database_url!r})"

    # -- The connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The URL is translated on first use (a scheme this store cannot
        speak is refused by name here, at the operation that needed
        it), the schema is created idempotently (``CREATE TABLE IF NOT
        EXISTS``, the contract every store in this workspace states),
        and the caller owns the connection — use it as a context
        manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection


# -- the seam's private vocabulary ---------------------------------------------


def _the_figures(figures: object) -> tuple[float, float]:
    """The ask's pair — sensitivity and specificity, read duck-typed and
    validated as read.

    The contract is the two attributes feature 266's value carries,
    read by what the carrier *is* because the loader imports members
    under synthetic names and an ``isinstance`` would refuse the very
    pair composition produced.  Each figure is defended exactly as
    :class:`~scoring.CalibrationFigures` defends it at construction —
    a real (``bool`` refused before it), finite, inside
    :data:`~scoring.RATE_BOUND` — restated because a duck-typed carrier
    owes the proof a constructor no longer stands behind, and because
    the likeliest thing wearing either name at this seam is a *count*
    of found reals or clean nulls, which an out-of-bound refusal names
    rather than clamps.

    A bare number is refused before the attributes are read, and the
    refusal names the figure it most likely is: the raw in-campaign
    rate — prd §4.1.3's artifact of φ, the number this module exists to
    replace on the dashboard and never an input to the reweighting,
    because no arithmetic on one number recovers the two the formula
    needs.
    """
    if figures is None or isinstance(figures, (bool, int, float)):
        raise FdrDeployError(
            f"FDR_deploy is reweighted from the calibration *pair* — "
            f"sensitivity and specificity, feature 266's measurement — and "
            f"this ask carried the singular figure {figures!r} "
            f"({type(figures).__name__}). The likeliest number wearing "
            f"this shape is the raw in-campaign rate, prd §4.1.3's "
            f"artifact of the campaign's φ and the figure that "
            f"reweighting exists to replace — it is not the pair, and no "
            f"arithmetic on one number recovers the two the formula "
            f"needs. Hand feature 266's CalibrationFigures, or any "
            f"carrier exposing its two figures (feature 267, prd §4.1.3)"
        )
    sensitivity = getattr(figures, "sensitivity", None)
    specificity = getattr(figures, "specificity", None)
    if sensitivity is None or specificity is None:
        raise FdrDeployError(
            f"FDR_deploy is reweighted from the calibration *pair*, and "
            f"this carrier exposes no readable one (got sensitivity="
            f"{sensitivity!r}, specificity={specificity!r} on a "
            f"{type(figures).__name__}): hand feature 266's "
            f"CalibrationFigures — answered by the scorer process's "
            f"calibration_figures verb — or any carrier exposing its two "
            f"figures; the pair is the measurement this projection is "
            f"priced on, and a carrier that does not answer it names no "
            f"measurement to reweight (feature 267, prd §4.1.3)"
        )
    return (
        _figure_value("sensitivity", sensitivity),
        _figure_value("specificity", specificity),
    )


def _figure_value(field: str, value: object) -> float:
    """Narrow one read figure to a finite ``float`` in ``[0, 1]``.

    The same narrowing, the same bound, the same words in this seam's
    own vocabulary: feature 266's constructor states it for a value it
    is about to hold, and this seam states it for a value it has just
    duck-read — the proof a carrier owes because no constructor stands
    behind it.  An out-of-bound figure is refused rather than clamped,
    the likeliest wearer of either name being a *count* of nodes, which
    clamped to an endpoint would reweight a calibration nobody
    measured.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise FdrDeployError(
            f"{field} must be a calibration figure — a fraction of a "
            f"planted class, feature 266's measurement — as a real number, "
            f"got {value!r} ({type(value).__name__}): the pair is what prd "
            f"§4.1.3's formula reweights into FDR_deploy, and a value that "
            f"is not a real is not a fraction (feature 267, prd §4.1.3)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise FdrDeployError(
            f"{field} must be finite, got {narrowed!r}: a NaN would make "
            f"the reweighted figure a NaN the store silently persisted, "
            f"and an infinity is not a fraction of a planted class "
            f"(feature 267, prd §4.1.3)"
        )
    if not 0.0 <= narrowed <= RATE_BOUND:
        raise FdrDeployError(
            f"{field} must be a figure in [0.0, {RATE_BOUND!r}], got "
            f"{narrowed!r}: the figure is a fraction of one planted class, "
            f"so it is bounded by construction. A value outside the bound "
            f"is not a high figure; it is a number that has stopped being "
            f"one, and the likeliest thing wearing its name is a *count* "
            f"of nodes, which reweighting would price as a calibration "
            f"nobody measured (feature 267, prd §4.1.3)"
        )
    return narrowed


def _reweighted(sensitivity: float, specificity: float) -> float:
    """§4.1.3's formula, spelled once — the projection both the free
    verb and the store's write answer through.

    Three products, one sum, one division, in the formula's own order,
    at :data:`DEPLOYMENT_BASE_RATE` and no other rate.  The corner the
    sum refuses is the one the module docstring argues: a pair that
    found no reals and committed no nulls is a campaign that committed
    to nothing (feature 266's answered corner), and ``0/0`` is not a
    measurement at any base rate — unknown, not zero, so the campaign
    that never declared has no false discovery rate to persist and the
    trend has no point for it.
    """
    false_alarms = DEPLOYMENT_BASE_RATE * (1.0 - specificity)
    true_alarms = (1.0 - DEPLOYMENT_BASE_RATE) * sensitivity
    denominator = false_alarms + true_alarms
    if denominator == 0.0:
        raise FdrDeployError(
            f"FDR_deploy is a fraction of the campaign's declarations, and "
            f"this pair — sensitivity {sensitivity!r}, specificity "
            f"{specificity!r} — is the measurement of a campaign that "
            f"committed to nothing: any commitment is to a real (and moves "
            f"sensitivity) or to a null (and moves specificity), so the "
            f"corner where both stand is feature 266's honest answer for "
            f"the empty declaration, and its reweighting is 0/0 at every "
            f"base rate. No fraction of declarations is defined for a "
            f"campaign that made none, and reading the corner as 0.0 would "
            f"answer a flawless policy for one that never ran — the "
            f"stand-in prd §4.1.3 refuses to buy (feature 267, prd §4.1.3)"
        )
    return false_alarms / denominator


def _canonical_campaign_id(value: object) -> str:
    """The campaign's id in the row's key spelling: canonical UUID text.

    The join is the discovery member's own law — the planner validates
    the campaign id this way because the value joins
    ``node.campaign_id`` and every reader of the campaign row resolves
    it — restated here in this seam's vocabulary, never imported (a
    member spells the join it performs in its own words, and the
    cross-member suites pin the spellings agree).  A :class:`uuid.UUID`
    or text one parses, canonicalized through :mod:`uuid` so a
    mixed-case or braced spelling upserts onto the one row rather than
    making one campaign look like two; anything else is refused,
    because an id that cannot join the tree's campaign key names no
    campaign a figure could be persisted for.
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
    raise FdrDeployError(
        f"campaign {value!r} ({type(value).__name__}) is not a UUID: the "
        f"per-campaign row is keyed by the campaign id that joins "
        f"node.campaign_id and the discovery member's campaign record, so "
        f"an id that cannot join them names no campaign an FDR_deploy "
        f"figure could be persisted for. Hand the campaign's id — a UUID "
        f"or its text, in any spelling uuid.UUID parses (feature 267)"
    )


def _instant_of(computed_at: str | None) -> str:
    """The row's label — the caller's instant, or the wall clock's now.

    ``computed_at`` defaults to *now* (UTC, second resolution — the
    spelling :meth:`datetime.datetime.isoformat` produces and the one
    the history read's ``ORDER BY`` stays chronological under), because
    a caller that closed a campaign out at a known instant passes it so
    the row's label matches the close-out rather than the write.  An
    explicit instant must be a non-empty string — it orders the trend,
    and a label that is not a nameable instant orders nothing.
    """
    if computed_at is None:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not isinstance(computed_at, str) or not computed_at.strip():
        raise FdrDeployError(
            f"a persisted FDR_deploy row's computed_at is an ISO 8601 UTC "
            f"string — got {computed_at!r} ({type(computed_at).__name__}). "
            f"The instant is the label the trend's order reads, so a value "
            f"that is not a nameable instant orders nothing; pass the "
            f"instant the campaign's close-out measured at, or nothing and "
            f"let the write stamp its own (feature 267)"
        )
    return computed_at


def _row_figure(row: Any) -> float:
    """Rebuild one persisted row's figure — from the pair it carries.

    The pair is the row's truth and the figure a derived view, so the
    read recomputes the projection under the one constant (:func:`fdr_deploy`'s
    own spelling, one formula in the module) and refuses the row that
    disagrees with itself: a stored ``fdr_deploy`` that the stored pair
    does not recompute to, or a stored ``base_rate`` that is not the
    deployment's, is a row no dashboard and no M3 gate could rely on,
    and refusing it by name is how the rest of the trend stays
    trustworthy.  The columns are read positionally in the SELECT's
    order — the store conventions of this workspace spell (no row
    factory; the SELECT is the contract).
    """
    campaign_id, base_rate, sensitivity, specificity, stored = (
        row[0],
        row[1],
        row[2],
        row[3],
        row[4],
    )
    if not isinstance(base_rate, float) or base_rate != DEPLOYMENT_BASE_RATE:
        raise FdrDeployError(
            f"the persisted FDR_deploy row for campaign {campaign_id!r} "
            f"carries a base rate of {base_rate!r}, not the deployment's "
            f"{DEPLOYMENT_BASE_RATE!r}: the figure docs §16 names is "
            f"'FDR_deploy at π₀ = 0.9' — the qualifier travels with the "
            f"number — and a row reweighted at a rate nobody pinned is a "
            f"number nobody targeted. The repair is the store's, never a "
            f"recompute at the rate the row happens to hold (feature 267, "
            f"docs §16)"
        )
    pair = _the_figures(_PairCarrier(float(sensitivity), float(specificity)))
    rebuilt = _reweighted(*pair)
    if not isinstance(stored, float) or stored != rebuilt:
        raise FdrDeployError(
            f"the persisted FDR_deploy row for campaign {campaign_id!r} "
            f"carries a figure of {stored!r} that its own pair "
            f"(sensitivity {sensitivity!r}, specificity {specificity!r}) "
            f"does not reweight to ({rebuilt!r} at π₀ = "
            f"{DEPLOYMENT_BASE_RATE!r}). The pair is the row's truth and "
            f"the figure a derived view over it, so a row that disagrees "
            f"with its own measurement is a figure no dashboard and no M3 "
            f"gate could rely on — the repair is the store's, never a "
            f"re-measure over a campaign that already closed (feature 267)"
        )
    return rebuilt


class _PairCarrier:
    """The row's pair, rewrapped for the one validation spelling.

    :func:`_the_figures` validates every carrier this module reads —
    the caller's duck-typed pair at the write, and the store's own
    columns at the read — and the read goes through the same narrowing
    so a corrupt row (a figure column that is not a finite real in
    ``[0, 1]``) is refused in the same vocabulary rather than reaching
    the arithmetic unvalidated.
    """

    __slots__ = ("sensitivity", "specificity")

    def __init__(self, sensitivity: float, specificity: float) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — this store's own
    spelling of the translation every store in this workspace performs.

    Only ``sqlite:///`` speaks (docs §16's single-machine allowance),
    any other scheme refused loudly rather than silently mis-parsed so a
    misrouted Postgres URL cannot hide behind a mysterious file, no
    host but ``localhost`` admitted, and a URL with no path refused —
    the same three refusals the replay member's metrics store and the
    bootstrap member's pool state for their own connections, restated
    because a member states its own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise FdrDeployError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            f"FDR_deploy store speaks sqlite:/// (docs §16's 'single "
            f"Postgres metrics table', the simpler option the section "
            f"defends at this scale), the same refusal every store in this "
            f"workspace documents — a Postgres metrics table arrives with "
            f"the versioned migration member, and pretending to speak it "
            f"here would hide a misrouted URL behind a mysterious file "
            f"(feature 267)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise FdrDeployError(
            f"the FDR_deploy store's sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 267)"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise FdrDeployError(
            f"the FDR_deploy store's sqlite {DATABASE_URL_ENV} carries no "
            f"database path (feature 267)"
        )
    return Path(path)
