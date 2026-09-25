"""Feature 341's endpoint: GET /metrics/fdr-deploy, the top-line figure.

app_spec.xml, "Observability & Dashboards", feature 341: *System
exposes GET /metrics/fdr-deploy which returns the base-rate reweighted
false discovery rate as the top-line figure.*  The spec's API summary
spells the route's one line under the Observability domain — ``GET
/metrics/fdr-deploy — Return the base-rate reweighted false discovery
rate`` — and it is the category's root feature: everything the
Observability & Dashboards category adds (342's lamps, 343's coverage,
344-347's and 350's persisted metrics, 348-349's log records, 351-352's
dashboard) depends on 341, because the surface this route establishes
is the one they all hang from.

**The route exists because §16 fixes what the top line is.**
docs/nullius-tech-architecture.md §16 states the observability
category's one binding presentation law in bold:
*"**The top-line dashboard number is ``FDR_deploy``, not Sharpe.**  If
the primary chart is an equity curve, the system's actual purpose has
been quietly abandoned."*  prd §11 makes the same figure the primary
metric (*"``FDR_deploy`` — base-rate-reweighted false discovery rate
(§4.1.3)"*, target *"< 25% at π₀ = 0.9"*), and the app spec's design
system carries the rule over verbatim (*"the top-line number is
FDR_deploy and never an equity curve; any panel that would promote
profit above epistemic state is rejected at review"*).  Before any
dashboard can be held to that law there must be a seam that answers
the number it names, answering nothing else in its place — which is
what this route is: the one place an operator surface asks for the
system's primary figure, and the answer is the reweighted one, never
the raw in-campaign rate prd §4.1.3 bars from the dashboard, never a
Sharpe, never a count.

**The figure is feature 267's, read through feature 267's own store —
never re-spelled here.**  The per-campaign ``FDR_deploy`` rows live in
the scoring member's ``scoring_fdr_deploy`` table, and the read that
serves them carries its own law: the pair is the row's truth, the
figure a derived view, every read *rebuilds* the projection from the
stored pair under the one constant, and a row whose stored figure
disagrees with its own pair — or whose base rate is not the
deployment's — is refused by name.  This module re-spells none of
that: not the table, not π₀, not §4.1.3's arithmetic, not the
corruption refusal.  It reaches the store through the scoring member
itself (:func:`require_scoring`, below), the way the router member
reaches the ingest member's parser — *"rather than growing a second
parser of the same venue response"* — because a second spelling of the
reweighting would be a second place the deployment projection could
drift from the one feature 267 persists and feature 268 publishes, and
prd §4.1.3's formula is the workspace's most explicitly
spelled-once law: feature 268's own spec pins it as *"the publication
seam's one formula, never re-spelled."*  The route is the figure's
third reader (the store, the headline, now the surface), and it holds
that discipline by delegating to the first one.

**This is the route's contract as a Python seam, not an HTTP server.**
The workspace's operations surface is its composed components — every
"exposes" feature in the spec landed as one, feature 94's
:class:`~ledger.keffective_route.KEffectiveEndpoint` (GET
/ledger/k-effective) the closest precedent — and this endpoint
follows: :meth:`FdrDeployEndpoint.get` takes no arguments (a GET over
the deployment's figures has no body and no filter to state) and
returns a :class:`FdrDeployResponse`, with :data:`FDR_DEPLOY_ROUTE`
spelling the route once so the endpoint, the spec's summary and
whatever HTTP adapter lands later cannot drift apart on the name.

**The top-line figure is the newest campaign's, and the order it is
drawn from is the store's own.**  §16's research metrics are *"per
campaign"* figures and prd §12's M3 exit reads them as a trend
(*"`FDR_deploy` improves at π₀ = 0.9"*, a falling sequence), so a
deployment holds *many* figures while the top line is *one* — the
numeral docs/design.md's hero renders beside *"the current campaign
plate"*.  That one is the most recently closed campaign's figure: the
newest row of the trend.  The route draws it from
:meth:`~scoring.FdrDeployStore.history` — the store's own read,
ordered oldest-first by ``computed_at`` then ``campaign_id`` — and
takes the last row, inheriting that order rather than restating it (an
``ORDER BY`` here would be a second spelling of "newest" the store
already owns).  The response identifies the figure it answered — the
campaign it belongs to and the instant it was computed — because a
top-line number an operator cannot attribute to the campaign that
measured it is a number nobody can audit, the same reasoning §16 gives
for carrying *"at π₀ = 0.9"* beside the figure.

**An empty trend is an honest absence, never a zero.**  A deployment
that has never closed a campaign out has no top-line figure, and
feature 267's own stance for exactly that state is the discoverable
one: *"an empty list is the honest answer ... a discoverable state,
not an exception."*  The response answers it with ``None`` figures and
a falsy value — never ``0.0``, because ``0.0`` is a *measurement* (a
campaign that projected to no false discoveries) where an absence is
an absence, and a caller that cannot tell them apart is the caller
prd §4.1.3's under-skeptical policy was made of.  The dashboard this
route feeds renders no numeral for it; what it must never render is a
flawless one.

**Neither an absent store nor a failed read is ever answered with a
number.**  No ``DATABASE_URL`` composes no endpoint
(:meth:`FdrDeployEndpoint.from_env` returns ``None``), the same
degrade-don't-break stance every store-bound builder in this workspace
takes — and the reason is §16's own weight: a top-line figure that
quietly fell back to zero would read as *"this system discovers
nothing falsely"*, which is the one direction that could steer an
operator past prd §11's target.  A configured store whose read *fails*
is translated into this member's vocabulary
(:class:`~ops.errors.FdrDeployMetricError`, the original chained)
rather than propagated raw — the member-seam law the router states
when it narrows the ingest parser's failures into
:class:`~router.errors.RouterFilterError`: a caller that wrote
``except FdrDeployMetricError`` must not be taken down by
:class:`~scoring.FdrDeployError`, an error from a module this route's
caller never imported — and it is never caught *into* an answer,
because every fallback this route could add is a number nobody
measured.

**The response validates what it holds.**  The store's read already
rebuilt and checked every figure it answered, but the response is
constructible by hand (tests, a later adapter over a recorded
history), and a frozen value that validated nothing would lend the
route's guarantees to a history nobody stood behind.  So construction
narrows every triple — a non-empty campaign id, a finite real figure
in ``[0, 1]``, a non-empty instant — and refuses instants that run
backwards, because "the last row is the newest" is the route's whole
derivation of the top line and a history whose order lied would
silently top-line the wrong campaign: the quietly-wrong-number failure
this family refuses everywhere else, refused here too.

Stdlib-only, like the rest of the member: :mod:`dataclasses` for the
response, :mod:`math` and :mod:`numbers` for the figures, :mod:`os` for
the environment, :mod:`typing` for ``Optional`` — and the one
cross-member import (:mod:`scoring`), declared in the member's
pyproject and deferred past both module scope *and* builder time
(:class:`_DeferredFdrStore` below) so the factory's scan stays
import-order-safe and composition never depends on a sibling's
presence on ``sys.path``.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any, Optional

from .errors import FdrDeployMetricError

__all__ = [
    "DATABASE_URL_ENV",
    "FDR_DEPLOY_ROUTE",
    "FdrDeployEndpoint",
    "FdrDeployResponse",
    "require_scoring",
]

#: The environment variable naming the relational store — the one
#: spelling every member store in this workspace already uses (the
#: bootstrap member's pool, the replay member's metrics rows, feature
#: 267's own FDR_deploy store), restated here so this module states its
#: own contract and imports no sibling's: the builder reads it eagerly
#: to decide whether a route composes at all, while the store it names
#: is reached through the scoring member at read time (see
#: :class:`_DeferredFdrStore`).
DATABASE_URL_ENV = "DATABASE_URL"

#: The route this endpoint serves — app_spec.xml's API summary row for
#: the Observability domain, spelled once: ``GET /metrics/fdr-deploy —
#: Return the base-rate reweighted false discovery rate``.  Carried on
#: the class (:attr:`FdrDeployEndpoint.route`) so a composed deployment
#: can state its routes from the components it holds rather than from a
#: string that lives somewhere else.
FDR_DEPLOY_ROUTE = "/metrics/fdr-deploy"


def require_scoring():
    """Import and return the :mod:`scoring` member, or raise loudly.

    Called from inside the endpoint's read paths — never at module
    scope, and never at builder time, where the scan has already taken
    the sibling's ``src/`` back off ``sys.path`` — for the reason
    :func:`router.exchange_info.require_ingest` gives for its own
    cross-member import: the factory's workspace scan imports this
    package to fire its ``@register``, and the scan puts one member's
    ``src/`` on ``sys.path`` at a time, so a module-scope ``import
    scoring`` here would make this component's presence in the composed
    application depend on scan order.  Deferring the import keeps this
    member import-safe in every environment the workspace contract
    promises one will be (factory scan, test sandbox, replay path),
    while a deployment that genuinely needs the figure and cannot reach
    the scoring member is told which wheel is missing rather than shown
    a bare :class:`ImportError`.

    The dependency itself is the "never grow a second parser" door the
    router member opened: feature 267's store owns the reweighting, the
    pair-truth read law and the table, and this member reads the figure
    through that one spelling rather than a second.
    """
    try:
        import scoring
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the ops member serves FDR_deploy by reading the scoring "
            "member's per-campaign store (feature 267) rather than "
            "re-spelling the reweighting, and that member is not "
            "importable in this environment; run `uv sync "
            "--all-packages` in the workspace root (or put "
            "packages/scoring/src on sys.path) so the store this route "
            "reads can be reached"
        ) from exc
    return scoring


@dataclass(frozen=True, slots=True)
class FdrDeployResponse:
    """The answer to one GET /metrics/fdr-deploy: the top-line figure.

    ``history`` is the store's whole answer — feature 267's per-campaign
    figures, oldest first, each triple ``(campaign_id, fdr_deploy,
    computed_at)`` already rebuilt from the pair it was measured on —
    and every other read the response offers is derived from it, never
    stored beside it, so the top-line and the trend are one answer
    rather than two that could disagree.  :attr:`fdr_deploy`,
    :attr:`campaign_id` and :attr:`computed_at` are the newest
    campaign's triple unpacked (the figure §16 puts at the top line,
    and the plate that attributes it); :attr:`history` stays reachable
    so prd §12's M3 reader (*"`FDR_deploy` improves"*) and feature
    351's dashboard draw the trend from the same read the numeral came
    from.

    There is deliberately no raw in-campaign rate anywhere on this
    value.  prd §4.1.3 bars that figure from the dashboard in the same
    breath as it fixes the one it wants (*"the raw in-campaign rate is
    an artifact of a design choice and must never be the figure on the
    dashboard"*), feature 267's store refuses to persist it where the
    pair belongs, and feature 268's headline refuses to answer it — a
    response that also carried it would invite at the route exactly the
    substitution those three refusals exist to prevent.

    Every figure is pinned to the deployment base rate by the store's
    own read law before it reaches this seam — a row reweighted at any
    other rate is refused here as a number nobody targeted — so the
    response carries no base-rate field to restate: the projection it
    answers *is* the deployment one, at π₀ = 0.9, and §16's qualifier
    ("``FDR_deploy`` at π₀ = 0.9") is a fact about every number this
    type can hold, not a column beside some of them.

    An empty ``history`` is the honest answer for a deployment that has
    never closed a campaign out: the derived reads answer ``None`` and
    the value is falsy, an absence — never ``0.0``, which would be a
    measurement no campaign made.

    Frozen, because the response is the route's testimony about the
    store at the moment it was read: re-reading answers a fresh value,
    and nothing here is a knob to adjust.
    """

    #: Feature 267's per-campaign figures, oldest first — one
    #: ``(campaign_id, fdr_deploy, computed_at)`` triple per closed
    #: campaign, the figure in each rebuilt from the pair its row
    #: carries.  The trend prd §12's M3 exit reads across.
    history: tuple[tuple[str, float, str], ...] = ()

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so normalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline the ledger member's derived views follow.
        rows: list[tuple[str, float, str]] = []
        previous_instant: Optional[str] = None
        for row in self.history:
            rows.append(_the_triple(row, previous_instant))
            previous_instant = rows[-1][2]
        object.__setattr__(self, "history", tuple(rows))

    # -- the top-line reads -------------------------------------------------

    @property
    def campaign_id(self) -> Optional[str]:
        """The campaign the top-line figure belongs to — its plate.

        ``None`` when no campaign has closed: the hero renders no plate
        beside no numeral, and an operator is told the deployment is
        young rather than shown an id nobody measured.
        """
        return self.history[-1][0] if self.history else None

    @property
    def fdr_deploy(self) -> Optional[float]:
        """The top-line figure — §16's number, the newest campaign's
        ``FDR_deploy``, reweighted at the deployment base rate.

        The one bare ``float`` an operator surface reads off this
        response.  ``None`` is the honest answer for a deployment that
        has closed no campaign — an absence, never ``0.0``, because a
        flawless projection is a measurement and this deployment made
        none.
        """
        return self.history[-1][1] if self.history else None

    @property
    def computed_at(self) -> Optional[str]:
        """When the top-line figure's campaign was computed (ISO 8601
        UTC, second resolution — the label the trend's order reads).

        ``None`` when no campaign has closed.
        """
        return self.history[-1][2] if self.history else None

    def __bool__(self) -> bool:
        """Whether the deployment has closed a campaign at all.

        ``False`` only when the trend is empty — no row was ever
        persisted.  The split this pins is the one the store's own
        ``history()`` states: an empty trend is a discoverable state
        (``False``, render no numeral), distinct from a trend whose
        newest figure is ``0.0`` (``True``, render it).
        """
        return bool(self.history)

    def __len__(self) -> int:
        """How many campaigns the response reports — the trend's size."""
        return len(self.history)


def _the_triple(row: Any, previous_instant: Optional[str]) -> tuple[str, float, str]:
    """Narrow one history row to the ``(campaign_id, fdr_deploy,
    computed_at)`` triple the response holds.

    The store's own read answers rows in exactly this shape, already
    validated — the figure rebuilt from the pair, the instant a
    non-empty ISO 8601 label — but the response is constructible by
    hand, and a frozen value that validated nothing would lend the
    store's guarantees to a history no store answered.  Each field is
    defended exactly as :mod:`scoring._fdr` defends its read: the
    campaign id a non-empty ``str`` (the store's canonical UUID text —
    its canonicalisation is 267's law, restated here only as "not
    empty", never re-derived), the figure a real (``bool`` refused
    before it), finite, inside ``[0, 1]``, the instant a non-empty
    ``str`` whose string order is chronological.

    A row whose instant runs backwards from the one before it is
    refused by name, because *the last row is the newest* is the whole
    of this route's derivation of the top line: a history whose order
    lied would silently top-line the wrong campaign, and the quietly
    wrong number is the one failure direction this family never takes.
    """
    if not isinstance(row, (tuple, list)) or len(row) != 3:
        raise FdrDeployMetricError(
            f"a GET {FDR_DEPLOY_ROUTE} history is a sequence of "
            f"(campaign_id, fdr_deploy, computed_at) triples — one per "
            f"closed campaign, feature 267's own read shape — and this "
            f"entry is not one (got {row!r}, {type(row).__name__}). The "
            f"response is the store's testimony about the trend, and an "
            f"entry that is not one campaign's figure is not testimony "
            f"anything made (feature 341, docs §16)"
        )
    campaign_value, figure_value, instant_value = row
    if not isinstance(campaign_value, str) or not campaign_value.strip():
        raise FdrDeployMetricError(
            f"a GET {FDR_DEPLOY_ROUTE} history is keyed by campaign id, "
            f"and this triple carries none (got campaign_id="
            f"{campaign_value!r}, {type(campaign_value).__name__}). The "
            f"per-campaign rows are keyed by the canonical UUID text "
            f"that joins node.campaign_id (feature 267's law), so an id "
            f"that names no campaign names no figure a top line could "
            f"be drawn from (feature 341, docs §16)"
        )
    if isinstance(figure_value, bool) or not isinstance(figure_value, Real):
        raise FdrDeployMetricError(
            f"fdr_deploy must be the base-rate-reweighted false "
            f"discovery rate — a fraction of declarations — as a real "
            f"number, got {figure_value!r} ({type(figure_value).__name__})"
            f": the top-line figure is prd §11's primary metric, and a "
            f"value that is not a real is not a fraction of anything "
            f"(feature 341, prd §4.1.3)"
        )
    figure = float(figure_value)
    if not math.isfinite(figure):
        raise FdrDeployMetricError(
            f"fdr_deploy must be finite, got {figure_value!r}: a NaN or "
            f"infinite top-line figure would render a number prd §11's "
            f"target cannot judge, and §16's dashboard would display a "
            f"numeral that is not a rate (feature 341, prd §11)"
        )
    if not 0.0 <= figure <= 1.0:
        raise FdrDeployMetricError(
            f"fdr_deploy must be a rate in [0.0, 1.0], got {figure!r}: "
            f"the figure is a fraction of the campaign's declarations "
            f"(prd §4.1.3), so it is bounded by construction, and a "
            f"value outside the bound is a number that has stopped "
            f"being one (feature 341, prd §4.1.3)"
        )
    if not isinstance(instant_value, str) or not instant_value.strip():
        raise FdrDeployMetricError(
            f"a persisted FDR_deploy triple's computed_at is an ISO 8601 "
            f"UTC string — got {instant_value!r} "
            f"({type(instant_value).__name__}). The instant is the label "
            f"the trend's order reads and the top-line figure is drawn "
            f"from the newest row, so a value that is not a nameable "
            f"instant orders nothing (feature 341)"
        )
    if previous_instant is not None and instant_value < previous_instant:
        raise FdrDeployMetricError(
            f"a GET {FDR_DEPLOY_ROUTE} history is oldest-first — the "
            f"store's own order, which the newest row is drawn from as "
            f"the top line — and this triple's computed_at "
            f"({instant_value!r}) runs backwards from the one before it "
            f"({previous_instant!r}). The top-line figure is the last "
            f"row's by construction, so a history whose order lied "
            f"would silently top-line the wrong campaign; the order is "
            f"the store's law and this response holds it, never "
            f"re-sorts around it (feature 341, docs §16)"
        )
    return (campaign_value, figure, instant_value)


class _DeferredFdrStore:
    """The store a composed route will read, resolved at first read.

    :meth:`FdrDeployEndpoint.from_env` reads ``DATABASE_URL`` eagerly —
    whether a route composes at all is a fact about the deployment, and
    the builder must decide it at composition — but it cannot
    *construct* the store there, for the scan-order reason
    :func:`require_scoring` exists: the factory's workspace scan puts
    one member's ``src/`` on ``sys.path`` at a time and has already
    taken the scoring member's off again by the time builders fire, so
    a build-time ``FdrDeployStore(...)`` would import the scoring
    member exactly where that import is not promised to work — and a
    component whose builder raises takes the whole composition down
    with it, which is a far worse failure than the route it broke.

    So the endpoint holds this carrier, which keeps the URL it was
    resolved from (that is the composition fact — the database the
    route and feature 267's store component both point at, pinned by
    tests without reading anything) and constructs the real store on
    the first ``history()``, where the caller is precisely one who
    reached for the figure and therefore runs somewhere the declared
    dependency is importable.  From that first read on, the store is
    the member's own object and every law is its: the read rebuilds
    figures from the pair, refuses corruption, orders oldest-first.

    Duck-shaped exactly as the endpoint's check demands — one
    ``history()`` — because that is the whole contract; nothing here
    re-spells a store behaviour, it only moves the store's construction
    from a moment the import cannot happen to the first moment it must.
    """

    __slots__ = ("_url", "_store")

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._store: Any = None

    @property
    def database_url(self) -> str:
        """The URL ``DATABASE_URL`` named at composition — carried, not
        re-read, so the route cannot drift to a later environment."""
        return self._url

    def history(self):
        """The scoring member's own trend read, over the resolved URL."""
        if self._store is None:
            scoring = require_scoring()
            self._store = scoring.FdrDeployStore(self._url)
        return self._store.history()


class FdrDeployEndpoint:
    """Serves GET /metrics/fdr-deploy over one FDR_deploy store.

    The store is feature 267's (:class:`~scoring.FdrDeployStore`),
    reached through the scoring member rather than re-implemented here
    — see :func:`require_scoring` for the door and the module docstring
    for the law.  Constructed with the store it reads; :meth:`get` is
    the route.  The endpoint holds no state of its own — no cache of a
    previous answer, no memo of a figure — because the top-line number
    must be the store's state at the moment it is asked for: a campaign
    closed between two reads must move the second answer, and a cached
    figure would make the dashboard's numeral a fact about when the
    reader happened to start rather than about what the system measured.

    The carrier is duck-checked, never ``isinstance``-guarded, for the
    reason every seam in this workspace gives: the factory's scan
    imports members under synthetic names, so a *composed* store is
    structurally the scoring member's and never the same class object a
    direct import yields.  The contract is the one read the route
    needs — ``history()`` — and that is what is checked; an object that
    can only answer one campaign's figure is not enough here, because
    the top line is drawn from the whole trend's order.
    """

    #: The route this endpoint serves — :data:`FDR_DEPLOY_ROUTE`, pinned
    #: as a class attribute so ``FdrDeployEndpoint.route`` states the
    #: contract without an instance.
    route = FDR_DEPLOY_ROUTE

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "history", None)):
            raise TypeError(
                "FdrDeployEndpoint speaks an FDR_deploy store (something "
                "with a history() trend read); got "
                f"{type(store).__name__}. The route returns the "
                "base-rate-reweighted false discovery rate as the "
                "top-line figure (feature 341, docs §16), and the "
                "top line is the newest row of the per-campaign trend "
                "feature 267's store answers — a carrier that cannot "
                "answer the trend cannot name the figure."
            )
        self._store = store

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["FdrDeployEndpoint"]:
        """The endpoint over the store ``DATABASE_URL`` names, or
        ``None`` when it names none.

        The URL is resolved eagerly — whether a route composes at all
        is a fact about the deployment, read from
        :data:`DATABASE_URL_ENV` with the same unset semantics every
        member store's resolution takes (absent, empty and
        whitespace-only all count as unset) — but the *store* it names
        is deferred to the first read
        (:class:`_DeferredFdrStore`), because a builder runs at
        composition and the factory's scan has already taken the
        scoring member's ``src/`` off ``sys.path`` by then: an import
        here would make this component's presence depend on scan order,
        the exact fragility :func:`require_scoring`'s deferral exists
        to avoid.  A caller that actually reads the figure runs where
        the declared dependency is importable, and that is where the
        store is constructed — over the same URL, so this route, the
        composed ``scoring-fdr-deploy`` component and every other
        reader of the per-campaign rows always point at the one
        database (§16's "single Postgres metrics table" allowance).

        No ``DATABASE_URL`` composes no endpoint — an unconfigured
        store is a discoverable state, not an error — while a
        deployment whose operator surface must read the top-line figure
        is the one that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(_DeferredFdrStore(raw))

    @property
    def store(self) -> Any:
        """The store this endpoint reads — feature 267's, held
        duck-typed across the member seam.  For an endpoint built by
        :meth:`from_env` this is the deferred carrier
        (:class:`_DeferredFdrStore`) until the first read: it carries
        the resolved ``database_url`` from composition and constructs
        the scoring member's store only where reading the figure
        actually happens."""
        return self._store

    # -- The route ----------------------------------------------------------

    def get(self) -> FdrDeployResponse:
        """Answer one GET /metrics/fdr-deploy: the top-line figure.

        The whole of feature 341 at its seam.  The route takes no
        arguments: a GET over the deployment's figures has no body, and
        the top line is the figure the *whole* trend names — a filtered
        ask (one campaign's number) is the store's own ``fdr(campaign)``
        read, not this route's.  The read is the store's ``history()``,
        every time: the figures arrive already rebuilt from the pair
        each row carries, at the deployment base rate, with a corrupt
        row refused there before it can reach a dashboard.

        A read that fails is translated into this member's vocabulary
        and chained to the original — a caller that catches
        :class:`~ops.errors.FdrDeployMetricError` must not be taken down
        by the scoring member's :class:`~scoring.FdrDeployError` — and
        nothing is ever caught *into* an answer, because every fallback
        this route could add is a number nobody measured.  An empty
        trend is not a failure: the response answers it with ``None``
        figures, the honest absence feature 267's own read states for a
        deployment that has never closed a campaign out.
        """
        scoring = require_scoring()
        try:
            rows = tuple(self._store.history())
        except scoring.FdrDeployError as exc:
            # The store's own refusal, translated at the member seam:
            # the rows are the scoring member's, the route is this
            # member's, and the vocabulary must live where the caller
            # catches it.  The original is chained so the operator still
            # sees the store's own words — never swallowed, never
            # retried, and never answered around.
            raise FdrDeployMetricError(
                f"could not answer GET {FDR_DEPLOY_ROUTE}: the "
                f"FDR_deploy store refused the trend read: {exc!r}. The "
                f"figure this route serves is docs §16's top-line "
                f"number and prd §11's primary target, so a store that "
                f"cannot be asked is surfaced rather than answered "
                f"around; the repair is the store's (the original "
                f"refusal is chained), never a fallback number "
                f"(feature 341, docs §16)"
            ) from exc
        return FdrDeployResponse(history=rows)
