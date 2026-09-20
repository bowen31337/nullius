"""Feature 69 — one shared cost library, and the second implementation refused.

app_spec.xml, "Cost Model & Fill Simulation", feature 69: *System rejects
a second implementation of the fee schedule, so research evaluation and
live execution import one shared cost library.*  The sentence is a
mechanism and a consequence, and both are testable:

* **rejects a second implementation** — the process's fee schedule is
  claimed once; a *different* implementation offered afterwards is
  refused by name, whichever of the two claimed first, and the refusal
  leaves the incumbent installed.
* **so research evaluation and live execution import one shared cost
  library** — the same implementation claimed twice (built
  independently, the way two consumers would each build it out of the
  symbols they imported) is idempotent: one implementation, two claims,
  no error.  That is the feature's outcome, not a tolerated edge.

And the two properties that make "same implementation" mean the right
thing: identity is the *owning module* — one source imported both
directly and through the factory's mangled scan name is one
implementation, never two — and the claim guards *code*, not data, so
the registry never confuses a second schedule value with a second
implementation.

:mod:`cost_model.fee_library` owns the claim; the service tests at the
end pin that the composed component reaches it — research evaluation
and live execution hold the composed application, and the service is
the door both walk through.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cost_model
import pytest
from cost_model import (
    SHARED_FEE_IMPLEMENTATION,
    CostModelError,
    CostModelService,
    DuplicateFeeImplementationError,
    FeeImplementation,
    FeeSchedule,
    PostCostReturn,
    apply_fee,
    install_fee_implementation,
    installed_fee_implementation,
    resolve_fee_schedule,
)
from cost_model.fee_library import _reset_fee_implementation

from app.module_loader import Application, Registration, create_app

#: The member's src/ — the scan root the factory is pointed at for the
#: composition tests, exactly as test_component.py derives it.
MEMBER_SRC = Path(cost_model.__file__).resolve().parent.parent

#: The module that owns the shared implementation — asserted by name
#: rather than derived, so a test failure says "the claim moved" rather
#: than silently following wherever it went.
SHARED_MODULE = "cost_model.fees"

#: A module name no code in this workspace carries: the second
#: implementation's origin, spelled the way a live-engine twin would
#: spell it.
FOREIGN_MODULE = "live_execution.fees"

#: The factory's prefix for scanned packages
#: (``app.module_loader._import_package`` mangles ``<pkg>`` into
#: ``_nullius_scanned_<pkg>``); the claim strips it, so the scanned twin
#: of ``cost_model.fees`` claims the same identity.
SCANNED_MODULE = "_nullius_scanned_cost_model.fees"


def _a_second_implementation(module: str = FOREIGN_MODULE) -> FeeImplementation:
    """Build a fee implementation that is genuinely second: its own module, type, charge and resolver.

    The twin is faithful on purpose — same resolver underneath, same
    subtraction in the charge — because feature 69 does not reject the
    second implementation for being *wrong*; it rejects it for being
    *second*.  A copy that prices identically today is still the module
    that can drift tomorrow, and drift-ability is the property the claim
    guards.
    """
    def _apply(pre_cost_return: float, fee_bps: float, side: str) -> float:
        # The twin's own subtraction — the same arithmetic, spelled a
        # second time, which is exactly what makes it a second
        # implementation rather than a shared one.
        return pre_cost_return - fee_bps / 10_000.0

    class _TwinSchedule:
        """The twin's own schedule type — a second type from a second module."""

        def __init__(self, schedule: FeeSchedule) -> None:
            self._schedule = schedule

        def rate(self, side: str) -> float:
            return self._schedule.rate(side)

    original = resolve_fee_schedule()

    def _resolve_twin(model: object = None) -> _TwinSchedule:
        source = original if model is None else resolve_fee_schedule(model)  # type: ignore[arg-type]
        return _TwinSchedule(source)

    return FeeImplementation(
        module=module,
        schedule_type=_TwinSchedule,
        apply=_apply,
        resolve=_resolve_twin,
    )


@pytest.fixture(autouse=True)
def _a_fresh_claim_per_test() -> Iterator[None]:
    """Give every test here an unclaimed process, and leave one behind.

    The claim is process-global by design — that is what makes it a
    claim — and this suite is one process, so without the reset one
    test's second implementation would set up every later test's
    refusals.  The reset is the module's own test seam, not a registry
    feature: production code cannot un-implement a fee schedule.
    """
    _reset_fee_implementation()
    yield
    _reset_fee_implementation()


class TestTheSharedImplementation:
    """The library's own implementation: what it owns, and that it claims cleanly."""

    def test_the_shared_value_is_this_librarys_own_symbols(self) -> None:
        assert SHARED_FEE_IMPLEMENTATION.module == SHARED_MODULE
        assert SHARED_FEE_IMPLEMENTATION.schedule_type is FeeSchedule
        assert SHARED_FEE_IMPLEMENTATION.apply is apply_fee
        assert SHARED_FEE_IMPLEMENTATION.resolve is resolve_fee_schedule

    def test_claiming_with_no_candidate_installs_the_shared_one(self) -> None:
        assert installed_fee_implementation() is None
        claimed = install_fee_implementation()
        assert claimed == SHARED_FEE_IMPLEMENTATION
        assert installed_fee_implementation() is claimed

    def test_the_implementation_prices_a_fill(self) -> None:
        # The claim is not a label: the value it returns carries the
        # charge and the resolver a consumer prices through, and they are
        # the ones fees.py owns.
        impl = install_fee_implementation()
        post = impl.apply(0.05, 10.0, "taker")
        assert isinstance(post, PostCostReturn)
        assert post.post_cost_return == pytest.approx(0.05 - 10.0 / 10_000.0)
        assert isinstance(impl.resolve(), FeeSchedule)

    def test_the_summary_names_the_owner_and_its_three_parts(self) -> None:
        summary = SHARED_FEE_IMPLEMENTATION.summary()
        assert summary["module"] == SHARED_MODULE
        assert summary["schedule_type"] == "FeeSchedule"
        assert summary["apply"] == "apply_fee"
        assert summary["resolve"] == "resolve_fee_schedule"

    def test_the_identity_is_the_module(self) -> None:
        assert SHARED_FEE_IMPLEMENTATION.identity == SHARED_MODULE


class TestOneSharedLibrary:
    """The feature's 'so' clause: two consumers, one implementation, no error."""

    def test_two_consumers_claiming_the_same_symbols_hold_one_implementation(self) -> None:
        # Research evaluation and live execution each import the library
        # and each build the value out of the symbols they hold — two
        # independently constructed values, one owning module.
        research_evaluation = FeeImplementation(
            module=SHARED_MODULE,
            schedule_type=FeeSchedule,
            apply=apply_fee,
            resolve=resolve_fee_schedule,
        )
        live_execution = FeeImplementation(
            module=SHARED_MODULE,
            schedule_type=FeeSchedule,
            apply=apply_fee,
            resolve=resolve_fee_schedule,
        )
        first = install_fee_implementation(research_evaluation)
        second = install_fee_implementation(live_execution)
        assert first is second
        assert first == SHARED_FEE_IMPLEMENTATION

    def test_re_claiming_returns_the_installed_value(self) -> None:
        installed = install_fee_implementation()
        again = FeeImplementation(
            module=SHARED_MODULE,
            schedule_type=FeeSchedule,
            apply=apply_fee,
            resolve=resolve_fee_schedule,
        )
        assert install_fee_implementation(again) is installed

    def test_a_second_schedule_value_is_not_a_second_implementation(self) -> None:
        # The claim guards code, not data: a process pricing two venues
        # holds two schedule values out of the one implementation, and
        # the second venue's pricing is not a divergence.
        first = install_fee_implementation()
        other_venue = FeeSchedule(venue="kraken_spot", taker_bps=16.0, maker_bps=16.0)
        assert other_venue.venue != first.resolve().venue
        assert install_fee_implementation() is first  # unaffected

    def test_the_scanned_twin_is_the_same_implementation(self) -> None:
        # The factory imports scanned packages under a mangled name, so
        # one process can hold two module objects for this one source.
        # The claim strips the prefix: the scanned twin claims the same
        # identity, and idempotence holds across import paths.
        direct = install_fee_implementation()
        scanned_twin = FeeImplementation(
            module=SCANNED_MODULE,
            schedule_type=FeeSchedule,
            apply=apply_fee,
            resolve=resolve_fee_schedule,
        )
        assert scanned_twin == direct
        assert install_fee_implementation(scanned_twin) is direct

    def test_equal_implementations_hash_equal(self) -> None:
        twin = FeeImplementation(
            module=SCANNED_MODULE,
            schedule_type=FeeSchedule,
            apply=apply_fee,
            resolve=resolve_fee_schedule,
        )
        assert len({SHARED_FEE_IMPLEMENTATION, twin}) == 1

    def test_a_foreign_implementation_is_not_equal(self) -> None:
        assert _a_second_implementation() != SHARED_FEE_IMPLEMENTATION
        assert _a_second_implementation("evaluator._fees") != _a_second_implementation()


class TestTheSecondImplementationIsRejected:
    """The feature's mechanism: the second, different implementation refused by name."""

    def test_a_second_implementation_after_the_shared_one_is_refused(self) -> None:
        install_fee_implementation()
        with pytest.raises(DuplicateFeeImplementationError) as raised:
            install_fee_implementation(_a_second_implementation())
        message = str(raised.value)
        assert SHARED_MODULE in message
        assert FOREIGN_MODULE in message
        assert SHARED_MODULE.index(SHARED_MODULE) < message.index(FOREIGN_MODULE)

    def test_the_shared_one_after_a_foreign_claim_is_refused(self) -> None:
        # First claim wins, whoever made it: a process claimed by another
        # module's implementation refuses the shared library's own claim
        # too — surfacing the divergent wiring, not falling back to it.
        install_fee_implementation(_a_second_implementation())
        with pytest.raises(DuplicateFeeImplementationError) as raised:
            install_fee_implementation()
        assert FOREIGN_MODULE in str(raised.value)
        assert SHARED_MODULE in str(raised.value)

    def test_the_refusal_names_the_shared_library_rule(self) -> None:
        install_fee_implementation()
        with pytest.raises(DuplicateFeeImplementationError, match="one shared cost library"):
            install_fee_implementation(_a_second_implementation())

    def test_the_refusal_leaves_the_incumbent_installed(self) -> None:
        incumbent = install_fee_implementation()
        with pytest.raises(DuplicateFeeImplementationError):
            install_fee_implementation(_a_second_implementation())
        assert installed_fee_implementation() is incumbent

    def test_a_third_module_after_a_second_is_also_refused(self) -> None:
        install_fee_implementation(_a_second_implementation("evaluator._fees"))
        with pytest.raises(DuplicateFeeImplementationError):
            install_fee_implementation(_a_second_implementation(FOREIGN_MODULE))
        assert installed_fee_implementation() == _a_second_implementation(
            "evaluator._fees"
        )

    def test_the_error_is_both_a_value_error_and_a_cost_model_error(self) -> None:
        # The refusal lands on whoever supplied the second implementation
        # (ValueError) and stays catchable as this package's one
        # vocabulary (CostModelError) — asserted as subclassing rather
        # than by nesting two pytest.raises, which would swallow the
        # exception for the outer context.
        assert issubclass(DuplicateFeeImplementationError, ValueError)
        assert issubclass(DuplicateFeeImplementationError, CostModelError)
        install_fee_implementation()
        with pytest.raises(ValueError):
            install_fee_implementation(_a_second_implementation())

    def test_comparison_with_a_non_implementation_is_not_equality(self) -> None:
        assert SHARED_FEE_IMPLEMENTATION != "cost_model.fees"
        assert SHARED_FEE_IMPLEMENTATION != None


class TestUnusableImplementations:
    """A value that implements nothing cannot claim anything."""

    def test_a_blank_module_is_refused(self) -> None:
        with pytest.raises(DuplicateFeeImplementationError, match="owns it"):
            FeeImplementation(
                module="   ",
                schedule_type=FeeSchedule,
                apply=apply_fee,
                resolve=resolve_fee_schedule,
            )

    def test_a_non_string_module_is_refused(self) -> None:
        with pytest.raises(DuplicateFeeImplementationError, match="implements nothing"):
            FeeImplementation(
                module=61,  # type: ignore[arg-type]
                schedule_type=FeeSchedule,
                apply=apply_fee,
                resolve=resolve_fee_schedule,
            )

    def test_a_non_type_schedule_is_refused(self) -> None:
        with pytest.raises(DuplicateFeeImplementationError, match="schedule type"):
            FeeImplementation(
                module=SHARED_MODULE,
                schedule_type="FeeSchedule",  # type: ignore[arg-type]
                apply=apply_fee,
                resolve=resolve_fee_schedule,
            )

    def test_a_non_callable_charge_is_refused(self) -> None:
        with pytest.raises(DuplicateFeeImplementationError, match="no callable apply"):
            FeeImplementation(
                module=SHARED_MODULE,
                schedule_type=FeeSchedule,
                apply=10.0,  # type: ignore[arg-type]
                resolve=resolve_fee_schedule,
            )

    def test_a_non_callable_resolver_is_refused(self) -> None:
        with pytest.raises(DuplicateFeeImplementationError, match="no callable resolve"):
            FeeImplementation(
                module=SHARED_MODULE,
                schedule_type=FeeSchedule,
                apply=apply_fee,
                resolve=None,  # type: ignore[arg-type]
            )

    def test_a_broken_value_installs_nothing(self) -> None:
        with pytest.raises(DuplicateFeeImplementationError):
            FeeImplementation(module="", schedule_type=FeeSchedule, apply=apply_fee, resolve=resolve_fee_schedule)
        assert installed_fee_implementation() is None


class TestTheServiceSeam:
    """Research evaluation and live execution hold the composed application — the door both walk through."""

    def test_the_service_claims_the_shared_implementation(self) -> None:
        service = CostModelService()
        claimed = service.fee_implementation()
        assert claimed == SHARED_FEE_IMPLEMENTATION
        assert installed_fee_implementation() is claimed

    def test_the_service_resolves_its_schedule_through_the_claim(self) -> None:
        service = CostModelService()
        schedule = service.fees()
        assert isinstance(schedule, FeeSchedule)
        assert schedule == resolve_fee_schedule(service.document)

    def test_the_service_refuses_to_price_under_a_foreign_claim(self) -> None:
        # A process claimed by a second implementation: the service does
        # not fall back to serving it — the claim is surfaced, which is
        # the divergence §6.2's β₄ penalizes, arrived at as an error
        # instead of a measurement.
        install_fee_implementation(_a_second_implementation())
        service = CostModelService()
        with pytest.raises(DuplicateFeeImplementationError):
            service.fee_implementation()
        with pytest.raises(DuplicateFeeImplementationError):
            service.fees()

    def test_two_services_hold_one_implementation(self) -> None:
        research_evaluation = CostModelService().fee_implementation()
        live_execution = CostModelService().fee_implementation()
        assert research_evaluation is live_execution

    def test_the_composed_component_claims_the_shared_module(
        self, test_database_url: str
    ) -> None:
        # The loader imports scanned packages under its mangled name, so
        # the composed service is the scanned copy's class — assert on
        # the observable contract (the claimed module), not on
        # cross-copy object identity, exactly as test_component.py does.
        app = create_app(str(MEMBER_SRC), registry=Registration())
        assert isinstance(app, Application)
        service = app.get("cost-model")
        assert service.fee_implementation().module == SHARED_MODULE

    def test_the_public_names_are_exported(self) -> None:
        for name in (
            "SHARED_FEE_IMPLEMENTATION",
            "FeeImplementation",
            "DuplicateFeeImplementationError",
            "install_fee_implementation",
            "installed_fee_implementation",
        ):
            assert name in cost_model.__all__
            assert hasattr(cost_model, name)
