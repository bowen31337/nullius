"""``cost_model`` — Z0: the shared cost library's configuration identity.

app_spec.xml, "Cost Model & Fill Simulation", feature 59: *System persists
the resolved cost model version string with its venue name after loading
the YAML configuration.*  docs/nullius-tech-architecture.md §6.2 fixes the
document (a ``cost_model`` block carrying ``version``, ``venue``, the fee
schedule, the fill model, the latency source and the borrow source) and
states the rule that makes the identity matter: *"``cost_model_hash`` is
part of every score's provenance triple"* — so the version string and its
venue are not decoration, they are half of what makes two scores
comparable at all.

Feature 60 lands the other half: *System persists ``cost_model_hash``
computed over the loaded configuration, so every score names its fee
assumptions.*  Where feature 59 records the ``(venue, version)`` *label* a
document chose, feature 60 pins the *bytes* behind it — the whole loaded
model, fee schedule and fill model and latency and borrow included —
because a label is something an author writes and two documents can carry
one label while pricing differently.  :mod:`cost_model.identity` holds the
formula (canonical JSON over the loaded model, hashed once as sha256), and
:class:`~cost_model.config.CostModelConfig` carries the result, folded from
the same parse the pair was resolved from — so the hash a score names is
the hash of the configuration that priced it, not of whatever the file says
now.  §14.1's triple is now whole in this package: the cost axis is
computed here, persisted here, and read back here.

This package is the **single shared cost library** §6.2 requires: *"Shared
library used by both the evaluator and the live execution engine.
Divergence between these two is exactly the quantity β₄ penalizes, so they
must be the same code, not two implementations of the same document."*
Feature 59 lands the configuration identity, loaded from the YAML document
and persisted, and feature 60 the hash over it.  The features that consume
it (the fee schedule of 61-62, the fill model of 63-66, the book walk of
66, the latency distribution of 67, the borrow series of 68) layer on top
of this package's resolved value rather than beside it, which is what keeps
one schedule from becoming two.

Feature 63 layers onto that identity from the fill model's passive half:
*System fills a passive order only when the recorded tape trades through
the quoted price, which rejects fills that merely touch it.*  It is §6.2's
``passive.require_trade_through: true`` made concrete, and
:mod:`cost_model.passive_fill` holds it — the recorded tape as a value
(:class:`~cost_model.passive_fill.RecordedTape`, chronological trades), the
resting order as a value (:class:`~cost_model.passive_fill.PassiveOrder`,
a side and a limit price), and the gate that answers *whether* the order
filled and names the trade that picked it off when it did
(:class:`~cost_model.passive_fill.PassiveFillDecision`).  It refuses the
fill the naive touch-based model would have granted — a trade that prints
exactly at the quote has reached the price but not crossed it — because a
passive provider is picked off only when the market moves *past* its quote.
It refuses what the tape did not record — a tape that never traded through
leaves the order unfilled — and a document whose ``require_trade_through``
is not ``true`` is refused, because the only alternative behaviour is the
touch-fill the sentence rules out and this library does not carry it.  It
is the gate features 64 and 65 build on: the queue-position penalty and the
fill-probability decay price a fill this feature has already granted.

Feature 64 layers onto that gate from the fill model's passive half:
*System charges a queue-position penalty in basis points on every passive
fill, so a zero-maker venue still returns a nonzero cost.*  It is §6.2's
``passive.queue_position_penalty_bps: 1.5`` made concrete, and
:mod:`cost_model.queue_penalty` holds it — the resolved rate
(:class:`~cost_model.queue_penalty.QueuePositionPenaltyModel`) and the
charge it levies on a fill (:class:`~cost_model.queue_penalty.QueuePenalty`,
which reads :attr:`~cost_model.queue_penalty.QueuePenalty.cost_bps`).  It
takes feature 63's decision as evidence and answers what that fill *cost*:
a filled order is charged the rate, an order the tape merely touched or
never reached is charged nothing, and the charge is flat per fill rather
than per unit — the queue depth is priced by feature 65 as a quantity, and
billing it again here would charge one fact twice.  It is what makes
`docs/alpha-engine-prd.md` §10's claim true: *"Going 0%-maker does not make
trading free. It converts fee cost into adverse-selection cost on passive
fills"* — a zero-maker venue whose passive orders fill still returns a
nonzero cost, because the maker's cost moved into the queue rather than
disappearing.  A document that omits the field is refused, because a cost
defaulted to zero silently is the floored simulator that feature exists to
prevent; a document that sets it to ``0.0`` is answered honestly.

Feature 65 layers onto that gate from the fill model's passive half:
*System models passive fill probability as exponential decay against queue
depth, which returns a fill fraction per rebalance.*  It is §6.2's
``passive.fill_probability_model: exp_decay_vs_queue_depth`` made concrete,
and :mod:`cost_model.fill_probability` holds it — the rebalance's view of
the queue as a value (:class:`~cost_model.fill_probability.QueueObservation`,
the depth ahead of the order, the order's size and the volume the level
traded), and the fraction that decays it
(:class:`~cost_model.fill_probability.FillProbability`).  The decay answers
the question feature 63's gate leaves open — a resting order that filled at
all filled *how much* — with ``exp(-queue_ahead / rebalance_volume)``,
multiplied by the volume bound ``min(1, volume / order_quantity)`` so the
fraction can never claim more of the order than the tape printed at its
price.  A document whose ``fill_probability_model`` names anything else is
refused, because the field names a model and this library carries one.

Feature 66 layers onto that identity from the fill model's aggressive
half: *System walks the recorded L2 book for an aggressive order rather
than crossing at the midpoint, which returns a realistic slippage
figure.*  It is §6.2's ``aggressive.walk_book: true`` made concrete, and
:mod:`cost_model.book_walk` holds it — the recorded ladder as a value
(:class:`~cost_model.book_walk.RecordedBook`), the crossing order as a
value (:class:`~cost_model.book_walk.AggressiveOrder`), and the walk that
consumes the ladder best-first to return the volume-weighted fill and the
slippage figure measured against the midpoint the naive model would have
filled at (:class:`~cost_model.book_walk.BookWalk`).  It refuses what the
tape did not record — an order beyond the recorded depth is refused, not
extrapolated, and a document whose ``walk_book`` is not ``true`` is
refused, because the only alternative behaviour is the midpoint crossing
the sentence rules out and this library does not carry it.

Feature 67 layers onto that identity: *System persists an empirical p50,
p95 and p99 latency distribution measured from shadow runs rather than an
assumed constant.*  It is the ``latency`` section of §6.2's document made
concrete — ``source: measured_from_shadow``, ``distribution:
empirical_p50_p95_p99`` — and it follows the same rule as the identity:
the distribution is measured from the tape and written down, never assumed.
:mod:`cost_model.latency` holds the distribution (the samples and the three
quantiles derived from them) and :mod:`cost_model.latency_store` persists
it, keyed by the ``(venue, version)`` identity feature 59 already persists
and the instant the latency was measured, so a cost model's latency is a
history that accumulates as shadow runs pile up rather than one assumed
number.  It, too, layers on the resolved identity rather than beside it.

Feature 69 closes the ring around all of the above: *System rejects a
second implementation of the fee schedule, so research evaluation and
live execution import one shared cost library.*  §6.2's rule — *"they
must be the same code, not two implementations of the same document"*
— is what every layer above kept structurally by living in this one
package, and :mod:`cost_model.fee_library` makes it enforceable: the
process's fee schedule is *claimed* once
(:func:`~cost_model.fee_library.install_fee_implementation`), the same
implementation claimed again is the one-shared-library outcome research
evaluation and live execution are supposed to produce, and a *different*
one offered afterwards is refused by name
(:class:`~cost_model.errors.DuplicateFeeImplementationError`) — both
modules in the message, so the divergent wiring is the error rather than
the ``β₄`` divergence it would have caused.  Identity is the owning
module with the factory's scan prefix stripped, so one source imported
twice (directly and through the factory's mangled name) is still one
implementation, never two.

Feature 62 layers onto feature 61's fee schedule: *System applies a
discount-token fee reduction when configured, which returns an effective
7.5 bps rate in place of 10 bps.*  It is §6.2's ``fees.discount_token:
BNB  # → 7.5 bps`` made concrete, and :mod:`cost_model.discount` holds it —
the token the document names and the fraction it takes off the rate
(:class:`~cost_model.discount.FeeDiscount`), and the reduced schedule that
fraction produces (:meth:`~cost_model.discount.FeeDiscount.reduce`).  It
changes one *input* of feature 61's charge rather than adding a charge of its
own: the reduced :class:`~cost_model.fees.FeeSchedule` goes through the very
:meth:`~cost_model.fees.FeeSchedule.apply` an undiscounted one goes through,
so the post-cost series is produced by the one subtraction there is and the
discount cannot drift from the fee it discounts (feature 69's promise, from
the discount side).  *"When configured"* is the condition and it is answered
rather than demanded — a document with no ``discount_token`` resolves to an
unconfigured discount whose effective rate is the schedule's own, because a
venue whose fees are paid in the quote currency has no token and that is not
a defect — while a token that is present but *names nothing* is refused,
because a typo in a signed Z0 artifact is not an absent field.  The reduction
is the shared library's constant rather than a document field (§6.2 names the
token and writes the arithmetic only as a comment), and it lands on both
sides, because `docs/alpha-engine-prd.md` §10 states one deduction on the
fee — *"0.1% maker/taker; 0.075% with BNB deduction"* — not a side-selective
one.

This package also *is* a component of the composed application: importing
it registers a builder with the application factory
(``app.module_loader.register``), so the module loader discovers it by
scanning the workspace members the root pyproject.toml declares.  No
central registry, router or app factory is edited to wire it in —
registration happens as an import side effect right here.

The registration lives in this module and deliberately not in a submodule:
``app.module_loader._import_package`` re-executes a package's
``__init__.py`` on every ``create_app()`` call, but a submodule already
cached in ``sys.modules`` under the loader's synthetic name is not
re-executed — so a ``@register`` in a submodule would fire on the first
composition of a process and silently drop out of every later one.

PyYAML is a declared dependency of this member but its import is deferred
to first use (:func:`cost_model.config.require_yaml`), so the factory's
workspace scan — which imports this module to fire the registration below
— does not need a YAML parser installed.  That keeps the member
import-safe in every environment the workspace contract promises one will
be: the factory scan, a test sandbox, the deterministic replay path.
"""

from __future__ import annotations

from app.module_loader import register

from .book_walk import (
    AGGRESSIVE_KEY,
    BUY,
    FILL_MODEL_KEY,
    SELL,
    WALK_BOOK_KEY,
    AggressiveFillModel,
    AggressiveOrder,
    BookLevel,
    BookWalk,
    RecordedBook,
    resolve_aggressive_fill_model,
    walk_recorded_book,
)
from .config import (
    COST_MODEL_KEY,
    COST_MODEL_PATH_ENV,
    DEFAULT_COST_MODEL_PATH,
    CostModelConfig,
    load_cost_model,
    read_cost_model_document,
    require_yaml,
)
from .discount import (
    DEFAULT_DISCOUNT_FRACTION,
    DISCOUNT_TOKEN_KEY,
    FeeDiscount,
    discount_fee_schedule,
    resolve_fee_discount,
)
from .errors import (
    CostModelConfigError,
    CostModelError,
    CostModelFillError,
    CostModelStoreError,
    DuplicateFeeImplementationError,
)
from .fee_library import (
    SHARED_FEE_IMPLEMENTATION,
    FeeImplementation,
    install_fee_implementation,
    installed_fee_implementation,
)
from .fees import (
    FEES_KEY,
    MAKER,
    MAKER_BPS_KEY,
    TAKER,
    TAKER_BPS_KEY,
    FeeSchedule,
    PostCostReturn,
    apply_fee,
    resolve_fee_schedule,
)
from .identity import (
    COST_MODEL_HASH_LENGTH,
    canonical_cost_model,
    cost_model_digest,
    normalize_cost_model_hash,
)
from .fill_probability import (
    EXP_DECAY_MODEL,
    FILL_PROBABILITY_KEY,
    HALF_LIFE_REBALANCES,
    FillProbability,
    FillProbabilityModel,
    QueueObservation,
    passive_fill_fraction,
    resolve_fill_probability_model,
)
from .latency import (
    DEFAULT_QUANTILES,
    QUANTILE_METHOD,
    EmpiricalLatencyDistribution,
    quantile,
)
from .latency_store import (
    LATENCY_TABLE,
    load_latency_distributions,
    load_latest_latency_distribution,
    persist_latency_distribution,
)
from .passive_fill import (
    PASSIVE_KEY,
    REQUIRE_TRADE_THROUGH_KEY,
    PassiveFillDecision,
    PassiveFillModel,
    PassiveOrder,
    RecordedTape,
    Trade,
    fill_passive_order,
    resolve_passive_fill_model,
)
from .queue_penalty import (
    QUEUE_POSITION_PENALTY_KEY,
    QueuePenalty,
    QueuePositionPenaltyModel,
    charge_queue_position_penalty,
    resolve_queue_position_penalty_model,
)
from .service import CostModelService, build_cost_model_service
from .store import (
    COST_MODEL_HASH_COLUMN,
    COST_MODEL_TABLE,
    DATABASE_URL_ENV,
    load_persisted_cost_model,
    persist_cost_model,
)

__all__ = [
    "AGGRESSIVE_KEY",
    "BUY",
    "COMPONENT_NAME",
    "COST_MODEL_HASH_COLUMN",
    "COST_MODEL_HASH_LENGTH",
    "COST_MODEL_KEY",
    "COST_MODEL_PATH_ENV",
    "COST_MODEL_TABLE",
    "DATABASE_URL_ENV",
    "DEFAULT_COST_MODEL_PATH",
    "DEFAULT_DISCOUNT_FRACTION",
    "DEFAULT_QUANTILES",
    "DISCOUNT_TOKEN_KEY",
    "EXP_DECAY_MODEL",
    "FEES_KEY",
    "FILL_MODEL_KEY",
    "FILL_PROBABILITY_KEY",
    "HALF_LIFE_REBALANCES",
    "LATENCY_TABLE",
    "MAKER",
    "MAKER_BPS_KEY",
    "PASSIVE_KEY",
    "QUANTILE_METHOD",
    "QUEUE_POSITION_PENALTY_KEY",
    "REQUIRE_TRADE_THROUGH_KEY",
    "SELL",
    "SHARED_FEE_IMPLEMENTATION",
    "TAKER",
    "TAKER_BPS_KEY",
    "WALK_BOOK_KEY",
    "AggressiveFillModel",
    "AggressiveOrder",
    "BookLevel",
    "BookWalk",
    "CostModelConfig",
    "CostModelConfigError",
    "CostModelError",
    "CostModelFillError",
    "CostModelService",
    "CostModelStoreError",
    "DuplicateFeeImplementationError",
    "EmpiricalLatencyDistribution",
    "FeeDiscount",
    "FeeImplementation",
    "FeeSchedule",
    "FillProbability",
    "FillProbabilityModel",
    "PassiveFillDecision",
    "PassiveFillModel",
    "PassiveOrder",
    "PostCostReturn",
    "QueueObservation",
    "QueuePenalty",
    "QueuePositionPenaltyModel",
    "RecordedBook",
    "RecordedTape",
    "Trade",
    "apply_fee",
    "build_cost_model_service",
    "canonical_cost_model",
    "charge_queue_position_penalty",
    "cost_model_digest",
    "discount_fee_schedule",
    "fill_passive_order",
    "install_fee_implementation",
    "installed_fee_implementation",
    "load_cost_model",
    "load_latency_distributions",
    "load_latest_latency_distribution",
    "load_persisted_cost_model",
    "normalize_cost_model_hash",
    "passive_fill_fraction",
    "persist_cost_model",
    "persist_latency_distribution",
    "quantile",
    "read_cost_model_document",
    "require_yaml",
    "resolve_aggressive_fill_model",
    "resolve_fee_discount",
    "resolve_fee_schedule",
    "resolve_fill_probability_model",
    "resolve_passive_fill_model",
    "resolve_queue_position_penalty_model",
    "walk_recorded_book",
]

__version__ = "0.1.0"

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the cost model service
#: at, and the name the seat in the app namespace
#: (``src/app/modules/cost-model``) asks for.  Spelled once here so the
#: member, the factory's registry and the seat cannot drift apart.
COMPONENT_NAME = "cost-model"


@register(COMPONENT_NAME)
def build_cost_model() -> CostModelService:
    """Component builder: the cost model service bound to the environment.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its configuration from the environment at build time, so a
    composed application always carries a service for the document and the
    store the process is actually pointed at
    (``NULLIUS_COST_MODEL_PATH`` and ``DATABASE_URL``, the latter set per
    test by the shared fixtures).

    Construction performs no I/O: the document is read on the first
    ``resolved()``/``load()`` call and the store is opened on the first
    persist, so composing the application never touches a file or a
    database.  The builder names
    :func:`~cost_model.service.build_cost_model_service` rather than
    repeating its body, so the registered builder and the importable symbol
    are one thing.
    """
    return build_cost_model_service()
