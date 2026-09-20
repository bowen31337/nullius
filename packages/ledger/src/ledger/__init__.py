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
stamps and derivations on top of it — the provenance triple of 87, the
epoch accounting of 88, the charge semantics of 89-90, the outcome of
91 (:mod:`ledger.outcome`: one of 'ok', 'timeout', 'error',
'tripwire_fail' persisted on every appended row, refused when absent or
misspelled), the opaque budget directive of 90
(:mod:`ledger.budget`: a genuine bool supplied by the caller, never
derived), the enforced immutability of 92, the ``K_effective`` family
of 93-96 — each as a layer over the one table this member creates, never
a second table beside it.

Importing this package registers two components with the application
factory.  ``"ledger"`` is the :class:`~ledger.store.TrialLedger` bound
to the database ``DATABASE_URL`` names (or nothing, when it names
nothing — an unconfigured store is a discoverable state, and the
composed application simply carries no ledger component).
``"ledger-debit"`` is feature 95's POST /ledger/debit endpoint
(:class:`~ledger.debit.DebitEndpoint`) over that same store — the
idempotent charge keyed by ``node_id`` that §14's spot-reclaimed eval
workers retry — resolved from the same environment so the endpoint and
the store it debits can never point at different databases.  The
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
  outcome.
* :class:`~ledger.store.TrialLedger` — the append, the idempotent
  debit, the ordered read, the count; bound to one database URL.
* :class:`~ledger.debit.DebitEndpoint` with :class:`~ledger.debit.
  DebitRequest` and :class:`~ledger.debit.DebitResponse` — feature 95's
  route: POST /ledger/debit, appending one trial row idempotently keyed
  by ``node_id`` and returning the prior sequence on a retry.
* :data:`~ledger.outcome.OUTCOMES` — feature 91's vocabulary: the four
  outcomes a trial can end in, the one closed set every appended row's
  ``outcome`` is drawn from.
* :func:`~ledger.budget.validated_charges_budget` — feature 90's
  directive: the genuine-bool check every appended row's
  ``charges_budget`` is validated through, supplied by the caller and
  never derived.
* :class:`~ledger.record.utc_now` — the append's default clock.
* The error taxonomy of :mod:`ledger.errors`, one base class wide.
"""

from __future__ import annotations

from typing import Optional

from app.module_loader import register

from .budget import validated_charges_budget
from .debit import DEBIT_ROUTE, DebitEndpoint, DebitRequest, DebitResponse
from .errors import (
    TrialImmutableError,
    TrialLedgerError,
    TrialRecordError,
    TrialStoreError,
)
from .outcome import OUTCOMES
from .record import TrialLedgerRecord, utc_now
from .store import DATABASE_URL_ENV, TRIAL_LEDGER_TABLE, TrialLedger

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DEBIT_COMPONENT_NAME",
    "DEBIT_ROUTE",
    "DebitEndpoint",
    "DebitRequest",
    "DebitResponse",
    "OUTCOMES",
    "TRIAL_LEDGER_TABLE",
    "TrialImmutableError",
    "TrialLedger",
    "TrialLedgerError",
    "TrialLedgerRecord",
    "TrialRecordError",
    "TrialStoreError",
    "build_ledger_debit",
    "build_trial_ledger",
    "utc_now",
    "validated_charges_budget",
]

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the ledger at, and the
#: name the seat in the app namespace (``src/app/modules/ledger``) asks
#: for.  Spelled once here so the member, the factory's registry and the
#: seat cannot drift apart.
COMPONENT_NAME = "ledger"

#: The component name feature 95's endpoint registers under — the
#: hyphenated satellite spelling the feature-store member's derived
#: components established (``feature-materialiser``, ``regime-metrics``,
#: …), so a composed deployment reaches the route as
#: ``app.get("ledger-debit")``.
DEBIT_COMPONENT_NAME = "ledger-debit"


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
