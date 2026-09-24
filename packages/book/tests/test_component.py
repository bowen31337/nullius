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


def test_the_members_public_surface_carries_the_three_features() -> None:
    # The exported surface is the three features' own names and nothing
    # else: 301's combiner, its value types and its one base error; 306's
    # record, its five constants, its predicate, its verdict and its two
    # sibling classes; 308's three verbs, its two constants and its two
    # sibling classes.  Pinned because the seat deliberately re-exports
    # none of it — a caller who wants these reaches the member's
    # namespace, so the namespace *is* the contract and a name that
    # drifted off it would leave a caller with no way in.
    assert set(member.__all__) == {
        "AGENT_AUTHOR_KINDS",
        "AGENT_MODIFICATION_CODE",
        "AUTHOR_KINDS",
        "COMPONENT_NAME",
        "HUMAN_AUTHOR_KIND",
        "KELLY_FRACTION",
        "OVERLEVERAGE_CODE",
        "REVISION_HEX_LENGTH",
        "AgentAuthoredModificationError",
        "BookChangeRequestError",
        "BookConstructionChange",
        "BookConstructionError",
        "CompositeBook",
        "LeverageRequestError",
        "LeverageTargetError",
        "PromotedSignal",
        "build_book_combiner",
        "combine",
        "is_agent_authored",
        "kelly_fraction",
        "leverage_cap",
        "rejects_agent_authored_modification",
        "rejects_overleveraged_target",
    }
    for name in member.__all__:
        assert hasattr(member, name), name
