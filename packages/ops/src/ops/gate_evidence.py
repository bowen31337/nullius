"""Feature 6's four endpoints: the M3 gate evidence, served read-only.

additions_spec_operator_surfaces.xml, "Gate Evidence Surfaces", feature 6:
*System serves the M3 gate evidence through four read endpoints in a new
ops/gate_evidence.py, following the ops/regime_coverage.py pattern.*  The
four figures are already persisted by this member's own stores — feature
344's planted-null calibration pair (:mod:`ops.null_calibration`), feature
345's Type-B depth past the flip (:mod:`ops.type_b_depth`), feature 346's
discovery rate (:mod:`ops.discovery_rate`) and feature 347's meta-overfit
gap (:mod:`ops.meta_overfit`) — and Journey Run 7 (J20) found that nothing
serves or shows them: the evidence prd §12's M3 exit reads exists in the
database and nowhere an operator can ask for it.  This module is that
read surface, and it adds no new statistic: every figure a route below
answers is a row one of the four stores above already wrote.

**The pattern copied is ``ops.regime_coverage``'s, narrowed to a
same-member read.**  Feature 343's route reaches *another* member's store
through a deferred import, because the factory's scan has taken that
member's ``src/`` off ``sys.path`` by the time a builder fires.  None of
that applies here: the four stores this module reads are the ops
member's own, already imported directly by this package's ``__init__``
(the same module that fires every ``@register`` in this file), so there is
no scan-order hazard to defer around and no cross-member error to
translate from a sibling's vocabulary — only this module's own
(:class:`~ops.errors.GateEvidenceMetricError`).  What *is* copied
verbatim is the rest of the family's law: a no-argument ``get()``, a
frozen response, ``None`` without ``DATABASE_URL``, and a store failure
surfaced rather than answered around.

**Each route answers one store's whole trend, not a point read.**  Every
one of the four stores already offers a per-campaign (or, for the
meta-overfit gap, per-cycle) point read — :meth:`~ops.null_calibration.
NullCalibrations.calibration`, :meth:`~ops.type_b_depth.TypeBDepths.depth`,
:meth:`~ops.discovery_rate.DiscoveryRates.rate`,
:meth:`~ops.meta_overfit.MetaOverfitGaps.gap` — and none of those is this
route's: a GET with no body has no campaign or cycle to filter by, so the
answer is the store's own :meth:`history` (oldest first, the order every
store in this workspace already returns it in) with the *newest* row read
off the last entry, the same derivation :mod:`ops.fdr_route` takes for its
own top-line figure.  An empty store answers an empty history and a
``newest`` of ``None`` — a discoverable absence, never a zero, because
every one of the four stores treats ``0`` (or ``0.0``) as a measurement a
campaign or cycle actually produced and reserves ``None`` for a trend
nobody has closed a row into yet.  This module restates neither
distinction; it carries the store's own answer through unchanged.

**No ``is_null`` label and no per-node null status ever reaches a
response, because none of the four tables holds one.**  Every row these
stores persist is a per-campaign or per-cycle *aggregate* — a pair of
fractions, a count, a quotient, a difference — never a per-node verdict,
so there is no field here to accidentally leak and no filtering this
module has to perform to keep PRD §4.2's boundary (the sidecar key that
labels a node real or null is granted to exactly one process, and it is
not this one).

**One error class for all four routes.**  Unlike the member's earlier
routes, which each own a class because each translates a *different*
sibling member's error, these four translate four errors that already
live in this member's own vocabulary (:class:`~ops.errors.
NullCalibrationError`, :class:`~ops.errors.TypeBDepthError`,
:class:`~ops.errors.DiscoveryRateError`,
:class:`~ops.errors.MetaOverfitGapError`) into one more — this module's
own :class:`~ops.errors.GateEvidenceMetricError` — so a caller that reads
all four gate-evidence surfaces catches one class rather than four, the
same economy the member's base :class:`~ops.errors.OpsError` offers one
level up.

Stdlib-only: :mod:`collections.abc` for the history guard, :mod:`os` for
nothing this module reads directly (the stores resolve ``DATABASE_URL``
themselves, through their own :meth:`resolve`), :mod:`dataclasses` for the
four responses, :mod:`typing` for ``Optional``.  No cross-member import at
all — the four stores are this member's own and already on the scan's
``sys.path`` wherever this package is.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Optional

from .discovery_rate import DiscoveryRate, DiscoveryRates
from .errors import (
    DiscoveryRateError,
    GateEvidenceMetricError,
    MetaOverfitGapError,
    NullCalibrationError,
    TypeBDepthError,
)
from .meta_overfit import MetaOverfitGap, MetaOverfitGaps
from .null_calibration import NullCalibration, NullCalibrations
from .type_b_depth import TypeBDepth, TypeBDepths

__all__ = [
    "DISCOVERY_RATE_ROUTE",
    "META_OVERFIT_ROUTE",
    "NULL_CALIBRATION_ROUTE",
    "OPS_DISCOVERY_RATE_ROUTE_COMPONENT_NAME",
    "OPS_META_OVERFIT_ROUTE_COMPONENT_NAME",
    "OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME",
    "OPS_TYPE_B_DEPTH_ROUTE_COMPONENT_NAME",
    "TYPE_B_DEPTH_ROUTE",
    "DiscoveryRateEndpoint",
    "DiscoveryRateHistoryResponse",
    "MetaOverfitEndpoint",
    "MetaOverfitHistoryResponse",
    "NullCalibrationEndpoint",
    "NullCalibrationHistoryResponse",
    "TypeBDepthEndpoint",
    "TypeBDepthHistoryResponse",
]

#: Feature 344's route — the planted-null calibration pair's trend.
NULL_CALIBRATION_ROUTE = "/metrics/null-calibration"

#: Feature 345's route — the Type-B depth past the flip trend.
TYPE_B_DEPTH_ROUTE = "/metrics/type-b-depth"

#: Feature 346's route — the discoveries-per-1000-budget-charging-trials
#: trend.
DISCOVERY_RATE_ROUTE = "/metrics/discovery-rate"

#: Feature 347's route — the train-versus-holdout gap trend.
META_OVERFIT_ROUTE = "/metrics/meta-overfit"

#: This route's component name.  Suffixed ``-route`` because
#: ``"ops-null-calibration"`` already names the *store* this route reads
#: (:data:`~ops.null_calibration.OPS_NULL_CALIBRATION_COMPONENT_NAME`), and
#: a composed application's components are looked up by name — the two
#: must not collide.
OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME = "ops-null-calibration-route"

#: This route's component name, beside
#: :data:`~ops.type_b_depth.OPS_TYPE_B_DEPTH_COMPONENT_NAME` (the store),
#: for the reason :data:`OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME` states.
OPS_TYPE_B_DEPTH_ROUTE_COMPONENT_NAME = "ops-type-b-depth-route"

#: This route's component name, beside
#: :data:`~ops.discovery_rate.OPS_DISCOVERY_RATE_COMPONENT_NAME` (the
#: store), for the reason :data:`OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME`
#: states.
OPS_DISCOVERY_RATE_ROUTE_COMPONENT_NAME = "ops-discovery-rate-route"

#: This route's component name, beside
#: :data:`~ops.meta_overfit.OPS_META_OVERFIT_COMPONENT_NAME` (the store),
#: for the reason :data:`OPS_NULL_CALIBRATION_ROUTE_COMPONENT_NAME` states.
OPS_META_OVERFIT_ROUTE_COMPONENT_NAME = "ops-meta-overfit-route"


def _the_history(history: Any, record_type: type, *, route: str) -> tuple[Any, ...]:
    """Narrow a hand-built ``history`` to a tuple of ``record_type``
    instances, oldest first, or refuse it.

    Shared by the four responses below: each one's rows are already this
    member's own frozen, self-validating record type (the stores'
    :meth:`history` answers them already checked and already ordered), so
    there is no field to re-parse — only the two facts a hand-built
    response (tests, a later adapter over a recorded trend) could get
    wrong: that every entry really is one of this table's rows, and that
    the order is the one the newest-row derivation below depends on.

    A ``str`` or ``bytes`` is refused explicitly rather than iterated (both
    are sequences, and iterating one descends into characters); a mapping
    is refused too, because a mapping of these keys to these rows is not
    the shape any store answers.  An entry that is not a ``record_type``
    instance is refused by name — an isinstance check, not duck typing,
    because unlike a cross-member seam (:mod:`ops.regime_coverage`'s), the
    record types read here are defined inside this same member and never
    reloaded under a synthetic scan alias, so there is no identity drift
    an isinstance check could be fooled by.  An entry whose
    ``recorded_at`` runs backwards from the one before it is refused for
    the same reason :mod:`ops.fdr_route` refuses it: "the last row is the
    newest" is every one of these four routes' whole derivation of its
    point answer, and a history whose order lied would silently serve the
    wrong row as current.
    """
    if isinstance(history, (str, bytes)) or not isinstance(history, Iterable):
        raise GateEvidenceMetricError(
            f"a GET {route} history is a sequence of {record_type.__name__} "
            f"rows, oldest first — the store's own trend read — and this is "
            f"not one (got {history!r}, {type(history).__name__}). The "
            f"response is the route's testimony about the trend, and "
            f"something that is not a sequence of rows is not a trend "
            f"anybody measured (feature 6)"
        )
    rows: list[Any] = []
    previous_instant: Optional[str] = None
    for entry in history:
        if not isinstance(entry, record_type):
            raise GateEvidenceMetricError(
                f"a GET {route} history holds {record_type.__name__} rows, "
                f"and this entry is not one (got {entry!r}, "
                f"{type(entry).__name__}). Each row is the owning store's "
                f"own frozen record, already validated at the store, and an "
                f"entry of any other shape is not a row that store wrote "
                f"(feature 6)"
            )
        if previous_instant is not None and entry.recorded_at < previous_instant:
            raise GateEvidenceMetricError(
                f"a GET {route} history is oldest-first — the store's own "
                f"order, which the newest row is drawn from as this route's "
                f"point answer — and this row's recorded_at "
                f"({entry.recorded_at!r}) runs backwards from the one "
                f"before it ({previous_instant!r}). A history whose order "
                f"lied would silently answer the wrong row as current; the "
                f"order is the store's law and this response holds it, "
                f"never re-sorts around it (feature 6)"
            )
        previous_instant = entry.recorded_at
        rows.append(entry)
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class NullCalibrationHistoryResponse:
    """The answer to one GET /metrics/null-calibration: feature 344's
    planted-null calibration trend, and its newest row.

    ``history`` is the calibration store's whole answer, oldest first —
    one :class:`~ops.null_calibration.NullCalibration` per closed
    campaign — and :attr:`newest` is derived from it (the last row), never
    stored beside it, so the trend and the point answer cannot disagree.
    An empty ``history`` is the honest answer for a deployment that has
    closed no campaign out: :attr:`newest` is ``None``, the value is
    falsy, and that is an absence, never the ``(0.0, 0.0)`` pair a
    careless surface could substitute for it.

    Frozen: the response is this route's testimony about the store at the
    moment it was read.
    """

    #: Every campaign's calibration pair on record, oldest first.
    history: tuple[NullCalibration, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history",
            _the_history(self.history, NullCalibration, route=NULL_CALIBRATION_ROUTE),
        )

    @property
    def newest(self) -> Optional[NullCalibration]:
        """The most recently closed campaign's calibration pair, or
        ``None`` when no campaign has closed one out."""
        return self.history[-1] if self.history else None

    def __bool__(self) -> bool:
        return bool(self.history)

    def __len__(self) -> int:
        return len(self.history)


@dataclass(frozen=True, slots=True)
class TypeBDepthHistoryResponse:
    """The answer to one GET /metrics/type-b-depth: feature 345's Type-B
    depth-past-the-flip trend, and its newest row.

    The same shape as :class:`NullCalibrationHistoryResponse`, over
    :class:`~ops.type_b_depth.TypeBDepth` rows: ``history`` oldest first,
    :attr:`newest` its last row or ``None`` for a deployment that has
    closed no Type-D campaign out.  A zero count is a measurement (a
    campaign that deepened past no flip) and is served like any other
    row; only the *absence* of a row answers ``None``.
    """

    #: Every campaign's Type-B depth count on record, oldest first.
    history: tuple[TypeBDepth, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history",
            _the_history(self.history, TypeBDepth, route=TYPE_B_DEPTH_ROUTE),
        )

    @property
    def newest(self) -> Optional[TypeBDepth]:
        """The most recently closed campaign's Type-B depth count, or
        ``None`` when no campaign has closed one out."""
        return self.history[-1] if self.history else None

    def __bool__(self) -> bool:
        return bool(self.history)

    def __len__(self) -> int:
        return len(self.history)


@dataclass(frozen=True, slots=True)
class DiscoveryRateHistoryResponse:
    """The answer to one GET /metrics/discovery-rate: feature 346's
    discoveries-per-1000-budget-charging-trials trend, and its newest row.

    The same shape as :class:`NullCalibrationHistoryResponse`, over
    :class:`~ops.discovery_rate.DiscoveryRate` rows: ``history`` oldest
    first, :attr:`newest` its last row or ``None`` for a deployment that
    has closed no campaign out.  A zero rate is a measurement (a campaign
    that found nothing) and is served like any other row; only the
    *absence* of a row answers ``None``.
    """

    #: Every campaign's discovery rate on record, oldest first.
    history: tuple[DiscoveryRate, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history",
            _the_history(self.history, DiscoveryRate, route=DISCOVERY_RATE_ROUTE),
        )

    @property
    def newest(self) -> Optional[DiscoveryRate]:
        """The most recently closed campaign's discovery rate, or
        ``None`` when no campaign has closed one out."""
        return self.history[-1] if self.history else None

    def __bool__(self) -> bool:
        return bool(self.history)

    def __len__(self) -> int:
        return len(self.history)


@dataclass(frozen=True, slots=True)
class MetaOverfitHistoryResponse:
    """The answer to one GET /metrics/meta-overfit: feature 347's
    train-versus-holdout gap trend, and its newest row.

    The same shape as :class:`NullCalibrationHistoryResponse`, over
    :class:`~ops.meta_overfit.MetaOverfitGap` rows keyed by cycle rather
    than campaign: ``history`` oldest first, :attr:`newest` its last row
    or ``None`` for a deployment whose dreaming loop has closed no cycle
    out.  A zero gap is a measurement (a cycle whose two halves read
    identically) and is served like any other row; only the *absence* of
    a row answers ``None``.
    """

    #: Every cycle's train-versus-holdout gap on record, oldest first.
    history: tuple[MetaOverfitGap, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history",
            _the_history(self.history, MetaOverfitGap, route=META_OVERFIT_ROUTE),
        )

    @property
    def newest(self) -> Optional[MetaOverfitGap]:
        """The most recently closed cycle's gap, or ``None`` when no
        cycle has closed one out."""
        return self.history[-1] if self.history else None

    def __bool__(self) -> bool:
        return bool(self.history)

    def __len__(self) -> int:
        return len(self.history)


class NullCalibrationEndpoint:
    """Serves GET /metrics/null-calibration over one calibration store.

    The store is this member's own
    (:class:`~ops.null_calibration.NullCalibrations`), held directly — no
    deferred carrier and no cross-member door, because the store lives in
    this same package.  Constructed with the store it reads; :meth:`get`
    is the route.  Holds no state of its own: a campaign closed between
    two reads must move the second answer, so nothing here is cached.
    """

    #: The route this endpoint serves.
    route = NULL_CALIBRATION_ROUTE

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "history", None)):
            raise TypeError(
                "NullCalibrationEndpoint speaks a calibration store "
                "(something with a history() trend read); got "
                f"{type(store).__name__}. The route answers the "
                "planted-null calibration trend (feature 6, docs §16), "
                "and that trend is the store's history()."
            )
        self._store = store

    @classmethod
    def from_env(
        cls, env: Optional[Any] = None
    ) -> Optional["NullCalibrationEndpoint"]:
        """The endpoint over the store ``DATABASE_URL`` names, or
        ``None`` when it names none.

        Delegates entirely to :meth:`~ops.null_calibration.
        NullCalibrations.resolve`, the store's own unset-aware
        resolution, rather than re-parsing the environment here: the two
        must compose on exactly the same decision, and restating it would
        be a second spelling that could drift from the store's.
        """
        store = NullCalibrations.resolve(env)
        return None if store is None else cls(store)

    @property
    def store(self) -> Any:
        """The calibration store this endpoint reads."""
        return self._store

    def get(self) -> NullCalibrationHistoryResponse:
        """Answer one GET /metrics/null-calibration: the planted-null
        calibration trend and its newest row.

        The read is the store's :meth:`~ops.null_calibration.
        NullCalibrations.history`, every time — no cache, no memo.  A
        read that fails is translated into this module's vocabulary and
        chained to the original; nothing is ever caught into an answer,
        because every fallback this route could add is a trend nobody
        measured.  An empty trend is not a failure: the response answers
        it with an empty history and a ``newest`` of ``None``.
        """
        try:
            rows = tuple(self._store.history())
        except NullCalibrationError as exc:
            raise GateEvidenceMetricError(
                f"could not answer GET {NULL_CALIBRATION_ROUTE}: the "
                f"planted-null calibration store refused the read: "
                f"{exc!r}. The repair is the store's (the original refusal "
                f"is chained), never a fallback trend (feature 6)"
            ) from exc
        return NullCalibrationHistoryResponse(history=rows)


class TypeBDepthEndpoint:
    """Serves GET /metrics/type-b-depth over one Type-B depth store.

    The same shape as :class:`NullCalibrationEndpoint`, over
    :class:`~ops.type_b_depth.TypeBDepths`.
    """

    #: The route this endpoint serves.
    route = TYPE_B_DEPTH_ROUTE

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "history", None)):
            raise TypeError(
                "TypeBDepthEndpoint speaks a Type-B depth store (something "
                f"with a history() trend read); got {type(store).__name__}. "
                "The route answers the Type-B depth trend (feature 6, docs "
                "§16), and that trend is the store's history()."
            )
        self._store = store

    @classmethod
    def from_env(cls, env: Optional[Any] = None) -> Optional["TypeBDepthEndpoint"]:
        """The endpoint over the store ``DATABASE_URL`` names, or
        ``None`` when it names none — delegated to
        :meth:`~ops.type_b_depth.TypeBDepths.resolve`, for the reason
        :meth:`NullCalibrationEndpoint.from_env` states."""
        store = TypeBDepths.resolve(env)
        return None if store is None else cls(store)

    @property
    def store(self) -> Any:
        """The Type-B depth store this endpoint reads."""
        return self._store

    def get(self) -> TypeBDepthHistoryResponse:
        """Answer one GET /metrics/type-b-depth: the Type-B
        depth-past-the-flip trend and its newest row.  See
        :meth:`NullCalibrationEndpoint.get` for the read's law."""
        try:
            rows = tuple(self._store.history())
        except TypeBDepthError as exc:
            raise GateEvidenceMetricError(
                f"could not answer GET {TYPE_B_DEPTH_ROUTE}: the Type-B "
                f"depth store refused the read: {exc!r}. The repair is the "
                f"store's (the original refusal is chained), never a "
                f"fallback trend (feature 6)"
            ) from exc
        return TypeBDepthHistoryResponse(history=rows)


class DiscoveryRateEndpoint:
    """Serves GET /metrics/discovery-rate over one discovery-rate store.

    The same shape as :class:`NullCalibrationEndpoint`, over
    :class:`~ops.discovery_rate.DiscoveryRates`.
    """

    #: The route this endpoint serves.
    route = DISCOVERY_RATE_ROUTE

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "history", None)):
            raise TypeError(
                "DiscoveryRateEndpoint speaks a discovery-rate store "
                f"(something with a history() trend read); got "
                f"{type(store).__name__}. The route answers the discovery "
                "rate trend (feature 6, docs §16), and that trend is the "
                "store's history()."
            )
        self._store = store

    @classmethod
    def from_env(
        cls, env: Optional[Any] = None
    ) -> Optional["DiscoveryRateEndpoint"]:
        """The endpoint over the store ``DATABASE_URL`` names, or
        ``None`` when it names none — delegated to
        :meth:`~ops.discovery_rate.DiscoveryRates.resolve`, for the reason
        :meth:`NullCalibrationEndpoint.from_env` states."""
        store = DiscoveryRates.resolve(env)
        return None if store is None else cls(store)

    @property
    def store(self) -> Any:
        """The discovery-rate store this endpoint reads."""
        return self._store

    def get(self) -> DiscoveryRateHistoryResponse:
        """Answer one GET /metrics/discovery-rate: the discoveries per
        1000 budget-charging trials trend and its newest row.  See
        :meth:`NullCalibrationEndpoint.get` for the read's law."""
        try:
            rows = tuple(self._store.history())
        except DiscoveryRateError as exc:
            raise GateEvidenceMetricError(
                f"could not answer GET {DISCOVERY_RATE_ROUTE}: the "
                f"discovery-rate store refused the read: {exc!r}. The "
                f"repair is the store's (the original refusal is "
                f"chained), never a fallback trend (feature 6)"
            ) from exc
        return DiscoveryRateHistoryResponse(history=rows)


class MetaOverfitEndpoint:
    """Serves GET /metrics/meta-overfit over one meta-overfit gap store.

    The same shape as :class:`NullCalibrationEndpoint`, over
    :class:`~ops.meta_overfit.MetaOverfitGaps`, keyed by dreaming cycle
    rather than campaign.
    """

    #: The route this endpoint serves.
    route = META_OVERFIT_ROUTE

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "history", None)):
            raise TypeError(
                "MetaOverfitEndpoint speaks a meta-overfit gap store "
                f"(something with a history() trend read); got "
                f"{type(store).__name__}. The route answers the "
                "train-versus-holdout gap trend (feature 6, docs §16), "
                "and that trend is the store's history()."
            )
        self._store = store

    @classmethod
    def from_env(cls, env: Optional[Any] = None) -> Optional["MetaOverfitEndpoint"]:
        """The endpoint over the store ``DATABASE_URL`` names, or
        ``None`` when it names none — delegated to
        :meth:`~ops.meta_overfit.MetaOverfitGaps.resolve`, for the reason
        :meth:`NullCalibrationEndpoint.from_env` states."""
        store = MetaOverfitGaps.resolve(env)
        return None if store is None else cls(store)

    @property
    def store(self) -> Any:
        """The meta-overfit gap store this endpoint reads."""
        return self._store

    def get(self) -> MetaOverfitHistoryResponse:
        """Answer one GET /metrics/meta-overfit: the train-versus-holdout
        gap trend and its newest row.  See
        :meth:`NullCalibrationEndpoint.get` for the read's law."""
        try:
            rows = tuple(self._store.history())
        except MetaOverfitGapError as exc:
            raise GateEvidenceMetricError(
                f"could not answer GET {META_OVERFIT_ROUTE}: the "
                f"meta-overfit gap store refused the read: {exc!r}. The "
                f"repair is the store's (the original refusal is "
                f"chained), never a fallback trend (feature 6)"
            ) from exc
        return MetaOverfitHistoryResponse(history=rows)
