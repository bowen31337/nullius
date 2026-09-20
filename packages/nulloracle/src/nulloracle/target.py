"""The null oracle's one route: POST /target — the ask, the status, §7.2's payload.

app_spec.xml, "Null Oracle & Planted Nulls", features 112 and 113: *System
exposes POST /target accepting node_id, campaign_id, depth, horizon, symbols
and a date range, which returns 200 for a known node* — and *System returns a
target series plus a charges_budget directive from POST /target, never which
returns is_null in any form.*  docs/nullius-tech-architecture.md §7.2 spells
the interface the two features serve::

    POST /target
      request:  { node_id, campaign_id, depth, horizon, symbols[], date_range }
      response: { target_series, charges_budget }   # is_null NEVER appears

and §6.1 names the caller: pipeline step 5 — ``null_gate ── ask null oracle
for the target series ── §7`` — is the only place a target series is ever
substituted, and this route is the thing that step asks.  Feature 112 owns
the ask and the answer's *status*; feature 113 owns the payload — the series
and the opaque directive.  They live in one module because they are two
halves of one answer, written where a caller reads them together: a status
without a payload is an ask that was heard, and a payload without a status is
a series attributed to nobody.

**The route's contract as a Python seam, not an HTTP server.**  The
workspace's operations surface is its composed components — every "exposes"
feature in the spec landed as one, feature 95's POST /ledger/debit and
feature 94's GET /ledger/k-effective among them — and this endpoint
follows: :class:`TargetEndpoint.post` takes a :class:`TargetRequest` (the
body) and returns a :class:`TargetResponse`, with :data:`TARGET_ROUTE`
spelling the route once so the endpoint, the spec's API summary and
whatever HTTP adapter lands later cannot drift apart on the name.

**A known node is a node the sidecar answers for.**  The route resolves
``known`` the only way this member can: §7.1's sidecar — the one artifact
in the system allowed to hold a node's null status — either holds an entry
for the ``node_id`` or does not, and :meth:`nulloracle.sidecar.
NullSidecar.assignment` is precisely that question.  A held entry answers
:data:`OK` (200); a node the sidecar does not hold answers :data:`NOT_FOUND`
(404) — an *answer*, not an error, because the feature's own clause
distinguishes the two ("which returns 200 for a known node") and a caller
that could not tell an unknown node from a broken oracle would retry the
one and escalate the other.  The same distinction is why the sidecar's own
failures *propagate*: a missing sidecar file and a sidecar that will not
open are deployment failures
(:class:`~nulloracle.errors.SidecarStoreError`,
:class:`~nulloracle.errors.SidecarDecryptionError`), and swallowing either
into a 404 would read "the world holds no such node" off a deployment that
never told the route what the world holds — the exact confusion the
taxonomy's central rule exists to prevent.

**The assignment is read, branched on, and never carried.**  Learning that a
node is known means opening the entry, and the entry carries ``is_null`` — the
one bit §7.2's response comment says NEVER appears.  Feature 113 is the
feature that finally *uses* it: §7.2's internal rule is *"if ``is_null``,
return ``block_permute(forward_returns, seed=perm_seed, block=20d)``; else
return the real forward returns"*, so the bit selects the branch.  Selecting
is not disclosing.  What leaves this module is a series and one bool, and the
bool is the *directive*: ``charges_budget`` is ``False`` exactly when the node
is null — §8's own column comment is ``charges_budget BOOLEAN NOT NULL, --
FALSE for null nodes`` — because a null node's signal was never compared to
real forward returns: it consumed agent calls and CPU but **no statistical
degrees of freedom** (§8), so it must not inflate ``K`` in the deflation term.
The direction is worth stating twice, because it is the one a plausible
implementation inverts: the flag says *this evaluation spent real degrees of
freedom*, and a null node's did not.  §8 states
the writing discipline in the same breath as the value: *"the evaluator must
set this flag without learning ``is_null``, so the null oracle returns it
alongside the target series as an opaque budget directive, never as a
label"* — which is why this is the one direction the bit may be read in, and
why ``is_null`` itself is spelled nowhere a response can reach.  The
corruption table in §15 names the failure this shape prevents: *"Null budget
flag leaked as a label → Audit: ``charges_budget`` correlated with anything
in the agent's context → Treat as a §7.4 VOID event; the flag must be
opaque."*

**The directive is the branch, which is the one thing feature 114 had to
reckon with.**  ``charges_budget = not is_null`` and ``is_null`` *is* the
branch, so a caller holding two responses for one node under two campaign
types could read the bit off the directive.  That is not a hole this module can
close and it is not this module's to close: §8 *requires* the directive to be
exactly this fact, and a directive that were constant (or randomised, or
derived from something else) would either charge a null node a budget it never
spent or refund a real one a budget it did — and either direction corrupts
``K``, the deflation term §8 exists to keep honest.  What feature 114 adds on
top of that one sanctioned crossing is that *nothing else* varies: same
response type, same fields, same branches — and the same work spent whichever
way the branch went (the next paragraph).  Every payload below is validated on
both branches by the same code at the same points, so the route has never
handed a caller a response whose *shape* varies; since feature 114, the same
is true of the clock.

**Feature 114: the same work, spent before the branch is chosen.**  §7.2's
promise — *"The caller cannot distinguish the two branches from the
response"* — has two halves, and a response is more than its bytes: *when* it
arrives is part of it too.  The null branch's payload is the real series put
through a block permutation, so a route that permuted only when the bit said
so would do strictly more work for a null node than for a real one — panel-
sized work, spent on one branch alone — and a caller holding nothing but a
stopwatch would read the bit off the latency, the same leak a
``try``-around-the-refusal gives, measured instead of caught.  So the route
computes **both** branches' series on every request: the permutation is run
and its support checked whichever branch serves, and the bit's only office is
to select between two values that already exist
(:meth:`TargetEndpoint.post`).  The cost is real and deliberate — a real
node's answer now pays for a permutation it discards — because the
alternative is a branch the caller can time.  The discipline is the one this
module already states in the small, extended to the series itself: both
supplies are named before the branch is chosen, both payload validators run
on both branches, and both branches' series are built before either is
served.  Nothing a caller can read — value, shape, call sequence, or clock —
varies with the bit except the one directive §8 sends across.

**Where the real series comes from, and why it is a seam.**  §7.2's rule
begins from ``forward_returns`` — *the real forward returns* — and this
member holds none: the aligned series is the work of pipeline step 4
(feature 75, the evaluator member), the sidecar holds only the bit and the
permutation parameters, and the tree store holds no returns at all.  So the
real series arrives the way every expensive or cross-member collaborator in
this workspace arrives — as an injected callable, exactly as feature 121's
resolution takes its ``permute`` and feature 76's gate takes its oracle.  The
endpoint is constructed with a ``targets`` seam.  A deployment that supplies
neither seam, or only one of them, composes a route that refuses *every* node
by name rather than answering half a world — the honest degradation, and one
that cannot disclose a branch, since the answer does not vary with the bit
(below).

**The refusals, and why each is a refusal rather than an answer.**  All of
them raise :class:`~nulloracle.errors.TargetPayloadError`, which is kept
distinct from :class:`~nulloracle.errors.TargetRouteError` because the two are
refused at different points about different things: a route error is a *body*
that cannot say what it is asking for and is refused before the sidecar is
opened, where a payload error is a *deployment* that cannot serve what the
body asked for and is only discoverable after the entry was read.

* *A known node with no series at all* — no ``targets`` seam composed, or a
  seam that answered nothing for this ask.  Refused on the *branch that was
  already chosen* rather than guessed at, and refused rather than answered
  with an empty series, which would read to the evaluator's gate as a mild
  dilution: the gate would measure against nothing while §8 charged the null
  node nothing either — a Type-B refund of a statistical debt that was in
  fact incurred, and the exact invisible error §8's directive exists to make
  auditable.  A 404 would be worse, because it would assert that the sidecar
  holds no entry for a node it just read one out of; a partial series would be
  worse than both, because a symbol nobody replied for is indistinguishable
  from a symbol nobody scored.
* *A node with no permutation to serve* — refused, and refused on *both*
  branches rather than where the need arises.  The entry's stored ``perm_seed``
  and ``block_days`` are parameters, and a parameter is not a mechanism;
  serving the real series in their place would hand the caller real signal
  inside a world planted to have none.  Only a null node *uses* the mechanism
  — but a route that raised where the need arose would raise for null nodes
  and answer real ones, and that difference, visible to any caller inside a
  ``try``, is the bit itself.  So the seam is named before the branch is
  chosen (:meth:`TargetEndpoint._permutation_seam`), which costs a route
  nothing it could otherwise do: a route without the permutation cannot serve
  a null node, and refusing both is the only answer that keeps the refusal
  from being a label.
* *A series that does not answer the request's own ask* — refused, before the
  branch is chosen, so the same check runs either way and nothing in it can
  vary with the bit.  Two terms, both of them §7.2's request's own: the
  *cross-section* (§7.2's branches preserve the aligned support exactly, so an
  answer covering other symbols than were asked for is a series that arrived
  by some path other than this one — the evaluator's own gate refuses it
  downstream, feature 76's support rule, and refusing it here means the
  substitution never leaves the oracle at all), and the *span* (an answer
  whose dates fall outside the ``date_range`` the ask named is an answer to a
  different ask).  Coverage is checked per requested symbol and both terms are
  checked on *names and dates*, never on values: a route that compared values
  would be the client-side null detector principle P2 forbids.  The span is
  checked as containment and never as equality, because a series' endpoints
  are exactly what a permutation moves.
* *A permutation that moved something other than the rows* — refused.  The
  block permutation §7.2 names acts on the series' day blocks, so the served
  series must carry exactly the dates the real one carried, each exactly once:
  the same check feature 121's resolution makes on its own ``permute`` seam
  ("a permuted series of a different length would mark the branch as plainly
  as an ``is_null`` column would"), stated here over a panel rather than a
  vector.

**Note what is *not* checked: whether the permutation actually moved
anything.**  A deployment could wire a stand-in — a callable returning its
argument — and this route would serve it as a null branch's series, undetected.
That is deliberate, and it is the same stance feature 121's resolution takes
on the same seam: the *oracle* holds the bit and the *caller* must not be able
to read it, so a check that refused an identity permutation would refuse
exactly the one-block cases (a series shorter than ``block_days`` has one block
and nothing to move) and would refuse them *only on the null branch* — a
refusal that is itself a branch oracle.  The quality of a permutation is
feature 116's to measure (:func:`nulloracle.preservation.preserves_structure`)
and §7.4's "rotate the permutation scheme" is the operator's response to a
deployment that wired the wrong one; it is not a runtime inspection this route
may perform.

That reasoning generalises, and it is what every check in this module is
written against: a condition is only fair game if it can *fire on both
branches*.  Both supply refusals fire whichever branch asked — the series
seam's because both branches read one series from it, and the permutation
seam's because its absence is named before the branch is chosen at all
(:meth:`TargetEndpoint._permutation_seam`) rather than on the branch that
would have used it.  That second one is worth stating, because it is the
module's closest call: a node needs a permutation only when it is null, so
checking the seam where it is needed is the natural place to write it and the
one place it cannot go — the refusal would then fall on null nodes alone and
the *exception* would be the bit.  The symbol check and the span check run
before the branch is even chosen, over the ask and not over the answer's
values; the date-preservation check runs on both branches — feature 114
computes the permutation whichever branch serves, so the check is spent
either way — and is fair because it compares the permuted series to the
series it permuted, a relation the served series of the real branch
satisfies by identity.  What would not be fair is anything that inspects the
*values* of the served series, because the real and permuted series differ
exactly in their values and in nothing else.

**The Type-D regime composes, and is not re-implemented.**  §7.2 adds: *"For
Type-D campaigns the oracle resolves the flip using ``depth``: below
``flip_depth`` the real targets are returned, at or beyond it the permuted
ones."*  That rule is feature 121's — :meth:`nulloracle.resolution.TypeDOracle.
resolve_request` reads the node's stored depth and its branch's stored flip and
applies it, and :func:`nulloracle.resolution.past_the_flip` is the comparison
at its centre — so this endpoint takes an optional ``past_flip`` seam: a
callable asked the request, answering ``True`` when the request sits at or
beyond its branch's flip (the node is null), ``False`` when it sits below it
(the node is real), and ``None`` when the campaign is not the Type-D regime at
all.  A deployment wires that one line to feature 121's store; a deployment
without it answers Type-R questions through the sidecar, which is precisely
the regime the sidecar speaks for.

The seam *overrides the sidecar's bit* and never replaces it: the node is
still looked up, still answers 404 when the sidecar holds no entry for it, and
still draws its permutation parameters from that same entry.  Both halves of
that are deliberate.  Feature 112's "known" stays one notion with one home —
a route where a Type-D node's known-ness came from a database and a Type-R
node's from the sealed file would report two different worlds under one word —
and §7.1's schema stays the single home of ``perm_seed`` and ``block_days``,
which is where feature 121's own docstring says a caller composes its
``permute`` from.  What the ``None`` return buys is that the seam may be
composed unconditionally: an adapter over feature 121's store answers only for
the campaigns that have flips (§7.3: *"Campaigns are homogeneous in null
type"*) and declines every other ask by saying so, rather than by raising the
store's refusal through a route that had a perfectly good answer available.

**The request is a frozen value, validated at construction.**  The six
terms §7.2 names are all required and all checked — the identities as UUIDs
(canonical lower-case text, so two spellings of one node are one request),
``depth`` as a genuine non-negative integer (a ``True``, a ``"3"`` or a
``-1`` is refused, exactly as the Type-D resolution refuses them), the
``horizon`` as one of the five the spec aligns (:data:`HORIZONS` — the
closed set the evaluator's alignment step spells, restated here because
this member is deliberately import-cheap and speaks no other member),
``symbols`` as a non-empty cross-section (a bare string is refused — it
is a sequence of characters, not a list of tickers), and ``date_range`` as
a first-to-last pair of calendar dates (ISO strings accepted — §7.2 is a
service boundary and ISO is the wire spelling; a ``datetime`` refused,
because a target is day-granular and truncating one would guess which
candle was meant).  A malformed body is refused
(:class:`~nulloracle.errors.TargetRouteError`) *before the sidecar is
opened*: a request that cannot say what it is asking for spends no read of
the one file in the system worth controlling.

**The response's payload is validated at construction, like the request's.**
:class:`TargetResponse` carries ``target_series`` and ``charges_budget`` and
checks both the way the evaluator's own client checks them — the series keyed
by calendar date (or ISO wire spelling) to a mapping of symbol to finite
float, the directive a genuine ``bool`` and nothing that merely looks like one
— plus the three coherence rules §7.2 needs and the wire record cannot state
alone: a payload exists exactly when the status is :data:`OK` (a 404 answers
with everything it knows, which is nothing), an :data:`OK` carries no
``detail`` (feature 112's rule, kept: an answer that explained itself would be
an answer that varies by node), and the payload's dates live inside the
request's own ``date_range``.  That last one is checked as *containment* and
in the one direction that cannot leak: a date outside the span the ask named
is an answer to a different ask, while the series' own endpoints are exactly
what a block permutation moves, so a route that refused a series for its
``min``/``max`` would refuse one branch and not the other.

**Stdlib only.**  ``datetime``, ``uuid`` by way of the assignment layer's
normalization, and nothing else at module scope — the factory's scan
imports this package to fire its ``@register``, and the route must not make
that import pay for anything (the same discipline every store in this
member states).  The sidecar arrives constructed; the endpoint holds no
key, no path and no labels of its own.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .assignment import normalize_node_id
from .errors import TargetPayloadError, TargetRouteError
from .sidecar import NullSidecar

__all__ = [
    "HORIZONS",
    "NOT_FOUND",
    "OK",
    "STATUS_CODES",
    "TARGET_ROUTE",
    "TargetEndpoint",
    "TargetRequest",
    "TargetResponse",
]

#: The route this endpoint serves — the spec's API summary row for the null
#: oracle, ``POST /target — Return a target series plus an opaque budget
#: directive``, spelled once.  Carried on the class
#: (:attr:`TargetEndpoint.route`) so a composed deployment can state its
#: routes from the components it holds rather than from a string that lives
#: somewhere else — the same discipline :data:`ledger.debit.DEBIT_ROUTE`
#: states for the route this one follows.
TARGET_ROUTE = "/target"

#: The horizons a request may ask for — the closed set of five the spec
#: aligns forward returns at ("horizons of 1, 2, 5, 10 and 20 periods",
#: feature 74) and the set the evaluator's own request record holds closed.
#: Restated here rather than imported, because this member speaks no other
#: member: a route that accepted a horizon nothing downstream measures
#: would answer a question no evaluation ever asks.
HORIZONS: tuple[int, ...] = (1, 2, 5, 10, 20)

#: The status a known node answers with — the feature's own figure: *which
#: returns 200 for a known node*.
OK = 200

#: The status an unknown node answers with — the counterpart the feature's
#: clause implies: a node the sidecar does not hold is *unknown*, a fact
#: about the world the route reports rather than a failure of the route.
NOT_FOUND = 404

#: The two statuses this route speaks.  Closed, because a response that
#: could carry any integer could carry a status no caller of §7.2's
#: interface has behaviour for — the same reasoning every closed
#: vocabulary in this workspace states.
STATUS_CODES = frozenset({OK, NOT_FOUND})


def _validated_identity(value: Any, field: str) -> str:
    """Validate a request identity, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``* — but re-raises its refusal as
    :class:`~nulloracle.errors.TargetRouteError`, translating at the seam:
    a malformed identity on a *request body* is the route's contract, not
    the sidecar schema's, and a caller reading :class:`SidecarError` out of
    a POST /target would look in the wrong module for the cause.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise TargetRouteError(
            f"{field} {value!r} is not a UUID: {exc}; §7.2's request names "
            "the node it asks for and the campaign that node belongs to, and "
            "an identity that cannot be joined to the tree store's node.id "
            "is a request that names nobody"
        ) from exc


def _validated_depth(value: Any) -> int:
    """Refuse a ``depth`` that is not a genuine non-negative integer.

    The same value the tree stores and the same refusal the Type-D
    resolution states (:func:`nulloracle.resolution.past_the_flip`), with
    its own spelling because the clause here is about the *request*:
    §7.2's body carries the node's depth for a Type-D oracle to resolve
    its flip on, and a claim that is not a depth is a body the route cannot
    answer coherently.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TargetRouteError(
            f"depth must be a non-negative integer, got {type(value).__name__} "
            f"({value!r}); §7.2's request carries the node's depth — the term "
            "a Type-D oracle resolves its flip on — and a depth that is not "
            "one is a request nobody placed the node at"
        )
    return value


def _validated_horizon(value: Any) -> int:
    """Refuse a ``horizon`` outside the five the spec aligns.

    The horizons are a closed set (feature 74: 1, 2, 5, 10 and 20
    periods), and the evaluator's own request record holds them closed on
    the client side; the route holds the same set on the server side, so
    the two ends of §7.2 cannot drift apart on what may be asked.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in HORIZONS
    ):
        raise TargetRouteError(
            f"the request's horizon must be one of the horizons the spec "
            f"aligns ({', '.join(str(h) for h in HORIZONS)}), got {value!r}; "
            "the route answers per horizon, and a horizon nothing measures "
            "is a question no evaluation asks"
        )
    return value


def _validated_symbols(value: Any) -> tuple[str, ...]:
    """Validate the cross-section, returning it as one sorted spelling.

    The answer must cover exactly the symbols that were scored, so the
    request names the cross-section once: a non-empty sequence of non-empty
    names, canonicalised to a sorted de-duplicated tuple so two requests
    naming one cross-section in different orders are one request — the same
    canonicalisation the identities get, for the same reason: the request
    is a value two callers must be able to compare.  A bare string is
    refused rather than iterated, because ``"AAPL"`` is a sequence of five
    characters and a cross-section of zero tickers.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TargetRouteError(
            f"symbols must be a sequence of the symbols the answer must "
            f"cover, got {type(value).__name__} ({value!r}); §7.2's request "
            "names the cross-section that was scored, and a value that is "
            "not a list of names is an ask with nobody to answer for"
        )
    if len(value) == 0:
        raise TargetRouteError(
            "symbols is empty; §7.2's request names the cross-section that "
            "was scored, and a request with no symbols would answer an "
            "evaluation that scored nobody"
        )
    for symbol in value:
        if not isinstance(symbol, str) or not symbol:
            raise TargetRouteError(
                f"symbols must be non-empty strings, found {symbol!r} "
                f"({type(symbol).__name__}); a label for a symbol nobody "
                "can name is a label no answer can carry"
            )
    return tuple(sorted(set(value)))


def _as_request_date(value: Any, field: str) -> dt.date:
    """One endpoint of ``date_range``, as a calendar :class:`datetime.date`.

    Accepted spellings: a ``date``, or an ISO string naming one — §7.2 is a
    service boundary, and ISO is the wire spelling (the same terms the
    evaluator's response dates accept).  A ``datetime`` is refused, because
    it names an instant and a target is day-granular: silently truncating
    one would guess which candle the ask meant, and a guessed label is the
    one value this system refuses everywhere.
    """
    if isinstance(value, dt.datetime):
        raise TargetRouteError(
            f"{field} is a datetime ({value!r}); §7.2's targets are "
            "day-granular — name the calendar date (or its ISO string), not "
            "an instant"
        )
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise TargetRouteError(
                f"{field} {value!r} is not an ISO date; §7.2's date_range is "
                "a pair of calendar dates, and ISO is the wire spelling"
            ) from exc
    raise TargetRouteError(
        f"{field} must be a calendar date or an ISO date string, got "
        f"{value!r} ({type(value).__name__})"
    )


def _validated_date_range(value: Any) -> tuple[dt.date, dt.date]:
    """Validate ``date_range``, returning the span as ``(first, last)``.

    The range the answer's dates must live inside — the evaluator builds it
    as the first and last of a horizon's aligned dates, and a range that
    ran last-to-first would describe a span nothing aligned ever did.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TargetRouteError(
            f"date_range must be a pair of calendar dates (first, last), "
            f"got {type(value).__name__} ({value!r}); §7.2's request bounds "
            "the answer, and a bound that is not a pair of dates bounds "
            "nothing"
        )
    if len(value) != 2:
        raise TargetRouteError(
            f"date_range must be a pair of calendar dates (first, last), "
            f"got {len(value)} terms ({value!r}); a range has two ends"
        )
    first = _as_request_date(value[0], "date_range[0]")
    last = _as_request_date(value[1], "date_range[1]")
    if first > last:
        raise TargetRouteError(
            f"date_range must run first-to-last, got {value!r}; the answer's "
            "dates live inside the range, and a reversed range describes a "
            "span nothing aligned ever did"
        )
    return (first, last)


def _optional_callable(value: Any, name: str) -> Any:
    """Refuse a named seam that is not callable; ``None`` stays ``None``.

    ``None`` is a supported state — a deployment that holds no step-4 series,
    no permutation, or no Type-D store composes a route that refuses by name
    rather than answering half a world — but a *named* seam that cannot be
    called is a wiring mistake, and it is refused here, at construction,
    rather than at the request that first needed it.  The factory builds every
    registered component on every :func:`~app.module_loader.create_app` call,
    so a constructor-time refusal surfaces at composition where an operator
    sees it, and a request-time one surfaces inside an evaluation.
    """
    if value is None or callable(value):
        return value
    raise TypeError(
        f"the {name} seam must be a callable or None, got "
        f"{type(value).__name__} ({value!r}); a route's collaborators arrive "
        "as injected callables, and a value the route cannot call would "
        "answer no request it was composed for"
    )


def _series_dates(series: Any) -> tuple[dt.date, ...] | None:
    """The dates a served series carries, ascending, or ``None`` to defer.

    The keys of the series' outer mapping, canonicalised through
    :func:`_as_payload_date` so a wire-spelled answer compares equal to a
    ``date``-spelled one; ``None`` when the value is not a mapping at all,
    which is :class:`TargetResponse`'s to refuse in its own single spelling
    rather than this helper's to refuse twice.
    """
    if not isinstance(series, Mapping):
        return None
    return tuple(sorted(_as_payload_date(key) for key in series))


def _series_symbols(series: Any) -> tuple[str, ...] | None:
    """The symbols a served series answers for, sorted, or ``None`` to defer.

    The union of every row's symbols: §7.2's answer is a panel, so what it
    "covers" is the cross-section appearing anywhere in it.  Rows that are not
    mappings, and symbols that are not non-empty strings, are left to
    :class:`TargetResponse`'s constructor for the same reason
    :func:`_series_dates` leaves a non-mapping — one contract, one refusal.
    """
    if not isinstance(series, Mapping):
        return None
    symbols: set[str] = set()
    for row in series.values():
        if not isinstance(row, Mapping):
            return None
        for symbol in row:
            if not isinstance(symbol, str) or not symbol:
                return None
            symbols.add(symbol)
    return tuple(sorted(symbols))


def _as_payload_date(value: Any) -> dt.date:
    """One key of a served ``target_series``, as a calendar date.

    Accepted spellings: a ``date``, or an ISO string naming one — the same
    pair :func:`_as_request_date` accepts, and for the same reason: §7.2 is a
    service boundary and ISO is the wire spelling.  Unlike the request's
    helper this one raises :class:`~nulloracle.errors.TargetPayloadError`,
    because the value being read is the *answer's* rather than the body's: a
    date the route cannot name is a series the route cannot serve, and a
    caller reading a request error out of a response would look for a
    malformed ask that does not exist.
    """
    if isinstance(value, dt.datetime):
        raise TargetPayloadError(
            f"the served target_series is keyed by a datetime ({value!r}); "
            "§7.2's targets are day-granular — key by the calendar date (or "
            "its ISO string), not an instant"
        )
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise TargetPayloadError(
                f"the served target date {value!r} is not an ISO date; the "
                "series is keyed by calendar dates (or ISO date strings), one "
                "per bar"
            ) from exc
    raise TargetPayloadError(
        f"the served target_series must be keyed by calendar dates or ISO "
        f"date strings, got {value!r} ({type(value).__name__})"
    )


def _validated_series(value: Any) -> Mapping[dt.date, Mapping[str, float]]:
    """Validate a served ``target_series``, returning it read-only.

    §7.2's payload half, checked the way the evaluator's own client checks it
    (:class:`evaluator.OracleResponse`, feature 76): ``{rebalance date:
    {symbol: forward return}}``, keyed at construction by calendar date or ISO
    date string and normalized to dates on capture, every value a finite
    number and never a ``bool`` (a ``True`` that happens to equal a score is
    not a score).  Two spellings of one date are refused rather than merged —
    one bar, one answer — and the captured mappings sit behind read-only
    proxies, so a caller keeping the dict it passed cannot add a target to a
    live response.

    The check is on the *shape* and nothing else.  Which branch produced the
    series, and what its values are, are not this function's business: §7.2
    promises the caller cannot distinguish the two branches from the response,
    so a route that inspected values here would be the client-side null
    detector principle P2 forbids — one running inside the oracle itself.
    """
    if not isinstance(value, Mapping):
        raise TargetPayloadError(
            "a served target_series must map rebalance date to "
            "{symbol: forward return}, got "
            f"{type(value).__name__} ({value!r}); §7.2's response carries the "
            "series the request asked for, and a value that is not a series "
            "is an answer to a different question"
        )
    captured: dict[dt.date, Mapping[str, float]] = {}
    for key, row in value.items():
        day = _as_payload_date(key)
        if day in captured:
            raise TargetPayloadError(
                f"the served target_series carries {day.isoformat()} twice "
                "under different spellings; one bar, one answer"
            )
        if not isinstance(row, Mapping):
            raise TargetPayloadError(
                f"the served row for {day.isoformat()} must map symbol to "
                f"forward return, got {type(row).__name__} ({row!r})"
            )
        inner: dict[str, float] = {}
        for symbol, element in row.items():
            if not isinstance(symbol, str) or not symbol:
                raise TargetPayloadError(
                    f"the served symbols for {day.isoformat()} must be "
                    f"non-empty strings, got {symbol!r}"
                )
            if isinstance(element, bool) or not isinstance(element, (int, float)):
                raise TargetPayloadError(
                    f"the served target for {symbol!r} on {day.isoformat()} "
                    f"must be a number, got {element!r} "
                    f"({type(element).__name__})"
                )
            number = float(element)
            if not math.isfinite(number):
                raise TargetPayloadError(
                    f"the served target for {symbol!r} on {day.isoformat()} "
                    f"is not finite ({element!r}); a NaN or ±inf label would "
                    "reach the metrics dressed as a measurement"
                )
            inner[symbol] = number
        captured[day] = MappingProxyType(inner)
    return MappingProxyType(captured)


def _validated_budget(value: Any) -> bool:
    """Refuse anything but a genuine ``bool`` for §7.2's budget directive.

    The directive is *"the only bit that crosses the barrier"* (§7.2), and a
    bit is not an integer that happens to be 0 or 1 — the same refusal the
    evaluator's client and the ledger's charge make for the same value, stated
    here so the route cannot emit a directive its consumers will refuse.
    Coercing would be worse than refusing, and in a direction: ``bool("false")``
    is ``True``, and a wrongly-``True`` directive tells the ledger to charge a
    node *more* than it spent.  A coerced ``0`` would be ``False`` and refund a
    node that spent real degrees of freedom — the direction §8's deflation term
    cannot absorb, because ``K_effective`` would under-count and the deflation
    would be too weak. Both directions are refused here rather than either one
    being guessed at.
    """
    if not isinstance(value, bool):
        raise TargetPayloadError(
            "charges_budget must be a genuine bool — §7.2's opaque budget "
            f"directive, the only bit that crosses the barrier — got {value!r} "
            f"({type(value).__name__}); a value that merely looks true or "
            "false would be read by §8's ledger as the wrong debit — "
            "K_effective counts the rows whose directive is true, so a "
            "coerced flag either charges a null node or refunds a real one"
        )
    return value


@dataclass(frozen=True, slots=True)
class TargetRequest:
    """The body of one POST /target: §7.2's six terms, as a value.

    ``node_id`` and ``campaign_id`` (the node the evaluation scores and the
    campaign whose world it lives in — campaigns are homogeneous in null
    type, §7.3, so the pair is what an oracle needs to answer coherently),
    ``depth`` (the node's depth in its tree — the term a Type-D oracle
    resolves the branch's flip on), ``horizon`` (which of the five aligned
    horizons this ask is for — the evaluator asks once per covered
    horizon), ``symbols`` (the cross-section that was scored) and
    ``date_range`` (the span the answer's dates must live inside).  All six
    required, none defaulted: §7.2's request is the experiment's own
    header, and a body that omits a term is not a shorter ask but a
    different one, which nobody made.

    Construction canonicalises (UUID identities to lower-case text, the
    cross-section to one sorted spelling, ISO dates to ``date``) and
    refuses everything else by name — see the validators — so two requests
    for the same evaluation compare equal however the caller came by the
    terms.  Frozen, because a request is a fact the caller stated; editing
    one in flight would be posting a different ask than was validated.
    """

    #: The node being evaluated — the identity §7.1's sidecar is keyed by,
    #: canonical UUID spelling.
    node_id: str
    #: The campaign the node belongs to, canonical UUID spelling.
    campaign_id: str
    #: The node's depth in its tree — the term a Type-D oracle resolves the
    #: flip with (below ``flip_depth`` real, at or beyond it permuted).
    depth: int
    #: The horizon this ask is for — one of :data:`HORIZONS`.
    horizon: int
    #: The cross-section the answer must cover, one sorted spelling.
    symbols: tuple[str, ...]
    #: The span the answer's dates must live inside, as ``(first, last)``.
    date_range: tuple[dt.date, dt.date]

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline the ledger's request records follow.
        object.__setattr__(
            self, "node_id", _validated_identity(self.node_id, "node_id")
        )
        object.__setattr__(
            self,
            "campaign_id",
            _validated_identity(self.campaign_id, "campaign_id"),
        )
        object.__setattr__(self, "depth", _validated_depth(self.depth))
        object.__setattr__(self, "horizon", _validated_horizon(self.horizon))
        object.__setattr__(
            self, "symbols", _validated_symbols(self.symbols)
        )
        object.__setattr__(
            self, "date_range", _validated_date_range(self.date_range)
        )


@dataclass(frozen=True, slots=True)
class TargetResponse:
    """The answer to one POST /target: §7.2's response, whole.

    ``status`` is :data:`OK` when the sidecar holds the node and
    :data:`NOT_FOUND` when it does not; ``node_id`` is whose answer this is
    (canonical UUID text, so a logged response joins to the tree store);
    ``target_series`` and ``charges_budget`` are §7.2's payload — feature
    113's half; and ``detail`` carries the human-readable reason a non-OK
    answer states.

    **``is_null`` is not among these fields and cannot be.**  Nothing in this
    record says which branch produced the series, and nothing can be derived
    from it either: the same type, the same field names and the same branches
    serve a real node and a null one, which is feature 114's identical-shape
    promise (see ``test_target.py``, which asserts this for the instance, the
    type and the ``repr``, and ``test_indistinguishability.py``, which holds
    the feature's other half — the identical work — against the route).  The
    one bit that does cross is ``charges_budget``,
    and it crosses as a *directive* — the caller learns whether to debit
    statistical budget without learning why (§7.2, §8).

    **The payload exists exactly when the status is OK.**  A 404 answers with
    everything the route knows, which is that the sidecar holds no such node;
    a 404 carrying a series would be an answer to a question the route just
    said it could not answer, and an :data:`OK` without a payload would be a
    status asserted over nothing.  Both are refused at construction rather
    than defaulted, because a default here is a world invented.

    Frozen, because the response is the route's testimony about the world
    at one moment; a response that could be edited after the fact would be
    the oracle revising an answer already given.
    """

    #: The status the route answered with — :data:`OK` or
    #: :data:`NOT_FOUND`, the closed pair :data:`STATUS_CODES` spells.
    status: int
    #: The node the answer is for, canonical UUID spelling.
    node_id: str
    #: The series served — ``{rebalance date: {symbol: forward return}}``,
    #: captured read-only, every value a finite float.  Present exactly when
    #: the status is :data:`OK`.  Whether it is the real series or a block
    #: permutation of it is unknowable from this side, by design.
    target_series: Mapping[dt.date, Mapping[str, float]] | None = None
    #: §7.2's opaque budget directive — whether the evaluation charges
    #: statistical budget.  ``False`` exactly for a null node (§8's column
    #: comment is ``-- FALSE for null nodes``: a null node's signal was never
    #: compared to real forward returns, so it consumed no statistical
    #: degrees of freedom, and ``K_effective`` counts only the rows whose
    #: directive is true), carried as a directive and never as a label.
    charges_budget: bool | None = None
    #: The reason a non-OK answer states, for a log line or an operator;
    #: ``None`` on an OK, which explains itself.
    detail: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or self.status not in STATUS_CODES
        ):
            raise TargetRouteError(
                f"status must be one of the two this route speaks "
                f"({OK} for a known node, {NOT_FOUND} for an unknown one), "
                f"got {self.status!r}; a response carrying any other "
                "integer is a status no caller of §7.2's interface has "
                "behaviour for"
            )
        object.__setattr__(
            self, "node_id", _validated_identity(self.node_id, "node_id")
        )
        if self.detail is not None:
            if not isinstance(self.detail, str) or not self.detail.strip():
                raise TargetRouteError(
                    f"detail must be a non-empty string when given, got "
                    f"{self.detail!r}; a reason that says nothing is a line "
                    "no log should carry"
                )
            if self.status == OK:
                raise TargetRouteError(
                    "an OK answer carries no detail; the feature's own "
                    "clause is 'which returns 200 for a known node', and an "
                    "answer that explained itself would be an answer that "
                    "varies by node — the exact variation feature 114 "
                    "forbids"
                )
        # The payload is checked after the status, so the two coherence
        # refusals below can be stated about a status already known to be one
        # of the two this route speaks.
        if self.status == OK:
            if self.target_series is None or self.charges_budget is None:
                missing = (
                    "target_series"
                    if self.target_series is None
                    else "charges_budget"
                )
                raise TargetPayloadError(
                    f"an OK answer carries §7.2's whole payload, and this one "
                    f"is missing {missing}; a 200 asserts the oracle answered "
                    "the ask, and a status asserted over no series is a claim "
                    "about a world nobody served"
                )
            object.__setattr__(
                self, "target_series", _validated_series(self.target_series)
            )
            object.__setattr__(
                self, "charges_budget", _validated_budget(self.charges_budget)
            )
        elif self.target_series is not None or self.charges_budget is not None:
            raise TargetPayloadError(
                f"a {self.status} answer carries no payload; the sidecar "
                f"holds no entry for this node, so there is no series to "
                "serve and no budget question to answer — a 404 carrying "
                "either would be an answer to a question the route just said "
                "it could not answer"
            )

    @property
    def known(self) -> bool:
        """Whether the sidecar held the node — the clause this answer asserts.

        The readable spelling of ``status == OK``, named for the feature's
        own word: *which returns 200 for a known node*, and the caller that
        just posted should be able to ask exactly that question.  It is a
        statement about the *node*, not about the branch: a real node and a
        null one are both known (feature 118's selection seals both), and
        ``known`` must not be read as "real".
        """
        return self.status == OK

    def __hash__(self) -> int:
        # The payload's mappings are not hashable until they collapse to
        # tuples.  The fold keeps __hash__ consistent with __eq__ and mirrors
        # the evaluator's own response, which collapses its series the same
        # way for the same reason.
        series = None
        if self.target_series is not None:
            series = tuple(
                (day, tuple(sorted(row.items())))
                for day, row in sorted(self.target_series.items())
            )
        return hash((self.status, self.node_id, series, self.charges_budget))


class TargetEndpoint:
    """Serves POST /target over one :class:`~nulloracle.sidecar.NullSidecar`.

    Constructed with the sidecar it answers from; :meth:`post` is the
    route.  The endpoint holds no state of its own — no memo of known
    nodes, no cache of the assignment map — because a cache would hold the
    plaintext labels in process memory, which is precisely what §7.1's
    sealed, mode-``0600`` file exists to prevent: the sidecar is the one
    copy, every request reads it, and reading it is the controlled
    operation.  A second process composing this endpoint over the same
    sidecar answers identically, because the answer is drawn from the file
    on every request.

    Three optional collaborators arrive beside the sidecar, all as injected
    callables and all for the same reason — this member holds no real forward
    returns and imports no other member's store:

    * ``targets`` — *give me the real forward-return series for this
      request* (§7.2's ``forward_returns``, produced by pipeline step 4);
    * ``permute`` — *permute this panel's days with this seed and block
      length* (feature 115's mechanism, called with the entry's own stored
      parameters, so the module that owns the shuffle is the module that
      performs it); the blocks it moves are runs of ``block_days``
      consecutive dates, each carrying its whole cross-section, which is the
      grain §7.3's preservation claim is about;
    * ``past_flip`` — *is this request at or beyond its branch's flip
      depth?* (feature 121's Type-D rule), answering ``None`` for a campaign
      that is not the Type-D regime.

    None is required.  A route missing either the series seam or the
    permutation seam refuses by name rather than serving half a world — and
    refuses on *both* branches, because a route that answered real nodes and
    raised for null ones would be telling the caller the bit.  That is the
    honest degradation: a route that guessed at any of them would be serving
    a world it does not hold.
    A seam that is named but not callable is refused **at construction**
    rather than at the request that needed it — the factory builds every
    component on every ``create_app()`` call, so a signature error must not
    wait for the first evaluation to surface.
    """

    #: The route this endpoint serves — :data:`TARGET_ROUTE`, pinned as a
    #: class attribute so ``TargetEndpoint.route`` states the contract
    #: without an instance.
    route = TARGET_ROUTE

    def __init__(
        self,
        sidecar: NullSidecar,
        *,
        targets: Callable[[Any], Any] | None = None,
        permute: Callable[..., Any] | None = None,
        past_flip: Callable[[Any], Any] | None = None,
    ) -> None:
        # Duck-checked rather than isinstance-guarded: the factory's scan
        # imports this member under an alias module, so the *composed*
        # sidecar component is structurally a NullSidecar but never the
        # same class object a direct import yields — an isinstance here
        # would refuse the very component the factory hands out.  The
        # contract is the per-node assignment seam, and that is what is
        # checked.
        if not callable(getattr(sidecar, "assignment", None)):
            raise TypeError(
                "TargetEndpoint speaks a NullSidecar (something with an "
                f"assignment(node_id) seam); got {type(sidecar).__name__}"
            )
        self._sidecar = sidecar
        self._targets = _optional_callable(targets, "targets")
        self._permute = _optional_callable(permute, "permute")
        self._past_flip = _optional_callable(past_flip, "past_flip")

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        targets: Callable[[Any], Any] | None = None,
        permute: Callable[..., Any] | None = None,
        past_flip: Callable[[Any], Any] | None = None,
    ) -> TargetEndpoint | None:
        """The endpoint over the sidecar the environment names, or ``None``.

        Resolves the sidecar exactly as the member's own builder does
        (:meth:`nulloracle.sidecar.NullSidecar.resolve`), so the endpoint
        and the composed ``nulloracle`` component always answer from the
        same file.  No location and key composes no endpoint — an
        unconfigured sidecar is a discoverable state, not an error — while
        the evaluation whose step 5 must ask is, again, the caller that
        must not find itself in it.

        The collaborators are threaded through so a deployment that *does*
        hold step 4's series, feature 115's permutation and feature 121's
        store composes a complete route through the same resolution — they
        are the caller's to supply, not the environment's to name, because a
        callable is not a configuration value and the factory reads no
        registry of them.
        """
        sidecar = NullSidecar.resolve(env)
        if sidecar is None:
            return None
        return cls(
            sidecar,
            targets=targets,
            permute=permute,
            past_flip=past_flip,
        )

    @property
    def sidecar(self) -> NullSidecar:
        """The sidecar this endpoint answers from."""
        return self._sidecar

    # -- The route ----------------------------------------------------------

    def post(self, request: TargetRequest) -> TargetResponse:
        """Answer one POST /target: §7.2's status line and payload, or a named refusal.

        Features 112 and 113, in the order §7.2 resolves them.

        The node the request names is looked up in §7.1's sidecar — the one
        artifact allowed to hold a node's null status.  A node it does not
        hold answers :data:`NOT_FOUND` with a detail naming the node: a fact
        about the world, not a failure of the route.  A node it does hold
        answers :data:`OK` with the payload, and which branch supplied that
        payload is decided by §7.2's internal rule: the ``past_flip`` seam
        first (a Type-D campaign's flip is a fact of depths, not of the
        sidecar, §7.3), then the entry's own ``is_null``.

        For the real branch the series comes from the ``targets`` seam
        unchanged.  For the null branch it is that same series put through
        the ``permute`` callable derived from the entry's stored
        ``perm_seed`` and ``block_days`` — feature 115's mechanism,
        composed here from the sealed parameters rather than re-implemented,
        so a campaign replayed from the same sidecar reproduces the same
        series (§12).  Either way ``charges_budget`` is ``not is_null``:
        §8 debits no statistical budget for a node whose signal was never
        compared to real forward returns, so the directive is ``False`` for
        the null branch and ``True`` for the real one.

        **Nothing on the answer names the branch, and neither does the work
        (feature 114).**  The response's type, field names and branches are
        the same whichever way the rule went, and so is the work spent
        producing it: both branches' series are *computed* — the real one
        from the ``targets`` seam, the permuted one through the stored
        parameters — and both are *checked* before the bit selects which to
        serve, so the permutation's cost and its validation are paid on a
        real node exactly as on a null one.  A route that permuted only when
        the bit said so would do strictly more work for a null node, and a
        caller holding nothing but a stopwatch would read the bit off the
        latency; see the module docstring for why that leak is the same one
        a branch-only refusal gives.  The one bit that crosses is the
        directive, carried as a directive.  This method names the branch
        exactly once — in the local binding below, reading the entry the
        sidecar handed it — and that name never reaches the response, a
        refusal message, or a log line.  The refusals below name the *missing
        supply* and the *node*, never the branch.
        """
        node = _validated_identity(request.node_id, "node_id")
        # assignment() is a whole-file read per call, by the sidecar's own
        # design: the labels do not live in a cache, here or anywhere.
        assignment = self._sidecar.assignment(node)
        if assignment is None:
            return TargetResponse(
                status=NOT_FOUND,
                node_id=node,
                detail=(
                    f"the sidecar holds no entry for node {node}; §7.2's "
                    "route answers for the nodes a campaign assigned, and a "
                    "node no sidecar holds is unknown — a fact about the "
                    "world, not a failure of the oracle"
                ),
            )
        # §7.2's branch rule, read here and carried no further.  A Type-D
        # campaign's flip is resolved by feature 121's store through the
        # seam; every other campaign's null-ness is the sidecar's own bit.
        is_null = self._is_null(request, node, assignment)
        # One series, read once, whichever branch serves it: the real branch
        # returns it unchanged and the null branch returns it permuted.  Both
        # branches spend the same read — the first half of feature 114's
        # same-work discipline, and the half a route could keep even before
        # the feature landed.
        series = self._real_series(request, node)
        # And both *supplies* are named before the branch is chosen, not on
        # the branch that wanted one.  A route missing either seam can serve
        # neither branch — which is what ``_real_series`` above already
        # enforces and what this line makes symmetric.  Checking the
        # permutation's seam down inside the null branch instead would mean a
        # route holding ``targets`` but no ``permute`` answered real nodes
        # with a 200 and raised *only* for null ones, so a caller catching
        # that exception would have read the bit §7.2 keeps behind the
        # barrier: the refusal itself would be the branch oracle.  Named here,
        # it fires whichever way the rule went.
        permutation = self._permutation_seam(node)
        self._covers(request, series, node)
        # Feature 114's half: both branches' series are computed and checked
        # before the bit selects which one is served, so the work — the seam
        # calls, the validations, the clock — does not vary with the bit.  A
        # route that permuted only on the null branch would hand a caller
        # holding a stopwatch the branch itself: the permutation is
        # panel-sized work, and latency is an answer the caller reads whether
        # the route means to send it or not.
        permuted = self._permuted(series, assignment, node, permutation)
        # The selection is the one move the bit makes, and it moves nothing
        # but *which already-computed value is served*: one conditional over
        # two locals, a cost that does not scale with the series and does not
        # touch a seam.  The permuted series exists on both branches; only
        # the null branch serves it — and a real node pays for it anyway,
        # which is the price of a branch no clock can name.
        served = permuted if is_null else series
        return TargetResponse(
            status=OK,
            node_id=node,
            target_series=served,
            charges_budget=not is_null,
        )

    # -- The branch rule -----------------------------------------------------

    def _is_null(self, request: Any, node: str, assignment: Any) -> bool:
        """§7.2's branch rule for one known node — the entry's bit, or the flip.

        The ``past_flip`` seam is asked first and wins when it answers: a
        Type-D campaign's null-ness is a fact of depths that the sidecar does
        not hold (§7.3: *"Campaigns are homogeneous in null type"*), so a
        Type-D branch's stored bit is whatever the last writer left, and
        reading it would answer the wrong regime's question.  The seam
        answering ``None`` means *this campaign is not Type-D*, and the entry's
        own bit is the answer — which is also the answer for every deployment
        that composed no seam at all.

        The bit is validated as a genuine ``bool`` on the way out, the same
        refusal the assignment layer makes at the write: ``bool("false")`` is
        ``True``, and a coerced bit here would silently serve the wrong world
        and charge the wrong budget in one step.
        """
        if self._past_flip is not None:
            flipped = self._past_flip(request)
            if flipped is not None:
                if not isinstance(flipped, bool):
                    raise TargetPayloadError(
                        f"the past_flip seam answered {flipped!r} "
                        f"({type(flipped).__name__}) for node {node}; the "
                        "seam answers True at or beyond the branch's flip, "
                        "False below it, and None for a campaign that is not "
                        "the Type-D regime — anything else leaves the branch "
                        "undecided, and an undecided branch cannot be served"
                    )
                return flipped
        is_null = getattr(assignment, "is_null", None)
        if not isinstance(is_null, bool):
            raise TargetPayloadError(
                f"the sidecar entry for node {node} carries a null-status "
                f"bit of {is_null!r} ({type(is_null).__name__}); the bit "
                "selects §7.2's branch and therefore which series is served, "
                "and a value that merely looks true or false would select "
                "one without saying so"
            )
        return is_null

    # -- The two supplies ----------------------------------------------------

    def _permutation_seam(self, node: str) -> Any:
        """The ``permute`` seam, or a refusal — asked on *both* branches.

        §7.2's null branch needs the mechanism, and a deployment that wired no
        ``permute`` has one to serve the real branch and none to serve the
        null one.  Refusing that at the moment the null branch wanted it would
        be the cheapest branch oracle in the module: the difference between a
        200 and an exception would *be* ``is_null``, read by any caller who
        wrapped the call in a ``try``.  So the seam's absence is named before
        the branch is chosen, exactly as the series seam's is, and a route
        missing it refuses both branches alike — the same honest degradation
        :meth:`_real_series` states for its own seam.

        The name is the *missing mechanism* and the *node*, never the branch:
        a message that said "this null node needs a permutation" would leak
        the bit it exists to protect.
        """
        if self._permute is None:
            raise TargetPayloadError(
                f"node {node} is served through §7.2's block permutation and "
                "this endpoint holds no permute seam to serve it through; the "
                "sidecar's stored seed and block length are the permutation's "
                "parameters, not the permutation, and serving the real series "
                "in its place would hand the caller real signal inside a "
                "world planted to have none"
            )
        return self._permute

    def _real_series(self, request: Any, node: str) -> Any:
        """The real forward returns for one request, from the ``targets`` seam.

        §7.2's ``forward_returns``, produced by pipeline step 4 and supplied
        by the deployment.  Its absences are named rather than defaulted: a
        route with no seam, a seam answering ``None`` for one request, and a
        seam answering nothing at all are three ways of having no series, and
        each of them refuses with the node in hand — a caller told *which*
        node the oracle could not serve can act on it, where a caller told
        "the oracle is broken" cannot.

        The returned value is *not* validated here.  It is validated by
        :class:`TargetResponse`'s constructor like every other payload this
        module builds, and validating it twice would mean two spellings of
        one contract; the seam's own failures, like an oracle's in feature
        76's gate, propagate unwrapped as its own.
        """
        if self._targets is None:
            raise TargetPayloadError(
                f"node {node} has a series to serve and this endpoint holds "
                "no seam to serve it from; §7.2's response carries the real "
                "forward returns pipeline step 4 aligned, and a route "
                "constructed without them can answer neither branch — serving "
                "an empty series would measure the evaluation against nothing "
                "while §8 charges it nothing either"
            )
        series = self._targets(request)
        if series is None:
            raise TargetPayloadError(
                f"the targets seam answered no series for node {node}; the "
                "seam answers the real forward returns for the request it was "
                "handed (§7.2's forward_returns), and a request it declines "
                "is a request this route cannot serve however the branch "
                "resolves"
            )
        return series

    def _permuted(
        self, series: Any, assignment: Any, node: str, permute: Any
    ) -> Any:
        """The permuted series: the real one through the stored permutation.

        Computed for **both** branches (feature 114) and served only for the
        null one — the method is reached on every request, so its cost and
        its checks are spent whichever branch serves, and the caller's clock
        cannot tell which branch the route was on.

        §7.2's own spelling — ``block_permute(forward_returns, seed=perm_seed,
        block=20d)`` — with both parameters read from the entry the sidecar
        just handed over, so the seed that built a null node's series is the
        seed feature 109 sealed beside the bit and a replayed campaign
        reproduces the same series without any code remembering which seed it
        used (§12).

        **The grain is the panel, so the blocks are days.**  §7.2 writes the
        permutation over ``forward_returns`` because that is what a single
        series is; the response this route serves is a *cross-section per
        rebalance date* (every symbol the ask named, on every covered day), so
        the blocks the permutation moves are runs of ``block_days``
        consecutive **dates**, each carrying its whole cross-section intact.
        That is the only reading under which §7.3's claim survives: *"Block
        permutation shuffles contiguous 20-day blocks, preserving return
        autocorrelation and volatility clustering while destroying the
        signal-to-target relationship"* — a permutation at (date, symbol)
        grain would tear a date's cross-section in half and pair one symbol's
        returns with another's, which destroys the cross-sectional structure
        too and plants a null no longer indistinguishable from a real world
        (feature 123's guard measures exactly that).

        **The dates stay where they are; the rows move between them.**  A
        panel is a grid of rebalance dates crossed with a cross-section, and
        the grid is not a series that can be shuffled — it is the *axis* the
        series is laid out on.  So the permutation's output slot ``i`` keeps
        date ``days[i]`` and takes the row that input slot ``perm[i]`` held,
        which is what makes the result a *different mapping* rather than the
        same mapping written in a different order: a permutation that moved
        each date together with its row would rebuild the identical series,
        and the null branch would report the real one under a shuffled
        insertion order — indistinguishable to every reader, since mapping
        equality is order-insensitive.  That is a world with none of the
        property §7.3 is about, and it is the exact mistake a naive
        ``{days[i]: series[days[i]] for i in perm}`` makes.

        The served series must carry exactly the dates the real one carried,
        each exactly once: the permutation moves day blocks and never creates
        or destroys a bar, so a series with different dates has been
        recomputed rather than rearranged — the check feature 121's resolution
        makes on the same mechanism.  Whether the permutation *moved* anything
        is deliberately not checked; see the module docstring for why a check
        that refused an identity permutation would itself be a branch oracle.

        The permute callable arrives as a parameter rather than being read off
        ``self`` here, because its *absence* is refused by
        :meth:`_permutation_seam` on both branches before this method is
        reached; taking it as an argument is what makes that ordering
        impossible to undo by moving a line.  Since feature 114 the method is
        itself reached on both branches, so the ordering and the cost hold
        together: the seam is named once, called once, and paid for once —
        whichever branch serves.

        The permute callable arrives as a seam for the same reason the others
        do — feature 115's module is not this module's to import at module
        scope, and the mechanism is a pure function of three values the caller
        already holds — but unlike the other two it is *required* wherever
        this method is reached, which since feature 114 is every request:
        the entry's ``perm_seed`` and ``block_days`` are parameters, and a
        parameter is not a mechanism.
        """
        served = permute(
            series,
            seed=getattr(assignment, "perm_seed", None),
            block_days=getattr(assignment, "block_days", None),
        )
        carried = _series_dates(served)
        real = _series_dates(series)
        if carried is not None and carried != real:
            raise TargetPayloadError(
                f"the permutation served {len(carried)} dates for node {node} "
                f"where the real series carries {len(real)}; the block "
                "permutation moves a series' day blocks and never adds or "
                "drops one, so a permuted series on a different support has "
                "been recomputed rather than rearranged (§7.2: the caller "
                "cannot distinguish the two branches from the response, and "
                "a support alone would distinguish them)"
            )
        return served

    # -- The series' own shape ----------------------------------------------

    def _covers(self, request: Any, series: Any, node: str) -> None:
        """Refuse a series that does not answer the request's own ask.

        Two terms of §7.2's request are checked against the series before the
        branch is chosen, so the same check runs whichever way the rule goes
        and nothing here can vary with the bit:

        * **the cross-section** — §7.2's branches preserve the aligned support
          exactly, so an answer naming a symbol the ask did not, or missing
          one it did, is a series that arrived by some path other than this
          one — the substitution the evaluator's gate refuses downstream
          (feature 76's support rule), refused here so the substitution never
          leaves the oracle at all.  The check is on *names*, never on values:
          a route that compared values would be the client-side null detector
          principle P2 forbids, running inside the oracle.
        * **the span** — an answer whose dates fall outside the ``date_range``
          the ask named is an answer to a different ask.  Containment, not
          equality: the real series may cover fewer days than the span (a
          horizon the window cannot reach), but it can never cover days the
          window does not hold.  Equality is exactly what must *not* be
          asserted — ``min``/``max`` of a series are properties a permutation
          can move, so a route that refused a series for its endpoints could
          refuse one branch and not the other.

        Both terms defer when either side is silent, rather than refuse: a
        series that does not state its own symbols or dates is left to
        :class:`TargetResponse`'s constructor (one contract, one refusal), and
        a request that states no cross-section or no span — the duck-typed ask
        the route reads on purpose, from the module-alias seam — states
        nothing to compare against.  Only a *stated* term is enforced, so a
        caller who built a :class:`TargetRequest` never slips past the check
        by accident and a caller who built something request-shaped never gets
        refused for a field they never had.
        """
        self._answers_symbols(request, series, node)
        self._answers_span(request, series, node)

    def _answers_symbols(self, request: Any, series: Any, node: str) -> None:
        """The cross-section term of :meth:`_covers`."""
        named = _series_symbols(series)
        if named is None:
            return
        asked = getattr(request, "symbols", None)
        if asked is None:
            return
        asked = tuple(asked)
        if named != asked:
            missing = sorted(set(asked) - set(named))
            extra = sorted(set(named) - set(asked))
            raise TargetPayloadError(
                f"the series served for node {node} answers for "
                f"{', '.join(named) or 'no symbols'} where the request named "
                f"{', '.join(asked) or 'no symbols'}"
                + (f" — missing {', '.join(missing)}" if missing else "")
                + (
                    f" — carrying {', '.join(extra)}, whom nobody asked for"
                    if extra
                    else ""
                )
                + "; §7.2's branches preserve the support they were asked on, "
                "so a series outside this request's cross-section arrived by "
                "some other path than this route"
            )

    def _answers_span(self, request: Any, series: Any, node: str) -> None:
        """The date-range term of :meth:`_covers`."""
        carried = _series_dates(series)
        if carried is None or not carried:
            return
        span = getattr(request, "date_range", None)
        if span is None:
            return
        try:
            first, last = span
            # Canonicalised the way the series' keys are, so a request that
            # spelled its span as ISO strings — or as anything else
            # :func:`_as_payload_date` refuses — is compared on the same
            # terms.  A span this route cannot read is deferred, not refused:
            # it is the request's own contract to state and
            # :func:`_validated_date_range` to refuse, and a route that
            # refused it here would be a second spelling of one rule, fired
            # only for callers who reached this route without a request.
            first = _as_payload_date(first)
            last = _as_payload_date(last)
        except (TypeError, ValueError, TargetPayloadError):
            return
        if first > last:
            return
        outside = tuple(
            day for day in carried if day < first or day > last
        )
        if outside:
            earliest, latest = outside[0], outside[-1]
            raise TargetPayloadError(
                f"the series served for node {node} carries "
                f"{len(outside)} date(s) outside the {first.isoformat()} to "
                f"{last.isoformat()} span the request named — "
                f"{earliest.isoformat()}"
                + (
                    f" through {latest.isoformat()}"
                    if latest != earliest
                    else ""
                )
                + "; §7.2 answers the window the ask named, and a series "
                "reaching past it is an answer to a different ask"
            )
