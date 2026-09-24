"""The plugin seam: composition via the module loader.

This is feature 301's registration contract from the other side — the
factory scans the workspace members, imports this package, the ``@register``
builder at the foot of ``book/__init__.py`` fires, and the composed
application carries a ``book`` component.  No registry, router, entry-points
table or factory was edited to make that true, and this suite exists to keep
it true.

Two properties of the loader shape these tests, and both are the same two
the artifacts, bootstrap, discovery and scoring suites state for their own
members:

* **the loader imports each member under a synthetic module name**
  (``_nullius_scanned_book``), so a package this suite also imported
  canonically as ``book`` exists in the process twice, with two distinct
  function objects.  ``isinstance`` and identity cannot hold across the two
  copies, so the composed component is pinned by name and — decisively —
  behaviour: the combiner the factory hands out answers the same composite
  the canonically-imported one does, field for field.
* **it re-executes a package's ``__init__`` on every ``create_app()`` but
  does not re-execute an already-cached submodule.**  So a ``@register``
  that lived in a submodule would fire on the first composition of a process
  and silently drop out of every later one.
  :func:`test_the_component_survives_a_second_composition` is what catches
  that, and it must assert on the *second* application or it passes
  vacuously.  This is the reason the builder lives in ``__init__.py`` and not
  beside the combiner it builds.

The builder must also never raise and needs no configuration — the combiner,
unlike every store-bound component in this workspace, has no deployment state
to degrade to: its whole configuration is the arithmetic.
:func:`test_the_builder_needs_no_environment` pins that, because a component
that could fail to compose would take composition down for every unrelated
feature, and a book component that silently absented itself would leave the
ranking it feeds computed over nothing.
"""

from __future__ import annotations

from pathlib import Path

import book as member
import pytest
from book import combine
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_THREE, SIGNAL_TWO, SOL, StandInSignal

from app.module_loader import Registration, create_app, scan_components

#: The three promoted signals this suite combines through the composed seam —
#: the conftest's fixture vocabulary is for the combiner's own suite; this
#: suite's question is only whether composition happened, so the same dyadic
#: IRs (1.0, 2.0, 1.0) carry it, with the composite checkable with ==.


def _signals() -> list[StandInSignal]:
    return [
        StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.2, ETH: 0.1, SOL: 0.3}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.1, ETH: 0.3, SOL: 0.2}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.3, ETH: 0.2, SOL: 0.1}),
    ]


def _fields(book: object) -> tuple[object, ...]:
    """A composite book's fields, read duck-typed across the loader's copies.

    The composed combiner answers a ``CompositeBook`` from the loader's own
    copy of the member, so ``==`` against a canonical one is identity
    comparison across two classes and cannot hold; the fields are the
    behaviour, and this is how the cross-copy discipline spells it.
    """
    return (book.scores, book.weights, book.information_ratios)  # type: ignore[attr-defined]


# -- Composition ------------------------------------------------------------------


def test_the_member_registers_under_the_book_component_name() -> None:
    # The component name is the *plugin* name the spec's features carry
    # (``plugin="book"``), so the component key, this member's seat and the
    # spec cannot drift apart.
    assert member.COMPONENT_NAME == "book"


def test_the_scanned_application_carries_the_combiner() -> None:
    app = create_app()
    assert "book" in app
    assert "book" in app.order
    component = app.get("book")
    assert callable(component)


def test_the_composed_combiner_is_the_members_law() -> None:
    # Name and behaviour, not identity: the loader's synthetic-name copy is a
    # different function object from the canonically-imported one, and the
    # composed one must answer exactly what the member's does.
    app = create_app()
    composed = app.get("book")
    direct = combine(_signals())
    answered = composed(_signals())
    assert _fields(answered) == _fields(direct)
    assert answered.scores[BTC] == direct.scores[BTC]
    # And the composed seam refuses what the member's refuses — the law
    # crosses composition whole, not just its happy path.  The refusal is
    # pinned by class *name*, not ``except member.BookConstructionError``:
    # the composed copy raises the loader's own class object, and an
    # ``except`` over the canonical one would not catch it — the same
    # synthetic-name trap the cross-copy field comparison above avoids.
    with pytest.raises(Exception) as caught:  # the copy's own base; named below
        composed([])
    assert type(caught.value).__name__ == "BookConstructionError"
    assert type(caught.value).__module__.endswith("book.errors")


def test_the_component_survives_a_second_composition() -> None:
    # The loader re-executes ``__init__`` (where the @register lives) on
    # every create_app() but caches submodules; a registration that lived in
    # _combine.py would fire on the first composition and silently drop out
    # of this one.  The assertion is on the SECOND application — against the
    # first, it passes vacuously.
    first = create_app()
    second = create_app()
    assert first.get("book") is not None
    assert second.get("book") is not None
    assert callable(second.get("book"))


def test_the_builder_needs_no_environment(monkeypatch) -> None:
    # Unlike every store-bound component in this workspace, the combiner has
    # no deployment state to degrade to: no DATABASE_URL to be absent, no
    # ARTIFACT_ROOT to be unset, nothing to read.  A builder that grew an
    # environment dependency would make composition — of every feature in the
    # workspace, since the factory builds all components on every create_app()
    # — conditional on a book deployment variable nothing else knows about.
    for gone in ("DATABASE_URL", "ARTIFACT_ROOT", "NULL_SIDECAR_PATH"):
        monkeypatch.delenv(gone, raising=False)
    app = create_app()
    component = app.get("book")
    assert callable(component)
    assert _fields(component(_signals())) == _fields(combine(_signals()))


def test_a_fresh_registry_scans_the_member_in() -> None:
    # The factory's own discovery protocol, exercised directly: scanning this
    # member's src root fires the registration into a fresh registry, so the
    # member joins (and leaves) an application by convention — no central
    # table anywhere says it exists.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    # The one registration — the combiner (301) — fires from the one
    # ``__init__.py``.
    assert [component.name for component in registry.components()] == ["book"]


# -- The leverage cap's composition story (feature 308) ---------------------------
#
# Feature 308 arrives as free functions beside the combiner, not as a second
# component — the shape feature 276's ceiling takes beside feature 270's freeze
# in the dreaming member.  Its whole input is figures the caller already holds
# (the book's Sharpe, its volatility, the target), so there is nothing for the
# factory to compose and nothing for a deployment to configure.  The tests
# below pin that absence, because "no new component" is a claim a later edit
# could quietly falsify — and a second registration would show up here as a
# second name in ``app.order``, silently rebuilding composition for every
# feature in the workspace.


def test_the_leverage_cap_registers_no_second_component() -> None:
    # The single-registration assertion above is the strong form; this is the
    # same fact read through the composed application, so a component added by
    # any route (not just this module's own ``__init__``) is caught.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    names = [component.name for component in registry.components()]
    assert names.count("book") == 1
    assert len(names) == 1


def test_the_cap_is_reachable_without_the_factory() -> None:
    # A free function, reached the way the ladder's verdicts are: imported
    # from the member, not asked of the composed application.  There is no
    # ``leverage`` component to ``app.get``, and a deployment cannot configure
    # the quarter — which is the design decision, not an omission.
    assert callable(member.leverage_cap)
    assert callable(member.rejects_overleveraged_target)
    assert callable(member.kelly_fraction)
    assert member.KELLY_FRACTION == 0.25
    app = create_app()
    assert "leverage" not in app
    assert "book-leverage" not in app


def test_the_cap_costs_the_scan_nothing() -> None:
    # The layering promise: the factory imports this package to fire its
    # ``@register``, so anything at module scope is paid on every
    # ``create_app()``.  The cap is answered from the same import that was
    # already being paid for — no new top-level import, no environment read,
    # no third party — so importing the member for the cap alone is the same
    # bill the combiner alone already charged.
    assert member.leverage_cap(1.0, volatility=0.2) == 1.25


def test_the_cap_never_respells_the_quarter_as_a_parameter() -> None:
    # ``build_book_combiner`` takes no arguments because the combiner's whole
    # configuration is its arithmetic; the cap's whole configuration is
    # Appendix B's figures, and a builder that had grown a ``kelly_fraction``
    # keyword would be a deployment knob on a document constant.  This is the
    # one place the two features' composition stories meet, so it is pinned
    # here rather than in either feature's own suite.
    import inspect

    parameters = inspect.signature(member.build_book_combiner).parameters
    assert not parameters


# -- The volatility target's composition story (feature 303) ---------------------
#
# Feature 303 arrives as a free function beside the combiner too, in the same
# shape the cap did: its whole input is a value and two figures the caller
# already holds (the combined book, its volatility, the configured target), so
# there is nothing for the factory to compose.  The one thing that must never
# appear here is a *configured* risk level: the factory's registration protocol
# takes no arguments, so a target that crossed composition would be a risk
# level no deployment could set — and a module-chosen fallback would be one no
# document states.  The target reaches the call, not the composition.


def test_the_volatility_target_registers_no_second_component() -> None:
    # The single-registration assertion above is the strong form; this is the
    # same fact read through a fresh scan, so a component added by any route
    # (not just this module's own ``__init__``) is caught — a second name here
    # would silently rebuild composition for every feature in the workspace.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    names = [component.name for component in registry.components()]
    assert names.count("book") == 1
    assert len(names) == 1


def test_the_volatility_target_is_reachable_without_the_factory() -> None:
    # A free function, reached the way the cap's and guard's verbs are:
    # imported from the member, not asked of the composed application.  There
    # is no ``volatility`` component to ``app.get`` — and there could not be
    # one that carried the configured target, because the factory's builders
    # take no arguments.
    assert callable(member.apply_volatility_target)
    assert callable(member.TargetWeights)
    assert member.FLAT_BOOK_CODE == "flat_book"
    app = create_app()
    assert "volatility" not in app
    assert "book-volatility" not in app


def test_the_volatility_target_costs_the_scan_nothing() -> None:
    # The layering promise: the factory imports this package to fire its
    # ``@register``, so anything at module scope is paid on every
    # ``create_app()``.  The act is answered from the same import that was
    # already being paid for — no new top-level import beyond the stdlib's
    # ``collections``, ``dataclasses``, ``types`` and ``typing``, no
    # environment read, no third party — and it reads a value the caller holds
    # rather than measuring one.  The configured volatility is handed to the
    # *call*, so a composed application cannot carry one and this test cannot
    # configure one: the composition is exercised, not the deployment.
    target = member.apply_volatility_target(
        combine(_signals()), volatility=0.5, target_volatility=0.2
    )
    assert target.scale == 0.4
    assert member.TargetWeights is not None


def test_the_volatility_target_never_crosses_composition() -> None:
    # The builder takes no arguments — the property that makes a *configured*
    # risk level unreachable from composition.  A builder that had grown a
    # ``target_volatility`` keyword would be a deployment knob on the one
    # component whose whole configuration is supposed to be the arithmetic, and
    # the factory would apply one risk level to every book it composed.  Pinned
    # here rather than in the act's own suite because it is the composition
    # story's claim: the target belongs to the call.
    import inspect

    parameters = inspect.signature(member.build_book_combiner).parameters
    assert not parameters
    # And the act's own signature is where the figure lives — required, with
    # no default, so no composition and no module has one to fall back on.
    parameters = inspect.signature(member.apply_volatility_target).parameters
    assert parameters["target_volatility"].default is inspect.Parameter.empty


# -- The limits' composition story (feature 304) ----------------------------------
#
# Feature 304 arrives in exactly the shape the volatility target did: free
# functions beside the combiner, judging a value the caller already holds, so
# there is nothing for the factory to compose and nothing for a deployment to
# configure.  What it must never grow is a parameter carrying a *limit*,
# because §C8 states the step and states no figure for either bound — the
# figures are the deployment's and reach the call, never a component.  These
# four tests are the composition story's own claim, in the form the cap's,
# the target's, the guard's and the companion's own stories take.


def test_the_limits_register_no_second_component() -> None:
    # The single-registration assertion above is the strong form; this is the
    # same fact read through a fresh scan, so a component added by any route
    # (not just this module's own ``__init__``) is caught — a second name here
    # would silently rebuild composition for every feature in the workspace.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    names = [component.name for component in registry.components()]
    assert names.count("book") == 1
    assert len(names) == 1


def test_the_limits_are_reachable_without_the_factory() -> None:
    # Free functions, reached the way the cap's, the target's and the guard's
    # verbs are: imported from the member, not asked of the composed
    # application.  There is no ``limits`` component to ``app.get`` — and
    # there could not be one that carried the configured bounds, because the
    # factory's builders take no arguments.
    assert callable(member.rejects_breaching_target_weights)
    assert callable(member.is_breaching_limits)
    assert callable(member.concentration)
    assert member.PER_POSITION_LIMIT_CODE == "position_above_limit"
    assert member.CONCENTRATION_LIMIT_CODE == "concentration_above_limit"
    app = create_app()
    assert "limits" not in app
    assert "book-limits" not in app


def test_the_limits_cost_the_scan_nothing() -> None:
    # The layering promise: the factory imports this package to fire its
    # ``@register``, so anything at module scope is paid on every
    # ``create_app()``.  The act is answered from the same import that was
    # already being paid for — no new top-level import beyond the stdlib's
    # ``collections``, ``dataclasses``, ``math`` and ``typing``, no environment
    # read, no third party — and it reads a value the caller holds rather than
    # measuring one.  Both limits are handed to the *call*, so a composed
    # application cannot carry one and this test cannot configure one: the
    # composition is exercised, not the deployment.
    target = member.apply_volatility_target(
        combine(_signals()), volatility=0.5, target_volatility=0.2
    )
    assert (
        member.rejects_breaching_target_weights(
            target, per_position_limit=1.0, concentration_limit=1.0
        )
        is None
    )
    assert member.is_breaching_limits(
        target, per_position_limit=0.01, concentration_limit=1.0
    )


def test_the_limits_never_cross_composition() -> None:
    # The builder takes no arguments — the property that makes a *configured*
    # bound unreachable from composition.  A builder that had grown a
    # ``per_position_limit`` or ``concentration_limit`` keyword would be a
    # deployment knob on the one component whose whole configuration is
    # supposed to be the arithmetic, and the factory would apply one risk
    # appetite to every book it composed.  Pinned here rather than in the
    # act's own suite because it is the composition story's claim: both
    # limits belong to the call.
    import inspect

    parameters = inspect.signature(member.build_book_combiner).parameters
    assert not parameters
    # And both live on the act's own signatures — required, with no default,
    # so no composition and no module has one to fall back on.
    for call in (
        member.is_breaching_limits,
        member.rejects_breaching_target_weights,
    ):
        parameters = inspect.signature(call).parameters
        assert set(parameters) == {
            "target_weights",
            "per_position_limit",
            "concentration_limit",
        }
        for name in ("per_position_limit", "concentration_limit"):
            assert parameters[name].default is inspect.Parameter.empty


# -- The authorship guard's composition story (feature 306) -----------------------
#
# Feature 306 arrives as free functions beside the combiner too, in the same
# shape the cap did: its whole input is a change record the caller already
# holds, so there is nothing for the factory to compose and nothing for a
# deployment to configure — and the one thing it must never grow is a
# parameter that widens the admitted author set, because a guard whose
# boundary its caller could move is not one.


def test_the_authorship_guard_registers_no_second_component() -> None:
    # The single-registration assertion above is the strong form; this is
    # the same fact read through a fresh scan, so a component added by any
    # route (not just this module's own ``__init__``) is caught — a second
    # name here would silently rebuild composition for every feature in
    # the workspace.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    names = [component.name for component in registry.components()]
    assert names.count("book") == 1
    assert len(names) == 1


def test_the_authorship_guard_is_reachable_without_the_factory() -> None:
    # A free function, reached the way the cap's verdicts are: imported
    # from the member, not asked of the composed application.  There is no
    # ``authorship`` component to ``app.get``, and a deployment cannot
    # configure the admitted author kinds — which is the design decision,
    # not an omission: the boundary is §C8's, not a deployment's.
    assert callable(member.rejects_agent_authored_modification)
    assert callable(member.is_agent_authored)
    assert member.HUMAN_AUTHOR_KIND == "human"
    app = create_app()
    assert "authorship" not in app
    assert "book-authorship" not in app


def test_the_guard_costs_the_scan_nothing() -> None:
    # The layering promise: the factory imports this package to fire its
    # ``@register``, so anything at module scope is paid on every
    # ``create_app()``.  The guard is answered from the same import that
    # was already being paid for — no new top-level import beyond the
    # stdlib's ``dataclasses`` and ``typing``, no environment read, no
    # third party — and it judges a record it is handed rather than state
    # it would have to go looking for.
    change = member.BookConstructionChange(
        "the information-ratio weighting",
        "Ada Lovelace",
        "human",
        "0123456789abcdef0123456789abcdef01234567",
    )
    assert member.rejects_agent_authored_modification(change) is None


# -- The changelog companion's composition story (feature 307) ------------------
#
# Feature 307 arrives as free functions beside the combiner too, in the same
# shape the cap and the guard did: its whole input is two records the caller
# already holds (the change and the entry that should accompany it), so there
# is nothing for the factory to compose and nothing for a deployment to
# configure — and the one thing it must never grow is a parameter that judges
# the entry's content, because the companion enforces presence, not prose.


def test_the_changelog_companion_registers_no_second_component() -> None:
    # The single-registration assertion above is the strong form; this is
    # the same fact read through a fresh scan, so a component added by any
    # route (not just this module's own ``__init__``) is caught — a second
    # name here would silently rebuild composition for every feature in
    # the workspace.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    names = [component.name for component in registry.components()]
    assert names.count("book") == 1
    assert len(names) == 1


def test_the_changelog_companion_is_reachable_without_the_factory() -> None:
    # A free function, reached the way the cap's and guard's verdicts are:
    # imported from the member, not asked of the composed application.
    # There is no ``changelog`` component to ``app.get``, and a deployment
    # cannot configure the companion's boundary — which is the design
    # decision, not an omission: the boundary is §C8's presence line, not a
    # deployment's.
    assert callable(member.requires_changelog_entry)
    assert callable(member.is_missing_changelog_entry)
    assert member.MISSING_CHANGELOG_ENTRY_CODE == "missing_changelog_entry"
    app = create_app()
    assert "changelog" not in app
    assert "book-changelog" not in app


def test_the_companion_costs_the_scan_nothing() -> None:
    # The layering promise: the factory imports this package to fire its
    # ``@register``, so anything at module scope is paid on every
    # ``create_app()``.  The companion is answered from the same import that
    # was already being paid for — no new top-level import beyond the
    # stdlib's ``dataclasses`` and ``typing``, no environment read, no third
    # party — and it judges two records it is handed rather than state it
    # would have to go looking for.
    change = member.BookConstructionChange(
        "the information-ratio weighting",
        "Ada Lovelace",
        "human",
        "0123456789abcdef0123456789abcdef01234567",
    )
    entry = member.ChangelogEntry(
        "the information-ratio weighting",
        "Changed the information-ratio weighting from equal to IR-proportional.",
    )
    assert member.requires_changelog_entry(change, entry) is None
    assert member.is_missing_changelog_entry(change, None) is True


def test_the_changelog_companion_takes_no_content_parameter() -> None:
    # ``build_book_combiner`` takes no arguments because the combiner's
    # whole configuration is its arithmetic; the companion's whole
    # configuration is two records, and a verb that had grown a content
    # keyword would be a deployment knob on a document rule — the companion
    # enforces presence, never prose.  This is pinned through the function
    # objects rather than the source text, so a renamed keyword still fails.
    import inspect

    for call in (member.is_missing_changelog_entry, member.requires_changelog_entry):
        assert set(inspect.signature(call).parameters) == {"change", "entry"}


def test_the_members_public_surface_carries_the_seven_features() -> None:
    # The exported surface is the seven features' own names and nothing
    # else: 301's combiner, its value types and its one base error; 303's
    # act, its record, its one code constant and its two sibling classes;
    # 304's three verbs, its two code constants and its two sibling classes;
    # 305's record, its three constants, its two verbs, its predicate and its
    # two sibling classes; 306's record, its five constants, its predicate,
    # its verdict and its two sibling classes; 307's record, its one code
    # constant, its predicate, its verdict and its two sibling classes; 308's
    # three verbs, its two constants and its two sibling classes.  Pinned
    # because the seat deliberately re-exports none of it — a caller who wants
    # these reaches the member's namespace, so the namespace *is* the contract
    # and a name that drifted off it would leave a caller with no way in.
    assert set(member.__all__) == {
        "AGENT_AUTHOR_KINDS",
        "AGENT_MODIFICATION_CODE",
        "ANNEXED_RECORD_CODE",
        "AUTHOR_KINDS",
        "COMPONENT_NAME",
        "CONCENTRATION_LIMIT_CODE",
        "FLAT_BOOK_CODE",
        "HUMAN_AUTHOR_KIND",
        "KELLY_FRACTION",
        "MISSING_CHANGELOG_ENTRY_CODE",
        "NO_BOOK_CODE",
        "OVERLEVERAGE_CODE",
        "PER_POSITION_LIMIT_CODE",
        "PUBLISHED_KIND",
        "REVISION_HEX_LENGTH",
        "AgentAuthoredModificationError",
        "BookChangeRequestError",
        "BookConstructionChange",
        "BookConstructionError",
        "ChangelogEntry",
        "ChangelogEntryRequestError",
        "CompositeBook",
        "FinalTargetWeights",
        "FinalWeightsRequestError",
        "LeverageRequestError",
        "LeverageTargetError",
        "LimitBreachError",
        "LimitRequestError",
        "MissingChangelogEntryError",
        "OrderLayerOutputError",
        "PromotedSignal",
        "TargetWeights",
        "VolatilityTargetError",
        "VolatilityTargetRequestError",
        "apply_volatility_target",
        "assert_only_output",
        "build_book_combiner",
        "combine",
        "concentration",
        "final_target_weights",
        "is_agent_authored",
        "is_breaching_limits",
        "is_missing_changelog_entry",
        "is_only_output",
        "kelly_fraction",
        "leverage_cap",
        "rejects_agent_authored_modification",
        "rejects_breaching_target_weights",
        "rejects_overleveraged_target",
        "requires_changelog_entry",
    }
    for name in member.__all__:
        assert hasattr(member, name), name


# -- The final weights' composition story (feature 305) ---------------------------
#
# Feature 305 arrives in exactly the shape the limits and the target did: free
# functions beside the combiner, publishing a value the caller already holds, so
# there is nothing for the factory to compose and nothing for a deployment to
# configure.  What it must never grow is a figure of its own — the chain's
# earlier steps carry every number (feature 303's configured volatility, feature
# 304's two limits) and each reaches its own call — so these tests are the
# composition story's own claim, in the form the other five features' stories
# take.


def test_the_final_weights_register_no_second_component() -> None:
    # The single-registration assertion above is the strong form; this is the
    # same fact read through a fresh scan, so a component added by any route
    # (not just this module's own ``__init__``) is caught — a second name here
    # would silently rebuild composition for every feature in the workspace.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    names = [component.name for component in registry.components()]
    assert names.count("book") == 1
    assert len(names) == 1


def test_the_final_weights_are_reachable_without_the_factory() -> None:
    # Free functions, reached the way the limits', the target's and the cap's
    # verbs are: imported from the member, not asked of the composed
    # application.  There is no ``publish`` component to ``app.get``, and a
    # deployment cannot configure the output — which is the design decision,
    # not an omission: the sentence names a shape, and a shape is not a figure.
    assert callable(member.final_target_weights)
    assert callable(member.is_only_output)
    assert callable(member.assert_only_output)
    assert member.PUBLISHED_KIND == "final_target_weights"
    app = create_app()
    assert "publish" not in app
    assert "book-publish" not in app


def test_the_final_weights_cost_the_scan_nothing() -> None:
    # The layering promise: the factory imports this package to fire its
    # ``@register``, so anything at module scope is paid on every
    # ``create_app()``.  The publication is answered from the same import that
    # was already being paid for — no new top-level import beyond the stdlib's
    # ``collections``, ``dataclasses``, ``math``, ``types`` and ``typing``, no
    # environment read, no third party — and it re-runs no arithmetic at all,
    # so it is cheaper than every step upstream of it.
    target = member.apply_volatility_target(
        combine(_signals()), volatility=0.5, target_volatility=0.2
    )
    final = member.final_target_weights(target)
    assert final.weight(BTC) == target.weight(BTC)
    assert member.is_only_output(final, target) is True


def test_the_final_weights_never_cross_composition() -> None:
    # The builder takes no arguments — the property that makes every figure in
    # this category unreachable from composition — and the publication's own
    # signature is where *nothing* lives: it carries the value to publish and
    # no figure beside it, because the chain's earlier steps already applied
    # theirs.  A keyword here would be a risk level or a bound wearing the
    # chain's last step's name, and the factory would apply it to every book it
    # composed.
    import inspect

    parameters = inspect.signature(member.build_book_combiner).parameters
    assert not parameters
    for call in (member.final_target_weights, member.is_only_output, member.assert_only_output):
        for parameter in inspect.signature(call).parameters.values():
            assert parameter.default is inspect.Parameter.empty
