"""The plugin seam: composition via the module loader.

This is feature 256's registration contract from the other side — the
factory scans the workspace members, imports this package, the
``@register`` builder at the foot of ``scoring/__init__.py`` fires, and
the composed application carries a ``scoring`` component.  No registry,
router, entry-points table or factory was edited to make that true, and
this suite exists to keep it true.

Two properties of the loader shape these tests, and both are the same two
the artifacts, bootstrap, discovery and null-oracle suites state for their
own members:

* **the loader imports each member under a synthetic module name**
  (``_nullius_scanned_scoring``), so a package this suite also imported
  canonically as ``scoring`` exists in the process twice, with two
  distinct function objects.  ``isinstance`` and identity cannot hold
  across the two copies, so the composed component is pinned by name and
  — decisively — behaviour: the objective the factory hands out answers
  the same world score the canonically-imported one does, field for
  field.
* **it re-executes a package's ``__init__`` on every ``create_app()`` but
  does not re-execute an already-cached submodule.**  So a ``@register``
  that lived in a submodule would fire on the first composition of a
  process and silently drop out of every later one.
  :func:`test_the_component_survives_a_second_composition` is what
  catches that, and it must assert on the *second* application or it
  passes vacuously.  This is the reason the builder lives in
  ``__init__.py`` and not beside the objective it builds.

The builder must also never raise and needs no configuration — the
objective, unlike every store-bound component in this workspace, has no
deployment state to degrade to: its whole configuration is the
arithmetic.  :func:`test_the_builder_needs_no_environment` pins that,
because a component that could fail to compose would take composition
down for every unrelated feature, and a scoring component that silently
absented itself would leave the ranking it feeds computed over nothing.

Feature 265 grew the member a second registration — the scorer process
under ``scoring-null-pick-rate``, its own builder in the same
``__init__.py`` — and this suite's fresh-registry test now asserts both
names, because the growth pattern is the same convention: no central
table says either component exists.  The scorer's own composition laws
(needing an environment to compose to a process, degrading to ``None``
without one, its seat) are pinned in ``test_scorer_component.py``, not
duplicated here.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import scoring as member

from app.module_loader import Registration, create_app, scan_components

#: The panel every behaviour check through the composed seam reads — the
#: conftest's fixture vocabulary is for the law's own suite; this suite's
#: question is only whether composition happened, so one hand-computed
#: panel (mean 1.5 over population std 0.5, ratio 3.0) carries it.
_PANEL = {dt.date(2026, 1, 5): 1.0, dt.date(2026, 1, 6): 2.0}


def _fields(score: object) -> tuple[object, ...]:
    """A world score's fields, read duck-typed across the loader's copies.

    The composed objective answers a ``WorldScore`` from the loader's own
    copy of the member, so ``==`` against a canonical one is identity
    comparison across two classes and cannot hold; the fields are the
    behaviour, and this is how the cross-copy discipline spells it.
    """
    return (score.world_id, score.node_id, score.ir_oos, score.score, score.epoch_id)  # type: ignore[attr-defined]


# -- Composition -------------------------------------------------------------------


def test_the_member_registers_under_the_scoring_component_name() -> None:
    # The component name is the *plugin* name the spec's features carry
    # (``plugin="scoring"``), so the component key, this member's seat and
    # the spec cannot drift apart.
    assert member.COMPONENT_NAME == "scoring"


def test_the_scanned_application_carries_the_objective() -> None:
    app = create_app()
    assert "scoring" in app
    assert "scoring" in app.order
    component = app.get("scoring")
    assert callable(component)


def test_the_composed_objective_is_the_members_law() -> None:
    # Name and behaviour, not identity: the loader's synthetic-name copy
    # is a different function object from the canonically-imported one,
    # and the composed one must answer exactly what the member's does.
    app = create_app()
    composed = app.get("scoring")
    direct = member.world_objective("financial-campaign-01", "node-a", _PANEL)
    answered = composed("financial-campaign-01", "node-a", _PANEL)
    assert _fields(answered) == _fields(direct)
    # And the composed seam refuses what the member's refuses — the law
    # crosses composition whole, not just its happy path.  The refusal is
    # pinned by class *name*, not ``except member.WorldObjectiveError``:
    # the composed copy raises the loader's own class object, and an
    # ``except`` over the canonical one would not catch it — the same
    # synthetic-name trap the cross-copy field comparison above avoids.
    with pytest.raises(Exception) as caught:  # the copy's own base; named below
        composed("financial-campaign-01", None, _PANEL)
    assert type(caught.value).__name__ == "WorldObjectiveError"
    assert type(caught.value).__module__.endswith("scoring.errors")


def test_the_component_survives_a_second_composition() -> None:
    # The loader re-executes ``__init__`` (where the @register lives) on
    # every create_app() but caches submodules; a registration that lived
    # in _objective.py would fire on the first composition and silently
    # drop out of this one.  The assertion is on the SECOND application —
    # against the first, it passes vacuously.
    first = create_app()
    second = create_app()
    assert first.get("scoring") is not None
    assert second.get("scoring") is not None
    assert callable(second.get("scoring"))


def test_the_builder_needs_no_environment(monkeypatch) -> None:
    # Unlike every store-bound component in this workspace, the objective
    # has no deployment state to degrade to: no DATABASE_URL to be absent,
    # no ARTIFACT_ROOT to be unset, nothing to read.  A builder that grew
    # an environment dependency would make composition — of every feature
    # in the workspace, since the factory builds all components on every
    # create_app() — conditional on a scoring deployment variable nothing
    # else knows about.
    for gone in ("DATABASE_URL", "ARTIFACT_ROOT", "NULL_SIDECAR_PATH"):
        monkeypatch.delenv(gone, raising=False)
    app = create_app()
    component = app.get("scoring")
    assert callable(component)
    assert _fields(component("w", "node-a", _PANEL)) == _fields(
        member.world_objective("w", "node-a", _PANEL)
    )


def test_a_fresh_registry_scans_the_member_in() -> None:
    # The factory's own discovery protocol, exercised directly: scanning
    # this member's src root fires the registration into a fresh registry,
    # so the member joins (and leaves) an application by convention — no
    # central table anywhere says it exists.
    src_root = Path(member.__file__).resolve().parent.parent
    registry = Registration()
    scan_components(src_root, registry=registry)
    # Both of the member's registrations — the objective (256) and the
    # scorer process (265) — fire from the one ``__init__.py``, sorted by
    # name as the registry orders them.
    assert [component.name for component in registry.components()] == [
        "scoring",
        "scoring-null-pick-rate",
    ]
