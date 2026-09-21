"""The resident campaign array — §9.3's load, feature 174.

app_spec.xml, "Tree & Artifact Persistence", feature 174: *System loads
one campaign of signal returns as a single dense float32 array of shape
nodes by periods.*  docs/nullius-tech-architecture.md §9.3 is the section
that sentence opens, and it states why the load exists before it states
what it is: *"The real cost is I/O.  A replay revealing 100 nodes reads
~20 MB of Parquet; 200 worlds × 40 policy versions done naively is
~160 GB per dreaming cycle."*  The answer it pins is the one this module
builds — *"Load each campaign's signal returns once as a single dense
``float32`` array of shape ``(nodes × T)``"* — so that ``ir_marginal``
becomes *"array indexing plus a rank-1 update, with no canonical-book
cache anywhere."*

**One array, two axes, and both are orderings the store already owns.**
The row axis is the campaign's nodes, in the store's own sorted listing
(:meth:`~artifacts.ArtifactStore.node_ids`) — the same order every
sweep of the tree walks, so a row's index is a fact about the campaign
rather than about which readdir happened first.  The column axis is the
campaign's periods: the sorted union of the rebalance dates the swept
panels priced at the pinned horizon — the market calendar §6.1's
alignment steps on, answered at campaign scale.  Every cell is one
``float32``: row-major, node after node, so a node's whole row is one
contiguous span and the resident set §9.3 sizes — *500 nodes × 2000
periods × 4 B = 4 MB per campaign* — is the buffer this module answers,
exactly, with nothing else riding along.

**float32 is the decision, and it is the opposite of the file's.**  The
grid on disk keeps ``float64`` because a stored measurement keeps the
double the evaluator computed (:mod:`artifacts._returns` says so in as
many words); this array narrows to ``float32`` because it is the
*resident replay* payload, where 500 nodes × 2000 periods must fit in
4 MB.  The narrowing happens once, at load, over the equal-weight mean
(see below) — never per read — and a mean too large for a ``float32``
to hold refuses rather than silently becoming ``inf``: an infinity in
the resident array would reach every rank-1 update dressed as a
measurement, which is the exact failure the file layer's non-finite
refusal exists to prevent, restated for the derived array.  (A mean too
*small* to survive narrowing underflows toward zero, as arithmetic
everywhere does; underflow is rounding, not invention.)

**One number per node per period, and it is the T-vector replay
measures with.**  §9.3: *"after portfolio construction each signal
contributes a single T-vector."*  The file's grain is ``(date, horizon,
symbol)`` — three axes — so loading it into two means collapsing two of
them, and both collapses are the evaluator's own, not new mathematics:

* *the horizon is pinned, one for the whole campaign.*  The panel is
  five horizons deep and a dense array holds one, so the load pins
  :data:`CAMPAIGN_LOAD_HORIZON` — the shortest horizon every node's
  panel covers, which is the evaluator's own
  ``METRICS_HORIZON`` policy ("the shortest horizon the priced panel
  covers", :mod:`evaluator._metrics`) restated at campaign scale: the
  fastest-turning, best-evidenced, hardest-hit horizon is the axis
  ``ir_marginal`` sits on, and a function of the panels rather than a
  caller's guess is what makes two loads of one campaign answer the
  same array.  A caller measuring at another horizon may pin it with
  ``horizon=``; the panels are on disk in full precisely so another
  axis can be loaded, and the default is a policy rather than a knob.
* *the symbols are collapsed equal-weight.*  The per-date value is the
  mean over the symbols that date holds — ``fsum`` over the day's
  post-cost returns divided by their count — which is feature 80's own
  reduction of a priced panel to "the equal-weight book's" per-date
  return, the very series ``ir_standalone`` and ``ir_marginal`` are
  defined over.  Equal-weight within each date's *own* cross-section
  (1/N on the N symbols that date holds), so a symbol entering or
  leaving the panel re-weights the day the way the turnover metric
  says it does; the value densified is the ``post_cost_return`` — the
  number §9.2 calls "after costs" — while the charge stays answerable
  from the file, which is what the file carrying all three numbers is
  *for*.

**Absence is not zero, and in a dense array absence is NaN.**  A node's
panel at the pinned horizon covers the dates it priced and not the
dates it did not — the trailing edge above all, where the last ``h``
dates have no ``h``-period future — and a campaign whose nodes were
priced on aligned windows still disagrees at the edges.  The dense
shape has a cell for every ``(node, period)`` regardless, and the
honest fill for a cell no panel measured is the IEEE quiet NaN: the
one value float32 defines that cannot be mistaken for a measurement,
and the convention every dense numeric array uses for "no data here".
Zero would be the lie — zero is a *measurement* ("the signal returned
nothing"), and the alignment layer's own rule ("a target that cannot
be computed is **absent**, never zero-filled and never NaN" — that
rule governs *stored targets*, where a row is a measurement and NaN
would be one nobody wrote) inverts here precisely because this array
is not a store: it is a derived, resident reshaping of one, where the
NaN *marks* the absent row rather than impersonating one.  What the
load refuses outright is the whole-row absence — a node whose panel
covers no date at the pinned horizon — because that is not an absent
cell but a node the pinned axis does not answer, and a row of pure NaN
would let a caller index a node that was never loaded for.  A caller
that needs to know which cells are measurements asks the array (NaN
test) or the file (:func:`~artifacts.signal_returns`, every row,
nothing reduced); nothing downstream may read a NaN as a zero.

**The load reads through the read side §1 grants replay, and nothing
else.**  Every panel comes back through :func:`~artifacts.signal_returns`
— the same decode, the same strictness, the same refusals — so a
tampered file fails the campaign load exactly where it fails a single
node's read, and this module adds no second decoder to trust.  The
sweep is the store's own listing: staged-but-uncommitted nodes are
invisible (the discipline feature 169 states, holding here too — a
campaign load never sees a half-written node), a node whose published
directory holds no ``signal_returns.parquet`` refuses the load naming
the node (the grid is the key artifact; a load that silently skipped
the node would answer an array that under-reports the campaign replay
is about to score), and a campaign holding no node directories at all
refuses as a fact about the store's contents rather than answering an
empty array no replay could score.

**One campaign, one sealed world, one schedule.**  Each panel's
identity — the sealed snapshot and feature 59's ``(venue, version)``
pair — rides in its file's schema metadata, one value per file.  A
campaign array joins those files into one measurement axis, so the load
is the seam where the per-file identity has to become a per-campaign
fact: panels that disagree on the snapshot were measured in different
sealed worlds (their "periods" are different calendars wearing the same
dates), and panels that disagree on the cost pair were priced under
different schedules (their "post-cost" numbers are different
quantities).  Either disagreement refuses, naming both spellings and
the nodes that carry them, because the alternative is an array whose
columns compare measurements no metric is defined over — and the agreed
triple is answered on :class:`CampaignReturns`, so a caller holding the
resident array also holds the world it was measured in.

**The buffer is stdlib, and that is load-bearing.**  The dense array is
:class:`array.array` — ``'f'``, C float, 4 bytes, IEEE 754 binary32 on
every platform Python builds for — not a third-party tensor: the member
declares pyarrow for the *file* format and the load reaches it only
through the read seam that already declares it, so the resident payload
adds no dependency at all.  ``array.array`` is contiguous and supports
the buffer protocol, so the day a consumer wants to hand it to numpy
(``np.frombuffer``) or Arrow it can, zero-copy; and it is mutable by
design, because the value this record carries is the buffer §9.3 says
to *pin* — the record is frozen in its shape and its axes (they are the
campaign's identity), while the buffer is the resident payload itself,
the thing feature 175 holds in memory and feature 178's rank-1 update
indexes.  A frozen record over a mutable buffer is the same split the
snapshot member makes between a seal's identity and the bytes it vouches
for.

**Validated at construction, both directions.**  The loader refuses
before it answers (above), and :class:`CampaignReturns` refuses a
hand-built value that is not the shape this module answers: unsorted or
repeated axes, a buffer of the wrong typecode or the wrong length, a
non-finite entry that is not the absent NaN.  A caller can therefore
not construct the lying spellings — a "campaign" whose row order is
insertion order, a "dense" array with a ragged spine — any more than
the writer of :class:`~artifacts.SignalReturns` can stage a panel its
own reader refuses.
"""

from __future__ import annotations

import array as _array
import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from ._errors import ArtifactNotFoundError, ArtifactStoreError
from ._keys import validate_campaign_id
from ._returns import SignalReturns, _validated_horizon, signal_returns
from ._store import ArtifactStore

__all__ = [
    "ABSENT",
    "CAMPAIGN_LOAD_HORIZON",
    "FLOAT32_TYPECODE",
    "CampaignReturns",
    "load_campaign_returns",
]

#: The typecode of the resident array — :mod:`array`'s spelling of C
#: ``float``, IEEE 754 binary32, 4 bytes on every platform CPython builds
#: for.  §9.3's arithmetic (``500 nodes × 2000 periods × 4 B = 4 MB``) is
#: arithmetic about *this* width, so the code is spelled once where the
#: sizing it answers for is named, and ``itemsize`` is checked against it
#: at construction — a buffer of any other width is not the array §9.3
#: sizes.
FLOAT32_TYPECODE = "f"

#: The value an unmeasured cell carries — the IEEE quiet NaN, spelled once
#: so the writer (the loader), the reader (any consumer testing a cell) and
#: the tests this feature owns share one marker instead of three spellings
#: of ``float("nan")`` that a refactor could drift apart.  NaN and not zero
#: because zero is a measurement ("the signal returned nothing") and an
#: unmeasured cell is the *absence* of one — see the module docstring for
#: why that rule inverts between the stored targets and this derived array.
ABSENT = float("nan")

#: The horizon the campaign array is loaded over — a *policy*, not a
#: number, and the evaluator's own (:data:`METRICS_HORIZON <evaluator.
#: _metrics.METRICS_HORIZON>`, "the shortest horizon the priced panel
#: covers") restated at campaign scale: the shortest horizon **every**
#: node's panel covers, because a dense array is one horizon deep for all
#: its rows at once.  The resolved value for a given load is
#: :attr:`CampaignReturns.horizon`; this name is the policy the resolution
#: implements, the axis ``ir_marginal`` sits on, and the reason two loads
#: of one campaign answer the same array without a caller choosing
#: anything.  A caller measuring at another horizon pins it explicitly —
#: the panels are stored in full so that another axis can be loaded.
CAMPAIGN_LOAD_HORIZON: str = (
    "the shortest horizon every node of the campaign covers"
)


# -- The campaign array, as a value -------------------------------------------------


@dataclass(frozen=True)
class CampaignReturns:
    """One campaign's returns resident — the dense ``nodes × periods`` array.

    The value :func:`load_campaign_returns` answers: the two identities
    the load was keyed by and agreed on (the campaign, and the sealed
    snapshot plus cost-model pair every swept panel named), the pinned
    horizon the values were reduced over, the two axes in their one
    order, and the float32 buffer itself — one cell per ``(node,
    period)``, row-major, :data:`ABSENT` where no panel measured.

    The axes and the identity are frozen — they are facts about the
    campaign, not editable state — while :attr:`values` is the mutable,
    contiguous buffer §9.3 says to pin: the record is the *shape* the
    replay indexes, the buffer is the resident payload it indexes into.
    Validated at construction (see the module docstring), so a value
    built by hand fails here rather than answering a campaign nobody
    loaded.
    """

    #: The campaign the array loads — §9.2's first key.
    campaign_id: str
    #: The sealed snapshot every swept panel named — the one world the
    #: measurements were taken in, checked agreed at load.
    snapshot_name: str
    #: Feature 59's venue — the one fee schedule that priced the panels.
    venue: str
    #: Feature 59's version — that schedule's version.
    version: str
    #: The horizon the values were reduced over — the resolved
    #: :data:`CAMPAIGN_LOAD_HORIZON`, or the horizon a caller pinned.
    horizon: int
    #: The row axis — the campaign's nodes, sorted, the store's own
    #: listing order.
    node_ids: tuple[str, ...]
    #: The column axis — the campaign's periods, sorted, the union of the
    #: rebalance dates the panels priced at the pinned horizon.
    periods: tuple[dt.date, ...]
    #: The resident array — ``float32``, row-major, one cell per
    #: ``(node, period)``, :data:`ABSENT` where unmeasured.
    values: _array.array

    def __post_init__(self) -> None:
        for field in ("campaign_id", "snapshot_name", "venue", "version"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ArtifactStoreError(
                    f"a resident campaign array names the {field.replace('_', ' ')} "
                    f"its measurements belong to — got {value!r}; §9.3's array is "
                    "one campaign's returns as one sealed snapshot measured them "
                    "under one fee schedule, and an array missing any of the "
                    "three cannot say what it is an array of"
                )
        horizon = _validated_horizon(self.horizon)
        nodes = _validated_axis_text(self.node_ids, "node_ids")
        periods = _validated_axis_dates(self.periods)
        if not isinstance(self.values, _array.array):
            raise ArtifactStoreError(
                "a resident campaign array's values are a float32 buffer — an "
                f"array.array, got {type(self.values).__name__}; the dense "
                "nodes × periods load answers one contiguous buffer a replay "
                "can pin (§9.3), and any other spelling of it is not that"
            )
        if self.values.typecode != FLOAT32_TYPECODE:
            raise ArtifactStoreError(
                "a resident campaign array's values are float32 — an "
                f"array.array of {FLOAT32_TYPECODE!r}, got typecode "
                f"{self.values.typecode!r} ({self.values.itemsize} bytes per "
                "cell); §9.3's sizing (500 nodes × 2000 periods × 4 B = 4 MB "
                "per campaign) is arithmetic about binary32, and a buffer of "
                "another width is either a different decision or a mistaken one"
            )
        expected = len(nodes) * len(periods)
        if len(self.values) != expected:
            raise ArtifactStoreError(
                f"a resident campaign array of {len(nodes)} nodes × "
                f"{len(periods)} periods holds {expected} cells — its buffer "
                f"holds {len(self.values)}; the dense shape is the whole point "
                "(§9.3), and a buffer that does not fill it is a campaign "
                "nobody loaded"
            )
        for position, value in enumerate(self.values):
            # NaN is the one non-finite value the buffer may carry, and only
            # as the absent marker; an inf is a measurement that overflowed
            # its float32 cell and would reach every rank-1 update dressed
            # as a number the evaluator computed.
            if math.isinf(value):
                raise ArtifactStoreError(
                    f"a resident campaign array carries the non-finite value "
                    f"{value!r} at cell {position} (node "
                    f"{nodes[position // len(periods)]!r}, period "
                    f"{periods[position % len(periods)].isoformat()}); the "
                    "loader narrows finite means, so an infinity is a value "
                    "built by hand or a buffer edited outside this package — "
                    "not a measurement any rank-1 update should trust"
                )
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "node_ids", nodes)
        object.__setattr__(self, "periods", periods)

    @property
    def shape(self) -> tuple[int, int]:
        """The dense shape — ``(nodes, periods)``, the feature's own words.

        Row count first, column count second: the buffer is row-major, so
        the shape is the pair that turns a flat index back into the
        ``(node, period)`` it addresses.
        """
        return (len(self.node_ids), len(self.periods))

    @property
    def footprint_bytes(self) -> int:
        """The RAM the resident buffer holds — cells × 4 B, §9.3's sizing.

        The measurement half of feature 175's sentence (*"...holding
        roughly 4 MB per campaign of 500 nodes"*): §9.3 sizes the
        residency with ``500 nodes × 2000 periods × 4 B = 4 MB per
        campaign``, and this is that arithmetic as a fact of the record
        rather than a comment beside it — one cell per ``(node,
        period)`` at the width :data:`FLOAT32_TYPECODE` pins, so the
        campaign §9.3 describes answers exactly ``4_000_000`` and a hold
        over any number of resident arrays (:mod:`artifacts._pins`) is
        a sum of these, never a guess.  The axes are the array's
        identity; this is what the payload *weighs*.
        """
        return len(self.values) * self.values.itemsize

    def row(self, node_id: str) -> _array.array:
        """One node's T-vector — its contiguous ``periods`` cells, float32.

        The single §9.3 says each signal contributes: the equal-weight
        per-date post-cost return at the pinned horizon, ``periods`` long,
        as a slice of the resident buffer (a copy in the ``array`` module's
        own spelling — same typecode, same width — so a consumer can hold
        it without pinning the whole campaign).  Refuses a node the array
        does not hold, naming the campaign, because a row an axis never
        addressed is a row nobody loaded.
        """
        try:
            index = self.node_ids.index(node_id)
        except ValueError:
            raise ArtifactStoreError(
                f"the campaign array of {self.campaign_id!r} holds no row for "
                f"node {node_id!r} — it holds {len(self.node_ids)} rows; a "
                "node the load never swept has no T-vector to answer"
            ) from None
        width = len(self.periods)
        return self.values[index * width : (index + 1) * width]

    def cell(self, node_id: str, period: dt.date) -> float:
        """One cell — the node's float32 return at the period, or ABSENT.

        The array indexing §9.3 wants ``ir_marginal`` to be: one node, one
        period, one ``float32``, with :data:`ABSENT` (NaN) for a cell no
        panel measured — a value the caller must test, not read.  Refuses
        an axis value the array does not hold, naming which half was wrong.
        """
        if isinstance(period, dt.datetime):
            raise ArtifactStoreError(
                f"a period of the campaign array of {self.campaign_id!r} is a "
                f"rebalance date — got the datetime {period!r}; a datetime is "
                "a date in Python and would pass a naive check, but the "
                "column axis is the market calendar the panels priced"
            )
        try:
            row_index = self.node_ids.index(node_id)
        except ValueError:
            raise ArtifactStoreError(
                f"the campaign array of {self.campaign_id!r} holds no row for "
                f"node {node_id!r} — it holds {len(self.node_ids)} rows"
            ) from None
        try:
            column = self.periods.index(period)
        except ValueError:
            raise ArtifactStoreError(
                f"the campaign array of {self.campaign_id!r} holds no column "
                f"for period {period.isoformat() if isinstance(period, dt.date) else period!r} "
                f"— it holds {len(self.periods)} periods"
            ) from None
        return self.values[row_index * len(self.periods) + column]


# -- The load ----------------------------------------------------------------------


def load_campaign_returns(
    store: ArtifactStore, campaign_id: str, *, horizon: int | None = None
) -> CampaignReturns:
    """Load one campaign's signal returns as the dense resident array.

    The feature's sentence as one call: every node the campaign's store
    listing holds is read back through :func:`~artifacts.signal_returns`
    — the read side §1 grants the replay engine, and the only decoder
    this load trusts — reduced per node to the equal-weight per-date
    post-cost return at the pinned horizon, and answered as one
    contiguous ``float32`` buffer of shape ``(nodes, periods)`` with the
    axes spelled out beside it.  §9.3's answer to the replay bottleneck:
    the Parquet is read once, here, and everything downstream is array
    indexing.

    The horizon is :data:`CAMPAIGN_LOAD_HORIZON` — the shortest horizon
    every swept panel covers — unless ``horizon`` pins another one
    explicitly (the panels are stored in full so another axis can be
    loaded; the default is the policy that makes two loads of one
    campaign answer the same array).

    Refusals, each naming what it refuses: a campaign whose store holds
    no node directories (:class:`~artifacts.ArtifactNotFoundError` — a
    fact about the store's contents, not a breakage); a node whose
    published directory holds no ``signal_returns.parquet`` (the grid is
    the key artifact, and a load that skipped the node would under-report
    the campaign); panels sharing no horizon at all, or a pinned horizon
    some panel covers no date of; panels disagreeing on their sealed
    snapshot or their ``(venue, version)`` cost pair; a mean too large
    for a ``float32`` cell.  Nothing is zero-filled, and nothing is
    reduced beyond the one collapse the dense shape demands.
    """
    validate_campaign_id(campaign_id)
    node_ids = store.node_ids(campaign_id)
    if not node_ids:
        raise ArtifactNotFoundError(
            f"no artifact directories are persisted under campaign "
            f"{campaign_id!r} (looked under {store.root}); the dense "
            "nodes × periods load sweeps the campaign's nodes, and a "
            "campaign holding none — never persisted, or every write "
            "discarded before committing — has no signal returns to load"
        )
    panels = {
        node_id: signal_returns(store, campaign_id, node_id)
        for node_id in node_ids
    }
    pinned = _pinned_horizon(campaign_id, panels, requested=horizon)
    snapshot_name, venue, version = _agreed_identity(campaign_id, panels)
    vectors: dict[str, dict[dt.date, float]] = {}
    covered: set[dt.date] = set()
    for node_id in node_ids:
        vector = _node_vector(
            panels[node_id], pinned, campaign_id=campaign_id
        )
        vectors[node_id] = vector
        covered.update(vector)
    periods = tuple(sorted(covered))
    column_of = {day: column for column, day in enumerate(periods)}
    width = len(periods)
    values = _array.array(
        FLOAT32_TYPECODE, [ABSENT] * (len(node_ids) * width)
    )
    for row_index, node_id in enumerate(node_ids):
        offset = row_index * width
        for day, mean in vectors[node_id].items():
            position = offset + column_of[day]
            values[position] = mean
            if math.isinf(values[position]):
                # The mean is finite in float64 (the file refused anything
                # else); an infinity here is the float32 cell overflowing,
                # and an overflowed measurement must not ride the resident
                # array as if the evaluator computed it.
                raise ArtifactStoreError(
                    f"the equal-weight return of node {node_id!r} of campaign "
                    f"{campaign_id!r} on {day.isoformat()} at horizon {pinned} "
                    f"is {mean!r}, which overflows the float32 cell §9.3's "
                    "resident array is sized for; a measurement that cannot "
                    "be narrowed is one the dense load cannot carry"
                )
    return CampaignReturns(
        campaign_id=campaign_id,
        snapshot_name=snapshot_name,
        venue=venue,
        version=version,
        horizon=pinned,
        node_ids=node_ids,
        periods=periods,
        values=values,
    )


# -- The load's own validation, spelled once ----------------------------------------


def _pinned_horizon(
    campaign_id: str,
    panels: dict[str, SignalReturns],
    *,
    requested: int | None,
) -> int:
    """Resolve the one horizon the campaign array is loaded over.

    An explicit ``requested`` horizon is validated as the positive period
    count it must be (:func:`artifacts._returns._validated_horizon`, the
    one spelling of that rule) and answered — whether a panel covers it
    is each panel's own question, answered by :func:`_node_vector`.

    Without one, this resolves :data:`CAMPAIGN_LOAD_HORIZON`: the
    shortest horizon **every** panel covers, the evaluator's
    ``METRICS_HORIZON`` policy at campaign scale.  A dense array is one
    horizon deep for all its rows, so the per-node policy ("the shortest
    *this* panel covers") has to meet the intersection, and an empty
    intersection — panels that share no horizon at all — refuses rather
    than guessing: two panels with no common axis are measurements no
    single dense array is defined over.
    """
    if requested is not None:
        return _validated_horizon(requested)
    shared: set[int] | None = None
    for panel in panels.values():
        covered = {row.horizon for row in panel.rows}
        shared = covered if shared is None else shared & covered
    if not shared:
        raise ArtifactStoreError(
            f"the nodes of campaign {campaign_id!r} share no horizon their "
            "panels all cover — "
            + "; ".join(
                f"node {node_id!r} covers "
                f"{', '.join(str(h) for h in sorted({row.horizon for row in panel.rows})) or 'no horizon'}"
                for node_id, panel in sorted(panels.items())
            )
            + "; a dense nodes × periods array is one horizon deep for every "
            "row at once, so panels with no common horizon are measurements "
            "no single resident array is defined over"
        )
    return min(shared)


def _agreed_identity(
    campaign_id: str, panels: dict[str, SignalReturns]
) -> tuple[str, str, str]:
    """The one ``(snapshot, venue, version)`` triple every panel names.

    Each panel's identity rides in its file's schema metadata, one value
    per file; the campaign array joins those files into one measurement
    axis, so the load is where the per-file identity has to hold as one
    per-campaign fact.  Panels disagreeing on the snapshot were measured
    in different sealed worlds, panels disagreeing on the cost pair were
    priced under different schedules, and either disagreement refuses
    naming both spellings — because the alternative is an array whose
    columns compare measurements no metric is defined over.
    """
    by_triple: dict[tuple[str, str, str], list[str]] = {}
    for node_id, panel in panels.items():
        by_triple.setdefault(
            (panel.snapshot_name, panel.venue, panel.version), []
        ).append(node_id)
    if len(by_triple) > 1:
        spelled = "; ".join(
            "measured in snapshot {!r} under cost model ({!r}, {!r}): nodes "
            "{}".format(
                snapshot,
                venue,
                version,
                ", ".join(repr(node) for node in sorted(node_ids)),
            )
            for (snapshot, venue, version), node_ids in sorted(
                by_triple.items()
            )
        )
        raise ArtifactStoreError(
            f"the nodes of campaign {campaign_id!r} do not agree on the "
            "sealed world their returns were measured in — " + spelled + "; "
            "§9.3's array is one campaign's returns as one snapshot measured "
            "them under one fee schedule, and joining worlds or schedules "
            "into one axis would compare measurements no metric is defined "
            "over"
        )
    snapshot, venue, version = next(iter(by_triple))
    return snapshot, venue, version


def _node_vector(
    panel: SignalReturns, horizon: int, *, campaign_id: str
) -> dict[dt.date, float]:
    """One panel reduced to its T-vector — the equal-weight per-date return.

    The two collapses the dense shape demands, both the evaluator's own:
    keep the rows at the pinned horizon, and reduce each date's
    cross-section to the mean of its post-cost returns — ``fsum`` over
    the day's values divided by their count, feature 80's own reduction
    of a priced panel to the equal-weight book's per-date return, the
    series ``ir_standalone`` and ``ir_marginal`` are defined over.
    Equal-weight within each date's *own* cross-section, so a symbol
    entering or leaving the panel re-weights that day the way the
    turnover metric says it does.

    Refuses a panel that covers no date at the horizon: not an absent
    cell but an unanswerable row — a node the pinned axis does not
    measure, which a row of pure NaN would let a caller index as if it
    had been loaded.
    """
    per_date: dict[dt.date, list[float]] = {}
    for row in panel.rows:
        if row.horizon == horizon:
            per_date.setdefault(row.rebalance_date, []).append(
                row.post_cost_return
            )
    if not per_date:
        covered = sorted({row.horizon for row in panel.rows})
        raise ArtifactStoreError(
            f"node {panel.node_id!r} of campaign {campaign_id!r} covers no "
            f"rebalance date at horizon {horizon} — its panel covers "
            f"{', '.join(str(h) for h in covered) or 'no horizon'}; the "
            "dense array is one horizon deep for every row, so a node the "
            "pinned axis does not measure has no row to load (pin the "
            "horizon the panel covers, or persist the panel on the axis "
            "the campaign shares)"
        )
    return {
        day: math.fsum(returns) / len(returns)
        for day, returns in per_date.items()
    }


def _validated_axis_text(values: Any, label: str) -> tuple[str, ...]:
    """The row axis as it must be — non-empty, non-empty-text, sorted, once.

    The store's listing is sorted and unique, and the record's axis is
    that listing spelled once; a hand-built axis in any other order —
    or carrying a node twice, which would give one node two rows of the
    campaign — refuses, because row order is part of the array's
    identity (§9.3's "array indexing" is only deterministic if the index
    is).
    """
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ArtifactStoreError(
            f"the resident campaign array's {label} are the campaign's "
            f"nodes as a sequence of ids — got {type(values).__name__}"
        )
    axis = tuple(values)
    if not axis:
        raise ArtifactStoreError(
            f"the resident campaign array's {label} cannot be empty; the "
            "dense load sweeps a campaign that holds at least one node, and "
            "an empty axis is a campaign nobody loaded"
        )
    for position, value in enumerate(axis):
        if not isinstance(value, str) or not value:
            raise ArtifactStoreError(
                f"the resident campaign array's {label} are node ids — got "
                f"{value!r} ({type(value).__name__}) at position {position}"
            )
    if list(axis) != sorted(axis) or len(set(axis)) != len(axis):
        raise ArtifactStoreError(
            f"the resident campaign array's {label} are the campaign's "
            "sorted node listing, each node once — the axis as given is not "
            "that order; row order is part of the array's identity (§9.3's "
            "array indexing is only deterministic if the index is)"
        )
    return axis


def _validated_axis_dates(values: Any) -> tuple[dt.date, ...]:
    """The column axis as it must be — non-empty, dates, sorted, once.

    The periods are the campaign's market calendar: sorted, each date
    once.  A :class:`~datetime.datetime` is refused before the date
    check (it is a subclass and would pass one) for the same reason the
    file layer refuses instants: a column keyed by an instant is one no
    rebalance date can address.
    """
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ArtifactStoreError(
            "the resident campaign array's periods are the campaign's "
            f"rebalance dates as a sequence — got {type(values).__name__}"
        )
    axis = tuple(values)
    if not axis:
        raise ArtifactStoreError(
            "the resident campaign array's periods cannot be empty; the "
            "dense load answers the union of the dates the panels priced, "
            "and an empty axis is a campaign nobody loaded"
        )
    for position, value in enumerate(axis):
        if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
            raise ArtifactStoreError(
                "the resident campaign array's periods are calendar dates — "
                f"got {value!r} ({type(value).__name__}) at position "
                f"{position}; the column axis is the market calendar the "
                "panels priced, and a key that is not a date is a period no "
                "rebalance can address"
            )
    if list(axis) != sorted(axis) or len(set(axis)) != len(axis):
        raise ArtifactStoreError(
            "the resident campaign array's periods are the campaign's "
            "sorted market calendar, each date once — the axis as given is "
            "not that order; column order is part of the array's identity, "
            "and a repeated date would give one period two columns"
        )
    return axis
