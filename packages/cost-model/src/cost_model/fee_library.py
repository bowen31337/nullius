"""Feature 69's guard: one implementation of the fee schedule per process.

app_spec.xml, "Cost Model & Fill Simulation", feature 69: *System rejects
a second implementation of the fee schedule, so research evaluation and
live execution import one shared cost library.*  The sentence's two halves
are a mechanism and a consequence, and the consequence is the point:
`docs/nullius-tech-architecture.md` §6.2 does not merely prefer that the
evaluator and the live execution engine price the same fee — *"Shared
library used by both the evaluator and the live execution engine.
Divergence between these two is exactly the quantity ``β₄`` penalizes, so
they must be the same code, not two implementations of the same
document"* — it makes the divergence a measured cost (§6.3's ``β₄`` term,
the live/sim IC gap) and then forbids it.  Features 61-67 kept that
promise *structurally*: every fee and fill behaviour lives in this one
package, resolved from the one cached parse, so the second
implementation had nowhere to live.  This module keeps it *enforceably*:
the promise gains a seam a process can be checked against, and a second
implementation offered at that seam is refused by name, both modules in
the message.

**Why a seam, when the package is already shared.**  Structure forbids
the second implementation from living *here*; it cannot forbid a
deployment from *wiring* one.  The evaluator's ``apply_costs`` step
(feature 79) reaches the charge through an injected cost schedule, the
live engine through its own wiring, and neither the evaluator nor this
package can see what the other was handed — a deployment that pointed
research evaluation at this library and live execution at a hand-rolled
twin would diverge silently, exactly the ``β₄`` failure §6.2's sentence
exists to prevent.  So the process's fee schedule is *claimed*, once, at
the door both consumers walk through — the composed service
(:meth:`cost_model.service.CostModelService.fee_implementation`) or this
module directly — and a claim that offers a *different* implementation
is the loud failure the silent wiring would otherwise have been.

**What an implementation is.**  :class:`FeeImplementation` is the three
things a consumer needs to price a fill — the schedule type it resolves
(:attr:`~FeeImplementation.schedule_type`), the charge it applies
(:attr:`~FeeImplementation.apply`) and the resolver that reads §6.2's
document (:attr:`~FeeImplementation.resolve`) — together with the module
that owns them (:attr:`~FeeImplementation.module`).  The module is the
identity: one implementation is one module's code, so two consumers that
independently construct the value out of ``cost_model.fees``' own symbols
claim the *same* implementation (that idempotence is the "one shared
library" outcome, not a near miss), while any value from any other
module is a second implementation no matter how faithfully it copies the
arithmetic — the copy is the divergence, because it can drift.

**One source imported twice is one implementation.**  The application
factory imports scanned packages under mangled names
(``app.module_loader._import_package``: ``_nullius_scanned_<name>``), so
one process can hold two module *objects* for this one source — the
directly-imported ``cost_model.fees`` and the scanned twin — with
distinct function objects for the very same code.  Identity by object
would call the scanned twin a second implementation; identity by module
name, with the loader's prefix stripped (:func:`_canonical_module_name`),
calls it what it is: the same source, claimed again.  The claim guards
*code*, and the code is the file, not the object identity it happened to
import under.

**The claim guards code, not data.**  A process pricing two venues holds
two :class:`~cost_model.fees.FeeSchedule` *values* out of the one
implementation, the way §6.2's own keying (feature 59: version with
venue) already anticipates, and that is not divergence — the claim counts
implementations, not schedules, because two schedules from one module
cannot disagree about the arithmetic while two modules always can.

**Why the state lives here and not in :mod:`cost_model.fees`.**  The fee
module's own contract is that it holds no state — the schedule arrives
as a value, the series as values, nothing persisted — and a process-wide
claim would break it.  The claim is not part of any one schedule's
pricing; it is a property of the *process* that prices, so it lives in
its own module beside the stateless one it guards, the same separation
:mod:`cost_model.store` makes for persistence.

**What this deliberately does not do.**  It hashes no code, scans no
imports and inspects no consumer: a general plugin registry would be a
second thing to diverge.  It is one seam with one refusal
(:class:`~cost_model.errors.DuplicateFeeImplementationError`), first
claim wins, and the error names the incumbent and the newcomer so the
operator sees which wiring has to go.  It also does not make the library
*un*-replaceable: a deployment that claims one different implementation
and wires *both* consumers to it has one implementation and no
divergence.  What it refuses is the second one — the state where
research evaluation and live execution would each import their own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .errors import DuplicateFeeImplementationError
from .fees import FeeSchedule, PostCostReturn, apply_fee, resolve_fee_schedule

__all__ = [
    "SHARED_FEE_IMPLEMENTATION",
    "FeeImplementation",
    "install_fee_implementation",
    "installed_fee_implementation",
]

#: The prefix the application factory gives scanned packages
#: (``app.module_loader._import_package`` names a package
#: ``_nullius_scanned_<dir>``).  Stripped before a module name becomes an
#: implementation's identity, so the factory's own import of this source is
#: the same implementation as a direct one — see the module docstring's
#: *"one source imported twice"*.
_SCANNED_MODULE_PREFIX = "_nullius_scanned_"


def _canonical_module_name(name: str) -> str:
    """Return ``name`` as an implementation's identity: whitespace-stripped, loader prefix stripped.

    The only transformation an implementation's origin undergoes, spelled
    once so the claim, the comparison and the error message cannot disagree
    about what names an implementation.  Everything else is preserved
    verbatim — ``cost_model.fees`` and ``cost_model.fee_library`` are
    different modules and stay different — because the prefix exists to be
    stripped and nothing else about a module's spelling is ever a mistake.
    """
    return name.strip().removeprefix(_SCANNED_MODULE_PREFIX)


@dataclass(frozen=True, eq=False)
class FeeImplementation:
    """One implementation of the fee schedule: its owner, type, charge and resolver.

    The value a process claims once (feature 69).  The three callables are
    what a consumer prices through — resolve the schedule out of §6.2's
    document, apply the side's rate to a return — and the module is who
    owns them.  Equality is the module alone (see :meth:`__eq__`): the
    callables are carried for *use*, not for identity, because the same
    source imported under two names holds two sets of function objects for
    one implementation, and a registry keyed on object identity would
    reject its own library's second import — the opposite of the feature's
    promise.

    Attributes:
        module: The dotted name of the module that owns the
            implementation, with the factory's scan prefix stripped (see
            :func:`_canonical_module_name`).  A non-blank string; this is
            the implementation's identity.
        schedule_type: The type the resolver returns — for the shared
            library, :class:`~cost_model.fees.FeeSchedule`.  Carried so a
            consumer that needs the type (an ``isinstance`` audit, a
            repr) reaches it through the claim rather than a second
            import.
        apply: The per-element charge — for the shared library,
            :func:`~cost_model.fees.apply_fee`.
        resolve: The document reader — for the shared library,
            :func:`~cost_model.fees.resolve_fee_schedule`.
    """

    module: str
    schedule_type: type
    apply: Callable[..., PostCostReturn]
    resolve: Callable[..., FeeSchedule]

    def __post_init__(self) -> None:
        # eq=False above: equality is the module (see __eq__), spelled here
        # so the fields the claim compares and the fields it merely carries
        # are distinguished at the value rather than by convention.
        if not isinstance(self.module, str) or not _canonical_module_name(self.module):
            raise DuplicateFeeImplementationError(
                f"a fee implementation names the module that owns it, got "
                f"{type(self.module).__name__} ({self.module!r}): a blank or "
                f"non-string module implements nothing, and a value that "
                f"implements nothing cannot claim a process's fee schedule"
            )
        if not isinstance(self.schedule_type, type):
            raise DuplicateFeeImplementationError(
                f"the fee implementation of {self.module!r} resolves no "
                f"schedule type, got {type(self.schedule_type).__name__} "
                f"({self.schedule_type!r}): a consumer that cannot construct "
                f"the schedule it charges through is not an implementation"
            )
        if not callable(self.apply) or not callable(self.resolve):
            broken = "apply" if not callable(self.apply) else "resolve"
            value = self.apply if broken == "apply" else self.resolve
            raise DuplicateFeeImplementationError(
                f"the fee implementation of {self.module!r} carries no "
                f"callable {broken}, got {type(value).__name__} ({value!r}): "
                f"the charge and the resolver are the implementation, and a "
                f"value missing either one prices nothing"
            )
        object.__setattr__(self, "module", _canonical_module_name(self.module))

    def __eq__(self, other: object) -> bool:
        """One implementation is one owning module — the callables are use, not identity.

        ``cost_model.fees`` claimed twice — by research evaluation, by live
        execution, once directly and once through the factory's mangled
        scan name — is the same implementation each time, which is what
        makes the idempotent re-claim of
        :func:`install_fee_implementation` the feature's *outcome* rather
        than a tolerated edge.  Any other module is a second
        implementation however similar its code, because similarity is not
        the invariant — drift-ability is, and only one module can own the
        code both consumers run.
        """
        if not isinstance(other, FeeImplementation):
            return NotImplemented
        return self.module == other.module

    def __hash__(self) -> int:
        # Consistent with __eq__: the identity is the module, so the hash
        # is the module's — the value can sit in a set or a dict key
        # alongside its own re-claim and collapse to one entry.
        return hash(self.module)

    @property
    def identity(self) -> str:
        """The implementation's identity spelled once: the owning module.

        What the claim compares, what the refusal names, and what a log
        line records — one string for all three, so they cannot drift the
        way two spellings of "which code priced this" inevitably would.
        """
        return self.module

    def summary(self) -> dict[str, object]:
        """The implementation as a persistable mapping: the owner and its three parts.

        The shape a caller logs beside a score's cost provenance: which
        module implemented the fee schedule this process charges through,
        and the qualified names of the type, the charge and the resolver
        it offers.  A view over the value, rebuilt on every call, so it
        can never be a stale copy of a frozen one.
        """
        return {
            "module": self.module,
            "schedule_type": self.schedule_type.__qualname__,
            "apply": getattr(self.apply, "__qualname__", repr(self.apply)),
            "resolve": getattr(self.resolve, "__qualname__", repr(self.resolve)),
        }


#: The shared cost library's own implementation — the one value §6.2's
#: sentence protects.  Built from :mod:`cost_model.fees`' own symbols, with
#: the module derived from the charge function's origin rather than
#: hard-coded, so this constant cannot claim an owner its callables do not
#: actually live in.  Under the factory's scan the twin module's name
#: canonicalizes to the same identity (see :func:`_canonical_module_name`),
#: which is the whole point: every import path of this source is one
#: implementation.
SHARED_FEE_IMPLEMENTATION = FeeImplementation(
    module=_canonical_module_name(apply_fee.__module__),
    schedule_type=FeeSchedule,
    apply=apply_fee,
    resolve=resolve_fee_schedule,
)

#: The process's claim: the one fee implementation this process prices
#: through, or ``None`` until something claims it.  Module state on
#: purpose (see the module docstring's *"why the state lives here"*): the
#: claim is a property of the process, not of any schedule it resolves.
_installed: FeeImplementation | None = None


def install_fee_implementation(
    candidate: FeeImplementation | None = None,
) -> FeeImplementation:
    """Claim the process's fee schedule; refuse a second, different implementation.

    The feature's mechanism.  The first claim wins and stays: a later
    claim of the *same* implementation — the same owning module, however
    the value was constructed or imported — returns the installed value
    (idempotence, and the "one shared library" outcome: research
    evaluation and live execution each claim, and both hold one
    implementation).  A later claim of a *different* implementation raises
    :class:`~cost_model.errors.DuplicateFeeImplementationError` naming the
    incumbent and the newcomer, and the registry keeps the incumbent —
    the refusal changes nothing about what already prices.

    ``candidate`` ``None`` claims the shared library itself
    (:data:`SHARED_FEE_IMPLEMENTATION`), which is what the composed
    service's
    :meth:`~cost_model.service.CostModelService.fee_implementation`
    does: a consumer that reaches the fee through the application is
    claiming this package's implementation, and if the process has
    already been claimed by some other module's, that claim is the
    divergence to surface — not a fallback to serve.
    """
    global _installed
    impl = SHARED_FEE_IMPLEMENTATION if candidate is None else candidate
    if _installed is None:
        _installed = impl
        return impl
    if _installed == impl:
        return _installed
    raise DuplicateFeeImplementationError(
        f"the fee schedule is already implemented by "
        f"{_installed.identity!r}; refusing a second implementation "
        f"{impl.identity!r}: the evaluator and the live execution engine "
        f"must be the same code, not two implementations of the same "
        f"document (docs/nullius-tech-architecture.md §6.2), so research "
        f"evaluation and live execution import one shared cost library"
    )


def installed_fee_implementation() -> FeeImplementation | None:
    """The implementation the process has claimed, or ``None`` when unclaimed.

    The non-claiming peek: it installs nothing, so a wiring tool can ask
    what already prices before claiming its own, and the member's own
    tests can assert the registry's state rather than infer it.  ``None``
    is a discoverable state — nothing has claimed the fee schedule yet —
    the same stance the factory takes toward an absent component, and not
    an error: the claim happens on first use, not at import.
    """
    return _installed


def _reset_fee_implementation() -> None:
    """Clear the process's claim.  A test seam, nothing else.

    The claim is process-global by design, and a test suite is one
    process — without this, one test's claim (or its deliberate second
    implementation) would set up every later test's refusals.  Production
    code never calls it: a deployment does not *un*-implement its fee
    schedule, and a caller wanting a different one reclaims nothing — it
    diverges, which is the error.
    """
    global _installed
    _installed = None
