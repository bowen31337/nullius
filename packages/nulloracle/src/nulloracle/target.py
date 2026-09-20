"""Feature 112's endpoint: POST /target, the oracle's one route.

app_spec.xml, "Null Oracle & Planted Nulls", feature 112: *System exposes
POST /target accepting node_id, campaign_id, depth, horizon, symbols and a
date range, which returns 200 for a known node.*  docs/nullius-tech-
architecture.md §7.2 spells the interface this route serves::

    POST /target
      request:  { node_id, campaign_id, depth, horizon, symbols[], date_range }
      response: { target_series, charges_budget }   # is_null NEVER appears

and §6.1 names the caller: pipeline step 5 — ``null_gate ── ask null oracle
for the target series ── §7`` — is the only place a target series is ever
substituted, and this route is the thing that step asks.  The feature's own
sentence stops at the request and the status line: the body §7.2 promises
(``target_series`` plus the opaque ``charges_budget`` directive) is feature
113's to serve and feature 114's to make branch-indistinguishable, so this
module owns the ask, the answer's *status*, and nothing of the payload —
the seam below is the half every later feature of the route composes onto.

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

**The assignment is read, and then discarded.**  Learning that a node is
known means opening the entry, and the entry carries ``is_null`` — the one
bit §7.2's response comment says NEVER appears.  Nothing in this module
branches on it, records it, or echoes it: the 200 a null node earns and the
200 a real node earns are the same answer built the same way (a real root
is as known as a null one — feature 118's selection seals both), which is
feature 114's identical-shape promise observed from the day the route
exists rather than retrofitted after it.

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

**Stdlib only.**  ``datetime``, ``uuid`` by way of the assignment layer's
normalization, and nothing else at module scope — the factory's scan
imports this package to fire its ``@register``, and the route must not make
that import pay for anything (the same discipline every store in this
member states).  The sidecar arrives constructed; the endpoint holds no
key, no path and no labels of its own.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .assignment import normalize_node_id
from .errors import TargetRouteError
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
    """The answer to one POST /target: the status line, and whose it is.

    Feature 112's half of §7.2's response — the status the route answers
    with.  ``status`` is :data:`OK` when the sidecar holds the node and
    :data:`NOT_FOUND` when it does not; ``node_id`` is whose answer this is
    (canonical UUID text, so a logged response joins to the tree store);
    ``detail`` carries the human-readable reason a non-OK answer states.
    The payload §7.2 promises — ``target_series`` and ``charges_budget`` —
    is feature 113's to serve and appears nowhere here: nothing in this
    response can say which branch produced it, so nothing does, from the
    route's first day.

    Frozen, because the response is the route's testimony about the world
    at one moment; a response that could be edited after the fact would be
    the oracle revising an answer already given.
    """

    #: The status the route answered with — :data:`OK` or
    #: :data:`NOT_FOUND`, the closed pair :data:`STATUS_CODES` spells.
    status: int
    #: The node the answer is for, canonical UUID spelling.
    node_id: str
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

    @property
    def known(self) -> bool:
        """Whether the sidecar held the node — the clause this answer asserts.

        The readable spelling of ``status == OK``, named for the feature's
        own word: *which returns 200 for a known node*, and the caller that
        just posted should be able to ask exactly that question.
        """
        return self.status == OK


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
    """

    #: The route this endpoint serves — :data:`TARGET_ROUTE`, pinned as a
    #: class attribute so ``TargetEndpoint.route`` states the contract
    #: without an instance.
    route = TARGET_ROUTE

    def __init__(self, sidecar: NullSidecar) -> None:
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

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> TargetEndpoint | None:
        """The endpoint over the sidecar the environment names, or ``None``.

        Resolves the sidecar exactly as the member's own builder does
        (:meth:`nulloracle.sidecar.NullSidecar.resolve`), so the endpoint
        and the composed ``nulloracle`` component always answer from the
        same file.  No location and key composes no endpoint — an
        unconfigured sidecar is a discoverable state, not an error — while
        the evaluation whose step 5 must ask is, again, the caller that
        must not find itself in it.
        """
        sidecar = NullSidecar.resolve(env)
        return None if sidecar is None else cls(sidecar)

    @property
    def sidecar(self) -> NullSidecar:
        """The sidecar this endpoint answers from."""
        return self._sidecar

    # -- The route ----------------------------------------------------------

    def post(self, request: TargetRequest) -> TargetResponse:
        """Answer one POST /target: 200 for a known node, 404 for an unknown one.

        The whole of feature 112 at its seam.  The node the request names
        is looked up in §7.1's sidecar — the one artifact allowed to hold a
        node's null status — and the sidecar's answer to *does it hold this
        node?* is the route's answer: a held entry returns
        :data:`TargetResponse` with :data:`OK`, and a node the sidecar
        does not hold returns :data:`NOT_FOUND` with a detail naming the
        node.  The entry itself is read and discarded: whether it says the
        node is null is the one bit this route never carries, serves, or
        branches on — the response's payload (feature 113) and its
        branch-indistinguishable shape and timing (feature 114) compose
        onto this answer without this module learning anything more.

        The endpoint reads the request duck-typed, validating the identity
        it reads (the composed endpoint and a directly-imported request are
        the same source under two module names, and an isinstance between
        them would refuse the legitimate caller).  A malformed identity is
        refused by name before the sidecar is opened, so a malformed body
        spends no read of the one file worth controlling.

        The sidecar's own failures propagate unwrapped: a missing file
        (:class:`~nulloracle.errors.SidecarStoreError`) or one that will
        not open (:class:`~nulloracle.errors.SidecarDecryptionError`) is a
        deployment failure, and dressing either as a 404 would read "no
        such node" off a world the route never saw.
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
        # The entry was read only to learn the node is known.  Its is_null,
        # perm_seed and block_days stay behind the barrier: features 113-
        # 114 compose the payload onto this answer, and none of it is this
        # feature's to carry.
        return TargetResponse(status=OK, node_id=node)
