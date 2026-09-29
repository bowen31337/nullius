"""The ledger member: append-only accounting for every evaluation.

app_spec.xml, "Trial Ledger Append-Only Accounting", lands on this
workspace member (``packages/ledger``, import name ``ledger``).
docs/nullius-tech-architecture.md §8 fixes its subject: the trial ledger
is *"the honest ``K`` counter"* — an append-only write-ahead log, never a
mutable table — and the category's features split that one sentence into
layers.  Feature 86 is the foundation they all stand on: *System
persists one trial_ledger row per evaluation under a monotonically
increasing sequence number.*  The append seam
(:class:`ledger.store.TrialLedger.append`) and the never-reused sequence
are this member's contribution; the features that follow add their own
stamps and derivations on top of it — the
epoch accounting of 88 (:mod:`ledger.epoch`: the sequestered epoch a
trial charged, required at the write and refused when absent — the
epoch is a depleting resource counted in ``epoch_ledger``, and a charge
that cannot name its holdout is a charge no audit can place), the
charge semantics of 89-90, the outcome of
91 (:mod:`ledger.outcome`: one of 'ok', 'timeout', 'error',
'tripwire_fail' persisted on every appended row, refused when absent or
misspelled), the charge unit of 89
(:mod:`ledger.units`: a positive finite real defaulting to §8's ``1.0``,
so an ordinary evaluation costs one unit and a cross-validated one whose
folds each compare a fit against the same forward returns costs more),
the opaque budget directive of 90
(:mod:`ledger.budget`: a genuine bool supplied by the caller, never
derived), the provenance triple of 87
(:mod:`ledger.provenance`: ``evaluator_hash``, ``snapshot_hash`` and
``cost_model_hash`` on every appended row — the frozen evaluator that
scored the trial, the sealed snapshot it was scored against and the
cost model that priced it, each the sha256 hexdigest its owning
feature computed, required at the write and refused when absent or not
64 hex characters, because a charge that cannot name its provenance is
a charge no replay can reproduce), the enforced immutability of 92, and the two derived views of
93-96 — §8's ``K_effective`` per epoch (feature 93, counting the
budget-charging rows of this member's own ``trial_ledger``) and the
epoch-usage counts (feature 96, reading ``epoch_ledger``, the table the
versioned migration and the promotion plugin own).  Features 93-95 sit
over the one table this member creates, never a second table beside it;
feature 96 is the exception the spec's own wording names, because the
sequestration a promotion decision spends is a different resource from
the statistical budget a trial charges, and it is counted in a table of
its own.

Importing this package registers three components with the application
factory.  ``"ledger"`` is the :class:`~ledger.store.TrialLedger` bound
to the database ``DATABASE_URL`` names (or nothing, when it names
nothing — an unconfigured store is a discoverable state, and the
composed application simply carries no ledger component).
``"ledger-debit"`` is feature 95's POST /ledger/debit endpoint
(:class:`~ledger.debit.DebitEndpoint`) over that same store — the
idempotent charge keyed by ``node_id`` that §14's spot-reclaimed eval
workers retry — and ``"ledger-k-effective"`` is feature 94's
GET /ledger/k-effective endpoint
(:class:`~ledger.keffective_route.KEffectiveEndpoint`) over it, the read
that hands §10.3's deflation term its ``K_effective`` per epoch.  All
three are resolved from the same environment, so the two routes and the
store they speak to can never point at different databases.  The
registrations are a deliberate import side effect: this is how a member
announces itself to the factory without the factory knowing its name in
advance.

**The ``@register`` decorator lives here, in this ``__init__``, and in
no submodule.**  The factory's scan re-executes a package's ``__init__``
on every :func:`~app.module_loader.create_app` call, but a submodule
already cached in ``sys.modules`` is not re-executed; a ``@register`` in
a submodule would therefore fire on the first composition of a process
and silently drop out of every later one.  Registration lives on the
import path the scan always runs — the same invariant every other
member's registration states.

The public API is small on purpose, and each piece is the seam a later
feature composes rather than a second spelling of something the store
already says:

* :class:`~ledger.record.TrialLedgerRecord` — one row as a value: the
  sequence the table assigned, the stamp, the two identities, the
  outcome, the budget directive, the charge unit, the epoch and the
  provenance triple.
* :class:`~ledger.store.TrialLedger` — the append, the idempotent
  debit, the ordered read, the count; bound to one database URL.
* :class:`~ledger.debit.DebitEndpoint` with :class:`~ledger.debit.
  DebitRequest` and :class:`~ledger.debit.DebitResponse` — feature 95's
  route: POST /ledger/debit, appending one trial row idempotently keyed
  by ``node_id`` and returning the prior sequence on a retry.
* :class:`~ledger.keffective_route.KEffectiveEndpoint` with
  :class:`~ledger.keffective_route.KEffectiveResponse` — feature 94's
  route: GET /ledger/k-effective, returning §8's ``K_effective`` per
  epoch as the deflation input, drawn from feature 93's derivation
  rather than from a raw row count.
* :data:`~ledger.outcome.OUTCOMES` — feature 91's vocabulary: the four
  outcomes a trial can end in, the one closed set every appended row's
  ``outcome`` is drawn from.
* :func:`~ledger.budget.validated_charges_budget` — feature 90's
  directive: the genuine-bool check every appended row's
  ``charges_budget`` is validated through, supplied by the caller and
  never derived.
* :data:`~ledger.units.DEFAULT_CHARGE_UNITS` with
  :func:`~ledger.units.validated_charge_units` — feature 89's unit: the
  positive-finite-real check every appended row's ``charge_units`` is
  validated through, and the ``1.0`` §8's DDL declares as the column's
  default, so an ordinary evaluation costs one unit and a cross-validated
  one states its folds' count.
* :func:`~ledger.epoch.validated_epoch_id` — feature 88's stamp: the
  charged-epoch check every appended row's ``epoch_id`` is validated
  through, required at the write seams (an absent epoch is refused
  before the ledger is touched) and ``None``-tolerant on the read,
  where a row that predates the stamp honestly names no epoch.
* :func:`~ledger.provenance.validated_provenance_hash` with
  :data:`~ledger.provenance.PROVENANCE_COLUMNS` — feature 87's stamp:
  the hexdigest check every appended row's ``evaluator_hash``,
  ``snapshot_hash`` and ``cost_model_hash`` are validated through,
  required at the write seams (an absent or malformed term is refused
  before the ledger is touched) and ``None``-tolerant on the read,
  where a row that predates the triple honestly names no provenance.
* :class:`~ledger.keffective.KEffective` with
  :func:`~ledger.keffective.derive_k_effective` and
  :data:`~ledger.keffective.UNNAMED_EPOCH` — feature 93's derivation:
  the budget-charging trial count per epoch, the number null nodes
  never inflate.  Read off the store as
  :meth:`~ledger.store.TrialLedger.k_effective`.
* :class:`~ledger.epochusage.EpochUsage` with
  :func:`~ledger.epochusage.derive_epoch_usage` — feature 96's
  derivation: the promotion decisions each sequestered epoch has
  served, the figure §15 retires epochs at three of.  Read off the
  store as :meth:`~ledger.store.TrialLedger.epoch_usage`, which reads
  the ``epoch_ledger`` table (feature 105) rather than this member's
  own — the two derived views of §8 are two reads over two tables.
* :class:`~ledger.record.utc_now` — the append's default clock.
* The error taxonomy of :mod:`ledger.errors`, one base class wide.
"""

from __future__ import annotations

from typing import Optional

from app.module_loader import register

from .budget import validated_charges_budget
from .debit import DEBIT_ROUTE, DebitEndpoint, DebitRequest, DebitResponse
from .epoch import validated_epoch_id
from .epochusage import EpochUsage, derive_epoch_usage
from .errors import (
    TrialImmutableError,
    TrialLedgerError,
    TrialRecordError,
    TrialStoreError,
)
from .keffective import KEffective, UNNAMED_EPOCH, derive_k_effective
from .keffective_route import (
    KEFFECTIVE_ROUTE,
    KEffectiveEndpoint,
    KEffectiveResponse,
)
from .outcome import OUTCOMES
from .provenance import PROVENANCE_COLUMNS, validated_provenance_hash
from .record import TrialLedgerRecord, utc_now
from .store import (
    DATABASE_URL_ENV,
    EPOCH_LEDGER_TABLE,
    TRIAL_LEDGER_TABLE,
    TrialLedger,
)
from .units import DEFAULT_CHARGE_UNITS, validated_charge_units

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DEFAULT_CHARGE_UNITS",
    "DEBIT_COMPONENT_NAME",
    "DEBIT_ROUTE",
    "EPOCH_LEDGER_TABLE",
    "KEFFECTIVE_COMPONENT_NAME",
    "KEFFECTIVE_ROUTE",
    "DebitEndpoint",
    "DebitRequest",
    "DebitResponse",
    "EpochUsage",
    "KEffective",
    "KEffectiveEndpoint",
    "KEffectiveResponse",
    "OUTCOMES",
    "PROVENANCE_COLUMNS",
    "TRIAL_LEDGER_TABLE",
    "TrialImmutableError",
    "TrialLedger",
    "TrialLedgerError",
    "TrialLedgerRecord",
    "TrialRecordError",
    "TrialStoreError",
    "UNNAMED_EPOCH",
    "build_ledger_debit",
    "build_ledger_k_effective",
    "build_trial_ledger",
    "derive_epoch_usage",
    "derive_k_effective",
    "utc_now",
    "validated_charge_units",
    "validated_charges_budget",
    "validated_epoch_id",
    "validated_provenance_hash",
]

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the ledger at, and the
#: name a caller reads it by (``create_app().get("ledger")``).  Spelled
#: once here so the member and the factory's registry cannot drift apart.
COMPONENT_NAME = "ledger"

#: The component name feature 95's endpoint registers under — the
#: hyphenated satellite spelling the feature-store member's derived
#: components established (``feature-materialiser``, ``regime-metrics``,
#: …), so a composed deployment reaches the route as
#: ``app.get("ledger-debit")``.
DEBIT_COMPONENT_NAME = "ledger-debit"

#: The component name feature 94's endpoint registers under — the same
#: hyphenated satellite spelling, so a composed deployment reaches the
#: route's read as ``app.get("ledger-k-effective")``.
KEFFECTIVE_COMPONENT_NAME = "ledger-k-effective"


@register(KEFFECTIVE_COMPONENT_NAME)
def build_ledger_k_effective() -> Optional[KEffectiveEndpoint]:
    """Component builder: the GET /ledger/k-effective endpoint (feature 94).

    Takes no arguments — the factory's registration protocol — and
    resolves the store from the environment exactly as
    :func:`build_trial_ledger` does, so the route reads the database the
    process is actually pointed at and can never serve a deflation input
    drawn from a different ledger than the composed ``"ledger"``
    component names.  Returns ``None`` when no ``DATABASE_URL`` is set,
    the same stance the store's own builder takes: an unconfigured store
    contributes no route either, while a deployment whose scoring process
    must deflate by ``K_effective`` is the caller that must not find
    itself composing in that state.
    """
    ledger = TrialLedger.resolve()
    return None if ledger is None else KEffectiveEndpoint(ledger)


@register(DEBIT_COMPONENT_NAME)
def build_ledger_debit() -> Optional[DebitEndpoint]:
    """Component builder: the POST /ledger/debit endpoint (feature 95).

    Takes no arguments — the factory's registration protocol — and
    resolves the store from the environment exactly as
    :func:`build_trial_ledger` does, so the endpoint composes over the
    database the process is actually pointed at and can never debit a
    different ledger than the composed ``"ledger"`` component names.
    Returns ``None`` when no ``DATABASE_URL`` is set, the same stance
    the store's own builder takes: an unconfigured store contributes no
    endpoint either, while the evaluator whose step 11 must debit is the
    caller that must not find itself composing in that state.
    """
    ledger = TrialLedger.resolve()
    return None if ledger is None else DebitEndpoint(ledger)


@register(COMPONENT_NAME)
def build_trial_ledger() -> Optional[TrialLedger]:
    """Component builder: the ledger bound to the configured database.

    Takes no arguments — that is the factory's registration protocol —
    and resolves its configuration from the environment at build time, so
    a composed application carries a ledger for the database the process
    is actually pointed at (``DATABASE_URL``, set per test by the shared
    fixtures).  Construction performs no I/O (the URL is translated and
    the schema created on first use), so composing the application never
    touches the database.

    Returns ``None`` when no ``DATABASE_URL`` is set: an unconfigured
    relational store is a supported state that contributes no component,
    the same stance the snapshot member's manifest store takes toward an
    absent store — while the pipeline that needs to debit a trial is the
    caller that must not find itself composing in that state.
    """
    return TrialLedger.resolve()
