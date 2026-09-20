"""The cost model as a composed application component (feature 59).

Feature 59 in one sentence: *"System persists the resolved cost model
version string with its venue name after loading the YAML
configuration."*  The sentence has an order — load, then persist — and
:class:`CostModelService.resolved` is that order made concrete: it loads
the YAML configuration (via :func:`cost_model.config.load_cost_model`),
persists the resolved pair (via :func:`cost_model.store.persist_cost_model`),
and returns the resolved :class:`~cost_model.config.CostModelConfig` so the
caller evaluates against the very identity that landed.  A caller that
loads and forgets to persist cannot get that ordering wrong by accident,
because there is no public method that does one without the other.

The factory's contract is one-way: a component knows how to build itself
from nothing, and the factory asks exactly that.
:meth:`CostModelService.from_env` is that self-construction — the document
path from :data:`~cost_model.config.COST_MODEL_PATH_ENV`, the store from
``DATABASE_URL``.  The factory never passes anything in, so nothing here
may require a parameter it will not receive.

Environment overrides (both optional, both validated loudly):

* ``NULLIUS_COST_MODEL_PATH`` — the YAML document to load (default: the
  §6.2 document this member ships, see
  :data:`~cost_model.config.DEFAULT_COST_MODEL_PATH`)
* ``DATABASE_URL`` — the relational store the resolved pair lands in (the
  workspace-wide spelling every member's store reads)

**Absent store, deferred refusal.**  Construction performs no I/O and
never requires a store: an application composes — and a process that only
wants to *read* a cost model runs — in a deployment with no
``DATABASE_URL`` at all, the same stance the snapshot member's manifest
store takes.  The refusal is deferred to the moment a persist is actually
asked for, and it names the variable that would have named the store.
That keeps "unconfigured" a discoverable state while keeping "configured
but broken" an error, which are not the same thing and must not be
conflated.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from .book_walk import AggressiveFillModel, resolve_aggressive_fill_model
from .config import (
    COST_MODEL_PATH_ENV,
    CostModelConfig,
    load_cost_model,
    read_cost_model_document,
)
from .errors import CostModelConfigError
from .fee_library import FeeImplementation, install_fee_implementation
from .fees import FeeSchedule
from .fill_probability import (
    FillProbabilityModel,
    resolve_fill_probability_model,
)
from .latency import EmpiricalLatencyDistribution
from .latency_store import (
    load_latest_latency_distribution,
    persist_latency_distribution,
)
from .passive_fill import PassiveFillModel, resolve_passive_fill_model
from .queue_penalty import (
    QueuePositionPenaltyModel,
    resolve_queue_position_penalty_model,
)
from .store import (
    DATABASE_URL_ENV,
    load_persisted_cost_model,
    persist_cost_model,
)

__all__ = ["CostModelService", "build_cost_model_service"]


class CostModelService:
    """Load the YAML cost model and persist the pair it resolves.

    Thin by design: every method delegates to the loader or the store, so
    the service adds path/store binding and nothing else.  Both addresses
    are captured at construction and every method still accepts an explicit
    override, so tests and tools can route the same service at a scratch
    document or a scratch store.
    """

    def __init__(
        self,
        config: CostModelConfig | None = None,
        *,
        config_path: str | os.PathLike[str] | None = None,
        database_url: str | None = None,
    ) -> None:
        """Bind a service to a document path (or an already-resolved config).

        ``config`` short-circuits loading: a caller holding a resolved
        :class:`~cost_model.config.CostModelConfig` — a test, or a tool that
        resolved it through some other door — gets a service that persists
        *that* identity without re-reading a document.  ``config_path``
        alone defers the load to the first call, so constructing a service
        performs no I/O and a service whose document is missing fails on
        use, at the caller who asked, rather than at composition.
        """
        if config is not None and config_path is not None:
            raise ValueError(
                "pass either a resolved config or a config_path, not both: a "
                "service bound to a config never reads a document, so the "
                "path would be silently ignored"
            )
        self._config = config
        self._document = None
        self.config_path = config_path
        self.database_url = (
            database_url
            if database_url is not None
            else os.environ.get(DATABASE_URL_ENV)
        )

    @classmethod
    def from_env(cls) -> CostModelService:
        """Construct the component the application factory composes.

        Reads the document path from
        :data:`~cost_model.config.COST_MODEL_PATH_ENV` and the store from
        ``DATABASE_URL``, both optional.  No I/O happens here: the document
        is read on the first :meth:`resolved`/:meth:`load`, and the store
        is opened on the first persist.
        """
        raw = os.environ.get(COST_MODEL_PATH_ENV)
        config_path: str | None = raw if raw else None
        return cls(config_path=config_path)

    @property
    def config(self) -> CostModelConfig:
        """The resolved cost model, loading the document on first access.

        The loaded value is cached, so a service that resolves once reads
        its document once — the YAML file is a signed Z0 artifact, and
        re-parsing it per call would both cost more and let a mid-process
        edit change the identity a caller is pricing against.

        Composing the service touches no disk; this property is what reads
        the document, and it raises
        :class:`~cost_model.errors.CostModelConfigError` for a document that
        is missing, unparseable or not a cost model.
        """
        if self._config is None:
            self._config = load_cost_model(self.config_path)
        return self._config

    def load(
        self, path: str | os.PathLike[str] | None = None
    ) -> CostModelConfig:
        """Load (or return the already-resolved) cost model.

        With ``path`` given the document is read fresh from that path and
        the result replaces the cached value, so one service can resolve
        several documents in sequence — the path is rebound too, because
        the cached parse (:attr:`document`) belongs to the document that
        produced it, and a service that had kept reading the first path
        would resolve the new identity against the old document's fill
        model.  With no path, an already-resolved config is returned
        as-is — the service was constructed with a value, and re-reading
        a document it was explicitly told not to read would be a
        surprise.
        """
        if path is not None:
            self._config = load_cost_model(path)
            self.config_path = str(path)
            self._document = None
        return self.config

    @property
    def document(self) -> Mapping[str, object]:
        """The parsed cost model document, read once and cached.

        The service-level spelling of the single-parse seam
        (:func:`~cost_model.config.read_cost_model_document`): the whole
        §6.2 document — the fee schedule, the fill model, latency and
        borrow — as a read-only mapping, resolved from the one parse so
        every section-bearing consumer of this service (feature 66's
        aggressive fill model here; feature 60's hash when it lands)
        reads the configuration the resolved identity was loaded from,
        not a re-read of whatever the file says now.

        Refused for a service bound to an already-resolved config: that
        service was explicitly told never to read a document, and it has
        none to parse — the refusal names the constructor pair that
        would carry one.  The parse is cached with the config and
        invalidated by :meth:`load`, so one service can resolve several
        documents in sequence exactly as it already could several
        identities.
        """
        if self._document is None:
            if self._config is not None and self.config_path is None:
                raise CostModelConfigError(
                    "a service bound to an already-resolved config carries "
                    "no document to read sections from; construct the "
                    "service with a config_path (or nothing, for the "
                    "shipped default) to resolve a fill model"
                )
            self._document, _origin = read_cost_model_document(self.config_path)
        return self._document

    def resolved(
        self, database_url: str | None = None
    ) -> CostModelConfig:
        """Load the configuration, persist the resolved pair, return it.

        Feature 59's sentence, in its order.  The load happens first and
        its failures (:class:`~cost_model.errors.CostModelConfigError`) are
        raised before any store is touched, so a bad document writes
        nothing; the persist then lands the pair, and a store failure
        (:class:`~cost_model.errors.CostModelStoreError`) is raised rather
        than swallowed, because a resolved cost model that never landed is
        the gap the feature closes.
        """
        config = self.config
        return persist_cost_model(
            config, database_url if database_url is not None else self.database_url
        )

    def persisted(
        self,
        venue: str,
        version: str,
        database_url: str | None = None,
    ) -> CostModelConfig | None:
        """Read a persisted cost model back, or ``None`` when absent.

        The reader a later feature resolves a score's fee assumptions
        against: given the venue and version a score names, the store
        answers with the identity that was loaded — or ``None``, which is
        the honest answer for a cost model this store has never priced
        against.
        """
        return load_persisted_cost_model(
            venue,
            version,
            database_url if database_url is not None else self.database_url,
        )

    def aggressive(self) -> AggressiveFillModel:
        """Resolve the aggressive fill model from the loaded document.

        Feature 66's configuration half: §6.2's document names the
        behaviour (``fill_model.aggressive.walk_book: true``), and this is
        the caller's handle on it — the evaluator and the live execution
        engine both reach the walk through the composed service, so the
        two cannot each grow their own fill model (feature 69's promise,
        and §6.2's ``β₄`` invariant).  The model is resolved from the one
        cached parse (see :attr:`document`), so it is the behaviour of the
        document the resolved identity was loaded from.

        Raises :class:`~cost_model.errors.CostModelConfigError` when the
        document names no fill model or names one whose ``walk_book`` is
        not exactly ``true`` — the shared library implements the walk and
        nothing else, because the only alternative the flag could name is
        the midpoint crossing the feature's sentence rules out.
        """
        return resolve_aggressive_fill_model(self.document)

    def passive(self) -> PassiveFillModel:
        """Resolve the passive fill model's trade-through gate from the loaded document.

        Feature 63's configuration half: §6.2's document names the
        behaviour (``fill_model.passive.require_trade_through: true``), and
        this is the caller's handle on it — the evaluator and the live
        execution engine both reach the gate through the composed service,
        so the two cannot each grow their own fill model (feature 69's
        promise, and §6.2's ``β₄`` invariant).  The gate is resolved from
        the one cached parse (see :attr:`document`), so it is the behaviour
        of the document the resolved identity was loaded from — the same
        parse the aggressive half (:meth:`aggressive`) reads, so the two
        halves of the fill model cannot disagree about which document was
        loaded.

        Raises :class:`~cost_model.errors.CostModelConfigError` when the
        document names no passive gate or names one whose
        ``require_trade_through`` is not exactly ``true`` — the shared
        library implements the trade-through gate and nothing else, because
        the only alternative the flag could name is the touch-fill the
        feature's sentence rules out.
        """
        return resolve_passive_fill_model(self.document)

    def fill_probability(self) -> FillProbabilityModel:
        """Resolve the passive fill-probability decay from the loaded document.

        Feature 65's configuration half: §6.2's document names the behaviour
        (``fill_model.passive.fill_probability_model:
        exp_decay_vs_queue_depth``), and this is the caller's handle on it —
        the evaluator and the live execution engine both reach the decay
        through the composed service, so the two cannot each grow their own
        fill-probability model (feature 69's promise, and §6.2's ``β₄``
        invariant).  The model is resolved from the one cached parse (see
        :attr:`document`), so it is the behaviour of the document the
        resolved identity was loaded from — the same parse the two fill
        gates read (:meth:`passive`, :meth:`aggressive`), so the passive
        half's gate and its fraction cannot disagree about which document
        was loaded.

        Raises :class:`~cost_model.errors.CostModelConfigError` when the
        document names no fill-probability model or names one that is not
        exactly ``exp_decay_vs_queue_depth`` — the shared library implements
        the exponential decay and nothing else, because a second model
        behind a string is how the two implementations feature 69 forbids
        grow back.
        """
        return resolve_fill_probability_model(self.document)

    def queue_penalty(self) -> QueuePositionPenaltyModel:
        """Resolve the passive queue-position penalty from the loaded document.

        Feature 64's configuration half: §6.2's document names the rate
        (``fill_model.passive.queue_position_penalty_bps: 1.5``), and this
        is the caller's handle on it — the evaluator and the live execution
        engine both charge a passive fill through the composed service, so
        the two cannot each grow their own penalty (feature 69's promise,
        and §6.2's ``β₄`` invariant).  The rate is resolved from the one
        cached parse (see :attr:`document`), so it is the behaviour of the
        document the resolved identity was loaded from — the same parse the
        passive gate, the fill-probability decay and the aggressive walk
        read, so the passive half's gate, its fraction and its cost cannot
        disagree about which document was loaded.

        Raises :class:`~cost_model.errors.CostModelConfigError` when the
        document names no penalty rate, or names one that is not a
        non-negative finite real — a cost defaulted to zero silently is the
        floored simulator `docs/alpha-engine-prd.md` §10 warns about, and a
        document that omits the field has not named the behaviour.
        """
        return resolve_queue_position_penalty_model(self.document)

    def fees(self) -> FeeSchedule:
        """Resolve the venue's taker and maker fee schedule from the loaded document.

        Feature 61's configuration half: §6.2's document carries the fee
        schedule (``fees.taker_bps`` and ``fees.maker_bps``), and this is the
        caller's handle on it — the evaluator and the live execution engine
        both deduct the fee through the composed service, so the two cannot
        each grow their own fee schedule (feature 69's promise, and §6.2's
        ``β₄`` invariant).  The schedule is resolved from the one cached
        parse (see :attr:`document`), so it is the schedule of the document
        the resolved identity was loaded from — the same parse the fill
        gates, the fill-probability decay, the aggressive walk and the queue
        penalty read, so the fee axis and the fill axis cannot disagree about
        which document was loaded.

        The resolution runs through the process's one claimed fee
        implementation (:meth:`fee_implementation`, feature 69): the
        resolver this method calls is the one the process claimed, so a
        process whose fee schedule has been claimed by some other module's
        implementation refuses to price here rather than quietly serving
        the second implementation — the divergence §6.2's ``β₄``
        penalizes, surfaced as an error instead of a measurement.

        This is the seam feature 62's discount token substitutes into: the
        discount resolves a *different rate* and hands it to
        :meth:`FeeSchedule.apply` (or :func:`~cost_model.fees.apply_fee`)
        rather than re-deriving the charge, so the discount is a change to
        one input rather than a second implementation of the fee.

        Raises :class:`~cost_model.errors.CostModelConfigError` when the
        document names no ``fees`` block, or names one whose taker or maker
        rate is absent or not a non-negative finite real, or whose venue is
        missing or blank — a fee defaulted to zero silently is the floored
        simulator `docs/alpha-engine-prd.md` §10 warns about, and a cost
        model that cannot price one side of a fill is not a cost model.
        Raises :class:`~cost_model.errors.DuplicateFeeImplementationError`
        when the process's fee schedule has been claimed by an
        implementation that is not the shared library's.
        """
        return self.fee_implementation().resolve(self.document)

    def fee_implementation(self) -> FeeImplementation:
        """Claim and return the one implementation of the fee schedule this process prices through.

        Feature 69's door: *"System rejects a second implementation of the
        fee schedule, so research evaluation and live execution import one
        shared cost library."*  Research evaluation and live execution
        both hold the composed application, and this is the handle the
        composition gives each of them — the claim is idempotent for the
        shared library, so the second consumer to ask holds the *same*
        implementation as the first (that is the feature's "so" clause,
        made a return value), and a process already claimed by a
        different implementation is refused here by name rather than
        served, because serving it would make this service the second
        implementation the feature exists to reject.

        Delegates to
        :func:`~cost_model.fee_library.install_fee_implementation`, so
        the service and the importable symbol are one mechanism, not a
        facade over a twin — the same stance every resolver method above
        takes toward its module function.
        """
        return install_fee_implementation()

    def persist_latency(
        self,
        distribution: EmpiricalLatencyDistribution,
        venue: str,
        version: str,
        *,
        measured_at: str | None = None,
        source: str | None = None,
        database_url: str | None = None,
    ) -> EmpiricalLatencyDistribution:
        """Persist a measured latency distribution for a cost model.

        Feature 67's persist half: the distribution's samples land keyed by
        the cost model's ``(venue, version)`` identity and the instant the
        latency was measured, so a cost model's latency is a history that
        accumulates as shadow runs pile up.  The load-then-persist ordering
        that :meth:`resolved` gives the identity is mirrored here — the
        caller measures a distribution and hands it over, and the store
        writes down what was measured rather than an assumed constant.

        A re-measurement at a later instant adds a row; at the same instant
        it upserts onto the one row (see
        :func:`cost_model.latency_store.persist_latency_distribution`).
        """
        return persist_latency_distribution(
            distribution,
            venue,
            version,
            measured_at=measured_at,
            source=source,
            database_url=database_url if database_url is not None else self.database_url,
        )

    def latency(
        self,
        venue: str,
        version: str,
        database_url: str | None = None,
    ) -> EmpiricalLatencyDistribution | None:
        """Read the most recently measured latency distribution for a cost model.

        The reader a latency-aware cost computation resolves against: given
        the venue and version a score names, the store answers with the
        latest distribution that was measured — or ``None``, which is the
        honest answer for a cost model whose latency has never been
        measured, and the signal that pricing against it must not fall back
        to an assumed constant.
        """
        return load_latest_latency_distribution(
            venue,
            version,
            database_url if database_url is not None else self.database_url,
        )


def build_cost_model_service() -> CostModelService:
    """Zero-argument builder registered with the application factory.

    Kept as a named module-level function (rather than passing
    ``CostModelService.from_env`` directly) so the registry shows an
    intention rather than a classmethod, and so tests can assert on the
    builder independently of construction.
    """
    return CostModelService.from_env()
