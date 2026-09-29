"""Feature 345's store: Type-B depth past the flip, per Type-D campaign,
in the relational store the deployment names.

app_spec.xml, "Observability & Dashboards", feature 345: *System persists
Type-B depth past the flip for Type-D worlds, which returns the trend
across campaigns.*  docs/nullius-tech-architecture.md §16 lists the figure
among the per-campaign research metrics (line 909) — *"Type-B depth past
the flip in Type-D worlds"* — and prd §11's scorecard carries it as the
one secondary metric whose target, like feature 346's, is a *direction*
rather than a bar (line 540):

    | **Secondary** | Type-B error rate: depth past the flip in Type-D
      worlds | falling across campaigns |

**The figure is feature 269's count, and this feature exists to trend
it.**  §7.3.1 states the split the whole accounting discipline stands on
(line 339): *"Two distinct failures, two distinct terms.  Conflating them
was the original design's blind spot"* — Type-A *committed to a null
node*, dominant in Type-R worlds; Type-B *kept deepening past the flip*,
dominant in Type-D worlds.  The scoring member's accounting
(:func:`scoring.account_errors`, feature 269) answers Type-B's metric as
:class:`~scoring.ErrorAccounting.depth_past_flip_errors` — the count of
explored nodes sitting at or beyond their branch's flip depth, §7.2's
inclusive boundary (line 311: *"below ``flip_depth`` the real targets are
returned, at or beyond it the permuted ones"*), each counted node one act
of continuing to deepen past a flip §7.3 says is silent and irreversible.
That feature's own docstring reserves this one: the accounting *"persists
nothing … the cross-campaign Type-B trend docs line 909 lists among the
research metrics is the ops member's feature (345's), which will read
this figure per campaign."*  This store is that reservation kept: it
lands one campaign's count as one row and answers the trend across the
rows — the sequence prd §11's *"falling"* is read over.

**The store owns no measurement, and — alone among this member's store
siblings — no arithmetic either.**  The member's law, stated in its
package docstring, is delegation, and it holds here twice over: the count
is the scoring member's answer over the campaign's Type-D explorations
joined to their branches' drawn flips, and the join that produces those
two integers is the null oracle's verb — feature 269's own seam takes the
facts already joined and declines to restate the ancestor walk, and this
store declines one layer further for the same reason.  Reaching for the
scoring member from here would make this table's construction depend on a
sibling the factory scan could not promise is on ``sys.path`` at build
time, and would grow a second spelling of a boundary the accounting
already owns.  So the store **reads no prefix, walks no branch and counts
no node**: it accepts the count handed over already measured — the same
"hand over, never derive" barrier feature 350 states for its four
metrics, feature 347 for its two halves, feature 346 for its three counts
and feature 267 for its pair.  And where 346 computes its quotient and
347 its difference, this store computes nothing at all: the figure is a
count of events, an integer with no derivation, so there is no derived
column to reconcile and no arithmetic to spell.  One figure in, the same
figure out — the simplest shape the family's barrier takes.

**The figure's kind is load-bearing: a count of events, never a rate.**
prd §11's row says *"Type-B error rate"*, and feature 269 already settled
what that word may mean here: the two metrics *"are different *kinds* on
purpose, because the two errors are different kinds of event"* — Type-A's
is a fraction of committed picks, Type-B's is a count of error events,
and the metric prd §11's row trends is the count.  The store holds the
same stance and refuses to invent the denominator the word *rate* might
suggest: there is no explored-total column, no normalisation, no
per-anything, because a store that divided the count by the campaign's
size would persist a figure the accounting never measured and would put a
*different* number into prd §11's trend than the one §16 names — a larger
campaign that deepened past proportionally fewer flips would read as
improvement by construction, which is the flattering direction the whole
observability category exists to keep out of its own rows.

**"For Type-D worlds" is the metric's scope, and the store holds it the
way feature 269 holds homogeneity: by reading no campaign declaration.**
§7.3 fixes the two campaign types — Type-R, the selection test; Type-D,
the stopping test, all roots real, a branch flipping null at a drawn
depth — and prd's design table states the homogeneity law (line 674:
*"never mixed within one tree"*).  §7.3.1 names where Type-B lives: *"In
a Type-R world, wasted depth is merely inefficient.  In a Type-D world,
the waste **is** the measurement."*  Which type a campaign is was decided
where the campaign was planned, and the accounting holds the boundary
*"without ever reading a campaign declaration"* — the collection's own
shape (every node carrying a drawn flip, or none) is the type's evidence.
This store takes the same stance one layer out: it judges no campaign's
type, because a row's scope is the caller's — the caller that ran the
accounting over a Type-D campaign's explorations is the one that knows
the campaign was Type-D, and which campaigns land rows here is that
caller's scope decision, not a gate this store could run honestly.  What
the store refuses is not the campaign it cannot type; it is the figure
that could not be the measurement.

**Zero is the target measurement, not an absence.**  prd §11's direction
is *"falling across campaigns"*, the trend drives toward zero, and a
Type-D campaign that deepened past nothing measured exactly that —
feature 269's own law (*"``0`` is the measurement of a campaign that
crossed nothing, not an absence"*) is the law this row carries.  A zero
count is persisted happily and served as the zero it is; an *absent*
figure is answered as an absence — ``None`` from the point read, an
empty tuple from the sweep — never as a zero, because a caller that could
not tell them apart would read a research programme that stopped
crossing flips out of a store that never ran.  The split is feature
267's toward an unclosed campaign, feature 347's toward an unclosed
cycle, feature 350's toward an unrecorded metric and feature 346's
toward the same unclosed campaign, restated because a member states its
own contract.

**One row per campaign, keyed by the campaign's canonical id.**  §16
fixes the grain in its own parenthesis — *"**Research metrics** (per
campaign)"* — so the key is the campaign id, canonicalised to UUID text
so a mixed-case or braced spelling upserts onto the one row rather than
making one campaign look like two.  The canonicalisation is the join law
the workspace already states: feature 267's ``FDR_deploy`` row and
feature 346's discovery-rate row are keyed this way because the value
joins ``node.campaign_id`` and every reader of the campaign row resolves
it, and this table's rows land under the same key so an operator reads
one campaign's base-rate-reweighted rate, its research yield and its
Type-B count off one identity, in one query.  The write is an upsert on
that key, on the siblings' reasoning restated for this row: the count is
a deterministic function of the campaign's revealed prefix and its
branches' drawn flips — both append-only facts no later run rewrites —
so a re-run is the *same measurement* written twice rather than a second
occurrence, and the upsert's refresh arm deliberately does not touch
``recorded_at``: the first instant the campaign's count was taken is a
fact about the trend's history a retry must not rewrite.  The trend is
read oldest-first by ``(recorded_at, campaign_id)``, the direction prd
§11's *"falling across campaigns"* is read in, the ordering rule §12
states and every store in this workspace restates.

**The store is the workspace's one relational store, addressed the way
every member store addresses it.**  ``DATABASE_URL`` — the one ambient
this member's route, dashboard and other stores already compose on,
imported from :mod:`ops.live_metrics` rather than re-spelled, so the
member holds **one** name for the database every one of its tables lives
in — ``sqlite:///`` on a single machine (docs §16's *"single Postgres
metrics table … the simpler option is defensible"*), the schema created
idempotently on connect (``CREATE TABLE IF NOT EXISTS``, the contract
every store in this workspace states) so no migration step is needed and
no shared schema file is touched.  The class resolves its path lazily, so
constructing one performs no I/O: composition-time work must not touch
the disk.  The ask is validated whole — campaign, count, instant —
**before a connection is opened**, so a malformed ask never reaches the
store and a refused record leaves no half-written row and no database
file at all.  The store's own failures (a scheme it cannot speak, a
locked or unwritable database) surface in this member's vocabulary
(:class:`~ops.errors.TypeBDepthError`, the original chained), never
swallowed — a count that measured but never landed is the state this
feature exists to rule out, because prd §11's direction is read off
these rows and a missing row reads as a campaign that crossed nothing,
the quietest possible flattery.

**The component beside the member's other stores.**  This is the ops
member's sixth component name and its fifth store-bound one — the growth
the member's own registration reserved when feature 341 landed and the
app-package seat reserved beside it (*"344's and 345's arrive as their
own tables under the same allowance"*).  The component name,
:data:`OPS_TYPE_B_DEPTH_COMPONENT_NAME` (``ops-type-b-depth``),
registers a builder that resolves
``DATABASE_URL`` and answers ``None`` when nothing names a store — the
degrade-don't-break stance every store-bound builder here takes, for the
reason the route's, the dashboard's and the other three stores' take it:
the factory builds every component on every ``create_app()`` call, and a
deployment without a relational store must still compose.

**What this law deliberately does not do.**  It counts no error (feature
269's verb, over the join the null oracle owns); it reads no explored
prefix and no drawn flip (the ancestor walk is the oracle's verb, argued
above); it normalises nothing (the count is the figure, not a rate, for
the reason stated above); it prices nothing — β₁ is feature 257's term,
§7.3.1's table charges Type-B there, and *"the accounting measures the
two errors, the terms charge for them"* is feature 269's own boundary,
held here unchanged; it decides no verdict — whether the trend is
*falling* is prd §11's scorecard judgment, read by whatever compares
these rows against the campaigns that came before them, and a threshold
here would be this member inventing a bar the documents put elsewhere;
it opens no route (§16's surfaces are feature 341's route and 342/343's
lamps and coverage); it renders no dashboard (351's sentence and the
member's); and it persists no row but its own — the live metrics are
350's, the meta-overfit gap 347's, the discovery rate 346's, the
sensitivity/specificity row 344's to come, and the ``FDR_deploy`` rows
the scoring member's (feature 267).

Stdlib-only, like the rest of the member: :mod:`datetime` for the row's
label, :mod:`sqlite3` for the store, :mod:`contextlib`/:mod:`pathlib`/
:mod:`urllib.parse` for the connection's plumbing, :mod:`os` for the
resolve door, :mod:`uuid` for the key's canonical spelling, and
:mod:`dataclasses` for the value — no third-party import at module scope,
and not even :mod:`math`, because a count of events has no finiteness to
check: the factory's scan (which imports this package to fire its
``@register`` builders) pays nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import TypeBDepthError
from .live_metrics import DATABASE_URL_ENV

__all__ = [
    "OPS_TYPE_B_DEPTH_COMPONENT_NAME",
    "TYPE_B_DEPTH_TABLE",
    "TypeBDepth",
    "TypeBDepths",
]

#: The component name the Type-B depth store registers under — this
#: member's sixth, beside :data:`~ops.OPS_COMPONENT_NAME` (the fdr-deploy
#: route), :data:`~ops.OPS_DASHBOARD_COMPONENT_NAME` (the dashboard),
#: :data:`~ops.OPS_LIVE_METRIC_COMPONENT_NAME` (the live-metrics store),
#: :data:`~ops.OPS_META_OVERFIT_COMPONENT_NAME` (the meta-overfit gap
#: store) and :data:`~ops.OPS_DISCOVERY_RATE_COMPONENT_NAME` (the
#: discovery-rate store), the way ``bootstrap-pool`` sits beside
#: ``bootstrap``.  The growth was reserved by the member's own
#: registration when feature 341 landed and the app-package seat reserved
#: beside it (*"344's and 345's arrive as their own tables under the same
#: allowance"*), spelled here once, imported by the member's ``__init__``,
#: and read by name through the composed application.  Prefixed with the
#: member's own name because a composed application's ``order`` is name-sorted
#: and the store must sort *beside* — never inside — the member's other
#: components.
OPS_TYPE_B_DEPTH_COMPONENT_NAME = "ops-type-b-depth"

#: The table the Type-B depth rows live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on
#: connect so no migration step is needed and no shared schema file is
#: touched.  Named member-first and subject-second (the way
#: ``scoring_fdr_deploy``, ``ops_discovery_rate`` and
#: ``ops_meta_overfit_gap`` are named) so a reader of the store can tell
#: whose research row it is holding: the ops member's, for the figure §16
#: lists among the per-campaign research metrics as *"Type-B depth past
#: the flip in Type-D worlds"*.
TYPE_B_DEPTH_TABLE = "ops_type_b_depth"

#: The largest count the table's column can hold: SQLite's ``INTEGER`` is
#: a signed 64-bit integer, and a whole number past it has no column to
#: land in.  The bound is a *shape* gate — it is stated here so a count
#: the store could never persist is refused at the door in this member's
#: vocabulary, rather than surfacing as a raw ``OverflowError`` from the
#: driver's binding step, which is neither this member's error nor a
#: measurement anybody made.
_MAX_COUNT = (1 << 63) - 1

_SCHEMA = f"""
-- Feature 345: Type-B depth past the flip, per Type-D campaign — docs
-- §16's research metrics, line 909: "Type-B depth past the flip in
-- Type-D worlds", and prd §11's secondary scorecard row: "Type-B error
-- rate: depth past the flip in Type-D worlds | falling across
-- campaigns".
--
-- The primary key is `campaign_id`, the campaign's id in canonical UUID
-- text — §16 fixes the grain in its own parenthesis ("Research metrics
-- (per campaign)"), and the canonical spelling is the join law feature
-- 267's FDR_deploy row and feature 346's discovery-rate row already key
-- on, so a mixed-case or braced spelling upserts onto the one row rather
-- than making one campaign look like two, and an operator reads one
-- campaign's figures off one identity.  One row per campaign: the write
-- is an upsert on this key, so a re-run of the same campaign's
-- measurement refreshes the measured column rather than appending a
-- second row.
--
-- `depth_past_flip_errors` is feature 269's own figure — the count of
-- explored nodes at or beyond their branch's flip depth (§7.2's
-- inclusive boundary), each one an act of continuing to deepen past a
-- flip §7.3 says is silent and irreversible — handed over already
-- measured by the caller that ran the accounting, never recomputed
-- here.  It is a COUNT of events, never a rate: prd §11's row says
-- "error rate" but the accounting that owns the figure answered a count
-- ("different kinds on purpose"), and this table deliberately carries no
-- denominator to normalise by — dividing by campaign size would persist
-- a figure nobody measured and flatter every larger campaign that came
-- after.  Zero is a measurement (a Type-D campaign that deepened past
-- nothing — the state prd §11's "falling" drives toward), not an
-- absence.
--
-- `recorded_at` is a label, not a measurement: when the row was written
-- (ISO 8601 UTC, second resolution — string order is chronological,
-- which is the order the trend read answers, the direction prd §11's
-- "falling across campaigns" is read in).  The upsert's refresh arm
-- deliberately does not touch it — a re-run of a campaign's count is the
-- same measurement (the campaign's revealed prefix and its branches'
-- drawn flips are append-only facts), and the first instant the row was
-- computed is a fact about the trend's history a retry must not rewrite.
CREATE TABLE IF NOT EXISTS {TYPE_B_DEPTH_TABLE} (
    campaign_id            TEXT NOT NULL,  -- canonical UUID text: the row's key
    depth_past_flip_errors INTEGER NOT NULL,  -- feature 269's count (>= 0)
    recorded_at            TEXT NOT NULL,  -- ISO 8601 UTC: when this row was written
    PRIMARY KEY (campaign_id)
);
"""

#: The per-campaign write: an upsert on the campaign's key.  ``ON CONFLICT``
#: refreshes the measured column — a re-run is the same measurement written
#: twice — and leaves ``recorded_at`` alone, for the reason the schema
#: comment above spells.
_UPSERT = f"""
INSERT INTO {TYPE_B_DEPTH_TABLE} (
    campaign_id, depth_past_flip_errors, recorded_at
) VALUES (?, ?, ?)
ON CONFLICT(campaign_id) DO UPDATE SET
    depth_past_flip_errors = excluded.depth_past_flip_errors
"""

#: One campaign's row, every column of it — the read the point answer is
#: rebuilt from, positional in the SELECT's order (the store conventions of
#: this workspace spell no row factory; the SELECT is the contract).
_SELECT_ROW = (
    f"SELECT campaign_id, depth_past_flip_errors, recorded_at "
    f"FROM {TYPE_B_DEPTH_TABLE} WHERE campaign_id = ?"
)

#: Every campaign's row, oldest first — the trend read, in the direction
#: prd §11's *"falling across campaigns"* is read in.  ``(recorded_at,
#: campaign_id)`` so two reads of one history return the same sequence
#: whatever the storage engine's accident (§12's ordering rule).
_SELECT_HISTORY = (
    f"SELECT campaign_id, depth_past_flip_errors, recorded_at "
    f"FROM {TYPE_B_DEPTH_TABLE} "
    f"ORDER BY recorded_at ASC, campaign_id ASC"
)


@dataclass(frozen=True, slots=True)
class TypeBDepth:
    """One Type-B depth row, as the table holds it.

    The three fields are the table's three columns: which campaign the
    count belongs to, how many of its explored nodes sat at or beyond
    their branch's flip, and the moment the row was written.  One type
    serves the write and the read — :meth:`TypeBDepths.record` returns
    what landed, :meth:`TypeBDepths.history` rebuilds what stands — so
    the row an operator reads and the row the table holds cannot be two
    things that disagree.

    **Frozen**, because a caller who could edit the count in memory could
    revise a figure prd §11's direction is read off after the trend
    consumed it — the in-memory spelling of the revision the value layer
    refuses — and because equality over the stored fields is what makes
    the record idempotent across a retry.

    Validated in :meth:`__post_init__` rather than only through the
    store, for the reason every sibling record states:
    ``dataclasses.replace`` and unpickling both rebuild instances past a
    factory's nose, and the *read* path needs the same check the write
    path does — SQLite's columns are dynamically typed, so a hand-edited
    row is reachable here.  There is deliberately no derived field to
    reconcile: the count is the figure feature 269 answers, an integer
    of events with no arithmetic over it, so the checks are the shapes —
    a campaign that joins the research rows, a count that is a count, a
    label that orders the trend.
    """

    #: The campaign whose explorations and flips the count was taken over
    #: — the row's key, in canonical UUID text, the spelling feature
    #: 267's and 346's rows are keyed on.
    campaign_id: str
    #: **Type-B's metric** — feature 269's ``depth_past_flip_errors``: how
    #: many of the campaign's explored nodes sat at or beyond their
    #: branch's flip depth (§7.2's inclusive boundary).  ``0`` is the
    #: measurement of a Type-D campaign that crossed nothing — the state
    #: prd §11's *"falling across campaigns"* drives toward — not an
    #: absence.
    depth_past_flip_errors: int
    #: When this row was written — a label, not a measurement, and the
    #: field the trend read orders by.
    recorded_at: str

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline feature 340's record, feature 347's and every
        # sibling value in this workspace follow.
        object.__setattr__(self, "campaign_id", _the_campaign(self.campaign_id))
        object.__setattr__(
            self,
            "depth_past_flip_errors",
            _the_count(self.depth_past_flip_errors),
        )
        object.__setattr__(self, "recorded_at", _the_instant(self.recorded_at))

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a later reporter or expose-surface reads the row
        through: the table's three columns under the record's own field
        names.
        """
        return {
            "campaign_id": self.campaign_id,
            "depth_past_flip_errors": self.depth_past_flip_errors,
            "recorded_at": self.recorded_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"TypeBDepth(campaign_id={self.campaign_id!r}, "
            f"depth_past_flip_errors={self.depth_past_flip_errors!r})"
        )


def _the_campaign(value: Any) -> str:
    """The row's key — the campaign id in canonical UUID text, or a
    refusal.

    The canonicalisation is the join law this workspace already states
    (feature 267's per-campaign row is keyed this way because the value
    joins ``node.campaign_id`` and every reader of the campaign row
    resolves it; feature 346's discovery-rate row lands under the same
    key, and this table's rows join both), restated here in this member's
    own words rather than imported: a member spells the join it performs
    in its own words, and the cross-member suites pin the spellings
    agree.  A :class:`uuid.UUID` or text one parses is canonicalized
    through :mod:`uuid`, so a mixed-case or braced spelling upserts onto
    the one row rather than making one campaign look like two — and
    anything else is refused, because an id that cannot join the tree's
    campaign key names no campaign a Type-B count could be persisted
    for.
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
    raise TypeBDepthError(
        f"campaign {value!r} ({type(value).__name__}) is not a UUID: the "
        f"per-campaign row is keyed by the campaign id that joins "
        f"node.campaign_id and the member's other research rows, so an id "
        f"that cannot join them names no campaign a Type-B count could be "
        f"persisted for — and §16's research metrics are per campaign, so "
        f"a row attributed to no campaign is a figure nobody can trend. "
        f"Hand the campaign's id — a UUID or its text, in any spelling "
        f"uuid.UUID parses (feature 345)"
    )


def _the_count(value: Any) -> int:
    """Type-B's metric — feature 269's count, a whole number of events,
    or a refusal.

    Four gates, each refused rather than resolved, the discipline feature
    340's ``_validated_bps`` and feature 346's ``_the_count`` state for
    their own figures:

    * **a whole number.**  ``bool`` is refused first (``True`` is ``1``,
      and a flag where a count belongs would persist a figure nobody
      measured), and anything that is not an ``int`` is refused with it —
      a fractional count most of all, because ``3.0`` errors is not a
      count of events and coercing it would be this store inventing a
      figure the caller never stated.
    * **never negative.**  The count is of events that happened; there is
      no path by which fewer than none occurred — the same words feature
      269's own narrowing uses, restated at the door this count passes
      through.
    * **zero admitted and honoured.**  ``0`` is the measurement of a
      Type-D campaign that deepened past nothing — the state prd §11's
      *"falling across campaigns"* is driving toward, and the honest
      answer the accounting gives for a campaign that crossed no flip.
    * **at most the column's range.**  SQLite's ``INTEGER`` is a signed
      64-bit integer; a count past it has no column to land in, and the
      alternative to refusing it here is a raw ``OverflowError``
      escaping the member's vocabulary from the driver's binding step.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeBDepthError(
            f"depth_past_flip_errors must be Type-B's metric — the count "
            f"of explored nodes at or beyond their branch's flip, feature "
            f"269's own figure handed over already measured — as a whole "
            f"number, got {value!r} ({type(value).__name__}). A count that "
            f"is not one number is not a measurement any reader of §16's "
            f"metric can act on, and a fractional spelling would be this "
            f"store inventing a figure the caller never stated (feature "
            f"345, prd §4.1.2)"
        )
    if value < 0:
        raise TypeBDepthError(
            f"depth_past_flip_errors must not be negative — got "
            f"{value!r}. The figure counts error events, each one a well "
            f"deepened past a silent flip, and there is no path by which "
            f"fewer than none occurred: a campaign that crossed nothing "
            f"made zero, and zero is the measurement prd §11's *falling "
            f"across campaigns* is driving toward, not a floor to undersell "
            f"(feature 345, prd §4.1.2)"
        )
    if value > _MAX_COUNT:
        raise TypeBDepthError(
            f"depth_past_flip_errors is {value!r}, past the range the "
            f"row's INTEGER column can hold ({_MAX_COUNT!r}). The bound is "
            f"the column's, not this store's opinion of the figure: a "
            f"count that cannot be persisted is refused here, in this "
            f"member's vocabulary, rather than surfacing as a raw "
            f"OverflowError from the driver's binding step — which is "
            f"neither this member's error nor a measurement anybody made "
            f"(feature 345)"
        )
    return value


def _the_instant(recorded_at: Any) -> str:
    """The row's label — the caller's instant, or the wall clock's now.

    ``recorded_at`` defaults to *now* (UTC, second resolution — the
    spelling :meth:`datetime.datetime.isoformat` produces and the one the
    trend read's ``ORDER BY`` stays chronological under), because a
    caller that closed a campaign out at a known instant passes it so the
    row's label matches the measurement rather than the write.  An
    explicit instant must be a non-empty string — it orders the trend,
    and a label that is not a nameable instant orders nothing.
    """
    if recorded_at is None:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise TypeBDepthError(
            f"a Type-B depth row's recorded_at is an ISO 8601 UTC string — "
            f"got {recorded_at!r} ({type(recorded_at).__name__}). The "
            f"instant is the label the trend's order reads, so a value "
            f"that is not a nameable instant orders prd §11's direction by "
            f"nothing; pass the instant the campaign's count was measured "
            f"at, or nothing and let the write stamp its own (feature 345)"
        )
    return recorded_at


class TypeBDepths:
    """§16's Type-B-depth-past-the-flip figure, in the relational store
    the deployment names.

    Constructed with the database URL it persists into; :meth:`record`
    lands one campaign's count as its row, :meth:`depth` answers one
    campaign's figure, and :meth:`history` answers every campaign's
    oldest-first — the trend prd §11 reads its *"falling across
    campaigns"* target across.  The class resolves its path lazily, so
    constructing one performs no I/O — composition-time work must not
    touch the disk, the contract every store in this workspace states —
    and the schema is created idempotently on the first connect, so no
    migration step is needed.

    Hand-written with ``__slots__`` and no ``__dict__``: a store is a
    holder, not a value, and there is no shadow state beside the URL for
    a caller to park a figure in.  Not frozen: the URL it holds is live
    deployment state, and the rows live in the database, never in the
    process — the store caches none of the counts it wrote, so a count
    read back is a fact about the world rather than about this process's
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
            raise TypeBDepthError(
                f"the Type-B depth store is constructed with a database "
                f"URL, and this one is not a non-empty string (got "
                f"{database_url!r}, {type(database_url).__name__}): pass "
                f"the relational store to persist Type-B depth past the "
                f"flip into — sqlite:///path/to/store.db, the spelling "
                f"every member store in this workspace takes (feature "
                f"345, docs §16)"
            )
        self._database_url = database_url.strip()
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Any = None) -> TypeBDepths | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names
        none.

        An empty or whitespace-only value counts as unset.  Absent is not
        an error: it is a deployment without a relational store, which
        composes no Type-B depth component — a discoverable state, not an
        exception — while the caller that must persist a count is the one
        that must not find itself in it.  The split is the one every
        resolve-shaped builder in this workspace states: this method
        answers *what is composed*, and the caller who needs a row and
        resolves ``None`` refuses to proceed rather than silently
        persisting nowhere — a trend with a hole in it exactly where a
        campaign's errors were counted is the quietly-defaulted number
        this category exists to rule out, and prd §11 reads its direction
        off these rows.
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
        operation needs it, which is the same laziness every store class
        in this workspace states for the same reason.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The verbs ------------------------------------------------------------

    def record(
        self,
        campaign_id: Any,
        *,
        depth_past_flip_errors: Any,
        recorded_at: Any = None,
    ) -> TypeBDepth:
        """Persist one campaign's Type-B depth past the flip — feature
        269's count, handed over already measured.

        ``campaign_id`` names the campaign (canonicalised to UUID text,
        §16's per-campaign grain, the row's key); ``depth_past_flip_errors``
        is **Type-B's metric** — feature 269's own
        :attr:`scoring.ErrorAccounting.depth_past_flip_errors`, the count
        of the campaign's explored nodes at or beyond their branch's flip
        depth, which the caller that ran the accounting hands over
        verbatim because the count and the join beneath it are the
        scoring member's and the null oracle's, never this store's;
        ``recorded_at`` defaults to *now* (UTC, second resolution), and a
        caller that closed the campaign out at a known instant passes it
        so the row's label matches the measurement.

        **The store computes nothing** — there is no quotient as feature
        346 computes, no difference as 347 computes, and no parameter for
        any derived figure at any spelling: the count is an integer of
        events with no arithmetic over it, so the ask is the figure and
        the row is the figure, the simplest shape the family's "hand
        over, never derive" barrier takes.

        The ask is validated whole — the campaign, the count, the
        instant — **before a connection is opened**, so a malformed ask
        never reaches the store and a refused record leaves no
        half-written row and no database file at all.  The write is an
        upsert on the campaign's key: the count is a deterministic
        function of the campaign's revealed prefix and its branches'
        drawn flips — both append-only facts — so a re-run is the same
        measurement written twice, the measured column refreshes and the
        row's original ``recorded_at`` stands, the law feature 267 states
        for its own per-campaign row.

        Returns:
            The :class:`TypeBDepth` **the table holds** — read back
            inside the same transaction as the write, so the count and
            the instant in the answer are the row's own rather than the
            arguments'.

        Raises:
            TypeBDepthError: The ask, refused — an id that is not a
                UUID, a count that is not a whole number (a ``bool``,
                ``3.0``, text, ``None``, one past the column's 64-bit
                range), a negative count, an instant that is not a
                nameable label; and any failure of the store itself,
                chained to the original and deliberately not swallowed —
                a count that measured but never landed is the state this
                feature exists to rule out.
        """
        campaign = _the_campaign(campaign_id)
        count = _the_count(depth_past_flip_errors)
        instant = _the_instant(recorded_at)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(_UPSERT, (campaign, count, instant))
                row = connection.execute(_SELECT_ROW, (campaign,)).fetchone()
        except TypeBDepthError:
            raise
        except (sqlite3.Error, OSError) as exc:
            # The store's own failure, translated: a caller catching this
            # member's base class must catch a count that measured but
            # never landed, and the original is chained so the operator
            # still sees the database's own words — never swallowed,
            # never retried over a measurement that already landed.
            raise TypeBDepthError(
                f"could not persist the Type-B depth for campaign "
                f"{campaign!r} into the store: {exc!r}. Type-B depth past "
                f"the flip is docs §16's research metric and prd §11's "
                f"secondary scorecard row, whose grade (*falling across "
                f"campaigns*) is read across these rows — so a count that "
                f"measured but never landed is the state feature 345 "
                f"exists to rule out, and a missing row reads as a "
                f"campaign that crossed nothing, the quietest possible "
                f"flattery. The failure is surfaced, and the repair is the "
                f"store's (the original refusal is chained), never a "
                f"re-measure over a campaign whose explored prefix the "
                f"append-only ledger already holds (feature 345, docs "
                f"§16, prd §11)"
            ) from exc
        if row is None:  # pragma: no cover - the write landed in this transaction
            raise TypeBDepthError(
                f"the Type-B depth for campaign {campaign!r} could not be "
                f"read back after the write. prd §11's direction is read "
                f"off these rows, so a row this store cannot vouch for is "
                f"a figure an operator would be trending blind (feature "
                f"345)"
            )
        return _record_from_row(row)

    def depth(self, campaign_id: Any) -> TypeBDepth | None:
        """One campaign's standing figure, or ``None`` when it holds
        none.

        The point read — the answer to *how much Type-B depth past the
        flip did this campaign account?* for a caller holding one
        campaign.  ``None`` is the honest absent answer (the campaign has
        closed no row out, or this deployment never measured one), never
        a zero: ``0`` is a *measurement* — a Type-D campaign that
        deepened past nothing — where ``None`` is an absence, and a
        caller that could not tell them apart would read a research
        programme already at its target out of a missing row.  The same
        stance feature 267's ``fdr`` takes toward an unclosed campaign,
        feature 346's ``rate`` toward the same, feature 347's ``gap``
        toward an unclosed cycle and feature 350's ``latest`` toward an
        unrecorded metric.
        """
        campaign = _the_campaign(campaign_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_SELECT_ROW, (campaign,)).fetchone()
        except TypeBDepthError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise TypeBDepthError(
                f"could not read the Type-B depth for campaign "
                f"{campaign!r} from the store: {exc!r}. The figure is prd "
                f"§11's secondary scorecard row, so a store that cannot be "
                f"asked is surfaced rather than answered around; the repair "
                f"is the store's (the original refusal is chained) (feature "
                f"345, docs §16, prd §11)"
            ) from exc
        return None if row is None else _record_from_row(row)

    def history(self) -> tuple[TypeBDepth, ...]:
        """Every campaign's count on record, oldest first — the trend
        read.

        prd §11 grades the metric by its *direction*, not against a bar —
        *"Type-B error rate: depth past the flip in Type-D worlds |
        falling across campaigns"* — so a reading is a comparison against
        what came before it, and that is the order this answers in: by
        the row's own instant, with the campaign's id breaking
        same-instant ties (§12's ordering rule).  An empty tuple is the
        honest answer for a deployment that has closed no campaign out:
        a discoverable state, not an exception and never a fabricated
        first point.

        The store computes no direction of its own: whether the sequence
        is *falling* is the scorecard's judgment, read by whatever
        compares these rows against each other — a slope or a verdict
        here would be this member inventing the very bar prd §11 pointed
        somewhere else on purpose.

        Fails with :class:`~ops.errors.TypeBDepthError` when the store
        could not be read, and when a stored row is not a row this store
        could have written — the refusal, not a skip: a skipped row is a
        campaign's errors wearing a shrug, and prd §11's direction is
        read across this sweep.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(_SELECT_HISTORY).fetchall()
        except TypeBDepthError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise TypeBDepthError(
                f"could not read the Type-B depth history from the store: "
                f"{exc!r}. The trend is the sequence prd §11's *falling "
                f"across campaigns* is graded across, so a store that "
                f"cannot be asked is surfaced rather than answered around; "
                f"the repair is the store's (the original refusal is "
                f"chained) (feature 345, docs §16, prd §11)"
            ) from exc
        return tuple(_record_from_row(row) for row in rows)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the store and the URL it holds — a URL is not a secret,
        # and a repr is a debugging aid — and nothing else: the rows live
        # in the database, and the counts are the caller's.
        return f"{type(self).__name__}({self._database_url!r})"

    # -- The connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The URL is translated on first use (a scheme this store cannot
        speak is refused by name here, at the operation that needed it),
        the schema is created idempotently (``CREATE TABLE IF NOT
        EXISTS``, the contract every store in this workspace states),
        and the caller owns the connection — use it as a context manager
        to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection


def _record_from_row(row: Any) -> TypeBDepth:
    """Rebuild one stored row, refusing a value no depth row can be.

    The refusal is the point: this table is written by this store, but
    SQLite will accept anything another tool inserts, and a row wearing
    an id that is not a campaign or a count that is not a count would
    otherwise reach prd §11's trend as an error figure nobody measured.
    The value layer performs the validation (one spelling of it, shared
    with the write path) and this re-read *names the campaign the bad row
    came from*, so an operator gets the row to repair rather than a
    complaint about a value with no address — the discipline feature
    340's ``_from_row`` and features 346/347's state for their own
    tables, restated in this member's vocabulary.
    """
    try:
        return TypeBDepth(
            campaign_id=row[0],
            depth_past_flip_errors=row[1],
            recorded_at=row[2],
        )
    except TypeBDepthError as refusal:
        raise TypeBDepthError(
            f"{refusal} — the row this came from is the Type-B depth "
            f"recorded for campaign {row[0]!r} at {row[2]!r}, holding "
            f"{row[1]!r} depth-past-flip error(s) (feature 345)"
        ) from refusal


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — this store's own
    spelling of the translation every store in this workspace performs.

    Only ``sqlite:///`` speaks (docs §16's single-machine allowance), any
    other scheme refused loudly rather than silently mis-parsed so a
    misrouted Postgres URL cannot hide behind a mysterious file, no host
    but ``localhost`` admitted, and a URL with no path refused — the same
    three refusals the live-metrics store, the meta-overfit gap store and
    the discovery-rate store beside this one state for their own
    connections, restated because a member states its own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise TypeBDepthError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            f"Type-B depth store speaks sqlite:/// (docs §16's 'single "
            f"Postgres metrics table', the simpler option the section "
            f"defends at this scale), the same refusal every store in this "
            f"workspace documents — a Postgres metrics table arrives with "
            f"the versioned migration member, and pretending to speak it "
            f"here would hide a misrouted URL behind a mysterious file "
            f"(feature 345)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise TypeBDepthError(
            f"the Type-B depth store's sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 345)"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise TypeBDepthError(
            f"the Type-B depth store's sqlite {DATABASE_URL_ENV} carries "
            f"no database path (feature 345)"
        )
    return Path(path)
