"""Feature 343's endpoint: GET /metrics/regime-coverage, the pool's
distribution across strata.

app_spec.xml, "Observability & Dashboards", feature 343: *System exposes
GET /metrics/regime-coverage which returns stored world counts per
stratum.*  The spec's API summary spells the route's one line under the
Observability domain — ``GET /metrics/regime-coverage — Return stored
world counts per regime stratum`` — directly beneath feature 341's
top-line figure and feature 342's lamps; the category's foundation is
341 (*"every later feature in the category declares
``depends_on="341"``"*), and this is the second figure to hang from the
surface that route established.

**The route exists because §C7's ledger is only a remedy if it is
visible.**  docs/alpha-engine-prd.md §C7 states the failure it was
written against — *"Run six months in low-vol chop and your entire pool
is low-vol chop; the meta-policy learns a chop-optimal search policy and
you find out when the regime breaks"* — and names three remedies, the
first of which is *"Maintain an explicit ledger:
``{high-vol trend: 2, low-vol chop: 14, crash: 0, …}``"*.  Feature 283's
store persists exactly that ledger and feature 284's read answers it,
but a ledger nobody can *ask for* across a process boundary is a paper
trail, and §C7's whole danger is that the skew is invisible until it is
paid for.  docs/nullius-tech-architecture.md counts the ledger among the
campaign's research metrics (§909: *"regime coverage ledger"*), and the
risk table's *"Replay pool is regime-monotone | High | §C7 coverage
ledger with promotion block"* is the operator's reason to look.  So this
route is the seam an operator surface asks the question through, and the
answer is **counts per stratum** — the distribution — with nothing else
in its place: not a coverage percentage, not a diversity verdict, not a
sum, and never a defaulted zero for a stratum nobody counted.

**The counts are feature 284's, read through the regime member's own
store — never re-spelled here.**  The per-stratum rows live in the
``regime_coverage`` table feature 107's migration declares, and both
halves of that table are the regime member's: feature 283's
:class:`~regime.RegimeCoverage` writes and reads one stratum's row, and
feature 284's :meth:`~regime.RegimeCoverage.ledger` is the member's
*only* whole-table ``SELECT``, answering a
:class:`~regime.CoverageLedger` with the named-empty set, the covered
set and the vocabulary holes as views derived on demand.  This module
re-spells none of that: not the table, not the columns, not the
``ORDER BY``, not the named-empty-versus-absent distinction, not the
corruption refusal.  It reaches the store through the regime member
itself (:func:`require_regime`, below), the way this member's fdr-deploy
route reaches feature 267's store through the scoring member — *"rather
than growing a second spelling"* — because a second whole-ledger read
would be a second place the pool's distribution could drift from the one
feature 284 answers and feature 285's promotion block and feature 289's
diversity refusal both judge.

**The one shape the route takes from the regime member is §C7's own.**
Feature 284's :attr:`CoverageLedger.counts` is *"the ledger in §C7's own
shape — ``{name: world_count}``"*, and its own docstring names this
feature as the reason it exists: *"the shape the spec's API summary
writes the endpoint in (…, feature 343)"*.  So :meth:`RegimeCoverage
Endpoint.get` reads ``ledger().counts`` — the regime member's derived
view, built from the rows its own read already validated and sorted —
rather than walking ``rows`` and rebuilding the mapping here.  What
crosses the member seam is plain data (stratum names and integers), not
the regime member's value types, exactly as the fdr-deploy route carries
``(campaign_id, fdr_deploy, computed_at)`` triples rather than the
scoring member's classes.

**This is the route's contract as a Python seam, not an HTTP server.**
The workspace's operations surface is its composed components — every
"exposes" feature in the spec landed as one, feature 94's
:class:`~ledger.KEffectiveEndpoint` (GET /ledger/k-effective) the
closest precedent outside this member and feature 341's own endpoint the
one inside it — and this route follows: :meth:`RegimeCoverageEndpoint.get`
takes no arguments (a GET over the ledger has no body and no stratum to
filter by) and returns a :class:`RegimeCoverageResponse`, with
:data:`REGIME_COVERAGE_ROUTE` spelling the route once so the endpoint,
the spec's summary and whatever HTTP adapter lands later cannot drift
apart on the name.

**An empty ledger is an honest absence, and it is not the same fact as
an unconfigured store.**  Two states that a careless surface would
collapse into one answer, kept apart on this side as feature 284 keeps
them apart on its own:

* **no store** — nothing names a database, so no route composes at all
  (:meth:`RegimeCoverageEndpoint.from_env` returns ``None``).  The
  deployment has nowhere a count could have been persisted, which is a
  different statement from a pool nobody has counted; feature 284's own
  :func:`~regime.read_ledger` refuses *by name* for exactly this reason
  (*"answering ``()`` would report coverage is zero everywhere about a
  system whose coverage was never counted"*), and the composed
  application answers it the way every store-bound builder in this
  workspace does — by carrying no component.
* **an empty ledger** — a configured database where no census has run
  yet names no stratum.  That is a real answer about a real pool: the
  response holds no rows, :attr:`RegimeCoverageResponse.counts` is an
  empty mapping and the value is falsy.  It is deliberately **not** an
  answer of ``0`` for each of :data:`~regime.DEFAULT_STRATA`, because a
  zero is a *measurement* — §C7's own ``crash: 0`` is a counted stratum
  — and a surface that stamped three zeroes onto an uncounted pool would
  report a distribution nobody measured, in the one direction §C7's
  ledger exists to make impossible.

**A stratum named and holding no worlds is a row; a stratum nobody
named is absent.**  Feature 107's detail 1 is the load-bearing
distinction under this route and the reason the answer is a mapping of
*rows* rather than a vocabulary: ``{"crash": 0}`` is a stratum the
census has counted and found empty — the state feature 286's
``empty_stratum`` warning fires on, and a finding an operator must see —
while a stratum missing from the mapping is one nobody has named, which
feature 286 must *not* report.  This route answers the mapping and lets
the two states stay distinguishable by presence alone; it never fills a
missing stratum in, and it never drops a zeroed one, because either edit
would make the answer a statement about a vocabulary instead of a
statement about the pool.

**No sum, no percentage, no verdict.**  The sentence asks for stored
world counts *per stratum*, and a route that also answered a total would
be answering a figure the system never measured: §C7's ledger is the
*shape* of the pool across regimes, and a five-stratum ledger holding
twenty worlds totals to a number that tells an operator nothing about
whether the next regime is covered — the pool's size is not its
distribution, and the two questions have different answers.  The richer
reads the category does build — feature 285's promotion block, feature
289's diversity floor, feature 286's warning — are judgements over this
ledger rather than figures on this route, and each is that feature's own
seam.  So the response carries the strata and their counts, and the
derived read an operator surface needs (§C7's own mapping), and stops.

**Neither an absent store nor a failed read is ever answered with a
number.**  No ``DATABASE_URL`` composes no endpoint, the degrade-don't-
break stance every store-bound builder in this workspace takes — and a
configured store whose read *fails* is translated into this member's
vocabulary (:class:`~ops.errors.RegimeCoverageMetricError`, the original
chained) rather than propagated raw — the member-seam law feature 341's
route states when it narrows the scoring store's failure into
:class:`~ops.errors.FdrDeployMetricError`: a caller that wrote
``except RegimeCoverageMetricError`` must not be taken down by
:class:`~regime.CoverageError`, an error from a module this route's
caller never imported.  And it is never caught *into* an answer, because
every fallback this route could add is a distribution nobody counted —
``{}`` for a broken database would read as *an empty ledger*, which is
the honest-absence answer above wearing a state it does not have.

**The response validates what it holds.**  The regime member's read
already validated and sorted every row it answered, but the response is
constructible by hand (tests, a later adapter over a recorded ledger),
and a frozen value that validated nothing would lend this route's
guarantees to a distribution nobody stood behind.  So construction
narrows every pair — a non-empty stratum name, a genuine non-negative
integer count (``bool`` refused first) — refuses a stratum named twice,
and sorts by stratum, the same canonical order feature 284's read
imposes and for the same reason: the display must not change because two
readings reached the same rows in a different order.

Stdlib-only, like the rest of the member: :mod:`dataclasses` for the
response, :mod:`os` for the environment, :mod:`collections.abc` for the
mapping check, :mod:`typing` for ``Optional`` — and the one cross-member
import (:mod:`regime`), declared in the member's pyproject and deferred
past both module scope *and* builder time
(:class:`_DeferredRegimeStore` below) so the factory's scan stays
import-order-safe and composition never depends on a sibling's presence
on ``sys.path``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from .errors import RegimeCoverageMetricError

__all__ = [
    "OPS_REGIME_COVERAGE_COMPONENT_NAME",
    "REGIME_COVERAGE_ROUTE",
    "RegimeCoverageEndpoint",
    "RegimeCoverageResponse",
    "require_regime",
]

#: The environment variable naming the relational store — the one
#: spelling every member store in this workspace already uses, restated
#: here so this module states its own contract and imports no sibling's:
#: the builder reads it eagerly to decide whether a route composes at
#: all, while the store it names is reached through the regime member at
#: read time (see :class:`_DeferredRegimeStore`).  The table this route
#: reads lives in that same database, which is what makes the coverage
#: ledger the promotion gate reads (feature 285) and the ledger this
#: surface publishes (feature 343) the *one* ledger rather than two
#: readings that could disagree.
DATABASE_URL_ENV = "DATABASE_URL"

#: The route this endpoint serves — app_spec.xml's API summary row for
#: the Observability domain, spelled once: ``GET
#: /metrics/regime-coverage — Return stored world counts per regime
#: stratum`` (the feature sentence's own words at line
#: ``<feature index="343">``: *returns stored world counts per
#: stratum*).  Carried on the class (:attr:`RegimeCoverageEndpoint.route`)
#: so a composed deployment can state its routes from the components it
#: holds rather than from a string that lives somewhere else.
REGIME_COVERAGE_ROUTE = "/metrics/regime-coverage"

#: The component name this route registers under — member-first and
#: route-second, the spelling every route-shaped component in this
#: workspace takes (feature 341's ``ops-fdr-deploy`` beside it, the
#: ledger member's ``ledger-k-effective`` for feature 94), so a composed
#: application's ``order`` sorts this member's routes *beside* — never
#: inside — another member's, and this route lands as a peer of the
#: fdr-deploy route rather than a new prefix family.  *Defined* here,
#: beside the module whose component it names, and imported by the
#: member's ``__init__`` where the ``@register`` lives — the placement
#: feature 350's live-metrics store name and features 344-347's store
#: names already take.  Spelled in the app package seat
#: (:mod:`app.modules.ops`) as well, and the member's suite asserts the
#: two agree.
OPS_REGIME_COVERAGE_COMPONENT_NAME = "ops-regime-coverage"


def require_regime() -> Any:
    """Import and return the :mod:`regime` member, or raise loudly.

    Called from inside the endpoint's read paths — never at module
    scope, and never at builder time, where the scan has already taken
    the sibling's ``src/`` back off ``sys.path`` — for the reason
    :func:`~ops.fdr_route.require_scoring` gives for its own cross-member
    import: the factory's workspace scan imports this package to fire its
    ``@register``, and the scan puts one member's ``src/`` on
    ``sys.path`` at a time, so a module-scope ``import regime`` here
    would make this component's presence in the composed application
    depend on scan order.  Deferring the import keeps this member
    import-safe in every environment the workspace contract promises one
    will be (factory scan, test sandbox, replay path), while a
    deployment that genuinely needs the ledger and cannot reach the
    regime member is told which wheel is missing rather than shown a
    bare :class:`ImportError`.

    The dependency itself is the "never grow a second reader" door
    feature 341's route opened for the scoring member: feature 283's
    store creates and serves the ``regime_coverage`` table, feature 284's
    read is the member's only whole-table ``SELECT`` and owns the
    named-empty distinction, and this member asks for the distribution
    through that one spelling rather than re-deriving it.
    """
    try:
        import regime
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the ops member serves the regime-coverage route by reading "
            "the regime member's coverage ledger (features 283's store "
            "and 284's read) rather than re-spelling the whole-table "
            "read, and that member is not importable in this "
            "environment; run `uv sync --all-packages` in the workspace "
            "root (or put packages/regime/src on sys.path) so the ledger "
            "this route publishes can be reached"
        ) from exc
    return regime


@dataclass(frozen=True, slots=True)
class RegimeCoverageResponse:
    """The answer to one GET /metrics/regime-coverage: the pool's
    stored world counts, one entry per named stratum.

    ``strata`` is the ledger's content as plain data — ``(stratum,
    world_count)`` pairs, sorted by stratum — and every other read the
    response offers (:attr:`counts`) is derived from it, never stored
    beside it, so §C7's mapping and the rows it came from are one answer
    rather than two that could disagree.  Plain pairs rather than the
    regime member's row values, because what crosses the member seam is
    data: this route re-spells none of the ledger's types, and a caller
    that wants the richer reads (the named-empty set, the covered set,
    the vocabulary holes) reads them off feature 284's ledger where they
    are defined.

    **The mapping is the distinction.**  A stratum *present* with a count
    of ``0`` is a row the census counted and found empty — §C7's own
    ``crash: 0``, the state feature 286's ``empty_stratum`` warning fires
    on — while a stratum *absent* from the mapping is one nobody has
    named at all.  Both facts survive this type untouched: no missing
    stratum is filled in with a zero, and no zeroed row is dropped.  A
    caller that needs them told apart has the distinction for the asking
    (``"crash" in response.counts``), and one that needs the vocabulary
    question asked properly asks it of feature 284's ledger, whose
    :meth:`~regime.CoverageLedger.holes` is the only thing in the
    workspace that turns an absence into something nameable.

    An empty ledger is the honest answer for a configured database where
    no census has run yet: the pairs are empty, :attr:`counts` is an
    empty mapping and the value is falsy.  That is a *reading* — the pool
    names nothing — and deliberately not the same as the unconfigured
    deployment, which composes no route at all rather than answering an
    empty one.

    Frozen, because the response is the route's testimony about the
    ledger at the moment it was read: re-reading answers a fresh value
    (the census writes counts from another process between two reads),
    and nothing here is a knob to adjust.
    """

    #: The ledger's rows as plain data, one ``(stratum, world_count)``
    #: pair per named stratum, sorted by stratum.  The distribution §C7
    #: draws — the *whole* of what this value has.
    #:
    #: Either a sequence of pairs or a mapping of stratum to count, because
    #: §C7 writes the ledger as a mapping (``{high-vol trend: 2, …}``) and
    #: a hand-built response should not have to convert the spec's own
    #: shape into the other to be accepted.  A mapping's entries are not
    #: ordered, so it is the order-by-stratum below — not the caller's —
    #: that fixes the answer's display order either way.
    strata: Any = ()

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so normalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline feature 341's response and the ledger member's
        # own value follow.
        rows: list[tuple[str, int]] = []
        seen: set[str] = set()
        for row in _a_sequence_of_pairs(self.strata):
            name, count = _the_pair(row)
            if name in seen:
                raise RegimeCoverageMetricError(
                    f"a GET {REGIME_COVERAGE_ROUTE} answer names stratum "
                    f"{name!r} twice; the ledger's identity is one row per "
                    f"name (the table's primary key), so an answer holding "
                    f"two rows for one stratum reports a different coverage "
                    f"depending on which row a reader happened to reach — "
                    f"and the caller that assembled both is the one that "
                    f"knows which was meant (feature 343, prd §C7)"
                )
            seen.add(name)
            rows.append((name, count))
        rows.sort(key=lambda row: row[0])
        object.__setattr__(self, "strata", tuple(rows))

    # -- The reads ----------------------------------------------------------

    @property
    def counts(self) -> dict[str, int]:
        """The ledger in §C7's own shape — ``{stratum: world_count}``.

        The doctrine's ledger written out (*"Maintain an explicit ledger:
        ``{high-vol trend: 2, low-vol chop: 14, crash: 0, …}``"*), the
        shape the spec's API summary writes this route in (*"Return
        stored world counts per regime stratum"*), and the shape feature
        284's own :attr:`~regime.CoverageLedger.counts` docstring names
        this feature as the reason for — so the answer an operator reads
        here is the ledger the regime member would have handed them, to
        the key and to the count.

        A fresh dict per call, so a caller cannot mutate this value's
        answer, and a view *over* :attr:`strata` rather than a second
        copy of the content: the names and counts are the rows', and a
        value that stored both would be two records of one distribution.
        ``0`` entries are present, because a named-empty stratum is a
        finding; absent strata are absent, because a stratum nobody
        counted is not a coverage of zero.
        """
        return dict(self.strata)

    def __bool__(self) -> bool:
        """Whether the ledger names any stratum at all.

        ``False`` only for an empty ledger — a configured database where
        no census has run yet, which is a discoverable state rather than
        an error.  The split this pins is the one the regime member's own
        read states: an empty ledger is *the pool names nothing*, which
        is a different answer from *every stratum holds zero worlds* —
        the latter is a non-empty mapping whose every value is ``0``, and
        it is truthy here, because those rows exist and are findings.
        """
        return bool(self.strata)

    def __len__(self) -> int:
        """How many strata the answer names — rows, not worlds.

        Deliberately not a sum of the counts: §C7's ledger drawn as a set
        of keys is a number of *strata*, and the pool's world total is a
        different question with a different answer.  The regime member's
        own ``__len__`` states the same law for the same reason.
        """
        return len(self.strata)


def _a_sequence_of_pairs(strata: Any) -> Any:
    """Return ``strata`` as something iterable, or refuse what is not.

    A ``str`` or ``bytes`` is refused explicitly rather than iterated:
    both are sequences, and iterating one would descend into its
    characters — an answer built from a string is not a ledger, and the
    refusal says so instead of raising a puzzling unpack error three
    frames later.

    A mapping is accepted and iterated through its items, because §C7
    writes the ledger *as* a mapping and the value this route derives for
    that shape (:attr:`RegimeCoverageResponse.counts`) is one: a caller
    that built the spec's own shape by hand should not be told it is not
    this value's input.  Iterating a plain mapping would yield its keys —
    names with no counts, each refused one by one — so the translation
    happens here, once, rather than surfacing as a pile of refusals about
    entries the caller never wrote.
    """
    if isinstance(strata, Mapping):
        return tuple(strata.items())
    if isinstance(strata, (str, bytes)) or not isinstance(strata, Iterable):
        raise RegimeCoverageMetricError(
            f"a GET {REGIME_COVERAGE_ROUTE} answer is a sequence of "
            f"(stratum, world_count) pairs — one per named stratum, the "
            f"shape the coverage ledger is read in — and this is not one "
            f"(got {strata!r}, {type(strata).__name__}). The response is "
            f"the route's testimony about the pool's distribution, and "
            f"something that is not a collection of strata is not a "
            f"distribution (feature 343, prd §C7)"
        )
    return strata


def _the_pair(row: Any) -> tuple[str, int]:
    """Narrow one ledger entry to the ``(stratum, world_count)`` pair
    the response holds.

    The regime member's read answers rows in exactly this shape, already
    validated — the name a non-empty string, the count a genuine
    non-negative integer, each row's vintage present — but the response
    is constructible by hand, and a frozen value that validated nothing
    would lend this route's guarantees to a distribution no store
    answered.  Each half is defended with feature 283's own law, restated
    rather than imported because the *type* of a cross-member value is
    not what this member can hold: a stratum name is non-empty text
    (feature 283's ``_validated_stratum``, whose strip is the near-miss
    guard against a trailing newline persisting as a second row for one
    stratum), and a count is a non-negative ``int`` with ``bool`` refused
    before it (``True`` is an ``int`` in Python, and a flag where a count
    belongs would silently answer one stored world).

    The *absent* count is refused for the reason every store in this
    workspace refuses one: a stratum with no count is not a stratum
    holding none — the table's column is ``NOT NULL DEFAULT 0`` so a row
    this route can read always carries a number — and answering ``None``
    where a count belongs would put the never-counted state into the
    mapping feature 286's warning reads.
    """
    if isinstance(row, (str, bytes)) or not isinstance(row, Iterable):
        raise RegimeCoverageMetricError(
            f"a GET {REGIME_COVERAGE_ROUTE} answer is a sequence of "
            f"(stratum, world_count) pairs — one per named stratum — and "
            f"this entry is not one (got {row!r}, {type(row).__name__}). "
            f"An entry that is not one stratum's count is not testimony "
            f"anything counted (feature 343, prd §C7)"
        )
    values = tuple(row)
    if len(values) != 2:
        raise RegimeCoverageMetricError(
            f"a GET {REGIME_COVERAGE_ROUTE} answer is a sequence of "
            f"(stratum, world_count) pairs — the two facts the ledger "
            f"holds per stratum, and no third — and this entry carries "
            f"{len(values)} values (got {row!r}). The route answers §C7's "
            f"distribution and nothing beside it: a stratum's name and "
            f"the number of stored worlds the pool holds in it (feature "
            f"343, prd §C7)"
        )
    name, count = values
    if not isinstance(name, str) or not name.strip():
        raise RegimeCoverageMetricError(
            f"a GET {REGIME_COVERAGE_ROUTE} answer is keyed by stratum, "
            f"and this entry carries no nameable one (got stratum="
            f"{name!r}, {type(name).__name__}). The ledger's identity is "
            f"one row per named stratum, so a name that states nothing "
            f"names no stratum a coverage could be reported for (feature "
            f"343, prd §C7)"
        )
    if isinstance(count, bool) or not isinstance(count, int):
        raise RegimeCoverageMetricError(
            f"a stratum's stored-world count on a GET "
            f"{REGIME_COVERAGE_ROUTE} answer must be a non-negative "
            f"integer — got {count!r} ({type(count).__name__}) for "
            f"stratum {name.strip()!r}. The count is of stored worlds in "
            f"the replay pool, and a number of worlds is a count, not a "
            f"truthy flag or a fraction — a value that is not one is a "
            f"coverage nobody counted, and §C7's ledger is the one view "
            f"of the pool that must not be filled in (feature 343, prd "
            f"§C7)"
        )
    if count < 0:
        raise RegimeCoverageMetricError(
            f"a stratum's stored-world count on a GET "
            f"{REGIME_COVERAGE_ROUTE} answer must be at least 0 — got "
            f"{count!r} for stratum {name.strip()!r}. §C6's tripwires "
            f"excise worlds from the pool but never create a stratum "
            f"that owes them, and a negative count is not a number of "
            f"stored worlds (feature 343, prd §C7)"
        )
    return (name.strip(), count)


class _DeferredRegimeStore:
    """The store a composed route will read, resolved at first read.

    :meth:`RegimeCoverageEndpoint.from_env` reads ``DATABASE_URL``
    eagerly — whether a route composes at all is a fact about the
    deployment, and the builder must decide it at composition — but it
    cannot *construct* the store there, for the scan-order reason
    :func:`require_regime` exists: the factory's workspace scan puts one
    member's ``src/`` on ``sys.path`` at a time and has already taken the
    regime member's off again by the time builders fire, so a build-time
    ``regime.RegimeCoverage(...)`` would import the regime member exactly
    where that import is not promised to work — and a component whose
    builder raises takes the whole composition down with it, which is a
    far worse failure than the route it broke.

    So the endpoint holds this carrier, which keeps the URL it was
    resolved from (that is the composition fact — the database this route
    and the composed ``regime`` store component both point at, pinned by
    tests without reading anything) and constructs the real store on the
    first ``ledger()``, where the caller is precisely one who reached for
    the distribution and therefore runs somewhere the declared dependency
    is importable.  From that first read on, the store is the member's
    own object and every law is its: the idempotent table creation, the
    whole-table ``SELECT`` in stratum order, the named-empty-versus-
    absent distinction, the corruption refusal that names the stratum it
    came off.

    Duck-shaped exactly as the endpoint's check demands — one ``ledger()``
    — because that is the whole contract; nothing here re-spells a store
    behaviour, it only moves the store's construction from a moment the
    import cannot happen to the first moment it must.
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

    def ledger(self):
        """The regime member's own whole-ledger read, over the resolved
        URL."""
        if self._store is None:
            regime = require_regime()
            self._store = regime.RegimeCoverage(self._url)
        return self._store.ledger()


class RegimeCoverageEndpoint:
    """Serves GET /metrics/regime-coverage over one coverage ledger.

    The store is the regime member's
    (:class:`~regime.RegimeCoverage`), reached through that member rather
    than re-implemented here — see :func:`require_regime` for the door
    and the module docstring for the law.  Constructed with the store it
    reads; :meth:`get` is the route.  The endpoint holds no state of its
    own — no cache of a previous answer, no memo of a distribution —
    because the answer must be the ledger's state at the moment it is
    asked for: the census (feature 290) and the backfill (feature 287)
    write counts from other callers, §C6's tripwires excise worlds
    between reads, and a cached mapping would make the operator's view of
    the pool a fact about when the surface happened to start rather than
    about what the pool holds.

    The carrier is duck-checked, never ``isinstance``-guarded, for the
    reason every seam in this workspace gives: the factory's scan imports
    members under synthetic names, so a *composed* store is structurally
    the regime member's and never the same class object a direct import
    yields.  The contract is the one read the route needs — ``ledger()``,
    feature 284's whole-table verb — and that is what is checked; an
    object that can only answer one stratum's row is not enough here,
    because the feature's sentence asks for counts *per stratum* — the
    distribution — and a reader that walked a vocabulary one name at a
    time would report nothing about a deployment whose labeler carves
    more strata than :data:`~regime.DEFAULT_STRATA` names.
    """

    #: The route this endpoint serves — :data:`REGIME_COVERAGE_ROUTE`,
    #: pinned as a class attribute so ``RegimeCoverageEndpoint.route``
    #: states the contract without an instance.
    route = REGIME_COVERAGE_ROUTE

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "ledger", None)):
            raise TypeError(
                "RegimeCoverageEndpoint speaks a coverage-ledger store "
                "(something with a ledger() whole-table read); got "
                f"{type(store).__name__}. The route returns stored world "
                "counts per stratum (feature 343, prd §C7), and the "
                "distribution is the whole table feature 284's read "
                "answers — a carrier that can only answer one stratum's "
                "row cannot report the pool's shape."
            )
        self._store = store

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["RegimeCoverageEndpoint"]:
        """The endpoint over the ledger ``DATABASE_URL`` names, or
        ``None`` when it names none.

        The URL is resolved eagerly — whether a route composes at all is
        a fact about the deployment, read from :data:`DATABASE_URL_ENV`
        with the same unset semantics every member store's resolution
        takes (absent, empty and whitespace-only all count as unset) —
        but the *store* it names is deferred to the first read
        (:class:`_DeferredRegimeStore`), because a builder runs at
        composition and the factory's scan has already taken the regime
        member's ``src/`` off ``sys.path`` by then: an import here would
        make this component's presence depend on scan order, the exact
        fragility :func:`require_regime`'s deferral exists to avoid.  A
        caller that actually reads the ledger runs where the declared
        dependency is importable, and that is where the store is
        constructed — over the same URL, so this route, the composed
        ``regime`` component (feature 283's store, the table's second
        creator) and the promotion gate that blocks on the same rows
        (feature 285) always point at the one database (§16's *"single
        Postgres metrics table"* allowance).

        No ``DATABASE_URL`` composes no endpoint — an unconfigured store
        is a discoverable state, not an error, and it is deliberately
        *not* the empty-ledger answer: this ``None`` says there is
        nowhere a count could have been persisted, while an empty ledger
        says the pool names no stratum.  A deployment whose operator
        surface must see the pool's shape is the one that must not find
        itself in the first state.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(_DeferredRegimeStore(raw))

    @property
    def store(self) -> Any:
        """The store this endpoint reads — the regime member's, held
        duck-typed across the member seam.  For an endpoint built by
        :meth:`from_env` this is the deferred carrier
        (:class:`_DeferredRegimeStore`) until the first read: it carries
        the resolved ``database_url`` from composition and constructs the
        regime member's store only where reading the ledger actually
        happens."""
        return self._store

    # -- The route ----------------------------------------------------------

    def get(self) -> RegimeCoverageResponse:
        """Answer one GET /metrics/regime-coverage: the pool's stored
        world counts, one entry per named stratum.

        The whole of feature 343 at its seam.  The route takes no
        arguments: a GET over the ledger has no body, and the sentence
        asks for counts *per stratum* — the distribution, not one
        stratum's count — so a filtered ask (a single name) is the
        regime store's own ``get()``, feature 283's verb, and not this
        route's.  The read is the store's ``ledger()``, every time: the
        rows arrive already validated, already sorted, with the
        named-empty distinction intact and a corrupt row refused there by
        the stratum it came off.

        The one shape taken from the regime member is §C7's own mapping
        (:attr:`~regime.CoverageLedger.counts`), the view feature 284's
        own docstring names this endpoint as the reason for.  A ledger
        value that does not answer that mapping is refused by name rather
        than guessed at, because the alternative — walking the value for
        whatever looks like a name and a count — would be this module
        assembling a distribution out of a carrier it does not
        understand.

        A read that fails is translated into this member's vocabulary and
        chained to the original — a caller that catches
        :class:`~ops.errors.RegimeCoverageMetricError` must not be taken
        down by the regime member's :class:`~regime.CoverageError` — and
        nothing is ever caught *into* an answer, because every fallback
        this route could add is a distribution nobody counted.  An empty
        ledger is not a failure: the response answers it with no strata,
        the honest absence feature 284's own read states for a configured
        database where no census has run.
        """
        regime = require_regime()
        try:
            ledger = self._store.ledger()
        except regime.CoverageError as exc:
            # The store's own refusal, translated at the member seam: the
            # rows are the regime member's, the route is this member's,
            # and the vocabulary must live where the caller catches it.
            # The original is chained so the operator still sees the
            # store's own words — never swallowed, never retried, and
            # never answered around.
            raise RegimeCoverageMetricError(
                f"could not answer GET {REGIME_COVERAGE_ROUTE}: the "
                f"coverage ledger refused the read: {exc!r}. §C7's ledger "
                f"is the one remedy named for a regime-monotone replay "
                f"pool — *\"you find out when the regime breaks\"* — so a "
                f"ledger that cannot be asked is surfaced rather than "
                f"answered around with an empty distribution; the repair "
                f"is the store's (the original refusal is chained), never "
                f"a fallback mapping (feature 343, prd §C7)"
            ) from exc
        return RegimeCoverageResponse(strata=_the_strata_of(ledger))


def _the_strata_of(ledger: Any) -> tuple[tuple[str, int], ...]:
    """Read §C7's mapping off the ledger the regime member answered.

    :meth:`~regime.CoverageLedger.counts` is the regime member's derived
    view — a fresh ``{stratum: world_count}`` dict built from the rows its
    own read already validated, ordered by stratum — and it is the shape
    this route is specified in, so the read is that one attribute rather
    than a walk over ``rows`` that would rebuild the mapping here.  What
    it yields is plain data (names and integers), which is what may cross
    the member seam: this module holds no regime value type.

    A ledger that does not answer a mapping is refused by name.  The
    composed store's answer always does — but the endpoint is
    constructible with any carrier that satisfies its ``ledger()`` duck
    check, and a value whose *content* cannot be read would otherwise
    reach construction as a puzzling ``AttributeError`` from somewhere
    inside this module's own plumbing.  The refusal names what arrived,
    so the operator learns which carrier lied rather than which line
    unpacked it.
    """
    counts = getattr(ledger, "counts", None)
    if not isinstance(counts, Mapping):
        raise RegimeCoverageMetricError(
            f"a GET {REGIME_COVERAGE_ROUTE} reads the coverage ledger in "
            f"§C7's own shape — a mapping of stratum to stored-world "
            f"count, the view feature 284's ledger answers — and the "
            f"ledger this route read does not carry one (got {ledger!r}, "
            f"{type(ledger).__name__}). The distribution is feature 284's "
            f"answer and this route re-derives none of it, so a carrier "
            f"that cannot state the mapping cannot be asked for the "
            f"route's figure (feature 343, prd §C7)"
        )
    return tuple(counts.items())
