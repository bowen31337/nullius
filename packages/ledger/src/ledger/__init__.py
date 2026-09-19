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
91, the enforced immutability of 92, the ``K_effective`` family of
93-96 — each as a layer over the one table this member creates, never a
second table beside it.

Importing this package registers one component with the application
factory: ``"ledger"``, the :class:`~ledger.store.TrialLedger` bound to
the database ``DATABASE_URL`` names (or nothing, when it names nothing —
an unconfigured store is a discoverable state, and the composed
application simply carries no ledger component).  The registration is a
deliberate import side effect: this is how a member announces itself to
the factory without the factory knowing its name in advance.

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
  sequence the table assigned, the stamp, the two identities.
* :class:`~ledger.store.TrialLedger` — the append, the ordered read, the
  count; bound to one database URL.
* :class:`~ledger.record.utc_now` — the append's default clock.
* The error taxonomy of :mod:`ledger.errors`, one base class wide.
"""

from __future__ import annotations

from typing import Optional

from app.module_loader import register

from .errors import TrialLedgerError, TrialRecordError, TrialStoreError
from .record import TrialLedgerRecord, utc_now
from .store import DATABASE_URL_ENV, TRIAL_LEDGER_TABLE, TrialLedger

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "TRIAL_LEDGER_TABLE",
    "TrialLedger",
    "TrialLedgerError",
    "TrialLedgerRecord",
    "TrialRecordError",
    "TrialStoreError",
    "build_trial_ledger",
    "utc_now",
]

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the ledger at, and the
#: name the seat in the app namespace (``src/app/modules/ledger``) asks
#: for.  Spelled once here so the member, the factory's registry and the
#: seat cannot drift apart.
COMPONENT_NAME = "ledger"


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
