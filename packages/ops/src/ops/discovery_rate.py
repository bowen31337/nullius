"""Feature 346's store: discoveries per 1000 budget-charging trials, in the
relational store the deployment names.

app_spec.xml, "Observability & Dashboards", feature 346: *System persists
discoveries per 1000 budget-charging trials, excluding null nodes from the
denominator.*  docs/nullius-tech-architecture.md §16 lists the figure among
the per-campaign research metrics — *"discoveries per 1000 **budget-charging**
trials"* — and prd §11's scorecard carries it as the one secondary metric
whose target is a *direction* rather than a bar:

    | **Secondary** | Discoveries per 1,000 trials charged (nulls excluded
      from the denominator) | trending up |

**The denominator's identity is the whole of the second clause, and it is
feature 93's law.**  §8 states what ``charges_budget`` is for: *"A null
node's signal was never compared to real forward returns, so it consumed
agent calls and CPU but* **no statistical degrees of freedom**. *It must not
inflate ``K`` in the deflation term"*.  Feature 93's ``K_effective`` is the
count that filter produces — *"the count of the trials that spent
statistical budget"* — and the module that derives it says plainly what the
two counts are: *"``K_effective`` is never the number of rows the ledger
holds: :meth:`ledger.store.TrialLedger.count` is that number and stays
deliberately plain, while this is the count of the trials that spent
statistical budget"*.  That divergence *is* the null nodes, and it is the
only place the sentence's second clause can be honoured from: a store that
divided by the ledger's row count would answer a *smaller* rate exactly in
proportion to how many nulls a campaign planted — the flattering direction,
which is the direction prd §11's *"trending up"* target would then reward.

**The store owns no measurement.**  The member's law, stated in its package
docstring, is delegation, and it holds here: how many discoveries a campaign
made is the selection surface's count (feature 274's argmax, feature 222's
terminal commit — the picks that stayed standing), the budget-charging trial
count is the ledger member's derivation (feature 93), and the ledger's raw
row count is the ledger store's own plain number.  Reaching for the ledger
member from here would make this table's construction depend on a sibling
the factory scan could not promise is on ``sys.path`` at build time, and
would grow a second spelling of the ``charges_budget`` filter that feature
93 already owns.  So the store **reads no ledger and counts no picks**: it
accepts the three counts handed over already measured — the same "hand over,
never derive" barrier feature 350 states for its four metrics, feature 347
for its two halves, feature 267 for its pair and feature 340 for its two
costs.

**What it *does* compute is the one quotient the sentence names.**  A rate is
not a measurement; it is the answer to *how many discoveries per 1000
budget-charging trials*, and the sentence names it as the persisted figure.
So there is no parameter for it, at any spelling, on the ask or anywhere
else — the identical stance feature 340 takes toward its ``difference_bps``
and feature 347 toward its ``gap``, and for the same reason: a
caller-supplied rate would let the system persist a numerator, a denominator
and a third number that disagrees with both, and prd §11 reads its direction
off this column.  Three counts stated, one quotient computed, the quotient
stored beside the counts that produced it so a reader can check the division
rather than trust it.

**The unit is part of the figure, and that is why the multiply by 1000 is
the store's and not the caller's.**  ``rate`` is *discoveries per 1000
budget-charging trials* — not a fraction, not a percentage, not an angle to
be rescaled at the reading surface.  A caller handed the quotient would be
handed a number whose unit lives in prose, and the first surface to divide by
a hundred (or to plot it beside ``FDR_deploy``'s ``[0, 1]``) would be showing
a figure nobody measured.  So the multiplication is inside the one spelling
of the arithmetic here, and the column means what §16's phrase means.

**The raw ledger count is carried beside the denominator, because without it
the second clause is unverifiable.**  *"Excluding null nodes from the
denominator"* is a claim about which count was divided into, and the only way
a stored row can be *checked* to have honoured it — rather than merely
labelled as having — is for the row to carry both counts, so
``ledger_trials − budget_charging_trials`` is the null nodes the sentence
excludes, visible by subtraction.  That is feature 93's own arithmetic stated
as a column: the two diverge by exactly the null nodes, and a row whose two
counts are equal is a campaign that planted none.  The pair also carries the
counts' *scale*, the reasoning feature 347 carries its world counts under:
3 discoveries over 1,200 budget-charging trials is not the same indicator as
3 over 120,000, and a rate read without its denominator invites exactly that
confusion.  The one *structural* check the pair admits is that charged trials
are a subset of the ledger's rows — the ledger is append-only with no UPDATE
and no DELETE (§8, enforced by role grants), so a row claiming more
budget-charging trials than the ledger ever held is a row lying about its own
accounting, and it is refused rather than served.  Deliberately **no check
relating the discoveries to either count**: a committed pick need not have
come from a trial this campaign charged (prd §4.2's resident book is selected
across campaigns), so a rate above 1000 is possible, is a measurement, and
clamping it would be this store inventing a bound the documents do not state.

**The counts are whole numbers, held to ``int``, and bounded by the column
that must hold them.**  ``bool`` is refused before ``int`` (a flag where a
count belongs — the family's law), a fractional count is refused rather than
coerced (``14.0`` trials is not a count of trials, and coercing it would be
this store inventing a denominator the caller did not state — feature 267's
count law and feature 347's world-count law, restated for the figures this
one divides), a non-positive denominator is refused *by name* because a rate
over no budget-charging trials is not a measurement at all — ``0/0`` is
undefined and answering ``0.0`` for it would persist a figure nobody
measured, the quietly-defaulted number this whole category exists to rule out
— and a count larger than SQLite's signed 64-bit ``INTEGER`` is refused
before the connection opens, because the row has no column that could hold it
and the alternative is a raw ``OverflowError`` escaping the member's
vocabulary at the binding.  Zero *discoveries* is admissible and is a
*measurement*, not an absence: a campaign that found nothing measured exactly
that, and prd §11's *"trending up"* is a direction a flat zero is the honest
bottom of (§8's own contrast — an epoch whose every trial failed still has a
``K_effective``, and it is not zero — is the other side of the same
distinction).

**One row per campaign, keyed by the campaign's canonical id.**  §16 fixes
the grain in its own parenthesis — *"**Research metrics** (per campaign)"* —
so the key is the campaign id, canonicalised to UUID text so a mixed-case or
braced spelling upserts onto the one row rather than making one campaign look
like two.  The canonicalisation is the join law the workspace already states
(feature 267's per-campaign row is keyed this way because the value *joins
``node.campaign_id`` and every reader of the campaign row resolves it*, and
features 344 and 345's research rows land in this same store under this same
key), restated here in this member's own words rather than imported — a
member spells the join it performs in its own words, and the cross-member
suites pin the spellings agree.  The write is an upsert on that key, on
feature 267's reasoning stated for this row: the figure is a deterministic
function of a campaign's ledger rows and its committed picks, so a re-run is
the *same measurement* written twice rather than a second occurrence, and the
upsert's refresh arm deliberately does not touch ``recorded_at`` — the first
instant the campaign's rate was computed is a fact about the trend's history
a retry must not rewrite.  The trend is read oldest-first by
``(recorded_at, campaign_id)``, the direction prd §11's *"trending up"* is
read in and the ordering rule every store in this workspace restates.

**An absent rate is answered as an absence, never defaulted.**  A deployment
that has closed no campaign out answers ``None`` from the point read and an
empty tuple from the sweep — a discoverable state, not an exception and never
a zero, because ``0.0`` is a *measurement* (a campaign that made no
discoveries) where ``None`` is an absence, and a caller that could not tell
them apart would read a barren research programme out of a missing row.  The
split is feature 267's toward an unclosed campaign, feature 347's toward an
unclosed cycle and feature 350's toward an unrecorded live metric, restated
because a member states its own contract.

**The store is the workspace's one relational store, addressed the way every
member store addresses it.**  ``DATABASE_URL`` — the one ambient this
member's route, dashboard and other stores already compose on, imported from
:mod:`ops.live_metrics` rather than re-spelled, so the member holds **one**
name for the database every one of its tables lives in — ``sqlite:///`` on a
single machine (docs §16's *"single Postgres metrics table ... the simpler
option is defensible"*), the schema created idempotently on connect
(``CREATE TABLE IF NOT EXISTS``, the contract every store in this workspace
states) so no migration step is needed and no shared schema file is touched.
The class resolves its path lazily, so constructing one performs no I/O:
composition-time work must not touch the disk.  The ask is validated whole —
campaign, all three counts, the instant, and the two checks that span them —
**before a connection is opened**, so a malformed ask never reaches the store
and a refused record leaves no half-written row and no database file at all.
The store's own failures (a scheme it cannot speak, a locked or unwritable
database) surface in this member's vocabulary
(:class:`~ops.errors.DiscoveryRateError`, the original chained), never
swallowed — a rate that measured but never landed is the state this feature
exists to rule out, because prd §11's direction is read off these rows and a
missing row reads as a quiet campaign.

**The component beside the member's other stores.**  This is the ops member's
fifth component name and its fourth store-bound one — the growth the member's
own registration reserved when feature 341 landed and the app-package seat
reserved beside it (*"344-346's arrive as their own tables under the same
allowance"*).  :data:`OPS_DISCOVERY_RATE_COMPONENT_NAME`
(``ops-discovery-rate``) registers a builder that resolves ``DATABASE_URL``
and answers ``None`` when nothing names a store — the degrade-don't-break
stance every store-bound builder here takes, for the reason the route's, the
dashboard's and the other two stores' take it: the factory builds every
component on every ``create_app()`` call, and a deployment without a
relational store must still compose.

**What this law deliberately does not do.**  It counts no discovery and reads
no ledger (each is the source member's derivation, handed over already
measured); it decides no verdict — whether a rate is *good* is prd §11's
scorecard's judgment, reached by the loop that reads the trend against the
campaigns that came before it, and a threshold here would be this member
inventing a bar the documents put elsewhere; it opens no route — §16's
observability surfaces are feature 341's route and 342/343's lamps and
coverage; it renders no dashboard (351's sentence and the member's); and it
persists no row but its own — the live metrics are 350's, the meta-overfit
gap 347's, the other research-metrics rows 344's and 345's, and the
``FDR_deploy`` rows the scoring member's (feature 267).

Stdlib-only, like the rest of the member: :mod:`datetime` for the row's
label, :mod:`math` for the count bound, :mod:`sqlite3` for the store,
:mod:`contextlib`/:mod:`pathlib`/:mod:`urllib.parse` for the connection's
plumbing, :mod:`dataclasses` for the value, :mod:`numbers` for the figures,
:mod:`uuid` for the key's canonical spelling — no third-party import at
module scope, so the factory's scan (which imports this package to fire its
``@register`` builders) pays nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import DiscoveryRateError
from .live_metrics import DATABASE_URL_ENV

__all__ = [
    "DISCOVERY_RATE_TABLE",
    "OPS_DISCOVERY_RATE_COMPONENT_NAME",
    "DiscoveryRate",
    "DiscoveryRates",
]

#: The component name the discovery-rate store registers under — this
#: member's fifth, beside :data:`~ops.OPS_COMPONENT_NAME` (the fdr-deploy
#: route), :data:`~ops.OPS_DASHBOARD_COMPONENT_NAME` (the dashboard),
#: :data:`~ops.OPS_LIVE_METRIC_COMPONENT_NAME` (the live-metrics store) and
#: :data:`~ops.OPS_META_OVERFIT_COMPONENT_NAME` (the meta-overfit gap store),
#: the way ``bootstrap-pool`` sits beside ``bootstrap``.  The growth was
#: reserved by the member's own registration when feature 341 landed and the
#: app-package seat reserved beside it (*"344-346's arrive as their own tables
#: under the same allowance"*), and spelled here, in the member's ``__init__``
#: and in the app-package seat (:mod:`app.modules.ops`) — two spellings of one
#: name the member's suite asserts agree.  Prefixed with the member's own name
#: because a composed application's ``order`` is name-sorted and the store must
#: sort *beside* — never inside — the member's other components.
OPS_DISCOVERY_RATE_COMPONENT_NAME = "ops-discovery-rate"

#: The table the discovery-rate rows live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on connect so
#: no migration step is needed and no shared schema file is touched.  Named
#: member-first and subject-second (the way ``scoring_fdr_deploy``,
#: ``ops_live_metrics`` and ``ops_meta_overfit_gap`` are named) so a reader of
#: the store can tell whose research row it is holding: the ops member's, for
#: the figure §16 lists among the per-campaign research metrics as
#: *"discoveries per 1000 budget-charging trials"*.
DISCOVERY_RATE_TABLE = "ops_discovery_rate"

#: The largest count the table's columns can hold: SQLite's ``INTEGER`` is a
#: signed 64-bit integer, and a whole number past it has no column to land in.
#: The bound is a *shape* gate — it is stated here so a count the store could
#: never persist is refused at the door in this member's vocabulary, rather
#: than surfacing as a raw ``OverflowError`` from the driver's binding step,
#: which is neither this member's error nor a measurement anybody made.
_MAX_COUNT = (1 << 63) - 1

_SCHEMA = f"""
-- Feature 346: discoveries per 1000 budget-charging trials, per campaign —
-- docs §16's research metrics, line 909: "discoveries per 1000
-- budget-charging trials", and prd §11's secondary scorecard row:
-- "Discoveries per 1,000 trials charged (nulls excluded from the
-- denominator) | trending up".
--
-- The primary key is `campaign_id`, the campaign's id in canonical UUID
-- text — §16 fixes the grain in its own parenthesis ("Research metrics
-- (per campaign)"), and the canonical spelling is the join law feature 267's
-- per-campaign row already keys on, so a mixed-case or braced spelling
-- upserts onto the one row rather than making one campaign look like two.
-- One row per campaign: the write is an upsert on this key, so a re-run of
-- the same campaign's measurement refreshes the measured columns rather than
-- appending a second row.
--
-- `discoveries` is the campaign's standing pick count — the selection
-- surface's figure, handed over already measured, never recomputed here.
-- Zero is a measurement (a campaign that found nothing), not an absence.
--
-- `budget_charging_trials` is the DENOMINATOR, and its identity is the
-- sentence's second clause: it is feature 93's `K_effective` count — the
-- trials whose `charges_budget` is true, i.e. the ones that spent
-- statistical degrees of freedom (§8: a null node "consumed agent calls and
-- CPU but NO statistical degrees of freedom").  It is deliberately NOT the
-- ledger's row count: dividing by that would answer a smaller rate exactly
-- in proportion to how many nulls a campaign planted, which is the
-- flattering direction prd §11's "trending up" target would reward.
--
-- `ledger_trials` is the ledger's plain row count (feature 93's contrast:
-- "TrialLedger.count is that number and stays deliberately plain"), carried
-- beside the denominator so the exclusion is CHECKABLE rather than merely
-- labelled: `ledger_trials - budget_charging_trials` is the null nodes the
-- sentence excludes, visible by subtraction.  The pair also carries the
-- counts' scale, so 3 discoveries over 1,200 is not confused with 3 over
-- 120,000.  Charged trials are a subset of the ledger's rows — the ledger is
-- append-only with no UPDATE and no DELETE (§8, enforced by role grants) —
-- so `ledger_trials >= budget_charging_trials` is a structural invariant and
-- a row that violates it is lying about its own accounting.  There is
-- deliberately NO bound relating `discoveries` to either count: a committed
-- pick need not have come from a trial this campaign charged, so a rate
-- above 1000 is possible and is a measurement, not a mistake.
--
-- `rate` is derived: `discoveries / budget_charging_trials * 1000`,
-- computed by the store because a caller-stated quotient would be an
-- unreconciled claim persisted on trust.  The unit is per 1000 — not a
-- fraction — because that is the figure §16 and prd §11 name, and a caller
-- handed the quotient would be handed a number whose unit lives in prose.
-- Both counts are positive-or-zero whole numbers with the denominator
-- strictly positive (a rate over no budget-charging trials is undefined, and
-- answering 0.0 for it would persist a figure nobody measured).
--
-- `recorded_at` is a label, not a measurement: when the row was written
-- (ISO 8601 UTC, second resolution — string order is chronological, which is
-- the order the trend read answers, the direction prd §11's "trending up" is
-- read in).  The upsert's refresh arm deliberately does not touch it — a
-- re-run of a campaign's rate is the same measurement (the campaign's ledger
-- rows and its committed picks), and the first instant the row was computed
-- is a fact about the trend's history a retry must not rewrite.
CREATE TABLE IF NOT EXISTS {DISCOVERY_RATE_TABLE} (
    campaign_id            TEXT NOT NULL,  -- canonical UUID text: the row's key
    discoveries            INTEGER NOT NULL,  -- the campaign's standing picks (>= 0)
    budget_charging_trials INTEGER NOT NULL,  -- the denominator: feature 93's K_effective (> 0)
    ledger_trials          INTEGER NOT NULL,  -- the ledger's plain row count (>= the denominator)
    rate                   REAL NOT NULL,  -- derived: discoveries / budget_charging_trials * 1000
    recorded_at            TEXT NOT NULL,  -- ISO 8601 UTC: when this row was written
    PRIMARY KEY (campaign_id)
);
"""

#: The per-campaign write: an upsert on the campaign's key.  ``ON CONFLICT``
#: refreshes the measured columns — a re-run is the same measurement written
#: twice — and leaves ``recorded_at`` alone, for the reason the schema comment
#: above spells.
_UPSERT = f"""
INSERT INTO {DISCOVERY_RATE_TABLE} (
    campaign_id, discoveries, budget_charging_trials, ledger_trials, rate,
    recorded_at
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(campaign_id) DO UPDATE SET
    discoveries            = excluded.discoveries,
    budget_charging_trials = excluded.budget_charging_trials,
    ledger_trials          = excluded.ledger_trials,
    rate                   = excluded.rate
"""

#: One campaign's row, every column of it — the read the point answer is
#: rebuilt from, positional in the SELECT's order (the store conventions of
#: this workspace spell no row factory; the SELECT is the contract).
_SELECT_ROW = (
    f"SELECT campaign_id, discoveries, budget_charging_trials, ledger_trials, "
    f"rate, recorded_at FROM {DISCOVERY_RATE_TABLE} WHERE campaign_id = ?"
)

#: Every campaign's row, oldest first — the trend read, in the direction prd
#: §11's *"trending up"* is read in.  ``(recorded_at, campaign_id)`` so two
#: reads of one history return the same sequence whatever the storage engine's
#: accident (§12's ordering rule).
_SELECT_HISTORY = (
    f"SELECT campaign_id, discoveries, budget_charging_trials, ledger_trials, "
    f"rate, recorded_at FROM {DISCOVERY_RATE_TABLE} "
    f"ORDER BY recorded_at ASC, campaign_id ASC"
)


@dataclass(frozen=True, slots=True)
class DiscoveryRate:
    """One discovery-rate row, as the table holds it.

    The six fields are the table's six columns: which campaign the figure
    belongs to, how many discoveries it made, the two trial counts the
    denominator's identity is checkable from, the quotient the store computed
    between them, and the moment the row was written.  One type serves the
    write and the read — :meth:`DiscoveryRates.record` returns what landed,
    :meth:`DiscoveryRates.history` rebuilds what stands — so the row an
    operator reads and the row the table holds cannot be two things that
    disagree.

    **Frozen**, because a caller who could edit ``rate`` in memory could
    revise a figure prd §11's direction is read off after the trend consumed
    it — the in-memory spelling of the revision the value layer refuses — and
    because equality over the stored fields is what makes the record
    idempotent across a retry.

    Validated in :meth:`__post_init__` rather than only through the store, for
    the reason every sibling record states: ``dataclasses.replace`` and
    unpickling both rebuild instances past a factory's nose, and the *read*
    path needs the same check the write path does — SQLite's columns are
    dynamically typed, so a hand-edited row is reachable here.  Two checks
    span more than one field, and both are the table's own accounting: the
    charged trials must not exceed the ledger's rows (a row claiming more
    charges than the ledger ever held is lying about which count it divided
    into), and ``rate`` must equal ``discoveries ÷ budget_charging_trials ×
    1000`` exactly — a row where it does not is a row lying about its own
    division, refused rather than served, because the surfaces that read the
    trend trust the stored quotient without recomputing it.
    """

    #: The campaign whose ledger rows and picks the figure was taken over —
    #: the row's key, in canonical UUID text.
    campaign_id: str
    #: The campaign's standing pick count — the selection surface's figure,
    #: handed over already measured.  Zero is a measurement, not an absence.
    discoveries: int
    #: **The denominator**: the trials whose ``charges_budget`` is true — the
    #: ones that spent statistical degrees of freedom (feature 93's
    #: ``K_effective``).  Strictly positive: a rate over no budget-charging
    #: trials is undefined.
    budget_charging_trials: int
    #: The ledger's plain row count, carried so the exclusion of null nodes
    #: from the denominator is checkable by subtraction rather than trusted
    #: from a label.  Never below the denominator.
    ledger_trials: int
    #: The store's own answer: ``discoveries ÷ budget_charging_trials ×
    #: 1000``, computed, never stated by the caller.  The unit is per 1000 —
    #: not a fraction — because that is the figure §16 and prd §11 name.
    rate: float
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
            self, "discoveries", _the_count(self.discoveries, "discoveries", least=0)
        )
        object.__setattr__(
            self,
            "budget_charging_trials",
            _the_count(
                self.budget_charging_trials, "budget_charging_trials", least=1
            ),
        )
        object.__setattr__(
            self,
            "ledger_trials",
            _the_count(self.ledger_trials, "ledger_trials", least=1),
        )
        object.__setattr__(self, "rate", _the_quotient(self.rate, "rate"))
        object.__setattr__(self, "recorded_at", _the_instant(self.recorded_at))
        # The row's own accounting, checked on the value so no path — write,
        # read, replace, unpickle — can carry a pair of counts that contradict
        # each other or a quotient that disagrees with the counts stored
        # beside it.  _the_span is the one spelling of the subset law and
        # _the_rate the one spelling of the division; both refuse at the door
        # on the write path for the reason the record() docstring states.
        _the_span(
            self.budget_charging_trials,
            self.ledger_trials,
            campaign=self.campaign_id,
        )
        recomputed = _the_rate(
            self.discoveries,
            self.budget_charging_trials,
            campaign=self.campaign_id,
        )
        # Exact on purpose: all three values round-trip through SQLite as the
        # same IEEE doubles this division was computed from, so anything but
        # exact equality is a hand that edited one of them — and prd §11's
        # grade is read off this column.
        if self.rate != recomputed:
            raise DiscoveryRateError(
                f"the discovery-rate row for campaign {self.campaign_id!r} "
                f"carries a rate of {self.rate!r} that its own counts "
                f"({self.discoveries!r} discover(y|ies) over "
                f"{self.budget_charging_trials!r} budget-charging trial(s)) do "
                f"not divide to ({recomputed!r}). The counts are the row's "
                f"truth and the rate a derived view over them, so a row that "
                f"disagrees with its own division is a figure no reader of "
                f"prd §11's direction could act on. The repair is the store's, "
                f"never a re-measure over a campaign whose ledger rows the "
                f"append-only ledger already holds (feature 346, docs §16, "
                f"prd §11)"
            )

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a later reporter or expose-surface reads the row through:
        the table's six columns under the record's own field names.
        """
        return {
            "campaign_id": self.campaign_id,
            "discoveries": self.discoveries,
            "budget_charging_trials": self.budget_charging_trials,
            "ledger_trials": self.ledger_trials,
            "rate": self.rate,
            "recorded_at": self.recorded_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"DiscoveryRate(campaign_id={self.campaign_id!r}, "
            f"discoveries={self.discoveries!r}, "
            f"budget_charging_trials={self.budget_charging_trials!r}, "
            f"rate={self.rate!r})"
        )


def _the_campaign(value: Any) -> str:
    """The row's key — the campaign id in canonical UUID text, or a refusal.

    The canonicalisation is the join law this workspace already states
    (feature 267's per-campaign row is keyed this way because the value joins
    ``node.campaign_id`` and every reader of the campaign row resolves it),
    restated here in this member's own words rather than imported: a member
    spells the join it performs in its own words, and the cross-member suites
    pin the spellings agree.  A :class:`uuid.UUID` or text one parses is
    canonicalized through :mod:`uuid`, so a mixed-case or braced spelling
    upserts onto the one row rather than making one campaign look like two —
    and anything else is refused, because an id that cannot join the tree's
    campaign key names no campaign a rate could be persisted for.
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
    raise DiscoveryRateError(
        f"campaign {value!r} ({type(value).__name__}) is not a UUID: the "
        f"per-campaign row is keyed by the campaign id that joins "
        f"node.campaign_id and the discovery member's campaign record, so an "
        f"id that cannot join them names no campaign a discovery rate could "
        f"be persisted for — and §16's research metrics are per campaign, so "
        f"a row attributed to no campaign is a figure nobody can trend. Hand "
        f"the campaign's id — a UUID or its text, in any spelling uuid.UUID "
        f"parses (feature 346)"
    )


def _the_count(value: Any, field: str, *, least: int) -> int:
    """One of the three counts — a whole number within the column's range.

    Four gates, each refused rather than resolved, the discipline feature
    340's ``_validated_bps`` and feature 347's ``_the_count`` state for their
    own figures:

    * **a whole number.**  ``bool`` is refused first (``True`` is ``1``, and a
      flag where a count belongs would persist a figure nobody measured), and
      anything that is not an ``int`` is refused with it — a fractional count
      most of all, because ``14.0`` trials is not a count of trials and
      coercing it would be this store inventing a denominator the caller
      never stated.
    * **at least ``least``.**  ``1`` for the two trial counts — a rate over
      **no** budget-charging trials is undefined, and answering ``0.0`` for
      ``0/0`` would persist the quietest possible lie about a campaign's
      research yield — and ``0`` for the discoveries, where zero is a
      *measurement*: a campaign that found nothing measured exactly that, and
      prd §11's *"trending up"* is a direction a flat zero is the honest
      bottom of.
    * **at most the column's range.**  SQLite's ``INTEGER`` is a signed 64-bit
      integer; a count past it has no column to land in, and the alternative
      to refusing it here is a raw ``OverflowError`` escaping the member's
      vocabulary from the driver's binding step.
    * **a finite one by construction.**  Every admissible count is at most
      ``2 ** 63 - 1``, which is why the quotient below needs no finiteness
      branch of its own — the bound is what makes the arithmetic total, and
      stating that here is cheaper than a check that could never fire.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiscoveryRateError(
            f"{field} must be a count — a whole number, the source member's "
            f"figure handed over already measured — got {value!r} "
            f"({type(value).__name__}). A count that is not one number is not "
            f"a measurement any reader of §16's metric can act on, and a "
            f"fractional spelling would be this store inventing a figure the "
            f"caller never stated (feature 346)"
        )
    if value < least:
        if least == 0:
            raise DiscoveryRateError(
                f"{field} must not be negative — got {value!r}. A negative "
                f"count of discoveries is not a measurement of anything: a "
                f"campaign that found nothing made zero, and prd §11's "
                f"*trending up* is a direction a flat zero is the honest "
                f"bottom of (feature 346)"
            )
        raise DiscoveryRateError(
            f"{field} must be at least 1 — got {value!r}. The figure is "
            f"discoveries per 1000 **budget-charging** trials, and a "
            f"denominator of zero names a campaign that spent no statistical "
            f"degrees of freedom at all (§8: a null node 'must not inflate K' "
            f"— and a ledger of nothing but null nodes charges nothing): the "
            f"quotient is undefined there, and answering 0.0 for it would "
            f"persist the quietest possible claim about a campaign whose "
            f"research yield was never measured. The repair is the caller's "
            f"(a campaign that charged budget), never the store's (feature "
            f"346)"
        )
    if value > _MAX_COUNT:
        raise DiscoveryRateError(
            f"{field} is {value!r}, past the range the row's INTEGER column "
            f"can hold ({_MAX_COUNT!r}). The bound is the column's, not this "
            f"store's opinion of the figure: a count that cannot be persisted "
            f"is refused here, in this member's vocabulary, rather than "
            f"surfacing as a raw OverflowError from the driver's binding step "
            f"— which is neither this member's error nor a measurement "
            f"anybody made (feature 346)"
        )
    return value


def _the_span(charged: int, ledger: int, *, campaign: Any) -> None:
    """The subset law — charged trials are rows of the ledger, or a refusal.

    The one spelling of the check that makes the sentence's second clause
    *structural* rather than a naming convention: ``ledger_trials`` is the
    ledger's plain row count (feature 93's contrast — *"``TrialLedger.count``
    is that number and stays deliberately plain"*) and
    ``budget_charging_trials`` is the count of those rows whose
    ``charges_budget`` is true, so the first can never be the smaller of the
    two.  The ledger is append-only with no UPDATE and no DELETE (§8,
    enforced by role grants), so nothing in the workspace can prune a row and
    produce the impossible pair honestly: a row where the denominator exceeds
    the ledger's own size is a row claiming to have divided by more charges
    than were ever recorded, and silently serving it would put a flattering
    denominator into prd §11's trend.

    There is deliberately **no check relating the discoveries to either
    count**: a committed pick need not have come from a trial this campaign
    charged (prd §4.2's resident book is selected across campaigns), so
    ``discoveries`` above either count is possible and is a measurement, and a
    bound here would be this store inventing a limit the documents do not
    state.
    """
    if charged > ledger:
        raise DiscoveryRateError(
            f"the discovery-rate row for campaign {campaign!r} carries "
            f"budget_charging_trials={charged!r} out of ledger_trials="
            f"{ledger!r}. The denominator is feature 93's "
            f"``K_effective`` — the *subset* of the ledger's rows whose "
            f"``charges_budget`` is true — *excluding null nodes* — so it can "
            f"never exceed the ledger's own size, and the ledger is "
            f"append-only with no UPDATE and no DELETE (§8, enforced by role "
            f"grants), so the pair cannot be produced honestly by any pruning "
            f"either. A row where it holds is a row lying about which count it "
            f"divided into, and serving it would put a flattering denominator "
            f"into prd §11's trend (feature 346, docs §8-§16)"
        )


def _the_rate(discoveries: int, charged: int, *, campaign: Any) -> float:
    """The quotient — ``discoveries ÷ charged × 1000``, computed here or
    nowhere.

    The one spelling of the store's arithmetic, shared by the write path
    (:meth:`DiscoveryRates.record`, which stores what this answers) and by the
    value layer (:meth:`DiscoveryRate.__post_init__`, which verifies a stored
    row against it), so the two cannot drift apart.  The multiplication by
    1000 is inside it because the unit is part of the figure: this answers
    *per 1000*, not a fraction, so no reading surface has to be trusted to
    rescale it.

    **There is no finiteness branch here, and the reason is upstream rather
    than an omission.**  Feature 347's difference needs its own check because
    two individually-finite levels can subtract to an infinity; this quotient
    cannot, because :func:`_the_count` has already held both operands to
    ``int`` and to the column's 64-bit range, so the largest value this can
    return is ``(2 ** 63 - 1) / 1 * 1000`` — a finite double by a wide margin.
    Stating the bound rather than re-checking it keeps the arithmetic total:
    a guard that could never fire would be a claim about a branch nobody can
    exercise.
    """
    return discoveries / charged * 1000.0


def _the_quotient(value: Any, field: str) -> float:
    """A stored quotient — a finite real, or a refusal.

    The *read* path's gate over the derived column, which may hold anything at
    all once SQLite's dynamic typing is in play.  ``bool`` is refused first
    (``True`` is ``1``, and a flag where a rate belongs would persist a figure
    nobody measured); anything that is not a :class:`~numbers.Real` is refused
    with it, because a rate is one number; and a non-finite value is refused
    by name — a stored ``nan`` compares false against everything and would ride
    into prd §11's trend while looking exactly like a data point, and an
    infinity is not a rate any campaign produced.  Unlike feature 347's
    ``_the_level`` the refusal here says nothing about the sign bound's
    absence: a rate is non-negative *by construction* (two non-negative counts
    over a strictly positive denominator), so a stored negative one is not a
    measurement this store could have written and is refused as the arithmetic
    disagreement it is by the value layer.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DiscoveryRateError(
            f"{field} must be the quotient the store computes — a real "
            f"number — got {value!r} ({type(value).__name__}). The rate is not "
            f"a measurement handed in but the answer to *discoveries per 1000 "
            f"budget-charging trials*; a value that is not one number is not "
            f"that answer (feature 346)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise DiscoveryRateError(
            f"{field} must be finite — got {narrowed!r}. A NaN compares false "
            f"against everything and would ride into prd §11's trend while "
            f"looking exactly like a data point, and an infinity is not a rate "
            f"any campaign produced; the two counts stored beside this column "
            f"are the row's truth, and a quotient that is not a number is a "
            f"row no reader could act on (feature 346)"
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
        raise DiscoveryRateError(
            f"a discovery-rate row's recorded_at is an ISO 8601 UTC string — "
            f"got {recorded_at!r} ({type(recorded_at).__name__}). The instant "
            f"is the label the trend's order reads, so a value that is not a "
            f"nameable instant orders prd §11's direction by nothing; pass the "
            f"instant the campaign's rate was measured at, or nothing and let "
            f"the write stamp its own (feature 346)"
        )
    return recorded_at


class DiscoveryRates:
    """§16's discoveries-per-1000-budget-charging-trials figure, in the
    relational store the deployment names.

    Constructed with the database URL it persists into; :meth:`record` lands
    one campaign's rate as its row, :meth:`rate` answers one campaign's
    figure, and :meth:`history` answers every campaign's oldest-first — the
    trend prd §11 reads its *"trending up"* target across.  The class resolves
    its path lazily, so constructing one performs no I/O — composition-time
    work must not touch the disk, the contract every store in this workspace
    states — and the schema is created idempotently on the first connect, so
    no migration step is needed.

    Hand-written with ``__slots__`` and no ``__dict__``: a store is a holder,
    not a value, and there is no shadow state beside the URL for a caller to
    park a figure in.  Not frozen: the URL it holds is live deployment state,
    and the rows live in the database, never in the process — the store caches
    none of the rates it wrote, so a rate read back is a fact about the world
    rather than about this process's history.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: Any) -> None:
        # The URL is held, not resolved: validating it would touch the
        # filesystem or parse a scheme, and constructing a store is
        # composition-time work (the builder runs on every create_app()) that
        # must not refuse.  A URL this store cannot speak is refused by name at
        # first use, where the operator's repair belongs.
        if not isinstance(database_url, str) or not database_url.strip():
            raise DiscoveryRateError(
                f"the discovery-rate store is constructed with a database URL, "
                f"and this one is not a non-empty string (got "
                f"{database_url!r}, {type(database_url).__name__}): pass the "
                f"relational store to persist discoveries per 1000 "
                f"budget-charging trials into — sqlite:///path/to/store.db, "
                f"the spelling every member store in this workspace takes "
                f"(feature 346, docs §16)"
            )
        self._database_url = database_url.strip()
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Any = None) -> DiscoveryRates | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        discovery-rate component — a discoverable state, not an exception —
        while the caller that must persist a rate is the one that must not find
        itself in it.  The split is the one every resolve-shaped builder in
        this workspace states: this method answers *what is composed*, and the
        caller who needs a row and resolves ``None`` refuses to proceed rather
        than silently persisting nowhere — a trend with a hole in it exactly
        where a campaign's yield was counted is the quietly-defaulted number
        this category exists to rule out, and prd §11 reads its direction off
        these rows.
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
        discoveries: Any,
        budget_charging_trials: Any,
        ledger_trials: Any,
        recorded_at: Any = None,
    ) -> DiscoveryRate:
        """Persist one campaign's discoveries per 1000 budget-charging
        trials — the quotient the store computes between the counts handed
        over.

        ``campaign_id`` names the campaign (canonicalised to UUID text, §16's
        per-campaign grain, the row's key); ``discoveries`` is the campaign's
        standing pick count, handed over **already measured** by the caller
        that holds the selection surface; ``budget_charging_trials`` is the
        **denominator** — feature 93's ``K_effective`` count of the trials
        whose ``charges_budget`` is true, the ones that spent statistical
        degrees of freedom, and deliberately *not* the ledger's row count;
        ``ledger_trials`` is the ledger's plain row count, carried so the
        exclusion of null nodes is checkable by subtraction rather than
        trusted from a label; ``recorded_at`` defaults to *now* (UTC, second
        resolution), and a caller that closed the campaign out at a known
        instant passes it so the row's label matches the measurement.

        **The rate is the store's own arithmetic**, ``discoveries ÷
        budget_charging_trials × 1000``, and there is no parameter for it at
        any spelling: a caller-stated quotient would let the system persist a
        numerator, a denominator and a third number that disagrees with both,
        and prd §11 reads its direction off this column — feature 340's stance
        toward its own ``difference_bps`` and feature 347's toward its ``gap``,
        restated for §16's metric.  The multiplication by 1000 is inside it
        too, because the unit is part of the figure.

        The ask is validated whole — the campaign, all three counts, the
        instant, and the two checks that span them (the denominator never
        exceeds the ledger's rows) — **before a connection is opened**, so a
        malformed ask never reaches the store and a refused record leaves no
        half-written row and no database file at all.  The write is an upsert
        on the campaign's key: the figure is a deterministic function of a
        campaign's ledger rows and its committed picks, so a re-run is the same
        measurement written twice — the measured columns refresh and the row's
        original ``recorded_at`` stands, the law feature 267 states for its own
        per-campaign row.

        Returns:
            The :class:`DiscoveryRate` **the table holds** — read back inside
            the same transaction as the write, so the quotient, the counts and
            the instant in the answer are the row's own rather than the
            arguments'.

        Raises:
            DiscoveryRateError: The ask, refused — an id that is not a UUID,
                a count that is not a whole number (a ``bool``, ``14.0``, text,
                ``None``, one past the column's 64-bit range), a denominator of
                zero or less (a rate over no budget-charging trials is
                undefined), a negative discovery count, a ledger size below the
                denominator, an instant that is not a nameable label; and any
                failure of the store itself, chained to the original and
                deliberately not swallowed — a rate that measured but never
                landed is the state this feature exists to rule out.
        """
        campaign = _the_campaign(campaign_id)
        found = _the_count(discoveries, "discoveries", least=0)
        charged = _the_count(
            budget_charging_trials, "budget_charging_trials", least=1
        )
        ledger = _the_count(ledger_trials, "ledger_trials", least=1)
        instant = _the_instant(recorded_at)
        # The two checks that span more than one field, called once more on
        # this side of the connection — the value's own construction
        # re-validates everything, so the write path and the read path share
        # one spelling of what a rate row is, but the span law is exactly the
        # ask that must not land: otherwise the INSERT would succeed and the
        # read-back would refuse its own row, leaving a row no later
        # ``history()`` could serve — a campaign that reads as a wedge in the
        # very trend prd §11 is graded on.
        _the_span(charged, ledger, campaign=campaign)
        rate = _the_rate(found, charged, campaign=campaign)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _UPSERT,
                    (campaign, found, charged, ledger, rate, instant),
                )
                row = connection.execute(_SELECT_ROW, (campaign,)).fetchone()
        except DiscoveryRateError:
            raise
        except (sqlite3.Error, OSError) as exc:
            # The store's own failure, translated: a caller catching this
            # member's base class must catch a rate that measured but never
            # landed, and the original is chained so the operator still sees
            # the database's own words — never swallowed, never retried over a
            # measurement that already landed.
            raise DiscoveryRateError(
                f"could not persist the discovery rate for campaign "
                f"{campaign!r} into the store: {exc!r}. Discoveries per 1000 "
                f"budget-charging trials is docs §16's research metric and prd "
                f"§11's secondary scorecard row, whose grade (*trending up*) is "
                f"read across these rows — so a rate that measured but never "
                f"landed is the state feature 346 exists to rule out, and a "
                f"missing row reads as a quiet campaign. The failure is "
                f"surfaced, and the repair is the store's (the original refusal "
                f"is chained), never a re-measure over a campaign whose ledger "
                f"rows the append-only ledger already holds (feature 346, docs "
                f"§16, prd §11)"
            ) from exc
        if row is None:  # pragma: no cover - the write landed in this transaction
            raise DiscoveryRateError(
                f"the discovery rate for campaign {campaign!r} could not be "
                f"read back after the write. prd §11's direction is read off "
                f"these rows, so a row this store cannot vouch for is a figure "
                f"an operator would be trending blind (feature 346)"
            )
        return _record_from_row(row)

    def rate(self, campaign_id: Any) -> DiscoveryRate | None:
        """One campaign's standing figure, or ``None`` when it holds none.

        The point read — the answer to *how many discoveries per 1000
        budget-charging trials did this campaign make?* for a caller holding
        one campaign.  ``None`` is the honest absent answer (the campaign has
        closed no row out, or this deployment never measured one), never a
        zero: ``0.0`` is a *measurement* — a campaign that made no discoveries
        — where ``None`` is an absence, and a caller that could not tell them
        apart would read a barren research programme out of a missing row.  The
        same stance feature 267's ``fdr`` takes toward an unclosed campaign,
        feature 347's ``gap`` toward an unclosed cycle and feature 350's
        ``latest`` toward an unrecorded metric.
        """
        campaign = _the_campaign(campaign_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_SELECT_ROW, (campaign,)).fetchone()
        except DiscoveryRateError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise DiscoveryRateError(
                f"could not read the discovery rate for campaign "
                f"{campaign!r} from the store: {exc!r}. The figure is prd "
                f"§11's secondary scorecard row, so a store that cannot be "
                f"asked is surfaced rather than answered around; the repair is "
                f"the store's (the original refusal is chained) (feature 346, "
                f"docs §16, prd §11)"
            ) from exc
        return None if row is None else _record_from_row(row)

    def history(self) -> tuple[DiscoveryRate, ...]:
        """Every campaign's rate on record, oldest first — the trend read.

        prd §11 grades the metric by its *direction*, not against a bar —
        *"Discoveries per 1,000 trials charged (nulls excluded from the
        denominator) | trending up"* — so a reading is a comparison against
        what came before it, and that is the order this answers in: by the
        row's own instant, with the campaign's id breaking same-instant ties
        (§12's ordering rule).  An empty tuple is the honest answer for a
        deployment that has closed no campaign out: a discoverable state, not
        an exception and never a fabricated first point.

        Fails with :class:`~ops.errors.DiscoveryRateError` when the store could
        not be read, and when a stored row is not a rate row this store could
        have written — the refusal, not a skip: a skipped row is a campaign's
        yield wearing a shrug, and prd §11's direction is read across this
        sweep.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(_SELECT_HISTORY).fetchall()
        except DiscoveryRateError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise DiscoveryRateError(
                f"could not read the discovery-rate history from the store: "
                f"{exc!r}. The trend is the sequence prd §11's *trending up* is "
                f"graded across, so a store that cannot be asked is surfaced "
                f"rather than answered around; the repair is the store's (the "
                f"original refusal is chained) (feature 346, docs §16, prd "
                f"§11)"
            ) from exc
        return tuple(_record_from_row(row) for row in rows)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the store and the URL it holds — a URL is not a secret, and a
        # repr is a debugging aid — and nothing else: the rows live in the
        # database, and the rates are the caller's.
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


def _record_from_row(row: Any) -> DiscoveryRate:
    """Rebuild one stored row, refusing a value no rate row can be.

    The refusal is the point: this table is written by this store, but SQLite
    will accept anything another tool inserts, and a row wearing an id that is
    not a campaign, a count that is not a count, a denominator below the
    ledger's size it is paired with, or a quotient that disagrees with the
    counts beside it would otherwise reach prd §11's trend as a yield nobody
    measured.  The value layer performs the validation (one spelling of it,
    shared with the write path) and this re-read *names the campaign the bad
    row came from*, so an operator gets the row to repair rather than a
    complaint about a value with no address — the discipline feature 340's
    ``_from_row`` and feature 347's state for their own tables, restated in
    this member's vocabulary.
    """
    try:
        return DiscoveryRate(
            campaign_id=row[0],
            discoveries=row[1],
            budget_charging_trials=row[2],
            ledger_trials=row[3],
            rate=row[4],
            recorded_at=row[5],
        )
    except DiscoveryRateError as refusal:
        raise DiscoveryRateError(
            f"{refusal} — the row this came from is the discovery rate "
            f"recorded for campaign {row[0]!r} at {row[5]!r}, holding "
            f"{row[1]!r} discover(y|ies) over {row[2]!r} budget-charging "
            f"trial(s) out of a ledger of {row[3]!r} row(s) (feature 346)"
        ) from refusal


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — this store's own spelling
    of the translation every store in this workspace performs.

    Only ``sqlite:///`` speaks (docs §16's single-machine allowance), any other
    scheme refused loudly rather than silently mis-parsed so a misrouted
    Postgres URL cannot hide behind a mysterious file, no host but
    ``localhost`` admitted, and a URL with no path refused — the same three
    refusals the live-metrics store and the meta-overfit gap store beside this
    one state for their own connections, restated because a member states its
    own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise DiscoveryRateError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            f"discovery-rate store speaks sqlite:/// (docs §16's 'single "
            f"Postgres metrics table', the simpler option the section defends "
            f"at this scale), the same refusal every store in this workspace "
            f"documents — a Postgres metrics table arrives with the versioned "
            f"migration member, and pretending to speak it here would hide a "
            f"misrouted URL behind a mysterious file (feature 346)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise DiscoveryRateError(
            f"the discovery-rate store's sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 346)"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise DiscoveryRateError(
            f"the discovery-rate store's sqlite {DATABASE_URL_ENV} carries no "
            f"database path (feature 346)"
        )
    return Path(path)
